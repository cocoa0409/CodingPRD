"""Employee CRUD and configuration-time validations.

Covers PRD §3.1 (Onboarding an Employee), §2.5 (OCC).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_employee,
    assert_version_incremented_by,
    clock_set,
    create_employee,
    create_employee_payload,
    TEST_DEFAULTS,
    update_employee_payload,
    validate_error,
    validate_success,
)


def setup_module(module):
    clock_set(TEST_DEFAULTS["WORKWEEK_ANCHOR"])


# ===========================================================================
# Employee creation — PRD §3.1
# ===========================================================================
class TestEmployeeCreate:

    def test_create_non_exempt_fed_employee(self, api,
                                            payroll_admin_headers):
        """PRD §3.1: NON_EXEMPT employee with base_hourly_rate_cents
        accepted; HR `status` is system-set to ACTIVE.

        Claim: "The HR `status` of a newly created employee is
        system-set to `ACTIVE`".
        """
        resp = api.create_employee(
            create_employee_payload(
                full_name="Alice NonExempt",
                jurisdiction="FED",
                classification="NON_EXEMPT",
                base_hourly_rate_cents=2000,
            ),
            payroll_admin_headers,
        )
        emp = validate_success(resp, expected_status=201)
        assert_employee(emp)
        assert emp["full_name"] == "Alice NonExempt"
        assert emp["jurisdiction"] == "FED"
        assert emp["classification"] == "NON_EXEMPT"
        assert emp["base_hourly_rate_cents"] == 2000
        assert emp["status"] == "ACTIVE"
        assert emp["version"] == 1

    def test_create_employee_below_federal_minimum_wage_rejected(
        self, api, payroll_admin_headers,
    ):
        """PRD §3.1: "The `base_hourly_rate_cents` is required when
        `classification` is `NON_EXEMPT` and must be at least 725 (the
        federal minimum wage in whole cents)".

        Claim: rate of 720 cents → ERR_BELOW_MINIMUM_WAGE.
        """
        resp = api.create_employee(
            create_employee_payload(
                jurisdiction="FED",
                classification="NON_EXEMPT",
                base_hourly_rate_cents=720,
            ),
            payroll_admin_headers,
        )
        validate_error(resp, "ERR_BELOW_MINIMUM_WAGE")

    def test_create_tipped_employee_requires_tipped_fields(
        self, api, payroll_admin_headers,
    ):
        """PRD §3.1: "A non-tipped employee must not supply either
        tipped field; supplying tipped fields on a non-tipped employee,
        or omitting them on a tipped employee, is rejected with
        `ERR_TIPPED_FIELDS_MISMATCH`."

        Claim: tipped_role=true without tipped_cash_rate_cents →
        ERR_TIPPED_FIELDS_MISMATCH.
        """
        payload = create_employee_payload(
            jurisdiction="FED",
            classification="NON_EXEMPT",
            base_hourly_rate_cents=725,
        )
        payload["tipped_role"] = True
        # Intentionally omit tipped_cash_rate_cents and
        # applicable_minimum_wage_cents.
        resp = api.create_employee(payload, payroll_admin_headers)
        validate_error(resp, "ERR_TIPPED_FIELDS_MISMATCH")

    def test_non_tipped_employee_supplies_tipped_fields_rejected(
        self, api, payroll_admin_headers,
    ):
        """PRD §3.1: "supplying tipped fields on a non-tipped employee
        ... is rejected with `ERR_TIPPED_FIELDS_MISMATCH`"."""
        resp = api.create_employee(
            create_employee_payload(
                jurisdiction="FED",
                classification="NON_EXEMPT",
                base_hourly_rate_cents=2000,
                tipped_role=False,
                tipped_cash_rate_cents=213,
                applicable_minimum_wage_cents=1500,
            ),
            payroll_admin_headers,
        )
        validate_error(resp, "ERR_TIPPED_FIELDS_MISMATCH")

    def test_create_tipped_employee_with_all_fields_succeeds(
        self, api, payroll_admin_headers,
    ):
        """PRD §3.1: "A tipped employee — one for whom `tipped_role` is
        true — must also supply `tipped_cash_rate_cents` ... and
        `applicable_minimum_wage_cents`".

        Claim: a fully-specified tipped employee is created at 201.
        """
        resp = api.create_employee(
            create_employee_payload(
                jurisdiction="FED",
                classification="NON_EXEMPT",
                base_hourly_rate_cents=725,
                tipped_role=True,
                tipped_cash_rate_cents=213,
                applicable_minimum_wage_cents=1500,
            ),
            payroll_admin_headers,
        )
        emp = validate_success(resp, expected_status=201)
        assert emp["tipped_role"] is True
        assert emp["tipped_cash_rate_cents"] == 213
        assert emp["applicable_minimum_wage_cents"] == 1500

    def test_tipped_cash_rate_below_213_rejected(
        self, api, payroll_admin_headers,
    ):
        """PRD §3.1: "The cash rate must be at least 213 (the federal
        tipped minimum in whole cents)".

        Claim: tipped_cash_rate_cents=200 → ERR_BELOW_MINIMUM_WAGE.
        """
        resp = api.create_employee(
            create_employee_payload(
                jurisdiction="FED",
                classification="NON_EXEMPT",
                base_hourly_rate_cents=725,
                tipped_role=True,
                tipped_cash_rate_cents=200,
                applicable_minimum_wage_cents=1500,
            ),
            payroll_admin_headers,
        )
        validate_error(resp, "ERR_BELOW_MINIMUM_WAGE")

    def test_create_exempt_employee_ignores_rate(
        self, api, payroll_admin_headers,
    ):
        """PRD §3.1: "for `EXEMPT` employees the field is ignored
        because exempt staff do not draw hourly pay through this system".

        Claim: an EXEMPT employee with classification=EXEMPT is created
        at 201.
        """
        resp = api.create_employee(
            create_employee_payload(
                full_name="Bob Exempt",
                jurisdiction="FED",
                classification="EXEMPT",
            ),
            payroll_admin_headers,
        )
        emp = validate_success(resp, expected_status=201)
        assert_employee(emp)
        assert emp["classification"] == "EXEMPT"


