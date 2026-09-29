"""Where a formula pins its evaluation order, that order is observable."""
import math
from decimal import ROUND_HALF_UP, Decimal

from test_helpers import (
    TEST_USERS,
    add_package,
    assert_package_pricing,
    cast_ballot,
    open_project,
    open_ve_review,
    propose_ve_item,
    read_budget_position,
    read_ledger,
    setup_program_at_schematic,
    setup_program_with_approved_package,
    validate_success,
)

ENGINEER = TEST_USERS["ride_engineer_headers"]

ITEM_A = {
    "title": "Substitute sculpted rockwork with pre-cast panels",
    "gross_saving_cents": 350000021,
    "rework_loss_pct": 75,
    "implementation_cost_cents": 4000000,
    "capacity_impact_guests_per_hour": -300,
    "scope_impact_delta_cents": -346000021,
}
ITEM_B = {
    "title": "Reduce practical flame effects to two positions",
    "gross_saving_cents": 70000021,
    "rework_loss_pct": 75,
    "implementation_cost_cents": 1000000,
    "capacity_impact_guests_per_hour": 0,
    "scope_impact_delta_cents": -69000021,
}


def _half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _adopt(item_id: str) -> None:
    """Carry an item to ADOPTED on two approvals and one abstention."""
    open_ve_review(item_id)
    cast_ballot(item_id, "OwnerRep", "APPROVE", comment="Saving accepted")
    cast_ballot(item_id, "ContractorPM", "APPROVE")
    cast_ballot(item_id, "CreativeDirector", "ABSTAIN")


class TestRideDerateGuardOrder:
    """The penalty cap and the derate floor are not interchangeable."""

    def test_penalty_cap_is_applied_before_the_derate_floor(self, api):
        """The order here is contractual: the penalty cap is applied *before* the derate floor, so a system with a great many show stops lands exactly on the thirty-five-hundredths floor rather than on the raw derate less a twenty-hundredths penalty.

        A raw derate of 0.48 with ten show stops an hour carries a 0.30 penalty
        that the cap trims to 0.20; the floor then lifts the 0.28 remainder back to
        0.35, so the row reports 327 guests per hour and not the 262 the reversed
        guard order would produce.

        Design: Difficulty/combinatorial_formula/ride_derate_nested_min_max_lands_on_floor_not_on_capped_subtraction
        """
        project = open_project(design_day_attendance=8000, peak_hour_share=0.10)

        response = api.create_ride_system(
            {
                "project_id": project["id"], "vendor_name": "Intamin",
                "system_type": "BOAT_FLUME", "vehicle_count": 8,
                "riders_per_vehicle": 6, "block_zone_count": 10,
                "cycle_time_seconds": 180, "availability_pct": 60,
                "load_efficiency_pct": 80, "show_stops_per_hour": 10,
            },
            ENGINEER,
        )

        row = validate_success(response, 201)
        assert row["dispatch_interval_seconds"] == 23
        assert row["theoretical_hourly_capacity_guests"] == 936
        assert row["operational_hourly_capacity_guests"] == 327
        assert row["operational_hourly_capacity_guests"] != 262

    def test_row_lands_on_the_floor_above_the_capped_subtraction(self, api):
        """Fourth, the **operationally derated capacity** variant applies real-world losses: the raw derate is `availability_pct` as a fraction of one hundred multiplied by `load_efficiency_pct` as a fraction of one hundred; the show-stop penalty is `show_stops_per_hour` multiplied by three hundredths per stop, capped at twenty hundredths; the effective derate is the raw derate less the show-stop penalty, floored at thirty-five hundredths; and `operational_hourly_capacity_guests` is the theoretical figure multiplied by that effective derate, rounded down to a whole guest.

        With the capped penalty subtracted the derate would be 0.28, below the
        floor, so the floor is what multiplies the theoretical figure: the reported
        figure is the theoretical 936 taken at 0.35 and rounded down, which is
        strictly larger than the same figure taken at 0.28.

        Design: Difficulty/combinatorial_formula/ride_derate_nested_min_max_lands_on_floor_not_on_capped_subtraction
        """
        project = open_project(design_day_attendance=8000, peak_hour_share=0.10)

        row = validate_success(
            api.create_ride_system(
                {
                    "project_id": project["id"], "vendor_name": "Intamin",
                    "system_type": "BOAT_FLUME", "vehicle_count": 8,
                    "riders_per_vehicle": 6, "block_zone_count": 10,
                    "cycle_time_seconds": 180, "availability_pct": 60,
                    "load_efficiency_pct": 80, "show_stops_per_hour": 10,
                },
                ENGINEER,
            ),
            201,
        )

        theoretical = row["theoretical_hourly_capacity_guests"]
        on_the_floor = math.floor(theoretical * Decimal("0.35"))
        after_capped_subtraction = math.floor(theoretical * Decimal("0.28"))
        assert row["operational_hourly_capacity_guests"] == on_the_floor
        assert row["operational_hourly_capacity_guests"] > after_capped_subtraction


