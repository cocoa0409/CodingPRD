"""Order, conversion and monitoring errors: single decisions, terminal states and the windows."""
from test_helpers import ApiErrorId, TEST_USERS, api_client, make_filer_headers
from test_helpers.factories import performance_report_payload
from test_helpers.fixtures import (
    application_decided,
    application_under_review,
    attach_condition,
    close_comment_period,
    consummate,
    create_acquirer,
    create_application,
    create_target,
    decide_hearing,
    file_report,
    file_substantive_protest,
    monitoring_world,
    read_application,
    read_condition,
    read_decision,
    read_institution,
    read_period,
    read_plan,
    read_conversion_plan,
    register_conversion_plan,
    request_hearing,
    reset_clock_to_epoch,
    satisfy_condition,
    set_clock,
)
from test_helpers.assertions import assert_same_instant
from test_helpers.test_users import MONITOR_USER_ID, make_monitor_headers
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
SECOND_OFFICIAL = TEST_USERS["second_official_headers"]
MONITOR = TEST_USERS["monitor_headers"]


class TestOneOrderPerApplication:
    """The order guard is per application, not per official."""

    def test_01_a_second_order_on_the_same_application_is_refused(self):
        """PRD §3.10: "At most one order may exist per application; a second attempt is refused with
        `ERR_DECISION_ALREADY_ISSUED`."
        PRD §3.10: "An approving order takes the application `RECOMMENDED → DECIDED`, is created with
        `status` `ISSUED`, and increments the application's `version` by 1."

        Design: Corner/errors/a_second_approval_decision_on_the_same_application_is_refused
        """
        world = application_decided(decision="APPROVED", recommendation="APPROVE")
        application_id = world["application"]["id"]
        before = read_application(application_id, world["acquirer"]["id"])

        response = api_client.create_approval_decision(
            {"application_id": application_id, "decision": "DENIED"}, SECOND_OFFICIAL)

        validate_error(response, ApiErrorId.ERR_DECISION_ALREADY_ISSUED.value, 409)
        decisions, meta = validate_paginated(api_client.list_approval_decisions(
            ANALYST, params={"application_id": application_id}))
        assert meta["total_count"] == 1
        assert [record["id"] for record in decisions] == [world["decision"]["id"]]
        assert decisions[0]["decision"] == "APPROVED", (
            "a second official cannot overwrite the first order"
        )
        application = read_application(application_id, world["acquirer"]["id"])
        assert application["filing_status"] == "DECIDED"
        assert application["public_review_status"] == before["public_review_status"], (
            "the refused second order moved neither axis"
        )
        assert application["version"] == before["version"]


class TestConditionSatisfactionIsNotIdempotent:
    """A satisfied condition admits no second satisfaction and keeps its attribution."""

    def test_02_satisfying_an_already_satisfied_condition_is_refused(self):
        """PRD §3.10: "A condition that is already `SATISFIED` cannot be satisfied again, an attempt
        yielding `ERR_INVALID_CONDITION_STATE`."
        PRD §3.10: "Satisfaction stamps `satisfied_at` from the logical clock and
        `satisfied_by_user_id` with the acting `X-User-ID`."

        Design: Corner/errors/satisfying_an_already_satisfied_condition_is_rejected
        """
        world = application_decided()
        condition = attach_condition(
            world["decision"]["id"], condition_type="CAPITAL_MAINTENANCE", timing="POST_CLOSING",
            threshold_usd=0,
            description="Hold pro forma CET1 at or above 7.0 percent for eight quarters.")
        first = satisfy_condition(condition["id"], MONITOR)
        assert first["status"] == "SATISFIED"
        assert first["satisfied_by_user_id"] == MONITOR_USER_ID
        assert_same_instant(first["satisfied_at"], "2026-09-15T00:00:00Z", "satisfied_at")

        response = api_client.satisfy_approval_condition(
            condition["id"], make_monitor_headers("monitor-2"))

        validate_error(response, ApiErrorId.ERR_INVALID_CONDITION_STATE.value, 409)
        refetched = read_condition(condition["id"])
        assert refetched["satisfied_by_user_id"] == MONITOR_USER_ID, (
            "the second monitor does not overwrite the attribution"
        )
        assert_same_instant(refetched["satisfied_at"], first["satisfied_at"], "satisfied_at")


