"""The arithmetic of the wire and the furnace.

This module exercises the numbers the plant computes rather than the states it moves
through: the drawing-reduction acceptance band and the lubricant floor that gate a
wire lot's release, the wire mass ledger settling a lot's reservation against what
heading actually consumed, the half-up rounding of kilogram amounts to three decimal
places, which of a lot's three piece counts the furnace charge is weighed from, and
how a lean carburising atmosphere amplifies the coupon's measured decarburisation
depth before the hardness-first conformance verdict is reached. Every expectation
below is read off PRD §2.6, §2.8, §3.2, §3.4 and §3.5.
"""

from datetime import datetime

import pytest

from test_helpers import (
    ApiErrorId,
    assert_lot_piece_ledger,
    assert_wire_mass_ledger,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

# The logical clock instant every chain below starts from.
CLOCK = "2026-09-01T06:00:00Z"

# The unplated reference part: 20.0 g blanks, a 0.05 scrap allowance, the
# 304..361 HV window and a 0.100 mm decarburisation ceiling.
REFERENCE_SPEC = {
    "part_number": "NP-M8-088",
    "blank_mass_g": 20.0,
    "scrap_allowance_pct": 0.05,
    "min_core_hardness_hv": 304,
    "max_core_hardness_hv": 361,
    "max_decarb_depth_mm": 0.100,
}


def _same_instant(actual: str, expected: str) -> bool:
    """Compare two ISO 8601 UTC instants, ignoring fractional-second formatting."""
    if not actual:
        return False
    parse = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
    return parse(actual) == parse(expected)


def _reference_environment(**overrides):
    """Part spec + VERIFIED heat + RELEASED 500 kg wire + MOUNTED die set + furnace."""
    spec_overrides = dict(REFERENCE_SPEC)
    spec_overrides.update(overrides.pop("spec_overrides", {}))
    return fixtures.setup_master_data(
        clock=CLOCK,
        unplated=True,
        spec_overrides=spec_overrides,
        wire_overrides={
            "inlet_diameter_mm": 8.00,
            "outlet_diameter_mm": 6.80,
            "lubricant_coating": "PHOSPHATE",
            "coating_weight_gsm": 4.5,
            "gross_mass_kg": 500.0,
        },
        tool_overrides={"tool_code": "DIE-4S-001", "rated_life_pieces": 120000},
        furnace_overrides={"furnace_code": "FCE-1", "max_charge_mass_kg": 400.0},
        **overrides,
    )


# ---------------------------------------------------------------------------
# Wire release: the drawing-reduction band and the lubricant floor
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "outlet_diameter_mm,stored_reduction_pct,expected_error",
    [
        pytest.param(
            7.80, 4.94, ApiErrorId.ERR_DRAW_REDUCTION_OUT_OF_RANGE.value, id="too_light_4_94"
        ),
        pytest.param(
            6.00, 43.75, ApiErrorId.ERR_DRAW_REDUCTION_OUT_OF_RANGE.value, id="too_heavy_43_75"
        ),
        pytest.param(7.60, 9.75, None, id="inside_band_9_75"),
        pytest.param(7.6734, 8.00, None, id="exactly_the_8_00_floor"),
        pytest.param(6.4497, 35.00, None, id="exactly_the_35_00_ceiling"),
    ],
)
def test_wire_release_gates_on_the_rounded_area_reduction_band(
    api, inspector_headers, outlet_diameter_mm, stored_reduction_pct, expected_error
):
    """A wire lot releases only when its stored reduction_pct sits inside 8.00..35.00 inclusive.

    Drawn from 8.00 mm, an outlet of 7.80 mm is an area reduction of 4.94 percent (a
    diameter-based reading would say 2.50) and is too light; 6.00 mm is 43.75 and too
    heavy; 7.60 mm is 9.75 and releases. The two boundary coils store exactly 8.00 and
    exactly 35.00 even though their unrounded intermediates fall the wrong side of the
    limit, and both release because the band is compared against the stored value.

    PRD: "The server derives `reduction_pct` from the diameters: divide the outlet diameter by the inlet diameter, square that ratio to get the surviving cross-sectional area fraction, subtract it from one, multiply by one hundred, and round the result half up to two decimal places."

    PRD: "The drawing must have been neither too gentle nor too aggressive: the stored, already-rounded `reduction_pct` must be at least 8.0 and at most 35.0 — both bounds inclusive, so exactly 8.00 and exactly 35.00 both pass — or the release is refused with `ERR_DRAW_REDUCTION_OUT_OF_RANGE`."

    PRD: "**Drawing reduction** (`reduction_pct`) is stored to 2 decimal places, and every comparison against the acceptance band is made on the rounded stored value, never on the unrounded intermediate."

    Design: Corner/calculations/draw_reduction_gate_uses_both_inclusive_bounds
    """
    fixtures.set_clock(CLOCK)
    heat = fixtures.create_verified_heat()
    wire = fixtures.register_wire_lot(
        heat["id"],
        draw_pass_count=3,
        inlet_diameter_mm=8.00,
        outlet_diameter_mm=outlet_diameter_mm,
        lubricant_coating="PHOSPHATE",
        coating_weight_gsm=4.5,
        gross_mass_kg=100.0,
    )
    assert wire["reduction_pct"] == pytest.approx(stored_reduction_pct, abs=0.0005), (
        f"Expected reduction_pct {stored_reduction_pct} for 8.00 -> "
        f"{outlet_diameter_mm} mm, got {wire['reduction_pct']}"
    )
    assert wire["status"] == "DRAWN", f"A fresh wire lot starts DRAWN, got {wire['status']}"

    response = api.release_wire_lot(wire["id"], inspector_headers)

    if expected_error is not None:
        validate_error(response, expected_error)
        after = fixtures.read_wire_lot(wire["id"])
        assert after["status"] == "DRAWN", (
            f"A refused release must leave the lot DRAWN, got {after['status']}"
        )
        assert after.get("inspected_at") in (None, ""), (
            f"A refused release must not stamp inspected_at, got {after.get('inspected_at')}"
        )
        assert after["version"] == wire["version"], (
            f"A refused release mutates nothing, so version stays {wire['version']}, "
            f"got {after['version']}"
        )
    else:
        released = validate_success(response)
        assert released["status"] == "RELEASED", (
            f"Expected RELEASED for a stored reduction_pct of {stored_reduction_pct}, "
            f"got {released['status']}"
        )
        assert _same_instant(released["inspected_at"], CLOCK), (
            f"Expected inspected_at stamped at {CLOCK}, got {released['inspected_at']}"
        )
        assert released["version"] == wire["version"] + 1, (
            f"Expected version {wire['version'] + 1} after release, got {released['version']}"
        )
        assert released["reduction_pct"] == pytest.approx(stored_reduction_pct, abs=0.0005), (
            "Releasing must not re-derive reduction_pct"
        )
        assert_wire_mass_ledger(released)


