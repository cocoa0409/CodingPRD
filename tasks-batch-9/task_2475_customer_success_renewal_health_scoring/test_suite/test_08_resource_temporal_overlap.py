"""Two occupancy rules with deliberately different interval arithmetic.

A sponsor's calendar is measured in half-open minutes with a 30-minute buffer
added to each existing booking, and the seam is tested strictly. An account's
save-play concurrency is measured in closed calendar days against an aggregate
limit of two active plays per day. Each rule is probed on the side that
conflicts and on the side that sits exactly at the seam and does not.
"""

import pytest

from test_helpers import (
    ENGAGEMENT_SCHEDULED,
    ENGAGEMENT_TYPE_EXEC_SYNC,
    ENGAGEMENT_TYPE_QBR,
    HEALTH_AMBER,
    OPS_ADMIN_HEADERS,
    PLAY_ACTION_ACTIVATE,
    PLAY_ACTIVE,
    PLAY_DRAFT,
    PLAY_TYPE_COMMERCIAL_CONCESSION,
    PLAY_TYPE_ENABLEMENT_SPRINT,
    PLAY_TYPE_TECHNICAL_REMEDIATION,
    POSTURE_RESTRICTED,
    RISK_ADOPTION_DECLINE,
    RISK_BUDGET_PRESSURE,
    RISK_OUTCOME_MISS,
    ApiErrorId,
    add_buyer_sponsor,
    assert_created,
    assert_field,
    assert_fields,
    assert_ok,
    draft_save_play,
    factories,
    list_rows,
    make_csm_headers,
    read_account,
    read_save_play,
    schedule_engagement,
    transition_save_play,
    validate_error,
)

# The standing booking every candidate below is measured against.
EXISTING_START = "2026-08-10T14:00:00Z"
EXISTING_END = "2026-08-10T15:00:00Z"

# The two ACTIVE windows that leave 2026-08-10 covered twice over.
FIRST_ACTIVE_WINDOW = ("2026-08-01", "2026-08-10")
SECOND_ACTIVE_WINDOW = ("2026-08-05", "2026-08-20")


def _sponsor_with_a_standing_engagement(api, state):
    """Give the account's economic buyer a 14:00-15:00 booking."""
    add_buyer_sponsor(api, state)
    state["engagement"] = schedule_engagement(
        api,
        state["account_id"],
        state["csm_id"],
        state["sponsor_id"],
        EXISTING_START,
        EXISTING_END,
        engagement_type=ENGAGEMENT_TYPE_QBR,
    )
    return state


def _propose_window(api, state, start_at, end_at):
    """Attempt a second engagement on the same sponsor's calendar."""
    return api.create_executive_engagement(
        state["account_id"],
        factories.executive_engagement(
            state["sponsor_id"],
            start_at,
            end_at,
            engagement_type=ENGAGEMENT_TYPE_EXEC_SYNC,
        ),
        make_csm_headers(state["csm_id"]),
    )


def _sponsor_calendar(api, state):
    """The reverse view of the sponsor's engagements."""
    return list_rows(
        api.list_sponsor_engagements(
            state["sponsor_id"], OPS_ADMIN_HEADERS, {"limit": 100}
        )
    )


def _two_overlapping_active_plays(api, state):
    """Activate the two plays that both cover 2026-08-10."""
    first = draft_save_play(
        api,
        state["account_id"],
        state["csm_id"],
        FIRST_ACTIVE_WINDOW[0],
        FIRST_ACTIVE_WINDOW[1],
        risk_code=RISK_ADOPTION_DECLINE,
        play_type=PLAY_TYPE_ENABLEMENT_SPRINT,
    )
    state["first_play"] = transition_save_play(
        api, first["id"], state["csm_id"], PLAY_ACTION_ACTIVATE
    )
    second = draft_save_play(
        api,
        state["account_id"],
        state["csm_id"],
        SECOND_ACTIVE_WINDOW[0],
        SECOND_ACTIVE_WINDOW[1],
        risk_code=RISK_OUTCOME_MISS,
        play_type=PLAY_TYPE_TECHNICAL_REMEDIATION,
    )
    state["second_play"] = transition_save_play(
        api, second["id"], state["csm_id"], PLAY_ACTION_ACTIVATE
    )
    return state


