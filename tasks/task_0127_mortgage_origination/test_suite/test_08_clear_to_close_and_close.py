"""Clear-to-close and close transitions, TRID gating, UDAAP gating,
and validation-priority ordering (PRD §3.10, §2.10).

Covers difficulty design instances:
- priority_pair_validation_conflict/state_vs_business_temporal_pair
- priority_pair_validation_conflict/business_safety_vs_business_fiscal_pair
- cross_entity_state_dependency/loan_application_clear_to_close_depends_on_title_search
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    create_and_pre_qualify,
    create_and_verify_asset,
    create_and_verify_income,
    iso_plus,
    issue_closing_disclosure,
    issue_loan_estimate,
    make_compliance_headers,
    order_and_complete_appraisal,
    order_and_complete_title_search,
    place_rate_lock,
    setup_application_in_conditional_approval,
    setup_application_in_underwriting,
    setup_application_ready_for_clear_to_close,
    setup_closed_application,
    submit_underwriting,
    submit_udaap,
    submit_udaap_pass,
    underwrite_approve,
    underwrite_decision_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Clear-to-close happy path — PRD §3.10
# ===========================================================================
def test_clear_to_close_happy_path(api, loan_officer_headers):
    """PRD §3.10: "Once an application is in CONDITIONAL_APPROVAL, the
    loan officer moves it to CLEAR_TO_CLOSE after five preconditions
    are met: a CLOSING_DISCLOSURE exists in ISSUED or ACKNOWLEDGED;
    SystemClock.now is no earlier than that disclosure's
    eligible_to_consummate_at (the TRID 3-business-day waiting period
    has elapsed); an active RateLock exists in LOCKED or EXTENDED whose
    lock_expires_at is strictly later than SystemClock.now; the
    TitleSearch is in CLEAR or RESOLVED; and a UDAAPReview with outcome
    of PASS exists on the latest CLOSING_DISCLOSURE version."

    Claim: with all five preconditions satisfied, clear-to-close
    advances the state to CLEAR_TO_CLOSE and stamps
    closing_eligible_at.
    """
    _, app, _, _, _ = setup_application_ready_for_clear_to_close(
        clock_anchor="2026-03-02T10:00:00.000Z",
    )
    res = api.clear_to_close(app["id"], None, loan_officer_headers)
    out = validate_success(res, 200)
    assert out["status"] == "CLEAR_TO_CLOSE"
    assert isinstance(out.get("closing_eligible_at"), str)


def test_clear_to_close_missing_udaap_pass_rejected(
    api, loan_officer_headers,
):
    """PRD §3.10: "a UDAAPReview with outcome of PASS exists on the
    latest CLOSING_DISCLOSURE version. ... a missing or non-PASS UDAAP
    surfaces as ERR_UDAAP_REVIEW_REQUIRED"

    Claim: build the application through to a CD-issued / ACK'd /
    TRID-elapsed state but submit a FLAG UDAAP (not PASS) on the CD;
    clear-to-close must fail with ERR_UDAAP_REVIEW_REQUIRED.

    NOTE: the default setup_application_ready_for_clear_to_close
    submits a PASS UDAAP after the CD. To exercise the failure path we
    construct the scenario manually.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    borrower, app, _, _ = setup_application_in_conditional_approval(
        clock_anchor="2026-03-02T10:00:00.000Z",
    )
    place_rate_lock(
        app["id"], locked_rate_bps=650, headers=loan_officer_headers,
    )
    cd = issue_closing_disclosure(
        app["id"], apr_bps=650, headers=loan_officer_headers,
    )
    # Submit FLAG UDAAP on the CD (not PASS).
    submit_udaap(
        app["id"], outcome="FLAG", notes="missing fee disclosure",
    )
    # Advance clock past the TRID window.
    advance_clock(iso_plus(cd["issued_at"], days=7))
    res = api.clear_to_close(app["id"], None, loan_officer_headers)
    validate_error(
        res,
        ApiErrorId.ERR_UDAAP_REVIEW_REQUIRED.value,
        expected_status=409,
    )


