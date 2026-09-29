"""Reference registries: agencies, appraisers, bidders and designated funds
(PRD 3.1), plus the logical clock endpoint (PRD 2.5).
"""

from flask import Blueprint

import clockmod
import db
import listing
import lookup
import response
import shape
from errors import fail
from middleware import (AGENCY_REP, ALL_ROLES, APPRAISER, BIDDER, CLERK, FINANCE,
                        MONITOR, RPO, SYSADMIN, authorize)
from services import calc, derive

bp = Blueprint("registries", __name__)

AGENCY_TYPES = ("STATE", "COUNTY", "MUNICIPAL", "SCHOOL_DISTRICT", "TRANSIT",
                "HOUSING_AUTHORITY", "FEDERAL")
PREFERENCE_CATEGORIES = ("AFFORDABLE_HOUSING", "PARK_OPEN_SPACE", "SCHOOL_SITE",
                         "INFILL_INFRASTRUCTURE", "NONE")
REGISTRY_STATUSES = ("REGISTERED", "LAPSED")
ENTITY_TYPES = ("INDIVIDUAL", "CORPORATION", "NONPROFIT", "PARTNERSHIP")
DEBARMENT_STATUSES = ("CLEAR", "DEBARRED")
LICENSE_STATUSES = ("ACTIVE", "EXPIRED")


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@authorize(*ALL_ROLES)
def set_clock():
    payload = shape.body()
    instant, _raw = shape.req_instant(payload, "current_utc")
    clockmod.set_now(instant)
    return response.empty_response()


# --------------------------------------------------------------------------
# Agencies
# --------------------------------------------------------------------------

@bp.post("/agencies")
@authorize(SYSADMIN)
def create_agency():
    payload = shape.body()
    name = shape.req_str(payload, "name", 1, 200)
    agency_type = shape.req_enum(payload, "agency_type", AGENCY_TYPES)
    contact_email = shape.req_str(payload, "contact_email", 1)
    is_preference_entity = shape.opt_bool(payload, "is_preference_entity", False)
    preference_category = shape.opt_enum(payload, "preference_category",
                                        PREFERENCE_CATEGORIES, "NONE")
    row = db.insert("agencies", {
        "name": name,
        "agency_type": agency_type,
        "contact_email": contact_email,
        "is_preference_entity": is_preference_entity,
        "preference_category": preference_category,
        "notice_registry_status": "REGISTERED",
    })
    return response.object_response(derive.agency_out(row), 201)


@bp.get("/agencies/<row_id>")
@authorize(RPO, CLERK, MONITOR, FINANCE, AGENCY_REP, SYSADMIN)
def get_agency(row_id):
    row = lookup.must("agencies", row_id)
    return response.object_response(derive.agency_out(row))


@bp.get("/agencies")
@authorize(RPO, CLERK, MONITOR, FINANCE, AGENCY_REP, SYSADMIN)
def list_agencies():
    limit, offset = listing.bounds()
    agency_type = shape.query_enum("agency_type", AGENCY_TYPES)
    is_preference_entity = shape.query_bool("is_preference_entity")
    preference_category = shape.query_enum("preference_category", PREFERENCE_CATEGORIES)
    registry_status = shape.query_enum("notice_registry_status", REGISTRY_STATUSES)
    rows = db.all_rows("agencies")
    if agency_type is not None:
        rows = [r for r in rows if r["agency_type"] == agency_type]
    if is_preference_entity is not None:
        rows = [r for r in rows if r["is_preference_entity"] == is_preference_entity]
    if preference_category is not None:
        rows = [r for r in rows if r["preference_category"] == preference_category]
    if registry_status is not None:
        rows = [r for r in rows if r["notice_registry_status"] == registry_status]
    return listing.respond(rows, derive.agency_out, limit, offset, listing.by_created_at)


@bp.patch("/agencies/<row_id>")
@authorize(SYSADMIN)
def patch_agency(row_id):
    payload = shape.body()
    registry_status = shape.opt_enum(payload, "notice_registry_status", REGISTRY_STATUSES)
    contact_email = shape.opt_str(payload, "contact_email", 1)
    row = lookup.must("agencies", row_id)
    if registry_status is not None:
        row["notice_registry_status"] = registry_status
    if contact_email is not None:
        row["contact_email"] = contact_email
    db.touch(row)
    return response.object_response(derive.agency_out(row))


# --------------------------------------------------------------------------
# Appraisers
# --------------------------------------------------------------------------

@bp.post("/appraisers")
@authorize(SYSADMIN)
def create_appraiser():
    payload = shape.body()
    name = shape.req_str(payload, "name", 1)
    license_number = shape.req_str(payload, "license_number", 1)
    expires_on, expires_raw = shape.req_instant(payload, "license_expires_on")
    if any(a["license_number"] == license_number for a in db.all_rows("appraisers")):
        fail("ERR_DUPLICATE_KEY", "license_number %s is already registered." % license_number)
    row = db.insert("appraisers", {
        "name": name,
        "license_number": license_number,
        "license_expires_on": expires_on,
    })
    db.set_raw(row, "license_expires_on", expires_raw)
    return response.object_response(derive.appraiser_out(row), 201)


@bp.get("/appraisers/<row_id>")
@authorize(RPO, CLERK, MONITOR, APPRAISER, SYSADMIN)
def get_appraiser(row_id):
    row = lookup.must("appraisers", row_id)
    return response.object_response(derive.appraiser_out(row))


