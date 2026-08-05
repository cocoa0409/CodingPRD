"""Reference data, clinician/facility registration, defaults, and the logical clock.

Covers Corner/entities and Corner/endpoints instances for the create/read surface.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, is_valid_uuid,
    create_clinician_payload, create_facility_payload, create_per_diem_locality_payload,
    create_license_payload,
    assert_per_diem_locality_shape, assert_timestamp_millis_z,
    DEFAULT_CLOCK_TIMESTAMP, UNKNOWN_UUID,
)
from test_helpers.fixtures import create_clinician

RECRUITER = TEST_USERS["recruiter_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]
CS1 = TEST_USERS["credentialing_specialist_headers"]


def test_clinician_creation_applies_defaults_and_system_fields(api):
    """PRD §3.1: "The optional tax_home_verified flag defaults to false and gates
    whether per-diem stipends may be paid tax-free. On registration the clinician's
    derived status is initialized to AVAILABLE (its other possible values being
    ON_ASSIGNMENT and INACTIVE), the active_assignment_count is initialized to 0,
    and both the ytd_taxable_wages_cents and ytd_nontaxable_stipend_cents counters
    are initialized to 0."
    PRD §2.4: "The version is an integer that starts at 1 on creation"

    Design: Corner/entities/corner_clinician_creation_applies_defaults_and_system_fields
    """
    payload = create_clinician_payload(full_name="Ada Reyes", discipline="RN", specialty="ICU",
                                       employment_type="W2_EMPLOYEE", primary_residence_state="TX")
    payload.pop("tax_home_verified", None)  # omit optional field
    resp = api.create_clinician(payload, RECRUITER)
    data = validate_success(resp, 201)
    assert resp.json()["response_type"] == "object"
    assert data["tax_home_verified"] is False
    assert data["status"] == "AVAILABLE"
    assert data["active_assignment_count"] == 0
    assert data["ytd_taxable_wages_cents"] == 0
    assert data["ytd_nontaxable_stipend_cents"] == 0
    assert data["version"] == 1
    assert data["created_at"] == DEFAULT_CLOCK_TIMESTAMP
    assert is_valid_uuid(data["id"]) and not data["id"].startswith("clin")


def test_clinician_get_unknown_id_returns_not_found(api):
    """PRD §2.10: "if a parent id in the path does not resolve, the corresponding
    not-found error is returned before any child filtering is attempted. Which error
    surfaces depends on which resource the unresolved id addresses:
    ERR_CLINICIAN_NOT_FOUND, ..."

    Design: Corner/entities/corner_clinician_get_unknown_id_not_found
    """
    resp = api.get_clinician(UNKNOWN_UUID, RECRUITER)
    err = validate_error(resp, ApiErrorId.ERR_CLINICIAN_NOT_FOUND.value)
    assert resp.json()["response_type"] == "error"
    assert set(err.keys()) <= {"error_id", "message"}


def test_clinician_create_missing_employment_type_rejected(api):
    """PRD §2.8: "Request shape — required fields present, types correct, ... else
    ERR_VALIDATION."
    PRD §3.1: "A Recruiter registers a traveling clinician with a full_name, a
    discipline ..., an employment_type (either W2_EMPLOYEE, which carries employer
    burden, or CONTRACTOR_1099, which does not) ..."

    Design: Corner/entities/corner_clinician_create_missing_required_employment_type_rejected
    """
    resp = api.create_clinician(
        {"full_name": "Ada Reyes", "discipline": "RN", "specialty": "ICU",
         "primary_residence_state": "TX"}, RECRUITER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_clinician_create_invalid_discipline_enum_rejected(api):
    """PRD §3.1: "A Recruiter registers a traveling clinician with a full_name, a
    discipline (one of RN, NP, PHYSICIAN, CRNA, THERAPIST), ..."
    PRD §2.8: "Request shape — ... enum members legal, ... else ERR_VALIDATION."

    Design: Corner/entities/corner_clinician_create_invalid_enum_discipline_rejected
    """
    resp = api.create_clinician(
        {"full_name": "Ada Reyes", "discipline": "PARAMEDIC", "specialty": "ICU",
         "employment_type": "W2_EMPLOYEE", "primary_residence_state": "TX"}, RECRUITER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_facility_optional_fields_fall_back_to_defaults(api):
    """PRD §3.1: "A facility may optionally declare is_compact_member, which is false
    unless supplied and marks the facility's state as recognizing multi-state compact
    licensure, and max_concurrent_travelers, its aggregate capacity, which defaults
    to 2 and must be at least 1."

    Design: Corner/entities/corner_facility_optional_fields_fall_back_to_declared_defaults
    """
    resp = api.create_facility(
        {"name": "Mesa Regional", "state_code": "AZ", "per_diem_locality_code": "PHX-AZ",
         "billing_contact_email": "ap@mesa.example"}, PLATFORM)
    data = validate_success(resp, 201)
    assert data["is_compact_member"] is False
    assert data["max_concurrent_travelers"] == 2


def test_per_diem_locality_is_immutable_and_carries_no_version(api):
    """PRD §2.4: "One entity is the exception: the PerDiemLocality reference row does
    not carry the common mutation fields. A PerDiemLocality exposes only id and
    created_at; it has no updated_at and no version, because per-diem rate rows are
    immutable once filed."

    Design: Corner/entities/corner_per_diem_locality_is_immutable_and_carries_no_version
    """
    resp = api.create_per_diem_locality(create_per_diem_locality_payload(), PLATFORM)
    data = validate_success(resp, 201)
    assert_per_diem_locality_shape(data)
    assert data["created_at"] == DEFAULT_CLOCK_TIMESTAMP


def test_license_status_input_ignored_on_create(api):
    """PRD §3.1: "A newly filed license is created in PENDING_VERIFICATION."

    Design: Corner/entities/corner_license_status_input_ignored_on_create
    """
    clin = create_clinician(api)
    payload = create_license_payload(clin["id"])
    payload["status"] = "VERIFIED"  # client-supplied system field
    resp = api.create_license(payload, RECRUITER)
    if resp.status_code == 400:
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
    else:
        data = validate_success(resp, 201)
        assert data["status"] == "PENDING_VERIFICATION", "license must never be created VERIFIED"
        assert data["verified_by_user_id"] is None
        assert data["verified_at"] is None


def test_logical_clock_defaults_then_moves(api):
    """PRD §2.4: "Before that capability is first invoked, the logical clock reads
    exactly 2026-05-01T00:00:00Z; it never falls back to real wall-clock time."
    PRD §2.4: "Both created_at and updated_at are ISO 8601 UTC timestamps with exactly
    three fractional digits (of the form YYYY-MM-DDTHH:MM:SS.mmmZ)."

    Design: Corner/endpoints/corner_logical_clock_defaults_to_2026_05_01_until_set
    """
    early = create_clinician(api, full_name="Early Bird", specialty="ER")
    assert early["created_at"] == DEFAULT_CLOCK_TIMESTAMP
    assert early["updated_at"] == DEFAULT_CLOCK_TIMESTAMP

    # PRD does not pin the fractional-digit rendering of the returned current_utc
    # (it is not one of created_at/updated_at/verified_at/... and §2.4 writes the
    # clock instant with a bare Z); asserting one exact form is non-derivable, so
    # we only assert the clock advance took effect via the created_at below.
    validate_success(api.set_clock("2026-08-01T12:00:00Z", PLATFORM), 200)

    late = create_clinician(api, full_name="Late Bird", specialty="ER")
    assert late["created_at"] == "2026-08-01T12:00:00.000Z"
    assert_timestamp_millis_z(late["created_at"])


def test_pagination_limit_above_maximum_rejected(api):
    """PRD §2.3: "The limit defaults to 10, must be at least 1, and may not exceed
    100. ... A limit outside the range 1 through 100, or a negative offset, is a
    body/parameter shape error and is rejected with ERR_VALIDATION (HTTP 400)."

    Design: Corner/endpoints/corner_pagination_limit_above_maximum_rejected
    """
    validate_error(api.list_assignments(RECRUITER, params={"limit": 101, "offset": 0}),
                   ApiErrorId.ERR_VALIDATION.value)
    data, meta = validate_paginated(api.list_assignments(RECRUITER, params={"limit": 100, "offset": 0}))
    assert data == [] and meta["total_count"] == 0 and meta["has_more"] is False
    data2, meta2 = validate_paginated(api.list_assignments(RECRUITER))
    assert meta2["limit"] == 10 and meta2["offset"] == 0
