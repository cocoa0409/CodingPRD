"""Validation priority ordering (PRD §2.6), explicit priority-pair
tests, and RBAC enforcement.

PRD §2.6 establishes a fixed total order for the rejection chain:
(1) user-context header  ->  (2) RBAC / SOD  ->  (3) path existence
(left-to-right)  ->  (4) plan ACTIVE gate  ->  (5) participant state
gate  ->  (6) target-resource state gate  ->  (7) business rules
->  (8) OCC. Each adjacent pair (where the PRD names both rules
explicitly) is testable: a request that violates both should surface
the higher-priority error.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    EMPLOYEE_ANNUAL_LIMIT_CENTS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_and_activate_plan,
    create_contribution_payload,
    create_hardship_payload,
    create_loan_payload,
    create_participant_payload,
    make_participant_headers,
    post_contribution,
    request_hardship,
    setup_basic_active_participant,
    setup_participant_with_balance,
    validate_error,
)


# ===========================================================================
# Priority 1 > 2: missing header beats forbidden role — PRD §2.6
# ===========================================================================
def test_missing_header_beats_role_mismatch(api):
    """PRD §2.6: "a missing header always wins over a permission
    problem".

    Claim: a request with NO X-User-Role header (would otherwise be
    a role mismatch) returns ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    not ERR_INSUFFICIENT_PERMISSIONS.
    """
    res = api.create_plan(
        create_participant_payload(),
        headers={"X-User-ID": "x", "Content-Type": "application/json"},
    )
    validate_error(
        res,
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        expected_status=400,
    )


# ===========================================================================
# Priority 2 > 3: permission beats not-found — PRD §2.6
# ===========================================================================
def test_permission_beats_not_found(api):
    """PRD §2.6: "a permission problem always wins over a not-found".

    Claim: a non-PayrollProcessor calling POST .../activate on a
    non-existent participant -> ERR_INSUFFICIENT_PERMISSIONS (NOT
    ERR_PLAN_NOT_FOUND or ERR_PARTICIPANT_NOT_FOUND).
    """
    res = api.activate_participant(
        NON_EXISTENT_UUID, NON_EXISTENT_UUID, None,
        TEST_USERS["admin_headers"],  # PlanAdmin cannot activate participants
    )
    validate_error(
        res,
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
        expected_status=403,
    )


# ===========================================================================
# Priority 3 left-to-right — PRD §2.5
# ===========================================================================
def test_path_left_to_right_plan_before_participant(api, admin_headers):
    """PRD §2.5: "A non-existent participant under a non-existent plan
    must surface as ERR_PLAN_NOT_FOUND, not as ERR_PARTICIPANT_NOT_FOUND."

    Claim: GET /plans/{fake}/participants/{fake} ->
    ERR_PLAN_NOT_FOUND.
    """
    res = api.get_participant(
        NON_EXISTENT_UUID, NON_EXISTENT_UUID, admin_headers,
    )
    validate_error(
        res, ApiErrorId.ERR_PLAN_NOT_FOUND.value, expected_status=404,
    )


# ===========================================================================
# Priority 4 > 5: plan-not-active beats participant-state — PRD §2.6
# ===========================================================================
def test_plan_not_active_beats_participant_state(api, admin_headers,
                                                 payroll_headers):
    """PRD §2.6: "a plan-not-active error always wins over a
    participant-state error".

    Claim: POST contribution-records on a DRAFT plan where the
    participant is in any state -> ERR_PLAN_NOT_ACTIVE (not
    ERR_PARTICIPANT_NOT_IN_VALID_STATE).

    Setup: create a DRAFT plan and an ENROLLED participant. The
    contribution endpoint requires Plan==ACTIVE (priority 4) AND
    Participant==ACTIVE (priority 5). Both fail; the priority 4 code
    must surface.
    """
    plan = create_and_activate_plan()  # ACTIVE so we can enroll
    res_enroll = api.create_participant(
        plan["id"],
        create_participant_payload(),
        admin_headers,
    )
    p_id = res_enroll.json()["data"]["id"]
    # Freeze the plan to make it non-ACTIVE.
    api.freeze_plan(plan["id"], None, admin_headers)
    # Participant is still ENROLLED (never activated), so it's also in
    # a non-permitting state for contributions. Plan check must win.
    res = api.create_contribution_record(
        plan["id"], p_id,
        create_contribution_payload(
            pay_period_end="2026-03-15", gross_pay_cents=500_000,
        ),
        payroll_headers,
    )
    body = res.json()
    err = body["data"]["error_id"]
    # PRD §2.6 explicitly: plan check beats participant. Either
    # ERR_PLAN_NOT_ACTIVE or ERR_PLAN_FROZEN is the higher-priority
    # surface for a FROZEN plan.
    assert err in (
        ApiErrorId.ERR_PLAN_NOT_ACTIVE.value,
        ApiErrorId.ERR_PLAN_FROZEN.value,
    ), f"Expected plan-level error, got {err}"


# ===========================================================================
# Priority pair: state(4) vs business_fiscal(10) — PRD §2.6 + scaffold
# difficulty design
# ===========================================================================
def test_state_beats_business_fiscal_on_loan_request(api):
    """PRD §2.6: "the plan-level state gate (the parent Plan must be
    in ACTIVE status for any participant-side mutation — enrollment,
    participant activation, contribution posting, loan request, loan
    approval ...), returning ERR_PLAN_NOT_ACTIVE".
    PRD §2.6: "then (7) the business rules ... loan caps ...".

    Claim: a loan request on a FROZEN plan whose requested amount also
    exceeds max_loan -> ERR_PLAN_NOT_ACTIVE (priority 4 / 7 wins
    over priority 10).

    # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_loan_request
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=1_000_000,
        cliff_years=1,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    # Freeze the plan.
    api.freeze_plan(plan["id"], None, TEST_USERS["admin_headers"])
    headers = make_participant_headers(p["id"])
    res = api.create_loan(
        plan["id"], p["id"],
        create_loan_payload(
            requested_amount_cents=99_999_999,
            term_months=12,
        ),
        headers,
    )
    body = res.json()
    err = body["data"]["error_id"]
    assert err in (
        ApiErrorId.ERR_PLAN_NOT_ACTIVE.value,
        ApiErrorId.ERR_PLAN_FROZEN.value,
    ), (
        f"Expected ERR_PLAN_NOT_ACTIVE / ERR_PLAN_FROZEN "
        f"(higher priority than ERR_LOAN_EXCEEDS_MAX), got {err}"
    )


