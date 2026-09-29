"""Lifecycle transitions: valid edges, refused edges, side effects and terminal states."""
from test_helpers import ApiErrorId, TEST_USERS, api_client, make_filer_headers
from test_helpers.assertions import (
    assert_approval_decision,
    assert_comment_period,
    assert_conversion_plan,
    assert_deposit_market,
    assert_hearing_request,
    assert_same_instant,
)
from test_helpers.fixtures import (
    application_under_review,
    close_comment_period,
    consummate,
    create_regulatory_schedule,
    decide_hearing,
    executed_standard_plan,
    file_report,
    file_substantive_protest,
    list_comment_periods,
    open_comment_period,
    read_application,
    read_branch,
    read_comment,
    read_hearing_request,
    read_institution,
    read_market,
    read_period,
    read_plan,
    read_report,
    request_hearing,
    rosewood_consummation_world,
    set_clock,
    submit_application,
    two_bank_world,
)
from test_helpers.test_users import COMMENTER_USER_ID, OFFICIAL_USER_ID
from prd_bench_local_runner.testing import validate_error, validate_success

ANALYST = TEST_USERS["analyst_headers"]
MONITOR = TEST_USERS["monitor_headers"]
COMMENTER = TEST_USERS["commenter_headers"]


class TestFilingAndAcceptanceEdges:
    """The filing dimension: return for amendment, the submission gate and acceptance."""

    def test_01_return_for_amendment_hands_a_submitted_filing_back(self):
        """PRD §3.4: "From `SUBMITTED → RETURNED_FOR_AMENDMENT` the only requirement is a `reason`
        that is present and non-blank; the transition sets `filing_status` and increments `version`
        by 1."
        PRD §3.4: "It differs in one respect — it increments `amendment_round` by 1 in addition to
        setting `filing_status` to `SUBMITTED` and incrementing `version` by 1."

        Design: Corner/state_machines/return_for_amendment_moves_a_submitted_application_back_to_the_filer
        """
        world = two_bank_world()
        application_id = world["application"]["id"]
        acquirer_id = world["acquirer"]["id"]
        create_regulatory_schedule(application_id, acquirer_id)
        submit_application(application_id, acquirer_id)

        response = api_client.return_merger_application_for_amendment(
            application_id,
            {"reason": "The pro forma schedule omits the branch-level deposit detail."},
            ANALYST,
        )
        returned = validate_success(response, 200)

        assert returned["filing_status"] == "RETURNED_FOR_AMENDMENT"
        assert returned["public_review_status"] == "NOT_OPEN", (
            "returning from SUBMITTED never opens the community record"
        )
        assert returned["amendment_round"] == 0, (
            "the counter advances on the re-filing, not on the return"
        )
        assert returned["version"] == 4, (
            "create, schedule, submit and return each increment the application by 1"
        )
        assert list_comment_periods(application_id) == [], (
            "only acceptance creates a comment period"
        )

    def test_02_submission_without_a_current_regulatory_schedule_is_refused(self):
        """PRD §3.4: "A pro forma capital schedule with `basis` `REGULATORY_ADJUSTED` and `status`
        `CURRENT` must exist for the application, and its absence yields
        `ERR_PRO_FORMA_SCHEDULE_MISSING`."
        PRD §3.2: "The composite is then banded into `management_rating`: a composite of 70.00 or
        more is `SATISFACTORY`, a composite of at least 55.00 but below 70.00 is `CONDITIONAL`, and
        anything below 55.00 is `UNSATISFACTORY`."

        Design: Corner/state_machines/submit_without_a_current_regulatory_schedule_is_rejected
        """
        world = two_bank_world()
        application_id = world["application"]["id"]
        acquirer_id = world["acquirer"]["id"]

        response = api_client.submit_merger_application(
            application_id, make_filer_headers(acquirer_id)
        )

        validate_error(response, ApiErrorId.ERR_PRO_FORMA_SCHEDULE_MISSING.value, 422)
        application = read_application(application_id, acquirer_id)
        assert application["filing_status"] == "DRAFT"
        assert application["management_rating"] == "SATISFACTORY", (
            "the management gate passed, so the missing schedule is what refused the filing"
        )
        assert application["version"] == 1, "a refused transition performs no write"

    def test_03_acceptance_opens_a_thirty_day_window_and_sets_the_earliest_decision(self):
        """PRD §3.4: "It creates a public comment period for the application, opening at the current
        clock instant with a `duration_days` of 30 and `status` `OPEN`."
        PRD §3.4: "And it sets `earliest_decision_at` to that period's `closes_at` plus a further 15
        days of post-comment review time."
        PRD §3.7: "A window's `closes_at` is always its `opens_at` plus `duration_days` plus
        `extended_days_total`, and the interval is half-open on the right as §2.10 describes."

        Design: Corner/state_machines/accept_creates_the_thirty_day_comment_period_and_the_earliest_decision_instant
        """
        world = application_under_review()
        application = world["application"]
        periods = list_comment_periods(application["id"])

        assert application["filing_status"] == "UNDER_REVIEW"
        assert application["public_review_status"] == "OPEN_FOR_COMMENT"
        assert len(periods) == 1, f"acceptance creates exactly one window, found {len(periods)}"
        period = periods[0]
        assert_comment_period(period)
        assert_same_instant(period["opens_at"], "2026-08-01T00:00:00Z", "opens_at")
        assert period["duration_days"] == 30
        assert_same_instant(period["closes_at"], "2026-08-31T00:00:00Z", "closes_at")
        assert period["status"] == "OPEN"
        assert_same_instant(application["earliest_decision_at"], "2026-09-15T00:00:00Z",
                            "earliest_decision_at")
        assert application["version"] == 4

    def test_04_acceptance_of_a_draft_application_is_refused(self):
        """PRD §3.4: "Acceptance for substantive review is the `CaseAnalyst`'s act and drives
        `SUBMITTED → UNDER_REVIEW`."
        PRD §2.5: "Own-resource state: the target record is in a state from which the requested
        transition is declared — one of `ERR_INVALID_APPLICATION_STATE`,
        `ERR_COMMENT_PERIOD_NOT_OPEN`, `ERR_INVALID_HEARING_REQUEST_STATE`,
        `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_DECISION_STATE`, `ERR_INVALID_CONDITION_STATE`,
        `ERR_INVALID_CONVERSION_PLAN_STATE`, `ERR_INVALID_REPORT_STATE` or
        `ERR_INVALID_BRANCH_STATE`, all at HTTP 409."

        Design: Corner/state_machines/accept_a_draft_application_is_rejected
        """
        world = two_bank_world()
        application_id = world["application"]["id"]

        response = api_client.accept_merger_application(application_id, ANALYST)

        validate_error(response, ApiErrorId.ERR_INVALID_APPLICATION_STATE.value, 409)
        assert read_application(application_id, world["acquirer"]["id"])["filing_status"] == "DRAFT"
        assert list_comment_periods(application_id) == [], (
            "a refused acceptance opens no comment window"
        )


