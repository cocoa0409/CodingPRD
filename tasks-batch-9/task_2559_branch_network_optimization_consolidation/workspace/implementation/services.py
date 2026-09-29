"""Lookups, cascades and the conservation-preserving state movements."""
import calc
from core import (DB, all_of, fail, touch, clock_today_iso, sort_key_created,
                  CLOCK, format_instant, day_diff, date_plus)

OPEN_CASE_STATUSES = ("SUBMITTED", "APPROVED", "NOTICE_FILED", "CLOSURE_EXECUTED",
                      "POST_CLOSE_MONITORING")


# --------------------------------------------------------------------------- #
# Resolution helpers (PRD 2.4 / precedence ranks 7 and 8)
# --------------------------------------------------------------------------- #
def path_lookup(collection, identifier, label):
    rec = DB[collection].get(identifier)
    if rec is None:
        fail("ERR_RESOURCE_NOT_FOUND", "%s '%s' was not found." % (label, identifier))
    return rec


def ref_lookup(collection, identifier, label):
    rec = DB[collection].get(identifier)
    if rec is None:
        fail("ERR_REFERENCED_RESOURCE_NOT_FOUND",
             "Referenced %s '%s' was not found." % (label, identifier))
    return rec


def children_of(collection, field, value):
    return [r for r in all_of(collection) if r.get(field) == value]


def newest_first(rows):
    return sorted(rows, key=sort_key_created, reverse=True)


def oldest_first(rows):
    return sorted(rows, key=sort_key_created)


# --------------------------------------------------------------------------- #
# 3.1 market footprint refresh
# --------------------------------------------------------------------------- #
def refresh_market_footprint(market):
    own = calc.count_own_branches(market["id"])
    density = calc.branch_density_per_100k(own, market["competitor_branch_count"],
                                           market["population"])
    market["own_branch_count"] = own
    market["branch_density_per_100k"] = density
    market["saturation_tier"] = calc.saturation_tier(density)
    touch(market)
    return market


# --------------------------------------------------------------------------- #
# 3.2 branch score refresh
# --------------------------------------------------------------------------- #
def refresh_branch_score(branch):
    score, band, _count = calc.score_history(branch["id"], branch["scoring_variant"])
    branch["performance_score_bps"] = score
    branch["performance_band"] = band
    return branch


# --------------------------------------------------------------------------- #
# 3.4 savings chain refresh
# --------------------------------------------------------------------------- #
def refresh_case_savings(case):
    calc.recompute_savings_chain(case)
    touch(case)
    return case


# --------------------------------------------------------------------------- #
# 3.5 assessments and notices
# --------------------------------------------------------------------------- #
def live_assessment(case_id):
    rows = [a for a in children_of("impact_assessments", "consolidation_case_id", case_id)
            if a["status"] != "SUPERSEDED"]
    rows = newest_first(rows)
    return rows[0] if rows else None


def supersede_live_assessment(case):
    """Any prior non-superseded assessment goes to SUPERSEDED.  Returns True if a
    FINALIZED assessment was dragged out, which resets the case's regulatory fields."""
    dragged = False
    for a in children_of("impact_assessments", "consolidation_case_id", case["id"]):
        if a["status"] in ("DRAFT", "FINALIZED", "REOPENED"):
            if a["status"] == "FINALIZED":
                dragged = True
            a["status"] = "SUPERSEDED"
            touch(a)
    if dragged:
        case["impact_tier"] = "UNASSESSED"
        case["notice_required_days"] = 0
    return dragged


def active_forecast(case_id):
    rows = [f for f in children_of("retention_forecasts", "consolidation_case_id", case_id)
            if f["status"] == "ACTIVE"]
    return newest_first(rows)[0] if rows else None


def supersede_active_forecast(case_id):
    for f in children_of("retention_forecasts", "consolidation_case_id", case_id):
        if f["status"] == "ACTIVE":
            f["status"] = "SUPERSEDED"
            touch(f)


def regulator_notice_open(case_id):
    rows = [n for n in children_of("closure_notices", "consolidation_case_id", case_id)
            if n["notice_type"] == "REGULATOR" and n["status"] in ("FILED", "EFFECTIVE")]
    return newest_first(rows)[0] if rows else None


def notice_window_conflict(new_notice_case, filed_on, buffer_end_date, exclude_notice_id=None):
    """Closed-interval collision against every other REGULATOR notice of the market."""
    market_id = market_of_case(new_notice_case)
    for n in all_of("closure_notices"):
        if exclude_notice_id is not None and n["id"] == exclude_notice_id:
            continue
        if n["notice_type"] != "REGULATOR" or n["status"] not in ("FILED", "EFFECTIVE"):
            continue
        other_case = DB["consolidation_cases"].get(n["consolidation_case_id"])
        if other_case is None or market_of_case(other_case) != market_id:
            continue
        if (day_diff(n["buffer_end_date"], filed_on) >= 0
                and day_diff(buffer_end_date, n["filed_on"]) >= 0):
            return True
    return False


def market_of_case(case):
    branch = DB["branches"].get(case["closing_branch_id"])
    return branch["market_area_id"] if branch else None


def market_of_branch(branch):
    return DB["market_areas"].get(branch["market_area_id"]) if branch else None


# --------------------------------------------------------------------------- #
# 3.9 remediation counters, de novo hold and the plan hold cascade
# --------------------------------------------------------------------------- #
def apply_de_novo_hold(market):
    """Third and fourth hops: re-derive the hold, then move APPROVED/HELD plans."""
    before = bool(market.get("de_novo_hold"))
    after = market["remediation_case_count"] >= 1
    market["de_novo_hold"] = after
    touch(market)
    if after == before:
        return
    if after:
        for p in children_of("de_novo_plans", "market_area_id", market["id"]):
            if p["status"] == "APPROVED":
                p["status"] = "HELD"
                touch(p)
    else:
        for p in children_of("de_novo_plans", "market_area_id", market["id"]):
            if p["status"] == "HELD":
                p["status"] = "APPROVED"
                touch(p)


def set_governance_flag(case, flag):
    market = DB["market_areas"].get(market_of_case(case))
    if case["governance_flag"] == flag:
        return
    case["governance_flag"] = flag
    if market is not None:
        if flag == "SAVINGS_WATCH":
            market["flagged_case_count"] += 1
        else:
            market["flagged_case_count"] -= 1
        touch(market)


# --------------------------------------------------------------------------- #
# 2.8 clock advance side effects
# --------------------------------------------------------------------------- #
def advance_clock(instant):
    CLOCK["current"] = instant
    today = clock_today_iso()
    notices_made_effective = 0
    properties_moved_to_holdover = 0
    for n in oldest_first(all_of("closure_notices")):
        if n["status"] == "FILED" and day_diff(today, n["effective_closure_date"]) >= 0:
            n["status"] = "EFFECTIVE"
            touch(n)
            notices_made_effective += 1
    for p in oldest_first(all_of("property_dispositions")):
        if p["status"] != "MARKETED" or p["tenure_class"] != "LEASED":
            continue
        if p.get("lease_end_date") is None:
            continue
        if day_diff(today, p["lease_end_date"]) > 0:
            p["status"] = "HOLDOVER"
            calc.refresh_carry(p)
            touch(p)
            properties_moved_to_holdover += 1
            case = DB["consolidation_cases"].get(p["consolidation_case_id"])
            if case is not None:
                refresh_case_savings(case)
    return {
        "current_utc": format_instant(instant),
        "notices_made_effective": notices_made_effective,
        "properties_moved_to_holdover": properties_moved_to_holdover,
    }
