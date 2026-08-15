"""Leak endpoints."""

import db
import errors
from errors import ApiError
from middleware import get_body, require_roles
from response import success_list, success_object
from routes import make_bp
from services import calc, core
from util import canon, paginate, sort_created, v_dt, v_num, v_str

bp = make_bp("leaks")

ROLES = {"ProgramDirector", "UtilityAnalyst", "FieldSupervisor"}
FS = {"FieldSupervisor"}


def _get_or_404(leak_id):
    rec = db.store["leaks"].get(leak_id)
    if rec is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "leak not found")
    return rec


def _survey_of(leak):
    return db.store["leak_surveys"][leak["survey_id"]]


def _dma_of(leak):
    return core.get_dma(_survey_of(leak)["dma_id"])


def _finish(rec, uid, role, before, action, recompute_count=True):
    db.touch(rec)
    if recompute_count:
        core.recompute_open_leak_count(_dma_of(rec))
    db.append_audit("Leak", rec["id"], action, uid, role,
                    {"before": before, "after": {"status": rec["status"]}})
    return success_object(db.serialize(rec))


@bp.route("/nrw/leaks", methods=["POST"])
def create_leak():
    uid, role = require_roles(FS)
    body = get_body()
    # priority 3: existence of body FK
    survey_id = body.get("survey_id")
    survey = db.store["leak_surveys"].get(survey_id) if isinstance(survey_id, str) else None
    if survey is None:
        if not isinstance(survey_id, str):
            raise ApiError(errors.ERR_VALIDATION, 422, "survey_id must be a string")
        raise ApiError(errors.ERR_NOT_FOUND, 404, "leak survey not found")
    # priority 5: parent survey must be IN_FIELD
    if survey["status"] != "IN_FIELD":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "leaks may only be reported against an IN_FIELD survey")
    # priority 9: scalar constraints
    location = v_str(body, "location_description")
    loss = v_num(body, "estimated_loss_lps", gt=0)
    detected = v_dt(body, "detected_at")
    cost = v_num(body, "repair_cost_estimate", ge=0)

    rec = db.new_record()
    rec.update({
        "survey_id": survey_id,
        "location_description": location,
        "estimated_loss_lps": loss,
        "detected_at": canon(detected),
        "repair_cost_estimate": cost,
        "actual_repair_cost": None,
        "status": "REPORTED",
        "reported_by_user_id": uid,
        "repair_priority_score": None,
        "priority_band": None,
        "annualized_loss_m3": None,
    })
    calc.compute_leak_priority(rec)
    db.store["leaks"][rec["id"]] = rec
    core.recompute_open_leak_count(core.get_dma(survey["dma_id"]))
    db.append_audit("Leak", rec["id"], "CREATE", uid, role,
                    {"before": None, "after": db.serialize(rec)})
    return success_object(db.serialize(rec), status=201)


@bp.route("/nrw/leaks", methods=["GET"])
def list_leaks():
    require_roles(ROLES)
    from flask import request
    items = list(db.store["leaks"].values())
    survey_id = request.args.get("survey_id")
    if survey_id is not None:
        items = [lk for lk in items if lk["survey_id"] == survey_id]
    dma_id = request.args.get("dma_id")
    if dma_id is not None:
        survey_dma = {s["id"]: s["dma_id"] for s in db.store["leak_surveys"].values()}
        items = [lk for lk in items if survey_dma.get(lk["survey_id"]) == dma_id]
    status = request.args.get("status")
    if status is not None:
        items = [lk for lk in items if lk["status"] == status]
    band = request.args.get("priority_band")
    if band is not None:
        items = [lk for lk in items if lk["priority_band"] == band]
    items = sort_created(items)
    page, meta = paginate(items)
    return success_list([db.serialize(lk) for lk in page], meta)


@bp.route("/nrw/leaks/<leak_id>", methods=["GET"])
def get_leak(leak_id):
    require_roles(ROLES)
    return success_object(db.serialize(_get_or_404(leak_id)))


