"""Enrollment funding dimension (cyclic), lapse boundary, and the claim
branching-with-revert machine.

Difficulty queue A: non_linear_state_machine, boundary_precision_check (lapse).
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    fixtures,
)

_ADMIN = TEST_USERS["benefits_admin_headers"]
_ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# ---------------------------------------------------------------------------
# non_linear_state_machine / enrollment_funding_cycle_current_lapsed_current
# ---------------------------------------------------------------------------
def test_funding_reinstated_to_current_after_lapse(api):
    """PRD §3.7: "A `POSTED` outcome resets the consecutive-failure count to 0
    and sets `funding_status` to `CURRENT`, whether the enrollment was previously
    `UNFUNDED` or `LAPSED`; reinstating a lapsed policy is simply a `POSTED`
    outcome that returns it to `CURRENT`."

    Design: Difficulty/non_linear_state_machine/enrollment_funding_cycle_current_lapsed_current
    """
    _, _, _, _, enr, _ = fixtures.create_active_enrollment()
    fixtures.post_deduction(enr["id"], 0, "POSTED")
    fixtures.post_deduction(enr["id"], 1, "FAILED")
    fixtures.post_deduction(enr["id"], 2, "FAILED")
    fixtures.post_deduction(enr["id"], 3, "FAILED")
    lapsed = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert lapsed["funding_status"] == "LAPSED"
    # Reinstate
    fixtures.post_deduction(enr["id"], 4, "POSTED")
    data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert data["funding_status"] == "CURRENT"


def test_funding_cycle_lifecycle_unchanged_by_funding_moves(api):
    """PRD §2.8: "An `Enrollment` carries two state dimensions that evolve
    independently on different triggers."

    Design: Difficulty/non_linear_state_machine/enrollment_funding_cycle_current_lapsed_current
    """
    _, _, _, _, enr, _ = fixtures.create_active_enrollment()
    fixtures.post_deduction(enr["id"], 0, "POSTED")
    fixtures.post_deduction(enr["id"], 1, "FAILED")
    fixtures.post_deduction(enr["id"], 2, "FAILED")
    fixtures.post_deduction(enr["id"], 3, "FAILED")
    fixtures.post_deduction(enr["id"], 4, "POSTED")
    data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert data["funding_status"] == "CURRENT"
    assert data["lifecycle_status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# boundary_precision_check / lapse_on_third_consecutive_failed_not_second
# ---------------------------------------------------------------------------
def test_second_consecutive_failed_does_not_lapse(api):
    """PRD §3.7: "The boundary is exact: the third consecutive `FAILED` deduction
    lapses the policy, while the second consecutive failure does not."

    Design: Difficulty/boundary_precision_check/lapse_on_third_consecutive_failed_not_second
    """
    _, _, _, _, enr, _ = fixtures.create_active_enrollment()
    fixtures.post_deduction(enr["id"], 0, "POSTED")
    fixtures.post_deduction(enr["id"], 1, "FAILED")
    fixtures.post_deduction(enr["id"], 2, "FAILED")
    data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert data["funding_status"] == "CURRENT"


def test_third_consecutive_failed_lapses(api):
    """PRD §3.7: "A `FAILED` outcome increments the consecutive-failure count; the
    policy lapses to `LAPSED` only when that count reaches 3."

    Design: Difficulty/boundary_precision_check/lapse_on_third_consecutive_failed_not_second
    """
    _, _, _, _, enr, _ = fixtures.create_active_enrollment()
    fixtures.post_deduction(enr["id"], 0, "POSTED")
    fixtures.post_deduction(enr["id"], 1, "FAILED")
    fixtures.post_deduction(enr["id"], 2, "FAILED")
    fixtures.post_deduction(enr["id"], 3, "FAILED")
    data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert data["funding_status"] == "LAPSED"


# ---------------------------------------------------------------------------
# non_linear_state_machine / claim_branch_revert_approved_to_under_review
# ---------------------------------------------------------------------------
def test_reopen_moves_approved_claim_back_to_under_review(api):
    """PRD §3.9: "An `APPROVED` claim that has not yet produced a settled
    disbursement may be **reopened** by a `ClaimsAdjuster`, moving it from
    `APPROVED` back to `UNDER_REVIEW`"

    Design: Difficulty/non_linear_state_machine/claim_branch_revert_approved_to_under_review
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
        )
    )
    claim = fixtures.file_review_approve_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    reopened = validate_success(api.reopen_claim(claim["id"], _ADJUSTER))
    assert reopened["status"] == "UNDER_REVIEW"
    assert reopened["approved_cents"] == 0


def test_reopen_credits_back_benefit_ledger(api):
    """PRD §3.9: "reopening credits the enrollment's `benefit_paid_cents` back by
    the claim's `approved_cents` (wellness claims excluded, since they never
    debited the ledger), recomputes `benefit_remaining_cents`, and resets the
    claim's `approved_cents` to 0."

    Design: Difficulty/non_linear_state_machine/claim_branch_revert_approved_to_under_review
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
        )
    )
    claim = fixtures.file_review_approve_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    api.reopen_claim(claim["id"], _ADJUSTER)
    data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert data["benefit_paid_cents"] == 0
    assert data["benefit_remaining_cents"] == 500000
