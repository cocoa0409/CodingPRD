"""Transitive cascades, non-linear cycles, cross-entity dependencies, boundaries.

Translates queue-A instances for transitive_cascade, non_linear_state_machine,
boundary_precision_check, cross_entity_state_dependency, and the waive
compensating-invariant.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    TEST_USERS, make_probation_officer_headers,
    create_diversion_payload, create_service_site_payload,
    create_service_assignment_payload,
    setup_arraigned_case, setup_accepted_diversion, setup_service_ready,
    setup_failed_case,
    fetch_diversion, fetch_warrant, fetch_plan, fetch_assignment, set_clock,
)

JUDGE = "judge_headers"
CLERK = "court_clerk_headers"
ADMIN = "court_admin_headers"


# ===========================================================================
# Rule 4 — transitive cascades.
# ===========================================================================

def _run_completion_cascade(api):
    ctx = setup_service_ready(api, pay_ledger=True, mandated_service_hours=10,
                              required_class_sessions=0, required_hours=10,
                              hours_logged=10, creator_officer_id="po_1")
    assignment = validate_success(
        api.verify_completion(ctx["assignment"]["id"], make_probation_officer_headers("po_2")), 200)
    ctx["assignment"] = assignment
    return ctx


def test_verify_completion_cascades_to_case_complied(api):
    """PRD §3.6: "When the agreement does reach COMPLETED, final_compliance_pct is
    recomputed to 100, the case bubbles up from DIVERSION_GRANTED to COMPLIED, and
    an expungement referral is created for the case in PENDING status with its
    eligible_date set to now."

    Design: Difficulty/transitive_cascade/verify_completion_cascade_to_expungement_referral
    """
    ctx = _run_completion_cascade(api)
    assert ctx["assignment"]["status"] == "COMPLETED"
    diversion = fetch_diversion(api, ctx["case"]["id"], ctx["diversion"]["id"])
    assert diversion["status"] == "COMPLETED"
    case = validate_success(api.get_case(ctx["case"]["id"], TEST_USERS[CLERK]), 200)
    assert case["status"] == "COMPLIED"


def test_verify_completion_creates_pending_expungement_referral(api):
    """PRD §3.9: "it bubbles up from DIVERSION_GRANTED the moment its diversion
    agreement reaches COMPLETED ... At that bubble-up the case's expungement
    referral is created in PENDING status with its eligible_date stamped at now."

    Design: Difficulty/transitive_cascade/verify_completion_cascade_to_expungement_referral
    """
    ctx = _run_completion_cascade(api)
    referrals = get_success_data(api.list_expungement_referrals(ctx["case"]["id"], TEST_USERS[CLERK]))
    assert len(referrals) == 1
    assert referrals[0]["status"] == "PENDING"
    assert referrals[0]["case_id"] == ctx["case"]["id"]


def test_warrant_cascades_case_and_diversion(api):
    """PRD §3.8: "Issuing the warrant advances the case from DIVERSION_GRANTED to
    FAILED_TO_COMPLY ... The diversion agreement moves from IN_PROGRESS to
    DEFAULTED."

    Design: Difficulty/transitive_cascade/warrant_cascade_to_diversion_default
    """
    ctx = setup_failed_case(api)
    assert ctx["case"]["status"] == "FAILED_TO_COMPLY"
    assert ctx["diversion"]["status"] == "DEFAULTED"
    assert ctx["warrant"]["status"] == "ISSUED"


def test_warrant_created_issued_and_listable(api):
    """PRD §3.8: "Caused by that default, a Warrant is created in ISSUED status
    with a human-readable reason recorded on it."
    PRD §3.8: "A case's warrants can be listed as the reverse of the warrant's
    case_id."

    Design: Difficulty/transitive_cascade/warrant_cascade_to_diversion_default
    """
    ctx = setup_failed_case(api)
    warrant = fetch_warrant(api, ctx["case"]["id"], ctx["warrant"]["id"])
    assert warrant["status"] == "ISSUED"
    assert isinstance(warrant["reason"], str) and len(warrant["reason"]) > 0


# ===========================================================================
# Rule 3 — non-linear (A->B->A) cycles.
# ===========================================================================

def test_case_failed_then_reinstated_cycle(api):
    """PRD §3.8: "When reinstatement proceeds, the case cycles back from
    FAILED_TO_COMPLY to DIVERSION_GRANTED ... the outstanding Warrant moves from
    ISSUED to RECALLED."

    Design: Difficulty/non_linear_state_machine/case_failed_to_comply_reinstated_cycle
    """
    ctx = setup_failed_case(api, with_amnesty=True)
    case = validate_success(
        api.reinstate_case(ctx["case"]["id"], {"amnesty_program_id": ctx["amnesty"]["id"]},
                           TEST_USERS[JUDGE]), 200)
    assert case["status"] == "DIVERSION_GRANTED"
    warrant = fetch_warrant(api, ctx["case"]["id"], ctx["warrant"]["id"])
    assert warrant["status"] == "RECALLED"


def test_case_reinstated_diversion_returns_in_progress(api):
    """PRD §3.8: "the diversion agreement returns from DEFAULTED to IN_PROGRESS,
    the outstanding Warrant moves from ISSUED to RECALLED."

    Design: Difficulty/non_linear_state_machine/case_failed_to_comply_reinstated_cycle
    """
    ctx = setup_failed_case(api, with_amnesty=True)
    validate_success(
        api.reinstate_case(ctx["case"]["id"], {"amnesty_program_id": ctx["amnesty"]["id"]},
                           TEST_USERS[JUDGE]), 200)
    diversion = fetch_diversion(api, ctx["case"]["id"], ctx["diversion"]["id"])
    assert diversion["status"] == "IN_PROGRESS"


def test_installment_plan_delinquent_after_warrant(api):
    """PRD §3.8: "any ACTIVE installment plan on the case's ledger account is
    demoted from ACTIVE to DELINQUENT."

    Design: Difficulty/non_linear_state_machine/installment_plan_delinquent_reinstated_cycle
    """
    ctx = setup_failed_case(api, with_amnesty=True, with_plan=True, plan_installments=6)
    assert ctx["plan_after_warrant"]["status"] == "DELINQUENT"


def test_installment_plan_reinstated_to_active(api):
    """PRD §3.8: "any DELINQUENT installment plan on the account returns to ACTIVE."

    Design: Difficulty/non_linear_state_machine/installment_plan_delinquent_reinstated_cycle
    """
    ctx = setup_failed_case(api, with_amnesty=True, with_plan=True, plan_installments=6)
    validate_success(
        api.reinstate_case(ctx["case"]["id"], {"amnesty_program_id": ctx["amnesty"]["id"]},
                           TEST_USERS[JUDGE]), 200)
    plan = fetch_plan(api, ctx["ledger_account"]["id"], ctx["plan"]["id"])
    assert plan["status"] == "ACTIVE"


# ===========================================================================
# Rule 6 — boundary precision.
# ===========================================================================

def test_first_offender_rejected_at_prior_count_one(api):
    """PRD §3.5: "If the defendant's prior_diversion_count is not below the
    first-offender ceiling of 1, the grant is rejected with ERR_NOT_FIRST_OFFENDER."

    Design: Difficulty/boundary_precision_check/first_offender_prior_count_boundary_rejected_at_one
    """
    ctx = setup_arraigned_case(api, plea="GUILTY", prior_diversion_count=1)
    resp = api.grant_diversion(ctx["case"]["id"], create_diversion_payload(mandated_service_hours=10),
                               TEST_USERS[JUDGE])
    validate_error(resp, ApiErrorId.ERR_NOT_FIRST_OFFENDER, 422)
    case = validate_success(api.get_case(ctx["case"]["id"], TEST_USERS[CLERK]), 200)
    assert case["status"] == "ARRAIGNED"


def test_first_offender_granted_at_prior_count_zero(api):
    """PRD §3.2: "a defendant with no prior completed diversion (a count of 0)
    qualifies, and a defendant with one or more priors does not."

    Design: Difficulty/boundary_precision_check/first_offender_prior_count_boundary_rejected_at_one
    """
    ctx = setup_arraigned_case(api, plea="GUILTY", prior_diversion_count=0)
    resp = api.grant_diversion(ctx["case"]["id"], create_diversion_payload(mandated_service_hours=10),
                               TEST_USERS[JUDGE])
    diversion = validate_success(resp, 201)
    assert diversion["status"] == "OFFERED"
    case = validate_success(api.get_case(ctx["case"]["id"], TEST_USERS[CLERK]), 200)
    assert case["status"] == "DIVERSION_GRANTED"


def test_amnesty_window_rejected_at_active_to(api):
    """PRD §3.8: "now must be at or after its active_from and strictly before its
    active_to; a reinstatement attempted outside that half-open window is rejected
    with ERR_AMNESTY_WINDOW_CLOSED."

    Design: Difficulty/boundary_precision_check/amnesty_window_end_boundary_rejected_at_active_to
    """
    ctx = setup_failed_case(api, with_amnesty=True)  # window [2026-06-01, 2026-08-01)
    set_clock(api, "2026-08-01T00:00:00Z")  # exactly active_to (exclusive)
    resp = api.reinstate_case(ctx["case"]["id"], {"amnesty_program_id": ctx["amnesty"]["id"]},
                              TEST_USERS[JUDGE])
    validate_error(resp, ApiErrorId.ERR_AMNESTY_WINDOW_CLOSED, 422)
    case = validate_success(api.get_case(ctx["case"]["id"], TEST_USERS[CLERK]), 200)
    assert case["status"] == "FAILED_TO_COMPLY"


def test_amnesty_window_open_just_before_active_to(api):
    """PRD §3.8: "Reinstatement is allowed only while the referenced program's
    window is open — now must be at or after its active_from and strictly before
    its active_to."

    Design: Difficulty/boundary_precision_check/amnesty_window_end_boundary_rejected_at_active_to
    """
    ctx = setup_failed_case(api, with_amnesty=True)  # window [2026-06-01, 2026-08-01)
    set_clock(api, "2026-07-31T23:59:59Z")  # strictly before active_to
    case = validate_success(
        api.reinstate_case(ctx["case"]["id"], {"amnesty_program_id": ctx["amnesty"]["id"]},
                           TEST_USERS[JUDGE]), 200)
    assert case["status"] == "DIVERSION_GRANTED"


# ===========================================================================
# Rule 7 — cross-entity state dependencies.
# ===========================================================================

def test_diversion_complete_blocked_by_unsettled_ledger(api):
    """PRD §3.6: "If all service and completion conditions are met but the ledger
    account is not SETTLED, the completion is blocked with ERR_LEDGER_NOT_SETTLED."

    Design: Difficulty/cross_entity_state_dependency/diversion_complete_blocked_by_unsettled_ledger
    """
    ctx = setup_service_ready(api, pay_ledger=False, mandated_service_hours=10,
                              required_hours=10, hours_logged=10, creator_officer_id="po_1")
    resp = api.verify_completion(ctx["assignment"]["id"], make_probation_officer_headers("po_2"))
    validate_error(resp, ApiErrorId.ERR_LEDGER_NOT_SETTLED, 409)


def test_diversion_stays_in_progress_when_ledger_unsettled(api):
    """PRD §3.6: "The agreement transitions from IN_PROGRESS to COMPLETED only
    when every one of its assignments is in COMPLETED or WAIVED status ... and — a
    cross-entity gate — the case's ledger account is already in SETTLED status."

    Design: Difficulty/cross_entity_state_dependency/diversion_complete_blocked_by_unsettled_ledger
    """
    ctx = setup_service_ready(api, pay_ledger=False, mandated_service_hours=10,
                              required_hours=10, hours_logged=10, creator_officer_id="po_1")
    api.verify_completion(ctx["assignment"]["id"], make_probation_officer_headers("po_2"))
    diversion = fetch_diversion(api, ctx["case"]["id"], ctx["diversion"]["id"])
    assert diversion["status"] == "IN_PROGRESS"


def _defaulted_with_assignment(api):
    ctx = setup_service_ready(api, pay_ledger=False, mandated_service_hours=10,
                              required_hours=10, hours_logged=10, creator_officer_id="po_1")
    set_clock(api, "2026-07-01T00:00:00Z")
    validate_success(api.issue_warrant(ctx["case"]["id"], TEST_USERS[JUDGE]), 201)
    return ctx


def test_verify_blocked_by_defaulted_diversion(api):
    """PRD §3.6: "the owning agreement must itself be IN_PROGRESS for the verify to
    be a legal transition; otherwise it is rejected with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/assignment_verify_blocked_by_defaulted_diversion
    """
    ctx = _defaulted_with_assignment(api)
    resp = api.verify_completion(ctx["assignment"]["id"], make_probation_officer_headers("po_2"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_assignment_stays_in_progress_when_diversion_defaulted(api):
    """PRD §3.8: "The diversion agreement moves from IN_PROGRESS to DEFAULTED."
    PRD §3.6: "the owning agreement must itself be IN_PROGRESS for the verify to
    be a legal transition; otherwise it is rejected with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/assignment_verify_blocked_by_defaulted_diversion
    """
    ctx = _defaulted_with_assignment(api)
    api.verify_completion(ctx["assignment"]["id"], make_probation_officer_headers("po_2"))
    assignment = fetch_assignment(api, ctx["assignment"]["id"])
    assert assignment["status"] == "IN_PROGRESS"


# ===========================================================================
# Rule 9 — waive preserves assigned_service_hours (conserved quantity).
# ===========================================================================

def _agreement_with_two_assignments(api):
    ctx = setup_accepted_diversion(api, diversion_overrides={"mandated_service_hours": 10})
    admin = TEST_USERS[ADMIN]
    officer = make_probation_officer_headers("po_1")
    site = validate_success(api.create_service_site(
        create_service_site_payload(concurrent_capacity=5), admin), 201)
    validate_success(api.create_service_assignment(
        ctx["diversion"]["id"],
        create_service_assignment_payload(site["id"], required_hours=6,
            session_start="2026-03-22T09:00:00Z", session_end="2026-03-22T15:00:00Z"),
        officer), 201)
    b = validate_success(api.create_service_assignment(
        ctx["diversion"]["id"],
        create_service_assignment_payload(site["id"], required_hours=4,
            session_start="2026-03-23T09:00:00Z", session_end="2026-03-23T13:00:00Z"),
        officer), 201)
    ctx["assignment_b"] = b
    return ctx


def test_waive_restores_assigned_service_hours(api):
    """PRD §3.6: "in both cases the assignment moves to WAIVED and the agreement's
    assigned_service_hours is recomputed so that the waived assignment's
    required_hours drops out of the conserved total."

    Design: Difficulty/compensating_invariant/waive_preserves_assigned_service_hours
    """
    ctx = _agreement_with_two_assignments(api)  # assigned_service_hours == 10 (6 + 4)
    validate_success(api.waive_assignment(ctx["assignment_b"]["id"], TEST_USERS[JUDGE]), 200)
    diversion = fetch_diversion(api, ctx["case"]["id"], ctx["diversion"]["id"])
    assert diversion["assigned_service_hours"] == 6.00


def test_assigned_service_hours_invariant_after_waive(api):
    """PRD §2.10: "assigned_service_hours is the sum of required_hours over the
    agreement's service assignments whose status is not WAIVED."

    Design: Difficulty/compensating_invariant/waive_preserves_assigned_service_hours
    """
    ctx = _agreement_with_two_assignments(api)
    validate_success(api.waive_assignment(ctx["assignment_b"]["id"], TEST_USERS[JUDGE]), 200)
    diversion = fetch_diversion(api, ctx["case"]["id"], ctx["diversion"]["id"])
    # Only assignment A (required_hours 6) is non-WAIVED.
    assert diversion["assigned_service_hours"] == 6.00
