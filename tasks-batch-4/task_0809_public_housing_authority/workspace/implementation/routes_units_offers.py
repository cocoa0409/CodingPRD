"""Units and the offer cycle (create/accept/refuse)."""
from datetime import timedelta

from flask import Blueprint

import db
import domain
from core import (
    ApiError, authenticate, authorize, require_ownership, get_or_404,
    owner_applicant_id, json_body, need_str, need_int, need_int_in,
    opt_int_nonneg, need_dt, pagination, opt_qint, ok, ok_list,
)

bp = Blueprint("units_offers", __name__)


def _paged(records):
    limit, offset = pagination()
    ordered = db.sorted_by_created(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [db.serialize(r) for r in page], limit, offset, total


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
@bp.route("/pha/units", methods=["POST"])
def create_unit():
    uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    body = json_body()
    address_label = need_str(body, "address_label")
    bedroom_size = need_int_in(body, "bedroom_size", 0, 6)
    income_limit_cents = need_int(body, "income_limit_cents")
    if income_limit_cents <= 0:
        raise ApiError("ERR_VALIDATION", "income_limit_cents must be > 0")
    utility_allowance_cents = opt_int_nonneg(body, "utility_allowance_cents", 0)
    unit = db.create(
        db.units,
        address_label=address_label,
        bedroom_size=bedroom_size,
        utility_allowance_cents=utility_allowance_cents,
        income_limit_cents=income_limit_cents,
        status="AVAILABLE",
        last_lease_end_date=None,
    )
    return ok(db.serialize(unit), 201)


@bp.route("/pha/units/<unit_id>", methods=["GET"])
def get_unit(unit_id):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "HousingSpecialist", "PropertyManager", "Applicant"})
    unit = get_or_404(db.units, unit_id, "ERR_UNIT_NOT_FOUND")
    return ok(db.serialize(unit))


@bp.route("/pha/units", methods=["GET"])
def list_units():
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "HousingSpecialist", "PropertyManager", "Applicant"})
    from flask import request
    status = request.args.get("status")
    bedroom_size = opt_qint("bedroom_size")
    records = list(db.units.values())
    if status:
        records = [u for u in records if u["status"] == status]
    if bedroom_size is not None:
        records = [u for u in records if u["bedroom_size"] == bedroom_size]
    items, limit, offset, total = _paged(records)
    return ok_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------
@bp.route("/pha/offers", methods=["POST"])
def create_offer():
    uid, role = authenticate()
    authorize(role, {"HousingSpecialist"})
    body = json_body()
    entry_id = need_str(body, "waitlist_entry_id")
    unit_id = need_str(body, "unit_id")
    expires_at = need_dt(body, "expires_at")
    entry = get_or_404(db.waitlist_entries, entry_id, "ERR_WAITLIST_ENTRY_NOT_FOUND")
    unit = get_or_404(db.units, unit_id, "ERR_UNIT_NOT_FOUND")
    # state: entry must be ACTIVE to be offered
    if entry["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "waitlist entry is not ACTIVE")
    # cross-entity: unit must be AVAILABLE
    if unit["status"] != "AVAILABLE":
        raise ApiError("ERR_UNIT_NOT_AVAILABLE", "unit is not AVAILABLE")
    # business: bedroom size must match the entry's waitlist
    waitlist = db.waitlists[entry["waitlist_id"]]
    if unit["bedroom_size"] != waitlist["bedroom_size"]:
        raise ApiError("ERR_BEDROOM_MISMATCH", "unit bedroom size does not match waitlist")
    # business: make-ready buffer
    if unit["last_lease_end_date"] is not None:
        ready_at = unit["last_lease_end_date"] + timedelta(days=domain.MAKE_READY_DAYS)
        if db.now() < ready_at:
            raise ApiError("ERR_UNIT_TURNOVER_CONFLICT", "make-ready buffer not elapsed")
    now = db.now()
    offer = db.create(
        db.offers,
        waitlist_entry_id=entry["id"],
        unit_id=unit["id"],
        status="PENDING",
        offered_at=now,
        expires_at=expires_at,
    )
    db.touch(unit, status="OFFERED")
    db.touch(entry, status="OFFERED", last_contact_at=now)
    return ok(db.serialize(offer), 201)


@bp.route("/pha/offers/<oid>", methods=["GET"])
def get_offer(oid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "HousingSpecialist", "PropertyManager", "Applicant"})
    offer = get_or_404(db.offers, oid, "ERR_OFFER_NOT_FOUND")
    require_ownership(role, uid, owner_applicant_id("offer", offer))
    return ok(db.serialize(offer))


@bp.route("/pha/offers", methods=["GET"])
def list_offers():
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "HousingSpecialist", "PropertyManager", "Applicant"})
    from flask import request
    entry_id = request.args.get("waitlist_entry_id")
    unit_id = request.args.get("unit_id")
    records = list(db.offers.values())
    if entry_id:
        records = [o for o in records if o["waitlist_entry_id"] == entry_id]
    if unit_id:
        records = [o for o in records if o["unit_id"] == unit_id]
    items, limit, offset, total = _paged(records)
    return ok_list(items, limit, offset, total)


@bp.route("/pha/offers/<oid>/accept", methods=["POST"])
def accept_offer(oid):
    uid, role = authenticate()
    authorize(role, {"Applicant"})
    offer = get_or_404(db.offers, oid, "ERR_OFFER_NOT_FOUND")
    require_ownership(role, uid, owner_applicant_id("offer", offer))
    if offer["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "offer is not PENDING")
    unit = db.units[offer["unit_id"]]
    if unit["status"] != "OFFERED":
        raise ApiError("ERR_UNIT_NOT_AVAILABLE", "offered unit is not OFFERED")
    if db.now() > offer["expires_at"]:
        raise ApiError("ERR_OFFER_EXPIRED", "offer has expired")
    tenancy = domain.accept_offer(offer)
    return ok(db.serialize(tenancy), 201)


@bp.route("/pha/offers/<oid>/refuse", methods=["POST"])
def refuse_offer(oid):
    uid, role = authenticate()
    authorize(role, {"Applicant"})
    offer = get_or_404(db.offers, oid, "ERR_OFFER_NOT_FOUND")
    require_ownership(role, uid, owner_applicant_id("offer", offer))
    if offer["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "offer is not PENDING")
    domain.refuse_offer(offer)
    return ok(db.serialize(offer))
