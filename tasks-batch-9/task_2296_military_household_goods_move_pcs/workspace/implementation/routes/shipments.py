"""Shipment booking, survey, movement and weight reconciliation (PRD §3.5-§3.8)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from db import base_record, by_seq, clock, db, mark_fresh, touch
from errors import ApiError
from middleware import (
    ROLE_CLAIMS_EXAMINER,
    ROLE_MOVE_COUNSELOR,
    ROLE_PROGRAM_ADMIN,
    ROLE_SERVICE_MEMBER,
    ROLE_TSP_COORDINATOR,
    endpoint,
    require_ownership,
)
from paging import list_response
from response import created, ok
from serializers import serialize
from services import calculations as calc
from services import ledger
from validation import (
    MARKET_CODE_RE,
    bad,
    get_body,
    opt_str,
    req_bool,
    req_dt,
    req_enum,
    req_int,
    req_list,
    req_pattern,
    req_str,
    validate_room_estimates,
)

bp = Blueprint("shipments", __name__)


def _entitlement_of(shipment):
    return db.entitlements.get(shipment["entitlement_id"])


def _authorization_gate(shipment):
    """Ladder step 19 — DRAFT or CLOSED ledgers take no shipment work."""
    entitlement = _entitlement_of(shipment)
    if entitlement is not None and entitlement["status"] in ("DRAFT", "CLOSED"):
        raise ApiError(
            "ERR_ENTITLEMENT_NOT_AUTHORIZED", "The owning entitlement is not authorized."
        )
    return entitlement


def _member_of(shipment):
    order = db.orders.get(shipment["order_id"])
    if order is None:
        return None
    return db.service_members.get(order["service_member_id"])


def _sync_member_count(shipment):
    member = _member_of(shipment)
    if member is not None:
        ledger.recompute_member_shipment_count(member)


def _record_certified_weights(shipment, body):
    actual_gross = req_int(body, "actual_gross_lbs", minimum=1)
    actual_tare = req_int(body, "actual_tare_lbs", minimum=0)
    weigh_date = req_dt(body, "weigh_date")
    scale_certified = req_bool(body, "scale_certified")
    if actual_tare >= actual_gross:
        raise bad("Field 'actual_tare_lbs' must be strictly less than 'actual_gross_lbs'.")
    return actual_gross, actual_tare, weigh_date, scale_certified


# --------------------------------------------------------------------- booking


@bp.post("/shipments")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def book_shipment():
    body = get_body()
    order_id = req_str(body, "order_id")
    entitlement_id = req_str(body, "entitlement_id")
    tsp_id = req_str(body, "tsp_id")
    shipment_code = req_str(body, "shipment_code", min_len=4, max_len=24)
    shipment_method = req_enum(body, "shipment_method", calc.SHIPMENT_METHODS)
    origin_market_code = req_pattern(
        body, "origin_market_code", MARKET_CODE_RE, "match ^MKT-[A-Z]{3}$"
    )
    requested_pack_date = req_dt(body, "requested_pack_date")
    requested_pickup_date = req_dt(body, "requested_pickup_date")
    requested_delivery_date = req_dt(body, "requested_delivery_date")
    expected_version = req_int(body, "expected_entitlement_version")
    superseded_shipment_id = opt_str(body, "superseded_shipment_id")
    if requested_pickup_date < requested_pack_date:
        raise bad("Field 'requested_pickup_date' must be on or after 'requested_pack_date'.")
    if requested_delivery_date <= requested_pickup_date:
        raise bad("Field 'requested_delivery_date' must be after 'requested_pickup_date'.")

    order = ledger.get_order(order_id)
    entitlement = ledger.get_entitlement(entitlement_id)
    tsp = ledger.get_tsp(tsp_id)
    superseded = None
    if superseded_shipment_id is not None:
        superseded = ledger.get_shipment(superseded_shipment_id)

    if entitlement["status"] in ("DRAFT", "CLOSED"):
        raise ApiError(
            "ERR_ENTITLEMENT_NOT_AUTHORIZED", "The entitlement is not authorized for shipments."
        )
    if entitlement["status"] == "SUSPENDED":
        raise ApiError("ERR_ENTITLEMENT_SUSPENDED", "The entitlement is suspended.")
    if expected_version != entitlement["version"]:
        raise ApiError(
            "ERR_STALE_ENTITLEMENT_VERSION", "The entitlement has been modified since it was read."
        )
    if tsp["status"] == "SUSPENDED":
        raise ApiError("ERR_TSP_NOT_ACTIVE", "This provider takes no new work.")
    if origin_market_code not in tsp["markets"]:
        raise ApiError("ERR_MARKET_NOT_SERVED", "This provider does not serve that market.")

    for existing in db.shipments.values():
        if existing["shipment_code"] == shipment_code:
            raise bad("Field 'shipment_code' must be unique across shipments.")

    booked_at = clock()
    window = calc.spread_window(requested_pickup_date, booked_at, order["distance_miles"])

    record = base_record()
    record.update(
        {
            "order_id": order["id"],
            "entitlement_id": entitlement["id"],
            "tsp_id": tsp["id"],
            "capacity_block_id": None,
            "superseded_shipment_id": superseded["id"] if superseded else None,
            "shipment_code": shipment_code,
            "shipment_method": shipment_method,
            "origin_market_code": origin_market_code,
            "requested_pack_date": requested_pack_date,
            "requested_pickup_date": requested_pickup_date,
            "requested_delivery_date": requested_delivery_date,
            "booked_at": booked_at,
            "is_short_notice": window["is_short_notice"],
            "peak_season": window["peak_season"],
            "spread_start_date": window["spread_start_date"],
            "spread_end_date": window["spread_end_date"],
            "transit_days_allowed": window["transit_days_allowed"],
            "required_delivery_by": None,
            "survey_date": None,
            "estimate_method": None,
            "room_estimates": None,
            "estimated_gross_lbs": None,
            "actual_gross_lbs": None,
            "actual_tare_lbs": None,
            "net_actual_lbs": None,
            "pro_gear_excluded_lbs": 0,
            "billable_weight_lbs": 0,
            "billable_basis": "NONE",
            "reweigh_required": False,
            "weigh_date": None,
            "pack_date": None,
            "actual_pickup_date": None,
            "delivery_date": None,
            "movement_status": "AWARDED",
            "weight_recon_status": "PENDING",
            "hold_reason": None,
            "cancel_reason": None,
        }
    )
    mark_fresh(record)
    db.shipments[record["id"]] = record

    _sync_member_count(record)
    ledger.recompute_entitlement_ledger(entitlement, cascade=True)
    return created(serialize(record))


@bp.get("/shipments")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_TSP_COORDINATOR, ROLE_CLAIMS_EXAMINER, ROLE_PROGRAM_ADMIN])
def list_shipments():
    return list_response(by_seq(list(db.shipments.values())))


@bp.get("/shipments/<shipment_id>")
@endpoint(
    [
        ROLE_SERVICE_MEMBER,
        ROLE_MOVE_COUNSELOR,
        ROLE_TSP_COORDINATOR,
        ROLE_CLAIMS_EXAMINER,
        ROLE_PROGRAM_ADMIN,
    ]
)
def read_shipment(shipment_id):
    shipment = ledger.get_shipment(shipment_id)
    require_ownership(ledger.member_of_shipment(shipment))
    return ok(serialize(shipment))


@bp.get("/shipments/<shipment_id>/superseding-shipments")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def list_superseding_shipments(shipment_id):
    shipment = ledger.get_shipment(shipment_id)
    records = by_seq(
        [s for s in db.shipments.values() if s["superseded_shipment_id"] == shipment["id"]]
    )
    return list_response(records)


# ---------------------------------------------------------------------- survey


@bp.post("/shipments/<shipment_id>/survey")
@endpoint([ROLE_TSP_COORDINATOR])
def survey_shipment(shipment_id):
    body = get_body()
    estimate_method = req_enum(body, "estimate_method", calc.ESTIMATE_METHODS)
    raw_rooms = req_list(body, "room_estimates")
    rooms = validate_room_estimates(raw_rooms)

    shipment = ledger.get_shipment(shipment_id)

    if shipment["movement_status"] != "AWARDED" or shipment["weight_recon_status"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_SHIPMENT_MOVEMENT_STATE",
            "A survey is only accepted on an awarded, unsurveyed shipment.",
        )
    _authorization_gate(shipment)
    if not rooms:
        raise ApiError("ERR_SURVEY_ROOM_ESTIMATES_EMPTY", "At least one room estimate is required.")

    shipment["survey_date"] = clock()
    shipment["estimate_method"] = estimate_method
    shipment["room_estimates"] = rooms
    shipment["estimated_gross_lbs"] = calc.survey_estimated_gross(rooms, estimate_method)
    shipment["movement_status"] = "SURVEYED"
    shipment["weight_recon_status"] = "ESTIMATED"
    touch(shipment)
    ledger.recompute_shipment_weight(shipment)

    entitlement = _entitlement_of(shipment)
    if entitlement is not None:
        ledger.recompute_entitlement_ledger(entitlement, cascade=True)
    return ok(serialize(shipment))


# ------------------------------------------------------------- pack and pickup


@bp.post("/shipments/<shipment_id>/pack")
@endpoint([ROLE_TSP_COORDINATOR])
def pack_shipment(shipment_id):
    body = get_body()
    pack_date = req_dt(body, "pack_date")

    shipment = ledger.get_shipment(shipment_id)

    if shipment["movement_status"] != "SURVEYED":
        raise ApiError(
            "ERR_INVALID_SHIPMENT_MOVEMENT_STATE", "Only a surveyed shipment may be packed."
        )
    _authorization_gate(shipment)
    if shipment["capacity_block_id"] is None:
        raise ApiError(
            "ERR_CAPACITY_BLOCK_NOT_ASSIGNED", "The shipment holds no weekly capacity slot."
        )
    if pack_date < shipment["spread_start_date"] - timedelta(days=1):
        raise ApiError("ERR_PACK_BEFORE_SPREAD", "The pack date is too early for the spread window.")

    shipment["pack_date"] = pack_date
    shipment["movement_status"] = "PACKED"
    touch(shipment)
    ledger.create_notification(shipment["id"], "PACK_DATE_CONFIRMED")
    return ok(serialize(shipment))


@bp.post("/shipments/<shipment_id>/pickup")
@endpoint([ROLE_TSP_COORDINATOR])
def pickup_shipment(shipment_id):
    body = get_body()
    actual_pickup_date = req_dt(body, "actual_pickup_date")

    shipment = ledger.get_shipment(shipment_id)

    if shipment["movement_status"] != "PACKED":
        raise ApiError(
            "ERR_INVALID_SHIPMENT_MOVEMENT_STATE", "Only a packed shipment may be picked up."
        )
    if (
        actual_pickup_date < shipment["spread_start_date"]
        or actual_pickup_date > shipment["spread_end_date"]
    ):
        raise ApiError("ERR_PICKUP_OUTSIDE_SPREAD", "The pickup date falls outside the spread window.")

    shipment["actual_pickup_date"] = actual_pickup_date
    shipment["required_delivery_by"] = actual_pickup_date + timedelta(
        days=shipment["transit_days_allowed"]
    )
    shipment["movement_status"] = "PICKED_UP"
    touch(shipment)
    ledger.create_notification(shipment["id"], "PICKUP_CONFIRMED")
    return ok(serialize(shipment))


# --------------------------------------------------------------- weight record


@bp.post("/shipments/<shipment_id>/record-actual-weight")
@endpoint([ROLE_TSP_COORDINATOR])
def record_actual_weight(shipment_id):
    body = get_body()
    shipment = ledger.get_shipment(shipment_id)
    actual_gross, actual_tare, weigh_date, scale_certified = _record_certified_weights(
        shipment, body
    )

    if shipment["weight_recon_status"] != "ESTIMATED":
        raise ApiError(
            "ERR_INVALID_WEIGHT_RECON_STATE",
            "The certified weight is only recorded against an estimated shipment.",
        )
    if shipment["movement_status"] not in ("SURVEYED", "PACKED", "PICKED_UP", "IN_SIT"):
        raise ApiError(
            "ERR_INVALID_SHIPMENT_MOVEMENT_STATE",
            "The scale can only be read between survey and storage.",
        )
    if scale_certified is not True:
        raise ApiError("ERR_UNCERTIFIED_SCALE", "The weight of record must come from a certified scale.")

    net = actual_gross - actual_tare
    shipment["actual_gross_lbs"] = actual_gross
    shipment["actual_tare_lbs"] = actual_tare
    shipment["net_actual_lbs"] = net
    shipment["weigh_date"] = weigh_date
    estimated = shipment["estimated_gross_lbs"] or 0
    shipment["reweigh_required"] = Decimal(net) > Decimal(estimated) * calc.REWEIGH_TRIGGER_RATIO
    shipment["weight_recon_status"] = "ACTUAL_RECORDED"
    touch(shipment)
    ledger.recompute_shipment_weight(shipment)

    entitlement = _entitlement_of(shipment)
    if entitlement is not None:
        ledger.recompute_entitlement_ledger(entitlement, cascade=True)
    ledger.create_notification(shipment["id"], "WEIGHT_RECON_COMPLETE")
    return ok(serialize(shipment))


@bp.post("/shipments/<shipment_id>/dispute-weight")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR])
def dispute_weight(shipment_id):
    body = get_body()
    req_str(body, "dispute_reason")

    shipment = ledger.get_shipment(shipment_id)
    require_ownership(ledger.member_of_shipment(shipment))

    if shipment["weight_recon_status"] != "ACTUAL_RECORDED":
        raise ApiError(
            "ERR_INVALID_WEIGHT_RECON_STATE", "Only a recorded weight of record may be disputed."
        )
    deadline = shipment["weigh_date"] + timedelta(days=calc.WEIGHT_DISPUTE_WINDOW_DAYS)
    if clock() > deadline:
        raise ApiError(
            "ERR_WEIGHT_DISPUTE_WINDOW_EXPIRED", "The 45-day dispute window has closed."
        )

    shipment["weight_recon_status"] = "DISPUTED"
    shipment["reweigh_required"] = True
    touch(shipment)
    return ok(serialize(shipment))


@bp.post("/shipments/<shipment_id>/reweigh")
@endpoint([ROLE_TSP_COORDINATOR])
def reweigh_shipment(shipment_id):
    body = get_body()
    shipment = ledger.get_shipment(shipment_id)
    actual_gross, actual_tare, weigh_date, scale_certified = _record_certified_weights(
        shipment, body
    )

    if shipment["weight_recon_status"] != "DISPUTED":
        raise ApiError(
            "ERR_INVALID_WEIGHT_RECON_STATE", "Only a disputed shipment may be reweighed."
        )
    if scale_certified is not True:
        raise ApiError("ERR_UNCERTIFIED_SCALE", "The weight of record must come from a certified scale.")

    shipment["actual_gross_lbs"] = actual_gross
    shipment["actual_tare_lbs"] = actual_tare
    shipment["net_actual_lbs"] = actual_gross - actual_tare
    shipment["weigh_date"] = weigh_date
    shipment["weight_recon_status"] = "ACTUAL_RECORDED"
    touch(shipment)
    ledger.recompute_shipment_weight(shipment)

    entitlement = _entitlement_of(shipment)
    if entitlement is not None:
        ledger.recompute_entitlement_ledger(entitlement, cascade=True)
    return ok(serialize(shipment))


@bp.post("/shipments/<shipment_id>/reconcile-weight")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def reconcile_weight(shipment_id):
    body = get_body()
    opt_str(body, "reconcile_note")

    shipment = ledger.get_shipment(shipment_id)

    if shipment["weight_recon_status"] != "ACTUAL_RECORDED":
        raise ApiError(
            "ERR_INVALID_WEIGHT_RECON_STATE",
            "Only a recorded weight of record may be reconciled.",
        )
    if shipment["movement_status"] != "DELIVERED":
        raise ApiError(
            "ERR_INVALID_SHIPMENT_MOVEMENT_STATE",
            "The shipment must be delivered before its weight is frozen.",
        )
    entitlement = _entitlement_of(shipment)
    if entitlement is not None and entitlement["excess_cost_due_usd"] != Decimal("0.00"):
        raise ApiError("ERR_EXCESS_COST_UNPAID", "Excess cost remains outstanding.")

    shipment["weight_recon_status"] = "RECONCILED"
    touch(shipment)
    if entitlement is not None:
        ledger.close_entitlement_if_complete(entitlement)
    return ok(serialize(shipment))


# --------------------------------------------------------- delivery and cancel


@bp.post("/shipments/<shipment_id>/deliver")
@endpoint([ROLE_TSP_COORDINATOR])
def deliver_shipment(shipment_id):
    body = get_body()
    delivery_date = req_dt(body, "delivery_date")

    shipment = ledger.get_shipment(shipment_id)

    if shipment["movement_status"] != "PICKED_UP":
        raise ApiError(
            "ERR_INVALID_SHIPMENT_MOVEMENT_STATE", "Only a picked-up shipment may be delivered."
        )
    if shipment["weight_recon_status"] not in ("ACTUAL_RECORDED", "DISPUTED", "RECONCILED"):
        raise ApiError(
            "ERR_INVALID_WEIGHT_RECON_STATE",
            "Goods cannot be delivered against a bare survey estimate.",
        )
    if delivery_date < shipment["actual_pickup_date"]:
        raise ApiError("ERR_DELIVERY_BEFORE_PICKUP", "Delivery cannot precede pickup.")

    shipment["delivery_date"] = delivery_date
    shipment["movement_status"] = "DELIVERED"
    touch(shipment)
    _sync_member_count(shipment)
    return ok(serialize(shipment))


@bp.post("/shipments/<shipment_id>/cancel")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_PROGRAM_ADMIN])
def cancel_shipment(shipment_id):
    body = get_body()
    cancel_reason = req_str(body, "cancel_reason")

    shipment = ledger.get_shipment(shipment_id)
    require_ownership(ledger.member_of_shipment(shipment))

    if shipment["movement_status"] not in ("AWARDED", "ON_HOLD", "SURVEYED", "PACKED"):
        raise ApiError(
            "ERR_INVALID_SHIPMENT_MOVEMENT_STATE", "The goods are already gone."
        )

    block_id = shipment["capacity_block_id"]
    shipment["cancel_reason"] = cancel_reason
    shipment["movement_status"] = "CANCELLED"
    touch(shipment)

    entitlement = _entitlement_of(shipment)
    if entitlement is not None:
        ledger.recompute_entitlement_ledger(entitlement, cascade=True)
    if block_id is not None:
        block = db.capacity_blocks.get(block_id)
        if block is not None:
            ledger.recompute_capacity_block(block, force_touch=False)
    _sync_member_count(shipment)
    return ok(serialize(shipment))
