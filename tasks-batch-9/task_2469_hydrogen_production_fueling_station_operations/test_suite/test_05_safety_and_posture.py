"""The freeze cascade, posture-versus-inventory error precedence and the H70 gate."""

import pytest
from test_helpers import (
    ADMIN,
    STANDARD_BANK,
    STANDARD_BANK_ONSITE_KG,
    api_client,
    create_session,
    dispense_session_payload,
    freeze_station_with_critical_leak,
    fuel_session,
    list_meta,
    list_rows,
    make_station_operator_headers,
    read_ledger,
    read_session,
    read_station,
    restrict_station_with_compressor_fault,
    setup_operational_station,
    validate_error,
    validate_success,
)

HIGH_ONLY_BANK = (
    {
        "bank_tier": "HIGH",
        "water_volume_l": 600.0,
        "mawp_bar": 1000.00,
        "min_residual_bar": 200.00,
        "initial_pressure_bar": 950.00,
    },
)


# ─── Recipe builders ──────────────────────────────────────────────────────


def _operational_station(bank=STANDARD_BANK, **station_overrides):
    overrides = {
        "nozzle_count": 4,
        "offload_bay_count": 1,
        "storage_capacity_kg": 900.000,
        "reserve_floor_kg": 100.000,
        "max_pressure_class": "H70",
    }
    overrides.update(station_overrides)
    return setup_operational_station(
        station_overrides=overrides,
        bank=bank,
        responders=2,
        vessel_due_date="2027-06-30",
    )


def _station_with_a_fill_in_flight():
    """A 20.000 kg H35 fill sitting at FUELING on an otherwise healthy station."""
    scenario = _operational_station()
    station_id = scenario["station"]["id"]
    scenario["opening"] = read_station(station_id)
    session = create_session(
        station_id,
        vehicle_class="LIGHT_DUTY",
        target_pressure_class="H35",
        fill_protocol="SAE_J2601_TABLE",
        planned_kg=20.000,
        ambient_temp_c=0.0,
    )
    scenario["session"] = fuel_session(session["id"], station_id, -20.0)
    return scenario


def _frozen_station_with_a_single_high_bank():
    """A frozen station whose 45.600 kg of stock is far below the requested fill."""
    scenario = _operational_station(bank=HIGH_ONLY_BANK)
    station_id = scenario["station"]["id"]
    scenario["event"] = freeze_station_with_critical_leak(station_id, nozzles=4)
    scenario["frozen"] = read_station(station_id)
    return scenario


def _restricted_station():
    """A station taken OPEN → RESTRICTED by a MAJOR compressor fault."""
    scenario = _operational_station()
    station_id = scenario["station"]["id"]
    scenario["event"] = restrict_station_with_compressor_fault(station_id, nozzles=2)
    scenario["restricted"] = read_station(station_id)
    return scenario


def _open_session_at_version(station_id, station_version, **overrides):
    """Attempt a session create against a caller-chosen station version."""
    return api_client.create_dispense_session(
        dispense_session_payload(station_id, station_version, **overrides),
        make_station_operator_headers(station_id),
    )


# ─── The freeze cascade ───────────────────────────────────────────────────


def test_a_critical_leak_freezes_the_station_and_aborts_the_fill_in_flight():
    """One event drives subsystem, posture, fill status and billing status in turn.

    "Hop two sets the corresponding subsystem field as described above. Hop three,
    because that subsystem field (or the presence of a `CRITICAL` open event) is a
    freezing condition, recomputes `safety_posture` to `FROZEN`. Hop four, because
    the posture became `FROZEN`, takes every dispensing session on the station whose
    `fill_status` is `PRECOOLING` or `FUELING` to `fill_status` of `ABORTED` with
    `abort_reason` of `STATION_FROZEN`."

    Design: Difficulty/transitive_cascade/critical_leak_freezes_station_then_aborts_fill_then_voids_billing_depth_4
    """
    scenario = _station_with_a_fill_in_flight()
    station_id = scenario["station"]["id"]
    assert scenario["opening"]["safety_posture"] == "OPEN"
    assert scenario["opening"]["leak_detection_status"] == "NORMAL"
    assert (scenario["session"]["fill_status"], scenario["session"]["billing_status"]) == (
        "FUELING",
        "PENDING",
    )

    event = freeze_station_with_critical_leak(station_id, nozzles=4)

    assert event["status"] == "OPEN"
    assert event["opened_by_user_id"] == "SO-1", "the acting officer is recorded"
    station = read_station(station_id)
    assert station["leak_detection_status"] == "ALARM"
    assert station["safety_posture"] == "FROZEN"
    session = read_session(scenario["session"]["id"])
    assert session["fill_status"] == "ABORTED"
    assert session["abort_reason"] == "STATION_FROZEN"
    assert session["billing_status"] == "VOIDED"


