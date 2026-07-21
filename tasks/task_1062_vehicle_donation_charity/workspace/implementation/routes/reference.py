"""Counterparty reference data and the logical clock (PRD section 3.1, 2.5)."""

from flask import Blueprint

import db
import middleware as mw
import response as resp
from errors import ApiError

bp = Blueprint("reference", __name__)

VENUE_TYPES = {"AUCTION", "SALVAGE", "DIRECT_SALE"}


# ------------------------------------------------------------- charities
@bp.post("/api/charities")
def create_charity():
    mw.auth("ProgramAdmin")
    data = mw.body()
    name = mw.req_string(data, "name")
    ein = mw.req_string(data, "ein")
    state_code = mw.req_state_code(data, "state_code")
    fee_pct = mw.opt_number(data, "remittance_fee_pct", 0.10)

    if any(c["ein"] == ein for c in db.charities.values()):
        raise ApiError("ERR_DUPLICATE_EIN", "This EIN is already registered.")
    if fee_pct < 0 or fee_pct > float(db.MAX_REMITTANCE_FEE_PCT):
        raise ApiError(
            "ERR_FEE_PCT_OUT_OF_RANGE",
            "remittance_fee_pct must be between 0 and 0.30 inclusive.",
        )

    rec = db.new_record()
    rec["name"] = name
    rec["ein"] = ein
    rec["state_code"] = state_code
    rec["remittance_fee_pct"] = fee_pct
    rec["status"] = "ACTIVE"
    rec["pledged_balance_cents"] = 0
    rec["remitted_balance_cents"] = 0
    db.charities[rec["id"]] = rec
    return resp.created(rec)


@bp.get("/api/charities/<charity_id>")
def get_charity(charity_id):
    mw.auth(
        "ProgramAdmin",
        "FinanceOfficer",
        "CharityAdmin",
        "IntakeAgent",
        "AuctionManager",
        "TitleClerk",
    )
    rec = mw.resolve(db.charities, charity_id, "ERR_CHARITY_NOT_FOUND")
    return resp.ok(rec)


@bp.get("/api/charities")
def list_charities():
    mw.auth("ProgramAdmin", "FinanceOfficer")
    status = mw.query_enum("status", {"ACTIVE", "SUSPENDED"})
    limit, offset = mw.pagination()
    rows = [c for c in db.charities.values() if status is None or c["status"] == status]
    return resp.listing(db.ordered(rows), limit, offset)


@bp.post("/api/charities/<charity_id>/suspend")
def suspend_charity(charity_id):
    mw.auth("ProgramAdmin")
    rec = mw.resolve(db.charities, charity_id, "ERR_CHARITY_NOT_FOUND")
    rec["status"] = "SUSPENDED"
    db.touch(rec)
    return resp.ok(rec)


# ------------------------------------------------------------- donors
@bp.post("/api/donors")
def create_donor():
    mw.auth("IntakeAgent", "ProgramAdmin")
    data = mw.body()
    email = mw.req_string(data, "email")
    full_name = mw.req_string(data, "full_name")
    state_code = mw.req_state_code(data, "state_code")

    if any(d["email"] == email for d in db.donors.values()):
        raise ApiError("ERR_DUPLICATE_EMAIL", "This email is already registered.")

    rec = db.new_record()
    rec["email"] = email
    rec["full_name"] = full_name
    rec["state_code"] = state_code
    rec["status"] = "ACTIVE"
    rec["donation_count"] = 0
    db.donors[rec["id"]] = rec
    return resp.created(rec)


@bp.get("/api/donors/<donor_id>")
def get_donor(donor_id):
    mw.auth("IntakeAgent", "ProgramAdmin", "FinanceOfficer", "Donor")
    rec = mw.resolve(db.donors, donor_id, "ERR_DONOR_NOT_FOUND")
    return resp.ok(rec)


@bp.post("/api/donors/<donor_id>/block")
def block_donor(donor_id):
    mw.auth("ProgramAdmin")
    rec = mw.resolve(db.donors, donor_id, "ERR_DONOR_NOT_FOUND")
    data = mw.body()
    mw.req_string(data, "reason")
    rec["status"] = "BLOCKED"
    db.touch(rec)
    return resp.ok(rec)


# ------------------------------------------------------------- tow vendors
@bp.post("/api/tow-vendors")
def create_tow_vendor():
    mw.auth("ProgramAdmin")
    data = mw.body()
    name = mw.req_string(data, "name")
    state_code = mw.req_state_code(data, "service_state_code")
    hourly_rate = mw.req_int(data, "hourly_rate_cents", minimum=1)
    capacity = mw.req_int(data, "daily_capacity_slots", minimum=1)

    rec = db.new_record()
    rec["name"] = name
    rec["service_state_code"] = state_code
    rec["hourly_rate_cents"] = hourly_rate
    rec["daily_capacity_slots"] = capacity
    rec["status"] = "ACTIVE"
    rec["booked_slots_count"] = 0
    db.tow_vendors[rec["id"]] = rec
    return resp.created(rec)


@bp.get("/api/tow-vendors/<vendor_id>")
def get_tow_vendor(vendor_id):
    mw.auth("ProgramAdmin", "IntakeAgent", "FinanceOfficer")
    rec = mw.resolve(db.tow_vendors, vendor_id, "ERR_TOW_VENDOR_NOT_FOUND")
    return resp.ok(rec)


@bp.post("/api/tow-vendors/<vendor_id>/suspend")
def suspend_tow_vendor(vendor_id):
    mw.auth("ProgramAdmin")
    rec = mw.resolve(db.tow_vendors, vendor_id, "ERR_TOW_VENDOR_NOT_FOUND")
    rec["status"] = "SUSPENDED"
    db.touch(rec)
    return resp.ok(rec)


# ------------------------------------------------------------- venues
@bp.post("/api/venues")
def create_venue():
    mw.auth("ProgramAdmin")
    data = mw.body()
    name = mw.req_string(data, "name")
    venue_type = mw.req_enum(data, "venue_type", VENUE_TYPES)
    state_code = mw.req_state_code(data, "state_code")
    commission = mw.opt_number(data, "commission_pct", 0.05)

    rec = db.new_record()
    rec["name"] = name
    rec["venue_type"] = venue_type
    rec["commission_pct"] = commission
    rec["state_code"] = state_code
    rec["status"] = "ACTIVE"
    db.venues[rec["id"]] = rec
    return resp.created(rec)


@bp.get("/api/venues/<venue_id>")
def get_venue(venue_id):
    mw.auth("ProgramAdmin", "AuctionManager", "FinanceOfficer")
    rec = mw.resolve(db.venues, venue_id, "ERR_VENUE_NOT_FOUND")
    return resp.ok(rec)


@bp.post("/api/venues/<venue_id>/suspend")
def suspend_venue(venue_id):
    mw.auth("ProgramAdmin")
    rec = mw.resolve(db.venues, venue_id, "ERR_VENUE_NOT_FOUND")
    rec["status"] = "SUSPENDED"
    db.touch(rec)
    return resp.ok(rec)


# ------------------------------------------------------------- logical clock
@bp.post("/api/_clock/set_current_utc")
def set_clock():
    mw.auth("ProgramAdmin")
    data = mw.body()
    instant = mw.req_datetime(data, "to_iso8601")
    db.set_clock(instant)
    return resp.ok({"current_utc": db.fmt_dt(instant)})
