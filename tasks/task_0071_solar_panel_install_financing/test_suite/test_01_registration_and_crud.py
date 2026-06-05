"""Registration, CRUD, RBAC, and common-field corner claims."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    create_homeowner_payload, create_utility_payload, create_project_payload,
    assert_homeowner, assert_warranty_policy,
    make_homeowner_headers,
    register_homeowner, register_installer, create_assessed_project,
    setup_operational_project,
)

ANON = TEST_USERS["anonymous_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_create_homeowner_returns_201_with_echoed_fields(api):
    """PRD 3.1: "A homeowner account captures an email that serves as a unique,
    non-empty login identifier across all homeowners, a full_name, a two-letter
    uppercase state_code drawn from the set CA, NJ, MA, TX, and AZ, and the
    homeowner's prior twelve-month electricity consumption annual_kwh_usage in
    kilowatt-hours, which must be zero or greater and later drives design sizing."

    Design: Corner/entities/create_homeowner_returns_201_with_fields
    """
    resp = api.create_homeowner(
        create_homeowner_payload(email="c1@x.com", full_name="C One",
                                 state_code="CA", annual_kwh_usage=9000),
        ANON,
    )
    data = validate_success(resp, 201)
    assert data["state_code"] == "CA"
    assert data["annual_kwh_usage"] == 9000
    assert data["version"] == 1
    assert_homeowner(data)


def test_get_project_not_found_returns_404(api):
    """PRD 2.5: "Single-resource reads validate their path identifier and return
    ERR_NOT_FOUND (HTTP 404) when the resource does not exist."

    Design: Corner/entities/get_project_not_found_returns_404
    """
    resp = api.get_project(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_create_project_missing_roof_area_rejected(api):
    """PRD 2.9: "and finally body well-formedness for create endpoints
    (ERR_INVALID_REQUEST, HTTP 400) — malformed or missing required fields,
    out-of-range enums, and negative numerics."

    Design: Corner/entities/create_project_missing_required_field_rejected
    """
    homeowner = register_homeowner()
    ho_headers = make_homeowner_headers(homeowner["id"])
    resp = api.create_project({"homeowner_id": homeowner["id"]}, ho_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_utility_export_credit_ratio_default_applied(api):
    """PRD 3.1: "and an export_credit_ratio between 0.0 and 1.0 that defaults to
    1.0 when omitted."

    Design: Corner/entities/utility_export_credit_ratio_default_applied
    """
    payload = create_utility_payload(name="Def U", state_code="CA",
                                     feeder_headroom_kw=500,
                                     net_metering_rate_cents_per_kwh=15.0)
    resp = api.create_utility(payload, ADMIN)
    data = validate_success(resp, 201)
    assert data["export_credit_ratio"] == 1.0


def test_project_computed_system_size_ignores_client_input(api):
    """PRD 3.3: "The pinned system_size_kw is the smaller of the area cap and the
    usage target."
    PRD 3.3: "the estimated_annual_production_kwh is the system_size_kw multiplied
    by peak_sun_hours, by three hundred sixty-five days, by the quantity one minus
    the shading_factor, and by a system-derate factor of 0.80, with the final
    product rounded half up to a whole kilowatt-hour."

    Design: Corner/entities/project_computed_system_size_ignores_client_input
    """
    homeowner, installer, project = create_assessed_project(
        roof_area_sqft=700, shading_factor=0.10, peak_sun_hours=5.0,
    )
    from test_helpers import design_payload, make_installer_headers
    resp = api.design_project(
        project["id"],
        design_payload(installer_id=installer["id"], gross_system_cost_cents=3000000),
        make_installer_headers(installer["id"]),
    )
    data = validate_success(resp, 200)
    assert data["system_size_kw"] == 7.3
    assert data["estimated_annual_production_kwh"] == 9592


def test_invalid_state_code_enum_rejected(api):
    """PRD 3.1: "a two-letter uppercase state_code drawn from the set CA, NJ, MA,
    TX, and AZ"
    PRD 2.9: "body well-formedness for create endpoints (ERR_INVALID_REQUEST,
    HTTP 400) — malformed or missing required fields, out-of-range enums, and
    negative numerics."

    Design: Corner/entities/enum_invalid_state_code_rejected
    """
    resp = api.create_homeowner(
        create_homeowner_payload(email="tc@x.com", full_name="Tc One",
                                 state_code="ZZ", annual_kwh_usage=9000),
        ANON,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_warranty_policy_immutable_no_version_field(api):
    """PRD 2.4: "a WarrantyPolicy is an immutable artifact minted when a project
    becomes operational, and so it carries only id and created_at. It has no
    updated_at and no version, because once written it is never mutated."

    Design: Corner/entities/warranty_policy_immutable_no_version_field
    """
    ctx = setup_operational_project()
    resp = api.list_warranty_policies(ctx["ho_headers"],
                                      params={"project_id": ctx["project"]["id"]})
    data, meta = validate_paginated(resp)
    matching = [p for p in data if p["project_id"] == ctx["project"]["id"]]
    assert len(matching) == 1, f"Expected exactly one WarrantyPolicy, got {len(matching)}"
    policy = matching[0]
    assert policy["coverage_years"] == 25
    assert_warranty_policy(policy)


# --- RBAC corners ---

def test_homeowner_cannot_design_project(api):
    """PRD 2.1: "A request whose role is not permitted to perform the requested
    operation is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/homeowner_cannot_design_project
    """
    homeowner, installer, project = create_assessed_project()
    ho_headers = make_homeowner_headers(homeowner["id"])
    from test_helpers import design_payload
    resp = api.design_project(
        project["id"],
        design_payload(installer_id=installer["id"], gross_system_cost_cents=3000000),
        ho_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD 2.1: "A request missing either header is rejected with
    ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    homeowner = register_homeowner()
    resp = api.create_project(
        create_project_payload(homeowner_id=homeowner["id"], roof_area_sqft=700),
        headers={},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


# --- consistency model corner ---

def test_design_changes_visible_in_same_response(api):
    """PRD 3.2: "When design succeeds, three figures are computed and pinned onto
    the project, described in Sections 3.3 and 3.4: the DC system size, the
    year-one production estimate, and the Federal tax credit."
    PRD 3.4: "The credit in cents is the gross_system_cost_cents multiplied by
    that effective rate, rounded half up to whole cents."

    Design: Corner/consistency_model/design_changes_visible_in_same_response
    """
    homeowner, installer, project = create_assessed_project(
        roof_area_sqft=700, shading_factor=0.10, peak_sun_hours=5.0,
    )
    from test_helpers import design_payload, make_installer_headers
    resp = api.design_project(
        project["id"],
        design_payload(installer_id=installer["id"], gross_system_cost_cents=3000000),
        make_installer_headers(installer["id"]),
    )
    data = validate_success(resp, 200)
    assert data["system_size_kw"] == 7.3
    assert data["itc_credit_cents"] == 900000
