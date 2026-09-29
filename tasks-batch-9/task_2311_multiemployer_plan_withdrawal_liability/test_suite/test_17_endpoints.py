"""Endpoint surfaces: the amendment that bumps the concurrency token, the sweep's
counters, the strictly-after acceleration gate, the three independent list filters, the
partial determination and the arbitration cross-check."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import BASELINE_NET_ASSESSED_CENTS
from test_helpers.fixtures import (
    build_issued_assessment,
    build_noticed_schedule,
    build_priced_assessment,
    build_registry,
    create_assessment,
    decide_review_request,
    determine_withdrawal_event,
    file_certified_valuations,
    file_contribution_record,
    get_assessment,
    get_employer,
    get_group,
    get_schedule,
    initiate_arbitration,
    issue_assessment,
    list_all_installments,
    pay_installment,
    register_controlled_group,
    register_employer,
    register_plan,
    report_withdrawal_event,
    run_sweep,
    set_clock,
)
from test_helpers.test_users import (
    FUND_ADMINISTRATOR_HEADERS,
    PLAN_TRUSTEE_HEADERS,
    PLAN_TRUSTEE_SECONDARY_HEADERS,
    make_employer_representative_headers,
)
from test_helpers.types import CoveredWorkStatus, ReportedCause, ReviewDecision

BASELINE_EMPLOYER = {"obligation_start_year": 2021, "cba_count": 1}

THREE_AGREEMENT_EMPLOYER = {
    "obligation_start_year": 2021,
    "covered_work_status": CoveredWorkStatus.PERFORMING.value,
    "cba_count": 3,
}

# Six plan years spread to 100000 base units and 2000000 cents a year, which prices a
# net assessment of 5000000 against a level annual payment of 100000000: a single
# amortisation year and four instalments of 1250000.
SMALL_HISTORY = (
    {
        "plan_year_start": 2020,
        "plan_year_end": 2025,
        "contribution_base_units": 600_000,
        "contribution_amount_cents": 12_000_004,
        "contribution_rate_cents_per_cbu": 1_000,
    },
)
SMALL_INSTALLMENT_CENTS = 1_250_000


class TestAmendingAnEmployer:
    def test_each_amendment_moves_the_version_and_leaves_the_unnamed_fields_alone(self, api):
        """Two successive amendments each name one field, each lifts the version by one, and
        together they invalidate a token read before either landed.

        PRD 3.1: "Later, the fund office may amend the employer's `covered_work_status`,
        `cba_count`, `directly_attributed_vested_benefits_cents` and
        `directly_attributed_assets_cents`; each such amendment increments the employer's
        `version`, which matters directly to any client holding an
        `expected_employer_version` from an earlier read."

        Design: Corner/endpoints/patching_an_employers_covered_work_status_bumps_the_optimistic_concurrency_token
        """
        registry = build_registry(api, employer_overrides=THREE_AGREEMENT_EMPLOYER)
        employer_id = registry["employer"]["id"]
        assert registry["employer"]["version"] == 1
        assert registry["employer"]["covered_work_status"] == "PERFORMING"

        first = validate_success(
            api.update_employer(
                employer_id,
                {"covered_work_status": CoveredWorkStatus.CEASED.value},
                FUND_ADMINISTRATOR_HEADERS,
            ),
            200,
        )
        assert first["covered_work_status"] == "CEASED"
        assert first["version"] == 2
        # PRD 4: the amendment names the covered-work status alone, so the bargaining
        # agreement count and the attributed figures are not touched.
        assert first["cba_count"] == 3
        assert first["directly_attributed_vested_benefits_cents"] == 0

        second = validate_success(
            api.update_employer(
                employer_id,
                {"directly_attributed_vested_benefits_cents": 500_000_000},
                FUND_ADMINISTRATOR_HEADERS,
            ),
            200,
        )
        assert second["version"] == 3
        assert second["directly_attributed_vested_benefits_cents"] == 500_000_000
        assert second["covered_work_status"] == "CEASED"

        for amended in (first, second):
            assert amended["status"] == "CONTRIBUTING"
            assert amended["outstanding_liability_cents"] == 0
            assert amended["obligation_start_year"] == 2021

        # PRD 2.8: the token observed before either amendment is now two versions behind.
        stale = api.create_contribution_record(
            factories.contribution_record_payload(employer_id, 2021, 2025, 1),
            FUND_ADMINISTRATOR_HEADERS,
        )
        validate_error(stale, ApiErrorId.STALE_EMPLOYER_VERSION.value, 412)


class TestTheSweepCounters:
    def test_a_paid_instalment_is_never_counted_delinquent_and_the_assessment_finalises(
        self, api
    ):
        """The second pass ages instalment 2 into DUE and finalises the unchallenged demand,
        while instalment 1 sits long past its grace date without being counted.

        PRD 3.7: "Second, every instalment whose `delinquent_on` has been reached by the
        logical clock while still `DUE` moves `DUE → DELINQUENT`."

        Design: Corner/endpoints/a_collection_sweep_reports_per_category_counts_and_skips_paid_installments
        """
        scenario = build_issued_assessment(
            api,
            employer_overrides=BASELINE_EMPLOYER,
            contribution_entries=SMALL_HISTORY,
        )
        schedule_id = scenario["schedule"]["id"]
        assert scenario["assessment"]["net_assessed_cents"] == 5_000_000
        assert scenario["assessment"]["review_deadline_at"].startswith("2026-10-30T00:00:00")
        assert scenario["schedule"]["installment_count"] == 4

        set_clock(api, "2026-09-30T00:00:00Z")
        first_pass = run_sweep(api, scenario["plan"]["id"])
        assert first_pass["installments_marked_due"] == 1
        assert first_pass["installments_marked_delinquent"] == 0
        assert first_pass["schedules_default_eligible"] == 0
        assert first_pass["review_requests_deemed_denied"] == 0
        assert first_pass["assessments_finalized"] == 0
        assert first_pass["swept_at"].startswith("2026-09-30T00:00:00")

        instalments = list_all_installments(api, schedule_id)
        paid = pay_installment(api, instalments[0], scenario["employer"]["id"])
        assert paid["status"] == "PAID"
        assert paid["amount_paid_cents"] == SMALL_INSTALLMENT_CENTS

        set_clock(api, "2026-12-30T00:00:00Z")
        second_pass = run_sweep(api, scenario["plan"]["id"])
        assert second_pass["installments_marked_due"] == 1
        # PRD 3.7: instalment 1 passed its delinquent_on of 2026-11-29, but it is PAID
        # rather than DUE, so the second hop does not reach it.
        assert second_pass["installments_marked_delinquent"] == 0
        assert second_pass["schedules_default_eligible"] == 0
        assert second_pass["review_requests_deemed_denied"] == 0
        # PRD 3.8: review_status is still NONE and the clock has passed review_deadline_at.
        assert second_pass["assessments_finalized"] == 1

        assessment = get_assessment(api, scenario["assessment"]["id"])
        assert assessment["lifecycle_status"] == "FINAL"
        assert assessment["review_status"] == "NONE"
        assert assessment["collection_status"] == "CURRENT"

        statuses = [row["status"] for row in list_all_installments(api, schedule_id)]
        assert statuses == ["PAID", "DUE", "SCHEDULED", "SCHEDULED"]

        employer = get_employer(api, scenario["employer"]["id"])
        assert employer["credit_watch"] is False
        assert employer["delinquency_strikes"] == 0
        assert employer["outstanding_liability_cents"] == 3 * SMALL_INSTALLMENT_CENTS


class TestTheAccelerationGate:
    def test_the_last_day_of_the_cure_period_is_protected_and_the_next_day_is_not(self, api):
        """The comparison is strictly after, so the deadline instant itself still belongs to
        the employer and only the following day converts the balance.

        PRD 3.7: "The logical clock must be **strictly after** `cure_deadline_at`; an attempt
        at or before that instant is rejected with `ERR_CURE_DEADLINE_NOT_EXPIRED`, because
        the cure period may not be cut short."

        Design: Corner/endpoints/accelerating_before_the_cure_deadline_is_rejected_and_permitted_one_day_after
        """
        scenario = build_noticed_schedule(api, employer_overrides=BASELINE_EMPLOYER)
        schedule_id = scenario["schedule"]["id"]
        assert scenario["schedule"]["cure_deadline_at"].startswith("2027-04-29T00:00:00")

        set_clock(api, "2027-04-29T00:00:00Z")
        too_early = api.accelerate_payment_schedule(schedule_id, PLAN_TRUSTEE_HEADERS)
        validate_error(too_early, ApiErrorId.CURE_DEADLINE_NOT_EXPIRED.value, 409)

        protected = get_schedule(api, schedule_id)
        assert protected["status"] == "NOTICED"
        assert protected["accelerated_balance_cents"] == 0

        set_clock(api, "2027-04-30T00:00:00Z")
        accelerated = validate_success(
            api.accelerate_payment_schedule(schedule_id, PLAN_TRUSTEE_HEADERS), 200
        )
        assert accelerated["status"] == "ACCELERATED"
        # PRD 3.7: nothing was ever paid, so every instalment's principal rolls in.
        assert accelerated["accelerated_balance_cents"] == BASELINE_NET_ASSESSED_CENTS

        instalments = list_all_installments(api, schedule_id)
        assert len(instalments) == 28
        assert {row["status"] for row in instalments} == {"ACCELERATED"}

        assessment = get_assessment(api, scenario["assessment"]["id"])
        assert assessment["collection_status"] == "ACCELERATED"

        employer = get_employer(api, scenario["employer"]["id"])
        assert employer["status"] == "DEFAULTED"
        assert employer["credit_watch"] is True
        assert employer["outstanding_liability_cents"] == BASELINE_NET_ASSESSED_CENTS

        group = get_group(api, scenario["group"]["id"])
        assert group["joint_exposure_cents"] == BASELINE_NET_ASSESSED_CENTS
        assert group["exposure_score"] == pytest.approx(2500.0, abs=0.0001)


class TestTheAssessmentListFilters:
    def test_the_collection_filter_answers_on_the_projection_rather_than_on_the_instalments(
        self, api
    ):
        """A swept-but-unpaid instalment leaves the projected dimension at NOT_YET_DUE, and
        the first payment is what moves it, so the same row answers two different filters
        before and after the cheque.

        PRD 3.7: "failing that, a generation any of whose instalments is `PAID` yields
        `CURRENT`; and failing all of those, `NOT_YET_DUE`."

        Design: Corner/endpoints/filtering_assessments_by_collection_status_returns_the_projected_dimension
        """
        scenario = build_issued_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        assessment_id = scenario["assessment"]["id"]
        employer_headers = make_employer_representative_headers(scenario["employer"]["id"])

        set_clock(api, "2026-09-30T00:00:00Z")
        run_sweep(api, scenario["plan"]["id"])
        first = list_all_installments(api, scenario["schedule"]["id"])[0]
        assert first["status"] == "DUE"

        before, before_meta = validate_paginated(
            api.list_liability_assessments(
                FUND_ADMINISTRATOR_HEADERS, {"collection_status": "NOT_YET_DUE"}
            )
        )
        assert before_meta["total_count"] == 1
        assert before[0]["id"] == assessment_id

        pay_installment(api, first, scenario["employer"]["id"])

        after, after_meta = validate_paginated(
            api.list_liability_assessments(employer_headers, {"collection_status": "CURRENT"})
        )
        assert after_meta["total_count"] == 1
        assert after[0]["id"] == assessment_id

        emptied, emptied_meta = validate_paginated(
            api.list_liability_assessments(
                FUND_ADMINISTRATOR_HEADERS, {"collection_status": "NOT_YET_DUE"}
            )
        )
        assert emptied_meta["total_count"] == 0
        assert emptied == []

        # PRD 2.3: the three dimensions are independent filters and travel alongside the
        # pagination parameters.
        combined, combined_meta = validate_paginated(
            api.list_liability_assessments(
                FUND_ADMINISTRATOR_HEADERS,
                {
                    "lifecycle_status": "ISSUED",
                    "review_status": "NONE",
                    "limit": 1,
                    "offset": 0,
                },
            )
        )
        assert combined_meta["total_count"] == 1
        assert combined_meta["has_more"] is False
        assert combined_meta["limit"] == 1
        assert combined_meta["offset"] == 0
        assert combined[0]["id"] == assessment_id


class TestThePartialDetermination:
    def test_one_of_three_agreements_scales_the_demand_and_leaves_the_obligation_alive(
        self, api
    ):
        """One ceased agreement out of three is the repeating third, carried at four places,
        and the employer keeps an open obligation while the demand shrinks to match.

        PRD 3.4: "For `PARTIAL_CBA_CESSATION` the fraction is `ceased_cba_count` divided by
        the employer's `cba_count`, rounded to four places."

        Design: Corner/endpoints/determining_a_cba_partial_cessation_sets_the_type_the_fraction_and_the_employer_status
        """
        scenario = build_priced_assessment(
            api,
            employer_overrides={"obligation_start_year": 2021, "cba_count": 3},
            withdrawal_overrides={
                "reported_cause": ReportedCause.CBA_PARTIAL_CESSATION.value,
                "ceased_cba_count": 1,
            },
            price=False,
        )
        event = scenario["event"]

        assert event["status"] == "PARTIAL_DETERMINED"
        assert event["determined_type"] == "PARTIAL_CBA_CESSATION"
        assert event["partial_withdrawal_fraction"] == pytest.approx(0.3333, abs=0.0001)
        assert event["rules_variant"] == "GENERAL_RULES"
        assert event["ceased_cba_count"] == 1
        assert event["determined_at"].startswith("2026-08-01T00:00:00")

        employer = get_employer(api, scenario["employer"]["id"])
        assert employer["status"] == "PARTIAL_WITHDRAWN"
        assert employer["ceased_cba_count"] == 1
        assert employer["obligation_end_year"] is None

        # PRD 3.5: the fraction is applied to the already-rounded full-withdrawal basis of
        # 250000000 cents.
        assessment = create_assessment(api, event["id"])
        assert assessment["gross_allocated_cents"] == 83_325_000
        assert assessment["de_minimis_reduction_cents"] == 0
        assert assessment["net_assessed_cents"] == 83_325_000


class TestTheArbitrationGateway:
    def test_a_sibling_employers_decided_request_is_not_a_gateway(self, api):
        """Both identifiers exist, the assessment is the caller's own and the request really
        is decided, so nothing but the pairing is wrong.

        PRD 3.8: "Third and last, the referenced request's `liability_assessment_id` must
        equal the `liability_assessment_id` named in the same payload, so an employer cannot
        borrow another employer's decided request as its own gateway; a mismatch is rejected
        with `ERR_EMPLOYER_PLAN_MISMATCH`."

        Design: Corner/endpoints/arbitrating_on_another_assessments_decided_review_request_is_rejected
        """
        plan = register_plan(api)
        group = register_controlled_group(api)
        file_certified_valuations(api, plan["id"])

        assessments = []
        employers = []
        for _ in range(2):
            employer = register_employer(api, plan["id"], group["id"], **BASELINE_EMPLOYER)
            employers.append(employer)
            file_contribution_record(api, employer["id"], 2021, 2025)
            event = determine_withdrawal_event(
                api, report_withdrawal_event(api, employer["id"])["id"]
            )
            assessments.append(
                issue_assessment(api, create_assessment(api, event["id"])["id"])
            )

        borrowed = validate_success(
            api.create_review_request(
                factories.review_request_payload(assessments[1]["id"]),
                make_employer_representative_headers(employers[1]["id"]),
            ),
            201,
        )
        decided = decide_review_request(
            api,
            borrowed["id"],
            decision=ReviewDecision.AFFIRMED.value,
            headers=PLAN_TRUSTEE_SECONDARY_HEADERS,
        )
        assert decided["status"] == "DECIDED"

        response = api.create_arbitration(
            factories.arbitration_payload(assessments[0]["id"], borrowed["id"]),
            make_employer_representative_headers(employers[0]["id"]),
        )
        validate_error(response, ApiErrorId.EMPLOYER_PLAN_MISMATCH.value, 422)

        for params in (
            {"liability_assessment_id": assessments[0]["id"]},
            {"review_request_id": borrowed["id"]},
        ):
            _rows, meta = validate_paginated(
                api.list_arbitrations(FUND_ADMINISTRATOR_HEADERS, params)
            )
            assert meta["total_count"] == 0

        assert get_assessment(api, assessments[0]["id"])["review_status"] == "NONE"
        assert get_assessment(api, assessments[1]["id"])["review_status"] == "DECIDED"

        own = initiate_arbitration(
            api, assessments[1]["id"], borrowed["id"], employers[1]["id"]
        )
        assert own["status"] == "BRIEFING"
        assert own["round_number"] == 1
