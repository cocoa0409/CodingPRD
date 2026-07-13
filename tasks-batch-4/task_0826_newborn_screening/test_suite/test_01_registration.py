"""Registration and basic entity contract tests (Newborn Screening PRD)."""
from test_helpers import (
    validate_success,
    validate_error,
    NON_EXISTENT_UUID,
    assert_facility,
    assert_infant,
    create_facility_payload,
    create_infant_payload,
    create_facility,
    TEST_USERS,
    make_birth_facility_user_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]


def test_facility_create_returns_201_with_echoed_fields(api):
    """PRD §3.1: "A newly registered facility starts with `total_booked_minutes` at zero."
    PRD §2.4: "`version` — an integer that begins at its initial value on creation and
    increments by one on every mutation."

    Design: Corner/entities/facility_create_returns_201_with_echoed_fields
    """
    res = api.create_facility(
        create_facility_payload(name="State Lab", facility_type="LAB", state_region="CA"),
        ADMIN,
    )
    facility = validate_success(res, 201)
    assert_facility(facility)
    assert facility["name"] == "State Lab"
    assert facility["facility_type"] == "LAB"
    assert facility["state_region"] == "CA"
    assert facility["total_booked_minutes"] == 0
    assert facility["version"] == 1


def test_get_infant_nonexistent_returns_404(api):
    """PRD §2.6: "a missing infant yields `ERR_INFANT_NOT_FOUND`, a missing facility
    `ERR_FACILITY_NOT_FOUND`, a missing specimen `ERR_SPECIMEN_NOT_FOUND`..."

    Design: Corner/entities/get_infant_nonexistent_returns_404
    """
    res = api.get_infant(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_INFANT_NOT_FOUND", expected_status=404)


def test_infant_create_missing_birth_datetime_returns_invalid_request(api):
    """PRD §2.10: "required body fields are present and correctly typed, else
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/infant_create_missing_required_birth_datetime_returns_invalid_request
    """
    facility = create_facility()
    hdr = make_birth_facility_user_headers(facility["id"])
    payload = create_infant_payload(facility["id"])
    del payload["birth_datetime"]
    res = api.create_infant(payload, hdr)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_infant_create_invalid_sex_enum_returns_invalid_enum(api):
    """PRD §2.10: "enum-valued body fields hold a declared member, else `ERR_INVALID_ENUM`
    (422)."
    PRD §3.2: "the recorded `sex` — one of `M`, `F`, or `U`..."

    Design: Corner/entities/infant_create_invalid_sex_enum_returns_invalid_enum
    """
    facility = create_facility()
    hdr = make_birth_facility_user_headers(facility["id"])
    res = api.create_infant(create_infant_payload(facility["id"], sex="X"), hdr)
    validate_error(res, "ERR_INVALID_ENUM", expected_status=422)


def test_infant_multiple_birth_defaults_false_and_version_one(api):
    """PRD §3.2: "an optional `multiple_birth` flag that defaults to false."
    PRD §3.2: "A freshly registered infant starts with `consent_status` at `PENDING`,
    `open_recollection_count` and `open_case_count` at zero, and `followup_status` at
    `CLEAR`."

    Design: Corner/entities/infant_multiple_birth_defaults_false_and_version_one
    """
    facility = create_facility()
    hdr = make_birth_facility_user_headers(facility["id"])
    payload = create_infant_payload(facility["id"])
    payload.pop("multiple_birth", None)
    infant = validate_success(api.create_infant(payload, hdr), 201)
    assert_infant(infant)
    assert infant["multiple_birth"] is False
    assert infant["consent_status"] == "PENDING"
    assert infant["followup_status"] == "CLEAR"
    assert infant["version"] == 1
