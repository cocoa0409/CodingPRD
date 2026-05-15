"""Applicant / University / Program CRUD and validation tests.

Covers PRD §3.1 (Applicant onboarding), §3.2 (Universities and Programs),
§3.3 (Application input shape validation).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    assert_applicant,
    assert_program,
    assert_university,
    assert_version_incremented_by_one,
    create_applicant,
    create_applicant_payload,
    create_program_payload,
    create_university,
    create_university_payload,
    iso_offset,
    make_applicant_headers,
    NON_EXISTENT_UUID,
    setup_university_with_program,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Applicant create (PRD §3.1)
# ---------------------------------------------------------------------------
class TestApplicantCreate:

    def test_create_applicant_returns_resource_with_common_fields(
        self, api, platform_admin_headers,
    ):
        """PRD §2.4: "Every persisted resource is keyed by an id, which
        is a server-minted UUID string with no type prefix. Resources
        record their birth time in created_at and the moment of their
        most recent mutation in updated_at; both are ISO 8601 UTC
        timestamps with three fractional digits. A monotonic integer
        version starts at 1 on creation and increments by one on every
        successful mutation of that resource."
        """
        res = api.create_applicant(
            create_applicant_payload(), platform_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_applicant(data)
        assert data["version"] == 1, (
            f"initial version must be 1, got {data['version']}"
        )

    def test_create_applicant_initial_ed_commitment_is_null(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "A ninth applicant field, ed_commitment_application_id,
        is system-managed and starts as null."
        """
        res = api.create_applicant(
            create_applicant_payload(), platform_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data.get("ed_commitment_application_id") is None, (
            f"ed_commitment_application_id must start as null, "
            f"got {data.get('ed_commitment_application_id')!r}"
        )

    def test_create_applicant_gpa_above_4_yields_err_validation(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "Applicant numeric ranges (high_school_gpa between
        0.00 and 4.00 inclusive, household_income_cents at least zero)
        are enforced on both create and update with ERR_VALIDATION."
        """
        res = api.create_applicant(
            create_applicant_payload(high_school_gpa=4.01),
            platform_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_create_applicant_gpa_below_zero_yields_err_validation(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "Applicant numeric ranges (high_school_gpa between
        0.00 and 4.00 inclusive, household_income_cents at least zero)
        are enforced on both create and update with ERR_VALIDATION."
        """
        res = api.create_applicant(
            create_applicant_payload(high_school_gpa=-0.01),
            platform_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_create_applicant_gpa_at_4_accepted(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "high_school_gpa between 0.00 and 4.00 inclusive."

        Boundary: 4.00 is the inclusive upper bound; must be accepted.
        """
        res = api.create_applicant(
            create_applicant_payload(high_school_gpa=4.00),
            platform_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["high_school_gpa"] == 4.00

    def test_create_applicant_gpa_at_zero_accepted(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "high_school_gpa between 0.00 and 4.00 inclusive.\""""
        res = api.create_applicant(
            create_applicant_payload(high_school_gpa=0.00),
            platform_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["high_school_gpa"] == 0.00

    def test_create_applicant_negative_income_yields_err_validation(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "household_income_cents at least zero ... are
        enforced ... with ERR_VALIDATION.\""""
        res = api.create_applicant(
            create_applicant_payload(household_income_cents=-1),
            platform_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_create_applicant_dob_too_young_yields_err_validation(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "a date_of_birth younger than 14 years before now
        also fails as ERR_VALIDATION."
        """
        # 13 years before today — younger than the 14-year cutoff.
        too_young = (date.today() - timedelta(days=13 * 365)).isoformat()
        res = api.create_applicant(
            create_applicant_payload(date_of_birth=too_young),
            platform_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_create_applicant_email_uniqueness(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "an email address conforming to RFC 5322 and
        unique across applicants.\""""
        payload = create_applicant_payload()
        res1 = api.create_applicant(payload, platform_admin_headers)
        validate_success(res1, expected_status=201)
        # Re-use the same email.
        res2 = api.create_applicant(
            create_applicant_payload(email=payload["email"]),
            platform_admin_headers,
        )
        validate_error(res2, ApiErrorId.ERR_VALIDATION.value)

    def test_create_applicant_optional_efcs_default_to_null(
        self, api, platform_admin_headers,
    ):
        """PRD §3.1: "Two further fields — fafsa_efc_cents and
        css_profile_efc_cents — are optional on creation and default
        to null.\""""
        payload = create_applicant_payload()
        # Strip optionals.
        payload.pop("fafsa_efc_cents", None)
        payload.pop("css_profile_efc_cents", None)
        res = api.create_applicant(payload, platform_admin_headers)
        data = validate_success(res, expected_status=201)
        assert data.get("fafsa_efc_cents") is None
        assert data.get("css_profile_efc_cents") is None


# ---------------------------------------------------------------------------
# Applicant read / update (PRD §3.1)
# ---------------------------------------------------------------------------
class TestApplicantReadAndUpdate:

    def test_get_applicant_not_found(self, api, platform_admin_headers):
        """PRD §2.6: "Missing Applicant ... records produce
        ERR_APPLICANT_NOT_FOUND."
        """
        res = api.get_applicant(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(res, ApiErrorId.ERR_APPLICANT_NOT_FOUND.value)

    def test_patch_applicant_updates_gpa_and_increments_version(self, api):
        """PRD §2.4: "A monotonic integer version starts at 1 on
        creation and increments by one on every successful mutation
        of that resource.\""""
        applicant = create_applicant(high_school_gpa=3.50)
        res = api.patch_applicant(
            applicant["id"], {"high_school_gpa": 3.75},
            make_applicant_headers(applicant["id"]),
        )
        data = validate_success(res)
        assert data["high_school_gpa"] == 3.75
        assert_version_incremented_by_one(applicant, data)

    def test_patch_applicant_with_wrong_version_yields_err_version_conflict(
        self, api,
    ):
        """PRD §2.5: "When version is supplied, the server compares it
        to the entity's current version before performing the mutation
        and rejects the request with ERR_VERSION_CONFLICT (HTTP 409)
        when the two differ."
        """
        applicant = create_applicant()
        res = api.patch_applicant(
            applicant["id"],
            {"high_school_gpa": 3.10, "version": 999},
            make_applicant_headers(applicant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_patch_applicant_invalid_gpa_yields_err_validation(self, api):
        """PRD §3.1: "Applicant numeric ranges ... are enforced on
        both create and update with ERR_VALIDATION."
        """
        applicant = create_applicant()
        res = api.patch_applicant(
            applicant["id"], {"high_school_gpa": 4.50},
            make_applicant_headers(applicant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)


# ---------------------------------------------------------------------------
# University (PRD §3.2)
# ---------------------------------------------------------------------------
class TestUniversity:

    def test_create_university_returns_resource_with_common_fields(
        self, api, platform_admin_headers,
    ):
        """PRD §2.4 common fields + §3.2 university defaults."""
        res = api.create_university(
            create_university_payload(), platform_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_university(data)
        assert data["version"] == 1

    def test_create_university_default_rolling_admission_false(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: "a boolean rolling_admission_enabled flag that
        defaults to false."
        """
        payload = create_university_payload()
        payload.pop("rolling_admission_enabled", None)
        res = api.create_university(payload, platform_admin_headers)
        data = validate_success(res, expected_status=201)
        assert data["rolling_admission_enabled"] is False

    def test_create_university_enrolled_count_starts_at_zero(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: "A university also exposes a running enrolled_count
        that begins at zero..."
        """
        res = api.create_university(
            create_university_payload(), platform_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["enrolled_count"] == 0

    def test_create_university_yield_target_at_least_one(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: "a yield_target_count of at least one (the total
        enrolled-class size the admissions office targets across all
        programs after yield management)."
        """
        res = api.create_university(
            create_university_payload(yield_target_count=0),
            platform_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)


# ---------------------------------------------------------------------------
# Program (PRD §3.2)
# ---------------------------------------------------------------------------
class TestProgram:

    def test_create_program_returns_resource(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: each Program references its owning university_id,
        has a name unique within that university, and a capacity of
        at least one applications.
        """
        uni = create_university()
        res = api.create_program(
            uni["id"], create_program_payload(),
            platform_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_program(data)
        assert data["university_id"] == uni["id"]
        assert data["admitted_count"] == 0

    def test_create_program_capacity_zero_yields_err_validation(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: "a capacity of at least one applications that may
        sit in ADMITTED or ENROLLED simultaneously."
        """
        uni = create_university()
        res = api.create_program(
            uni["id"], create_program_payload(capacity=0),
            platform_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_create_program_under_missing_university_yields_not_found(
        self, api, platform_admin_headers,
    ):
        """PRD §2.6: "Missing ... University ... records produce ...
        ERR_UNIVERSITY_NOT_FOUND."
        """
        res = api.create_program(
            NON_EXISTENT_UUID, create_program_payload(),
            platform_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_UNIVERSITY_NOT_FOUND.value)

    def test_get_program_not_found(self, api, platform_admin_headers):
        """PRD §2.6: "Missing ... Program ... produce ERR_PROGRAM_NOT_FOUND."
        """
        res = api.get_program(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value)
