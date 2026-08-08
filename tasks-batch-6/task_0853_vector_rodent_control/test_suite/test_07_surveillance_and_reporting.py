"""Bait stations, the composite rodent index and the program roll-up."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_bait_station,
    assert_posture_matches_index,
    bootstrap_registry,
    file_complaint,
    install_station,
    make_inspector_headers,
    record_reading,
    set_clock,
    setup_issued_order,
    setup_zone_with_station,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


def test_installed_station_copies_the_parcel_zone_and_counts_as_active(api):
    """PRD §3.8: "The station is created in status `ACTIVE`, its `zone_id` copied
    from the parcel and its `installed_at` stamped from the logical clock, with
    `last_reading_at` null, `reading_count` 0 and `cumulative_take_pct` 0.
    Installation raises the zone's `active_station_count` by one."
    PRD §3.8: "Stations can be read individually and listed with optional
    filters on `property_id`, on `zone_id` and on `status`."

    Design: Corner/entities/corner_bait_station_copies_zone_from_property
    """
    env = bootstrap_registry(inspectors=1, with_supervisor=False)
    inspector = make_inspector_headers(env["insp_id"])

    resp = api.create_bait_station(
        {"property_id": env["prop_id"], "station_code": "BS-01",
         "bait_type": "SNAP_TRAP"},
        inspector,
    )
    station = validate_success(resp, 201)
    assert_bait_station(station)
    assert station["zone_id"] == env["zone_id"]
    assert station["status"] == "ACTIVE"
    assert station["installed_at"] == "2026-05-04T09:00:00.000Z"
    assert station["reading_count"] == 0
    assert station["cumulative_take_pct"] == 0
    assert station["last_reading_at"] is None

    zone = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert zone["active_station_count"] == 1

    rows, meta = validate_paginated(
        api.list_bait_stations(ADMIN, params={"zone_id": env["zone_id"]})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_damaged_station_repairs_back_to_active(api):
    """PRD §3.8: "A condition of `DAMAGED` moves an `ACTIVE` station to
    `DAMAGED`; a condition of `INTACT` moves a `DAMAGED` station back to
    `ACTIVE`, which is the repair loop that makes the station lifecycle cyclic; a
    condition of `MISSING` moves a station to `REMOVED` from either `ACTIVE` or
    `DAMAGED`."
    PRD §3.8: "An accepted reading updates the station's `last_reading_at` to
    this reading's `reading_at`, raises `reading_count` by one, and adds this
    reading's `take_pct` to the running `cumulative_take_pct`."
    PRD §3.8: "`ACTIVE` and `DAMAGED` are both treated as eligible for
    surveillance purposes, so the repair loop does not disturb the zone's
    `active_station_count` in either direction."

    Design: Corner/state_machines/corner_bait_station_damage_then_repair_cycle
    """
    env = setup_zone_with_station(inspectors=1, with_supervisor=False)
    inspector = make_inspector_headers(env["insp_id"])
    record_reading(
        env["station_id"], env["insp_id"], take_pct=10, activity_sign_count=0,
        station_condition="INTACT", rebaited=True,
    )

    set_clock("2026-05-05T10:00:00Z")
    validate_success(
        api.create_reading(
            env["station_id"],
            {"take_pct": 20, "activity_sign_count": 2,
             "station_condition": "DAMAGED", "rebaited": False},
            inspector,
        ),
        201,
    )
    damaged = validate_success(api.get_bait_station(env["station_id"], inspector))
    assert damaged["status"] == "DAMAGED"

    set_clock("2026-05-06T11:00:00Z")
    validate_success(
        api.create_reading(
            env["station_id"],
            {"take_pct": 30, "activity_sign_count": 1,
             "station_condition": "INTACT", "rebaited": True},
            inspector,
        ),
        201,
    )
    repaired = validate_success(api.get_bait_station(env["station_id"], inspector))
    assert repaired["status"] == "ACTIVE"
    assert repaired["reading_count"] == 3
    assert repaired["cumulative_take_pct"] == 60
    assert repaired["last_reading_at"] == "2026-05-06T11:00:00.000Z"

    zone = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert zone["active_station_count"] == 1
    assert zone["rodent_index"] == pytest.approx(13.75, abs=0.001)


def test_removed_station_drops_out_of_the_index_and_takes_no_more_readings(api):
    """PRD §3.8: "A station whose status is already `REMOVED` accepts no further
    readings and rejects them with `ERR_STATION_DECOMMISSIONED`."
    PRD §3.8: "Reaching `REMOVED` is different: it drops the zone's
    `active_station_count` by one and, more consequentially, removes *all* of
    that station's historical readings from the surveillance input set, after
    which the zone's `rodent_index` and `posture` are recomputed."
    PRD §3.8: "The `posture` follows directly from the resulting index:
    `HOTSPOT` when the index is at least 70.00, otherwise `ELEVATED` when the
    index is at least 40.00, otherwise `NORMAL`."

    Design: Corner/state_machines/corner_removed_station_rejects_readings_and_drops_from_index
    """
    env = setup_zone_with_station(
        inspectors=1, with_supervisor=False, bait_type="ANTICOAGULANT"
    )
    inspector = make_inspector_headers(env["insp_id"])
    record_reading(
        env["station_id"], env["insp_id"], take_pct=80, activity_sign_count=0,
        station_condition="INTACT", rebaited=True,
    )
    before = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert before["rodent_index"] == pytest.approx(40.00, abs=0.001)
    assert before["posture"] == "ELEVATED"

    set_clock("2026-05-05T10:00:00Z")
    validate_success(
        api.create_reading(
            env["station_id"],
            {"take_pct": 0, "activity_sign_count": 0,
             "station_condition": "MISSING", "rebaited": False},
            inspector,
        ),
        201,
    )
    removed = validate_success(api.get_bait_station(env["station_id"], inspector))
    assert removed["status"] == "REMOVED"

    zone = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert zone["active_station_count"] == 0
    assert zone["rodent_index"] == pytest.approx(0.00, abs=0.001)
    assert zone["posture"] == "NORMAL"
    assert_posture_matches_index(zone)

    set_clock("2026-05-06T11:00:00Z")
    refused = api.create_reading(
        env["station_id"],
        {"take_pct": 50, "activity_sign_count": 3,
         "station_condition": "INTACT", "rebaited": True},
        inspector,
    )
    assert refused.status_code == 409
    validate_error(refused, ApiErrorId.ERR_STATION_DECOMMISSIONED.value)

    final = validate_success(api.get_bait_station(env["station_id"], inspector))
    assert final["reading_count"] == 2


def test_second_reading_inside_twenty_four_hours_is_refused(api):
    """PRD §3.8: "And a station may not be serviced again within 24 hours of its
    `last_reading_at`: a reading recorded strictly less than 24 hours after the
    previous one is refused with `ERR_READING_TOO_SOON`, while one recorded
    exactly 24 hours later is accepted."
    PRD §3.8: "An accepted reading updates the station's `last_reading_at` to
    this reading's `reading_at`, raises `reading_count` by one, and adds this
    reading's `take_pct` to the running `cumulative_take_pct`."

    Design: Corner/validations/corner_reading_inside_minimum_interval_rejected
    """
    env = setup_zone_with_station(inspectors=1, with_supervisor=False)
    inspector = make_inspector_headers(env["insp_id"])
    record_reading(
        env["station_id"], env["insp_id"], take_pct=30, activity_sign_count=1,
        station_condition="INTACT", rebaited=True,
    )

    set_clock("2026-05-05T08:00:00Z")
    too_soon = api.create_reading(
        env["station_id"],
        {"take_pct": 40, "activity_sign_count": 2,
         "station_condition": "INTACT", "rebaited": True},
        inspector,
    )
    assert too_soon.status_code == 409
    validate_error(too_soon, ApiErrorId.ERR_READING_TOO_SOON.value)
    assert validate_success(
        api.get_bait_station(env["station_id"], inspector)
    )["reading_count"] == 1

    set_clock("2026-05-05T09:00:00Z")
    accepted = api.create_reading(
        env["station_id"],
        {"take_pct": 40, "activity_sign_count": 2,
         "station_condition": "INTACT", "rebaited": True},
        inspector,
    )
    validate_success(accepted, 201)

    station = validate_success(api.get_bait_station(env["station_id"], inspector))
    assert station["reading_count"] == 2
    assert station["last_reading_at"] == "2026-05-05T09:00:00.000Z"
    assert station["cumulative_take_pct"] == 70


def test_program_summary_rolls_up_one_zone(api):
    """PRD §3.9: "The roll-up reports twelve figures. `complaint_total` is the
    number of complaints in scope and `complaint_open` the number of those not in
    any of the four closed statuses, while `complaint_closed_resolved` counts
    those in `CLOSED_RESOLVED` specifically. `orders_issued` is the number of
    abatement orders in scope regardless of their current status,
    `orders_complied` the number now in `COMPLIED`, and `orders_city_abated` the
    number now in `CITY_ABATED`."
    PRD §3.9: "On the money side, `invoiced_cents` is the sum of
    `final_total_cents` over invoices that have been approved (that is, those
    whose `billing_status` is `APPROVED`, `PARTIALLY_PAID` or `PAID`),
    `collected_cents` is the sum of `amount_paid_cents` over all invoices in
    scope, `outstanding_cents` is the sum of `balance_due_cents` over invoices
    whose `billing_status` is `APPROVED` or `PARTIALLY_PAID`, and `liens_filed`
    is the number of invoices in scope whose `lien_status` is `FILED`."
    PRD §3.9: "`chronic_property_count` is the number of parcels in scope whose
    `chronic_flag` is true, and `hotspot_zone_count` the number of zones in scope
    whose `posture` is `HOTSPOT` — which is 1 or 0 when the report is narrowed to
    one zone."

    Design: Corner/endpoints/corner_program_summary_report_rollup
    """
    env = setup_issued_order()
    summary = validate_success(
        api.get_program_summary(ADMIN, params={"zone_id": env["zone_id"]})
    )
    assert summary["complaint_total"] == 1
    assert summary["complaint_open"] == 1
    assert summary["complaint_closed_resolved"] == 0
    assert summary["orders_issued"] == 1
    assert summary["orders_complied"] == 0
    assert summary["orders_city_abated"] == 0
    assert summary["chronic_property_count"] == 1
    assert summary["hotspot_zone_count"] == 0
    assert summary["invoiced_cents"] == 0
    assert summary["collected_cents"] == 0
    assert summary["outstanding_cents"] == 0
    assert summary["liens_filed"] == 0


def _hotspot_reading_env():
    env = bootstrap_registry(inspectors=1, with_supervisor=False)
    file_complaint(
        env["prop_id"], complaint_type="RODENT_SIGHTING",
        reported_severity="ROUTINE",
        description="Rats crossing the sidewalk at dusk",
    )
    station = install_station(env["prop_id"], env["insp_id"])
    env["station_id"] = station["id"]
    set_clock("2026-05-06T09:00:00Z")
    record_reading(
        env["station_id"], env["insp_id"], take_pct=87, activity_sign_count=6,
        station_condition="INTACT", rebaited=True,
    )
    return env


def test_surveillance_summary_blends_the_three_components(api):
    """PRD §3.8: "Otherwise the **bait component** is the sum of `take_pct`
    across the window readings divided by the number of window readings, rounded
    half-up to two decimal places; and the **sign component** is the sum of
    `activity_sign_count` across the window readings divided by the number of
    window readings, multiplied by a scale factor of 12.5, capped at 100.0, and
    rounded half-up to two decimal places."
    PRD §3.8: "The three rounded components are then blended: the bait component
    weighted 0.50, the sign component weighted 0.30 and the complaint component
    weighted 0.20, and the weighted sum is rounded half-up to two decimal places
    once more."

    Design: Difficulty/combinatorial_formula/zone_rodent_index_three_component_nonlinear_blend
    """
    env = _hotspot_reading_env()
    summary = validate_success(api.get_surveillance_summary(env["zone_id"], ADMIN))
    assert summary["bait_component"] == pytest.approx(87.00, abs=0.001)
    assert summary["sign_component"] == pytest.approx(75.00, abs=0.001)
    assert summary["complaint_component"] == pytest.approx(20.00, abs=0.001)
    assert summary["rodent_index"] == pytest.approx(70.00, abs=0.001)
    assert summary["posture"] == "HOTSPOT"
    assert summary["in_window_reading_count"] == 1
    assert summary["eligible_station_count"] == 1


def test_zone_row_stores_the_recomputed_index_and_posture(api):
    """PRD §3.8: "The `posture` follows directly from the resulting index:
    `HOTSPOT` when the index is at least 70.00, otherwise `ELEVATED` when the
    index is at least 40.00, otherwise `NORMAL`."
    PRD §3.8: "Recomputation is triggered whenever a reading is recorded,
    whenever a bait station's status changes, whenever a complaint enters or
    leaves an open status — that is, at intake and at every closure or reopening
    — and on every read of the zone's surveillance summary."

    Design: Difficulty/combinatorial_formula/zone_rodent_index_three_component_nonlinear_blend
    """
    env = _hotspot_reading_env()
    zone = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert zone["rodent_index"] == pytest.approx(70.00, abs=0.001)
    assert zone["posture"] == "HOTSPOT"
    assert_posture_matches_index(zone)


def _thirty_day_window_env():
    env = bootstrap_registry(
        clock="2026-04-05T09:00:00Z", inspectors=1, with_supervisor=False,
        parcel_specs=[{"property_type": "VACANT_LOT"}],
    )
    station = install_station(
        env["prop_id"], env["insp_id"], bait_type="ANTICOAGULANT"
    )
    env["station_id"] = station["id"]
    record_reading(
        station["id"], env["insp_id"], take_pct=40, activity_sign_count=0,
        station_condition="INTACT", rebaited=True,
    )
    return env


def test_reading_exactly_thirty_days_old_is_inside_the_window(api):
    """PRD §3.8: "A zone's `rodent_index` is a weighted blend of three components
    measured over a closed 30-day window that ends at the current logical clock
    and begins exactly 30 days earlier; a reading or complaint sitting exactly on
    either boundary is inside the window."
    PRD §3.8: "The window readings are the readings of those eligible stations
    whose `reading_at` falls inside the window."

    Design: Difficulty/boundary_precision_check/surveillance_window_lower_bound_is_inclusive
    """
    env = _thirty_day_window_env()
    set_clock("2026-05-05T09:00:00Z")
    summary = validate_success(api.get_surveillance_summary(env["zone_id"], ADMIN))
    assert summary["in_window_reading_count"] == 1
    assert summary["bait_component"] == pytest.approx(40.00, abs=0.001)
    assert summary["sign_component"] == pytest.approx(0.00, abs=0.001)
    assert summary["complaint_component"] == pytest.approx(0.00, abs=0.001)
    assert summary["rodent_index"] == pytest.approx(20.00, abs=0.001)
    assert summary["posture"] == "NORMAL"


def test_reading_one_second_older_than_the_window_drops_out(api):
    """PRD §3.8: "A zone's `rodent_index` is a weighted blend of three components
    measured over a closed 30-day window that ends at the current logical clock
    and begins exactly 30 days earlier; a reading or complaint sitting exactly on
    either boundary is inside the window."
    PRD §3.8: "When there are no window readings at all, the bait component and
    the sign component are both exactly 0.00."

    Design: Difficulty/boundary_precision_check/surveillance_window_lower_bound_is_inclusive
    """
    env = _thirty_day_window_env()
    set_clock("2026-05-05T09:00:01Z")
    summary = validate_success(api.get_surveillance_summary(env["zone_id"], ADMIN))
    assert summary["in_window_reading_count"] == 0
    assert summary["bait_component"] == pytest.approx(0.00, abs=0.001)
    assert summary["rodent_index"] == pytest.approx(0.00, abs=0.001)
    assert summary["posture"] == "NORMAL"
    assert summary["window_start"] == "2026-04-05T09:00:01.000Z"

    zone = validate_success(api.get_zone(env["zone_id"], ADMIN))
    assert zone["rodent_index"] == pytest.approx(0.00, abs=0.001)