class TestConversionPlanInitialState:
    """A freshly registered systems conversion carries no disclosure yet."""

    def test_05_a_new_conversion_plan_is_draft_with_no_disclosure_recorded(self):
        """PRD §3.11: "The plan is created with `status` `DRAFT` and with
        `customer_disclosure_sent_at` and `disclosure_lead_days` null."
        PRD §3.11: "Sending the customer disclosure drives `DRAFT → DISCLOSED` and carries
        `disclosure_channels`, a non-empty array whose members are drawn from `MAIL`, `EMAIL`,
        `IN_BRANCH_NOTICE` and `ONLINE_BANKING`."

        Design: Corner/state_machines/new_systems_conversion_plan_starts_in_draft_with_no_disclosure_recorded
        """
        world = two_bank_world()
        payload = {
            "application_id": world["application"]["id"],
            "conversion_start_date": "2027-06-01",
            "conversion_end_date": "2027-06-15",
            "affected_customer_count": 5000,
        }

        response = api_client.create_conversion_plan(
            payload, make_filer_headers(world["acquirer"]["id"])
        )
        plan = validate_success(response, 201)

        assert_conversion_plan(plan)
        assert plan["status"] == "DRAFT"
        assert plan["customer_disclosure_sent_at"] is None, (
            "no disclosure has been sent, so the stamp stays null"
        )
        assert plan["disclosure_lead_days"] is None, (
            "the lead is computed from the disclosure instant, which does not exist yet"
        )


