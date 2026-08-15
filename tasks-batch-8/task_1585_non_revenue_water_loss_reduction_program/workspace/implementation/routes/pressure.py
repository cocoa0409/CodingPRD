"""PressureProject endpoints."""

import db
import errors
from errors import ApiError
from middleware import get_body, require_roles
from response import success_object
from routes import make_bp
from services import calc, core
from util import D, canon, v_dt, v_num, v_str

bp = make_bp("pressure")

UA = {"UtilityAnalyst"}
PD = {"ProgramDirector"}


def _get_or_404(project_id):
    rec = db.store["pressure_projects"].get(project_id)
    if rec is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "pressure project not found")
    return rec


def _finish(rec, uid, role, before_status, action):
    db.append_audit("PressureProject", rec["id"], action, uid, role,
                    {"before": {"status": before_status},
                     "after": {"status": rec["status"]}})
    return success_object(db.serialize(rec))


@bp.route("/nrw/pressure-projects", methods=["POST"])
def create_project():
    uid, role = require_roles(UA)
    body = get_body()
    # priority 3: existence of body FK
    dma_id = body.get("dma_id")
    dma = db.store["dmas"].get(dma_id) if isinstance(dma_id, str) else None
    if dma is None:
        if not isinstance(dma_id, str):
            raise ApiError(errors.ERR_VALIDATION, 422, "dma_id must be a string")
        raise ApiError(errors.ERR_NOT_FOUND, 404, "DMA not found")
    # priority 8: interval arithmetic (creation of pressure projects is not
    # posture-gated per the validation table)
    start = db.parse_dt(body.get("planned_start"))
    end = db.parse_dt(body.get("planned_end"))
    if start is not None and end is not None and not end > start:
        raise ApiError(errors.ERR_WINDOW_CONFLICT, 409,
                       "planned_end must be after planned_start")
    # priority 9: scalar constraints
    v_dt(body, "planned_start")
    v_dt(body, "planned_end")
    name = v_str(body, "name")
    baseline = v_num(body, "baseline_pressure_m", gt=0)
    target = v_num(body, "target_pressure_m", gt=0)
    if not D(target) < D(baseline):
        raise ApiError(errors.ERR_VALIDATION, 422,
                       "target_pressure_m must be below baseline_pressure_m")

    rec = db.new_record()
    rec.update({
        "dma_id": dma_id,
        "name": name,
        "planned_start": canon(start),
        "planned_end": canon(end),
        "baseline_pressure_m": baseline,
        "target_pressure_m": target,
        "status": "PROPOSED",
        "measured_pressure_m": None,
        "pressure_reduction_pct": None,
        "estimated_leak_reduction_m3_per_year": None,
    })
    db.store["pressure_projects"][rec["id"]] = rec
    core.recompute_posture(dma)
    db.append_audit("PressureProject", rec["id"], "CREATE", uid, role,
                    {"before": None, "after": db.serialize(rec)})
    return success_object(db.serialize(rec), status=201)


@bp.route("/nrw/pressure-projects/<project_id>", methods=["GET"])
def get_project(project_id):
    require_roles({"ProgramDirector", "UtilityAnalyst"})
    return success_object(db.serialize(_get_or_404(project_id)))


@bp.route("/nrw/pressure-projects/<project_id>/approve", methods=["POST"])
def approve_project(project_id):
    uid, role = require_roles(PD)
    rec = _get_or_404(project_id)
    if rec["status"] != "PROPOSED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a PROPOSED project can be approved")
    # priority 6: posture must be exactly OPEN
    dma = core.get_dma(rec["dma_id"])
    if dma["posture"] != "OPEN":
        raise ApiError(errors.ERR_DMA_FROZEN, 409,
                       "pressure project approval requires DMA posture OPEN")
    rec["status"] = "APPROVED"
    db.touch(rec)
    return _finish(rec, uid, role, "PROPOSED", "APPROVE")


@bp.route("/nrw/pressure-projects/<project_id>/reject", methods=["POST"])
def reject_project(project_id):
    uid, role = require_roles(PD)
    rec = _get_or_404(project_id)
    if rec["status"] not in ("PROPOSED", "APPROVED"):
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a PROPOSED or APPROVED project can be rejected")
    before = rec["status"]
    rec["status"] = "REJECTED"
    db.touch(rec)
    core.recompute_posture(core.get_dma(rec["dma_id"]))
    return _finish(rec, uid, role, before, "REJECT")


@bp.route("/nrw/pressure-projects/<project_id>/activate", methods=["POST"])
def activate_project(project_id):
    uid, role = require_roles(PD)
    rec = _get_or_404(project_id)
    if rec["status"] != "APPROVED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only an APPROVED project can be activated")
    if db.logical_now() < db.parse_dt(rec["planned_start"]):
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "the logical clock has not reached planned_start")
    rec["status"] = "ACTIVE"
    db.touch(rec)
    core.recompute_posture(core.get_dma(rec["dma_id"]))
    return _finish(rec, uid, role, "APPROVED", "ACTIVATE")


@bp.route("/nrw/pressure-projects/<project_id>/commission", methods=["POST"])
def commission_project(project_id):
    uid, role = require_roles(PD)
    rec = _get_or_404(project_id)
    if rec["status"] != "ACTIVE":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only an ACTIVE project can be commissioned")
    body = get_body()
    # priority 9 scalar (present-but-invalid) then priority 10 prerequisite (absent)
    if "measured_pressure_m" in body and body["measured_pressure_m"] is not None:
        measured = v_num(body, "measured_pressure_m", gt=0)
        if D(measured) > D(rec["baseline_pressure_m"]):
            raise ApiError(errors.ERR_VALIDATION, 422,
                           "measured_pressure_m must not exceed baseline_pressure_m")
    else:
        raise ApiError(errors.ERR_MISSING_PREREQUISITE, 422,
                       "measured_pressure_m is required to commission a project")
    rec["measured_pressure_m"] = measured
    rec["status"] = "COMMISSIONED"
    calc.compute_pressure_reduction(rec)
    db.touch(rec)
    core.recompute_posture(core.get_dma(rec["dma_id"]))
    db.append_audit("PressureProject", rec["id"], "COMMISSION", uid, role,
                    {"before": {"status": "ACTIVE"},
                     "after": {"status": "COMMISSIONED",
                               "measured_pressure_m": measured}})
    return success_object(db.serialize(rec))
