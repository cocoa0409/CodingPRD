"""Practice groups, search firms, engagements and the logical clock."""

from datetime import timedelta

import calculations as calc
import cascades
import listing
import lookups as lk
import middleware as mw
import services as svc
from db import db, new_row, pub, set_fields
from errors import ApiError
from flask import Blueprint
from response import empty_response, object_response

bp = Blueprint("config", __name__, url_prefix="/lateral-hiring")

READ_GROUP = mw.READ_ALL
READ_FIRM = ("SystemAdmin", "RecruitingCoordinator", "PracticeGroupLeader",
             "CommitteeMember", "CommitteeChair")


# ---------------------------------------------------------------- practice groups

@bp.post("/practice-groups")
def create_practice_group():
    mw.authenticate(("SystemAdmin",))
    data = mw.body()
    name = mw.v_str(data, "name", 1, 120)
    budget = mw.v_num(data, "guarantee_budget_total_usd", minimum=0)
    capacity = mw.v_int(data, "onboarding_capacity", minimum=1)
    leverage = mw.v_num(data, "leverage_ratio", minimum=0, exclusive_min=True)
    target_rate = mw.v_num(data, "target_standard_rate_usd", minimum=0,
                           exclusive_min=True)
    for existing in db.practice_groups.values():
        if existing["name"] == name:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field 'name' must be unique across practice groups.")
    row = new_row({
        "name": name,
        "status": "OPEN",
        "guarantee_budget_total_usd": budget,
        "available_guarantee_budget_usd": budget,
        "reserved_guarantee_budget_usd": calc.ZERO,
        "committed_guarantee_total_usd": calc.ZERO,
        "onboarding_capacity": capacity,
        "active_onboarding_count": 0,
        "leverage_ratio": leverage,
        "target_standard_rate_usd": target_rate,
    })
    db.practice_groups[row["id"]] = row
    return object_response(pub(row), 201)


@bp.get("/practice-groups/<practice_group_id>")
def read_practice_group(practice_group_id):
    mw.authenticate(READ_GROUP)
    return object_response(pub(lk.get_practice_group(practice_group_id)))


@bp.get("/practice-groups")
def list_practice_groups():
    mw.authenticate(READ_GROUP)
    rows = listing.eq_filter(list(db.practice_groups.values()), "status")
    return listing.paged(rows)


@bp.post("/practice-groups/<practice_group_id>/freeze")
def freeze_practice_group(practice_group_id):
    mw.authenticate(("SystemAdmin",))
    group = lk.get_practice_group(practice_group_id)
    data = mw.body()
    mw.v_str(data, "reason", 1, None)
    if group["status"] != "OPEN":
        raise ApiError("ERR_PRACTICE_GROUP_FROZEN")
    set_fields(group, status="HIRING_FROZEN")
    return object_response(pub(group))


@bp.post("/practice-groups/<practice_group_id>/unfreeze")
def unfreeze_practice_group(practice_group_id):
    mw.authenticate(("SystemAdmin",))
    group = lk.get_practice_group(practice_group_id)
    if group["status"] != "HIRING_FROZEN":
        raise ApiError("ERR_PRACTICE_GROUP_FROZEN")
    set_fields(group, status="OPEN")
    return object_response(pub(group))


# ------------------------------------------------------------------ search firms

@bp.post("/search-firms")
def create_search_firm():
    mw.authenticate(("SystemAdmin",))
    data = mw.body()
    name = mw.v_str(data, "name", 1, 120)
    max_fee_pct = mw.v_num(data, "max_fee_pct", minimum=0, maximum="0.40",
                           exclusive_min=True)
    max_concurrent = mw.v_int(data, "max_concurrent_engagements", minimum=1)
    for existing in db.search_firms.values():
        if existing["name"] == name:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field 'name' must be unique across search firms.")
    row = new_row({
        "name": name,
        "max_fee_pct": max_fee_pct,
        "max_concurrent_engagements": max_concurrent,
        "engagement_count": 0,
    })
    db.search_firms[row["id"]] = row
    return object_response(pub(row), 201)


@bp.get("/search-firms/<search_firm_id>")
def read_search_firm(search_firm_id):
    mw.authenticate(READ_FIRM)
    return object_response(pub(lk.get_search_firm(search_firm_id)))


@bp.get("/search-firms")
def list_search_firms():
    mw.authenticate(READ_FIRM)
    return listing.paged(list(db.search_firms.values()))


# ------------------------------------------------------------------- engagements

