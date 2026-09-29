"""Floor resolution and the two jurisdictional legs of an exemption analysis."""

from typing import Any, Dict

import pytest

from test_helpers import (
    AnalysisOutcome,
    AnalysisStatus,
    ExemptionTest,
    ProjectStatus,
    RespondentType,
    SalaryThresholdSource,
    assert_money,
    assert_one_decimal,
    factories,
    fixtures,
)

FLAT_ACCOUNT = (80.0, 42, 0, False)


def _attest_pair(api, position_id, interviewer, windows, account, refs):
    manager = fixtures.book_interview(
        api, position_id, interviewer, windows[0], RespondentType.MANAGER, refs[0]
    )
    fixtures.complete_interview(api, manager["id"], account)
    fixtures.attest_interview(api, manager["id"])
    incumbent = fixtures.book_interview(
        api, position_id, interviewer, windows[1], RespondentType.INCUMBENT, refs[1]
    )
    fixtures.complete_interview(api, incumbent["id"], account)
    fixtures.attest_interview(api, incumbent["id"])


@pytest.fixture
def california_actuary_analysis(api, pinned_clock) -> Dict[str, Any]:
    """A well-paid California professional whose weekly salary sits under the state floor."""
    fixtures.register_state_rule(
        api,
        factories.california_rule_payload(
            liquidated_damages_multiplier=1.0, back_wage_lookback_weeks_override=156
        ),
    )
    project = fixtures.create_project(api)
    family = fixtures.create_family(api, project["id"], name="Professional Staff", code="PROF")
    fixtures.advance_project(api, project["id"], ProjectStatus.FIELDWORK)
    position = fixtures.create_position(
        api,
        family["id"],
        title="Staff Actuary",
        job_code="ACT-300",
        claimed_exemption_test=ExemptionTest.PROFESSIONAL,
        annual_salary_cents=5000000,
        incumbent_count=1,
        avg_weekly_hours=42,
        requires_advanced_degree=True,
    )
    fixtures.add_duty(
        api,
        position["id"],
        duty_code="A-EX",
        description="Builds and signs off reserve models",
        claimed_time_pct=80,
        is_exempt_duty=True,
    )
    fixtures.add_duty(
        api,
        position["id"],
        duty_code="A-NX",
        description="Compiles routine data extracts",
        claimed_time_pct=20,
        is_exempt_duty=False,
        discretion_level="ROUTINE",
    )
    _attest_pair(
        api,
        position["id"],
        "int-3",
        (
            ("2026-09-16T09:00:00Z", "2026-09-16T10:00:00Z"),
            ("2026-09-17T09:00:00Z", "2026-09-17T10:00:00Z"),
        ),
        FLAT_ACCOUNT,
        ("MGR-A", "INC-A"),
    )
    analysis = fixtures.author_analysis(
        api, position["id"], applied_test=ExemptionTest.PROFESSIONAL
    )
    submitted = fixtures.submit_analysis(api, analysis["id"])
    return {"position_id": position["id"], "analysis": submitted}


@pytest.fixture
def texas_floor_boundary(api, pinned_clock) -> Dict[str, Any]:
    """Two Texas therapists whose weekly salaries land on and one cent under the federal floor."""
    fixtures.register_state_rule(
        api,
        factories.texas_rule_payload(
            hce_shortcut_recognized=True, liquidated_damages_multiplier=1.0
        ),
    )
    project = fixtures.create_project(api, name="FY26 Texas Sweep")
    family = fixtures.create_family(
        api, project["id"], name="Clinical Professionals", code="CLIN-PRO"
    )
    fixtures.advance_project(api, project["id"], ProjectStatus.FIELDWORK)
    at_floor = fixtures.create_position(
        api,
        family["id"],
        title="Staff Therapist At Floor",
        job_code="ST-401",
        claimed_exemption_test=ExemptionTest.PROFESSIONAL,
        annual_salary_cents=4388800,
        work_state_code="TX",
        incumbent_count=1,
        avg_weekly_hours=42,
        requires_advanced_degree=True,
    )
    below_floor = fixtures.create_position(
        api,
        family["id"],
        title="Staff Therapist Below Floor",
        job_code="ST-402",
        claimed_exemption_test=ExemptionTest.PROFESSIONAL,
        annual_salary_cents=4388748,
        work_state_code="TX",
        incumbent_count=1,
        avg_weekly_hours=42,
        requires_advanced_degree=True,
    )
    _attest_pair(
        api,
        at_floor["id"],
        "int-2",
        (
            ("2026-09-14T09:00:00Z", "2026-09-14T10:00:00Z"),
            ("2026-09-14T10:00:00Z", "2026-09-14T11:00:00Z"),
        ),
        FLAT_ACCOUNT,
        ("MGR-A", "INC-A"),
    )
    _attest_pair(
        api,
        below_floor["id"],
        "int-2",
        (
            ("2026-09-14T11:00:00Z", "2026-09-14T12:00:00Z"),
            ("2026-09-14T12:00:00Z", "2026-09-14T13:00:00Z"),
        ),
        FLAT_ACCOUNT,
        ("MGR-B", "INC-B"),
    )
    at_analysis = fixtures.submit_analysis(
        api,
        fixtures.author_analysis(api, at_floor["id"], applied_test=ExemptionTest.PROFESSIONAL)["id"],
    )
    below_analysis = fixtures.submit_analysis(
        api,
        fixtures.author_analysis(api, below_floor["id"], applied_test=ExemptionTest.PROFESSIONAL)[
            "id"
        ],
    )
    return {
        "at_floor_position_id": at_floor["id"],
        "below_floor_position_id": below_floor["id"],
        "at_analysis": at_analysis,
        "below_analysis": below_analysis,
    }


