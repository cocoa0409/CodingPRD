"""Non-linear state machine tests: the request negotiation cycle
SUBMITTED -> COUNTERED -> SUBMITTED and the crew readiness cycle
CLEARED_TO_WORK -> SAFETY_HOLD -> BRIEFED -> CLEARED_TO_WORK (PRD §3.3, §3.5)."""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    make_program_admin_headers, make_host_coordinator_headers,
    make_responding_coordinator_headers, make_crew_supervisor_headers,
    make_host_safety_officer_headers,
    set_clock, create_company, create_event, create_and_publish_schedule,
    create_request, create_accepted_request, commit_crew,
    conduct_and_acknowledge_briefing, arrive_crew, create_submitted_timesheet,
    setup_event_active, setup_event_with_accepted_request,
    setup_cleared_arrived_crew,
    create_safety_briefing_payload, create_assistance_request_payload,
)


class TestAssistanceRequestCounterAmendCycle:
    def _setup_draft_request(self):
        set_clock("2026-05-01T08:00:00Z")
        host, rsp, event = setup_event_active(set_clock_first=False)
        request = create_request(event["id"], host["id"], rsp["id"], submit=False)
        return host, rsp, event, request

    def test_two_full_counter_cycles_increment_amendment_round(self):
        """PRD §3.3: "The host answers a counter by resubmitting with amended
        terms: resubmission from `COUNTERED` requires `amended_crews` in the
        payload — its absence is an `ERR_INVALID_REQUEST` — and replaces
        `requested_crews` with the amendment, replaces `required_minimum_crews`
        when `amended_required_minimum` is present, and increments
        `amendment_round` by one. The `SUBMITTED` to `COUNTERED` to `SUBMITTED`
        cycle may repeat without bound, with `amendment_round` tracking the
        rounds."

        Design: Difficulty/non_linear_state_machine/assistance_request_counter_amend_cycle
        """
        host, rsp, event, request = self._setup_draft_request()
        rid = request["id"]
        resp = api_client.submit_assistance_request(rid, {}, make_host_coordinator_headers(host["id"]))
        validate_success(resp)
        resp = api_client.counter_assistance_request(
            rid, {"counter_crews": [{"crew_type": "LINE", "count": 1}],
                  "counter_note": "only one crew available"},
            make_responding_coordinator_headers(rsp["id"]))
        validate_success(resp)
        resp = api_client.submit_assistance_request(
            rid, {"amended_crews": [{"crew_type": "LINE", "count": 1},
                                    {"crew_type": "TREE", "count": 1}]},
            make_host_coordinator_headers(host["id"]))
        req = validate_success(resp)
        assert req["amendment_round"] == 1
        resp = api_client.counter_assistance_request(
            rid, {"counter_crews": [{"crew_type": "TREE", "count": 2}],
                  "counter_note": "tree-heavy mix"},
            make_responding_coordinator_headers(rsp["id"]))
        validate_success(resp)
        resp = api_client.submit_assistance_request(
            rid, {"amended_crews": [{"crew_type": "TREE", "count": 2}]},
            make_host_coordinator_headers(host["id"]))
        req = validate_success(resp)
        assert req["status"] == "SUBMITTED"
        assert req["amendment_round"] == 2

    def test_latest_counter_terms_and_amended_crews_replace_earlier(self):
        """PRD §3.3: "The responding utility's `RespondingCoordinator`, scoped
        to the request's `responding_utility_id`, may counter, moving `SUBMITTED`
        to `COUNTERED` and recording the supplied `counter_crews` and optional
        `counter_note` into the request's `counter_terms`." PRD §3.3: "replaces
        `requested_crews` with the amendment"

        Design: Difficulty/non_linear_state_machine/assistance_request_counter_amend_cycle
        """
        host, rsp, event, request = self._setup_draft_request()
        rid = request["id"]
        api_client.submit_assistance_request(rid, {}, make_host_coordinator_headers(host["id"]))
        api_client.counter_assistance_request(
            rid, {"counter_crews": [{"crew_type": "LINE", "count": 1}],
                  "counter_note": "first note"},
            make_responding_coordinator_headers(rsp["id"]))
        api_client.submit_assistance_request(
            rid, {"amended_crews": [{"crew_type": "LINE", "count": 1}]},
            make_host_coordinator_headers(host["id"]))
        api_client.counter_assistance_request(
            rid, {"counter_crews": [{"crew_type": "TREE", "count": 2}],
                  "counter_note": "tree-heavy mix"},
            make_responding_coordinator_headers(rsp["id"]))
        resp = api_client.submit_assistance_request(
            rid, {"amended_crews": [{"crew_type": "TREE", "count": 2}]},
            make_host_coordinator_headers(host["id"]))
        req = validate_success(resp)
        assert req["counter_terms"]["counter_note"] == "tree-heavy mix"
        assert req["requested_crews"] == [{"crew_type": "TREE", "count": 2}]


