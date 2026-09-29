"""Month-to-date metering rollups, the parallel billing axis and ledger conservation."""

import pytest
from test_helpers import (
    STANDARD_BANK,
    STANDARD_BANK_ONSITE_KG,
    complete_session,
    create_session,
    find_ledger_entry,
    fuel_session,
    read_ledger,
    read_ledger_meta,
    read_session,
    read_station,
    run_completed_fill,
    run_settled_fill,
    settle_session,
    setup_operational_station,
    void_session_meter,
    assert_ledger_replays,
)

H35_LIGHT_DUTY = {
    "vehicle_class": "LIGHT_DUTY",
    "target_pressure_class": "H35",
    "fill_protocol": "SAE_J2601_TABLE",
    "ambient_temp_c": 0.0,
}

# ─── Recipe builders ──────────────────────────────────────────────────────


def _standard_station():
    return setup_operational_station(
        station_overrides={
            "nozzle_count": 4,
            "offload_bay_count": 1,
            "storage_capacity_kg": 900.000,
            "reserve_floor_kg": 100.000,
            "max_pressure_class": "H70",
        },
        bank=STANDARD_BANK,
        responders=2,
        vessel_due_date="2027-06-30",
    )


def _three_fills_two_settled():
    """Three same-month H35 fills; the first two are already settled."""
    scenario = _standard_station()
    station_id = scenario["station"]["id"]
    first = run_settled_fill(
        station_id, 3.200, 3.100, -20.0, 700.00, 438.00, **H35_LIGHT_DUTY
    )
    second = run_settled_fill(
        station_id, 4.300, 4.250, -20.0, 700.00, 438.00, **H35_LIGHT_DUTY
    )
    third = run_completed_fill(
        station_id, 5.600, 5.500, -20.0, 750.00, 438.00, **H35_LIGHT_DUTY
    )
    scenario["sessions"] = [first, second, third]
    return scenario


def _one_completed_transit_bus_fill(vehicle_class="LIGHT_DUTY"):
    """A single 80.000 kg H35 fill taken to COMPLETED but not yet settled."""
    scenario = _standard_station()
    station_id = scenario["station"]["id"]
    opening = read_station(station_id)
    session = create_session(
        station_id,
        planned_kg=80.000,
        **{**H35_LIGHT_DUTY, "vehicle_class": vehicle_class},
    )
    fuelled = fuel_session(session["id"], station_id, -20.0)
    completed = complete_session(session["id"], station_id, 79.850, 700.00, 438.00)
    scenario["opening"] = opening
    scenario["created"] = session
    scenario["fuelled"] = fuelled
    scenario["completed"] = completed
    return scenario


# ─── Month-to-date rollup rounding order ──────────────────────────────────


def test_month_to_date_rollup_sums_the_already_rounded_session_masses():
    """Rounding each fill before summing gives 12.948 kg, not 12.947 kg.

    "The rounding order here is pinned and consequential: each session's
    corrected mass is rounded first and the rounded values are then summed.
    Rounding the sum of the unrounded products instead is explicitly not the
    required behaviour; the two answers can differ by up to a milligram per
    session."

    Design: Difficulty/combinatorial_formula/metering_rollup_rounds_per_session_before_summing_mode_b
    """
    scenario = _three_fills_two_settled()
    first, second, third = scenario["sessions"]

    settled_third = settle_session(third["id"])

    assert first["corrected_kg"] == pytest.approx(3.125, abs=0.001)
    assert second["corrected_kg"] == pytest.approx(4.284, abs=0.001)
    assert settled_third["corrected_kg"] == pytest.approx(5.539, abs=0.001)

    station = read_station(scenario["station"]["id"])
    assert station["corrected_kg_mtd"] == pytest.approx(12.948, abs=0.0005), (
        "3.125 + 4.284 + 5.539 is 12.948"
    )
    assert station["corrected_kg_mtd"] != pytest.approx(12.947, abs=0.0005), (
        "12.947 is the forbidden sum-then-round answer"
    )


