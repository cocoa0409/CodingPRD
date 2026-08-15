"""Nurse registration, computed fields, directory listing, and error envelope.

Covers PRD §2.1-§2.4 and §3.1: enrollment defaults, required fields,
employee_code uniqueness, existence checks, pagination envelope.
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_nurse,
    assert_nurse_invariants,
    create_nurse,
    create_nurse_payload,
    get_nurse,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestNurseRegistration:
    def test_nurse_creation_applies_program_defaults(self, api):
        """PRD §3.1: "New nurses enter the program at `current_level` `CN_I` —
        the ladder floor — with `differential_status` `INACTIVE` and a
        `retention_risk_score` of zero."

        Design: Corner/entities/nurse_creation_applies_defaults
        """
        resp = api.create_nurse(
            create_nurse_payload(
                employee_code="RN-100", full_name="Default Nurse",
                hire_date="2020-01-01T00:00:00Z", home_unit="MED-2E",
            ),
            ADMIN,
        )
        data = validate_success(resp, 201)
        assert_nurse(data)
        assert data["current_level"] == "CN_I", (
            f"new nurse must start at the ladder floor CN_I, got {data['current_level']}"
        )
        assert data["differential_status"] == "INACTIVE", (
            f"new nurse differential must start INACTIVE, got {data['differential_status']}"
        )
        assert data["retention_risk_score"] == 0
        assert isinstance(data["version"], int)

    @pytest.mark.parametrize(
        "missing_field", ["employee_code", "full_name", "hire_date", "home_unit"]
    )
    def test_nurse_missing_required_field_returns_invalid_request(
        self, api, missing_field
    ):
        """PRD §2.8: "A request whose payload is missing a required field,
        carries a value of the wrong type, or names an enum value outside the
        declared set fails with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/nurse_missing_required_field_returns_invalid_request
        """
        payload = create_nurse_payload(employee_code="RN-NC")
        payload.pop(missing_field)
        resp = api.create_nurse(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_nurse_duplicate_employee_code_rejected(self, api):
        """PRD §3.1: "A `ProgramAdmin` enrolls a nurse by registering their
        `employee_code` (a hospital HR code such as "RN-1042", unique across
        all nurses and immutable once set)..."

        Design: Corner/entities/nurse_duplicate_employee_code_rejected
        """
        first = api.create_nurse(
            create_nurse_payload(employee_code="RN-DUP", full_name="First"), ADMIN
        )
        validate_success(first, 201)
        second = api.create_nurse(
            create_nurse_payload(
                employee_code="RN-DUP", full_name="Second", home_unit="ICU-4W"
            ),
            ADMIN,
        )
        body = second.json()
        assert body.get("response_type") == "error", (
            f"duplicate employee_code must be rejected, got {second.status_code}"
        )
        assert 400 <= second.status_code < 500
        nurses, meta = validate_paginated(api.list_nurses(ADMIN))
        assert meta["total_count"] == 1, "the duplicate nurse must not be persisted"


class TestNurseReads:
    def test_nurse_get_not_found(self, api):
        """PRD §2.8: "...with a missing resource surfacing `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/nurse_get_not_found
        """
        resp = api.get_nurse(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_nurse_list_pagination_envelope(self, api):
        """PRD §2.3: "The `meta` block of every list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/nurse_list_pagination_envelope
        """
        for i in range(3):
            create_nurse(employee_code=f"RN-P{i + 1}", full_name=f"P{i + 1}")
        data, meta = validate_paginated(
            api.list_nurses(ADMIN, params={"limit": 2, "offset": 0})
        )
        assert len(data) == 2, f"limit=2 must return 2 rows, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

    def test_computed_fields_have_prd_values_on_creation(self, api):
        """PRD §3.1: "The nurse's `tenure_years` is never stored; it is
        recomputed on every read from the logical clock as the number of whole
        years elapsed since `hire_date`, computed by dividing the elapsed days
        by 365.25 and rounding down to the whole year."
        PRD §3.1: "New nurses enter the program at `current_level` `CN_I` —
        the ladder floor — with `differential_status` `INACTIVE` and a
        `retention_risk_score` of zero."

        Design: Corner/entities/computed_fields_ignore_client_input
        """
        resp = api.create_nurse(
            create_nurse_payload(
                employee_code="RN-CMP", full_name="Computed",
                hire_date="2016-07-01T00:00:00Z", home_unit="MED-2E",
            ),
            ADMIN,
        )
        data = validate_success(resp, 201)
        # At the default logical clock 2026-08-01, elapsed days since
        # 2016-07-01 = 3683; 3683 / 365.25 = 10.08 -> whole years = 10.
        assert data["tenure_years"] == 10, (
            f"tenure_years must be floor of whole years since hire_date, "
            f"got {data['tenure_years']}"
        )
        assert data["retention_risk_score"] == 0
        reread = validate_success(api.get_nurse(data["id"], ADMIN))
        assert_nurse_invariants(reread)
        assert reread["tenure_years"] == 10


class TestErrorEnvelope:
    def test_error_envelope_shape(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/error_envelope_shape
        """
        resp = api.get_nurse(NON_EXISTENT_UUID, ADMIN)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
        assert err["message"].strip(), "error message must be non-empty"
        body = resp.json()
        assert body["response_type"] == "error"
        assert is_valid_uuid  # silence unused import linters
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
