"""Facility onboarding, response envelope, pagination, and shared read surface."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_facility,
    assert_parking_session,
    create_access_device_payload,
    create_facility_payload,
    create_parker,
    create_parker_account_payload,
    create_rate_schedule_payload,
    enter_vehicle,
    enter_vehicle_at,
    get_success_data,
    make_gate_device_headers,
    make_monthly_parker_headers,
    pay_session_card_at,
    setup_entry_ready_facility,
    validate_error,
    validate_paginated,
    validate_success,
)

ATT = TEST_USERS["parking_attendant_headers"]


def test_create_facility_applies_defaults(api, facility_manager_headers):
    """PRD: "An optional `levy_pct` sets the fraction of the day's collections
    credited to the capital reserve at close-of-business; it defaults to 0.1 —
    ten percent — and must lie between 0 and 1 inclusive."
    PRD: "A new facility opens in posture `NORMAL` with `closed_spaces`,
    `capital_reserve_cents`, `deposit_liability_cents`, and
    `cumulative_collected_cents` at zero"
    PRD: "At startup the logical clock reads exactly 2026-08-01T00:00:00Z"

    Design: Corner/entities/create_facility_applies_defaults
    """
    payload = create_facility_payload(name="Defaults Fac", total_spaces=200,
                                      monthly_capacity=50, event_pool_spaces=40)
    assert "levy_pct" not in payload
    facility = validate_success(api.create_facility(payload, facility_manager_headers), 201)
    assert_facility(facility)
    assert facility["levy_pct"] == pytest.approx(0.1), "levy_pct default 0.1 applied"
    assert facility["posture"] == "NORMAL"
    assert facility["capital_reserve_cents"] == 0
    assert facility["deposit_liability_cents"] == 0
    assert facility["cumulative_collected_cents"] == 0
    assert facility["closed_spaces"] == 0
    assert facility["created_at"].startswith("2026-08-01T00:00:00"), (
        f"created_at must be read from the logical clock startup default, "
        f"got {facility['created_at']!r}")


def test_get_facility_not_found_returns_404(api, facility_manager_headers):
    """PRD: "the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
    first identifier that does not correspond to an existing resource"

    Design: Corner/entities/get_facility_not_found_returns_404
    """
    res = api.get_facility(NON_EXISTENT_UUID, facility_manager_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_facility_list_pagination_envelope(api, facility_manager_headers):
    """PRD: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/facility_list_pagination_envelope
    """
    for name in ("Pg A", "Pg B", "Pg C"):
        get_success_data(api.create_facility(
            create_facility_payload(name=name, total_spaces=10, monthly_capacity=1,
                                    event_pool_spaces=1), facility_manager_headers))
    data, meta = validate_paginated(api.list_facilities(
        facility_manager_headers, params={"limit": 2, "offset": 0}))
    assert len(data) == 2, f"limit=2 must return exactly 2 items, got {len(data)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_parker_account_creation_and_retrieval(api, facility_manager_headers):
    """PRD: "a `FacilityManager` or `ParkingAttendant` creates a parker account
    with the parker's `full_name` and contact `email`"
    PRD: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/entities/parker_account_creation_and_retrieval
    """
    created = validate_success(api.create_parker_account(
        create_parker_account_payload(full_name="Rita Reader", email="rita@x.com"),
        ATT), 201)
    retrieved = validate_success(api.get_parker_account(created["id"], facility_manager_headers), 200)
    assert retrieved["full_name"] == "Rita Reader"
    assert retrieved["email"] == "rita@x.com"
    assert retrieved["id"] == created["id"]


def test_create_rate_schedule_missing_required_returns_validation(api, facility_manager_headers):
    """PRD: "required fields present, enum values in range, numeric ranges
    respected (inspection ratings 1 through 5, strictly positive amounts where
    declared, and so on), else `ERR_VALIDATION`."
    PRD: "A `FacilityManager` drafts one against a `facility_id` with a human
    `label`, the lane parameters `grace_minutes`, `first_hour_cents`,
    `additional_hour_cents`, `daily_max_cents`"

    Design: Corner/entities/create_rate_schedule_missing_required_returns_validation
    """
    payload = create_rate_schedule_payload("placeholder")
    del payload["facility_id"]
    res = api.create_rate_schedule(payload, facility_manager_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_create_device_with_invalid_enum_rejected(api, facility_manager_headers):
    """PRD: "Access and revenue-control hardware is registered per facility
    with a `device_label` (for example, \"Entry Lane 1\") and a `device_kind`
    of `ENTRY_GATE`, `EXIT_GATE`, or `PAY_STATION`."
    PRD: "required fields present, enum values in range, numeric ranges
    respected (inspection ratings 1 through 5, strictly positive amounts where
    declared, and so on), else `ERR_VALIDATION`."

    Design: Corner/entities/create_device_with_invalid_enum_rejected
    """
    facility = validate_success(api.create_facility(
        create_facility_payload(name="Enum Fac", total_spaces=10, monthly_capacity=1,
                                event_pool_spaces=1), facility_manager_headers), 201)
    res = api.create_access_device(
        create_access_device_payload(facility["id"], device_label="Bad",
                                     device_kind="FOUNTAIN"),
        facility_manager_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_dashboard_computed_read_matches_sources(api, facility_manager_headers):
    """PRD: "Occupancy pressure is pure derivation: `occupied_spaces` counts
    the facility's sessions standing `PARKED`, `monthly_allocated` counts its
    agreements standing `ACTIVE` or `SUSPENDED`, and
    `available_transient_spaces` is `total_spaces` minus `closed_spaces` minus
    `occupied_spaces`."
    PRD: "A computed operational snapshot is available per facility, reporting
    `posture`, `occupied_spaces`, `closed_spaces`, `available_transient_spaces`,
    `monthly_allocated`, `monthly_capacity`, `capital_reserve_cents`,
    `deposit_liability_cents`, and `cumulative_collected_cents`."

    Design: Corner/entities/dashboard_computed_read_matches_sources
    """
    facility, schedule, gate = setup_entry_ready_facility(name="Dash Fac")
    s1 = enter_vehicle_at(facility["id"], gate, "DA-1", "2026-08-01T10:00:00Z")
    enter_vehicle(facility["id"], gate, "DA-2")
    enter_vehicle(facility["id"], gate, "DA-3")
    pay_session_card_at(s1["id"], "2026-08-01T11:00:00Z")
    get_success_data(api.exit_session(s1["id"], make_gate_device_headers(gate["id"])))

    dashboard = validate_success(api.get_facility_dashboard(facility["id"], facility_manager_headers), 200)
    assert dashboard["occupied_spaces"] == 2, "three entries minus one exit"
    assert dashboard["available_transient_spaces"] == 198, "200 total - 0 closed - 2 occupied"
    assert dashboard["cumulative_collected_cents"] == 500, "one 1h CARD settle"


def test_immediate_consistency_read_after_write(api, facility_manager_headers):
    """PRD: "A recorded entry stands `PARKED` with billing `OPEN`, `entry_at`
    read from the logical clock, the facility's effective `PUBLISHED` schedule
    pinned into `rate_schedule_id`"
    PRD: "The facility's `occupied_spaces` reflects the new arrival
    immediately, being derived on read."

    Design: Corner/consistency_model/immediate_consistency_read_after_write
    """
    facility, schedule, gate = setup_entry_ready_facility(name="IC Fac")
    session = enter_vehicle_at(facility["id"], gate, "IC-1", "2026-08-01T10:00:00Z")
    read = validate_success(api.get_parking_session(session["id"], facility_manager_headers), 200)
    assert_parking_session(read)
    assert read["occupancy_state"] == "PARKED"
    assert read["rate_schedule_id"] == schedule["id"], (
        "GET immediately after POST shows the schedule pinned at entry")


def test_all_roles_can_read_facility(api, facility_manager_headers):
    """PRD endpoint table: "| GET | `/ops/facilities/{facility_id}` | Get a
    facility | Any authenticated role |"
    PRD: "Once identified, the caller's role must appear in the endpoint's
    authorized role list; a caller whose role is not listed is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/all_roles_can_read_facility
    """
    facility = validate_success(api.create_facility(
        create_facility_payload(name="RB5 Fac"), facility_manager_headers), 201)
    parker = create_parker(full_name="Read Only", email="ro@x.com")
    res = api.get_facility(facility["id"], make_monthly_parker_headers(parker["id"]))
    data = validate_success(res, 200)
    assert data["name"] == "RB5 Fac", "MonthlyParker shares the read surface"
