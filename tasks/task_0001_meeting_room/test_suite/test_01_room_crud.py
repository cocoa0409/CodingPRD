"""Test Room CRUD operations and field validation.

Covers:
- Room creation with all required fields (Table 5: POST /rooms)
- Room retrieval (GET /rooms/{room_id})
- Room listing with filters (GET /rooms)
- Room update (PUT /rooms/{room_id})
- Field defaults (peak_multiplier defaults to 1.0)
- Room name uniqueness (ERR_ROOM_NAME_TAKEN)
- Missing required fields (ERR_BAD_REQUEST)
- Not-found errors (ERR_ROOM_NOT_FOUND)
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, is_valid_uuid, is_iso8601_timestamp, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    assert_room,
    create_room_payload, create_premium_room_payload,
    create_standard_room, create_premium_room,
)


_admin = TEST_USERS["facility_admin_headers"]
_employee = TEST_USERS["employee_headers"]
_manager = TEST_USERS["manager_headers"]


class TestCreateRoom:
    """POST /rooms"""

    def test_create_standard_room_success(self):
        """Create a STANDARD room with all fields. Verify 201, status=ACTIVE, ops_run_index=0."""
        payload = create_room_payload(tier="STANDARD")
        resp = api_client.create_room(payload, _admin)
        data = validate_success(resp, 201)
        assert_room(data)
        assert data["status"] == "ACTIVE"
        assert data["tier"] == "STANDARD"
        assert data["ops_run_index"] == 0
        assert data["version"] == 1
        assert data["name"] == payload["name"]
        assert data["capacity"] == payload["capacity"]
        assert data["floor"] == payload["floor"]
        assert data["hourly_rate_cents"] == payload["hourly_rate_cents"]

    def test_create_premium_room_success(self):
        """Create a PREMIUM room. Verify tier=PREMIUM."""
        payload = create_premium_room_payload()
        resp = api_client.create_room(payload, _admin)
        data = validate_success(resp, 201)
        assert_room(data)
        assert data["tier"] == "PREMIUM"
        assert data["status"] == "ACTIVE"

    def test_create_room_with_amenities(self):
        """Room created with amenities list is returned with those amenities."""
        amenities = ["PROJECTOR", "VIDEO_CONF", "PHONE"]
        payload = create_room_payload(amenities=amenities)
        resp = api_client.create_room(payload, _admin)
        data = validate_success(resp, 201)
        assert set(data["amenities"]) == set(amenities)

    def test_create_room_without_optional_fields(self):
        """Create room without peak_multiplier, peak_hours_start, peak_hours_end, amenities."""
        payload = {
            "name": f"Minimal-{__import__('uuid').uuid4().hex[:8]}",
            "capacity": 5,
            "floor": 2,
            "tier": "STANDARD",
            "hourly_rate_cents": 3000,
        }
        resp = api_client.create_room(payload, _admin)
        data = validate_success(resp, 201)
        assert_room(data)
        # peak_multiplier should default to 1.0
        if data.get("peak_multiplier") is not None:
            assert data["peak_multiplier"] == pytest.approx(1.0, abs=0.01)

    def test_create_room_duplicate_name(self):
        """Creating a room with a name that already exists -> ERR_ROOM_NAME_TAKEN."""
        payload = create_room_payload()
        resp1 = api_client.create_room(payload, _admin)
        validate_success(resp1, 201)

        payload2 = create_room_payload(name=payload["name"])
        resp2 = api_client.create_room(payload2, _admin)
        validate_error(resp2, ApiErrorId.ERR_ROOM_NAME_TAKEN)

    @pytest.mark.parametrize("missing_field", ["name", "capacity", "floor", "tier", "hourly_rate_cents"])
    def test_create_room_missing_required_field(self, missing_field):
        """Omitting a required field -> ERR_BAD_REQUEST."""
        payload = create_room_payload()
        del payload[missing_field]
        resp = api_client.create_room(payload, _admin)
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST)

    def test_create_room_employee_forbidden(self):
        """Employee cannot create rooms -> ERR_FORBIDDEN."""
        payload = create_room_payload()
        resp = api_client.create_room(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_create_room_manager_forbidden(self):
        """Manager cannot create rooms -> ERR_FORBIDDEN."""
        payload = create_room_payload()
        resp = api_client.create_room(payload, _manager)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestGetRoom:
    """GET /rooms/{room_id}"""

    def test_get_room_success(self):
        """Retrieve a room by ID. All fields match creation."""
        room = create_standard_room()
        resp = api_client.get_room(room["id"], _employee)
        data = validate_success(resp, 200)
        assert_room(data)
        assert data["id"] == room["id"]
        assert data["name"] == room["name"]

    def test_get_room_not_found(self):
        """Non-existent room_id -> ERR_ROOM_NOT_FOUND."""
        resp = api_client.get_room(NON_EXISTENT_UUID, _employee)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_FOUND)

    def test_get_room_any_role(self):
        """All three roles can read a room."""
        room = create_standard_room()
        for headers in [_employee, _manager, _admin]:
            resp = api_client.get_room(room["id"], headers)
            validate_success(resp, 200)


class TestListRooms:
    """GET /rooms"""

    def test_list_rooms_success(self):
        """List rooms returns a paginated array."""
        create_standard_room()
        resp = api_client.list_rooms(_employee)
        items, _ = validate_paginated(resp)
        assert len(items) >= 1

    def test_list_rooms_filter_by_status(self):
        """Filter rooms by status=ACTIVE."""
        room = create_standard_room()
        resp = api_client.list_rooms(_employee, params={"status": "ACTIVE"})
        items, _ = validate_paginated(resp)
        for item in items:
            assert item["status"] == "ACTIVE"

    def test_list_rooms_filter_by_tier(self):
        """Filter rooms by tier=PREMIUM."""
        create_premium_room()
        resp = api_client.list_rooms(_employee, params={"tier": "PREMIUM"})
        items, _ = validate_paginated(resp)
        for item in items:
            assert item["tier"] == "PREMIUM"

    def test_list_rooms_filter_by_min_capacity(self):
        """Filter rooms by min_capacity."""
        room = create_standard_room(capacity=50)
        resp = api_client.list_rooms(_employee, params={"min_capacity": 50})
        items, _ = validate_paginated(resp)
        for item in items:
            assert item["capacity"] >= 50

    def test_list_rooms_filter_by_floor(self):
        """Filter rooms by floor."""
        room = create_standard_room(floor=99)
        resp = api_client.list_rooms(_employee, params={"floor": 99})
        items, _ = validate_paginated(resp)
        for item in items:
            assert item["floor"] == 99

    def test_list_rooms_pagination(self):
        """Paginated listing with limit and offset."""
        for _ in range(3):
            create_standard_room()
        resp = api_client.list_rooms(_employee, params={"limit": 2, "offset": 0})
        items, _ = validate_paginated(resp)
        assert len(items) <= 2


class TestUpdateRoom:
    """PUT /rooms/{room_id}"""

    def test_update_room_name(self):
        """Update room name. Version increments."""
        room = create_standard_room()
        new_name = f"Updated-{__import__('uuid').uuid4().hex[:8]}"
        resp = api_client.update_room(room["id"], {"name": new_name}, _admin)
        data = validate_success(resp, 200)
        assert data["name"] == new_name
        assert data["version"] > room["version"]

    def test_update_room_capacity(self):
        """Update room capacity."""
        room = create_standard_room(capacity=10)
        resp = api_client.update_room(room["id"], {"capacity": 20}, _admin)
        data = validate_success(resp, 200)
        assert data["capacity"] == 20

    def test_update_room_tier(self):
        """Update room tier from STANDARD to PREMIUM."""
        room = create_standard_room()
        resp = api_client.update_room(room["id"], {"tier": "PREMIUM"}, _admin)
        data = validate_success(resp, 200)
        assert data["tier"] == "PREMIUM"

    def test_update_room_pricing(self):
        """Update hourly_rate_cents and peak_multiplier."""
        room = create_standard_room()
        resp = api_client.update_room(
            room["id"],
            {"hourly_rate_cents": 9000, "peak_multiplier": 2.0},
            _admin,
        )
        data = validate_success(resp, 200)
        assert data["hourly_rate_cents"] == 9000
        assert data["peak_multiplier"] == pytest.approx(2.0, abs=0.01)

    def test_update_room_not_found(self):
        """Updating non-existent room -> ERR_ROOM_NOT_FOUND."""
        resp = api_client.update_room(NON_EXISTENT_UUID, {"name": "X"}, _admin)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_FOUND)

    def test_update_room_employee_forbidden(self):
        """Employee cannot update rooms -> ERR_FORBIDDEN."""
        room = create_standard_room()
        resp = api_client.update_room(room["id"], {"name": "X"}, _employee)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_update_room_duplicate_name(self):
        """Updating room name to an existing name -> ERR_ROOM_NAME_TAKEN."""
        room1 = create_standard_room()
        room2 = create_standard_room()
        resp = api_client.update_room(room2["id"], {"name": room1["name"]}, _admin)
        validate_error(resp, ApiErrorId.ERR_ROOM_NAME_TAKEN)

    def test_update_room_version_conflict(self):
        """Optimistic concurrency: stale version -> ERR_VERSION_CONFLICT."""
        room = create_standard_room()
        # First update succeeds
        api_client.update_room(room["id"], {"capacity": 15, "version": room["version"]}, _admin)
        # Second update with same (now stale) version fails
        resp = api_client.update_room(room["id"], {"capacity": 20, "version": room["version"]}, _admin)
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT)
