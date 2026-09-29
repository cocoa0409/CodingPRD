"""The annual assessment roll: share units, clamps, the single redistribution
pass, and the two competing allocation methods."""
import pytest

from test_helpers import (
    assert_levy_allocation_conserved,
    assert_one_charge_per_parcel,
    expected_reserve_contribution,
    list_roll_charges,
    make_clerk_headers,
    read_association,
    read_roll,
    set_clock,
    setup_annual_assessment,
    setup_assessment_roll,
    validate_success,
)

# The association and segment the depth scenarios share.
PINE_HOLLOW = {
    "name": "Pine Hollow Road Association",
    "reserve_target_cents": 1_000_000,
    "default_voting_basis": "PER_PARCEL",
    "delinquency_interest_basis": "STATUTORY",
    "quorum_bps": 5000,
}
PINE_HOLLOW_SEGMENT = {
    "name": "Pine Hollow Road",
    "length_feet": 2400,
    "width_feet": 22,
    "max_grade_pct": 9,
    "surface_type": "GRAVEL",
    "turnout_count": 2,
    "culvert_count": 3,
    "turnaround_present": True,
    "bridge_present": False,
}

# Three parcels whose frontage units are 290 / 240 / 200 (730 in total) and
# whose trip units are 208 / 155 / 200 (563 in total).
THREE_PARCELS = [
    {
        "deed_book_page": "DB120-P41",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 6,
    },
    {
        "deed_book_page": "DB120-P42",
        "frontage_feet": 400,
        "usage_class": "SEASONAL",
        "trips_per_day": 3,
    },
    {
        "deed_book_page": "DB120-P43",
        "frontage_feet": 250,
        "usage_class": "AGRICULTURAL",
        "trips_per_day": 6,
    },
]

# Four parcels whose frontage units are 2000 / 900 / 50 / 50 (3000 in total).
CLAMP_PARCELS = [
    {
        "deed_book_page": "DB410-P01",
        "frontage_feet": 2000,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 8,
    },
    {
        "deed_book_page": "DB410-P02",
        "frontage_feet": 900,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 4,
    },
    {
        "deed_book_page": "DB410-P03",
        "frontage_feet": 200,
        "usage_class": "UNDEVELOPED",
        "trips_per_day": 0,
    },
    {
        "deed_book_page": "DB410-P04",
        "frontage_feet": 200,
        "usage_class": "UNDEVELOPED",
        "trips_per_day": 0,
    },
]

# Three parcels whose frontage units are 290 / 240 / 10 (540 in total).
TINY_BUDGET_PARCELS = [
    {
        "deed_book_page": "DB140-P01",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 6,
    },
    {
        "deed_book_page": "DB140-P02",
        "frontage_feet": 400,
        "usage_class": "SEASONAL",
        "trips_per_day": 3,
    },
    {
        "deed_book_page": "DB140-P03",
        "frontage_feet": 40,
        "usage_class": "UNDEVELOPED",
        "trips_per_day": 1,
    },
]


def _fy2027(parcel_specs, budget_requirement_cents, **overrides):
    """Levy an FY2027 frontage-weighted roll over `parcel_specs`."""
    set_clock("2026-10-01T00:00:00Z")
    return setup_annual_assessment(
        parcel_specs=parcel_specs,
        fiscal_year=2027,
        fy_start_date="2026-10-01",
        fy_end_date="2027-09-30",
        budget_requirement_cents=budget_requirement_cents,
        method_variant="FRONTAGE_WEIGHTED",
        association_overrides=PINE_HOLLOW,
        segment_overrides=PINE_HOLLOW_SEGMENT,
        **overrides,
    )


def _charge_for(parcel_id, charges):
    matches = [c for c in charges if c["parcel_id"] == parcel_id]
    assert len(matches) == 1, f"expected exactly one charge for parcel {parcel_id}"
    return matches[0]


