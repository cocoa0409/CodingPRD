"""Auth headers, role enforcement, response envelope, pagination, and
left-to-right path resolution.

PRD §2.1 (auth), §2.2 (envelope), §2.3 (pagination), §2.5 (path
hierarchy).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_operator_payload,
    create_pile_payload,
    create_pricing_version,
    create_station,
    create_station_owner_operator,
    create_platform_operator_row,
    create_member_payload,
    setup_operator_station_shelved_pile,
    setup_ready_to_charge,
    validate_error,
    validate_paginated,
    validate_success,
    PO, PO_ALT, FT, CS,
    make_station_owner_headers,
)


# ===========================================================================
# Auth header presence (PRD §2.1, validation priority 1)
# ===========================================================================
class TestAuthHeadersRequired:
    """PRD §2.1: 'Every non-test-harness request must carry two HTTP
    headers: X-User-ID (the calling identity) and X-User-Role.'"""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: 'A request that omits either header on an endpoint
        that requires authentication is rejected with
        ERR_AUTH_MISSING.'"""
        res = api.create_operator(create_operator_payload(), {})
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: 'A request that omits either header on an endpoint
        that requires authentication is rejected with
        ERR_AUTH_MISSING.'"""
        res = api.create_operator(
            create_operator_payload(),
            {"X-User-Role": "PlatformOperator"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: 'A request that omits either header on an endpoint
        that requires authentication is rejected with
        ERR_AUTH_MISSING.'"""
        res = api.create_operator(
            create_operator_payload(),
            {"X-User-ID": "some-id"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_unrecognized_role_rejected(self, api):
        """PRD §2.1: 'A request whose X-User-Role value is not one of the
        recognized role names ... is rejected with ERR_AUTH_INVALID.'"""
        res = api.create_operator(
            create_operator_payload(),
            {"X-User-ID": "ghost", "X-User-Role": "Sysadmin"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_INVALID.value)


# ===========================================================================
# Role authorization (PRD §2.1, ERR_FORBIDDEN)
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: 'A request with valid headers whose role is not
    authorized for the requested endpoint is rejected with
    ERR_FORBIDDEN.'"""

    def test_create_operator_forbidden_for_customer_service(self, api):
        """PRD §2.1: 'PlatformOperator is the only role permitted to
        create pricing versions and promotional activities, decommission
        piles, open repair tickets, create and issue payouts, and
        exercise the test-harness endpoints.' POST /operators is a
        PlatformOperator-only endpoint per PRD §4."""
        res = api.create_operator(create_operator_payload(), CS)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_create_pricing_version_forbidden_for_field_technician(
        self, api,
    ):
        """PRD §2.1: 'PlatformOperator is the only role permitted to
        create pricing versions.' POST /pricing-versions therefore
        rejects FieldTechnician with ERR_FORBIDDEN."""
        operator = create_platform_operator_row()
        from test_helpers import create_pricing_version_payload, iso_day
        payload = create_pricing_version_payload(
            operator_id=operator["id"],
            effective_from=iso_day(2026, 1, 1),
            effective_to=iso_day(2027, 1, 1),
        )
        res = api.create_pricing_version(payload, FT)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_abort_session_forbidden_for_ev_driver(self, api):
        """PRD §2.1 / §3.4: 'CustomerService may invoke an override
        abort'. PRD §4 lists POST /sessions/{id}/abort under
        CustomerService only, so EVDriver is rejected with
        ERR_FORBIDDEN."""
        from test_helpers import make_ev_driver_headers, setup_charging_session
        ctx = setup_charging_session()
        member_id = ctx["member"]["id"]
        res = api.abort_session(
            ctx["session"]["id"],
            make_ev_driver_headers(member_id),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Path resource existence (PRD §2.5, ERR_NOT_FOUND)
# ===========================================================================
class TestPathExistence:
    """PRD §2.5: 'Nested URL paths are validated left-to-right ... if it
    does not, the response is ERR_NOT_FOUND regardless of any other
    condition.'"""

    def test_get_operator_with_non_existent_id_returns_not_found(
        self, api,
    ):
        """PRD §2.5: 'Resource existence (path identifiers, then body
        foreign keys) is checked next.'"""
        res = api.get_operator(NON_EXISTENT_UUID, PO)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_station_with_non_existent_id_returns_not_found(self, api):
        """PRD §2.5: 'For an endpoint like /stations/{id}/queue-entries,
        the station identified by the path must exist before the
        queue-entry collection is consulted; if it does not, the
        response is ERR_NOT_FOUND regardless of any other condition.'"""
        res = api.get_station(NON_EXISTENT_UUID, PO)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_shelve_pile_with_non_existent_id_returns_not_found(
        self, api, station_owner_fallback_headers,
    ):
        """PRD §2.5: existence-check precedes state-machine check (and
        precedes any authorization-as-owner check)."""
        res = api.shelve_pile(
            NON_EXISTENT_UUID, station_owner_fallback_headers,
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_session_with_unknown_pile_returns_not_found(
        self, api,
    ):
        """PRD §2.5: 'Body foreign keys ... are also resolved at
        creation time; a reference to a non-existent target yields
        ERR_NOT_FOUND.'"""
        # Need an existing member but a fake pile.
        from test_helpers import (
            create_session_payload, make_ev_driver_headers,
        )
        ctx = setup_ready_to_charge()
        payload = create_session_payload(
            pile_id=NON_EXISTENT_UUID,
            member_id=ctx["member"]["id"],
            auth_method="APP",
        )
        res = api.create_session(
            payload, make_ev_driver_headers(ctx["member"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Response envelope (PRD §2.2)
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: 'All successful API responses follow this standard
    envelope format ... meta, response_type, data.'"""

    def test_success_envelope_has_meta_and_data(self, api):
        """PRD §2.2: 'The api_request_id is a server-generated unique
        identifier for the request that starts with req_.'"""
        res = api.create_operator(
            create_operator_payload(role_kind="PLATFORM"), PO,
        )
        body = validate_success(res, expected_status=201)
        # validate_success already asserts envelope shape.
        assert body  # data must be non-empty

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: 'data { error_id ..., message ... }.'"""
        res = api.get_station(NON_EXISTENT_UUID, PO)
        body = validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)
        assert "error_id" in body
        assert "message" in body


# ===========================================================================
# Pagination (PRD §2.3)
# ===========================================================================
class TestPagination:
    """PRD §2.3: 'The limit defaults to 10 when omitted, with a minimum
    of 1 and a maximum of 100; values outside that range are rejected
    with ERR_VALIDATION.'"""

    def test_list_operators_pagination_envelope(self, api):
        """PRD §2.3: 'The response meta block includes limit, offset,
        total_count, and has_more.'"""
        # Create at least 2 operators so list is non-empty.
        create_platform_operator_row()
        create_platform_operator_row()
        res = api.list_operators(PO, params={"limit": 5, "offset": 0})
        rows, meta = validate_paginated(res)
        assert isinstance(rows, list)
        assert "total_count" in meta
        assert "has_more" in meta
        assert meta.get("limit") == 5
        assert meta.get("offset") == 0

    def test_list_with_limit_above_max_rejected(self, api):
        """PRD §2.3: 'values outside that range are rejected with
        ERR_VALIDATION.'"""
        res = api.list_operators(PO, params={"limit": 101})
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_list_with_limit_zero_rejected(self, api):
        """PRD §2.3: 'a minimum of 1 ... values outside that range are
        rejected with ERR_VALIDATION.'"""
        res = api.list_operators(PO, params={"limit": 0})
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_list_with_negative_offset_rejected(self, api):
        """PRD §2.3: 'The offset defaults to 0 and must be
        non-negative.'"""
        res = api.list_operators(PO, params={"offset": -1})
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)