def test_clear_to_close_sod_violation_loan_officer_is_reviewer(
    api,
):
    """PRD §2.1: "on underwrite-decision and on clear-to-close, the
    actor's X-User-ID must not equal the compliance_reviewer_id
    recorded on the application. Violations are rejected with
    ERR_UDAAP_SOD_VIOLATION."

    Claim: when the acting X-User-ID equals the application's
    compliance_reviewer_id, clear-to-close is rejected with
    ERR_UDAAP_SOD_VIOLATION (403).
    """
    # Use a distinct compliance reviewer id so we can both (a) drive
    # the workflow as 'lo-001' and (b) then attack with that same id
    # acting as compliance.
    _, app, _, _, _ = setup_application_ready_for_clear_to_close(
        clock_anchor="2026-03-02T10:00:00.000Z",
        compliance_reviewer_id="co-001",
    )
    # Now act as the compliance officer (X-User-ID=co-001) attempting
    # clear-to-close.
    bad_headers = make_compliance_headers("co-001")
    res = api.clear_to_close(app["id"], None, bad_headers)
    # Note: the role on this request is ComplianceOfficer, not
    # LoanOfficer. PRD §4: clear-to-close is exclusive to LoanOfficer.
    # PRD §2.10: role checks (priority 2) come before SoD (priority 6).
    # So this request actually returns ERR_FORBIDDEN_ROLE.
    validate_error(
        res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403,
    )


def test_clear_to_close_sod_violation_same_loan_officer_role(api):
    """PRD §2.1: "on underwrite-decision and on clear-to-close, the
    actor's X-User-ID must not equal the compliance_reviewer_id
    recorded on the application. Violations are rejected with
    ERR_UDAAP_SOD_VIOLATION."

    Claim: pass X-User-Role=LoanOfficer AND X-User-ID equals the
    compliance_reviewer_id (a previously-recorded review assignment) ->
    ERR_UDAAP_SOD_VIOLATION (403).
    """
    from test_helpers import make_loan_officer_headers
    _, app, _, _, _ = setup_application_ready_for_clear_to_close(
        clock_anchor="2026-03-02T10:00:00.000Z",
        compliance_reviewer_id="co-001",
    )
    # X-User-ID = co-001 (same as compliance_reviewer_id) with
    # X-User-Role=LoanOfficer.
    sod_headers = make_loan_officer_headers("co-001")
    res = api.clear_to_close(app["id"], None, sod_headers)
    validate_error(
        res,
        ApiErrorId.ERR_UDAAP_SOD_VIOLATION.value,
        expected_status=403,
    )