class TestAllocationMethodVariants:
    """The same parcels and the same budget under both method variants."""

    def test_trip_generation_variant_reallocates_the_same_budget(self, api):
        """PRD §3.4: "Second, each parcel in that set contributes a share unit
        chosen by the roll's `method_variant`: its `frontage_share_units` under
        `FRONTAGE_WEIGHTED`, or its `trip_share_units` under
        `TRIP_GENERATION_WEIGHTED`. The sum of those units across the set becomes
        the roll's `total_share_units`."
        PRD §3.2: "`trip_share_units` is the parcel's `trips_per_day` multiplied
        by twenty-five, plus its `frontage_feet` multiplied by two tenths."

        Design: Difficulty/dual_variant_calc/annual_roll_method_variant_divergence_frontage_vs_trip
        """
        scenario = _fy2027(THREE_PARCELS, 4_000_000)
        p1, p2, p3 = scenario["parcels"]

        trip_roll = setup_assessment_roll(
            scenario["association"]["id"],
            fiscal_year=2028,
            fy_start_date="2027-10-01",
            fy_end_date="2028-09-30",
            budget_requirement_cents=4_000_000,
            method_variant="TRIP_GENERATION_WEIGHTED",
        )
        certified = validate_success(api.certify_roll(trip_roll["id"], make_clerk_headers()))

        assert certified["status"] == "CERTIFIED"
        assert certified["total_share_units"] == pytest.approx(563, abs=0.01), (
            f"trip units must total 563, got {certified['total_share_units']}"
        )
        assert certified["total_levied_cents"] == 4_000_000
        assert certified["unallocated_residual_cents"] == 0

        charges = list_roll_charges(trip_roll["id"])
        assert _charge_for(p1["id"], charges)["amount_cents"] == 1_477_798
        assert _charge_for(p2["id"], charges)["amount_cents"] == 1_101_243
        assert _charge_for(p3["id"], charges)["amount_cents"] == 1_420_959
        assert _charge_for(p1["id"], charges)["share_units_snapshot"] == pytest.approx(
            208, abs=0.01
        )
        assert _charge_for(p2["id"], charges)["share_units_snapshot"] == pytest.approx(
            155, abs=0.01
        )
        assert _charge_for(p3["id"], charges)["share_units_snapshot"] == pytest.approx(
            200, abs=0.01
        )
        assert_one_charge_per_parcel(charges, [p1["id"], p2["id"], p3["id"]])

    def test_frontage_roll_amounts_survive_a_later_trip_weighted_certification(self, api):
        """PRD §3.4: "Third, each parcel's raw pro-rata share is the roll's
        `budget_requirement_cents` multiplied by that parcel's share unit and
        divided by `total_share_units`, held as an exact rational with no
        rounding yet."
        PRD §3.2: "Reclassification is never retroactive: charges that already
        exist keep the `share_units_snapshot` and `amount_cents` they were
        created with."

        Design: Difficulty/dual_variant_calc/annual_roll_method_variant_divergence_frontage_vs_trip
        """
        scenario = _fy2027(THREE_PARCELS, 4_000_000)
        p1, p2, p3 = scenario["parcels"]
        frontage_roll = scenario["roll"]

        assert frontage_roll["total_share_units"] == pytest.approx(730, abs=0.01)
        assert frontage_roll["total_levied_cents"] == 3_999_999
        assert frontage_roll["unallocated_residual_cents"] == 1

        trip_roll = setup_assessment_roll(
            scenario["association"]["id"],
            fiscal_year=2028,
            fy_start_date="2027-10-01",
            fy_end_date="2028-09-30",
            budget_requirement_cents=4_000_000,
            method_variant="TRIP_GENERATION_WEIGHTED",
        )
        validate_success(api.certify_roll(trip_roll["id"], make_clerk_headers()))

        reread = read_roll(frontage_roll["id"])
        assert reread["total_share_units"] == pytest.approx(730, abs=0.01)
        assert reread["total_levied_cents"] == 3_999_999
        assert reread["unallocated_residual_cents"] == 1

        charges = list_roll_charges(frontage_roll["id"])
        assert _charge_for(p1["id"], charges)["amount_cents"] == 1_589_041
        assert _charge_for(p2["id"], charges)["amount_cents"] == 1_315_068
        assert _charge_for(p3["id"], charges)["amount_cents"] == 1_095_890

    def test_method_comparison_reports_signed_per_parcel_divergence(self, api):
        """PRD §3.4: "It answers with an object carrying `roll_id`, the roll's own
        `method_variant`, `frontage_weighted_total_cents`,
        `trip_generation_weighted_total_cents`,
        `frontage_weighted_unallocated_residual_cents`,
        `trip_generation_weighted_unallocated_residual_cents`,
        `divergent_parcel_count` — the number of parcels whose rounded amount
        differs between the two methods — and `max_absolute_divergence_cents`,
        the largest absolute per-parcel difference."

        Design: Difficulty/dual_variant_calc/annual_roll_method_variant_divergence_frontage_vs_trip
        """
        scenario = _fy2027(THREE_PARCELS, 4_000_000)

        trip_roll = setup_assessment_roll(
            scenario["association"]["id"],
            fiscal_year=2028,
            fy_start_date="2027-10-01",
            fy_end_date="2028-09-30",
            budget_requirement_cents=4_000_000,
            method_variant="TRIP_GENERATION_WEIGHTED",
        )
        comparison = validate_success(
            api.get_method_comparison(trip_roll["id"], make_clerk_headers())
        )

        assert comparison["roll_id"] == trip_roll["id"]
        assert comparison["method_variant"] == "TRIP_GENERATION_WEIGHTED"
        assert comparison["frontage_weighted_total_cents"] == 3_999_999
        assert comparison["trip_generation_weighted_total_cents"] == 4_000_000
        assert comparison["frontage_weighted_unallocated_residual_cents"] == 1
        assert comparison["trip_generation_weighted_unallocated_residual_cents"] == 0
        assert comparison["divergent_parcel_count"] == 3
        assert comparison["max_absolute_divergence_cents"] == 325_069

    def test_method_comparison_mutates_nothing(self, api):
        """PRD §3.4: "This capability runs the full eight-step allocation under
        **both** method variants and mutates nothing at all — no charges, no
        totals, no versions."

        Design: Difficulty/dual_variant_calc/annual_roll_method_variant_divergence_frontage_vs_trip
        """
        scenario = _fy2027(THREE_PARCELS, 4_000_000)
        roll_before = read_roll(scenario["roll"]["id"])
        charges_before = list_roll_charges(roll_before["id"])

        validate_success(api.get_method_comparison(roll_before["id"], make_clerk_headers()))

        roll_after = read_roll(roll_before["id"])
        assert roll_after["version"] == roll_before["version"]
        assert roll_after["total_levied_cents"] == roll_before["total_levied_cents"]
        assert roll_after["unallocated_residual_cents"] == (
            roll_before["unallocated_residual_cents"]
        )

        charges_after = list_roll_charges(roll_before["id"])
        assert len(charges_after) == len(charges_before)
        for before, after in zip(charges_before, charges_after):
            assert after["amount_cents"] == before["amount_cents"]
            assert after["version"] == before["version"]