@pytest.mark.parametrize(
    "lubricant_coating,coating_weight_gsm,expected_error",
    [
        pytest.param(
            "NONE", 5.0, ApiErrorId.ERR_LUBRICATION_INSUFFICIENT.value, id="uncoated_heavy_film"
        ),
        pytest.param(
            "PHOSPHATE", 1.5, ApiErrorId.ERR_LUBRICATION_INSUFFICIENT.value, id="below_the_floor"
        ),
        pytest.param("PHOSPHATE", 2.0, None, id="exactly_the_2_0_gsm_floor"),
    ],
)
def test_wire_release_requires_a_coating_of_at_least_two_gsm(
    api, inspector_headers, lubricant_coating, coating_weight_gsm, expected_error
):
    """Lubrication is two tests: a coating other than NONE, and a film of at least 2.0 gsm.

    All three coils are drawn 8.00 -> 6.80 mm, so each stores a reduction_pct of 27.75
    and the drawing band decides none of the three outcomes. An uncoated coil fails
    however heavy its film, a phosphated coil at 1.5 gsm fails, and a phosphated coil at
    exactly 2.0 gsm releases.

    PRD: "The wire must actually be lubricated: `lubricant_coating` must be something other than `NONE` and `coating_weight_gsm` must be at least 2.0 grams per square metre, or the release is refused with `ERR_LUBRICATION_INSUFFICIENT`."

    PRD: "On success the lot moves `DRAWN → RELEASED`, `inspected_at` is stamped from the logical clock, and the lot's `version` increments by 1."

    Design: Corner/calculations/lubrication_floor_of_two_gsm_is_inclusive
    """
    fixtures.set_clock(CLOCK)
    heat = fixtures.create_verified_heat()
    wire = fixtures.register_wire_lot(
        heat["id"],
        draw_pass_count=3,
        inlet_diameter_mm=8.00,
        outlet_diameter_mm=6.80,
        lubricant_coating=lubricant_coating,
        coating_weight_gsm=coating_weight_gsm,
        gross_mass_kg=100.0,
    )
    assert wire["reduction_pct"] == pytest.approx(27.75, abs=0.0005), (
        f"8.00 -> 6.80 mm is a reduction_pct of 27.75, got {wire['reduction_pct']}"
    )

    response = api.release_wire_lot(wire["id"], inspector_headers)

    if expected_error is not None:
        validate_error(response, expected_error)
        after = fixtures.read_wire_lot(wire["id"])
        assert after["status"] == "DRAWN", (
            f"A refused release must leave the lot DRAWN, got {after['status']}"
        )
        assert after.get("inspected_at") in (None, ""), (
            f"A refused release must not stamp inspected_at, got {after.get('inspected_at')}"
        )
        assert after["version"] == wire["version"], (
            f"A refused release mutates nothing, so version stays {wire['version']}, "
            f"got {after['version']}"
        )
    else:
        released = validate_success(response)
        assert released["status"] == "RELEASED", (
            f"A coating of exactly 2.0 gsm must release, got {released['status']}"
        )
        assert _same_instant(released["inspected_at"], CLOCK), (
            f"Expected inspected_at stamped at {CLOCK}, got {released['inspected_at']}"
        )
        assert released["version"] == wire["version"] + 1, (
            f"Expected version {wire['version'] + 1} after release, got {released['version']}"
        )


