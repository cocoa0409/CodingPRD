"""Plan onboarding, response envelope, and ledger seeding tests."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    is_iso8601_timestamp,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_plan,
    create_plan_payload,
    get_plan,
    get_ledger,
    assert_plan,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]


class TestPlanCreationAndLedger:
    def test_plan_creation_applies_defaults_and_seeds_ledger(self, api):
        """PRD §3.1: "Two optional opening balances, `initial_carryover_balance` and
        `initial_prefunding_balance`, each default to zero when omitted."
        PRD §3.1: "Plan creation automatically creates the plan's credit-balance
        ledger, a one-to-one sub-resource seeded with `carryover_balance` equal to
        `initial_carryover_balance`, `prefunding_balance` equal to
        `initial_prefunding_balance`, and `total_applied_to_date` of zero."
        PRD §3.1: "A new plan begins with `status` `ACTIVE` and `current_posture`
        `UNRESTRICTED`."

        Design: Corner/entities/plan_creation_applies_defaults_and_seeds_ledger
        """
        resp = api.create_plan(
            create_plan_payload(sponsor_name="Defaults Co", prior_aftap_pct=90.00),
            PLAN_ADMIN,
        )
        plan = validate_success(resp, 201)
        assert_plan(plan)
        assert plan["status"] == "ACTIVE"
        assert plan["current_posture"] == "UNRESTRICTED"
        assert plan["version"] == 1

        ledger = get_ledger(plan["id"])
        assert ledger["carryover_balance"] == 0
        assert ledger["prefunding_balance"] == 0
        assert ledger["total_applied_to_date"] == 0

    def test_plan_creation_seeds_ledger_with_initial_balances(self, api):
        """PRD §3.1: "Plan creation automatically creates the plan's credit-balance
        ledger, a one-to-one sub-resource seeded with `carryover_balance` equal to
        `initial_carryover_balance`, `prefunding_balance` equal to
        `initial_prefunding_balance`, and `total_applied_to_date` of zero."

        Design: Corner/entities/plan_creation_applies_defaults_and_seeds_ledger
        """
        plan = create_plan(
            sponsor_name="Seeded Co",
            initial_carryover_balance=2000,
            initial_prefunding_balance=3000,
        )
        ledger = get_ledger(plan["id"])
        assert ledger["carryover_balance"] == 2000
        assert ledger["prefunding_balance"] == 3000
        assert ledger["total_applied_to_date"] == 0


class TestPlanValidation:
    def test_plan_missing_required_field_returns_validation_error(self, api):
        """PRD §2.8: "Request-body well-formedness — required fields present, values
        well-typed, enum members valid, amounts positive where required — is the
        lowest-priority check of all, surfaced as `ERR_VALIDATION` (HTTP 400) only
        when no earlier rule has fired."
        PRD §3.1: plan_year is a required input ("the calendar `plan_year`").

        Design: Corner/entities/plan_missing_required_field_returns_validation_error
        """
        payload = {
            "sponsor_name": "Broken Co",
            "accrual_rate": 0.01,
            "normal_retirement_age": 62,
            "prior_aftap_pct": 90.00,
        }
        resp = api.create_plan(payload, PLAN_ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestPlanNotFound:
    def test_plan_get_not_found_returns_404(self, api):
        """PRD §2.8: "Requests that target nested resources are resolved left to
        right along the path ... and the first identifier that does not correspond
        to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/plan_get_not_found_returns_404
        """
        resp = api.get_plan(NON_EXISTENT_UUID, PLAN_ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestPlanPagination:
    def test_plan_list_pagination_envelope(self, api):
        """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."
        PRD §3.1: "The plan listing supports pagination and an optional `status`
        filter."

        Design: Corner/entities/plan_list_pagination_envelope
        """
        for i in range(3):
            create_plan(sponsor_name=f"Page Co {i}")
        resp = api.list_plans(PLAN_ADMIN, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0


class TestEnvelopeShapes:
    def test_error_envelope_shape_on_404(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard
        envelope format" with `meta` containing `api_request_id` and
        `api_request_timestamp`, `response_type` of "error", and `data` carrying
        `error_id` and `message`.

        Design: Corner/endpoints/error_envelope_shape_on_404
        """
        resp = api.get_plan(NON_EXISTENT_UUID, PLAN_ADMIN)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["error_id"], str)
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)

    def test_success_envelope_shape_on_create(self, api):
        """PRD §2.2: "`response_type` is either "object" for a single resource or
        "array" for a list of resources"; "The `data` field contains the resource
        object."
        PRD §2.4: "`id` (string): a server-minted UUID, with no type prefix" and
        "`created_at` (string): an ISO 8601 UTC timestamp with three fractional
        digits".

        Design: Corner/endpoints/success_envelope_shape_on_create
        """
        resp = api.create_plan(
            create_plan_payload(sponsor_name="Envelope Co"),
            PLAN_ADMIN,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["response_type"] == "object"
        data = body["data"]
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])


class TestClockDefault:
    def test_clock_default_is_pinned(self, api):
        """PRD §2.5: "At server startup, before any set call, the logical clock reads
        exactly 2026-08-01T00:00:00Z and must not fall back to wall-clock time."
        PRD §3.6: "Before April 1, `presumed_aftap_pct` equals `prior_aftap_pct`
        and the plan is presumed adequate, with posture `UNRESTRICTED`."

        Design: Corner/endpoints/clock_default_is_pinned
        """
        plan = create_plan(sponsor_name="Clock Co", prior_aftap_pct=77.00)
        fetched = get_plan(plan["id"])
        assert fetched["presumed_aftap_pct"] == 77.00
        assert fetched["current_posture"] == "UNRESTRICTED"
        assert fetched["certified_aftap_pct"] is None
