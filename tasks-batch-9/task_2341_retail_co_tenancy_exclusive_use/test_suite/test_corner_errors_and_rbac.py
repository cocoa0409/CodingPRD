"""Header authentication, schema rejection, and the role/scope access rules.

Covers the two refusals that sit at the top of the validation ladder — a missing
or undeclared ``X-User-Role`` and a body that breaks a declared shape — and the
access rules of PRD §2.1: an unauthorized role, a ``TenantRep`` reaching outside
its own tenant, and an operation both of its declared holders may perform.
"""
from test_helpers import (
    ASSET_MANAGER_USER_ID,
    COMPLIANCE_ENFORCER_USER_ID,
    COMPLIANCE_OFFICER_USER_ID,
    ERR_INVALID_REQUEST,
    ERR_TENANT_SCOPE_FORBIDDEN,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    LEASE_ADMIN_USER_ID,
    Scenario,
    add_clause,
    assert_center_quantities,
    assert_lease_dimensions,
    assert_null,
    assert_pct,
    build_center_with_leases,
    create_center,
    create_tenant,
    draft_lease,
    factories,
    fetch_center,
    fetch_lease,
    fetch_measurement,
    fetch_notice,
    issue_notice,
    make_asset_manager_headers,
    make_compliance_officer_headers,
    make_headers_missing_role,
    make_headers_unknown_role,
    make_lease_administrator_headers,
    make_lender_rep_headers,
    make_tenant_rep_headers,
    prepare_measurement,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"


def _northgate(api) -> Scenario:
    """Northgate Crossing: 300000 sqft with five open suites (255000 counted)."""
    return build_center_with_leases(
        api,
        [
            {
                "suite_code": "A1",
                "gla_sqft": 120000,
                "parcel_kind": "ANCHOR_BOX",
                "primary_use_code": "DISCOUNT_DEPT",
                "base_rent_monthly_cents": 6000000,
                "expiration_date": "2036-12-31",
                "tenant_legal_name": "Boxmart Retail Inc",
                "is_national_chain": True,
            },
            {
                "suite_code": "A2",
                "gla_sqft": 100000,
                "parcel_kind": "ANCHOR_BOX",
                "primary_use_code": "GROCERY",
                "base_rent_monthly_cents": 4000000,
                "expiration_date": "2036-12-31",
                "tenant_legal_name": "Grocerway Foods LLC",
                "is_national_chain": True,
            },
            {
                "suite_code": "I1",
                "gla_sqft": 2000,
                "parcel_kind": "INLINE",
                "primary_use_code": "COFFEE",
                "base_rent_monthly_cents": 1000000,
                "expiration_date": "2036-12-31",
                "tenant_legal_name": "Bean Theory Coffee LLC",
            },
            {
                "suite_code": "I2",
                "gla_sqft": 3000,
                "parcel_kind": "INLINE",
                "primary_use_code": "BOOKS",
                "base_rent_monthly_cents": 1200000,
                "expiration_date": "2036-12-31",
                "tenant_legal_name": "Margin Books LLC",
            },
            {
                "suite_code": "I3",
                "gla_sqft": 30000,
                "parcel_kind": "INLINE",
                "primary_use_code": "FITNESS",
                "base_rent_monthly_cents": 1500000,
                "expiration_date": "2036-12-31",
                "tenant_legal_name": "Pulse Fitness Group",
                "is_national_chain": True,
            },
        ],
        total_gla_sqft=300000,
        occupancy_grace_days=30,
        clock=CLOCK,
    )


def _northgate_with_two_notices(api):
    """Northgate plus two ``ISSUED`` notices, one against I3 and one against I2."""
    scenario = _northgate(api)
    clause_coffee = add_clause(
        api,
        scenario.lease_id("I1"),
        protected_use_codes=["COFFEE"],
        exclusivity_scope="CENTER_WIDE",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
    )
    add_clause(
        api,
        scenario.lease_id("I3"),
        protected_use_codes=["FITNESS"],
        exclusivity_scope="CENTER_WIDE",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
    )
    notice_for_la = issue_notice(
        api,
        scenario.lease_id("I3"),
        notice_kind="EXCLUSIVE_USE",
        clause_id=clause_coffee["id"],
        narrative="Espresso bar in the fitness premises.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    notice_for_co = issue_notice(
        api,
        scenario.lease_id("I2"),
        notice_kind="PROHIBITED_USE",
        narrative="Yoga studio inside the bookstore.",
        cure_period_days=30,
        user_id=COMPLIANCE_ENFORCER_USER_ID,
    )
    return scenario, notice_for_la, notice_for_co


# ---------------------------------------------------------------------------
# Authentication and schema (PRD §2.1, §2.9)
# ---------------------------------------------------------------------------
def test_center_registration_without_a_role_header_is_unauthenticated(api):
    """A request that omits X-User-Role is refused 401 and creates nothing.

    PRD: "A request whose `X-User-Role` header is absent, blank, or carries a string that is not one of those five names is rejected with `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/errors/request_without_the_x_user_role_header_returns_unauthenticated
    """
    set_clock(api, CLOCK, user_id=COMPLIANCE_OFFICER_USER_ID)

    response = api.create_center(
        factories.center_payload(
            name="Northgate Crossing", total_gla_sqft=300000, occupancy_grace_days=30
        ),
        make_headers_missing_role(ASSET_MANAGER_USER_ID),
    )

    validate_error(response, ERR_UNAUTHENTICATED, 401)

    # The refusal happens ahead of any persistence (PRD §2.9 rung 1).
    _, meta = validate_paginated(api.list_centers(make_asset_manager_headers()))
    assert meta["total_count"] == 0


def test_unknown_role_value_is_unauthenticated_not_unauthorized(api):
    """A role string outside the five declared names is refused 401, not 403.

    PRD: "A request whose `X-User-Role` header is absent, blank, or carries a string that is not one of those five names is rejected with `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/errors/unknown_role_value_in_the_header_returns_unauthenticated
    """
    set_clock(api, CLOCK, user_id=COMPLIANCE_OFFICER_USER_ID)

    response = api.create_center(
        factories.center_payload(
            name="Northgate Crossing", total_gla_sqft=300000, occupancy_grace_days=30
        ),
        make_headers_unknown_role("pm-1", "PropertyManager"),
    )

    # Authentication (rung 1) answers before authorization (rung 2).
    validate_error(response, ERR_UNAUTHENTICATED, 401)
    assert response.json()["data"]["error_id"] != ERR_UNAUTHORIZED

    _, meta = validate_paginated(api.list_centers(make_asset_manager_headers()))
    assert meta["total_count"] == 0


def test_negative_cents_field_returns_invalid_request(api):
    """A negative `_cents` value is a schema failure and records nothing.

    PRD: "Schema — every required body field present with its declared type, every enum field carrying a declared member, every percentage between 0 and 100 inclusive, every `_cents` field a non-negative integer, and every date a well-formed ISO 8601 calendar date."

    Design: Corner/errors/negative_cents_and_bad_date_return_invalid_request
    """
    scenario = _northgate(api)

    response = api.create_radius_restriction(
        scenario.lease_id("I3"),
        factories.radius_restriction_payload(
            radius_miles=3.0,
            measured_from="CENTER_BOUNDARY",
            recapture_basis="GROSS_SALES",
            recapture_pct=8.0,
            protected_baseline_cents=-500,
            window_from_date="2026-01-01",
            window_through_date="2026-12-31",
        ),
        make_lease_administrator_headers(LEASE_ADMIN_USER_ID),
    )

    validate_error(response, ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(
        api.list_radius_restrictions(
            make_lease_administrator_headers(),
            params={"lease_id": scenario.lease_id("I3")},
        )
    )
    assert meta["total_count"] == 0


def test_malformed_calendar_date_returns_invalid_request(api):
    """A date string that names no calendar day is a schema failure.

    PRD: "Schema — every required body field present with its declared type, every enum field carrying a declared member, every percentage between 0 and 100 inclusive, every `_cents` field a non-negative integer, and every date a well-formed ISO 8601 calendar date."

    Design: Corner/errors/negative_cents_and_bad_date_return_invalid_request
    """
    scenario = _northgate(api)

    response = api.create_radius_restriction(
        scenario.lease_id("I3"),
        factories.radius_restriction_payload(
            radius_miles=3.0,
            measured_from="CENTER_BOUNDARY",
            recapture_basis="GROSS_SALES",
            recapture_pct=8.0,
            protected_baseline_cents=0,
            window_from_date="2026-02-30",
            window_through_date="2026-12-31",
        ),
        make_lease_administrator_headers(LEASE_ADMIN_USER_ID),
    )

    validate_error(response, ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(
        api.list_radius_restrictions(
            make_lease_administrator_headers(),
            params={"lease_id": scenario.lease_id("I3")},
        )
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Role authorization and tenant scope (PRD §2.1)
# ---------------------------------------------------------------------------
def test_tenant_rep_cannot_execute_its_own_lease(api):
    """Execution is closed to TenantRep, so the refusal is the role error.

    PRD: "A request whose role is well-formed but is not listed among the authorized roles of the addressed endpoint in §4 is rejected with `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/tenant_rep_cannot_execute_a_lease
    """
    set_clock(api, CLOCK, user_id=COMPLIANCE_OFFICER_USER_ID)
    center = create_center(
        api, name="Northgate Crossing", total_gla_sqft=300000, occupancy_grace_days=30
    )
    tenant = create_tenant(
        api,
        legal_name="Boxmart Retail Inc",
        notice_email="legal@boxmart.example",
        primary_use_code="DISCOUNT_DEPT",
        is_national_chain=True,
    )
    lease = draft_lease(
        api,
        center["id"],
        tenant["id"],
        suite_code="A1",
        gla_sqft=210000,
        parcel_kind="ANCHOR_BOX",
        primary_use_code="DISCOUNT_DEPT",
        base_rent_monthly_cents=8000000,
        commencement_date="2026-01-01",
        expiration_date="2036-12-31",
    )

    response = api.execute_lease(
        lease["id"], None, make_tenant_rep_headers(tenant["id"])
    )

    # The role is refused at PRD §2.1 before any ownership comparison runs.
    validate_error(response, ERR_UNAUTHORIZED, 403)
    assert response.json()["data"]["error_id"] != ERR_TENANT_SCOPE_FORBIDDEN

    assert_lease_dimensions(fetch_lease(api, lease["id"]), premises_status="DRAFT")
    assert_center_quantities(fetch_center(api, center["id"]), occupied_gla_sqft=0)


def test_lender_rep_cannot_issue_a_use_violation_notice(api):
    """Issuing a notice is closed to LenderRep but open to ComplianceOfficer.

    PRD: "A request whose role is well-formed but is not listed among the authorized roles of the addressed endpoint in §4 is rejected with `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/lender_rep_cannot_issue_a_use_violation_notice
    """
    scenario = _northgate(api)
    clause = add_clause(
        api,
        scenario.lease_id("I1"),
        protected_use_codes=["COFFEE"],
        exclusivity_scope="CENTER_WIDE",
        gla_carve_out_sqft=0,
        incidental_sales_pct_cap=0.0,
        effective_from_date="2026-01-01",
        effective_through_date="2036-12-31",
    )
    payload = factories.notice_payload(
        violating_lease_id=scenario.lease_id("I3"),
        notice_kind="EXCLUSIVE_USE",
        clause_id=clause["id"],
        narrative="Espresso bar in the fitness premises.",
        cure_period_days=30,
    )

    refused = api.create_notice(payload, make_lender_rep_headers())
    validate_error(refused, ERR_UNAUTHORIZED, 403)

    # The very same body from an authorized ComplianceOfficer is accepted.
    accepted = validate_success(
        api.create_notice(
            payload, make_compliance_officer_headers(COMPLIANCE_ENFORCER_USER_ID)
        ),
        201,
    )
    notice = fetch_notice(api, accepted["id"])
    assert notice["status"] == "ISSUED"
    assert notice["issued_by_user_id"] == COMPLIANCE_ENFORCER_USER_ID
    assert_center_quantities(
        fetch_center(api, scenario.center_id), open_violation_count=1
    )


def test_asset_manager_cannot_certify_an_occupancy_measurement(api):
    """Certification is closed to AssetManager and the row stays DRAFT.

    PRD: "A request whose role is well-formed but is not listed among the authorized roles of the addressed endpoint in §4 is rejected with `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/asset_manager_cannot_certify_an_occupancy_measurement
    """
    scenario = _northgate(api)
    measurement = prepare_measurement(
        api,
        scenario.center_id,
        variant="SNAPSHOT_STRICT",
        window_from_date="2026-07-01",
        window_through_date="2026-08-02",
        user_id=COMPLIANCE_OFFICER_USER_ID,
    )

    response = api.certify_measurement(
        measurement["id"], None, make_asset_manager_headers(ASSET_MANAGER_USER_ID)
    )

    validate_error(response, ERR_UNAUTHORIZED, 403)

    after = fetch_measurement(api, measurement["id"])
    assert after["status"] == "DRAFT"
    assert_null(after["certified_by_user_id"], "certified_by_user_id")
    # 255000 of 300000 sqft counted open under SNAPSHOT_STRICT (PRD §2.5).
    assert_pct(after["gla_occupancy_pct"], 85.00, "gla_occupancy_pct")


def test_tenant_rep_of_another_tenant_cannot_drive_a_lease_dark(api):
    """A TenantRep addressing another tenant's lease is a scope refusal.

    PRD: "A `TenantRep` acting outside its own tenant's leases is refused with `ERR_TENANT_SCOPE_FORBIDDEN` (403)."

    Design: Corner/rbac/tenant_rep_of_another_tenant_is_scope_forbidden_on_go_dark
    """
    scenario = _northgate(api)

    response = api.go_dark(
        scenario.lease_id("I1"),
        None,
        make_tenant_rep_headers(scenario.tenant_id("I2")),
    )

    # TenantRep is an authorized role on go-dark, so the failure is ownership.
    validate_error(response, ERR_TENANT_SCOPE_FORBIDDEN, 403)
    assert response.json()["data"]["error_id"] != ERR_UNAUTHORIZED

    lease = fetch_lease(api, scenario.lease_id("I1"))
    assert_lease_dimensions(lease, premises_status="OPEN")
    assert_null(lease["dark_since"], "dark_since")
    assert_center_quantities(
        fetch_center(api, scenario.center_id),
        occupied_gla_sqft=255000,
        open_occupancy_pct=85.00,
    )


def test_lease_administrator_may_accept_a_cure(api):
    """The first holder of the shared cure operation reaches CURED.

    PRD: "A `LeaseAdministrator` or `ComplianceOfficer` accepts the tenant's cure by supplying a `cure_evidence_code`."

    Design: Corner/rbac/both_holders_of_the_shared_cure_operation_succeed
    """
    scenario, notice_for_la, _ = _northgate_with_two_notices(api)

    cured = validate_success(
        api.cure_notice(
            notice_for_la["id"],
            factories.cure_payload("USE_DISCONTINUED"),
            make_lease_administrator_headers(LEASE_ADMIN_USER_ID),
        ),
        200,
    )

    assert cured["status"] == "CURED"
    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I3")), use_compliance_status="CLEAR"
    )
    # One of the two notices remains open, so the count decrements to 1.
    assert_center_quantities(
        fetch_center(api, scenario.center_id), open_violation_count=1
    )


def test_compliance_officer_may_accept_a_cure(api):
    """The second holder of the shared cure operation also reaches CURED.

    PRD: "A `LeaseAdministrator` or `ComplianceOfficer` accepts the tenant's cure by supplying a `cure_evidence_code`."

    Design: Corner/rbac/both_holders_of_the_shared_cure_operation_succeed
    """
    scenario, notice_for_la, notice_for_co = _northgate_with_two_notices(api)

    validate_success(
        api.cure_notice(
            notice_for_la["id"],
            factories.cure_payload("USE_DISCONTINUED"),
            make_lease_administrator_headers(LEASE_ADMIN_USER_ID),
        ),
        200,
    )
    cured = validate_success(
        api.cure_notice(
            notice_for_co["id"],
            factories.cure_payload("SUBLEASE_TERMINATED"),
            make_compliance_officer_headers(COMPLIANCE_ENFORCER_USER_ID),
        ),
        200,
    )

    assert cured["status"] == "CURED"
    assert fetch_notice(api, notice_for_la["id"])["status"] == "CURED"
    assert_lease_dimensions(
        fetch_lease(api, scenario.lease_id("I2")), use_compliance_status="CLEAR"
    )
    assert_center_quantities(
        fetch_center(api, scenario.center_id),
        open_violation_count=0,
        compliance_posture="COMPLIANT",
    )
