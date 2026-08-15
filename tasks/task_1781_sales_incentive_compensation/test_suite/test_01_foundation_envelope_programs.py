"""Foundation: program/plan creation defaults, response envelope shape,
and the priority-1 auth / malformed-body rejections."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_comp_plan,
    assert_comp_program,
    create_plan_payload,
    create_program,
    is_iso8601_timestamp,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["comp_admin_headers"]


class TestProgramAndPlanDefaults:
    def test_program_creation_starts_period_one_and_zero_accrual(self, api):
        """PRD §2.4: "The first, `current_period_index`, is the one-based index
        of the program's currently open compensation period; it starts at 1 when
        the program is created and advances by exactly one each time the period
        is closed — there is no other way to move it. The second,
        `accrued_balance_cents`, is the program's recognized-but-unpaid net
        payout liability: it starts at 0, grows at each period close by the sum
        of that period's `net_payable_cents` across all settled statements, and
        is relieved at payroll export by the export's `total_cents`."

        Design: Corner/entities/program_creation_defaults
        """
        resp = api.create_program({"name": "Prog Zero"}, ADMIN)
        program = validate_success(resp, 201)
        assert_comp_program(program)
        assert program["current_period_index"] == 1
        assert program["accrued_balance_cents"] == 0

    def test_plan_creation_defaults_and_creator_recording(self, api):
        """PRD §3.1: "A new plan is born in `DRAFT` status with
        `document_version` 1 and its `created_by_user_id` stamped from the
        caller."
        PRD §3.1: "`attainment_mode` selects which credits count toward
        attainment — `DIRECT_ONLY` or `INCLUDE_ROLLUP` — and defaults to
        `DIRECT_ONLY` when omitted. `rollup_rate_bps` is the fraction of a
        subordinate's posted credit, expressed in basis points, that rolls up
        to the direct manager; it defaults to 0 and may never be negative."

        Design: Corner/entities/plan_creation_defaults_and_creator_recording
        """
        program = create_program("Prog PD")
        payload = create_plan_payload(program["id"], name="Plan PD")
        resp = api.create_plan(payload, ADMIN)  # ADMIN is X-User-ID "admin-1"
        plan = validate_success(resp, 201)
        assert_comp_plan(plan)
        assert plan["status"] == "DRAFT"
        assert plan["document_version"] == 1
        assert plan["attainment_mode"] == "DIRECT_ONLY"
        assert plan["rollup_rate_bps"] == 0
        assert plan.get("payout_cap_cents") is None, "omitted cap means uncapped"
        assert plan["created_by_user_id"] == "admin-1"


class TestEnvelopeAndCatalogSmoke:
    def test_response_envelope_success_and_error_shapes(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape_success_and_error
        """
        program = create_program("Prog ENV")

        ok = api.get_program(program["id"], ADMIN)
        body = ok.json()
        assert ok.status_code == 200
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["data"]["id"] == program["id"]

        err = api.get_program(NON_EXISTENT_UUID, ADMIN)
        err_body = err.json()
        assert err.status_code == 404
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert len(err_body["data"]["message"].strip()) > 0

    def test_error_catalog_smoke_program_readable(self, api):
        """PRD §2.4: "The first, `current_period_index`, is the one-based index
        of the program's currently open compensation period; it starts at 1
        when the program is created and advances by exactly one each time the
        period is closed — there is no other way to move it."

        Smoke check anchoring the error-catalog cross-check: a created program
        is readable back through the envelope with its period counter at 1.
        Individual error triggers live in their own targeted tests.

        Design: Corner/errors/error_catalog_crosscheck
        """
        program = create_program("Prog EC")
        data = validate_success(api.get_program(program["id"], ADMIN))
        assert_comp_program(data)
        assert data["current_period_index"] == 1


class TestPlanCreationRejections:
    def test_get_missing_plan_returns_not_found(self, api):
        """PRD §2.9: "**Existence and visibility** — path and body identifiers
        resolve to existing resources (`ERR_NOT_FOUND`)."

        Design: Corner/entities/plan_get_not_found_returns_404
        """
        create_program("Prog NF")
        resp = api.get_plan(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_create_plan_without_auth_headers_rejected(self, api):
        """PRD §2.1: "Failure to provide valid headers — a missing or malformed
        header, or a role value that is not one of the four declared roles —
        will result in an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error."

        Design: Corner/validations/create_plan_missing_auth_header_returns_400
        """
        program = create_program("Prog AU")
        payload = create_plan_payload(program["id"], name="Plan AU")
        resp = api.create_plan(payload, {"Content-Type": "application/json"})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)

    def test_create_plan_missing_curve_tiers_rejected(self, api):
        """PRD §2.9: "A malformed body, a missing required field, or an invalid
        enum value is rejected with `ERR_INVALID_REQUEST` before any business
        rule is consulted."

        Design: Corner/validations/create_plan_missing_required_field_returns_400
        """
        program = create_program("Prog MR")
        payload = {
            "program_id": program["id"],
            "name": "Plan MR",
            "effective_start_date": "2026-01-01",
            "effective_end_date": "2026-12-31",
        }
        resp = api.create_plan(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_create_plan_invalid_attainment_mode_rejected(self, api):
        """PRD §2.9: "A malformed body, a missing required field, or an invalid
        enum value is rejected with `ERR_INVALID_REQUEST` before any business
        rule is consulted."
        PRD §3.1: "`attainment_mode` selects which credits count toward
        attainment — `DIRECT_ONLY` or `INCLUDE_ROLLUP` — and defaults to
        `DIRECT_ONLY` when omitted."

        Design: Corner/validations/create_plan_invalid_enum_returns_400
        """
        program = create_program("Prog IE")
        payload = create_plan_payload(program["id"], name="Plan IE",
                                      attainment_mode="BOGUS")
        resp = api.create_plan(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_plan_curve_first_floor_must_be_zero(self, api):
        """PRD §3.1: "The first tier's floor must be exactly 0 basis points,
        floors must be strictly ascending across the array, and no rate may be
        negative; any violation is rejected with `ERR_CURVE_TIERS_INVALID`."

        Design: Corner/validations/plan_curve_first_floor_nonzero_returns_400
        """
        program = create_program("Prog CV")
        payload = create_plan_payload(
            program["id"], name="Plan CV",
            curve_tiers=[{"attainment_floor_bps": 1000, "rate_bps": 1000}])
        resp = api.create_plan(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CURVE_TIERS_INVALID, 400)
