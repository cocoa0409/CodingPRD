"""Derived quantities: density adders, auxiliary demand clamps, rounding and roll-ups."""
import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import (
    assert_classification,
    assert_demand_ledger,
    assert_density,
    assert_flow,
    assert_money,
    assert_posture,
    assert_pressure,
)
from test_helpers.factories import (
    build_fee_payment_payload,
    build_withdraw_payload,
    build_resubmit_payload,
)
from test_helpers.fixtures import (
    CONTRACTOR_HEADERS,
    HC1_REQUIRED_PSI,
    build_converged_stage,
    build_permitted_stage,
    build_under_review_stage,
    build_project_stage,
    create_auxiliary_system,
    create_calculation,
    create_evaluation,
    create_hazard_area,
    create_project,
    read_auxiliary_system,
    read_calculation,
    read_project,
    read_submittal,
    qc_pass,
    seal,
    begin_review,
    complete_review,
    open_acceptance_test,
    raise_comment,
    record_witness,
    schedule_witness,
    read_acceptance_test,
)
from test_helpers.test_users import make_ahj_reviewer_headers, make_design_engineer_headers

# Five bays differing in nothing but the deflector plane height.
ORDINARY_1_BAY = dict(
    hazard_class="ORDINARY_1",
    commodity_class="CLASS_III",
    storage_height_ft=8.0,
    ceiling_height_ft=30.0,
    area_sqft=24000.0,
    sprinkler_system_type="WET",
    ceiling_slope_pct=4.0,
    room_area_sqft=None,
    enclosure_rating_hours=None,
    room_has_unprotected_opening=None,
)


def _bay(client, ctx, label, ceiling_height_ft):
    return create_hazard_area(
        client,
        ctx["project_id"],
        ctx["lead_id"],
        **dict(ORDINARY_1_BAY, label=label, ceiling_height_ft=ceiling_height_ft),
    )


class TestHighCeilingDensityAdder:
    def test_01_thirty_feet_and_thirty_four_point_nine_feet_both_stay_at_the_base(
        self, client
    ):
        """When `ceiling_height_ft` is strictly greater than 30 feet, the density is increased
        in whole steps.

        Design: Corner/calculations/ceiling_height_density_adder_steps_at_thirty_five_feet_and_caps_at_six_hundredths
        """
        ctx = build_project_stage(client)
        at_the_trigger = _bay(client, ctx, "Bay 30ft", 30.0)
        below_the_first_step = _bay(client, ctx, "Bay 34.9ft", 34.9)

        assert_classification(at_the_trigger, "ORDINARY_1", 0.150, 1500, 250.0)
        assert_classification(below_the_first_step, "ORDINARY_1", 0.150, 1500, 250.0)

    def test_02_thirty_five_feet_earns_one_step_and_forty_five_feet_earns_three(
        self, client
    ):
        """the number of steps is the excess height above 30 feet divided by 5 feet and
        rounded down to a whole number, each step adds 0.02 gallons per minute per square
        foot.

        Design: Corner/calculations/ceiling_height_density_adder_steps_at_thirty_five_feet_and_caps_at_six_hundredths
        """
        ctx = build_project_stage(client)
        one_step = _bay(client, ctx, "Bay 35ft", 35.0)
        three_steps = _bay(client, ctx, "Bay 45ft", 45.0)

        assert_classification(one_step, "ORDINARY_1", 0.170, 1500, 250.0)
        assert_classification(three_steps, "ORDINARY_1", 0.210, 1500, 250.0)

    def test_03_fifty_feet_earns_four_steps_but_is_clamped_to_the_same_figure(self, client):
        """the total addition is capped at 0.06 — so a ceiling at 45 feet earns three steps and
        the full 0.06, and a ceiling at 60 feet earns the same 0.06 and no more.

        Design: Corner/calculations/ceiling_height_density_adder_steps_at_thirty_five_feet_and_caps_at_six_hundredths
        """
        ctx = build_project_stage(client)
        three_steps = _bay(client, ctx, "Bay 45ft", 45.0)
        four_steps_clamped = _bay(client, ctx, "Bay 50ft", 50.0)

        assert_density(four_steps_clamped["design_density"], 0.210)
        assert_density(
            four_steps_clamped["design_density"], three_steps["design_density"]
        )
        assert_classification(four_steps_clamped, "ORDINARY_1", 0.210, 1500, 250.0)


