"""Vessel condemnation venting and the high-bank deliverable posture boundary."""

import pytest
from test_helpers import (
    STANDARD_BANK,
    STANDARD_BANK_ONSITE_KG,
    add_emergency_responders,
    commission_vessel,
    condemn_vessel,
    find_ledger_entry,
    read_ledger,
    read_station,
    read_vessel,
    run_completed_fill,
    set_clock,
    setup_operational_station,
    setup_station,
)

SINGLE_HIGH_BANK = (
    {
        "bank_tier": "HIGH",
        "water_volume_l": 1250.0,
        "mawp_bar": 1000.00,
        "min_residual_bar": 200.00,
        "initial_pressure_bar": 950.00,
    },
)

H35_FILL = {"target_pressure_class": "H35", "fill_protocol": "SAE_J2601_TABLE",
            "ambient_temp_c": 20.0}


# ─── Recipe builders ──────────────────────────────────────────────────────


def _station_with_a_low_bank_falling_due():
    """A three-vessel station whose LOW vessel reaches its due date on 2026-08-15."""
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        station_overrides={
            "nozzle_count": 4,
            "offload_bay_count": 1,
            "storage_capacity_kg": 900.000,
            "reserve_floor_kg": 100.000,
            "max_pressure_class": "H70",
        },
    )
    station_id = scenario["station"]["id"]
    vessels = {}
    for spec in STANDARD_BANK:
        due = "2026-08-15" if spec["bank_tier"] == "LOW" else "2027-06-30"
        vessels[spec["bank_tier"]] = commission_vessel(
            station_id, next_inspection_due_date=due, **spec
        )
    add_emergency_responders(station_id, count=2)
    scenario["vessels"] = vessels

    set_clock("2026-08-15T00:00:00Z")
    scenario["low_before"] = read_vessel(vessels["LOW"]["id"])
    scenario["before"] = read_station(station_id)
    return scenario


def _station_drawn_down_to_the_high_bank_boundary():
    """A 65.000 kg H35 fill that lands `high_bank_deliverable_kg` on exactly 10.000."""
    scenario = setup_operational_station(
        station_overrides={
            "nozzle_count": 4,
            "offload_bay_count": 1,
            "storage_capacity_kg": 900.000,
            "reserve_floor_kg": 10.000,
            "max_pressure_class": "H35",
        },
        bank=SINGLE_HIGH_BANK,
        responders=2,
        vessel_due_date="2027-06-30",
    )
    scenario["opening"] = read_station(scenario["station"]["id"])
    scenario["first_fill"] = run_completed_fill(
        scenario["station"]["id"],
        65.000,
        65.000,
        -30.0,
        700.00,
        438.00,
        vehicle_class="HEAVY_TRUCK",
        **H35_FILL,
    )
    return scenario


# ─── Condemnation vents inventory and restricts the station ───────────────


def test_condemning_a_due_vessel_vents_its_contents_to_the_ledger():
    """The vent is recorded as the negation of the mass standing in the vessel.

    "A condemning inspection is accepted from either `DUE` or `OVERDUE` — the
    `DUE → CONDEMNED` and `OVERDUE → CONDEMNED` legs are specified identically — and
    it sets `inspection_status` to `CONDEMNED`, zeroes `current_pressure_bar` to
    0.00, and appends an `INSPECTION_VENT` ledger entry whose `delta_kg` is the
    negation of the vessel's stored mass at that moment, recording the vented
    contents."

    Design: Difficulty/transitive_cascade/vessel_condemnation_vents_inventory_then_restricts_station_depth_3
    """
    scenario = _station_with_a_low_bank_falling_due()
    station_id = scenario["station"]["id"]
    low_id = scenario["vessels"]["LOW"]["id"]
    assert scenario["low_before"]["inspection_status"] == "DUE", (
        "a vessel whose due date is exactly today is DUE, not CURRENT"
    )
    assert scenario["low_before"]["stored_mass_kg"] == pytest.approx(120.000, abs=0.001)
    assert scenario["before"]["safety_posture"] == "OPEN"
    assert scenario["before"]["onsite_inventory_kg"] == pytest.approx(
        STANDARD_BANK_ONSITE_KG, abs=0.001
    )

    condemned = condemn_vessel(low_id)

    assert condemned["inspection_status"] == "CONDEMNED"
    assert condemned["current_pressure_bar"] == pytest.approx(0.00, abs=0.01)
    assert condemned["stored_mass_kg"] == pytest.approx(0.000, abs=0.001)
    entries = read_ledger(station_id, params={"limit": 100, "offset": 0})
    vent = find_ledger_entry(entries, "INSPECTION_VENT")
    assert vent["delta_kg"] == pytest.approx(-120.000, abs=0.001)
    assert read_station(station_id)["onsite_inventory_kg"] == pytest.approx(
        101.600, abs=0.001
    )