class TestConversionOrderOfOperations:
    """A draft conversion cannot be completed, and a disclosure must go by mail."""

    def test_03_converting_a_draft_plan_and_disclosing_without_mail_are_refused(self):
        """PRD §3.11: "A plan that is not `DRAFT` when a disclosure is attempted, or not `DISCLOSED`
        when a conversion is attempted, is refused with `ERR_INVALID_CONVERSION_PLAN_STATE`."
        PRD §3.11: "`MAIL` is mandatory: a disclosure that omits it is refused with
        `ERR_CLOSURE_NOTICE_REQUIRED`."
        PRD §2.5: "Own-resource state: the target record is in a state from which the requested
        transition is declared — one of `ERR_INVALID_APPLICATION_STATE`, `ERR_COMMENT_PERIOD_NOT_OPEN`,
        `ERR_INVALID_HEARING_REQUEST_STATE`, `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_DECISION_STATE`,
        `ERR_INVALID_CONDITION_STATE`, `ERR_INVALID_CONVERSION_PLAN_STATE`, `ERR_INVALID_REPORT_STATE`
        or `ERR_INVALID_BRANCH_STATE`, all at HTTP 409."

        Design: Corner/errors/converting_before_disclosure_and_disclosing_without_mail_are_rejected
        """
        reset_clock_to_epoch()
        acquirer = create_acquirer()
        target = create_target()
        application = create_application(acquirer["id"], target["id"])
        plan = register_conversion_plan(
            application["id"], acquirer["id"], conversion_start_date="2026-12-01T00:00:00Z",
            conversion_end_date="2026-12-05T00:00:00Z", affected_customer_count=40_000)
        filer_headers = make_filer_headers(acquirer["id"])

        early_conversion = api_client.convert_conversion_plan(plan["id"], filer_headers)
        mailless_disclosure = api_client.disclose_conversion_plan(
            plan["id"], {"disclosure_channels": ["EMAIL", "ONLINE_BANKING"]}, filer_headers)

        validate_error(early_conversion, ApiErrorId.ERR_INVALID_CONVERSION_PLAN_STATE.value, 409)
        validate_error(mailless_disclosure, ApiErrorId.ERR_CLOSURE_NOTICE_REQUIRED.value, 422)
        refetched = read_conversion_plan(plan["id"])
        assert refetched["status"] == "DRAFT"
        assert refetched["customer_disclosure_sent_at"] is None
        assert refetched["disclosure_lead_days"] is None

    def test_04_the_same_disclosure_with_mail_included_is_accepted(self):
        """PRD §3.11: "Sending the customer disclosure drives `DRAFT → DISCLOSED` and carries
        `disclosure_channels`, a non-empty array whose members are drawn from `MAIL`, `EMAIL`,
        `IN_BRANCH_NOTICE` and `ONLINE_BANKING`."
        PRD §3.11: "The service stamps `customer_disclosure_sent_at` from the logical clock and
        computes `disclosure_lead_days` as the number of whole UTC days from
        `customer_disclosure_sent_at` to `conversion_start_date`, discarding any partial day."

        Design: Corner/errors/converting_before_disclosure_and_disclosing_without_mail_are_rejected
        """
        reset_clock_to_epoch()
        acquirer = create_acquirer()
        target = create_target()
        application = create_application(acquirer["id"], target["id"])
        plan = register_conversion_plan(
            application["id"], acquirer["id"], conversion_start_date="2026-12-01T00:00:00Z",
            conversion_end_date="2026-12-05T00:00:00Z", affected_customer_count=40_000)

        disclosed = validate_success(api_client.disclose_conversion_plan(
            plan["id"], {"disclosure_channels": ["MAIL", "EMAIL"]},
            make_filer_headers(acquirer["id"])))

        assert disclosed["status"] == "DISCLOSED"
        assert disclosed["disclosure_lead_days"] == 122, (
            "2026-08-01 to 2026-12-01 is 122 whole UTC days"
        )
        assert_same_instant(disclosed["customer_disclosure_sent_at"], "2026-08-01T00:00:00Z",
                            "customer_disclosure_sent_at")


