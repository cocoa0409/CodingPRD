"""The identity ladder, role exclusivity and the departmental roll-up."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_compliance_summary,
    condemn_parcel_well,
    create_active_contractor,
    create_approved_site_evaluation,
    create_approved_system_design,
    create_parcel,
    create_well,
    refresh_system_design,
    unique_apn,
    unique_license_number,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_missing_identity_headers_outrank_the_existence_lookup(api, no_auth_headers):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` does not spell one of
    the seven roles below exactly, the request is refused with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD §2.1: "Authentication is always evaluated before authorisation, and both are
    evaluated before the server looks for any resource named in the path."

    Design: Corner/validations/corner_missing_role_header_returns_unauthenticated_before_any_other_check
    """
    response = api.get_parcel(NON_EXISTENT_UUID, no_auth_headers)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_wrong_role_outranks_the_existence_lookup(api, applicant_headers):
    """PRD §2.6: "**Checks 1 and 2 — identity.** The headers are validated as described
    in §2.1 (`ERR_UNAUTHENTICATED`, 401), then the acting role is matched against the
    operation's authorised roles (`ERR_UNAUTHORIZED`, 403). Both apply to every
    operation in the register."
    PRD §2.6: "**Check 3 — path resolution.** Every resource named by a path segment
    must exist, and path segments are resolved strictly left to right, so a request
    against a well nested under a non-existent parcel reports the parcel as missing
    rather than the well."

    Design: Corner/validations/corner_wrong_role_returns_unauthorized_before_existence_lookup
    """
    response = api.issue_repair_order(NON_EXISTENT_UUID, applicant_headers)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_applicant_may_not_issue_a_construction_permit(api, applicant_headers):
    """PRD §3.5: "Issuing the construction permit is the `HealthOfficer`'s act, and it
    is the register's busiest single operation."
    PRD §2.1: "If both headers are well formed but the named role is not among the roles
    the target operation authorises, the refusal is `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/corner_applicant_cannot_issue_a_construction_permit
    """
    parcel = create_parcel(
        api, headers=applicant_headers, apn=unique_apn("0856-R1"), site_address="72 Role Ridge"
    )
    evaluation = create_approved_site_evaluation(api, parcel["id"])
    design = create_approved_system_design(api, evaluation["id"])
    contractor = create_active_contractor(
        api, license_number=unique_license_number("LIC-0856-AL")
    )

    refused = api.create_construction_permit(
        {
            "system_design_id": design["id"],
            "contractor_id": contractor["id"],
            "valid_from": "2026-05-01T00:00:00Z",
            "valid_until": "2027-05-01T00:00:00Z",
        },
        applicant_headers,
    )
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    _, meta = validate_paginated(
        api.list_construction_permits(applicant_headers, params={"parcel_id": parcel["id"]})
    )
    assert meta["total_count"] == 0
    assert refresh_system_design(api, design["id"])["status"] == "APPROVED"


def test_specialist_may_not_read_the_departmental_roll_up(api, applicant_headers, ehs_field_headers, records_clerk_headers):
    """PRD §3.9: "**Departmental reporting.** A `HealthOfficer` or a `RecordsClerk` may
    pull a computed, department-wide compliance roll-up, optionally scoped to a single
    county by supplying `county_code`; with no scope the report covers every parcel in
    the register."
    PRD §3.9: "`parcel_count` is the number of parcels in scope."

    Design: Corner/rbac/corner_environmental_health_specialist_cannot_read_the_compliance_summary_report
    """
    create_parcel(
        api, headers=applicant_headers, apn=unique_apn("0856-R2"), site_address="73 Report Row"
    )

    refused = api.get_compliance_summary(ehs_field_headers)
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    allowed = validate_success(api.get_compliance_summary(records_clerk_headers), 200)
    assert_compliance_summary(allowed)
    assert allowed["parcel_count"] == 1


def test_compliance_summary_counts_advisory_wells_without_reaching_high_risk(
    api, applicant_headers, health_officer_headers, records_clerk_headers
):
    """PRD §3.9: "And `advisory_well_count` is the number of wells on in-scope parcels
    whose `advisory_status` is `ADVISORY` or `CONDEMNED`."
    PRD §3.9: "`high_risk_parcel_count` is the number of in-scope parcels whose
    `risk_tier` is `HIGH`."
    PRD §3.9: "`total_fee_balance_cents` is the sum of `fee_balance_cents` over the
    in-scope parcels."

    Design: Corner/endpoints/corner_compliance_summary_report_rolls_up_department_wide_counts
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-EP2"),
        county_code="OR",
        site_address="69 Summary Street",
        water_source="PRIVATE_WELL",
    )
    well = create_well(api, parcel["id"], headers=applicant_headers, depth_ft=110)
    condemn_parcel_well(api, well["id"])

    in_scope = validate_success(
        api.get_compliance_summary(health_officer_headers, params={"county_code": "OR"}), 200
    )
    assert_compliance_summary(in_scope)
    assert in_scope["parcel_count"] == 1
    assert in_scope["advisory_well_count"] == 1
    assert in_scope["high_risk_parcel_count"] == 0, (
        "40 water-quality points reach ELEVATED, not the 60-point HIGH threshold"
    )
    assert in_scope["active_operating_permit_count"] == 0
    assert in_scope["delinquent_permit_count"] == 0
    assert in_scope["due_soon_permit_count"] == 0
    assert in_scope["open_repair_order_count"] == 0
    assert in_scope["total_fee_balance_cents"] == 0

    out_of_scope = validate_success(
        api.get_compliance_summary(records_clerk_headers, params={"county_code": "WA"}), 200
    )
    assert out_of_scope["parcel_count"] == 0
    assert out_of_scope["advisory_well_count"] == 0
    assert out_of_scope["high_risk_parcel_count"] == 0
    assert out_of_scope["active_operating_permit_count"] == 0
    assert out_of_scope["delinquent_permit_count"] == 0
    assert out_of_scope["due_soon_permit_count"] == 0
    assert out_of_scope["open_repair_order_count"] == 0
    assert out_of_scope["total_fee_balance_cents"] == 0
