"""Delivery transit losses, the lot-release gate on offload and offload-bay capacity."""

import pytest
from test_helpers import (
    ADMIN,
    DISPATCHER,
    api_client,
    arrive_delivery,
    add_emergency_responders,
    book_liquid_tanker_delivery,
    book_tube_trailer_delivery,
    certify_lot_ci,
    commission_bank,
    commission_vessel,
    create_production_asset,
    create_power_supply_contract,
    create_production_lot,
    list_meta,
    list_rows,
    make_station_operator_headers,
    read_delivery,
    read_lot,
    read_station,
    read_vessel,
    record_purity_test,
    release_lot,
    setup_canonical_produced_lot,
    setup_canonical_released_lot,
    setup_station,
    tube_trailer_delivery_payload,
    validate_error,
    validate_success,
    CANONICAL_ASSET,
    CANONICAL_CONTRACT,
    CANONICAL_LOT,
    CANONICAL_PURITY,
    STANDARD_BANK,
    STANDARD_BANK_ONSITE_KG,
)

# ─── Recipe builders ──────────────────────────────────────────────────────


def _two_modes_in_transit():
    """One tube-trailer and one liquid-tanker load booked into separate LOW vessels."""
    scenario = setup_station(
        station_overrides={"offload_bay_count": 1, "max_pressure_class": "H70"}
    )
    station_id = scenario["station"]["id"]
    high = commission_vessel(
        station_id,
        bank_tier="HIGH",
        water_volume_l=600.0,
        mawp_bar=1000.00,
        min_residual_bar=200.00,
        initial_pressure_bar=950.00,
        next_inspection_due_date="2027-06-30",
    )
    low_one = commission_vessel(
        station_id,
        bank_tier="LOW",
        water_volume_l=5000.0,
        mawp_bar=1000.00,
        min_residual_bar=100.00,
        initial_pressure_bar=300.00,
        next_inspection_due_date="2027-06-30",
    )
    low_two = commission_vessel(
        station_id,
        bank_tier="LOW",
        water_volume_l=5000.0,
        mawp_bar=1000.00,
        min_residual_bar=100.00,
        initial_pressure_bar=300.00,
        next_inspection_due_date="2027-06-30",
    )
    add_emergency_responders(station_id, count=2)
    lot = setup_canonical_released_lot()["lot"]

    trailer_load = book_tube_trailer_delivery(
        station_id,
        lot["id"],
        low_one["id"],
        planned_kg=300.000,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
        departed_at="2026-08-01T12:00:00Z",
        trailer_water_volume_l=2500.0,
        trailer_final_pressure_bar=210.00,
    )
    tanker_load = book_liquid_tanker_delivery(
        station_id,
        lot["id"],
        low_two["id"],
        planned_kg=200.000,
        window_start="2026-08-02T06:00:00Z",
        window_end="2026-08-02T12:00:00Z",
        departed_at="2026-08-01T14:00:00Z",
    )
    return {
        "station": read_station(station_id),
        "vessels": {"HIGH": high, "LOW_1": low_one, "LOW_2": low_two},
        "trailer": trailer_load,
        "tanker": tanker_load,
    }


def _arrive_both_loads(scenario):
    trailer = arrive_delivery(scenario["trailer"]["id"], at_clock="2026-08-02T02:00:00Z")
    tanker = arrive_delivery(scenario["tanker"]["id"], at_clock="2026-08-02T08:00:00Z")
    return trailer, tanker


def _arrived_load_against_an_unreleased_lot():
    """A tube-trailer load standing ARRIVED while its lot is still only PRODUCED."""
    scenario = setup_station(
        station_overrides={"offload_bay_count": 1, "max_pressure_class": "H70"}
    )
    station_id = scenario["station"]["id"]
    scenario["vessels"] = commission_bank(
        station_id, STANDARD_BANK, next_inspection_due_date="2027-06-30"
    )
    add_emergency_responders(station_id, count=2)

    lot_scenario = setup_canonical_produced_lot()
    lot_id = lot_scenario["lot"]["id"]
    purity = record_purity_test(lot_id, **CANONICAL_PURITY)
    certified = certify_lot_ci(lot_id)

    delivery = book_tube_trailer_delivery(
        station_id,
        lot_id,
        scenario["vessels"]["MEDIUM"]["id"],
        planned_kg=60.000,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
        departed_at="2026-08-01T12:00:00Z",
        trailer_water_volume_l=2500.0,
        trailer_final_pressure_bar=210.00,
    )
    delivery = arrive_delivery(delivery["id"], at_clock="2026-08-02T02:00:00Z")
    scenario["purity_test"] = purity
    scenario["lot"] = certified
    scenario["delivery"] = delivery
    scenario["operator"] = make_station_operator_headers(station_id)
    return scenario


