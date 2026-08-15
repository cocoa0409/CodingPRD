"""Validation ordering, fiscal guards, RBAC denials, optimistic concurrency (PRD §2.1, §2.7, §2.9)."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, validate_success, validate_error, get_success_data,
    ApiErrorId, create_agent_payload, create_plan_p1_payload, create_plan_p2_payload,
    create_deal_payload, create_enrollment_payload, create_debit_adjustment_payload,
    setup_active_agent, setup_active_plan_p1, setup_active_plan_p2,
    setup_agent_on_plan,
    setup_closed_deal, setup_settled_deal, get_leg_by_type,
    make_agent_headers, make_office_manager_headers,
    make_transaction_coordinator_headers, NON_EXISTENT_UUID,
)


class TestSchemaBeforeExistence:
    def test_put_nonexistent_deal_with_bad_body_returns_400(self, api):
        """PRD §2.9: "the first failing guard determines the error returned";
        item 5 (Request schema) precedes item 6 (Path existence) — an incomplete
        PUT body yields ERR_INVALID_REQUEST even for a nonexistent id.

        Design: Corner/validations/put_nonexistent_deal_missing_fields_returns_invalid_request
        """
        resp = api.put_deal(NON_EXISTENT_UUID, {"address": "Only Address"},
                            TEST_USERS["transaction_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestDealFiscalValidationBattery:
    def test_gross_zero_rejected(self, api):
        """PRD §3.5: "The `gross_commission_cents` must be greater than zero,
        else `ERR_NONPOSITIVE_GROSS` (HTTP 422)."

        Design: Corner/validations/deal_fiscal_validation_battery
        """
        agent = setup_active_agent(name="Fiscal Fred")
        ref = setup_active_agent(name="Ref Target")
        resp = api.create_deal(
            create_deal_payload(agent["id"], address="90 Zero St",
                                gross_commission_cents=0, closing_date="2026-01-15"),
            TEST_USERS["transaction_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_NONPOSITIVE_GROSS, expected_status=422)

    def test_cobroke_equal_gross_and_pct_over_one_rejected(self, api):
        """PRD §3.5: "The cobroke_payout_cents must be at least zero and strictly
        less than the gross, else ERR_COBROKE_EXCEEDS_GROSS (HTTP 422)... The
        referral_pct must lie between 0 and 1 inclusive, else
        ERR_PCT_OUT_OF_RANGE."

        Design: Corner/validations/deal_fiscal_validation_battery
        """
        agent = setup_active_agent(name="Fiscal Fred")
        ref = setup_active_agent(name="Ref Target")
        resp = api.create_deal(
            create_deal_payload(agent["id"], address="91 Cobroke Ct", gross_commission_cents=500000,
                                closing_date="2026-01-15", cobroke_payout_cents=500000,
                                cobroke_payee_name="Outside"),
            TEST_USERS["transaction_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_COBROKE_EXCEEDS_GROSS, expected_status=422)
        resp = api.create_deal(
            create_deal_payload(agent["id"], address="92 Pct Pl", gross_commission_cents=500000,
                                closing_date="2026-01-15", referral_pct=1.5,
                                referral_agent_id=ref["id"]),
            TEST_USERS["transaction_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_PCT_OUT_OF_RANGE, expected_status=422)
        deals = get_success_data(api.list_deals(TEST_USERS["broker_admin_headers"],
                                                params={"agent_id": agent["id"]}))
        assert deals == []


class TestPlanTierShapeValidation:
    def test_non_ascending_tiers_rejected(self, api):
        """PRD §3.2: "A plan whose tiers are empty, not strictly ascending, or
        whose final tier is not the zero-split cap is rejected with
        ERR_PLAN_TIERS_INVALID (HTTP 422)."

        Design: Corner/validations/plan_tier_shape_validation
        """
        resp = api.create_plan(
            create_plan_p1_payload(name="BadTiers1", tiers=[
                {"threshold_company_dollar_cents": 2500000, "broker_split_pct": 0.30},
                {"threshold_company_dollar_cents": 1000000, "broker_split_pct": 0.20},
                {"threshold_company_dollar_cents": 0, "broker_split_pct": 0.0},
            ]),
            TEST_USERS["broker_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_PLAN_TIERS_INVALID, expected_status=422)

    def test_final_tier_without_zero_split_rejected(self, api):
        """PRD §3.2: "the final element must carry a broker_split_pct of exactly
        0 — the capped tier in which the agent keeps the entire post-royalty
        commission" — otherwise ERR_PLAN_TIERS_INVALID.

        Design: Corner/validations/plan_tier_shape_validation
        """
        resp = api.create_plan(
            create_plan_p1_payload(name="BadTiers2", tiers=[
                {"threshold_company_dollar_cents": 2500000, "broker_split_pct": 0.30},
            ]),
            TEST_USERS["broker_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_PLAN_TIERS_INVALID, expected_status=422)


class TestReferralCobrokeLinkage:
    def test_referral_pct_without_agent_and_cobroke_without_payee(self, api):
        """PRD §3.5: "the referral pair must be complete in both directions — a
        referral_agent_id with a zero or missing referral_pct, or a positive
        referral_pct with no referral_agent_id, is rejected with
        ERR_REFERRAL_INCOMPLETE (HTTP 422)"; "whenever a co-broke payout is
        present, cobroke_payee_name is required, else ERR_COBROKE_PAYEE_MISSING
        (HTTP 422)."

        Design: Corner/validations/referral_cobroke_linkage_battery
        """
        agent = setup_active_agent(name="Link Lora")
        resp = api.create_deal(
            create_deal_payload(agent["id"], address="93 Half Ref", gross_commission_cents=500000,
                                closing_date="2026-01-15", referral_pct=0.25),
            TEST_USERS["transaction_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_REFERRAL_INCOMPLETE, expected_status=422)
        resp = api.create_deal(
            create_deal_payload(agent["id"], address="94 No Payee", gross_commission_cents=500000,
                                closing_date="2026-01-15", cobroke_payout_cents=100000),
            TEST_USERS["transaction_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_COBROKE_PAYEE_MISSING, expected_status=422)


class TestDuplicateLicense:
    def test_duplicate_license_number_rejected(self, api):
        """PRD §3.1: "The license_number is the state license identifier and must
        be unique across all agents; a collision is rejected with
        ERR_LICENSE_NUMBER_TAKEN (HTTP 409)."

        Design: Corner/validations/duplicate_license_number_rejected
        """
        get_success_data(api.create_agent(
            create_agent_payload(full_name="First", email="f@x.com",
                                 license_number="LIC-DUP", joined_at="2025-09-01"),
            TEST_USERS["broker_admin_headers"]))
        resp = api.create_agent(
            create_agent_payload(full_name="Second", email="s@x.com",
                                 license_number="LIC-DUP", joined_at="2025-09-01"),
            TEST_USERS["broker_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_LICENSE_NUMBER_TAKEN, expected_status=409)


class TestClockAndFutureClosing:
    def test_clock_regression_rejected(self, api):
        """PRD §2.4: "The clock moves forward only: a to_iso8601 that is not
        strictly later than the current clock instant is rejected with
        ERR_CLOCK_REGRESSION (HTTP 422)."

        Design: Corner/validations/clock_regression_and_future_closing_rejected
        """
        resp = api.set_clock({"to_iso8601": "2026-07-01T00:00:00Z"}, TEST_USERS["broker_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION, expected_status=422)

    def test_future_closing_rejected_and_deal_left_pending(self, api):
        """PRD §3.5: "it must not lie after the clock date — future closings are
        rejected with ERR_FUTURE_CLOSING (HTTP 422)."

        Design: Corner/validations/clock_regression_and_future_closing_rejected
        """
        agent = setup_active_agent(name="Clock Carol")
        deal = get_success_data(api.create_deal(
            create_deal_payload(agent["id"], address="95 Future Ave",
                                gross_commission_cents=100000, closing_date="2026-01-15"),
            TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.submit_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        resp = api.close_deal(deal["id"], {"actual_closing_date": "2026-12-31"},
                              TEST_USERS["transaction_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_FUTURE_CLOSING, expected_status=422)
        deal_after = get_success_data(api.get_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert deal_after["status"] == "PENDING_CLOSING"


class TestSettleWithoutEnrollment:
    def test_settle_without_covering_enrollment_returns_no_plan_enrollment(self, api):
        """PRD §3.3: "Settling a deal requires such a covering enrollment for the
        deal's agent; without one the settle is rejected with
        ERR_NO_PLAN_ENROLLMENT (HTTP 409)."

        Design: Corner/validations/settle_without_enrollment_returns_no_plan_enrollment
        """
        agent = setup_active_agent(name="NoPlan Nate")
        deal = setup_closed_deal(agent["id"], address="96 Coverage Gap",
                                 gross_commission_cents=1000000, closing_date="2026-01-15")
        resp = api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_NO_PLAN_ENROLLMENT, expected_status=409)
        settlements = get_success_data(api.list_settlements(
            TEST_USERS["broker_admin_headers"], params={"deal_id": deal["id"]}))
        assert settlements == []


class TestPriorityPairConflicts:
    def test_settle_state_error_beats_missing_enrollment(self, api):
        """PRD §2.9: "the first failing guard determines the error returned — a
        request that would fail several checks always reports the earliest one";
        item 8 (State validity: ERR_DEAL_INVALID_STATE) precedes item 15
        (Referential state guards: ERR_NO_PLAN_ENROLLMENT).

        Design: Difficulty/priority_pair_validation_conflict/settle_state_error_beats_missing_enrollment_referential
        """
        agent = setup_active_agent(name="NoPlan Nina")
        deal = get_success_data(api.create_deal(
            create_deal_payload(agent["id"], address="55 Draft Dr",
                                gross_commission_cents=1000000, closing_date="2026-01-15"),
            TEST_USERS["transaction_coordinator_headers"]))
        resp = api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_DEAL_INVALID_STATE, expected_status=409)
        settlements = get_success_data(api.list_settlements(
            TEST_USERS["broker_admin_headers"], params={"deal_id": deal["id"]}))
        assert settlements == []

    def test_state_first_and_no_settlement_created(self, api):
        """PRD §2.9: "the first failing guard determines the error returned — a
        request that would fail several checks always reports the earliest one"
        — state validity (item 8, `ERR_DEAL_INVALID_STATE`) precedes the
        `ERR_NO_PLAN_ENROLLMENT` guard (item 15), so no Settlement row appears.

        Design: Difficulty/priority_pair_validation_conflict/settle_state_error_beats_missing_enrollment_referential
        """
        agent = setup_active_agent(name="NoPlan Nina")
        deal = get_success_data(api.create_deal(
            create_deal_payload(agent["id"], gross_commission_cents=1000000,
                                closing_date="2026-01-15"),
            TEST_USERS["transaction_coordinator_headers"]))
        resp = api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"])
        assert resp.status_code == 409
        settlements = get_success_data(api.list_settlements(
            TEST_USERS["broker_admin_headers"], params={"deal_id": deal["id"]}))
        assert settlements == []

    def test_temporal_error_beats_fiscal_error(self, api):
        """PRD §2.9: item 10 (The join-date temporal rule: ERR_DEAL_BEFORE_JOIN)
        precedes item 17 (Fiscal range constraints, checked last:
        ERR_NONPOSITIVE_GROSS); "the first failing guard determines the error
        returned".

        Design: Difficulty/priority_pair_validation_conflict/deal_create_temporal_error_beats_fiscal_error
        """
        agent = setup_active_agent(joined_at="2025-09-01", name="Tim Temporal")
        resp = api.create_deal(
            create_deal_payload(agent["id"], address="66 Bad Blvd",
                                gross_commission_cents=0, closing_date="2025-01-01"),
            TEST_USERS["transaction_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_DEAL_BEFORE_JOIN, expected_status=422)
        deals = get_success_data(api.list_deals(TEST_USERS["broker_admin_headers"],
                                                params={"agent_id": agent["id"]}))
        assert deals == []

    def test_temporal_wins_and_no_deal_persisted(self, api):
        """PRD §2.9: "the first failing guard determines the error returned — a
        request that would fail several checks always reports the earliest one"
        — ERR_DEAL_BEFORE_JOIN (item 10) fires before ERR_NONPOSITIVE_GROSS
        (item 17, "checked last"), and the rejected create persists nothing.

        Design: Difficulty/priority_pair_validation_conflict/deal_create_temporal_error_beats_fiscal_error
        """
        agent = setup_active_agent(joined_at="2025-09-01", name="Tim Temporal")
        resp = api.create_deal(
            create_deal_payload(agent["id"], gross_commission_cents=0, closing_date="2025-01-01"),
            TEST_USERS["transaction_coordinator_headers"])
        assert resp.status_code == 422
        deals = get_success_data(api.list_deals(TEST_USERS["broker_admin_headers"],
                                                params={"agent_id": agent["id"]}))
        assert deals == []


class TestCrossEntityStateDependency:
    def test_deal_create_requires_active_agent(self, api):
        """PRD §3.1: "only ACTIVE agents may be credited with new deals, so deal
        creation by or for an agent in any other status is rejected with
        ERR_AGENT_INVALID_STATE (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/deal_create_requires_active_agent
        """
        agent = get_success_data(api.create_agent(
            create_agent_payload(full_name="Newbie Ned", email="ned@x.com",
                                 license_number="LIC-NN1", joined_at="2025-09-01"),
            TEST_USERS["broker_admin_headers"]))
        resp = api.create_deal(
            create_deal_payload(agent["id"], address="1 Too Early Way",
                                gross_commission_cents=500000, closing_date="2026-01-15"),
            TEST_USERS["transaction_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_AGENT_INVALID_STATE, expected_status=409)
        deals = get_success_data(api.list_deals(TEST_USERS["broker_admin_headers"],
                                                params={"agent_id": agent["id"]}))
        assert deals == []

    def test_suspended_agent_cannot_create_deals(self, api):
        """PRD §3.1: "a suspended agent keeps their existing deal pipeline but
        cannot create new deals" — creation for a SUSPENDED agent is rejected
        with ERR_AGENT_INVALID_STATE.

        Design: Difficulty/cross_entity_state_dependency/deal_create_requires_active_agent
        """
        agent = setup_active_agent(name="Suspended Sue")
        get_success_data(api.suspend_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        resp = api.create_deal(
            create_deal_payload(agent["id"], gross_commission_cents=500000,
                                closing_date="2026-01-15"),
            TEST_USERS["transaction_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_AGENT_INVALID_STATE, expected_status=409)

    def test_enrollment_requires_active_plan(self, api):
        """PRD §3.3: "the plan must be `ACTIVE`, else `ERR_PLAN_NOT_ACTIVE`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/enrollment_requires_active_plan
        """
        agent = setup_active_agent(name="Planless Pam")
        plan = get_success_data(api.create_plan(
            create_plan_p1_payload(name="P-DRAFT", mentor_split_pct=0.0, mentor_deal_count=0),
            TEST_USERS["broker_admin_headers"]))
        resp = api.create_enrollment(
            agent["id"],
            create_enrollment_payload(plan["id"], "2025-09-01", agent["version"]),
            TEST_USERS["broker_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE, expected_status=409)
        enrollments = get_success_data(api.list_enrollments(
            TEST_USERS["broker_admin_headers"], params={"agent_id": agent["id"]}))
        assert enrollments == []

    def test_draft_plan_never_accepting_enrollment(self, api):
        """PRD §3.2: "Activation moves a plan from `DRAFT` to `ACTIVE` — only
        `ACTIVE` plans accept enrollments" — a `DRAFT` plan rejects enrollment
        with `ERR_PLAN_NOT_ACTIVE` (§3.3).

        Design: Difficulty/cross_entity_state_dependency/enrollment_requires_active_plan
        """
        agent = setup_active_agent(name="Planless Pam")
        plan = get_success_data(api.create_plan(
            create_plan_p1_payload(name="P-DRAFT"), TEST_USERS["broker_admin_headers"]))
        assert plan["status"] == "DRAFT"
        resp = api.create_enrollment(
            agent["id"],
            create_enrollment_payload(plan["id"], "2025-09-01", agent["version"]),
            TEST_USERS["broker_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE, expected_status=409)


class TestPlanRetireAndAgentTerminate:
    def test_retire_blocked_while_enrolled_then_allowed(self, api):
        """PRD §3.2: "Retiring a plan that any enrollment still references in
        ACTIVE or SCHEDULED status is blocked with ERR_PLAN_IN_USE (HTTP 409)."
        PRD §3.1: "Termination cascades into the agent's enrollments: the
        agent's ACTIVE enrollment, if any, moves to ENDED with its effective_to
        set to the termination date (the clock date)".

        Design: Corner/state_machines/plan_retire_blocked_while_enrolled_then_allowed
        """
        agent = setup_active_agent(name="Retire Rita")
        plan = setup_active_plan_p1(mentor_split_pct=0.0, mentor_deal_count=0)
        e1 = get_success_data(api.create_enrollment(
            agent["id"], create_enrollment_payload(plan["id"], "2025-09-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        resp = api.retire_plan(plan["id"], TEST_USERS["broker_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_PLAN_IN_USE, expected_status=409)
        get_success_data(api.terminate_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        e1_after = get_success_data(api.get_enrollment(e1["id"], TEST_USERS["broker_admin_headers"]))
        assert e1_after["status"] == "ENDED"
        assert e1_after["effective_to"] == "2026-08-01"
        retired = get_success_data(api.retire_plan(plan["id"], TEST_USERS["broker_admin_headers"]))
        assert retired["status"] == "RETIRED"

    def test_retire_draft_plan_allowed(self, api):
        """PRD §3.2: "retirement moves a plan from either `DRAFT` or `ACTIVE`
        to `RETIRED`, the terminal state."

        Design: Corner/state_machines/plan_retire_blocked_while_enrolled_then_allowed
        """
        plan = get_success_data(api.create_plan(create_plan_p1_payload(name="PDraft"),
                                                TEST_USERS["broker_admin_headers"]))
        retired = get_success_data(api.retire_plan(plan["id"], TEST_USERS["broker_admin_headers"]))
        assert retired["status"] == "RETIRED"

    def test_terminate_blocked_by_open_deals_then_succeeds(self, api):
        """PRD §3.1: "It is blocked while the agent still has deals in DRAFT or
        PENDING_CLOSING — the rejection is ERR_AGENT_HAS_OPEN_DEALS (HTTP 409)".

        Design: Corner/state_machines/terminate_blocked_by_open_deal_then_succeeds
        """
        agent = setup_active_agent(name="Open Olga")
        deal = get_success_data(api.create_deal(
            create_deal_payload(agent["id"], address="11 Pipeline Pl",
                                gross_commission_cents=100000, closing_date="2026-01-15"),
            TEST_USERS["transaction_coordinator_headers"]))
        resp = api.terminate_agent(agent["id"], TEST_USERS["broker_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_AGENT_HAS_OPEN_DEALS, expected_status=409)
        get_success_data(api.submit_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        resp = api.terminate_agent(agent["id"], TEST_USERS["broker_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_AGENT_HAS_OPEN_DEALS, expected_status=409)
        get_success_data(api.fall_through_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        terminated = get_success_data(api.terminate_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        assert terminated["status"] == "TERMINATED"


class TestReferralFkIntegrity:
    def test_referral_fk_must_exist_and_differ(self, api):
        """PRD §3.5: "A `referral_agent_id` must reference an existing Agent
        (`ERR_NOT_FOUND`) that differs from the deal's own `agent_id`
        (`ERR_SELF_REFERENCE`, HTTP 422)."

        Design: Corner/entities/deal_create_referral_fk_must_exist
        """
        agent = setup_active_agent(name="Ref Rachel")
        resp1 = api.create_deal(
            create_deal_payload(agent["id"], address="3 Ghost Ct", gross_commission_cents=500000,
                                closing_date="2026-01-15", referral_pct=0.25,
                                referral_agent_id=NON_EXISTENT_UUID),
            TEST_USERS["transaction_coordinator_headers"])
        validate_error(resp1, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
        resp2 = api.create_deal(
            create_deal_payload(agent["id"], address="4 Self St", gross_commission_cents=500000,
                                closing_date="2026-01-15", referral_pct=0.25,
                                referral_agent_id=agent["id"]),
            TEST_USERS["transaction_coordinator_headers"])
        validate_error(resp2, ApiErrorId.ERR_SELF_REFERENCE, expected_status=422)
        deals = get_success_data(api.list_deals(TEST_USERS["broker_admin_headers"],
                                                params={"agent_id": agent["id"]}))
        assert deals == []


class TestRbacDenials:
    def test_agent_cannot_create_plan(self, api):
        """PRD §2.1: "a caller whose role is not on an endpoint's list is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)." §4: POST
        /brokerage/plans is BrokerAdmin-only.

        Design: Corner/rbac/agent_cannot_create_plan_forbidden
        """
        agent = setup_active_agent(name="Role Rex")
        resp = api.create_plan(create_plan_p1_payload(name="PX"),
                               make_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)
        plans = get_success_data(api.list_plans(TEST_USERS["broker_admin_headers"],
                                                params={"status": "DRAFT"}))
        assert plans == []

    def test_transaction_coordinator_cannot_authorize_leg(self, api):
        """PRD §2.1: "a caller whose role is not on an endpoint's list is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)"; §4 shows the
        authorize endpoint's roles as "OfficeManager, BrokerAdmin" only.

        Design: Corner/rbac/transaction_coordinator_cannot_authorize_leg_forbidden
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Deny Dora")
        settlement, deal = setup_settled_deal(agent["id"], poster_user_id="tc-1")
        leg = get_leg_by_type(settlement["id"], "AGENT")
        resp = api.authorize_leg(leg["id"], make_transaction_coordinator_headers("tc-9"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)

    def test_office_manager_cannot_settle_deal(self, api):
        """PRD §2.1: "a caller whose role is not on an endpoint's list is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)"; §4 shows the settle
        endpoint's role as "TransactionCoordinator" only.

        Design: Corner/rbac/office_manager_cannot_settle_deal_forbidden
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Settle Seth")
        deal = setup_closed_deal(agent["id"], address="101 Settle St",
                                 gross_commission_cents=1000000, closing_date="2026-01-15")
        resp = api.settle_deal(deal["id"], make_office_manager_headers("om-7"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)
        deal_after = get_success_data(api.get_deal(deal["id"], TEST_USERS["broker_admin_headers"]))
        assert deal_after["status"] == "CLOSED"
        settlements = get_success_data(api.list_settlements(
            TEST_USERS["broker_admin_headers"], params={"deal_id": deal["id"]}))
        assert settlements == []

    def test_auditor_cannot_terminate_agent(self, api):
        """PRD §2.1: "An `Auditor` is a read-only compliance auditor with access
        to every read endpoint, including the global trust ledger, and no write
        access at all."

        Design: Corner/rbac/auditor_cannot_terminate_agent_forbidden
        """
        agent = setup_active_agent(name="Audit Amy")
        resp = api.terminate_agent(agent["id"], TEST_USERS["auditor_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)
        after = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        assert after["status"] == "ACTIVE"

    def test_agent_cannot_adjust_own_debit(self, api):
        """PRD §2.9: "Role admission: the caller's role must appear in the
        endpoint's role list, else `ERR_FORBIDDEN_FOR_ROLE`" (item 2) precedes
        "Agent ownership scoping" (item 4); §4 shows debit-adjustments as
        BrokerAdmin only, so even an Agent touching their own balance is
        role-denied.

        Design: Corner/rbac/agent_cannot_adjust_own_debit_forbidden
        """
        agent = setup_active_agent(name="Self Serve")
        resp = api.create_debit_adjustment(
            agent["id"], create_debit_adjustment_payload(-1, "self service"),
            make_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)

    def test_agent_reading_other_agents_deal_forbidden(self, api):
        """PRD §2.1: "a caller touching a resource owned by another agent is
        rejected with `ERR_FORBIDDEN_RESOURCE` (HTTP 403)."

        Design: Corner/rbac/agent_reading_other_agents_deal_forbidden
        """
        a = setup_active_agent(name="Owner Owen")
        b = setup_active_agent(name="Pry Pam")
        deal = get_success_data(api.create_deal(
            create_deal_payload(a["id"], address="102 Private Pl",
                                gross_commission_cents=100000, closing_date="2026-01-15"),
            TEST_USERS["transaction_coordinator_headers"]))
        resp = api.get_deal(deal["id"], make_agent_headers(b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE, expected_status=403)
        own = get_success_data(api.get_deal(deal["id"], make_agent_headers(a["id"])))
        assert own["id"] == deal["id"]

    def test_unknown_agent_identity_rejected(self, api):
        """PRD §2.1: "A request arriving with `X-User-Role` set to `Agent` whose
        `X-User-ID` does not identify an existing Agent is rejected with
        `ERR_UNKNOWN_USER_IDENTITY` (HTTP 403)."

        Design: Corner/rbac/unknown_agent_identity_rejected
        """
        resp = api.list_deals(make_agent_headers(NON_EXISTENT_UUID))
        validate_error(resp, ApiErrorId.ERR_UNKNOWN_USER_IDENTITY, expected_status=403)

    def test_missing_auth_headers_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty
        value in either, is rejected with `ERR_MISSING_USER_CONTEXT`
        (HTTP 400)."

        Design: Corner/rbac/missing_auth_headers_returns_400
        """
        resp = api.list_agents({})
        validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT, expected_status=400)


class TestOptimisticConcurrency:
    def test_enrollment_create_stale_agent_version(self, api):
        """PRD §2.7: "A POST /brokerage/agents/{agentId}/enrollments request must
        carry expected_agent_version ... a value that no longer matches the
        agent's current version means another write has moved the agent since
        the caller last read it; the create is then rejected with
        ERR_STALE_AGENT_VERSION (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_enrollment_create_stale_agent_version
        """
        agent = setup_active_agent(name="Occ Olivia")
        p1 = setup_active_plan_p1(mentor_split_pct=0.0, mentor_deal_count=0)
        p2 = setup_active_plan_p2()
        v_snapshot = agent["version"]
        e1 = get_success_data(api.create_enrollment(
            agent["id"], create_enrollment_payload(p1["id"], "2025-09-01", v_snapshot),
            TEST_USERS["broker_admin_headers"]))
        assert e1["status"] == "ACTIVE"
        resp = api.create_enrollment(
            agent["id"], create_enrollment_payload(p2["id"], "2026-03-01", v_snapshot),
            TEST_USERS["broker_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_AGENT_VERSION, expected_status=412)
        enrollments = get_success_data(api.list_enrollments(
            TEST_USERS["broker_admin_headers"], params={"agent_id": agent["id"]}))
        assert len(enrollments) == 1

    def test_enrollment_create_bumps_agent_version_by_one(self, api):
        """PRD §3.3: "the agent's version rises by exactly 1 for the whole
        enrollment-creation request."

        Design: Corner/cross_cutting_layers/occ_enrollment_create_stale_agent_version
        """
        agent = setup_active_agent(name="Occ Olivia")
        p1 = setup_active_plan_p1(mentor_split_pct=0.0, mentor_deal_count=0)
        v_before = agent["version"]
        get_success_data(api.create_enrollment(
            agent["id"], create_enrollment_payload(p1["id"], "2025-09-01", v_before),
            TEST_USERS["broker_admin_headers"]))
        after = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        assert after["version"] == v_before + 1

    def test_plan_update_stale_version(self, api):
        """PRD §2.7: "A PUT /brokerage/plans/{planId} request must carry
        expected_plan_version. If an intervening edit has already advanced the
        plan's version, applying the caller's diff would silently discard that
        edit, so the request is rejected with ERR_STALE_PLAN_VERSION
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_plan_update_stale_version
        """
        plan = get_success_data(api.create_plan(
            create_plan_p1_payload(name="OccPlan", mentor_split_pct=0.0, mentor_deal_count=0),
            TEST_USERS["broker_admin_headers"]))
        p_v = plan["version"]
        updated = get_success_data(api.put_plan(plan["id"], {
            "expected_plan_version": p_v, "name": "OccPlan v2",
            "royalty_pct": 0.06, "royalty_cap_cents": 300000,
            "eo_fee_cents": 6500, "transaction_fee_cents": 25000,
            "tiers": [
                {"threshold_company_dollar_cents": 2500000, "broker_split_pct": 0.30},
                {"threshold_company_dollar_cents": 10**18, "broker_split_pct": 0.0},
            ],
        }, TEST_USERS["broker_admin_headers"]))
        assert updated["version"] == p_v + 1
        assert updated["eo_fee_cents"] == 6500
        resp = api.put_plan(plan["id"], {
            "expected_plan_version": p_v, "name": "OccPlan stale",
            "royalty_pct": 0.07, "royalty_cap_cents": 300000,
            "eo_fee_cents": 6000, "transaction_fee_cents": 25000,
            "tiers": [
                {"threshold_company_dollar_cents": 2500000, "broker_split_pct": 0.30},
                {"threshold_company_dollar_cents": 10**18, "broker_split_pct": 0.0},
            ],
        }, TEST_USERS["broker_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_PLAN_VERSION, expected_status=412)
        after = get_success_data(api.get_plan(plan["id"], TEST_USERS["broker_admin_headers"]))
        assert after["name"] == "OccPlan v2"
        assert after["royalty_pct"] == 0.06

    def test_plan_update_version_increments_by_one(self, api):
        """PRD §3.2: "a successful edit increments the plan's `version` by 1".

        Design: Corner/cross_cutting_layers/occ_plan_update_stale_version
        """
        plan = get_success_data(api.create_plan(
            create_plan_p1_payload(name="OccPlan"), TEST_USERS["broker_admin_headers"]))
        v1 = plan["version"]
        updated = get_success_data(api.put_plan(plan["id"], {
            "expected_plan_version": v1, "name": "OccPlan v2",
            "royalty_pct": 0.06, "royalty_cap_cents": 300000,
            "eo_fee_cents": 6500, "transaction_fee_cents": 25000,
            "tiers": [
                {"threshold_company_dollar_cents": 2500000, "broker_split_pct": 0.30},
                {"threshold_company_dollar_cents": 10**18, "broker_split_pct": 0.0},
            ],
        }, TEST_USERS["broker_admin_headers"]))
        assert updated["version"] == v1 + 1

    def test_agent_patch_stale_version(self, api):
        """PRD §2.7: "A PATCH /brokerage/agents/{agentId} request must likewise
        carry expected_agent_version. When the caller's snapshot of the agent
        predates an intervening write ... the mismatch is rejected with
        ERR_STALE_AGENT_VERSION (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_agent_patch_stale_version
        """
        agent = get_success_data(api.create_agent(
            create_agent_payload(full_name="Patch Paul", email="pp2@x.com",
                                 license_number="LIC-OC2", joined_at="2025-09-01"),
            TEST_USERS["broker_admin_headers"]))
        v1 = agent["version"]
        activated = get_success_data(api.activate_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        v2 = activated["version"]
        resp = api.patch_agent(agent["id"], {"expected_agent_version": v1, "email": "stale@x.com"},
                               TEST_USERS["broker_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_AGENT_VERSION, expected_status=412)
        patched = get_success_data(api.patch_agent(
            agent["id"], {"expected_agent_version": v2, "email": "fresh@x.com"},
            TEST_USERS["broker_admin_headers"]))
        assert patched["email"] == "fresh@x.com"
        assert patched["version"] == v2 + 1

    def test_agent_patch_successful_increments_version(self, api):
        """PRD §3.1: "a successful patch increments the agent's `version` by
        1".

        Design: Corner/cross_cutting_layers/occ_agent_patch_stale_version
        """
        agent = get_success_data(api.create_agent(
            create_agent_payload(full_name="Patch Paul", email="pp2@x.com",
                                 license_number="LIC-OC2", joined_at="2025-09-01"),
            TEST_USERS["broker_admin_headers"]))
        patched = get_success_data(api.patch_agent(
            agent["id"], {"expected_agent_version": agent["version"], "email": "fresh@x.com"},
            TEST_USERS["broker_admin_headers"]))
        assert patched["version"] == agent["version"] + 1


class TestSuccessEnvelopeVersionIncrements:
    def test_version_increments_exactly_one_per_mutation(self, api):
        """PRD §2.5: "version (integer): a system-managed integer starting at 1
        that increments by exactly 1 on every mutation of the resource,
        including state transitions and cascade-driven changes."

        Design: Corner/endpoints/success_envelope_and_version_increment_on_mutation
        """
        agent = get_success_data(api.create_agent(
            create_agent_payload(full_name="Version Vic", email="vv@x.com",
                                 license_number="LIC-VV1", joined_at="2025-09-01"),
            TEST_USERS["broker_admin_headers"]))
        assert agent["version"] == 1
        activated = get_success_data(api.activate_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        assert activated["version"] == 2
        patched = get_success_data(api.patch_agent(
            agent["id"], {"expected_agent_version": 2, "email": "vv2@x.com"},
            TEST_USERS["broker_admin_headers"]))
        assert patched["version"] == 3

    def test_object_envelope_on_mutations(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field" — every response is the object envelope with meta.api_request_id.

        Design: Corner/endpoints/success_envelope_and_version_increment_on_mutation
        """
        resp = api.create_agent(
            create_agent_payload(full_name="Version Vic", email="vv@x.com",
                                 license_number="LIC-VV1", joined_at="2025-09-01"),
            TEST_USERS["broker_admin_headers"])
        body = resp.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"]
        data = body["data"]
        resp2 = api.activate_agent(data["id"], TEST_USERS["broker_admin_headers"])
        body2 = resp2.json()
        assert body2["response_type"] == "object"
        assert body2["meta"]["api_request_id"]
