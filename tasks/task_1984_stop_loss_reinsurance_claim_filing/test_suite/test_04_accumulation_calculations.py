"""Accumulation sweeps and the filing requested-amount calculation."""
from test_helpers import (
    assert_accumulation_invariants,
    assert_filing_line_item,
    create_and_pay_claim,
    create_filing,
    get_specific_row,
    list_line_items,
    setup_plan_contract_member,
)


class TestFilingSweepChronology:
    def test_filing_requested_amount_chronological_position(self, api):
        """PRD §3.5: "The filing's `requested_amount_cents` comes out of the
        filing sweep, which runs over the attached claims in `PAID` status
        ordered by service date and then creation timestamp."
        PRD §3.5: "The line's `eligible_excess_cents` is then the amount by
        which the new running total exceeds the greater of the prior position
        and the applicable deductible — taken as zero when it does not exceed
        it — minus the amount by which the prior position already exceeded the
        applicable deductible, again taken as zero when it did not."
        PRD §3.5: "Each line's eligible excess feeds the requested total, and
        the final requested total becomes `requested_amount_cents`."

        Design: Corner/calculations/filing_requested_amount_chronological_position
        """
        ctx = setup_plan_contract_member(plan_name="P")
        plan_id = ctx["plan"]["id"]
        member_id = ctx["member"]["id"]
        cl1 = create_and_pay_claim(plan_id, member_id, 8_000_000,
                                   service_date="2026-02-01T00:00:00Z",
                                   paid_date="2026-02-02T00:00:00Z")
        cl2 = create_and_pay_claim(plan_id, member_id, 5_000_000,
                                   service_date="2026-03-01T00:00:00Z",
                                   paid_date="2026-03-02T00:00:00Z")
        filing = create_filing(ctx["contract"]["id"], [cl1["id"], cl2["id"]],
                               filing_scope="SPECIFIC", member_id=member_id)

        # Specific deductible is 10_000_000: the first claim (8_000_000) sits
        # entirely below it; only 3_000_000 of the second claim sits above.
        assert filing["requested_amount_cents"] == 3_000_000, (
            f"requested_amount_cents must be 3000000, got "
            f"{filing['requested_amount_cents']}")

        lines = list_line_items(filing["id"])
        assert len(lines) == 2
        by_claim = {line["claim_id"]: line for line in lines}
        for line in lines:
            assert_filing_line_item(line)
        assert by_claim[cl1["id"]]["eligible_excess_cents"] == 0, (
            "First claim sits below the deductible: eligible excess 0")
        assert by_claim[cl2["id"]]["eligible_excess_cents"] == 3_000_000, (
            "Second claim's excess is its portion above the deductible")
        assert by_claim[cl1["id"]]["disputed"] is False
        assert by_claim[cl2["id"]]["disputed"] is False


class TestImmediateConsistency:
    def test_accumulation_visible_immediately_after_pay(self, api):
        """PRD §1: "The consistency model is immediate: every claim mutation
        recomputes the affected accumulation ledgers before the response
        returns."
        PRD §3.4: "The member's specific row sums the `paid_amount_cents` of
        all that member's claims in `PAID` status whose inclusion date —
        `service_date` under a `POLICY_YEAR` contract, `paid_date` under a
        `PAID` contract — falls within the window from `run_in_days` before
        `policy_year_start` up to but not including `run_out_days` after
        `policy_year_end`."

        Design: Corner/consistency_model/immediate_consistency_on_claim_pay
        """
        ctx = setup_plan_contract_member(plan_name="P")
        claim = create_and_pay_claim(ctx["plan"]["id"], ctx["member"]["id"],
                                     7_000_000)
        row = get_specific_row(ctx["contract"]["id"], ctx["member"]["id"])
        assert row["accumulated_cents"] == 7_000_000, (
            f"SPECIFIC row must reflect the pay in the same transaction, got "
            f"{row['accumulated_cents']}")
        assert row["applicable_deductible_cents"] == 10_000_000
        assert_accumulation_invariants(row)
        assert row["excess_cents"] == 0