def _two_bay_station_with_two_overlapping_windows():
    """A two-bay station already carrying two windows that overlap each other."""
    scenario = setup_station(
        station_overrides={
            "nozzle_count": 4,
            "offload_bay_count": 2,
            "storage_capacity_kg": 900.000,
            "reserve_floor_kg": 100.000,
            "max_pressure_class": "H70",
        }
    )
    station_id = scenario["station"]["id"]
    vessel = commission_vessel(
        station_id,
        bank_tier="MEDIUM",
        water_volume_l=1000.0,
        mawp_bar=1000.00,
        min_residual_bar=150.00,
        initial_pressure_bar=700.00,
        next_inspection_due_date="2027-06-30",
    )
    asset = create_production_asset(**CANONICAL_ASSET)
    create_power_supply_contract(asset["id"], **CANONICAL_CONTRACT)
    lot = create_production_lot(asset["id"], **CANONICAL_LOT)

    windows = (("2026-08-02T00:00:00Z", "2026-08-02T06:00:00Z"),
               ("2026-08-02T02:00:00Z", "2026-08-02T08:00:00Z"))
    booked = [
        book_tube_trailer_delivery(
            station_id,
            lot["id"],
            vessel["id"],
            planned_kg=10.000,
            window_start=start,
            window_end=end,
            departed_at="2026-08-01T12:00:00Z",
            trailer_water_volume_l=2500.0,
            trailer_final_pressure_bar=210.00,
        )
        for start, end in windows
    ]
    scenario["vessel"] = vessel
    scenario["lot"] = lot
    scenario["booked"] = booked
    return scenario


def _book_window(scenario, window_start, window_end):
    return api_client.create_delivery(
        tube_trailer_delivery_payload(
            scenario["station"]["id"],
            scenario["lot"]["id"],
            scenario["vessel"]["id"],
            planned_kg=10.000,
            window_start=window_start,
            window_end=window_end,
            departed_at="2026-08-01T12:00:00Z",
            trailer_water_volume_l=2500.0,
            trailer_final_pressure_bar=210.00,
        ),
        DISPATCHER,
    )


# ─── Transit-loss variants ────────────────────────────────────────────────


def test_trailer_heel_and_tanker_boiloff_are_computed_from_different_inputs():
    """Each transport mode loses hydrogen by its own mechanism.

    "Under `TUBE_TRAILER`, the loss is the residual **heel** left in the tubes:
    `heel_kg` is the `trailer_final_pressure_bar` multiplied by the
    `trailer_water_volume_l` and by 0.00008 kilograms per litre per bar, rounded
    half-up to three decimal places, and `boiloff_kg` is 0.000."  "Under
    `LIQUID_TANKER`, the loss is **boil-off** accumulating linearly with transit
    time: `heel_kg` is 0.000, and `boiloff_kg` is the `planned_kg` multiplied by a
    daily boil-off rate of 0.003, multiplied by `transit_hours`, divided by
    twenty-four, and rounded half-up to three decimal places."

    Design: Difficulty/dual_variant_calc/delivery_loss_tube_trailer_heel_versus_liquid_tanker_boiloff
    """
    scenario = _two_modes_in_transit()

    trailer, tanker = _arrive_both_loads(scenario)

    assert trailer["transit_hours"] == pytest.approx(14.000, abs=0.001)
    assert trailer["heel_kg"] == pytest.approx(42.000, abs=0.001), (
        "2500.0 L finishing at 210.00 bar leaves 42.000 kg behind"
    )
    assert trailer["boiloff_kg"] == pytest.approx(0.000, abs=0.001)
    assert trailer["net_receipt_kg"] == pytest.approx(258.000, abs=0.001)

    assert tanker["transit_hours"] == pytest.approx(18.000, abs=0.001)
    assert tanker["heel_kg"] == pytest.approx(0.000, abs=0.001)
    assert tanker["boiloff_kg"] == pytest.approx(0.450, abs=0.001), (
        "200.000 kg boiling off for 18 of 24 hours loses 0.450 kg"
    )
    assert tanker["net_receipt_kg"] == pytest.approx(199.550, abs=0.001)


