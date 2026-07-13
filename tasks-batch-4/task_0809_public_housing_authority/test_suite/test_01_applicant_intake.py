"""Applicant intake, household composition, and unit creation basics."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    applicant_payload, member_payload, unit_payload,
    assert_applicant, assert_unit,
    NON_EXISTENT_UUID,
)

IC = TEST_USERS["intake_clerk_headers"]
PM = TEST_USERS["property_manager_headers"]


def test_applicant_create_starts_applied(api):
    """PRD §3.1: "The new Applicant begins in the APPLIED state, and the system
    stamps its application_date from the logical clock at creation time."
    PRD §2.9: "On startup the clock reads exactly 2026-03-01T00:00:00Z, and until
    it is explicitly set it never advances to real wall-clock time."

    Design: Corner/entities/applicant_create_returns_201_with_system_fields
    """
    resp = api.create_applicant(applicant_payload("Nguyen"), IC)
    data = validate_success(resp, expected_status=201)
    assert_applicant(data)
    assert data["status"] == "APPLIED", f"expected APPLIED, got {data['status']}"
    assert data["application_date"].startswith("2026-03-01T00:00:00"), \
        f"application_date should be the unset-clock default, got {data['application_date']}"


def test_applicant_create_has_zero_household_size(api):
    """PRD §3.1: "household_size is the count of the applicant's household members".

    Design: Corner/entities/applicant_create_returns_201_with_system_fields
    """
    data = get_success_data(api.create_applicant(applicant_payload("FreshHH"), IC))
    assert data["household_size"] == 0, f"a new applicant has no members, got {data['household_size']}"


def test_applicant_missing_household_name_rejected(api):
    """PRD §2.5: "request-body field validation (ERR_VALIDATION), which confirms
    that required fields are present, that types and enum members are valid, and
    that amounts declared as non-negative are not negative."

    Design: Corner/entities/applicant_missing_household_name_rejected
    """
    resp = api.create_applicant({}, IC)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_member_invalid_relationship_enum_rejected(api):
    """PRD §3.1: "a relationship — one of HEAD, SPOUSE, DEPENDENT, or OTHER_ADULT."
    PRD §2.5: request-body field validation "confirms ... that types and enum
    members are valid ... (ERR_VALIDATION)".

    Design: Corner/entities/member_invalid_relationship_enum_rejected
    """
    app = get_success_data(api.create_applicant(applicant_payload("EnumTest"), IC))
    resp = api.add_member(app["id"], member_payload("Bad", "COUSIN"), IC)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_unit_create_defaults_utility_allowance_zero(api):
    """PRD §3.4: "A unit may optionally declare a utility_allowance_cents (a
    non-negative monthly utility allowance in whole cents, default 0)".
    PRD §3.4: "A unit's status is AVAILABLE, OFFERED, or OCCUPIED, beginning at
    AVAILABLE".

    Design: Corner/entities/unit_create_defaults_utility_allowance_zero
    """
    resp = api.create_unit(unit_payload("U-D", bedroom_size=2, income_limit_cents=5000000), PM)
    data = validate_success(resp, expected_status=201)
    assert_unit(data)
    assert data["utility_allowance_cents"] == 0, \
        f"omitted utility_allowance_cents should default to 0, got {data['utility_allowance_cents']}"
    assert data["status"] == "AVAILABLE", f"new unit should be AVAILABLE, got {data['status']}"


def test_applicant_not_found_returns_404(api):
    """PRD §2.5: "the system resolves them left to right and rejects the request at
    the first identifier that does not correspond to a live resource, returning the
    not-found error specific to that resource — ERR_APPLICANT_NOT_FOUND ... (all HTTP 404)."

    Design: Corner/entities/applicant_not_found_returns_404
    """
    resp = api.get_applicant(NON_EXISTENT_UUID, IC)
    validate_error(resp, ApiErrorId.ERR_APPLICANT_NOT_FOUND)
