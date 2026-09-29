"""Validations along the dispute path: the ninety-day filing window, the shape of an
assumption challenge, the single entry point, the single decision, the arbitration
deadline and the concession a regeneration must have behind it."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import BASELINE_INTEREST_RATE_BPS, BASELINE_NET_ASSESSED_CENTS
from test_helpers.fixtures import (
    build_issued_assessment,
    build_reviewed_assessment,
    decide_review_request,
    file_review_request,
    get_assessment,
    get_review_request,
    list_all_schedules,
    set_clock,
)
from test_helpers.test_users import (
    FUND_ADMINISTRATOR_HEADERS,
    PLAN_ACTUARY_HEADERS,
    PLAN_TRUSTEE_SECONDARY_HEADERS,
    TEST_USERS,
    make_employer_representative_headers,
)
from test_helpers.types import (
    AssumptionRuling,
    ChallengedAssumption,
    PaymentScheduleSource,
    ReviewDecision,
)

BASELINE_EMPLOYER = {"obligation_start_year": 2021, "cba_count": 1}

DECIDING_TRUSTEE_ID = TEST_USERS["plan_trustee_secondary"]["user_id"]

PROPOSED_RATE_BPS = 450


class TestTheFilingWindow:
    def test_the_last_instant_is_timely_and_one_second_later_is_not(self, api):
        """Two independent demands issued together: the first is challenged on the deadline
        itself, and a second later the other one can no longer be challenged at all.

        PRD 3.6: "Issuance stamps `issued_at` with the logical clock, `issued_by_user_id`
        with the acting `X-User-ID`, and `review_deadline_at` with the instant ninety days
        after `issued_at`. A request for review filed at exactly `review_deadline_at` is
        timely."

        Design: Corner/validations/the_review_window_is_inclusive_at_ninety_days_and_closed_one_second_later
        """
        first = build_issued_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        second = build_issued_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        assert first["assessment"]["review_deadline_at"].startswith("2026-10-30T00:00:00")
        assert second["assessment"]["review_deadline_at"].startswith("2026-10-30T00:00:00")

        set_clock(api, "2026-10-30T00:00:00Z")
        filed = file_review_request(
            api, first["assessment"]["id"], first["employer"]["id"]
        )
        assert filed["status"] == "PENDING"
        assert filed["filed_at"].startswith("2026-10-30T00:00:00")
        assert filed["plan_response_deadline_at"].startswith("2027-02-27T00:00:00")
        # PRD 3.8: a PENDING request has no trigger instant, so the deadline is the outer
        # bound of 180 days after filing.
        assert filed["arbitration_deadline_at"].startswith("2027-04-28T00:00:00")
        assert filed["decision"] == "NONE"
        assert filed["assumption_ruling"] == "PENDING"
        assert filed["recomputed_net_assessed_cents"] is None

        challenged = get_assessment(api, first["assessment"]["id"])
        assert challenged["review_status"] == "REQUESTED"
        assert challenged["collection_status"] == "NOT_YET_DUE"

        set_clock(api, "2026-10-30T00:00:01Z")
        # PRD 2.9: the state precondition sits at tier 8 and the temporal window at tier 11,
        # so the assessment that is already under review answers on its own status.
        duplicate = api.create_review_request(
            factories.review_request_payload(first["assessment"]["id"]),
            make_employer_representative_headers(first["employer"]["id"]),
        )
        validate_error(duplicate, ApiErrorId.DUPLICATE_REVIEW_REQUEST.value, 409)

        late = api.create_review_request(
            factories.review_request_payload(second["assessment"]["id"]),
            make_employer_representative_headers(second["employer"]["id"]),
        )
        validate_error(late, ApiErrorId.REVIEW_WINDOW_CLOSED.value, 409)

        assert get_assessment(api, second["assessment"]["id"])["review_status"] == "NONE"
        _rows, meta = validate_paginated(
            api.list_review_requests(
                FUND_ADMINISTRATOR_HEADERS,
                {"liability_assessment_id": second["assessment"]["id"]},
            )
        )
        assert meta["total_count"] == 0


class TestTheShapeOfAnAssumptionChallenge:
    def test_the_proposed_rate_must_accompany_the_interest_rate_challenge_and_only_that_one(
        self, api
    ):
        """Omitting the rate under an interest-rate challenge and supplying it under a
        mortality challenge are both malformed; the well-formed filing changes no rate.

        PRD 3.8: "Where and only where the challenge is `INTEREST_RATE`,
        `proposed_interest_rate_bps` must be supplied, between 1 and 3000 basis points;
        supplying it under any other challenge, or omitting it under an interest-rate
        challenge, is a malformed request."

        Design: Corner/validations/an_interest_rate_challenge_without_a_proposed_rate_is_rejected
        """
        scenario = build_issued_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        employer_headers = make_employer_representative_headers(
            scenario["employer"]["id"]
        )

        missing_rate = api.create_review_request(
            factories.review_request_payload(
                scenario["assessment"]["id"],
                challenged_assumption=ChallengedAssumption.INTEREST_RATE.value,
            ),
            employer_headers,
        )
        validate_error(missing_rate, ApiErrorId.INVALID_REQUEST.value, 400)

        stray_rate = api.create_review_request(
            factories.review_request_payload(
                scenario["assessment"]["id"],
                challenged_assumption=ChallengedAssumption.MORTALITY.value,
                proposed_interest_rate_bps=PROPOSED_RATE_BPS,
            ),
            employer_headers,
        )
        validate_error(stray_rate, ApiErrorId.INVALID_REQUEST.value, 400)

        assert get_assessment(api, scenario["assessment"]["id"])["review_status"] == "NONE"

        filed = file_review_request(
            api,
            scenario["assessment"]["id"],
            scenario["employer"]["id"],
            challenged_assumption=ChallengedAssumption.INTEREST_RATE.value,
            proposed_interest_rate_bps=PROPOSED_RATE_BPS,
        )
        assert filed["challenged_assumption"] == "INTEREST_RATE"
        assert filed["proposed_interest_rate_bps"] == PROPOSED_RATE_BPS
        assert filed["status"] == "PENDING"
        assert filed["assumption_ruling"] == "PENDING"

        # PRD 3.8: the proposal is recorded and nothing on the demand moves.
        assessment = get_assessment(api, scenario["assessment"]["id"])
        assert assessment["review_status"] == "REQUESTED"
        assert assessment["interest_rate_bps_applied"] == BASELINE_INTEREST_RATE_BPS
        assert assessment["net_assessed_cents"] == BASELINE_NET_ASSESSED_CENTS


class TestTheSingleEntryPoint:
    def test_a_second_request_against_the_same_demand_is_refused(self, api):
        """The review dimension has one door, and the first filing closed it, so the second
        attempt leaves exactly one request on the assessment.

        PRD 3.8: "Filing further requires the assessment's `review_status` to be `NONE` —
        there is exactly one entry point into the dispute dimension, and a second attempt
        is rejected with `ERR_DUPLICATE_REVIEW_REQUEST` — and requires the logical clock
        to be at or before `review_deadline_at`, a later filing being rejected with
        `ERR_REVIEW_WINDOW_CLOSED`."

        Design: Corner/validations/filing_a_second_review_request_for_the_same_assessment_is_rejected
        """
        scenario = build_issued_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        assessment_id = scenario["assessment"]["id"]
        filed = file_review_request(api, assessment_id, scenario["employer"]["id"])

        response = api.create_review_request(
            factories.review_request_payload(assessment_id),
            make_employer_representative_headers(scenario["employer"]["id"]),
        )
        validate_error(response, ApiErrorId.DUPLICATE_REVIEW_REQUEST.value, 409)

        rows, meta = validate_paginated(
            api.list_review_requests(
                FUND_ADMINISTRATOR_HEADERS, {"liability_assessment_id": assessment_id}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == filed["id"]
        assert rows[0]["status"] == "PENDING"

        assessment = get_assessment(api, assessment_id)
        assert assessment["review_status"] == "REQUESTED"
        assert assessment["collection_status"] == "NOT_YET_DUE"


class TestTheSingleDecision:
    def test_a_decided_request_cannot_be_decided_again(self, api):
        """A second disposition would rewrite both the concession and the arbitration window,
        so it is refused and every stamp from the first decision survives.

        PRD 3.8: "The request's `status` must be `PENDING`, else `ERR_REVIEW_ALREADY_DECIDED`;
        the assessment must be `ISSUED`; and the acting `X-User-ID` must differ from the
        assessment's `issued_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/deciding_a_review_request_twice_is_rejected
        """
        scenario = build_issued_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        filed = file_review_request(
            api, scenario["assessment"]["id"], scenario["employer"]["id"]
        )
        decided = decide_review_request(
            api,
            filed["id"],
            decision=ReviewDecision.AFFIRMED.value,
            assumption_ruling=AssumptionRuling.REJECTED.value,
            headers=PLAN_TRUSTEE_SECONDARY_HEADERS,
        )
        assert decided["status"] == "DECIDED"
        assert decided["arbitration_deadline_at"].startswith("2026-09-30T00:00:00")

        response = api.decide_review_request(
            filed["id"],
            factories.review_decision_payload(
                ReviewDecision.REVERSED.value, AssumptionRuling.SUSTAINED.value
            ),
            PLAN_TRUSTEE_SECONDARY_HEADERS,
        )
        validate_error(response, ApiErrorId.REVIEW_ALREADY_DECIDED.value, 409)

        settled = get_review_request(api, filed["id"])
        assert settled["status"] == "DECIDED"
        assert settled["decision"] == "AFFIRMED"
        assert settled["assumption_ruling"] == "REJECTED"
        assert settled["decided_by_user_id"] == DECIDING_TRUSTEE_ID
        assert settled["decided_at"].startswith("2026-08-01T00:00:00")
        assert settled["arbitration_deadline_at"].startswith("2026-09-30T00:00:00")
        assert settled["recomputed_net_assessed_cents"] is None

        assessment = get_assessment(api, scenario["assessment"]["id"])
        assert assessment["review_status"] == "DECIDED"
        assert assessment["net_assessed_cents"] == BASELINE_NET_ASSESSED_CENTS


class TestTheArbitrationDeadline:
    def test_a_day_past_the_deadline_closes_the_arbitral_door(self, api):
        """The decision on the day of issuance pulled the deadline back to sixty days later,
        and the initiation a day after that is out of time.

        PRD 3.8: "Second, the logical clock must be at or before that request's
        `arbitration_deadline_at`, a later attempt being rejected with
        `ERR_ARBITRATION_WINDOW_CLOSED`."

        Design: Corner/validations/initiating_arbitration_one_day_after_the_deadline_is_rejected
        """
        scenario = build_issued_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        filed = file_review_request(
            api, scenario["assessment"]["id"], scenario["employer"]["id"]
        )
        decided = decide_review_request(
            api,
            filed["id"],
            decision=ReviewDecision.AFFIRMED.value,
            headers=PLAN_TRUSTEE_SECONDARY_HEADERS,
        )
        assert decided["arbitration_deadline_at"].startswith("2026-09-30T00:00:00")

        set_clock(api, "2026-10-01T00:00:00Z")
        response = api.create_arbitration(
            factories.arbitration_payload(scenario["assessment"]["id"], filed["id"]),
            make_employer_representative_headers(scenario["employer"]["id"]),
        )
        validate_error(response, ApiErrorId.ARBITRATION_WINDOW_CLOSED.value, 409)

        _rows, meta = validate_paginated(
            api.list_arbitrations(
                FUND_ADMINISTRATOR_HEADERS,
                {"liability_assessment_id": scenario["assessment"]["id"]},
            )
        )
        assert meta["total_count"] == 0

        assessment = get_assessment(api, scenario["assessment"]["id"])
        assert assessment["review_status"] == "DECIDED"
        assert assessment["lifecycle_status"] == "ISSUED"
        assert get_review_request(api, filed["id"])["status"] == "DECIDED"


class TestTheConcessionBehindARegeneration:
    def test_an_affirmed_decision_concedes_nothing_and_mints_no_generation(self, api):
        """The decision exists and is final, but it reduced nothing, so there is no amount to
        carry onto a new generation and the original schedule stands alone.

        PRD 3.8: "Each source must have a real concession behind it: `REVIEW_DECISION`
        requires a request for review on that assessment whose `status` is `DECIDED`, whose
        `decision` is `REDUCED`, and whose `recomputed_net_assessed_cents` is non-null;
        `ARBITRATION_AWARD` requires an arbitration on that assessment whose `award_outcome`
        is `REDUCE`; `ACTUARIAL_CORRECTION` requires `override_net_assessed_cents` to be
        supplied."

        Design: Corner/validations/regenerating_a_schedule_from_a_review_decision_with_nothing_conceded_is_rejected
        """
        scenario = build_reviewed_assessment(
            api,
            decision=ReviewDecision.AFFIRMED.value,
            employer_overrides=BASELINE_EMPLOYER,
        )
        assessment_id = scenario["assessment"]["id"]
        assert scenario["review_request"]["decision"] == "AFFIRMED"
        assert scenario["review_request"]["recomputed_net_assessed_cents"] is None

        response = api.create_payment_schedule(
            factories.payment_schedule_payload(
                assessment_id,
                scenario["assessment"]["version"],
                source=PaymentScheduleSource.REVIEW_DECISION.value,
            ),
            PLAN_ACTUARY_HEADERS,
        )
        validate_error(response, ApiErrorId.NO_REDUCTION_TO_APPLY.value, 422)

        schedules = list_all_schedules(api, assessment_id)
        assert len(schedules) == 1
        assert schedules[0]["generation_seq"] == 1
        assert schedules[0]["source"] == "ISSUANCE"
        assert schedules[0]["status"] == "ACTIVE"

        assessment = get_assessment(api, assessment_id)
        assert assessment["net_assessed_cents"] == BASELINE_NET_ASSESSED_CENTS
        assert assessment["award_adjustment_cents"] == 0
        assert assessment["active_schedule_generation"] == 1
        assert assessment["review_status"] == "DECIDED"
