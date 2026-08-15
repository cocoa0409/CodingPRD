"""Meet records: standing-record uniqueness, the strictly-faster challenge
boundary, challenge ratification/rejection, and the finalization gates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_entry,
    add_event,
    add_swimmer,
    add_team,
    complete_event_with_times,
    create_meet,
    create_open_meet,
    create_standing_record,
    get_success_data,
    lane_for_entry,
    seed_meet,
    setup_deck_coverage,
    setup_in_progress_event,
    start_event,
    submit_clean_readings,
    validate_error,
    validate_success,
    verify_entry,
)

DIRECTOR = TEST_USERS["meet_director_headers"]
RECORDS = TEST_USERS["records_officer_headers"]


def _two_event_meet_with_records(api):
    """Meet with M and F 50 Free events, each holding a standing record of
    2450; returns (meet, team, ev_m, ev_f, sw_m, sw_f)."""
    meet = create_open_meet(meet_name="RC1")
    team = add_team(meet["id"])
    sw_m = add_swimmer(team["id"], full_name="Sw M", birth_date="2014-03-10",
                       gender="M")
    sw_f = add_swimmer(team["id"], full_name="Sw F", birth_date="2014-04-11",
                       gender="F")
    ev_m = add_event(meet["id"], event_number=1, gender="M",
                     qualifying_time_cs=3000, scheduled_start_minute=540,
                     scheduled_end_minute=570)
    ev_f = add_event(meet["id"], event_number=2, gender="F",
                     qualifying_time_cs=3000, scheduled_start_minute=570,
                     scheduled_end_minute=600)
    create_standing_record(ev_m["id"], record_time_cs=2450,
                           holder_name="Old Boy")
    create_standing_record(ev_f["id"], record_time_cs=2450,
                           holder_name="Old Girl")
    return meet, team, ev_m, ev_f, sw_m, sw_f


def _race_and_publish(api, meet, event, swimmer, team, pad_cs,
                      coverage_prefix):
    """Enter, verify, cover, race and publish one event (meet already SEEDED
    for the first caller; this helper seeds on its own when needed)."""
    entry = add_entry(event["id"], swimmer["id"], team["id"],
                      seed_time_cs=2480)
    verify_entry(entry["id"])
    coverage = setup_deck_coverage(event["id"], meet["id"],
                                   lsc_prefix=coverage_prefix)
    return entry, coverage


class TestStandingRecordRules:
    def test_ratify_from_current_rejected(self, api):
        """PRD §3.9: "Challenges follow `PENDING_VERIFICATION` → `SUBMITTED` on
        verification, and `SUBMITTED` → `CURRENT` on ratification" and "a
        record transition attempted from a posture that forbids it fails with
        `ERR_RECORD_INVALID_STATE`."

        Design: Corner/errors/record_ratify_from_current_returns_invalid_state
        """
        meet = create_open_meet(meet_name="RE1")
        event = add_event(meet["id"])
        record = create_standing_record(event["id"], record_time_cs=2450,
                                        holder_name="Old")
        assert record["status"] == "CURRENT"
        resp = api.ratify_record(record["id"], RECORDS)
        validate_error(resp, ApiErrorId.ERR_RECORD_INVALID_STATE)

    def test_second_standing_record_rejected(self, api):
        """PRD §3.9: "A standing record is created explicitly against an event
        with `record_time_cs`, `holder_name`, `holder_team`, and `set_on_date`,
        and is born `CURRENT` — but only while no `CURRENT` record exists for
        that event, or the creation fails with `ERR_RECORD_STANDING_EXISTS`."

        Design: Corner/errors/standing_record_uniqueness_rejected
        """
        meet = create_open_meet(meet_name="RE2")
        event = add_event(meet["id"])
        create_standing_record(event["id"], record_time_cs=2450,
                               holder_name="Old")
        resp = api.create_standing_record(
            event["id"],
            {"record_time_cs": 2440, "holder_name": "New",
             "holder_team": "NEW", "set_on_date": "2026-01-01"},
            RECORDS)
        validate_error(resp, ApiErrorId.ERR_RECORD_STANDING_EXISTS)


class TestRecordChallengeBoundary:
    def test_equal_does_not_break_faster_does(self, api):
        """PRD §3.9: "Challengers are the event's `OFFICIAL`, non-`DQ_EXCLUDED`
        results whose `final_time_cs` is strictly faster than the standing
        record's `record_time_cs`; a time exactly equal to the record does not
        break it. When a standing record exists and at least one challenger
        beats it, publication auto-creates exactly one MeetRecord in
        `PENDING_VERIFICATION`: its `record_time_cs` is the fastest challenger
        time, its holder is that result's swimmer `full_name` or relay
        display, its `holder_team` is the club's `team_code`, its `set_on_date`
        is the event's `session_date`, and its `challenger_entry_id` points at
        the challenging entry."

        Design: Corner/calculations/record_challenge_strictly_faster_boundary
        """
        meet, team, ev_m, ev_f, sw_m, sw_f = \
            _two_event_meet_with_records(api)
        en_m, cov_m = _race_and_publish(api, meet, ev_m, sw_m, team, 2450,
                                        "LSC-M")
        en_f, cov_f = _race_and_publish(api, meet, ev_f, sw_f, team, 2449,
                                        "LSC-F")
        seed_meet(meet["id"])

        # Event M: the winner equals the standing record (2450 == 2450).
        started_m = start_event(ev_m["id"])
        submit_clean_readings(lane_for_entry(en_m["id"])["id"], 2450)
        validate_success(api.complete_event(ev_m["id"], started_m["version"],
                                            DIRECTOR))
        validate_success(api.publish_event(ev_m["id"], DIRECTOR))

        # Event F: the winner finishes one centisecond faster (2449 < 2450).
        started_f = start_event(ev_f["id"])
        submit_clean_readings(lane_for_entry(en_f["id"])["id"], 2449)
        validate_success(api.complete_event(ev_f["id"], started_f["version"],
                                            DIRECTOR))
        validate_success(api.publish_event(ev_f["id"], DIRECTOR))

        recs_m = get_success_data(
            api.list_event_records(ev_m["id"], DIRECTOR))
        assert len(recs_m) == 1, "equality does not break a record"
        assert recs_m[0]["status"] == "CURRENT"
        assert recs_m[0]["record_time_cs"] == 2450

        recs_f = get_success_data(
            api.list_event_records(ev_f["id"], DIRECTOR))
        assert len(recs_f) == 2, "one standing record plus one challenge"
        challenges = [r for r in recs_f if r["status"] == "PENDING_VERIFICATION"]
        assert len(challenges) == 1
        assert challenges[0]["record_time_cs"] == 2449
        assert challenges[0]["challenger_entry_id"] == en_f["id"]


class TestRatificationCapstone:
    def _setup_pending_challenge(self, api, meet_name="RC2"):
        """Event raced (2400 beats the 2450 standing record), completed, and
        OFFICIAL; the auto-created challenge is PENDING_VERIFICATION."""
        workspace = setup_in_progress_event(meet_name=meet_name,
                                            seed_times=(2480,))
        create_standing_record(workspace["event"]["id"], record_time_cs=2450,
                               holder_name="Old Star")
        complete_event_with_times(workspace, [2400])
        validate_success(api.publish_event(workspace["event"]["id"], DIRECTOR))
        records = get_success_data(api.list_records(
            RECORDS, params={"event_id": workspace["event"]["id"]}))
        old = next(r for r in records if r["record_time_cs"] == 2450)
        challenge = next(r for r in records
                         if r["status"] == "PENDING_VERIFICATION")
        assert challenge["record_time_cs"] == 2400
        assert challenge["challenger_entry_id"] == workspace["entries"][0]["id"]
        return workspace, old, challenge

    def test_pending_records_block_finalize_until_ratified(self, api):
        """PRD §3.9: "Finalizing moves from `COMPLETED` to `OFFICIAL` and
        requires that no record of the meet remain in `PENDING_VERIFICATION`
        or `SUBMITTED`; pending records block finalization with
        `ERR_RECORDS_PENDING`."
        PRD §3.9: "Challenges follow `PENDING_VERIFICATION` → `SUBMITTED` on
        verification".

        Design: Corner/state_machines/record_ratification_supersedes_and_gates_finalize
        """
        workspace, _old, challenge = self._setup_pending_challenge(api)
        completed_meet = validate_success(
            api.complete_meet(workspace["meet"]["id"], DIRECTOR))
        assert completed_meet["status"] == "COMPLETED"
        resp = api.finalize_meet(workspace["meet"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_RECORDS_PENDING,
                       )  # PENDING_VERIFICATION blocks
        submitted = validate_success(api.verify_record(challenge["id"],
                                                       RECORDS))
        assert submitted["status"] == "SUBMITTED"
        resp2 = api.finalize_meet(workspace["meet"]["id"], DIRECTOR)
        validate_error(resp2, ApiErrorId.ERR_RECORDS_PENDING,
                       )  # SUBMITTED still blocks

    def test_ratify_supersedes_and_finalize_succeeds(self, api):
        """PRD §3.9: "`SUBMITTED` → `CURRENT` on ratification; ratification
        supersedes the prior `CURRENT` record of the same event to
        `SUPERSEDED` and auto-rejects any slower still-pending challenges for
        that event to `REJECTED`."
        PRD §3.9: "Finalizing moves from `COMPLETED` to `OFFICIAL`".
        PRD §3.1: "once the meet is `COMPLETED` or `OFFICIAL`, withdrawal is
        refused with `ERR_MEET_ALREADY_COMPLETED`."

        Design: Corner/state_machines/record_ratification_supersedes_and_gates_finalize
        """
        workspace, old, challenge = self._setup_pending_challenge(
            api, meet_name="RC2b")
        validate_success(api.verify_record(challenge["id"], RECORDS))
        ratified = validate_success(api.ratify_record(challenge["id"],
                                                      RECORDS))
        assert ratified["status"] == "CURRENT"
        old_after = get_success_data(api.get_record(old["id"], DIRECTOR))
        assert old_after["status"] == "SUPERSEDED", \
            "ratification supersedes the prior CURRENT record"
        validate_success(api.complete_meet(workspace["meet"]["id"], DIRECTOR))
        finalized = validate_success(
            api.finalize_meet(workspace["meet"]["id"], DIRECTOR))
        assert finalized["status"] == "OFFICIAL"
        resp = api.withdraw_team(workspace["teams"]["AAA"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_MEET_ALREADY_COMPLETED)


class TestChallengeRejection:
    def test_reject_keeps_standing_and_unblocks_finalize(self, api):
        """PRD §3.9: "Rejection moves a `PENDING_VERIFICATION` or `SUBMITTED`
        record to `REJECTED`."
        PRD §3.9: "Finalizing moves from `COMPLETED` to `OFFICIAL` and
        requires that no record of the meet remain in `PENDING_VERIFICATION`
        or `SUBMITTED`; pending records block finalization with
        `ERR_RECORDS_PENDING`."

        Design: Corner/state_machines/record_reject_keeps_standing
        """
        workspace = setup_in_progress_event(meet_name="RC3",
                                            seed_times=(2480,))
        create_standing_record(workspace["event"]["id"], record_time_cs=2450,
                               holder_name="Old Star")
        complete_event_with_times(workspace, [2400])
        validate_success(api.publish_event(workspace["event"]["id"], DIRECTOR))
        records = get_success_data(api.list_records(
            RECORDS, params={"event_id": workspace["event"]["id"],
                             "challenger_entry_id":
                                 workspace["entries"][0]["id"]}))
        assert len(records) == 1
        challenge = records[0]
        old = get_success_data(api.list_records(
            RECORDS, params={"event_id": workspace["event"]["id"]}))
        old_standing = next(r for r in old if r["record_time_cs"] == 2450)

        rejected = validate_success(api.reject_record(challenge["id"],
                                                      RECORDS))
        assert rejected["status"] == "REJECTED"
        standing_after = get_success_data(
            api.get_record(old_standing["id"], DIRECTOR))
        assert standing_after["status"] == "CURRENT", \
            "the standing record is untouched by the rejection"
        validate_success(api.complete_meet(workspace["meet"]["id"], DIRECTOR))
        finalized = validate_success(
            api.finalize_meet(workspace["meet"]["id"], DIRECTOR))
        assert finalized["status"] == "OFFICIAL", \
            "no pending records remain, so finalization proceeds"