def _draft_candidate(api, state, window_start_date, window_end_date):
    """Draft the third play whose activation is under test."""
    return draft_save_play(
        api,
        state["account_id"],
        state["csm_id"],
        window_start_date,
        window_end_date,
        risk_code=RISK_BUDGET_PRESSURE,
        play_type=PLAY_TYPE_COMMERCIAL_CONCESSION,
    )


def _activate(api, state, play_id):
    """Attempt the `ACTIVATE` action as the owning manager."""
    return api.transition_save_play(
        play_id,
        factories.save_play_transition(PLAY_ACTION_ACTIVATE),
        make_csm_headers(state["csm_id"]),
    )


class TestSponsorCalendarBuffer:
    """The buffered, half-open conflict test on a sponsor's calendar."""

    def test_a_candidate_starting_inside_the_buffer_conflicts(
        self, api, clock, roster_and_account
    ):
        """A 15:15 start collides with a 14:00-15:00 booking buffered to 15:30.

        PRD §2.5: "**Executive-engagement windows are half-open minute intervals.** The interval runs from `start_at` inclusive to `end_at` exclusive."
        PRD §3.3: "A 30-minute travel buffer is applied to each existing row's bounds on both sides."
        PRD §3.3: "The candidate conflicts with an existing row when the candidate's `start_at` is strictly earlier than that row's `end_at` plus 30 minutes **and** the candidate's `end_at` is strictly later than that row's `start_at` minus 30 minutes; any conflict is refused with `ERR_ENGAGEMENT_WINDOW_CONFLICT`."
        PRD §3.3: "The strictness matters at the seam: against an existing engagement running 14:00 to 15:00, a candidate starting at 15:15 conflicts, a candidate starting at exactly 15:30 does not, and a candidate running 13:00 to 13:30 does not, because ending exactly at the buffered lower bound is not "strictly later" than it."

        Design: Difficulty/resource_temporal_overlap/sponsor_calendar_uses_half_open_minutes_with_a_thirty_minute_buffer
        """
        state = _sponsor_with_a_standing_engagement(api, roster_and_account)

        response = _propose_window(
            api, state, "2026-08-10T15:15:00Z", "2026-08-10T16:00:00Z"
        )
        validate_error(response, ApiErrorId.ENGAGEMENT_WINDOW_CONFLICT)

        calendar = _sponsor_calendar(api, state)
        assert [row["id"] for row in calendar] == [state["engagement"]["id"]], (
            f"the refused booking must not reach the calendar: {calendar}"
        )

    @pytest.mark.parametrize(
        ("start_at", "end_at"),
        [
            ("2026-08-10T15:30:00Z", "2026-08-10T16:30:00Z"),
            ("2026-08-10T13:00:00Z", "2026-08-10T13:30:00Z"),
        ],
        ids=["starts_at_the_upper_bound", "ends_at_the_lower_bound"],
    )
    def test_a_candidate_exactly_at_a_buffered_bound_is_admitted(
        self, api, clock, roster_and_account, start_at, end_at
    ):
        """Touching a buffered bound is not conflicting, because both tests are strict.

        PRD §2.5: "**Executive-engagement windows are half-open minute intervals.** The interval runs from `start_at` inclusive to `end_at` exclusive."
        PRD §3.3: "The candidate conflicts with an existing row when the candidate's `start_at` is strictly earlier than that row's `end_at` plus 30 minutes **and** the candidate's `end_at` is strictly later than that row's `start_at` minus 30 minutes; any conflict is refused with `ERR_ENGAGEMENT_WINDOW_CONFLICT`."
        PRD §3.3: "The strictness matters at the seam: against an existing engagement running 14:00 to 15:00, a candidate starting at 15:15 conflicts, a candidate starting at exactly 15:30 does not, and a candidate running 13:00 to 13:30 does not, because ending exactly at the buffered lower bound is not "strictly later" than it."
        PRD §3.3: "A new engagement starts in state `SCHEDULED` with `outcome_recorded_at` null, and no health figure moves until an outcome is recorded."

        Design: Difficulty/resource_temporal_overlap/sponsor_calendar_uses_half_open_minutes_with_a_thirty_minute_buffer
        """
        state = _sponsor_with_a_standing_engagement(api, roster_and_account)

        admitted = assert_created(_propose_window(api, state, start_at, end_at))
        assert_fields(
            admitted,
            {
                "state": ENGAGEMENT_SCHEDULED,
                "sponsor_contact_id": state["sponsor_id"],
                "outcome_recorded_at": None,
            },
        )

        calendar = _sponsor_calendar(api, state)
        assert sorted(row["id"] for row in calendar) == sorted(
            [state["engagement"]["id"], admitted["id"]]
        ), f"the sponsor calendar must hold exactly two bookings: {calendar}"