class TestClampAndRedistribution:
    """The fifty-thousand-cent floor, the forty-percent cap, and the single pass."""

    def test_cap_and_floor_clamp_the_raw_pro_rata_shares(self, api):
        """PRD §3.4: "Fourth, each raw share is clamped between a floor of fifty
        thousand cents and a per-parcel cap, where the cap is forty percent of
        `budget_requirement_cents` with any fraction discarded downward."

        Design: Difficulty/combinatorial_formula/assessment_cap_clamp_bounds_single_redistribution_pass
        """
        scenario = _fy2027(CLAMP_PARCELS, 1_000_000, levy=False)
        roll = scenario["roll"]
        q1, q2, q3, q4 = scenario["parcels"]

        assert roll["status"] == "CERTIFIED"
        assert roll["total_share_units"] == pytest.approx(3000, abs=0.01)

        charges = list_roll_charges(roll["id"])
        assert _charge_for(q1["id"], charges)["amount_cents"] == 400_000, (
            "the cap floor(0.40 * 1000000) must clamp Q1 down from its raw share"
        )
        assert _charge_for(q3["id"], charges)["amount_cents"] == 50_000
        assert _charge_for(q4["id"], charges)["amount_cents"] == 50_000
        assert [c["share_units_snapshot"] for c in charges] == [
            pytest.approx(2000, abs=0.01),
            pytest.approx(900, abs=0.01),
            pytest.approx(50, abs=0.01),
            pytest.approx(50, abs=0.01),
        ]

    def test_redistribution_is_bounded_by_the_remaining_cap_headroom(self, api):
        """PRD §3.4: "For each unclamped parcel, provided that sum of unclamped
        units is greater than zero, its wanted adjustment is the residual
        multiplied by its own share unit and divided by the sum of unclamped
        units; when the residual is zero or positive the adjustment actually
        applied is the smaller of that wanted amount and the headroom remaining
        below the cap, and when the residual is negative the adjustment applied
        is the larger of that wanted amount and the distance down to the
        fifty-thousand-cent floor."
        PRD §3.4: "This is exactly one pass: there is no second clamping round
        and no fixed-point iteration, even though the cap depends on the budget,
        the residual depends on the clamps, and the redistribution depends on the
        residual."

        Design: Difficulty/combinatorial_formula/assessment_cap_clamp_bounds_single_redistribution_pass
        """
        scenario = _fy2027(CLAMP_PARCELS, 1_000_000, levy=False)
        roll = scenario["roll"]
        q2 = scenario["parcels"][1]

        charges = list_roll_charges(roll["id"])
        assert _charge_for(q2["id"], charges)["amount_cents"] == 400_000, (
            "Q2 could absorb only min(200000, 400000 - 300000) of the residual"
        )
        assert roll["total_levied_cents"] == 900_000
        assert roll["unallocated_residual_cents"] == 100_000
        assert max(c["amount_cents"] for c in charges) == 400_000, (
            "the single pass must never push a parcel back above the cap"
        )
        assert_levy_allocation_conserved(roll, charges)


