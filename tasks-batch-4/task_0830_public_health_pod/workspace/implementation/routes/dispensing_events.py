from flask import Blueprint, request

from db import db
from errors import ApiError
from helpers import (
    fetch_or_404, get_json_body, new_common_fields, paginate,
    parse_pagination, require_enum, require_fields, require_type,
    sorted_by_created, strip_internal, touch,
)
from middleware import require_role
from response import success_array, success_object
from services import lot_adjust_on_hand, maybe_cascade_restrict_from_dispense, pod_adjust_queue_backlog

bp = Blueprint("dispensing_events", __name__)

RISK_GROUPS = {"GENERAL_PUBLIC", "HEALTHCARE_WORKER", "FIRST_RESPONDER", "HIGH_RISK_MEDICAL"}
READ_ROLES = ["PublicHealthAdmin", "LogisticsCoordinator", "ClinicalLead", "Volunteer"]


def _select_fefo_lot(pod_id, countermeasure_id, dose_count):
    candidates = [
        lot for lot in db.inventory_lots.values()
        if lot["pod_id"] == pod_id and lot["countermeasure_id"] == countermeasure_id
        and lot["available_quantity"] >= dose_count
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda l: (l["expiration_date"], l["created_at"], l["_seq"]))[0]


@bp.route("/dispensing-events", methods=["POST"])
@require_role("Volunteer", "ClinicalLead")
def create_dispensing_event():
    body = get_json_body()
    pod_id = body.get("pod_id")
    countermeasure_id = body.get("countermeasure_id")

    pod = fetch_or_404(db.pods, pod_id, "POD")
    fetch_or_404(db.countermeasures, countermeasure_id, "Countermeasure")

    require_fields(body, ["registrant_full_name", "registrant_risk_group"])
    require_type(body["registrant_full_name"], str, "registrant_full_name")
    require_type(body["registrant_risk_group"], str, "registrant_risk_group")
    require_enum(body["registrant_risk_group"], RISK_GROUPS, "registrant_risk_group")
    dose_count = body.get("dose_count", 1)
    require_type(dose_count, int, "dose_count")
    if dose_count <= 0:
        raise ApiError("ERR_VALIDATION", "dose_count must be > 0.", 400)

    row = new_common_fields()
    row.update({
        "pod_id": pod_id,
        "countermeasure_id": countermeasure_id,
        "inventory_lot_id": None,
        "registrant_full_name": body["registrant_full_name"],
        "registrant_risk_group": body["registrant_risk_group"],
        "dose_count": dose_count,
        "status": "REGISTERED",
        "screened_by_staff_member_id": None,
        "dispensed_by_staff_member_id": None,
        "deferral_reason": None,
    })
    db.dispensing_events[row["id"]] = row
    pod_adjust_queue_backlog(pod, 1)
    return success_object(strip_internal(row), 201)


@bp.route("/dispensing-events/<event_id>", methods=["GET"])
@require_role(*READ_ROLES)
def get_dispensing_event(event_id):
    row = fetch_or_404(db.dispensing_events, event_id, "DispensingEvent")
    return success_object(strip_internal(row))


@bp.route("/dispensing-events", methods=["GET"])
@require_role(*READ_ROLES)
def list_dispensing_events():
    limit, offset = parse_pagination(request.args)
    filters = {
        "pod_id": request.args.get("pod_id"),
        "countermeasure_id": request.args.get("countermeasure_id"),
        "inventory_lot_id": request.args.get("inventory_lot_id"),
        "screened_by_staff_member_id": request.args.get("screened_by_staff_member_id"),
        "dispensed_by_staff_member_id": request.args.get("dispensed_by_staff_member_id"),
        "status": request.args.get("status"),
    }
    rows = list(db.dispensing_events.values())
    for field, value in filters.items():
        if value:
            rows = [r for r in rows if r[field] == value]
    rows = sorted_by_created(rows)
    items, total = paginate(rows, limit, offset)
    return success_array(items, limit, offset, total)


