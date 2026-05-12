"""Station, ShelfZone, and Staff creation, defaults, and status changes.

PRD §3.1 ("Standing Up a Station").
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_shelf_zone,
    assert_staff,
    assert_station,
    create_shelf_zone_payload,
    create_staff_payload,
    create_station_payload,
    DEFAULT_FREE_STORAGE_HOURS,
    make_clerk_headers,
    make_manager_headers,
    setup_station_with_staff,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Station create
# ===========================================================================
class TestStationCreate:
    def test_create_station_minimal_uses_default_free_storage_hours(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "an optional free_storage_hours that defaults to
        72 hours when not supplied and must itself be at least one."

        Claim: omitting free_storage_hours yields a station whose
        free_storage_hours == 72.
        """
        payload = create_station_payload()
        payload.pop("free_storage_hours", None)
        resp = api.create_station(payload, platform_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_station(data)
        assert data["free_storage_hours"] == DEFAULT_FREE_STORAGE_HOURS

    def test_new_station_starts_active_and_zero_occupancy(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "Newly created stations start in ACTIVE status,
        with current_occupancy initialized to zero and quality_score
        initialized to null until the first quality assessment closes
        for the station."

        Claim: POST /stations response carries status=ACTIVE,
        current_occupancy=0, quality_score=null.
        """
        resp = api.create_station(
            create_station_payload(), platform_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"
        assert data["current_occupancy"] == 0
        assert data["quality_score"] is None

    @pytest.mark.parametrize("storage_capacity", [0, -1])
    def test_storage_capacity_below_one_rejected(
        self, api, platform_admin_headers, storage_capacity,
    ):
        """PRD §3.1: "A PlatformAdmin creates a station with a name between 1 and 100 characters, a free-form address, business hours given as business_hours_open and business_hours_close in the HH:MM 24-hour pattern (where the close time must be strictly later than the open time on the same day), a storage_capacity of at least one parcel, and an optional free_storage_hours that defaults to 72 hours when not supplied and must itself be at least one."

        Claim: storage_capacity < 1 surfaces as ERR_VALIDATION.
        """
        resp = api.create_station(
            create_station_payload(storage_capacity=storage_capacity),
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    @pytest.mark.parametrize("free_storage_hours", [0, -1])
    def test_free_storage_hours_below_one_rejected(
        self, api, platform_admin_headers, free_storage_hours,
    ):
        """PRD §3.1: "an optional free_storage_hours that defaults to 72 hours when not supplied and must itself be at least one."

        Claim: free_storage_hours < 1 surfaces as ERR_VALIDATION.
        """
        resp = api.create_station(
            create_station_payload(free_storage_hours=free_storage_hours),
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


# ===========================================================================
# Station status change
# ===========================================================================
class TestStationStatus:
    def test_suspended_station_blocks_inbound_with_err_station_not_active(
        self, api,
    ):
        """PRD §3.1: "When a station's status is not ACTIVE, every
        inbound and pickup action is rejected with ERR_STATION_NOT_ACTIVE
        (HTTP 409)."

        Claim: with the station SUSPENDED, POST /stations/{id}/parcels
        yields ERR_STATION_NOT_ACTIVE.
        """
        ctx = setup_station_with_staff(station_status="SUSPENDED")
        from test_helpers import register_parcel_payload
        payload = register_parcel_payload(
            shelf_zone_id=ctx["zone"]["id"],
            shelf_position="R01-C01",
        )
        resp = api.register_parcel(
            ctx["station"]["id"], payload, ctx["clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STATION_NOT_ACTIVE)

    def test_suspended_station_still_readable(self, api):
        """PRD §3.1: "list and read operations remain available while
        a station is SUSPENDED."

        Claim: GET /stations/{id} returns the station even when its
        status is SUSPENDED.
        """
        ctx = setup_station_with_staff(station_status="SUSPENDED")
        resp = api.get_station(
            ctx["station"]["id"], TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "SUSPENDED"


# ===========================================================================
# ShelfZone
# ===========================================================================
class TestShelfZone:
    def test_create_shelf_zone_capacity_is_rows_times_columns(self, api):
        """PRD §3.1: "The server derives the zone's capacity as the row
        count multiplied by the column count."

        Claim: POST /stations/{id}/shelf-zones returns capacity ==
        row_count * column_count.
        """
        ctx = setup_station_with_staff(create_zone=False)
        from test_helpers import create_shelf_zone
        zone = create_shelf_zone(
            ctx["station"]["id"], ctx["manager_headers"],
            row_count=3, column_count=4,
        )
        assert zone["capacity"] == 12
        assert_shelf_zone(zone)


# ===========================================================================
# Staff
# ===========================================================================
class TestStaff:
    def test_new_staff_lands_in_active(self, api):
        """PRD §3.1: "New staff land in ACTIVE status; managers may
        move staff to OFF_DUTY or TERMINATED."

        Claim: POST /stations/{id}/staff returns status=ACTIVE.
        """
        ctx = setup_station_with_staff()
        from test_helpers import create_staff_payload
        resp = api.create_staff(
            ctx["station"]["id"],
            create_staff_payload(role_kind="CLERK"),
            ctx["manager_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_staff(data)
        assert data["status"] == "ACTIVE"