def test_the_frozen_abort_releases_the_reservation_without_moving_any_mass():
    """The fifth hop restores availability while the ledger stays untouched.

    "Hop five, because those sessions have left the reserving set, moves each of
    them whose `billing_status` was `PENDING` to `VOIDED`, and recomputes the
    station's `reserved_kg`, `available_kg`, `projected_available_kg` and
    `supply_alert`."  On the abort leg "no ledger entry is appended because no mass
    moved".

    Design: Difficulty/transitive_cascade/critical_leak_freezes_station_then_aborts_fill_then_voids_billing_depth_4
    """
    scenario = _station_with_a_fill_in_flight()
    station_id = scenario["station"]["id"]
    before = read_station(station_id)
    assert before["reserved_kg"] == pytest.approx(20.000, abs=0.001)

    freeze_station_with_critical_leak(station_id, nozzles=4)

    station = read_station(station_id)
    assert station["reserved_kg"] == pytest.approx(0.000, abs=0.001)
    assert station["available_kg"] == pytest.approx(STANDARD_BANK_ONSITE_KG, abs=0.001)
    assert station["projected_available_kg"] == pytest.approx(
        STANDARD_BANK_ONSITE_KG, abs=0.001
    )
    assert station["supply_alert"] is False
    assert station["onsite_inventory_kg"] == pytest.approx(
        STANDARD_BANK_ONSITE_KG, abs=0.001
    )
    session = read_session(scenario["session"]["id"])
    assert session["metered_kg"] is None
    assert session["corrected_kg"] is None
    entries = read_ledger(station_id, params={"limit": 100, "offset": 0})
    assert [entry["reason"] for entry in entries] == [
        "OPENING_BALANCE",
        "OPENING_BALANCE",
        "OPENING_BALANCE",
    ], "an aborted fill moves no hydrogen"


# ─── Posture outranks inventory ───────────────────────────────────────────


def test_the_frozen_gate_is_reported_ahead_of_the_inventory_shortfall():
    """A frozen station refuses the session before its stock is even consulted.

    "Session creation is the most heavily gated create in the system, and the order
    of its checks is deliberate so that the most fundamental obstacle is the one
    reported."  "Then the frozen gate: a `FROZEN` station accepts no new session,
    and the attempt returns `ERR_STATION_FROZEN`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_state_error_outranks_insufficient_inventory_fiscal_error
    """
    scenario = _frozen_station_with_a_single_high_bank()
    station_id = scenario["station"]["id"]
    assert scenario["frozen"]["safety_posture"] == "FROZEN"
    assert scenario["frozen"]["available_kg"] == pytest.approx(45.600, abs=0.001)
    assert scenario["frozen"]["high_bank_deliverable_kg"] == pytest.approx(36.000, abs=0.001)

    response = _open_session_at_version(
        station_id,
        scenario["frozen"]["version"],
        vehicle_class="HEAVY_TRUCK",
        target_pressure_class="H35",
        fill_protocol="SAE_J2601_TABLE",
        planned_kg=100.000,
        ambient_temp_c=0.0,
    )

    error_data = validate_error(response, "ERR_STATION_FROZEN", expected_status=409)
    assert error_data["error_id"] != "ERR_INSUFFICIENT_AVAILABLE_INVENTORY", (
        "the 100.000 kg request also over-reserves the 45.600 kg on hand"
    )


