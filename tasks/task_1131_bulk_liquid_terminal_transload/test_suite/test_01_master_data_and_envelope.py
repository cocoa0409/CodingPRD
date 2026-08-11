"""Master data creation, system-managed fields, pagination and the response
envelope (PRD §2.2, §2.3, §2.4, §2.5, §2.6, §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_customer,
    create_customer,
    create_lease,
    create_movement_payload,
    create_tank,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import MANAGER, OPERATOR, SCHEDULER


class TestCustomerSystemFields:
    def test_customer_create_returns_system_fields(self, api):
        """PRD §2.5: "Every top-level resource carries a system-managed `id`
        formatted as a UUID with no type prefix, a `created_at` timestamp in
        ISO 8601 UTC with three fractional digits, an `updated_at` timestamp
        refreshed on every mutation, and an integer `version` that starts at
        creation and increments by one on every modification."
        PRD §2.4: "At startup the logical clock reads exactly
        `2026-05-01T00:00:00Z`; until a `TerminalManager` advances it, every
        timestamp the system stamps comes from that default and the clock
        never falls back to wall time."

        Design: Corner/entities/customer_create_returns_system_fields
        """
        # Warmup record so the asserted customer is not the first row ever.
        validate_success(api.create_customer(
            {"name": "Warmup Customer", "contact_email": "warmup@example.com"}, MANAGER),
            expected_status=201)
        resp = api.create_customer(
            {"name": "System Fields Co", "contact_email": "sys@example.com"}, MANAGER)
        data = validate_success(resp, expected_status=201)
        assert_customer(data)
        assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
        assert isinstance(data["version"], int), "version must be an integer"
        assert data["created_at"].startswith("2026-05-01T00:00:00"), (
            f"created_at must be stamped from the logical clock default, got {data['created_at']}"
        )


class TestTankComputedCapacity:
    def test_working_capacity_computed_server_side(self, api):
        """PRD §2.6: "`working_capacity_bbl` equals the floor of `capacity_bbl`
        multiplied by `safe_fill_pct`, minus `heel_bbl` — the floor is applied
        to the product before the heel is subtracted, so the result is a whole
        number of barrels before heel subtraction."
        PRD §3.1: "At creation the tank's `working_capacity_bbl` is computed
        per §2.6, its `current_inventory_bbl` and `provisional_inventory_bbl`
        start at 0, and its `status` is `AVAILABLE`."
        floor(200000 * 0.95) - 100 == 189900; the injected working_capacity_bbl
        is not part of the create payload and must not override the computation.

        Design: Corner/entities/tank_computed_working_capacity_input_ignored
        """
        payload = {
            "tank_code": "T-9001", "product_grade": "DIESEL", "capacity_bbl": 200000,
            "heel_bbl": 100, "working_capacity_bbl": 1,
        }
        resp = api.create_tank(payload, OPERATOR)
        data = validate_success(resp, expected_status=201)
        assert data["working_capacity_bbl"] == 189900, (
            f"working_capacity_bbl must be computed server-side; got {data['working_capacity_bbl']}"
        )
        assert data["status"] == "AVAILABLE"
        assert data["current_inventory_bbl"] == 0

    def test_safe_fill_pct_defaults_to_095(self, api):
        """PRD §2.6: "When `safe_fill_pct` is omitted at tank creation it
        defaults to 0.95, and it must always lie strictly between 0 and 1
        inclusive at the upper bound."
        floor(200000 * 0.95) - 100 == 189900.

        Design: Corner/entities/tank_default_safe_fill_pct_applied
        """
        resp = api.create_tank(
            {"tank_code": "T-9002", "product_grade": "DIESEL", "capacity_bbl": 200000,
             "heel_bbl": 100},
            OPERATOR)
        data = validate_success(resp, expected_status=201)
        assert data["safe_fill_pct"] == 0.95, (
            f"omitted safe_fill_pct must default to 0.95, got {data['safe_fill_pct']}"
        )
        assert data["working_capacity_bbl"] == 189900


class TestNotFound:
    def test_get_unknown_movement_returns_404(self, api):
        """PRD §2.9: "the system resolves path identifiers strictly left to
        right and rejects with the 404 variant corresponding to the first
        identifier that fails to resolve. The per-entity variants are
        `ERR_CUSTOMER_NOT_FOUND`, `ERR_TANK_NOT_FOUND`, `ERR_RESOURCE_NOT_FOUND`,
        `ERR_LEASE_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND`,
        `ERR_ALLOCATION_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
        `ERR_MOVEMENT_NOT_FOUND`, `ERR_SAMPLE_NOT_FOUND`,
        `ERR_CUSTODY_TRANSFER_NOT_FOUND`, and `ERR_STATEMENT_NOT_FOUND`, each
        with HTTP 404."

        Design: Corner/entities/movement_get_not_found_returns_404
        """
        create_customer(name="Ghost Reference Co", contact_email="ghost@example.com")
        resp = api.get_movement("11111111-2222-3333-4444-555555555555", SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_MOVEMENT_NOT_FOUND)
        assert resp.status_code == 404


class TestPagination:
    def test_lease_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10 when omitted, and any value below 1 or
        above 100 is outside the allowed range. The `offset` parameter sets how
        many items to skip and defaults to 0. Every list response sorts its
        resources by `created_at` in ascending order, and the `meta` object of
        every list response carries `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/lease_list_pagination_envelope
        """
        customer = create_customer(name="Paged Customer", contact_email="paged@example.com")
        create_lease(customer["id"], committed_capacity_bbl=10000, min_monthly_throughput_bbl=10)
        create_lease(customer["id"], committed_capacity_bbl=20000, min_monthly_throughput_bbl=20)
        resp = api.list_lease_agreements(MANAGER, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"limit=1 must return exactly 1 row, got {len(data)}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert resp.json()["response_type"] == "array"


class TestSchemaValidation:
    def test_permit_missing_valid_until_returns_400(self, api):
        """PRD §2.9: "then request schema and field validity including the
        requirement that an amendment proposal carry at least one proposed
        field (`ERR_VALIDATION`), then path and body reference resolution (the
        404 family)". A permit creation omitting the required `valid_until`
        field of its validity window fails schema validation.

        Design: Corner/entities/permit_missing_required_valid_until_returns_400
        """
        tank = create_tank(tank_code="T-9201")
        resp = api.create_permit(
            {"permit_type": "VAPOR_CONTROL", "tank_id": tank["id"],
             "valid_from": "2026-05-01T00:00:00Z"},
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        assert resp.status_code == 400


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        string the system does not recognize, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        customer = create_customer(name="Auth Probe Co", contact_email="ap@example.com")
        resp = api.get_customer(customer["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401


class TestErrorEnvelope:
    def test_error_envelope_shape_on_business_rejection(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
        unique, machine-readable string that identifies the specific error."
        and "The `message` provides a human-readable explanation of what went
        wrong."
        PRD §3.2: "Creating a movement and scheduling it both require the lease
        to be `ACTIVE`."

        Design: Corner/errors/error_response_envelope_shape
        """
        customer = create_customer(name="Envelope Co", contact_email="env@example.com")
        tank = create_tank(tank_code="T-9801")
        lease = create_lease(customer["id"])  # stays DRAFT
        payload = create_movement_payload(lease["id"], tank["id"])
        resp = api.create_movement(payload, SCHEDULER)
        body = resp.json()
        assert body.get("response_type") == "error"
        err = validate_error(resp, ApiErrorId.ERR_LEASE_NOT_ACTIVE)
        assert isinstance(err["message"], str) and err["message"].strip(), "message must be non-empty"
        assert body["meta"].get("api_request_id"), "meta.api_request_id must be present"
