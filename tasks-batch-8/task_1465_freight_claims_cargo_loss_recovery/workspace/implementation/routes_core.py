"""Routes: logical clock, carriers, lanes, carrier-lane assignments, shipments."""

from flask import Blueprint, g, request

from db import STORE, iso, new_id, next_seq, now, now_iso, parse_dt, set_now
from errors import (
    ApiError,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_CARRIER_INVALID_STATE,
    ERR_CARRIER_NOT_FOUND,
    ERR_DUPLICATE_KEY,
    ERR_INVALID_REQUEST,
    ERR_INVALID_TEMPORAL_RANGE,
    ERR_LANE_INVALID_STATE,
    ERR_LANE_NOT_FOUND,
    ERR_OPEN_EXPOSURE_EXISTS,
)
from middleware import as_enum, as_int, as_str, opt_int, req_field, request_body, require_roles
from response import paginate, success_object
from serializers import ser_assignment, ser_carrier, ser_lane, ser_shipment
from services import (
    TERMINAL_CLAIM_STATES,
    bump_lane_counters,
    run_scheduled_sweeps,
    touch,
)

bp = Blueprint("core", __name__)

LIABILITY_MODELS = {"FULL_VALUE", "RELEASED_RATE", "PER_PACKAGE", "PER_POUND"}
COMMODITY_CLASSES = {"GENERAL", "FRAGILE", "PERISHABLE", "HIGH_VALUE", "HAZMAT"}


# ---------------------------------------------------------------------------
# Test-driving logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_clock():
    body = request_body()
    target = parse_dt(req_field(body, "to_iso8601"), "to_iso8601")
    set_now(target)
    run_scheduled_sweeps()
    return success_object({"now_iso8601": now_iso()})


# ---------------------------------------------------------------------------
# Carriers
# ---------------------------------------------------------------------------

def get_carrier_or_404(carrier_id):
    carrier = STORE["carriers"].get(carrier_id)
    if carrier is None:
        raise ApiError(ERR_CARRIER_NOT_FOUND, f"Carrier '{carrier_id}' not found", 404)
    return carrier


@bp.post("/freight-claims/carriers")
@require_roles("ClaimsManager")
def create_carrier():
    body = request_body()
    scac_code = as_str(req_field(body, "scac_code"), "scac_code")
    legal_name = as_str(req_field(body, "legal_name"), "legal_name")
    liability_model = as_enum(req_field(body, "liability_model"), "liability_model", LIABILITY_MODELS)
    released_rate = opt_int(body, "released_rate_cents_per_lb")
    per_package_cap = opt_int(body, "per_package_cap_cents")
    per_pound_cap = opt_int(body, "per_pound_cap_cents")
    max_auto_settle = as_int(req_field(body, "max_auto_settle_cents"), "max_auto_settle_cents")
    ack_days = opt_int(body, "carmack_acknowledgment_days")
    filing_days = opt_int(body, "carmack_filing_days")
    if ack_days is None:
        ack_days = 30
    if filing_days is None:
        filing_days = 270
    if ack_days <= 0 or filing_days < 270 or max_auto_settle < 0:
        raise ApiError(ERR_INVALID_REQUEST,
                       "carmack_acknowledgment_days must be > 0, carmack_filing_days >= 270,"
                       " max_auto_settle_cents >= 0", 400)
    for name, val in (("released_rate_cents_per_lb", released_rate),
                      ("per_package_cap_cents", per_package_cap),
                      ("per_pound_cap_cents", per_pound_cap)):
        if val is not None and val < 0:
            raise ApiError(ERR_INVALID_REQUEST, f"Field '{name}' must be >= 0", 400)
    if any(c["scac_code"] == scac_code for c in STORE["carriers"].values()):
        raise ApiError(ERR_DUPLICATE_KEY, f"Carrier with scac_code '{scac_code}' already exists", 409)
    stamp = iso(now())
    carrier = {
        "id": new_id(),
        "scac_code": scac_code,
        "legal_name": legal_name,
        "liability_model": liability_model,
        "released_rate_cents_per_lb": released_rate,
        "per_package_cap_cents": per_package_cap,
        "per_pound_cap_cents": per_pound_cap,
        "max_auto_settle_cents": max_auto_settle,
        "carmack_acknowledgment_days": ack_days,
        "carmack_filing_days": filing_days,
        "claims_filed_count": 0,
        "claims_paid_count": 0,
        "claim_ratio_bp": 0,
        "status": "ACTIVE",
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }
    STORE["carriers"][carrier["id"]] = carrier
    return success_object(ser_carrier(carrier), status=201)


