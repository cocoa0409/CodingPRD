"""Stored-aggregate re-derivation (PRD 2.8: always re-run the defining query).

Each helper writes the aggregate onto its row and bumps that row's version, since
PRD 2.4 counts a server-initiated recompute as a mutation of the row it lands on.
"""

from decimal import Decimal

from store import D, ZERO, db, q2, q4, today, date_of, touch

from services import calc

CONFIRMED_LIKE = ("CONFIRMED", "AMENDED", "LOCKED")
ACTIVE_CAMPAIGN_POSTURES = ("OPEN", "SOLICITATION_CLOSED")
SUBMITTED_EVER = (
    "SUBMITTED",
    "UNDER_PANEL_REVIEW",
    "SUSPENDED_REVIEW",
    "PANEL_APPROVED",
    "PANEL_DECLINED",
    "AWARDED",
    "REPORTING",
    "CLOSED_SATISFIED",
)
AWARD_HOLDING = ("AWARDED", "REPORTING", "CLOSED_SATISFIED")


# --------------------------------------------------------------------------- #
# collection helpers
# --------------------------------------------------------------------------- #


def campaign_pledges(campaign_id):
    return [p for p in db.pledges.values() if p["campaign_id"] == campaign_id]


def pledge_lines(pledge_id):
    return [d for d in db.designations.values() if d["pledge_id"] == pledge_id]


def active_lines(pledge_id):
    return [d for d in pledge_lines(pledge_id) if d["status"] == "ACTIVE"]


def agency_reviews(agency_id):
    return [r for r in db.reviews.values() if r["agency_id"] == agency_id]


def agency_requests(agency_id):
    return [r for r in db.requests.values() if r["agency_id"] == agency_id]


def cycle_requests(cycle_id):
    return [r for r in db.requests.values() if r["cycle_id"] == cycle_id]


def request_scores(request_id):
    return [s for s in db.scores.values() if s["request_id"] == request_id]


def request_reports(request_id):
    return [r for r in db.reports.values() if r["request_id"] == request_id]


def cycle_assignments(cycle_id):
    return [a for a in db.assignments.values() if a["cycle_id"] == cycle_id]


def assignment_for(cycle_id, panelist_id):
    for row in db.assignments.values():
        if row["cycle_id"] == cycle_id and row["panelist_id"] == panelist_id:
            return row
    return None


# --------------------------------------------------------------------------- #
# Employer / CampaignCoordinator
# --------------------------------------------------------------------------- #


def recompute_employer_active_campaign_count(employer):
    count = 0
    for campaign in db.campaigns.values():
        if campaign["employer_id"] == employer["id"] and campaign["posture"] in ACTIVE_CAMPAIGN_POSTURES:
            count += 1
    employer["active_campaign_count"] = count
    touch("employer", employer)
    return employer


def recompute_coordinator_pledge_count(coordinator):
    if coordinator is None:
        return None
    count = 0
    for pledge in db.pledges.values():
        if (pledge.get("recorded_by_coordinator_id") == coordinator["id"]
                and pledge["designation_status"] in CONFIRMED_LIKE):
            count += 1
    coordinator["recorded_pledge_count"] = count
    touch("coordinator", coordinator)
    return coordinator


# --------------------------------------------------------------------------- #
# Campaign
# --------------------------------------------------------------------------- #


def recompute_campaign_totals(campaign):
    confirmed_gross = ZERO
    designated_gross = ZERO
    undesignated_gross = ZERO
    fee_total = ZERO
    for pledge in campaign_pledges(campaign["id"]):
        if pledge["designation_status"] not in CONFIRMED_LIKE:
            continue
        confirmed_gross = confirmed_gross + D(pledge["gross_amount"])
        undesignated_gross = undesignated_gross + D(pledge["undesignated_amount"])
        fee_total = fee_total + D(pledge["designation_fee_total"])
        for line in active_lines(pledge["id"]):
            designated_gross = designated_gross + D(line["designated_amount"])
    campaign["confirmed_gross_total"] = q2(confirmed_gross)
    campaign["designated_gross_total"] = q2(designated_gross)
    campaign["undesignated_gross_total"] = q2(undesignated_gross)
    campaign["designation_fee_total"] = q2(fee_total)
    touch("campaign", campaign)
    return campaign


def recompute_projected_payroll_total(campaign):
    total = ZERO
    for pledge in campaign_pledges(campaign["id"]):
        if (pledge["giving_method"] == "PAYROLL_DEDUCTION"
                and pledge["designation_status"] in ("CONFIRMED", "AMENDED")
                and pledge["collection_status"] in ("PENDING", "PARTIAL")):
            total = total + D(pledge["gross_amount"])
    campaign["projected_payroll_pledge_total"] = q2(total)
    return campaign


# --------------------------------------------------------------------------- #
# Agency
# --------------------------------------------------------------------------- #


def recompute_agency_passthrough(agency):
    total = ZERO
    for line in db.designations.values():
        if line["agency_id"] == agency["id"] and line["status"] == "ACTIVE":
            total = total + D(line["collected_designated_amount"])
    agency["designated_passthrough_ytd"] = q2(total)
    touch("agency", agency)
    return agency


def recompute_agency_passthrough_for_ids(agency_ids):
    seen = []
    for agency_id in agency_ids:
        if agency_id in seen:
            continue
        seen.append(agency_id)
        agency = db.agencies.get(agency_id)
        if agency is not None:
            recompute_agency_passthrough(agency)