class TestValueEngineeringProgramSavings:
    """Each item's retained saving is rounded before anything is summed."""

    def test_each_retained_saving_is_rounded_before_the_program_total(self):
        """The rounding order is contractual — rounding each item's retained saving before subtracting its implementation cost, never summing exact retained savings across items and rounding once.

        Opening the ballot fixes the item's net saving: the retained saving is
        `gross_saving_cents` multiplied by one minus `rework_loss_pct` divided by
        one hundred, and `net_saving_cents` is that retained saving rounded half up
        to whole cents *first* and then reduced by `implementation_cost_cents`.

        The two exact retained savings are 87500005.25 and 17500005.25. Rounded
        one at a time they net 83500005 and 16500005, a programme total of
        100000010; summing the exact figures and rounding once would report
        100000011.

        Design: Difficulty/combinatorial_formula/ve_program_savings_round_per_item_then_sum
        """
        ctx = setup_program_with_approved_package()
        item_a = propose_ve_item(ctx["project"]["id"], **ITEM_A)
        _adopt(item_a["id"])
        item_b = propose_ve_item(ctx["project"]["id"], **ITEM_B)
        _adopt(item_b["id"])

        budget = read_budget_position(ctx["project"]["id"])

        assert budget["ve_program_net_savings_cents"] == 100000010
        assert budget["ve_program_net_savings_cents"] != 100000011

    def test_both_items_reach_adopted_and_reduce_the_committed_cost(self, api):
        """Across the programme, `ve_program_net_savings_cents` is the sum of `net_saving_cents` over items whose `status` is `ADOPTED`, and that sum is never re-rounded.

        A ledger entry is minted with `entry_kind` `VE_SAVING`, an `amount_cents`
        equal to zero minus the item's `net_saving_cents` — a saving is a negative
        ledger amount — a `sequence_no` one greater than the programme's
        `ledger_sequence_high_water` (which then advances), and a `memo` of the
        form `VE_SAVING for ` followed by the item's `title`.

        Two adoptions therefore carry the committed 3080000000 down to 2979999990,
        each item contributing its own separately rounded net saving.

        Design: Difficulty/combinatorial_formula/ve_program_savings_round_per_item_then_sum
        """
        ctx = setup_program_with_approved_package()
        item_a = propose_ve_item(ctx["project"]["id"], **ITEM_A)
        _adopt(item_a["id"])
        item_b = propose_ve_item(ctx["project"]["id"], **ITEM_B)
        _adopt(item_b["id"])

        row_a = validate_success(api.get_value_engineering_item(item_a["id"], TEST_USERS["owner_rep_headers"]))
        row_b = validate_success(api.get_value_engineering_item(item_b["id"], TEST_USERS["owner_rep_headers"]))
        savings, _meta = read_ledger(ctx["project"]["id"], params={"entry_kind": "VE_SAVING"})
        budget = read_budget_position(ctx["project"]["id"])

        assert row_a["status"] == "ADOPTED" and row_a["net_saving_cents"] == 83500005
        assert row_b["status"] == "ADOPTED" and row_b["net_saving_cents"] == 16500005
        assert sorted(entry["amount_cents"] for entry in savings) == [-83500005, -16500005]
        assert budget["committed_cost_cents"] == 2979999990


