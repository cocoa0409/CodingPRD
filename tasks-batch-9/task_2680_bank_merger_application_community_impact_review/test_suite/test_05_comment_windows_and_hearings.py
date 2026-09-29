"""Comment windows, their half-open overlap rule, and the hearing grant cascade."""
from test_helpers import ApiErrorId, TEST_USERS, api_client
from test_helpers.assertions import (
    assert_comment_period,
    assert_hearing_request,
    assert_same_instant,
)
from test_helpers.factories import hearing_request_payload
from test_helpers.fixtures import (
    application_under_review,
    close_comment_period,
    decide_hearing,
    file_comment,
    file_substantive_protest,
    list_comment_periods,
    open_comment_period,
    read_application,
    read_period,
    request_hearing,
    two_bank_world,
)
from test_helpers.test_users import COMMENTER_USER_ID, make_commenter_headers
from prd_bench_local_runner.testing import validate_error, validate_paginated


class TestHearingGrantAdvancesOnlyTheReviewAxis:
    """The filing axis holds at UNDER_REVIEW while the community axis walks forward."""

    def test_the_grant_extends_the_cited_comment_window(self):
        """PRD §3.8: "Second — caused by the first link, not by the caller — the cited period moves
        `OPEN → EXTENDED`: 30 days are added to its `extended_days_total`, its `closes_at` is
        recomputed as `opens_at` plus `duration_days` plus the new `extended_days_total`, and its
        `extension_count` increments by 1."

        Design: Difficulty/non_linear_state_machine/merger_application_parallel_review_dimension_advances_while_filing_dimension_holds
        """
        world = application_under_review()
        period = world["period"]
        comment = file_substantive_protest(period["id"])
        request = request_hearing(world["application"]["id"], comment["id"])

        decide_hearing(request["id"], outcome="GRANTED")

        extended = read_period(period["id"])
        assert_comment_period(extended)
        assert extended["status"] == "EXTENDED"
        assert extended["extension_count"] == 1
        assert extended["extended_days_total"] == 30
        assert_same_instant(extended["closes_at"], "2026-09-30T00:00:00Z", "closes_at")
        assert extended["substantive_protest_count"] == 1

    def test_the_petition_records_the_thirty_day_extension_it_granted(self):
        """PRD §3.8: "First, the petition moves `PENDING → GRANTED` with `decided_at` stamped from
        the logical clock, `decided_by_user_id` taken from the acting `X-User-ID`,
        `decision_rationale` recorded, and `extension_days_granted` set to 30."

        Design: Difficulty/non_linear_state_machine/merger_application_parallel_review_dimension_advances_while_filing_dimension_holds
        """
        world = application_under_review()
        comment = file_substantive_protest(world["period"]["id"])
        request = request_hearing(world["application"]["id"], comment["id"])

        granted = decide_hearing(request["id"], outcome="GRANTED")

        assert_hearing_request(granted)
        assert granted["status"] == "GRANTED"
        assert granted["extension_days_granted"] == 30

    def test_the_filing_axis_holds_while_the_review_axis_reaches_hearing_granted(self):
        """PRD §3.2: "An application can sit in `UNDER_REVIEW` while its community review walks from
        `OPEN_FOR_COMMENT` to `PROTEST_PENDING` to `HEARING_GRANTED` and back, and neither axis
        constrains the other except where this document says so explicitly."

        Design: Difficulty/non_linear_state_machine/merger_application_parallel_review_dimension_advances_while_filing_dimension_holds
        """
        world = application_under_review()
        comment = file_substantive_protest(world["period"]["id"])
        request = request_hearing(world["application"]["id"], comment["id"])
        decide_hearing(request["id"], outcome="GRANTED")

        application = read_application(world["application"]["id"], world["acquirer"]["id"])

        assert application["public_review_status"] == "HEARING_GRANTED"
        assert application["filing_status"] == "UNDER_REVIEW"
        assert application["amendment_round"] == 0
        assert application["substantive_protest_count"] == 1
        assert application["unresolved_protest_count"] == 1

    def test_the_grant_pushes_the_earliest_decision_instant_out_by_the_extension(self):
        """PRD §3.8: "Third — caused by the second link — the application's `earliest_decision_at`
        becomes the extended `closes_at` plus 15 days, and its community-review axis moves
        `HEARING_PENDING → HEARING_GRANTED`."

        Design: Difficulty/non_linear_state_machine/merger_application_parallel_review_dimension_advances_while_filing_dimension_holds
        """
        world = application_under_review()
        comment = file_substantive_protest(world["period"]["id"])
        request = request_hearing(world["application"]["id"], comment["id"])
        decide_hearing(request["id"], outcome="GRANTED")

        application = read_application(world["application"]["id"], world["acquirer"]["id"])

        assert_same_instant(application["earliest_decision_at"], "2026-10-15T00:00:00Z",
                            "earliest_decision_at")