RACK_BAY = dict(
    label="Rack Storage Bay A",
    hazard_class="ORDINARY_2",
    commodity_class="CLASS_IV",
    storage_height_ft=18.0,
    ceiling_height_ft=36.0,
    area_sqft=24000.0,
    sprinkler_system_type="WET",
    ceiling_slope_pct=4.0,
    room_area_sqft=None,
    enclosure_rating_hours=None,
    room_has_unprotected_opening=None,
)


def _rack_project(client):
    ctx = build_project_stage(client)
    ctx["hazard_area_id"] = create_hazard_area(
        client, ctx["project_id"], ctx["lead_id"], **RACK_BAY
    )["id"]
    return ctx


def _in_rack(client, ctx, label, head_count):
    return create_auxiliary_system(
        client,
        ctx["project_id"],
        ctx["lead_id"],
        system_type="IN_RACK",
        label=label,
        hazard_area_id=ctx["hazard_area_id"],
        in_rack_head_count=head_count,
    )


class TestInRackDemandClamps:
    def test_04_three_heads_are_lifted_to_the_floor_and_twenty_are_cut_to_the_cap(
        self, client
    ):
        """An in-rack system takes 30.0 per assumed operating head, then is raised to a floor
        of 150.0 if it falls below that, and capped at 480.0.

        Design: Corner/calculations/in_rack_head_count_is_clamped_by_the_floor_and_the_cap_and_scales_between_them
        """
        ctx = _rack_project(client)
        three_heads = _in_rack(client, ctx, "Rack tier 3 heads", 3)
        twenty_heads = _in_rack(client, ctx, "Rack tier 20 heads", 20)

        assert_flow(three_heads["demand_gpm"], 150.0)
        assert_flow(twenty_heads["demand_gpm"], 480.0)
        for row in (three_heads, twenty_heads):
            assert row["interlock_required"] is False
            assert row["status"] == "PROPOSED"

    def test_05_ten_and_twelve_heads_scale_linearly_between_the_two_clamps(self, client):
        """The demand each type contributes to the ledger is derived on creation as
        `demand_gpm`, rounded to 1 decimal place.

        Design: Corner/calculations/in_rack_head_count_is_clamped_by_the_floor_and_the_cap_and_scales_between_them
        """
        ctx = _rack_project(client)
        ten_heads = _in_rack(client, ctx, "Rack tier 10 heads", 10)
        twelve_heads = _in_rack(client, ctx, "Rack tier 12 heads", 12)

        assert_flow(ten_heads["demand_gpm"], 300.0)
        assert_flow(twelve_heads["demand_gpm"], 360.0)
        assert read_auxiliary_system(client, ten_heads["id"])["hazard_area_id"] == (
            ctx["hazard_area_id"]
        )

    def test_06_the_ledger_sums_the_clamped_figures_not_the_raw_ones(self, client):
        """the project ledger is recomputed so `auxiliary_demand_gpm` and
        `total_system_demand_gpm` rise by the new `demand_gpm`.

        Design: Corner/calculations/in_rack_head_count_is_clamped_by_the_floor_and_the_cap_and_scales_between_them
        """
        ctx = _rack_project(client)
        for label, heads in (
            ("Rack tier 3 heads", 3),
            ("Rack tier 10 heads", 10),
            ("Rack tier 12 heads", 12),
            ("Rack tier 20 heads", 20),
        ):
            _in_rack(client, ctx, label, heads)

        # 150.0 + 300.0 + 360.0 + 480.0, not the unclamped 90.0 + 300.0 + 360.0 + 600.0.
        assert_demand_ledger(read_project(client, ctx["project_id"]), None, 0.0, 1290.0, 1290.0)