# ===========================================================================
# Employee read / list / update — PRD §3.1, §2.5
# ===========================================================================
class TestEmployeeReadAndUpdate:

    def test_get_employee_returns_created_record(
        self, api, payroll_admin_headers,
    ):
        """PRD §3.1 / §2.4: GET /employees/{id} retrieves a previously
        created employee with all common fields.
        """
        emp = create_employee()
        resp = api.get_employee(emp["id"], payroll_admin_headers)
        retrieved = validate_success(resp, expected_status=200)
        assert retrieved["id"] == emp["id"]
        assert_employee(retrieved)

    def test_patch_employee_increments_version(
        self, api, payroll_admin_headers,
    ):
        """PRD §2.4: "`version` ... increments by exactly 1 on every
        mutation."
        """
        emp = create_employee(base_hourly_rate_cents=2000)
        resp = api.update_employee(
            emp["id"],
            update_employee_payload(base_hourly_rate_cents=2200),
            payroll_admin_headers,
        )
        updated = validate_success(resp, expected_status=200)
        assert updated["base_hourly_rate_cents"] == 2200
        assert_version_incremented_by(updated["version"], emp["version"])

    def test_patch_with_stale_version_returns_err_version_conflict(
        self, api, payroll_admin_headers,
    ):
        """PRD §2.5: "If the caller supplies a `version` value and it
        does not match the current persisted `version` of the target
        resource, the request is rejected with `ERR_VERSION_CONFLICT`
        and HTTP status 409."
        """
        emp = create_employee(base_hourly_rate_cents=2000)
        # First update bumps version to 2.
        first = api.update_employee(
            emp["id"],
            update_employee_payload(base_hourly_rate_cents=2100),
            payroll_admin_headers,
        )
        validate_success(first, expected_status=200)
        # Send stale version=1.
        resp = api.update_employee(
            emp["id"],
            update_employee_payload(
                version=1, base_hourly_rate_cents=2200,
            ),
            payroll_admin_headers,
        )
        validate_error(resp, "ERR_VERSION_CONFLICT")

    def test_patch_without_version_skips_occ(
        self, api, payroll_admin_headers,
    ):
        """PRD §2.5: "If the caller omits the `version` field, the OCC
        check is skipped and the mutation proceeds."
        """
        emp = create_employee(base_hourly_rate_cents=2000)
        resp = api.update_employee(
            emp["id"],
            update_employee_payload(base_hourly_rate_cents=2200),
            payroll_admin_headers,
        )
        updated = validate_success(resp, expected_status=200)
        assert updated["base_hourly_rate_cents"] == 2200
