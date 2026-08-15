"""Program configuration, lifecycle, response envelope, and global auth rules."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_jurisdiction_program,
    create_application,
    create_production,
    create_program,
    create_program_payload,
    get_program,
    is_valid_uuid,
    make_producer_headers,
    open_program,
    register_company,
    transition_program,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PRODUCER_FALLBACK = TEST_USERS["producer_headers"]


class TestProgramCreationDefaults:
    def test_program_create_applies_system_defaults(self, api):
        """PRD §3.1: "A new program starts in `DRAFT` status with
        `allocated_credit_cents` at zero and `remaining_cap_cents` equal to the
        annual cap."

        Design: Corner/entities/program_create_applies_system_defaults
        """
        resp = api.create_jurisdiction_program(create_program_payload(), ADMIN)
        program = validate_success(resp, 201)
        assert_jurisdiction_program(program)
        assert program["status"] == "DRAFT", "new program must start DRAFT"
        assert program["allocated_credit_cents"] == 0
        assert program["remaining_cap_cents"] == 100_000_000, (
            "remaining cap must equal the annual cap at creation")
        assert program["annual_cap_cents"] == 100_000_000
        assert isinstance(program["version"], int) and program["version"] >= 1


class TestResponseEnvelope:
    def test_response_envelope_shape_on_success_and_error(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        create_resp = api.create_jurisdiction_program(create_program_payload(), ADMIN)
        assert create_resp.status_code == 201
        body = create_resp.json()
        assert "meta" in body and "response_type" in body and "data" in body
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id must start with req_")
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "object"
        assert is_valid_uuid(body["data"]["id"])

        err_resp = api.get_jurisdiction_program(NON_EXISTENT_UUID, ADMIN)
        assert err_resp.status_code == 404
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert err_body["data"]["message"]
        assert "api_request_id" in err_body["meta"]
        assert "api_request_timestamp" in err_body["meta"]


class TestProgramWindowOverlap:
    def test_overlapping_same_jurisdiction_window_rejected(self, api):
        """PRD §3.1: "The check runs against every other program with the same
        `jurisdiction_code` whose status is anything other than `CLOSED`, and it
        runs when a program is created, whenever an amend changes the window, and
        on every transition into `OPEN`, including re-entry from `SUSPENDED`. A
        conflict is rejected with `ERR_PROGRAM_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/program_window_interval_overlap_half_open
        """
        create_program()  # incumbent GA window [2026-08-01, 2027-07-01), DRAFT counts
        overlap = create_program_payload(
            program_name="GA Film Credit FY28 Overlap", fiscal_year="FY2028",
            window_opens_at="2027-06-15T00:00:00Z",
            window_closes_at="2028-01-01T00:00:00Z")
        resp = api.create_jurisdiction_program(overlap, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_WINDOW_OVERLAP)

    def test_touching_boundary_and_other_jurisdiction_allowed(self, api):
        """PRD §3.1: "Windows that merely touch, one closing at the exact instant
        the other opens, do not conflict."
        PRD §3.1: "For this check a window is a half-open interval that includes
        its opening instant and excludes its closing instant, and two windows
        conflict when they intersect — each opening strictly before the other
        closes."

        Design: Difficulty/resource_temporal_overlap/program_window_interval_overlap_half_open
        """
        create_program()  # incumbent GA [2026-08-01, 2027-07-01)
        adjacent = create_program_payload(
            program_name="GA Film Credit FY28 Adjacent", fiscal_year="FY2028",
            window_opens_at="2027-07-01T00:00:00Z",
            window_closes_at="2028-07-01T00:00:00Z")
        resp = api.create_jurisdiction_program(adjacent, ADMIN)
        program_b = validate_success(resp, 201)
        assert program_b["status"] == "DRAFT", (
            "half-open adjacency (opens == incumbent closes) is not an overlap")

        other_jurisdiction = create_program_payload(
            jurisdiction_code="NM", program_name="NM Film Credit FY27",
            annual_cap_cents=50_000_000, minimum_qualified_spend_cents=5_000_000,
            elevated_tier_threshold_cents=100_000_000,
            window_opens_at="2026-10-01T00:00:00Z",
            window_closes_at="2027-04-01T00:00:00Z")
        resp = api.create_jurisdiction_program(other_jurisdiction, ADMIN)
        validate_success(resp, 201)


class TestProgramLifecycle:
    def test_program_suspend_resume_cycle_gates_submit(self, api):
        """PRD §3.3: "Submission is an owner-only action (`ERR_NOT_OWNER`) gated
        by the program's window: the program must currently be `OPEN`, or the
        attempt is rejected with `ERR_PROGRAM_NOT_OPEN`"

        Design: Corner/state_machines/program_suspend_resume_cycle_gates_submit
        """
        program = open_program()
        suspended = transition_program(program, "SUSPENDED")
        assert suspended["status"] == "SUSPENDED"

        company = register_company()
        production = create_production(company)
        application = create_application(production, program)
        producer = make_producer_headers(company["id"])

        blocked = api.submit_application(application["id"], producer)
        validate_error(blocked, ApiErrorId.ERR_PROGRAM_NOT_OPEN)
        assert get_program(program)["status"] == "SUSPENDED"

        resumed = transition_program(program, "OPEN")
        assert resumed["status"] == "OPEN"
        ok = api.submit_application(application["id"], producer)
        submitted = validate_success(ok, 200)
        assert submitted["status"] == "SUBMITTED"

    def test_amend_closed_program_returns_invalid_state(self, api):
        """PRD §3.1: "Amending a `SUSPENDED` or `CLOSED` program is rejected with
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/amend_closed_program_returns_invalid_state
        """
        program = open_program()
        transition_program(program, "CLOSED")
        current = get_program(program)
        resp = api.amend_jurisdiction_program(
            program["id"],
            {"expected_program_version": current["version"],
             "base_rate_standard": 0.22},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_occ_program_amend_stale_version(self, api):
        """PRD §2.8: "Amending a program's configuration requires the request to
        carry `expected_program_version` equal to the program's current
        `version`; each amend legitimately supersedes the prior configuration
        values, so if the program's version has advanced past the one the client
        last observed, the amend is rejected with `ERR_STALE_PROGRAM_VERSION`
        (HTTP 412) rather than allowed to write on a stale basis."
        PRD §3.1: "Amendments are guarded by optimistic concurrency as described
        in §2.8, increment the program's `version` by one, and legitimately
        supersede the prior configuration values."

        Design: Corner/cross_cutting_layers/occ_program_amend_stale_version
        """
        program = create_program()
        observed_version = program["version"]

        first = api.amend_jurisdiction_program(
            program["id"],
            {"expected_program_version": observed_version,
             "base_rate_standard": 0.22},
            ADMIN)
        amended = validate_success(first, 200)
        assert amended["base_rate_standard"] == 0.22
        assert amended["version"] == observed_version + 1, (
            "each amend increments the program's version by one")

        stale = api.amend_jurisdiction_program(
            program["id"],
            {"expected_program_version": observed_version,
             "base_rate_standard": 0.21},
            ADMIN)
        validate_error(stale, ApiErrorId.ERR_STALE_PROGRAM_VERSION)
        assert get_program(program)["base_rate_standard"] == 0.22, (
            "the rejected amend must not write on a stale basis")


class TestGlobalAuthRules:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a malformed
        value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        program = create_program()
        resp = api.get_jurisdiction_program(program["id"], headers=None)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_get_application_not_found_returns_404(self, api):
        """PRD §2.10: "The first identifier that does not resolve to an existing
        resource rejects the request with `ERR_NOT_FOUND`, and no further
        validation runs."

        Design: Corner/entities/get_application_not_found_returns_404
        """
        resp = api.get_application(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_producer_cannot_transition_program_forbidden(self, api):
        """PRD §2.1: "A request whose role is not on the target endpoint's
        authorized list is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: "| POST | `/api/jurisdiction-programs/{programId}/transition` |
        Program lifecycle transition per the JurisdictionProgram state machine |
        FilmOfficeAdmin |"

        Design: Corner/rbac/producer_cannot_transition_program_forbidden
        """
        program = create_program()
        company = register_company()
        resp = api.transition_jurisdiction_program(
            program["id"], "OPEN", make_producer_headers(company["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert get_program(program)["status"] == "DRAFT"
