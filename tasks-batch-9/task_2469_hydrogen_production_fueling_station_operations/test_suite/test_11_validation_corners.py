"""Validation corners: guard ordering, half-open windows and one-directional refusals."""

import pytest
from test_helpers import (
    ADMIN,
    ANALYST,
    DISPATCHER,
    NON_EXISTENT_UUID,
    api_client,
    arrive_delivery,
    book_tube_trailer_delivery,
    complete_session,
    create_session,
    fuel_session,
    list_meta,
    list_rows,
    make_station_operator_headers,
    open_session,
    purity_test_payload,
    read_delivery,
    read_ledger,
    read_lot,
    read_station,
    read_station_version,
    read_session,
    read_vessel,
    set_clock,
    setup_operational_station,
    setup_small_produced_lot,
    setup_small_released_lot,
    validate_error,
    validate_success,
    HALF_LIMIT_PURITY,
)

HIGH_VESSEL = {
    "bank_tier": "HIGH",
    "water_volume_l": 600.0,
    "mawp_bar": 1000.00,
    "min_residual_bar": 200.00,
    "initial_pressure_bar": 950.00,
}
LOW_VESSEL = {
    "bank_tier": "LOW",
    "water_volume_l": 5000.0,
    "mawp_bar": 1000.00,
    "min_residual_bar": 100.00,
    "initial_pressure_bar": 300.00,
}
SMALL_LOW_VESSEL = {
    "bank_tier": "LOW",
    "water_volume_l": 500.0,
    "mawp_bar": 1000.00,
    "min_residual_bar": 100.00,
    "initial_pressure_bar": 300.00,
}
H70_LIGHT_DUTY = {
    "vehicle_class": "LIGHT_DUTY",
    "target_pressure_class": "H70",
    "fill_protocol": "SAE_J2601_TABLE",
    "planned_kg": 5.000,
    "ambient_temp_c": 30.0,
}
H35_BUS = {
    "vehicle_class": "TRANSIT_BUS",
    "target_pressure_class": "H35",
    "fill_protocol": "SAE_J2601_TABLE",
    "planned_kg": 5.000,
    "ambient_temp_c": 20.0,
}


# ─── Recipe builders ──────────────────────────────────────────────────────


def _station(code, name, bank, pressure_class, nozzle_count=4, **station_overrides):
    """A dispensing-ready station: bank commissioned, two current responder certifications."""
    return setup_operational_station(
        clock="2026-08-01T00:00:00Z",
        agreement_overrides={
            "agreement_code": f"FA-{code}",
            "min_uptime_pct": 99.000,
            "penalty_per_point_cents": 250000,
            "initial_holdback_cents": 500000,
            "uptime_method": "NOZZLE_WEIGHTED",
        },
        station_overrides={
            "code": code,
            "name": name,
            "nozzle_count": nozzle_count,
            "offload_bay_count": 2,
            "storage_capacity_kg": 900.000,
            "reserve_floor_kg": 20.000,
            "max_pressure_class": pressure_class,
            "setback_compliant": True,
            **station_overrides,
        },
        bank=bank,
        responders=2,
        vessel_due_date="2027-06-30",
    )


def _h70_session_awaiting_precool(code):
    """One H70 session at ambient 30.0, so the ceiling it must reach is -33.0."""
    scenario = _station(code, "Protocol Station", (HIGH_VESSEL,), "H70")
    station_id = scenario["station"]["id"]
    scenario["session"] = create_session(station_id, **H70_LIGHT_DUTY)
    return scenario


def _book(station_id, lot_id, vessel_id, window_start, window_end, planned_kg=20.000,
          trailer_final_pressure_bar=100.00):
    return book_tube_trailer_delivery(
        station_id,
        lot_id,
        vessel_id,
        planned_kg=planned_kg,
        window_start=window_start,
        window_end=window_end,
        departed_at="2026-08-02T04:00:00Z",
        trailer_water_volume_l=1000.0,
        trailer_final_pressure_bar=trailer_final_pressure_bar,
    )


# ─── The fill-protocol ceiling ────────────────────────────────────────────


