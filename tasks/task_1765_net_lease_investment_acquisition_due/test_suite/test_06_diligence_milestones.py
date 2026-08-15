"""Diligence milestones: waiver restrictions, clock-driven overdue cascades,
and the financing-lapse chain."""
from test_helpers import (
    ApiErrorId,
    create_financing_application_payload,
    get_deal,
    get_milestone_by_type,
    list_milestones,
    set_clock,
    setup_psa_executed,
    validate_error,
    validate_success,
)


class TestMilestoneWaiverRules:
    def test_milestone_waive_title_review_not_waivable(
            self, api, committee_headers):
        """PRD §3.5: "Two milestone types are never waivable — `TITLE_REVIEW`
        and `ENVIRONMENTAL` — and an attempt to waive either is rejected with
        `ERR_MILESTONE_NOT_WAIVABLE` (HTTP 422)."

        Design: Corner/state_machines/milestone_waive_title_review_not_waivable
        """
        ctx = setup_psa_executed(deal_name="WaiveDeal")
        deal_id = ctx["deal"]["id"]

        title_ms = get_milestone_by_type(deal_id, "TITLE_REVIEW")
        resp = api.waive_milestone(deal_id, title_ms["id"], committee_headers)
        validate_error(resp, ApiErrorId.ERR_MILESTONE_NOT_WAIVABLE)

        env_ms = get_milestone_by_type(deal_id, "ENVIRONMENTAL")
        resp2 = api.waive_milestone(deal_id, env_ms["id"], committee_headers)
        validate_error(resp2, ApiErrorId.ERR_MILESTONE_NOT_WAIVABLE)


