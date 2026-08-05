"""Registry creation, resource lookup, not-found errors, and access control.

Covers Corner queue instances in the entities, errors, validations, and rbac
sections that establish the CRUD/auth baseline.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    make_applicant_headers,
    assert_well, assert_aquifer,
    factories as f, fixtures as fx,
)

OFFICER = TEST_USERS["health_officer_headers"]


# --------------------------------------------------------------------------
# entities section
# --------------------------------------------------------------------------
def test_create_well_returns_proposed_unknown_zero(api):
    """PRD §3.1: "A new well is born in registry status PROPOSED and potability
    status UNKNOWN, with active_advisory_count at 0 and depth_ft unset."

    Design: Corner/entities/create_well_success_returns_proposed
    """
    aquifer = fx.create_aquifer(api, sensitivity="LOW")
    applicant = fx.create_applicant(api)
    headers = make_applicant_headers(applicant["id"])
    resp = api.create_well(
        f.well_payload(applicant["id"], aquifer["id"], intended_use="DOMESTIC"), headers)
    data = validate_success(resp, 201)
    assert_well(data)
    assert data["registry_status"] == "PROPOSED"
    assert data["potability_status"] == "UNKNOWN"
    assert data["active_advisory_count"] == 0


def test_get_unknown_well_returns_not_found(api):
    """PRD §2.5: "Each resource type has its own not-found error: ...
    ERR_WELL_NOT_FOUND ... each returning HTTP 404."

    Design: Corner/entities/get_well_not_found_returns_404
    """
    resp = api.get_well(NON_EXISTENT_UUID, OFFICER)
    validate_error(resp, ApiErrorId.ERR_WELL_NOT_FOUND)


def test_create_well_missing_intended_use_rejected(api):
    """PRD §2.9: "then request-body well-formedness (ERR_VALIDATION — required
    fields present, enum values in range, and requested_analytes a non-empty
    subset of BACTERIA, NITRATE, LEAD)".

    Design: Corner/entities/create_well_missing_required_intended_use_returns_invalid_request
    """
    aquifer = fx.create_aquifer(api, sensitivity="LOW")
    applicant = fx.create_applicant(api)
    payload = f.well_payload(applicant["id"], aquifer["id"])
    payload.pop("intended_use")
    resp = api.create_well(payload, make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_create_well_bad_intended_use_enum_rejected(api):
    """PRD §2.9: "then request-body well-formedness (ERR_VALIDATION — required
    fields present, enum values in range, and requested_analytes a non-empty
    subset of BACTERIA, NITRATE, LEAD)".

    Design: Corner/entities/create_well_bad_enum_intended_use_returns_invalid_request
    """
    aquifer = fx.create_aquifer(api, sensitivity="LOW")
    applicant = fx.create_applicant(api)
    payload = f.well_payload(applicant["id"], aquifer["id"], intended_use="MINING")
    resp = api.create_well(payload, make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_create_well_unknown_aquifer_returns_not_found(api):
    """PRD §2.5: "All referenced resources are validated to exist. ... Each
    resource type has its own not-found error: ... ERR_AQUIFER_NOT_FOUND".

    Design: Corner/entities/create_well_unknown_aquifer_returns_not_found
    """
    applicant = fx.create_applicant(api)
    payload = f.well_payload(applicant["id"], NON_EXISTENT_UUID, intended_use="DOMESTIC")
    resp = api.create_well(payload, make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_AQUIFER_NOT_FOUND)


def test_list_wells_returns_paginated_array(api):
    """PRD §2.3: "The meta block of a list response reports limit, offset,
    total_count (the number of records matching the filter before pagination),
    and has_more (true when records beyond the current page remain)."

    Design: Corner/entities/list_wells_pagination_envelope
    """
    aquifer = fx.create_aquifer(api, sensitivity="LOW")
    applicant = fx.create_applicant(api)
    fx.create_well(api, applicant["id"], aquifer["id"])
    resp = api.list_wells(OFFICER, params={"applicant_id": applicant["id"]})
    data, meta = validate_paginated(resp)
    assert isinstance(data, list)
    assert "total_count" in meta and "has_more" in meta


def test_aquifer_has_no_version_field(api):
    """PRD §2.4: "An Aquifer is an immutable configuration record: it carries
    only id and created_at — it has neither updated_at nor version, and once
    created it is never modified."

    Design: Corner/entities/aquifer_is_immutable_config_no_version
    """
    resp = api.create_aquifer(f.aquifer_payload(sensitivity="MODERATE"), OFFICER)
    data = validate_success(resp, 201)
    assert_aquifer(data)
    assert "version" not in data
    assert "updated_at" not in data


# --------------------------------------------------------------------------
# errors section — per-type not-found lookups
# --------------------------------------------------------------------------
def test_permit_not_found_returns_404(api):
    """PRD §2.5: "Each resource type has its own not-found error" — ERR_PERMIT_NOT_FOUND for an
    unknown construction permit.

    Design: Corner/errors/permit_not_found_returns_404
    """
    validate_error(api.get_construction_permit(NON_EXISTENT_UUID, OFFICER),
                   ApiErrorId.ERR_PERMIT_NOT_FOUND)


def test_sample_not_found_returns_404(api):
    """PRD §2.5: "Each resource type has its own not-found error" — ERR_SAMPLE_NOT_FOUND for an
    unknown water sample.

    Design: Corner/errors/sample_not_found_returns_404
    """
    validate_error(api.get_water_sample(NON_EXISTENT_UUID, OFFICER),
                   ApiErrorId.ERR_SAMPLE_NOT_FOUND)


def test_result_not_found_returns_404(api):
    """PRD §2.5: "Each resource type has its own not-found error" — ERR_RESULT_NOT_FOUND for an
    unknown sample result.

    Design: Corner/errors/result_not_found_returns_404
    """
    validate_error(api.get_sample_result(NON_EXISTENT_UUID, OFFICER),
                   ApiErrorId.ERR_RESULT_NOT_FOUND)


def test_case_not_found_returns_404(api):
    """PRD §2.5: "Each resource type has its own not-found error" — ERR_CASE_NOT_FOUND for an
    unknown contamination case.

    Design: Corner/errors/case_not_found_returns_404
    """
    validate_error(api.get_contamination_case(NON_EXISTENT_UUID, OFFICER),
                   ApiErrorId.ERR_CASE_NOT_FOUND)


def test_advisory_not_found_returns_404(api):
    """PRD §2.5: "Each resource type has its own not-found error" — ERR_ADVISORY_NOT_FOUND for an
    unknown advisory.

    Design: Corner/errors/advisory_not_found_returns_404
    """
    validate_error(api.get_advisory(NON_EXISTENT_UUID, OFFICER),
                   ApiErrorId.ERR_ADVISORY_NOT_FOUND)


def test_abandonment_not_found_returns_404(api):
    """PRD §2.5: "Each resource type has its own not-found error" — ERR_ABANDONMENT_NOT_FOUND for an
    unknown abandonment permit.

    Design: Corner/errors/abandonment_not_found_returns_404
    """
    validate_error(api.get_abandonment_permit(NON_EXISTENT_UUID, OFFICER),
                   ApiErrorId.ERR_ABANDONMENT_NOT_FOUND)


def test_requirement_not_found_returns_404(api):
    """PRD §2.5: "Each resource type has its own not-found error" — ERR_REQUIREMENT_NOT_FOUND for an
    unknown real-estate test requirement.

    Design: Corner/errors/requirement_not_found_returns_404
    """
    validate_error(api.get_real_estate_requirement(NON_EXISTENT_UUID, OFFICER),
                   ApiErrorId.ERR_REQUIREMENT_NOT_FOUND)


def test_driller_log_not_found_returns_404(api):
    """PRD §2.5: "Each resource type has its own not-found error" — ERR_DRILLER_LOG_NOT_FOUND for an
    unknown driller log.

    Design: Corner/errors/driller_log_not_found_returns_404
    """
    validate_error(api.get_driller_log(NON_EXISTENT_UUID, OFFICER),
                   ApiErrorId.ERR_DRILLER_LOG_NOT_FOUND)


def test_driller_not_found_returns_404(api):
    """PRD §2.5: "Each resource type has its own not-found error" — ERR_DRILLER_NOT_FOUND for an
    unknown driller.

    Design: Corner/errors/driller_not_found_returns_404
    """
    validate_error(api.get_driller(NON_EXISTENT_UUID, OFFICER),
                   ApiErrorId.ERR_DRILLER_NOT_FOUND)


def test_applicant_not_found_returns_404(api):
    """PRD §2.5: "Each resource type has its own not-found error" — ERR_APPLICANT_NOT_FOUND for an
    unknown applicant.

    Design: Corner/errors/applicant_not_found_returns_404
    """
    validate_error(api.get_applicant(NON_EXISTENT_UUID, OFFICER),
                   ApiErrorId.ERR_APPLICANT_NOT_FOUND)


def test_aquifer_not_found_returns_404(api):
    """PRD §2.5: "Each resource type has its own not-found error" — ERR_AQUIFER_NOT_FOUND for an
    unknown aquifer.

    Design: Corner/errors/aquifer_not_found_returns_404
    """
    validate_error(api.get_aquifer(NON_EXISTENT_UUID, OFFICER),
                   ApiErrorId.ERR_AQUIFER_NOT_FOUND)


# --------------------------------------------------------------------------
# validations / rbac — authentication and authorization
# --------------------------------------------------------------------------
def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of
    the four recognized roles, the request is rejected with ERR_UNAUTHENTICATED
    (HTTP 401)."

    Design: Corner/validations/unauthenticated_request_returns_unauthenticated
    """
    resp = api.get_well(NON_EXISTENT_UUID, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_applicant_approve_permit_returns_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to invoke the requested endpoint, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/validations/applicant_approve_permit_returns_unauthorized
    """
    resp = api.approve_permit(NON_EXISTENT_UUID, make_applicant_headers("someone"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_driller_issue_permit_returns_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to invoke the requested endpoint, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/driller_cannot_issue_permit_returns_unauthorized
    """
    resp = api.issue_permit(NON_EXISTENT_UUID, TEST_USERS["driller_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_applicant_record_result_returns_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to invoke the requested endpoint, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/applicant_cannot_record_result_returns_unauthorized
    """
    payload = f.sample_result_payload(NON_EXISTENT_UUID)
    resp = api.create_sample_result(payload, make_applicant_headers("some-applicant"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