@bp.route("/dispensing-events/<event_id>/screen", methods=["POST"])
@require_role("ClinicalLead")
def screen_dispensing_event(event_id):
    event = fetch_or_404(db.dispensing_events, event_id, "DispensingEvent")
    if event["status"] != "REGISTERED":
        raise ApiError("ERR_INVALID_STATE", "DispensingEvent must be REGISTERED to screen.", 409)
    pod = fetch_or_404(db.pods, event["pod_id"], "POD")
    if pod["operational_status"] not in ("OPERATIONAL", "RESTRICTED"):
        raise ApiError("ERR_POD_NOT_OPERATIONAL", "POD must be OPERATIONAL or RESTRICTED to screen.", 409)
    body = get_json_body()
    event["status"] = "SCREENED"
    event["screened_by_staff_member_id"] = body.get("screened_by_staff_member_id")
    touch(event)
    return success_object(strip_internal(event))


@bp.route("/dispensing-events/<event_id>/defer", methods=["POST"])
@require_role("ClinicalLead")
def defer_dispensing_event(event_id):
    event = fetch_or_404(db.dispensing_events, event_id, "DispensingEvent")
    if event["status"] != "SCREENED":
        raise ApiError("ERR_INVALID_STATE", "DispensingEvent must be SCREENED to defer.", 409)
    body = get_json_body()
    deferral_reason = body.get("deferral_reason")
    if not deferral_reason or not isinstance(deferral_reason, str):
        raise ApiError("ERR_VALIDATION", "deferral_reason must be a non-empty string.", 400)
    event["status"] = "DEFERRED"
    event["deferral_reason"] = deferral_reason
    touch(event)
    return success_object(strip_internal(event))


@bp.route("/dispensing-events/<event_id>/rescreen", methods=["POST"])
@require_role("ClinicalLead")
def rescreen_dispensing_event(event_id):
    event = fetch_or_404(db.dispensing_events, event_id, "DispensingEvent")
    if event["status"] != "DEFERRED":
        raise ApiError("ERR_INVALID_STATE", "DispensingEvent must be DEFERRED to rescreen.", 409)
    event["status"] = "SCREENED"
    event["deferral_reason"] = None
    touch(event)
    return success_object(strip_internal(event))


@bp.route("/dispensing-events/<event_id>/refuse", methods=["POST"])
@require_role("ClinicalLead")
def refuse_dispensing_event(event_id):
    event = fetch_or_404(db.dispensing_events, event_id, "DispensingEvent")
    if event["status"] != "SCREENED":
        raise ApiError("ERR_INVALID_STATE", "DispensingEvent must be SCREENED to refuse.", 409)
    event["status"] = "REFUSED"
    touch(event)
    pod = db.pods.get(event["pod_id"])
    if pod is not None:
        pod_adjust_queue_backlog(pod, -1)
    return success_object(strip_internal(event))


@bp.route("/dispensing-events/<event_id>/dispense", methods=["POST"])
@require_role("ClinicalLead")
def dispense_dispensing_event(event_id):
    event = fetch_or_404(db.dispensing_events, event_id, "DispensingEvent")
    if event["status"] != "SCREENED":
        raise ApiError("ERR_INVALID_STATE", "DispensingEvent must be SCREENED to dispense.", 409)
    pod = fetch_or_404(db.pods, event["pod_id"], "POD")
    if pod["operational_status"] not in ("OPERATIONAL", "RESTRICTED"):
        raise ApiError("ERR_POD_NOT_OPERATIONAL", "POD must be OPERATIONAL or RESTRICTED to dispense.", 409)
    countermeasure = fetch_or_404(db.countermeasures, event["countermeasure_id"], "Countermeasure")

    lot = _select_fefo_lot(pod["id"], event["countermeasure_id"], event["dose_count"])
    if lot is None:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY", "No POD-scoped InventoryLot has sufficient available_quantity.", 409)

    body = get_json_body()
    event["status"] = "DISPENSED"
    event["dispensed_by_staff_member_id"] = body.get("dispensed_by_staff_member_id")
    event["inventory_lot_id"] = lot["id"]
    touch(event)

    pod_adjust_queue_backlog(pod, -1)

    lot_adjust_on_hand(lot, -event["dose_count"])  # Cascade A hop 1

    auto_request = maybe_cascade_restrict_from_dispense(pod, lot, countermeasure)  # hops 2 + 3
    if auto_request is not None:
        db.allocation_requests[auto_request["id"]] = auto_request

    return success_object(strip_internal(event))