def test_the_two_transport_modes_produce_different_loss_ratios():
    """Geometry-driven heel and time-driven boil-off are not interchangeable.

    The heel "is a function of trailer geometry and final pressure alone and is
    completely independent of how long the trailer was on the road", whereas the
    boil-off "is completely independent of trailer geometry".  "In both modes,
    `net_receipt_kg` — the mass that will actually be credited to station
    inventory — is the `planned_kg` minus `heel_kg` minus `boiloff_kg`, rounded
    half-up to three decimal places."

    Design: Difficulty/dual_variant_calc/delivery_loss_tube_trailer_heel_versus_liquid_tanker_boiloff
    """
    scenario = _two_modes_in_transit()

    trailer, tanker = _arrive_both_loads(scenario)

    trailer_ratio = trailer["net_receipt_kg"] / trailer["planned_kg"]
    tanker_ratio = tanker["net_receipt_kg"] / tanker["planned_kg"]
    assert trailer_ratio == pytest.approx(0.860, abs=0.001)
    assert tanker_ratio == pytest.approx(0.997750, abs=0.000001)
    assert trailer_ratio != pytest.approx(tanker_ratio, abs=0.001), (
        "one mechanism keeps 86.0 % of the load and the other keeps 99.775 %"
    )
    assert trailer["status"] == "ARRIVED"
    assert tanker["status"] == "ARRIVED"


# ─── The lot-release gate on offload ──────────────────────────────────────


def test_offload_is_refused_while_the_referenced_lot_is_unreleased():
    """An arrived load cannot be accepted from a lot that is still PRODUCED.

    "The delivery's lot must have reached `RELEASED`; a lot still `PRODUCED`,
    already `REJECTED`, or already `CONSUMED` blocks the receipt with
    `ERR_LOT_NOT_RELEASED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/delivery_offload_blocked_until_production_lot_reaches_released
    """
    scenario = _arrived_load_against_an_unreleased_lot()
    assert scenario["purity_test"]["verdict"] == "PASS"
    assert scenario["lot"]["status"] == "PRODUCED"
    assert scenario["lot"]["ci_status"] == "CERTIFIED"
    assert scenario["delivery"]["status"] == "ARRIVED"
    assert scenario["delivery"]["heel_kg"] == pytest.approx(42.000, abs=0.001)
    assert scenario["delivery"]["net_receipt_kg"] == pytest.approx(18.000, abs=0.001)

    response = api_client.offload_delivery(
        scenario["delivery"]["id"], scenario["operator"]
    )

    validate_error(response, "ERR_LOT_NOT_RELEASED", expected_status=422)

    unchanged = read_delivery(scenario["delivery"]["id"])
    assert unchanged["status"] == "ARRIVED"
    assert unchanged.get("accepted_at") is None
    station = read_station(scenario["station"]["id"])
    assert station["onsite_inventory_kg"] == pytest.approx(
        STANDARD_BANK_ONSITE_KG, abs=0.001
    ), "a refused offload moves no hydrogen"
    assert read_vessel(scenario["vessels"]["MEDIUM"]["id"])[
        "current_pressure_bar"
    ] == pytest.approx(700.00, abs=0.01)


