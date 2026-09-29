"""Job family risk scoring: the variant premium, the empty family and the weighted mean."""

from typing import Any, Dict

import pytest

from test_helpers import (
    AUDITOR_HEADERS,
    CLASSIFICATION_REVIEWER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    DutiesValidationStatus,
    ExemptionTest,
    ProjectStatus,
    RespondentType,
    assert_family_risk,
    assert_one_decimal,
    assert_project_ledgers,
    factories,
    fixtures,
    get_success_data,
    validate_success,
)


@pytest.fixture
def engineering_family(api, pinned_clock) -> Dict[str, Any]:
    """One job whose duty and hours figures are identical corroborated or not."""
    fixtures.register_state_rule(
        api,
        factories.california_rule_payload(
            liquidated_damages_multiplier=1.0, back_wage_lookback_weeks_override=156
        ),
    )
    project = fixtures.create_project(api)
    family = fixtures.create_family(api, project["id"], name="Field Engineering", code="FLD-ENG")
    fixtures.advance_project(api, project["id"], ProjectStatus.FIELDWORK)
    position = fixtures.create_position(
        api,
        family["id"],
        title="Systems Engineer",
        job_code="SE-200",
        claimed_exemption_test=ExemptionTest.PROFESSIONAL,
        annual_salary_cents=8000000,
        incumbent_count=3,
        avg_weekly_hours=49,
        requires_advanced_degree=True,
    )
    fixtures.add_duty(
        api,
        position["id"],
        duty_code="E-EX",
        description="Designs and reviews system architecture",
        claimed_time_pct=49.6,
        is_exempt_duty=True,
    )
    fixtures.add_duty(
        api,
        position["id"],
        duty_code="E-NX",
        description="Executes scripted test runs",
        claimed_time_pct=50.4,
        is_exempt_duty=False,
        discretion_level="ROUTINE",
    )
    manager = fixtures.book_interview(
        api,
        position["id"],
        "int-2",
        ("2026-09-14T09:00:00Z", "2026-09-14T10:00:00Z"),
        RespondentType.MANAGER,
        "MGR-E",
    )
    fixtures.complete_interview(api, manager["id"], (46.0, 49, 0, False))
    fixtures.attest_interview(api, manager["id"])
    incumbent = fixtures.book_interview(
        api,
        position["id"],
        "int-2",
        ("2026-09-15T09:00:00Z", "2026-09-15T10:00:00Z"),
        RespondentType.INCUMBENT,
        "INC-E",
    )
    fixtures.complete_interview(api, incumbent["id"], (52.0, 49, 0, False))
    fixtures.attest_interview(api, incumbent["id"])
    return {
        "project_id": project["id"],
        "family_id": family["id"],
        "position_id": position["id"],
        "incumbent_interview": incumbent,
    }


@pytest.fixture
def umbrella_and_child_family(api, pinned_clock) -> Dict[str, Any]:
    """A parent family holding no jobs of its own above a child family that holds one."""
    fixtures.register_state_rule(
        api,
        factories.california_rule_payload(
            liquidated_damages_multiplier=1.0, back_wage_lookback_weeks_override=156
        ),
    )
    project = fixtures.create_project(api)
    parent = fixtures.create_family(
        api, project["id"], name="Operations Umbrella", code="OPS-UMB"
    )
    child = fixtures.create_family(
        api,
        project["id"],
        name="Shift Leadership",
        code="OPS-SHIFT",
        parent_family_id=parent["id"],
    )
    fixtures.advance_project(api, project["id"], ProjectStatus.FIELDWORK)
    position = fixtures.create_position(api, child["id"])
    return {
        "project_id": project["id"],
        "parent_family_id": parent["id"],
        "child_family_id": child["id"],
        "position_id": position["id"],
    }


def test_corroborated_family_scores_without_the_uncertainty_premium(api, engineering_family):
    """With every job's duties validated the family carries no premium.

    PRD: "**Hours risk.** Take the position's `validated_weekly_hours` less the standard 40-hour
    workweek, treating any negative result as 0, multiply by 2, round half up to a whole number,
    and cap the component at 20."

    Design: Difficulty/dual_variant_calc/job_family_risk_screening_premium_is_the_only_delta_versus_evidence_weighted
    """
    family = get_success_data(api.get_job_family(engineering_family["family_id"], AUDITOR_HEADERS))

    assert_family_risk(family, 58, "HIGH", variant="EVIDENCE_WEIGHTED", headcount=3)

    position = fixtures.read_position(api, engineering_family["position_id"])
    assert position["duties_validation_status"] == DutiesValidationStatus.CORROBORATED, (
        f"both accounts are attested, got {position['duties_validation_status']}"
    )
    assert_one_decimal(position["primary_duty_pct"], 49.6, "primary_duty_pct")
    assert position["validated_weekly_hours"] == 49, (
        f"both accounts reported 49 hours, got {position['validated_weekly_hours']}"
    )


