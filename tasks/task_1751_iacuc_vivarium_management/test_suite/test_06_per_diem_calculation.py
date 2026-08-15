"""Per-diem calculation: PROVISIONAL vs FINAL variants, rat age-tier
max semantics, per-day rounding order, and adjacent-period exclusivity
(PRD §3.7).
"""
from test_helpers import (
    assert_per_diem_charge,
)
from test_helpers.fixtures import (
    add_cage,
    add_mouse,
    compute_provisional_ok,
    create_approved_protocol,
    create_billing_run,
    file_census,
    list_run_charges,
    setup_dual_variant_billing,
    setup_flat_rate_billing,
    setup_rat_tier_billing,
)


class TestProvisionalVsFinalVariants:
    def test_provisional_variant_bills_every_occupied_day(self, api):
        """PRD §3.7: "A cage accrues one billable cage-day, accumulated into
        `cage_days`, for each calendar day from `period_start` up to but not
        including `period_end` on which it held at least one `ALIVE` animal,
        regardless of headcount. The daily `rate_cents` is fixed by species:
        125 for mice, 400 for rabbits, 40 for zebrafish." and "the system
        creates one per-diem charge of `variant` `PROVISIONAL` for every cage
        occupied during the period".

        Design: Difficulty/dual_variant_calc/per_diem_provisional_vs_final_on_cage_billing
        """
        scenario = setup_dual_variant_billing()
        provisional = scenario["provisional_charges"]
        assert len(provisional) == 1
        charge = provisional[0]
        assert_per_diem_charge(charge)
        assert charge["variant"] == "PROVISIONAL"
        assert charge["cage_days"] == 21, (
            "the mouse was ALIVE for all of 2026-08-01..2026-08-21 at "
            "provisional time"
        )
        assert charge["rate_cents"] == 125
        assert charge["amount_cents"] == 2625, f"21 days x 125 = 2625, got {charge['amount_cents']}"

    def test_final_variant_excludes_retired_animal_from_status_change_date(self, api):
        """PRD §3.7: "Finalization moves the run from `PROVISIONAL` to
        `FINALIZED` and recomputes every charge as `variant` `FINAL` under the
        reconciled-census model: identical to the provisional model except
        that a day counts only when a reconciled census — a census record
        whose `discrepancy` is zero — confirms occupancy for that day, and
        animals that reached `RETIRED` or `EUTHANIZED` before `period_end` are
        excluded from the day's headcount on and after their status-change
        date. The two variants therefore diverge precisely when a mid-period
        retirement or euthanasia occurred."

        Design: Difficulty/dual_variant_calc/per_diem_provisional_vs_final_on_cage_billing
        """
        scenario = setup_dual_variant_billing()
        provisional_amount = scenario["provisional_charges"][0]["amount_cents"]

        final_charges = scenario["final_charges"]
        assert len(final_charges) == 1
        charge = final_charges[0]
        assert_per_diem_charge(charge)
        assert charge["variant"] == "FINAL"
        assert charge["cage_days"] == 10, (
            "the mouse retired with status-change date 2026-08-11, so only "
            "2026-08-01..2026-08-10 remain billable"
        )
        assert charge["amount_cents"] == 1250, f"10 days x 125 = 1250, got {charge['amount_cents']}"
        assert charge["amount_cents"] != provisional_amount, (
            "FINAL (1250) must diverge from PROVISIONAL (2625) after a "
            "mid-period retirement"
        )
        assert provisional_amount == 2625


class TestRatAgeTiering:
    def test_mixed_age_rat_cage_bills_at_highest_tier(self, api):
        """PRD §3.7: "Rat cages are tiered by the ages of the rats present
        each day: a rat younger than 21 days bills at the pup rate of 75, a
        rat older than 365 days bills at the aged rate of 210, and any other
        rat bills at the adult rate of 150; a cage housing rats of mixed ages
        bills the whole day at the highest tier present among its rats."

        Design: Difficulty/combinatorial_formula/rat_cage_tiered_daily_rate_mixed_ages
        """
        scenario = setup_rat_tier_billing()
        by_cage = {c["cage_id"]: c for c in scenario["charges"]}
        mixed = by_cage[scenario["cage_aged"]["id"]]
        assert_per_diem_charge(mixed)
        assert mixed["rate_cents"] == 210, (
            "mixed-age cage bills the whole day at the highest tier present"
        )
        assert mixed["cage_days"] == 21
        assert mixed["amount_cents"] == 4410, f"21 days x 210 = 4410, got {mixed['amount_cents']}"

    def test_rat_tiers_combine_by_max_not_sum(self, api):
        """PRD §3.7: "a cage housing rats of mixed ages bills the whole day at
        the highest tier present among its rats." An additive reading would
        produce 21 x (150 + 210) = 7560; the max-tier rule produces 4410, and
        the adult-only cage bills 21 x 150 = 3150.

        Design: Difficulty/combinatorial_formula/rat_cage_tiered_daily_rate_mixed_ages
        """
        scenario = setup_rat_tier_billing()
        by_cage = {c["cage_id"]: c for c in scenario["charges"]}
        mixed = by_cage[scenario["cage_aged"]["id"]]
        adult = by_cage[scenario["cage_adult"]["id"]]
        assert adult["rate_cents"] == 150
        assert adult["cage_days"] == 21
        assert adult["amount_cents"] == 3150, f"21 days x 150 = 3150, got {adult['amount_cents']}"
        assert mixed["amount_cents"] == 4410
        assert mixed["amount_cents"] != 21 * (150 + 210), (
            "max-tier semantics: the mixed cage must not bill the sum of tiers"
        )