class TestPendingPetitionBlocksClosure:
    """A live petition keeps the comment window open."""

    def test_05_closing_a_window_with_a_pending_petition_is_refused(self):
        """PRD §3.7: "It is refused with `ERR_HEARING_REQUEST_PENDING` while any hearing request
        citing a comment of that period is still `PENDING`."
        PRD §2.5: "Cross-entity state: both institutions are `ACTIVE` at submission, the decision is
        `CONSUMMATED` before a systems conversion, every comment period is `CLOSED` before
        consummation, and no hearing request citing a comment of a period is `PENDING` when that
        period closes — one of `ERR_INSTITUTION_NOT_ACTIVE`, `ERR_HEARING_REQUEST_PENDING`,
        `ERR_COMMENT_PERIOD_NOT_OPEN` or `ERR_INVALID_DECISION_STATE`, all at HTTP 409."

        Design: Corner/errors/closing_a_period_with_a_pending_hearing_request_is_rejected
        """
        world = application_under_review()
        set_clock("2026-08-10T00:00:00Z")
        protest = file_substantive_protest(
            world["period"]["id"], commenter_name="Kestrel Housing Coalition",
            commenter_type="COMMUNITY_ORGANIZATION",
            body="The merged bank would leave two tracts unbanked.")
        request_hearing(world["application"]["id"], protest["id"])

        response = api_client.close_comment_period(world["period"]["id"], ANALYST)

        validate_error(response, ApiErrorId.ERR_HEARING_REQUEST_PENDING.value, 409)
        assert read_period(world["period"]["id"])["status"] == "OPEN"
        application = read_application(world["application"]["id"], world["acquirer"]["id"])
        assert application["public_review_status"] == "HEARING_PENDING", (
            "no side effect of closing ran, so the axis never reached COMMENT_CLOSED"
        )

    def test_06_the_window_closes_once_the_petition_is_ruled_upon(self):
        """PRD §3.7: "Closing a period is the `CaseAnalyst`'s act, available from `OPEN → CLOSED` and
        from `EXTENDED → CLOSED`."
        PRD §3.8: "The petition moves `PENDING → DENIED` with `decided_at`, `decided_by_user_id` and
        `decision_rationale` recorded and `extension_days_granted` left at 0."

        Design: Corner/errors/closing_a_period_with_a_pending_hearing_request_is_rejected
        """
        world = application_under_review()
        set_clock("2026-08-10T00:00:00Z")
        protest = file_substantive_protest(world["period"]["id"])
        petition = request_hearing(world["application"]["id"], protest["id"])
        decide_hearing(petition["id"], outcome="DENIED",
                       rationale="The written record answers the concerns raised.")

        closed = close_comment_period(world["period"]["id"])

        assert closed["status"] == "CLOSED", (
            "the block was on the PENDING status alone"
        )