def _closed_intersects(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


@bp.post("/search-firm-engagements")
def create_engagement():
    mw.authenticate(("RecruitingCoordinator",))
    data = mw.body()
    # Existence (body FKs in input declaration order) precedes schema.
    firm = None
    group = None
    if isinstance(data.get("search_firm_id"), str):
        firm = lk.get_search_firm(data["search_firm_id"])
    if isinstance(data.get("practice_group_id"), str):
        group = lk.get_practice_group(data["practice_group_id"])

    mw.v_str(data, "search_firm_id", 1, None)
    mw.v_str(data, "practice_group_id", 1, None)
    fee_pct = mw.v_num(data, "fee_pct", minimum=0, exclusive_min=True)
    fee_cap = mw.v_num(data, "fee_cap_usd", minimum=0, exclusive_min=True)
    start = mw.v_dt(data, "exclusivity_start_date")
    end = mw.v_dt(data, "exclusivity_end_date")
    tail_off_days = mw.v_int(data, "tail_off_days", minimum=0, maximum=365)

    # Priority 17: practice-group exclusivity (half-open overlap + quiet gap).
    for other in db.engagements.values():
        if other["practice_group_id"] != group["id"] or other["status"] != "ACTIVE":
            continue
        overlaps = start < other["exclusivity_end_date"] and \
            other["exclusivity_start_date"] < end
        gap_end = other["exclusivity_end_date"] + timedelta(days=other["tail_off_days"])
        if overlaps or start < gap_end:
            raise ApiError("ERR_ENGAGEMENT_EXCLUSIVITY_CONFLICT")

    # Priority 18: search-firm capacity under closed interval semantics.
    concurrent = 0
    for other in db.engagements.values():
        if other["search_firm_id"] != firm["id"] or other["status"] != "ACTIVE":
            continue
        if _closed_intersects(start, end, other["exclusivity_start_date"],
                              other["exclusivity_end_date"]):
            concurrent += 1
    if concurrent >= firm["max_concurrent_engagements"]:
        raise ApiError("ERR_SEARCH_FIRM_CAPACITY_EXCEEDED")

    # Priority 20: window sanity.
    if end <= start:
        raise ApiError("ERR_LOOKBACK_WINDOW_INVALID")

    # Priority 22: fee ceiling.
    if fee_pct > firm["max_fee_pct"]:
        raise ApiError("ERR_FEE_PCT_ABOVE_FIRM_MAX")

    row = new_row({
        "search_firm_id": firm["id"],
        "practice_group_id": group["id"],
        "fee_pct": fee_pct,
        "fee_cap_usd": fee_cap,
        "exclusivity_start_date": start,
        "exclusivity_end_date": end,
        "tail_off_days": tail_off_days,
        "status": "ACTIVE",
        "fee_status": "NOT_DUE",
        "fee_basis": "NONE",
        "fee_amount_usd": calc.ZERO,
    })
    db.engagements[row["id"]] = row
    svc.sync_firm_engagement_count(firm)
    return object_response(pub(row), 201)


@bp.get("/search-firm-engagements/<engagement_id>")
def read_engagement(engagement_id):
    mw.authenticate(READ_FIRM)
    return object_response(pub(lk.get_engagement(engagement_id)))


@bp.get("/search-firm-engagements")
def list_engagements():
    mw.authenticate(READ_FIRM)
    rows = list(db.engagements.values())
    rows = listing.eq_filter(rows, "search_firm_id")
    rows = listing.eq_filter(rows, "practice_group_id")
    rows = listing.eq_filter(rows, "status")
    return listing.paged(rows)


@bp.post("/search-firm-engagements/<engagement_id>/terminate")
def terminate_engagement(engagement_id):
    mw.authenticate(("RecruitingCoordinator",))
    engagement = lk.get_engagement(engagement_id)
    data = mw.body()
    mw.v_str(data, "reason", 1, None)
    if engagement["status"] != "ACTIVE":
        raise ApiError("ERR_ENGAGEMENT_INVALID_STATE")
    set_fields(engagement, status="TERMINATED", fee_status="FEE_WAIVED",
               fee_basis="NONE", fee_amount_usd=calc.ZERO)
    return object_response(pub(engagement))


# ------------------------------------------------------------------ logical clock

@bp.post("/_clock/set_current_utc")
def set_clock():
    mw.authenticate(("SystemAdmin",))
    data = mw.body()
    moment = mw.v_dt(data, "to_iso8601")
    cascades.advance_clock(moment)
    return empty_response()