@bp.get("/freight-claims/carriers")
@require_roles("Any")
def list_carriers():
    records = list(STORE["carriers"].values())
    status = request.args.get("status")
    if status is not None:
        records = [c for c in records if c["status"] == status]
    return paginate(records, ser_carrier)


@bp.get("/freight-claims/carriers/<carrier_id>")
@require_roles("Any")
def get_carrier(carrier_id):
    return success_object(ser_carrier(get_carrier_or_404(carrier_id)))


@bp.post("/freight-claims/carriers/<carrier_id>/suspend")
@require_roles("ClaimsManager")
def suspend_carrier(carrier_id):
    carrier = get_carrier_or_404(carrier_id)
    if carrier["status"] != "ACTIVE":
        raise ApiError(ERR_CARRIER_INVALID_STATE,
                       "Carrier must be ACTIVE to suspend", 409)
    for claim in STORE["claims"].values():
        if (claim["carrier_id"] == carrier_id
                and claim["filing_status"] not in TERMINAL_CLAIM_STATES
                and claim["reserve_amount_cents"] > 0):
            raise ApiError(ERR_OPEN_EXPOSURE_EXISTS,
                           "Carrier has non-terminal claims with open reserves", 409)
    carrier["status"] = "SUSPENDED"
    touch(carrier)
    return success_object(ser_carrier(carrier))


@bp.post("/freight-claims/carriers/<carrier_id>/reinstate")
@require_roles("ClaimsManager")
def reinstate_carrier(carrier_id):
    carrier = get_carrier_or_404(carrier_id)
    if carrier["status"] != "SUSPENDED":
        raise ApiError(ERR_CARRIER_INVALID_STATE,
                       "Carrier must be SUSPENDED to reinstate", 409)
    carrier["status"] = "ACTIVE"
    touch(carrier)
    return success_object(ser_carrier(carrier))


@bp.post("/freight-claims/carriers/<carrier_id>/terminate")
@require_roles("FinanceController")
def terminate_carrier(carrier_id):
    carrier = get_carrier_or_404(carrier_id)
    if carrier["status"] != "SUSPENDED":
        raise ApiError(ERR_CARRIER_INVALID_STATE,
                       "Carrier must be SUSPENDED to terminate", 409)
    for claim in STORE["claims"].values():
        if (claim["carrier_id"] == carrier_id
                and claim["filing_status"] not in TERMINAL_CLAIM_STATES):
            raise ApiError(ERR_OPEN_EXPOSURE_EXISTS,
                           "Carrier has claims in non-terminal states", 409)
    carrier["status"] = "TERMINATED"
    touch(carrier)
    return success_object(ser_carrier(carrier))


# ---------------------------------------------------------------------------
# Lanes
# ---------------------------------------------------------------------------

def get_lane_or_404(lane_id):
    lane = STORE["lanes"].get(lane_id)
    if lane is None:
        raise ApiError(ERR_LANE_NOT_FOUND, f"Lane '{lane_id}' not found", 404)
    return lane


@bp.post("/freight-claims/lanes")
@require_roles("ClaimsManager")
def create_lane():
    body = request_body()
    origin_zip3 = as_str(req_field(body, "origin_zip3"), "origin_zip3")
    destination_zip3 = as_str(req_field(body, "destination_zip3"), "destination_zip3")
    baseline = as_int(req_field(body, "baseline_claim_ratio_bp"), "baseline_claim_ratio_bp")
    if baseline < 0:
        raise ApiError(ERR_INVALID_REQUEST, "baseline_claim_ratio_bp must be >= 0", 400)
    stamp = iso(now())
    lane = {
        "id": new_id(),
        "origin_zip3": origin_zip3,
        "destination_zip3": destination_zip3,
        "baseline_claim_ratio_bp": baseline,
        "shipments_count": 0,
        "claims_count": 0,
        "lane_claim_ratio_bp": 0,
        "status": "ACTIVE",
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }
    STORE["lanes"][lane["id"]] = lane
    return success_object(ser_lane(lane), status=201)


