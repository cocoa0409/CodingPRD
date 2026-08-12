"""Engagement terms: sign gate, retainer funding, and OCC on superseding writes."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_engagement, assert_version_incremented, ApiErrorId,
    create_expert, create_case, open_request, screen_candidate,
    create_draft_engagement, propose_engagement, sign_engagement, fund_retainer,
    setup_scenario, setup_active_engagement,
    TEST_USERS, make_expert_headers, make_case_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["case_manager_headers"]


class TestSignGate:

    def test_sign_from_draft_rejected(self, api):
        """PRD §3.3: "Signature belongs to the engaged expert alone. Signing moves
        `PROPOSED` → `SIGNED`, sets `nda_executed` to true".
        PRD §2.11: "then the target entity's state preconditions for the requested
        transition are checked, with violations yielding `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/engagement_sign_from_draft_rejected
        """
        sc = setup_scenario(target_state="DRAFT", fund=False)
        engagement = sc["engagement"]
        assert engagement["status"] == "DRAFT"

        res = api.sign_engagement(engagement["id"], make_expert_headers(sc["expert"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_engagement(engagement["id"], CM), 200)
        assert after["status"] == "DRAFT"
        assert after["nda_executed"] is False


class TestRetainerFunding:

    def test_overfund_rejected_then_exact_funding_activates(self, api):
        """PRD §3.3: "A payment that would push the funded total above `retainer_cents` is
        rejected with `ERR_RETAINER_OVERFUND`; a payment that brings the funded total to
        exactly `retainer_cents` completes funding and moves the engagement `SIGNED` →
        `ACTIVE`."

        Design: Corner/endpoints/retainer_overfund_rejected_exact_funding_passes
        """
        sc = setup_scenario(target_state="SIGNED", fund=False,
                            engagement_overrides={"retainer_cents": 10_000})
        engagement = sc["engagement"]
        assert engagement["status"] == "SIGNED"

        res = api.fund_retainer(engagement["id"], {"amount_cents": 10_001}, CM)
        validate_error(res, ApiErrorId.ERR_RETAINER_OVERFUND)

        funded = validate_success(
            api.fund_retainer(engagement["id"], {"amount_cents": 10_000}, CM), 200)
        assert_engagement(funded)
        assert funded["status"] == "ACTIVE", "exact funding completes the retainer and activates"
        assert funded["retainer_funded_cents"] == 10_000


class TestOptimisticConcurrency:

    def test_engagement_amend_happy_path_then_stale_rejected(self, api):
        """PRD §2.6: "A request to `POST /litigation/engagements/{id}/amend` must carry
        `expected_engagement_version`, holding the caller's last observed `version` of the
        target Engagement. Because a newer amendment legitimately supersedes prior terms, a
        second sequential amendment carrying a stale version observes no state-field
        rejection and must be stopped by OCC: if the value does not match the engagement's
        current `version`, the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_layers/engagement_amend_occ_happy_and_stale
        """
        sc = setup_active_engagement()
        engagement = validate_success(api.get_engagement(sc["engagement"]["id"], CM), 200)
        v0 = engagement["version"]

        amended = validate_success(api.amend_engagement(
            engagement["id"],
            {"expected_engagement_version": v0, "hourly_rate_cents": 45_000, "reason": "rate uplift"},
            CM), 200)
        assert amended["hourly_rate_cents"] == 45_000
        assert_version_incremented(amended["version"], v0)

        stale = api.amend_engagement(
            engagement["id"],
            {"expected_engagement_version": v0, "hourly_rate_cents": 47_000, "reason": "stale writer"},
            CM)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        after = validate_success(api.get_engagement(engagement["id"], CM), 200)
        assert after["hourly_rate_cents"] == 45_000, "rejected amend must not change terms"

    def test_case_budget_revision_stale_rejected(self, api):
        """PRD §2.6: "A request to `POST /litigation/cases/{id}/budget-revisions` must carry
        `expected_case_version`, holding the caller's last observed `version` of the target
        Case. Each revision legitimately supersedes the prior budget, so only the OCC check
        distinguishes a stale writer: a mismatch with the case's current `version` is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/case_budget_revision_occ_stale_rejected
        """
        case = create_case(budget_cents=500_000)
        v0 = case["version"]

        revised = validate_success(api.revise_budget(
            case["id"],
            {"new_budget_cents": 600_000, "reason": "scope growth", "expected_case_version": v0},
            CM), 200)
        assert revised["budget_cents"] == 600_000
        assert_version_incremented(revised["version"], v0)

        stale = api.revise_budget(
            case["id"],
            {"new_budget_cents": 700_000, "reason": "stale writer", "expected_case_version": v0},
            CM)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        after = validate_success(api.get_case(case["id"], CM), 200)
        assert after["budget_cents"] == 600_000


class TestImmediateConsistency:

    def test_amend_response_reflects_new_terms_immediately(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field."
        PRD §3.3: "the new terms supersede the prior ones and the engagement's `version`
        increments."

        Design: Corner/consistency_model/amend_response_reflects_new_terms_immediately
        """
        sc = setup_active_engagement()
        engagement = validate_success(api.get_engagement(sc["engagement"]["id"], CM), 200)
        v0 = engagement["version"]

        amended = validate_success(api.amend_engagement(
            engagement["id"],
            {"expected_engagement_version": v0, "hourly_rate_cents": 55_000, "reason": "uplift"},
            CM), 200)
        assert amended["hourly_rate_cents"] == 55_000, "mutation must be visible in the amend response"
        assert amended["version"] == v0 + 1

        fetched = validate_success(api.get_engagement(engagement["id"], CM), 200)
        assert fetched["hourly_rate_cents"] == 55_000, "a subsequent read must agree"