class TestPerDayRoundingOrder:
    def test_zebrafish_flat_rate_and_cage_days(self, api):
        """PRD §3.7: "The daily `rate_cents` is fixed by species: 125 for
        mice, 400 for rabbits, 40 for zebrafish." and a cage accrues "one
        billable cage-day ... for each calendar day from `period_start` up to
        but not including `period_end` on which it held at least one `ALIVE`
        animal" — 21 days for [2026-08-01, 2026-08-22).

        Design: Difficulty/combinatorial_formula/per_diem_per_day_rounding_order
        """
        scenario = setup_flat_rate_billing()
        assert len(scenario["charges"]) == 1
        charge = scenario["charges"][0]
        assert_per_diem_charge(charge)
        assert charge["rate_cents"] == 40, "zebrafish flat daily rate"
        assert charge["cage_days"] == 21

    def test_zebrafish_amount_is_sum_of_per_day_rounded_charges(self, api):
        """PRD §3.7: "Each cage's `amount_cents` is the sum over its billable
        days of that day's rate, with each day's charge rounded half-up to
        integer cents before the days are summed." For the integer 40-cent
        zebrafish rate the per-day-then-sum order pins amount_cents to exactly
        21 x 40 = 840.

        Design: Difficulty/combinatorial_formula/per_diem_per_day_rounding_order
        """
        scenario = setup_flat_rate_billing()
        charge = scenario["charges"][0]
        assert charge["variant"] == "PROVISIONAL"
        assert charge["amount_cents"] == 840, (
            f"per-day rounding then summing pins 21 x 40 = 840 exactly, got "
            f"{charge['amount_cents']}"
        )
        assert isinstance(charge["amount_cents"], int), (
            "all money is integer cents (PRD §2.9)"
        )


class TestAdjacentBillingPeriods:
    def _two_adjacent_runs(self):
        scenario = create_approved_protocol(species="MOUSE", max_animals=5)
        proto_id = scenario["protocol"]["id"]
        cage = add_cage(proto_id, species="MOUSE", capacity_adults=5,
                        room_code="VIV-601")
        add_mouse(cage["id"], proto_id)
        file_census(cage["id"], "2026-08-01T00:00:00Z", 1)
        run1 = compute_provisional_ok(create_billing_run(
            "2026-08-01T00:00:00Z", "2026-08-22T00:00:00Z",
        )["id"])
        file_census(cage["id"], "2026-08-22T00:00:00Z", 1)
        run2 = compute_provisional_ok(create_billing_run(
            "2026-08-22T00:00:00Z", "2026-09-01T00:00:00Z",
        )["id"])
        return scenario, cage, run1, run2

    def test_period_end_is_exclusive(self, api):
        """PRD §3.7: "A `BillingCoordinator` opens a billing run by supplying
        `period_start`, the first billable day (inclusive, midnight UTC), and
        `period_end`, the last billable day (exclusive, midnight UTC, and it
        must fall after `period_start`)." — [2026-08-01, 2026-08-22) bills the
        21 days 2026-08-01..2026-08-21 and excludes 2026-08-22.

        Design: Difficulty/resource_temporal_overlap/billing_period_adjacency_exclusive_end
        """
        scenario, cage, run1, run2 = self._two_adjacent_runs()
        charges1 = list_run_charges(run1["id"])
        assert len(charges1) == 1
        assert charges1[0]["cage_days"] == 21, (
            "August 22 is excluded by the exclusive period_end"
        )
        assert charges1[0]["amount_cents"] == 2625

        charges2 = list_run_charges(run2["id"])
        assert len(charges2) == 1, (
            "the cage is still occupied, so the adjacent run bills it too"
        )
        assert charges2[0]["cage_days"] == 10, (
            "[2026-08-22, 2026-09-01) covers 2026-08-22..2026-08-31"
        )
        assert charges2[0]["amount_cents"] == 1250

    def test_adjacent_runs_bill_each_day_exactly_once(self, api):
        """PRD §3.7: "`period_end`, the last billable day (exclusive, midnight
        UTC, and it must fall after `period_start`)" — adjacent runs
        [2026-08-01, 2026-08-22) and [2026-08-22, 2026-09-01) are disjoint, so
        together they bill 21 + 10 = 31 days with no double-billing of the
        shared boundary day.

        Design: Difficulty/resource_temporal_overlap/billing_period_adjacency_exclusive_end
        """
        scenario, cage, run1, run2 = self._two_adjacent_runs()
        charges1 = list_run_charges(run1["id"])
        charges2 = list_run_charges(run2["id"])
        assert charges1[0]["cage_id"] == cage["id"]
        assert charges2[0]["cage_id"] == cage["id"]
        total_days = charges1[0]["cage_days"] + charges2[0]["cage_days"]
        assert total_days == 31, (
            f"adjacent disjoint periods bill each day exactly once: 21 + 10 = "
            f"31, got {total_days}"
        )
