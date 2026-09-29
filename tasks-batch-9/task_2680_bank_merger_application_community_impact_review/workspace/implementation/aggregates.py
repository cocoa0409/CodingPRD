"""Derived aggregates: the includable branch set, market/institution rollups,
the six-step concentration screen and the application-level rollups."""
import calc
from db import db, set_fields


def includable(branch):
    return branch["status"] in calc.INCLUDABLE_BRANCH_STATUSES


def market_branches(market_id):
    return [b for b in db.branches.values() if b["market_id"] == market_id and includable(b)]


def institution_branches(institution_id):
    return [
        b
        for b in db.branches.values()
        if b["institution_id"] == institution_id and includable(b)
    ]


def deposits_by_institution(market_id):
    totals = {}
    for branch in market_branches(market_id):
        totals[branch["institution_id"]] = (
            totals.get(branch["institution_id"], 0) + int(branch["deposits_usd"])
        )
    return totals


# --------------------------------------------------------------------------
# market and institution aggregates (PRD 2.8)
# --------------------------------------------------------------------------
def recompute_market(market):
    if market is None:
        return
    totals = deposits_by_institution(market["id"])
    total_deposits = sum(totals.values())
    hhi_current = calc.hhi_from_deposits(list(totals.values()), total_deposits)
    set_fields(
        market,
        total_deposits_usd=total_deposits,
        participant_count=len(totals),
        hhi_current=hhi_current,
    )


def recompute_institution(institution):
    if institution is None:
        return
    branches = institution_branches(institution["id"])
    set_fields(
        institution,
        total_deposits_usd=sum(int(b["deposits_usd"]) for b in branches),
        branch_count=len(branches),
    )


def recompute_market_ids(market_ids):
    for market_id in set(market_ids):
        recompute_market(db.markets.get(market_id))


def recompute_institution_ids(institution_ids):
    for institution_id in set(institution_ids):
        recompute_institution(db.institutions.get(institution_id))


# --------------------------------------------------------------------------
# the six-step concentration screen (PRD 3.5)
# --------------------------------------------------------------------------
def designated_divestiture_deposits(application_id, market_id):
    total = 0
    for branch in db.branches.values():
        if (
            branch["market_id"] == market_id
            and branch["status"] == "DESIGNATED_FOR_DIVESTITURE"
            and branch.get("designation_application_id") == application_id
        ):
            total += int(branch["deposits_usd"])
    return total


def compute_analysis_figures(application, market):
    totals = deposits_by_institution(market["id"])
    denominator = sum(totals.values())
    acquirer_deposits = totals.get(application["acquirer_id"], 0)
    target_deposits = totals.get(application["target_id"], 0)
    others = [
        amount
        for institution_id, amount in totals.items()
        if institution_id not in (application["acquirer_id"], application["target_id"])
    ]
    others.sort(reverse=True)

    # step 1
    hhi_pre = calc.hhi_from_deposits(list(totals.values()), denominator)
    # step 2
    combined = acquirer_deposits + target_deposits
    hhi_post_unmitigated = calc.hhi_from_deposits(others + [combined], denominator)
    hhi_delta_unmitigated = hhi_post_unmitigated - hhi_pre
    # step 3
    ceiling = calc.market_ceiling(market["market_type"])
    screen_result = calc.screen_result_for(hhi_post_unmitigated, hhi_delta_unmitigated, ceiling)
    # step 4
    if screen_result == "PASS":
        required = 0
    else:
        required = calc.required_divestiture(others, combined, denominator, hhi_pre, ceiling)
    # step 5
    designated = designated_divestiture_deposits(application["id"], market["id"])
    mitigated_shares = others + [combined - designated]
    if designated > 0:
        mitigated_shares.append(designated)
    hhi_post_mitigated = calc.hhi_from_deposits(mitigated_shares, denominator)
    # step 6
    mitigation_satisfied = bool(
        designated >= required
        and (
            hhi_post_mitigated < ceiling
            or (hhi_post_mitigated - hhi_pre) <= calc.HHI_DELTA_SAFE_HARBOR
        )
    )
    return {
        "combined_market_deposits_usd": combined,
        "hhi_pre_merger": hhi_pre,
        "hhi_post_unmitigated": hhi_post_unmitigated,
        "hhi_delta_unmitigated": hhi_delta_unmitigated,
        "screen_result": screen_result,
        "required_divestiture_deposits_usd": required,
        "designated_divestiture_deposits_usd": designated,
        "hhi_post_mitigated": hhi_post_mitigated,
        "mitigation_satisfied": mitigation_satisfied,
    }


def recompute_analysis(analysis):
    """Recompute one analysis unless its application is already consummated."""
    application = db.applications.get(analysis["application_id"])
    market = db.markets.get(analysis["market_id"])
    if application is None or market is None:
        return
    if application["filing_status"] == "CONSUMMATED":
        return  # analyses are frozen at consummation (PRD 3.5)
    set_fields(analysis, **compute_analysis_figures(application, market))


