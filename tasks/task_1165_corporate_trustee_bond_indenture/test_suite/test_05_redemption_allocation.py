"""Redemption pro-rata allocation: floor-then-remainder reconciliation,
tie-breaks, zero-cent records, and the principal conservation invariant
(PRD §3.2, §3.4)."""
import pytest

from test_helpers import (
    api_client, validate_success, ApiErrorId,
    CLOCK_START, set_clock,
    setup_indenture_with_positions, create_redemption_run, fund_run,
    execute_run, reverse_run, list_run_records, run_records_by_position,
    get_position, get_tranche, get_indenture,
    assert_payment_run, assert_principal_conservation,
)


def _setup_three_position_redemption(api, target=99999999):
    """Active indenture, positions 400M/350M/250M, funded redemption run."""
    set_clock(CLOCK_START)
    ctx = setup_indenture_with_positions(
        amounts=(400000000, 350000000, 250000000),
        holder_prefixes=("H-A", "H-B", "H-C"),
        tranche_overrides={"series_code": "T1", "original_principal_cents": 1000000000,
                           "notice_period_days": 30},
        reset_clock=False,
    )
    run = create_redemption_run(ctx["tranche"]["id"], target,
                                scheduled_payment_date="2026-06-15")
    fund_run(run["id"], target, issuer_ref="issuer-1")
    ctx["run"] = run
    return ctx


class TestProRataLargestRemainder:
    def test_pro_rata_floor_then_remainder_allocations(self, api):
        """PRD §3.4: "every raw share is floored to a whole cent first, and
        the remainder — the gross minus the sum of floored shares — is then
        distributed one cent at a time to positions in descending order of
        fractional part, with ties broken by creation time ascending and then
        by `original_principal_cents` descending, never by identifier."

        Target 99999999 over 400M/350M/250M: raw shares
        39999999.6 / 34999999.65 / 24999999.75 floor to a sum of 99999997;
        the two remainder cents go to the largest fractions (C then B).

        Design: Difficulty/combinatorial_formula/pro_rata_largest_remainder_reconciliation
        """
        ctx = _setup_three_position_redemption(api)
        run = execute_run(ctx["run"]["id"])
        assert_payment_run(run)
        assert run["gross_amount_cents"] == 99999999

        by_position = run_records_by_position(run["id"], ctx["positions"])
        expected = [39999999, 35000000, 25000000]
        total = 0
        for position, want in zip(ctx["positions"], expected):
            record = by_position[position["id"]]
            assert record["allocated_cents"] == want, (
                f"allocation for principal {position['principal_amount_cents']}: "
                f"expected {want}, got {record['allocated_cents']}")
            total += record["allocated_cents"]
        assert total == run["gross_amount_cents"] == 99999999, (
            "floor-first remainder reconciliation sums exactly to the gross")

    def test_pro_rata_reconciles_positions_and_tranche(self, api):
        """PRD §3.4: "Redemption execution then reduces each position's
        `principal_amount_cents` by its allocated share, appends the new value
        to `principal_history`, moves zeroed positions to `REDEEMED`,
        recomputes the tranche's `outstanding_principal_cents`, and recomputes
        the indenture's `outstanding_principal_cents`."

        Design: Difficulty/combinatorial_formula/pro_rata_largest_remainder_reconciliation
        """
        ctx = _setup_three_position_redemption(api)
        run = execute_run(ctx["run"]["id"])

        positions_after = [get_position(p["id"]) for p in ctx["positions"]]
        expected_principals = [360000001, 315000000, 225000000]
        for position, want in zip(positions_after, expected_principals):
            assert position["principal_amount_cents"] == want, (
                f"position principal after redemption: expected {want}, "
                f"got {position['principal_amount_cents']}")
            assert position["status"] == "ACTIVE"
            assert len(position["principal_history"]) == 2, (
                "history appended per executed redemption")

        tranche = get_tranche(ctx["tranche"]["id"])
        indenture = get_indenture(ctx["indenture"]["id"])
        assert tranche["outstanding_principal_cents"] == 900000001
        assert_principal_conservation(tranche, positions_after, indenture)


