"""Cascade and compensating-invariant tests: deep ledger reversals, conserved
quantities across forward+compensating pairs, and committee cascades.
"""
import pytest

from test_helpers import (
    validate_success,
    TEST_USERS,
    make_applicant_headers,
    award_payload,
    fixtures,
)

ADMIN = TEST_USERS["foundation_admin_headers"]
OFFICER = TEST_USERS["disbursement_officer_headers"]


# ===========================================================================
# Queue A — transitive_cascade
# ===========================================================================
def test_settled_disbursement_return_cascade_depth3(api):
    """PRD §3.7: "Returning a `SETTLED` disbursement is a deeper compensation: the
    fund's `disbursed_cents` is decreased by the disbursement's `amount_cents`, the
    fund's `committed_cents` is decreased by the award's `provisional_award_cents`,
    `available_cents` is recomputed, and the parent award cascades to the terminal
    `REVOKED` state."

    Design: Difficulty/transitive_cascade/settled_disbursement_return_cascade_depth3
    """
    ctx = fixtures.setup_settled_disbursement(
        institution_id="I7",
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=1_000_000, verified_gpa=3.20,
        scores=[(95, 90, 85), (95, 90, 85)],
    )
    award_id = ctx["award"]["id"]
    disb_id = ctx["disbursement"]["id"]
    # Sanity: settled state established the committed=1000000, disbursed=900000.
    fund_before = validate_success(api.get_fund(ctx["fund"]["id"], ADMIN))
    assert fund_before["committed_cents"] == 1_000_000
    assert fund_before["disbursed_cents"] == 900_000

    returned = validate_success(api.return_disbursement(disb_id, OFFICER))
    assert returned["status"] == "RETURNED"

    fund_after = validate_success(api.get_fund(ctx["fund"]["id"], ADMIN))
    assert fund_after["disbursed_cents"] == 0
    assert fund_after["committed_cents"] == 0
    assert fund_after["available_cents"] == 5_000_000
    award_after = validate_success(api.get_award(award_id, ADMIN))
    assert award_after["status"] == "REVOKED"


def test_finalize_scoring_completes_assignments_decrements_count(api):
    """PRD §3.5: "Finalize-scoring also cascades to the committee: every committee
    assignment on the application that is in `ASSIGNED` status is transitioned to
    `COMPLETED`, and each affected member's `active_assignment_count` is recomputed
    downward."

    Design: Difficulty/transitive_cascade/finalize_scoring_completes_assignments_decrements_count_depth2
    """
    ctx = fixtures.setup_scored_application(
        endowment_cents=3_000_000, min_gpa=2.00, max_award_cents=500_000,
        requested_amount_cents=300_000, verified_gpa=3.20,
        scores=[(90, 90, 90), (90, 90, 90)],
    )
    member = ctx["members"][0]
    member_after = validate_success(api.get_committee_member(member["id"], ADMIN))
    assert member_after["active_assignment_count"] == 0
    assert ctx["application"]["status"] == "SCORED"


# ===========================================================================
# Queue A — compensating_invariant
# ===========================================================================
def test_award_then_revoke_leaves_committed_cents_unchanged(api):
    """PRD §2.7: "a forward award followed by its revoke leaves `committed_cents`
    exactly as it was before"
    PRD §3.8: "On revoke, the fund's `committed_cents` is decreased by the award's
    `provisional_award_cents` and `available_cents` is recomputed, releasing the
    commitment — the compensation that, paired with the original award, leaves the
    committed total unchanged."

    Design: Difficulty/compensating_invariant/award_then_revoke_leaves_committed_cents_unchanged
    """
    ctx = fixtures.setup_committed_award(
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=1_000_000, verified_gpa=3.50,
        scores=[(95, 90, 85), (95, 90, 85)],
    )
    award_id = ctx["award"]["id"]
    revoked = validate_success(api.revoke_award(award_id, ADMIN))
    assert revoked["status"] == "REVOKED"
    fund_after = validate_success(api.get_fund(ctx["fund"]["id"], ADMIN))
    assert fund_after["committed_cents"] == 0
    assert fund_after["available_cents"] == 5_000_000


def test_settle_then_return_leaves_disbursed_cents_unchanged(api):
    """PRD §2.7: "a settle followed by its return leaves both `disbursed_cents` and
    `committed_cents` exactly as they were before."
    PRD §3.7: "Returning a `SETTLED` disbursement is a deeper compensation: the fund's
    `disbursed_cents` is decreased by the disbursement's `amount_cents`"

    Design: Difficulty/compensating_invariant/settle_then_return_leaves_disbursed_cents_unchanged
    """
    ctx = fixtures.setup_settled_disbursement(
        institution_id="I17",
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=1_000_000, verified_gpa=3.20,
        scores=[(95, 90, 85), (95, 90, 85)],
    )
    disb_id = ctx["disbursement"]["id"]
    returned = validate_success(api.return_disbursement(disb_id, OFFICER))
    assert returned["status"] == "RETURNED"
    fund_after = validate_success(api.get_fund(ctx["fund"]["id"], ADMIN))
    assert fund_after["disbursed_cents"] == 0


# ===========================================================================
# Queue B — cascading_side_effects
# ===========================================================================
def test_withdraw_revokes_assignments_and_decrements_count(api):
    """PRD §3.3: "Withdrawing an application cascades to its committee assignments:
    every assignment on it that is in `ASSIGNED` status transitions to `REVOKED`, and
    each affected member's `active_assignment_count` is recomputed downward to reflect
    the removed assignment."

    Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_withdraw_revokes_assignments
    """
    fund = fixtures.create_open_fund(endowment_cents=1_000_000, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_draft_application_with_docs(
        fund["id"], applicant["id"], requested_amount_cents=100_000, verified_gpa=3.00,
    )
    member = fixtures.create_member()
    assignment = fixtures.assign_member(app["id"], member["id"])
    headers = make_applicant_headers(applicant["id"])
    validate_success(api.submit_application(app["id"], headers))

    withdrawn = validate_success(api.withdraw_application(app["id"], headers))
    assert withdrawn["status"] == "WITHDRAWN"
    asg_after = validate_success(api.get_committee_assignment(assignment["id"], ADMIN))
    assert asg_after["status"] == "REVOKED"
    member_after = validate_success(api.get_committee_member(member["id"], ADMIN))
    assert member_after["active_assignment_count"] == 0