@bp.get("/freight-claims/lanes")
@require_roles("Any")
def list_lanes():
    records = list(STORE["lanes"].values())
    status = request.args.get("status")
    if status is not None:
        records = [l for l in records if l["status"] == status]
    return paginate(records, ser_lane)


@bp.get("/freight-claims/lanes/<lane_id>")
@require_roles("Any")
def get_lane(lane_id):
    return success_object(ser_lane(get_lane_or_404(lane_id)))


@bp.post("/freight-claims/lanes/<lane_id>/retire")
@require_roles("ClaimsManager")
def retire_lane(lane_id):
    lane = get_lane_or_404(lane_id)
    if lane["status"] != "ACTIVE":
        raise ApiError(ERR_LANE_INVALID_STATE, "Lane must be ACTIVE to retire", 409)
    for shipment in STORE["shipments"].values():
        if shipment["lane_id"] == lane_id and shipment["status"] == "CLAIMED":
            raise ApiError(ERR_OPEN_EXPOSURE_EXISTS,
                           "Lane has shipments in CLAIMED status", 409)
    lane["status"] = "RETIRED"
    touch(lane)
    return success_object(ser_lane(lane))


# ---------------------------------------------------------------------------
# Carrier-lane assignments
# ---------------------------------------------------------------------------

def get_assignment_or_404(assignment_id):
    assignment = STORE["assignments"].get(assignment_id)
    if assignment is None:
        raise ApiError(ERR_ASSIGNMENT_NOT_FOUND,
                       f"Carrier-lane assignment '{assignment_id}' not found", 404)
    return assignment


@bp.post("/freight-claims/carrier-lane-assignments")
@require_roles("ClaimsManager")
def create_assignment():
    body = request_body()
    carrier_id = as_str(req_field(body, "carrier_id"), "carrier_id")
    lane_id = as_str(req_field(body, "lane_id"), "lane_id")
    discount = as_int(req_field(body, "contracted_discount_pct"), "contracted_discount_pct")
    effective_from = req_field(body, "effective_from")
    effective_to = req_field(body, "effective_to")
    if not 0 <= discount <= 100:
        raise ApiError(ERR_INVALID_REQUEST, "contracted_discount_pct must be between 0 and 100", 400)
    from_dt = parse_dt(effective_from, "effective_from")
    to_dt = parse_dt(effective_to, "effective_to")
    if to_dt <= from_dt:
        raise ApiError(ERR_INVALID_TEMPORAL_RANGE,
                       "effective_to must be later than effective_from", 400)
    get_carrier_or_404(carrier_id)
    get_lane_or_404(lane_id)
    for existing in STORE["assignments"].values():
        if (existing["carrier_id"] == carrier_id
                and existing["lane_id"] == lane_id
                and existing["effective_from"] == effective_from):
            raise ApiError(ERR_DUPLICATE_KEY,
                           "Assignment with this carrier_id, lane_id and effective_from exists", 409)
    assignment = {
        "id": new_id(),
        "carrier_id": carrier_id,
        "lane_id": lane_id,
        "contracted_discount_pct": discount,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "created_at": iso(now()),
        "_effective_from_dt": from_dt,
        "_effective_to_dt": to_dt,
        "_seq": next_seq(),
    }
    STORE["assignments"][assignment["id"]] = assignment
    return success_object(ser_assignment(assignment), status=201)


@bp.get("/freight-claims/carrier-lane-assignments")
@require_roles("Any")
def list_assignments():
    records = list(STORE["assignments"].values())
    carrier_id = request.args.get("carrier_id")
    lane_id = request.args.get("lane_id")
    if carrier_id is not None:
        records = [a for a in records if a["carrier_id"] == carrier_id]
    if lane_id is not None:
        records = [a for a in records if a["lane_id"] == lane_id]
    return paginate(records, ser_assignment)


