"""The decision ladder read in clause order: a suspended licence outranks perfect scores,
and exactly ninety percent mandatory compliance lands on the provisional rung."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_pct
from test_helpers.test_users import OFFICER_TWO_ID
from test_helpers.types import (
    AccreditationStatus,
    Certification,
    CompliancePosture,
    CycleStatus,
    DecisionLevel,
    DeficiencySeverity,
    DeficiencyStatus,
    SelfScore,
    StandardDomain,
    StateLicenseStatus,
    TeamRole,
)

SUSPENDED_STANDARDS = [
    fx.universal_mandatory_standard(
        "SU.1", domain=StandardDomain.SUPERVISION, scoring_weight=1
    ),
    fx.universal_optional_standard("OM.2", domain=StandardDomain.OPERATIONS, scoring_weight=1),
]

NINETY_CODES = tuple(f"M{index:02d}" for index in range(1, 11))

NINETY_STANDARDS = [
    fx.universal_mandatory_standard(code, domain=StandardDomain.SUPERVISION, scoring_weight=1)
    for code in NINETY_CODES
]


def _plain_team(prefix: str):
    return [
        {
            "key": "lead",
            "full_name": f"{prefix} Lead",
            "home_state_code": "PA",
            "certifications": [Certification.LEAD_VISITOR],
            "team_role": TeamRole.LEAD,
        },
        {
            "key": "member",
            "full_name": f"{prefix} Member",
            "home_state_code": "PA",
            "certifications": [],
            "team_role": TeamRole.MEMBER,
        },
    ]


def _perfect_cycle_whose_licence_is_pulled_before_the_decision(api):
    """Both rows scored MET, then the state suspends the licence, then the office decides."""
    fx.reset_clock(api)
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-SUS",
        standards=SUSPENDED_STANDARDS,
        camp={"name": "Suspended License Camp"},
        self_scores={"SU.1": SelfScore.MET, "OM.2": SelfScore.MET},
    )
    fx.move_state_license(
        api, scenario.camp_id, StateLicenseStatus.ACTIVE, "OH-CAMP-40001"
    )
    fx.submit_self_assessment(api, scenario.cycle_id, scenario.camp_id)
    fx.seat_team(
        api,
        scenario,
        team=_plain_team("Suspend"),
        window=("2026-08-01", "2026-08-07"),
        travel=("2026-08-01", "2026-08-03"),
        confirm=True,
    )
    fx.score_visit(
        api,
        scenario,
        visitor_scores={"SU.1": fx.ALL_MET_OBSERVED, "OM.2": fx.ALL_MET_OBSERVED},
        clock=None,
    )
    fx.move_state_license(api, scenario.camp_id, StateLicenseStatus.SUSPENDED)
    return fx.decide_cycle(api, scenario)


def _cycle_scoring_nine_of_ten_mandatory_standards(api):
    """Ten mandatory rows of equal weight, nine of them met on site."""
    fx.reset_clock(api)
    self_scores = {code: SelfScore.MET for code in NINETY_CODES}
    self_scores["M10"] = SelfScore.PARTIAL
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-P90",
        standards=NINETY_STANDARDS,
        camp={"name": "Ninety Percent Camp"},
        self_scores=self_scores,
        submit=True,
    )
    fx.seat_team(
        api,
        scenario,
        team=_plain_team("P90"),
        window=("2026-08-01", "2026-08-07"),
        travel=("2026-08-01", "2026-08-03"),
        confirm=True,
    )
    verdicts = {code: fx.ALL_MET_OBSERVED for code in NINETY_CODES}
    verdicts["M10"] = fx.NOT_MET_OBSERVED
    fx.score_visit(api, scenario, visitor_scores=verdicts, clock=None)
    return fx.decide_cycle(api, scenario)


def test_a_suspended_licence_denies_a_cycle_that_met_every_standard(api):
    """PRD §3.7: "`DENIED` when the camp's `state_license_status` is `SUSPENDED`, or when
    `final_mandatory_pct` is below 90.00."

    Design: Corner/calculations/decision_denies_a_fully_compliant_cycle_when_the_state_license_is_suspended_at_decision_time
    """
    scenario = _perfect_cycle_whose_licence_is_pulled_before_the_decision(api)

    assert_pct(scenario.cycle["final_mandatory_pct"], 100.00)
    assert_pct(scenario.cycle["final_weighted_pct"], 100.00)
    assert scenario.cycle["decision_level"] == DecisionLevel.DENIED
    # The DENIED landing outranks the no-open-findings CLOSED landing.
    assert scenario.cycle["status"] == CycleStatus.TERMINATED
    assert scenario.cycle["open_deficiency_count"] == 0
    assert scenario.cycle["decision_issued_by_user_id"] == OFFICER_TWO_ID


def test_the_denied_branch_still_assesses_the_fee_and_revokes_the_camp(api):
    """PRD §3.7: "`assessed_fee_cents` is stamped on every branch, including `DENIED`, and is
    built from four line items."

    Design: Corner/calculations/decision_denies_a_fully_compliant_cycle_when_the_state_license_is_suspended_at_decision_time
    """
    scenario = _perfect_cycle_whose_licence_is_pulled_before_the_decision(api)

    # 95000 base + 700 for two standards + no paying domain + 108000 for six travel days.
    assert scenario.cycle["assessed_fee_cents"] == 95000 + 700 + 108000
    assert scenario.cycle["assessed_fee_cents"] == 203700

    camp = fx.read_camp(api, scenario.camp_id)
    assert camp["accreditation_status"] == AccreditationStatus.REVOKED
    assert camp["prior_accredited_cycle_count"] == 0
    assert camp["last_accredited_year"] is None
    # The freeze comes from the licence alone: no finding was ever raised.
    assert camp["compliance_posture"] == CompliancePosture.FROZEN
    assert camp["penalty_point_balance"] == 0


def test_exactly_ninety_percent_mandatory_compliance_is_provisional_not_denied(api):
    """PRD §3.7: "Otherwise `PROVISIONAL` when `final_mandatory_pct` is below 100.00 — that
    is, anything from 90.00 up to but not including full mandatory compliance."

    Design: Corner/calculations/exactly_ninety_percent_mandatory_compliance_lands_on_provisional_not_denied
    """
    scenario = _cycle_scoring_nine_of_ten_mandatory_standards(api)

    assert_pct(scenario.cycle["final_mandatory_pct"], 90.00)
    assert_pct(scenario.cycle["final_weighted_pct"], 90.00)
    # The mandatory rung is read before the weighted rung, so 90.00 weighted never matters.
    assert scenario.cycle["decision_level"] == DecisionLevel.PROVISIONAL
    assert scenario.cycle["status"] == CycleStatus.IN_CORRECTION
    assert scenario.cycle["open_deficiency_count"] == 1
    assert fx.read_camp(api, scenario.camp_id)["accreditation_status"] == (
        AccreditationStatus.PROVISIONAL
    )


def test_a_lone_mandatory_finding_sits_below_the_first_tier_break(api):
    """PRD §3.6: "A batch base total of 9 or less selects tier 0, a total from 10 through 19
    selects tier 1, and a total of 20 or more selects tier 2."

    Design: Corner/calculations/exactly_ninety_percent_mandatory_compliance_lands_on_provisional_not_denied
    """
    scenario = _cycle_scoring_nine_of_ten_mandatory_standards(api)

    assert len(scenario.deficiencies) == 1
    finding = scenario.deficiencies[0]
    assert finding["standard_id"] == scenario.standards["M10"]["id"]
    assert finding["severity"] == DeficiencySeverity.MANDATORY
    assert finding["base_points"] == 5
    # Batch base 5 is below the first break, so tier 0 adds nothing and allows 90 days.
    assert finding["penalty_points"] == 5
    assert finding["correction_due_date"] == "2026-10-30"
    assert finding["status"] == DeficiencyStatus.OPEN

    camp = fx.read_camp(api, scenario.camp_id)
    assert camp["penalty_point_balance"] == 5
    assert camp["compliance_posture"] == CompliancePosture.RESTRICTED
    assert scenario.cycle["assessed_fee_cents"] == 95000 + 3500 + 108000
    assert scenario.cycle["assessed_fee_cents"] == 206500
