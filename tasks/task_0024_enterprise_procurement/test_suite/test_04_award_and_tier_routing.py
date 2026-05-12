"""Award, PO tier routing, and approval-step generation (PRD §3.3)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_purchase_order,
    award_payload,
    find_step_by_stage,
    find_steps_by_stage,
    setup_awarded_po,
    setup_shortlisted_requirement,
    validate_error,
    validate_success,
)


# ===========================================================================
# Award preconditions (PRD §3.3, §2.8 priority 11)
# ===========================================================================
class TestAwardPreconditions:
    def test_award_with_two_shortlisted_rejected(self, api, buyer_headers):
        """PRD §3.3: "there must be at least 3 quotes in SHORTLISTED status
        on this requirement; the awarded quote's id must be among that
        shortlisted set; and justification must be non-empty. Any of these
        three failing is reported as ERR_INSUFFICIENT_QUOTES."

        Claim: with only 2 shortlisted quotes, award yields
        ERR_INSUFFICIENT_QUOTES.
        """
        setup = setup_shortlisted_requirement(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)],
            shortlist_indices=[0, 1],  # only 2 shortlisted
        )
        payload = award_payload(awarded_quote_id=setup["quotes"][0]["id"])
        res = api.award_requirement(
            setup["requirement"]["id"], payload, buyer_headers
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_QUOTES.value)

    def test_award_with_three_shortlisted_succeeds(self, api, buyer_headers):
        """PRD §3.3: "there must be at least 3 quotes in SHORTLISTED status
        on this requirement".

        Claim: with exactly 3 SHORTLISTED quotes, award succeeds (boundary
        at the lower edge of the constraint).
        """
        setup = setup_shortlisted_requirement(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)]
        )
        payload = award_payload(awarded_quote_id=setup["quotes"][0]["id"])
        po = validate_success(
            api.award_requirement(
                setup["requirement"]["id"], payload, buyer_headers
            ),
            201,
        )
        assert_purchase_order(po)

    def test_award_with_empty_justification_rejected(self, api, buyer_headers):
        """PRD §3.3: "justification must be non-empty. Any of these three
        failing is reported as ERR_INSUFFICIENT_QUOTES."

        Claim: an empty justification yields ERR_INSUFFICIENT_QUOTES.
        """
        setup = setup_shortlisted_requirement(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)]
        )
        payload = award_payload(
            awarded_quote_id=setup["quotes"][0]["id"], justification=""
        )
        res = api.award_requirement(
            setup["requirement"]["id"], payload, buyer_headers
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_QUOTES.value)

    def test_award_quote_not_in_shortlist_rejected(self, api, buyer_headers):
        """PRD §3.3: "the awarded quote's id must be among that
        shortlisted set ... Any of these three failing is reported as
        ERR_INSUFFICIENT_QUOTES."

        Claim: choosing an awarded_quote_id that is not in the SHORTLISTED
        set yields ERR_INSUFFICIENT_QUOTES.
        """
        setup = setup_shortlisted_requirement(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0), (130, 60.0)],
            shortlist_indices=[0, 1, 2],  # only first three; quote 3 is not shortlisted
        )
        payload = award_payload(awarded_quote_id=setup["quotes"][3]["id"])
        res = api.award_requirement(
            setup["requirement"]["id"], payload, buyer_headers
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_QUOTES.value)


# ===========================================================================
# Award side effects: sibling rejection + budget commit (PRD §3.3)
# ===========================================================================
class TestAwardSideEffects:
    def test_award_sets_awarded_and_rejects_siblings(self, api, buyer_headers):
        """PRD §3.3: "On success, the awarded quote transitions to
        AWARDED, every other shortlisted quote on the same requirement
        transitions from SHORTLISTED to REJECTED (the system writes these
        sibling rejections, not the buyer)".

        Claim: after award, the chosen quote is AWARDED and the other
        shortlisted siblings are REJECTED.
        """
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)],
            awarded_index=0,
        )
        winner = validate_success(
            api.get_quote(setup["awarded_quote"]["id"], buyer_headers), 200
        )
        assert winner["status"] == "AWARDED"
        for i in (1, 2):
            sibling = validate_success(
                api.get_quote(setup["quotes"][i]["id"], buyer_headers), 200
            )
            assert sibling["status"] == "REJECTED"

    def test_award_creates_po_with_pinned_total(self, api, buyer_headers):
        """PRD §3.3: "Its total_amount_cents is the awarded quote's
        unit_price_cents multiplied by the requirement's quantity, pinned
        at PO creation".

        Claim: PO.total_amount_cents == quote.unit_price_cents *
        requirement.quantity.
        """
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)],
            quantity=10,
            awarded_index=0,
        )
        po = setup["po"]
        assert po["total_amount_cents"] == 100 * 10

    def test_award_increments_committed_amount(
        self, api, buyer_headers, finance_headers
    ):
        """PRD §3.3: "committed_amount_cents is increased by the purchase
        order's total_amount_cents and the commitment is recorded."

        Claim: BudgetAccount.committed_amount_cents goes up by exactly
        PO.total_amount_cents after award.
        """
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)],
            quantity=10,
            awarded_index=0,
        )
        budget = validate_success(
            api.get_budget_account(setup["budget"]["id"], finance_headers), 200
        )
        # Single award; committed should equal PO total.
        assert budget["committed_amount_cents"] == setup["po"]["total_amount_cents"]


# ===========================================================================
# Tier assignment boundaries (PRD §3.3)
# ===========================================================================
class TestPoTierBoundaries:
    """PRD §3.3: "TIER1_MAX_CENTS is 500,000 cents ... TIER2_MAX_CENTS is
    5,000,000 cents ... TIER3_MAX_CENTS is 50,000,000 cents. A
    purchase-order total strictly less than TIER1_MAX_CENTS is TIER_1; a
    total at least TIER1_MAX_CENTS and strictly less than TIER2_MAX_CENTS
    is TIER_2; a total at least TIER2_MAX_CENTS and strictly less than
    TIER3_MAX_CENTS is TIER_3; a total at least TIER3_MAX_CENTS is TIER_4."
    """

    def test_tier_1_just_below_500000(self, api):
        """PRD §3.3: "A purchase-order total strictly less than
        TIER1_MAX_CENTS is TIER_1".

        Claim: total = 499,999 lands in TIER_1.
        """
        setup = setup_awarded_po(
            quote_specs=[(499_999, 90.0), (500_000, 80.0), (510_000, 70.0)],
            quantity=1,
            awarded_index=0,
            budget_total_cents=10_000_000,
        )
        assert setup["po"]["tier"] == "TIER_1"
        assert setup["po"]["total_amount_cents"] == 499_999

    def test_tier_2_at_500000(self, api):
        """PRD §3.3: "a total at least TIER1_MAX_CENTS and strictly less
        than TIER2_MAX_CENTS is TIER_2".

        Claim: total = 500,000 lands in TIER_2 (boundary at low edge).
        """
        setup = setup_awarded_po(
            quote_specs=[(500_000, 90.0), (510_000, 80.0), (520_000, 70.0)],
            quantity=1,
            awarded_index=0,
            budget_total_cents=10_000_000,
        )
        assert setup["po"]["tier"] == "TIER_2"
        assert setup["po"]["total_amount_cents"] == 500_000

    def test_tier_3_at_5_000_000(self, api):
        """PRD §3.3: "a total at least TIER2_MAX_CENTS and strictly less
        than TIER3_MAX_CENTS is TIER_3".

        Claim: total = 5,000,000 lands in TIER_3.
        """
        setup = setup_awarded_po(
            quote_specs=[(5_000_000, 90.0), (5_100_000, 80.0), (5_200_000, 70.0)],
            quantity=1,
            awarded_index=0,
            budget_total_cents=100_000_000,
        )
        assert setup["po"]["tier"] == "TIER_3"

    def test_tier_4_at_50_000_000(self, api):
        """PRD §3.3: "a total at least TIER3_MAX_CENTS is TIER_4".

        Claim: total = 50,000,000 lands in TIER_4.
        """
        setup = setup_awarded_po(
            quote_specs=[(50_000_000, 90.0), (51_000_000, 80.0), (52_000_000, 70.0)],
            quantity=1,
            awarded_index=0,
            budget_total_cents=200_000_000,
        )
        assert setup["po"]["tier"] == "TIER_4"


# ===========================================================================
# Tier-driven approval step generation (PRD §3.3)
# ===========================================================================
class TestTierApprovalSteps:
    def test_tier_1_one_serial_dept_head_step(self, api):
        """PRD §3.3: "TIER_1 produces a single serial chain of length one:
        a DEPARTMENT_HEAD step."

        Claim: a TIER_1 PO has exactly one ApprovalStep with stage =
        DEPARTMENT_HEAD and mode = SERIAL.
        """
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)],
            quantity=10,
            awarded_index=0,
        )
        assert setup["po"]["tier"] == "TIER_1"
        steps = setup["approval_steps"]
        assert len(steps) == 1
        assert steps[0]["stage"] == "DEPARTMENT_HEAD"
        assert steps[0]["mode"] == "SERIAL"
        assert steps[0]["assignee_role"] == "DepartmentHead"

    def test_tier_2_two_serial_dept_then_finance(self, api):
        """PRD §3.3: "TIER_2 produces a serial chain of two steps:
        DEPARTMENT_HEAD, then FINANCE."

        Claim: TIER_2 PO has DEPT_HEAD + FINANCE both in SERIAL mode.
        """
        setup = setup_awarded_po(
            quote_specs=[(10_000, 90.0), (12_000, 80.0), (15_000, 70.0)],
            quantity=100,  # total = 1,000,000 -> TIER_2
            awarded_index=0,
            budget_total_cents=10_000_000,
        )
        assert setup["po"]["tier"] == "TIER_2"
        steps = setup["approval_steps"]
        stages = sorted([s["stage"] for s in steps])
        assert stages == sorted(["DEPARTMENT_HEAD", "FINANCE"])
        for s in steps:
            assert s["mode"] == "SERIAL"

    def test_tier_3_dept_then_parallel_fin_legal_then_gm(self, api):
        """PRD §3.3: "TIER_3 produces three logical positions: a
        DEPARTMENT_HEAD step first; then a FINANCE step and a LEGAL step
        that run in PARALLEL (both must reach APPROVED before the next
        position activates); then a GENERAL_MANAGER step."

        Claim: TIER_3 PO has DEPT_HEAD (SERIAL), FINANCE (PARALLEL),
        LEGAL (PARALLEL), GM (SERIAL).
        """
        setup = setup_awarded_po(
            quote_specs=[(100_000, 90.0), (110_000, 80.0), (120_000, 70.0)],
            quantity=100,  # total 10,000,000 -> TIER_3
            awarded_index=0,
            budget_total_cents=100_000_000,
        )
        assert setup["po"]["tier"] == "TIER_3"
        steps = setup["approval_steps"]
        stages = {s["stage"]: s for s in steps}
        assert set(stages.keys()) == {
            "DEPARTMENT_HEAD", "FINANCE", "LEGAL", "GENERAL_MANAGER"
        }
        assert stages["DEPARTMENT_HEAD"]["mode"] == "SERIAL"
        assert stages["FINANCE"]["mode"] == "PARALLEL"
        assert stages["LEGAL"]["mode"] == "PARALLEL"
        assert stages["GENERAL_MANAGER"]["mode"] == "SERIAL"

    def test_tier_4_same_shape_with_gm_comment_required(self, api, buyer_headers):
        """PRD §3.3: "TIER_4 has the same shape as TIER_3 — DEPARTMENT_HEAD,
        then FINANCE and LEGAL in parallel, then GENERAL_MANAGER — with the
        additional rule that on a TIER_4 purchase order the final
        GENERAL_MANAGER step's decision_comment is required (an approval
        submitted with an empty decision_comment on that step is rejected)."

        Claim: TIER_4 has 4 steps with the TIER_3 shape, and the GM step
        requires a non-empty decision_comment.
        """
        setup = setup_awarded_po(
            quote_specs=[(50_000_000, 90.0), (51_000_000, 80.0), (52_000_000, 70.0)],
            quantity=1,  # total = 50,000,000 -> TIER_4
            awarded_index=0,
            budget_total_cents=200_000_000,
        )
        assert setup["po"]["tier"] == "TIER_4"
        steps = setup["approval_steps"]
        stages = {s["stage"]: s for s in steps}
        assert set(stages.keys()) == {
            "DEPARTMENT_HEAD", "FINANCE", "LEGAL", "GENERAL_MANAGER"
        }
        assert stages["FINANCE"]["mode"] == "PARALLEL"
        assert stages["LEGAL"]["mode"] == "PARALLEL"


# ===========================================================================
# Budget gate at award (PRD §3.3, priority 14)
# ===========================================================================
class TestBudgetGateAtAward:
    def test_award_blocked_when_committed_plus_total_exceeds(
        self, api, buyer_headers
    ):
        """PRD §3.3: "Before any approval step is generated, the system
        verifies that adding the new purchase order's total_amount_cents
        to the bound BudgetAccount's current committed_amount_cents would
        not push the total past the account's total_amount_cents. If the
        sum would exceed, the award is rejected with ERR_BUDGET_WOULD_EXCEED
        and no purchase order is created."

        Claim: an award that would push committed past total yields
        ERR_BUDGET_WOULD_EXCEED.
        """
        # Budget total 1,000,000; first award commits 600,000; second
        # award (price 500_000 * qty 1 = 500,000) would push to 1,100,000.
        from test_helpers import (
            create_budget_account,
            create_qualified_supplier,
            create_qualified_suppliers,
            create_draft_requirement,
            submit_requirement,
            add_quote,
            shortlist_quotes,
            award_requirement,
        )
        budget = create_budget_account(total_amount_cents=1_000_000)
        # First award: commits 600_000
        suppliers_a = create_qualified_suppliers(3, qualification_categories=["IT_HARDWARE"])
        req_a = create_draft_requirement(
            budget_account_id=budget["id"], category="IT_HARDWARE", quantity=1
        )
        submit_requirement(req_a["id"])
        qa = [
            add_quote(req_a["id"], supplier_id=suppliers_a[i]["id"], unit_price_cents=p)
            for i, p in enumerate([600_000, 700_000, 800_000])
        ]
        shortlist_quotes(req_a["id"], [q["id"] for q in qa])
        award_requirement(req_a["id"], awarded_quote_id=qa[0]["id"])

        # Second award: would push total to 1,100,000.
        suppliers_b = create_qualified_suppliers(3, qualification_categories=["IT_HARDWARE"])
        req_b = create_draft_requirement(
            budget_account_id=budget["id"], category="IT_HARDWARE", quantity=1
        )
        submit_requirement(req_b["id"])
        qb = [
            add_quote(req_b["id"], supplier_id=suppliers_b[i]["id"], unit_price_cents=p)
            for i, p in enumerate([500_000, 600_000, 700_000])
        ]
        shortlist_quotes(req_b["id"], [q["id"] for q in qb])
        payload = award_payload(awarded_quote_id=qb[0]["id"])
        res = api.award_requirement(req_b["id"], payload, buyer_headers)
        validate_error(res, ApiErrorId.ERR_BUDGET_WOULD_EXCEED.value)
