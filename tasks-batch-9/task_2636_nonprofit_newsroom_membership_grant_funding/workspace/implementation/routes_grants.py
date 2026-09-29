"""The grant pipeline: proposal development, award, release and reporting
(§3.7)."""

from flask import Blueprint

import calc
import derive
import guards
from core import (
    DB, ROLE_BOARD_OVERSIGHT, ROLE_DEVELOPMENT_OFFICER, ROLE_EDITORIAL_DIRECTOR,
    ROLE_FINANCE_CONTROLLER, acting_user, apply_changes, authenticate, body,
    check_bps_range, check_date_order, clock_date, fail, iso_date, iso_ms,
    list_response, lookup, lookup_fk, new_row, now_clock, object_response,
    pagination, paginate, parse_date, public, q_enum, q_str, round_half_up, rows,
    v_date, v_enum, v_int, v_str,
)
from routes_fiscal import finalize_create

bp = Blueprint("grants", __name__)

GRANT_READ_ROLES = (ROLE_DEVELOPMENT_OFFICER, ROLE_EDITORIAL_DIRECTOR,
                    ROLE_FINANCE_CONTROLLER, ROLE_BOARD_OVERSIGHT)
REPORT_READ_ROLES = (ROLE_DEVELOPMENT_OFFICER, ROLE_FINANCE_CONTROLLER,
                     ROLE_EDITORIAL_DIRECTOR, ROLE_BOARD_OVERSIGHT)

MIN_GRANT_CENTS = 100000
INSTITUTIONAL_TYPES = ("FOUNDATION", "GOVERNMENT")


def get_proposal(proposal_id):
    return lookup("grant_proposals", proposal_id, "ERR_GRANT_PROPOSAL_NOT_FOUND")


def get_report(report_id):
    return lookup("grant_reports", report_id, "ERR_GRANT_REPORT_NOT_FOUND")


# ---------------------------------------------------------------------------
# Drafting and reads
# ---------------------------------------------------------------------------

@bp.post("/grant-proposals")
def create_grant_proposal():
    authenticate(ROLE_DEVELOPMENT_OFFICER)
    data = body()
    funder = lookup_fk("funders", data.get("funder_id"), "ERR_FUNDER_NOT_FOUND")
    if funder is None:
        fail("ERR_INVALID_REQUEST", "funder_id is required")
    period = lookup_fk("fiscal_periods", data.get("fiscal_period_id"),
                       "ERR_FISCAL_PERIOD_NOT_FOUND")
    if period is None:
        fail("ERR_INVALID_REQUEST", "fiscal_period_id is required")
    area = lookup_fk("coverage_areas", data.get("coverage_area_id"),
                     "ERR_COVERAGE_AREA_NOT_FOUND")
    title = v_str(data, "title", min_len=1)
    requested_amount_cents = v_int(data, "requested_amount_cents",
                                   minimum=MIN_GRANT_CENTS)
    restriction_type = v_enum(data, "restriction_type", calc.RESTRICTION_TYPES)
    restriction_start_date = v_date(data, "restriction_start_date", required=False)
    restriction_end_date = v_date(data, "restriction_end_date", required=False)
    reporting_cadence = v_enum(data, "reporting_cadence", calc.REPORTING_CADENCES,
                               required=False, default="NONE")
    award_probability_bps = v_int(data, "award_probability_bps", required=False,
                                 default=5000)
    check_bps_range("award_probability_bps", award_probability_bps)
    check_date_order(restriction_start_date, restriction_end_date)
    if funder["funder_type"] not in INSTITUTIONAL_TYPES:
        fail("ERR_FUNDER_NOT_INSTITUTIONAL",
             "only a FOUNDATION or GOVERNMENT funder may be named on a grant")

    proposal = new_row("grant_proposals", {
        "funder_id": funder["id"],
        "coverage_area_id": area["id"] if area else None,
        "fiscal_period_id": period["id"],
        "title": title,
        "requested_amount_cents": requested_amount_cents,
        "restriction_type": restriction_type,
        "restriction_start_date": iso_date(restriction_start_date),
        "restriction_end_date": iso_date(restriction_end_date),
        "reporting_cadence": reporting_cadence,
        "award_probability_bps": award_probability_bps,
        "status": "DRAFT",
        "revision_round_count": 0,
        "awarded_amount_cents": 0,
        "released_cents": 0,
        "unreleased_cents": 0,
        "returned_cents": 0,
        "compliance_flag": "COMPLIANT",
        "award_date": None,
        "report_count": 0,
        "drafted_by_user_id": acting_user(),
        "cleared_by_user_id": None,
        "suspended_reason": None,
    })
    return object_response(public(proposal), 201)


