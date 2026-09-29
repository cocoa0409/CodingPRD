"""Two cross-entity dependencies: an assessment gated on another entity's
certification state, and a determination decided by a field on the employer."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import BASELINE_NET_ASSESSED_CENTS
from test_helpers.fixtures import (
    certify_valuation,
    determine_withdrawal_event,
    file_certified_valuations,
    file_contribution_history,
    get_employer,
    get_event,
    get_valuation,
    register_controlled_group,
    register_employer,
    register_plan,
    report_withdrawal_event,
)
from test_helpers.test_users import PLAN_ACTUARY_HEADERS
from test_helpers.types import (
    AllocationMethod,
    CommonControlBasis,
    CoveredWorkStatus,
    Industry,
    ReportedCause,
)

FULL_HISTORY = (
    {
        "plan_year_start": 2021,
        "plan_year_end": 2025,
        "contribution_base_units": 250_000,
        "contribution_amount_cents": 250_000_000,
        "contribution_rate_cents_per_cbu": 1_000,
    },
)


def _gap_in_the_lookback_window(api):
    """A determined 2026 withdrawal whose 2023 valuation is still in DRAFT."""
    plan = register_plan(
        api,
        allocation_method=AllocationMethod.MODIFIED_PRESUMPTIVE.value,
        de_minimis_variant="STATUTORY",
    )
    group = register_controlled_group(api, common_control_basis=CommonControlBasis.COMBINED.value)
    employer = register_employer(
        api, plan["id"], group["id"], obligation_start_year=2021, cba_count=1
    )
    valuations = file_certified_valuations(
        api, plan["id"], per_year={2023: {"certify_on_create": False}}
    )
    file_contribution_history(api, employer["id"], FULL_HISTORY)
    event = report_withdrawal_event(api, employer["id"])
    determine_withdrawal_event(api, event["id"])
    return {
        "plan": plan,
        "employer": employer,
        "event": event,
        "draft_valuation": valuations[2023],
    }


def _construction_pair(api):
    """Two construction employers reporting the same cessation, one still working."""
    plan = register_plan(
        api,
        industry=Industry.CONSTRUCTION.value,
        allocation_method=AllocationMethod.PRESUMPTIVE.value,
    )
    group = register_controlled_group(
        api, common_control_basis=CommonControlBasis.BROTHER_SISTER.value
    )
    file_certified_valuations(
        api,
        plan["id"],
        years=(2025,),
        uvb_total_cents=8_000_000_000,
        uvb_pool_cents=800_000_000,
    )

    employers = {}
    events = {}
    for key, work_status in (
        ("performing", CoveredWorkStatus.PERFORMING.value),
        ("ceased", CoveredWorkStatus.CEASED.value),
    ):
        employer = register_employer(
            api,
            plan["id"],
            group["id"],
            obligation_start_year=2021,
            covered_work_status=work_status,
            cba_count=1,
        )
        file_contribution_history(api, employer["id"], FULL_HISTORY)
        event = report_withdrawal_event(
            api,
            employer["id"],
            cessation_date="2026-05-01T00:00:00Z",
            reported_cause=ReportedCause.CONTRIBUTION_OBLIGATION_CEASED.value,
        )
        assert event["rules_variant"] == "CONSTRUCTION_RULES"
        employers[key] = employer
        events[key] = determine_withdrawal_event(api, event["id"])
    return employers, events


class TestAssessmentNeedsEveryLookbackValuationCertified:
    def test_a_draft_valuation_inside_the_window_blocks_the_assessment(self, api):
        """The 2023 valuation sits in DRAFT, which is a gap in the five-year window, so the
        assessment cannot be created and the withdrawal event is left as it was.

        PRD 3.5: "Every plan year in the five-year window running from five years before
        the withdrawal plan year through the year immediately preceding it must have a
        certified valuation for the employer's plan; a gap anywhere in that window is
        rejected with `ERR_VALUATION_YEAR_MISSING`."

        Design: Difficulty/cross_entity_state_dependency/assessment_creation_requires_every_lookback_valuation_certified
        """
        scenario = _gap_in_the_lookback_window(api)
        assert scenario["draft_valuation"]["status"] == "DRAFT"

        response = api.create_liability_assessment(
            factories.liability_assessment_payload(scenario["event"]["id"]),
            PLAN_ACTUARY_HEADERS,
        )
        validate_error(response, ApiErrorId.VALUATION_YEAR_MISSING.value, 422)

        assert get_event(api, scenario["event"]["id"])["status"] == "COMPLETE_DETERMINED"

    def test_certifying_the_missing_year_unblocks_the_identical_request(self, api):
        """Certifying the 2023 valuation closes the gap, and the same request now prices the
        withdrawal at 250000000 cents.

        PRD 3.2: "Certification is the `DRAFT → CERTIFIED` transition and is the actuary's
        act: it stamps `certified_by_user_id` with the acting `X-User-ID` and
        `certified_at` with the current logical clock"

        Design: Difficulty/cross_entity_state_dependency/assessment_creation_requires_every_lookback_valuation_certified
        """
        scenario = _gap_in_the_lookback_window(api)
        blocked = api.create_liability_assessment(
            factories.liability_assessment_payload(scenario["event"]["id"]),
            PLAN_ACTUARY_HEADERS,
        )
        validate_error(blocked, ApiErrorId.VALUATION_YEAR_MISSING.value, 422)

        certify_valuation(api, scenario["draft_valuation"]["id"])
        assert get_valuation(api, scenario["draft_valuation"]["id"])["status"] == "CERTIFIED"

        assessment = validate_success(
            api.create_liability_assessment(
                factories.liability_assessment_payload(scenario["event"]["id"]),
                PLAN_ACTUARY_HEADERS,
            ),
            201,
        )
        assert assessment["gross_allocated_cents"] == BASELINE_NET_ASSESSED_CENTS
        assert assessment["net_assessed_cents"] == BASELINE_NET_ASSESSED_CENTS
        assert assessment["lifecycle_status"] == "DRAFT"


class TestConstructionCompleteWithdrawalNeedsCoveredWork:
    def test_an_employer_still_performing_covered_work_withdraws_completely(self, api):
        """Under construction rules the cessation of the contribution obligation is a
        complete withdrawal while covered work continues.

        PRD 3.4: "Under `CONSTRUCTION_RULES` the two complete-withdrawal causes carry an
        additional requirement: cessation of the contribution obligation and cessation of
        covered work each yield `COMPLETE` only while the employer's `covered_work_status`
        is `PERFORMING`, and yield `NONE` when it is `CEASED`."

        Design: Difficulty/cross_entity_state_dependency/construction_complete_withdrawal_requires_employer_still_performing_covered_work
        """
        employers, events = _construction_pair(api)
        event = events["performing"]

        assert event["determined_type"] == "COMPLETE"
        assert event["status"] == "COMPLETE_DETERMINED"
        assert event["partial_withdrawal_fraction"] == pytest.approx(1.0, abs=0.0001)

        employer = get_employer(api, employers["performing"]["id"])
        assert employer["status"] == "COMPLETE_WITHDRAWN"
        assert employer["obligation_end_year"] == 2026

    def test_an_employer_whose_covered_work_ceased_withdraws_not_at_all(self, api):
        """The identical report against an employer whose covered work has ceased
        determines to no withdrawal and leaves that employer contributing.

        PRD 3.4: "A `REPORTED → NO_WITHDRAWAL` determination sets `determined_type` to
        `NONE` and `partial_withdrawal_fraction` to 0.0000 and leaves the employer's
        `status` entirely alone; `NO_WITHDRAWAL` is terminal."

        Design: Difficulty/cross_entity_state_dependency/construction_complete_withdrawal_requires_employer_still_performing_covered_work
        """
        employers, events = _construction_pair(api)
        event = events["ceased"]

        assert event["determined_type"] == "NONE"
        assert event["status"] == "NO_WITHDRAWAL"
        assert event["partial_withdrawal_fraction"] == pytest.approx(0.0, abs=0.0001)

        employer = get_employer(api, employers["ceased"]["id"])
        assert employer["status"] == "CONTRIBUTING"
        assert employer["obligation_end_year"] is None
