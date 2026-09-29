"""Two calendars with opposite interval conventions: the mentor's buffered closed
observation windows and the cohort's unbuffered half-open seminar slots.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.api_errors import (
    ERR_COHORT_WEEKLY_SEMINAR_CAP_EXCEEDED,
    ERR_OBSERVATION_WINDOW_CONFLICT,
    ERR_SEMINAR_SESSION_OVERLAP,
)
from test_helpers.fixtures import (
    build_program,
    create_cohort,
    create_site,
    open_observation_cycle,
    schedule_seminar_session,
)
from test_helpers.test_users import ADMIN, make_mentor_headers


class TestMentorObservationBufferedClosedInterval:
    """A 30-minute gap still collides; 31 minutes is clear."""

    @staticmethod
    def _booked_nine_to_ten(api: InductionApiClient) -> dict:
        program = build_program(api)
        open_observation_cycle(
            api,
            program["match_id"],
            program["mentor_id"],
            1,
            "2026-08-05T09:00:00Z",
            "2026-08-05T10:00:00Z",
        )
        return program

    @pytest.mark.parametrize(
        "cycle_index,window_start,window_end,gap_minutes",
        [
            (2, "2026-08-05T10:25:00Z", "2026-08-05T11:25:00Z", 25),
            (3, "2026-08-05T10:30:00Z", "2026-08-05T11:30:00Z", 30),
        ],
    )
    def test_a_gap_of_thirty_minutes_or_less_still_conflicts(
        self,
        api: InductionApiClient,
        cycle_index: int,
        window_start: str,
        window_end: str,
        gap_minutes: int,
    ):
        """The travel buffer pushes the collision out to a full half hour either side.

        The PRD sets the boundary inside the conflicting side: "The comparison
        treats both intervals as closed and expands them by a 30-minute buffer on
        each side: a conflict exists when the proposed start is at or before the
        other window's end plus 30 minutes and, simultaneously, the other window's
        start is at or before the proposed end plus 30 minutes. Two windows that
        merely touch therefore conflict, and so do two windows exactly 30 minutes
        apart; a gap of 31 minutes is accepted."

        Design: Difficulty/resource_temporal_overlap/mentor_observation_buffered_closed_interval
        """
        program = self._booked_nine_to_ten(api)

        response = api.create_observation_cycle(
            f.observation_cycle_payload(
                program["match_id"], cycle_index, window_start, window_end
            ),
            make_mentor_headers(program["mentor_id"]),
        )
        validate_error(response, ERR_OBSERVATION_WINDOW_CONFLICT, 409)

        _, meta = validate_paginated(
            api.list_observation_cycles(ADMIN, {"match_id": program["match_id"]})
        )
        assert meta["total_count"] == 1, (
            f"a {gap_minutes}-minute gap stores nothing, got total_count "
            f"{meta['total_count']}"
        )

    def test_a_gap_of_thirty_one_minutes_is_accepted(self, api: InductionApiClient):
        """One minute beyond the buffer the booking is clear and opens PRE_CONFERENCE.

        The same rule names the accepted side explicitly: "Two windows that merely
        touch therefore conflict, and so do two windows exactly 30 minutes apart;
        a gap of 31 minutes is accepted."

        Design: Difficulty/resource_temporal_overlap/mentor_observation_buffered_closed_interval
        """
        program = self._booked_nine_to_ten(api)

        cycle = validate_success(
            api.create_observation_cycle(
                f.observation_cycle_payload(
                    program["match_id"], 4, "2026-08-05T10:31:00Z", "2026-08-05T11:31:00Z"
                ),
                make_mentor_headers(program["mentor_id"]),
            ),
            201,
        )
        assert cycle["phase"] == "PRE_CONFERENCE", (
            f"a new cycle opens in PRE_CONFERENCE, got {cycle['phase']}"
        )

        _, meta = validate_paginated(
            api.list_observation_cycles(ADMIN, {"match_id": program["match_id"]})
        )
        assert meta["total_count"] == 2, (
            f"both bookings now stand, got total_count {meta['total_count']}"
        )


class TestCohortSeminarHalfOpenAdjacencyAllowed:
    """Back-to-back seminars are legal; a one-minute intersection is not."""

    @staticmethod
    def _monday_afternoon_session(api: InductionApiClient) -> str:
        create_site(api)
        cohort = create_cohort(api)
        schedule_seminar_session(
            api,
            cohort["id"],
            1,
            "2026-08-03T14:00:00Z",
            "2026-08-03T16:00:00Z",
            topic="Classroom routines seminar",
        )
        return cohort["id"]

    def test_a_session_starting_as_another_ends_is_accepted_but_one_minute_of_overlap_is_not(
        self, api: InductionApiClient
    ):
        """16:00-18:00 sits legally against 14:00-16:00; 17:59-19:59 does not.

        The seminar calendar uses the opposite convention to the observation one:
        "A proposed seminar window conflicts with any other session *of the same
        cohort* whose `status` is `SCHEDULED` or `HELD`, where a conflict exists
        when the proposed start is strictly before the other session's end and the
        other session's start is strictly before the proposed end. This is the
        opposite convention to the observation rule: back-to-back sessions, where
        one ends at the exact instant the next begins, are permitted here and
        forbidden there."

        Design: Difficulty/resource_temporal_overlap/cohort_seminar_half_open_adjacency_allowed
        """
        cohort_id = self._monday_afternoon_session(api)

        adjacent = validate_success(
            api.create_seminar_session(
                f.seminar_session_payload(
                    cohort_id,
                    2,
                    "2026-08-03T16:00:00Z",
                    "2026-08-03T18:00:00Z",
                    topic="Formative assessment seminar",
                ),
                ADMIN,
            ),
            201,
        )
        assert adjacent["scheduled_minutes"] == 120, (
            f"the derived duration is a whole number of minutes, got "
            f"{adjacent['scheduled_minutes']}"
        )

        response = api.create_seminar_session(
            f.seminar_session_payload(
                cohort_id,
                3,
                "2026-08-03T17:59:00Z",
                "2026-08-03T19:59:00Z",
                topic="Family engagement seminar",
            ),
            ADMIN,
        )
        validate_error(response, ERR_SEMINAR_SESSION_OVERLAP, 409)

        _, meta = validate_paginated(
            api.list_seminar_sessions(ADMIN, {"cohort_id": cohort_id})
        )
        assert meta["total_count"] == 2, (
            f"only the two legal sessions are stored, got {meta['total_count']}"
        )

    def test_a_disjoint_session_is_still_stopped_by_the_weekly_budget(
        self, api: InductionApiClient
    ):
        """A 30-minute Tuesday slot overlaps nothing yet pushes the ISO week to 270.

        The aggregate rule is separate from the pairwise one: "For the ISO week
        containing the proposed session's start — Monday at 00:00:00 UTC up to but
        not including the following Monday at 00:00:00 UTC — the system sums the
        `scheduled_minutes` of every `SCHEDULED` or `HELD` session of that cohort
        whose `scheduled_start` falls in that week, adds the proposed session's own
        minutes, and refuses the booking if the total exceeds four hours."

        Design: Difficulty/resource_temporal_overlap/cohort_seminar_half_open_adjacency_allowed
        """
        cohort_id = self._monday_afternoon_session(api)
        schedule_seminar_session(
            api,
            cohort_id,
            2,
            "2026-08-03T16:00:00Z",
            "2026-08-03T18:00:00Z",
            topic="Formative assessment seminar",
        )

        response = api.create_seminar_session(
            f.seminar_session_payload(
                cohort_id,
                4,
                "2026-08-04T14:00:00Z",
                "2026-08-04T14:30:00Z",
                topic="Reflective practice clinic",
            ),
            ADMIN,
        )
        error = validate_error(response, ERR_COHORT_WEEKLY_SEMINAR_CAP_EXCEEDED, 422)
        assert error["error_id"] != ERR_SEMINAR_SESSION_OVERLAP, (
            "a Tuesday slot cannot collide with two Monday sessions, so the refusal "
            "must be the aggregate weekly one"
        )

        _, meta = validate_paginated(
            api.list_seminar_sessions(ADMIN, {"cohort_id": cohort_id})
        )
        assert meta["total_count"] == 2, (
            f"the week keeps its 240 accepted minutes only, got {meta['total_count']}"
        )
