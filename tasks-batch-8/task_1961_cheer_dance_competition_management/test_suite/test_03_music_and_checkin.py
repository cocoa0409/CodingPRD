"""Music licensing lifecycle, the parallel team dimensions, and check-in
gates (event LIVE, music VERIFIED)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_music_submission_payload,
    generate_schedule,
    get_success_data,
    lock_roster,
    make_team_coach_headers,
    setup_event_with_division,
    setup_registered_team,
    submit_and_verify_music,
    validate_error,
    validate_paginated,
)

DIRECTOR = TEST_USERS["event_director_headers"]
MUSIC = TEST_USERS["music_compliance_headers"]


class TestParallelDimensions:
    def test_team_parallel_dimensions_reg_and_music(self, api):
        """PRD §3.2: "A team is born with `reg_status` of `REGISTERED` and a
        parallel `music_status` of `PENDING`; these two dimensions evolve
        independently and must both be satisfied where §3.3 and §3.4 say so."
        PRD §3.3: "A `decision` of `VERIFIED` moves the submission to
        `VERIFIED` and the team's `music_status` to `VERIFIED`."

        Design: Difficulty/non_linear_state_machine/team_parallel_dimensions_reg_and_music
        """
        event, division, panel, head, safety = setup_event_with_division()
        team, athlete, entry = setup_registered_team(division, coach_id="coach-1")

        # Music reaches VERIFIED while reg_status is still REGISTERED.
        submit_and_verify_music(team["id"], "coach-1", "LIC-9")
        mid = get_success_data(api.get_team(team["id"], DIRECTOR))
        assert mid["reg_status"] == "REGISTERED"
        assert mid["music_status"] == "VERIFIED"

        # The reg transition leaves the music dimension untouched.
        lock_roster(team["id"], "coach-1")
        after = get_success_data(api.get_team(team["id"], DIRECTOR))
        assert after["reg_status"] == "ROSTER_LOCKED"
        assert after["music_status"] == "VERIFIED"

    def test_team_music_persists_through_roster_lock(self, api):
        """PRD §3.3: "Music licensing runs on the parallel dimension."
        PRD §3.3: "Locking increments the team's `version`."

        Design: Difficulty/non_linear_state_machine/team_parallel_dimensions_reg_and_music
        """
        event, division, panel, head, safety = setup_event_with_division()
        team, athlete, entry = setup_registered_team(division, coach_id="coach-1")

        # Lock first, then verify music: the dimensions commute.
        lock_roster(team["id"], "coach-1")
        submit_and_verify_music(team["id"], "coach-1", "LIC-2")
        after = get_success_data(api.get_team(team["id"], DIRECTOR))
        assert after["reg_status"] == "ROSTER_LOCKED"
        assert after["music_status"] == "VERIFIED"


class TestMusicLifecycle:
    def test_music_flag_then_replacement_supersedes(self, api):
        """PRD §3.3: "when the submission replaces a `FLAGGED` predecessor,
        the old record transitions to `SUPERSEDED`."
        PRD §3.3: "Each new submission arrives as a **MusicSubmission** in
        `SUBMITTED` status and immediately moves the team's `music_status` to
        `SUBMITTED`"

        Design: Corner/state_machines/music_flag_then_replacement_supersedes
        """
        event, division, panel, head, safety = setup_event_with_division()
        team, athlete, entry = setup_registered_team(division, coach_id="coach-1")
        coach = make_team_coach_headers("coach-1")

        first = get_success_data(api.create_music_submission(
            team["id"],
            create_music_submission_payload(license_reference="LIC-OLD"),
            coach))
        get_success_data(api.review_music_submission(
            first["id"], {"decision": "FLAGGED", "reason": "unlicensed track 2"},
            MUSIC))

        second = get_success_data(api.create_music_submission(
            team["id"],
            create_music_submission_payload(license_reference="LIC-NEW"),
            coach))
        assert second["status"] == "SUBMITTED"

        submissions, _ = validate_paginated(
            api.list_music_submissions(team["id"], MUSIC))
        assert len(submissions) == 2
        assert submissions[0]["id"] == first["id"]
        assert submissions[0]["status"] == "SUPERSEDED"
        assert submissions[1]["id"] == second["id"]
        assert submissions[1]["status"] == "SUBMITTED"

        team_after = get_success_data(api.get_team(team["id"], DIRECTOR))
        assert team_after["music_status"] == "SUBMITTED"

    def test_music_submit_while_review_pending_rejected(self, api):
        """PRD §3.3: "submitting while the latest submission is `SUBMITTED`
        (still awaiting review) or already `VERIFIED` is rejected with
        `ERR_MUSIC_STATE_CONFLICT`."

        Design: Corner/state_machines/music_submit_while_review_pending_rejected
        """
        event, division, panel, head, safety = setup_event_with_division()
        team, athlete, entry = setup_registered_team(division, coach_id="coach-1")
        coach = make_team_coach_headers("coach-1")

        get_success_data(api.create_music_submission(
            team["id"], create_music_submission_payload(), coach))

        resp = api.create_music_submission(
            team["id"],
            create_music_submission_payload(track_count=3,
                                            license_provider="BMI",
                                            license_reference="LIC-2"),
            coach)
        validate_error(resp, ApiErrorId.ERR_MUSIC_STATE_CONFLICT)


class TestCheckInGates:
    def test_checkin_with_unverified_music_rejected(self, api):
        """PRD §3.3: "the team's `music_status` must be `VERIFIED` (else
        `ERR_MUSIC_NOT_VERIFIED`)"

        Design: Corner/errors/checkin_with_unverified_music_rejected
        """
        # Build to LIVE with music left at SUBMITTED (never reviewed).
        event, division, panel, head, safety = setup_event_with_division()
        team, athlete, entry = setup_registered_team(division, coach_id="coach-1")
        coach = make_team_coach_headers("coach-1")
        lock_roster(team["id"], "coach-1")
        get_success_data(api.create_music_submission(
            team["id"], create_music_submission_payload(), coach))

        get_success_data(api.close_registration(event["id"], DIRECTOR))
        division = get_success_data(api.get_division(division["id"], DIRECTOR))
        generate_schedule(division["id"], division["version"])
        get_success_data(api.go_live(event["id"], DIRECTOR))

        resp = api.check_in_team(team["id"], [athlete["id"]], coach)
        validate_error(resp, ApiErrorId.ERR_MUSIC_NOT_VERIFIED)
        after = get_success_data(api.get_team(team["id"], DIRECTOR))
        assert after["reg_status"] == "ROSTER_LOCKED"
