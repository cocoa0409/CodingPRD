"""Authentication and role-authorization claims."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    create_airport_payload,
    create_airport,
    create_atc_controller,
    create_strike_report_payload,
    make_atc_controller_headers,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
)


def test_unauthenticated_request_missing_headers(api):
    """PRD §2.1: "Every request carries two HTTP headers identifying the
    caller: `X-User-ID` and `X-User-Role`. A request missing either header, or
    presenting a role value outside the declared set, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_request_missing_headers
    """
    res = api.list_airports(headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_unauthorized_role_cannot_create_airport(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted to
    invoke the target endpoint per the RBAC matrix is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST /wildlife/airports is authorized for AirportAdmin only.

    Design: Corner/validations/unauthorized_role_cannot_create_airport
    """
    res = api.create_airport(
        create_airport_payload(
            icao_code="KIII", name="India Airport", annual_plan_cycle_year=2026,
        ),
        TEST_USERS["biologist_headers"],
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_atc_cannot_create_strike_report(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted to
    invoke the target endpoint per the RBAC matrix is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST /wildlife/strike-reports is authorized for WildlifeBiologist
    only.

    Design: Corner/rbac/atc_cannot_create_strike_report
    """
    airport = create_airport(icao_code="KQQQ", name="Quebec Airport")
    controller = create_atc_controller(airport["id"], facility_id="TWR-QQQ")
    payload = create_strike_report_payload(
        airport["id"], controller["id"], NON_EXISTENT_UUID,
        strike_at="2026-07-15T10:00:00Z", aircraft_registration="N-Q1",
    )
    res = api.create_strike_report(payload, make_atc_controller_headers(controller["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)