class TestNegativeUnallocatedResidual:
    """A budget so small that every parcel is clamped."""

    def test_floor_and_cap_together_produce_a_negative_residual(self, api):
        """PRD §3.4: "Eighth, the roll's `total_levied_cents` is the sum of those
        rounded per-parcel amounts, and its `unallocated_residual_cents` is
        `budget_requirement_cents` minus `total_levied_cents`. That residual is
        recorded rather than spread, and it may legitimately be negative when the
        fifty-thousand-cent floor over-collected, just as it may be positive when
        the per-parcel cap absorbed budget."

        Design: Difficulty/boundary_precision_check/minimum_charge_floor_and_cap_together_yield_negative_unallocated_residual
        """
        scenario = _fy2027(TINY_BUDGET_PARCELS, 200_000, levy=False)
        roll = scenario["roll"]
        p1, p2, p3 = scenario["parcels"]

        assert p3["frontage_share_units"] == pytest.approx(10, abs=0.0001), (
            "40 feet of UNDEVELOPED frontage is 10 share units"
        )
        assert roll["total_share_units"] == pytest.approx(540, abs=0.01)
        assert roll["total_levied_cents"] == 210_000
        assert roll["unallocated_residual_cents"] == -10_000

        charges = list_roll_charges(roll["id"])
        assert _charge_for(p1["id"], charges)["amount_cents"] == 80_000
        assert _charge_for(p2["id"], charges)["amount_cents"] == 80_000
        assert _charge_for(p3["id"], charges)["amount_cents"] == 50_000
        assert all(50_000 <= c["amount_cents"] <= 80_000 for c in charges), (
            "no parcel may sit outside the floor/cap band"
        )
        assert sum(c["amount_cents"] for c in charges) == 210_000
        assert_levy_allocation_conserved(roll, charges)

    def test_reserve_contribution_follows_the_budget_not_the_over_collection(self, api):
        """PRD §3.4: "The roll's `reserve_contribution_cents` is set to fifteen
        percent of `budget_requirement_cents`, rounded half up to whole cents, and
        that amount is credited to the association's `reserve_balance_cents`,
        after which `reserve_funding_ratio` and `reserve_posture` are recomputed"
        PRD §2.6: "the posture is `FULLY_FUNDED` when the balance is at least the
        target; otherwise it is `ADEQUATE` when the balance multiplied by one
        hundred is at least the target multiplied by sixty — so a balance of
        exactly sixty percent of target is `ADEQUATE` — and otherwise it is
        `UNDERFUNDED`."

        Design: Difficulty/boundary_precision_check/minimum_charge_floor_and_cap_together_yield_negative_unallocated_residual
        """
        scenario = _fy2027(TINY_BUDGET_PARCELS, 200_000)
        roll = scenario["roll"]

        assert roll["status"] == "LEVIED"
        assert roll["reserve_contribution_cents"] == 30_000
        assert roll["reserve_contribution_cents"] == expected_reserve_contribution(200_000)
        assert roll["total_levied_cents"] == 210_000, (
            "the contribution is not fifteen percent of the over-collected total"
        )

        association = read_association(scenario["association"]["id"])
        assert association["reserve_balance_cents"] == 30_000
        assert association["reserve_posture"] == "UNDERFUNDED"

    def test_levy_stamps_the_forty_five_day_due_date_on_every_charge(self, api):
        """PRD §3.4: "On levy, every `ANNUAL` charge of the roll whose `status` is
        `PENDING` moves `PENDING → OPEN` and is stamped with a `due_date` of the
        levy date plus forty-five days; `levied_at` is stamped with the current
        logical-clock instant and the roll's own `due_date` is set to the same
        date."

        Design: Difficulty/boundary_precision_check/minimum_charge_floor_and_cap_together_yield_negative_unallocated_residual
        """
        scenario = _fy2027(TINY_BUDGET_PARCELS, 200_000)
        charges = list_roll_charges(scenario["roll"]["id"])

        assert len(charges) == 3
        for charge in charges:
            assert charge["status"] == "OPEN"
            assert charge["due_date"] == "2026-11-15", (
                f"levied 2026-10-01 plus 45 days is 2026-11-15, got {charge['due_date']}"
            )
            assert charge["paid_cents"] == 0
            assert charge["balance_cents"] == charge["amount_cents"]
        assert scenario["roll"]["due_date"] == "2026-11-15"
