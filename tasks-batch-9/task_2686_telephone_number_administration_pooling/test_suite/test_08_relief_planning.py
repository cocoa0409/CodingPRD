"""Relief planning: the comment window boundary and the ninety-day calendar buffer."""
from test_helpers import (
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    APPROVER_HEADERS,
    CLOCK_PLUS_30,
    COMMENTER_HEADERS,
    DEFAULT_CLOCK,
    ApiErrorId,
    api_client,
    assert_pct,
    close_and_recommend,
    create_public_comment_payload,
    get_success_data,
    read_relief_plan,
    relief_transition,
    set_clock,
    setup_plan_in_public_comment,
    validate_error,
)

ORDERED_EFFECTIVE_AT = "2026-11-29T00:00:00Z"
PERMISSIVE_DIALING_END_AT = "2027-05-28T00:00:00Z"
ONE_DAY_INSIDE_THE_BUFFER = "2027-08-25T00:00:00Z"
FIRST_DATE_CLEAR_OF_THE_BUFFER = "2027-08-26T00:00:00Z"


def _plan_at_its_closing_instant():
    """A thirty-day comment window that has just reached its closing instant."""
    set_clock()
    npa, plan = setup_plan_in_public_comment(comment_window_days=30)
    assert plan["status"] == "PUBLIC_COMMENT"
    assert plan["comment_window_open_at"] == DEFAULT_CLOCK
    assert plan["comment_window_close_at"] == CLOCK_PLUS_30
    set_clock(CLOCK_PLUS_30)
    return npa, plan


class TestTheCommentWindowCloseBoundary:
    """The closing instant belongs to the closure, not to the commenter."""

    def test_a_comment_filed_at_the_closing_instant_is_refused(self):
        """Standing exactly on the closing instant is already too late to comment.

        and a comment filed at exactly the closing instant is refused with
        `ERR_COMMENT_WINDOW_CLOSED`

        Design: Difficulty/boundary_precision_check/comment_at_window_close_instant_rejected_and_zero_comments_recommends_overlay
        """
        _npa, plan = _plan_at_its_closing_instant()

        validate_error(
            api_client.create_public_comment(
                plan["id"],
                create_public_comment_payload(
                    "CONSUMER", "SUPPORT_SPLIT", "filed at the closing instant"
                ),
                COMMENTER_HEADERS,
            ),
            ApiErrorId.ERR_COMMENT_WINDOW_CLOSED,
            409,
        )

        unchanged = read_relief_plan(plan["id"])
        assert unchanged["status"] == "PUBLIC_COMMENT"
        assert unchanged["comment_count"] == 0
        assert unchanged["recommended_relief_type"] is None

    def test_the_closure_is_accepted_at_that_same_instant_and_recommends_the_overlay(self):
        """The same instant that turned the comment away lets the closure through, and an
        empty consultation still produces a recommendation.

        Note the deliberate asymmetry with comment filing: at exactly the closing instant a
        comment is refused but the closure is accepted.

        a plan closed with no comments at all recommends the overlay with both weights at
        0.00 and `comment_count` at 0

        Design: Difficulty/boundary_precision_check/comment_at_window_close_instant_rejected_and_zero_comments_recommends_overlay
        """
        _npa, plan = _plan_at_its_closing_instant()
        validate_error(
            api_client.create_public_comment(
                plan["id"],
                create_public_comment_payload(
                    "CONSUMER", "SUPPORT_SPLIT", "filed at the closing instant"
                ),
                COMMENTER_HEADERS,
            ),
            ApiErrorId.ERR_COMMENT_WINDOW_CLOSED,
            409,
        )

        closed = close_and_recommend(plan)

        assert closed["status"] == "OVERLAY_RECOMMENDED"
        assert closed["recommended_relief_type"] == "ALL_SERVICES_OVERLAY"
        assert_pct(closed["support_overlay_weight"], 0.00, "support_overlay_weight")
        assert_pct(closed["support_split_weight"], 0.00, "support_split_weight")
        assert closed["comment_count"] == 0
        assert closed["recommender_user_id"] == ADMIN_USER_ID


