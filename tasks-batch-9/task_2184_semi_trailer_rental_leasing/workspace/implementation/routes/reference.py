"""Clock, branches, trailer types and trailers."""

from flask import Blueprint

import auth
import calc
import envelope
import serializers
import services
import store
import validate
from auth import ALL_ROLES, authenticate
from errors import fail

bp = Blueprint("reference", __name__)

REGIONS = ("WEST", "CENTRAL", "EAST")
TYPE_CODES = ("DRY_VAN_53", "REEFER_53", "FLATBED_48", "CHASSIS_40")
AVAILABILITY = ("AVAILABLE", "ALLOCATED", "ON_RENT", "ON_LEASE", "IN_TRANSIT", "RETIRED", "SOLD")
SERVICE = ("SERVICEABLE", "PM_DUE", "OOS_DAMAGE", "OOS_DOT_EXPIRED")
PRODUCTS = ("SHORT_TERM_RENTAL", "FULL_SERVICE_LEASE")


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------
@bp.post("/fleet/_clock/set_current_utc")
def set_clock():
    authenticate(["FleetAdmin"])
    payload = validate.body()
    raw = validate.req_string(payload, "to_iso8601")
    parsed = store.parse_datetime(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant")
    store.set_clock(parsed)
    return envelope.ok({"current_utc": store.iso_ts()})


# ---------------------------------------------------------------------------
# branches
# ---------------------------------------------------------------------------
@bp.post("/fleet/branches")
def create_branch():
    authenticate(["FleetAdmin"])
    payload = validate.body()
    code = validate.req_string(payload, "code", 1, 16)
    name = validate.req_string(payload, "name")
    region = validate.req_enum(payload, "region", REGIONS)
    capacity = validate.req_int(payload, "yard_capacity", minimum=1)
    peak_start = validate.req_date(payload, "peak_season_start_date")
    peak_end = validate.req_date(payload, "peak_season_end_date")
    reserve = validate.opt_number(payload, "lease_reserve_pct", 0.00, 0.00, 1.00)

    if peak_end < peak_start:
        fail("ERR_INVALID_DATE_RANGE", "peak_season_end_date must be on or after peak_season_start_date")
    for existing in store.branches.values():
        if existing["code"] == code:
            fail("ERR_DUPLICATE_BRANCH_CODE", "Branch code %s already exists" % code)

    rec = store.new_record()
    rec.update({
        "code": code,
        "name": name,
        "region": region,
        "yard_capacity": capacity,
        "peak_season_start_date": peak_start.isoformat(),
        "peak_season_end_date": peak_end.isoformat(),
        "lease_reserve_pct": reserve,
    })
    store.branches[rec["id"]] = rec
    return envelope.created(serializers.branch(rec))


@bp.get("/fleet/branches/<branch_id>")
def read_branch(branch_id):
    authenticate(ALL_ROLES)
    rec = services.get_branch(branch_id)
    return envelope.ok(serializers.branch(rec))


@bp.get("/fleet/branches")
def list_branches():
    authenticate(ALL_ROLES)
    limit, offset = validate.pagination()
    region = validate.query_enum("region", REGIONS)
    rows = [b for b in store.branches.values() if region is None or b["region"] == region]
    rows = store.sorted_rows(rows)
    page = validate.paginate(rows, limit, offset)
    return envelope.listing([serializers.branch(r) for r in page], limit, offset, len(rows))


@bp.get("/fleet/branches/<branch_id>/availability")
def branch_availability(branch_id):
    authenticate(["FleetAdmin", "BranchManager"])
    branch = services.get_branch(branch_id)
    trailer_type_id = validate.query("trailer_type_id")
    product = validate.query_enum("product", PRODUCTS)
    window_start = validate.query_date("window_start_date")
    window_end = validate.query_date("window_end_date")

    peak_start = store.parse_date(branch["peak_season_start_date"])
    peak_end = store.parse_date(branch["peak_season_end_date"])
    if window_start is None and window_end is None:
        intersects = True
    else:
        start = window_start or peak_start
        end = window_end or peak_end
        intersects = start <= peak_end and peak_start < end

    on_hand = calc.branch_on_hand_count(branch_id)
    serviceable = calc.branch_serviceable_available_count(branch_id, trailer_type_id)
    if product == "SHORT_TERM_RENTAL" and intersects:
        reserved = calc.ceil_dec(calc.dec(serviceable) * calc.dec(branch.get("lease_reserve_pct") or 0))
    else:
        reserved = 0
    inbound = len([o for o in store.relocation_orders.values()
                   if o["destination_branch_id"] == branch_id and o["status"] in ("APPROVED", "IN_TRANSIT")])
    return envelope.ok({
        "branch_id": branch_id,
        "trailer_type_id": trailer_type_id,
        "on_hand_count": on_hand,
        "serviceable_available_count": serviceable,
        "lease_reserved_count": reserved,
        "rental_available_count": serviceable - reserved,
        "inbound_committed_count": inbound,
    })


# ---------------------------------------------------------------------------
# trailer types
# ---------------------------------------------------------------------------
@bp.post("/fleet/trailer-types")
def create_trailer_type():
    authenticate(["FleetAdmin"])
    payload = validate.body()
    code = validate.req_enum(payload, "code", TYPE_CODES)
    description = validate.req_string(payload, "description")
    base_daily = validate.req_int(payload, "base_daily_rate_cents", minimum=0)
    base_monthly = validate.req_int(payload, "base_monthly_rate_cents", minimum=0)
    residual = validate.req_int(payload, "residual_floor_cents", minimum=0)
    required_limit = validate.req_int(payload, "required_physical_damage_limit_cents", minimum=0)
    dot_interval = validate.opt_int(payload, "dot_inspection_interval_days", 365, minimum=1)
    pm_interval = validate.opt_int(payload, "pm_interval_miles", 30000, minimum=1)

    for existing in store.trailer_types.values():
        if existing["code"] == code:
            fail("ERR_DUPLICATE_TRAILER_TYPE_CODE", "Trailer type code %s already exists" % code)

    rec = store.new_record()
    rec.update({
        "code": code,
        "description": description,
        "base_daily_rate_cents": base_daily,
        "base_monthly_rate_cents": base_monthly,
        "residual_floor_cents": residual,
        "dot_inspection_interval_days": dot_interval,
        "pm_interval_miles": pm_interval,
        "required_physical_damage_limit_cents": required_limit,
    })
    store.trailer_types[rec["id"]] = rec
    return envelope.created(serializers.trailer_type(rec))


@bp.get("/fleet/trailer-types/<trailer_type_id>")
def read_trailer_type(trailer_type_id):
    authenticate(ALL_ROLES)
    return envelope.ok(serializers.trailer_type(services.get_trailer_type(trailer_type_id)))


@bp.get("/fleet/trailer-types")
def list_trailer_types():
    authenticate(ALL_ROLES)
    limit, offset = validate.pagination()
    code = validate.query_enum("code", TYPE_CODES)
    rows = [t for t in store.trailer_types.values() if code is None or t["code"] == code]
    rows = store.sorted_rows(rows)
    page = validate.paginate(rows, limit, offset)
    return envelope.listing([serializers.trailer_type(r) for r in page], limit, offset, len(rows))


# ---------------------------------------------------------------------------
# trailers
# ---------------------------------------------------------------------------
@bp.post("/fleet/trailers")
def create_trailer():
    authenticate(["FleetAdmin"])
    payload = validate.body()
    if validate.present(payload, "trailer_type_id") and isinstance(payload["trailer_type_id"], str):
        ttype = services.get_trailer_type(payload["trailer_type_id"])
    else:
        ttype = None
    if validate.present(payload, "home_branch_id") and isinstance(payload["home_branch_id"], str):
        services.get_branch(payload["home_branch_id"])

    unit_number = validate.req_string(payload, "unit_number")
    type_id = validate.req_string(payload, "trailer_type_id")
    home_branch_id = validate.req_string(payload, "home_branch_id")
    cost = validate.req_int(payload, "acquisition_cost_cents", minimum=0)
    in_service = validate.req_date(payload, "in_service_date")
    last_dot = validate.req_date(payload, "last_dot_inspection_date")
    hub_miles = validate.opt_int(payload, "hub_miles", 0, minimum=0)

    for existing in store.trailers.values():
        if existing["unit_number"] == unit_number:
            fail("ERR_DUPLICATE_UNIT_NUMBER", "Unit number %s already exists" % unit_number)

    rec = store.new_record()
    rec.update({
        "unit_number": unit_number,
        "trailer_type_id": type_id,
        "home_branch_id": home_branch_id,
        "current_branch_id": home_branch_id,
        "availability_status": "AVAILABLE",
        "hub_miles": hub_miles,
        "last_pm_hub_miles": hub_miles,
        "last_dot_inspection_date": last_dot.isoformat(),
        "dot_expires_on": calc.compute_dot_expires_on(last_dot.isoformat(), ttype),
        "last_dot_passed": True,
        "last_damage_repair_at": None,
        "_last_damage_repair_seq": None,
        "acquisition_cost_cents": cost,
        "in_service_date": in_service.isoformat(),
        "retired_reason": None,
    })
    store.trailers[rec["id"]] = rec
    return envelope.created(serializers.trailer(rec))


@bp.get("/fleet/trailers/<trailer_id>")
def read_trailer(trailer_id):
    authenticate(ALL_ROLES)
    return envelope.ok(serializers.trailer(services.get_trailer(trailer_id)))


@bp.get("/fleet/trailers")
def list_trailers():
    authenticate(ALL_ROLES)
    limit, offset = validate.pagination()
    type_id = validate.query("trailer_type_id")
    home_branch_id = validate.query("home_branch_id")
    current_branch_id = validate.query("current_branch_id")
    availability = validate.query_enum("availability_status", AVAILABILITY)
    service = validate.query_enum("service_status", SERVICE)

    rows = []
    for t in store.trailers.values():
        if type_id is not None and t["trailer_type_id"] != type_id:
            continue
        if home_branch_id is not None and t["home_branch_id"] != home_branch_id:
            continue
        if current_branch_id is not None and t["current_branch_id"] != current_branch_id:
            continue
        if availability is not None and t["availability_status"] != availability:
            continue
        if service is not None and calc.trailer_service_status(t) != service:
            continue
        rows.append(t)
    rows = store.sorted_rows(rows)
    page = validate.paginate(rows, limit, offset)
    return envelope.listing([serializers.trailer(r) for r in page], limit, offset, len(rows))


@bp.post("/fleet/trailers/<trailer_id>/retire")
def retire_trailer(trailer_id):
    authenticate(["FleetAdmin"])
    trailer = services.get_trailer(trailer_id)
    payload = validate.body()
    reason = validate.req_string(payload, "reason")

    if trailer["availability_status"] != "AVAILABLE":
        fail("ERR_TRAILER_NOT_AVAILABLE", "Trailer is not idle")

    trailer["availability_status"] = "RETIRED"
    trailer["retired_reason"] = reason
    store.touch(trailer)
    return envelope.ok(serializers.trailer(trailer))
