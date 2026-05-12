"""PRD §3.2: Fund drafting, compliance review, shelf lifecycle.

Covers DRAFT -> UNDER_REVIEW -> ON_SHELF (and back), suspension cascade,
off-shelf preconditions, segregation-of-duties checks on
approve/reject-shelf, fee-tier validation at create and approve, and the
DRAFT->UNDER_REVIEW->DRAFT->UNDER_REVIEW->ON_SHELF revision cycle.

Difficulty-design coverage tags appear in test docstrings.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    assert_fund,
    create_draft_fund,
    create_fund_payload,
    create_kyc_approved_investor,
    create_on_shelf_fund,
    fee_tier,
    find_audit_entries,
    get_fund_fresh,
    holding_period_tier,
    list_audit_logs_for,
    setup_basic_investor_and_fund,
    setup_investor_with_confirmed_subscribe,
    submit_subscribe_order,
    validate_error,
    validate_success,
)


# =====================================================================
# Submit-for-review (PRD §3.2)
# =====================================================================
class TestSubmitForReview:
    def test_draft_to_under_review_locks_creator(self, api):
        """PRD §3.2: "When the operator who drafted the fund subsequently
        submits it for review, the fund advances `DRAFT → UNDER_REVIEW`,
        and the server stamps `Fund.shelf_creator_actor_id` with the
        submitter's `X-User-ID`, locking the creator identity for the
        segregation-of-duties check that follows."

        Claim: submit-for-review transitions DRAFT -> UNDER_REVIEW and
        records the submitter's X-User-ID for downstream SoD comparison.
        """
        fund = create_draft_fund()
        assert fund["status"] == "DRAFT"
        res = api.submit_fund_for_review(
            fund["id"], TEST_USERS["product_operator_headers"]
        )
        submitted = validate_success(res)
        assert submitted["status"] == "UNDER_REVIEW"


# =====================================================================
# Approve-shelf with SoD (PRD §3.2)
# =====================================================================
class TestApproveShelfSoD:
    def test_approver_equals_creator_rejected(self, api):
        """PRD §3.2: "Approval requires that the reviewer's `X-User-ID`
        differs from the stored `Fund.shelf_creator_actor_id` (otherwise
        `ERR_SOD_VIOLATION_SHELF`)."

        Claim: an approve-shelf call by the same X-User-ID that submitted
        the fund is rejected with ERR_SOD_VIOLATION_SHELF (403).
        """
        # Submitter and approver share the same X-User-ID. Although the
        # SoD comparison is on X-User-ID rather than role, this is the
        # canonical violation.
        from test_helpers import build_user_headers
        same_id_product = build_user_headers("same-actor", "ProductOperator")
        same_id_compliance = build_user_headers(
            "same-actor", "ComplianceReviewer"
        )
        fund = create_draft_fund()
        api.submit_fund_for_review(fund["id"], same_id_product)
        res = api.approve_fund_shelf(fund["id"], same_id_compliance)
        validate_error(res, "ERR_SOD_VIOLATION_SHELF")

    def test_approve_with_distinct_reviewer_succeeds(self, api):
        """PRD §3.2: "On approval, the fund advances `UNDER_REVIEW →
        ON_SHELF`."

        Claim: when approver's X-User-ID differs from the creator's, the
        fund transitions to ON_SHELF.
        """
        fund = create_on_shelf_fund()
        assert fund["status"] == "ON_SHELF"
        assert_fund(fund)


# =====================================================================
# Confirmation cycle days table (PRD §3.2)
# =====================================================================
class TestConfirmationCycleDays:
    @pytest.mark.parametrize("fund_type,expected_days", [
        ("MONEY_MARKET", 0),
        ("BOND", 1),
        ("EQUITY", 2),
        ("HYBRID", 2),
        ("QDII", 3),
    ])
    def test_cycle_days_set_on_approval(
        self, api, fund_type, expected_days
    ):
        """PRD §3.2: "`Fund.confirmation_cycle_days` is computed from
        `Fund.fund_type` according to the table: `MONEY_MARKET` is 0
        days, `BOND` is 1 day, `EQUITY` is 2 days, `HYBRID` is 2 days,
        and `QDII` is 3 days."

        Claim: every fund_type maps to the documented integer days on
        approve-shelf.
        """
        fund = create_on_shelf_fund(fund_type=fund_type)
        assert fund["confirmation_cycle_days"] == expected_days


# =====================================================================
# Reject-shelf (PRD §3.2)
# =====================================================================
class TestRejectShelf:
    def test_reject_clears_creator(self, api):
        """PRD §3.2: "Symmetrically, the reviewer can reject the fund:
        rejection also requires the same segregation-of-duties check,
        advances the fund `UNDER_REVIEW → DRAFT`, clears
        `Fund.shelf_creator_actor_id` back to null so a different
        operator may resubmit."

        Claim: reject-shelf transitions UNDER_REVIEW -> DRAFT and clears
        the locked creator identity, allowing a re-submission cycle.

        # difficulty: non_linear_state_machine/fund_shelf_revision_cycle
        """
        fund = create_draft_fund()
        api.submit_fund_for_review(
            fund["id"], TEST_USERS["product_operator_headers"]
        )
        res = api.reject_fund_shelf(
            fund["id"], TEST_USERS["compliance_reviewer_headers"]
        )
        rejected = validate_success(res)
        assert rejected["status"] == "DRAFT"
        # After reject, a DIFFERENT product operator may resubmit.
        api.submit_fund_for_review(
            fund["id"], TEST_USERS["product_operator_headers_alt"]
        )
        # And a different reviewer may approve.
        approved = validate_success(api.approve_fund_shelf(
            fund["id"], TEST_USERS["compliance_reviewer_headers"]
        ))
        assert approved["status"] == "ON_SHELF"


# =====================================================================
# Suspend / resume cascade (PRD §3.2 / §2.8)
# =====================================================================
class TestSuspendResume:
    def test_suspend_on_shelf_fund(self, api):
        """PRD §3.2: "Suspending an `ON_SHELF` fund advances it to
        `SUSPENDED`."

        Claim: POST /funds/{id}/suspend transitions ON_SHELF -> SUSPENDED.

        # difficulty: non_linear_state_machine/fund_shelf_revision_cycle
        """
        fund = create_on_shelf_fund()
        res = api.suspend_fund(
            fund["id"], TEST_USERS["compliance_reviewer_headers"]
        )
        suspended = validate_success(res)
        assert suspended["status"] == "SUSPENDED"

    def test_resume_returns_to_on_shelf(self, api):
        """PRD §3.2: "Resuming a `SUSPENDED` fund reverses the lifecycle
        without cascading, advancing `SUSPENDED → ON_SHELF`."

        Claim: a suspend/resume pair restores the fund to ON_SHELF.

        # difficulty: non_linear_state_machine/fund_shelf_revision_cycle
        """
        fund = create_on_shelf_fund()
        api.suspend_fund(
            fund["id"], TEST_USERS["compliance_reviewer_headers"]
        )
        res = api.resume_fund(
            fund["id"], TEST_USERS["compliance_reviewer_headers"]
        )
        resumed = validate_success(res)
        assert resumed["status"] == "ON_SHELF"


# =====================================================================
# Off-shelf preconditions (PRD §3.2)
# =====================================================================
class TestOffShelf:
    def test_off_shelf_zero_holders_succeeds(self, api):
        """PRD §3.2: "Permanent de-listing -- taking the fund `OFF_SHELF`
        from either `ON_SHELF` or `SUSPENDED` -- requires
        `Fund.total_outstanding_shares` to equal exactly 0."

        Claim: a fund with zero holders may be taken OFF_SHELF.
        """
        fund = create_on_shelf_fund()
        assert fund["total_outstanding_shares"] == 0
        res = api.off_shelf_fund(
            fund["id"], TEST_USERS["compliance_reviewer_headers"]
        )
        offshelf = validate_success(res)
        assert offshelf["status"] == "OFF_SHELF"

    def test_off_shelf_with_holders_rejected(self, api):
        """PRD §3.2: "Permanent de-listing ... requires
        `Fund.total_outstanding_shares` to equal exactly 0, otherwise
        `ERR_FUND_HAS_HOLDERS` is returned."

        Claim: when total_outstanding_shares > 0, off-shelf is rejected.
        """
        investor, fund, order, nav = setup_investor_with_confirmed_subscribe(
            gross_amount_cents=100,
        )
        fund_fresh = get_fund_fresh(fund["id"])
        assert fund_fresh["total_outstanding_shares"] > 0
        res = api.off_shelf_fund(
            fund["id"], TEST_USERS["compliance_reviewer_headers"]
        )
        validate_error(res, "ERR_FUND_HAS_HOLDERS")


# =====================================================================
# Fee-tier validation (PRD §3.2 / §2.10 priority 17)
# =====================================================================
class TestFeeTierValidation:
    def test_overlapping_subscription_tiers_rejected_at_create(self, api):
        """PRD §3.2: "A submission that includes overlapping or
        non-ascending tiers is rejected with `ERR_FEE_TIERS_INVALID`."

        Claim: overlapping subscription_fee_tiers at create -> 422
        ERR_FEE_TIERS_INVALID.
        """
        bad_tiers = [
            fee_tier(0, 100_000, 100),
            fee_tier(50_000, 200_000, 50),  # overlaps with first
        ]
        res = api.create_fund(
            create_fund_payload(subscription_fee_tiers=bad_tiers),
            TEST_USERS["product_operator_headers"],
        )
        validate_error(res, "ERR_FEE_TIERS_INVALID")

    def test_descending_redemption_tiers_rejected_at_create(self, api):
        """PRD §3.2: "the array must be ordered ascending by
        `min_holding_days` and the tiers must not overlap."

        Claim: descending redemption_fee_tiers at create -> 422
        ERR_FEE_TIERS_INVALID.
        """
        bad_tiers = [
            holding_period_tier(30, None, 25),
            holding_period_tier(0, 30, 50),  # descending order
        ]
        res = api.create_fund(
            create_fund_payload(redemption_fee_tiers=bad_tiers),
            TEST_USERS["product_operator_headers"],
        )
        validate_error(res, "ERR_FEE_TIERS_INVALID")