class TestDesignPackageTierKeying:
    """The pricing tier is looked up on the base construction cost alone."""

    def test_one_cent_above_the_tier_ceiling_totals_less(self):
        """A consequence worth internalising: because the tier is keyed on the base, a base one cent above a tier ceiling drops into the cheaper tier and can produce a *smaller* total than a base one cent below it.

        A base of exactly 2500000000 sits in the ten-percent fee band and totals
        3080000000; a base one cent higher falls into the eight-and-a-half-percent
        band and totals 2983750001, which is 96249999 cents less.

        Design: Difficulty/combinatorial_formula/design_package_tier_keyed_on_base_not_on_running_total
        """
        ctx = setup_program_at_schematic(
            project_overrides={"budget_ceiling_cents": 9000000000}
        )
        at_ceiling = add_package(
            ctx["project"]["id"], ctx["ride_system"]["id"],
            package_label="Set Package At Tier Ceiling", discipline_scope="SHOW_SET",
            base_construction_cost_cents=2500000000,
        )
        one_cent_above = add_package(
            ctx["project"]["id"], ctx["ride_system"]["id"],
            package_label="Set Package One Cent Above", discipline_scope="SHOW_SET",
            base_construction_cost_cents=2500000001,
        )

        assert_package_pricing(at_ceiling, base=2500000000, design_fee=250000000,
                               contingency=330000000, total=3080000000)
        assert_package_pricing(one_cent_above, base=2500000001, design_fee=212500000,
                               contingency=271250000, total=2983750001)
        assert (at_ceiling["total_cost_of_work_cents"]
                - one_cent_above["total_cost_of_work_cents"]) == 96249999

    def test_contingency_base_includes_the_fee_of_the_tier_the_base_chose(self):
        """Third, `contingency_cents` is the sum of `base_construction_cost_cents` and the just-computed `design_fee_cents`, multiplied by the tier's contingency percentage, rounded half up to whole cents — the fee sits *inside* the contingency base.

        Pricing looks circular at first glance — the total depends on the fee and
        the fee depends on a tier — but the tier is keyed on the base construction
        cost alone and never on the running total, and the four steps are evaluated
        in a fixed order.

        Each package's contingency is its own base plus its own fee at its own
        tier's percentage: twelve percent for the base at the ceiling, ten percent
        for the base one cent above it.

        Design: Difficulty/combinatorial_formula/design_package_tier_keyed_on_base_not_on_running_total
        """
        ctx = setup_program_at_schematic(
            project_overrides={"budget_ceiling_cents": 9000000000}
        )
        at_ceiling = add_package(
            ctx["project"]["id"], ctx["ride_system"]["id"],
            package_label="Set Package At Tier Ceiling", discipline_scope="SHOW_SET",
            base_construction_cost_cents=2500000000,
        )
        one_cent_above = add_package(
            ctx["project"]["id"], ctx["ride_system"]["id"],
            package_label="Set Package One Cent Above", discipline_scope="SHOW_SET",
            base_construction_cost_cents=2500000001,
        )

        for package, fee_pct, contingency_pct in (
            (at_ceiling, Decimal("0.10"), Decimal("0.12")),
            (one_cent_above, Decimal("0.085"), Decimal("0.10")),
        ):
            base = Decimal(package["base_construction_cost_cents"])
            expected_fee = _half_up(base * fee_pct)
            expected_contingency = _half_up((base + expected_fee) * contingency_pct)
            assert package["design_fee_cents"] == expected_fee
            assert package["contingency_cents"] == expected_contingency
            assert package["total_cost_of_work_cents"] == (
                package["base_construction_cost_cents"]
                + expected_fee + expected_contingency
            )
