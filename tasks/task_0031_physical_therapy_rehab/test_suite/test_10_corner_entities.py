"""Corner Coverage — entities section.

CRUD primitives, defaults, type constraints, and uniqueness checks on Patient
and Therapist (the two non-FK-rooted entities most exercised by the corner index).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    set_clock,
    create_patient_payload,
    create_therapist_payload,
    NON_EXISTENT_UUID,
    TEST_USERS,
)


def test_patient_creation_with_required_fields_returns_201(api):
    """PRD §3.1: "On successful creation the patient is persisted with `status` `ACTIVE`."
    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by one
    with every mutation."

    Design: Corner/entities/patient_creation_with_required_fields_returns_201
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_patient(
        create_patient_payload(
            full_name="Alice", date_of_birth="1980-01-15",
            insurance_type="COMMERCIAL", is_veteran=False,
        ),
        TEST_USERS["platform_admin_headers"],
    )
    pt = validate_success(res, 201)
    assert pt["status"] == "ACTIVE"
    assert pt["version"] == 1


def test_patient_get_by_nonexistent_id_returns_404(api):
    """PRD §2.5: "If the identifier in any position does not name an existing row,
    the request is rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) for that segment,
    before any later segment or any body field is inspected."

    Design: Corner/entities/patient_get_by_nonexistent_id_returns_404
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.get_patient(NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"])
    validate_error(res, "ERR_RESOURCE_NOT_FOUND", expected_status=404)


def test_patient_list_pagination_envelope_total_count_has_more(api):
    """PRD §2.3: "Each list response includes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/patient_list_pagination_envelope_total_count_has_more
    """
    set_clock("2026-06-01T00:00:00Z")
    admin = TEST_USERS["platform_admin_headers"]
    for i, dob in enumerate(["1970-01-01", "1971-01-01", "1972-01-01"]):
        api.create_patient(
            create_patient_payload(
                full_name=f"P{i+1}", date_of_birth=dob,
                insurance_type="COMMERCIAL", is_veteran=False,
            ),
            admin,
        )
    data, meta = validate_paginated(api.list_patients(admin))
    assert len(data) == 3
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_patient_missing_required_field_returns_invalid_request(api):
    """PRD §3.1: "The payload supplies `full_name` (the patient's legal name, between
    1 and 120 characters), `date_of_birth` as an ISO 8601 date in `YYYY-MM-DD` form, and
    `insurance_type` from the closed enum `MEDICARE`, `COMMERCIAL`, `MEDICAID`,
    `VA_TRICARE`, `SELF_PAY`."
    PRD §2.11: "and finally generic input validation (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/patient_missing_required_field_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_patient(
        # Missing full_name.
        {"date_of_birth": "1970-01-01", "insurance_type": "COMMERCIAL", "is_veteran": False},
        TEST_USERS["platform_admin_headers"],
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_patient_is_veteran_default_false_when_omitted(api):
    """PRD §3.1: "The `is_veteran` flag is optional and defaults to false."

    Design: Corner/entities/patient_is_veteran_default_false_when_omitted
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_patient(
        # Omit is_veteran entirely.
        {"full_name": "DefaultPat", "date_of_birth": "1970-01-01",
         "insurance_type": "COMMERCIAL"},
        TEST_USERS["platform_admin_headers"],
    )
    pt = validate_success(res, 201)
    assert pt["is_veteran"] is False


def test_patient_insurance_type_invalid_enum_returns_invalid_request(api):
    """PRD §3.1: "`insurance_type` from the closed enum `MEDICARE`, `COMMERCIAL`,
    `MEDICAID`, `VA_TRICARE`, `SELF_PAY`."
    PRD §2.11: "and finally generic input validation (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/patient_insurance_type_invalid_enum_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_patient(
        create_patient_payload(
            full_name="BadEnumPat", date_of_birth="1970-01-01",
            insurance_type="INVALID_PAYER", is_veteran=False,
        ),
        TEST_USERS["platform_admin_headers"],
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_therapist_npi_uniqueness_enforced(api):
    """PRD §3.1: "the ten-digit `npi_number` (the National Provider Identifier, which
    must be unique across the `Therapist` table)"

    Design: Corner/entities/therapist_npi_uniqueness_enforced
    """
    set_clock("2026-06-01T00:00:00Z")
    admin = TEST_USERS["platform_admin_headers"]
    first = api.create_therapist(
        create_therapist_payload(
            full_name="Th One", npi_number="2000000001",
            license_state="CA", medicare_provider_enrolled=False,
        ),
        admin,
    )
    validate_success(first, 201)
    dup = api.create_therapist(
        create_therapist_payload(
            full_name="Th Two", npi_number="2000000001",
            license_state="CA", medicare_provider_enrolled=False,
        ),
        admin,
    )
    validate_error(dup, "ERR_INVALID_REQUEST", expected_status=400)
