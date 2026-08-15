"""Plan enrollments, effective dating, anniversary windows, clock sweep (PRD §3.3, §3.4, §2.4)."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, validate_success, validate_error, get_success_data,
    ApiErrorId, create_agent_payload, create_enrollment_payload,
    setup_active_agent, setup_active_plan_p1, setup_active_plan_p2,
    setup_agent_on_plan, setup_closed_deal, setup_settled_deal,
    get_window_for_agent,
)


class TestEnrollmentImmediateVsScheduled:
    def test_past_effective_from_activates_inline(self, api):
        """PRD §3.3: "An enrollment created with an effective_from on or before
        the clock date activates inline: it is born ACTIVE."

        Design: Corner/state_machines/enrollment_immediate_vs_scheduled_activation
        """
        agent = setup_active_agent(name="Eff Eddie")
        p1 = setup_active_plan_p1()
        e1 = get_success_data(api.create_enrollment(
            agent["id"],
            create_enrollment_payload(p1["id"], "2025-09-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        assert e1["status"] == "ACTIVE"

    def test_future_effective_from_parks_scheduled_and_leaves_current_untouched(self, api):
        """PRD §3.3: "An enrollment created with a future effective_from instead
        sits in SCHEDULED with effective_to null — open-ended — until time
        catches up."

        Design: Corner/state_machines/enrollment_immediate_vs_scheduled_activation
        """
        agent = setup_active_agent(name="Eff Eddie")
        p1 = setup_active_plan_p1()
        p2 = setup_active_plan_p2()
        e1 = get_success_data(api.create_enrollment(
            agent["id"],
            create_enrollment_payload(p1["id"], "2025-09-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        agent = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        e2 = get_success_data(api.create_enrollment(
            agent["id"],
            create_enrollment_payload(p2["id"], "2027-01-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        assert e2["status"] == "SCHEDULED"
        e1_after = get_success_data(api.get_enrollment(e1["id"], TEST_USERS["broker_admin_headers"]))
        assert e1_after["status"] == "ACTIVE"
        assert e1_after["effective_to"] is None


class TestEnrollmentOverlapRejected:
    def test_same_effective_from_rejected_as_regression(self, api):
        """PRD §3.3: "the new effective_from must be strictly after the
        effective_from of the agent's current ACTIVE or SCHEDULED enrollment,
        with no overlap and no back-dating over the current plan; a violation is
        ERR_EFFECTIVE_DATE_REGRESSION (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/enrollment_window_overlap_rejected_adjacency_allowed
        """
        agent = setup_active_agent(name="Overlap Owen")
        p1 = setup_active_plan_p1()
        p2 = setup_active_plan_p2()
        e1 = get_success_data(api.create_enrollment(
            agent["id"],
            create_enrollment_payload(p1["id"], "2025-09-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        agent = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        resp = api.create_enrollment(
            agent["id"],
            create_enrollment_payload(p2["id"], "2025-09-01", agent["version"]),
            TEST_USERS["broker_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_EFFECTIVE_DATE_REGRESSION, expected_status=422)
        # E1 untouched
        e1_after = get_success_data(api.get_enrollment(e1["id"], TEST_USERS["broker_admin_headers"]))
        assert e1_after["status"] == "ACTIVE"

    def test_strictly_later_future_effective_from_is_allowed(self, api):
        """PRD §3.3: "An enrollment created with a future `effective_from`
        instead sits in `SCHEDULED` with `effective_to` null — open-ended —
        until time catches up."

        Design: Difficulty/resource_temporal_overlap/enrollment_window_overlap_rejected_adjacency_allowed
        """
        agent = setup_active_agent(name="Overlap Owen")
        p1 = setup_active_plan_p1()
        p2 = setup_active_plan_p2()
        get_success_data(api.create_enrollment(
            agent["id"],
            create_enrollment_payload(p1["id"], "2025-09-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        agent = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        e2 = get_success_data(api.create_enrollment(
            agent["id"],
            create_enrollment_payload(p2["id"], "2026-09-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        assert e2["status"] == "SCHEDULED"


class TestClockSweepCascade:
    def test_sweep_activates_scheduled_and_supersedes_current(self, api):
        """PRD §3.3: "When the advancing clock reaches a SCHEDULED enrollment's
        effective_from, the sweep activates it with the identical supersede
        cascade on the agent's previously ACTIVE enrollment." PRD §2.4: the
        response reports "the list activated_enrollment_ids".

        Design: Difficulty/transitive_cascade/clock_sweep_activates_scheduled_and_supersedes_current
        """
        agent = setup_active_agent(name="Sweep Sam")
        p1 = setup_active_plan_p1()
        p2 = setup_active_plan_p2()
        e1 = get_success_data(api.create_enrollment(
            agent["id"],
            create_enrollment_payload(p1["id"], "2025-09-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        agent = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        e2 = get_success_data(api.create_enrollment(
            agent["id"],
            create_enrollment_payload(p2["id"], "2026-09-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        assert e2["status"] == "SCHEDULED"
        sweep = get_success_data(api.set_clock({"to_iso8601": "2026-09-15T00:00:00Z"},
                                               TEST_USERS["broker_admin_headers"]))
        assert e2["id"] in sweep["activated_enrollment_ids"]
        e1_after = get_success_data(api.get_enrollment(e1["id"], TEST_USERS["broker_admin_headers"]))
        assert e1_after["status"] == "SUPERSEDED"
        assert e1_after["effective_to"] == "2026-09-01"
        e2_after = get_success_data(api.get_enrollment(e2["id"], TEST_USERS["broker_admin_headers"]))
        assert e2_after["status"] == "ACTIVE"

    def test_supersede_sets_effective_to_to_new_effective_from(self, api):
        """PRD §3.3: "the agent's previously ACTIVE enrollment, if any, is
        superseded — moved to SUPERSEDED with its effective_to set to the
        activating enrollment's effective_from."

        Design: Difficulty/transitive_cascade/clock_sweep_activates_scheduled_and_supersedes_current
        """
        agent = setup_active_agent(name="Sweep Sam")
        p1 = setup_active_plan_p1()
        p2 = setup_active_plan_p2()
        e1 = get_success_data(api.create_enrollment(
            agent["id"],
            create_enrollment_payload(p1["id"], "2025-09-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        agent = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        e2 = get_success_data(api.create_enrollment(
            agent["id"],
            create_enrollment_payload(p2["id"], "2026-09-01", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        api.set_clock({"to_iso8601": "2026-09-15T00:00:00Z"}, TEST_USERS["broker_admin_headers"])
        e1_after = get_success_data(api.get_enrollment(e1["id"], TEST_USERS["broker_admin_headers"]))
        assert e1_after["status"] == "SUPERSEDED"
        assert e1_after["effective_to"] == "2026-09-01"


class TestAnniversaryWindowSweep:
    def test_window_closes_and_next_window_materializes(self, api):
        """PRD §3.4: "A window is OPEN until the books close: when the clock date
        reaches or passes window_end, the sweep moves the window to CLOSED" and
        "the clock sweep materializes every window from each non-ONBOARDING
        agent's join date through the window containing the new clock date."

        Design: Corner/state_machines/window_sweep_materializes_and_closes_windows
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Sweep Wanda")
        # Small deal accrued into window 0: company 28200 (gross 100000:
        # royalty 6000, after_royalty 94000, company 28200)
        setup_settled_deal(agent["id"], gross_commission_cents=100000, closing_date="2026-01-15")
        w0_before = get_window_for_agent(agent["id"], 0)
        sweep = get_success_data(api.set_clock({"to_iso8601": "2026-09-15T00:00:00Z"},
                                               TEST_USERS["broker_admin_headers"]))
        assert w0_before["id"] in sweep["closed_window_ids"]
        windows = get_success_data(api.list_anniversary_periods(
            TEST_USERS["broker_admin_headers"], params={"agent_id": agent["id"]}))
        assert windows[0]["status"] == "CLOSED"
        assert windows[0]["company_dollar_accrued_cents"] == 28200
        assert windows[1]["status"] == "OPEN"
        assert windows[1]["window_start"] == "2026-09-01"

    def test_window_accumulators_survive_closure(self, api):
        """PRD §3.4: "Each window carries two accumulators, both starting at 0:
        company_dollar_accrued_cents, fed by posted settlements with the company
        dollar each produced" — closure does not erase accrued figures.

        Design: Corner/state_machines/window_sweep_materializes_and_closes_windows
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Sweep Wanda")
        setup_settled_deal(agent["id"], gross_commission_cents=100000, closing_date="2026-01-15")
        api.set_clock({"to_iso8601": "2026-09-15T00:00:00Z"}, TEST_USERS["broker_admin_headers"])
        w0 = get_window_for_agent(agent["id"], 0)
        assert w0["status"] == "CLOSED"
        assert w0["company_dollar_accrued_cents"] == 28200
        assert w0["royalty_accrued_cents"] == 6000


class TestClosedWindowRejection:
    def test_settle_into_closed_window_rejected(self, api):
        """PRD §3.4: "Settling a deal whose closing date falls in a CLOSED window
        is rejected with ERR_WINDOW_CLOSED (HTTP 409) — the books for that
        anniversary year are final."

        Design: Difficulty/resource_temporal_overlap/anniversary_window_exact_tiling_and_closed_window_rejection
        """
        agent = setup_active_agent(joined_at="2025-03-10", name="Window Wanda")
        plan = setup_active_plan_p1(mentor_split_pct=0.0, mentor_deal_count=0)
        get_success_data(api.create_enrollment(
            agent["id"],
            create_enrollment_payload(plan["id"], "2025-03-10", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        deal = get_success_data(api.create_deal(
            {"agent_id": agent["id"], "address": "12 Retro Rd",
             "gross_commission_cents": 500000, "closing_date": "2025-03-15"},
            TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.submit_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.close_deal(deal["id"], {"actual_closing_date": "2025-03-15"},
                                        TEST_USERS["transaction_coordinator_headers"]))
        # Advance the clock past window 0's end (2026-03-10); window 0 closes.
        get_success_data(api.set_clock({"to_iso8601": "2027-01-01T00:00:00Z"},
                                       TEST_USERS["broker_admin_headers"]))
        resp = api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_WINDOW_CLOSED, expected_status=409)

    def test_windows_tile_exactly_and_window_end_is_exclusive(self, api):
        """PRD §3.4: "Windows are half-open: a date belongs to the window whose
        start is on or before it and whose end is strictly after it, so a
        closing date exactly equal to a window_end belongs to the next window.
        By construction the windows tile the agent's timeline exactly — no gaps,
        no overlaps."

        Design: Difficulty/resource_temporal_overlap/anniversary_window_exact_tiling_and_closed_window_rejection
        """
        agent = setup_active_agent(joined_at="2025-03-10", name="Window Wanda")
        plan = setup_active_plan_p1(mentor_split_pct=0.0, mentor_deal_count=0)
        get_success_data(api.create_enrollment(
            agent["id"],
            create_enrollment_payload(plan["id"], "2025-03-10", agent["version"]),
            TEST_USERS["broker_admin_headers"]))
        # Advance the clock so the sweep materializes windows 0 and 1.
        get_success_data(api.set_clock({"to_iso8601": "2027-01-01T00:00:00Z"},
                                       TEST_USERS["broker_admin_headers"]))
        windows = get_success_data(api.list_anniversary_periods(
            TEST_USERS["broker_admin_headers"], params={"agent_id": agent["id"]}))
        assert windows[0]["window_start"] == "2025-03-10"
        assert windows[0]["window_end"] == "2026-03-10"
        assert windows[1]["window_start"] == "2026-03-10"
        assert windows[1]["window_end"] == "2027-03-10"
