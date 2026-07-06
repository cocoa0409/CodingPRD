"""Breadth coverage: CRUD basics, RBAC, screening approval errors."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, build_user_headers,
    create_under_review_application, setup_listed_inventory_with_consented_recipient,
    place_hold,
)

SO = TEST_USERS["screening_officer_headers"]
LT = TEST_USERS["lab_tech_headers"]
CM = TEST_USERS["catalog_manager_headers"]


# ---------------------------------------------------------------------------
# entities
# ---------------------------------------------------------------------------
def test_create_donor_returns_201_with_defaults(api):
    """PRD §3.1: "A freshly registered donor enters status APPLICANT, with
    reported_family_count initialized to 0, fda_eligible and genetic_panel_clear both
    false by default, and is_family_limit_reached false."

    Design: Corner/entities/create_donor_returns_201_and_defaults
    """
    data = validate_success(api.create_donor({
        "display_code": "D-C1", "full_name": "Corner One", "donor_type": "OOCYTE",
        "blood_type": "A_POS", "family_limit": 5,
    }, SO), expected_status=201)
    assert data["status"] == "APPLICANT"
    assert data["reported_family_count"] == 0
    assert data["is_family_limit_reached"] is False
    assert data["version"] == 1


def test_get_donor_not_found_returns_404(api):
    """PRD §2.5: "If any referenced identifier does not resolve to an existing
    entity, the request is rejected with ERR_NOT_FOUND".

    Design: Corner/entities/get_donor_not_found_returns_404
    """
    resp = api.get_donor(NON_EXISTENT_UUID, SO)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_donor_missing_required_field_returns_invalid_request(api):
    """PRD §2.9: "When a required field is absent, an enum value is not one of the
    permitted strings, or one of these numeric constraints is violated, the create is
    rejected with ERR_INVALID_REQUEST at HTTP 400."

    Design: Corner/entities/create_donor_missing_required_field_returns_invalid_request
    """
    resp = api.create_donor({
        "display_code": "D-C2", "full_name": "Corner Two", "donor_type": "SPERM",
        "blood_type": "O_POS",  # family_limit omitted
    }, SO)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_specimen_nonpositive_vial_count_returns_invalid_request(api):
    """PRD §2.9: "Several fields must be supplied as strictly positive integers:
    initial_vial_count on a specimen, vial_count on a vial reservation, family_limit
    on a donor, and stored_vials on a storage account must each be at least 1."

    Design: Corner/entities/create_specimen_nonpositive_vial_count_returns_invalid_request
    """
    donor = validate_success(api.create_donor({
        "display_code": "D-C3", "full_name": "Corner Three", "donor_type": "SPERM",
        "blood_type": "O_POS", "family_limit": 5,
    }, SO), expected_status=201)
    resp = api.create_specimen({
        "donor_id": donor["id"], "collection_date": "2026-05-01T00:00:00Z",
        "initial_vial_count": 0, "quarantine_release_date": "2026-06-01T00:00:00Z",
        "retest_negative": True,
    }, LT)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_donor_list_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the meta
    object of the response envelope: limit, offset, total_count, and has_more."

    Design: Corner/entities/donor_list_pagination_envelope
    """
    validate_success(api.create_donor({
        "display_code": "D-C4a", "full_name": "P A", "donor_type": "SPERM",
        "blood_type": "O_POS", "family_limit": 5}, SO), expected_status=201)
    validate_success(api.create_donor({
        "display_code": "D-C4b", "full_name": "P B", "donor_type": "OOCYTE",
        "blood_type": "A_NEG", "family_limit": 5}, SO), expected_status=201)
    data, meta = validate_paginated(api.list_donors(CM, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ---------------------------------------------------------------------------
# rbac
# ---------------------------------------------------------------------------
def test_labtech_cannot_approve_screening(api):
    """PRD §2.1: "When the headers are valid but the named role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE."
    PRD §4: the approve operation is authorized for ScreeningOfficer only.

    Design: Corner/rbac/labtech_cannot_approve_screening
    """
    donor_id, app_id = create_under_review_application(display_code="D-C17")
    resp = api.approve_application(app_id, LT)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    app = validate_success(api.get_screening_application(app_id, SO))
    assert app["status"] == "UNDER_REVIEW"


def test_recipient_cannot_confirm_reservation(api):
    """PRD §2.1: "When the headers are valid but the named role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE."
    PRD §4: confirm a held reservation is authorized for CatalogManager only.

    Design: Corner/rbac/recipient_cannot_confirm_reservation
    """
    ctx = setup_listed_inventory_with_consented_recipient(
        display_code="D-C18", dewar_code="T-C18", initial_vial_count=5)
    res = place_hold(ctx["inventory_id"], ctx["recipient_id"], ctx["headers"], 1,
                     ctx["inventory_version"])
    resp = api.confirm_reservation(res["id"], ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    reservation = validate_success(api.get_vial_reservation(res["id"], CM))
    assert reservation["status"] == "HELD"


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role does not name a
    recognized role, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    nobody = build_user_headers("nobody-1", "Nobody")
    resp = api.create_donor({
        "display_code": "D-C19", "full_name": "Corner Nineteen", "donor_type": "SPERM",
        "blood_type": "O_POS", "family_limit": 5,
    }, nobody)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------
def test_approve_with_fda_risk_flag_returns_fda_ineligible(api):
    """PRD §3.1: "If an approval is attempted while fda_risk_flag is true, it is
    rejected with ERR_FDA_INELIGIBLE."

    Design: Corner/errors/error_fda_ineligible_on_approve
    """
    donor_id, app_id = create_under_review_application(
        display_code="D-C22", fda_risk_flag=True, genetic_carrier_count=0)
    resp = api.approve_application(app_id, SO)
    validate_error(resp, ApiErrorId.ERR_FDA_INELIGIBLE.value)
    donor = validate_success(api.get_donor(donor_id, SO))
    assert donor["status"] == "SCREENING"


def test_approve_with_incomplete_genetic_screening_returns_error(api):
    """PRD §3.1: "If an approval is attempted while genetic_carrier_count is greater
    than 0 and partner_screening_required is true, it is rejected with
    ERR_GENETIC_SCREENING_INCOMPLETE."

    Design: Corner/errors/error_genetic_screening_incomplete_on_approve
    """
    donor_id, app_id = create_under_review_application(
        display_code="D-C23", fda_risk_flag=False, genetic_carrier_count=1,
        partner_screening_required=True)
    resp = api.approve_application(app_id, SO)
    validate_error(resp, ApiErrorId.ERR_GENETIC_SCREENING_INCOMPLETE.value)
    donor = validate_success(api.get_donor(donor_id, SO))
    assert donor["status"] == "SCREENING"
