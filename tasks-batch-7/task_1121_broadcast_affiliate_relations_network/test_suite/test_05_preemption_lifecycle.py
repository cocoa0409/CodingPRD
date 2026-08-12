"""Preemption request lifecycle: state machine, counter rounds, quota.

Covers the difficulty preemption_counter_cycle instance, several corner
state-machine entries, and the cross-entity dependency on agreement state.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    create_agreement_payload,
    create_preemption_payload,
    get_success_data,
    make_nar_headers,
    make_platform_admin_headers,
    make_station_group_owner_headers,
    setup_basic_scenario,
    setup_clock,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import (
    create_draft_agreement,
    create_preemption_request,
    create_program,
)


class TestPreemptionCounterCycle:
    def test_three_counter_rounds_then_exhausted(self, api):
        """PRD §3.3: "Resubmission is capped — when `counter_round_count` has
        already reached 3, the resubmit is rejected with
        `ERR_COUNTER_ROUND_EXHAUSTED` (HTTP 409), preventing endless volleys."

        Design: Difficulty/non_linear_state_machine/preemption_counter_cycle
        """
        scenario = setup_basic_scenario(clock_iso="2026-05-15T00:00:00Z")
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        program = create_program(
            nid,
            avail_minutes_total=30,
            avail_minutes_local_allocatable=10,
            is_syndicated=True,
            scheduled_start_utc="2026-06-01T20:00:00Z",
            scheduled_end_utc="2026-06-01T22:00:00Z",
        )
        pr = create_preemption_request(
            nid, sid, program["id"], scenario["agreement"]["id"], sgo,
            requested_start_utc="2026-06-01T20:00:00Z",
            requested_end_utc="2026-06-01T22:00:00Z",
        )

        # Three counter/resubmit cycles.
        counters = [
            ("2026-06-01T21:00:00Z", "2026-06-01T22:00:00Z"),
            ("2026-06-01T21:30:00Z", "2026-06-01T22:00:00Z"),
            ("2026-06-01T21:45:00Z", "2026-06-01T22:00:00Z"),
        ]
        last = None
        for cs, ce in counters:
            get_success_data(api.begin_review_preemption(nid, sid, pr["id"], nar))
            get_success_data(
                api.counter_preemption(
                    nid, sid, pr["id"],
                    {"counter_start_utc": cs, "counter_end_utc": ce},
                    nar,
                )
            )
            last = get_success_data(api.resubmit_preemption(nid, sid, pr["id"], sgo))
        # After three rounds, counter_round_count == 3.
        assert last["counter_round_count"] == 3, (
            f"After three resubmits counter_round_count must be 3; got "
            f"{last['counter_round_count']!r}"
        )
        # Fourth cycle: begin-review, counter, then resubmit must fail.
        get_success_data(api.begin_review_preemption(nid, sid, pr["id"], nar))
        get_success_data(
            api.counter_preemption(
                nid, sid, pr["id"],
                {"counter_start_utc": "2026-06-01T21:50:00Z",
                 "counter_end_utc": "2026-06-01T22:00:00Z"},
                nar,
            )
        )
        resp = api.resubmit_preemption(nid, sid, pr["id"], sgo)
        validate_error(resp, ApiErrorId.ERR_COUNTER_ROUND_EXHAUSTED)

    def test_counter_window_becomes_requested_window_on_resubmit(self, api):
        """PRD §3.3: "the requested window is updated to the counter window
        (`requested_start_utc` becomes `counter_start_utc`, `requested_end_utc`
        becomes `counter_end_utc`), `counter_round_count` increments by 1".

        Design: Difficulty/non_linear_state_machine/preemption_counter_cycle
        """
        scenario = setup_basic_scenario(clock_iso="2026-05-15T00:00:00Z")
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        program = create_program(
            nid,
            avail_minutes_total=30,
            avail_minutes_local_allocatable=10,
            is_syndicated=True,
            scheduled_start_utc="2026-06-01T20:00:00Z",
            scheduled_end_utc="2026-06-01T22:00:00Z",
        )
        pr = create_preemption_request(
            nid, sid, program["id"], scenario["agreement"]["id"], sgo,
            requested_start_utc="2026-06-01T20:00:00Z",
            requested_end_utc="2026-06-01T22:00:00Z",
        )
        get_success_data(api.begin_review_preemption(nid, sid, pr["id"], nar))
        get_success_data(
            api.counter_preemption(
                nid, sid, pr["id"],
                {"counter_start_utc": "2026-06-01T21:00:00Z",
                 "counter_end_utc": "2026-06-01T22:00:00Z"},
                nar,
            )
        )
        resub = get_success_data(api.resubmit_preemption(nid, sid, pr["id"], sgo))
        assert resub["counter_round_count"] == 1
        assert resub["requested_start_utc"] == "2026-06-01T21:00:00Z", (
            f"After resubmit the requested window must equal the prior counter; "
            f"got {resub['requested_start_utc']!r}"
        )
        assert resub["requested_end_utc"] == "2026-06-01T22:00:00Z"


class TestCrossEntityDependencySecondWitness:
    def test_begin_review_blocked_when_agreement_terminated(self, api):
        """PRD §3.3: "The referenced agreement must be in `ACTIVE` or
        `EXPIRING` at this point; a request filed against an agreement that
        has lapsed or terminated cannot enter review."

        Design: Difficulty/cross_entity_state_dependency/preemption_approve_depends_on_agreement_active
        """
        scenario = setup_basic_scenario(clock_iso="2026-05-10T00:00:00Z")
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        nar = scenario["nar_headers"]
        program = create_program(
            nid, avail_minutes_total=10, avail_minutes_local_allocatable=5,
            is_syndicated=False,
        )
        # Create the preemption while the agreement is ACTIVE.
        pr = create_preemption_request(
            nid, sid, program["id"], scenario["agreement"]["id"], sgo,
        )
        # Terminate the agreement (allowed because no DRAFT settlements).
        get_success_data(
            api_client.terminate_agreement(
                nid, sid, scenario["agreement"]["id"], nar
            )
        )
        # Now begin-review must fail because the agreement is TERMINATED.
        resp = api_client.begin_review_preemption(nid, sid, pr["id"], nar)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPreemptionWithdraw:
    def test_withdraw_from_submitted_works(self, api):
        """PRD §3.3: "a request in `SUBMITTED` may also be withdrawn
        directly."

        Design: Corner/state_machines/preemption_withdraw_from_submitted_works
        """
        scenario = setup_basic_scenario(clock_iso="2026-05-15T00:00:00Z")
        nid = scenario["network"]["id"]
        sid = scenario["station"]["id"]
        sgo = scenario["sgo_headers"]
        program = create_program(nid, avail_minutes_total=10,
                                 avail_minutes_local_allocatable=5,
                                 is_syndicated=False)
        pr = create_preemption_request(
            nid, sid, program["id"], scenario["agreement"]["id"], sgo,
            requested_start_utc="2026-06-01T20:00:00Z",
            requested_end_utc="2026-06-01T21:00:00Z",
        )
        resp = api.withdraw_preemption(nid, sid, pr["id"], sgo)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "WITHDRAWN", (
            f"SUBMITTED -> WITHDRAWN must succeed; got {data['status']!r}"
        )


class TestCrossEntityDependency:
    def test_begin_review_blocked_when_agreement_not_active(self, api):
        """PRD §3.3: "The referenced agreement must be in `ACTIVE` or
        `EXPIRING` at this point; a request filed against an agreement that
        has lapsed or terminated cannot enter review."

        Design: Difficulty/cross_entity_state_dependency/preemption_approve_depends_on_agreement_active
        """
        setup_clock("2026-05-10T00:00:00Z")
        admin = make_platform_admin_headers()
        nar = make_nar_headers()
        from test_helpers import (
            create_network_payload, create_station_group_payload,
            create_station_payload,
        )
        net = get_success_data(api.create_network(create_network_payload(), admin))
        grp = get_success_data(api.create_station_group(create_station_group_payload(), admin))
        sgo = make_station_group_owner_headers(grp["id"])
        station = get_success_data(
            api.create_station(
                net["id"], create_station_payload(station_group_id=grp["id"]), nar
            )
        )
        program = create_program(
            net["id"], avail_minutes_total=10, avail_minutes_local_allocatable=5,
            is_syndicated=False,
        )
        # Draft agreement — never submitted/activated.
        agreement = create_draft_agreement(net["id"], station["id"])
        pr = create_preemption_request(
            net["id"], station["id"], program["id"], agreement["id"], sgo,
            requested_start_utc="2026-06-01T20:00:00Z",
            requested_end_utc="2026-06-01T21:00:00Z",
        )
        resp = api.begin_review_preemption(net["id"], station["id"], pr["id"], nar)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
