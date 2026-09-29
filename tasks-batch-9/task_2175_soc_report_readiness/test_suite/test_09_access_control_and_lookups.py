"""Authentication, role authorisation, and the entity-specific not-found codes."""

from test_helpers import (
    MISSING_UUID,
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiErrorId,
    create_control,
    create_criterion,
    create_engagement,
    create_engagement_payload,
    make_headers,
    read_control,
    validate_error,
    validate_paginated,
    validate_success,
)

CL_HEADERS = TEST_USERS["compliance_lead_headers"]
AUD_HEADERS = TEST_USERS["auditor_headers"]
AE_HEADERS = TEST_USERS["account_executive_headers"]
OWN_HEADERS = TEST_USERS["control_owner_headers"]
PA_HEADERS = TEST_USERS["platform_admin_headers"]


def test_a_request_without_identity_headers_is_unauthenticated(api):
    """PRD 2.1: "Every request to this API — without exception, including reads and
    including the logical-clock utility — must carry two headers: `X-User-ID`, identifying
    the operator making the call, and `X-User-Role`, naming the capacity in which they act.
    If either header is absent or empty, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/corner_missing_auth_headers_returns_unauthenticated
    """
    create_engagement(client_name="Guarded")

    response = api.list_engagements(NO_AUTH_HEADERS)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert response.json()["response_type"] == "error"


def test_a_role_outside_the_seven_declared_names_is_unknown(api):
    """PRD 2.1: "If `X-User-Role` carries a string that is not one of the seven role names
    defined below, the rejection is `ERR_UNKNOWN_ROLE`, also HTTP 401."
    PRD 2.1: "The seven roles are `ComplianceLead`, `ControlOwner`, `EvidenceReviewer`,
    `Auditor`, `AccountExecutive`, `SubserviceContact` and `PlatformAdmin`, spelled exactly
    as written."

    Design: Corner/validations/corner_unknown_role_header_returns_unknown_role
    """
    engagement = create_engagement(client_name="Guarded")

    response = api.get_engagement(engagement["id"], make_headers("who-1", "SuperUser"))
    validate_error(response, ApiErrorId.ERR_UNKNOWN_ROLE.value, 401)


def test_gap_bridge_cuec_and_questionnaire_report_their_own_not_found_codes(api):
    """PRD 2.9: "Each entity has a dedicated not-found code, and the same code is used
    whether the identifier arrived in the URL or in a request body: engagements report
    `ERR_ENGAGEMENT_NOT_FOUND`, system descriptions `ERR_SYSTEM_DESCRIPTION_NOT_FOUND`,
    boundary components `ERR_BOUNDARY_COMPONENT_NOT_FOUND`, criteria
    `ERR_TRUST_CRITERION_NOT_FOUND`, controls `ERR_CONTROL_NOT_FOUND`, mappings
    `ERR_CRITERIA_MAPPING_NOT_FOUND`, evidence requests `ERR_EVIDENCE_REQUEST_NOT_FOUND`,
    gaps `ERR_GAP_NOT_FOUND`, samples `ERR_AUDIT_SAMPLE_NOT_FOUND`, exceptions
    `ERR_AUDIT_EXCEPTION_NOT_FOUND`, subservice organizations
    `ERR_SUBSERVICE_ORG_NOT_FOUND`, complementary user entity controls
    `ERR_CUEC_NOT_FOUND`, distributions `ERR_REPORT_DISTRIBUTION_NOT_FOUND`, bridge letters
    `ERR_BRIDGE_LETTER_NOT_FOUND` and questionnaires `ERR_QUESTIONNAIRE_NOT_FOUND`."

    Design: Corner/errors/corner_not_found_errors_are_entity_specific
    """
    create_engagement(client_name="Lookup")

    validate_error(
        api.get_gap(MISSING_UUID, CL_HEADERS), ApiErrorId.ERR_GAP_NOT_FOUND.value, 404
    )
    validate_error(
        api.get_bridge_letter(MISSING_UUID, AE_HEADERS),
        ApiErrorId.ERR_BRIDGE_LETTER_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_cuec(MISSING_UUID, CL_HEADERS), ApiErrorId.ERR_CUEC_NOT_FOUND.value, 404
    )
    validate_error(
        api.get_customer_questionnaire(MISSING_UUID, AE_HEADERS),
        ApiErrorId.ERR_QUESTIONNAIRE_NOT_FOUND.value,
        404,
    )