# ===========================================================================
# State vs TRID priority — PRD §2.10
# difficulty: priority_pair_validation_conflict/state_vs_business_temporal_pair
# ===========================================================================
def test_clear_to_close_state_check_precedes_trid(api, loan_officer_headers):
    """PRD §2.10: "After authentication, existence checks run in path
    order — first the parent LoanApplication, then any nested
    resource. State-machine checks (whether the source state matches
    the transition's from) precede business-rule checks."
    PRD §2.10 ordering: state (priority 5) precedes business_temporal
    (TRID waiting at priority 8).

    Claim: when an application is in INTAKE (wrong source state) AND
    no CD exists (TRID would also fail), clear-to-close returns
    ERR_INVALID_STATE (state check at priority 5) — NOT
    ERR_TRID_WAITING_PERIOD.

    # difficulty: priority_pair_validation_conflict/state_vs_business_temporal_pair
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify()
    # app is in PRE_QUALIFIED after the pre-qualify call; bring it back
    # to INTAKE by creating a fresh application without pre-qualifying.
    from test_helpers import create_borrower_and_application
    _, intake_app = create_borrower_and_application()
    assert intake_app["status"] == "INTAKE"
    res = api.clear_to_close(intake_app["id"], None, loan_officer_headers)
    validate_error(
        res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409,
    )


# ===========================================================================
# business_safety (SoD) vs business_fiscal (DTI) priority — PRD §2.10
# difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_pair
# ===========================================================================
def test_underwrite_decision_sod_precedes_fiscal_check(api):
    """PRD §2.10: "Among the business-safety rules,
    segregation-of-duties is checked before the UDAAP-review-required
    check".
    PRD §2.10: "Fiscal-ratio checks (DTI and LTV ceilings at the
    approve decision) are the lowest-priority business checks before
    generic body schema validation".
    PRD §2.10: "The practical consequence is that, for example, an
    underwrite-decision request from a user who is also the compliance
    reviewer surfaces as ERR_UDAAP_SOD_VIOLATION rather than as a
    downstream DTI/LTV failure, even if the DTI would also have
    failed."

    Claim: a LoanOfficer call (X-User-Role=LoanOfficer) with
    X-User-ID == compliance_reviewer_id on an application whose
    LTV > 0.97 (a fiscal failure that would otherwise trigger
    ERR_LTV_EXCEEDED) surfaces as ERR_UDAAP_SOD_VIOLATION (priority 6)
    rather than ERR_LTV_EXCEEDED (priority 17).

    Setup: requested=$380k, appraised=$390k, sale=$400k
       -> value_basis = min(400, 390) = 390; ltv = 380/390 = 0.9744 > 0.97.

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_pair
    """
    from test_helpers import make_loan_officer_headers
    _, app, _, _ = setup_application_in_underwriting(
        clock_anchor="2026-03-02T10:00:00.000Z",
        annual_income_cents=15_000_000,
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=38_000_000,
        appraised_value_cents=39_000_000,
        compliance_reviewer_id="co-001",
    )
    # PASS UDAAP first so the UDAAP-required check (priority 7) does
    # not preempt the SoD check (priority 6).
    submit_udaap_pass(app["id"], compliance_officer_id="co-001")

    # Act with X-User-Role=LoanOfficer AND X-User-ID=co-001 (the
    # compliance_reviewer_id). LTV would fail (0.9744 > 0.97) but PRD
    # §2.10 priority puts SoD (P6) ahead of LTV (P17).
    sod_headers = make_loan_officer_headers("co-001")
    res = api.underwrite_decision(
        app["id"],
        underwrite_decision_payload(decision="APPROVE"),
        sod_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_UDAAP_SOD_VIOLATION.value,
        expected_status=403,
    )


# ===========================================================================
# Cross-entity dependency: clear-to-close ↔ TitleSearch
# difficulty: cross_entity_state_dependency/loan_application_clear_to_close_depends_on_title_search
# ===========================================================================
# NOTE: PRD §3.4 defines the TitleSearch state machine as
#   ORDERED -> CLEAR (terminal)  | ISSUES_FOUND -> RESOLVED (terminal).
# There is no backward transition out of CLEAR or RESOLVED. PRD §3.7
# requires title in CLEAR or RESOLVED at submit-underwriting (a
# precondition for UNDERWRITING / CONDITIONAL_APPROVAL). Therefore an
# application that has reached CONDITIONAL_APPROVAL cannot have its
# TitleSearch in ISSUES_FOUND. The clear-to-close title precondition
# "in CLEAR or RESOLVED" is structurally vacuous: any CONDITIONAL_-
# APPROVAL-bound application's title is already CLEAR or RESOLVED.
#
# The companion test that asserted "title-in-ISSUES_FOUND blocks
# clear-to-close" was deleted: the scenario is unreachable under PRD-
# faithful operation (Cardinal Rule: STEP 1b unique derivability
# fails — there is no PRD-faithful path to that state).


def test_clear_to_close_after_title_resolve_succeeds(api, loan_officer_headers):
    """PRD §3.10: "the TitleSearch is in CLEAR or RESOLVED"
    PRD §3.4: "A title search in ISSUES_FOUND can subsequently be
    resolved by the loan officer ... at which point status becomes
    RESOLVED".

    Claim: clear-to-close accepts TitleSearch in RESOLVED (the
    alternative to CLEAR). The setup drives the title through
    ISSUES_FOUND -> RESOLVED *before* submit-underwriting (since
    submit-underwriting itself requires title in CLEAR or RESOLVED per
    PRD §3.7), then completes the workflow.

    # difficulty: cross_entity_state_dependency/loan_application_clear_to_close_depends_on_title_search
    """
    from test_helpers import (
        acknowledge_disclosure,
        create_and_pre_qualify,
        create_and_verify_asset,
        create_and_verify_income,
        get_loan_application,
        issue_loan_estimate,
        order_and_complete_appraisal,
        submit_underwriting,
        underwrite_approve,
    )
    advance_clock("2026-03-02T10:00:00.000Z")
    borrower, app = create_and_pre_qualify(headers=loan_officer_headers)
    create_and_verify_income(app["id"], headers=loan_officer_headers)
    create_and_verify_asset(app["id"], headers=loan_officer_headers)
    order_and_complete_appraisal(
        app["id"], appraised_value_cents=40_000_000,
        headers=loan_officer_headers,
    )
    # Complete title with defects -> ISSUES_FOUND, then resolve ->
    # RESOLVED (a terminal acceptable state for underwriting per §3.7).
    from test_helpers import api_client as _api
    _api.order_title_search(app["id"], None, loan_officer_headers)
    _api.complete_title_search(
        app["id"], {"defects_found": ["lien"]}, loan_officer_headers,
    )
    validate_success(
        api.resolve_title_search(app["id"], None, loan_officer_headers),
        200,
    )
    # Now title is RESOLVED — drive the rest of the workflow.
    issue_loan_estimate(
        app["id"], apr_bps=650, headers=loan_officer_headers,
    )
    submit_underwriting(app["id"], headers=loan_officer_headers)
    submit_udaap_pass(app["id"])
    underwrite_approve(app["id"], headers=loan_officer_headers)
    place_rate_lock(
        app["id"], locked_rate_bps=650, headers=loan_officer_headers,
    )
    cd = issue_closing_disclosure(
        app["id"], apr_bps=650, headers=loan_officer_headers,
    )
    app_state = get_loan_application(
        app["id"], headers=loan_officer_headers,
    )
    acknowledge_disclosure(app["id"], cd["id"], app_state["borrower_id"])
    submit_udaap_pass(app["id"])
    advance_clock(iso_plus(cd["issued_at"], days=7))
    res = api.clear_to_close(app["id"], None, loan_officer_headers)
    out = validate_success(res, 200)
    assert out["status"] == "CLEAR_TO_CLOSE"


# ===========================================================================
# Close — PRD §3.10
# ===========================================================================
def test_close_happy_path_cascades_rate_lock_to_consumed(
    api, loan_officer_headers,
):
    """PRD §3.10: "Closing the application transitions status from
    CLEAR_TO_CLOSE to CLOSED. ... On a successful close the system
    cascades the RateLock to CONSUMED and ensures the latest
    CLOSING_DISCLOSURE has been marked ACKNOWLEDGED if it was not
    already."

    Claim: after /close, application.status=CLOSED and RateLock.status
    =CONSUMED.
    """
    _, app, _, _, _ = setup_closed_application(
        clock_anchor="2026-03-02T10:00:00.000Z",
    )
    assert app["status"] == "CLOSED"
    rl = validate_success(api.get_rate_lock(
        app["id"], loan_officer_headers,
    ), 200)
    assert rl["status"] == "CONSUMED", (
        "PRD §3.10: close cascades RateLock to CONSUMED."
    )


def test_close_terminal_state_no_further_transitions(api, loan_officer_headers):
    """PRD §3.10: "The application's terminal states are CLOSED,
    DENIED, and WITHDRAWN. No transition leaves any of them."

    Claim: from CLOSED, any state-transition endpoint returns
    ERR_INVALID_STATE.
    """
    _, app, _, _, _ = setup_closed_application(
        clock_anchor="2026-03-02T10:00:00.000Z",
    )
    assert app["status"] == "CLOSED"
    res = api.withdraw_application(app["id"], None, loan_officer_headers)
    validate_error(
        res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409,
    )
