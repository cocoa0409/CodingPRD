"""Vehicle and Driver registration tests (PRD §3.1).

PRD coverage: §3.1 fleet onboarding rules, §2.4 common properties.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_driver,
    assert_vehicle,
    create_driver_payload,
    create_vehicle_payload,
    unique_license_no,
    unique_vehicle_no,
    validate_error,
    validate_success,
)


# ===========================================================================
# Vehicle creation
# ===========================================================================
def test_create_vehicle_minimum_payload(api, carrier_headers):
    """PRD §3.1: 'On creation the server assigns status of AVAILABLE.'"""
    payload = create_vehicle_payload(
        compartment_count=1, insured_cap_cents=1,
    )
    data = validate_success(
        api.create_vehicle(payload, carrier_headers), expected_status=201,
    )
    assert_vehicle(data)
    assert data["status"] == "AVAILABLE"
    assert data["compartment_count"] == 1
    assert data["insured_cap_cents"] == 1


def test_create_vehicle_compartment_count_zero_rejected(
    api, carrier_headers,
):
    """PRD §3.1: 'compartment_count is the number of independently
    temperature-controlled compartments and must be an integer in the
    range one through six.'"""
    resp = api.create_vehicle(
        create_vehicle_payload(compartment_count=0), carrier_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_vehicle_compartment_count_seven_rejected(
    api, carrier_headers,
):
    """PRD §3.1: 'compartment_count ... must be an integer in the range
    one through six.'"""
    resp = api.create_vehicle(
        create_vehicle_payload(compartment_count=7), carrier_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_vehicle_compartment_count_six_accepted(
    api, carrier_headers,
):
    """PRD §3.1: 'compartment_count ... must be an integer in the range
    one through six.' Six is the inclusive upper bound."""
    data = validate_success(
        api.create_vehicle(
            create_vehicle_payload(compartment_count=6), carrier_headers,
        ),
        expected_status=201,
    )
    assert data["compartment_count"] == 6


def test_create_vehicle_zero_insured_cap_rejected(api, carrier_headers):
    """PRD §3.1: 'insured_cap_cents is the per-incident cap in cents on
    cargo carried by this vehicle and must be a positive integer.'"""
    resp = api.create_vehicle(
        create_vehicle_payload(insured_cap_cents=0), carrier_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_get_vehicle_not_found(api, carrier_headers):
    """PRD §2.6: 'every id segment in the URL ... is resolved in order,
    and the first missing id is reported as ERR_NOT_FOUND (status 404).'"""
    resp = api.get_vehicle(NON_EXISTENT_UUID, carrier_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Driver creation
# ===========================================================================
def test_create_driver_default_max_daily_minutes(api, carrier_headers):
    """PRD §3.1: 'max_daily_minutes defaults to 660 — that is, eleven
    hours — when omitted.'"""
    payload = create_driver_payload()
    payload.pop("max_daily_minutes", None)
    data = validate_success(
        api.create_driver(payload, carrier_headers), expected_status=201,
    )
    assert_driver(data)
    assert data["max_daily_minutes"] == 660
    assert data["status"] == "OFF_DUTY"


def test_create_driver_with_custom_max_daily_minutes(api, carrier_headers):
    """PRD §3.1: 'max_daily_minutes ... is an integer in the range one
    to one thousand four hundred forty.'"""
    data = validate_success(
        api.create_driver(
            create_driver_payload(max_daily_minutes=480), carrier_headers,
        ),
        expected_status=201,
    )
    assert data["max_daily_minutes"] == 480


def test_create_driver_max_daily_minutes_zero_rejected(api, carrier_headers):
    """PRD §3.1: 'max_daily_minutes ... is an integer in the range one
    to one thousand four hundred forty.'"""
    resp = api.create_driver(
        create_driver_payload(max_daily_minutes=0), carrier_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_driver_max_daily_minutes_too_large_rejected(
    api, carrier_headers,
):
    """PRD §3.1: 'max_daily_minutes ... is an integer in the range one
    to one thousand four hundred forty.'"""
    resp = api.create_driver(
        create_driver_payload(max_daily_minutes=1441), carrier_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_get_driver_not_found(api, carrier_headers):
    """PRD §2.6 path-id existence check."""
    resp = api.get_driver(NON_EXISTENT_UUID, carrier_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