def _ordered_plan_occupying_the_calendar():
    """A first relief effort ordered onto 2026-11-29, so its window runs to 2027-05-28."""
    npa, plan = _plan_at_its_closing_instant()
    close_and_recommend(plan)
    ordered = relief_transition(
        plan, "ORDER", APPROVER_HEADERS,
        new_npa_code="380", effective_at=ORDERED_EFFECTIVE_AT,
    )
    return npa, ordered


def _attempt_successor_plan(npa, effective_at):
    """A second plan for the same area code, pencilled in for a given effective date."""
    return api_client.create_relief_plan(
        npa["id"],
        {
            "planned_relief_type": "GEOGRAPHIC_SPLIT",
            "comment_window_days": 30,
            "new_npa_code": "220",
            "effective_at": effective_at,
        },
        ADMIN_HEADERS,
    )


class TestTheNinetyDayReliefBuffer:
    """A successor plan must clear the previous plan's window by a full ninety days."""

    def test_a_date_one_day_inside_the_buffer_is_refused(self):
        """The ordered plan occupies the calendar until its permissive dialing ends, and a
        successor pencilled in one day too early is turned away.

        the interval each plan occupies is `window_end_at`: `permissive_dialing_end_at` once
        the plan is `ORDERED`

        A new plan's `effective_at` must be at least 90 days after the `window_end_at` of the
        newest non-withdrawn plan for the same area code

        Design: Difficulty/resource_temporal_overlap/relief_plan_effective_date_must_clear_previous_window_by_ninety_days
        """
        npa, ordered = _ordered_plan_occupying_the_calendar()
        assert ordered["status"] == "ORDERED"
        assert ordered["recommended_relief_type"] == "ALL_SERVICES_OVERLAY"
        assert ordered["effective_at"] == ORDERED_EFFECTIVE_AT
        assert ordered["permissive_dialing_end_at"] == PERMISSIVE_DIALING_END_AT
        assert ordered["window_end_at"] == PERMISSIVE_DIALING_END_AT

        validate_error(
            _attempt_successor_plan(npa, ONE_DAY_INSIDE_THE_BUFFER),
            ApiErrorId.ERR_RELIEF_WINDOW_OVERLAP,
            409,
        )

        plans = get_success_data(api_client.list_npa_relief_plans(npa["id"], ADMIN_HEADERS))
        assert len(plans) == 1
        assert plans[0]["id"] == ordered["id"]

    def test_the_first_date_clear_of_the_buffer_is_accepted(self):
        """One day later the buffer is exactly satisfied, so the boundary is inclusive and
        the successor plan opens in planning.

        The check runs both when the plan is created and when it is ordered, because
        `effective_at` can be supplied at either point.

        A new plan opens at `status` `PLANNING` with `comment_window_open_at`,
        `comment_window_close_at`, `recommended_relief_type`

        Design: Difficulty/resource_temporal_overlap/relief_plan_effective_date_must_clear_previous_window_by_ninety_days
        """
        npa, ordered = _ordered_plan_occupying_the_calendar()
        validate_error(
            _attempt_successor_plan(npa, ONE_DAY_INSIDE_THE_BUFFER),
            ApiErrorId.ERR_RELIEF_WINDOW_OVERLAP,
            409,
        )

        successor = get_success_data(
            _attempt_successor_plan(npa, FIRST_DATE_CLEAR_OF_THE_BUFFER)
        )
        assert successor["status"] == "PLANNING"
        assert successor["npa_id"] == npa["id"]
        assert successor["successor_npa_id"] is None
        assert successor["effective_at"] == FIRST_DATE_CLEAR_OF_THE_BUFFER
        assert successor["comment_window_open_at"] is None
        assert successor["comment_window_close_at"] is None

        plans = get_success_data(api_client.list_npa_relief_plans(npa["id"], ADMIN_HEADERS))
        assert len(plans) == 2
        assert {plan["id"] for plan in plans} == {ordered["id"], successor["id"]}