class TestRemainderTiebreak:
    def test_remainder_tiebreak_by_creation_time(self, api):
        """PRD §3.4: "the remainder — the gross minus the sum of floored
        shares — is then distributed one cent at a time to positions in
        descending order of fractional part, with ties broken by creation time
        ascending and then by `original_principal_cents` descending, never by
        identifier."

        Equal principals 50000/50000 with target 9999: identical floors 4999
        and identical fractions 0.5; the single remainder cent goes to the
        earlier-created position.

        Design: Corner/calculations/pro_rata_remainder_tiebreak_by_created_at
        """
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(50000, 50000),
            holder_prefixes=("H-Q1", "H-Q2"),
            tranche_overrides={"series_code": "T5", "original_principal_cents": 100000,
                               "payment_frequency": "ANNUAL", "notice_period_days": 30},
            reset_clock=False,
        )
        run = create_redemption_run(ctx["tranche"]["id"], 9999,
                                    scheduled_payment_date="2026-06-15")
        fund_run(run["id"], 9999, issuer_ref="issuer-1")
        run = execute_run(run["id"])

        by_position = run_records_by_position(run["id"], ctx["positions"])
        q1 = by_position[ctx["positions"][0]["id"]]
        q2 = by_position[ctx["positions"][1]["id"]]
        assert q1["allocated_cents"] == 5000, "earlier created_at wins the tied remainder"
        assert q2["allocated_cents"] == 4999
        assert q1["allocated_cents"] + q2["allocated_cents"] == 9999 == run["gross_amount_cents"]


class TestZeroCentAllocations:
    def test_zero_cent_allocations_still_create_records(self, api):
        """PRD §3.4: "On execution `executed_at` is stamped from the logical
        clock and the run creates one **DistributionRecord**, status
        `PENDING`, per `ACTIVE` position of the tranche — including records
        whose allocation computes to zero cents."

        A 1-cent redemption over 400M/350M/250M yields raw shares
        0.4/0.35/0.25 — all floors 0; the single remainder cent goes to A
        (largest fraction); B and C still receive zero-cent records.

        Design: Corner/calculations/redemption_zero_cent_allocation_records_created
        """
        ctx = _setup_three_position_redemption(api, target=1)
        run = execute_run(ctx["run"]["id"])

        records = list_run_records(run["id"])
        assert len(records) == 3, "zero-cent positions are not skipped"
        by_position = run_records_by_position(run["id"], ctx["positions"])
        expected = [1, 0, 0]
        for position, want in zip(ctx["positions"], expected):
            record = by_position[position["id"]]
            assert record["allocated_cents"] == want
            assert record["status"] == "PENDING"
        assert sum(r["allocated_cents"] for r in records) == 1 == run["gross_amount_cents"]


class TestRedemptionReversalConservation:
    def test_redemption_midflight_then_restored(self, api):
        """PRD §3.2: "Executing a redemption and then reversing that same run
        must leave all three quantities bit-identical to their pre-execution
        values."
        PRD §3.4: "redemption principal reductions are undone with
        `principal_amount_cents` restored and the restored value appended to
        `principal_history`"

        Design: Difficulty/compensating_invariant/redemption_execute_reverse_principal_conservation
        """
        ctx = _setup_three_position_redemption(api)
        run = execute_run(ctx["run"]["id"])

        # Mid-flight evidence: reductions applied.
        mid = [get_position(p["id"])["principal_amount_cents"] for p in ctx["positions"]]
        assert mid == [360000001, 315000000, 225000000]
        assert get_tranche(ctx["tranche"]["id"])["outstanding_principal_cents"] == 900000001

        reverse_run(run["id"])
        positions_after = [get_position(p["id"]) for p in ctx["positions"]]
        restored = [p["principal_amount_cents"] for p in positions_after]
        assert restored == [400000000, 350000000, 250000000], (
            f"bit-identical principal restoration, got {restored}")

    def test_redemption_reverse_restores_principal_exactly(self, api):
        """PRD §3.2: "for every tranche, `outstanding_principal_cents` always
        equals `original_principal_cents` minus the sum of principal
        reductions applied by executed, non-reversed redemption runs, and
        always equals the sum of `principal_amount_cents` over that tranche's
        `ACTIVE` positions; and the indenture's `outstanding_principal_cents`
        always equals the sum of its tranches' outstanding principal."
        PRD §3.4: "every record in `PENDING`, `HELD`, or `PAID` becomes
        `RETURNED`"

        Design: Difficulty/compensating_invariant/redemption_execute_reverse_principal_conservation
        """
        ctx = _setup_three_position_redemption(api)
        run = execute_run(ctx["run"]["id"])
        reverse_run(run["id"])

        tranche = get_tranche(ctx["tranche"]["id"])
        indenture = get_indenture(ctx["indenture"]["id"])
        positions_after = [get_position(p["id"]) for p in ctx["positions"]]
        assert tranche["outstanding_principal_cents"] == 1000000000
        assert indenture["outstanding_principal_cents"] == 1000000000
        assert_principal_conservation(tranche, positions_after, indenture)
        assert tranche["status"] == "ACTIVE"

        records = list_run_records(run["id"])
        assert len(records) == 3
        for record in records:
            assert record["status"] == "RETURNED"