def test_state_beats_business_fiscal_on_loan_request_second(api):
    """PRD §2.6 priority pinning — second test for the difficulty
    instance, exercised at a different balance scale.

    # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_loan_request
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=2_000_000,
        cliff_years=1,
        starting_clock="2026-02-01", hire_date="2020-06-01",
    )
    api.freeze_plan(plan["id"], None, TEST_USERS["admin_headers"])
    headers = make_participant_headers(p["id"])
    res = api.create_loan(
        plan["id"], p["id"],
        create_loan_payload(
            requested_amount_cents=10_000_000,
            term_months=12,
        ),
        headers,
    )
    body = res.json()
    err = body["data"]["error_id"]
    assert err in (
        ApiErrorId.ERR_PLAN_NOT_ACTIVE.value,
        ApiErrorId.ERR_PLAN_FROZEN.value,
    )


# ===========================================================================
# Priority pair: business_temporal(7) vs business_safety(8)
# duplicate-pay-period vs deferral-suspended.
# ===========================================================================
def test_duplicate_pay_period_beats_deferral_suspended(api, payroll_headers):
    """PRD §3.3: "No two ContributionRecord rows may share the pair
    (participant_id, pay_period_end). A duplicate request is rejected
    with ERR_DUPLICATE_PAY_PERIOD."
    PRD §3.3: "A contribution post is rejected with
    ERR_DEFERRAL_SUSPENDED whenever the participant's
    deferral_suspended_until is non-null and PlanClock.current_date is
    less than or equal to deferral_suspended_until."

    Claim: posting a contribution that is BOTH a duplicate pay-period
    AND while the participant is suspended -> ERR_DUPLICATE_PAY_PERIOD
    (priority 7 wins over priority 8).

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_contribution
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=500_000,
        cliff_years=1,
        starting_clock="2026-01-01", hire_date="2020-01-01",
        elected_deferral_pct=5.0,
    )
    # First contribution (succeeds).
    post_contribution(
        plan["id"], p["id"],
        pay_period_end="2026-02-15", gross_pay_cents=500_000,
        headers=payroll_headers,
    )
    # Hardship -> approval -> suspension.
    from test_helpers import approve_hardship
    hw = request_hardship(
        plan["id"], p["id"],
        requested_amount_cents=100_000,
        hardship_reason_code="MEDICAL",
    )
    approve_hardship(plan["id"], p["id"], hw["id"])
    # Now try duplicate pay-period while suspended.
    res = api.create_contribution_record(
        plan["id"], p["id"],
        create_contribution_payload(
            pay_period_end="2026-02-15", gross_pay_cents=500_000,
        ),
        payroll_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_DUPLICATE_PAY_PERIOD.value,
        expected_status=409,
    )