class TestSavePlayDayBudget:
    """The aggregate, closed-day concurrency budget of an account's save plays."""

    def test_a_third_play_touching_a_doubly_covered_day_is_refused(
        self, api, clock, trending_account
    ):
        """2026-08-10 is the closing day of one play and inside the other, so it is full.

        PRD §2.5: "**Save-play windows are closed calendar-day intervals.** Both `window_start_date` and `window_end_date` belong to the play, so two plays where one ends on the same calendar day the next begins do overlap on that shared day."
        PRD §3.5: "And the window must fit within the account's concurrency budget: no calendar day from `window_start_date` through `window_end_date` inclusive may already be covered by 2 of the account's plays in state `ACTIVE`."
        PRD §3.5: "An account with `ACTIVE` plays covering 2026-08-01 to 2026-08-10 and 2026-08-05 to 2026-08-20 has both plays covering 2026-08-10; a candidate window of 2026-08-10 to 2026-08-15 is therefore refused with `ERR_SAVE_PLAY_WINDOW_CAPACITY`, while a candidate of 2026-08-11 to 2026-08-15 is admitted because only one play covers those days."

        Design: Difficulty/resource_temporal_overlap/save_play_windows_use_closed_days_with_an_aggregate_cap_of_two
        """
        state = _two_overlapping_active_plays(api, trending_account)
        assert_field(state["first_play"], "state", PLAY_ACTIVE)
        assert_field(state["second_play"], "state", PLAY_ACTIVE)
        candidate = _draft_candidate(api, state, "2026-08-10", "2026-08-15")

        validate_error(
            _activate(api, state, candidate["id"]),
            ApiErrorId.SAVE_PLAY_WINDOW_CAPACITY,
        )

        assert_field(read_save_play(api, candidate["id"]), "state", PLAY_DRAFT)
        assert_fields(
            read_account(api, state["account_id"]),
            {
                "open_save_play_count": 2,
                "coverage_posture": POSTURE_RESTRICTED,
                "health_tier": HEALTH_AMBER,
            },
        )

    @pytest.mark.parametrize(
        ("window_start_date", "window_end_date"),
        [
            ("2026-08-11", "2026-08-15"),
            ("2026-08-21", "2026-08-25"),
        ],
        ids=["day_after_the_doubly_covered_day", "day_after_the_longer_play_ends"],
    )
    def test_a_third_play_clear_of_the_doubly_covered_day_is_admitted(
        self, api, clock, trending_account, window_start_date, window_end_date
    ):
        """Windows whose every day carries at most one active play activate normally.

        PRD §2.5: "**Save-play windows are closed calendar-day intervals.** Both `window_start_date` and `window_end_date` belong to the play, so two plays where one ends on the same calendar day the next begins do overlap on that shared day."
        PRD §3.5: "An account with `ACTIVE` plays covering 2026-08-01 to 2026-08-10 and 2026-08-05 to 2026-08-20 has both plays covering 2026-08-10; a candidate window of 2026-08-10 to 2026-08-15 is therefore refused with `ERR_SAVE_PLAY_WINDOW_CAPACITY`, while a candidate of 2026-08-11 to 2026-08-15 is admitted because only one play covers those days."
        PRD §3.5: "A successful activation carries the play `DRAFT → ACTIVE`, increments `open_save_play_count` by 1 and re-derives `coverage_posture`, which necessarily yields `RESTRICTED`."

        Design: Difficulty/resource_temporal_overlap/save_play_windows_use_closed_days_with_an_aggregate_cap_of_two
        """
        state = _two_overlapping_active_plays(api, trending_account)
        candidate = _draft_candidate(api, state, window_start_date, window_end_date)

        activated = assert_ok(_activate(api, state, candidate["id"]))
        assert_fields(
            activated,
            {
                "state": PLAY_ACTIVE,
                "window_start_date": window_start_date,
                "window_end_date": window_end_date,
            },
        )

        assert_fields(
            read_account(api, state["account_id"]),
            {
                "open_save_play_count": 3,
                "coverage_posture": POSTURE_RESTRICTED,
            },
        )
