"""Concurrency races and clock-driven transitions.

PRD §2.11 names four first-writer-wins races and their loser error_ids
verbatim. PRD §3.7 names the time-gated transitions fired by
/_clock/advance.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    add_hours_iso,
    add_minutes_iso,
    advance_clock_to,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    award_bid_window,
    build_pairing_with_one_duty_period,
    call_out_reserve_payload,
    create_crew_member,
    crew_role_headers,
    get_pairing,
    iso_from_dt,
    iso_now_utc,
    place_on_reserve,
    publish_pairing,
    run_race,
    scheduler_headers,
    scheduler_headers_alt,
    setup_pairing_admin_assigned,
    setup_pairing_in_bidding,
    submit_bid,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestBidWindowAwardRace:

    def test_concurrent_award_sweeps_serialize_with_already_awarded(self, api):
        """PRD §2.11: "Two CrewScheduler operators racing the bid-window
        awarding sweep on the same window serialize on the
        Pairing.status transition from BIDDING_OPEN to AWARDED;
        whichever sweep commits first wins, and the loser receives
        ERR_BID_WINDOW_ALREADY_AWARDED."
        """
        pilot = create_crew_member(rank="CAPTAIN")
        pairing, bw = setup_pairing_in_bidding(
            required_rank_composition={"CAPTAIN": 1},
        )
        submit_bid(pilot, pairing["id"], bw, preference_rank=1)
        # Race two sweeps.
        results = run_race(
            lambda: api.award_bid_window(bw, scheduler_headers),
            lambda: api.award_bid_window(bw, scheduler_headers_alt),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser_resp = outcome["failures"][0]
        validate_error(
            loser_resp, ApiErrorId.ERR_BID_WINDOW_ALREADY_AWARDED.value,
        )


class TestReserveCalloutRace:

    def test_concurrent_callouts_to_same_slot_serialize(self, api):
        """PRD §2.11: "Two reserve callouts targeting the same vacated
        rank slot on the same pairing serialize on the insertion of an
        Assignment row keyed by (pairing_id, assigned_rank_slot); the
        second writer receives ERR_SLOT_ALREADY_COVERED."
        """
        # Two reserve members, both eligible, same pairing/slot.
        m1 = create_crew_member(rank="CAPTAIN", base_airport="DFW")
        m2 = create_crew_member(rank="CAPTAIN", base_airport="DFW")
        # PRD §2.7 — the logical clock is fixed at server boot. Read the
        # server's now and back up the standby start by one minute so the
        # half-open inclusion check (PRD §3.4: standby_start_at inclusive)
        # is guaranteed to include the impl's get_now() at request time.
        from test_helpers import api_client
        server_now = api_client.clock_now(scheduler_headers).json()["data"]["now"]
        now_iso = add_minutes_iso(server_now, -1)
        end_iso = add_hours_iso(server_now, 12)
        rp1 = place_on_reserve(
            m1["id"], reserve_date=now_iso,
            standby_start_at=now_iso, standby_end_at=end_iso,
        )
        rp2 = place_on_reserve(
            m2["id"], reserve_date=now_iso,
            standby_start_at=now_iso, standby_end_at=end_iso,
        )
        # Build a PUBLISHED pairing with an OPEN CAPTAIN slot — the
        # callouts in this race are the candidates that compete to fill
        # that slot. (No pre-binding via admin_assign.)
        pairing, _, _ = build_pairing_with_one_duty_period(
            base_airport="DFW",
            required_rank_composition={"CAPTAIN": 1},
        )
        publish_pairing(pairing["id"])
        # Race two manual callouts on the same slot.
        results = run_race(
            lambda: api.call_out_reserve(
                rp1["id"],
                call_out_reserve_payload(
                    pairing_id=pairing["id"],
                    assigned_rank_slot="CAPTAIN",
                ),
                scheduler_headers,
            ),
            lambda: api.call_out_reserve(
                rp2["id"],
                call_out_reserve_payload(
                    pairing_id=pairing["id"],
                    assigned_rank_slot="CAPTAIN",
                ),
                scheduler_headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser_resp = outcome["failures"][0]
        validate_error(
            loser_resp, ApiErrorId.ERR_SLOT_ALREADY_COVERED.value,
        )


class TestClockAdvanceLifecycle:

    def test_advance_past_start_at_transitions_pairing_to_in_progress(
        self, api,
    ):
        """PRD §3.6: "When now reaches or exceeds Pairing.start_at and
        all required rank slots have a SCHEDULED assignment, the
        pairing transitions from AWARDED to IN_PROGRESS and every
        SCHEDULED assignment on it transitions to IN_PROGRESS."

        # difficulty: non_linear_state_machine/assignment_branching_release_vs_progress
        """
        pilot = create_crew_member(rank="CAPTAIN")
        start_at = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(hours=48),
        )
        pairing, assignment = setup_pairing_admin_assigned(
            pilot, start_at=start_at, assigned_rank_slot="CAPTAIN",
        )
        # Refresh pairing to read its current start_at (server may
        # normalise the value).
        pairing = get_pairing(pairing["id"])
        # Pairing snapshot will be in AWARDED only after award, but
        # admin-override creates SCHEDULED Assignment without changing
        # pairing.status. The clock-driven transition wording in
        # PRD §3.6 keys on (start_at, all required slots SCHEDULED) →
        # advancing the clock should land the assignment in IN_PROGRESS.
        advance_clock_to(add_minutes_iso(pairing["start_at"], 1))
        from test_helpers import get_assignment
        a = get_assignment(assignment["id"])
        # PRD §3.6 commits Assignment SCHEDULED -> IN_PROGRESS when
        # Pairing crosses start_at.
        assert a["status"] == "IN_PROGRESS"

    def test_advance_past_end_at_transitions_to_completed_and_computes_credit(
        self, api,
    ):
        """PRD §3.6: "When now reaches or exceeds Pairing.end_at, the
        pairing transitions from IN_PROGRESS to CLOSED, every
        IN_PROGRESS assignment on it transitions to COMPLETED, and for
        each completed assignment the system computes
        actual_block_minutes ... and then runs the pay-credit
        calculation."
        """
        pilot = create_crew_member(rank="CAPTAIN")
        start_at = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(hours=48),
        )
        pairing, assignment = setup_pairing_admin_assigned(
            pilot, start_at=start_at, assigned_rank_slot="CAPTAIN",
            revenue_block_minutes=300, duty_minutes=480,
        )
        pairing = get_pairing(pairing["id"])
        # Cross start, then cross end.
        advance_clock_to(add_minutes_iso(pairing["start_at"], 1))
        advance_clock_to(add_minutes_iso(pairing["end_at"], 1))
        from test_helpers import get_assignment
        a = get_assignment(assignment["id"])
        assert a["status"] == "COMPLETED"
        assert a["pay_credit_minutes"] > 0, (
            "PRD §3.6: pay-credit calculation runs on completion."
        )
