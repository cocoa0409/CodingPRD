"""Recreational leasing, proration and hunting-season blackouts (PRD 3.6)."""

from decimal import Decimal

from flask import Blueprint

import calc
import db
import middleware
import response
import serializers
import services
import validate
from db import store
from errors import ApiError

bp = Blueprint("leases", __name__)

ZERO = Decimal("0.00")


@bp.post("/recreational-leases")
def create_lease():
    middleware.require("FundAdmin")
    body = validate.json_body()

    raw_property_id = validate.opt_str_id(body, "property_id")
    prop = None
    if raw_property_id is not None:
        prop = services.find(store.properties, raw_property_id, "ERR_PROPERTY_NOT_FOUND")

    property_id = validate.string(body, "property_id")
    lessee_name = validate.string(body, "lessee_name", 1, 120)
    leased_acres = validate.number(body, "leased_acres", minimum=0,
                                   exclusive_min=True, dp=2)
    rent_per_acre = validate.number(body, "rent_per_acre_usd", minimum=0,
                                    exclusive_min=True, dp=2)
    term_start_raw, term_start = validate.date_field(body, "term_start_date")
    term_end_raw, term_end = validate.date_field(body, "term_end_date")
    blackout_start_raw, blackout_start = validate.date_field(body, "blackout_start_date")
    blackout_end_raw, blackout_end = validate.date_field(body, "blackout_end_date")
    if prop is None:
        prop = services.find(store.properties, property_id, "ERR_PROPERTY_NOT_FOUND")

    # Non-empty half-open term, non-empty blackout, blackout inside the term.
    if term_end <= term_start:
        raise ApiError("ERR_LEASE_TERM_INVALID")
    if blackout_end <= blackout_start:
        raise ApiError("ERR_LEASE_TERM_INVALID")
    if blackout_start < term_start or blackout_end > term_end:
        raise ApiError("ERR_LEASE_TERM_INVALID")

    rec = db.base_fields()
    rec.update({
        "property_id": prop["id"],
        "lessee_name": lessee_name,
        "leased_acres": leased_acres,
        "rent_per_acre_usd": rent_per_acre,
        "term_start_date": term_start_raw,
        "term_end_date": term_end_raw,
        "blackout_start_date": blackout_start_raw,
        "blackout_end_date": blackout_end_raw,
        "_term_start": term_start,
        "_term_end": term_end,
        "_blackout_start": blackout_start,
        "_blackout_end": blackout_end,
        "status": "PENDING",
        "annual_rent_usd": calc.annual_rent(leased_acres, rent_per_acre),
        "term_days": db.days_between(term_start, term_end),
        "first_year_prorated_rent_usd": None,
        "earned_rent_usd": ZERO,
        "refunded_rent_usd": ZERO,
        "termination_effective_date": None,
    })
    store.recreational_leases[rec["id"]] = rec
    return response.created(serializers.recreational_lease(rec))


@bp.get("/recreational-leases/<lease_id>")
def get_lease(lease_id):
    middleware.require(*middleware.ANY_ROLE)
    lease = services.find(store.recreational_leases, lease_id,
                          "ERR_RECREATIONAL_LEASE_NOT_FOUND")
    services.apply_lazy_lease_expiry(lease)
    return response.ok(serializers.recreational_lease(lease))


@bp.post("/recreational-leases/<lease_id>/activate")
def activate_lease(lease_id):
    middleware.require("FundAdmin")
    lease = services.find(store.recreational_leases, lease_id,
                          "ERR_RECREATIONAL_LEASE_NOT_FOUND")
    prop = store.properties.get(lease["property_id"])

    if lease["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if prop["status"] not in ("OWNED", "HBU_MARKETED"):
        raise ApiError("ERR_PROPERTY_NOT_OWNED")
    if services.lease_coverage_conflict(prop, lease):
        raise ApiError("ERR_LEASE_ACREAGE_EXCEEDED")

    rent = calc.first_year_prorated_rent(lease["annual_rent_usd"], lease["term_days"])
    lease["first_year_prorated_rent_usd"] = rent
    lease["status"] = "ACTIVE"
    services.mark(lease)
    fund = services.fund_of_property(prop)
    if fund is not None:
        services.credit_fund(fund, rent, operating=True)
    return response.ok(serializers.recreational_lease(lease))


@bp.post("/recreational-leases/<lease_id>/terminate")
def terminate_lease(lease_id):
    middleware.require("FundAdmin")
    lease = services.find(store.recreational_leases, lease_id,
                          "ERR_RECREATIONAL_LEASE_NOT_FOUND")
    body = validate.json_body()
    effective_raw, effective = validate.date_field(body, "termination_effective_date")

    prop = store.properties.get(lease["property_id"])
    status = lease["status"]
    if status == "ACTIVE":
        if effective < lease["_term_start"] or effective >= lease["_term_end"]:
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        earned = calc.earned_rent(lease["annual_rent_usd"],
                                  db.days_between(lease["_term_start"], effective))
        refund = calc.rhu(
            calc.D(lease["first_year_prorated_rent_usd"] or 0) - earned, 2)
        fund = services.fund_of_property(prop) if prop else None
        if fund is not None:
            services.guard_fund_cash(fund, refund)
        lease["earned_rent_usd"] = earned
        lease["refunded_rent_usd"] = refund
        lease["termination_effective_date"] = effective_raw
        lease["status"] = "TERMINATED"
        services.mark(lease)
        if fund is not None:
            services.debit_fund(fund, refund, operating=True)
    elif status == "PENDING":
        # No rent was ever charged, so nothing moves.
        lease["termination_effective_date"] = effective_raw
        lease["status"] = "TERMINATED"
        services.mark(lease)
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    return response.ok(serializers.recreational_lease(lease))
