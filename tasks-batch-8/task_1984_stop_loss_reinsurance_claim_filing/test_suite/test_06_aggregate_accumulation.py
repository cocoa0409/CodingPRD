"""Aggregate accumulation: the per-member cap (mirroring rule), the laser
interaction, and the pinned specific-first evaluation order."""
from test_helpers import (
    assert_accumulation_invariants,
    create_and_pay_claim,
    create_laser,
    create_member,
    get_aggregate_row,
    get_specific_row,
    setup_plan_contract_member,
)


def _three_member_book():
    """Contract with aggregating cap 150000_00 / aggregate ded 250000_00;
    members A, B, C enrolled; B lasered at 180000_00."""
    ctx = setup_plan_contract_member(
        plan_name="Gamma Health", member_external_id="A",
        aggregate_deductible_cents=25_000_000,
        aggregating_specific_deductible_cents=15_000_000)
    plan_id = ctx["plan"]["id"]
    contract_id = ctx["contract"]["id"]
    m2 = create_member(plan_id, "B")
    m3 = create_member(plan_id, "C")
    create_laser(contract_id, m2["id"], 18_000_000,
                 "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
    ctx["m2"] = m2
    ctx["m3"] = m3
    return ctx


def _pay_three(ctx):
    m1, m2, m3 = ctx["member"], ctx["m2"], ctx["m3"]
    plan_id = ctx["plan"]["id"]
    create_and_pay_claim(plan_id, m1["id"], 20_000_000,
                         service_date="2026-02-01T00:00:00Z",
                         paid_date="2026-02-02T00:00:00Z")
    create_and_pay_claim(plan_id, m2["id"], 19_000_000,
                         service_date="2026-03-01T00:00:00Z",
                         paid_date="2026-03-02T00:00:00Z")
    create_and_pay_claim(plan_id, m3["id"], 8_000_000,
                         service_date="2026-04-01T00:00:00Z",
                         paid_date="2026-04-02T00:00:00Z")


class TestAggregateCapWithLaserInteraction:
    def test_aggregate_caps_each_member_before_summing(self, api):
        """PRD §3.4: "Immediately after the specific sweep — never before,
        per the pinned order of §2.6 — the aggregate sweep runs. Each
        member's contribution is the lesser of that member's total eligible
        paid amount and the cap (`aggregating_specific_deductible_cents` when
        present, otherwise `specific_deductible_cents`); the capped
        integer-cent contributions are then summed into the aggregate row's
        `accumulated_cents`."

        Design: Difficulty/combinatorial_formula/aggregate_cap_with_laser_interaction_mode_a
        """
        ctx = _three_member_book()
        _pay_three(ctx)
        row = get_aggregate_row(ctx["contract"]["id"])
        # min(20000000,15000000) + min(19000000,15000000) + min(8000000,15000000)
        assert row["accumulated_cents"] == 38_000_000, (
            f"Aggregate accumulated must be 38000000, got "
            f"{row['accumulated_cents']}")
        assert row["applicable_deductible_cents"] == 25_000_000
        assert_accumulation_invariants(row)
        assert row["excess_cents"] == 13_000_000, (
            f"Aggregate excess must be 38000000 - 25000000 = 13000000, got "
            f"{row['excess_cents']}")
        assert row["member_id"] is None

    def test_lasered_member_specific_row_uses_lasered_deductible(self, api):
        """PRD §3.4: "The `applicable_deductible_cents` for the row is the
        lasered override when an `ACTIVE` laser covers the member for the
        service window, and the contract's `specific_deductible_cents`
        otherwise."
        PRD §3.3: "A laser takes effect in the ledger at once: creation
        recalculates the `SPECIFIC` accumulation row for that contract and
        member so that `applicable_deductible_cents` reflects the lasered
        override"

        Design: Difficulty/combinatorial_formula/aggregate_cap_with_laser_interaction_mode_a
        """
        ctx = _three_member_book()
        _pay_three(ctx)
        row = get_specific_row(ctx["contract"]["id"], ctx["m2"]["id"])
        assert row["applicable_deductible_cents"] == 18_000_000, (
            f"Lasered member's applicable deductible must be 18000000, got "
            f"{row['applicable_deductible_cents']}")
        assert row["accumulated_cents"] == 19_000_000
        assert_accumulation_invariants(row)
        assert row["excess_cents"] == 1_000_000, (
            f"Lasered specific excess must be 19000000 - 18000000 = 1000000, "
            f"got {row['excess_cents']}")


def _two_member_book():
    """Contract with specific ded 100000_00, aggregating cap 110000_00,
    aggregate ded 120000_00; members A and B enrolled."""
    ctx = setup_plan_contract_member(
        plan_name="Delta Health", member_external_id="A",
        aggregate_deductible_cents=12_000_000,
        aggregating_specific_deductible_cents=11_000_000)
    ctx["m2"] = create_member(ctx["plan"]["id"], "B")
    return ctx


def _pay_two(ctx):
    plan_id = ctx["plan"]["id"]
    create_and_pay_claim(plan_id, ctx["member"]["id"], 15_000_000,
                         service_date="2026-02-01T00:00:00Z",
                         paid_date="2026-02-02T00:00:00Z")
    create_and_pay_claim(plan_id, ctx["m2"]["id"], 3_000_000,
                         service_date="2026-03-01T00:00:00Z",
                         paid_date="2026-03-02T00:00:00Z")


class TestAggregateEvaluationOrder:
    def test_specific_sweep_reports_full_per_member_excess(self, api):
        """PRD §2.6: "First, the per-member specific sweep always completes
        before the plan-wide aggregate sweep begins, so the aggregate
        computation always sees final per-member amounts even though the two
        appear to depend on one another."
        PRD §3.4: "The row's `excess_cents` is the amount by which the
        accumulated total exceeds the applicable deductible, or zero when it
        does not."

        Design: Difficulty/combinatorial_formula/aggregate_evaluation_order_mode_c
        """
        ctx = _two_member_book()
        _pay_two(ctx)
        row = get_specific_row(ctx["contract"]["id"], ctx["member"]["id"])
        assert row["accumulated_cents"] == 15_000_000
        assert row["applicable_deductible_cents"] == 10_000_000
        assert_accumulation_invariants(row)
        assert row["excess_cents"] == 5_000_000, (
            f"Specific excess must be 15000000 - 10000000 = 5000000, got "
            f"{row['excess_cents']}")

    def test_aggregate_uses_capped_totals_not_net_of_specific_recovery(self, api):
        """PRD §2.6: "Second, each member's contribution to the aggregate is
        capped at the contract's `aggregating_specific_deductible_cents` when
        one is present, and otherwise at the contract's
        `specific_deductible_cents` — the mirroring rule, so named because no
        member may contribute more toward the aggregate deductible than the
        per-member deductible the contract mirrors. Caps are applied to each
        member as integer cents first and only then summed; there is no
        rounding after the summation."

        Design: Difficulty/combinatorial_formula/aggregate_evaluation_order_mode_c
        """
        ctx = _two_member_book()
        _pay_two(ctx)
        row = get_aggregate_row(ctx["contract"]["id"])
        # min(15000000,11000000) + min(3000000,11000000); the specific sweep's
        # 5000000 excess is not netted out of the aggregate.
        assert row["accumulated_cents"] == 14_000_000, (
            f"Aggregate accumulated must be 14000000, got "
            f"{row['accumulated_cents']}")
        assert row["applicable_deductible_cents"] == 12_000_000
        assert_accumulation_invariants(row)
        assert row["excess_cents"] == 2_000_000, (
            f"Aggregate excess must be 14000000 - 12000000 = 2000000, got "
            f"{row['excess_cents']}")