class TestClockDrivenMilestoneOverdue:
    def test_scheduled_deferred_action_milestone_overdue_via_clock(
            self, api, platform_admin_headers):
        """PRD §2.6: "a pending diligence milestone whose `due_date` has
        passed flips to `OVERDUE` and pushes the deal posture to
        `DD_BLOCKED`"
        PRD §3.4: "When the PSA carries a `financing_contingency_days` of
        zero — no financing contingency — the `FINANCING_COMMITMENT`
        milestone is created directly in `WAIVED`, since no loan is
        required."

        Design: Corner/cross_cutting_layers/scheduled_deferred_action_milestone_overdue_via_clock
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = setup_psa_executed(deal_name="SchedDeal", dd_period_days=15,
                                 financing_contingency_days=0)
        deal_id = ctx["deal"]["id"]
        # All eight milestones carry due_date == dd_period_end (2026-08-16).
        assert all(m["status"] in ("PENDING", "WAIVED")
                   for m in ctx["milestones"])

        # Advance the clock past dd_period_end.
        set_clock("2026-08-17T00:00:00Z")

        milestones = list_milestones(deal_id)
        by_type = {m["milestone_type"]: m["status"] for m in milestones}
        overdue = [t for t, s in by_type.items() if s == "OVERDUE"]
        assert len(overdue) == 7, (
            f"The seven PENDING milestones flip to OVERDUE, got {by_type}")
        assert by_type["FINANCING_COMMITMENT"] == "WAIVED", (
            "The auto-waived financing milestone is terminal and stays WAIVED")

        deal = get_deal(deal_id)
        assert deal["posture"] == "DD_BLOCKED"


class TestFinancingLapseCascade:
    def _setup_submitted_app(self, api, capital_markets_headers):
        """Deal at PSA_EXECUTED (dd 30 days, financing window 20 days, so the
        contingency closes 2026-08-21) with one SUBMITTED application."""
        set_clock("2026-08-01T00:00:00Z")
        ctx = setup_psa_executed(
            deal_name="ClockCascadeDeal", purchase_price_cents=20000000,
            lease_rent_cents=1400000, lease_type="NN",
            lease_expiration="2033-01-01T00:00:00Z",
            dd_period_days=30, financing_contingency_days=20,
            property_overrides={"address": "9 Clock Ln",
                                "rentable_sqft": 12000, "year_built": 2011},
            tenant_overrides={"legal_name": "ClockTenant"})
        deal_id = ctx["deal"]["id"]
        app = validate_success(api.create_financing_application(
            deal_id,
            create_financing_application_payload(loan_amount_cents=12000000),
            capital_markets_headers), 201)
        submitted = validate_success(api.submit_financing_application(
            deal_id, app["id"], capital_markets_headers))
        assert submitted["status"] == "SUBMITTED"
        return ctx, app

    def test_clock_advance_lapses_application_and_blocks_posture(
            self, api, platform_admin_headers, capital_markets_headers):
        """PRD §2.6: "a financing application still sitting in `SUBMITTED`
        when the clock passes the deal's `financing_contingency_end` lapses
        to `LAPSED`, which marks the financing milestone `OVERDUE` and
        recomputes the deal posture"
        PRD §2.7: "Blocking events (a `FATAL` title exception raised, an
        environmental assessment failed, a milestone rolling `OVERDUE`, a
        financing application lapsing) push the posture to `DD_BLOCKED`"

        Design: Difficulty/transitive_cascade/milestone_overdue_cascade_depth2_from_clock_advance
        """
        ctx, app = self._setup_submitted_app(api, capital_markets_headers)
        deal_id = ctx["deal"]["id"]

        set_clock("2026-08-22T00:00:00Z")

        app_after = validate_success(api.get_financing_application(
            deal_id, app["id"], capital_markets_headers))
        assert app_after["status"] == "LAPSED", (
            "Link 1: the clock advance lapses the SUBMITTED application")

        fin_ms = get_milestone_by_type(deal_id, "FINANCING_COMMITMENT")
        assert fin_ms["status"] == "OVERDUE", (
            "Link 2: the lapse flips the financing milestone to OVERDUE")

        deal = get_deal(deal_id)
        assert deal["posture"] == "DD_BLOCKED", (
            "Link 3: the overdue milestone recomputes the posture")

    def test_commit_on_lapsed_application_is_invalid_state(
            self, api, capital_markets_headers):
        """PRD §3.9: "Invalid from-states on any of these transitions return
        `ERR_FINANCING_INVALID_STATE`."
        PRD §2.6: "a financing application still sitting in `SUBMITTED` when
        the clock passes the deal's `financing_contingency_end` lapses to
        `LAPSED`"

        Design: Difficulty/transitive_cascade/milestone_overdue_cascade_depth2_from_clock_advance
        """
        ctx, app = self._setup_submitted_app(api, capital_markets_headers)
        deal_id = ctx["deal"]["id"]
        set_clock("2026-08-22T00:00:00Z")

        resp = api.commit_financing_application(deal_id, app["id"],
                                                capital_markets_headers)
        validate_error(resp, ApiErrorId.ERR_FINANCING_INVALID_STATE)


class TestCertifyMilestoneGate:
    def test_certify_blocked_while_milestones_outstanding(
            self, api, committee_headers, dd_officer_headers):
        """PRD §3.10: "The certification enforces seven gates, evaluated
        after the generic validation layers of §2.8: every milestone must be
        `SATISFIED` or `WAIVED` (else `ERR_MILESTONES_OUTSTANDING`)"
        PRD §3.5: "starting the first milestone moves the deal itself from
        `PSA_EXECUTED` into `DUE_DILIGENCE`"

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_pair_on_estoppel_certify
        """
        ctx = setup_psa_executed(deal_name="PriorityDeal2a",
                                 purchase_price_cents=20000000,
                                 lease_rent_cents=1300000, lease_type="NN",
                                 lease_expiration="2034-06-01T00:00:00Z",
                                 dd_period_days=45,
                                 financing_contingency_days=30)
        deal_id = ctx["deal"]["id"]
        # Move the deal into DUE_DILIGENCE; seven milestones stay PENDING.
        walkthrough = get_milestone_by_type(deal_id, "FINAL_WALKTHROUGH")
        validate_success(api.start_milestone(deal_id, walkthrough["id"],
                                             dd_officer_headers))
        resp = api.certify_clear_to_close(deal_id, committee_headers)
        validate_error(resp, ApiErrorId.ERR_MILESTONES_OUTSTANDING)
