from flask import Blueprint, g, request

from decimal import Decimal

from db import db
from decimalutil import round_half_up
from errors import ApiError
from helpers import (
    fetch_or_404, get_json_body, new_common_fields, paginate,
    parse_pagination, require_enum, require_type,
    sorted_by_created, strip_internal, touch,
)
from middleware import require_role
from response import success_array, success_object
from services import lot_adjust_on_hand, lot_adjust_reserved, lot_adjust_both, pod_adjust_open_allocation_count

bp = Blueprint("allocation_requests", __name__)

SOURCE_TYPES = {"SNS_CACHE", "MUTUAL_AID"}
READ_ROLES = ["PublicHealthAdmin", "LogisticsCoordinator", "MutualAidPartner"]
RISK_TIER_WEIGHT = {"STANDARD": 1, "ELEVATED": 2, "CRITICAL": 3}
BASE_QTY_WEIGHT = Decimal("0.01")
MAX_QTY_CAP = 5000


def _resolve_source_lot(ar):
    if ar["source_type"] == "SNS_CACHE":
        candidates = [
            lot for lot in db.inventory_lots.values()
            if lot["pod_id"] is None and lot["countermeasure_id"] == ar["countermeasure_id"]
        ]
    else:
        candidates = [
            lot for lot in db.inventory_lots.values()
            if lot["pod_id"] == ar["partner_pod_id"] and lot["countermeasure_id"] == ar["countermeasure_id"]
        ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda l: (l["created_at"], l["_seq"]))[0]


def _compute_priority_score(ar, pod):
    qty_term = BASE_QTY_WEIGHT * Decimal(min(ar["requested_quantity"], MAX_QTY_CAP))
    risk_term = Decimal(RISK_TIER_WEIGHT[pod["risk_tier"]])
    return round_half_up(qty_term + risk_term, 2)


@bp.route("/allocation-requests", methods=["POST"])
@require_role("LogisticsCoordinator")
def create_allocation_request():
    body = get_json_body()
    pod_id = body.get("pod_id")
    countermeasure_id = body.get("countermeasure_id")
    source_type = body.get("source_type", "SNS_CACHE")
    partner_pod_id = body.get("partner_pod_id")
    requested_quantity = body.get("requested_quantity")
    expected_pod_version = body.get("expected_pod_version")

    # priority 5: body FK existence
    pod = fetch_or_404(db.pods, pod_id, "POD")
    fetch_or_404(db.countermeasures, countermeasure_id, "Countermeasure")
    if partner_pod_id:
        fetch_or_404(db.pods, partner_pod_id, "POD")

    # priority 12: owning hazard plan must be ACTIVATED
    plan = db.hazard_plans.get(pod["hazard_plan_id"])
    if plan is None or plan["status"] != "ACTIVATED":
        raise ApiError("ERR_HAZARD_PLAN_NOT_ACTIVATED", "The requesting POD's hazard plan is not ACTIVATED.", 409)

    # priority 15: source_type / partner_pod_id pairing
    require_type(source_type, str, "source_type")
    require_enum(source_type, SOURCE_TYPES, "source_type")
    if source_type == "MUTUAL_AID":
        if not partner_pod_id or partner_pod_id == pod_id:
            raise ApiError("ERR_INVALID_SOURCE_CONFIGURATION", "MUTUAL_AID requires partner_pod_id set and different from pod_id.", 400)
    else:
        if partner_pod_id is not None:
            raise ApiError("ERR_INVALID_SOURCE_CONFIGURATION", "SNS_CACHE requires partner_pod_id to be null.", 400)

    # priority 19: OCC on POD.version
    if expected_pod_version != pod["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_pod_version does not match the POD's current version.", 412)

    # priority 23: general validation
    require_type(requested_quantity, int, "requested_quantity")
    if requested_quantity <= 0:
        raise ApiError("ERR_VALIDATION", "requested_quantity must be > 0.", 400)

    row = new_common_fields()
    row.update({
        "pod_id": pod_id,
        "countermeasure_id": countermeasure_id,
        "source_type": source_type,
        "partner_pod_id": partner_pod_id,
        "requested_quantity": requested_quantity,
        "status": "REQUESTED",
        "reserved_quantity": 0,
        "fulfilled_quantity": 0,
        "source_inventory_lot_id": None,
        "priority_score": 0,
        "reimbursement_cost_usd": 0,
    })
    db.allocation_requests[row["id"]] = row
    pod_adjust_open_allocation_count(pod, 1)
    return success_object(strip_internal(row), 201)


