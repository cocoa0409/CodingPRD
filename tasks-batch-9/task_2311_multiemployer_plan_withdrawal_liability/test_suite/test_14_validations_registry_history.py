"""Validations on the registry, the certified history and the determination fork:
the global identifier, the supersession interval, the two allocation-input refusals
and the two rule-set refusals."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    build_registry,
    determine_withdrawal_event,
    file_certified_valuations,
    file_contribution_history,
    file_contribution_record,
    get_employer,
    get_event,
    get_plan,
    get_record,
    register_controlled_group,
    register_employer,
    register_plan,
    report_withdrawal_event,
)
from test_helpers.test_users import FUND_ADMINISTRATOR_HEADERS, PLAN_ACTUARY_HEADERS
from test_helpers.types import Industry, ReportedCause

BASELINE_EMPLOYER = {"obligation_start_year": 2021, "cba_count": 1}

# Two plan years that both sit before the five-year allocation window of a 2026
# withdrawal, which runs 2021 through 2025.
OUT_OF_WINDOW_HISTORY = (
    {
        "plan_year_start": 2019,
        "plan_year_end": 2020,
        "contribution_base_units": 200_000,
        "contribution_amount_cents": 200_000_000,
        "contribution_rate_cents_per_cbu": 1_000,
    },
)


class TestTheGlobalEmployerIdentifier:
    def test_the_same_ein_is_refused_under_its_own_plan_and_under_a_second_plan(self, api):
        """Uniqueness is system-wide rather than per plan, so neither repeat lands, and a
        fresh number registers cleanly as the plan's second employer.

        PRD 3.1: "It carries a `legal_name` of 1 to 200 characters and an `ein` of exactly
        nine digits which must be unique across every employer in the system — a repeat is
        rejected with `ERR_DUPLICATE_EIN`."

        Design: Corner/validations/registering_a_second_employer_with_a_duplicate_ein_is_rejected
        """
        plan = register_plan(api)
        group = register_controlled_group(api)
        taken = factories.next_ein()
        first = register_employer(api, plan["id"], group["id"], ein=taken, **BASELINE_EMPLOYER)
        assert first["ein"] == taken

        same_plan = api.create_employer(
            factories.employer_payload(plan["id"], group["id"], ein=taken),
            FUND_ADMINISTRATOR_HEADERS,
        )
        validate_error(same_plan, ApiErrorId.DUPLICATE_EIN.value, 409)

        other_plan = register_plan(api)
        across_plans = api.create_employer(
            factories.employer_payload(other_plan["id"], group["id"], ein=taken),
            FUND_ADMINISTRATOR_HEADERS,
        )
        validate_error(across_plans, ApiErrorId.DUPLICATE_EIN.value, 409)

        second = register_employer(api, plan["id"], group["id"], **BASELINE_EMPLOYER)
        assert second["ein"] != taken
        assert second["version"] == 1
        assert second["status"] == "CONTRIBUTING"
        assert second["outstanding_liability_cents"] == 0
        assert second["obligation_end_year"] is None
        assert second["ceased_cba_count"] == 0
        assert second["credit_watch"] is False
        assert second["delinquency_strikes"] == 0

        assert get_plan(api, plan["id"])["employer_count"] == 2
        assert get_plan(api, other_plan["id"])["employer_count"] == 0

        _rows, meta = validate_paginated(
            api.list_employers(FUND_ADMINISTRATOR_HEADERS, {"plan_id": plan["id"]})
        )
        assert meta["total_count"] == 2


class TestTheSupersessionInterval:
    def test_an_amendment_covering_a_shorter_interval_is_refused_on_the_interval(self, api):
        """The referenced row is excluded from the overlap comparison, so the shorter
        interval surfaces as a period mismatch and the original stays certified.

        PRD 3.3: "When `supersedes_record_id` is supplied, the referenced record must be
        `CERTIFIED`, must belong to the same `employer_id`, and must cover exactly the same
        `plan_year_start` and `plan_year_end`; a reference that fails any of those tests is
        rejected with `ERR_SUPERSEDED_RECORD_PERIOD_MISMATCH`, while an identifier that
        resolves to nothing is rejected with `ERR_CONTRIBUTION_RECORD_NOT_FOUND`."

        Design: Corner/validations/superseding_a_record_that_covers_a_different_interval_is_rejected
        """
        registry = build_registry(api, employer_overrides=BASELINE_EMPLOYER)
        employer_id = registry["employer"]["id"]

        original = file_contribution_record(api, employer_id, 2021, 2025)
        assert original["status"] == "CERTIFIED"
        assert original["employer_version_at_apply"] == 2
        assert get_employer(api, employer_id)["version"] == 2

        response = api.create_contribution_record(
            factories.contribution_record_payload(
                employer_id, 2021, 2024, 2, supersedes_record_id=original["id"]
            ),
            FUND_ADMINISTRATOR_HEADERS,
        )
        validate_error(
            response, ApiErrorId.SUPERSEDED_RECORD_PERIOD_MISMATCH.value, 422
        )

        assert get_record(api, original["id"])["status"] == "CERTIFIED"
        assert get_employer(api, employer_id)["version"] == 2
        _rows, meta = validate_paginated(
            api.list_contribution_records(
                FUND_ADMINISTRATOR_HEADERS, {"employer_id": employer_id}
            )
        )
        assert meta["total_count"] == 1


class TestTheAllocationInputs:
    def test_history_that_stops_short_of_the_window_leaves_nothing_to_allocate(self, api):
        """Every valuation year is certified and the event is determined, so the only
        obstacle is a history that ends the year before the window opens.

        PRD 3.5: "And at least one certified contribution record must cover at least one plan
        year in that same five-year window; where none does, the request is rejected with
        `ERR_EMPTY_CONTRIBUTION_WINDOW`."

        Design: Corner/validations/an_allocation_window_with_no_certified_records_is_rejected
        """
        registry = build_registry(api, employer_overrides=BASELINE_EMPLOYER)
        employer_id = registry["employer"]["id"]
        file_certified_valuations(api, registry["plan"]["id"])
        file_contribution_history(api, employer_id, OUT_OF_WINDOW_HISTORY)

        event = determine_withdrawal_event(
            api, report_withdrawal_event(api, employer_id)["id"]
        )
        assert event["status"] == "COMPLETE_DETERMINED"

        response = api.create_liability_assessment(
            factories.liability_assessment_payload(event["id"]), PLAN_ACTUARY_HEADERS
        )
        validate_error(response, ApiErrorId.EMPTY_CONTRIBUTION_WINDOW.value, 422)

        _rows, meta = validate_paginated(
            api.list_liability_assessments(
                FUND_ADMINISTRATOR_HEADERS, {"withdrawal_event_id": event["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert get_event(api, event["id"])["status"] == "COMPLETE_DETERMINED"

    def test_a_window_of_zero_base_units_cannot_be_amortised_at_all(self, api):
        """The record is perfectly valid and remitted real money, but a level annual payment
        of nothing has no amortisation, so the demand never comes into being.

        PRD 3.5: "A contribution history that yields an annual payment of 0 cannot be
        amortised at all, and the assessment is rejected with `ERR_ANNUAL_PAYMENT_ZERO`."

        Design: Corner/validations/an_assessment_whose_annual_payment_is_zero_is_rejected
        """
        registry = build_registry(api, employer_overrides=BASELINE_EMPLOYER)
        employer_id = registry["employer"]["id"]
        file_certified_valuations(api, registry["plan"]["id"])

        # PRD 3.3: all three monetary figures must be at least 0, so no base units at all
        # is a legitimate filing.
        record = file_contribution_record(
            api,
            employer_id,
            2021,
            2025,
            contribution_base_units=0,
            contribution_amount_cents=100_000_000,
            contribution_rate_cents_per_cbu=1_000,
        )
        assert record["status"] == "CERTIFIED"
        assert record["contribution_base_units"] == 0

        event = determine_withdrawal_event(
            api, report_withdrawal_event(api, employer_id)["id"]
        )

        response = api.create_liability_assessment(
            factories.liability_assessment_payload(event["id"]), PLAN_ACTUARY_HEADERS
        )
        validate_error(response, ApiErrorId.ANNUAL_PAYMENT_ZERO.value, 422)

        _rows, meta = validate_paginated(
            api.list_liability_assessments(
                FUND_ADMINISTRATOR_HEADERS, {"withdrawal_event_id": event["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert get_event(api, event["id"])["status"] == "COMPLETE_DETERMINED"


class TestTheDeterminationFork:
    def test_a_bargaining_agreement_partial_with_nothing_ceased_is_refused(self, api):
        """Zero ceased agreements is neither a complete withdrawal nor a partial one, so the
        event keeps its reported shape and the employer keeps contributing.

        PRD 3.4: "A partial cessation of bargaining agreements yields `COMPLETE` when
        `ceased_cba_count` is greater than or equal to the employer's `cba_count`, yields
        `PARTIAL_CBA_CESSATION` when `ceased_cba_count` is greater than 0 and strictly less
        than the employer's `cba_count`, and is rejected with
        `ERR_CBA_CESSATION_COUNT_INVALID` when `ceased_cba_count` is 0."

        Design: Corner/validations/determining_a_cba_partial_cessation_with_no_ceased_agreements_is_rejected
        """
        registry = build_registry(
            api, employer_overrides={"obligation_start_year": 2021, "cba_count": 3}
        )
        employer_id = registry["employer"]["id"]
        file_certified_valuations(api, registry["plan"]["id"], years=(2025,))

        event = report_withdrawal_event(
            api,
            employer_id,
            reported_cause=ReportedCause.CBA_PARTIAL_CESSATION.value,
            ceased_cba_count=0,
        )
        assert event["rules_variant"] == "GENERAL_RULES"
        assert event["ceased_cba_count"] == 0

        response = api.determine_withdrawal_event(event["id"], PLAN_ACTUARY_HEADERS)
        validate_error(response, ApiErrorId.CBA_CESSATION_COUNT_INVALID.value, 422)

        undetermined = get_event(api, event["id"])
        assert undetermined["status"] == "REPORTED"
        assert undetermined["determined_type"] == "NONE"
        assert undetermined["determined_at"] is None
        assert undetermined["ceased_cba_count"] == 0
        assert undetermined["partial_withdrawal_fraction"] == pytest.approx(0.0, abs=0.0001)

        employer = get_employer(api, employer_id)
        assert employer["status"] == "CONTRIBUTING"
        assert employer["ceased_cba_count"] == 0
        assert employer["obligation_end_year"] is None
        assert employer["version"] == 1

    def test_construction_rules_have_no_base_unit_decline_partial_at_all(self, api):
        """The employer still performs covered work and the valuation year is certified, yet
        the decline apparatus simply does not exist under construction rules.

        PRD 3.4: "The partial-withdrawal apparatus is narrower: a reported base-unit decline
        and a reported facility cessation are both rejected with
        `ERR_PARTIAL_WITHDRAWAL_NOT_AVAILABLE`, because neither the decline test nor the
        facility partial applies to the construction industry."

        Design: Corner/validations/a_cbu_decline_partial_withdrawal_is_not_available_under_construction_rules
        """
        registry = build_registry(
            api,
            plan_overrides={"industry": Industry.CONSTRUCTION.value},
            employer_overrides=BASELINE_EMPLOYER,
        )
        employer_id = registry["employer"]["id"]
        file_certified_valuations(api, registry["plan"]["id"], years=(2025,))

        event = report_withdrawal_event(
            api, employer_id, reported_cause=ReportedCause.CBU_DECLINE.value
        )
        assert event["rules_variant"] == "CONSTRUCTION_RULES"

        response = api.determine_withdrawal_event(event["id"], PLAN_ACTUARY_HEADERS)
        validate_error(
            response, ApiErrorId.PARTIAL_WITHDRAWAL_NOT_AVAILABLE.value, 422
        )

        undetermined = get_event(api, event["id"])
        assert undetermined["status"] == "REPORTED"
        assert undetermined["determined_type"] == "NONE"
        assert undetermined["determined_at"] is None
        # PRD 3.4: with no certified record anywhere the base-year pool averages 0, and the
        # ratio is recorded as 0.000000 whenever that average is 0.
        assert undetermined["decline_ratio"] == pytest.approx(0.0, abs=0.000001)
        assert undetermined["partial_withdrawal_fraction"] == pytest.approx(0.0, abs=0.0001)

        employer = get_employer(api, employer_id)
        assert employer["status"] == "CONTRIBUTING"
        assert employer["obligation_end_year"] is None
        assert employer["version"] == 1