def test_voiding_one_account_adds_exactly_the_screening_premium(api, engineering_family):
    """The duty and hours figures do not move, so the whole delta is the premium.

    PRD: "So the identical set of positions scores 12 points higher under `SCREENING` than under
    `EVIDENCE_WEIGHTED`."

    Design: Difficulty/dual_variant_calc/job_family_risk_screening_premium_is_the_only_delta_versus_evidence_weighted
    """
    before = get_success_data(api.get_job_family(engineering_family["family_id"], AUDITOR_HEADERS))

    get_success_data(
        api.void_interview(
            engineering_family["incumbent_interview"]["id"],
            {"void_reason": "Incumbent account withdrawn pending re-interview"},
            CLASSIFICATION_REVIEWER_HEADERS,
        )
    )

    after = get_success_data(api.get_job_family(engineering_family["family_id"], AUDITOR_HEADERS))
    assert_family_risk(after, 70, "HIGH", variant="SCREENING", headcount=3)
    assert after["risk_score"] - before["risk_score"] == 12, (
        "the whole movement must be the uncertainty premium, got "
        f"{after['risk_score']} - {before['risk_score']}"
    )

    position = fixtures.read_position(api, engineering_family["position_id"])
    assert position["duties_validation_status"] == DutiesValidationStatus.PENDING, (
        f"one voided account breaks the pair, got {position['duties_validation_status']}"
    )
    assert_one_decimal(position["primary_duty_pct"], 49.6, "primary_duty_pct after the void")
    assert position["validated_weekly_hours"] == 49, (
        f"the hours figure must not move, got {position['validated_weekly_hours']}"
    )


def test_parent_only_family_short_circuits_to_zero(api, umbrella_and_child_family):
    """A family with no jobs of its own never divides by a zero headcount.

    PRD: "An empty family short-circuits: when `family_headcount` is 0, `risk_variant` is
    `EVIDENCE_WEIGHTED`, `risk_score` is 0 and `risk_tier` is `LOW`, with no division performed and
    no uncertainty premium added."

    Design: Difficulty/boundary_precision_check/empty_and_parent_only_family_scores_zero_without_dividing_by_headcount
    """
    parent = get_success_data(
        api.get_job_family(umbrella_and_child_family["parent_family_id"], AUDITOR_HEADERS)
    )

    assert_family_risk(
        parent, 0, "LOW", variant="EVIDENCE_WEIGHTED", headcount=0, misclassified=0
    )
    assert parent["remediation_priority_rank"] is None, (
        f"the rank stays null outside remediation, got {parent['remediation_priority_rank']!r}"
    )


def test_the_child_family_scores_on_its_own_population(api, umbrella_and_child_family):
    """The child's real score proves the parent's zero is a short-circuit, not an omission.

    PRD: "**Salary risk.** Take the position's annual salary divided by 52 and truncated to a whole
    cent. Compute a comfort threshold as the applicable salary floor multiplied by 1.15 and rounded
    half up to a whole cent. The component is 0 when the weekly figure is at or above that comfort
    threshold, 15 when it is below the comfort threshold but at or above the applicable salary floor
    itself, and 30 when it is below the applicable salary floor."

    Design: Difficulty/boundary_precision_check/empty_and_parent_only_family_scores_zero_without_dividing_by_headcount
    """
    child = get_success_data(
        api.get_job_family(umbrella_and_child_family["child_family_id"], AUDITOR_HEADERS)
    )

    assert_family_risk(child, 96, "CRITICAL", variant="SCREENING", headcount=2)
    assert child["parent_family_id"] == umbrella_and_child_family["parent_family_id"], (
        "the child must still point at its parent"
    )

    project = fixtures.read_project(api, umbrella_and_child_family["project_id"])
    assert_project_ledgers(project, headcount=0)


def test_family_risk_is_headcount_weighted_not_a_plain_average(api, pinned_clock):
    """A small high-risk job beside a large low-risk one must be weighted by incumbents.

    PRD: "The roll-up itself is a **headcount-weighted mean, not a plain mean**: multiply each
    position's capped risk total by that position's `incumbent_count`, sum those products across
    the population, and divide by `family_headcount`."

    Design: Corner/calculations/family_risk_is_headcount_weighted_not_a_plain_average_of_positions
    """
    fixtures.register_state_rule(api, factories.california_rule_payload())
    project = fixtures.create_project(api)
    family = fixtures.create_family(api, project["id"])
    fixtures.advance_project(api, project["id"], ProjectStatus.FIELDWORK)
    fixtures.create_position(
        api,
        family["id"],
        title="Shift Supervisor",
        job_code="SS-410",
        annual_salary_cents=5500000,
        incumbent_count=1,
        avg_weekly_hours=47,
    )

    validate_success(
        api.create_position(
            factories.position_payload(
                family["id"],
                title="Regional Director",
                job_code="RD-420",
                annual_salary_cents=20000000,
                incumbent_count=20,
                avg_weekly_hours=40,
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        201,
    )

    scored = get_success_data(api.get_job_family(family["id"], AUDITOR_HEADERS))
    assert_family_risk(scored, 54, "MEDIUM", variant="SCREENING", headcount=21, misclassified=0)