def test_a_dispenser_warmer_than_the_ceiling_violates_the_fill_protocol():
    """-30.0 is warmer than the required -33.0, so the fill never starts.

    "The transition is accepted only while `fill_status` is `PRECOOLING`; the station
    must not be `FROZEN`, or `ERR_STATION_FROZEN` applies; a `RESTRICTED` posture again
    blocks an `H70` session with `ERR_POSTURE_RESTRICTS_H70`, re-checked here because
    posture may have degraded during precooling; and fill-protocol compliance requires
    that `precool_temp_achieved_c` be no warmer than `required_precool_c`, meaning
    numerically less than or equal to it."  "A dispenser that failed to reach the ceiling
    is refused with `ERR_FILL_PROTOCOL_VIOLATION` (HTTP 422)."

    Design: Corner/validations/precool_shortfall_violates_the_fill_protocol_and_is_rejected
    """
    scenario = _h70_session_awaiting_precool("STN-V1")
    station_id = scenario["station"]["id"]
    session = scenario["session"]
    assert session["required_precool_c"] == pytest.approx(-33.0, abs=0.05)
    version_before = read_station_version(station_id)

    response = api_client.fuel_dispense_session(
        session["id"], {"precool_temp_achieved_c": -30.0}, make_station_operator_headers(station_id)
    )

    validate_error(response, "ERR_FILL_PROTOCOL_VIOLATION", expected_status=422)
    unchanged = read_session(session["id"])
    assert unchanged["fill_status"] == "PRECOOLING", "the operator may chill further and retry"
    assert unchanged["precool_temp_achieved_c"] is None
    station = read_station(station_id)
    assert station["version"] == version_before, "a refused call writes nothing"
    assert station["reserved_kg"] == pytest.approx(5.000, abs=0.001)
    assert [row["reason"] for row in read_ledger(station_id)] == ["OPENING_BALANCE"], (
        "no hydrogen moved, so no ledger row was appended"
    )


def test_a_dispenser_exactly_on_the_ceiling_starts_the_fill():
    """Equality complies, so achieving precisely -33.0 advances the fill axis.

    "Equality complies."  "On success the achieved temperature is stored, `fill_status`
    moves `PRECOOLING → FUELING`, `billing_status` remains `PENDING`, and the session's
    `planned_kg` stays inside the station's `reserved_kg`."  And "`available_kg` is
    `onsite_inventory_kg` minus `reserved_kg`".

    Design: Corner/validations/precool_exactly_at_the_requirement_satisfies_the_fill_protocol
    """
    scenario = _h70_session_awaiting_precool("STN-V2")
    station_id = scenario["station"]["id"]
    session = scenario["session"]

    fuelling = fuel_session(session["id"], station_id, -33.0)

    assert fuelling["fill_status"] == "FUELING"
    assert fuelling["precool_temp_achieved_c"] == pytest.approx(-33.0, abs=0.05)
    assert fuelling["billing_status"] == "PENDING", "the billing axis is untouched"
    station = read_station(station_id)
    assert station["reserved_kg"] == pytest.approx(5.000, abs=0.001)
    assert station["available_kg"] == pytest.approx(40.600, abs=0.001), (
        "45.600 kg on site less the 5.000 kg still reserved"
    )


# ─── Authentication and authorisation outrank everything ──────────────────


def test_a_missing_role_header_is_answered_before_body_and_reference_checks():
    """Four rules are broken at once and only the authentication failure is reported.

    "If either header is absent, or if `X-User-Role` does not name one of the roles
    below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."  "These two
    checks run before any other validation in the system: authentication first, then
    endpoint authorisation."

    Design: Corner/validations/missing_role_header_is_rejected_before_role_body_and_schema_checks
    """
    set_clock("2026-08-01T00:00:00Z")

    response = api_client.create_dispense_session(
        {
            "station_id": NON_EXISTENT_UUID,
            "vehicle_class": "LIGHT_DUTY",
            "target_pressure_class": "H70",
            "fill_protocol": "SAE_J2601_TABLE",
            "ambient_temp_c": 20.0,
        },
        {"X-User-ID": "PA-1"},
    )

    error = validate_error(response, "ERR_UNAUTHENTICATED", expected_status=401)
    assert error["error_id"] not in (
        "ERR_ROLE_NOT_PERMITTED",
        "ERR_INVALID_REQUEST",
        "ERR_STATION_NOT_FOUND",
    ), "the missing planned_kg, the unknown station and the role are all left unreported"
    assert sorted(error.keys()) == ["error_id", "message"]


