"""Filing workflow: the dispute cycle, submission gates, and deadlines."""
from test_helpers import (
    ApiErrorId,
    create_filing,
    dispute_filing,
    get_filing,
    list_line_items,
    set_clock,
    setup_draft_filing,
    setup_paid_claim_scenario,
    setup_under_review_filing,
    submit_filing,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api_client
from test_helpers.fixtures import ANALYST, REVIEWER


class TestDisputeCycle:
    def test_dispute_moves_to_disputed_and_flags_line(self, api):
        """PRD §3.6: "The dispute path challenges individual charges. The
        reviewer supplies `disputed_line_item_ids`, and the system sets
        `disputed` to true on each listed line as the filing moves from
        `UNDER_REVIEW` to `DISPUTED`."

        Design: Difficulty/non_linear_state_machine/filing_dispute_cycle
        """
        ctx = setup_under_review_filing(plan_name="Epsilon",
                                        claim_cents=15_000_000)
        filing_id = ctx["filing"]["id"]
        line_id = list_line_items(filing_id)[0]["id"]

        resp = _api_client.dispute_filing(
            filing_id, {"disputed_line_item_ids": [line_id]}, REVIEWER)
        filing = validate_success(resp, 200)
        assert filing["status"] == "DISPUTED", (
            f"Filing must move to DISPUTED, got {filing['status']}")
        line = [l for l in list_line_items(filing_id) if l["id"] == line_id][0]
        assert line["disputed"] is True, "Listed line must be flagged disputed"

    def test_resolve_dispute_returns_to_under_review_and_clears_flags(self, api):
        """PRD §3.6: "A `StopLossAnalyst` then works the dispute and resolves
        it: the flags on the resolved lines are cleared,
        `requested_amount_cents` is recomputed through the filing sweep, and
        the filing returns from `DISPUTED` to `UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/filing_dispute_cycle
        """
        ctx = setup_under_review_filing(plan_name="Epsilon",
                                        claim_cents=15_000_000)
        filing_id = ctx["filing"]["id"]
        line_id = list_line_items(filing_id)[0]["id"]
        dispute_filing(filing_id, [line_id])
        assert get_filing(filing_id)["status"] == "DISPUTED"

        resp = _api_client.resolve_dispute(filing_id, ANALYST)
        filing = validate_success(resp, 200)
        assert filing["status"] == "UNDER_REVIEW", (
            f"Filing must return to UNDER_REVIEW, got {filing['status']}")
        line = [l for l in list_line_items(filing_id) if l["id"] == line_id][0]
        assert line["disputed"] is False, "Resolved line must be cleared"
        # Recomputed through the sweep: 150000_00 paid, 100000_00 deductible.
        assert filing["requested_amount_cents"] == 5_000_000


class TestZeroRequestedAmountBoundary:
    def test_zero_requested_amount_submit_rejected(self, api):
        """PRD §3.5: "Then the fiscal gate: `requested_amount_cents` must be
        greater than zero, else `ERR_AMOUNT_OUT_OF_RANGE`."

        Design: Difficulty/boundary_precision_check/filing_submit_zero_requested_amount_rejected
        """
        # Claim of 80000_00 sits entirely below the 100000_00 deductible:
        # eligible excess is zero, so the filing's requested total is zero.
        # (80000_00 >= 0.50 * deductible, so the notice is armed and filed
        # first to keep the notice gate out of the way.)
        ctx = setup_paid_claim_scenario(plan_name="Mu", claim_cents=8_000_000,
                                        file_the_notice=True)
        filing = create_filing(ctx["contract"]["id"], [ctx["claim"]["id"]],
                               filing_scope="SPECIFIC",
                               member_id=ctx["member"]["id"])
        assert filing["requested_amount_cents"] == 0
        resp = _api_client.submit_filing(filing["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_AMOUNT_OUT_OF_RANGE)
        assert get_filing(filing["id"])["status"] == "DRAFT"

    def test_one_cent_requested_amount_submits(self, api):
        """PRD §3.5: "Then the fiscal gate: `requested_amount_cents` must be
        greater than zero, else `ERR_AMOUNT_OUT_OF_RANGE`."
        PRD §3.5: "A successful submission stamps `submitted_at` with the
        current logical instant and increments the filing's `version` by
        one."

        Design: Difficulty/boundary_precision_check/filing_submit_zero_requested_amount_rejected
        """
        # Claim of 100000_01 exceeds the 100000_00 deductible by one cent.
        ctx = setup_paid_claim_scenario(plan_name="Mu", claim_cents=10_000_001,
                                        file_the_notice=True)
        filing = create_filing(ctx["contract"]["id"], [ctx["claim"]["id"]],
                               filing_scope="SPECIFIC",
                               member_id=ctx["member"]["id"])
        assert filing["requested_amount_cents"] == 1
        resp = _api_client.submit_filing(filing["id"], ANALYST)
        submitted = validate_success(resp, 200)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_at"] is not None, (
            "A successful submission stamps submitted_at")


class TestFilingDeadline:
    def test_submit_after_deadline_rejected(self, api):
        """PRD §3.5: "Last comes the deadline gate: the current logical
        instant must be on or before `policy_year_end` plus
        `filing_deadline_days`, with the final day itself still admissible; a
        later submission is rejected with `ERR_FILING_DEADLINE_PASSED`."

        Design: Corner/validations/filing_deadline_passed_rejected
        """
        ctx = setup_draft_filing(plan_name="P", claim_cents=15_000_000,
                                 filing_deadline_days=30)
        # Deadline is 2027-01-01 + 30 days = 2027-01-31; 2027-02-15 is past it.
        set_clock("2027-02-15T00:00:00Z")
        resp = _api_client.submit_filing(ctx["filing"]["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_FILING_DEADLINE_PASSED)
        assert get_filing(ctx["filing"]["id"])["status"] == "DRAFT"


class TestStateGatePrecedesDeadlineGate:
    def _submitted_filing_then_clock_past_deadline(self):
        ctx = setup_draft_filing(plan_name="Iota", claim_cents=15_000_000,
                                 filing_deadline_days=30)
        set_clock("2027-01-15T00:00:00Z")  # within the 2027-01-31 deadline
        submitted = submit_filing(ctx["filing"]["id"])
        assert submitted["status"] == "SUBMITTED"
        set_clock("2027-03-01T00:00:00Z")  # now past the deadline too
        return ctx

    def test_resubmit_past_deadline_reports_invalid_state(self, api):
        """PRD §3.5: "Submission moves the filing from `DRAFT` to `SUBMITTED`
        and evaluates its gates in a fixed order, so an earlier gate is never
        masked by a later one. The state gate comes first: the filing must be
        in `DRAFT`, at least one line item must exist, and every line's claim
        must be in `PAID` status — violations surface as `ERR_INVALID_STATE`."
        PRD §3.5: "Last comes the deadline gate: the current logical instant
        must be on or before `policy_year_end` plus `filing_deadline_days`,
        with the final day itself still admissible; a later submission is
        rejected with `ERR_FILING_DEADLINE_PASSED`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_filing_submit
        """
        ctx = self._submitted_filing_then_clock_past_deadline()
        resp = _api_client.submit_filing(ctx["filing"]["id"], ANALYST)
        # The filing is SUBMITTED (state violation) AND the deadline has
        # passed; the state gate is evaluated first.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_resubmit_leaves_filing_submitted(self, api):
        """PRD §3.5: "The state gate comes first: the filing must be in
        `DRAFT`, at least one line item must exist, and every line's claim
        must be in `PAID` status — violations surface as
        `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_filing_submit
        """
        ctx = self._submitted_filing_then_clock_past_deadline()
        before = get_filing(ctx["filing"]["id"])
        resp = _api_client.submit_filing(ctx["filing"]["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_filing(ctx["filing"]["id"])
        assert after["status"] == "SUBMITTED"
        assert after["submitted_at"] == before["submitted_at"], (
            "A rejected re-submission must not move submitted_at")