@bp.get("/grant-proposals/<proposal_id>")
def read_grant_proposal(proposal_id):
    authenticate(*GRANT_READ_ROLES)
    return object_response(public(get_proposal(proposal_id)))


@bp.get("/grant-proposals")
def list_grant_proposals():
    authenticate(*GRANT_READ_ROLES)
    funder_id = q_str("funder_id")
    area_id = q_str("coverage_area_id")
    period_id = q_str("fiscal_period_id")
    status = q_enum("status", calc.PROPOSAL_STATUSES)
    compliance_flag = q_enum("compliance_flag", calc.COMPLIANCE_FLAGS)
    limit, offset = pagination()
    items = []
    for proposal in rows("grant_proposals"):
        if funder_id is not None and proposal["funder_id"] != funder_id:
            continue
        if area_id is not None and proposal["coverage_area_id"] != area_id:
            continue
        if period_id is not None and proposal["fiscal_period_id"] != period_id:
            continue
        if status is not None and proposal["status"] != status:
            continue
        if compliance_flag is not None and proposal["compliance_flag"] != compliance_flag:
            continue
        items.append(proposal)
    page, total = paginate(items, limit, offset)
    return list_response([public(p) for p in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Development-side pipeline moves
# ---------------------------------------------------------------------------

PIPELINE_SOURCES = {
    "SUBMIT_FOR_REVIEW": ("DRAFT", "REVISION_REQUESTED"),
    "REVISE": ("REVISION_REQUESTED",),
    "SUBMIT": ("CLEARED",),
    "WITHDRAW": ("DRAFT", "INDEPENDENCE_REVIEW", "REVISION_REQUESTED", "CLEARED",
                 "SUBMITTED"),
}


@bp.post("/grant-proposals/<proposal_id>/pipeline-actions")
def grant_pipeline_actions(proposal_id):
    authenticate(ROLE_DEVELOPMENT_OFFICER)
    proposal = get_proposal(proposal_id)
    data = body()
    action = v_enum(data, "action", tuple(PIPELINE_SOURCES))
    funder = DB["funders"].get(proposal["funder_id"])
    period = DB["fiscal_periods"].get(proposal["fiscal_period_id"])
    restricted = calc.is_restricted_scope(proposal["restriction_type"])

    guards.require_not_terminal(proposal["status"], calc.PROPOSAL_TERMINAL,
                                "grant proposal")
    guards.require_state(proposal["status"], PIPELINE_SOURCES[action],
                         "grant proposal")

    if action == "SUBMIT_FOR_REVIEW":
        if restricted and (proposal["coverage_area_id"] is None
                           or proposal["restriction_start_date"] is None
                           or proposal["restriction_end_date"] is None):
            fail("ERR_INVALID_REQUEST",
                 "a restricted proposal needs a coverage area and a restriction window")
        apply_changes(proposal, {"status": "INDEPENDENCE_REVIEW"}, force=True)
    elif action == "REVISE":
        apply_changes(proposal, {"status": "DRAFT"}, force=True)
    elif action == "SUBMIT":
        if funder is not None:
            guards.require_funder_not_restricted(funder)
        if restricted:
            guards.require_publication_gate_open(proposal["coverage_area_id"])
        if funder is not None:
            guards.require_cooling_off(proposal, funder)
        guards.require_period_open(period)
        apply_changes(proposal, {"status": "SUBMITTED"}, force=True)
    else:
        apply_changes(proposal, {"status": "WITHDRAWN"}, force=True)
        if period is not None:
            derive.recompute_period(period)
    return object_response(public(proposal))


@bp.post("/grant-proposals/<proposal_id>/internal-review")
def grant_internal_review(proposal_id):
    authenticate(ROLE_EDITORIAL_DIRECTOR)
    proposal = get_proposal(proposal_id)
    data = body()
    decision = v_enum(data, "decision", ("CLEAR", "REQUEST_REVISION"))
    v_str(data, "review_note", required=False, default=None, min_len=0)
    funder = DB["funders"].get(proposal["funder_id"])
    restricted = calc.is_restricted_scope(proposal["restriction_type"])

    guards.require_not_terminal(proposal["status"], calc.PROPOSAL_TERMINAL,
                                "grant proposal")
    guards.require_state(proposal["status"], ("INDEPENDENCE_REVIEW",),
                         "grant proposal")
    guards.require_dual_control(proposal.get("drafted_by_user_id"))

    if decision == "CLEAR":
        guards.require_funder_cleared(funder or {})
        guards.require_risk_below_hard_bar(int(funder["independence_risk_score"]))
        if restricted:
            guards.require_active_disclosure(proposal["funder_id"],
                                             proposal["coverage_area_id"])
            guards.require_no_stale_disclosure(proposal["funder_id"],
                                               proposal["coverage_area_id"])
        apply_changes(proposal, {
            "status": "CLEARED",
            "cleared_by_user_id": acting_user(),
        }, force=True)
    else:
        if int(proposal["revision_round_count"]) >= calc.MAX_REVISION_ROUNDS:
            fail("ERR_REVISION_ROUNDS_EXHAUSTED",
                 "the proposal has already used %s revision rounds"
                 % proposal["revision_round_count"])
        apply_changes(proposal, {
            "status": "REVISION_REQUESTED",
            "revision_round_count": int(proposal["revision_round_count"]) + 1,
        }, force=True)
    return object_response(public(proposal))


# ---------------------------------------------------------------------------
# Recording the funder's decision
# ---------------------------------------------------------------------------

def generate_report_obligations(proposal, period, award_date):
    """The award generates a contiguous series of reporting periods, then
    allocates release capacity across them."""
    if calc.is_restricted_scope(proposal["restriction_type"]):
        window_start = parse_date(proposal["restriction_start_date"])
        window_end = parse_date(proposal["restriction_end_date"])
    else:
        window_start = award_date
        window_end = parse_date(period["end_date"]) if period else None
    schedule = calc.report_obligation_schedule(window_start, window_end,
                                               proposal["reporting_cadence"])
    for entry in schedule:
        new_row("grant_reports", {
            "grant_proposal_id": proposal["id"],
            "sequence_no": entry["sequence_no"],
            "period_start": iso_date(entry["period_start"]),
            "period_end": iso_date(entry["period_end"]),
            "due_date": iso_date(entry["due_date"]),
            "status": "SCHEDULED",
            "allocated_release_cents": 0,
            "consumed_release_cents": 0,
            "spend_reported_cents": None,
            "variance_bps": None,
            "submitted_at": None,
        })
    return len(schedule)


def overlapping_awarded_count(proposal):
    start = parse_date(proposal.get("restriction_start_date"))
    end = parse_date(proposal.get("restriction_end_date"))
    count = 0
    for other in rows("grant_proposals"):
        if other["id"] == proposal["id"]:
            continue
        if other.get("coverage_area_id") != proposal.get("coverage_area_id"):
            continue
        if other.get("status") != "AWARDED":
            continue
        if calc.windows_overlap(start, end,
                                parse_date(other.get("restriction_start_date")),
                                parse_date(other.get("restriction_end_date"))):
            count += 1
    return count


@bp.post("/grant-proposals/<proposal_id>/record-outcome")
def grant_record_outcome(proposal_id):
    authenticate(ROLE_DEVELOPMENT_OFFICER)
    proposal = get_proposal(proposal_id)
    data = body()
    outcome = v_enum(data, "outcome", ("AWARDED", "DECLINED"))
    awarded_amount_cents = v_int(data, "awarded_amount_cents", required=False)
    award_date = v_date(data, "award_date", required=False)
    funder = DB["funders"].get(proposal["funder_id"])
    period = DB["fiscal_periods"].get(proposal["fiscal_period_id"])
    restricted = calc.is_restricted_scope(proposal["restriction_type"])

    if outcome == "AWARDED":
        if (awarded_amount_cents is None or awarded_amount_cents < 1
                or awarded_amount_cents > int(proposal["requested_amount_cents"])):
            fail("ERR_AWARD_AMOUNT_INVALID",
                 "awarded_amount_cents must be between 1 and requested_amount_cents")
        if award_date is None:
            fail("ERR_AWARD_AMOUNT_INVALID", "award_date is required for an award")
        if period is not None:
            start = parse_date(period["start_date"])
            end = parse_date(period["end_date"])
            if start is not None and end is not None and not (start <= award_date <= end):
                fail("ERR_AWARD_AMOUNT_INVALID",
                     "award_date must fall inside the fiscal period")

    guards.require_period_open(period)
    guards.require_not_terminal(proposal["status"], calc.PROPOSAL_TERMINAL,
                                "grant proposal")
    guards.require_state(proposal["status"], ("SUBMITTED",), "grant proposal")

    if outcome == "DECLINED":
        apply_changes(proposal, {"status": "DECLINED"}, force=True)
        if period is not None:
            derive.recompute_period(period)
        return object_response(public(proposal))

    if funder is not None:
        guards.require_funder_not_restricted(funder)
        guards.require_cooling_off(proposal, funder)
    if restricted:
        if overlapping_awarded_count(proposal) >= calc.MAX_RESTRICTED_GRANTS_PER_AREA:
            fail("ERR_RESTRICTED_GRANT_CAP_EXCEEDED",
                 "the beat already carries %s overlapping awarded grants"
                 % calc.MAX_RESTRICTED_GRANTS_PER_AREA)

    report_count = generate_report_obligations(proposal, period, award_date)
    apply_changes(proposal, {
        "status": "AWARDED",
        "awarded_amount_cents": awarded_amount_cents,
        "award_date": iso_date(award_date),
        "released_cents": 0,
        "unreleased_cents": awarded_amount_cents,
        "returned_cents": 0,
        "report_count": report_count,
    }, force=True)
    derive.reallocate_release_buckets(proposal)
    if funder is not None:
        derive.recompute_funder(funder)
    area = DB["coverage_areas"].get(proposal["coverage_area_id"])
    if area is not None:
        derive.recompute_coverage_area(area)
    if period is not None:
        derive.recompute_period(period)
    return object_response(public(proposal))


# ---------------------------------------------------------------------------
# Releasing restricted principal
# ---------------------------------------------------------------------------

@bp.post("/grant-proposals/<proposal_id>/release-restricted-funds")
def grant_release_restricted_funds(proposal_id):
    authenticate(ROLE_FINANCE_CONTROLLER)
    proposal = get_proposal(proposal_id)
    data = body()
    request_amount_cents = v_int(data, "request_amount_cents", minimum=1)
    period = DB["fiscal_periods"].get(proposal["fiscal_period_id"])

    guards.require_period_open(period)
    guards.require_not_terminal(proposal["status"], calc.PROPOSAL_TERMINAL,
                                "grant proposal")
    guards.require_state(proposal["status"], ("AWARDED",), "grant proposal")

    cap_bps = int(period["restricted_release_cap_pct_bps"]) if period else 0
    if cap_bps <= 0:
        fail("ERR_POSTURE_BLOCKS_RELEASE",
             "the fiscal period's sustainability posture blocks any release")
    if cap_bps != 10000:
        # Skipped entirely at a HEALTHY posture, where the cap equals the whole
        # unreleased principal and the waterfall guard binds instead.
        allowed = round_half_up(int(proposal["unreleased_cents"]) * cap_bps, 10000)
        if request_amount_cents > allowed:
            fail("ERR_RELEASE_CAP_EXCEEDED",
                 "the release cap allows at most %s cents" % allowed)
    if request_amount_cents > derive.release_capacity(proposal):
        fail("ERR_RELEASE_EXCEEDS_AWARD",
             "the request exceeds the unconsumed release buckets")
    if proposal["compliance_flag"] != "COMPLIANT":
        fail("ERR_PROPOSAL_DELINQUENT", "the proposal is DELINQUENT")

    derive.consume_release(proposal, request_amount_cents)
    released = int(proposal["released_cents"]) + request_amount_cents
    apply_changes(proposal, {
        "released_cents": released,
        "unreleased_cents": (int(proposal["awarded_amount_cents"]) - released
                             - int(proposal["returned_cents"])),
    }, force=True)
    if period is not None:
        derive.recompute_period(period, balance_delta=request_amount_cents)
    return object_response(public(proposal))


@bp.post("/grant-proposals/<proposal_id>/reinstate")
def grant_reinstate(proposal_id):
    authenticate(ROLE_FINANCE_CONTROLLER)
    proposal = get_proposal(proposal_id)
    body()
    funder = DB["funders"].get(proposal["funder_id"])
    period = DB["fiscal_periods"].get(proposal["fiscal_period_id"])

    guards.require_not_terminal(proposal["status"], calc.PROPOSAL_TERMINAL,
                                "grant proposal")
    guards.require_state(proposal["status"], ("SUSPENDED",), "grant proposal")
    guards.require_funder_cleared(funder or {})
    if calc.is_restricted_scope(proposal["restriction_type"]):
        guards.require_publication_gate_open(proposal["coverage_area_id"])
    if proposal["compliance_flag"] != "COMPLIANT":
        fail("ERR_PROPOSAL_DELINQUENT", "the proposal is still DELINQUENT")

    returned = int(proposal["returned_cents"])
    for report in derive.proposal_reports_ordered(proposal["id"]):
        apply_changes(report, {"consumed_release_cents": 0})
    apply_changes(proposal, {
        "status": "AWARDED",
        "unreleased_cents": int(proposal["unreleased_cents"]) + returned,
        "returned_cents": 0,
        "suspended_reason": None,
    }, force=True)
    derive.reallocate_release_buckets(proposal)
    area = DB["coverage_areas"].get(proposal["coverage_area_id"])
    if area is not None:
        derive.recompute_coverage_area(area)
    if period is not None:
        derive.recompute_period(period)
    return object_response(public(proposal))


@bp.post("/grant-proposals/<proposal_id>/close")
def grant_close(proposal_id):
    authenticate(ROLE_FINANCE_CONTROLLER)
    proposal = get_proposal(proposal_id)
    data = body()
    closure_justification = v_str(data, "closure_justification", required=False,
                                  default=None, min_len=0)
    period = DB["fiscal_periods"].get(proposal["fiscal_period_id"])

    guards.require_not_terminal(proposal["status"], calc.PROPOSAL_TERMINAL,
                                "grant proposal")
    guards.require_state(proposal["status"], ("AWARDED",), "grant proposal")
    reports = derive.proposal_reports_ordered(proposal["id"])
    for report in reports:
        if report["status"] not in ("ACCEPTED", "SCHEDULED", "WAIVED"):
            fail("ERR_INVALID_STATE",
                 "report %s is %s and blocks closure"
                 % (report["sequence_no"], report["status"]))
    unreleased = int(proposal["unreleased_cents"])
    if unreleased != 0 and not closure_justification:
        fail("ERR_INVALID_REQUEST",
             "closure_justification is required while unreleased principal remains")

    for report in reports:
        if report["status"] == "SCHEDULED":
            apply_changes(report, {"status": "WAIVED"})
    apply_changes(proposal, {
        "status": "CLOSED",
        "unreleased_cents": 0,
        "returned_cents": int(proposal["returned_cents"]) + unreleased,
    }, force=True)
    area = DB["coverage_areas"].get(proposal["coverage_area_id"])
    if area is not None:
        derive.recompute_coverage_area(area)
    if period is not None:
        derive.recompute_period(period)
    return object_response(public(proposal))


# ---------------------------------------------------------------------------
# Reporting obligations
# ---------------------------------------------------------------------------

@bp.get("/grant-proposals/<proposal_id>/reports")
def list_proposal_reports(proposal_id):
    authenticate(*REPORT_READ_ROLES)
    proposal = get_proposal(proposal_id)
    status = q_enum("status", calc.REPORT_STATUSES)
    limit, offset = pagination()
    items = [r for r in derive.proposal_reports_ordered(proposal["id"])
             if status is None or r["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([public(r) for r in page], total, limit, offset)


@bp.get("/grant-reports/<report_id>")
def read_grant_report(report_id):
    authenticate(*REPORT_READ_ROLES)
    return object_response(public(get_report(report_id)))


@bp.get("/grant-reports")
def list_grant_reports():
    authenticate(*REPORT_READ_ROLES)
    proposal_id = q_str("grant_proposal_id")
    status = q_enum("status", calc.REPORT_STATUSES)
    limit, offset = pagination()
    items = []
    for report in rows("grant_reports"):
        if proposal_id is not None and report["grant_proposal_id"] != proposal_id:
            continue
        if status is not None and report["status"] != status:
            continue
        items.append(report)
    items.sort(key=lambda r: (r["due_date"], r["_seq"]))
    page, total = paginate(items, limit, offset)
    return list_response([public(r) for r in page], total, limit, offset)


@bp.post("/grant-reports/<report_id>/submit")
def submit_grant_report(report_id):
    authenticate(ROLE_DEVELOPMENT_OFFICER)
    report = get_report(report_id)
    data = body()
    spend_reported_cents = v_int(data, "spend_reported_cents", minimum=0)
    proposal = DB["grant_proposals"].get(report["grant_proposal_id"])
    consumed = int(report["consumed_release_cents"] or 0)

    if spend_reported_cents > consumed:
        fail("ERR_SPEND_EXCEEDS_RELEASE",
             "the declared spend exceeds the %s cents released against this report"
             % consumed)
    guards.require_not_terminal(report["status"], calc.REPORT_TERMINAL,
                                "grant report")
    guards.require_state(report["status"], ("SCHEDULED", "OVERDUE", "RETURNED"),
                         "grant report")
    if proposal is None or proposal["status"] not in ("AWARDED", "SUSPENDED"):
        fail("ERR_INVALID_STATE",
             "the proposal must be AWARDED or SUSPENDED to accept a report")
    for other in derive.proposal_reports_ordered(proposal["id"]):
        if int(other["sequence_no"]) >= int(report["sequence_no"]):
            continue
        if other["status"] not in ("ACCEPTED", "WAIVED"):
            fail("ERR_REPORT_SEQUENCE_VIOLATION",
                 "report %s must be accepted or waived first" % other["sequence_no"])
    period_end = parse_date(report["period_end"])
    if period_end is not None and clock_date() < period_end:
        fail("ERR_REPORT_PERIOD_NOT_ELAPSED",
             "the reporting period ends on %s" % report["period_end"])

    variance_bps = 0
    if consumed != 0:
        variance_bps = round_half_up(10000 * (spend_reported_cents - consumed),
                                     consumed)
    apply_changes(report, {
        "status": "SUBMITTED",
        "spend_reported_cents": spend_reported_cents,
        "variance_bps": variance_bps,
        "submitted_at": iso_ms(now_clock()),
    }, force=True)
    return object_response(public(report))


@bp.post("/grant-reports/<report_id>/review")
def review_grant_report(report_id):
    authenticate(ROLE_FINANCE_CONTROLLER)
    report = get_report(report_id)
    data = body()
    decision = v_enum(data, "decision", ("ACCEPT", "RETURN"))
    v_str(data, "review_note", required=False, default=None, min_len=0)
    proposal = DB["grant_proposals"].get(report["grant_proposal_id"])

    guards.require_not_terminal(report["status"], calc.REPORT_TERMINAL,
                                "grant report")
    guards.require_state(report["status"], ("SUBMITTED",), "grant report")

    if decision == "ACCEPT":
        if abs(int(report["variance_bps"] or 0)) > calc.MAX_ACCEPTABLE_VARIANCE_BPS:
            fail("ERR_VARIANCE_UNACCEPTABLE",
                 "variance_bps %s exceeds the tolerance of %s"
                 % (report["variance_bps"], calc.MAX_ACCEPTABLE_VARIANCE_BPS))
        apply_changes(report, {"status": "ACCEPTED"}, force=True)
    else:
        apply_changes(report, {
            "status": "RETURNED",
            "spend_reported_cents": None,
            "variance_bps": None,
        }, force=True)
    if proposal is not None:
        derive.recompute_proposal_compliance(proposal)
    return object_response(public(report))
