"""
Tests for FeeSchedule CRUD.
Claims from Tables 1, 5, 6.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    assert_fee_schedule,
    create_fee_schedule_payload,
    create_shelter,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
)
from test_helpers.factories import _future_iso, _past_iso


class TestFeeScheduleCreation:
    """POST /fee-schedules."""

    def test_create_fee_schedule_success(self, api, manager_headers):
        """Create fee schedule entry with valid data -> 201."""
        shelter = create_shelter()
        payload = create_fee_schedule_payload(
            shelter["id"],
            fee_type="ADOPTION_BASE",
            species="DOG",
            amount=200.00,
        )
        res = api.create_fee_schedule(payload, manager_headers)
        schedule = validate_success(res, 201)
        assert_fee_schedule(schedule)
        assert schedule["fee_type"] == "ADOPTION_BASE"
        assert schedule["species"] == "DOG"
        assert schedule["amount"] == pytest.approx(200.00, abs=0.01)
        assert schedule["is_active"] is True

    def test_create_fee_schedule_invalid_dates(self, api, manager_headers):
        """effective_to before effective_from -> ERR_INVALID_DATES."""
        shelter = create_shelter()
        payload = create_fee_schedule_payload(
            shelter["id"],
            effective_from=_future_iso(days=30),
            effective_to=_past_iso(days=30),
        )
        res = api.create_fee_schedule(payload, manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_DATES)

    def test_get_nonexistent_fee_schedule(self, api, manager_headers):
        """ERR_FEE_SCHEDULE_NOT_FOUND."""
        res = api.get_fee_schedule(NON_EXISTENT_UUID, manager_headers)
        validate_error(res, ApiErrorId.ERR_FEE_SCHEDULE_NOT_FOUND)

    def test_create_fee_schedule_nonexistent_shelter(self, api, manager_headers):
        """FK to non-existent shelter -> ERR_SHELTER_NOT_FOUND."""
        payload = create_fee_schedule_payload(NON_EXISTENT_UUID)
        res = api.create_fee_schedule(payload, manager_headers)
        validate_error(res, ApiErrorId.ERR_SHELTER_NOT_FOUND)

    @pytest.mark.parametrize("missing_field", [
        "shelter_id", "fee_type", "species", "amount", "effective_from",
    ])
    def test_create_fee_schedule_missing_field(self, api, manager_headers, missing_field):
        """Missing required field -> ERR_INVALID_REQUEST."""
        shelter = create_shelter()
        payload = create_fee_schedule_payload(shelter["id"])
        del payload[missing_field]
        res = api.create_fee_schedule(payload, manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_list_fee_schedules(self, api, manager_headers):
        """GET /fee-schedules with filters."""
        shelter = create_shelter()
        api.create_fee_schedule(
            create_fee_schedule_payload(shelter["id"], fee_type="ADOPTION_BASE", species="DOG"),
            manager_headers,
        )
        data, meta = validate_paginated(
            api.list_fee_schedules(manager_headers, params={"shelter_id": shelter["id"]})
        )
        assert meta["total_count"] >= 1

    def test_fee_schedule_optional_effective_to(self, api, manager_headers):
        """effective_to is optional; omitting it means no end date."""
        shelter = create_shelter()
        payload = create_fee_schedule_payload(shelter["id"])
        del payload["effective_to"]
        res = api.create_fee_schedule(payload, manager_headers)
        schedule = validate_success(res, 201)
        assert schedule["is_active"] is True