class TestCrewReadinessCycleViaRebriefing:
    def _setup_held_scenario(self):
        ctx = setup_cleared_arrived_crew(clock_after_arrival="2026-05-05T09:00:00Z")
        ts = create_submitted_timesheet(ctx["crew"]["id"], work_date="2026-05-04",
                                        day_classification="WORK", reported_work_minutes=480)
        resp = api_client.suspend_crew(
            ctx["crew"]["id"], {"reason": "PPE violation"},
            make_host_safety_officer_headers(ctx["host"]["id"]))
        assert resp.status_code == 200, f"Setup failed suspending crew: {resp.text}"
        ctx["ts"] = ts
        return ctx

    def test_suspension_then_rebriefing_restores_cleared_readiness(self):
        """PRD §3.5: "a crew under `SAFETY_HOLD` moves to `BRIEFED` only when
        the briefing's `conducted_at` is later than the crew's
        `last_suspended_at`" PRD §3.5: "A clean acknowledgment records
        `acknowledged_at`, moves the briefing from `CONDUCTED` to `ACKNOWLEDGED`,
        and advances the crew from `BRIEFED` to `CLEARED_TO_WORK`."

        Design: Difficulty/non_linear_state_machine/crew_readiness_cycle_via_rebriefing
        """
        ctx = self._setup_held_scenario()
        crew_id, event_id, host_id = ctx["crew"]["id"], ctx["event"]["id"], ctx["host"]["id"]
        # Suspended: readiness must be SAFETY_HOLD
        resp = api_client.get_crew(crew_id, make_program_admin_headers())
        assert validate_success(resp)["readiness_status"] == "SAFETY_HOLD"
        set_clock("2026-05-05T10:00:00Z")
        briefing = conduct_and_acknowledge_briefing(
            crew_id, event_id, host_id, conductor_ref="OFF-2",
            host_rules_version="HR-2026.2", topics=["grounding", "PPE"])
        resp = api_client.get_crew(crew_id, make_program_admin_headers())
        crew = validate_success(resp)
        assert crew["readiness_status"] == "CLEARED_TO_WORK"
        assert crew["last_suspended_at"] is not None

    def test_mobility_stays_arrived_and_held_timesheet_returns_to_submitted(self):
        """PRD §3.5: "The two status dimensions then evolve independently — a
        suspended crew may still travel, arrive, or be released" PRD §3.5: "When
        the crew had been returning from a hold, the same acknowledgment fires
        the hold-release cascade: the crew's `HELD` timesheets and `HELD`
        per-diem claims return to `SUBMITTED`"

        Design: Difficulty/non_linear_state_machine/crew_readiness_cycle_via_rebriefing
        """
        ctx = self._setup_held_scenario()
        crew_id, event_id, host_id = ctx["crew"]["id"], ctx["event"]["id"], ctx["host"]["id"]
        ts_id = ctx["ts"]["id"]
        resp = api_client.get_timesheet(ts_id, make_program_admin_headers())
        assert validate_success(resp)["status"] == "HELD", (
            "the crew's SUBMITTED timesheet must be parked in HELD by the suspension"
        )
        resp = api_client.get_crew(crew_id, make_program_admin_headers())
        assert validate_success(resp)["mobility_status"] == "ARRIVED"
        set_clock("2026-05-05T10:00:00Z")
        conduct_and_acknowledge_briefing(
            crew_id, event_id, host_id, conductor_ref="OFF-2",
            host_rules_version="HR-2026.2", topics=["grounding", "PPE"])
        resp = api_client.get_timesheet(ts_id, make_program_admin_headers())
        assert validate_success(resp)["status"] == "SUBMITTED"
        resp = api_client.get_crew(crew_id, make_program_admin_headers())
        assert validate_success(resp)["mobility_status"] == "ARRIVED"