def _four_riser_class_i(client, project_id, engineer_id):
    return create_auxiliary_system(
        client,
        project_id,
        engineer_id,
        system_type="STANDPIPE_CLASS_I",
        label="Four stair risers",
        riser_count=4,
    )


class TestClassIStandpipeCap:
    def test_07_the_low_rise_cap_holds_at_forty_two_feet_and_at_exactly_the_trigger(
        self, client
    ):
        """the cap is 1000.0 gallons per minute for a building whose `building_height_ft` is at
        most 150 feet, and 1250.0 for a taller, high-rise building.

        Design: Corner/calculations/class_i_standpipe_cap_moves_only_above_the_high_rise_trigger
        """
        ctx = build_project_stage(client)
        low_rise = _four_riser_class_i(client, ctx["project_id"], ctx["lead_id"])
        assert_flow(low_rise["demand_gpm"], 1000.0)
        assert_flow(
            read_project(client, ctx["project_id"])["auxiliary_demand_gpm"], 1000.0
        )

        at_the_trigger = create_project(
            client,
            ctx["lead_id"],
            ctx["reviewer_id"],
            project_number="FP-2602",
            building_name="Congress Avenue Tower",
            building_height_ft=150.0,
        )
        borderline = _four_riser_class_i(client, at_the_trigger["id"], ctx["lead_id"])
        assert_flow(borderline["demand_gpm"], 1000.0)
        assert_flow(read_project(client, at_the_trigger["id"])["auxiliary_demand_gpm"], 1000.0)

    def test_08_above_the_trigger_the_raw_per_riser_figure_survives(self, client):
        """A Class I standpipe starts at 500.0 gallons per minute for the first riser and adds
        250.0 for each additional riser.

        Design: Corner/calculations/class_i_standpipe_cap_moves_only_above_the_high_rise_trigger
        """
        ctx = build_project_stage(client)
        high_rise = create_project(
            client,
            ctx["lead_id"],
            ctx["reviewer_id"],
            project_number="FP-2603",
            building_name="Guadalupe Heights",
            building_height_ft=200.0,
        )
        four_risers = _four_riser_class_i(client, high_rise["id"], ctx["lead_id"])
        assert_flow(four_risers["demand_gpm"], 1250.0)

        # Two risers sit below either cap, so the per-riser rate is visibly unchanged.
        two_risers = create_auxiliary_system(
            client,
            high_rise["id"],
            ctx["lead_id"],
            system_type="STANDPIPE_CLASS_I",
            label="Stair 1 and 2 standpipes",
            riser_count=2,
        )
        assert_flow(two_risers["demand_gpm"], 750.0)
        assert_flow(read_project(client, high_rise["id"])["auxiliary_demand_gpm"], 2000.0)


def _hood(client, ctx, label, water_wash_enabled):
    return create_auxiliary_system(
        client,
        ctx["project_id"],
        ctx["lead_id"],
        system_type="COOKING",
        label=label,
        appliance_count=4,
        water_wash_enabled=water_wash_enabled,
        agent_type="WET_CHEMICAL",
    )