@bp.route("/nrw/leaks/<leak_id>/verify", methods=["POST"])
def verify_leak(leak_id):
    uid, role = require_roles(FS)
    rec = _get_or_404(leak_id)
    if rec["status"] != "REPORTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a REPORTED leak can be verified")
    survey = _survey_of(rec)
    if survey["status"] != "IN_FIELD":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "the parent survey is no longer IN_FIELD")
    before = {"status": "REPORTED"}
    rec["status"] = "VERIFIED"
    calc.compute_leak_priority(rec)
    return _finish(rec, uid, role, before, "VERIFY")


@bp.route("/nrw/leaks/<leak_id>/schedule-repair", methods=["POST"])
def schedule_repair(leak_id):
    uid, role = require_roles(FS)
    rec = _get_or_404(leak_id)
    if rec["status"] not in ("VERIFIED", "REOPENED"):
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a VERIFIED or REOPENED leak can be scheduled for repair")
    before = {"status": rec["status"]}
    rec["status"] = "REPAIR_SCHEDULED"
    return _finish(rec, uid, role, before, "SCHEDULE_REPAIR")


@bp.route("/nrw/leaks/<leak_id>/complete-repair", methods=["POST"])
def complete_repair(leak_id):
    uid, role = require_roles(FS)
    rec = _get_or_404(leak_id)
    if rec["status"] != "REPAIR_SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a REPAIR_SCHEDULED leak can be completed")
    body = get_body()
    # priority 9: scalar (present-but-invalid) then priority 10: prerequisite (absent)
    if "actual_repair_cost" in body and body["actual_repair_cost"] is not None:
        cost = v_num(body, "actual_repair_cost", ge=0)
    else:
        raise ApiError(errors.ERR_MISSING_PREREQUISITE, 422,
                       "actual_repair_cost is required to complete a repair")
    before = {"status": "REPAIR_SCHEDULED"}
    rec["actual_repair_cost"] = cost
    rec["status"] = "REPAIRED"
    db.touch(rec)
    core.recompute_open_leak_count(_dma_of(rec))
    db.append_audit("Leak", rec["id"], "COMPLETE_REPAIR", uid, role,
                    {"before": before,
                     "after": {"status": "REPAIRED", "actual_repair_cost": cost}})
    return success_object(db.serialize(rec))


@bp.route("/nrw/leaks/<leak_id>/verify-repair", methods=["POST"])
def verify_repair(leak_id):
    uid, role = require_roles(FS)
    rec = _get_or_404(leak_id)
    if rec["status"] != "REPAIRED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a REPAIRED leak can be repair-verified")
    # priority 7: segregation of duties
    if uid == rec["reported_by_user_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                       "the reporter of a leak may not verify its repair")
    before = {"status": "REPAIRED"}
    rec["status"] = "VERIFIED_REPAIR"
    return _finish(rec, uid, role, before, "VERIFY_REPAIR")


@bp.route("/nrw/leaks/<leak_id>/reopen", methods=["POST"])
def reopen_leak(leak_id):
    uid, role = require_roles(FS)
    rec = _get_or_404(leak_id)
    if rec["status"] != "REPAIRED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a REPAIRED leak can be reopened")
    before = {"status": "REPAIRED"}
    rec["status"] = "REOPENED"
    calc.compute_leak_priority(rec, reopened=True)
    return _finish(rec, uid, role, before, "REOPEN")


@bp.route("/nrw/leaks/<leak_id>/withdraw", methods=["POST"])
def withdraw_leak(leak_id):
    uid, role = require_roles(FS)
    rec = _get_or_404(leak_id)
    if rec["status"] not in ("REPORTED", "VERIFIED"):
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a REPORTED or VERIFIED leak can be withdrawn")
    before = {"status": rec["status"]}
    rec["status"] = "WITHDRAWN"
    return _finish(rec, uid, role, before, "WITHDRAW")