class TestPreConsummationConditionsGateTheClosing:
    """Only PRE_CONSUMMATION timing gates the closing."""

    def test_07_an_open_pre_consummation_condition_blocks_the_closing(self):
        """PRD §3.11: "Every approval condition on the order whose `timing` is `PRE_CONSUMMATION`
        must have `status` `SATISFIED`; a condition still `OPEN` or sitting in `BREACHED` yields
        `ERR_CONDITION_NOT_SATISFIED`."
        PRD §3.11: "The target institution's `status` becomes `MERGED_OUT`, and a `MERGED_OUT`
        institution can never again be the acquirer or the target of a submitted application."
        PRD §3.10: "`consummated_at` begins null on every order."

        Design: Corner/errors/consummation_with_an_open_pre_consummation_condition_is_rejected
        """
        world = application_decided()
        condition = attach_condition(
            world["decision"]["id"], condition_type="DIVESTITURE", timing="PRE_CONSUMMATION",
            threshold_usd=50_000_000,
            description="Complete the designated divestiture before closing.")
        assert condition["status"] == "OPEN"
        set_clock("2026-10-05T00:00:00Z")

        response = api_client.consummate(
            world["decision"]["id"], make_filer_headers(world["acquirer"]["id"]))

        validate_error(response, ApiErrorId.ERR_CONDITION_NOT_SATISFIED.value, 422)
        decision = read_decision(world["decision"]["id"])
        assert decision["status"] == "ISSUED"
        assert decision["consummated_at"] is None
        assert read_institution(world["target"]["id"])["status"] == "ACTIVE", (
            "none of the consummation cascade ran"
        )
        assert read_application(
            world["application"]["id"], world["acquirer"]["id"])["filing_status"] == "DECIDED"

    def test_08_an_open_post_closing_condition_does_not_block_the_closing(self):
        """PRD §3.11: "Every approval condition on the order whose `timing` is `PRE_CONSUMMATION`
        must have `status` `SATISFIED`; a condition still `OPEN` or sitting in `BREACHED` yields
        `ERR_CONDITION_NOT_SATISFIED`."
        PRD §3.10: "Pre-consummation conditions gate the closing; post-closing conditions are
        monitored afterwards."
        PRD §3.11: "The order's `status` becomes `CONSUMMATED` and its `consummated_at` is stamped
        from the logical clock."

        Design: Corner/errors/consummation_with_an_open_pre_consummation_condition_is_rejected
        """
        world = application_decided()
        condition = attach_condition(
            world["decision"]["id"], condition_type="CAPITAL_MAINTENANCE", timing="POST_CLOSING",
            threshold_usd=50_000_000,
            description="Hold pro forma CET1 above 7.0 percent for eight quarters after closing.")
        set_clock("2026-10-05T00:00:00Z")

        consummated = consummate(world["decision"]["id"], world["acquirer"]["id"])

        assert consummated["status"] == "CONSUMMATED", (
            "the rule reads only PRE_CONSUMMATION timing"
        )
        assert_same_instant(consummated["consummated_at"], "2026-10-05T00:00:00Z", "consummated_at")
        assert read_condition(condition["id"])["status"] == "OPEN", (
            "the post-closing condition survives the closing untouched"
        )
        assert read_institution(world["target"]["id"])["status"] == "MERGED_OUT"


