"""Compensating invariant: paying then reversing a claim leaves the
accumulation ledgers with zero net drift."""
from test_helpers import (
    adjudicate_claim,
    assert_accumulation_invariants,
    create_claim,
    get_claim,
    get_member,
    get_specific_row,
    get_aggregate_row,
    setup_plan_contract_member,
    validate_success,
)
from test_helpers import api_client as _api_client
from test_helpers.fixtures import EXAMINER


def _adjudicated_claim(ctx, amount=4_000_000):
    claim = create_claim(ctx["plan"]["id"], ctx["member"]["id"],
                         billed_amount_cents=amount)
    adjudicate_claim(claim["id"], amount)
    return claim


class TestPayReversePreservesAccumulation:
    def test_specific_row_returns_to_baseline_after_reverse(self, api):
        """PRD §3.4: "Reversal removes the claim's contribution by
        recomputing both sweeps without it."
        PRD §3.4: "The member's specific row sums the `paid_amount_cents` of
        all that member's claims in `PAID` status whose inclusion date —
        `service_date` under a `POLICY_YEAR` contract, `paid_date` under a
        `PAID` contract — falls within the window from `run_in_days` before
        `policy_year_start` up to but not including `run_out_days` after
        `policy_year_end`."

        Design: Difficulty/compensating_invariant/claim_pay_reverse_preserves_accumulation
        """
        ctx = setup_plan_contract_member(plan_name="Rho")
        claim = _adjudicated_claim(ctx)
        before = get_specific_row(ctx["contract"]["id"], ctx["member"]["id"])
        assert before["accumulated_cents"] == 0

        resp = _api_client.pay_claim(
            claim["id"], {"paid_amount_cents": 4_000_000,
                          "paid_date": "2026-02-02T00:00:00Z"}, EXAMINER)
        validate_success(resp, 200)
        after_pay = get_specific_row(ctx["contract"]["id"], ctx["member"]["id"])
        assert after_pay["accumulated_cents"] == 4_000_000
        assert_accumulation_invariants(after_pay)

        resp = _api_client.reverse_claim(claim["id"], EXAMINER)
        validate_success(resp, 200)
        after_reverse = get_specific_row(
            ctx["contract"]["id"], ctx["member"]["id"])
        assert after_reverse["accumulated_cents"] == before["accumulated_cents"], (
            f"Net drift must be zero: baseline {before['accumulated_cents']}, "
            f"got {after_reverse['accumulated_cents']} after pay+reverse")
        assert_accumulation_invariants(after_reverse)

    def test_aggregate_row_and_member_notice_return_to_baseline(self, api):
        """PRD §3.4: "Reversal removes the claim's contribution by
        recomputing both sweeps without it."
        PRD §3.4: "When a reversal pulls the member's accumulation back below
        the notice threshold and `notice_triggered` flips from true to false,
        a member still in `NOTICE_PENDING` is reset to `NONE` — but a member
        whose notice already reached `NOTICE_FILED` stays filed."

        Design: Difficulty/compensating_invariant/claim_pay_reverse_preserves_accumulation
        """
        ctx = setup_plan_contract_member(plan_name="Rho")
        claim = _adjudicated_claim(ctx)
        contract_id = ctx["contract"]["id"]
        agg_before = get_aggregate_row(contract_id)
        assert agg_before["accumulated_cents"] == 0

        # 40000_00 stays below the 0.50 * 100000_00 notice threshold.
        validate_success(_api_client.pay_claim(
            claim["id"], {"paid_amount_cents": 4_000_000,
                          "paid_date": "2026-02-02T00:00:00Z"}, EXAMINER), 200)
        agg_paid = get_aggregate_row(contract_id)
        # Aggregate cap is the base specific deductible (no aggregating cap).
        assert agg_paid["accumulated_cents"] == 4_000_000
        assert_accumulation_invariants(agg_paid)
        assert get_member(ctx["member"]["id"])["notice_status"] == "NONE"

        reversed_claim = validate_success(
            _api_client.reverse_claim(claim["id"], EXAMINER), 200)
        assert reversed_claim["status"] == "REVERSED"
        agg_after = get_aggregate_row(contract_id)
        assert agg_after["accumulated_cents"] == agg_before["accumulated_cents"]
        assert_accumulation_invariants(agg_after)
        assert get_member(ctx["member"]["id"])["notice_status"] == "NONE"
        assert get_claim(claim["id"])["status"] == "REVERSED"
