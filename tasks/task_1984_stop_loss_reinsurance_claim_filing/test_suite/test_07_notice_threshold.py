"""The fifty-percent notice obligation: inclusive boundary, the pay ->
notice flip, and the filing submission gate."""
from test_helpers import (
    ApiErrorId,
    create_and_pay_claim,
    create_filing,
    file_notice,
    get_filing,
    get_member,
    get_specific_row,
    setup_plan_contract_member,
    setup_paid_claim_scenario,
    validate_error,
)
from test_helpers import api_client as _api_client
from test_helpers.fixtures import ANALYST


class TestNoticeThresholdBoundary:
    def test_accumulation_exactly_at_threshold_triggers_notice(self, api):
        """PRD §3.4: "On every recompute of a `SPECIFIC` row, the
        `notice_triggered` flag compares `accumulated_cents` against the
        `notice_threshold_pct` fraction of `applicable_deductible_cents`; the
        boundary is inclusive, so a member whose accumulation equals exactly
        the threshold fraction of the deductible has triggered the
        obligation."
        PRD §3.4: "When the flag flips from false to true, the member's
        `notice_status` moves from `NONE` to `NOTICE_PENDING`."

        Design: Difficulty/boundary_precision_check/notice_threshold_exact_equality_triggers
        """
        ctx = setup_plan_contract_member(plan_name="Lambda")
        member = ctx["member"]
        # Exactly 0.50 * 100000_00 = 50000_00 paid.
        create_and_pay_claim(ctx["plan"]["id"], member["id"], 5_000_000)
        row = get_specific_row(ctx["contract"]["id"], member["id"])
        assert row["notice_triggered"] is True, (
            "Accumulation equal to exactly 0.50 * deductible must trigger")
        assert get_member(member["id"])["notice_status"] == "NOTICE_PENDING"

    def test_one_cent_below_threshold_leaves_notice_untriggered(self, api):
        """PRD §3.4: "the boundary is inclusive, so a member whose
        accumulation equals exactly the threshold fraction of the deductible
        has triggered the obligation."
        PRD §3.4: "The comparison is evaluated in rational arithmetic, both
        sides multiplied through so the test lands on integer cents and no
        floating-point approximation can blur the boundary."

        Design: Difficulty/boundary_precision_check/notice_threshold_exact_equality_triggers
        """
        ctx = setup_plan_contract_member(plan_name="Lambda")
        member = ctx["member"]
        # One cent below 0.50 * 100000_00.
        create_and_pay_claim(ctx["plan"]["id"], member["id"], 4_999_999)
        row = get_specific_row(ctx["contract"]["id"], member["id"])
        assert row["notice_triggered"] is False, (
            "Accumulation one cent below the threshold must not trigger")
        assert get_member(member["id"])["notice_status"] == "NONE"


class TestNoticeGateOnFilingSubmit:
    def test_submit_blocked_while_notice_pending(self, api):
        """PRD §3.4: "When the flag flips from false to true, the member's
        `notice_status` moves from `NONE` to `NOTICE_PENDING`."
        PRD §3.5: "Next comes the notice gate: a `SPECIFIC` filing may not be
        submitted for a member whose `notice_status` is still
        `NOTICE_PENDING`, because the fifty-percent notice must reach the
        carrier before any specific reimbursement filing; the rejection is
        `ERR_NOTICE_OUTSTANDING`."

        Design: Difficulty/transitive_cascade/claim_pay_to_member_notice_to_filing_gate
        """
        # Claim of 60000_00 pushes the SPECIFIC accumulation to
        # 60000_00 >= 0.50 * 100000_00 without crossing the deductible.
        ctx = setup_paid_claim_scenario(plan_name="Eta", claim_cents=6_000_000,
                                        file_the_notice=False)
        member_id = ctx["member"]["id"]
        assert get_member(member_id)["notice_status"] == "NOTICE_PENDING"

        filing = create_filing(ctx["contract"]["id"], [ctx["claim"]["id"]],
                               filing_scope="SPECIFIC", member_id=member_id)
        resp = _api_client.submit_filing(filing["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_NOTICE_OUTSTANDING)
        assert get_filing(filing["id"])["status"] == "DRAFT"

    def test_notice_gate_clears_then_fiscal_gate_surfaces(self, api):
        """PRD §3.5: "Submission moves the filing from `DRAFT` to `SUBMITTED`
        and evaluates its gates in a fixed order, so an earlier gate is never
        masked by a later one."
        PRD §3.5: "Then the fiscal gate: `requested_amount_cents` must be
        greater than zero, else `ERR_AMOUNT_OUT_OF_RANGE`."

        Design: Difficulty/transitive_cascade/claim_pay_to_member_notice_to_filing_gate
        """
        ctx = setup_paid_claim_scenario(plan_name="Eta", claim_cents=6_000_000,
                                        file_the_notice=False)
        member_id = ctx["member"]["id"]
        filing = create_filing(ctx["contract"]["id"], [ctx["claim"]["id"]],
                               filing_scope="SPECIFIC", member_id=member_id)
        resp = _api_client.submit_filing(filing["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_NOTICE_OUTSTANDING)

        # Once the notice is filed, the notice gate passes and the filing's
        # zero requested amount (60000_00 < 100000_00 deductible) surfaces at
        # the fiscal gate instead.
        file_notice(member_id)
        assert get_member(member_id)["notice_status"] == "NOTICE_FILED"
        resp = _api_client.submit_filing(filing["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_AMOUNT_OUT_OF_RANGE)
        assert get_filing(filing["id"])["status"] == "DRAFT"