class TestHearingPetitionOutcomes:
    """The petition's three outcomes are terminal, and only a grant extends the window."""

    def test_06_a_denied_petition_drops_the_review_axis_back_without_extending(self):
        """PRD §3.8: "The petition moves `PENDING → DENIED` with `decided_at`,
        `decided_by_user_id` and `decision_rationale` recorded and `extension_days_granted` left at
        0."
        PRD §3.8: "Nothing else moves: the cited period keeps its original `closes_at`, its
        `extended_days_total` and `extension_count` are untouched, and the application's
        `earliest_decision_at` is untouched."
        PRD §3.8: "The community-review axis then falls back, and which way it falls depends on the
        protest record — `HEARING_PENDING → PROTEST_PENDING` when the application's
        `unresolved_protest_count` is at least 1, and `HEARING_PENDING → OPEN_FOR_COMMENT` when that
        count is 0."

        Design: Corner/state_machines/denied_hearing_returns_the_review_dimension_to_protest_pending_without_extending
        """
        world = application_under_review()
        application_id = world["application"]["id"]
        period_id = world["period"]["id"]
        set_clock("2026-08-10T00:00:00Z")
        comment = file_substantive_protest(period_id)
        petition = request_hearing(application_id, comment["id"])

        decided = decide_hearing(petition["id"], outcome="DENIED",
                                 rationale="The written record is adequate.")

        assert_hearing_request(decided)
        assert decided["status"] == "DENIED"
        assert decided["extension_days_granted"] == 0
        assert decided["decided_by_user_id"] == OFFICIAL_USER_ID
        application = read_application(application_id, world["acquirer"]["id"])
        assert application["public_review_status"] == "PROTEST_PENDING", (
            "the cited protest is still unanswered, so the axis falls back to PROTEST_PENDING"
        )
        assert application["filing_status"] == "UNDER_REVIEW", (
            "the two status axes are independent"
        )
        period = read_period(period_id)
        assert period["status"] == "OPEN"
        assert period["extension_count"] == 0
        assert_same_instant(period["closes_at"], "2026-08-31T00:00:00Z", "closes_at")
        assert_same_instant(application["earliest_decision_at"], "2026-09-15T00:00:00Z",
                            "earliest_decision_at")

    def test_07_withdrawing_an_already_denied_petition_is_refused(self):
        """PRD §3.8: "All three of `GRANTED`, `DENIED` and `WITHDRAWN` are terminal for a petition."
        PRD §3.8: "The requester may withdraw their own petition instead, and only the requester
        may: the acting `X-User-ID` must equal the petition's `requester_user_id`, or the withdrawal
        is refused with `ERR_NOT_REQUEST_OWNER`."
        PRD §2.5: "Own-resource state: the target record is in a state from which the requested
        transition is declared — one of `ERR_INVALID_APPLICATION_STATE`,
        `ERR_COMMENT_PERIOD_NOT_OPEN`, `ERR_INVALID_HEARING_REQUEST_STATE`,
        `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_DECISION_STATE`, `ERR_INVALID_CONDITION_STATE`,
        `ERR_INVALID_CONVERSION_PLAN_STATE`, `ERR_INVALID_REPORT_STATE` or
        `ERR_INVALID_BRANCH_STATE`, all at HTTP 409."

        Design: Corner/state_machines/withdraw_a_denied_hearing_request_is_rejected
        """
        world = application_under_review()
        application_id = world["application"]["id"]
        period_id = world["period"]["id"]
        set_clock("2026-08-10T00:00:00Z")
        comment = file_substantive_protest(period_id)
        assert read_comment(comment["id"])["commenter_user_id"] == COMMENTER_USER_ID
        petition = request_hearing(application_id, comment["id"])
        decide_hearing(petition["id"], outcome="DENIED",
                       rationale="The written record is adequate.")

        response = api_client.withdraw_hearing_request(petition["id"], COMMENTER)

        validate_error(response, ApiErrorId.ERR_INVALID_HEARING_REQUEST_STATE.value, 409)
        petition = read_hearing_request(petition["id"])
        assert petition["status"] == "DENIED", "a terminal petition never leaves its outcome"
        assert petition["extension_days_granted"] == 0
        assert_same_instant(read_period(period_id)["closes_at"], "2026-08-31T00:00:00Z",
                            "closes_at")