def analyses_for_application(application_id):
    return [a for a in db.analyses.values() if a["application_id"] == application_id]


def recompute_analyses_for_market(market_id, application_id=None):
    """Recompute every analysis touching a market, then re-roll each posture."""
    touched_applications = set()
    for analysis in list(db.analyses.values()):
        if analysis["market_id"] != market_id:
            continue
        if application_id is not None and analysis["application_id"] != application_id:
            continue
        recompute_analysis(analysis)
        touched_applications.add(analysis["application_id"])
    for app_id in touched_applications:
        application = db.applications.get(app_id)
        if application is not None and application["filing_status"] != "CONSUMMATED":
            rollup_posture(application)


def rollup_posture(application):
    analyses = analyses_for_application(application["id"])
    if not analyses:
        posture = "NOT_ANALYZED"
    elif any(
        a["screen_result"] == "PRESUMPTIVE_VIOLATION" and not a["mitigation_satisfied"]
        for a in analyses
    ):
        posture = "BLOCKED"
    elif any(
        a["screen_result"] == "MITIGATION_REQUIRED" and not a["mitigation_satisfied"]
        for a in analyses
    ):
        posture = "MITIGATION_REQUIRED"
    elif any(a["screen_result"] != "PASS" for a in analyses):
        posture = "CLEARED_WITH_DIVESTITURE"
    else:
        posture = "CLEARED"
    set_fields(application, competitive_posture=posture)
    return posture


def overlap_market_ids(application):
    """Markets in which both parties hold at least one includable branch."""
    result = []
    for market in db.markets.values():
        totals = deposits_by_institution(market["id"])
        if totals.get(application["acquirer_id"], 0) > 0 and totals.get(
            application["target_id"], 0
        ) > 0:
            result.append(market["id"])
    return result


# --------------------------------------------------------------------------
# comment and protest counters (PRD 3.7)
# --------------------------------------------------------------------------
PROTEST_COUNTED_STATUSES = ("RECEIVED", "ACKNOWLEDGED", "RESPONDED")
UNRESOLVED_STATUSES = ("RECEIVED", "ACKNOWLEDGED")


def period_comments(period_id):
    return [c for c in db.comments.values() if c["period_id"] == period_id]


def application_periods(application_id):
    return [p for p in db.periods.values() if p["application_id"] == application_id]


def _is_substantive_protest(comment, statuses):
    return (
        comment["stance"] == "PROTEST"
        and bool(comment["substantive"])
        and comment["status"] in statuses
    )


def recompute_period_counters(period):
    comments = period_comments(period["id"])
    set_fields(
        period,
        comment_count=len(comments),
        substantive_protest_count=sum(
            1 for c in comments if _is_substantive_protest(c, PROTEST_COUNTED_STATUSES)
        ),
    )


def recompute_application_protest_counts(application):
    substantive = 0
    unresolved = 0
    for period in application_periods(application["id"]):
        for comment in period_comments(period["id"]):
            if _is_substantive_protest(comment, PROTEST_COUNTED_STATUSES):
                substantive += 1
            if _is_substantive_protest(comment, UNRESOLVED_STATUSES):
                unresolved += 1
    set_fields(
        application,
        substantive_protest_count=substantive,
        unresolved_protest_count=unresolved,
    )


# --------------------------------------------------------------------------
# related-record lookups
# --------------------------------------------------------------------------
def application_hearings(application_id):
    return [h for h in db.hearings.values() if h["application_id"] == application_id]


def has_pending_hearing(application_id, exclude_id=None):
    return any(
        h["status"] == "PENDING" and h["id"] != exclude_id
        for h in application_hearings(application_id)
    )


def granted_hearing_count(application_id):
    return sum(1 for h in application_hearings(application_id) if h["status"] == "GRANTED")


def application_decision(application_id):
    for decision in db.decisions.values():
        if decision["application_id"] == application_id:
            return decision
    return None


def decision_conditions(decision_id):
    return [c for c in db.conditions.values() if c["decision_id"] == decision_id]


def executed_plan(application_id):
    for plan in db.plans.values():
        if plan["application_id"] == application_id and plan["status"] == "EXECUTED":
            return plan
    return None


def plan_line_items(plan_id):
    return [li for li in db.line_items.values() if li["plan_id"] == plan_id]


def plan_reports(plan_id):
    return [r for r in db.reports.values() if r["plan_id"] == plan_id]


def current_schedule(application_id, basis):
    for schedule in db.schedules.values():
        if (
            schedule["application_id"] == application_id
            and schedule["basis"] == basis
            and schedule["status"] == "CURRENT"
        ):
            return schedule
    return None


def max_hhi_delta(application_id):
    deltas = [int(a["hhi_delta_unmitigated"]) for a in analyses_for_application(application_id)]
    return max(deltas) if deltas else 0