def test_the_remaining_collections_report_their_own_not_found_codes(api):
    """PRD 2.9: "Path identifiers are resolved left to right. Where a URL nests an action
    beneath a resource, the resource identifier is resolved first and its not-found code is
    the one reported; only once it resolves does the action's own logic run."
    PRD 2.9: "Each entity has a dedicated not-found code, and the same code is used whether
    the identifier arrived in the URL or in a request body: engagements report
    `ERR_ENGAGEMENT_NOT_FOUND`, system descriptions `ERR_SYSTEM_DESCRIPTION_NOT_FOUND`,
    boundary components `ERR_BOUNDARY_COMPONENT_NOT_FOUND`, criteria
    `ERR_TRUST_CRITERION_NOT_FOUND`, controls `ERR_CONTROL_NOT_FOUND`, mappings
    `ERR_CRITERIA_MAPPING_NOT_FOUND`, evidence requests `ERR_EVIDENCE_REQUEST_NOT_FOUND`,
    gaps `ERR_GAP_NOT_FOUND`, samples `ERR_AUDIT_SAMPLE_NOT_FOUND`, exceptions
    `ERR_AUDIT_EXCEPTION_NOT_FOUND`, subservice organizations
    `ERR_SUBSERVICE_ORG_NOT_FOUND`, complementary user entity controls
    `ERR_CUEC_NOT_FOUND`, distributions `ERR_REPORT_DISTRIBUTION_NOT_FOUND`, bridge letters
    `ERR_BRIDGE_LETTER_NOT_FOUND` and questionnaires `ERR_QUESTIONNAIRE_NOT_FOUND`."

    Design: Corner/errors/corner_remaining_collections_report_their_own_not_found_codes
    """
    create_engagement(client_name="Lookup Sweep")

    validate_error(
        api.get_boundary_component(MISSING_UUID, CL_HEADERS),
        ApiErrorId.ERR_BOUNDARY_COMPONENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_trust_criterion(MISSING_UUID, PA_HEADERS),
        ApiErrorId.ERR_TRUST_CRITERION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_criteria_mapping(MISSING_UUID, CL_HEADERS),
        ApiErrorId.ERR_CRITERIA_MAPPING_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_evidence_request(MISSING_UUID, OWN_HEADERS),
        ApiErrorId.ERR_EVIDENCE_REQUEST_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_audit_sample(MISSING_UUID, AUD_HEADERS),
        ApiErrorId.ERR_AUDIT_SAMPLE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_audit_exception(MISSING_UUID, AUD_HEADERS),
        ApiErrorId.ERR_AUDIT_EXCEPTION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_subservice_organization(MISSING_UUID, CL_HEADERS),
        ApiErrorId.ERR_SUBSERVICE_ORG_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_report_distribution(MISSING_UUID, AE_HEADERS),
        ApiErrorId.ERR_REPORT_DISTRIBUTION_NOT_FOUND.value,
        404,
    )


