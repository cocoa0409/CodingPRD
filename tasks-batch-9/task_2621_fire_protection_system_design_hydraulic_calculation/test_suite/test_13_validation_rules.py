"""Field-level and conditional validation rules, each pinned to its own error identifier."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_calculation_demand_snapshot,
    assert_classification,
    assert_flow,
    assert_margin,
    assert_money,
    assert_posture,
    assert_pressure,
    assert_reopened,
    assert_sheet_counters,
)
from test_helpers.factories import (
    build_clock_payload,
    build_commission_payload,
    build_fee_payment_payload,
    build_fire_pump_payload,
    build_hydraulic_calculation_payload,
    build_iteration_payload,
    build_reclassify_payload,
    build_acceptance_test_payload,
    build_auxiliary_system_payload,
    build_submittal_payload,
    build_schedule_witness_payload,
    build_trade_clearance_payload,
)
from test_helpers.fixtures import (
    CHAIN_ITERATION_1,
    CHAIN_SUPPLY_ITERATION,
    CONTRACTOR_HEADERS,
    HC1_REQUIRED_PSI,
    PROJECT_TOTAL_DEMAND_GPM,
    STANDPIPE_DEMAND_GPM,
    append_iteration,
    build_evaluated_stage,
    build_design_stage,
    build_iterating_stage,
    build_permitted_stage,
    build_project_stage,
    build_qc_passed_stage,
    build_under_review_stage,
    create_auxiliary_system,
    create_calculation,
    create_evaluation,
    create_flow_test,
    create_hazard_area,
    create_shop_drawing,
    open_acceptance_test,
    open_clearance,
    raise_comment,
    read_acceptance_test,
    read_auxiliary_system,
    close_comment,
    read_calculation,
    read_evaluation,
    read_project,
    read_shop_drawing,
    read_submittal,
    seal,
)
from test_helpers.test_users import (
    make_ahj_reviewer_headers,
    make_clock_headers,
    make_design_engineer_headers,
)

SEGMENT_TWO = dict(
    pipe_size_in="4", length_ft=90.0, fitting_equivalent_ft=5.0, flow_gpm=420.0,
    elevation_change_ft=0.0,
)


def _append(client, ctx, calculation_id, **iteration):
    return client.append_iteration(
        calculation_id,
        build_iteration_payload(**iteration),
        make_design_engineer_headers(ctx["lead_id"]),
    )


class TestIterationIndexSequence:
    def test_01_skipping_an_index_is_refused_and_appends_nothing(self, client):
        """`iteration_index` must equal the number of iteration rows the calculation already
        has, plus one — including rows that have been superseded out of the active chain — and
        any other value is rejected with `ERR_ITERATION_OUT_OF_SEQUENCE`.

        Design: Corner/validations/iteration_index_must_be_exactly_one_past_the_existing_row_count
        """
        ctx = build_design_stage(client)
        calculation = create_calculation(
            client, ctx["project_id"], ctx["hazard_area_id"], ctx["lead_id"]
        )
        append_iteration(client, calculation["id"], ctx["lead_id"], **CHAIN_ITERATION_1)

        refused = _append(client, ctx, calculation["id"], iteration_index=3, **SEGMENT_TWO)
        validate_error(refused, "ERR_ITERATION_OUT_OF_SEQUENCE", expected_status=409)

        assert read_calculation(client, calculation["id"])["iteration_count"] == 1
        rows = validate_success(
            client.list_iterations(
                calculation["id"], make_design_engineer_headers(ctx["lead_id"])
            )
        )
        assert [row["iteration_index"] for row in rows] == [1]

    def test_02_the_retry_at_the_next_index_is_accepted(self, client):
        """`iteration_index` must equal the number of iteration rows the calculation already
        has, plus one — including rows that have been superseded out of the active chain — and
        any other value is rejected with `ERR_ITERATION_OUT_OF_SEQUENCE`.

        Design: Corner/validations/iteration_index_must_be_exactly_one_past_the_existing_row_count
        """
        ctx = build_design_stage(client)
        calculation = create_calculation(
            client, ctx["project_id"], ctx["hazard_area_id"], ctx["lead_id"]
        )
        append_iteration(client, calculation["id"], ctx["lead_id"], **CHAIN_ITERATION_1)
        validate_error(
            _append(client, ctx, calculation["id"], iteration_index=3, **SEGMENT_TWO),
            "ERR_ITERATION_OUT_OF_SEQUENCE",
        )

        created = validate_success(
            _append(client, ctx, calculation["id"], iteration_index=2, **SEGMENT_TWO),
            expected_status=201,
        )
        assert created["iteration_index"] == 2
        assert created["cumulative_psi_after"] == 45.28

        after = read_calculation(client, calculation["id"])
        assert after["iteration_count"] == 2
        assert after["required_psi_at_base_of_riser"] == 45.28


RESTART_SEGMENT = dict(
    iteration_index=4, pipe_size_in="2.5", length_ft=150.0, fitting_equivalent_ft=40.0,
    flow_gpm=110.0, elevation_change_ft=0.0,
)
UPSIZED_SEGMENT = dict(
    iteration_index=5, pipe_size_in="6", length_ft=90.0, fitting_equivalent_ft=5.0,
    flow_gpm=420.0, elevation_change_ft=0.0,
)
UPSIZED_SUPPLY = dict(
    iteration_index=6, pipe_size_in="8", length_ft=60.0, fitting_equivalent_ft=5.0,
    flow_gpm=880.0, elevation_change_ft=8.0, is_supply_connection=True,
)


def _pressure_deficient_hc1(client):
    """HC-1 closed against a seasonally derated supply, 3.11 psi short."""
    ctx = build_iterating_stage(client)
    ctx["evaluation"] = create_evaluation(
        client,
        ctx["project_id"],
        ctx["flow_test_id"],
        ctx["calculation_id"],
        ctx["lead_id"],
        evaluation_basis="SEASONAL_ADJUSTED",
    )
    append_iteration(client, ctx["calculation_id"], ctx["lead_id"], **CHAIN_SUPPLY_ITERATION)
    return ctx


class TestChainRestartFlagAgreesWithTheState:
    def test_03_leaving_pressure_deficient_without_the_flag_is_refused(self, client):
        """The `restart_chain` flag must agree with the state the calculation is in: it is
        **required** to be true when the calculation is in `PRESSURE_DEFICIENT` or `REOPENED`
        ... A mismatch either way is rejected with `ERR_CHAIN_RESTART_REQUIRED`.

        Design: Corner/validations/restart_flag_is_required_leaving_pressure_deficient_and_refused_while_iterating
        """
        ctx = _pressure_deficient_hc1(client)
        deficient = read_calculation(client, ctx["calculation_id"])
        assert deficient["state"] == "PRESSURE_DEFICIENT"
        assert_pressure(deficient["deficiency_psi"], 3.11)
        assert_pressure(ctx["evaluation"]["available_psi_at_demand"], 52.43)

        refused = _append(client, ctx, ctx["calculation_id"], **RESTART_SEGMENT)
        validate_error(refused, "ERR_CHAIN_RESTART_REQUIRED", expected_status=409)

        unchanged = read_calculation(client, ctx["calculation_id"])
        assert unchanged["state"] == "PRESSURE_DEFICIENT"
        assert unchanged["iteration_count"] == 3
        assert unchanged["chain_start_index"] == 1

    def test_04_the_same_body_with_the_flag_opens_a_revised_chain(self, client):
        """An iteration with `restart_chain` true raises the calculation's `chain_start_index`
        to that iteration's own `iteration_index`, resets `iteration_count` to 1, marks every
        earlier iteration `in_active_chain` false without deleting it, and re-derives
        `end_head_psi` from this iteration's `flow_gpm`.

        Design: Corner/validations/restart_flag_is_required_leaving_pressure_deficient_and_refused_while_iterating
        """
        ctx = _pressure_deficient_hc1(client)
        headers = make_design_engineer_headers(ctx["lead_id"])
        validate_error(
            _append(client, ctx, ctx["calculation_id"], **RESTART_SEGMENT),
            "ERR_CHAIN_RESTART_REQUIRED",
        )

        restarted = validate_success(
            _append(client, ctx, ctx["calculation_id"], restart_chain=True, **RESTART_SEGMENT),
            expected_status=201,
        )
        assert_pressure(restarted["friction_loss_psi"], 8.96)
        assert restarted["velocity_fps"] == 7.37
        assert_pressure(restarted["cumulative_psi_after"], 28.01)
        assert restarted["in_active_chain"] is True

        calculation = read_calculation(client, ctx["calculation_id"])
        assert calculation["state"] == "ITERATING"
        assert calculation["chain_start_index"] == 4
        assert calculation["iteration_count"] == 1
        assert_pressure(calculation["end_head_psi"], 19.05)
        assert calculation["stale_reason"] is None

        rows = validate_success(client.list_iterations(ctx["calculation_id"], headers))
        superseded = {
            row["iteration_index"]: row["in_active_chain"]
            for row in rows
            if row["iteration_index"] < 4
        }
        assert superseded == {1: False, 2: False, 3: False}

    def test_05_carrying_the_flag_again_while_iterating_is_the_same_refusal(self, client):
        """... and it is **forbidden** — false or absent — when the calculation is in `DRAFT`
        or `ITERATING`. A mismatch either way is rejected with `ERR_CHAIN_RESTART_REQUIRED`.

        Design: Corner/validations/restart_flag_is_required_leaving_pressure_deficient_and_refused_while_iterating
        """
        ctx = _pressure_deficient_hc1(client)
        append_iteration(
            client, ctx["calculation_id"], ctx["lead_id"], restart_chain=True, **RESTART_SEGMENT
        )

        refused = _append(
            client, ctx, ctx["calculation_id"], restart_chain=True, **UPSIZED_SEGMENT
        )
        validate_error(refused, "ERR_CHAIN_RESTART_REQUIRED", expected_status=409)

        held = read_calculation(client, ctx["calculation_id"])
        assert held["state"] == "ITERATING"
        assert held["iteration_count"] == 1
        assert held["chain_start_index"] == 4

    def test_06_the_upsized_chain_reconverges_against_the_seasonal_supply(self, client):
        """When that figure is less than or equal to the evaluation's
        `available_psi_at_demand`, the calculation moves `ITERATING → CONVERGED`.

        Design: Corner/validations/restart_flag_is_required_leaving_pressure_deficient_and_refused_while_iterating
        """
        ctx = _pressure_deficient_hc1(client)
        append_iteration(
            client, ctx["calculation_id"], ctx["lead_id"], restart_chain=True, **RESTART_SEGMENT
        )
        middle = append_iteration(
            client, ctx["calculation_id"], ctx["lead_id"], **UPSIZED_SEGMENT
        )
        assert_pressure(middle["friction_loss_psi"], 0.67)
        assert_pressure(middle["cumulative_psi_after"], 28.68)

        closing = append_iteration(
            client, ctx["calculation_id"], ctx["lead_id"], **UPSIZED_SUPPLY
        )
        assert_pressure(closing["friction_loss_psi"], 0.47)
        assert_pressure(closing["elevation_loss_psi"], 3.46)
        assert_pressure(closing["cumulative_psi_after"], 32.61)

        calculation = read_calculation(client, ctx["calculation_id"])
        assert calculation["state"] == "CONVERGED"
        assert calculation["iteration_count"] == 3
        assert_pressure(calculation["required_psi_at_base_of_riser"], 32.61)
        assert calculation["deficiency_psi"] is None

        project = read_project(client, ctx["project_id"])
        assert project["governing_hydraulic_calculation_id"] == ctx["calculation_id"]
        assert_flow(project["total_system_demand_gpm"], PROJECT_TOTAL_DEMAND_GPM)


def _sheet_with_structural_open(client):
    """Sheet FP-101 over the sealed HC-1, carrying one STRUCTURAL coordination item."""
    ctx = build_qc_passed_stage(client)
    seal(client, ctx["calculation_id"], ctx["lead_id"])
    sheet = create_shop_drawing(client, ctx["project_id"], ctx["calculation_id"])
    ctx["sheet_id"] = sheet["id"]
    ctx["structural"] = open_clearance(client, sheet["id"], "STRUCTURAL")
    return ctx


class TestOneItemPerTradePerSheet:
    def test_07_a_second_structural_item_on_the_same_sheet_is_refused(self, client):
        """Only one item per trade per sheet is permitted, and a second attempt for the same
        `trade` is refused with `ERR_DUPLICATE_TRADE_CLEARANCE`.

        Design: Corner/validations/one_trade_may_be_cleared_only_once_per_sheet
        """
        ctx = _sheet_with_structural_open(client)
        assert ctx["structural"]["trade"] == "STRUCTURAL"

        refused = client.create_trade_clearance(
            ctx["sheet_id"],
            build_trade_clearance_payload(
                trade="STRUCTURAL", elevation_low_in=100.0, elevation_high_in=130.0
            ),
            CONTRACTOR_HEADERS,
        )
        validate_error(refused, "ERR_DUPLICATE_TRADE_CLEARANCE", expected_status=409)

        # The refusal touches neither counter on the sheet.
        assert_sheet_counters(read_shop_drawing(client, ctx["sheet_id"]), "IN_COORDINATION", 0)

    def test_08_a_different_trade_on_the_same_sheet_opens_normally(self, client):
        """A new item opens in state `PENDING` with `conflict_severity` and `note` both null.

        Design: Corner/validations/one_trade_may_be_cleared_only_once_per_sheet
        """
        ctx = _sheet_with_structural_open(client)
        validate_error(
            client.create_trade_clearance(
                ctx["sheet_id"],
                build_trade_clearance_payload(
                    trade="STRUCTURAL", elevation_low_in=100.0, elevation_high_in=130.0
                ),
                CONTRACTOR_HEADERS,
            ),
            "ERR_DUPLICATE_TRADE_CLEARANCE",
        )

        mechanical = validate_success(
            client.create_trade_clearance(
                ctx["sheet_id"],
                build_trade_clearance_payload(
                    trade="MECHANICAL", elevation_low_in=120.0, elevation_high_in=144.0
                ),
                CONTRACTOR_HEADERS,
            ),
            expected_status=201,
        )
        assert mechanical["trade"] == "MECHANICAL"
        assert mechanical["state"] == "PENDING"
        assert mechanical["conflict_severity"] is None
        assert mechanical["note"] is None
        assert mechanical["shop_drawing_id"] == ctx["sheet_id"]

        # Two open items, still nothing cleared.
        assert_sheet_counters(read_shop_drawing(client, ctx["sheet_id"]), "IN_COORDINATION", 0)


OVERSTATED_SUPPLY = dict(CHAIN_SUPPLY_ITERATION, flow_gpm=900.0)


def _iterating_with_preliminary_evaluation(client):
    """HC-1 at two segments with an EVALUATED raw-test supply already on the project."""
    ctx = build_iterating_stage(client)
    ctx["evaluation"] = create_evaluation(
        client,
        ctx["project_id"],
        ctx["flow_test_id"],
        ctx["calculation_id"],
        ctx["lead_id"],
    )
    return ctx


class TestSupplyConnectionFlowMustMatchTheDesignFlow:
    def test_09_a_more_conservative_closing_flow_is_still_refused(self, client):
        """Both branches first require that the closing segment's `flow_gpm` is exactly equal
        to the calculation's `design_flow_gpm`; a mismatch is rejected with
        `ERR_SUPPLY_FLOW_MISMATCH`.

        Design: Corner/validations/supply_connection_flow_must_equal_the_calculations_design_flow_exactly
        """
        ctx = _iterating_with_preliminary_evaluation(client)
        assert_flow(read_calculation(client, ctx["calculation_id"])["design_flow_gpm"], 880.0)
        assert_pressure(ctx["evaluation"]["available_psi_at_demand"], 65.54)

        refused = _append(client, ctx, ctx["calculation_id"], **OVERSTATED_SUPPLY)
        validate_error(refused, "ERR_SUPPLY_FLOW_MISMATCH", expected_status=422)

        held = read_calculation(client, ctx["calculation_id"])
        assert held["state"] == "ITERATING"
        assert held["iteration_count"] == 2

    def test_10_the_retry_at_exactly_the_design_flow_converges(self, client):
        """When that figure is less than or equal to the evaluation's
        `available_psi_at_demand`, the calculation moves `ITERATING → CONVERGED`.

        Design: Corner/validations/supply_connection_flow_must_equal_the_calculations_design_flow_exactly
        """
        ctx = _iterating_with_preliminary_evaluation(client)
        validate_error(
            _append(client, ctx, ctx["calculation_id"], **OVERSTATED_SUPPLY),
            "ERR_SUPPLY_FLOW_MISMATCH",
        )

        closing = validate_success(
            _append(client, ctx, ctx["calculation_id"], **CHAIN_SUPPLY_ITERATION),
            expected_status=201,
        )
        assert closing["iteration_index"] == 3
        assert_pressure(closing["cumulative_psi_after"], 50.54)

        converged = read_calculation(client, ctx["calculation_id"])
        assert converged["state"] == "CONVERGED"
        assert_pressure(converged["required_psi_at_base_of_riser"], HC1_REQUIRED_PSI)
        assert converged["iteration_count"] == 3


UNENCLOSED_RACK = dict(
    label="Rack Storage Bay A", hazard_class="ORDINARY_2", commodity_class="CLASS_IV",
    storage_height_ft=18.0, ceiling_height_ft=36.0, area_sqft=24000.0,
    sprinkler_system_type="WET", ceiling_slope_pct=4.0,
    room_area_sqft=None, enclosure_rating_hours=None, room_has_unprotected_opening=None,
)
SMALL_ROOM = dict(
    hazard_class="ORDINARY_1", commodity_class="CLASS_III", storage_height_ft=8.0,
    ceiling_height_ft=12.0, area_sqft=1800.0, sprinkler_system_type="WET",
    ceiling_slope_pct=4.0, room_has_unprotected_opening=False,
)
OVERSIZE_ROOM = dict(
    SMALL_ROOM, label="Oversize room", room_area_sqft=1800.0, enclosure_rating_hours=2.0
)
THIN_ENCLOSURE_ROOM = dict(
    SMALL_ROOM, label="Thin enclosure room", room_area_sqft=1200.0,
    enclosure_rating_hours=0.5,
)
COMPLIANT_ROOM = dict(
    SMALL_ROOM, label="Compliant room", room_area_sqft=1200.0, enclosure_rating_hours=2.0
)


def _open_room_design(client, ctx, hazard_area_id):
    return client.create_hydraulic_calculation(
        build_hydraulic_calculation_payload(
            project_id=ctx["project_id"], hazard_area_id=hazard_area_id,
            method="ROOM_DESIGN", k_factor=25.2,
        ),
        make_design_engineer_headers(ctx["lead_id"]),
    )


class TestRoomDesignAdmissibility:
    def test_11_an_area_with_no_enclosing_room_declared_cannot_use_the_method(self, client):
        """... the method is admissible only while three conditions all hold:
        `room_area_sqft` is present ... A request that asks for `ROOM_DESIGN` where any of the
        three fails is rejected with `ERR_ROOM_DESIGN_NOT_PERMITTED`.

        Design: Corner/validations/room_design_method_is_permitted_only_by_an_enclosed_room_no_larger_than_the_design_area
        """
        ctx = build_project_stage(client)
        area = create_hazard_area(client, ctx["project_id"], ctx["lead_id"], **UNENCLOSED_RACK)
        assert area["room_area_sqft"] is None

        refused = _open_room_design(client, ctx, area["id"])
        validate_error(refused, "ERR_ROOM_DESIGN_NOT_PERMITTED", expected_status=422)

    def test_12_a_room_larger_than_the_design_area_cannot_use_the_method(self, client):
        """... `room_area_sqft` is less than or equal to `design_area_sqft` ... A request that
        asks for `ROOM_DESIGN` where any of the three fails is rejected with
        `ERR_ROOM_DESIGN_NOT_PERMITTED`.

        Design: Corner/validations/room_design_method_is_permitted_only_by_an_enclosed_room_no_larger_than_the_design_area
        """
        ctx = build_project_stage(client)
        area = create_hazard_area(client, ctx["project_id"], ctx["lead_id"], **OVERSIZE_ROOM)
        assert_classification(area, "ORDINARY_1", 0.150, 1500.0, 250.0)
        assert area["room_area_sqft"] == 1800.0

        refused = _open_room_design(client, ctx, area["id"])
        validate_error(refused, "ERR_ROOM_DESIGN_NOT_PERMITTED", expected_status=422)

    def test_13_an_enclosure_below_one_hour_cannot_use_the_method(self, client):
        """... and `enclosure_rating_hours` is at least 1.0 hour. A request that asks for
        `ROOM_DESIGN` where any of the three fails is rejected with
        `ERR_ROOM_DESIGN_NOT_PERMITTED`.

        Design: Corner/validations/room_design_method_is_permitted_only_by_an_enclosed_room_no_larger_than_the_design_area
        """
        ctx = build_project_stage(client)
        area = create_hazard_area(
            client, ctx["project_id"], ctx["lead_id"], **THIN_ENCLOSURE_ROOM
        )
        assert area["enclosure_rating_hours"] == 0.5

        refused = _open_room_design(client, ctx, area["id"])
        validate_error(refused, "ERR_ROOM_DESIGN_NOT_PERMITTED", expected_status=422)

    def test_14_the_compliant_room_computes_the_demand_off_the_room_area(self, client):
        """Under `ROOM_DESIGN`, the basis area is the hazard area's `room_area_sqft` ... when
        the room has no unprotected opening the penalty is 0.0.

        Design: Corner/validations/room_design_method_is_permitted_only_by_an_enclosed_room_no_larger_than_the_design_area
        """
        ctx = build_project_stage(client)
        area = create_hazard_area(client, ctx["project_id"], ctx["lead_id"], **COMPLIANT_ROOM)
        for rejected in (UNENCLOSED_RACK, THIN_ENCLOSURE_ROOM):
            other = create_hazard_area(
                client, ctx["project_id"], ctx["lead_id"], **rejected
            )
            validate_error(
                _open_room_design(client, ctx, other["id"]), "ERR_ROOM_DESIGN_NOT_PERMITTED"
            )

        calculation = validate_success(
            _open_room_design(client, ctx, area["id"]), expected_status=201
        )
        assert calculation["state"] == "DRAFT"
        assert calculation["method"] == "ROOM_DESIGN"
        assert_calculation_demand_snapshot(calculation, 198.0, 250.0, 448.0)

        # A DRAFT calculation never enters the project ledger.
        assert read_project(client, ctx["project_id"])[
            "governing_hydraulic_calculation_id"
        ] is None


WEAK_HYDRANT = dict(
    hydrant_tag="H-22", static_psi=50.0, residual_psi=30.0, flow_gpm=4000.0,
    tested_at="2026-06-20T10:00:00.000Z",
)
RACK_TIER_HEADS = dict(
    system_type="IN_RACK", label="Rack tier heads", in_rack_head_count=20,
)


def _size_pump(client, ctx, evaluation, model_tag):
    return client.create_fire_pump(
        build_fire_pump_payload(
            project_id=ctx["project_id"],
            water_supply_evaluation_id=evaluation["id"],
            expected_water_supply_evaluation_version=evaluation["version"],
            model_tag=model_tag,
        ),
        make_design_engineer_headers(ctx["lead_id"]),
    )


def _weak_evaluation(client, ctx):
    """A second evaluation of the same design against the 50 / 30 / 4000 hydrant."""
    weak_test = create_flow_test(client, ctx["project_id"], ctx["lead_id"], **WEAK_HYDRANT)
    ctx["weak_test_id"] = weak_test["id"]
    return create_evaluation(
        client, ctx["project_id"], weak_test["id"], ctx["calculation_id"], ctx["lead_id"]
    )


class TestPumpSizingGuards:
    def test_15_an_adequate_evaluation_needs_no_pump(self, client):
        """The referenced evaluation ... must carry a `margin_verdict` other than `ADEQUATE` —
        an adequate supply needs no pump, and asking for one is refused with
        `ERR_PUMP_NOT_REQUIRED`.

        Design: Corner/validations/pump_sizing_is_refused_when_adequate_already_sized_or_beyond_the_catalogue
        """
        ctx = build_evaluated_stage(client)
        evaluation = ctx["evaluation"]
        assert_margin(evaluation, 65.54, 10.00, 15.3, "ADEQUATE")

        refused = _size_pump(client, ctx, evaluation, "PUMP-X")
        validate_error(refused, "ERR_PUMP_NOT_REQUIRED", expected_status=409)

        assert read_evaluation(client, evaluation["id"])["pump_sized"] is False

    def test_16_a_second_selection_against_the_same_evaluation_is_refused(self, client):
        """... and its `pump_sized` must still be false, since a second selection against the
        same evaluation is refused with `ERR_PUMP_ALREADY_SIZED`.

        Design: Corner/validations/pump_sizing_is_refused_when_adequate_already_sized_or_beyond_the_catalogue
        """
        ctx = build_evaluated_stage(client)
        weak = _weak_evaluation(client, ctx)
        assert_flow(weak["design_demand_gpm"], PROJECT_TOTAL_DEMAND_GPM)
        assert_margin(weak, 43.77, -11.77, -26.9, "INADEQUATE_PUMP_REQUIRED")

        pump = validate_success(_size_pump(client, ctx, weak, "PUMP-A"), expected_status=201)
        assert_flow(pump["rated_flow_gpm"], 2500.0)
        assert pump["sizing_verdict"] == "ACCEPTABLE"
        assert pump["state"] == "SIZED"

        # Re-reading the row first keeps the version pin current, so the guard that
        # answers is the one about the pump already existing.
        current = read_evaluation(client, weak["id"])
        assert current["pump_sized"] is True
        refused = _size_pump(client, ctx, current, "PUMP-B")
        validate_error(refused, "ERR_PUMP_ALREADY_SIZED", expected_status=409)

    def test_17_a_demand_past_the_top_of_the_catalogue_cannot_be_pumped(self, client):
        """`rated_flow_gpm` is the smallest catalogue rating that is greater than or equal to
        the evaluation's `design_demand_gpm`; when no rating reaches the demand the request is
        refused with `ERR_PUMP_CAPACITY_UNAVAILABLE`.

        Design: Corner/validations/pump_sizing_is_refused_when_adequate_already_sized_or_beyond_the_catalogue
        """
        ctx = build_evaluated_stage(client)
        weak = _weak_evaluation(client, ctx)
        _size_pump(client, ctx, weak, "PUMP-A")

        create_auxiliary_system(
            client,
            ctx["project_id"],
            ctx["lead_id"],
            hazard_area_id=ctx["hazard_area_id"],
            **RACK_TIER_HEADS,
        )
        project = read_project(client, ctx["project_id"])
        assert_flow(project["auxiliary_demand_gpm"], 1230.0)
        assert_flow(project["total_system_demand_gpm"], 2610.0)

        beyond = create_evaluation(
            client,
            ctx["project_id"],
            ctx["weak_test_id"],
            ctx["calculation_id"],
            ctx["lead_id"],
        )
        assert_flow(beyond["design_demand_gpm"], 2610.0)
        assert_margin(beyond, 40.92, -14.62, -35.7, "INADEQUATE_PUMP_REQUIRED")

        refused = _size_pump(client, ctx, beyond, "PUMP-C")
        validate_error(refused, "ERR_PUMP_CAPACITY_UNAVAILABLE", expected_status=422)

        pumps, meta = validate_paginated(
            client.list_fire_pumps(
                make_design_engineer_headers(ctx["lead_id"]),
                params={"project_id": ctx["project_id"]},
            )
        )
        assert meta["total_count"] == 1
        assert len(pumps) == 1


ZERO_LENGTH_OUTAGE = ("2026-09-05T08:00:00.000Z", "2026-09-05T08:00:00.000Z")
INVERTED_OUTAGE = ("2026-09-05T12:00:00.000Z", "2026-09-05T08:00:00.000Z")
GOOD_OUTAGE = ("2026-09-05T08:00:00.000Z", "2026-09-05T12:00:00.000Z")


def _commission(client, system_id, window):
    start, end = window
    return client.commission_auxiliary_system(
        system_id,
        build_commission_payload(outage_start_at=start, outage_end_at=end),
        CONTRACTOR_HEADERS,
    )


class TestOutageWindowIsStrictlyOrdered:
    def test_18_a_zero_length_outage_window_is_refused(self, client):
        """The window start must be strictly before the window end, and a window that is empty
        or inverted is refused with `ERR_WINDOW_START_NOT_BEFORE_END`.

        Design: Corner/validations/outage_window_start_must_be_strictly_before_its_end
        """
        ctx = build_design_stage(client)
        system_id = ctx["standpipe"]["id"]
        assert ctx["standpipe"]["interlock_required"] is False

        validate_error(
            _commission(client, system_id, ZERO_LENGTH_OUTAGE),
            "ERR_WINDOW_START_NOT_BEFORE_END",
            expected_status=422,
        )

        untouched = read_auxiliary_system(client, system_id)
        assert untouched["status"] == "PROPOSED"
        assert untouched["outage_start_at"] is None
        assert untouched["outage_end_at"] is None

    def test_19_an_inverted_outage_window_is_refused(self, client):
        """This check guards both witness scheduling and auxiliary system commissioning.

        Design: Corner/validations/outage_window_start_must_be_strictly_before_its_end
        """
        ctx = build_design_stage(client)
        system_id = ctx["standpipe"]["id"]

        validate_error(
            _commission(client, system_id, INVERTED_OUTAGE),
            "ERR_WINDOW_START_NOT_BEFORE_END",
            expected_status=422,
        )

        untouched = read_auxiliary_system(client, system_id)
        assert untouched["status"] == "PROPOSED"
        assert untouched["outage_start_at"] is None
        assert untouched["outage_end_at"] is None
        # No partial window was stored, and the ledger never moved.
        assert_flow(
            read_project(client, ctx["project_id"])["auxiliary_demand_gpm"],
            STANDPIPE_DEMAND_GPM,
        )

    def test_20_the_properly_ordered_window_commissions_the_same_row(self, client):
        """`outage_start_at` and `outage_end_at` bound the window and may be accompanied by
        `interlock_verified`.

        Design: Corner/validations/outage_window_start_must_be_strictly_before_its_end
        """
        ctx = build_design_stage(client)
        system_id = ctx["standpipe"]["id"]
        for bad in (ZERO_LENGTH_OUTAGE, INVERTED_OUTAGE):
            validate_error(
                _commission(client, system_id, bad), "ERR_WINDOW_START_NOT_BEFORE_END"
            )

        commissioned = validate_success(
            _commission(client, system_id, GOOD_OUTAGE), expected_status=200
        )
        assert commissioned["status"] == "COMMISSIONED"
        assert str(commissioned["outage_start_at"]).startswith("2026-09-05T08:00:00")
        assert str(commissioned["outage_end_at"]).startswith("2026-09-05T12:00:00")
        assert_flow(commissioned["demand_gpm"], STANDPIPE_DEMAND_GPM)

        assert_flow(
            read_project(client, ctx["project_id"])["auxiliary_demand_gpm"],
            STANDPIPE_DEMAND_GPM,
        )


MOVED_CLOCK = "2026-09-15T09:00:00Z"
PAST_ZERO_LENGTH = ("2026-09-10T14:00:00Z", "2026-09-10T14:00:00Z")
PAST_WINDOW = ("2026-09-10T14:00:00Z", "2026-09-10T18:00:00Z")
AT_THE_CLOCK_WINDOW = ("2026-09-15T09:00:00Z", "2026-09-15T13:00:00Z")


def _book(client, ctx, window):
    start, end = window
    return client.schedule_witness(
        ctx["acceptance_test_id"],
        build_schedule_witness_payload(witness_window_start=start, witness_window_end=end),
        make_ahj_reviewer_headers(ctx["reviewer_id"]),
    )


def _test_awaiting_a_witness_at_the_moved_clock(client):
    """A permitted project with an unscheduled acceptance test, the clock moved forward."""
    ctx = build_permitted_stage(client)
    test_row = open_acceptance_test(client, ctx["project_id"])
    ctx["acceptance_test_id"] = test_row["id"]
    assert test_row["witness_status"] == "NOT_SCHEDULED"
    validate_success(
        client.set_clock(build_clock_payload(current_utc=MOVED_CLOCK), make_clock_headers())
    )
    return ctx


class TestWitnessWindowAgainstTheLogicalClock:
    def test_21_the_ordering_check_answers_before_the_past_check(self, client):
        """The window start must be strictly before the window end, or the booking is refused
        with `ERR_WINDOW_START_NOT_BEFORE_END`, and it must be at or after the current logical
        clock reading, or refused with `ERR_WITNESS_WINDOW_IN_PAST`.

        Design: Corner/validations/witness_window_may_start_exactly_at_the_logical_clock_but_never_before_it
        """
        ctx = _test_awaiting_a_witness_at_the_moved_clock(client)

        # The window is both zero-length and behind the clock; ordering is checked first.
        refused = _book(client, ctx, PAST_ZERO_LENGTH)
        validate_error(refused, "ERR_WINDOW_START_NOT_BEFORE_END", expected_status=422)

        untouched = read_acceptance_test(client, ctx["acceptance_test_id"])
        assert untouched["witness_status"] == "NOT_SCHEDULED"
        assert untouched["witness_reviewer_id"] is None

    def test_22_a_well_ordered_window_behind_the_clock_is_in_the_past(self, client):
        """... and it must be at or after the current logical clock reading, or refused with
        `ERR_WITNESS_WINDOW_IN_PAST`.

        Design: Corner/validations/witness_window_may_start_exactly_at_the_logical_clock_but_never_before_it
        """
        ctx = _test_awaiting_a_witness_at_the_moved_clock(client)

        refused = _book(client, ctx, PAST_WINDOW)
        validate_error(refused, "ERR_WITNESS_WINDOW_IN_PAST", expected_status=422)

        untouched = read_acceptance_test(client, ctx["acceptance_test_id"])
        assert untouched["witness_status"] == "NOT_SCHEDULED"
        assert untouched["witness_reviewer_id"] is None
        assert untouched["retest_count"] == 0

    def test_23_a_window_starting_on_the_clock_instant_is_accepted(self, client):
        """A successful booking moves the witness dimension `NOT_SCHEDULED → SCHEDULED` on a
        first attempt.

        Design: Corner/validations/witness_window_may_start_exactly_at_the_logical_clock_but_never_before_it
        """
        ctx = _test_awaiting_a_witness_at_the_moved_clock(client)
        for bad, error_id in (
            (PAST_ZERO_LENGTH, "ERR_WINDOW_START_NOT_BEFORE_END"),
            (PAST_WINDOW, "ERR_WITNESS_WINDOW_IN_PAST"),
        ):
            validate_error(_book(client, ctx, bad), error_id)

        booked = validate_success(_book(client, ctx, AT_THE_CLOCK_WINDOW), expected_status=200)
        assert booked["witness_status"] == "SCHEDULED"
        assert str(booked["witness_window_start"]).startswith("2026-09-15T09:00:00")
        assert booked["witness_reviewer_id"] == ctx["reviewer_id"]
        assert booked["retest_count"] == 0
        assert booked["documentation_status"] == "PENDING"


MAJOR_COMMENT = dict(
    code_section="NFPA 13 12.3.2",
    severity="MAJOR",
    description="Rack demand not demonstrated",
)
REVISED_OFFICE_AREA = dict(
    label="Revised office area", hazard_class="ORDINARY_1", commodity_class="CLASS_III",
    storage_height_ft=8.0, ceiling_height_ft=12.0, area_sqft=24000.0,
    sprinkler_system_type="WET", ceiling_slope_pct=4.0,
    room_area_sqft=None, enclosure_rating_hours=None, room_has_unprotected_opening=None,
)


def _gated_by_one_major_comment(client):
    """One MAJOR comment outstanding on the package under review, so the project is GATED."""
    ctx = build_under_review_stage(client)
    ctx["comment"] = raise_comment(
        client,
        ctx["submittal_id"],
        ctx["reviewer_id"],
        assigned_engineer_id=ctx["lead_id"],
        **MAJOR_COMMENT,
    )
    project = read_project(client, ctx["project_id"])
    assert project["open_major_comment_count"] == 1
    assert_posture(project, "GATED")
    return ctx


class TestGatedPostureBlastRadius:
    def test_24_lodging_a_package_is_refused_while_a_major_comment_is_open(self, client):
        """A `GATED` posture is narrower and refuses only the three package-advancing writes
        with `ERR_PROJECT_POSTURE_GATED` (HTTP 409): sealing a hydraulic calculation, lodging a
        permit submittal, and opening an acceptance test.

        Design: Corner/validations/an_open_major_comment_gates_the_three_package_writes_and_nothing_else
        """
        ctx = _gated_by_one_major_comment(client)

        # The version pin is read fresh, so the posture is what has to answer.
        refused = client.create_submittal(
            build_submittal_payload(
                project_id=ctx["project_id"],
                included_calculation_ids=[ctx["calculation_id"]],
                expected_project_version=read_project(client, ctx["project_id"])["version"],
            ),
            make_design_engineer_headers(ctx["lead_id"]),
        )
        validate_error(refused, "ERR_PROJECT_POSTURE_GATED", expected_status=409)

        assert read_project(client, ctx["project_id"])["submittal_cycle_count"] == 1

    def test_25_opening_an_acceptance_test_is_refused_while_the_gate_holds(self, client):
        """... refuses only the three package-advancing writes with
        `ERR_PROJECT_POSTURE_GATED` (HTTP 409) ... and opening an acceptance test.

        Design: Corner/validations/an_open_major_comment_gates_the_three_package_writes_and_nothing_else
        """
        ctx = _gated_by_one_major_comment(client)

        refused = client.create_acceptance_test(
            build_acceptance_test_payload(
                project_id=ctx["project_id"], test_type="SYSTEM_FLOW_TEST"
            ),
            CONTRACTOR_HEADERS,
        )
        validate_error(refused, "ERR_PROJECT_POSTURE_GATED", expected_status=409)

        assert read_project(client, ctx["project_id"])["status"] == "PERMIT_REVIEW"

    def test_26_a_design_write_on_the_same_project_stays_available(self, client):
        """Everything else stays available on purpose — while a `MAJOR` comment is outstanding
        the designer must still be able to revise geometry, re-run the chain and write the
        response that clears the gate.

        Design: Corner/validations/an_open_major_comment_gates_the_three_package_writes_and_nothing_else
        """
        ctx = _gated_by_one_major_comment(client)

        area = create_hazard_area(
            client, ctx["project_id"], ctx["lead_id"], **REVISED_OFFICE_AREA
        )
        assert area["label"] == "Revised office area"
        assert_classification(area, "ORDINARY_1", 0.150, 1500.0, 250.0)

        # The gate is still up; only the design surface was open.
        assert_posture(read_project(client, ctx["project_id"]), "GATED")

    def test_27_withdrawing_the_comment_returns_the_posture_to_open(self, client):
        """`WITHDRAWN` retracts the comment entirely from `OPEN`, moving it to `WITHDRAWN`.
        Every disposition recounts the package's `open_comment_count` and
        `major_comment_count`, recounts the project's `open_major_comment_count`, and
        recomputes the posture, which may return the project to `OPEN`.

        Design: Corner/validations/an_open_major_comment_gates_the_three_package_writes_and_nothing_else
        """
        ctx = _gated_by_one_major_comment(client)

        withdrawn = close_comment(
            client,
            ctx["comment"]["id"],
            ctx["reviewer_id"],
            disposition="WITHDRAWN",
            close_note="Raised against the wrong sheet",
        )
        assert withdrawn["state"] == "WITHDRAWN"
        assert withdrawn["disposition"] == "WITHDRAWN"

        submittal = read_submittal(client, ctx["submittal_id"])
        assert submittal["state"] == "UNDER_REVIEW"
        assert submittal["open_comment_count"] == 0
        assert submittal["major_comment_count"] == 0

        project = read_project(client, ctx["project_id"])
        assert project["open_major_comment_count"] == 0
        assert_posture(project, "OPEN")
        # Raising and withdrawing before the pass closed out moved nothing downstream.
        assert project["sealed_calculation_count"] == 1
        assert read_calculation(client, ctx["calculation_id"])["state"] == "SEALED"


def _rack_project(client):
    """FP-2601 with the CLASS_IV rack area and no auxiliary system yet."""
    ctx = build_project_stage(client)
    area = create_hazard_area(client, ctx["project_id"], ctx["lead_id"], **UNENCLOSED_RACK)
    ctx["hazard_area_id"] = area["id"]
    return ctx


def _propose_system(client, ctx, **fields):
    return client.create_auxiliary_system(
        build_auxiliary_system_payload(project_id=ctx["project_id"], **fields),
        make_design_engineer_headers(ctx["lead_id"]),
    )


class TestSystemTypeConditionalFields:
    def test_28_each_type_refuses_the_body_that_omits_its_own_field(self, client):
        """Which further fields are required depends entirely on the type, and a missing one is
        refused with `ERR_SYSTEM_TYPE_FIELD_REQUIRED`.

        Design: Corner/validations/system_type_decides_which_schema_optional_fields_are_actually_required
        """
        ctx = _rack_project(client)
        bodies = [
            dict(system_type="STANDPIPE_CLASS_I", label="Stairs with no riser count"),
            dict(
                system_type="COOKING", label="Hood with no appliance count",
                water_wash_enabled=True, agent_type="WET_CHEMICAL",
            ),
            dict(
                system_type="FOAM_DELUGE", label="Foam with no area", agent_type="AFFF"
            ),
        ]
        for body in bodies:
            refused = _propose_system(client, ctx, **body)
            validate_error(refused, "ERR_SYSTEM_TYPE_FIELD_REQUIRED", expected_status=422)

        # None of the refused bodies left a partial row behind.
        assert_flow(read_project(client, ctx["project_id"])["auxiliary_demand_gpm"], 0.0)

    def test_29_in_rack_needs_both_of_its_conditional_fields(self, client):
        """`IN_RACK` requires both `in_rack_head_count`, the number of in-rack sprinklers
        assumed operating, at least 1 when present, and a `hazard_area_id` naming the area the
        racks stand in.

        Design: Corner/validations/system_type_decides_which_schema_optional_fields_are_actually_required
        """
        ctx = _rack_project(client)

        no_head_count = _propose_system(
            client, ctx, system_type="IN_RACK", label="Rack with no head count",
            hazard_area_id=ctx["hazard_area_id"],
        )
        validate_error(no_head_count, "ERR_SYSTEM_TYPE_FIELD_REQUIRED", expected_status=422)

        no_area = _propose_system(
            client, ctx, system_type="IN_RACK", label="Rack with no hazard area",
            in_rack_head_count=10,
        )
        validate_error(no_area, "ERR_SYSTEM_TYPE_FIELD_REQUIRED", expected_status=422)

        assert_flow(read_project(client, ctx["project_id"])["auxiliary_demand_gpm"], 0.0)

    def test_30_a_type_whose_conditional_field_is_present_is_accepted(self, client):
        """A Class II standpipe starts at 100.0 for the first riser, adds 75.0 for each
        additional riser, and is capped at 400.0.

        Design: Corner/validations/system_type_decides_which_schema_optional_fields_are_actually_required
        """
        ctx = _rack_project(client)
        validate_error(
            _propose_system(
                client, ctx, system_type="STANDPIPE_CLASS_I", label="Stairs with no riser count"
            ),
            "ERR_SYSTEM_TYPE_FIELD_REQUIRED",
        )

        accepted = validate_success(
            _propose_system(
                client, ctx, system_type="STANDPIPE_CLASS_II", label="Hose station",
                riser_count=1,
            ),
            expected_status=201,
        )
        assert_flow(accepted["demand_gpm"], 100.0)
        assert accepted["interlock_required"] is False
        assert accepted["status"] == "PROPOSED"

        project = read_project(client, ctx["project_id"])
        assert_flow(project["auxiliary_demand_gpm"], 100.0)
        assert_flow(project["total_system_demand_gpm"], 100.0)


SECOND_HOSE_STATION = dict(
    system_type="STANDPIPE_CLASS_II", label="Hose station 2", riser_count=1
)


def _qc_passed_then_a_hose_station_added(client):
    """HC-1 is QC-passed against a 2130.0 gpm ledger, then a hose station lifts it."""
    ctx = build_qc_passed_stage(client)
    assert_flow(ctx["evaluation"]["design_demand_gpm"], PROJECT_TOTAL_DEMAND_GPM)
    create_auxiliary_system(
        client, ctx["project_id"], ctx["lead_id"], **SECOND_HOSE_STATION
    )
    project = read_project(client, ctx["project_id"])
    assert_flow(project["auxiliary_demand_gpm"], 850.0)
    assert_flow(project["total_system_demand_gpm"], 2230.0)
    return ctx


class TestSealReconcilesAgainstTheCurrentLedger:
    def test_31_a_demand_added_after_the_evaluation_blocks_the_seal(self, client):
        """... and the evaluation's `design_demand_gpm` must equal the project's current
        `total_system_demand_gpm`. Any one of the three disagreeing is refused with
        `ERR_EVALUATION_REFERENCE_STALE`.

        Design: Corner/validations/seal_is_refused_until_the_evaluation_is_rebuilt_on_the_new_ledger_total
        """
        ctx = _qc_passed_then_a_hose_station_added(client)

        refused = client.seal_calculation(
            ctx["calculation_id"], make_design_engineer_headers(ctx["lead_id"])
        )
        validate_error(refused, "ERR_EVALUATION_REFERENCE_STALE", expected_status=409)

        calculation = read_calculation(client, ctx["calculation_id"])
        assert calculation["state"] == "QC_PASSED"
        assert calculation["sealed_at"] is None
        assert calculation["sealed_by_engineer_id"] is None
        assert read_project(client, ctx["project_id"])["sealed_calculation_count"] == 0

    def test_32_a_fresh_evaluation_on_the_new_total_lets_the_seal_land(self, client):
        """This is the check that catches the case the version pins cannot: an auxiliary system
        added after the evaluation was taken raises the project's demand without touching the
        calculation, and the seal must not be granted against evidence that no longer describes
        the design.

        Design: Corner/validations/seal_is_refused_until_the_evaluation_is_rebuilt_on_the_new_ledger_total
        """
        ctx = _qc_passed_then_a_hose_station_added(client)
        headers = make_design_engineer_headers(ctx["lead_id"])
        validate_error(
            client.seal_calculation(ctx["calculation_id"], headers),
            "ERR_EVALUATION_REFERENCE_STALE",
        )

        rebuilt = create_evaluation(
            client,
            ctx["project_id"],
            ctx["flow_test_id"],
            ctx["calculation_id"],
            ctx["lead_id"],
        )
        assert_flow(rebuilt["design_demand_gpm"], 2230.0)
        assert_pressure(rebuilt["required_psi_at_demand"], 55.54)
        assert_margin(rebuilt, 64.26, 8.72, 13.6, "MARGINAL")
        assert rebuilt["pinned_calculation_iteration_count"] == 3

        sealed = validate_success(
            client.seal_calculation(ctx["calculation_id"], headers), expected_status=200
        )
        assert sealed["state"] == "SEALED"
        assert sealed["sealed_by_engineer_id"] == ctx["lead_id"]

        project = read_project(client, ctx["project_id"])
        assert project["sealed_calculation_count"] == 1
        assert project["governing_hydraulic_calculation_id"] == ctx["calculation_id"]
        assert_flow(project["total_system_demand_gpm"], 2230.0)


class TestFeePaymentAgainstAZeroBalance:
    def test_33_one_cent_over_a_zero_balance_is_refused_and_inert(self, client):
        """Overpayment is refused rather than clamped: when `amount_usd` exceeds the current
        `review_fee_balance_usd` the payment is rejected with
        `ERR_FEE_PAYMENT_EXCEEDS_BALANCE` and the balance is untouched.

        Design: Corner/validations/fee_payment_of_one_cent_against_a_zero_balance_is_refused
        """
        ctx = build_project_stage(client)
        before = read_project(client, ctx["project_id"])
        assert_money(before["review_fee_balance_usd"], 0.00)

        refused = client.pay_review_fee(
            ctx["project_id"],
            build_fee_payment_payload(amount_usd=0.01),
            CONTRACTOR_HEADERS,
        )
        validate_error(refused, "ERR_FEE_PAYMENT_EXCEEDS_BALANCE", expected_status=422)

        after = read_project(client, ctx["project_id"])
        assert_money(after["review_fee_balance_usd"], 0.00)
        assert after["version"] == before["version"], "the refused payment must be inert"
        assert after["submittal_cycle_count"] == 0


DOWNGRADE_TO_ORDINARY_1 = dict(
    hazard_class="ORDINARY_1", commodity_class="CLASS_III", storage_height_ft=8.0,
    ceiling_height_ft=12.0, area_sqft=24000.0, ceiling_slope_pct=4.0,
    room_area_sqft=None, enclosure_rating_hours=None, room_has_unprotected_opening=None,
)


class TestAcceptanceThresholdsNeedAGoverningCalculation:
    def test_34_reclassifying_after_the_permit_empties_the_eligible_set(self, client):
        """When the eligible set is empty, `governing_hydraulic_calculation_id` is null and
        `governing_demand_gpm` is 0.0.

        Design: Corner/validations/reclassifying_after_the_permit_leaves_the_acceptance_thresholds_undefined
        """
        ctx = build_permitted_stage(client)
        assert read_shop_drawing(client, ctx["sheet_id"])["state"] == "ISSUED"

        reclassified = validate_success(
            client.reclassify_hazard_area(
                ctx["hazard_area_id"],
                build_reclassify_payload(**DOWNGRADE_TO_ORDINARY_1),
                make_design_engineer_headers(ctx["lead_id"]),
            )
        )
        assert_classification(reclassified, "ORDINARY_1", 0.150, 1500.0, 250.0)

        assert_reopened(
            read_calculation(client, ctx["calculation_id"]), "HAZARD_RECLASSIFIED"
        )
        project = read_project(client, ctx["project_id"])
        assert project["governing_hydraulic_calculation_id"] is None
        assert_flow(project["governing_demand_gpm"], 0.0)
        assert_flow(project["total_system_demand_gpm"], STANDPIPE_DEMAND_GPM)

        # ISSUED is terminal, so the cascade that stales COORDINATED sheets skips it.
        assert read_shop_drawing(client, ctx["sheet_id"])["state"] == "ISSUED"

    def test_35_the_acceptance_test_cannot_freeze_thresholds_that_do_not_exist(self, client):
        """... the project must have a governing hydraulic calculation, since otherwise the
        pass thresholds are undefined and the request is refused with
        `ERR_NO_GOVERNING_CALCULATION`.

        Design: Corner/validations/reclassifying_after_the_permit_leaves_the_acceptance_thresholds_undefined
        """
        ctx = build_permitted_stage(client)
        validate_success(
            client.reclassify_hazard_area(
                ctx["hazard_area_id"],
                build_reclassify_payload(**DOWNGRADE_TO_ORDINARY_1),
                make_design_engineer_headers(ctx["lead_id"]),
            )
        )

        refused = client.create_acceptance_test(
            build_acceptance_test_payload(
                project_id=ctx["project_id"], test_type="SYSTEM_FLOW_TEST"
            ),
            CONTRACTOR_HEADERS,
        )
        validate_error(refused, "ERR_NO_GOVERNING_CALCULATION", expected_status=409)

        assert read_project(client, ctx["project_id"])["status"] == "PERMITTED"
        listed, meta = validate_paginated(
            client.list_acceptance_tests(
                CONTRACTOR_HEADERS, params={"project_id": ctx["project_id"]}
            )
        )
        assert meta["total_count"] == 0
        assert listed == []