def test_state_floor_resolution_snapshots_the_higher_state_floor(api, california_actuary_analysis):
    """The applicable floor is the greater of the two, and the source names the state.

    PRD: "The `salary_threshold_source` records `STATE` when the jurisdiction's weekly floor
    **strictly exceeds** the federal floor, and `FEDERAL` otherwise -- so a state floor that
    merely equals the federal floor is reported as `FEDERAL`."

    Design: Difficulty/combinatorial_formula/exemption_same_position_evaluated_twice_federal_pass_state_fail
    """
    analysis = california_actuary_analysis["analysis"]

    assert analysis["status"] == AnalysisStatus.SUBMITTED, (
        f"submission must advance the analysis to SUBMITTED, got {analysis['status']}"
    )
    assert_money(analysis["weekly_salary_cents_snapshot"], 96153, "weekly_salary_cents_snapshot")
    assert_one_decimal(analysis["primary_duty_pct_snapshot"], 80.0, "primary_duty_pct_snapshot")
    assert_money(
        analysis["applicable_salary_floor_cents"], 132000, "applicable_salary_floor_cents"
    )
    assert analysis["applicable_duty_floor_pct"] == 50.0, (
        "the quantitative variant carries a 50.0 percent floor, got "
        f"{analysis['applicable_duty_floor_pct']}"
    )
    assert analysis["salary_threshold_source"] == SalaryThresholdSource.STATE, (
        f"the state floor strictly exceeds the federal one, got {analysis['salary_threshold_source']}"
    )


def test_the_two_legs_disagree_when_only_the_state_floor_bites(api, california_actuary_analysis):
    """One evaluation produces a passing federal leg and a failing state leg at once.

    PRD: "Because the state leg adds a recognition requirement, a higher salary floor, a possibly
    higher duty floor, and a jurisdictional veto over the shortcut, a position can pass federally
    and still fail on the state leg."

    Design: Difficulty/combinatorial_formula/exemption_same_position_evaluated_twice_federal_pass_state_fail
    """
    analysis = california_actuary_analysis["analysis"]

    assert analysis["federal_pass"] is True, (
        f"96153 clears the federal 84400 floor with an 80 percent duty share, got {analysis['federal_pass']}"
    )
    assert analysis["state_pass"] is False, (
        f"96153 falls short of the 132000 state floor, got {analysis['state_pass']}"
    )
    assert analysis["hce_shortcut_applied"] is False, (
        "a 50,000 dollar salary is nowhere near the highly-compensated floor, got "
        f"{analysis['hce_shortcut_applied']}"
    )
    assert analysis["outcome"] == AnalysisOutcome.NONEXEMPT, (
        f"only two passing legs produce EXEMPT, got {analysis['outcome']}"
    )


def test_weekly_salary_exactly_at_the_federal_floor_passes_both_legs(api, texas_floor_boundary):
    """A weekly salary equal to the floor satisfies the greater-than-or-equal comparison.

    PRD: "Otherwise, when the position's `salary_basis` is anything other than `HOURLY`, the leg
    passes exactly when the weekly salary is greater than or equal to the given floor."

    Design: Difficulty/boundary_precision_check/state_salary_floor_boundary_is_exact_to_the_cent
    """
    position = fixtures.read_position(api, texas_floor_boundary["at_floor_position_id"])
    assert_money(position["weekly_salary_cents"], 84400, "at-floor weekly_salary_cents")

    analysis = texas_floor_boundary["at_analysis"]
    assert_money(analysis["applicable_salary_floor_cents"], 84400, "applicable_salary_floor_cents")
    assert analysis["applicable_duty_floor_pct"] == 50.0, (
        f"the federal variant carries a 50.0 percent floor, got {analysis['applicable_duty_floor_pct']}"
    )
    assert analysis["salary_threshold_source"] == SalaryThresholdSource.FEDERAL, (
        "a state floor below the federal one is reported as FEDERAL, got "
        f"{analysis['salary_threshold_source']}"
    )
    assert analysis["hce_shortcut_applied"] is False, (
        f"the shortcut is not what carried this analysis, got {analysis['hce_shortcut_applied']}"
    )
    assert analysis["federal_pass"] is True, f"the federal leg must pass, got {analysis['federal_pass']}"
    assert analysis["state_pass"] is True, f"the state leg must pass, got {analysis['state_pass']}"
    assert analysis["outcome"] == AnalysisOutcome.EXEMPT, (
        f"two passing legs produce EXEMPT, got {analysis['outcome']}"
    )