def test_releasing_the_lot_unblocks_the_identical_offload_request():
    """Releasing the sibling lot makes the same offload succeed and writes back to it.

    "A lot tracks `accepted_delivered_kg`, the sum of `net_receipt_kg` over every
    delivery of that lot whose `status` is `ACCEPTED`."  And 18.000 kg falls far
    below ninety percent of the lot's 1000.000 kg: "A lot below that threshold stays
    `RELEASED` and remains available for further deliveries."

    Design: Difficulty/cross_entity_state_dependency/delivery_offload_blocked_until_production_lot_reaches_released
    """
    scenario = _arrived_load_against_an_unreleased_lot()
    validate_error(
        api_client.offload_delivery(scenario["delivery"]["id"], scenario["operator"]),
        "ERR_LOT_NOT_RELEASED",
        expected_status=422,
    )

    released = release_lot(scenario["lot"]["id"])
    assert released["status"] == "RELEASED"

    accepted = validate_success(
        api_client.offload_delivery(scenario["delivery"]["id"], scenario["operator"]),
        expected_status=200,
    )

    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_at"].startswith("2026-08-02T02:00:00")
    vessel = read_vessel(scenario["vessels"]["MEDIUM"]["id"])
    assert vessel["current_pressure_bar"] == pytest.approx(925.00, abs=0.01)
    assert vessel["stored_mass_kg"] == pytest.approx(74.000, abs=0.001)
    station = read_station(scenario["station"]["id"])
    assert station["onsite_inventory_kg"] == pytest.approx(239.600, abs=0.001)
    lot = read_lot(scenario["lot"]["id"])
    assert lot["accepted_delivered_kg"] == pytest.approx(18.000, abs=0.001)
    assert lot["status"] == "RELEASED"


# ─── Offload-bay aggregate capacity ───────────────────────────────────────


def test_a_third_simultaneous_window_exhausts_the_two_offload_bays():
    """Two bays absorb two overlapping windows and refuse the third.

    "That last check is an aggregate-capacity test rather than a pairwise one:
    count the station's other deliveries whose `status` is `SCHEDULED` or
    `ARRIVED` and whose half-open window from `window_start` inclusive to
    `window_end` exclusive intersects the requested window; the booking is
    accepted only while that count is strictly less than the station's
    `offload_bay_count`."

    Design: Difficulty/resource_temporal_overlap/offload_bay_aggregate_capacity_two_bays_with_half_open_windows
    """
    scenario = _two_bay_station_with_two_overlapping_windows()
    assert [row["status"] for row in scenario["booked"]] == ["SCHEDULED", "SCHEDULED"], (
        "two bays absorb two mutually overlapping windows"
    )

    response = _book_window(scenario, "2026-08-02T03:00:00Z", "2026-08-02T05:00:00Z")

    validate_error(response, "ERR_OFFLOAD_BAY_CONFLICT", expected_status=409)
    listing = api_client.list_deliveries(
        ADMIN, params={"station_id": scenario["station"]["id"], "limit": 100, "offset": 0}
    )
    assert list_meta(listing)["total_count"] == 2, "the refused booking created no row"


def test_a_window_touching_an_existing_window_end_sees_only_one_occupant():
    """A window starting exactly when another ends does not consume that bay.

    "Windows that merely touch — where an existing window's `window_end` exactly
    equals the new window's `window_start` — do not intersect and do not consume
    a bay."

    Design: Difficulty/resource_temporal_overlap/offload_bay_aggregate_capacity_two_bays_with_half_open_windows
    """
    scenario = _two_bay_station_with_two_overlapping_windows()
    validate_error(
        _book_window(scenario, "2026-08-02T03:00:00Z", "2026-08-02T05:00:00Z"),
        "ERR_OFFLOAD_BAY_CONFLICT",
        expected_status=409,
    )

    admitted = validate_success(
        _book_window(scenario, "2026-08-02T06:00:00Z", "2026-08-02T10:00:00Z"),
        expected_status=201,
    )

    assert admitted["status"] == "SCHEDULED"
    listing = api_client.list_deliveries(
        ADMIN, params={"station_id": scenario["station"]["id"], "limit": 100, "offset": 0}
    )
    rows = list_rows(listing)
    assert list_meta(listing)["total_count"] == 3
    assert {row["status"] for row in rows} == {"SCHEDULED"}
    station = read_station(scenario["station"]["id"])
    assert station["inbound_planned_kg"] == pytest.approx(30.000, abs=0.001)
    assert station["projected_available_kg"] == pytest.approx(86.000, abs=0.001)
    assert station["supply_alert"] is True, (
        "56.000 kg on site plus 30.000 kg inbound is below the 100.000 kg floor"
    )
