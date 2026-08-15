"""Routes: logical clock, servicers, crews, investor allowables, properties."""

from flask import Blueprint, request

from auth import get_auth, require_role, ANY_ROLE
from db import store, new_entity, bump, bump_if_changed, public, iso_clock
from errors import raise_err
from response import ok, ok_list
from services import recompute_is_current, snapshot_allowable_version
from util import (
    get_body, req_str, req_amount, opt_amount, req_enum, opt_bool,
    req_date, opt_str_list, req_datetime, get_or_404, parse_pagination,
    paginate, sort_created, INVESTOR_TYPES, ITEM_CODES, HEATING_SYSTEMS,
)

bp = Blueprint("core", __name__)


# ---- logical clock -----------------------------------------------------------

@bp.post("/preservation/_clock/set_current_utc")
def set_clock():
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    b = get_body()
    dt = req_datetime(b, "to_iso8601")
    store.clock = dt
    return ok({"current_utc": iso_clock(store.clock)})


# ---- Servicer ----------------------------------------------------------------

@bp.post("/preservation/servicers")
def create_servicer():
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    b = get_body()
    name = req_str(b, "name")
    code = req_str(b, "code")
    for s in store.servicers.values():
        if s["code"] == code:
            raise_err("ERR_INVALID_REQUEST", "code must be unique across all servicers")
    svc = new_entity({
        "name": name,
        "code": code,
        "active": True,
        "prior_month_gross_cents": 0,
        "volume_rebate_cents": 0,
    })
    store.servicers[svc["id"]] = svc
    return ok(public(svc), status=201)


@bp.get("/preservation/servicers/<servicerId>")
def get_servicer(servicerId):
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    svc = get_or_404(store.servicers, servicerId, "Servicer")
    return ok(public(svc))


# ---- Crew --------------------------------------------------------------------

@bp.post("/preservation/crews")
def create_crew():
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    b = get_body()
    name = req_str(b, "name")
    crew_code = req_str(b, "crew_code")
    region_state_codes = opt_str_list(b, "region_state_codes", default=[])
    daily_capacity_jobs = b.get("daily_capacity_jobs")
    if daily_capacity_jobs is None:
        daily_capacity_jobs = 8
    elif isinstance(daily_capacity_jobs, bool) or not isinstance(daily_capacity_jobs, int) or daily_capacity_jobs < 0:
        raise_err("ERR_INVALID_REQUEST", "daily_capacity_jobs must be a non-negative integer")
    for c in store.crews.values():
        if c["crew_code"] == crew_code:
            raise_err("ERR_INVALID_REQUEST", "crew_code must be unique across all crews")
    crew = new_entity({
        "name": name,
        "crew_code": crew_code,
        "region_state_codes": region_state_codes,
        "daily_capacity_jobs": daily_capacity_jobs,
    })
    store.crews[crew["id"]] = crew
    return ok(public(crew), status=201)


@bp.get("/preservation/crews/<crewId>")
def get_crew(crewId):
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    crew = get_or_404(store.crews, crewId, "Crew")
    return ok(public(crew))


# ---- InvestorAllowable -------------------------------------------------------

@bp.post("/preservation/investor-allowables")
def create_allowable():
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    b = get_body()
    investor_type = req_enum(b, "investor_type", INVESTOR_TYPES)
    item_code = req_enum(b, "item_code", ITEM_CODES)
    max_per_occurrence_cents = req_amount(b, "max_per_occurrence_cents")
    max_occurrences = req_amount(b, "max_occurrences_per_calendar_year")
    aggregate_cap = req_amount(b, "aggregate_cap_cents_per_property_year")
    requires_bid_over_cents = req_amount(b, "requires_bid_over_cents")
    effective_from = req_date(b, "effective_from")
    for a in store.allowables.values():
        if (
            a["investor_type"] == investor_type
            and a["item_code"] == item_code
            and a["effective_from"] == effective_from
        ):
            raise_err(
                "ERR_INVALID_REQUEST",
                "(investor_type, item_code, effective_from) must be unique",
            )
    row = new_entity({
        "investor_type": investor_type,
        "item_code": item_code,
        "max_per_occurrence_cents": max_per_occurrence_cents,
        "max_occurrences_per_calendar_year": max_occurrences,
        "aggregate_cap_cents_per_property_year": aggregate_cap,
        "requires_bid_over_cents": requires_bid_over_cents,
        "effective_from": effective_from,
        "is_current": False,
    })
    store.allowables[row["id"]] = row
    snapshot_allowable_version(row)
    recompute_is_current(investor_type, item_code, skip_bump_id=row["id"])
    return ok(public(row), status=201)


@bp.get("/preservation/investor-allowables/<allowableId>")
def get_allowable(allowableId):
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    row = get_or_404(store.allowables, allowableId, "InvestorAllowable")
    return ok(public(row))


