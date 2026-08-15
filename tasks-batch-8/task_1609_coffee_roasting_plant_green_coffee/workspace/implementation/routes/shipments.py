"""Shipment endpoints: booking, transit drumbeat, receipt, disputes (PRD §3.4-3.5)."""

from flask import Blueprint

from clock import parse_iso
from db import DB
from errors import (
    ERR_CONTRACT_CAPACITY_EXCEEDED, ERR_DELIVERY_WINDOW_VIOLATION,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND, err,
)
from middleware import (
    COMMON_SYS, D, base_fields, check_unknown_fields, get_json_body, is_number,
    paginate, pub, require_fields, require_role, sort_created, touch,
    v_enum, v_int, v_iso, v_num, v_string,
)
from response import success_list, success_object
from services import (
    contract_received_accum, landed_cost_at_receipt,
    recompute_counterparty_exposure, recompute_position,
)

bp = Blueprint("shipments", __name__)

SHIPMENT_INPUTS = {"shipment_ref", "planned_lbs", "scheduled_arrival"}
SHIPMENT_SYS = {
    "contract_id", "transit_status", "qc_status", "dispute_status", "received_lbs",
} | COMMON_SYS

RECEIVE_ALLOWED = {
    "received_lbs", "lot_code", "moisture_pct", "warehouse_location",
    # GreenLot system/computed fields a client might submit are ignored.
    "shipment_id", "landed_cost_usd_per_lb", "available_lbs", "cup_score",
    "lot_status", "transit_status", "qc_status", "dispute_status",
} | COMMON_SYS

RESOLVE_ALLOWED = {"outcome", "discount_pct"} | COMMON_SYS

GET_ROLES = ("Trader", "LogisticsCoordinator", "WarehouseClerk", "QAGrader")


def get_shipment_or_404(shipment_id):
    s = DB.shipments.get(shipment_id)
    if s is None:
        raise err(ERR_NOT_FOUND, "Shipment id does not exist")
    return s


def _norm_iso(s):
    from clock import fmt_iso
    return fmt_iso(parse_iso(s))


@bp.post("/roastery/contracts/<contract_id>/shipments")
def create_shipment(contract_id):
    require_role("LogisticsCoordinator")
    contract = DB.contracts.get(contract_id)
    if contract is None:
        raise err(ERR_NOT_FOUND, "Contract id does not exist")
    body = get_json_body()
    check_unknown_fields(body, SHIPMENT_INPUTS | SHIPMENT_SYS)

    # Priority 19: delivery-window check (inclusive both ends), when parseable.
    arrival_raw = body.get("scheduled_arrival")
    if isinstance(arrival_raw, str):
        try:
            arrival = parse_iso(arrival_raw)
            ws = parse_iso(contract["delivery_window_start"])
            we = parse_iso(contract["delivery_window_end"])
            if not (ws <= arrival <= we):
                raise err(ERR_DELIVERY_WINDOW_VIOLATION,
                          "scheduled_arrival falls outside the contract delivery window")
        except ValueError:
            pass  # unparseable -> structural 400 below

    # Priorities 22/23: structural.
    require_fields(body, ["shipment_ref", "planned_lbs", "scheduled_arrival"])
    ref = v_string(body, "shipment_ref")
    planned = v_int(body, "planned_lbs", gt=0)
    arrival = v_iso(body, "scheduled_arrival")

    # Priority 30: aggregate capacity against non-cancelled sibling shipments.
    sibling_planned = sum(
        s["planned_lbs"] for s in DB.shipments.values()
        if s["contract_id"] == contract_id and s["transit_status"] != "CANCELLED"
    )
    if planned + sibling_planned > contract["total_lbs"]:
        raise err(ERR_CONTRACT_CAPACITY_EXCEEDED,
                  "Cumulative non-cancelled planned_lbs would exceed contract total_lbs")

    s = base_fields()
    s.update({
        "contract_id": contract_id,
        "shipment_ref": ref,
        "planned_lbs": planned,
        "scheduled_arrival": _norm_iso(arrival),
        "transit_status": "BOOKED",
        "qc_status": "NOT_REQUIRED",
        "dispute_status": "NONE",
        "received_lbs": None,
    })
    DB.shipments[s["id"]] = s
    return success_object(pub(s), status=201)


@bp.get("/roastery/shipments/<shipment_id>")
def get_shipment(shipment_id):
    require_role(*GET_ROLES)
    return success_object(pub(get_shipment_or_404(shipment_id)))


@bp.get("/roastery/contracts/<contract_id>/shipments")
def list_shipments(contract_id):
    require_role("Trader", "LogisticsCoordinator", "WarehouseClerk")
    if contract_id not in DB.contracts:
        raise err(ERR_NOT_FOUND, "Contract id does not exist")
    items = sort_created(
        [s for s in DB.shipments.values() if s["contract_id"] == contract_id])
    page, limit, offset, total = paginate(items)
    return success_list([pub(s) for s in page], limit, offset, total)


@bp.post("/roastery/shipments/<shipment_id>/depart")
def depart_shipment(shipment_id):
    require_role("LogisticsCoordinator")
    s = get_shipment_or_404(shipment_id)
    get_json_body()
    if s["transit_status"] != "BOOKED":
        raise err(ERR_INVALID_STATE, "Depart requires transit_status BOOKED")
    s["transit_status"] = "IN_TRANSIT"
    touch(s)
    return success_object(pub(s))


