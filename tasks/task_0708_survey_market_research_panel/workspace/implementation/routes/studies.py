"""Study + QuotaCell endpoints (PRD §3.1, §3.4, §3.9)."""
from flask import Blueprint

import db
import errors
import lookup
import response
import validation
from middleware import get_identity, require_roles
from services import core, lifecycle

bp = Blueprint("studies", __name__)

ALL_OPERATORS = {"ResearchManager", "PanelOps", "FieldCoordinator"}


@bp.post("/studies")
def create_study():
    user_id, role = get_identity()
    require_roles(role, {"ResearchManager"})
    body = validation.get_json_body()

    title = validation.require_str(body, "title")
    # irb_protocol_number is required as a field but MAY be empty at create time;
    # the non-empty rule is a LAUNCH precondition (PRD §3.1 line 124), enforced as
    # ERR_IRB_PROTOCOL_REQUIRED on /launch, not at create.
    irb = validation.require_present_str(body, "irb_protocol_number")
    estimated_minutes = validation.require_int(body, "estimated_minutes", minimum=1)
    base_points = validation.require_int(body, "base_incentive_points", minimum=0)
    screener_min_age = validation.require_int(body, "screener_min_age", minimum=0)
    required_consent_version = validation.opt_int(
        body, "required_consent_version", default=1, minimum=1)

    rec = db.base_record(common_fields=True)
    rec.update({
        "title": title,
        "irb_protocol_number": irb,
        "estimated_minutes": estimated_minutes,
        "base_incentive_points": base_points,
        "screener_min_age": screener_min_age,
        "required_consent_version": required_consent_version,
        "status": "DRAFT",
    })
    db.studies[rec["id"]] = rec
    return response.object_response(core.serialize_study(rec), status=201)


@bp.get("/studies")
def list_studies():
    user_id, role = get_identity()
    require_roles(role, ALL_OPERATORS)
    from flask import request
    status = request.args.get("status")
    records = [s for s in db.studies.values()
               if status is None or s["status"] == status]
    window, limit, offset, total = validation.paginate(records)
    return response.array_response(
        [core.serialize_study(s) for s in window], limit, offset, total)


@bp.get("/studies/<sid>")
def get_study(sid):
    user_id, role = get_identity()
    require_roles(role, ALL_OPERATORS)
    study = lookup.study(sid)
    return response.object_response(core.serialize_study(study))


def _transition_only(role):
    require_roles(role, {"ResearchManager"})


@bp.post("/studies/<sid>/launch")
def launch_study(sid):
    user_id, role = get_identity()
    _transition_only(role)
    study = lookup.study(sid)
    if study["status"] != "DRAFT":
        errors.fail(errors.ERR_INVALID_STATE, "Study is not in DRAFT")
    # Preconditions (PRD §3.1). Order per error catalog: IRB (422) then quota (409).
    if not study["irb_protocol_number"]:
        errors.fail(errors.ERR_IRB_PROTOCOL_REQUIRED, "irb_protocol_number is empty")
    target_total_n, _ = core.study_totals(study)
    if target_total_n < 1:
        errors.fail(errors.ERR_NO_QUOTA_CELLS, "Study has no quota cells")
    study["status"] = "FIELDING"
    db.touch(study)
    return response.object_response(core.serialize_study(study))


@bp.post("/studies/<sid>/pause")
def pause_study(sid):
    user_id, role = get_identity()
    _transition_only(role)
    study = lookup.study(sid)
    if study["status"] != "FIELDING":
        errors.fail(errors.ERR_INVALID_STATE, "Study is not in FIELDING")
    study["status"] = "PAUSED"
    db.touch(study)
    return response.object_response(core.serialize_study(study))


@bp.post("/studies/<sid>/resume")
def resume_study(sid):
    user_id, role = get_identity()
    _transition_only(role)
    study = lookup.study(sid)
    if study["status"] != "PAUSED":
        errors.fail(errors.ERR_INVALID_STATE, "Study is not in PAUSED")
    study["status"] = "FIELDING"
    db.touch(study)
    return response.object_response(core.serialize_study(study))


@bp.post("/studies/<sid>/close")
def close_study(sid):
    user_id, role = get_identity()
    _transition_only(role)
    study = lookup.study(sid)
    if study["status"] not in ("FIELDING", "PAUSED"):
        errors.fail(errors.ERR_INVALID_STATE, "Study is not FIELDING or PAUSED")
    study["status"] = "CLOSED"
    db.touch(study)
    # Cascade A: SCREENING/SCREENED_IN participations -> VOIDED.
    lifecycle.cascade_void_for_study(study["id"])
    return response.object_response(core.serialize_study(study))


@bp.post("/studies/<sid>/deliver")
def deliver_study(sid):
    user_id, role = get_identity()
    _transition_only(role)
    study = lookup.study(sid)
    if study["status"] != "CLOSED":
        errors.fail(errors.ERR_INVALID_STATE, "Study is not in CLOSED")
    ready = [d for d in db.data_deliveries.values()
             if d["study_id"] == study["id"] and d["status"] == "READY"]
    if not ready:
        errors.fail(errors.ERR_DELIVERY_NOT_READY, "No READY DataDelivery for study")
    study["status"] = "DELIVERED"
    db.touch(study)
    for d in ready:
        d["status"] = "DELIVERED"
        db.touch(d)
    return response.object_response(core.serialize_study(study))


# ----- Quota cells -----
@bp.post("/studies/<sid>/quota-cells")
def create_quota_cell(sid):
    user_id, role = get_identity()
    require_roles(role, {"ResearchManager"})
    study = lookup.study(sid)
    body = validation.get_json_body()
    segment_key = validation.require_str(body, "segment_key")
    target_n = validation.require_int(body, "target_n", minimum=1)

    # Cells may be added while DRAFT or FIELDING (PRD §3.1).
    if study["status"] not in ("DRAFT", "FIELDING"):
        errors.fail(errors.ERR_INVALID_STATE,
                    "Quota cells can only be added in DRAFT or FIELDING")

    for cell in db.quota_cells.values():
        if cell["study_id"] == study["id"] and cell["segment_key"] == segment_key:
            errors.fail(errors.ERR_DUPLICATE_SEGMENT,
                        "segment_key already used in this study")

    rec = db.base_record(common_fields=True)
    rec.update({
        "study_id": study["id"],
        "segment_key": segment_key,
        "target_n": target_n,
    })
    db.quota_cells[rec["id"]] = rec
    return response.object_response(core.serialize_quota_cell(rec), status=201)


@bp.get("/studies/<sid>/quota-cells")
def list_quota_cells(sid):
    user_id, role = get_identity()
    require_roles(role, ALL_OPERATORS)
    study = lookup.study(sid)
    records = [c for c in db.quota_cells.values() if c["study_id"] == study["id"]]
    window, limit, offset, total = validation.paginate(records)
    return response.array_response(
        [core.serialize_quota_cell(c) for c in window], limit, offset, total)


@bp.get("/quota-cells/<cid>")
def get_quota_cell(cid):
    user_id, role = get_identity()
    require_roles(role, ALL_OPERATORS)
    cell = lookup.quota_cell(cid)
    return response.object_response(core.serialize_quota_cell(cell))