@bp.get("/appraisers")
@authorize(RPO, CLERK, MONITOR, APPRAISER, SYSADMIN)
def list_appraisers():
    limit, offset = listing.bounds()
    license_status = shape.query_enum("license_status", LICENSE_STATUSES)
    rows = db.all_rows("appraisers")
    if license_status is not None:
        rows = [r for r in rows if derive.license_status(r) == license_status]
    return listing.respond(rows, derive.appraiser_out, limit, offset, listing.by_created_at)


# --------------------------------------------------------------------------
# Bidders
# --------------------------------------------------------------------------

@bp.post("/bidders")
@authorize(SYSADMIN)
def create_bidder():
    payload = shape.body()
    legal_name = shape.req_str(payload, "legal_name", 1)
    entity_type = shape.req_enum(payload, "entity_type", ENTITY_TYPES)
    contact_email = shape.req_str(payload, "contact_email", 1)
    row = db.insert("bidders", {
        "legal_name": legal_name,
        "entity_type": entity_type,
        "contact_email": contact_email,
        "debarment_status": "CLEAR",
        "debarment_reason": None,
        "available_funds_cents": 0,
        "escrow_held_cents": 0,
        "lifetime_deposits_cents": 0,
    })
    return response.object_response(derive.bidder_out(row), 201)


@bp.get("/bidders/<row_id>")
@authorize(RPO, CLERK, MONITOR, FINANCE, BIDDER, SYSADMIN)
def get_bidder(row_id):
    row = lookup.must("bidders", row_id)
    return response.object_response(derive.bidder_out(row))


@bp.get("/bidders")
@authorize(RPO, CLERK, MONITOR, FINANCE, SYSADMIN)
def list_bidders():
    limit, offset = listing.bounds()
    debarment_status = shape.query_enum("debarment_status", DEBARMENT_STATUSES)
    entity_type = shape.query_enum("entity_type", ENTITY_TYPES)
    rows = db.all_rows("bidders")
    if debarment_status is not None:
        rows = [r for r in rows if r["debarment_status"] == debarment_status]
    if entity_type is not None:
        rows = [r for r in rows if r["entity_type"] == entity_type]
    return listing.respond(rows, derive.bidder_out, limit, offset, listing.by_created_at)


@bp.post("/bidders/<row_id>/funding")
@authorize(FINANCE)
def fund_bidder(row_id):
    payload = shape.body()
    amount = shape.req_int(payload, "amount_cents", 1)
    row = lookup.must("bidders", row_id)
    calc.credit_funding(row, amount)
    return response.object_response(derive.bidder_out(row))


@bp.post("/bidders/<row_id>/debarment")
@authorize(MONITOR)
def debar_bidder(row_id):
    payload = shape.body()
    reason = shape.req_str(payload, "debarment_reason", 1)
    row = lookup.must("bidders", row_id)
    row["debarment_status"] = "DEBARRED"
    row["debarment_reason"] = reason
    db.touch(row)
    return response.object_response(derive.bidder_out(row))


# --------------------------------------------------------------------------
# Designated funds
# --------------------------------------------------------------------------

@bp.post("/funds")
@authorize(FINANCE)
def create_fund():
    payload = shape.body()
    name = shape.req_str(payload, "name", 1)
    fund_code = shape.req_str(payload, "fund_code", 1)
    priority_rank = shape.req_int(payload, "priority_rank", 1)
    allocation_pct = shape.req_fraction(payload, "allocation_pct")
    fixed_reserve = shape.opt_cents(payload, "fixed_reserve_cents", 0)
    existing = db.all_rows("funds")
    if any(f["fund_code"] == fund_code for f in existing):
        fail("ERR_DUPLICATE_KEY", "fund_code %s is already configured." % fund_code)
    if any(f["priority_rank"] == priority_rank for f in existing):
        fail("ERR_DUPLICATE_KEY", "priority_rank %s is already taken." % priority_rank)
    row = db.insert("funds", {
        "name": name,
        "fund_code": fund_code,
        "priority_rank": priority_rank,
        "allocation_pct": allocation_pct,
        "fixed_reserve_cents": fixed_reserve,
        "balance_cents": 0,
        "lifetime_credits_cents": 0,
        "lifetime_debits_cents": 0,
    })
    return response.object_response(derive.fund_out(row), 201)


@bp.get("/funds/<row_id>")
@authorize(RPO, CLERK, MONITOR, FINANCE, SYSADMIN)
def get_fund(row_id):
    row = lookup.must("funds", row_id)
    return response.object_response(derive.fund_out(row))


@bp.get("/funds")
@authorize(RPO, CLERK, MONITOR, FINANCE, SYSADMIN)
def list_funds():
    limit, offset = listing.bounds()
    rows = db.all_rows("funds")
    return listing.respond(rows, derive.fund_out, limit, offset,
                           lambda f: f["priority_rank"])


@bp.patch("/funds/<row_id>")
@authorize(FINANCE)
def patch_fund(row_id):
    payload = shape.body()
    allocation_pct = shape.opt_fraction(payload, "allocation_pct")
    fixed_reserve = shape.opt_cents(payload, "fixed_reserve_cents")
    row = lookup.must("funds", row_id)
    if allocation_pct is not None:
        row["allocation_pct"] = allocation_pct
    if fixed_reserve is not None:
        row["fixed_reserve_cents"] = fixed_reserve
    db.touch(row)
    return response.object_response(derive.fund_out(row))