@bp.post("/roastery/shipments/<shipment_id>/arrive")
def arrive_shipment(shipment_id):
    require_role("LogisticsCoordinator")
    s = get_shipment_or_404(shipment_id)
    get_json_body()
    if s["transit_status"] != "IN_TRANSIT":
        raise err(ERR_INVALID_STATE, "Arrive requires transit_status IN_TRANSIT")
    s["transit_status"] = "ARRIVED"
    touch(s)
    return success_object(pub(s))


@bp.post("/roastery/shipments/<shipment_id>/cancel")
def cancel_shipment(shipment_id):
    require_role("LogisticsCoordinator")
    s = get_shipment_or_404(shipment_id)
    get_json_body()
    if s["transit_status"] != "BOOKED":
        raise err(ERR_INVALID_STATE, "Only BOOKED shipments may be cancelled")
    s["transit_status"] = "CANCELLED"
    touch(s)
    return success_object(pub(s))


@bp.post("/roastery/shipments/<shipment_id>/receive")
def receive_shipment(shipment_id):
    require_role("WarehouseClerk")
    s = get_shipment_or_404(shipment_id)
    body = get_json_body()

    # Priority 6: transition state preconditions (received-mass sanity is part
    # of the receipt transition per PRD §3.4 -> ERR_INVALID_STATE).
    if s["transit_status"] != "ARRIVED":
        raise err(ERR_INVALID_STATE, "Receive requires transit_status ARRIVED")
    received_raw = body.get("received_lbs")
    if is_number(received_raw):
        if not (received_raw > 0):
            raise err(ERR_INVALID_STATE, "received_lbs must be strictly positive")
        if received_raw > s["planned_lbs"]:
            raise err(ERR_INVALID_STATE, "Over-receipt not permitted: received_lbs > planned_lbs")

    # Priorities 22/23: structural.
    check_unknown_fields(body, RECEIVE_ALLOWED)
    require_fields(body, ["received_lbs", "lot_code", "moisture_pct", "warehouse_location"])
    received = v_int(body, "received_lbs")
    lot_code = v_string(body, "lot_code")
    moisture = v_num(body, "moisture_pct", ge=0, le=100)
    location = v_string(body, "warehouse_location")
    if not (received > 0) or received > s["planned_lbs"]:
        raise err(ERR_INVALID_STATE, "received_lbs must be in 1..planned_lbs")

    contract = DB.contracts.get(s["contract_id"])

    # Transition the shipment and create the single GreenLot child.
    s["transit_status"] = "RECEIVED"
    s["qc_status"] = "PENDING_CUP"
    s["received_lbs"] = received
    touch(s)

    lot = base_fields()
    lot.update({
        "shipment_id": s["id"],
        "lot_code": lot_code,
        "received_lbs": received,
        "moisture_pct": moisture,
        "warehouse_location": location,
        "landed_cost_usd_per_lb": landed_cost_at_receipt(contract),
        "available_lbs": received,
        "cup_score": None,
        "lot_status": "QUARANTINE",
    })
    DB.green_lots[lot["id"]] = lot

    # Receipt rolls uphill to the contract.
    if contract is not None:
        contract["received_lbs_accum"] = contract_received_accum(contract["id"])
        if contract["received_lbs_accum"] == contract["total_lbs"]:
            contract["fulfillment_status"] = "FULLY_RECEIVED"
        elif contract["received_lbs_accum"] > 0:
            contract["fulfillment_status"] = "PARTIALLY_RECEIVED"
        touch(contract)
        cp = DB.counterparties.get(contract["counterparty_id"])
        if cp is not None:
            recompute_counterparty_exposure(cp)

    recompute_position()
    return success_object(pub(s))


@bp.post("/roastery/shipments/<shipment_id>/resolve-dispute")
def resolve_dispute(shipment_id):
    require_role("Trader")
    s = get_shipment_or_404(shipment_id)
    body = get_json_body()

    # Priority 6: state preconditions.
    if s["dispute_status"] != "DISPUTED" or s["qc_status"] != "CUP_FAILED":
        raise err(ERR_INVALID_STATE,
                  "Resolve-dispute requires dispute_status DISPUTED and qc_status CUP_FAILED")

    check_unknown_fields(body, RESOLVE_ALLOWED)
    outcome = v_enum(body, "outcome", {"ACCEPT", "REJECT"})
    discount = None
    if outcome == "ACCEPT":
        discount = v_num(body, "discount_pct", ge=0, le=1)
    elif body.get("discount_pct") is not None:
        v_num(body, "discount_pct", ge=0, le=1)

    lot = next(
        (l for l in DB.green_lots.values() if l["shipment_id"] == s["id"]), None)

    if outcome == "ACCEPT":
        s["dispute_status"] = "RESOLVED_ACCEPTED"
        if lot is not None and lot["lot_status"] == "REJECTED":
            from middleware import q5
            lot["landed_cost_usd_per_lb"] = q5(
                D(lot["landed_cost_usd_per_lb"]) * (1 - D(discount)))
            lot["lot_status"] = "RELEASED"
            touch(lot)
    else:
        s["dispute_status"] = "RESOLVED_REJECTED"
        # Lot stays REJECTED, marked for return/destruction; physical_lbs
        # was already excluding it.
    touch(s)
    recompute_position()
    return success_object(pub(s))
