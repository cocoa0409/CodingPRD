"""One submit request that breaks two rules at once answers with the higher-priority one, and
the plan-review and one-cycle-per-year guards read on the same camp."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    cycle_payload,
    health_center_payload,
    plan_review_payload,
    self_assessment_payload,
)
from test_helpers.test_users import OFFICER_ONE_HEADERS
from test_helpers.types import (
    CampType,
    CompliancePosture,
    CycleStatus,
    HealthStaffingLevel,
    PlanReviewDecision,
    PlanType,
    PopulationServed,
    SelfScore,
    SelfStatus,
    StandardDomain,
    WrittenPlanStatus,
)
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

GAP_STANDARDS = [
    fx.universal_mandatory_standard(
        "SU.1", domain=StandardDomain.SUPERVISION, scoring_weight=1
    ),
    {
        "code": "OM.2",
        "title": "Day camp arrival logs",
        "domain": StandardDomain.OPERATIONS,
        "mandatory": False,
        "scoring_weight": 1,
        "applies_to_camp_types": [CampType.DAY],
    },
]


def _camp_whose_health_centre_lags_its_requirement(api):
    """A medically fragile resident camp staffed one rank below what its own numbers demand."""
    fx.reset_clock(api)
    return fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-GAP",
        standards=GAP_STANDARDS,
        camp={
            "name": "Staffing Gap Camp",
            "camp_type": CampType.RESIDENT,
            "state_code": "OH",
            "population_served": PopulationServed.MEDICALLY_FRAGILE,
            "resident_census": 200,
            "distance_to_hospital_km": 45,
            "health_staffing_level": HealthStaffingLevel.RN_ONSITE,
        },
    )


def _the_same_camp_once_a_physician_is_on_site(api):
    """The staffing gap closed, leaving the incompleteness as the only remaining fault."""
    scenario = _camp_whose_health_centre_lags_its_requirement(api)
    upgraded = validate_success(
        api.patch_health_center(
            scenario.camp_id,
            health_center_payload(health_staffing_level=HealthStaffingLevel.PHYSICIAN_ONSITE),
            scenario.health_staff_headers,
        )
    )
    assert upgraded["health_staffing_level"] == HealthStaffingLevel.PHYSICIAN_ONSITE
    assert upgraded["required_health_staffing_level"] == HealthStaffingLevel.PHYSICIAN_ONSITE
    assert upgraded["compliance_posture"] == CompliancePosture.OPEN
    return scenario.refresh(api)


def _submit(api, scenario):
    return api.submit_self_assessment(scenario.cycle_id, scenario.director_headers)


def test_the_staffing_gate_answers_before_the_completeness_gate_on_one_submit(api):
    """PRD §3.4: "Two gates apply, and they are evaluated in the order the ladder of §2.5
    dictates: first the staffing gate, then the completeness gate."

    Design: Corner/validations/staffing_rank_check_outranks_self_assessment_completeness_on_the_same_submit
    """
    scenario = _camp_whose_health_centre_lags_its_requirement(api)
    assert scenario.camp["health_staffing_level"] == HealthStaffingLevel.RN_ONSITE
    assert scenario.camp["required_health_staffing_level"] == HealthStaffingLevel.PHYSICIAN_ONSITE
    assert scenario.camp["compliance_posture"] == CompliancePosture.RESTRICTED

    # The OPERATIONS row was frozen inapplicable by the DAY gate, so it takes no verdict.
    validate_error(
        api.patch_self_assessment(
            scenario.evaluation_id("OM.2"),
            self_assessment_payload(SelfScore.MET),
            scenario.director_headers,
        ),
        ApiErrorId.STANDARD_NOT_APPLICABLE,
        422,
    )

    # The mandatory row carries no self_score either, and the staffing rank still answers.
    validate_error(_submit(api, scenario), ApiErrorId.HEALTH_STAFFING_INSUFFICIENT, 422)
    assert fx.read_cycle(api, scenario.cycle_id)["self_assessment_submitted_at"] is None


def test_closing_the_staffing_gap_uncovers_the_completeness_gate_beneath_it(api):
    """PRD §3.4: "Then every applicable evaluation on the cycle must carry a non-null
    `self_score` and sit in `self_status` `SUBMITTED`, or the submission is rejected with
    `ERR_SELF_ASSESSMENT_INCOMPLETE` (HTTP 422)."

    Design: Corner/validations/staffing_rank_check_outranks_self_assessment_completeness_on_the_same_submit
    """
    scenario = _the_same_camp_once_a_physician_is_on_site(api)

    validate_error(_submit(api, scenario), ApiErrorId.SELF_ASSESSMENT_INCOMPLETE, 422)

    fx.record_self_score(api, scenario.evaluation_id("SU.1"), scenario.camp_id, SelfScore.MET)
    submitted = validate_success(_submit(api, scenario))
    assert is_iso8601_timestamp(submitted["self_assessment_submitted_at"])
    assert submitted["self_assessment_submitted_at"].startswith("2026-08-01T00:00:00")
    assert submitted["status"] == CycleStatus.SELF_ASSESSMENT

    assert fx.read_evaluation(api, scenario.evaluation_id("SU.1"))["self_status"] == (
        SelfStatus.VERIFIED
    )
    # The inapplicable row was never required to carry a verdict and did not move.
    untouched = fx.read_evaluation(api, scenario.evaluation_id("OM.2"))
    assert untouched["applicable"] is False
    assert untouched["self_score"] is None
    assert untouched["self_status"] == SelfStatus.DRAFT


def test_a_second_cycle_for_the_same_year_is_refused_rather_than_superseding(api):
    """PRD §3.3: "A second cycle for the same camp and the same `cycle_year` is rejected with
    `ERR_DUPLICATE_CYCLE_YEAR` (HTTP 409)."

    Design: Corner/validations/staffing_rank_check_outranks_self_assessment_completeness_on_the_same_submit
    """
    scenario = _the_same_camp_once_a_physician_is_on_site(api)

    validate_error(
        api.create_cycle(
            cycle_payload(
                scenario.camp_id,
                scenario.edition["id"],
                fx.read_camp(api, scenario.camp_id)["version"],
                2026,
            ),
            OFFICER_ONE_HEADERS,
        ),
        ApiErrorId.DUPLICATE_CYCLE_YEAR,
        409,
    )

    rows, meta = validate_paginated(
        api.list_cycles({"camp_id": scenario.camp_id}, OFFICER_ONE_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == scenario.cycle_id


def test_a_health_care_plan_cannot_be_verified_before_a_physician_reviews_it(api):
    """PRD §3.4: "A `HEALTH_CARE` plan may only reach `VERIFIED` when its `physician_reviewed`
    flag is true; otherwise the review is rejected with `ERR_PHYSICIAN_REVIEW_REQUIRED` (HTTP
    422)."

    Design: Corner/validations/staffing_rank_check_outranks_self_assessment_completeness_on_the_same_submit
    """
    scenario = _the_same_camp_once_a_physician_is_on_site(api)
    plan = fx.file_plan(
        api,
        scenario.camp_id,
        PlanType.HEALTH_CARE,
        body_ref="plan/health-care/v1",
        effective_date="2026-08-01",
        expires_at="2027-08-01",
        physician_reviewed=False,
        as_health_care_staff=True,
    )
    assert plan["status"] == WrittenPlanStatus.SUBMITTED

    validate_error(
        api.review_written_plan(
            plan["id"],
            plan_review_payload(PlanReviewDecision.VERIFY, "health care plan review"),
            OFFICER_ONE_HEADERS,
        ),
        ApiErrorId.PHYSICIAN_REVIEW_REQUIRED,
        422,
    )
    held = fx.read_plan(api, plan["id"])
    assert held["status"] == WrittenPlanStatus.SUBMITTED
    assert held["verified_at"] is None

    # The same officer may still refuse the plan outright.
    rejected = fx.reject_plan(api, plan["id"], "no physician sign off on file")
    assert rejected["status"] == WrittenPlanStatus.REJECTED