def recompute_open_review_count(agency):
    count = 0
    for review in agency_reviews(agency["id"]):
        if review["status"] == "PENDING":
            count += 1
    agency["open_review_count"] = count
    return agency


def recompute_latest_standing_score(agency):
    certified = [r for r in agency_reviews(agency["id"]) if r["status"] == "CERTIFIED"]
    if not certified:
        agency["latest_standing_score"] = None
        return agency
    ordered = sorted(
        certified,
        key=lambda r: (r["fiscal_year"], r["created_at"], r["_seq"]),
        reverse=True,
    )
    agency["latest_standing_score"] = ordered[0]["certified_score"]
    return agency


def agency_is_delinquent(agency_id):
    """PRD 3.9 delinquency definition, evaluated against the logical clock date."""
    clock_date = today()
    for req in db.requests.values():
        if req["agency_id"] != agency_id:
            continue
        if req["status"] not in ("AWARDED", "REPORTING"):
            continue
        due = req.get("outcome_report_due_date")
        if due is None:
            continue
        if not (clock_date > date_of(due)):
            continue
        accepted = False
        for report in request_reports(req["id"]):
            if report["status"] == "ACCEPTED":
                accepted = True
                break
        if not accepted:
            return True
    return False


def recompute_agency_delinquency(agency, bump=True):
    value = agency_is_delinquent(agency["id"])
    changed = agency["outcome_report_delinquent"] != value
    agency["outcome_report_delinquent"] = value
    if bump or changed:
        touch("agency", agency)
    return changed


def recompute_all_agency_delinquency():
    """Clock moves re-derive delinquency; only rows whose flag actually changed
    are mutations (PRD 2.7)."""
    for agency in list(db.agencies.values()):
        recompute_agency_delinquency(agency, bump=False)


# --------------------------------------------------------------------------- #
# AllocationCycle
# --------------------------------------------------------------------------- #


def _cycle_counts(cycle):
    submitted = 0
    suspended = 0
    for req in cycle_requests(cycle["id"]):
        if req["status"] in SUBMITTED_EVER:
            submitted += 1
        if req["status"] == "SUSPENDED_REVIEW":
            suspended += 1
    cycle["submitted_request_count"] = submitted
    cycle["suspended_request_count"] = suspended
    if submitted == 0:
        cycle["suspended_request_ratio"] = Decimal("0.0000")
    else:
        cycle["suspended_request_ratio"] = q4(D(suspended) / D(submitted))
    return cycle["suspended_request_ratio"]


def recompute_cycle_counts(cycle):
    _cycle_counts(cycle)
    touch("cycle", cycle)
    return cycle


def recompute_cycle_pool(cycle):
    awarded = ZERO
    for req in cycle_requests(cycle["id"]):
        if req["status"] in AWARD_HOLDING and req.get("total_award") is not None:
            awarded = awarded + D(req["total_award"])
    cycle["awarded_total"] = q2(awarded)
    cycle["available_undesignated_pool"] = q2(D(cycle["opening_undesignated_pool"]) - awarded)
    touch("cycle", cycle)
    return cycle


def apply_restriction(cycle):
    """Probation cascade link 4: recount, then restrict at or above the ratio."""
    ratio = _cycle_counts(cycle)
    if cycle["posture"] == "OPEN" and ratio >= calc.CYCLE_RESTRICT_RATIO:
        cycle["posture"] = "RESTRICTED"
        cycle["awards_blocked"] = True
    touch("cycle", cycle)
    return cycle


def release_restriction(cycle):
    """Reinstatement reversal: recount, then release strictly below the ratio."""
    ratio = _cycle_counts(cycle)
    if cycle["posture"] == "RESTRICTED" and ratio < calc.CYCLE_RESTRICT_RATIO:
        cycle["posture"] = "OPEN"
        cycle["awards_blocked"] = False
    touch("cycle", cycle)
    return cycle


# --------------------------------------------------------------------------- #
# AllocationRequest / Panelist / PanelAssignment
# --------------------------------------------------------------------------- #


def eligible_score_pool(req):
    """Every score of the request whose author holds a conflict-free seat on the
    request's cycle (PRD 3.7). The trimmed `eligible` flag is not consulted."""
    pool = []
    for score in request_scores(req["id"]):
        seat = assignment_for(req["cycle_id"], score["panelist_id"])
        if seat is not None and not seat["conflict_declared"]:
            pool.append(score)
    return sorted(pool, key=lambda s: (s["created_at"], s["_seq"]))


def recompute_eligible_score_count(req):
    req["eligible_score_count"] = len(eligible_score_pool(req))
    return req


def recompute_panelist_counters(panelist):
    scores = 0
    for score in db.scores.values():
        if score["panelist_id"] == panelist["id"]:
            scores += 1
    visits = 0
    for report in db.reports.values():
        if report.get("site_visit_panelist_id") == panelist["id"]:
            visits += 1
    panelist["submitted_score_count"] = scores
    panelist["site_visit_count"] = visits
    touch("panelist", panelist)
    return panelist


def recompute_assignment_score_count(assignment):
    if assignment is None:
        return None
    count = 0
    for score in db.scores.values():
        if score["panelist_id"] != assignment["panelist_id"]:
            continue
        req = db.requests.get(score["request_id"])
        if req is not None and req["cycle_id"] == assignment["cycle_id"]:
            count += 1
    assignment["submitted_score_count"] = count
    touch("assignment", assignment)
    return assignment