class TestCommentWindowClosure:
    """Closing is idempotent-hostile, and the axis only settles once every window is shut."""

    def test_08_closing_an_already_closed_window_is_refused(self):
        """PRD §3.7: "Closing sets the period's `status` to `CLOSED`, sets the application's
        `earliest_decision_at` to that period's `closes_at` plus 15 days of post-comment review,
        and — once every period of the application is `CLOSED` — moves the application's
        community-review axis to `COMMENT_CLOSED`."
        PRD §3.7: "Closing a period is the `CaseAnalyst`'s act, available from `OPEN → CLOSED` and
        from `EXTENDED → CLOSED`."

        Design: Corner/state_machines/closing_an_already_closed_comment_period_is_rejected
        """
        world = application_under_review()
        application_id = world["application"]["id"]
        period_id = world["period"]["id"]
        close_comment_period(period_id)

        response = api_client.close_comment_period(period_id, ANALYST)

        validate_error(response, ApiErrorId.ERR_COMMENT_PERIOD_NOT_OPEN.value, 409)
        assert read_period(period_id)["status"] == "CLOSED"
        application = read_application(application_id, world["acquirer"]["id"])
        assert application["public_review_status"] == "COMMENT_CLOSED"
        assert_same_instant(application["earliest_decision_at"], "2026-09-15T00:00:00Z",
                            "earliest_decision_at unchanged by the refused second close")

    def test_09_the_review_axis_settles_only_after_the_last_window_closes(self):
        """PRD §3.7: "That axis reaches `COMMENT_CLOSED` from `OPEN_FOR_COMMENT`, from
        `PROTEST_PENDING` and from `HEARING_GRANTED` alike; each of those three edges carries the
        same precondition that every period of the application is `CLOSED` after the call, and the
        same effect on the axis."
        PRD §3.7: "Creating a period whose interval overlaps any existing period of the same
        application is refused with `ERR_COMMENT_PERIOD_OVERLAP`; a period that begins exactly where
        a prior one ended is accepted."

        Design: Corner/state_machines/public_review_reaches_comment_closed_only_when_every_period_is_closed
        """
        world = application_under_review()
        application_id = world["application"]["id"]
        acquirer_id = world["acquirer"]["id"]
        first_period = world["period"]
        second_period = open_comment_period(application_id, "2026-09-01T00:00:00Z",
                                            duration_days=30)
        assert_same_instant(second_period["closes_at"], "2026-10-01T00:00:00Z", "closes_at")

        close_comment_period(first_period["id"])

        assert read_period(first_period["id"])["status"] == "CLOSED"
        assert read_period(second_period["id"])["status"] == "OPEN"
        assert read_application(application_id, acquirer_id)["public_review_status"] == \
            "OPEN_FOR_COMMENT", "a live second window holds the axis open"

        close_comment_period(second_period["id"])

        assert read_period(second_period["id"])["status"] == "CLOSED"
        application = read_application(application_id, acquirer_id)
        assert application["public_review_status"] == "COMMENT_CLOSED"
        assert_same_instant(application["earliest_decision_at"], "2026-10-16T00:00:00Z",
                            "earliest_decision_at from the last window closed")