class TestConsummationWindow:
    """The window is closed at the front, inclusive at both ends, and lapses on overrun."""

    def test_09_consummation_before_the_window_opens_is_refused(self):
        """PRD §3.11: "The current clock instant must be at or after `consummation_window_open_at`,
        an earlier attempt yielding `ERR_WAITING_PERIOD_NOT_ELAPSED`."
        PRD §3.10: "`consummation_window_open_at` is `decided_at` advanced by `waiting_period_days`
        whole days, and consummation is permitted at that instant inclusive."
        PRD §3.10: "Adjustments are then applied to the base: 15 days are added when a hearing has
        been granted, 10 days are added when the `unresolved_protest_count` is greater than 0, and 10
        days are subtracted when `expedited_processing` is true."

        Design: Corner/errors/consummation_is_rejected_before_the_window_opens_and_after_it_lapses
        """
        world = application_decided(decision="APPROVED", recommendation="APPROVE")
        decision = world["decision"]
        acquirer_id = world["acquirer"]["id"]
        assert decision["expedited_processing"] is True
        assert decision["waiting_period_days"] == 5, (
            "a bank-level structure bases at 15 days, expedited takes off 10, and the floor is 5"
        )
        assert_same_instant(decision["consummation_window_open_at"], "2026-09-20T00:00:00Z",
                            "consummation_window_open_at")
        assert_same_instant(decision["consummation_deadline_at"], "2027-03-14T00:00:00Z",
                            "consummation_deadline_at")

        set_clock("2026-09-16T00:00:00Z")
        early = api_client.consummate(decision["id"], make_filer_headers(acquirer_id))
        set_clock("2026-09-19T23:59:59Z")
        one_second_short = api_client.consummate(decision["id"], make_filer_headers(acquirer_id))

        validate_error(early, ApiErrorId.ERR_WAITING_PERIOD_NOT_ELAPSED.value, 422)
        validate_error(one_second_short, ApiErrorId.ERR_WAITING_PERIOD_NOT_ELAPSED.value, 422)
        refetched = read_decision(decision["id"])
        assert refetched["status"] == "ISSUED", "an early attempt is inert"
        assert refetched["consummated_at"] is None
        assert read_institution(world["target"]["id"])["status"] == "ACTIVE"

    def test_10_consummation_exactly_at_the_opening_instant_is_permitted(self):
        """PRD §3.10: "`consummation_window_open_at` is `decided_at` advanced by
        `waiting_period_days` whole days, and consummation is permitted at that instant inclusive."
        PRD §3.11: "Consummation is the `Filer`'s act against the issued order, and it drives both
        `filing_status` `DECIDED → CONSUMMATED` and the order's `ISSUED → CONSUMMATED`."

        Design: Corner/errors/consummation_is_rejected_before_the_window_opens_and_after_it_lapses
        """
        world = application_decided(decision="APPROVED", recommendation="APPROVE")
        acquirer_id = world["acquirer"]["id"]
        set_clock("2026-09-20T00:00:00Z")

        consummated = consummate(world["decision"]["id"], acquirer_id)

        assert consummated["status"] == "CONSUMMATED", "the front edge is inclusive"
        assert_same_instant(consummated["consummated_at"], "2026-09-20T00:00:00Z", "consummated_at")
        assert read_application(
            world["application"]["id"], acquirer_id)["filing_status"] == "CONSUMMATED"

    def test_11_consummation_after_the_deadline_lapses_the_order(self):
        """PRD §3.11: "When consummation is attempted and the current clock instant is strictly after
        `consummation_deadline_at`, the order moves `ISSUED → LAPSED` **first** and the caller then
        receives `ERR_CONSUMMATION_WINDOW_LAPSED`; the application stays in `filing_status`
        `DECIDED`."
        PRD §3.11: "Because the lapse is recorded before the error is returned, a second attempt
        against the same order finds it no longer `ISSUED` and reports the own-resource state error
        `ERR_INVALID_DECISION_STATE` rather than the temporal one."

        Design: Corner/errors/consummation_is_rejected_before_the_window_opens_and_after_it_lapses
        """
        world = application_decided(decision="APPROVED", recommendation="APPROVE")
        decision = world["decision"]
        acquirer_id = world["acquirer"]["id"]
        set_clock("2027-04-01T00:00:00Z")

        late = api_client.consummate(decision["id"], make_filer_headers(acquirer_id))
        second_attempt = api_client.consummate(decision["id"], make_filer_headers(acquirer_id))

        validate_error(late, ApiErrorId.ERR_CONSUMMATION_WINDOW_LAPSED.value, 422)
        validate_error(second_attempt, ApiErrorId.ERR_INVALID_DECISION_STATE.value, 409)
        refetched = read_decision(decision["id"])
        assert refetched["status"] == "LAPSED", "the lapse is recorded before the error is returned"
        assert refetched["consummated_at"] is None
        assert read_application(
            world["application"]["id"], acquirer_id)["filing_status"] == "DECIDED"
        assert read_institution(world["target"]["id"])["status"] == "ACTIVE"


