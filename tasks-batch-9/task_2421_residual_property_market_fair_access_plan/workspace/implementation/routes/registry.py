"""Plan foundations (PRD 3.1): member carriers, territories and producers."""

from flask import Blueprint

import lookup
from db import db, new_record, touch
from errors import fail, invalid
from middleware import require
from response import created, ok
from routes.common import matches, page, unique
from services.constants import (
    ALLOCATION_STATUSES,
    ASSESSMENT_STATUSES,
    COMMISSION_TIERS,
    DEFAULT_RESTRICTED_MIN_CONDITION_SCORE,
    FILING_STATUSES,
    MEMBER_STATUSES,
    PERILS,
    PERIL_PACKAGES,
    PRODUCER_ACTIONS,
    RATE_BPS_PREFERRED,
    RATE_BPS_STANDARD,
)
from validate import (
    body,
    filter_enum,
    opt_enum,
    opt_int,
    opt_percent,
    pagination,
    present,
    req_date,
    req_enum,
    req_int,
    req_percent,
    req_string,
    store_date,
)

bp = Blueprint("registry", __name__)

# The membership path is one-way: ACTIVE -> RUNOFF -> WITHDRAWN.
MEMBER_TRANSITIONS = {
    ("ACTIVE", "ACTIVE"),
    ("ACTIVE", "RUNOFF"),
    ("RUNOFF", "RUNOFF"),
    ("RUNOFF", "WITHDRAWN"),
    ("WITHDRAWN", "WITHDRAWN"),
}


# --- member insurers ------------------------------------------------------

@bp.post("/member-insurers")
def admit_member():
    require("PlanAdmin")
    data = body()
    name = req_string(data, "name")
    naic_code = req_string(data, "naic_code")
    market_share_pct = req_percent(data, "market_share_pct")
    written_premium_share_pct = req_percent(data, "written_premium_share_pct")

    unique(db.member_insurers, "naic_code", naic_code, "naic_code")

    member = new_record({
        "name": name,
        "naic_code": naic_code,
        "market_share_pct": market_share_pct,
        "written_premium_share_pct": written_premium_share_pct,
        "status": "ACTIVE",
        "takeout_credit_count": 0,
        "cumulative_assessed_cents": 0,
    })
    db.member_insurers[member["id"]] = member
    return created(member)


@bp.patch("/member-insurers/<member_id>")
def update_member(member_id):
    require("PlanAdmin")
    data = body()
    new_status = opt_enum(data, "status", MEMBER_STATUSES)
    market_share_pct = opt_percent(data, "market_share_pct")
    written_premium_share_pct = opt_percent(data, "written_premium_share_pct")

    member = lookup.member(member_id)

    if new_status is not None:
        if (member["status"], new_status) not in MEMBER_TRANSITIONS:
            invalid("Member status cannot move from %s to %s"
                    % (member["status"], new_status))
        member["status"] = new_status
    if market_share_pct is not None:
        member["market_share_pct"] = market_share_pct
    if written_premium_share_pct is not None:
        member["written_premium_share_pct"] = written_premium_share_pct

    touch(member)
    return ok(member)


@bp.get("/member-insurers/<member_id>")
def read_member(member_id):
    require("PlanAdmin", "Regulator", "MemberInsurerUser")
    return ok(lookup.member(member_id))


@bp.get("/member-insurers")
def list_members():
    require("PlanAdmin", "Regulator")
    limit, offset = pagination()
    status = filter_enum("status", MEMBER_STATUSES)
    rows = [m for m in db.member_insurers.values() if matches(m, {"status": status})]
    return page(rows, limit, offset)


@bp.get("/member-insurers/<member_id>/declinations")
def list_member_declinations(member_id):
    require("PlanAdmin", "Regulator", "MemberInsurerUser")
    limit, offset = pagination()
    member = lookup.member(member_id)
    rows = [d for d in db.declinations.values()
            if d["member_insurer_id"] == member["id"]]
    return page(rows, limit, offset)


@bp.get("/member-insurers/<member_id>/allocations")
def list_member_allocations(member_id):
    require("PlanAdmin", "MemberInsurerUser")
    limit, offset = pagination()
    status = filter_enum("status", ALLOCATION_STATUSES)
    member = lookup.member(member_id)
    rows = [a for a in db.assessment_allocations.values()
            if a["member_insurer_id"] == member["id"] and matches(a, {"status": status})]
    return page(rows, limit, offset)


# --- catastrophe zones ----------------------------------------------------