class TestClosedPeriodOutranksTheMissingProtest:
    """A petition that fails both hearing preconditions reports the state one."""

    def test_a_petition_on_a_closed_period_reports_the_period_state_error(self):
        """PRD §3.8: "Two things must hold: the cited comment must itself be a substantive protest
        and its period's `substantive_protest_count` must be at least 1, failing which the petition
        is refused with `ERR_NO_SUBSTANTIVE_PROTEST`; and the cited comment's period must have
        `status` `OPEN` or `EXTENDED`, failing which it is refused with
        `ERR_COMMENT_PERIOD_NOT_OPEN`."
        PRD §2.5: "Own-resource state: the target record is in a state from which the requested
        transition is declared — one of `ERR_INVALID_APPLICATION_STATE`,
        `ERR_COMMENT_PERIOD_NOT_OPEN`, `ERR_INVALID_HEARING_REQUEST_STATE`,
        `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_DECISION_STATE`, `ERR_INVALID_CONDITION_STATE`,
        `ERR_INVALID_CONVERSION_PLAN_STATE`, `ERR_INVALID_REPORT_STATE` or
        `ERR_INVALID_BRANCH_STATE`, all at HTTP 409."

        Design: Difficulty/priority_pair_validation_conflict/hearing_request_closed_period_error_wins_over_non_substantive_comment
        """
        world = application_under_review()
        comment = file_comment(world["period"]["id"], stance="OPPOSE", substantive=False)
        close_comment_period(world["period"]["id"])

        response = api_client.create_hearing_request(
            hearing_request_payload(world["application"]["id"], comment["id"]),
            make_commenter_headers(COMMENTER_USER_ID),
        )

        validate_error(response, ApiErrorId.ERR_COMMENT_PERIOD_NOT_OPEN.value, 409)

    def test_no_petition_row_survives_the_refusal(self):
        """PRD §3.8: "The petition is created with `status` `PENDING`, `requested_at` stamped from
        the logical clock, `requester_user_id` taken from the acting `X-User-ID`,
        `extension_days_granted` at 0, and `decided_at`, `decided_by_user_id` and
        `decision_rationale` null."

        Design: Difficulty/priority_pair_validation_conflict/hearing_request_closed_period_error_wins_over_non_substantive_comment
        """
        world = application_under_review()
        comment = file_comment(world["period"]["id"], stance="OPPOSE", substantive=False)
        close_comment_period(world["period"]["id"])
        api_client.create_hearing_request(
            hearing_request_payload(world["application"]["id"], comment["id"]),
            make_commenter_headers(COMMENTER_USER_ID),
        )

        listed = api_client.list_hearing_requests(
            make_commenter_headers(COMMENTER_USER_ID),
            params={"application_id": world["application"]["id"]},
        )

        records, _meta = validate_paginated(listed)
        assert records == [], "a refused petition never becomes a stored record"

    def test_closing_the_window_moves_the_review_axis_and_leaves_the_counters(self):
        """PRD §3.7: "Closing sets the period's `status` to `CLOSED`, sets the application's
        `earliest_decision_at` to that period's `closes_at` plus 15 days of post-comment review,
        and — once every period of the application is `CLOSED` — moves the application's
        community-review axis to `COMMENT_CLOSED`."
        PRD §3.7: "The period's `comment_count` is the number of comments on it regardless of
        `status`."

        Design: Difficulty/priority_pair_validation_conflict/hearing_request_closed_period_error_wins_over_non_substantive_comment
        """
        world = application_under_review()
        file_comment(world["period"]["id"], stance="OPPOSE", substantive=False)

        close_comment_period(world["period"]["id"])

        period = read_period(world["period"]["id"])
        application = read_application(world["application"]["id"], world["acquirer"]["id"])
        assert period["status"] == "CLOSED"
        assert period["comment_count"] == 1
        assert period["substantive_protest_count"] == 0
        assert application["public_review_status"] == "COMMENT_CLOSED"


class TestCommentWindowOverlapIsHalfOpen:
    """Touching windows are legal; windows that share a day are not."""

    def test_a_window_opening_at_a_prior_windows_closing_instant_is_accepted(self):
        """PRD §2.10: "Two windows of the same application overlap when the first opens strictly
        before the second closes and the second opens strictly before the first closes; windows that
        merely touch — one beginning at exactly the instant another ends — do not overlap and are
        both legal."
        PRD §3.7: "A window's `closes_at` is always its `opens_at` plus `duration_days` plus
        `extended_days_total`, and the interval is half-open on the right as §2.10 describes."

        Design: Difficulty/resource_temporal_overlap/adjacent_comment_period_allowed_overlapping_period_rejected
        """
        world = two_bank_world()
        application_id = world["application"]["id"]
        first = open_comment_period(application_id, "2026-08-01T00:00:00Z", duration_days=30)
        assert_same_instant(first["closes_at"], "2026-08-31T00:00:00Z", "closes_at")

        second = open_comment_period(application_id, "2026-08-31T00:00:00Z", duration_days=30)

        assert second["status"] == "OPEN"
        assert_same_instant(second["closes_at"], "2026-09-30T00:00:00Z", "closes_at")

    def test_a_window_overlapping_an_existing_window_is_refused(self):
        """PRD §3.7: "Creating a period whose interval overlaps any existing period of the same
        application is refused with `ERR_COMMENT_PERIOD_OVERLAP`; a period that begins exactly where
        a prior one ended is accepted."

        Design: Difficulty/resource_temporal_overlap/adjacent_comment_period_allowed_overlapping_period_rejected
        """
        world = two_bank_world()
        application_id = world["application"]["id"]
        open_comment_period(application_id, "2026-08-01T00:00:00Z", duration_days=30)
        open_comment_period(application_id, "2026-08-31T00:00:00Z", duration_days=30)

        response = api_client.create_comment_period(
            {"application_id": application_id, "opens_at": "2026-09-29T00:00:00Z",
             "duration_days": 30},
            TEST_USERS["analyst_headers"],
        )

        validate_error(response, ApiErrorId.ERR_COMMENT_PERIOD_OVERLAP.value, 409)
        assert len(list_comment_periods(application_id)) == 2, (
            "the refused window never becomes a third stored period"
        )
