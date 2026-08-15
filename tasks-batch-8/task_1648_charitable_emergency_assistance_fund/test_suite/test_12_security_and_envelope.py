"""Authentication, authorization, validation ordering across categories, and
the fixed response envelope on both success and failure paths."""
from test_helpers import (
    ApiErrorId,
    create_funding_source,
    create_funding_source_payload,
    create_household_payload,
    TEST_USERS,
    validate_error,
    validate_success,
)

CW1 = TEST_USERS["caseworker_headers"]
PM1 = TEST_USERS["program_manager_headers"]
FIN1 = TEST_USERS["finance_officer_headers"]
AUD1 = TEST_USERS["auditor_headers"]


class TestAuthentication:
    def test_households_create_missing_auth_header_unauthenticated(self, api):
        """PRD §2.1: "Every request carries two headers: `X-User-ID`, identifying
        the acting operator, and `X-User-Role`, naming the operator's role. A
        request missing either header, or carrying a role outside the declared
        set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/households_create_missing_auth_header_unauthenticated
        """
        resp = api.create_household(create_household_payload(), {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorization:
    def test_caseworker_cannot_approve_or_create_sources(self, api):
        """PRD §2.1: "An authenticated operator whose role is not authorized for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "`ProgramManager` — program manager: policy and funding-source
        administration, award decisions, adjustments, overrides, replenishment
        runs, and clock control."

        Design: Corner/rbac/caseworker_cannot_approve_or_create_sources
        """
        resp1 = api.approve_application(
            "2b2c3d4e-5555-4666-8777-888899990000", CW1
        )
        validate_error(resp1, ApiErrorId.ERR_FORBIDDEN)
        resp2 = api.create_funding_source(create_funding_source_payload(), CW1)
        validate_error(resp2, ApiErrorId.ERR_FORBIDDEN)

    def test_program_manager_cannot_clear_payments(self, api):
        """PRD §2.1: "An authenticated operator whose role is not authorized for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "`FinanceOfficer` — finance officer: the direct-to-vendor
        payment lifecycle (issue, clear, fail, reissue, void)."

        Design: Corner/rbac/program_manager_cannot_clear_payments
        """
        resp = api.clear_payment("3c3c3d4e-5555-4666-8777-888899990000", PM1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_finance_officer_cannot_run_replenishment(self, api):
        """PRD §2.1: "An authenticated operator whose role is not authorized for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "`ProgramManager` — program manager: policy and funding-source
        administration, award decisions, adjustments, overrides, replenishment
        runs, and clock control."

        Design: Corner/rbac/finance_officer_cannot_run_replenishment
        """
        resp = api.create_replenishment_run(FIN1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_auditor_cannot_create_household_but_can_report(self, api):
        """PRD §2.1: "`Auditor` — read-only auditor: reviews records and pulls
        donor/grant reports; cannot mutate anything."
        PRD §2.1: "An authenticated operator whose role is not authorized for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.9: "The funding-source report, available to `ProgramManager` and
        `Auditor`, answers with `funding_source_id`, `committed_cents`,
        `reserved_cents`, `available_cents`, `cash_utilization_pct`,
        `encumbrance_utilization_pct`, `rent_committed_cents`,
        `utility_committed_cents`, `households_served`, `period_start`, and
        `period_end`."

        Design: Corner/rbac/auditor_cannot_create_household_but_can_report
        """
        source = create_funding_source(total_budget_cents=50000)
        resp = api.create_household(create_household_payload(), AUD1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        report = validate_success(api.get_funding_source_report(source["id"], AUD1), 200)
        assert report["cash_utilization_pct"] == 0.0
        fetched = validate_success(api.get_funding_source(source["id"], AUD1), 200)
        assert fetched["id"] == source["id"]


class TestValidationOrderingAcrossCategories:
    def test_existence_checked_before_state_on_action(self, api):
        """PRD §2.9: "4. Existence — path identifiers and body foreign keys
        reference existing resources, validated left to right, else
        `ERR_NOT_FOUND`."
        PRD §2.9: "6. State legality — the target resource is in a state from
        which the requested transition exists. This family surfaces as
        `ERR_INVALID_APPLICATION_STATE` on the application action endpoints
        (submit, approve, deny, waitlist, appeal, withdraw, close); as
        `ERR_INVALID_VERIFICATION_STATE` on verification completion; as
        `ERR_INVALID_DUPLICATION_CHECK_STATE` on resolve or override; as
        `ERR_INVALID_AWARD_STATE` on award adjust or void; as
        `ERR_INVALID_PAYMENT_STATE` on payment clear, fail, reissue, or void; as
        `ERR_INVALID_SOURCE_STATE` on deposits into or closure of a `CLOSED`
        source; as `ERR_INVALID_POLICY_STATE` on activating a non-`DRAFT` policy;
        as `ERR_INVALID_STATE` on vendor suspend or reactivate; as
        `ERR_VENDOR_SUSPENDED` on submit against a suspended vendor; and as
        `ERR_NO_ACTIVE_POLICY` on submit or a replenishment run when no policy is
        active."

        Design: Corner/validations/existence_checked_before_state_on_action
        """
        resp = api.approve_application(
            "7a7a7a7a-2222-4333-8444-555566667777", PM1
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestResponseEnvelope:
    def test_error_envelope_shape_on_failure_and_success(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `data` field contains the resource object or an array of
        resource objects. For 2xx responses with no data, it contains an empty
        object. Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/errors/error_envelope_shape_on_failure_and_success
        """
        err_resp = api.get_household("1b2c3d4e-5555-4666-8777-888899990000", AUD1)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"]
        assert isinstance(err_body["meta"]["api_request_id"], str)
        validate_error(err_resp, ApiErrorId.ERR_NOT_FOUND)

        ok_resp = api.create_household(create_household_payload(), CW1)
        ok_body = ok_resp.json()
        assert ok_resp.status_code == 201
        assert ok_body["response_type"] == "object"
        assert isinstance(ok_body["meta"]["api_request_timestamp"], str)
        created = validate_success(ok_resp, 201)
        assert created["id"] == ok_body["data"]["id"]