def test_duplicate_pay_period_beats_deferral_suspended_second(api,
                                                              payroll_headers):
    """PRD §3.3 priority pinning — second test for the difficulty
    instance, via a different pay-period date.

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_contribution
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=600_000,
        cliff_years=1,
        starting_clock="2026-03-01", hire_date="2020-06-01",
        elected_deferral_pct=5.0,
    )
    post_contribution(
        plan["id"], p["id"],
        pay_period_end="2026-04-30", gross_pay_cents=500_000,
        headers=payroll_headers,
    )
    from test_helpers import approve_hardship
    hw = request_hardship(
        plan["id"], p["id"],
        requested_amount_cents=100_000,
        hardship_reason_code="EVICTION",
    )
    approve_hardship(plan["id"], p["id"], hw["id"])
    res = api.create_contribution_record(
        plan["id"], p["id"],
        create_contribution_payload(
            pay_period_end="2026-04-30", gross_pay_cents=500_000,
        ),
        payroll_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_DUPLICATE_PAY_PERIOD.value,
        expected_status=409,
    )


# ===========================================================================
# RBAC — per-endpoint role enforcement (PRD §2.1 / §4)
# ===========================================================================
@pytest.mark.parametrize("role_key,role_name", [
    ("payroll_headers", "PayrollProcessor"),
    ("compliance_headers", "ComplianceOfficer"),
])
def test_create_plan_rejects_non_admin_roles(api, role_key, role_name):
    """PRD §4: 'POST /plans | PlanAdministrator'.
    PRD §2.1: "A request that presents valid headers but invokes an
    endpoint the role is not authorized to use is rejected with
    ERR_INSUFFICIENT_PERMISSIONS."

    Claim: POST /plans by non-PlanAdministrator role ->
    ERR_INSUFFICIENT_PERMISSIONS.
    """
    res = api.create_plan(
        create_participant_payload(),
        TEST_USERS[role_key],
    )
    validate_error(
        res,
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
        expected_status=403,
    )


def test_approve_hardship_rejects_non_compliance_officer(api):
    """PRD §4: 'POST .../hardship-withdrawals/{withdrawalId}/approve |
    ComplianceOfficer'.

    Claim: approving hardship as PlanAdministrator (not
    ComplianceOfficer) -> ERR_INSUFFICIENT_PERMISSIONS.
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=500_000,
        cliff_years=1,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    hw = request_hardship(
        plan["id"], p["id"],
        requested_amount_cents=100_000,
        hardship_reason_code="MEDICAL",
    )
    res = api.approve_hardship_withdrawal(
        plan["id"], p["id"], hw["id"], None,
        TEST_USERS["admin_headers"],  # wrong role
    )
    validate_error(
        res,
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
        expected_status=403,
    )


def test_create_rmd_schedule_rejects_non_compliance_officer(api):
    """PRD §4: 'POST .../rmd-schedules | ComplianceOfficer'.

    Claim: creating an RMD schedule as PlanAdministrator ->
    ERR_INSUFFICIENT_PERMISSIONS.
    """
    plan = create_and_activate_plan(plan_year=2024)
    res_enroll = api.create_participant(
        plan["id"],
        create_participant_payload(date_of_birth="1951-06-15"),
        TEST_USERS["admin_headers"],
    )
    p_id = res_enroll.json()["data"]["id"]
    res = api.create_rmd_schedule(
        plan["id"], p_id,
        {"rmd_year": 2024},
        TEST_USERS["admin_headers"],  # wrong role
    )
    validate_error(
        res,
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
        expected_status=403,
    )


# ===========================================================================
# Participant ownership: participant cannot act on another participant
# ===========================================================================
def test_participant_cannot_request_loan_on_another_participants_record(api):
    """PRD §2.1: "Ownership checks on any participant-scoped operation
    compare the resource's participant_id (or the participantId in the
    URL path) to X-User-ID; the participant may act only on
    themselves."

    Claim: Participant A trying to POST .../participants/{B}/loans ->
    ERR_INSUFFICIENT_PERMISSIONS (B != A.id).
    """
    # Build two participants under the same plan.
    plan, p_a = setup_participant_with_balance(
        target_balance_cents=2_000_000,
        cliff_years=1,
        starting_clock="2026-01-01", hire_date="2020-01-01",
    )
    p_b = api.create_participant(
        plan["id"],
        create_participant_payload(
            employee_external_id="emp-B-1",
            date_of_birth="1985-01-01",
            hire_date="2020-01-01",
        ),
        TEST_USERS["admin_headers"],
    ).json()["data"]
    # Headers say "I am Participant A" but URL targets B.
    headers_a = make_participant_headers(p_a["id"])
    res = api.create_loan(
        plan["id"], p_b["id"],
        create_loan_payload(
            requested_amount_cents=100_000, term_months=10,
        ),
        headers_a,
    )
    validate_error(
        res,
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
        expected_status=403,
    )


# ===========================================================================
# Schema validation — PRD §3.2 + §5
# ===========================================================================
def test_enroll_participant_invalid_deferral_pct_rejected(api, admin_headers):
    """PRD §5: "ERR_INVALID_REQUEST: Required field missing, wrong
    type, or out-of-range value (e.g., elected_deferral_pct > 100)."

    Claim: enroll with elected_deferral_pct=150.0 ->
    ERR_INVALID_REQUEST.
    """
    plan = create_and_activate_plan()
    payload = create_participant_payload(elected_deferral_pct=150.0)
    res = api.create_participant(plan["id"], payload, admin_headers)
    validate_error(
        res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400,
    )
