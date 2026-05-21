"""Auth headers (PRD §2.1, §2.9 priority 1), RBAC (priority 2),
ownership (PRD §2.1), mass assignment, and SQL injection probes.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_appointment_payload,
    create_customer,
    create_parcel,
    create_parcel_payload,
    iso_utc,
    make_customer_headers,
    make_driver_headers,
    setup_baseline,
    setup_parcel_in_exception,
    utcnow,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Auth headers — PRD §2.1, §2.9 priority 1
# ---------------------------------------------------------------------------
class TestAuthenticationHeaders:

    def test_missing_both_headers_returns_unauthenticated(self, api):
        """PRD §2.1: 'If either header is missing or malformed, the
        request is rejected with ERR_UNAUTHENTICATED.'"""
        res = api.create_customer(
            {"email": "a@b.com", "full_name": "X", "phone": "+15550000000"},
            headers={},
        )
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_missing_user_role_returns_unauthenticated(self, api):
        """PRD §2.1: 'X-User-Role declares the operational capacity ...
        If either header is missing or malformed, the request is
        rejected with ERR_UNAUTHENTICATED.'"""
        res = api.list_parcels({"X-User-ID": "someone"})
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_missing_user_id_returns_unauthenticated(self, api):
        """PRD §2.1: 'X-User-ID identifies the acting principal ...
        If either header is missing or malformed ... ERR_UNAUTHENTICATED.'"""
        res = api.list_parcels({"X-User-Role": "Dispatcher"})
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_unknown_role_string_returns_forbidden(self, api):
        """PRD §2.1: 'The system recognizes five role names — spelled
        exactly as Customer, Driver, Dispatcher, SortingHubOperator,
        and ComplianceOfficer. When a request carries a valid pair of
        headers but the role is not authorized for the endpoint, the
        response is ERR_FORBIDDEN.'

        Two-reader: an unknown role string is not in the recognized
        set, so the auth check at priority 2 fails. PRD spells the
        error_id ERR_FORBIDDEN for this case."""
        res = api.list_parcels(
            build_user_headers("user-1", "UnknownRole"),
        )
        # PRD §2.9 priority 1 vs 2: header presence passes; role
        # authorization fails -> ERR_FORBIDDEN.
        validate_error(res, "ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# RBAC — wrong role for endpoint
# ---------------------------------------------------------------------------
class TestRbacRoleForbidden:

    def test_compliance_officer_cannot_create_parcel(self, api):
        """PRD §4 table: POST /parcels is restricted to Dispatcher
        and SortingHubOperator. ComplianceOfficer is read-only per
        PRD §2.1."""
        base = setup_baseline()
        res = api.create_parcel(
            create_parcel_payload(
                customer_id=base["customer"]["id"],
                origin_center_id=base["center"]["id"],
                destination_address_id=base["address"]["id"],
            ),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_customer_cannot_dispatch_route(self, api):
        """PRD §4 table: POST /routes/{id}/dispatch is restricted to
        Dispatcher."""
        base = setup_baseline()
        res = api._request(
            "POST", f"/routes/{NON_EXISTENT_UUID}/dispatch",
            None, make_customer_headers(base["customer"]["id"]),
        )
        # Either ERR_FORBIDDEN (priority 2) or ERR_NOT_FOUND
        # (priority 3); PRD §2.9 pins forbidden first.
        validate_error(res, "ERR_FORBIDDEN")

    def test_sorting_hub_operator_cannot_create_route(self, api):
        """PRD §4 table: POST /routes is exclusive to Dispatcher."""
        res = api.create_route(
            {"center_id": NON_EXISTENT_UUID,
             "driver_id": NON_EXISTENT_UUID,
             "planned_date": "2026-12-01"},
            TEST_USERS["sorting_hub_operator_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# Ownership — entity-backed identities
# ---------------------------------------------------------------------------
class TestOwnership:

    def test_customer_cannot_read_other_customers_parcel(self, api):
        """PRD §2.1: 'A Customer reading or filing an appointment for
        a parcel they do not own must be rejected with ERR_FORBIDDEN.'"""
        base = setup_baseline()
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        other = create_customer()
        res = api.get_parcel(
            parcel["id"], make_customer_headers(other["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_customer_can_read_own_parcel(self, api):
        """PRD §2.1: 'ownership checks ... compare the resource's
        foreign-key field (most notably Parcel.customer_id ...) to
        X-User-ID' — when X-User-ID == owner, access is allowed."""
        base = setup_baseline()
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        res = api.get_parcel(
            parcel["id"],
            make_customer_headers(base["customer"]["id"]),
        )
        validate_success(res, 200)

    def test_customer_cannot_file_appointment_on_other_parcel(self, api):
        """PRD §2.1: 'A Customer reading or filing an appointment for
        a parcel they do not own must be rejected with ERR_FORBIDDEN.'"""
        ctx = setup_parcel_in_exception()
        other = create_customer()
        from datetime import timedelta
        from test_helpers import current_clock
        start = current_clock() + timedelta(hours=4)
        end = start + timedelta(hours=3)
        res = api.create_appointment(
            create_appointment_payload(
                parcel_id=ctx["parcel"]["id"],
                requested_window_start=iso_utc(start),
                requested_window_end=iso_utc(end),
            ),
            make_customer_headers(other["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# Validation-priority — auth before existence
# ---------------------------------------------------------------------------
class TestValidationPriority:

    def test_missing_headers_beats_missing_resource(self, api):
        """PRD §2.9: 'Header presence is checked before role
        authorization, which is checked before path-id existence'."""
        res = api.get_parcel(NON_EXISTENT_UUID, headers={})
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_forbidden_role_beats_missing_resource(self, api):
        """PRD §2.9: 'role authorization ... is checked before path-id
        existence'."""
        # ComplianceOfficer cannot dispatch a route; even a missing
        # route id must hit the forbidden check first.
        res = api._request(
            "POST", f"/routes/{NON_EXISTENT_UUID}/dispatch",
            None, TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# Mass assignment & SQL injection
# ---------------------------------------------------------------------------
SQL_INJECTION_PAYLOADS = [
    "'; DROP TABLE parcels; --",
    "' OR '1'='1",
    "' UNION SELECT * FROM users--",
]
SQL_ERROR_PATTERNS = [
    "sql syntax", "sqlstate", "database error",
    "sqlite", "pg_", "mysql_",
]


class TestSecurity:

    @pytest.mark.parametrize("injection", SQL_INJECTION_PAYLOADS)
    def test_sql_injection_in_customer_full_name(self, api, injection):
        """Security: injection in a string field must not produce a
        500 or leak SQL errors. The API may accept the string
        verbatim (PRD §3.1 allows arbitrary full_name) or reject it
        with a 4xx, but never crash."""
        res = api.create_customer(
            {
                "email": f"sqli_{abs(hash(injection))}@example.com",
                "full_name": injection,
                "phone": "+15550000099",
            },
            TEST_USERS["dispatcher_headers"],
        )
        assert res.status_code != 500
        for pattern in SQL_ERROR_PATTERNS:
            assert pattern not in res.text.lower()

    def test_mass_assignment_status_field_ignored_on_create(self, api):
        """PRD §3.3: 'places the parcel into the initial state
        INDUCTED'. A client-supplied status must not override that.
        PRD §1.1 marks Parcel.status as source: computed (server-set)."""
        base = setup_baseline()
        payload = create_parcel_payload(
            customer_id=base["customer"]["id"],
            origin_center_id=base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        payload["status"] = "DELIVERED"  # attempt mass assignment
        res = api.create_parcel(payload, TEST_USERS["dispatcher_headers"])
        parcel = validate_success(res, 201)
        # PRD pins INDUCTED as initial state regardless of input.
        assert parcel["status"] == "INDUCTED"

    def test_mass_assignment_tracking_number_ignored(self, api):
        """PRD §3.3: 'The server mints a 12-character alphanumeric
        tracking_number ... Parcel.tracking_number is source: system'.
        A client-supplied tracking_number must not stick."""
        base = setup_baseline()
        payload = create_parcel_payload(
            customer_id=base["customer"]["id"],
            origin_center_id=base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        payload["tracking_number"] = "AAAAAAAAAAAA"
        res = api.create_parcel(payload, TEST_USERS["dispatcher_headers"])
        parcel = validate_success(res, 201)
        # Server-minted — the supplied value should not be honoured.
        assert parcel["tracking_number"] != "AAAAAAAAAAAA"
