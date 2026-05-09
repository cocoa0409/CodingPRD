"""
Tests covering basic CRUD, response envelope shape, common-field semantics,
and 4xx-on-bad-input for the shared-power-bank API.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    MODEL_TOTAL_SLOTS,
    NON_EXISTENT_UUID,
    OPERATOR_HEADERS,
    api_client,
    assert_cabinet,
    assert_device,
    assert_location_partner,
    assert_pricing_plan,
    assert_user,
    create_cabinet_payload,
    create_device_payload,
    create_location_partner_payload,
    create_pricing_plan_payload,
    create_user_payload,
    create_location_partner,
    create_pricing_plan,
    setup_cabinet_with_device,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------


def test_success_envelope_shape_on_create_partner(api):
    """PRD §2.2: success envelope has meta with api_request_id (prefix req_),
    api_request_timestamp (ISO 8601 with three fractional digits), response_type,
    and data.
    """
    res = api.create_location_partner(
        create_location_partner_payload(), ADMIN_HEADERS
    )
    body = res.json()
    assert res.status_code == 201, body
    assert "meta" in body
    assert body["meta"]["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in body["meta"]
    assert body["response_type"] == "object"
    assert "data" in body
    assert_location_partner(body["data"])


def test_error_envelope_shape_on_unknown_path(api):
    """PRD §2.2: error envelope carries response_type='error' and
    data.error_id + data.message."""
    res = api.get_cabinet(NON_EXISTENT_UUID, ADMIN_HEADERS)
    body = res.json()
    assert res.status_code == 404
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str)


# ---------------------------------------------------------------------------
# Common fields (PRD §2.4)
# ---------------------------------------------------------------------------


def test_common_fields_on_partner(api):
    """PRD §2.4: every entity that carries common fields exposes id,
    created_at, updated_at, version (initialized to 1)."""
    partner = validate_success(
        api.create_location_partner(create_location_partner_payload(), ADMIN_HEADERS),
        201,
    )
    assert partner["version"] == 1
    assert partner["created_at"] == partner["updated_at"]


def test_payment_event_omits_updated_at_and_version(api):
    """PRD §2.4: "only PaymentEvent does not carry the common fields; a
    PaymentEvent exposes id and created_at only, and has neither updated_at
    nor version."
    """
    env = setup_cabinet_with_device()
    # Create a rental so we have a real rental_id to attach the event to.
    from test_helpers import setup_borrow_environment, borrow_for

    benv = setup_borrow_environment()
    rental = borrow_for(benv["user"], benv["cabinet"]["id"])
    res = api.post_payment_event(
        {
            "idempotency_key": "idem-pe-1",
            "event_type": "PAYMENT_CONFIRMED",
            "rental_id": rental["id"],
            "amount": 3.00,
            "occurred_at": "2026-01-01T10:00:00Z",
        }
    )
    body = res.json()
    assert res.status_code == 200, body
    pe = body["data"]
    assert "id" in pe and "created_at" in pe
    assert "updated_at" not in pe, "PaymentEvent must not have updated_at (PRD §2.4)"
    assert "version" not in pe, "PaymentEvent must not have version (PRD §2.4)"


# ---------------------------------------------------------------------------
# total_slots derived from model (PRD §3.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model,expected_slots", [
    ("SLOT_8", 8),
    ("SLOT_16", 16),
    ("SLOT_24", 24),
])
def test_total_slots_derived_from_model(api, model, expected_slots):
    """PRD §3.1: "The server derives total_slots directly from the model —
    eight, sixteen, or twenty-four respectively."
    """
    partner = create_location_partner()
    create_pricing_plan(city_code="BJ")
    payload = create_cabinet_payload(partner["id"], model=model)
    cab = validate_success(api.create_cabinet(payload, ADMIN_HEADERS), 201)
    assert_cabinet(cab)
    assert cab["total_slots"] == expected_slots
    # The server should ignore total_slots if the user passed it.
    assert cab["total_slots"] == MODEL_TOTAL_SLOTS[model]


def test_cabinet_creates_slot_rows_in_empty_state(api):
    """PRD §3.1: "auto-creates one Slot row per index in the half-open range
    starting at zero up to total_slots. Every freshly-created slot has its
    slot_status initialised to EMPTY and its device_id set to null."
    """
    create_pricing_plan(city_code="BJ")
    partner = create_location_partner()
    payload = create_cabinet_payload(partner["id"], model="SLOT_8")
    cab = validate_success(api.create_cabinet(payload, ADMIN_HEADERS), 201)
    full = validate_success(api.get_cabinet(cab["id"], ADMIN_HEADERS), 200)
    slots = full["slots"]
    assert len(slots) == 8, f"SLOT_8 should yield 8 slot rows, got {len(slots)}"
    for i, s in enumerate(sorted(slots, key=lambda x: x["slot_index"])):
        assert s["slot_index"] == i
        assert s["slot_status"] == "EMPTY"
        assert s["device_id"] is None


def test_cabinet_initial_online_and_last_heartbeat(api):
    """PRD §3.1: "The cabinet's online_status is initialised to ONLINE and
    last_heartbeat_at is initialised to the cabinet's own created_at."
    """
    create_pricing_plan(city_code="BJ")
    partner = create_location_partner()
    payload = create_cabinet_payload(partner["id"], model="SLOT_8")
    cab = validate_success(api.create_cabinet(payload, ADMIN_HEADERS), 201)
    assert cab["online_status"] == "ONLINE"
    assert cab["last_heartbeat_at"] == cab["created_at"]


# ---------------------------------------------------------------------------
# 4xx on bad input (PRD §2.7 priority 4)
# ---------------------------------------------------------------------------


def test_invalid_cabinet_model_rejected(api):
    """PRD §2.7 priority 4: enum membership invalid → ERR_INVALID_INPUT."""
    create_pricing_plan(city_code="BJ")
    partner = create_location_partner()
    payload = create_cabinet_payload(partner["id"], model="SLOT_99")
    res = api.create_cabinet(payload, ADMIN_HEADERS)
    validate_error(res, "ERR_INVALID_INPUT")


def test_invalid_city_code_rejected(api):
    """PRD §3.1: city_code "must be BJ or SH"."""
    partner = create_location_partner()
    payload = create_cabinet_payload(partner["id"], city_code="NY")
    res = api.create_cabinet(payload, ADMIN_HEADERS)
    validate_error(res, "ERR_INVALID_INPUT")


def test_invalid_device_battery_level_rejected(api):
    """PRD §3.1: "battery_level as an integer percentage between 0 and 100
    inclusive."
    """
    create_pricing_plan(city_code="BJ")
    partner = create_location_partner()
    cab = validate_success(
        api.create_cabinet(create_cabinet_payload(partner["id"]), ADMIN_HEADERS),
        201,
    )
    res = api.create_device(
        create_device_payload(cab["id"], 0, battery_level=150), ADMIN_HEADERS
    )
    validate_error(res, "ERR_INVALID_INPUT")


def test_pricing_plan_daily_cap_must_exceed_hourly_rate(api):
    """PRD §3.3: "the plan's daily_cap must be strictly greater than its
    hourly_rate."
    """
    res = api.create_pricing_plan(
        create_pricing_plan_payload(
            city_code="BJ", hourly_rate=10.00, daily_cap=10.00
        ),
        ADMIN_HEADERS,
    )
    validate_error(res, "ERR_INVALID_INPUT")


# ---------------------------------------------------------------------------
# 404 on missing path-parameter resource (PRD §2.7 priority 3)
# ---------------------------------------------------------------------------


def test_get_nonexistent_cabinet_returns_not_found(api):
    """PRD §2.7 priority 3: existence of path-parameter resources →
    ERR_NOT_FOUND on miss."""
    res = api.get_cabinet(NON_EXISTENT_UUID, ADMIN_HEADERS)
    validate_error(res, "ERR_NOT_FOUND")


def test_get_nonexistent_device_returns_not_found(api):
    res = api.get_device(NON_EXISTENT_UUID, ADMIN_HEADERS)
    validate_error(res, "ERR_NOT_FOUND")


def test_eject_nonexistent_cabinet_returns_not_found(api, operator_headers):
    """PRD §2.10: "the cabinet identified by {id} must exist before the slot
    identified by {slot_index} is sought; if the cabinet is missing the
    response is ERR_NOT_FOUND and the slot is never looked up."
    """
    res = api.eject_slot(NON_EXISTENT_UUID, 0, operator_headers)
    validate_error(res, "ERR_NOT_FOUND")


# ---------------------------------------------------------------------------
# User registration starts with zeros (PRD §3.3)
# ---------------------------------------------------------------------------


def test_user_registration_starts_with_zero_balances(api):
    """PRD §3.3: "starts with wallet_balance 0.00, deposit_balance 0.00,
    refund_count_30d 0, and borrow_count_24h 0."
    """
    user = validate_success(
        api.create_user(create_user_payload(), ADMIN_HEADERS), 201
    )
    assert_user(user)
    assert user["wallet_balance"] == 0.00
    assert user["deposit_balance"] == 0.00
    assert user["refund_count_30d"] == 0
    assert user["borrow_count_24h"] == 0


def test_pricing_plan_create_then_observable(api):
    """PRD §3.3: city_code is unique; create then observe via cabinet that
    references it."""
    plan = validate_success(
        api.create_pricing_plan(create_pricing_plan_payload(city_code="BJ"), ADMIN_HEADERS),
        201,
    )
    assert_pricing_plan(plan)
    assert plan["city_code"] == "BJ"