class TestCookingWaterWashTerm:
    def test_09_the_wash_cycle_is_worth_exactly_sixty_gallons_per_minute(self, client):
        """A cooking system takes a fixed 40.0 for the hood, adds 15.0 per protected appliance,
        and adds a further 60.0 when `water_wash_enabled` is true.

        Design: Corner/calculations/cooking_water_wash_term_is_worth_exactly_sixty_gpm
        """
        ctx = build_project_stage(client)
        with_wash = _hood(client, ctx, "Cafeteria hood with wash", True)
        without_wash = _hood(client, ctx, "Cafeteria hood without wash", False)

        assert_flow(with_wash["demand_gpm"], 160.0)
        assert_flow(without_wash["demand_gpm"], 100.0)
        assert_flow(with_wash["demand_gpm"] - without_wash["demand_gpm"], 60.0)
        assert_demand_ledger(read_project(client, ctx["project_id"]), None, 0.0, 260.0, 260.0)

    def test_10_the_interlock_keys_off_the_type_and_not_off_the_wash_flag(self, client):
        """Creation also derives `interlock_required`, which is true for exactly two types —
        `COOKING` and `HAZMAT_DELUGE` — and false for the rest.

        Design: Corner/calculations/cooking_water_wash_term_is_worth_exactly_sixty_gpm
        """
        ctx = build_project_stage(client)
        with_wash = _hood(client, ctx, "Cafeteria hood with wash", True)
        without_wash = _hood(client, ctx, "Cafeteria hood without wash", False)

        for row in (with_wash, without_wash):
            assert row["interlock_required"] is True
            assert row["interlock_verified"] is False
            assert row["agent_type"] == "WET_CHEMICAL"
            assert row["water_wash_enabled"] is (row is with_wash)


def _deluge(client, ctx, system_type, label, protected_area_sqft, agent_type=None):
    return create_auxiliary_system(
        client,
        ctx["project_id"],
        ctx["lead_id"],
        system_type=system_type,
        label=label,
        protected_area_sqft=protected_area_sqft,
        agent_type=agent_type,
    )


class TestDelugeDensityProducts:
    def test_11_both_deluge_families_are_lifted_by_their_own_floor(self, client):
        """A foam deluge system takes a density of 0.16 gallons per minute per square foot over
        `protected_area_sqft`, rounded to 1 decimal place, and is raised to a floor of 250.0 if
        it falls below it. A hazardous-materials deluge system works the same way at a density
        of 0.30 gallons per minute per square foot with a floor of 300.0.

        Design: Corner/calculations/deluge_density_products_are_rounded_to_a_tenth_then_lifted_by_their_floor
        """
        ctx = build_project_stage(client)
        foam = _deluge(client, ctx, "FOAM_DELUGE", "Foam pit floor case", 1000.0, "AFFF")
        hazmat = _deluge(client, ctx, "HAZMAT_DELUGE", "Hazmat store floor case", 800.0)

        # 0.16 x 1000 is 160.0 and 0.30 x 800 is 240.0; both are below their floors.
        assert_flow(foam["demand_gpm"], 250.0)
        assert_flow(hazmat["demand_gpm"], 300.0)
        assert foam["interlock_required"] is False
        assert hazmat["interlock_required"] is True

    def test_12_the_product_is_rounded_before_the_floor_is_consulted(self, client):
        """The demand each type contributes to the ledger is derived on creation as
        `demand_gpm`, rounded to 1 decimal place, and the branches are as follows.

        Design: Corner/calculations/deluge_density_products_are_rounded_to_a_tenth_then_lifted_by_their_floor
        """
        ctx = build_project_stage(client)
        _deluge(client, ctx, "FOAM_DELUGE", "Foam pit floor case", 1000.0, "AFFF")
        foam = _deluge(client, ctx, "FOAM_DELUGE", "Foam pit rounding case", 1573.0, "AFFF")
        _deluge(client, ctx, "HAZMAT_DELUGE", "Hazmat store floor case", 800.0)
        hazmat = _deluge(client, ctx, "HAZMAT_DELUGE", "Hazmat store rounding case", 1005.0)

        # 0.16 x 1573 is 251.68, which rounds up to 251.7 rather than truncating to 251.6.
        assert foam["demand_gpm"] == pytest.approx(251.7, abs=0.005)
        assert hazmat["demand_gpm"] == pytest.approx(301.5, abs=0.005)
        assert_flow(
            read_project(client, ctx["project_id"])["auxiliary_demand_gpm"], 1103.2
        )