def test_the_condemned_vessel_leaves_both_deliverable_sums_and_restricts_the_station():
    """Dropping out of the deliverable sums is itself a restricting condition.

    "Vessels that are `OVERDUE` or `CONDEMNED` contribute to neither figure."  The
    station is then `RESTRICTED` because "at least one `PressureVessel` on the
    station has `inspection_status` of `OVERDUE` or `CONDEMNED`".

    Design: Difficulty/transitive_cascade/vessel_condemnation_vents_inventory_then_restricts_station_depth_3
    """
    scenario = _station_with_a_low_bank_falling_due()
    station_id = scenario["station"]["id"]
    assert scenario["before"]["total_deliverable_kg"] == pytest.approx(160.000, abs=0.001)
    assert scenario["before"]["high_bank_deliverable_kg"] == pytest.approx(36.000, abs=0.001)

    condemn_vessel(scenario["vessels"]["LOW"]["id"])

    station = read_station(station_id)
    assert station["total_deliverable_kg"] == pytest.approx(80.000, abs=0.001), (
        "the 80.000 kg of LOW-bank deliverable mass has left the sum"
    )
    assert station["high_bank_deliverable_kg"] == pytest.approx(36.000, abs=0.001), (
        "the high bank is untouched by a LOW-bank condemnation"
    )
    assert station["safety_posture"] == "RESTRICTED"
    assert station["supply_alert"] is False, (
        "101.600 kg projected still clears the 100.000 kg reserve floor"
    )
    assert station["version"] > scenario["before"]["version"]


# ─── The high-bank deliverable boundary ───────────────────────────────────


def test_high_bank_deliverable_landing_exactly_on_the_minimum_keeps_the_station_open():
    """Ten kilograms exactly is not strictly less than ten, so the posture holds.

    "Otherwise the station is `RESTRICTED` when any of these hold: `compressor_status`
    is `OFFLINE`, or `high_bank_deliverable_kg` is strictly less than 10.000 kg".
    "The high-bank comparison is made at three decimal places."

    Design: Difficulty/boundary_precision_check/high_bank_deliverable_exactly_at_min_keeps_posture_open
    """
    scenario = _station_drawn_down_to_the_high_bank_boundary()
    station_id = scenario["station"]["id"]
    assert scenario["opening"]["onsite_inventory_kg"] == pytest.approx(95.000, abs=0.001)
    assert scenario["opening"]["high_bank_deliverable_kg"] == pytest.approx(75.000, abs=0.001)
    fill = scenario["first_fill"]
    assert fill["required_precool_c"] == pytest.approx(-26.0, abs=0.01)
    assert fill["direct_cascade_kg"] == pytest.approx(51.200, abs=0.001)
    assert fill["compressor_makeup_kg"] == pytest.approx(13.800, abs=0.001)
    assert fill["density_correction_factor"] == pytest.approx(1.0, abs=0.000001)
    assert fill["corrected_kg"] == pytest.approx(65.000, abs=0.001)
    assert fill["metering_error_pct"] == pytest.approx(0.000, abs=0.001)

    station = read_station(station_id)

    assert read_vessel(scenario["vessels"]["HIGH"]["id"])[
        "current_pressure_bar"
    ] == pytest.approx(300.00, abs=0.01)
    assert station["high_bank_deliverable_kg"] == pytest.approx(10.000, abs=0.0005)
    assert station["safety_posture"] == "OPEN", (
        "exactly 10.000 kg sits on the boundary and does not restrict"
    )
    assert station["onsite_inventory_kg"] == pytest.approx(30.000, abs=0.001)


def test_one_more_tenth_of_a_kilogram_crosses_the_boundary_into_restricted():
    """The fill that empties the high bank is the fill that restricts the station.

    "That last recomputation carries a consequence worth stating on its own: a
    station that was `OPEN` with at least 10.000 kg of high-bank deliverable mass
    before the draw, and whose `high_bank_deliverable_kg` falls below 10.000 kg as a
    result of the draw, moves `OPEN → RESTRICTED` on the completion itself — the
    fill that emptied the high bank is the fill that restricts the next `H70`
    customer."

    Design: Difficulty/boundary_precision_check/high_bank_deliverable_exactly_at_min_keeps_posture_open
    """
    scenario = _station_drawn_down_to_the_high_bank_boundary()
    station_id = scenario["station"]["id"]
    assert read_station(station_id)["safety_posture"] == "OPEN"

    second = run_completed_fill(
        station_id, 0.100, 0.100, -30.0, 700.00, 438.00,
        vehicle_class="FORKLIFT", **H35_FILL,
    )

    assert second["direct_cascade_kg"] == pytest.approx(0.000, abs=0.001), (
        "the vessel now sits below the 438.00 bar terminal pressure of an H35 fill"
    )
    assert second["compressor_makeup_kg"] == pytest.approx(0.100, abs=0.001)
    assert read_vessel(scenario["vessels"]["HIGH"]["id"])[
        "current_pressure_bar"
    ] == pytest.approx(299.00, abs=0.01)
    station = read_station(station_id)
    assert station["high_bank_deliverable_kg"] == pytest.approx(9.900, abs=0.0005)
    assert station["safety_posture"] == "RESTRICTED"
    assert station["onsite_inventory_kg"] == pytest.approx(29.900, abs=0.001)
    assert station["supply_alert"] is False, (
        "29.900 kg projected still clears the 10.000 kg reserve floor"
    )