@bp.post("/cat-zones")
def create_zone():
    require("PlanAdmin")
    data = body()
    code = req_string(data, "code")
    peril = req_enum(data, "peril", PERILS)
    exposure_cap_cents = req_int(data, "exposure_cap_cents", positive=True)
    restricted_min = opt_int(data, "restricted_min_condition_score",
                             default=DEFAULT_RESTRICTED_MIN_CONDITION_SCORE,
                             minimum=0, maximum=100)

    unique(db.cat_zones, "code", code, "code")

    zone = new_record({
        "code": code,
        "peril": peril,
        "exposure_cap_cents": exposure_cap_cents,
        "restricted_min_condition_score": restricted_min,
        "aggregate_insured_value_cents": 0,
        "concentration_ratio": 0.0,
        "status": "OPEN",
    })
    db.cat_zones[zone["id"]] = zone
    return created(zone)


@bp.get("/cat-zones/<zone_id>")
def read_zone(zone_id):
    require("PlanAdmin", "Regulator", "Underwriter", "RateAnalyst")
    return ok(lookup.cat_zone(zone_id))


@bp.get("/cat-zones/<zone_id>/properties")
def list_zone_properties(zone_id):
    require("PlanAdmin", "Underwriter")
    limit, offset = pagination()
    zone = lookup.cat_zone(zone_id)
    rows = [p for p in db.properties.values() if p["cat_zone_id"] == zone["id"]]
    return page(rows, limit, offset)


@bp.get("/cat-zones/<zone_id>/rate-filings")
def list_zone_filings(zone_id):
    require("PlanAdmin", "RateAnalyst", "Regulator", "Underwriter")
    limit, offset = pagination()
    status = filter_enum("status", FILING_STATUSES)
    peril_package = filter_enum("peril_package", PERIL_PACKAGES)
    zone = lookup.cat_zone(zone_id)
    rows = [f for f in db.rate_filings.values()
            if f["cat_zone_id"] == zone["id"]
            and matches(f, {"status": status, "peril_package": peril_package})]
    return page(rows, limit, offset)


@bp.get("/cat-zones/<zone_id>/assessment-events")
def list_zone_events(zone_id):
    require("PlanAdmin", "Regulator")
    limit, offset = pagination()
    status = filter_enum("status", ASSESSMENT_STATUSES)
    zone = lookup.cat_zone(zone_id)
    rows = [e for e in db.assessment_events.values()
            if e["cat_zone_id"] == zone["id"] and matches(e, {"status": status})]
    return page(rows, limit, offset)


# --- producers ------------------------------------------------------------

@bp.post("/producers")
def register_producer():
    require("PlanAdmin")
    data = body()
    full_name = req_string(data, "full_name")
    license_number = req_string(data, "license_number")
    commission_tier = req_enum(data, "commission_tier", COMMISSION_TIERS)
    e_and_o_expiry_date = req_date(data, "e_and_o_expiry_date")

    unique(db.producers, "license_number", license_number, "license_number")

    producer = new_record({
        "full_name": full_name,
        "license_number": license_number,
        "commission_tier": commission_tier,
        "commission_rate_bps": 0,
        "e_and_o_expiry_date": store_date(e_and_o_expiry_date),
        "agreement_status": "PENDING",
        "agreement_effective_date": None,
        "ytd_commission_cents": 0,
    })
    db.producers[producer["id"]] = producer
    return created(producer)


@bp.post("/producers/<producer_id>/agreement-execution")
def execute_agreement(producer_id):
    require("PlanAdmin")
    data = body()
    agreement_effective_date = req_date(data, "agreement_effective_date")

    producer = lookup.producer(producer_id)
    if producer["agreement_status"] != "PENDING":
        fail("ERR_PRODUCER_STATUS_INVALID",
             "Producer agreement is %s, not PENDING" % producer["agreement_status"])

    producer["agreement_status"] = "APPOINTED"
    producer["agreement_effective_date"] = store_date(agreement_effective_date)
    producer["commission_rate_bps"] = (
        RATE_BPS_PREFERRED if producer["commission_tier"] == "PREFERRED"
        else RATE_BPS_STANDARD)
    touch(producer)
    return ok(producer)


@bp.post("/producers/<producer_id>/status-actions")
def producer_status_action(producer_id):
    require("PlanAdmin")
    data = body()
    action = req_enum(data, "action", PRODUCER_ACTIONS)
    if present(data, "reason"):
        req_string(data, "reason")

    producer = lookup.producer(producer_id)
    current = producer["agreement_status"]

    if action == "SUSPEND":
        allowed, target = ("APPOINTED",), "SUSPENDED"
    elif action == "REINSTATE":
        allowed, target = ("SUSPENDED",), "APPOINTED"
    else:
        allowed, target = ("APPOINTED", "SUSPENDED"), "TERMINATED"

    if current not in allowed:
        fail("ERR_PRODUCER_STATUS_INVALID",
             "Action %s is not accepted from agreement status %s" % (action, current))

    producer["agreement_status"] = target
    touch(producer)
    return ok(producer)


@bp.get("/producers/<producer_id>")
def read_producer(producer_id):
    require("PlanAdmin", "Producer", "Underwriter")
    return ok(lookup.producer(producer_id))