@bp.get("/freight-claims/carrier-lane-assignments/<assignment_id>")
@require_roles("Any")
def get_assignment(assignment_id):
    return success_object(ser_assignment(get_assignment_or_404(assignment_id)))


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------

def get_shipment_or_404(shipment_id):
    shipment = STORE["shipments"].get(shipment_id)
    if shipment is None:
        raise ApiError(ERR_SHIPMENT_NOT_FOUND, f"Shipment '{shipment_id}' not found", 404)
    return shipment


@bp.post("/freight-claims/shipments")
@require_roles("ClaimsClerk")
def create_shipment():
    body = request_body()
    bol_number = as_str(req_field(body, "bol_number"), "bol_number")
    carrier_id = as_str(req_field(body, "carrier_id"), "carrier_id")
    lane_id = as_str(req_field(body, "lane_id"), "lane_id")
    ship_date = req_field(body, "ship_date")
    delivery_date = req_field(body, "delivery_date")
    declared_value = as_int(req_field(body, "declared_value_cents"), "declared_value_cents")
    total_weight = as_int(req_field(body, "total_weight_lbs"), "total_weight_lbs")
    package_count = as_int(req_field(body, "package_count"), "package_count")
    commodity_class = as_enum(req_field(body, "commodity_class"), "commodity_class", COMMODITY_CLASSES)
    is_concealed = body.get("is_concealed_damage", False)
    if not isinstance(is_concealed, bool):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'is_concealed_damage' must be a boolean", 400)
    if declared_value < 0 or total_weight <= 0 or package_count <= 0:
        raise ApiError(ERR_INVALID_REQUEST,
                       "declared_value_cents must be >= 0; total_weight_lbs and package_count > 0", 400)
    ship_dt = parse_dt(ship_date, "ship_date")
    delivery_dt = parse_dt(delivery_date, "delivery_date")
    if delivery_dt < ship_dt:
        raise ApiError(ERR_INVALID_TEMPORAL_RANGE,
                       "delivery_date must not be earlier than ship_date", 400)
    get_carrier_or_404(carrier_id)
    get_lane_or_404(lane_id)
    if any(s["bol_number"] == bol_number for s in STORE["shipments"].values()):
        raise ApiError(ERR_DUPLICATE_KEY, f"Shipment with bol_number '{bol_number}' exists", 409)
    stamp = iso(now())
    shipment = {
        "id": new_id(),
        "bol_number": bol_number,
        "carrier_id": carrier_id,
        "lane_id": lane_id,
        "ship_date": ship_date,
        "delivery_date": delivery_date,
        "declared_value_cents": declared_value,
        "total_weight_lbs": total_weight,
        "package_count": package_count,
        "commodity_class": commodity_class,
        "is_concealed_damage": is_concealed,
        "status": "DELIVERED",
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_ship_date_dt": ship_dt,
        "_delivery_date_dt": delivery_dt,
        "_seq": next_seq(),
    }
    STORE["shipments"][shipment["id"]] = shipment
    lane = STORE["lanes"][lane_id]
    bump_lane_counters(lane, shipments_delta=1)
    return success_object(ser_shipment(shipment), status=201)


@bp.get("/freight-claims/shipments")
@require_roles("Any")
def list_shipments():
    records = list(STORE["shipments"].values())
    carrier_id = request.args.get("carrier_id")
    lane_id = request.args.get("lane_id")
    status = request.args.get("status")
    if carrier_id is not None:
        records = [s for s in records if s["carrier_id"] == carrier_id]
    if lane_id is not None:
        records = [s for s in records if s["lane_id"] == lane_id]
    if status is not None:
        records = [s for s in records if s["status"] == status]
    return paginate(records, ser_shipment)


@bp.get("/freight-claims/shipments/<shipment_id>")
@require_roles("Any")
def get_shipment(shipment_id):
    return success_object(ser_shipment(get_shipment_or_404(shipment_id)))