def test_a_forbidden_role_is_answered_before_the_bodys_reference_lookup():
    """Authorisation is decided before the three unknown identifiers are ever resolved.

    "If the headers are well formed but the named role is not among those authorised
    for the target endpoint, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP
    403)."  "These two checks run before any other validation in the system:
    authentication first, then endpoint authorisation."

    Design: Corner/validations/role_denial_is_rejected_before_the_body_reference_lookup
    """
    set_clock("2026-08-01T00:00:00Z")

    response = api_client.create_delivery(
        {
            "station_id": NON_EXISTENT_UUID,
            "production_lot_id": NON_EXISTENT_UUID,
            "receiving_vessel_id": NON_EXISTENT_UUID,
            "mode": "LIQUID_TANKER",
            "planned_kg": 100.000,
            "window_start": "2026-08-02T08:00:00Z",
            "window_end": "2026-08-02T12:00:00Z",
            "departed_at": "2026-08-02T04:00:00Z",
        },
        make_station_operator_headers(NON_EXISTENT_UUID),
    )

    error = validate_error(response, "ERR_ROLE_NOT_PERMITTED", expected_status=403)
    assert error["error_id"] not in (
        "ERR_STATION_NOT_FOUND",
        "ERR_PRODUCTION_LOT_NOT_FOUND",
        "ERR_PRESSURE_VESSEL_NOT_FOUND",
    ), "existence is never consulted for an unauthorised role"
    listing = api_client.list_deliveries(ADMIN, params={"limit": 100, "offset": 0})
    assert list_meta(listing)["total_count"] == 0, "no delivery row was created"


# ─── The half-open arrival window ─────────────────────────────────────────


def test_one_clock_instant_is_outside_one_window_and_inside_the_next():
    """12:00:00Z ends the first window and starts the second, and only one arrival stands.

    "Recording arrival is also the dispatcher's job, takes no payload, and is accepted
    only while the delivery is `SCHEDULED` and the logical-clock instant lies inside the
    half-open booked window — at or after `window_start` and strictly before
    `window_end`."  "An arrival recorded outside that window is refused with
    `ERR_ARRIVAL_OUTSIDE_WINDOW` (HTTP 422)."  "`transit_hours` is the elapsed time from
    `departed_at` to `arrived_at` expressed in hours and rounded half-up to three decimal
    places; it is null until arrival."

    Design: Corner/validations/delivery_arrival_at_window_end_is_rejected_while_window_start_is_accepted
    """
    scenario = _station("STN-V5", "Window Station", (LOW_VESSEL,), "H35", nozzle_count=2)
    station_id = scenario["station"]["id"]
    vessel_id = scenario["vessels"]["LOW"]["id"]
    lot = setup_small_produced_lot()["lot"]
    ending = _book(station_id, lot["id"], vessel_id, "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z")
    starting = _book(station_id, lot["id"], vessel_id, "2026-08-02T12:00:00Z", "2026-08-02T16:00:00Z")
    set_clock("2026-08-02T12:00:00Z")

    refused = api_client.arrive_delivery(ending["id"], DISPATCHER)
    admitted = validate_success(
        api_client.arrive_delivery(starting["id"], DISPATCHER), expected_status=200
    )

    validate_error(refused, "ERR_ARRIVAL_OUTSIDE_WINDOW", expected_status=422)
    still_scheduled = read_delivery(ending["id"])
    assert still_scheduled["status"] == "SCHEDULED"
    assert still_scheduled["arrived_at"] is None
    assert still_scheduled["transit_hours"] is None

    assert admitted["status"] == "ARRIVED"
    assert admitted["transit_hours"] == pytest.approx(8.000, abs=0.001)
    assert admitted["heel_kg"] == pytest.approx(8.000, abs=0.001), (
        "1000.0 L finishing at 100.00 bar"
    )
    assert admitted["boiloff_kg"] == pytest.approx(0.000, abs=0.001)
    assert admitted["net_receipt_kg"] == pytest.approx(12.000, abs=0.001)
    assert read_station(station_id)["inbound_planned_kg"] == pytest.approx(40.000, abs=0.001), (
        "an arrived load is still inbound until it is offloaded"
    )


# ─── Nozzle capacity counts only active fills ─────────────────────────────


