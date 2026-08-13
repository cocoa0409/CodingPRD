"""Developer onboarding, cluster creation, response envelope, and the 404 family."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_cluster_group,
    assert_developer,
    create_cluster_group_payload,
    create_developer_payload,
    create_project_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_developer_headers,
    setup_developer_and_cluster,
    validate_error,
    validate_success,
)

# Shared opaque-role headers (these roles are not ownership-gated — PRD §2.1).
TEST_QUEUE_ADMIN = TEST_USERS["queue_admin_headers"]
TEST_REGULATOR = TEST_USERS["regulator_headers"]


class TestDeveloperOnboarding:
    def test_developer_create_missing_legal_name(self, api):
        """PRD §3.1: "a `QueueAdministrator` onboards an interconnection customer by
        providing the organization's `legal_name`, its `contact_email`, and a
        `developer_type` of `IPP`, `UTILITY_SCALE`, or `COMMUNITY`."
        PRD §2.8: "Ninth, structural business constraints are enforced (capacity,
        window-overlap, uniqueness, and conflict errors, plus `ERR_INVALID_REQUEST`
        for malformed inputs)."

        Design: Corner/entities/developer_create_missing_required_field_returns_invalid_request
        """
        payload = create_developer_payload()
        del payload["legal_name"]
        resp = api.create_developer(payload, TEST_QUEUE_ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_developer_create_applies_system_fields(self, api):
        """PRD §2.4: "Every resource carries a system-minted `id`, formatted as a
        bare UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC
        with three fractional digits."
        PRD §4: "Operations that create a new resource — onboarding a developer,
        standing up a cluster, submitting a project, posting a deposit ledger entry,
        submitting milestone evidence, scoping a study, issuing an agreement,
        requesting an extension, recording a curtailment limit, publishing a
        transparency snapshot — return `201 Created`."

        Design: Corner/entities/developer_create_applies_system_fields
        """
        resp = api.create_developer(
            create_developer_payload(legal_name="Acme Renewables LLC",
                                     contact_email="queue@acme.example",
                                     developer_type="IPP"),
            TEST_QUEUE_ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_developer(data)
        assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
        assert data["version"] == 1, "version starts at its initial value"
        assert data["legal_name"] == "Acme Renewables LLC"
        assert data["contact_email"] == "queue@acme.example"
        assert data["developer_type"] == "IPP"

    def test_cluster_group_defaults_at_creation(self, api):
        """PRD §3.1: "A new cluster begins in `FORMING` with `committed_mw`
        initialized to zero."

        Design: Corner/entities/cluster_group_defaults_at_creation
        """
        resp = api.create_cluster_group(create_cluster_group_payload(), TEST_QUEUE_ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_cluster_group(data)
        assert data["committed_mw"] == 0, "committed_mw initialized to zero"
        assert data["status"] == "FORMING"
        assert data["version"] == 1

    def test_cluster_invalid_window_rejected(self, api):
        """PRD §2.9: "The window is half-open: `application_window_open` marks the
        inclusive start and `application_window_close` the exclusive end, and the
        close must be strictly later than the open, otherwise creation fails with
        `ERR_INVALID_WINDOW` (HTTP 400)."

        Design: Corner/validations/cluster_invalid_window_rejected
        """
        payload = create_cluster_group_payload(
            name="BadWindow",
            application_window_open="2026-08-01T00:00:00Z",
            application_window_close="2026-08-01T00:00:00Z")
        resp = api.create_cluster_group(payload, TEST_QUEUE_ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


class TestResponseEnvelope:
    def test_response_envelope_success_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body"
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/endpoints/response_envelope_success_shape
        """
        resp = api.create_developer(create_developer_payload(), TEST_QUEUE_ADMIN)
        data = validate_success(resp, expected_status=201)
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["data"]["id"] == data["id"]

    def test_response_envelope_error_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format:"
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/response_envelope_error_shape
        """
        payload = create_developer_payload()
        del payload["legal_name"]
        resp = api.create_developer(payload, TEST_QUEUE_ADMIN)
        error_data = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.json()["response_type"] == "error"
        assert error_data["error_id"] == "ERR_INVALID_REQUEST"
        assert error_data["message"].strip(), "message must be a non-empty string"


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a value the
        server cannot interpret, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/developer_create_missing_auth_header_unauthenticated
        """
        resp = api.create_developer(create_developer_payload(), None)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestNotFoundFamily:
    def test_project_get_not_found(self, api):
        """PRD §2.8: "The first identifier that does not resolve to an existing
        resource determines the 404 error: a missing developer yields
        `ERR_DEVELOPER_NOT_FOUND`, a missing cluster group
        `ERR_CLUSTER_GROUP_NOT_FOUND`, a missing project `ERR_PROJECT_NOT_FOUND`,
        a missing study `ERR_STUDY_NOT_FOUND`, a missing agreement
        `ERR_AGREEMENT_NOT_FOUND`, a missing milestone submission
        `ERR_MILESTONE_SUBMISSION_NOT_FOUND`, and a missing transparency report
        `ERR_TRANSPARENCY_REPORT_NOT_FOUND` — each at HTTP 404, and always in path
        order before any business rule is consulted."

        Design: Corner/entities/project_get_not_found_returns_404
        """
        resp = api.get_project(NON_EXISTENT_UUID, TEST_QUEUE_ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND)

    def test_not_found_errors_across_resources(self, api):
        """PRD §2.8: "Third, resource existence along path and body identifiers is
        verified left to right (the 404 family above)."
        PRD §2.8: "a missing developer yields `ERR_DEVELOPER_NOT_FOUND`, a missing
        cluster group `ERR_CLUSTER_GROUP_NOT_FOUND`, a missing project
        `ERR_PROJECT_NOT_FOUND`, a missing study `ERR_STUDY_NOT_FOUND`, a missing
        agreement `ERR_AGREEMENT_NOT_FOUND`, a missing milestone submission
        `ERR_MILESTONE_SUBMISSION_NOT_FOUND`, and a missing transparency report
        `ERR_TRANSPARENCY_REPORT_NOT_FOUND` — each at HTTP 404"

        Design: Corner/errors/not_found_errors_across_resources
        """
        _developer, cluster = setup_developer_and_cluster()

        resp = api.get_cluster_group(NON_EXISTENT_UUID, TEST_QUEUE_ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLUSTER_GROUP_NOT_FOUND)

        resp = api.get_study(NON_EXISTENT_UUID, TEST_QUEUE_ADMIN)
        validate_error(resp, ApiErrorId.ERR_STUDY_NOT_FOUND)

        ghost_dev = "11111111-1111-1111-1111-111111111111"
        resp = api.execute_agreement(NON_EXISTENT_UUID, make_developer_headers(ghost_dev))
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_FOUND)

        resp = api.review_milestone_submission(
            NON_EXISTENT_UUID, {"decision": "ACCEPTED"}, TEST_QUEUE_ADMIN)
        validate_error(resp, ApiErrorId.ERR_MILESTONE_SUBMISSION_NOT_FOUND)

        resp = api.get_transparency_report(NON_EXISTENT_UUID, TEST_REGULATOR)
        validate_error(resp, ApiErrorId.ERR_TRANSPARENCY_REPORT_NOT_FOUND)

        payload = create_project_payload(ghost_dev, cluster["id"])
        resp = api.create_project(payload, make_developer_headers(ghost_dev))
        validate_error(resp, ApiErrorId.ERR_DEVELOPER_NOT_FOUND)


class TestProjectPayloadValidation:
    def test_project_create_invalid_enum_technology(self, api):
        """PRD §3.2: "A `Developer` submits an interconnection request into a
        specific cluster by supplying a payload containing the `developer_id`, the
        target `cluster_group_id`, a `project_name`, a `technology` of `SOLAR`,
        `WIND`, `STORAGE`, or `HYBRID`, the `capacity_mw` nameplate (greater than
        zero and at most 500), a `service_type` of `ENERGY_ONLY` or `CAPACITY`, and
        the `point_of_interconnection` identifying the substation or feeder."
        PRD §2.8: "plus `ERR_INVALID_REQUEST` for malformed inputs"

        Design: Corner/validations/project_create_invalid_enum_technology
        """
        developer, cluster = setup_developer_and_cluster()
        payload = create_project_payload(
            developer["id"], cluster["id"], project_name="Geo1",
            technology="GEOTHERMAL")
        resp = api.create_project(payload, make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
