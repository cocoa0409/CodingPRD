"""The authentication rungs and the sixteen entity-specific not-found codes."""

from test_helpers import (
    ADMIN,
    OFFICER,
    ApiErrorId,
    api_client,
    build_user_headers,
    is_iso8601_timestamp,
    seed_poverty_guidelines,
    validate_error,
    validate_paginated,
    validate_success,
)

CORNER_2026_GUIDELINE = ((2026, 1620000, 570000),)


def test_a_request_without_an_operator_identifier_never_reaches_body_validation():
    """Rung 1 answers first, so the missing required money fields go unremarked.

    PRD 2.12: "1. Both `X-User-ID` and `X-User-Role` are present and non-empty, on every
    endpoint — otherwise `ERR_MISSING_AUTH_HEADERS` (401)."

    PRD 2.12: "4. On every write endpoint, the body contains every required input field,
    every enum-typed value is a declared member of that enum, every integer and number
    satisfies its declared constraint, and no system-managed or computed field is
    supplied by the client — otherwise `ERR_VALIDATION` (400)."

    PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/errors/request_missing_x_user_id_returns_unauthenticated
    """
    headerless = {"X-User-Role": "PlatformAdmin", "Content-Type": "application/json"}

    response = api_client.create_health_center(
        {"legal_name": "Headerless Health", "grant_number": "H80CS00999"}, headerless
    )

    validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value, 401)
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"].strip() != ""
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].strip() != ""
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

    _, meta = validate_paginated(api_client.list_health_centers(ADMIN))
    assert meta["total_count"] == 0, "the refused registration stored nothing"


def test_an_undeclared_role_is_unauthenticated_rather_than_unauthorised():
    """Rung 2 rejects a role name that is not in the vocabulary at all.

    PRD 2.12: "2. `X-User-Role` names one of the seven declared roles, on every endpoint
    — otherwise `ERR_UNKNOWN_ROLE` (401)."

    PRD 2.12: "3. The acting role is authorised for the endpoint, on every endpoint —
    otherwise `ERR_UNAUTHORIZED` (403)."

    Design: Corner/errors/unknown_role_header_returns_unauthenticated
    """
    guidelines = seed_poverty_guidelines(CORNER_2026_GUIDELINE)
    guideline_id = guidelines[2026]["id"]

    validate_error(
        api_client.get_poverty_guideline(
            guideline_id, build_user_headers("aud-1", "Auditor")
        ),
        ApiErrorId.ERR_UNKNOWN_ROLE.value,
        401,
    )

    readable = validate_success(
        api_client.get_poverty_guideline(guideline_id, OFFICER)
    )
    assert readable["guideline_year"] == 2026, (
        "the very same read succeeds for a declared role"
    )


def test_every_declared_not_found_code_names_its_own_entity():
    """Sixteen unresolved path identifiers produce sixteen distinct error identifiers.

    PRD 2.12: "6. On every endpoint carrying a path identifier, each path identifier
    resolves, left to right — otherwise the matching not-found code of the unresolved
    entity, drawn from the list in section 2.10 (404)."

    PRD 2.10: "The full set of existence codes is `ERR_HEALTH_CENTER_NOT_FOUND`,
    `ERR_POVERTY_GUIDELINE_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`,
    `ERR_SERVICE_SITE_NOT_FOUND`, `ERR_SERVICE_DEFINITION_NOT_FOUND`,
    `ERR_SCOPE_CHANGE_REQUEST_NOT_FOUND`, `ERR_FEE_SCHEDULE_NOT_FOUND`,
    `ERR_DISCOUNT_TIER_NOT_FOUND`, `ERR_INCOME_VERIFICATION_NOT_FOUND`,
    `ERR_ENCOUNTER_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_BOARD_MEMBER_NOT_FOUND`,
    `ERR_UDS_REPORT_NOT_FOUND`, `ERR_QUALITY_MEASURE_RESULT_NOT_FOUND`,
    `ERR_SITE_VISIT_FINDING_NOT_FOUND` and `ERR_CORRECTIVE_ACTION_PLAN_NOT_FOUND`, each
    returned with HTTP 404."

    Design: Corner/errors/every_declared_not_found_error_is_triggerable_by_unknown_path_id
    """
    seed_poverty_guidelines(CORNER_2026_GUIDELINE)
    lookups = [
        (api_client.get_health_center, "01", ApiErrorId.ERR_HEALTH_CENTER_NOT_FOUND),
        (api_client.get_poverty_guideline, "02", ApiErrorId.ERR_POVERTY_GUIDELINE_NOT_FOUND),
        (api_client.get_board_member, "03", ApiErrorId.ERR_BOARD_MEMBER_NOT_FOUND),
        (api_client.get_service_site, "04", ApiErrorId.ERR_SERVICE_SITE_NOT_FOUND),
        (api_client.get_service_definition, "05", ApiErrorId.ERR_SERVICE_DEFINITION_NOT_FOUND),
        (api_client.get_scope_change_request, "06", ApiErrorId.ERR_SCOPE_CHANGE_REQUEST_NOT_FOUND),
        (api_client.get_fee_schedule, "07", ApiErrorId.ERR_FEE_SCHEDULE_NOT_FOUND),
        (api_client.get_discount_tier, "08", ApiErrorId.ERR_DISCOUNT_TIER_NOT_FOUND),
        (api_client.get_patient, "09", ApiErrorId.ERR_PATIENT_NOT_FOUND),
        (api_client.get_income_verification, "0a", ApiErrorId.ERR_INCOME_VERIFICATION_NOT_FOUND),
        (api_client.get_encounter, "0b", ApiErrorId.ERR_ENCOUNTER_NOT_FOUND),
        (api_client.get_waiver, "0c", ApiErrorId.ERR_WAIVER_NOT_FOUND),
        (api_client.get_uds_report, "0d", ApiErrorId.ERR_UDS_REPORT_NOT_FOUND),
        (api_client.get_quality_measure_result, "0e", ApiErrorId.ERR_QUALITY_MEASURE_RESULT_NOT_FOUND),
        (api_client.get_site_visit_finding, "0f", ApiErrorId.ERR_SITE_VISIT_FINDING_NOT_FOUND),
        (api_client.get_corrective_action_plan, "10", ApiErrorId.ERR_CORRECTIVE_ACTION_PLAN_NOT_FOUND),
    ]

    seen = set()
    for getter, suffix, expected_error in lookups:
        unknown_id = f"00000000-0000-4000-8000-0000000000{suffix}"
        error = validate_error(
            getter(unknown_id, OFFICER), expected_error.value, 404
        )
        seen.add(error["error_id"])

    assert len(seen) == 16, (
        f"each entity answers with its own code, got {len(seen)} distinct identifiers"
    )
