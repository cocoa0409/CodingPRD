"""Tests for FeeSchedule creation and validity window.

Covers: PRD Section 3.1 (Price lists / FeeSchedule), Table 1, Table 4 priority 22.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_fee_schedule,
    create_fee_schedule_payload,
    future_date, past_date,
    create_shelter,
)

_manager = TEST_USERS["manager_headers"]
_case_worker = TEST_USERS["case_worker_headers"]


class TestFeeScheduleCreation:
    """PRD 3.1: ShelterManager creates FeeSchedule rows."""

    def test_create_adoption_base_success(self):
        shelter = create_shelter()
        payload = create_fee_schedule_payload(
            shelter["id"], fee_type="ADOPTION_BASE", species="DOG",
            amount_cents=15000,
        )
        resp = api_client.create_fee_schedule(payload, _manager)
        data = validate_success(resp, 201)
        assert_fee_schedule(data)
        assert data["fee_type"] == "ADOPTION_BASE"
        assert data["species"] == "DOG"
        assert data["amount_cents"] == 15000
        assert data["is_currently_active"] is True

    def test_create_boarding_daily(self):
        shelter = create_shelter()
        payload = create_fee_schedule_payload(
            shelter["id"], fee_type="BOARDING_DAILY", species="ALL", amount_cents=2500
        )
        resp = api_client.create_fee_schedule(payload, _manager)
        data = validate_success(resp, 201)
        assert data["fee_type"] == "BOARDING_DAILY"

    def test_create_loyalty_discount_pct(self):
        """LOYALTY_DISCOUNT_PCT amount_cents stores an integer percentage."""
        shelter = create_shelter()
        payload = create_fee_schedule_payload(
            shelter["id"], fee_type="LOYALTY_DISCOUNT_PCT", species="ALL",
            amount_cents=15,
        )
        resp = api_client.create_fee_schedule(payload, _manager)
        data = validate_success(resp, 201)
        assert data["amount_cents"] == 15

    def test_create_invalid_dates(self):
        """effective_to <= effective_from returns ERR_INVALID_DATES."""
        shelter = create_shelter()
        payload = create_fee_schedule_payload(
            shelter["id"], fee_type="ADOPTION_BASE",
            effective_days_ago=5, effective_to_days_from_now=None,
        )
        # Override effective_to to be same as effective_from (violates strict >).
        payload["effective_to"] = payload["effective_from"]
        resp = api_client.create_fee_schedule(payload, _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_DATES)

    def test_create_shelter_not_found(self):
        payload = create_fee_schedule_payload(NON_EXISTENT_UUID)
        resp = api_client.create_fee_schedule(payload, _manager)
        validate_error(resp, ApiErrorId.ERR_SHELTER_NOT_FOUND)

    def test_create_invalid_fee_type(self):
        shelter = create_shelter()
        payload = create_fee_schedule_payload(shelter["id"], fee_type="MYSTERY_FEE")
        resp = api_client.create_fee_schedule(payload, _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestFeeScheduleValidity:
    """PRD 3.1: is_currently_active true iff current time ∈ [effective_from, effective_to)."""

    def test_currently_active_window(self):
        shelter = create_shelter()
        payload = create_fee_schedule_payload(
            shelter["id"], effective_days_ago=1, effective_to_days_from_now=30
        )
        data = get_success_data(api_client.create_fee_schedule(payload, _manager))
        assert data["is_currently_active"] is True

    def test_future_window_not_yet_active(self):
        shelter = create_shelter()
        payload = create_fee_schedule_payload(shelter["id"], effective_days_ago=0)
        # Make effective_from in future
        payload["effective_from"] = future_date(days=5)
        payload["effective_to"] = future_date(days=10)
        data = get_success_data(api_client.create_fee_schedule(payload, _manager))
        assert data["is_currently_active"] is False

    def test_past_window_expired(self):
        shelter = create_shelter()
        payload = create_fee_schedule_payload(
            shelter["id"], effective_days_ago=10, effective_to_days_from_now=None
        )
        payload["effective_to"] = past_date(days=1)
        data = get_success_data(api_client.create_fee_schedule(payload, _manager))
        assert data["is_currently_active"] is False

    def test_open_ended_null_effective_to(self):
        shelter = create_shelter()
        payload = create_fee_schedule_payload(
            shelter["id"], effective_days_ago=1, effective_to_days_from_now=None
        )
        payload["effective_to"] = None
        data = get_success_data(api_client.create_fee_schedule(payload, _manager))
        assert data["is_currently_active"] is True


class TestFeeScheduleRetrieval:
    def test_get_fee_schedule(self):
        shelter = create_shelter()
        fs = get_success_data(api_client.create_fee_schedule(
            create_fee_schedule_payload(shelter["id"]), _manager
        ))
        resp = api_client.get_fee_schedule(fs["id"], _manager)
        data = validate_success(resp)
        assert_fee_schedule(data)

    def test_get_fee_schedule_not_found(self):
        resp = api_client.get_fee_schedule(NON_EXISTENT_UUID, _manager)
        validate_error(resp, ApiErrorId.ERR_FEE_SCHEDULE_NOT_FOUND)

    def test_list_fee_schedules(self):
        shelter = create_shelter()
        get_success_data(api_client.create_fee_schedule(
            create_fee_schedule_payload(shelter["id"]), _manager
        ))
        resp = api_client.list_fee_schedules(_manager)
        validate_success(resp)
