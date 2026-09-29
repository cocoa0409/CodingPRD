"""Concurrency guards, version monotonicity and thresholds crossed step by step.

The four guarded writes each get their own case, and in every one the staleness is
produced naturally by an earlier legitimate write rather than by an invented number.
Two threshold cases then walk a running total and a temporal window across their
edges, observing both the band below the edge and the band at it.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    DIRECTOR_HEADERS,
    OFFICER_ONE,
    TRAINER_HEADERS,
    api_client,
    assertions,
    factories,
    fixtures,
    make_compliance_officer_headers,
)

CLOCK = "2026-08-01T00:00:00Z"
EPISODE_START = "2026-08-03T09:00:00Z"
FIRST_CONDUCT_AT = "2026-07-28T20:00:00Z"
SECOND_CONDUCT_AT = "2026-07-29T20:00:00Z"
ONE_DAY_SHORT = "2026-08-14T00:00:00Z"
COOLING_OFF_ELAPSED = "2026-08-15T00:00:00Z"


def _approved_show_and_a_fresh_grid():
    """The canonical approved sixty-minute music show plus an untouched grid whose
    creation version is the token a second writer would be holding."""
    base = fixtures.station()
    approved = fixtures.create_approved_program(
        base["host_id"],
        base["members"],
        title="Delta Blues Hour",
        format_code="MUSIC",
        requested_daypart="MIDDAY",
        requested_duration_minutes=60,
    )
    grid = fixtures.create_grid()
    return {
        "program_id": approved["program_id"],
        "grid_id": grid["id"],
        "grid_v0": grid["version"],
    }


def _place(grid_id, program_id, expected_version, day_of_week):
    return api_client.create_slot_assignment(
        grid_id,
        factories.create_slot_assignment_payload(
            program_id,
            expected_version,
            day_of_week=day_of_week,
            start_minute=540,
            duration_minutes=60,
        ),
        DIRECTOR_HEADERS,
    )


def _file_political_content(program_id, occurred_at, complainant_note):
    return validate_success(
        api_client.create_compliance_incident(
            factories.create_incident_payload(
                "POLITICAL_CONTENT",
                "MAJOR",
                occurred_at,
                complainant_note=complainant_note,
                program_id=program_id,
            ),
            make_compliance_officer_headers(OFFICER_ONE),
        ),
        201,
    )


class TestGridVersionGuard:
    def test_a_token_consumed_by_the_first_placement_cannot_place_a_second_show(self):
        """The first write's own side effect is what makes the token stale.

        "Creating a slot occupation on a grid requires `expected_grid_version` to
        equal that `ScheduleGrid`'s current `version`. A mismatch is rejected with
        `ERR_STALE_GRID_VERSION` (HTTP 412). The grid's occupation set is exactly the
        input to the placement decision ... so a writer whose picture of which minutes
        are free is out of date cannot be trusted to place a show." Re-reading the
        grid and resubmitting the identical body succeeds, which proves the refusal
        was the guard and not the body.

        Design: Corner/cross-cutting complexity layers/occ_slot_create_rejects_a_grid_version_that_another_write_advanced
        """
        setup = _approved_show_and_a_fresh_grid()

        validate_success(
            _place(setup["grid_id"], setup["program_id"], setup["grid_v0"], 1), 201
        )
        assert fixtures.read_grid(setup["grid_id"])["total_assigned_minutes"] == 60

        validate_error(
            _place(setup["grid_id"], setup["program_id"], setup["grid_v0"], 2),
            "ERR_STALE_GRID_VERSION",
            412,
        )

        _, meta = validate_paginated(api_client.list_slot_assignments(DIRECTOR_HEADERS))
        assert meta["total_count"] == 1

        held = fixtures.read_grid(setup["grid_id"])
        assert held["total_assigned_minutes"] == 60
        assert held["version"] > setup["grid_v0"]

        validate_success(
            _place(setup["grid_id"], setup["program_id"], held["version"], 2), 201
        )

    def test_a_stale_publication_is_refused_before_any_quota_is_measured(self):
        """Two accepted writes moved the grid, and the guard outranks the quota check.

        "Publishing a grid requires `expected_grid_version` to equal that
        `ScheduleGrid`'s current `version`; a mismatch is rejected with
        `ERR_STALE_GRID_VERSION` (HTTP 412)." The ladder settles which refusal wins:
        "a grid that is stale, still holds a tentative occupation, has no assigned
        airtime at all, and falls short of the public-affairs quota reports
        `ERR_STALE_GRID_VERSION` first". Nothing is published, so `published_at` stays
        null and the show stays where its confirmation left it.

        Design: Corner/cross-cutting complexity layers/occ_grid_publish_rejects_a_stale_grid_version
        """
        setup = _approved_show_and_a_fresh_grid()
        placed = validate_success(
            _place(setup["grid_id"], setup["program_id"], setup["grid_v0"], 1), 201
        )
        fixtures.confirm_slot(placed["id"])
        assert fixtures.read_grid(setup["grid_id"])["version"] > setup["grid_v0"]

        validate_error(
            api_client.publish_schedule_grid(
                setup["grid_id"],
                factories.publish_grid_payload(setup["grid_v0"]),
                DIRECTOR_HEADERS,
            ),
            "ERR_STALE_GRID_VERSION",
            412,
        )

        grid = fixtures.read_grid(setup["grid_id"])
        assert grid["status"] == "IN_REVIEW"
        assert grid["published_at"] is None

        assert fixtures.read_program(setup["program_id"])["programming_status"] == "SCHEDULED"


class TestProposalVersionGuard:
    def test_a_tally_computed_from_a_stale_ballot_set_is_refused(self):
        """Quorum is satisfied and the composite would approve, so only the guard bites.

        "Deciding a proposal requires `expected_proposal_version` to equal that
        `ProgramProposal`'s current `version`; a mismatch is rejected with
        `ERR_STALE_PROPOSAL_VERSION` (HTTP 412)." No tally ran, so the proposal keeps
        "a null `composite_score`" and a null `decided_at`, and because "An approval
        creates the show" no `Program` exists either. Resubmitted at the right version
        the same tally weights three uniform fours to `4.00` and approves.

        Design: Corner/cross-cutting complexity layers/occ_proposal_decide_rejects_a_stale_proposal_version
        """
        fixtures.set_clock(CLOCK)
        host = fixtures.create_certified_host()
        members = fixtures.create_committee_members(count=3)
        chain = fixtures.open_review_chain(host["id"], members)
        fixtures.cast_uniform_ballots(chain["proposal_id"], members)

        current = fixtures.proposal_version(chain["proposal_id"])
        validate_error(
            api_client.decide_proposal(
                chain["proposal_id"],
                factories.decide_proposal_payload(current - 1),
                DIRECTOR_HEADERS,
            ),
            "ERR_STALE_PROPOSAL_VERSION",
            412,
        )

        stalled = validate_success(
            api_client.get_proposal(chain["proposal_id"], DIRECTOR_HEADERS), 200
        )
        assert stalled["status"] == "IN_COMMITTEE"
        assert stalled["composite_score"] is None
        assert stalled["decided_at"] is None

        _, meta = validate_paginated(api_client.list_programs(DIRECTOR_HEADERS))
        assert meta["total_count"] == 0

        decided = validate_success(
            api_client.decide_proposal(
                chain["proposal_id"],
                factories.decide_proposal_payload(current),
                DIRECTOR_HEADERS,
            ),
            200,
        )
        assert decided["status"] == "APPROVED"
        assertions.assert_two_decimals_equal(
            decided["composite_score"], 4.00, "composite_score"
        )


class TestProgramVersionGuard:
    def test_the_guard_answers_before_the_state_rule_on_a_cancellation(self):
        """A show that could not be cancelled at all still answers on the token first.

        "Cancelling a program requires `expected_program_version` to equal that
        `Program`'s current `version`; a mismatch is rejected with
        `ERR_STALE_PROGRAM_VERSION` (HTTP 412)." Cancellation is "available only from
        `UNDER_REVIEW` or `PROBATION`", and the version guards sit above state
        legality in the ladder, so an `APPROVED_UNSCHEDULED` show with a stale token
        reports the 412 rather than `ERR_INVALID_STATE`. The new show starts with "a
        null `cancellation_reason`" and keeps it.

        Design: Corner/cross-cutting complexity layers/occ_program_cancel_rejects_a_stale_program_version
        """
        base = fixtures.station()
        approved = fixtures.create_approved_program(
            base["host_id"],
            base["members"],
            title="Delta Blues Hour",
            format_code="MUSIC",
            requested_daypart="MIDDAY",
            requested_duration_minutes=60,
        )
        program = fixtures.read_program(approved["program_id"])
        assert program["programming_status"] == "APPROVED_UNSCHEDULED"

        validate_error(
            api_client.cancel_program(
                approved["program_id"],
                factories.cancel_program_payload(
                    program["version"] - 1, cancellation_reason="Host withdrew"
                ),
                DIRECTOR_HEADERS,
            ),
            "ERR_STALE_PROGRAM_VERSION",
            412,
        )

        stored = fixtures.read_program(approved["program_id"])
        assert stored["programming_status"] == "APPROVED_UNSCHEDULED"
        assert stored["cancellation_reason"] is None


class TestVersionMonotonicity:
    def test_two_amendments_walk_the_version_one_two_three(self):
        """Version movement counts writes and says nothing about state.

        `version` "starts at 1 on creation and increases by exactly 1 on every
        mutation of the row". "Amending a roster entry lets the `TrainingCoordinator`
        or the `ProgramDirector` change `legal_name`, `email` and `committee_seat` and
        nothing else", and the roster standing "is entirely server-driven", so a
        volunteer who has certified in nothing stays on `PROSPECT` across both writes.

        Design: Corner/cross-cutting complexity layers/occ_version_advances_on_every_successful_write
        """
        fixtures.set_clock(CLOCK)
        volunteer = fixtures.create_volunteer()
        assert volunteer["version"] == 1

        renamed = validate_success(
            api_client.update_volunteer(
                volunteer["id"], {"legal_name": "Ada M. Reyes"}, TRAINER_HEADERS
            ),
            200,
        )
        assert renamed["version"] == 2
        assert renamed["legal_name"] == "Ada M. Reyes"
        assert renamed["status"] == "PROSPECT"

        seated = validate_success(
            api_client.update_volunteer(
                volunteer["id"], {"committee_seat": True}, DIRECTOR_HEADERS
            ),
            200,
        )
        assert seated["version"] == 3
        assert seated["committee_seat"] is True
        assert seated["status"] == "PROSPECT"


class TestCumulativeThreshold:
    def test_two_three_point_charges_walk_the_standing_from_watch_to_restricted(self):
        """The band below the edge and the edge itself are both observed on one show.

        For `POLITICAL_CONTENT` the base "is 1, 3 and 6", and doubling belongs to
        indecency alone — "No other category is ever a safe-harbour violation." The
        bands are "`CLEAR` at exactly 0 points, `WATCH` from 1 through 5 points, and
        `RESTRICTED` at 6 points or more". `WATCH` "is a warning state only: a show on
        `WATCH` keeps airing, keeps its occupations", while `RESTRICTED` takes "every
        occupation of that show in `TENTATIVE` or `CONFIRMED` ... to `PREEMPTED`" and
        "every airing of that show whose `air_status` is `SCHEDULED` ... to
        `CANCELLED`".

        Design: Corner/cross-cutting complexity layers/rate_threshold_penalty_points_flip_the_standing_at_exactly_six
        """
        base = fixtures.station()
        chain = fixtures.episode_chain(
            base["host_id"],
            base["members"],
            title="Delta Blues Hour",
            format_code="MUSIC",
            requested_daypart="MIDDAY",
            duration_minutes=60,
            day_of_week=1,
            start_minute=540,
            scheduled_start_utc=EPISODE_START,
            air_status=None,
        )
        assert fixtures.read_program(chain["program_id"])["compliance_standing"] == "CLEAR"

        first = _file_political_content(
            chain["program_id"],
            FIRST_CONDUCT_AT,
            "Candidate endorsement aired without balance.",
        )
        assert first["penalty_points"] == 3
        assert first["safe_harbor_violation"] is False
        fixtures.adjudicate_incident(first["id"], finding="SUBSTANTIATED")

        watched = fixtures.read_program(chain["program_id"])
        assert watched["compliance_penalty_points"] == 3
        assert watched["compliance_standing"] == "WATCH"
        assert fixtures.read_slot(chain["slot_id"])["status"] == "CONFIRMED"

        second = _file_political_content(
            chain["program_id"], SECOND_CONDUCT_AT, "Second unbalanced endorsement."
        )
        assert second["penalty_points"] == 3
        assert second["safe_harbor_violation"] is False
        fixtures.adjudicate_incident(second["id"], finding="SUBSTANTIATED")

        restricted = fixtures.read_program(chain["program_id"])
        assert restricted["compliance_penalty_points"] == 6
        assert restricted["compliance_standing"] == "RESTRICTED"
        assert fixtures.read_slot(chain["slot_id"])["status"] == "PREEMPTED"
        assert fixtures.read_episode(chain["episode_id"])["air_status"] == "CANCELLED"


class TestTemporalThresholdReset:
    def test_day_thirteen_is_refused_and_day_fourteen_reopens_the_record(self):
        """Both sides of the same window, driven on one record.

        "The station imposes a **fourteen-day cooling-off window**: the clock must
        have reached at least fourteen days past `last_attempt_at`, and an earlier
        request is refused with `ERR_RETAKE_TOO_SOON`." The accepted reopening "clears
        `exam_score` back to null, leaves `attempt_count` exactly as it stands".
        `current_certification_count` counts records "whose `status` is `PASSED`", so a
        record that has never passed leaves the holder on `IN_TRAINING` with a count of
        zero throughout.

        Design: Corner/cross-cutting complexity layers/rate_threshold_retake_window_resets_after_fourteen_days
        """
        fixtures.set_clock(CLOCK)
        volunteer = fixtures.create_volunteer()
        record = fixtures.add_certification(volunteer["id"], "BOARD_OPERATION", 70)
        assert record["status"] == "FAILED"

        fixtures.set_clock(ONE_DAY_SHORT)
        validate_error(
            api_client.retake_certification(record["id"], TRAINER_HEADERS),
            "ERR_RETAKE_TOO_SOON",
            409,
        )
        holder = validate_success(
            api_client.get_volunteer(volunteer["id"], TRAINER_HEADERS), 200
        )
        assert holder["status"] == "IN_TRAINING"
        assert holder["current_certification_count"] == 0

        fixtures.set_clock(COOLING_OFF_ELAPSED)
        reopened = validate_success(
            api_client.retake_certification(record["id"], TRAINER_HEADERS), 200
        )
        assert reopened["status"] == "PENDING_EXAM"
        assert reopened["attempt_count"] == 1
        assert reopened["exam_score"] is None

        holder_again = validate_success(
            api_client.get_volunteer(volunteer["id"], TRAINER_HEADERS), 200
        )
        assert holder_again["status"] == "IN_TRAINING"
        assert holder_again["current_certification_count"] == 0
