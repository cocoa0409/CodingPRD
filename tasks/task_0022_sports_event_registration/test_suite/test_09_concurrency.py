"""Concurrency rules and OCC (PRD §2.5, §2.13)."""
from __future__ import annotations

import pytest

from test_helpers import (
    add_minutes,
    add_seconds,
    advance_clock,
    api_client,
    assert_exactly_one_succeeds,
    assign_assistant_referee,
    assign_head_referee,
    create_referee,
    custody_payload,
    custody_dispatch,
    custody_receive,
    event_in_progress,
    list_matches,
    make_doping_headers,
    make_referee_headers,
    open_doping_sample,
    positive_doping_for,
    run_race,
    setup_single_elim_8_with_complete,
    submit_result_payload,
    TEST_USERS,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# 2.13 — Concurrency rules
# ===========================================================================
class TestConcurrencyRules:
    def test_two_referees_disagreement_keeps_pending(self, api):
        """PRD §2.13: 'Two referees racing to submit cross-verifying
        ResultEntry rows for the same match serialize first-writer-wins on
        the match's transition from SCHEDULED to RESULT_PENDING; the
        second submission whose scores disagree with the first is rejected
        with ERR_RESULT_DISAGREEMENT, the match remains in
        RESULT_PENDING, and no Dispute is auto-opened.'"""
        event, parts, _ = event_in_progress(
            event_type="ROUND_ROBIN",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        match = next(m for m in list_matches(event["id"])
                     if m["round_index"] == 1 and m["status"] != "BYE"
                     and m.get("home_participant_id")
                     and m.get("away_participant_id"))
        head = create_referee(country_code="GR", team_affiliation=None,
                               qualifications=[event["event_type"]])
        asst = create_referee(country_code="HR", team_affiliation=None,
                                qualifications=[event["event_type"]])
        head_asg = assign_head_referee(match["id"], head["id"])
        asst_asg = assign_assistant_referee(match["id"], asst["id"])
        advance_clock(add_seconds(match["scheduled_end_at"], 1))

        def submit_2_1():
            return api_client.submit_result(
                match["id"],
                submit_result_payload(
                    submitted_by_assignment_id=head_asg["id"],
                    home_score=2, away_score=1,
                ),
                make_referee_headers(head["id"]),
            )

        def submit_3_2():
            return api_client.submit_result(
                match["id"],
                submit_result_payload(
                    submitted_by_assignment_id=asst_asg["id"],
                    home_score=3, away_score=2,
                ),
                make_referee_headers(asst["id"]),
            )

        results = run_race(submit_2_1, submit_3_2)
        # PRD §2.13: exactly one survives as the first REFEREE_SUBMISSION;
        # the disagreeing second is rejected with ERR_RESULT_DISAGREEMENT.
        successes = [r for r in results if 200 <= r.status_code < 300]
        failures = [r for r in results if r.status_code >= 400]
        assert len(successes) == 1, (
            "PRD §2.13: first-writer-wins must allow exactly one "
            f"submission; got successes={len(successes)}, "
            f"failures={len(failures)}"
        )
        # The failure must be ERR_RESULT_DISAGREEMENT.
        validate_error_is_one_of(failures[0], ["ERR_RESULT_DISAGREEMENT"])

    def test_chain_of_custody_concurrent_appends_strict_monotonic(self, api):
        """PRD §2.13: 'Two doping officers concurrently appending custody
        rows to the same DopingSample are serialized by strict
        monotonicity on chain_log[].at; the loser whose appended at is
        less than or equal to the prior tail's at receives
        ERR_CHAIN_OF_CUSTODY_BROKEN.'"""
        completed, parts, _ = setup_single_elim_8_with_complete()
        s = open_doping_sample(completed["id"], parts[0]["id"],
                                collected_at="2030-04-01T08:00:00.000Z")

        # Two parallel appends with the SAME at — at most one can be
        # strictly greater than the prior tail (the empty list); the
        # second loses on monotonicity.
        same_at = "2030-04-01T08:30:00.000Z"

        def append_a():
            return api_client.append_custody(
                s["id"],
                custody_payload(action="DISPATCH", at=same_at),
                make_doping_headers("dop-001"),
            )

        def append_b():
            return api_client.append_custody(
                s["id"],
                custody_payload(action="DISPATCH", at=same_at),
                make_doping_headers("dop-002"),
            )

        results = run_race(append_a, append_b)
        # Exactly one append succeeds; the loser is
        # ERR_CHAIN_OF_CUSTODY_BROKEN per PRD §2.13.
        successes = [r for r in results if 200 <= r.status_code < 300]
        failures = [r for r in results if r.status_code >= 400]
        assert len(successes) == 1
        validate_error_is_one_of(failures[0], ["ERR_CHAIN_OF_CUSTODY_BROKEN"])

    def test_two_organizers_complete_same_event_one_wins(self, api,
                                                          organizer_headers,
                                                          organizer_headers_alt):
        """PRD §2.13: 'Two organizers concurrently completing the same
        event are serialized first-writer-wins on the event's transition
        to COMPLETED; the loser receives ERR_INVALID_STATE.'"""
        # Build a COMPLETED-ready event manually so concurrency is around
        # /complete itself. Use a 2-participant SINGLE_ELIM and lock its
        # one round-1 match.
        from test_helpers import (
            event_in_progress, list_matches, lock_match, advance_clock,
        )
        event, parts, matches = event_in_progress(
            event_type="SINGLE_ELIM",
            n_participants=2,
            countries=["FR", "IT"],
            teams=["TFR", "TIT"],
        )
        live = next(m for m in list_matches(event["id"])
                    if m["round_index"] == 1 and m["status"] != "BYE"
                    and m.get("home_participant_id")
                    and m.get("away_participant_id"))
        lock_match(live, home_score=2, away_score=1, event_type="SINGLE_ELIM")

        def complete_a():
            return api_client.complete_event(event["id"], organizer_headers)

        def complete_b():
            return api_client.complete_event(event["id"], organizer_headers_alt)

        results = run_race(complete_a, complete_b)
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # Loser must be ERR_INVALID_STATE per PRD §2.13.
        loser = outcome["failures"][0]
        validate_error_is_one_of(loser, ["ERR_INVALID_STATE"])
