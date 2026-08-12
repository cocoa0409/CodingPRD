"""Response-envelope, authentication, and authorization claims (PRD 2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_envelope_object,
    assert_error_envelope,
    create_facility_site_payload,
    make_family_headers,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    create_family,
    create_site,
    setup_pod_active,
    setup_pod_with_approved_policy_and_plan,
    set_clock,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["pod_operator_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


class TestResponseEnvelope:
    def test_response_envelope_object_shape(self, api):
        """PRD 2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body" with
        meta.api_request_id, meta.api_request_timestamp, response_type and
        data; and "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."

        Design: Corner/endpoints/response_envelope_object_shape
        """
        site = create_site(site_name="RE")
        resp = api.get_facility_site(site["id"], ADMIN)
        body = resp.json()
        assert_envelope_object(body)
        assert body["response_type"] == "object", (
            f"single-resource GET must have response_type 'object', got "
            f"{body['response_type']}"
        )
        assert body["data"]["id"] == site["id"]

    def test_error_envelope_shape(self, api):
        """PRD 2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with response_type "error" and data
        carrying error_id and message; "The `message` provides a
        human-readable explanation of what went wrong."

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api.get_pod(NON_EXISTENT_UUID, OPERATOR)
        body = resp.json()
        assert resp.status_code == 404
        assert_error_envelope(body)
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"


class TestAuthentication:
    def test_unauthenticated_missing_role_header(self, api):
        """PRD 2.1: "A request whose `X-User-Role` header is missing or
        holds a value outside this set — or whose `X-User-ID` header is
        missing for any of these roles — is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_role_header
        """
        resp = api.list_pods({"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestAuthorization:
    def test_forbidden_role_for_platform_admin_endpoint(self, api):
        """PRD 2.1: "A request whose role is recognized but not permitted to
        invoke the target endpoint is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/validations/forbidden_role_for_platform_admin_endpoint
        """
        family = create_family(family_name="F1")
        resp = api.create_facility_site(
            create_facility_site_payload(site_name="Bad", max_occupancy=10,
                                         indoor_sqft=500),
            make_family_headers(family["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_pod_operator_cannot_approve_own_curriculum_plan(self, api):
        """PRD 3.2: "Plan approval is reserved for a `PlatformAdmin` and
        enforces two checks, rejected jointly as `ERR_CURRICULUM_INADEQUATE`
        (HTTP 422): the pod must hold at least one `APPROVED` safety policy,
        and the plan must clear the 1200-minute weekly floor while covering
        every grade band present among enrolled seats."

        Design: Corner/rbac/pod_operator_cannot_approve_own_curriculum_plan
        """
        set_clock("2026-06-01T00:00:00Z")
        pod, site, policy, plan = setup_pod_with_approved_policy_and_plan()
        # Create a second, still-DRAFT plan and submit it; approve as the operator.
        from test_helpers import create_curriculum_plan_payload
        plan2 = validate_success(
            api.create_curriculum_plan(pod["id"], create_curriculum_plan_payload(),
                                       OPERATOR),
            expected_status=201,
        )
        validate_success(
            api.submit_curriculum_plan(pod["id"], plan2["id"], OPERATOR)
        )
        resp = api.approve_curriculum_plan(pod["id"], plan2["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_family_cannot_suspend_pod(self, api):
        """PRD 2.1: "A request whose role is recognized but not permitted to
        invoke the target endpoint is rejected with `ERR_FORBIDDEN`
        (HTTP 403)." (suspend is listed under ComplianceOfficer in section 4)

        Design: Corner/rbac/family_cannot_suspend_pod
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, *_ = setup_pod_active()
        family = create_family(family_name="NoSuspend")
        resp = api.suspend_pod(pod["id"], make_family_headers(family["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_registrar_cannot_approve_safety_policy(self, api):
        """PRD 3.2: "Approval is a `PlatformAdmin` act that requires the
        emergency plan text to run at least 200 characters and the drill
        cadence to sit inside the 7-to-90-day window; a policy failing
        either requirement is rejected with `ERR_SAFETY_POLICY_MISSING`."

        Design: Corner/rbac/registrar_cannot_approve_safety_policy
        """
        set_clock("2026-06-01T00:00:00Z")
        site = create_site()
        from test_helpers import create_pod_payload, create_safety_policy_payload
        pod = validate_success(
            api.create_pod(create_pod_payload(site["id"]), OPERATOR),
            expected_status=201,
        )
        policy = validate_success(
            api.create_safety_policy(pod["id"], create_safety_policy_payload(),
                                     OPERATOR),
            expected_status=201,
        )
        resp = api.approve_safety_policy(pod["id"], policy["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    # test_guide_identity_entity_backed was DELETED: PRD 2.1 enumerates the
    # ERR_UNAUTHENTICATED triggers verbatim (missing/out-of-set role header,
    # or missing X-User-ID) and PRD 2.6 enumerates the ERR_NOT_FOUND triggers
    # (path-templated identifiers and body-carried foreign keys). A
    # present-but-nonexistent entity-backed X-User-ID appears in neither
    # list, so rejecting it is a scaffold-only rule (Corner/rbac/
    # guide_identity_entity_backed's "HTTP 401 or 404" assertion) with no
    # verbatim PRD basis — STEP 1a silence.