class TestReportSequenceAndLabelUniqueness:
    """A quarter may be filed once, and only the next quarter in line."""

    def test_12_a_report_out_of_sequence_is_refused_while_the_first_quarter_is_taken(self):
        """PRD §3.12: "The `period_index` must equal the plan's `filed_report_count` plus 1, so the
        previous quarter's report must already have completed review before the next may be filed; a
        mismatch is refused with `ERR_REPORT_PERIOD_OUT_OF_SEQUENCE`."
        PRD §3.12: "`credited_usd` on the report is the sum of the applied amounts across all
        categories, and `excess_uncredited_usd` is the sum of the amounts that could not be credited
        — whether because the category is not in the plan or because the achievement overshot the
        category's cap."
        PRD §3.12: "Filing already computes the fulfilment figures, though it does not yet move the
        plan's ledger."

        Design: Corner/errors/report_sequence_and_period_label_uniqueness_are_both_enforced
        """
        world = monitoring_world(measurement_basis="CUMULATIVE_TO_DATE")
        plan_id = world["plan"]["id"]
        acquirer_id = world["acquirer"]["id"]
        assert read_plan(plan_id)["filed_report_count"] == 0
        achieved = {"MORTGAGE_LENDING": 60_000_000, "SMALL_BUSINESS_LENDING": 30_000_000,
                    "PHILANTHROPY": 2_000_000, "CDFI_INVESTMENT": 4_000_000}

        out_of_sequence = api_client.create_performance_report(
            performance_report_payload(plan_id, "2027-Y2", 2, achieved),
            make_filer_headers(acquirer_id))
        first = file_report(plan_id, acquirer_id, "2026-Y1", 1, achieved)

        validate_error(out_of_sequence, ApiErrorId.ERR_REPORT_PERIOD_OUT_OF_SEQUENCE.value, 422)
        assert first["status"] == "FILED"
        assert first["credited_usd"] == 96_000_000, (
            "every category sits under its own committed cap, so nothing is trimmed"
        )
        assert first["excess_uncredited_usd"] == 0
        assert first["reviewed_at"] is None
        plan = read_plan(plan_id)
        assert plan["credited_to_date_usd"] == 0, "the ledger moves only when the report is reviewed"
        assert plan["filed_report_count"] == 0
        assert plan["remaining_commitment_usd"] == 392_000_000

    def test_13_a_second_report_under_the_same_period_label_is_refused(self):
        """PRD §3.12: "A report names its `plan_id`, a `period_label` such as "2027Q1" of between 4
        and 16 characters that must be unique within the plan — a duplicate being refused with
        `ERR_DUPLICATE_REPORT_PERIOD` — a `period_index` that is a 1-based quarter number of at least
        1, and an `achieved_by_category` map from commitment category to dollars achieved during the
        period, which must be non-empty and whose values must all be at least 0."
        PRD §2.5: "Uniqueness constraints — `ERR_DUPLICATE_MARKET_CODE`, `ERR_DUPLICATE_ANALYSIS`,
        `ERR_DUPLICATE_CONVERSION_PLAN` or `ERR_DUPLICATE_REPORT_PERIOD`, all at HTTP 409."

        Design: Corner/errors/report_sequence_and_period_label_uniqueness_are_both_enforced
        """
        world = monitoring_world(measurement_basis="CUMULATIVE_TO_DATE")
        plan_id = world["plan"]["id"]
        acquirer_id = world["acquirer"]["id"]
        first = file_report(
            plan_id, acquirer_id, "2026-Y1", 1,
            {"MORTGAGE_LENDING": 60_000_000, "SMALL_BUSINESS_LENDING": 30_000_000,
             "PHILANTHROPY": 2_000_000, "CDFI_INVESTMENT": 4_000_000})

        duplicate = api_client.create_performance_report(
            performance_report_payload(
                plan_id, "2026-Y1", 1,
                {"MORTGAGE_LENDING": 1_000_000, "SMALL_BUSINESS_LENDING": 1_000_000,
                 "PHILANTHROPY": 1_000_000, "CDFI_INVESTMENT": 1_000_000}),
            make_filer_headers(acquirer_id))

        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_REPORT_PERIOD.value, 409)
        reports, meta = validate_paginated(api_client.list_performance_reports(
            MONITOR, params={"plan_id": plan_id}))
        assert meta["total_count"] == 1
        assert [record["id"] for record in reports] == [first["id"]]
        assert reports[0]["credited_usd"] == 96_000_000, (
            "the refused duplicate rewrote nothing on the accepted filing"
        )
        assert read_plan(plan_id)["filed_report_count"] == 0, (
            "the label is unique within the plan even while the index stays admissible"
        )
