"""Anniversary boundaries, plan-change variant selection, payout-estimate (PRD §3.4, §3.3, §3.6)."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, validate_success, validate_error, get_success_data,
    ApiErrorId, create_agent_payload, create_plan_p1_payload,
    create_enrollment_payload, create_deal_payload,
    setup_active_agent, setup_active_plan_p1, setup_active_plan_p2,
    setup_agent_on_plan, setup_closed_deal, setup_settled_deal, get_window_for_agent,
    make_transaction_coordinator_headers,
)


class TestWindowEndExclusiveBoundary:
    def test_last_day_of_window_vs_window_end(self, api):
        """PRD §3.4: "Windows are half-open: a date belongs to the window whose
        start is on or before it and whose end is strictly after it, so a
        closing date exactly equal to a window_end belongs to the next window."

        Design: Corner/calculations/anniversary_window_end_exclusive_boundary
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Edge Ed")
        da = get_success_data(api.create_deal(
            create_deal_payload(agent["id"], address="30 Last Day Ln",
                                gross_commission_cents=100000, closing_date="2026-08-31"),
            TEST_USERS["transaction_coordinator_headers"]))
        db = get_success_data(api.create_deal(
            create_deal_payload(agent["id"], address="31 First Day Rd",
                                gross_commission_cents=100000, closing_date="2026-09-01"),
            TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.submit_deal(da["id"], TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.submit_deal(db["id"], TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.set_clock({"to_iso8601": "2026-08-31T12:00:00Z"},
                                       TEST_USERS["broker_admin_headers"]))
        get_success_data(api.close_deal(da["id"], {}, TEST_USERS["transaction_coordinator_headers"]))
        sa = get_success_data(api.settle_deal(da["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert sa["window_start"] == "2025-09-01"
        get_success_data(api.set_clock({"to_iso8601": "2026-09-01T00:00:01Z"},
                                       TEST_USERS["broker_admin_headers"]))
        get_success_data(api.close_deal(db["id"], {}, TEST_USERS["transaction_coordinator_headers"]))
        sb = get_success_data(api.settle_deal(db["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert sb["window_start"] == "2026-09-01"
        assert sb["royalty_cents"] == 6000
        assert sb["company_dollar_cents"] == 28200

    def test_each_window_accrued_independently(self, api):
        """PRD §3.4: "Each window carries two accumulators, both starting at 0" —
        a deal posting to the next window accrues there, leaving the prior
        window's total untouched.

        Design: Corner/calculations/anniversary_window_end_exclusive_boundary
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Edge Ed")
        da = get_success_data(api.create_deal(
            create_deal_payload(agent["id"], gross_commission_cents=100000,
                                closing_date="2026-08-31"),
            TEST_USERS["transaction_coordinator_headers"]))
        db = get_success_data(api.create_deal(
            create_deal_payload(agent["id"], gross_commission_cents=100000,
                                closing_date="2026-09-01"),
            TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.submit_deal(da["id"], TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.submit_deal(db["id"], TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.set_clock({"to_iso8601": "2026-08-31T12:00:00Z"},
                                       TEST_USERS["broker_admin_headers"]))
        get_success_data(api.close_deal(da["id"], {}, TEST_USERS["transaction_coordinator_headers"]))
        api.settle_deal(da["id"], TEST_USERS["transaction_coordinator_headers"])
        get_success_data(api.set_clock({"to_iso8601": "2026-09-01T00:00:01Z"},
                                       TEST_USERS["broker_admin_headers"]))
        get_success_data(api.close_deal(db["id"], {}, TEST_USERS["transaction_coordinator_headers"]))
        api.settle_deal(db["id"], TEST_USERS["transaction_coordinator_headers"])
        windows = get_success_data(api.list_anniversary_periods(
            TEST_USERS["broker_admin_headers"], params={"agent_id": agent["id"]}))
        assert windows[0]["company_dollar_accrued_cents"] == 28200
        assert windows[0]["status"] == "CLOSED"
        assert windows[1]["company_dollar_accrued_cents"] == 28200
        assert windows[1]["status"] == "OPEN"


class TestLeapDayJoinAnniversaryRoll:
    def test_feb29_join_rolls_to_mar01_in_non_leap_year(self, api):
        """PRD §3.4: "The window_start is joined_at advanced by window_index
        years — an agent who joined on February 29 starts their window on March
        1 in non-leap years — and the window_end is the start of the following
        window."

        Design: Corner/calculations/leap_day_join_anniversary_roll
        """
        agent = setup_active_agent(joined_at="2028-02-29", name="Leap Lena")
        plan = setup_active_plan_p1(mentor_split_pct=0.0, mentor_deal_count=0)
        # Enrollment effective at the join date is future vs the default clock
        e = get_success_data(api.create_enrollment(
            agent["id"], create_enrollment_payload(plan["id"], "2028-02-29", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        assert e["status"] == "SCHEDULED"
        da = get_success_data(api.create_deal(
            create_deal_payload(agent["id"], address="40 Leap Ln A",
                                gross_commission_cents=100000, closing_date="2029-02-28"),
            TEST_USERS["transaction_coordinator_headers"]))
        db = get_success_data(api.create_deal(
            create_deal_payload(agent["id"], address="41 Leap Ln B",
                                gross_commission_cents=100000, closing_date="2029-03-01"),
            TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.submit_deal(da["id"], TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.submit_deal(db["id"], TEST_USERS["transaction_coordinator_headers"]))
        sweep = get_success_data(api.set_clock({"to_iso8601": "2029-02-28T12:00:00Z"},
                                               TEST_USERS["broker_admin_headers"]))
        assert sweep["activated_enrollment_ids"]
        get_success_data(api.close_deal(da["id"], {}, TEST_USERS["transaction_coordinator_headers"]))
        sa = get_success_data(api.settle_deal(da["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert sa["window_start"] == "2028-02-29"
        get_success_data(api.set_clock({"to_iso8601": "2029-03-01T00:00:01Z"},
                                       TEST_USERS["broker_admin_headers"]))
        get_success_data(api.close_deal(db["id"], {}, TEST_USERS["transaction_coordinator_headers"]))
        sb = get_success_data(api.settle_deal(db["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert sb["window_start"] == "2029-03-01"

    def test_window_before_roll_date_stays_in_window_zero(self, api):
        """PRD §3.4: "Windows are half-open: a date belongs to the window whose
        start is on or before it and whose end is strictly after it" — with the
        Feb-29 roll, 2029-02-28 is strictly before the rolled window_end of
        2029-03-01 and stays in window 0.

        Design: Corner/calculations/leap_day_join_anniversary_roll
        """
        agent = setup_active_agent(joined_at="2028-02-29", name="Leap Lena")
        plan = setup_active_plan_p1(mentor_split_pct=0.0, mentor_deal_count=0)
        get_success_data(api.create_enrollment(
            agent["id"], create_enrollment_payload(plan["id"], "2028-02-29", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        da = get_success_data(api.create_deal(
            create_deal_payload(agent["id"], gross_commission_cents=100000,
                                closing_date="2029-02-28"),
            TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.submit_deal(da["id"], TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.set_clock({"to_iso8601": "2029-02-28T12:00:00Z"},
                                       TEST_USERS["broker_admin_headers"]))
        get_success_data(api.close_deal(da["id"], {}, TEST_USERS["transaction_coordinator_headers"]))
        sa = get_success_data(api.settle_deal(da["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert sa["window_start"] == "2028-02-29"


class TestPlanChangeMidAnniversary:
    def test_plan_change_keeps_window_accumulators(self, api):
        """PRD §3.4: "Each window carries two accumulators, both starting at 0:
        company_dollar_accrued_cents, fed by posted settlements with the company
        dollar each produced" — a mid-window plan change does not reset them;
        PRD §3.6: the covering enrollment for the closing date governs the
        terms.

        Design: Corner/calculations/plan_change_mid_anniversary_keeps_accumulators
        """
        agent = setup_active_agent(name="Mid Milo")
        p1 = setup_active_plan_p1()
        p2 = setup_active_plan_p2()
        get_success_data(api.create_enrollment(
            agent["id"], create_enrollment_payload(p1["id"], "2025-09-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        d1 = setup_closed_deal(agent["id"], address="50 Old Plan Pl",
                               gross_commission_cents=1000000, closing_date="2026-01-15")
        api.settle_deal(d1["id"], TEST_USERS["transaction_coordinator_headers"])
        agent = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        e2 = get_success_data(api.create_enrollment(
            agent["id"], create_enrollment_payload(p2["id"], "2026-03-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        assert e2["status"] == "ACTIVE"
        d2 = setup_closed_deal(agent["id"], address="51 New Plan Way",
                               gross_commission_cents=500000, closing_date="2026-04-01")
        s2 = get_success_data(api.settle_deal(d2["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert s2["enrollment_id"] == e2["id"]
        assert s2["eo_fee_cents"] == 7000
        assert s2["transaction_fee_cents"] == 20000
        assert s2["company_dollar_cents"] == 117500
        assert s2["royalty_cents"] == 30000
        assert s2["agent_net_cents"] == 325500
        w0 = get_window_for_agent(agent["id"], 0)
        assert w0["company_dollar_accrued_cents"] == 399500
        assert w0["royalty_accrued_cents"] == 90000

    def test_closing_date_selects_the_covering_enrollment(self, api):
        """PRD §3.6: "the covering enrollment is located, and third, the plan
        terms pinned on that enrollment's plan_version — recorded on the
        settlement as plan_version_used — become the governing schedule";
        §3.3: "An enrollment covers a closing date when its effective_from is on
        or before the closing date and either its effective_to is null or the
        closing date falls strictly before effective_to."

        Design: Corner/calculations/plan_change_mid_anniversary_keeps_accumulators
        """
        agent = setup_active_agent(name="Mid Milo")
        p1 = setup_active_plan_p1()
        p2 = setup_active_plan_p2()
        e1 = get_success_data(api.create_enrollment(
            agent["id"], create_enrollment_payload(p1["id"], "2025-09-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        agent = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        e2 = get_success_data(api.create_enrollment(
            agent["id"], create_enrollment_payload(p2["id"], "2026-03-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        d2 = setup_closed_deal(agent["id"], gross_commission_cents=500000, closing_date="2026-04-01")
        s2 = get_success_data(api.settle_deal(d2["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert s2["enrollment_id"] == e2["id"]


class TestRetroactiveEnrollmentReplanning:
    def test_retroactive_plan_change_replans_by_closing_date(self, api):
        """PRD §3.3: "An enrollment covers a closing date when its effective_from
        is on or before the closing date and either its effective_to is null or
        the closing date falls strictly before effective_to." §3.6: "the
        covering enrollment is located" per deal by closing date.

        Design: Corner/calculations/enrollment_retroactive_effective_date_replans_by_closing_date
        """
        agent = setup_active_agent(joined_at="2026-01-01", name="Retro Rex")
        p1 = setup_active_plan_p1()
        p2 = setup_active_plan_p2()
        e1 = get_success_data(api.create_enrollment(
            agent["id"], create_enrollment_payload(p1["id"], "2026-01-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        da = setup_closed_deal(agent["id"], address="60 Feb Ct",
                               gross_commission_cents=500000, closing_date="2026-02-15")
        db = setup_closed_deal(agent["id"], address="61 Mar Ct",
                               gross_commission_cents=500000, closing_date="2026-03-15")
        agent = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        e2 = get_success_data(api.create_enrollment(
            agent["id"], create_enrollment_payload(p2["id"], "2026-03-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        sa = get_success_data(api.settle_deal(da["id"], TEST_USERS["transaction_coordinator_headers"]))
        sb = get_success_data(api.settle_deal(db["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert sa["enrollment_id"] == e1["id"]
        assert sa["company_dollar_cents"] == 141000
        assert sa["agent_net_cents"] == 298000
        assert sa["eo_fee_cents"] == 6000
        assert sb["enrollment_id"] == e2["id"]
        assert sb["company_dollar_cents"] == 117500
        assert sb["agent_net_cents"] == 325500
        assert sb["eo_fee_cents"] == 7000

    def test_retro_activation_supersedes_predecessor_with_effective_to(self, api):
        """PRD §3.3: "An enrollment created with an effective_from on or before
        the clock date activates inline: it is born ACTIVE, and the agent's
        previously ACTIVE enrollment, if any, is superseded — moved to
        SUPERSEDED with its effective_to set to the activating enrollment's
        effective_from."

        Design: Corner/calculations/enrollment_retroactive_effective_date_replans_by_closing_date
        """
        agent = setup_active_agent(joined_at="2026-01-01", name="Retro Rex")
        p1 = setup_active_plan_p1()
        p2 = setup_active_plan_p2()
        e1 = get_success_data(api.create_enrollment(
            agent["id"], create_enrollment_payload(p1["id"], "2026-01-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        agent = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        get_success_data(api.create_enrollment(
            agent["id"], create_enrollment_payload(p2["id"], "2026-03-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        e1_after = get_success_data(api.get_enrollment(e1["id"], TEST_USERS["broker_admin_headers"]))
        assert e1_after["status"] == "SUPERSEDED"
        assert e1_after["effective_to"] == "2026-03-01"


class TestPayoutEstimate:
    def test_estimate_is_provisional_and_read_only(self, api):
        """PRD §3.6: "The estimate runs the identical waterfall against the
        current accumulator and debit-balance state but produces no side effects
        whatsoever: no settlement, no legs, no ledger entries, no accumulator
        mutation. Its response carries a variant field set to PROVISIONAL".

        Design: Corner/calculations/payout_estimate_is_read_only_and_state_gated
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Est Erin")
        deal = get_success_data(api.create_deal(
            create_deal_payload(agent["id"], address="80 Estimate Ave",
                                gross_commission_cents=1000000, closing_date="2026-01-15"),
            TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.submit_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        v_pre = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))["version"]
        est = get_success_data(api.payout_estimate(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert est["variant"] == "PROVISIONAL"
        assert est["agent_net_cents"] == 627000
        v_post = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))["version"]
        assert v_pre == v_post
        settlements = get_success_data(api.list_settlements(
            TEST_USERS["broker_admin_headers"], params={"deal_id": deal["id"]}))
        assert settlements == []

    def test_estimate_rejected_on_fell_through_deal(self, api):
        """PRD §3.6: "a provisional payout estimate is available for a deal in
        DRAFT, PENDING_CLOSING, CLOSED, or SETTLED — asking for it on a
        FELL_THROUGH or VOIDED deal is rejected with ERR_DEAL_INVALID_STATE."

        Design: Corner/calculations/payout_estimate_is_read_only_and_state_gated
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Est Erin")
        deal = get_success_data(api.create_deal(
            create_deal_payload(agent["id"], address="81 Dead End",
                                gross_commission_cents=500000, closing_date="2026-01-16"),
            TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.submit_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.fall_through_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        resp = api.payout_estimate(deal["id"], TEST_USERS["transaction_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_DEAL_INVALID_STATE, expected_status=409)


class TestDealsListStatusFilter:
    def test_status_filter_partitions(self, api):
        """PRD §3.5: "The deal listing supports the filters `agent_id`,
        `referral_agent_id`, and `status`"; §2.3: "Paginated list responses
        carry the fields `limit`, `offset`, `total_count`, and `has_more` in
        the `meta` object of the envelope."

        Design: Corner/entities/deals_list_status_filter_counts
        """
        from test_helpers import validate_paginated
        agent = setup_active_agent(name="Filter Fred")
        da = get_success_data(api.create_deal(
            create_deal_payload(agent["id"], address="1 A Ave", gross_commission_cents=100000,
                                closing_date="2026-01-15"),
            TEST_USERS["transaction_coordinator_headers"]))
        db = get_success_data(api.create_deal(
            create_deal_payload(agent["id"], address="2 B Blvd", gross_commission_cents=200000,
                                closing_date="2026-01-16"),
            TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.submit_deal(db["id"], TEST_USERS["transaction_coordinator_headers"]))
        drafts, meta_d = validate_paginated(api.list_deals(
            TEST_USERS["broker_admin_headers"],
            params={"agent_id": agent["id"], "status": "DRAFT"}))
        assert meta_d["total_count"] == 1
        assert [d["id"] for d in drafts] == [da["id"]]
        pendings, meta_p = validate_paginated(api.list_deals(
            TEST_USERS["broker_admin_headers"],
            params={"agent_id": agent["id"], "status": "PENDING_CLOSING"}))
        assert meta_p["total_count"] == 1
        assert [d["id"] for d in pendings] == [db["id"]]


class TestInitialStates:
    def test_fresh_rows_start_in_declared_initial_states(self, api):
        """PRD §3.1: "A newly created agent starts in `ONBOARDING` status";
        §3.2: "A plan is born in `DRAFT` status"; §3.5: "A deal enters the
        system as a `DRAFT`"; §3.3: "An enrollment created with a future
        `effective_from` instead sits in `SCHEDULED`"; §3.9: "A generated form
        starts in `DRAFT`."

        Design: Corner/state_machines/initial_states_across_entities
        """
        agent = get_success_data(api.create_agent(
            create_agent_payload(full_name="Init Irene", email="ii@x.com",
                                 license_number="LIC-I1", joined_at="2025-09-01"),
            TEST_USERS["broker_admin_headers"]))
        assert agent["status"] == "ONBOARDING"
        agent = get_success_data(api.activate_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        plan = get_success_data(api.create_plan(create_plan_p1_payload(), TEST_USERS["broker_admin_headers"]))
        assert plan["status"] == "DRAFT"
        get_success_data(api.activate_plan(plan["id"], TEST_USERS["broker_admin_headers"]))
        enrollment = get_success_data(api.create_enrollment(
            agent["id"], create_enrollment_payload(plan["id"], "2027-01-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        assert enrollment["status"] == "SCHEDULED"
        deal = get_success_data(api.create_deal(
            create_deal_payload(agent["id"], address="5 Init Ln", gross_commission_cents=100000,
                                closing_date="2026-01-15"),
            TEST_USERS["transaction_coordinator_headers"]))
        assert deal["status"] == "DRAFT"
        form = get_success_data(api.create_tax_form(agent["id"], {"tax_year": 2025},
                                                    TEST_USERS["broker_admin_headers"]))
        assert form["status"] == "DRAFT"

    def test_empty_year_form_has_zero_paid_and_not_required(self, api):
        """PRD §3.9: "filing_required is true exactly when gross_paid_cents
        reaches the reporting threshold of sixty thousand cents" — a year with
        no released compensation reports zero and stays below the bar.

        Design: Corner/state_machines/initial_states_across_entities
        """
        agent = setup_active_agent(name="Init Irene")
        form = get_success_data(api.create_tax_form(agent["id"], {"tax_year": 2025},
                                                    TEST_USERS["broker_admin_headers"]))
        assert form["gross_paid_cents"] == 0
        assert form["filing_required"] is False


class TestErrorEnvelopeShape:
    def test_error_envelope_on_not_found(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with response_type "error" and data carrying
        error_id and message; "The meta object for error responses contains only
        api_request_id and api_request_timestamp."

        Design: Corner/errors/error_envelope_shape_on_not_found
        """
        from test_helpers import NON_EXISTENT_UUID, is_iso8601_timestamp
        resp = api.get_plan(NON_EXISTENT_UUID, TEST_USERS["broker_admin_headers"])
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert body["meta"]["api_request_id"]
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