def test_one_cent_below_the_federal_floor_fails_the_salary_leg(api, texas_floor_boundary):
    """A single cent of weekly salary flips the salary leg and therefore the outcome.

    PRD: "The `applicable_salary_floor_cents` is the greater of the federal weekly floor of 84,400
    cents and the jurisdiction's `min_weekly_salary_cents`."

    Design: Difficulty/boundary_precision_check/state_salary_floor_boundary_is_exact_to_the_cent
    """
    position = fixtures.read_position(api, texas_floor_boundary["below_floor_position_id"])
    assert_money(position["weekly_salary_cents"], 84399, "below-floor weekly_salary_cents")

    analysis = texas_floor_boundary["below_analysis"]
    assert_money(analysis["applicable_salary_floor_cents"], 84400, "applicable_salary_floor_cents")
    assert analysis["federal_pass"] is False, (
        f"84399 falls one cent short of the floor, got {analysis['federal_pass']}"
    )
    assert analysis["outcome"] == AnalysisOutcome.NONEXEMPT, (
        f"a failing federal leg produces NONEXEMPT, got {analysis['outcome']}"
    )
    assert_one_decimal(
        analysis["primary_duty_pct_snapshot"], 80.0, "below-floor primary_duty_pct_snapshot"
    )
    assert_one_decimal(
        texas_floor_boundary["at_analysis"]["primary_duty_pct_snapshot"],
        80.0,
        "at-floor primary_duty_pct_snapshot",
    )


def test_hce_shortcut_reads_the_federal_annual_and_weekly_constants(api, pinned_clock):
    """A very well-paid executive clears the abbreviated duties test it would otherwise fail.

    PRD: "A position is eligible for it when all four of the following hold: `annual_salary_cents`
    is at least the highly-compensated floor resolved above; the weekly salary is at least the
    federal weekly floor of 84,400 cents; `primary_duty_pct` is at least 20.0 percent; and the
    `applied_test` is one of `EXECUTIVE`, `ADMINISTRATIVE` or `PROFESSIONAL`."

    Design: Corner/calculations/hce_shortcut_reads_the_federal_annual_constant_and_the_federal_weekly_floor
    """
    fixtures.register_state_rule(api, factories.texas_rule_payload(hce_shortcut_recognized=True))
    project = fixtures.create_project(api)
    family = fixtures.create_family(
        api, project["id"], name="Corporate Leadership", code="CORP-LEAD"
    )
    fixtures.advance_project(api, project["id"], ProjectStatus.FIELDWORK)
    position = fixtures.create_position(
        api,
        family["id"],
        title="Regional Vice President",
        job_code="RVP-900",
        annual_salary_cents=14000000,
        work_state_code="TX",
        incumbent_count=1,
        avg_weekly_hours=42,
    )
    _attest_pair(
        api,
        position["id"],
        "int-22",
        (
            ("2026-09-12T14:00:00Z", "2026-09-12T15:00:00Z"),
            ("2026-09-13T14:00:00Z", "2026-09-13T15:00:00Z"),
        ),
        (25.0, 42, 1, False),
        ("MGR-9", "INC-9"),
    )

    analysis = fixtures.submit_analysis(
        api,
        fixtures.author_analysis(api, position["id"], applied_test=ExemptionTest.EXECUTIVE)["id"],
    )

    assert_money(analysis["weekly_salary_cents_snapshot"], 269230, "weekly_salary_cents_snapshot")
    assert_money(analysis["applicable_salary_floor_cents"], 84400, "applicable_salary_floor_cents")
    assert analysis["salary_threshold_source"] == SalaryThresholdSource.FEDERAL, (
        "the Texas floor sits below the federal one, got "
        f"{analysis['salary_threshold_source']}"
    )
    assert analysis["applicable_duty_floor_pct"] == 50.0, (
        f"the federal variant carries a 50.0 percent floor, got {analysis['applicable_duty_floor_pct']}"
    )
    assert_one_decimal(analysis["primary_duty_pct_snapshot"], 25.0, "primary_duty_pct_snapshot")
    assert analysis["hce_shortcut_applied"] is True, (
        "25.0 percent clears the abbreviated floor while failing the ordinary one, got "
        f"{analysis['hce_shortcut_applied']}"
    )
    assert analysis["federal_pass"] is True, f"the federal leg must pass, got {analysis['federal_pass']}"
    assert analysis["state_pass"] is True, f"the state leg must pass, got {analysis['state_pass']}"
    assert analysis["outcome"] == AnalysisOutcome.EXEMPT, (
        f"two passing legs produce EXEMPT, got {analysis['outcome']}"
    )
    assert analysis["status"] == AnalysisStatus.SUBMITTED, (
        f"the analysis must be SUBMITTED, got {analysis['status']}"
    )