class TestConsummationCascade:
    """Closing merges out the target, reassigns its open offices and divests only the designated one."""

    def test_10_the_order_and_both_application_axes_settle_at_closing(self):
        """PRD §3.11: "The order's `status` becomes `CONSUMMATED` and its `consummated_at` is
        stamped from the logical clock."
        PRD §3.11: "The application's `filing_status` becomes `CONSUMMATED` and its `version`
        increments by 1."
        PRD §3.11: "Finally the application's `post_closing_monitoring_status` becomes `MONITORING`
        when an `EXECUTED` community benefits plan exists for it, and `NOT_APPLICABLE` otherwise."
        PRD §3.10: "`waiting_period_days` is the larger of the adjusted figure and a floor of 5
        days."

        Design: Corner/state_machines/consummation_merges_out_the_target_reassigns_its_branches_and_divests_only_designated_offices
        """
        world = rosewood_consummation_world()
        acquirer_id = world["acquirer"]["id"]

        closed = consummate(world["decision"]["id"], acquirer_id)

        assert_approval_decision(closed)
        assert closed["status"] == "CONSUMMATED"
        assert_same_instant(closed["consummated_at"], "2026-09-20T00:00:00Z", "consummated_at")
        assert closed["waiting_period_days"] == 5, (
            "a 15-day bank-level base less the 10-day expedited reduction lands on the 5-day floor"
        )
        assert_same_instant(closed["consummation_window_open_at"], "2026-09-20T00:00:00Z",
                            "consummation_window_open_at")
        assert_same_instant(closed["consummation_deadline_at"], "2027-03-14T00:00:00Z",
                            "consummation_deadline_at")
        application = read_application(world["application"]["id"], acquirer_id)
        assert application["filing_status"] == "CONSUMMATED"
        assert application["post_closing_monitoring_status"] == "NOT_APPLICABLE", (
            "no executed benefits plan stands behind this order"
        )
        assert read_institution(world["target"]["id"])["status"] == "MERGED_OUT"
        assert read_institution(acquirer_id)["status"] == "ACTIVE"

    def test_11_only_the_designated_office_is_divested_and_the_market_recomputes(self):
        """PRD §3.11: "Every branch whose `institution_id` is the target and whose `status` is
        `OPEN` is reassigned to the acquirer by rewriting its `institution_id`, which drops the
        target's `total_deposits_usd` and `branch_count` to 0."
        PRD §3.11: "Every branch whose `designation_application_id` is this application and whose
        `status` is `DESIGNATED_FOR_DIVESTITURE` becomes `DIVESTED`."
        PRD §2.8: "A branch whose `status` is `DIVESTED` or `CLOSED` is excluded from every
        aggregate."

        Design: Corner/state_machines/consummation_merges_out_the_target_reassigns_its_branches_and_divests_only_designated_offices
        """
        world = rosewood_consummation_world()
        acquirer_id = world["acquirer"]["id"]

        consummate(world["decision"]["id"], acquirer_id)

        far_office = read_branch(world["branch_far"]["id"])
        assert far_office["institution_id"] == acquirer_id, (
            "an OPEN target office is reassigned to the acquirer, not disposed of"
        )
        assert far_office["status"] == "OPEN"
        assert read_branch(world["branch_target"]["id"])["status"] == "DIVESTED"
        assert read_branch(world["branch_acquirer"]["id"])["status"] == "OPEN"
        market = read_market(world["market"]["id"])
        assert_deposit_market(market)
        assert market["total_deposits_usd"] == 950_000_000, (
            "the divested 50,000,000 leaves the includable set"
        )
        assert market["participant_count"] == 4
        assert market["hhi_current"] == 3019
        far_market = read_market(world["far_market"]["id"])
        assert far_market["total_deposits_usd"] == 30_000_000
        assert far_market["participant_count"] == 1
        acquirer = read_institution(acquirer_id)
        assert acquirer["total_deposits_usd"] == 230_000_000
        assert acquirer["branch_count"] == 2
        target = read_institution(world["target"]["id"])
        assert target["total_deposits_usd"] == 0
        assert target["branch_count"] == 0


class TestReportReopenGuard:
    """A report that was never reviewed has nothing to undo."""

    def test_12_reopening_a_still_filed_report_is_refused(self):
        """PRD §3.12: "Reopening drives `ACCEPTED → FILED` or `DEFICIENT → FILED`, and is permitted
        only when no later report of the same plan has been reviewed; otherwise it is refused with
        `ERR_INVALID_REPORT_STATE`, as is a reopen of a report that is already `FILED` or a review
        of a report that is not `FILED`."
        PRD §3.12: "The ledger identity that `credited_to_date_usd` plus
        `remaining_commitment_usd` equals `total_committed_usd` holds before the review and after
        the reopen alike."

        Design: Corner/state_machines/reopen_a_report_that_is_still_filed_is_rejected
        """
        world = application_under_review()
        application_id = world["application"]["id"]
        acquirer_id = world["acquirer"]["id"]
        executed = executed_standard_plan(application_id, acquirer_id,
                                          measurement_basis="CUMULATIVE_TO_DATE", term_years=3)
        plan_id = executed["plan"]["id"]
        report = file_report(plan_id, acquirer_id, "2027Q1", 1, {
            "MORTGAGE_LENDING": 30_000_000,
            "SMALL_BUSINESS_LENDING": 8_000_000,
            "PHILANTHROPY": 500_000,
        })

        response = api_client.reopen_performance_report(report["id"], MONITOR)

        validate_error(response, ApiErrorId.ERR_INVALID_REPORT_STATE.value, 409)
        stored = read_report(report["id"])
        assert stored["status"] == "FILED"
        assert stored["reviewed_at"] is None, "an unreviewed report carries no review stamp"
        plan = read_plan(plan_id)
        assert plan["filed_report_count"] == 0, (
            "the counter advances at review, so a refused reopen leaves it at 0"
        )
        assert plan["credited_to_date_usd"] == 0
        assert plan["remaining_commitment_usd"] == 392_000_000