def test_the_refused_frozen_session_reserves_nothing():
    """A refusal at the frozen gate creates no session and no reservation.

    "Finally inventory: `planned_kg` must be no greater than the station's
    `available_kg` at the moment of creation, and an over-reservation is refused
    with `ERR_INSUFFICIENT_AVAILABLE_INVENTORY` (HTTP 422)."  That later fiscal
    check is never reached, and either way no reservation is recorded.

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_state_error_outranks_insufficient_inventory_fiscal_error
    """
    scenario = _frozen_station_with_a_single_high_bank()
    station_id = scenario["station"]["id"]

    validate_error(
        _open_session_at_version(
            station_id,
            scenario["frozen"]["version"],
            vehicle_class="HEAVY_TRUCK",
            target_pressure_class="H35",
            fill_protocol="SAE_J2601_TABLE",
            planned_kg=100.000,
            ambient_temp_c=0.0,
        ),
        "ERR_STATION_FROZEN",
        expected_status=409,
    )

    listing = api_client.list_station_dispense_sessions(
        station_id, ADMIN, params={"limit": 100, "offset": 0}
    )
    assert list_meta(listing)["total_count"] == 0, "the refused create wrote no row"
    station = read_station(station_id)
    assert station["reserved_kg"] == pytest.approx(0.000, abs=0.001)
    assert station["available_kg"] == pytest.approx(45.600, abs=0.001)
    assert station["version"] == scenario["frozen"]["version"], (
        "a refused create never moves the station's version"
    )


# ─── The restricted posture gates only H70 ────────────────────────────────


def test_a_restricted_station_refuses_the_high_pressure_fill():
    """Restriction bites on the requested pressure class, not on the station as a whole.

    "Then the restricted gate on high-pressure fills: a `RESTRICTED` station accepts
    no session whose `target_pressure_class` is `H70`, returning
    `ERR_POSTURE_RESTRICTS_H70`."

    Design: Difficulty/cross_entity_state_dependency/h70_session_blocked_by_restricted_station_while_h35_still_allowed
    """
    scenario = _restricted_station()
    station_id = scenario["station"]["id"]
    assert scenario["restricted"]["safety_posture"] == "RESTRICTED"
    assert scenario["restricted"]["compressor_status"] == "OFFLINE"
    assert scenario["restricted"]["leak_detection_status"] == "NORMAL"

    response = _open_session_at_version(
        station_id,
        scenario["restricted"]["version"],
        vehicle_class="LIGHT_DUTY",
        target_pressure_class="H70",
        fill_protocol="SAE_J2601_TABLE",
        planned_kg=30.000,
        ambient_temp_c=20.0,
    )

    validate_error(response, "ERR_POSTURE_RESTRICTS_H70", expected_status=422)
    assert read_station(station_id)["version"] == scenario["restricted"]["version"]


def test_the_same_station_version_still_admits_an_h35_fill():
    """The identical request at H35 is accepted from the very same snapshot.

    "A `COMPRESSOR_FAULT` event of `MAJOR` severity opened against an `OPEN` station
    sets `compressor_status` to `OFFLINE` and recomputes the posture to
    `RESTRICTED`, taking the station `OPEN → RESTRICTED`; in-flight sessions
    continue, because a restricted posture only gates *new* `H70` sessions and *new*
    compressor makeup."  For an H35 fill in the mild band the table value is
    "−26.0 in the mild band".

    Design: Difficulty/cross_entity_state_dependency/h70_session_blocked_by_restricted_station_while_h35_still_allowed
    """
    scenario = _restricted_station()
    station_id = scenario["station"]["id"]
    station_version = scenario["restricted"]["version"]
    validate_error(
        _open_session_at_version(
            station_id,
            station_version,
            vehicle_class="LIGHT_DUTY",
            target_pressure_class="H70",
            fill_protocol="SAE_J2601_TABLE",
            planned_kg=30.000,
            ambient_temp_c=20.0,
        ),
        "ERR_POSTURE_RESTRICTS_H70",
        expected_status=422,
    )

    accepted = validate_success(
        _open_session_at_version(
            station_id,
            station_version,
            vehicle_class="LIGHT_DUTY",
            target_pressure_class="H35",
            fill_protocol="SAE_J2601_TABLE",
            planned_kg=30.000,
            ambient_temp_c=20.0,
        ),
        expected_status=201,
    )

    assert accepted["fill_status"] == "PRECOOLING"
    assert accepted["billing_status"] == "PENDING"
    assert accepted["required_precool_c"] == pytest.approx(-26.0, abs=0.01)
    station = read_station(station_id)
    assert station["reserved_kg"] == pytest.approx(30.000, abs=0.001)
    assert station["available_kg"] == pytest.approx(191.600, abs=0.001)
    listing = api_client.list_station_dispense_sessions(
        station_id, ADMIN, params={"limit": 100, "offset": 0}
    )
    assert list_meta(listing)["total_count"] == 1
    assert [row["id"] for row in list_rows(listing)] == [accepted["id"]]