def test_month_to_date_metering_error_follows_the_rounded_rollup():
    """The reported error percentage is derived from the pinned rollup order.

    "`metering_error_pct_mtd` is `metered_kg_mtd` minus `corrected_kg_mtd`,
    divided by `corrected_kg_mtd`, multiplied by one hundred, and rounded half-up
    to three decimal places."  "`metering_accuracy_flag` is `WITHIN_TOLERANCE`
    when the absolute value of `metering_error_pct_mtd` is no greater than 1.500
    percent, and `OUT_OF_TOLERANCE` otherwise."

    Design: Difficulty/combinatorial_formula/metering_rollup_rounds_per_session_before_summing_mode_b
    """
    scenario = _three_fills_two_settled()
    third = scenario["sessions"][2]

    settle_session(third["id"])

    station = read_station(scenario["station"]["id"])
    assert station["metered_kg_mtd"] == pytest.approx(12.850, abs=0.0005), (
        "3.100 + 4.250 + 5.500 is 12.850"
    )
    assert station["metering_error_pct_mtd"] == pytest.approx(-0.757, abs=0.0005)
    assert station["metering_error_pct_mtd"] != pytest.approx(-0.749, abs=0.0005), (
        "-0.749 is what the forbidden rounding order would report"
    )
    assert station["metering_accuracy_flag"] == "WITHIN_TOLERANCE"
    assert station["onsite_inventory_kg"] == pytest.approx(208.652, abs=0.001), (
        "221.600 kg less the 12.948 kg of corrected mass actually dispensed"
    )


# ─── The two independent session axes ─────────────────────────────────────


def test_fill_and_billing_axes_advance_without_disturbing_each_other():
    """Settlement and voiding leave the physical axis pinned at COMPLETED.

    "A dispensing session carries two independent state dimensions on the same
    row. `fill_status` tracks the physical fill and runs `PRECOOLING → FUELING →
    COMPLETED`, with `ABORTED` reachable from either of the first two; `COMPLETED`
    and `ABORTED` are the terminal values of that axis. `billing_status` tracks
    settlement and runs `PENDING → METERED`, with `VOIDED` reachable from either."

    Design: Difficulty/non_linear_state_machine/dispense_session_parallel_fill_and_billing_axes_advance_independently
    """
    scenario = _one_completed_transit_bus_fill()
    session_id = scenario["created"]["id"]
    assert (scenario["created"]["fill_status"], scenario["created"]["billing_status"]) == (
        "PRECOOLING",
        "PENDING",
    )
    assert (scenario["fuelled"]["fill_status"], scenario["fuelled"]["billing_status"]) == (
        "FUELING",
        "PENDING",
    )
    assert (
        scenario["completed"]["fill_status"],
        scenario["completed"]["billing_status"],
    ) == ("COMPLETED", "PENDING")

    settled = settle_session(session_id)
    voided = void_session_meter(session_id, void_reason="BILLING_DISPUTE")

    assert (settled["fill_status"], settled["billing_status"]) == ("COMPLETED", "METERED")
    assert (voided["fill_status"], voided["billing_status"]) == ("COMPLETED", "VOIDED")


def test_voiding_a_settlement_never_marks_the_fill_as_aborted():
    """A void is a billing action, so it writes `void_reason` and not `abort_reason`.

    "`abort_reason` is null unless `fill_status` is `ABORTED`."  The void also
    "refreshes the metering rollup, which now excludes the voided session from
    `metered_kg_mtd`, `corrected_kg_mtd`, `metering_error_pct_mtd` and
    `metering_accuracy_flag`."

    Design: Difficulty/non_linear_state_machine/dispense_session_parallel_fill_and_billing_axes_advance_independently
    """
    scenario = _one_completed_transit_bus_fill()
    session_id = scenario["created"]["id"]
    settle_session(session_id)

    void_session_meter(session_id, void_reason="BILLING_DISPUTE")

    session = read_session(session_id)
    assert session["abort_reason"] is None, "the billing axis never touches the fill axis"
    assert session["void_reason"] == "BILLING_DISPUTE"
    assert session["corrected_kg"] == pytest.approx(80.489, abs=0.001)
    station = read_station(scenario["station"]["id"])
    assert station["onsite_inventory_kg"] == pytest.approx(141.750, abs=0.001)
    assert station["corrected_kg_mtd"] == pytest.approx(0.000, abs=0.001), (
        "the voided row has left the rollup input set"
    )