def test_the_single_nozzle_frees_up_the_moment_the_fill_completes():
    """The occupancy count spans PRECOOLING and FUELING only, not the finished row.

    "Then nozzle availability: the count of the station's sessions whose `fill_status`
    is `PRECOOLING` or `FUELING` must be strictly less than the station's `nozzle_count`,
    and a station whose every nozzle is occupied refuses with `ERR_NO_NOZZLE_AVAILABLE`
    (HTTP 409)."  "Alongside them, `reserved_kg` is the sum of `planned_kg` across the
    station's dispensing sessions whose `fill_status` is `PRECOOLING` or `FUELING`;
    `available_kg` is `onsite_inventory_kg` minus `reserved_kg`; `inbound_planned_kg` is
    the sum of `planned_kg` across the station's deliveries whose `status` is `SCHEDULED`
    or `ARRIVED`; `projected_available_kg` is `available_kg` plus `inbound_planned_kg`;
    and `supply_alert` is true exactly when `projected_available_kg` is strictly less than
    the station's `reserve_floor_kg`, and false otherwise."

    Design: Corner/validations/nozzle_capacity_is_an_aggregate_over_active_sessions_only
    """
    scenario = _station(
        "STN-V6", "Single Nozzle Station", (HIGH_VESSEL,), "H35", nozzle_count=1,
        offload_bay_count=1,
    )
    station_id = scenario["station"]["id"]
    first = create_session(station_id, **H35_BUS)
    assert first["fill_status"] == "PRECOOLING"

    refused = open_session(station_id, **H35_BUS)

    validate_error(refused, "ERR_NO_NOZZLE_AVAILABLE", expected_status=409)

    fuel_session(first["id"], station_id, -30.0)
    finished = complete_session(first["id"], station_id, 5.000, 700.00, 438.00)
    assert finished["fill_status"] == "COMPLETED"
    assert finished["corrected_kg"] == pytest.approx(5.000, abs=0.001), (
        "the correction factor is exactly one at ambient 20.0 and 700.00 bar"
    )
    assert finished["metering_error_pct"] == pytest.approx(0.000, abs=0.0005)

    second = validate_success(open_session(station_id, **H35_BUS), expected_status=201)

    assert second["fill_status"] == "PRECOOLING", "the completed row no longer holds the nozzle"
    station = read_station(station_id)
    assert station["onsite_inventory_kg"] == pytest.approx(40.600, abs=0.001)
    assert station["reserved_kg"] == pytest.approx(5.000, abs=0.001), (
        "only the new session reserves inventory"
    )


# ─── Two physical limits in their fixed order ─────────────────────────────


def test_the_vessel_pressure_limit_is_reported_ahead_of_the_storage_capacity():
    """A load breaching both limits reports the vessel; a smaller one reports the station.

    "Then two physical limits: the receiving vessel's `current_pressure_bar` plus
    `net_receipt_kg` divided by the product of the vessel's `water_volume_l` and 0.00008
    must be no greater than the vessel's `mawp_bar`, or `ERR_VESSEL_PRESSURE_LIMIT` (HTTP
    422) applies; and the station's `onsite_inventory_kg` plus `net_receipt_kg` must be no
    greater than its `storage_capacity_kg`, or `ERR_STORAGE_CAPACITY_EXCEEDED` (HTTP 422)
    applies."

    Design: Corner/validations/vessel_pressure_limit_is_checked_before_station_storage_capacity
    """
    scenario = _station(
        "STN-V7", "Tight Storage Station", (SMALL_LOW_VESSEL,), "H35", nozzle_count=2,
        storage_capacity_kg=20.000, reserve_floor_kg=5.000,
    )
    station_id = scenario["station"]["id"]
    vessel_id = scenario["vessels"]["LOW"]["id"]
    operator = make_station_operator_headers(station_id)
    lot = setup_small_released_lot()["lot"]
    big = _book(
        station_id, lot["id"], vessel_id, "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z",
        planned_kg=300.000, trailer_final_pressure_bar=750.00,
    )
    small = _book(
        station_id, lot["id"], vessel_id, "2026-08-02T12:00:00Z", "2026-08-02T16:00:00Z"
    )
    big = arrive_delivery(big["id"], at_clock="2026-08-02T10:00:00Z")
    small = arrive_delivery(small["id"], at_clock="2026-08-02T13:00:00Z")
    assert big["net_receipt_kg"] == pytest.approx(240.000, abs=0.001)
    assert small["net_receipt_kg"] == pytest.approx(12.000, abs=0.001)

    over_pressure = api_client.offload_delivery(big["id"], operator)
    over_capacity = api_client.offload_delivery(small["id"], operator)

    validate_error(over_pressure, "ERR_VESSEL_PRESSURE_LIMIT", expected_status=422)
    validate_error(over_capacity, "ERR_STORAGE_CAPACITY_EXCEEDED", expected_status=422)
    assert read_delivery(big["id"])["status"] == "ARRIVED"
    assert read_delivery(small["id"])["status"] == "ARRIVED"
    assert read_vessel(vessel_id)["current_pressure_bar"] == pytest.approx(300.00, abs=0.005)
    station = read_station(station_id)
    assert station["onsite_inventory_kg"] == pytest.approx(12.000, abs=0.001)
    consumed_nothing = read_lot(lot["id"])
    assert consumed_nothing["accepted_delivered_kg"] == pytest.approx(0.000, abs=0.001)
    assert consumed_nothing["status"] == "RELEASED"