# ---------------------------------------------------------------------------
# The wire mass ledger
# ---------------------------------------------------------------------------
def test_heading_completion_settles_the_reservation_against_actual_consumption(
    api, engineer_headers
):
    """Reservation carries the scrap allowance; consumption does not, and the difference returns.

    A lot of 5000 planned 20.0 g pieces reserves 5000 * 20.0 * 1.05 / 1000 == 105.000 kg,
    while heading 4900 good plus 60 spoiled pieces burns only (4900 + 60) * 20.0 / 1000 ==
    99.200 kg, so 5.800 kg goes back to available_mass_kg — 400.800 — and the conserved
    identity 500.000 == 400.800 + 0.000 + 99.200 still holds.

    PRD: "The required mass is `planned_pieces` multiplied by the part's `blank_mass_g`, multiplied by one plus `scrap_allowance_pct`, divided by 1000 to convert grams to kilograms, and rounded half up to three decimal places."

    PRD: "The wire ledger settles: the actually consumed mass is the sum of the two reported counts multiplied by `blank_mass_g`, divided by 1000, rounded half up to three decimal places; the lot's original `wire_reserved_kg` is subtracted from the wire lot's `reserved_mass_kg`, the consumed mass is added to `consumed_mass_kg`, and the difference between the reservation and the consumption is added back to `available_mass_kg` — which will be negative when the lot over-consumed."

    PRD: "For every wire lot, the mass received from the mill equals the mass still free, plus the mass reserved by lots in setup, plus the mass already burned into blanks: `gross_mass_kg` equals `available_mass_kg` plus `reserved_mass_kg` plus `consumed_mass_kg`."

    PRD: "The lot then snapshots its own wear picture as `tool_utilization_pct`, which is 100 multiplied by the set's new `cumulative_pieces_current_cycle`, divided by its `rated_derated_life_pieces`, rounded half up to two decimal places — note that wear is always measured against the *rated derated* budget, never against the conservative one, whatever the part's qualification programme."

    Design: Corner/calculations/wire_ledger_settles_reservation_against_actual_consumption
    """
    env = _reference_environment()
    lot = fixtures.open_production_lot(
        env["spec"]["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        press_code=env["press_code"],
        lot_code="L-2601",
        planned_pieces=5000,
    )
    assert lot["wire_reserved_kg"] == pytest.approx(105.000, abs=0.0005), (
        f"Expected a reservation of 105.000 kg, got {lot['wire_reserved_kg']}"
    )

    wire_before = fixtures.read_wire_lot(env["wire"]["id"])
    assert wire_before["reserved_mass_kg"] == pytest.approx(105.000, abs=0.0005), (
        f"Expected 105.000 kg reserved, got {wire_before['reserved_mass_kg']}"
    )
    assert wire_before["available_mass_kg"] == pytest.approx(395.000, abs=0.0005), (
        f"Expected 395.000 kg available, got {wire_before['available_mass_kg']}"
    )
    assert wire_before["consumed_mass_kg"] == pytest.approx(0.000, abs=0.0005), (
        f"Nothing is consumed before heading, got {wire_before['consumed_mass_kg']}"
    )
    assert_wire_mass_ledger(wire_before)

    headed = validate_success(
        api.complete_heading(
            lot["id"], {"headed_count": 4900, "heading_scrap_count": 60}, engineer_headers
        )
    )

    assert headed["wire_consumed_kg"] == pytest.approx(99.200, abs=0.0005), (
        f"Expected 99.200 kg consumed by 4960 blanks, got {headed['wire_consumed_kg']}"
    )
    assert headed["wire_reserved_kg"] == pytest.approx(0.000, abs=0.0005), (
        f"The reservation drops to zero at heading, got {headed['wire_reserved_kg']}"
    )
    assert headed["tool_utilization_pct"] == pytest.approx(4.13, abs=0.005), (
        f"Expected tool_utilization_pct 4.13 for 4960 of 120000 pieces, "
        f"got {headed['tool_utilization_pct']}"
    )
    assert_lot_piece_ledger(headed)

    wire_after = fixtures.read_wire_lot(env["wire"]["id"])
    assert wire_after["consumed_mass_kg"] == pytest.approx(99.200, abs=0.0005), (
        f"Expected consumed_mass_kg 99.200, got {wire_after['consumed_mass_kg']}"
    )
    assert wire_after["reserved_mass_kg"] == pytest.approx(0.000, abs=0.0005), (
        f"Expected reserved_mass_kg 0.000, got {wire_after['reserved_mass_kg']}"
    )
    assert wire_after["available_mass_kg"] == pytest.approx(400.800, abs=0.0005), (
        f"Expected the 5.800 kg allowance back, giving 400.800, "
        f"got {wire_after['available_mass_kg']}"
    )
    assert wire_after["gross_mass_kg"] == pytest.approx(500.000, abs=0.0005), (
        f"gross_mass_kg never moves, got {wire_after['gross_mass_kg']}"
    )
    assert_wire_mass_ledger(wire_after)
    assert wire_after["version"] == wire_before["version"] + 1, (
        f"Expected wire lot version {wire_before['version'] + 1} after the settlement, "
        f"got {wire_after['version']}"
    )

    tool = fixtures.read_tool(env["tool"]["id"])
    assert tool["cumulative_pieces_current_cycle"] == 4960, (
        f"Expected 4960 pieces on the open cycle, "
        f"got {tool['cumulative_pieces_current_cycle']}"
    )


def test_kilogram_amounts_are_rounded_half_up_to_three_decimals(api, heat_treat_headers):
    """A charge mass landing exactly on a half at the fourth decimal rounds up, not down.

    With 20.5 g blanks the reservation 5000 * 20.5 * 1.05 / 1000 == 107.625 kg and the
    consumption 4960 * 20.5 / 1000 == 101.680 kg are both exact, but a furnace charge of
    4851 pieces is 99.4455 kg, which must store as 99.446 — a truncating or
    round-half-even implementation would store 99.445.

    PRD: "All rounding in this system is **round half up** — a value exactly at the midpoint rounds away from zero."

    PRD: "**Mass in kilograms** is stored to 3 decimal places."

    PRD: "The run's `charge_mass_kg` is derived, not supplied: it is the lot's `available_count` multiplied by the part's `blank_mass_g`, divided by 1000, rounded half up to three decimal places, and it may not exceed the furnace's `max_charge_mass_kg` — the comparison is inclusive, so a charge exactly at capacity is accepted, and anything heavier is refused with `ERR_FURNACE_CAPACITY_EXCEEDED`."

    Design: Corner/calculations/kilogram_amounts_round_half_up_to_three_decimals
    """
    env = _reference_environment(
        spec_overrides={"part_number": "NP-M8-205", "blank_mass_g": 20.5}
    )
    lot = fixtures.open_production_lot(
        env["spec"]["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        press_code=env["press_code"],
        lot_code="L-2605",
        planned_pieces=5000,
    )
    assert lot["wire_reserved_kg"] == pytest.approx(107.625, abs=0.0005), (
        f"Expected a reservation of 107.625 kg for 20.5 g blanks, "
        f"got {lot['wire_reserved_kg']}"
    )

    fixtures.report_heading(lot["id"], 4900, 60)
    wire = fixtures.read_wire_lot(env["wire"]["id"])
    assert wire["consumed_mass_kg"] == pytest.approx(101.680, abs=0.0005), (
        f"Expected consumed_mass_kg 101.680, got {wire['consumed_mass_kg']}"
    )
    assert wire["available_mass_kg"] == pytest.approx(398.320, abs=0.0005), (
        f"Expected available_mass_kg 398.320, got {wire['available_mass_kg']}"
    )
    assert wire["gross_mass_kg"] == pytest.approx(500.000, abs=0.0005), (
        f"gross_mass_kg never moves, got {wire['gross_mass_kg']}"
    )
    assert_wire_mass_ledger(wire)

    fixtures.run_secondary_op(lot["id"], op_type="THREAD_ROLL", sequence_no=1, pieces_out=4851)

    run = validate_success(
        api.create_heat_treat_run(
            factories.create_heat_treat_run_payload(
                lot["id"],
                env["furnace"]["id"],
                window_start_at="2026-09-01T18:00:00Z",
                window_end_at="2026-09-01T23:00:00Z",
                carbon_potential_pct=0.42,
            ),
            heat_treat_headers,
        ),
        201,
    )
    assert run["charge_mass_kg"] == pytest.approx(99.446, abs=0.0005), (
        f"4851 * 20.5 / 1000 == 99.4455 must store as 99.446, got {run['charge_mass_kg']}"
    )


# ---------------------------------------------------------------------------
# The furnace charge and the metallurgical verdict
# ---------------------------------------------------------------------------
def test_furnace_charge_is_weighed_from_available_count(api, heat_treat_headers):
    """The charge reads what is actually going into the basket, not what was planned or headed.

    The lot planned 5000 pieces, headed 4900 and came out of thread rolling with 4850
    available, so the charge is 4850 * 20.0 / 1000 == 97.000 kg — a run reading
    planned_pieces would book 100.000 and one reading headed_count 98.000. Booking the
    window does not occupy the furnace.

    PRD: "The run's `charge_mass_kg` is derived, not supplied: it is the lot's `available_count` multiplied by the part's `blank_mass_g`, divided by 1000, rounded half up to three decimal places, and it may not exceed the furnace's `max_charge_mass_kg` — the comparison is inclusive, so a charge exactly at capacity is accepted, and anything heavier is refused with `ERR_FURNACE_CAPACITY_EXCEEDED`."

    PRD: "A booked run begins in `status` `PLANNED` with `started_at`, `completed_at`, `core_hardness_hv`, `surface_decarb_depth_mm`, `total_decarb_depth_mm` all empty and `result` of `PENDING`; booking does not occupy the furnace."

    Design: Corner/calculations/heat_treat_charge_reads_available_count_not_planned_or_headed
    """
    env = _reference_environment()
    env = fixtures.setup_secondary_done_lot(
        env=env,
        planned_pieces=5000,
        headed_count=4900,
        heading_scrap_count=60,
        lot_overrides={"lot_code": "L-2601"},
        ops=[
            {
                "op_type": "THREAD_ROLL",
                "sequence_no": 1,
                "pieces_out": 4850,
                "machine_code": "TR-1",
            }
        ],
    )
    lot = env["lot"]
    assert lot["available_count"] == 4850, (
        f"Thread rolling leaves 4850 available, got {lot['available_count']}"
    )
    assert lot["headed_count"] == 4900, (
        f"headed_count stays 4900, got {lot['headed_count']}"
    )
    assert lot["planned_pieces"] == 5000, (
        f"planned_pieces stays 5000, got {lot['planned_pieces']}"
    )

    run = validate_success(
        api.create_heat_treat_run(
            factories.create_heat_treat_run_payload(
                lot["id"],
                env["furnace"]["id"],
                window_start_at="2026-09-01T18:00:00Z",
                window_end_at="2026-09-01T23:00:00Z",
                carbon_potential_pct=0.42,
            ),
            heat_treat_headers,
        ),
        201,
    )

    assert run["charge_mass_kg"] == pytest.approx(97.000, abs=0.0005), (
        f"Expected 4850 * 20.0 / 1000 == 97.000 kg, got {run['charge_mass_kg']}"
    )
    assert run["status"] == "PLANNED", (
        f"A booked run starts PLANNED, got {run['status']}"
    )
    assert run["result"] == "PENDING", (
        f"A booked run starts with result PENDING, got {run['result']}"
    )
    assert run["production_lot_id"] == lot["id"], (
        "One run charges exactly one lot"
    )

    furnace = fixtures.read_furnace(env["furnace"]["id"])
    assert furnace["status"] == "IDLE", (
        f"Booking a run does not occupy the furnace, got {furnace['status']}"
    )


def test_lean_atmosphere_amplifies_the_measured_decarburisation_depth(api, inspector_headers):
    """Identical coupons diverge on carbon potential alone: 0.42 passes, 0.30 fails on decarb.

    Both coupons measure a surface loss of 0.085 mm against a 0.100 mm ceiling. The run
    held at a carbon potential of 0.42 contributes no carbon deficit, so its
    total_decarb_depth_mm stays 0.085 and the run passes. The run held at 0.30 carries a
    deficit of 0.100, which amplifies the same measurement to 0.085 * 1.2 == 0.102 —
    strictly greater than the ceiling — and fails with FAIL_DECARB, freezing its lot.

    PRD: "The carbon deficit is the greater of 0 and 0.40 minus the run's `carbon_potential_pct` — so an atmosphere whose carbon potential is at or above 0.40 contributes no deficit at all."

    PRD: "`total_decarb_depth_mm` is then the measured `surface_decarb_depth_mm` multiplied by one plus 2.0 multiplied by that deficit, rounded half up to three decimal places."

    PRD: "Otherwise, if `total_decarb_depth_mm` is strictly greater than the part's `max_decarb_depth_mm`, the `result` is `FAIL_DECARB`; a depth exactly equal to the limit passes."

    PRD: "On `PASS`, the lot's `heat_treat_completed` flag becomes true and the lot moves `SECONDARY_DONE → HEAT_TREATED`."

    PRD: "On either `FAIL_HARDNESS` or `FAIL_DECARB`, the lot's `disposition` moves to `HOLD` with `hold_source` of `HT_FAILURE` while its `process_state` stays exactly where it was."

    Design: Corner/calculations/lean_atmosphere_amplifies_the_measured_decarb_depth
    """
    env = _reference_environment()
    env = fixtures.setup_secondary_done_lot(
        env=env,
        lot_overrides={
            "lot_code": "L-2601",
            "press_window_start_at": "2026-09-01T06:00:00Z",
            "press_window_end_at": "2026-09-01T08:00:00Z",
        },
    )
    rich_lot = env["lot"]
    env = fixtures.setup_secondary_done_lot(
        env=env,
        lot_overrides={
            "lot_code": "L-2602",
            "press_window_start_at": "2026-09-01T08:00:00Z",
            "press_window_end_at": "2026-09-01T10:00:00Z",
        },
    )
    lean_lot = env["lot"]

    rich_run = fixtures.book_heat_treat(
        rich_lot["id"],
        env["furnace"]["id"],
        window_start_at="2026-09-01T18:00:00Z",
        window_end_at="2026-09-01T20:00:00Z",
        carbon_potential_pct=0.42,
    )
    lean_run = fixtures.book_heat_treat(
        lean_lot["id"],
        env["furnace"]["id"],
        window_start_at="2026-09-01T21:00:00Z",
        window_end_at="2026-09-01T23:00:00Z",
        carbon_potential_pct=0.30,
    )

    fixtures.start_heat_treat(rich_run["id"], at="2026-09-01T19:00:00Z")
    rich_result = validate_success(
        api.record_heat_treat_results(
            rich_run["id"],
            {"core_hardness_hv": 330.0, "surface_decarb_depth_mm": 0.085},
            inspector_headers,
        )
    )
    assert rich_result["total_decarb_depth_mm"] == pytest.approx(0.085, abs=0.0005), (
        f"A carbon potential of 0.42 contributes no deficit, so 0.085 stays 0.085, "
        f"got {rich_result['total_decarb_depth_mm']}"
    )
    assert rich_result["result"] == "PASS", (
        f"0.085 mm is inside the 0.100 mm ceiling, got {rich_result['result']}"
    )

    rich_after = fixtures.read_lot(rich_lot["id"])
    assert rich_after["process_state"] == "HEAT_TREATED", (
        f"A passing run takes the lot to HEAT_TREATED, got {rich_after['process_state']}"
    )
    assert rich_after["heat_treat_completed"] is True, (
        "A passing run sets heat_treat_completed"
    )
    assert rich_after["disposition"] == "IN_PROCESS", (
        f"A passing run leaves the lot IN_PROCESS, got {rich_after['disposition']}"
    )

    fixtures.start_heat_treat(lean_run["id"], at="2026-09-01T21:30:00Z")
    fixtures.set_clock("2026-09-01T22:30:00Z")
    lean_result = validate_success(
        api.record_heat_treat_results(
            lean_run["id"],
            {"core_hardness_hv": 330.0, "surface_decarb_depth_mm": 0.085},
            inspector_headers,
        )
    )
    assert lean_result["total_decarb_depth_mm"] == pytest.approx(0.102, abs=0.0005), (
        f"A carbon potential of 0.30 amplifies 0.085 by 1.2 to 0.102, "
        f"got {lean_result['total_decarb_depth_mm']}"
    )
    assert lean_result["result"] == "FAIL_DECARB", (
        f"0.102 mm is strictly greater than the 0.100 mm ceiling, "
        f"got {lean_result['result']}"
    )

    lean_after = fixtures.read_lot(lean_lot["id"])
    assert lean_after["disposition"] == "HOLD", (
        f"A failing run freezes the lot, got {lean_after['disposition']}"
    )
    assert lean_after["hold_source"] == "HT_FAILURE", (
        f"Expected hold_source HT_FAILURE, got {lean_after['hold_source']}"
    )
    assert lean_after["process_state"] == "SECONDARY_DONE", (
        f"A failing run leaves process_state where it was, got {lean_after['process_state']}"
    )
    assert lean_after["heat_treat_completed"] is False, (
        "A failing run does not set heat_treat_completed"
    )

    furnace = fixtures.read_furnace(env["furnace"]["id"])
    assert furnace["status"] == "IDLE", (
        f"Recording results returns the furnace to IDLE, got {furnace['status']}"
    )
    assert _same_instant(furnace["last_run_end_at"], "2026-09-01T22:30:00Z"), (
        f"Expected last_run_end_at 2026-09-01T22:30:00Z, got {furnace['last_run_end_at']}"
    )


def test_hardness_failure_is_decided_before_decarburisation_failure(api, inspector_headers):
    """A coupon breaching both limits reports FAIL_HARDNESS, and still records its decarb depth.

    Core hardness of 400.0 HV lies above the 361 HV ceiling of the 304..361 window and
    the amplified depth of 0.200 mm is double the 0.100 mm limit, but the pinned
    evaluation order decides hardness first, so the verdict is FAIL_HARDNESS rather than
    FAIL_DECARB. The depth is recorded all the same, and the failed run still frees the
    furnace.

    PRD: "Evaluation order is pinned, hardness first and decarburization second."

    PRD: "If `core_hardness_hv` falls outside the part's band — below `min_core_hardness_hv` or above `max_core_hardness_hv`, both bounds inclusive so a coupon exactly on either bound passes — the `result` is `FAIL_HARDNESS`."

    PRD: "Recording results always takes the run `RUNNING → COMPLETED` (a terminal status), stamps `completed_at` from the logical clock, returns the furnace to `IDLE`, and sets the furnace's `last_run_end_at` to the same instant."

    PRD: "On either `FAIL_HARDNESS` or `FAIL_DECARB`, the lot's `disposition` moves to `HOLD` with `hold_source` of `HT_FAILURE` while its `process_state` stays exactly where it was."

    Design: Corner/calculations/hardness_failure_is_decided_before_decarb_failure
    """
    env = _reference_environment()
    env = fixtures.setup_secondary_done_lot(
        env=env, lot_overrides={"lot_code": "L-2601"}
    )
    lot = env["lot"]

    run = fixtures.book_heat_treat(
        lot["id"],
        env["furnace"]["id"],
        window_start_at="2026-09-01T18:00:00Z",
        window_end_at="2026-09-01T23:00:00Z",
        carbon_potential_pct=0.42,
    )
    fixtures.start_heat_treat(run["id"], at="2026-09-01T19:00:00Z")

    result = validate_success(
        api.record_heat_treat_results(
            run["id"],
            {"core_hardness_hv": 400.0, "surface_decarb_depth_mm": 0.200},
            inspector_headers,
        )
    )

    assert result["result"] == "FAIL_HARDNESS", (
        f"Both limits are breached, but hardness is evaluated first, so the verdict is "
        f"FAIL_HARDNESS, got {result['result']}"
    )
    assert result["total_decarb_depth_mm"] == pytest.approx(0.200, abs=0.0005), (
        f"The measured depth is still recorded, got {result['total_decarb_depth_mm']}"
    )
    assert result["core_hardness_hv"] == pytest.approx(400.0, abs=0.05), (
        f"The measured hardness is still recorded, got {result['core_hardness_hv']}"
    )
    assert result["status"] == "COMPLETED", (
        f"Recording results always completes the run, got {result['status']}"
    )
    assert _same_instant(result["completed_at"], "2026-09-01T19:00:00Z"), (
        f"Expected completed_at 2026-09-01T19:00:00Z, got {result['completed_at']}"
    )

    lot_after = fixtures.read_lot(lot["id"])
    assert lot_after["disposition"] == "HOLD", (
        f"A failing run freezes the lot, got {lot_after['disposition']}"
    )
    assert lot_after["hold_source"] == "HT_FAILURE", (
        f"Expected hold_source HT_FAILURE, got {lot_after['hold_source']}"
    )
    assert lot_after["process_state"] == "SECONDARY_DONE", (
        f"A failing run leaves process_state where it was, got {lot_after['process_state']}"
    )
    assert lot_after["heat_treat_completed"] is False, (
        "A failing run does not set heat_treat_completed"
    )

    furnace = fixtures.read_furnace(env["furnace"]["id"])
    assert furnace["status"] == "IDLE", (
        f"A failed run still frees the furnace, got {furnace['status']}"
    )
