"""Admin bootstrap, basic CRUD, auth/RBAC, and the standard response
envelope. These tests exercise PRD §2.1 (auth), §2.2 (envelope),
§2.3 (pagination), §3.1 (employees and expense standards), and §4
(RBAC of admin-exclusive endpoints).
"""
from __future__ import annotations
import uuid

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_employee,
    assert_expense_standard,
    build_user_headers,
    create_employee_payload,
    create_expense_standard_payload,
    get_success_data,
    make_admin_headers,
    publish_expense_standard,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Auth: missing headers (PRD §2.1)
# ---------------------------------------------------------------------------
class TestAuthMissing:

    def test_missing_both_headers_returns_err_auth_missing(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_AUTH_MISSING (HTTP 401)."

        Claim: omitting X-User-ID AND X-User-Role triggers ERR_AUTH_MISSING.
        """
        res = api.create_travel_application(
            {"destination_city": "x", "destination_tier": "TIER_2",
             "travel_scope": "DOMESTIC", "purpose": "p",
             "planned_start": "2025-06-01T09:00:00.000Z",
             "planned_end": "2025-06-04T18:00:00.000Z",
             "estimated_budget": 100.00},
            headers={},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_id_returns_err_auth_missing(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_AUTH_MISSING (HTTP 401)."

        Claim: X-User-Role alone (no X-User-ID) → ERR_AUTH_MISSING.
        """
        res = api.list_expense_standards({"X-User-Role": "Admin"})
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_role_returns_err_auth_missing(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_AUTH_MISSING (HTTP 401)."

        Claim: X-User-ID alone (no X-User-Role) → ERR_AUTH_MISSING.
        """
        res = api.list_expense_standards({"X-User-ID": "admin-001"})
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)


# ---------------------------------------------------------------------------
# RBAC: role not permitted for endpoint (PRD §2.1, §4)
# ---------------------------------------------------------------------------
class TestForbidden:

    def test_non_admin_cannot_create_employee(self, api, applicant_headers):
        """PRD §2.1: "If both headers are present but the role is not
        permitted to invoke the endpoint per the matrix below, the
        request is rejected with ERR_FORBIDDEN (HTTP 403)."
        PRD §4: POST /employees is Admin-only.

        Claim: Applicant attempting POST /employees → ERR_FORBIDDEN.
        """
        res = api.create_employee(
            create_employee_payload(), applicant_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_non_admin_cannot_publish_expense_standard(self, api,
                                                      finance_headers):
        """PRD §4: POST /expense-standards is Admin-only.
        PRD §2.1: "If both headers are present but the role is not
        permitted to invoke the endpoint per the matrix below, the
        request is rejected with ERR_FORBIDDEN (HTTP 403)."

        Claim: Finance attempting POST /expense-standards → ERR_FORBIDDEN.
        """
        res = api.create_expense_standard(
            create_expense_standard_payload(version=99), finance_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_non_finance_cannot_create_payment_batch(self, api,
                                                    applicant_headers):
        """PRD §4: POST /payments/batches is Finance-only (exclusive_operations).
        PRD §2.1: role not permitted → ERR_FORBIDDEN (HTTP 403).

        Claim: Applicant attempting POST /payments/batches → ERR_FORBIDDEN.
        """
        res = api.create_payment_batch(
            {"form_ids": [str(uuid.uuid4())], "channel": "BANK_TRANSFER"},
            applicant_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# Employee creation + retrieval (PRD §3.1, §4)
# ---------------------------------------------------------------------------
class TestEmployeeBootstrap:

    def test_admin_creates_employee_returns_active(self, api, admin_headers):
        """PRD §3.1: "Newly registered employees are created with status
        set to ACTIVE by default."

        Claim: POST /employees as Admin → 201 + status=ACTIVE.
        """
        res = api.create_employee(
            create_employee_payload(
                full_name="Test Employee A", employee_level="STAFF",
            ),
            admin_headers,
        )
        employee = validate_success(res, expected_status=201)
        assert_employee(employee)
        assert employee["status"] == "ACTIVE"
        assert employee["full_name"] == "Test Employee A"
        assert employee["employee_level"] == "STAFF"

    def test_get_employee_by_id_returns_persisted_row(self, api, admin_headers):
        """PRD §4: GET /employees/{id} returns the persisted Employee row.

        Claim: a freshly created Employee is retrievable via GET.
        """
        created = get_success_data(
            api.create_employee(
                create_employee_payload(full_name="Test Employee B"),
                admin_headers,
            )
        )
        retrieved = validate_success(
            api.get_employee(created["id"], admin_headers),
        )
        assert retrieved["id"] == created["id"]
        assert retrieved["full_name"] == "Test Employee B"

    def test_get_employee_nonexistent_returns_not_found(self, api,
                                                       admin_headers):
        """PRD §2.8: "Path existence — ERR_NOT_FOUND for any unknown id
        in the URL, evaluated left-to-right."

        Claim: GET /employees/{unknown} → ERR_NOT_FOUND.
        """
        res = api.get_employee(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# ExpenseStandard publish + auto-close (PRD §3.1)
# ---------------------------------------------------------------------------
class TestExpenseStandardPublish:

    def test_admin_publishes_expense_standard(self, api, admin_headers):
        """PRD §3.1: an ExpenseStandard row is keyed by (version, city_tier,
        employee_level) and carries the three caps plus holiday_multiplier.

        Claim: POST /expense-standards as Admin → 201 + valid row shape.
        """
        # Use a unique bucket so this test doesn't collide with others.
        std = get_success_data(
            api.create_expense_standard(
                create_expense_standard_payload(
                    version=1,
                    city_tier="TIER_3",
                    employee_level="EXECUTIVE",
                    effective_from="2024-03-15T00:00:00.000Z",
                    lodging_daily_cap=1_000.00,
                    per_diem_amount=300.00,
                    transportation_daily_cap=400.00,
                    holiday_multiplier=1.30,
                ),
                admin_headers,
            )
        )
        assert_expense_standard(std)
        assert std["version"] == 1
        assert std["city_tier"] == "TIER_3"
        assert std["employee_level"] == "EXECUTIVE"
        assert std["lodging_daily_cap"] == 1_000.00

    def test_publishing_v2_auto_closes_v1(self, api, admin_headers):
        """PRD §3.1: "When an admin publishes a new row for an existing
        (city_tier, employee_level) bucket, the system auto-closes the
        prior open row in the same bucket — that is, the prior row's
        effective_to is set to the new row's effective_from."

        Claim: publishing v2 closes v1 by setting v1.effective_to = v2.effective_from.
        """
        bucket_tier = "TIER_3"
        bucket_level = "MANAGER"
        v1 = publish_expense_standard(
            version=1, city_tier=bucket_tier, employee_level=bucket_level,
            effective_from="2024-04-01T00:00:00.000Z",
            lodging_daily_cap=300.00,
        )
        v2_effective_from = "2025-07-01T00:00:00.000Z"
        publish_expense_standard(
            version=2, city_tier=bucket_tier, employee_level=bucket_level,
            effective_from=v2_effective_from,
            lodging_daily_cap=400.00,
        )

        listing_data, _meta = validate_paginated(
            api.list_expense_standards(
                admin_headers,
                params={"city_tier": bucket_tier,
                        "employee_level": bucket_level},
            )
        )
        v1_row = next(
            row for row in listing_data
            if row["id"] == v1["id"]
        )
        assert v1_row.get("effective_to") == v2_effective_from, (
            f"PRD §3.1: prior row's effective_to must equal new row's "
            f"effective_from ({v2_effective_from}); got "
            f"{v1_row.get('effective_to')!r}"
        )


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
class TestPagination:

    def test_pagination_default_envelope_meta_present(self, api, admin_headers):
        """PRD §2.3: "All list endpoints accept the two query parameters
        limit and offset. The default limit is 10, the minimum is 1, and
        the maximum is 100." PRD §2.2: meta carries limit, offset,
        total_count, has_more on list responses.

        Claim: a list endpoint returns the four pagination meta fields.
        """
        data, meta = validate_paginated(
            api.list_expense_standards(admin_headers)
        )
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"meta missing '{key}' per PRD §2.2"
        assert meta["limit"] == 10, "PRD §2.3: default limit is 10"
        assert meta["offset"] == 0, "PRD §2.3: default offset is 0"

    def test_pagination_limit_out_of_range_rejected(self, api, admin_headers):
        """PRD §2.3: "the maximum is 100; out-of-range values are
        rejected with ERR_VALIDATION."

        Claim: limit=101 → ERR_VALIDATION.
        """
        res = api.list_expense_standards(admin_headers, params={"limit": 101})
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_pagination_negative_offset_rejected(self, api, admin_headers):
        """PRD §2.3: "The default offset is 0; negative offsets are
        rejected with ERR_VALIDATION."

        Claim: offset=-1 → ERR_VALIDATION.
        """
        res = api.list_expense_standards(admin_headers, params={"offset": -1})
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)


# ---------------------------------------------------------------------------
# Validation priority — auth ranks above existence/state (PRD §2.8)
# ---------------------------------------------------------------------------
def test_missing_auth_pre_empts_not_found(api):
    """PRD §2.8: "Header authentication — ERR_AUTH_MISSING for the
    missing-headers case." It heads the priority order.

    Claim: an unauthenticated request to a non-existent path-id still
    returns ERR_AUTH_MISSING (auth is priority 1, existence is priority 3).
    """
    res = api.get_travel_application(NON_EXISTENT_UUID, headers={})
    validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)