@bp.route("/allocation-requests/<ar_id>", methods=["GET"])
@require_role(*READ_ROLES)
def get_allocation_request(ar_id):
    row = fetch_or_404(db.allocation_requests, ar_id, "AllocationRequest")
    return success_object(strip_internal(row))


@bp.route("/allocation-requests", methods=["GET"])
@require_role(*READ_ROLES)
def list_allocation_requests():
    limit, offset = parse_pagination(request.args)
    pod_id = request.args.get("pod_id")
    countermeasure_id = request.args.get("countermeasure_id")
    partner_pod_id = request.args.get("partner_pod_id")
    source_inventory_lot_id = request.args.get("source_inventory_lot_id")
    status = request.args.get("status")
    rows = list(db.allocation_requests.values())
    if pod_id:
        rows = [r for r in rows if r["pod_id"] == pod_id]
    if countermeasure_id:
        rows = [r for r in rows if r["countermeasure_id"] == countermeasure_id]
    if partner_pod_id:
        rows = [r for r in rows if r["partner_pod_id"] == partner_pod_id]
    if source_inventory_lot_id:
        rows = [r for r in rows if r["source_inventory_lot_id"] == source_inventory_lot_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_by_created(rows)
    items, total = paginate(rows, limit, offset)
    return success_array(items, limit, offset, total)


@bp.route("/allocation-requests/<ar_id>/reserve", methods=["POST"])
@require_role("LogisticsCoordinator", "MutualAidPartner")
def reserve_allocation_request(ar_id):
    ar = fetch_or_404(db.allocation_requests, ar_id, "AllocationRequest")
    if ar["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "AllocationRequest must be REQUESTED to reserve.", 409)

    pod = fetch_or_404(db.pods, ar["pod_id"], "POD")
    plan = db.hazard_plans.get(pod["hazard_plan_id"])
    if plan is None or plan["status"] != "ACTIVATED":
        raise ApiError("ERR_HAZARD_PLAN_NOT_ACTIVATED", "The requesting POD's hazard plan is not ACTIVATED.", 409)

    if ar["source_type"] == "SNS_CACHE" and g.user_role != "LogisticsCoordinator":
        raise ApiError("ERR_SOURCE_ROLE_MISMATCH", "Only LogisticsCoordinator may reserve SNS_CACHE requests.", 403)
    if ar["source_type"] == "MUTUAL_AID" and g.user_role != "MutualAidPartner":
        raise ApiError("ERR_SOURCE_ROLE_MISMATCH", "Only MutualAidPartner may reserve MUTUAL_AID requests.", 403)

    lot = _resolve_source_lot(ar)
    available = lot["available_quantity"] if lot else 0
    if available < ar["requested_quantity"]:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY", "Source InventoryLot does not have sufficient available_quantity.", 409)

    body = get_json_body()
    expected_lot_version = body.get("expected_inventory_lot_version")
    if expected_lot_version != lot["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_inventory_lot_version does not match the source lot's current version.", 412)

    lot_adjust_reserved(lot, ar["requested_quantity"])

    ar["status"] = "RESERVED"
    ar["reserved_quantity"] = ar["requested_quantity"]
    ar["source_inventory_lot_id"] = lot["id"]
    ar["priority_score"] = _compute_priority_score(ar, pod)
    touch(ar)

    pod_adjust_open_allocation_count(pod, -1)
    return success_object(strip_internal(ar))


@bp.route("/allocation-requests/<ar_id>/deny", methods=["POST"])
@require_role("LogisticsCoordinator", "MutualAidPartner")
def deny_allocation_request(ar_id):
    ar = fetch_or_404(db.allocation_requests, ar_id, "AllocationRequest")
    if ar["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "AllocationRequest must be REQUESTED to deny.", 409)

    pod = fetch_or_404(db.pods, ar["pod_id"], "POD")
    plan = db.hazard_plans.get(pod["hazard_plan_id"])
    if plan is None or plan["status"] != "ACTIVATED":
        raise ApiError("ERR_HAZARD_PLAN_NOT_ACTIVATED", "The requesting POD's hazard plan is not ACTIVATED.", 409)

    if ar["source_type"] == "SNS_CACHE" and g.user_role != "LogisticsCoordinator":
        raise ApiError("ERR_SOURCE_ROLE_MISMATCH", "Only LogisticsCoordinator may deny SNS_CACHE requests.", 403)
    if ar["source_type"] == "MUTUAL_AID" and g.user_role != "MutualAidPartner":
        raise ApiError("ERR_SOURCE_ROLE_MISMATCH", "Only MutualAidPartner may deny MUTUAL_AID requests.", 403)

    ar["status"] = "DENIED"
    touch(ar)
    pod_adjust_open_allocation_count(pod, -1)
    return success_object(strip_internal(ar))


@bp.route("/allocation-requests/<ar_id>/fulfill", methods=["POST"])
@require_role("LogisticsCoordinator")
def fulfill_allocation_request(ar_id):
    ar = fetch_or_404(db.allocation_requests, ar_id, "AllocationRequest")
    if ar["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", "AllocationRequest must be RESERVED to fulfill.", 409)

    source_lot = fetch_or_404(db.inventory_lots, ar["source_inventory_lot_id"], "InventoryLot")
    countermeasure = fetch_or_404(db.countermeasures, ar["countermeasure_id"], "Countermeasure")

    ar["status"] = "FULFILLED"
    ar["fulfilled_quantity"] = ar["reserved_quantity"]
    if ar["source_type"] == "MUTUAL_AID":
        cost_per_dose_cents = Decimal(countermeasure["unit_cost_cents"]) / Decimal(countermeasure["doses_required"])
        reimbursement = (cost_per_dose_cents * Decimal(ar["fulfilled_quantity"])) / Decimal(100)
        ar["reimbursement_cost_usd"] = round_half_up(reimbursement, 2)
    touch(ar)

    requesting_lot = None
    candidates = [
        lot for lot in db.inventory_lots.values()
        if lot["pod_id"] == ar["pod_id"] and lot["countermeasure_id"] == ar["countermeasure_id"]
    ]
    if candidates:
        requesting_lot = sorted(candidates, key=lambda l: (l["created_at"], l["_seq"]))[0]
        lot_adjust_on_hand(requesting_lot, ar["fulfilled_quantity"])
    else:
        new_lot = new_common_fields()
        new_lot.update({
            "countermeasure_id": ar["countermeasure_id"],
            "pod_id": ar["pod_id"],
            "lot_number": f"AUTO-{ar['id']}",
            "on_hand_quantity": ar["fulfilled_quantity"],
            "reserved_quantity": 0,
            "available_quantity": ar["fulfilled_quantity"],
            "expiration_date": source_lot["expiration_date"],
        })
        db.inventory_lots[new_lot["id"]] = new_lot

    lot_adjust_both(source_lot, -ar["fulfilled_quantity"], -ar["fulfilled_quantity"])

    return success_object(strip_internal(ar))


@bp.route("/allocation-requests/<ar_id>/cancel", methods=["POST"])
@require_role("LogisticsCoordinator", "MutualAidPartner")
def cancel_allocation_request(ar_id):
    ar = fetch_or_404(db.allocation_requests, ar_id, "AllocationRequest")
    if ar["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", "AllocationRequest must be RESERVED to cancel.", 409)

    source_lot = db.inventory_lots.get(ar["source_inventory_lot_id"])
    if source_lot is not None:
        lot_adjust_reserved(source_lot, -ar["reserved_quantity"])

    ar["status"] = "CANCELLED"
    touch(ar)
    return success_object(strip_internal(ar))
