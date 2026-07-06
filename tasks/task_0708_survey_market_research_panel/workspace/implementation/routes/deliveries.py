"""DataDelivery endpoints + logical-clock setter (PRD §3.9, §2.4)."""
from flask import Blueprint, request

import clock
import db
import errors
import lookup
import response
import validation
from middleware import get_identity, require_roles

from services import core

bp = Blueprint("deliveries", __name__)


def _included_completes_n(study_id):
    """Count of the study's participations with quality_status PASS and
    completion_status COMPLETED at build time (PRD §3.9)."""
    n = 0
    for p in db.participations.values():
        if (p["study_id"] == study_id
                and p["quality_status"] == "PASS"
                and p["completion_status"] == "COMPLETED"):
            n += 1
    return n


@bp.post("/data-deliveries")
def create_delivery():
    user_id, role = get_identity()
    require_roles(role, {"ResearchManager"})
    body = validation.get_json_body()
    study_id = validation.require_str(body, "study_id")
    report_format = validation.require_enum(
        body, "report_format", {"CSV", "SPSS", "DASHBOARD"})
    lookup.study(study_id)

    rec = db.base_record(common_fields=True)
    rec.update({
        "study_id": study_id,
        "included_completes_n": 0,
        "report_format": report_format,
        "status": "BUILDING",
    })
    db.data_deliveries[rec["id"]] = rec
    return response.object_response(core.serialize_data_delivery(rec), status=201)


@bp.get("/data-deliveries")
def list_deliveries():
    user_id, role = get_identity()
    require_roles(role, {"ResearchManager", "PanelOps"})
    study_id = request.args.get("study_id")
    status = request.args.get("status")
    records = []
    for d in db.data_deliveries.values():
        if study_id is not None and d["study_id"] != study_id:
            continue
        if status is not None and d["status"] != status:
            continue
        records.append(d)
    window, limit, offset, total = validation.paginate(records)
    return response.array_response(
        [core.serialize_data_delivery(d) for d in window], limit, offset, total)


@bp.get("/data-deliveries/<did>")
def get_delivery(did):
    user_id, role = get_identity()
    require_roles(role, {"ResearchManager", "PanelOps"})
    d = lookup.data_delivery(did)
    return response.object_response(core.serialize_data_delivery(d))


@bp.post("/data-deliveries/<did>/build")
def build_delivery(did):
    user_id, role = get_identity()
    require_roles(role, {"ResearchManager"})
    d = lookup.data_delivery(did)
    if d["status"] != "BUILDING":
        errors.fail(errors.ERR_INVALID_STATE, "DataDelivery is not BUILDING")
    study = lookup.study(d["study_id"])
    if study["status"] != "CLOSED":
        errors.fail(errors.ERR_STUDY_NOT_CLOSED, "Parent study is not CLOSED")
    d["included_completes_n"] = _included_completes_n(d["study_id"])
    d["status"] = "READY"
    db.touch(d)
    return response.object_response(core.serialize_data_delivery(d))


@bp.post("/data-deliveries/<did>/revoke")
def revoke_delivery(did):
    user_id, role = get_identity()
    require_roles(role, {"ResearchManager"})
    d = lookup.data_delivery(did)
    if d["status"] not in ("BUILDING", "READY"):
        errors.fail(errors.ERR_INVALID_STATE, "DataDelivery is not BUILDING or READY")
    d["status"] = "REVOKED"
    db.touch(d)
    return response.object_response(core.serialize_data_delivery(d))


# ----- Logical clock (test-driving) -----
@bp.post("/_clock/set_current_utc")
def set_clock():
    user_id, role = get_identity()
    require_roles(role, {"ResearchManager", "PanelOps", "FieldCoordinator"})
    body = validation.get_json_body()
    to_iso8601 = validation.require_str(body, "to_iso8601")
    try:
        clock.set_now(to_iso8601)
    except (ValueError, TypeError):
        errors.fail(errors.ERR_VALIDATION, "to_iso8601 must be an ISO 8601 instant")
    return response.object_response({"current_utc": clock.now_iso()})