@bp.patch("/preservation/investor-allowables/<allowableId>")
def patch_allowable(allowableId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    row = get_or_404(store.allowables, allowableId, "InvestorAllowable")
    b = get_body()
    changes = {}
    for field in (
        "max_per_occurrence_cents",
        "max_occurrences_per_calendar_year",
        "aggregate_cap_cents_per_property_year",
        "requires_bid_over_cents",
    ):
        v = opt_amount(b, field)
        if v is not None:
            changes[field] = v
    for k, v in changes.items():
        row[k] = v
    bump(row)
    snapshot_allowable_version(row)
    return ok(public(row))


# ---- Property ----------------------------------------------------------------

@bp.post("/preservation/properties")
def create_property():
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin", "Servicer"])
    b = get_body()
    servicer_id = b.get("servicer_id")
    if servicer_id is not None:
        if not isinstance(servicer_id, str):
            raise_err("ERR_INVALID_REQUEST", "servicer_id must be a string")
        svc = store.servicers.get(servicer_id)
        if svc is None:
            raise_err("ERR_NOT_FOUND", f"Servicer not found: {servicer_id}")
    if role == "Servicer":
        if servicer_id is None:
            raise_err("ERR_INVALID_REQUEST", "Missing required field: servicer_id")
        if servicer_id != user_id:
            raise_err("ERR_FORBIDDEN_FOR_ROLE", "Servicer may create properties only under its own servicer_id")
    if servicer_id is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: servicer_id")

    address_line1 = req_str(b, "address_line1")
    municipality_code = req_str(b, "municipality_code")
    state_code = req_str(b, "state_code")
    zip_code = req_str(b, "zip")
    investor_type = req_enum(b, "investor_type", INVESTOR_TYPES)
    lot_size_sqft = req_amount(b, "lot_size_sqft")
    heating_system = req_enum(b, "heating_system", HEATING_SYSTEMS)
    fixture_count = req_amount(b, "fixture_count")
    has_pool = opt_bool(b, "has_pool", default=False)

    prop = new_entity({
        "servicer_id": servicer_id,
        "address_line1": address_line1,
        "municipality_code": municipality_code,
        "state_code": state_code,
        "zip": zip_code,
        "investor_type": investor_type,
        "lot_size_sqft": lot_size_sqft,
        "heating_system": heating_system,
        "has_pool": has_pool,
        "fixture_count": fixture_count,
        "status": "ACTIVE",
        "occupancy_status": "UNKNOWN",
        "condition_score": 100,
        "compliance_posture": "CLEAR",
        "ytd_investor_approved_cents": 0,
        "ytd_calendar_year": store.clock.year,
        "financial_review_required": False,
    })
    store.properties[prop["id"]] = prop
    return ok(public(prop), status=201)


@bp.get("/preservation/properties/<propertyId>")
def get_property(propertyId):
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    prop = get_or_404(store.properties, propertyId, "Property")
    return ok(public(prop))


@bp.get("/preservation/properties")
def list_properties():
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(store.properties.values())
    f_servicer = request.args.get("servicer_id")
    f_status = request.args.get("status")
    f_posture = request.args.get("compliance_posture")
    if f_servicer is not None:
        items = [p for p in items if p["servicer_id"] == f_servicer]
    if f_status is not None:
        items = [p for p in items if p["status"] == f_status]
    if f_posture is not None:
        items = [p for p in items if p["compliance_posture"] == f_posture]
    items = sort_created(items)
    page, total = paginate(items, public, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.post("/preservation/properties/<propertyId>/convey")
def convey_property(propertyId):
    user_id, role = get_auth()
    require_role(role, ["Servicer"])
    prop = get_or_404(store.properties, propertyId, "Property")
    if prop["servicer_id"] != user_id:
        raise_err("ERR_FORBIDDEN_FOR_ROLE", "Servicer may convey only its own properties")
    if prop["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Property is not ACTIVE")
    for wo in store.work_orders.values():
        if wo["property_id"] == prop["id"] and wo["status"] in ("ISSUED", "ASSIGNED", "IN_PROGRESS", "SUBMITTED"):
            raise_err("ERR_OPEN_WORK_ORDERS", "Property has work orders in an open status")
    # Cascade: end every ACTIVE/SUSPENDED recurring plan silently (no compensation).
    for plan in store.plans.values():
        if plan["property_id"] == prop["id"] and plan["status"] in ("ACTIVE", "SUSPENDED"):
            plan["status"] = "ENDED"
            bump(plan)
    prop["status"] = "CONVEYED"
    bump(prop)
    return ok(public(prop))


@bp.post("/preservation/properties/<propertyId>/clear-financial-review")
def clear_financial_review(propertyId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    prop = get_or_404(store.properties, propertyId, "Property")
    bump_if_changed(prop, {"financial_review_required": False})
    return ok(public(prop))