# ─── Ledger conservation across settle and void ───────────────────────────


def test_meter_void_reversal_exactly_undoes_the_meter_correction():
    """The reversal is the additive inverse, so on-site mass returns with no drift.

    "A void moves `billing_status` `METERED → VOIDED` and appends a
    `METER_VOID_REVERSAL` entry whose `delta_kg` is the session's `corrected_kg`
    minus its `metered_kg` — the exact additive inverse of the `METER_CORRECTION`
    entry the settlement appended."

    Design: Difficulty/compensating_invariant/meter_void_reversal_conserves_hydrogen_mass_in_kg_across_the_ledger
    """
    scenario = _one_completed_transit_bus_fill(vehicle_class="TRANSIT_BUS")
    station_id = scenario["station"]["id"]
    assert scenario["opening"]["onsite_inventory_kg"] == pytest.approx(
        STANDARD_BANK_ONSITE_KG, abs=0.001
    )
    assert scenario["completed"]["corrected_kg"] == pytest.approx(80.489, abs=0.001)
    settle_session(scenario["created"]["id"])
    assert read_station(station_id)["onsite_inventory_kg"] == pytest.approx(
        141.111, abs=0.001
    ), "the correction removed 0.639 kg"

    void_session_meter(scenario["created"]["id"], void_reason="AUDIT_ADJUSTMENT")

    entries = read_ledger(station_id, params={"limit": 100, "offset": 0})
    correction = find_ledger_entry(entries, "METER_CORRECTION")
    reversal = find_ledger_entry(entries, "METER_VOID_REVERSAL")
    assert correction["delta_kg"] == pytest.approx(-0.639, abs=0.001)
    assert reversal["delta_kg"] == pytest.approx(0.639, abs=0.001)
    assert correction["delta_kg"] + reversal["delta_kg"] == pytest.approx(0.000, abs=0.001)
    assert read_station(station_id)["onsite_inventory_kg"] == pytest.approx(
        141.750, abs=0.001
    ), "45.600 + 56.000 + 120.000 - 79.850 - 0.639 + 0.639 is 141.750"


def test_the_append_only_ledger_replays_to_the_stations_onsite_inventory():
    """Six append-only rows replay to the station's reported on-site mass.

    "Replaying the ledger means starting a running total at 0.000 and, for each
    entry in that order, adding the entry's `delta_kg` to the running total,
    rounding the result half-up to three decimal places, and recording that
    rounded total as the entry's `resulting_onsite_kg`."

    Design: Difficulty/compensating_invariant/meter_void_reversal_conserves_hydrogen_mass_in_kg_across_the_ledger
    """
    scenario = _one_completed_transit_bus_fill(vehicle_class="TRANSIT_BUS")
    station_id = scenario["station"]["id"]
    settle_session(scenario["created"]["id"])

    void_session_meter(scenario["created"]["id"], void_reason="AUDIT_ADJUSTMENT")

    entries = read_ledger(station_id, params={"limit": 100, "offset": 0})
    assert read_ledger_meta(station_id, params={"limit": 100, "offset": 0})[
        "total_count"
    ] == 6
    assert [entry["sequence_no"] for entry in entries] == [1, 2, 3, 4, 5, 6]
    assert [entry["reason"] for entry in entries] == [
        "OPENING_BALANCE",
        "OPENING_BALANCE",
        "OPENING_BALANCE",
        "DISPENSE_DRAW",
        "METER_CORRECTION",
        "METER_VOID_REVERSAL",
    ]
    assert_ledger_replays(entries)
    station = read_station(station_id)
    assert entries[-1]["resulting_onsite_kg"] == pytest.approx(141.750, abs=0.001)
    assert entries[-1]["resulting_onsite_kg"] == pytest.approx(
        station["onsite_inventory_kg"], abs=0.001
    )
    session = read_session(scenario["created"]["id"])
    assert (session["billing_status"], session["fill_status"]) == ("VOIDED", "COMPLETED")
    assert station["metered_kg_mtd"] == pytest.approx(0.000, abs=0.001)
    assert station["corrected_kg_mtd"] == pytest.approx(0.000, abs=0.001)