def test_a_control_owner_may_not_add_controls(api):
    """PRD 2.1: "A `ControlOwner` is the operator accountable for one or more controls and
    submits the periodic evidence artifacts for them."
    PRD 2.1: "Each endpoint in §4 declares the roles permitted to call it. **The role check
    runs before any path identifier is resolved**, so a role that is not permitted on an
    endpoint receives `ERR_ROLE_NOT_PERMITTED` (HTTP 403) even when the identifier in the
    URL names no stored row at all."

    Design: Corner/rbac/corner_control_owner_cannot_create_controls
    """
    engagement = create_engagement(client_name="Peer Roles")

    response = api.create_control(
        {
            "engagement_id": engagement["id"],
            "control_ref": "X-99",
            "title": "Sneaky control",
            "frequency": "MONTHLY",
        },
        OWN_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    _, meta = validate_paginated(
        api.list_controls(CL_HEADERS, params={"engagement_id": engagement["id"]})
    )
    assert meta["total_count"] == 0


def test_the_auditor_may_neither_map_criteria_nor_open_engagements(api):
    """PRD 2.1: "A `ComplianceLead` owns the readiness track. They open engagements, author
    system descriptions and their boundaries, register subservice organizations and set
    their presentation method, add controls, map controls to criteria and retire those
    mappings, assign control owners, generate the evidence calendar, run the readiness
    assessment and the calendar ops-run, plan and remediate gaps, draft and articulate
    complementary user entity controls, and approve, deny or revoke distribution requests."
    PRD 2.1: "An `Auditor` is the examining practitioner: they return descriptions to draft
    or approve them, approve control design, draw and test samples, conclude and void them,
    evaluate exceptions, verify and reopen gaps, and advance the engagement onto the report
    track."

    Design: Corner/rbac/corner_auditor_cannot_create_criteria_mappings_or_engagements
    """
    criterion = create_criterion("CC1.1")
    engagement = create_engagement(client_name="Split Duties")
    control = create_control(engagement["id"], control_ref="K-01", title="Access provisioning")

    mapping_attempt = api.create_criteria_mapping(
        {
            "control_id": control["id"],
            "trust_criterion_id": criterion["id"],
            "mapping_type": "PRIMARY",
        },
        AUD_HEADERS,
    )
    validate_error(mapping_attempt, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    engagement_attempt = api.create_engagement(
        create_engagement_payload(client_name="Auditor Engagement"), AUD_HEADERS
    )
    validate_error(engagement_attempt, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    _, mapping_meta = validate_paginated(
        api.list_criteria_mappings(CL_HEADERS, params={"control_id": control["id"]})
    )
    assert mapping_meta["total_count"] == 0
    _, engagement_meta = validate_paginated(api.list_engagements(CL_HEADERS))
    assert engagement_meta["total_count"] == 1


def test_the_platform_admin_owns_the_catalog_but_no_engagement_content(api):
    """PRD 2.1: "A `PlatformAdmin` curates the global trust services criteria catalog, may
    drive the calendar ops-run, and sets the server's logical clock. This role holds no
    business authority over any engagement's content."
    PRD 3.3: "The trust services criteria catalog is global, shared across every
    engagement, and curated by a `PlatformAdmin`."

    Design: Corner/rbac/corner_platform_admin_holds_no_business_authority
    """
    engagement = create_engagement(client_name="Operator Limits")

    engagement_attempt = api.create_engagement(
        create_engagement_payload(client_name="Admin Engagement"), PA_HEADERS
    )
    validate_error(engagement_attempt, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    gap_attempt = api.create_gap(
        {"engagement_id": engagement["id"], "severity": "LOW", "description": "Admin logged gap"},
        PA_HEADERS,
    )
    validate_error(gap_attempt, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    criterion = validate_success(
        api.create_trust_criterion(
            {
                "criterion_code": "CC1.1",
                "category": "SECURITY",
                "title": "Control environment",
                "min_primary_controls": 1,
                "applies_to_report_types": ["SOC_2_TYPE_2"],
            },
            PA_HEADERS,
        ),
        201,
    )
    assert criterion["criterion_code"] == "CC1.1"

    _, meta = validate_paginated(
        api.list_gaps(CL_HEADERS, params={"engagement_id": engagement["id"]})
    )
    assert meta["total_count"] == 0


def test_a_forbidden_role_calling_a_missing_control_sees_the_role_error(api):
    """PRD 2.1: "Each endpoint in §4 declares the roles permitted to call it. **The role
    check runs before any path identifier is resolved**, so a role that is not permitted on
    an endpoint receives `ERR_ROLE_NOT_PERMITTED` (HTTP 403) even when the identifier in the
    URL names no stored row at all."
    PRD 2.7: "**Role permitted on the endpoint**, else `ERR_ROLE_NOT_PERMITTED` (403). This
    runs *before* any identifier lookup, so a forbidden role calling a nonexistent
    identifier sees the authorization failure, never a not-found."

    Design: Difficulty/priority_pair_validation_conflict/role_auth_beats_control_existence_lookup
    """
    engagement = create_engagement(client_name="Fourth Coffee")
    control = create_control(
        engagement["id"],
        control_ref="R-01",
        title="Onboarding checklist",
        frequency="MONTHLY",
        automation="MANUAL",
        risk_rating="LOW",
        population_size=5,
    )

    response = api.assign_control_owner(
        MISSING_UUID, {"owner_user_id": "own-1"}, AUD_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    assert read_control(control["id"])["owner_user_id"] is None


def test_a_permitted_role_calling_a_missing_control_sees_the_not_found_error(api):
    """PRD 2.7: "**Path identifiers resolve**, validated left to right along the URL. The
    first segment identifier that names no stored row decides the error; each entity has its
    own code, listed in §5."
    PRD 3.4: "A `ComplianceLead` assigns one by supplying `owner_user_id`, the opaque
    operator identifier of the `ControlOwner` who will submit that control's evidence."

    Design: Difficulty/priority_pair_validation_conflict/role_auth_beats_control_existence_lookup
    """
    engagement = create_engagement(client_name="Fourth Coffee")
    control = create_control(
        engagement["id"],
        control_ref="R-01",
        title="Onboarding checklist",
        frequency="MONTHLY",
        automation="MANUAL",
        risk_rating="LOW",
        population_size=5,
    )

    forbidden = api.assign_control_owner(MISSING_UUID, {"owner_user_id": "own-1"}, AUD_HEADERS)
    assert forbidden.status_code == 403

    missing = api.assign_control_owner(MISSING_UUID, {"owner_user_id": "own-1"}, CL_HEADERS)
    validate_error(missing, ApiErrorId.ERR_CONTROL_NOT_FOUND.value, 404)
    assert read_control(control["id"])["owner_user_id"] is None
