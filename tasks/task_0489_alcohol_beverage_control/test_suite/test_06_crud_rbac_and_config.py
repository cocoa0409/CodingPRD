"""Configuration CRUD, field validation, defaults, listing envelope, initial
state, and role-based access control.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    NON_EXISTENT_UUID,
    make_applicant_headers,
    ApiErrorId,
    setup_reference_data,
    create_submitted_application,
    setup_issued_license,
    advance_to_protest_period,
)

DIRECTOR = TEST_USERS["director_headers"]
ZONING = TEST_USERS["zoning_officer_headers"]


# ─── Queue B: entities ────────────────────────────────────────────────────
def test_create_license_class_returns_201_with_fields(api):
    """PRD §3.1: "A **license class** is created with a `code` ... Each class
    declares a `premise_type` ... a `base_fee_cents` annual base fee of zero or
    more; a `renewal_cycle_months` term length that must be 12, 24, or 36 ... and
    a `max_servers_per_license` count"
    PRD §4: "Operations that create a new, stand-alone resource return `201
    Created`."

    Design: Corner/entities/create_license_class_returns_201_with_all_fields
    """
    data = validate_success(api.create_license_class(
        {"code": "OFF_21", "premise_type": "OFF_PREMISE", "quota_managed": True,
         "base_fee_cents": 80000, "renewal_cycle_months": 24, "requires_zoning": True,
         "max_servers_per_license": 0}, DIRECTOR), expected_status=201)
    assert data["code"] == "OFF_21"
    assert data["base_fee_cents"] == 80000
    assert data["renewal_cycle_months"] == 24
    assert "id" in data and data["id"]


def test_get_quota_region_not_found_returns_404(api):
    """PRD §2.5: "Existence of every path and body foreign key is checked this way
    (applicants, premises, license classes, quota regions, applications, licenses,
    protests, hearings, violations, and the rest); a reference to a non-existent
    resource always yields `ERR_NOT_FOUND`."

    Design: Corner/entities/get_quota_region_not_found_returns_404
    """
    resp = api.get_quota_region(NON_EXISTENT_UUID, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_premise_missing_distance_returns_invalid_request(api):
    """PRD §3.1: "A **premise** is registered for an applicant in a region: it
    carries `applicant_id` ... `region_code` ... a non-empty `street_address`, a
    `distance_to_school_m` distance in metres (zero or more) to the nearest school
    or place of worship that the zoning buffer rule consults, and a
    `zoning_district`"
    PRD §2.8: "request well-formedness (`ERR_INVALID_REQUEST`, 400)"

    Omitting the required distance_to_school_m -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_premise_missing_required_field_returns_invalid_request
    """
    get_success_data(api.create_quota_region(
        {"region_code": "CTY_LA", "population": 50000, "persons_per_license": 25000}, DIRECTOR))
    owner = get_success_data(api.create_applicant({"legal_name": "Acme Bar LLC"}, DIRECTOR))
    resp = api.create_premise(
        {"applicant_id": owner["id"], "region_code": "CTY_LA", "street_address": "1 Main St",
         "zoning_district": "COMMERCIAL"}, make_applicant_headers(owner["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_license_class_defaults_applied_when_omitted(api):
    """PRD §3.1: "a `quota_managed` boolean that defaults to true ... a
    `requires_zoning` boolean defaulting to true (on- and off-premise classes
    require zoning, manufacturers do not)"

    Omitting quota_managed and requires_zoning applies both defaults (true).

    Design: Corner/entities/license_class_defaults_applied_when_optional_fields_omitted
    """
    data = validate_success(api.create_license_class(
        {"code": "ON_48", "premise_type": "ON_PREMISE", "base_fee_cents": 90000,
         "renewal_cycle_months": 12, "max_servers_per_license": 3}, DIRECTOR),
        expected_status=201)
    assert data["quota_managed"] is True
    assert data["requires_zoning"] is True


def test_create_premise_invalid_zoning_district_rejected(api):
    """PRD §3.1: "a `zoning_district` that is one of `COMMERCIAL`, `MIXED_USE`,
    `RESIDENTIAL`, or `INDUSTRIAL`."
    PRD §2.8: "request well-formedness (`ERR_INVALID_REQUEST`, 400)"

    A zoning_district outside the enum -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_premise_with_invalid_zoning_district_enum_rejected
    """
    get_success_data(api.create_quota_region(
        {"region_code": "CTY_LA", "population": 50000, "persons_per_license": 25000}, DIRECTOR))
    owner = get_success_data(api.create_applicant({"legal_name": "Acme Bar LLC"}, DIRECTOR))
    resp = api.create_premise(
        {"applicant_id": owner["id"], "region_code": "CTY_LA", "street_address": "1 Main St",
         "distance_to_school_m": 200, "zoning_district": "PARKLAND"}, make_applicant_headers(owner["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── Queue B: state_machines (initial state) ──────────────────────────────
def test_server_permit_created_in_pending_no_count_change(api):
    """PRD §3.7: "A permit is created in `PENDING` under a license named by
    `license_id`, with a non-empty `holder_name` and a `training_completed` flag"
    PRD §3.5: "starts with `renewal_count`, `demerit_points`, `active_server_count`,
    and `outstanding_fine_cents` all at zero."

    A newly created permit is PENDING and the parent license's active_server_count
    is unchanged (0).

    Design: Corner/state_machines/server_permit_initial_state_is_pending
    """
    bundle = setup_issued_license()
    lic_id = bundle["license"]["id"]
    owner = make_applicant_headers(bundle["ref"]["owner_id"])
    permit = validate_success(api.create_server_permit(
        {"license_id": lic_id, "holder_name": "New Hire", "training_completed": False}, owner),
        expected_status=201)
    assert permit["status"] == "PENDING"
    lic = get_success_data(api.get_license(lic_id, DIRECTOR))
    assert lic["active_server_count"] == 0


# ─── Queue B: endpoints (listing) ─────────────────────────────────────────
def test_list_applications_paginated_envelope_and_filter(api):
    """PRD §2.3: "Each list response surfaces four pagination fields in the
    envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §4: GET `/license-applications` "List/filter applications"

    GET /license-applications filtered by applicant_id returns an array envelope
    with pagination meta and includes the created application.

    Design: Corner/endpoints/list_applications_paginated_envelope
    """
    ref = setup_reference_data()
    owner = make_applicant_headers(ref["owner_id"])
    app = get_success_data(api.create_application(
        {"applicant_id": ref["owner_id"], "premise_id": ref["premise"]["id"],
         "license_class_code": "ON_47"}, owner))
    resp = api.list_applications(DIRECTOR, params={"applicant_id": ref["owner_id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert any(item["id"] == app["id"] for item in data), "created application must appear in the list"
    assert "total_count" in meta and "has_more" in meta


# ─── Queue B: rbac ────────────────────────────────────────────────────────
def test_applicant_cannot_approve_application_forbidden_role(api):
    """PRD §2.1: "When an authenticated role is recognised but is not permitted to
    perform the requested operation per the access matrix in Section 4, the
    request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST `/license-applications/{id}/approve` "Approve an application"
    authorized role is Director only.

    An Applicant calling approve (Director-exclusive) -> ERR_FORBIDDEN_ROLE;
    application stays PROTEST_PERIOD.

    Design: Corner/rbac/applicant_cannot_approve_application_forbidden_role
    """
    ref, app = create_submitted_application()
    advance_to_protest_period(ref, app)
    get_success_data(api.set_clock("2026-02-01T00:00:00Z", DIRECTOR))
    resp = api.approve_application(app["id"], make_applicant_headers(ref["owner_id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    after = get_success_data(api.get_application(app["id"], DIRECTOR))
    assert after["status"] == "PROTEST_PERIOD"