class TestChainRoundsEverySegment:
    def test_13_the_end_head_and_each_segment_loss_are_rounded_to_two_places(self, client):
        """`end_head_psi` is the pressure required at the end sprinkler head of the active
        chain: divide the `flow_gpm` of the first active iteration by the calculation's
        `k_factor`, square the quotient, and round to 2 decimal places.

        Design: Corner/calculations/pipe_chain_rounds_every_segment_to_two_places_before_accumulating
        """
        ctx = build_converged_stage(client)
        rows = validate_success(
            client.list_iterations(
                ctx["calculation_id"], make_design_engineer_headers(ctx["lead_id"])
            )
        )
        by_index = {row["iteration_index"]: row for row in rows}

        assert_pressure(read_calculation(client, ctx["calculation_id"])["end_head_psi"], 19.05)
        assert by_index[1]["friction_loss_psi"] == 21.29
        assert by_index[1]["elevation_loss_psi"] == 0.00
        assert by_index[1]["velocity_fps"] == 10.52
        assert by_index[2]["friction_loss_psi"] == 4.94
        assert by_index[2]["velocity_fps"] == 10.59
        assert by_index[3]["friction_loss_psi"] == 1.80
        assert by_index[3]["elevation_loss_psi"] == 3.46
        assert by_index[3]["velocity_fps"] == 9.77

    def test_14_the_running_total_is_re_rounded_after_every_segment(self, client):
        """each segment's already-rounded `friction_loss_psi` and `elevation_loss_psi` are
        added to the running pressure and the running total is rounded again to 2 decimal
        places, and that value is stored on the segment as `cumulative_psi_after`.

        Design: Corner/calculations/pipe_chain_rounds_every_segment_to_two_places_before_accumulating
        """
        ctx = build_converged_stage(client)
        rows = validate_success(
            client.list_iterations(
                ctx["calculation_id"], make_design_engineer_headers(ctx["lead_id"])
            )
        )
        by_index = {row["iteration_index"]: row for row in rows}

        # 19.05 -> 40.34 -> 45.28 -> 50.54, never the once-rounded raw sum of 50.56.
        assert by_index[1]["cumulative_psi_after"] == 40.34
        assert by_index[2]["cumulative_psi_after"] == 45.28
        assert by_index[3]["cumulative_psi_after"] == 50.54

        calculation = read_calculation(client, ctx["calculation_id"])
        assert calculation["required_psi_at_base_of_riser"] == HC1_REQUIRED_PSI
        assert calculation["iteration_count"] == 3
        assert calculation["state"] == "CONVERGED"


BULK_PLASTICS_BAY = dict(
    RACK_BAY, label="Bulk Plastics Bay", hazard_class="EXTRA_2"
)


def _sealed_fp2601(client):
    """HC-1 sealed at 1380.0 gpm beside the 750.0 gpm standpipe pair."""
    ctx = build_converged_stage(client)
    create_evaluation(
        client,
        ctx["project_id"],
        ctx["flow_test_id"],
        ctx["calculation_id"],
        ctx["lead_id"],
    )
    qc_pass(client, ctx["calculation_id"], ctx["second_id"])
    seal(client, ctx["calculation_id"], ctx["lead_id"])
    return ctx


