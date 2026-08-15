"""LeakSurvey endpoints."""

import db
import errors
from errors import ApiError
from middleware import get_body, require_roles
from response import success_list, success_object
from routes import make_bp
from services import core
from util import canon, paginate, sort_created, v_dt, v_enum, v_num, v_str

bp = make_bp("surveys")

READ_ROLES = {"ProgramDirector", "UtilityAnalyst", "FieldSupervisor"}
METHODS = ("ACOUSTIC", "CORRELATOR", "SATELLITE", "STEP_TEST", "NOISE_LOGGER")


def _get_or_404(survey_id):
    rec = db.store["leak_surveys"].get(survey_id)
    if rec is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "leak survey not found")
    return rec


def _leaks_found_count(survey_id):
    return sum(1 for lk in db.store["leaks"].values()
               if lk["survey_id"] == survey_id and lk["status"] != "WITHDRAWN")


def _serialize(survey):
    out = db.serialize(survey)
    out["leaks_found_count"] = _leaks_found_count(survey["id"])
    return out


@bp.route("/nrw/leak-surveys", methods=["POST"])
def create_survey():
    uid, role = require_roles({"FieldSupervisor"})
    body = get_body()
    # priority 3: existence of body FK
    dma_id = body.get("dma_id")
    dma = db.store["dmas"].get(dma_id) if isinstance(dma_id, str) else None
    if dma is None:
        if not isinstance(dma_id, str):
            raise ApiError(errors.ERR_VALIDATION, 422, "dma_id must be a string")
        raise ApiError(errors.ERR_NOT_FOUND, 404, "DMA not found")
    # priority 6: DMA posture gate
    if dma["posture"] == "FROZEN":
        raise ApiError(errors.ERR_DMA_FROZEN, 409, "parent DMA is FROZEN")
    # priority 8: interval arithmetic
    start = db.parse_dt(body.get("planned_start"))
    end = db.parse_dt(body.get("planned_end"))
    if start is not None and end is not None:
        if not end > start:
            raise ApiError(errors.ERR_WINDOW_CONFLICT, 409,
                           "planned_end must be after planned_start")
        for other in db.store["leak_surveys"].values():
            if other["dma_id"] != dma_id:
                continue
            if other["status"] not in ("PLANNED", "IN_FIELD"):
                continue
            if core.windows_overlap(start, end,
                                    db.parse_dt(other["planned_start"]),
                                    db.parse_dt(other["planned_end"])):
                raise ApiError(errors.ERR_WINDOW_CONFLICT, 409,
                               "survey window overlaps an existing planned/in-field survey")
    # priority 9: scalar constraints
    v_dt(body, "planned_start")
    v_dt(body, "planned_end")
    method = v_enum(body, "method", METHODS)
    crew = v_str(body, "crew_lead_user_id")

    rec = db.new_record()
    rec.update({
        "dma_id": dma_id,
        "planned_start": canon(start),
        "planned_end": canon(end),
        "method": method,
        "crew_lead_user_id": crew,
        "status": "PLANNED",
        "coverage_pct": None,
        "leaks_found_count": 0,
    })
    db.store["leak_surveys"][rec["id"]] = rec
    db.append_audit("LeakSurvey", rec["id"], "CREATE", uid, role,
                    {"before": None, "after": _serialize(rec)})
    return success_object(_serialize(rec), status=201)


@bp.route("/nrw/leak-surveys/<survey_id>", methods=["GET"])
def get_survey(survey_id):
    require_roles(READ_ROLES)
    return success_object(_serialize(_get_or_404(survey_id)))


@bp.route("/nrw/leak-surveys/<survey_id>/leaks", methods=["GET"])
def survey_leaks(survey_id):
    require_roles(READ_ROLES)
    _get_or_404(survey_id)
    from flask import request
    items = [lk for lk in db.store["leaks"].values() if lk["survey_id"] == survey_id]
    status = request.args.get("status")
    if status is not None:
        items = [lk for lk in items if lk["status"] == status]
    band = request.args.get("priority_band")
    if band is not None:
        items = [lk for lk in items if lk["priority_band"] == band]
    items = sort_created(items)
    page, meta = paginate(items)
    return success_list([db.serialize(lk) for lk in page], meta)


@bp.route("/nrw/leak-surveys/<survey_id>/start", methods=["POST"])
def start_survey(survey_id):
    uid, role = require_roles({"FieldSupervisor"})
    rec = _get_or_404(survey_id)
    # priority 5: state-machine validity + clock precondition
    if rec["status"] != "PLANNED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a PLANNED survey can be started")
    if db.logical_now() < db.parse_dt(rec["planned_start"]):
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "the logical clock has not reached planned_start")
    # priority 6: DMA posture must be exactly OPEN
    dma = core.get_dma(rec["dma_id"])
    if dma["posture"] != "OPEN":
        raise ApiError(errors.ERR_DMA_FROZEN, 409,
                       "parent DMA posture must be OPEN to start field work")
    rec["status"] = "IN_FIELD"
    db.touch(rec)
    db.append_audit("LeakSurvey", rec["id"], "START", uid, role,
                    {"before": {"status": "PLANNED"}, "after": {"status": "IN_FIELD"}})
    return success_object(_serialize(rec))


@bp.route("/nrw/leak-surveys/<survey_id>/complete", methods=["POST"])
def complete_survey(survey_id):
    uid, role = require_roles({"FieldSupervisor"})
    rec = _get_or_404(survey_id)
    if rec["status"] != "IN_FIELD":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only an IN_FIELD survey can be completed")
    body = get_body()
    coverage = v_num(body, "coverage_pct", gt=0, le=100)
    rec["coverage_pct"] = coverage
    rec["status"] = "COMPLETED"
    db.touch(rec)
    db.append_audit("LeakSurvey", rec["id"], "COMPLETE", uid, role,
                    {"before": {"status": "IN_FIELD"},
                     "after": {"status": "COMPLETED", "coverage_pct": coverage}})
    return success_object(_serialize(rec))


@bp.route("/nrw/leak-surveys/<survey_id>/cancel", methods=["POST"])
def cancel_survey(survey_id):
    uid, role = require_roles({"FieldSupervisor"})
    rec = _get_or_404(survey_id)
    if rec["status"] not in ("PLANNED", "IN_FIELD"):
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a PLANNED or IN_FIELD survey can be cancelled")
    # priority 14: cancellation children guard
    children = [lk for lk in db.store["leaks"].values() if lk["survey_id"] == survey_id]
    if rec["status"] == "PLANNED":
        if children:
            raise ApiError(errors.ERR_CHILDREN_OPEN, 409,
                           "a PLANNED survey with leak rows cannot be cancelled")
    else:
        if any(lk["status"] not in core.LEAK_TERMINAL for lk in children):
            raise ApiError(errors.ERR_CHILDREN_OPEN, 409,
                           "an IN_FIELD survey with non-terminal leaks cannot be cancelled")
    before = rec["status"]
    rec["status"] = "CANCELLED"
    db.touch(rec)
    db.append_audit("LeakSurvey", rec["id"], "CANCEL", uid, role,
                    {"before": {"status": before}, "after": {"status": "CANCELLED"}})
    return success_object(_serialize(rec))
