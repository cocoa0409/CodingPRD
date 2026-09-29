"""Optimistic concurrency on the two anchors that carry a client token, and the immediate
visibility of the whole issuance cascade in the response that caused it."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    BASELINE_ANNUAL_PAYMENT_CENTS,
    BASELINE_FINAL_INSTALLMENT_CENTS,
    BASELINE_INSTALLMENT_COUNT,
    BASELINE_NET_ASSESSED_CENTS,
    BASELINE_QUARTERLY_INSTALLMENT_CENTS,
    BASELINE_UVB_TOTAL_CENTS,
)
from test_helpers.fixtures import (
    build_issued_assessment,
    build_priced_assessment,
    current_employer_version,
    decide_review_request,
    file_review_request,
    get_assessment,
    get_employer,
    get_event,
    get_group,
    get_schedule,
    get_valuation,
    latest_schedule,
    list_all_installments,
    list_all_schedules,
    register_controlled_group,
    register_employer,
    register_plan,
)
from test_helpers.test_users import (
    FUND_ADMINISTRATOR_HEADERS,
    PLAN_ACTUARY_HEADERS,
    PLAN_TRUSTEE_HEADERS,
    PLAN_TRUSTEE_SECONDARY_HEADERS,
    TEST_USERS,
)
from test_helpers.types import (
    AssumptionRuling,
    ChallengedAssumption,
    PaymentScheduleSource,
    ReviewDecision,
)

BASELINE_EMPLOYER = {"obligation_start_year": 2021, "cba_count": 1}

ANNUAL_HISTORY_CBU = 50_000
ANNUAL_HISTORY_CENTS = 50_000_000

REDUCED_NET_CENTS = 150_000_000
REDUCED_INSTALLMENT_CENTS = 9_375_000
REDUCED_INSTALLMENT_COUNT = 16


class TestTheEmployerConcurrencyAnchor:
    def test_a_replayed_employer_token_is_refused_and_the_stamp_records_the_new_value(
        self, api
    ):
        """The employer row anchors its whole contribution history, so the token read before
        the first filing is already spent, and each accepted filing stamps the value it
        produced rather than the one presented.

        PRD 2.8: "Every operation that mutates an employer — including the withdrawal
        determination and the amendment endpoint — advances that `version`, and each
        accepted contribution record records the resulting value on the record itself as
        `employer_version_at_apply` so a client can chain successive history corrections
        without a separate read."

        Design: Corner/complexity_layers/a_contribution_record_with_a_stale_expected_employer_version_is_rejected
        """
        plan = register_plan(api)
        group = register_controlled_group(api)
        employer = register_employer(api, plan["id"], group["id"], **BASELINE_EMPLOYER)
        employer_id = employer["id"]
        spent_token = employer["version"]
        assert spent_token == 1

        first = validate_success(
            api.create_contribution_record(
                factories.contribution_record_payload(
                    employer_id,
                    2021,
                    2021,
                    spent_token,
                    contribution_base_units=ANNUAL_HISTORY_CBU,
                    contribution_amount_cents=ANNUAL_HISTORY_CENTS,
                ),
                FUND_ADMINISTRATOR_HEADERS,
            ),
            201,
        )
        assert first["employer_version_at_apply"] == 2
        assert current_employer_version(api, employer_id) == 2

        stale = api.create_contribution_record(
            factories.contribution_record_payload(
                employer_id,
                2022,
                2022,
                spent_token,
                contribution_base_units=ANNUAL_HISTORY_CBU,
                contribution_amount_cents=ANNUAL_HISTORY_CENTS,
            ),
            FUND_ADMINISTRATOR_HEADERS,
        )
        validate_error(stale, ApiErrorId.STALE_EMPLOYER_VERSION.value, 412)

        # PRD 2.8: the refusal is a precondition failure, so it consumed no version.
        assert current_employer_version(api, employer_id) == 2
        _rows, meta = validate_paginated(
            api.list_contribution_records(
                FUND_ADMINISTRATOR_HEADERS, {"employer_id": employer_id}
            )
        )
        assert meta["total_count"] == 1

        second = validate_success(
            api.create_contribution_record(
                factories.contribution_record_payload(
                    employer_id,
                    2022,
                    2022,
                    2,
                    contribution_base_units=ANNUAL_HISTORY_CBU,
                    contribution_amount_cents=ANNUAL_HISTORY_CENTS,
                ),
                FUND_ADMINISTRATOR_HEADERS,
            ),
            201,
        )
        assert second["employer_version_at_apply"] == 3
        assert current_employer_version(api, employer_id) == 3

        _certified, certified_meta = validate_paginated(
            api.list_contribution_records(
                FUND_ADMINISTRATOR_HEADERS,
                {"employer_id": employer_id, "status": "CERTIFIED"},
            )
        )
        assert certified_meta["total_count"] == 2


class TestTheAssessmentConcurrencyAnchor:
    def test_the_token_read_at_issuance_is_stale_by_the_time_regeneration_is_legal(self, api):
        """The decision that authorises the new generation is itself a write on the
        assessment, so the issuance-era token can never be the right one, and the retry
        reprices the conceded amount from scratch.

        PRD 2.8: "A new generation legitimately supersedes the incumbent one, so nothing in
        the schedule state machine prevents a second regeneration; the stale-version check is
        the only thing that stops a regeneration derived from an obsolete
        `net_assessed_cents` from replacing a newer generation."

        Design: Corner/complexity_layers/regenerating_a_schedule_with_a_stale_expected_assessment_version_is_rejected
        """
        scenario = build_issued_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        assessment_id = scenario["assessment"]["id"]
        first_generation_id = scenario["schedule"]["id"]
        issuance_token = scenario["assessment"]["version"]
        assert scenario["assessment"]["net_assessed_cents"] == BASELINE_NET_ASSESSED_CENTS
        assert scenario["assessment"]["annual_payment_cents"] == BASELINE_ANNUAL_PAYMENT_CENTS
        assert scenario["schedule"]["installment_count"] == BASELINE_INSTALLMENT_COUNT

        request = file_review_request(
            api,
            assessment_id,
            scenario["employer"]["id"],
            challenged_assumption=ChallengedAssumption.INTEREST_RATE.value,
            proposed_interest_rate_bps=450,
        )
        decide_review_request(
            api,
            request["id"],
            decision=ReviewDecision.REDUCED.value,
            assumption_ruling=AssumptionRuling.SUSTAINED.value,
            recomputed_net_assessed_cents=REDUCED_NET_CENTS,
            headers=PLAN_TRUSTEE_SECONDARY_HEADERS,
        )

        refused = api.create_payment_schedule(
            factories.payment_schedule_payload(
                assessment_id,
                issuance_token,
                source=PaymentScheduleSource.REVIEW_DECISION.value,
            ),
            PLAN_ACTUARY_HEADERS,
        )
        validate_error(refused, ApiErrorId.STALE_ASSESSMENT_VERSION.value, 412)

        untouched = list_all_schedules(api, assessment_id)
        assert len(untouched) == 1
        assert untouched[0]["status"] == "ACTIVE"
        blocked = get_assessment(api, assessment_id)
        assert blocked["active_schedule_generation"] == 1
        # PRD 3.8: the recomputed figure is a proposal only until a generation is minted.
        assert blocked["net_assessed_cents"] == BASELINE_NET_ASSESSED_CENTS
        fresh_token = blocked["version"]

        regenerated = validate_success(
            api.create_payment_schedule(
                factories.payment_schedule_payload(
                    assessment_id,
                    fresh_token,
                    source=PaymentScheduleSource.REVIEW_DECISION.value,
                ),
                PLAN_ACTUARY_HEADERS,
            ),
            201,
        )
        assert regenerated["generation_seq"] == 2
        assert regenerated["source"] == "REVIEW_DECISION"
        assert regenerated["applied_credit_cents"] == 0
        assert regenerated["amortization_basis_cents"] == REDUCED_NET_CENTS
        assert regenerated["amortization_years"] == 4
        assert regenerated["forgiven_by_cap_cents"] == 0
        assert regenerated["installment_count"] == REDUCED_INSTALLMENT_COUNT
        assert regenerated["quarterly_installment_cents"] == REDUCED_INSTALLMENT_CENTS
        assert regenerated["final_installment_cents"] == REDUCED_INSTALLMENT_CENTS
        assert regenerated["first_due_date"].startswith("2026-09-30T00:00:00")

        superseded = get_schedule(api, first_generation_id)
        assert superseded["status"] == "SUPERSEDED"
        voided = list_all_installments(api, first_generation_id)
        assert len(voided) == BASELINE_INSTALLMENT_COUNT
        assert {row["status"] for row in voided} == {"VOID"}

        assessment = get_assessment(api, assessment_id)
        assert assessment["award_adjustment_cents"] == (
            BASELINE_NET_ASSESSED_CENTS - REDUCED_NET_CENTS
        )
        assert assessment["net_assessed_cents"] == REDUCED_NET_CENTS
        assert assessment["active_schedule_generation"] == 2
        assert assessment["version"] > fresh_token

        assert get_employer(api, scenario["employer"]["id"])[
            "outstanding_liability_cents"
        ] == REDUCED_NET_CENTS
        group = get_group(api, scenario["group"]["id"])
        assert group["joint_exposure_cents"] == REDUCED_NET_CENTS
        assert group["exposure_score"] == pytest.approx(1500.0, abs=0.0001)


class TestTheImmediateIssuanceCascade:
    def test_the_issue_response_already_carries_every_link_of_the_cascade(self, api):
        """One call mints a generation, twenty-eight instalments, the employer's balance, the
        group's score, the conserved allocation and the event's new status, and every one of
        them is observable at that same instant.

        PRD 3.6: "Alongside the cascade, the anchor valuation's `allocated_uvb_cents` rises
        by `net_assessed_cents` and its `unallocated_uvb_cents` falls by the same amount,
        preserving the plan-UVB conservation rule; the withdrawal event travels from
        `COMPLETE_DETERMINED` or `PARTIAL_DETERMINED` to `ASSESSED`; every *other* draft
        assessment for the same withdrawal event is driven to `RESCINDED`; and the plan's
        `issued_assessment_count` rises by one."

        Design: Corner/consistency_model/the_whole_issuance_cascade_is_visible_in_the_issue_response_itself
        """
        scenario = build_priced_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        assessment_id = scenario["assessment"]["id"]
        assert scenario["assessment"]["net_assessed_cents"] == BASELINE_NET_ASSESSED_CENTS

        issued = validate_success(
            api.issue_liability_assessment(assessment_id, PLAN_TRUSTEE_HEADERS), 200
        )
        assert issued["lifecycle_status"] == "ISSUED"
        assert issued["active_schedule_generation"] == 1
        assert issued["review_deadline_at"].startswith("2026-10-30T00:00:00")
        assert issued["issued_by_user_id"] == TEST_USERS["plan_trustee"]["user_id"]
        assert issued["issued_at"].startswith("2026-08-01T00:00:00")
        assert issued["review_status"] == "NONE"
        assert issued["collection_status"] == "NOT_YET_DUE"

        schedules = list_all_schedules(api, assessment_id)
        assert len(schedules) == 1
        generation = latest_schedule(api, assessment_id)
        assert generation["status"] == "ACTIVE"
        assert generation["amortization_years"] == 7
        assert generation["installment_count"] == BASELINE_INSTALLMENT_COUNT
        assert generation["quarterly_installment_cents"] == BASELINE_QUARTERLY_INSTALLMENT_CENTS
        assert generation["final_installment_cents"] == BASELINE_FINAL_INSTALLMENT_CENTS
        assert generation["first_due_date"].startswith("2026-09-30T00:00:00")

        instalments = list_all_installments(api, generation["id"])
        assert len(instalments) == BASELINE_INSTALLMENT_COUNT
        assert {row["status"] for row in instalments} == {"SCHEDULED"}
        assert sum(row["principal_cents"] for row in instalments) == BASELINE_NET_ASSESSED_CENTS
        assert instalments[0]["due_date"].startswith("2026-09-30T00:00:00")
        assert instalments[0]["delinquent_on"].startswith("2026-11-29T00:00:00")
        assert instalments[-1]["due_date"].startswith("2033-06-30T00:00:00")

        assert get_event(api, scenario["event"]["id"])["status"] == "ASSESSED"
        assert get_employer(api, scenario["employer"]["id"])[
            "outstanding_liability_cents"
        ] == BASELINE_NET_ASSESSED_CENTS
        group = get_group(api, scenario["group"]["id"])
        assert group["joint_exposure_cents"] == BASELINE_NET_ASSESSED_CENTS
        assert group["exposure_score"] == pytest.approx(2500.0, abs=0.0001)

        anchor = get_valuation(api, scenario["valuations"][2025]["id"])
        assert anchor["allocated_uvb_cents"] == BASELINE_NET_ASSESSED_CENTS
        assert anchor["unallocated_uvb_cents"] == (
            BASELINE_UVB_TOTAL_CENTS - BASELINE_NET_ASSESSED_CENTS
        )

        # PRD 3.6: the cascade lands inside the one call, so no lagging second write can
        # move the row afterwards.
        reread = get_assessment(api, assessment_id)
        assert reread == issued