class TestLedgerInputSetFiltering:
    def test_15_a_heavier_draft_calculation_never_takes_the_governing_role(self, client):
        """First, the eligible set is pinned by state: only calculations of this project in
        `CONVERGED`, `QC_PASSED` or `SEALED` are eligible. Calculations in `DRAFT`, `ITERATING`,
        `PRESSURE_DEFICIENT`, `REOPENED` or `ARCHIVED` are excluded.

        Design: Corner/calculations/demand_ledger_ignores_draft_calculations_and_withdrawn_auxiliary_systems
        """
        ctx = _sealed_fp2601(client)
        heavier_area = create_hazard_area(
            client, ctx["project_id"], ctx["lead_id"], **BULK_PLASTICS_BAY
        )
        heavier = create_calculation(
            client, ctx["project_id"], heavier_area["id"], ctx["lead_id"]
        )
        assert heavier["state"] == "DRAFT"
        assert_flow(heavier["hazard_total_demand_gpm"], 1655.0)

        project = read_project(client, ctx["project_id"])
        assert_demand_ledger(project, ctx["calculation_id"], 1380.0, 750.0, 2130.0)
        assert project["sealed_calculation_count"] == 1

    def test_16_a_withdrawn_system_leaves_the_roll_up_but_keeps_its_own_demand(self, client):
        """Third, `auxiliary_demand_gpm` is the sum of `demand_gpm` over every auxiliary system
        of the project whose `status` is anything other than `WITHDRAWN`.

        Design: Corner/calculations/demand_ledger_ignores_draft_calculations_and_withdrawn_auxiliary_systems
        """
        ctx = _sealed_fp2601(client)
        heavier_area = create_hazard_area(
            client, ctx["project_id"], ctx["lead_id"], **BULK_PLASTICS_BAY
        )
        create_calculation(client, ctx["project_id"], heavier_area["id"], ctx["lead_id"])

        racks = create_auxiliary_system(
            client,
            ctx["project_id"],
            ctx["lead_id"],
            system_type="IN_RACK",
            label="Rack tier heads",
            hazard_area_id=ctx["hazard_area_id"],
            in_rack_head_count=10,
        )
        assert_flow(racks["demand_gpm"], 300.0)
        assert_demand_ledger(
            read_project(client, ctx["project_id"]),
            ctx["calculation_id"],
            1380.0,
            1050.0,
            2430.0,
        )

        withdrawn = validate_success(
            client.withdraw_auxiliary_system(
                racks["id"],
                make_design_engineer_headers(ctx["lead_id"]),
                build_withdraw_payload("Value engineered out"),
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert_flow(withdrawn["demand_gpm"], 300.0)

        project = read_project(client, ctx["project_id"])
        assert_demand_ledger(project, ctx["calculation_id"], 1380.0, 750.0, 2130.0)
        assert project["sealed_calculation_count"] == 1


MINOR_ROUNDS = [
    ("NFPA 13 23.4.1", "Remote area label missing"),
    ("NFPA 13 23.4.2", "Node numbering unclear"),
    ("NFPA 13 23.4.3", "Riser detail incomplete"),
    ("NFPA 13 23.4.4", "Hanger schedule missing"),
]


def _minor_round(client, ctx, submittal_id, round_index):
    """Raise one MINOR comment and close the pass, returning the commented package."""
    code_section, description = MINOR_ROUNDS[round_index]
    raise_comment(
        client,
        submittal_id,
        ctx["reviewer_id"],
        code_section=code_section,
        severity="MINOR",
        description=description,
        assigned_engineer_id=ctx["lead_id"],
    )
    return complete_review(client, submittal_id, ctx["reviewer_id"])


def _resubmit(client, ctx, submittal_id):
    payload = build_resubmit_payload(
        included_calculation_ids=[ctx["calculation_id"]],
        expected_project_version=read_project(client, ctx["project_id"])["version"],
    )
    return client.resubmit(
        submittal_id, payload, make_design_engineer_headers(ctx["lead_id"])
    )


def _pay(client, ctx, amount_usd):
    return validate_success(
        client.pay_review_fee(
            ctx["project_id"], build_fee_payment_payload(amount_usd), CONTRACTOR_HEADERS
        )
    )


def _walk_to_cycle(client, target_cycle):
    """Walk the FP-2601 package through MINOR comment rounds up to `target_cycle`.

    The target cycle is left in `SUBMITTED` with whatever fee it charged outstanding.
    """
    ctx = build_under_review_stage(client)
    ctx["cycles"] = {1: read_submittal(client, ctx["submittal_id"])}
    current = ctx["submittal_id"]
    for cycle in range(2, target_cycle + 1):
        _minor_round(client, ctx, current, cycle - 2)
        successor = validate_success(_resubmit(client, ctx, current), expected_status=201)
        ctx["cycles"][cycle] = successor
        current = successor["id"]
        if cycle < target_cycle:
            balance = read_project(client, ctx["project_id"])["review_fee_balance_usd"]
            if balance > 0:
                _pay(client, ctx, balance)
            begin_review(client, current, ctx["reviewer_id"])
    ctx["current_submittal_id"] = current
    return ctx


class TestResubmittalFeeSchedule:
    def test_17_the_first_two_cycles_are_free_and_the_third_charges_two_fifty(self, client):
        """`review_fee_usd` is 0.00 for the first two cycles, 250.00 for the third cycle, and
        500.00 for the fourth.

        Design: Corner/calculations/resubmittal_fee_walks_free_free_two_fifty_five_hundred_then_refuses_a_fifth_cycle
        """
        ctx = _walk_to_cycle(client, 3)
        first, second, third = (ctx["cycles"][n] for n in (1, 2, 3))

        assert first["cycle_number"] == 1
        assert_money(first["review_fee_usd"], 0.00)
        assert second["cycle_number"] == 2
        assert_money(second["review_fee_usd"], 0.00)
        assert second["supersedes_submittal_id"] == first["id"]
        assert third["cycle_number"] == 3
        assert_money(third["review_fee_usd"], 250.00)
        assert third["supersedes_submittal_id"] == second["id"]

        project = read_project(client, ctx["project_id"])
        assert_money(project["review_fee_balance_usd"], 250.00)
        assert project["submittal_cycle_count"] == 3
        assert read_submittal(client, first["id"])["state"] == "SUPERSEDED"
        assert read_submittal(client, second["id"])["state"] == "SUPERSEDED"

    def test_18_the_outstanding_balance_blocks_review_until_it_is_paid(self, client):
        """The authority opens review only against a paid-up project: while
        `review_fee_balance_usd` is above 0.00 the attempt is refused with
        `ERR_REVIEW_FEE_OUTSTANDING`.

        Design: Corner/calculations/resubmittal_fee_walks_free_free_two_fifty_five_hundred_then_refuses_a_fifth_cycle
        """
        ctx = _walk_to_cycle(client, 3)
        third = ctx["cycles"][3]

        refused = client.begin_review(
            third["id"], make_ahj_reviewer_headers(ctx["reviewer_id"])
        )
        validate_error(refused, "ERR_REVIEW_FEE_OUTSTANDING", expected_status=402)
        assert read_submittal(client, third["id"])["state"] == "SUBMITTED"

        paid = _pay(client, ctx, 250.00)
        assert_money(paid["review_fee_balance_usd"], 0.00)
        opened = begin_review(client, third["id"], ctx["reviewer_id"])
        assert opened["state"] == "UNDER_REVIEW"

    def test_19_the_fourth_cycle_charges_five_hundred_and_a_fifth_is_refused(self, client):
        """the fourth is the last cycle the authority accepts, and a fifth is refused with
        `ERR_RESUBMITTAL_CYCLE_LIMIT`.

        Design: Corner/calculations/resubmittal_fee_walks_free_free_two_fifty_five_hundred_then_refuses_a_fifth_cycle
        """
        ctx = _walk_to_cycle(client, 4)
        fourth = ctx["cycles"][4]
        assert fourth["cycle_number"] == 4
        assert_money(fourth["review_fee_usd"], 500.00)
        assert_money(
            read_project(client, ctx["project_id"])["review_fee_balance_usd"], 500.00
        )

        _pay(client, ctx, 500.00)
        begin_review(client, fourth["id"], ctx["reviewer_id"])
        commented = _minor_round(client, ctx, fourth["id"], 3)
        assert commented["state"] == "COMMENTS_ISSUED"

        refused = _resubmit(client, ctx, fourth["id"])
        validate_error(refused, "ERR_RESUBMITTAL_CYCLE_LIMIT", expected_status=409)

        project = read_project(client, ctx["project_id"])
        assert project["submittal_cycle_count"] == 4
        assert_money(project["review_fee_balance_usd"], 0.00)
        assert read_submittal(client, ctx["cycles"][3]["id"])["state"] == "SUPERSEDED"
        assert read_submittal(client, fourth["id"])["state"] == "COMMENTS_ISSUED"


FIRST_WITNESS_WINDOW = ("2026-09-10T14:00:00Z", "2026-09-10T18:00:00Z")
RETEST_WINDOW = ("2026-09-12T14:00:00Z", "2026-09-12T18:00:00Z")


def _scheduled_flow_test(client):
    """A permitted FP-2601 with its SYSTEM_FLOW_TEST booked for the examiner."""
    ctx = build_permitted_stage(client)
    test_row = open_acceptance_test(client, ctx["project_id"], test_type="SYSTEM_FLOW_TEST")
    ctx["acceptance_test_id"] = test_row["id"]
    assert_flow(test_row["required_flow_gpm"], 2023.5)
    assert_pressure(test_row["required_residual_psi"], HC1_REQUIRED_PSI)
    ctx["scheduled"] = schedule_witness(
        client, ctx["acceptance_test_id"], ctx["reviewer_id"], *FIRST_WITNESS_WINDOW
    )
    return ctx


class TestWitnessThresholdsAreNonStrict:
    def test_20_one_hundredth_below_the_residual_threshold_fails_the_test(self, client):
        """The test passes only when both readings meet or exceed their threshold:
        `measured_flow_gpm` at least `required_flow_gpm` **and** `measured_residual_psi` at
        least `required_residual_psi`.

        Design: Corner/calculations/witness_passes_exactly_at_the_frozen_thresholds_and_fails_one_hundredth_below
        """
        ctx = _scheduled_flow_test(client)
        failed = record_witness(
            client, ctx["acceptance_test_id"], ctx["reviewer_id"], 2023.5, 50.53
        )
        assert failed["witness_status"] == "WITNESSED_FAIL"

        project = read_project(client, ctx["project_id"])
        assert project["status"] == "CORRECTIVE_ACTION"
        assert_posture(project, "FROZEN")
        assert read_auxiliary_system(client, ctx["standpipe"]["id"])["status"] == "PROPOSED"

    def test_21_the_retest_measuring_the_thresholds_exactly_passes(self, client):
        """It is also the route back from a failed test: from `WITNESSED_FAIL` it moves the
        dimension to `SCHEDULED` again, raises `retest_count` by 1, returns the project
        `CORRECTIVE_ACTION → ACCEPTANCE`, and recomputes the project's posture.

        Design: Corner/calculations/witness_passes_exactly_at_the_frozen_thresholds_and_fails_one_hundredth_below
        """
        ctx = _scheduled_flow_test(client)
        record_witness(client, ctx["acceptance_test_id"], ctx["reviewer_id"], 2023.5, 50.53)

        rebooked = schedule_witness(
            client, ctx["acceptance_test_id"], ctx["reviewer_id"], *RETEST_WINDOW
        )
        assert rebooked["witness_status"] == "SCHEDULED"
        assert rebooked["retest_count"] == 1
        lifted = read_project(client, ctx["project_id"])
        assert lifted["status"] == "ACCEPTANCE"
        assert_posture(lifted, "OPEN")

        passed = record_witness(
            client, ctx["acceptance_test_id"], ctx["reviewer_id"], 2023.5, 50.54
        )
        assert passed["witness_status"] == "WITNESSED_PASS"
        assert_flow(passed["measured_flow_gpm"], 2023.5)
        assert_pressure(passed["measured_residual_psi"], HC1_REQUIRED_PSI)

        final = read_acceptance_test(client, ctx["acceptance_test_id"])
        assert final["retest_count"] == 1
        assert read_project(client, ctx["project_id"])["status"] == "ACCEPTANCE"
