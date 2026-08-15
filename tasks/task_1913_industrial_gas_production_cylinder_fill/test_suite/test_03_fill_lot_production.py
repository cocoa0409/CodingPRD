"""Fill-lot production: dual-variant draw, headroom boundary, tank gating,
venting compensation, and the rework cycle (PRD §3.3, §2.10)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_tank_volume_invariants,
    complete_fill_lot,
    create_test_cylinder,
    create_test_fill_lot,
    create_test_plant,
    create_test_tank,
    get_cylinder,
    get_fill_lot,
    get_tank,
    post_telemetry,
    record_lot_analysis,
    set_logical_clock,
    setup_awaiting_analysis_lot,
    setup_failed_lot,
    setup_planned_lot,
    start_fill_lot,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
OP = TEST_USERS["production_operator_headers"]
QM = TEST_USERS["quality_manager_headers"]


# --- Difficulty: dual_variant_calc / fill_draw_provisional_vs_final_divergence ---

def test_fill_draw_provisional_estimate_and_final_actual_diverge(api):
    """PRD §3.3: "The server now computes the final variant of the fill draw:
    identical to the provisional rule except that each cylinder's measured
    residual pressure replaces the 5-bar standard. The gap matters — a lot of two
    `STANDARD` cylinders filled to a 200-bar target draws 197.0 liters
    provisionally, but 187.0 liters when each cylinder's measured residual is
    15 bar."
    PRD §3.3: "each cylinder reserved into the lot contributes its
    `water_capacity_liters` multiplied by the difference between the lot's
    `target_fill_pressure_bar` and a standard residual of 5 bar, divided by 100;
    once at least one cylinder is assigned, a line loss of 2 liters is added to
    the sum, and with no cylinders assigned the estimate is zero."

    Design: Difficulty/dual_variant_calc/fill_draw_provisional_vs_final_divergence
    """
    ctx = setup_planned_lot(num_cylinders=2)
    lot = ctx["lot"]
    assert lot["draw_estimate_liters"] == pytest.approx(197.0, abs=0.01), (
        "PROVISIONAL: 2 * 50 * (200 - 5) / 100 + 2 = 197.0"
    )
    assert lot["draw_actual_liters"] is None, "actual stays null until complete-fill"

    start_fill_lot(lot["id"])
    completed = complete_fill_lot(lot["id"], ctx["cylinders"],
                                  residual_pressure_bar=15)
    assert completed["draw_estimate_liters"] == pytest.approx(197.0, abs=0.01)
    assert completed["draw_actual_liters"] == pytest.approx(187.0, abs=0.01), (
        "FINAL: 2 * 50 * (200 - 15) / 100 + 2 = 187.0"
    )
    divergence = completed["draw_estimate_liters"] - completed["draw_actual_liters"]
    assert divergence == pytest.approx(10.0, abs=0.01), (
        "the two variants diverge by exactly 10.0 liters for 15-bar residuals"
    )


def test_complete_fill_reconciles_tank_ledger_to_final_draw(api):
    """PRD §3.3: "Completion moves the lot from `FILLING` to
    `AWAITING_ANALYSIS`, subtracts the estimated draw from the tank's
    `reserved_liters`, adds the actual draw to the tank's `drawn_liters`,
    recomputes the tank's `current_level_liters` and `low_level_flag` —
    reconciling the provisional reservation to the final actual — stores the
    actual in `draw_actual_liters`, stamps `completed_by_user_id` from the acting
    operator's header, and increments both the lot's and the tank's `version`."

    Design: Difficulty/dual_variant_calc/fill_draw_provisional_vs_final_divergence
    """
    ctx = setup_planned_lot(num_cylinders=2)
    lot, tank = ctx["lot"], ctx["tank"]
    start_fill_lot(lot["id"])
    during = get_tank(tank["id"])
    assert during["reserved_liters"] == pytest.approx(197.0, abs=0.01), (
        "start-fill reserves the provisional estimate"
    )

    complete_fill_lot(lot["id"], ctx["cylinders"], residual_pressure_bar=15)
    after = get_tank(tank["id"])
    assert after["reserved_liters"] == pytest.approx(0.0, abs=0.01), (
        "the reservation is released in full at completion"
    )
    assert after["drawn_liters"] == pytest.approx(187.0, abs=0.01)
    assert after["current_level_liters"] == pytest.approx(4813.0, abs=0.01), (
        "5000.0 initial level minus the 187.0 final draw"
    )
    assert_tank_volume_invariants(after)


# --- Difficulty: boundary_precision_check / tank_reserve_exact_equality_start_fill ---

def _setup_pinned_tank_lot(plant, pinned_level):
    """Tank whose governing reading pins current_level at `pinned_level`, plus a
    PLANNED lot with two STANDARD cylinders (estimate 197.0)."""
    tank = create_test_tank(plant["id"])
    set_logical_clock("2026-08-01T09:00:00Z")
    post_telemetry(
        {"tank_id": tank["id"], "measured_level_liters": pinned_level,
         "measured_at": "2026-08-01T08:30:00Z", "source": "MANUAL_DIP"}
    )
    cylinders = [create_test_cylinder(), create_test_cylinder()]
    lot = create_test_fill_lot(tank["id"])
    for cyl in cylinders:
        validate_success(
            api_client_assign(lot["id"], cyl["id"]), 201
        )
    return tank, lot


def api_client_assign(lot_id, cylinder_id):
    from test_helpers import api_client
    return api_client.assign_cylinder_to_lot(lot_id, {"cylinder_id": cylinder_id}, OP)


def test_start_fill_succeeds_at_exact_headroom_equality(api):
    """PRD §3.3: "the tank's `current_level_liters` minus its `reserved_liters`
    must be greater than or equal to the lot's `draw_estimate_liters` plus a
    minimum tank reserve of 100 liters, with equality allowed; otherwise the
    start is rejected with `ERR_TANK_LEVEL_TOO_LOW`."

    Design: Difficulty/boundary_precision_check/tank_reserve_exact_equality_start_fill
    """
    plant = create_test_plant(plant_name="P-BP3")
    tank, lot = _setup_pinned_tank_lot(plant, 297)
    lot_now = get_fill_lot(lot["id"])
    assert lot_now["draw_estimate_liters"] == pytest.approx(197.0, abs=0.01)

    started = validate_success(api.start_fill(lot["id"], OP), 200)
    assert started["status"] == "FILLING", "297 >= 197 + 100 exactly: equality passes"
    tank_after = get_tank(tank["id"])
    assert tank_after["reserved_liters"] == pytest.approx(197.0, abs=0.01)


def test_start_fill_rejected_one_liter_below_headroom(api):
    """PRD §3.3: "the tank's `current_level_liters` minus its `reserved_liters`
    must be greater than or equal to the lot's `draw_estimate_liters` plus a
    minimum tank reserve of 100 liters, with equality allowed; otherwise the
    start is rejected with `ERR_TANK_LEVEL_TOO_LOW`."

    Design: Difficulty/boundary_precision_check/tank_reserve_exact_equality_start_fill
    """
    plant = create_test_plant(plant_name="P-BP3B")
    tank, lot = _setup_pinned_tank_lot(plant, 296)
    res = api.start_fill(lot["id"], OP)
    validate_error(res, ApiErrorId.ERR_TANK_LEVEL_TOO_LOW.value)
    assert get_fill_lot(lot["id"])["status"] == "PLANNED", (
        "296 < 197 + 100 by one liter: the lot must not transition"
    )


# --- Difficulty: cross_entity_state_dependency / fill_start_requires_tank_in_service ---

def test_start_fill_rejected_while_tank_in_maintenance(api):
    """PRD §3.1: "while a tank is in `MAINTENANCE` or `QUARANTINED`, starting a
    fill against it is rejected with `ERR_TANK_NOT_IN_SERVICE`."
    PRD §3.3: "It requires the lot's plant to be `OPERATING` (else
    `ERR_PLANT_NOT_OPERATING`), the tank to be `IN_SERVICE` (else
    `ERR_TANK_NOT_IN_SERVICE`), at least one cylinder `RESERVED` into the lot
    (else `ERR_LOT_HAS_NO_CYLINDERS`), and sufficient headroom: the tank's
    `current_level_liters` minus its `reserved_liters` must be greater than or
    equal to the lot's `draw_estimate_liters` plus a minimum tank reserve of 100
    liters, with equality allowed; otherwise the start is rejected with
    `ERR_TANK_LEVEL_TOO_LOW`."

    Design: Difficulty/cross_entity_state_dependency/fill_start_requires_tank_in_service
    """
    ctx = setup_planned_lot(num_cylinders=1)
    lot, tank = ctx["lot"], ctx["tank"]
    moved = validate_success(
        api.set_tank_status(tank["id"], {"target_status": "MAINTENANCE"}, PM), 200
    )
    assert moved["status"] == "MAINTENANCE"

    res = api.start_fill(lot["id"], OP)
    validate_error(res, ApiErrorId.ERR_TANK_NOT_IN_SERVICE.value)
    assert get_fill_lot(lot["id"])["status"] == "PLANNED"


def test_start_fill_succeeds_after_tank_returns_to_service(api):
    """PRD §3.1: "Returning to `IN_SERVICE` from either state is always
    permitted, and every transition increments the tank's `version`."
    PRD §3.3: "On success the lot moves from `PLANNED` to `FILLING`, the tank's
    `reserved_liters` increases by the estimated draw, `low_level_flag` is
    recomputed, and both the lot's and the tank's `version` increment."

    Design: Difficulty/cross_entity_state_dependency/fill_start_requires_tank_in_service
    """
    ctx = setup_planned_lot(num_cylinders=1)
    lot, tank = ctx["lot"], ctx["tank"]
    validate_success(
        api.set_tank_status(tank["id"], {"target_status": "MAINTENANCE"}, PM), 200
    )
    back = validate_success(
        api.set_tank_status(tank["id"], {"target_status": "IN_SERVICE"}, PM), 200
    )
    assert back["status"] == "IN_SERVICE"

    started = validate_success(api.start_fill(lot["id"], OP), 200)
    assert started["status"] == "FILLING", (
        "the identical request succeeds once the tank is back in service"
    )
    assert get_tank(tank["id"])["reserved_liters"] == pytest.approx(99.5, abs=0.01)


# --- Difficulty: compensating_invariant / tank_reserve_then_vent_volume_conserved ---

def test_reserve_then_vent_restores_tank_volume(api):
    """PRD §2.10: "Starting a fill reserves the estimated draw against the tank's
    `reserved_liters`; completing a fill releases that reservation in full and
    adds the measured actual draw to `drawn_liters`; venting a lot undoes
    whatever the lot had done — restoring the reservation in full when the fill
    had only started, or subtracting the actual draw back out of `drawn_liters`
    when the fill had completed."
    PRD §3.3: "a lot vented from `FILLING` has the full estimated draw subtracted
    back out of the tank's `reserved_liters`, restoring the reservation exactly"

    Design: Difficulty/compensating_invariant/tank_reserve_then_vent_volume_conserved
    """
    ctx = setup_planned_lot(num_cylinders=2)
    lot, tank, cylinders = ctx["lot"], ctx["tank"], ctx["cylinders"]
    start_fill_lot(lot["id"])
    during = get_tank(tank["id"])
    assert during["reserved_liters"] == pytest.approx(197.0, abs=0.01)

    vented = validate_success(api.vent_fill_lot(lot["id"], OP), 200)
    assert vented["status"] == "VENTED"
    after = get_tank(tank["id"])
    assert after["current_level_liters"] == pytest.approx(5000.0, abs=0.01)
    assert after["reserved_liters"] == pytest.approx(0.0, abs=0.01)
    assert after["drawn_liters"] == pytest.approx(0.0, abs=0.01)
    assert_tank_volume_invariants(after)
    for cyl in cylinders:
        back = get_cylinder(cyl["id"])
        assert back["status"] == "IN_STOCK"
        assert back["current_fill_lot_id"] is None


def test_complete_then_vent_reverses_drawn_volume(api):
    """PRD §3.3: "a lot vented from `AWAITING_ANALYSIS` or from
    `ANALYSIS_FAILED` has the actual draw subtracted back out of the tank's
    `drawn_liters`, reversing the physical draw, with `current_level_liters` and
    `low_level_flag` recomputed. In every case the lot's linked cylinders —
    `RESERVED` ones, or `QUARANTINED` ones when the lot had failed — return to
    `IN_STOCK` with their `current_fill_lot_id` cleared."
    PRD §2.10: "Under every path, the liquid a tank is accountable for is exactly
    its latest telemetry level minus the physical draws not yet reflected in a
    newer reading."

    Design: Difficulty/compensating_invariant/tank_reserve_then_vent_volume_conserved
    """
    ctx = setup_awaiting_analysis_lot(num_cylinders=2, residual_pressure_bar=15)
    lot, tank, cylinders = ctx["lot"], ctx["tank"], ctx["cylinders"]
    mid = get_tank(tank["id"])
    assert mid["drawn_liters"] == pytest.approx(187.0, abs=0.01)
    assert mid["current_level_liters"] == pytest.approx(4813.0, abs=0.01)

    vented = validate_success(api.vent_fill_lot(lot["id"], OP), 200)
    assert vented["status"] == "VENTED"
    after = get_tank(tank["id"])
    assert after["drawn_liters"] == pytest.approx(0.0, abs=0.01), (
        "the 187.0-liter physical draw is fully reversed"
    )
    assert after["reserved_liters"] == pytest.approx(0.0, abs=0.01)
    assert after["current_level_liters"] == pytest.approx(5000.0, abs=0.01)
    assert_tank_volume_invariants(after)
    for cyl in cylinders:
        back = get_cylinder(cyl["id"])
        assert back["status"] == "IN_STOCK"
        assert back["current_fill_lot_id"] is None


# --- Difficulty: non_linear_state_machine / fill_lot_rework_cycle_reentry ---

def test_failed_lot_rework_returns_cylinders_to_reserved(api):
    """PRD §3.4: "A `FAIL` moves a fill lot to `ANALYSIS_FAILED` and drives every
    cylinder reserved into it to `QUARANTINED` with the lot link kept so that
    rework can find them, or moves a blend order to `REWORK`."
    PRD §3.3: "The rework action requires the lot to be `ANALYSIS_FAILED` (else
    `ERR_FILL_LOT_INVALID_STATE`) and the plant to be `OPERATING` (else
    `ERR_PLANT_NOT_OPERATING`); it returns the lot to `FILLING` and moves every
    cylinder still linked to the lot through `current_fill_lot_id` from
    `QUARANTINED` back to `RESERVED`."

    Design: Difficulty/non_linear_state_machine/fill_lot_rework_cycle_reentry
    """
    ctx = setup_failed_lot(num_cylinders=1)
    lot, cyl = ctx["lot"], ctx["cylinders"][0]
    assert lot["status"] == "ANALYSIS_FAILED"
    assert cyl["status"] == "QUARANTINED"
    assert cyl["current_fill_lot_id"] == lot["id"], "the lot link is kept for rework"

    reworked = validate_success(api.rework_fill_lot(lot["id"], OP), 200)
    assert reworked["status"] == "FILLING", "the cycle re-enters FILLING"
    cyl_after = get_cylinder(cyl["id"])
    assert cyl_after["status"] == "RESERVED"
    assert cyl_after["current_fill_lot_id"] == lot["id"]


def test_reworked_lot_releases_on_second_pass(api):
    """PRD §3.3: "No tank re-reservation occurs: the failed fill's liquid stays
    drawn, and the rework re-pressurizes the same cylinders."
    PRD §3.4: "A `PASS` releases the subject: a fill lot moves from
    `AWAITING_ANALYSIS` to `RELEASED`, and every cylinder reserved into it
    becomes `FILLED` with its `current_fill_lot_id` cleared and its
    `last_fill_lot_id` stamped with the lot's identity as permanent provenance —
    that provenance is set at release and never cleared, and it is what recall
    targeting later reads."

    Design: Difficulty/non_linear_state_machine/fill_lot_rework_cycle_reentry
    """
    ctx = setup_failed_lot(num_cylinders=1)
    lot, cyl = ctx["lot"], ctx["cylinders"][0]
    validate_success(api.rework_fill_lot(lot["id"], OP), 200)
    complete_fill_lot(lot["id"], [cyl], residual_pressure_bar=15)
    analysis = record_lot_analysis(lot["id"],
                                   readings=[{"analyte": "CO", "reading_ppm": 5}])
    assert analysis["result"] == "PASS"

    lot_after = get_fill_lot(lot["id"])
    assert lot_after["status"] == "RELEASED"
    cyl_after = get_cylinder(cyl["id"])
    assert cyl_after["status"] == "FILLED"
    assert cyl_after["current_fill_lot_id"] is None
    assert cyl_after["last_fill_lot_id"] == lot["id"], "release stamps provenance"


# --- Corner: errors / error_lot_has_no_cylinders_triggerable ---

def test_start_fill_with_no_cylinders_rejected(api):
    """PRD §3.3: "It requires the lot's plant to be `OPERATING` (else
    `ERR_PLANT_NOT_OPERATING`), the tank to be `IN_SERVICE` (else
    `ERR_TANK_NOT_IN_SERVICE`), at least one cylinder `RESERVED` into the lot
    (else `ERR_LOT_HAS_NO_CYLINDERS`), and sufficient headroom: the tank's
    `current_level_liters` minus its `reserved_liters` must be greater than or
    equal to the lot's `draw_estimate_liters` plus a minimum tank reserve of 100
    liters, with equality allowed; otherwise the start is rejected with
    `ERR_TANK_LEVEL_TOO_LOW`."

    Design: Corner/errors/error_lot_has_no_cylinders_triggerable
    """
    plant, tank = create_test_plant(plant_name="P-ER1"), None
    tank = create_test_tank(plant["id"])
    lot = create_test_fill_lot(tank["id"])
    res = api.start_fill(lot["id"], OP)
    validate_error(res, ApiErrorId.ERR_LOT_HAS_NO_CYLINDERS.value)
    assert get_fill_lot(lot["id"])["status"] == "PLANNED"
    assert get_tank(tank["id"])["reserved_liters"] == pytest.approx(0.0, abs=0.01)


# --- Corner: errors / error_product_service_mismatch_triggerable ---

def test_assign_cylinder_with_mismatched_service_gas_rejected(api):
    """PRD §3.3: "Assignment is refused with `ERR_FILL_LOT_INVALID_STATE` when
    the lot is not `PLANNED`, with `ERR_CYLINDER_NOT_AVAILABLE` when the cylinder
    is not `IN_STOCK`, with `ERR_HYDRO_RETEST_OVERDUE` when the cylinder is
    hydro-overdue at the clock date, and with `ERR_PRODUCT_SERVICE_MISMATCH` when
    the cylinder's `service_gas` differs from the lot's `product_code`."

    Design: Corner/errors/error_product_service_mismatch_triggerable
    """
    plant = create_test_plant(plant_name="P-ER2")
    tank = create_test_tank(plant["id"], product_code="O2")
    cyl = create_test_cylinder(serial_number="SN-ER2-A", service_gas="N2")
    lot = create_test_fill_lot(tank["id"], product_code="O2")
    res = api.assign_cylinder_to_lot(lot["id"], {"cylinder_id": cyl["id"]}, OP)
    validate_error(res, ApiErrorId.ERR_PRODUCT_SERVICE_MISMATCH.value)
    assert get_cylinder(cyl["id"])["status"] == "IN_STOCK"


# --- Corner: state_machines / complete_fill_from_planned_rejected ---

def test_complete_fill_from_planned_rejected(api):
    """PRD §3.3: "The plant must be `OPERATING` and the lot must be `FILLING`,
    else the request is rejected with `ERR_PLANT_NOT_OPERATING` or
    `ERR_FILL_LOT_INVALID_STATE` respectively."

    Design: Corner/state_machines/complete_fill_from_planned_rejected
    """
    ctx = setup_planned_lot(num_cylinders=1)
    lot, tank, cyl = ctx["lot"], ctx["tank"], ctx["cylinders"][0]
    res = api.complete_fill(
        lot["id"],
        {"measured_residuals": [{"cylinder_id": cyl["id"], "residual_pressure_bar": 15}]},
        OP,
    )
    validate_error(res, ApiErrorId.ERR_FILL_LOT_INVALID_STATE.value)
    assert get_fill_lot(lot["id"])["status"] == "PLANNED"
    assert get_tank(tank["id"])["reserved_liters"] == pytest.approx(0.0, abs=0.01)


# --- Corner: state_machines / vented_lot_terminal_lockdown ---

def test_vented_lot_rejects_rework_start_fill_and_recall(api):
    """PRD §3.3: "A lot may be vented from `PLANNED`, `FILLING`,
    `AWAITING_ANALYSIS`, or `ANALYSIS_FAILED` — from any other state the request
    is rejected with `ERR_FILL_LOT_INVALID_STATE` — and venting is terminal,
    landing the lot in `VENTED`."
    PRD §3.3: "The rework action requires the lot to be `ANALYSIS_FAILED` (else
    `ERR_FILL_LOT_INVALID_STATE`)"
    PRD §3.3: "A released lot can later be recalled by a `QualityManager`; the
    lot must be `RELEASED`, otherwise the recall is rejected with
    `ERR_FILL_LOT_INVALID_STATE`."

    Design: Corner/state_machines/vented_lot_terminal_lockdown
    """
    ctx = setup_planned_lot(num_cylinders=1)
    lot, cyl = ctx["lot"], ctx["cylinders"][0]
    start_fill_lot(lot["id"])
    vented = validate_success(api.vent_fill_lot(lot["id"], OP), 200)
    assert vented["status"] == "VENTED"

    for trigger in (
        lambda: api.rework_fill_lot(lot["id"], OP),
        lambda: api.start_fill(lot["id"], OP),
        lambda: api.recall_fill_lot(lot["id"], QM),
    ):
        validate_error(trigger(), ApiErrorId.ERR_FILL_LOT_INVALID_STATE.value)

    assert get_fill_lot(lot["id"])["status"] == "VENTED", "VENTED is terminal"
    cyl_after = get_cylinder(cyl["id"])
    assert cyl_after["status"] == "IN_STOCK"
    assert cyl_after["current_fill_lot_id"] is None