# ─── A one-directional equipment limit ────────────────────────────────────


def test_an_h35_station_refuses_the_h70_target_and_accepts_the_h35_one():
    """The equipment ceiling is one-directional and leaves the station untouched.

    "Then equipment capability: an `H70` request at a station whose `max_pressure_class`
    is `H35` is refused with `ERR_PRESSURE_CLASS_UNSUPPORTED` (HTTP 422), a permanent
    configuration limit distinct from the temporary posture restriction above."  "For an
    `H35` fill it is −33.0 degrees in the hot band, −26.0 in the mild band and −17.0 in
    the cold band."

    Design: Corner/validations/h70_target_on_an_h35_station_is_rejected_while_h35_is_accepted
    """
    scenario = _station(
        "STN-V8", "H35 Only Station", (HIGH_VESSEL,), "H35", nozzle_count=2, offload_bay_count=1
    )
    station_id = scenario["station"]["id"]
    version_before = read_station_version(station_id)

    refused = open_session(
        station_id, vehicle_class="LIGHT_DUTY", target_pressure_class="H70",
        fill_protocol="SAE_J2601_TABLE", planned_kg=5.000, ambient_temp_c=20.0,
    )

    validate_error(refused, "ERR_PRESSURE_CLASS_UNSUPPORTED", expected_status=422)
    assert read_station_version(station_id) == version_before, (
        "the refused request leaves the station snapshot valid"
    )

    admitted = validate_success(open_session(station_id, **H35_BUS), expected_status=201)

    assert admitted["required_precool_c"] == pytest.approx(-26.0, abs=0.05), (
        "ambient 20.0 is the mild band for an H35 fill"
    )
    assert read_station(station_id)["reserved_kg"] == pytest.approx(5.000, abs=0.001), (
        "only the accepted session reserves inventory"
    )


# ─── The sampling boundary ────────────────────────────────────────────────


def test_a_sample_one_second_early_is_rejected_and_one_at_the_boundary_stands():
    """The comparison is at-or-after, so the production end instant itself is valid.

    "A sample cannot predate the end of the window that produced the hydrogen, so the
    test's `sampled_at` must be at or after the lot's `production_end_at`; an earlier
    sample is rejected with `ERR_SAMPLE_BEFORE_PRODUCTION_END` (HTTP 422)."  "A `PASS`
    sets the lot's `qa_status` to `PASSED` and leaves `status` at `PRODUCED`."

    Design: Corner/validations/purity_sample_before_production_end_is_rejected_at_the_second_boundary
    """
    scenario = setup_small_produced_lot(
        asset_overrides={
            "asset_code": "PA-V9",
            "pathway": "ALKALINE_ELECTROLYSIS",
            "nameplate_kg_per_day": 900.000,
        }
    )
    lot_id = scenario["lot"]["id"]
    assert scenario["lot"]["production_end_at"].startswith("2026-07-21T00:00:00")

    early = api_client.create_purity_test(
        lot_id,
        purity_test_payload(lot_id, **{**HALF_LIMIT_PURITY, "sampled_at": "2026-07-20T23:59:59Z"}),
        ANALYST,
    )

    validate_error(early, "ERR_SAMPLE_BEFORE_PRODUCTION_END", expected_status=422)
    assert read_lot(lot_id)["qa_status"] == "PENDING"
    assert list_meta(
        api_client.list_purity_tests(lot_id, ADMIN, params={"limit": 100, "offset": 0})
    )["total_count"] == 0, "the refused sample created no row"

    on_the_boundary = validate_success(
        api_client.create_purity_test(
            lot_id,
            purity_test_payload(
                lot_id, **{**HALF_LIMIT_PURITY, "sampled_at": "2026-07-21T00:00:00Z"}
            ),
            ANALYST,
        ),
        expected_status=201,
    )

    assert on_the_boundary["verdict"] == "PASS"
    assert on_the_boundary["purity_margin_pct"] == pytest.approx(50.000, abs=0.0005)
    passed = read_lot(lot_id)
    assert passed["qa_status"] == "PASSED"
    assert passed["status"] == "PRODUCED"
    listing = api_client.list_purity_tests(lot_id, ADMIN, params={"limit": 100, "offset": 0})
    assert list_meta(listing)["total_count"] == 1
    assert [row["id"] for row in list_rows(listing)] == [on_the_boundary["id"]]
