"""Two per-line arithmetic rules: the incident component of the risk index, rounded and
window-filtered disclosure by disclosure, and the fee's domain surcharges under a capped
multi-year discount."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_pct, assert_risk_index_breakdown
from test_helpers.types import (
    AccreditationStatus,
    AnnualReportDecision,
    AnnualReportStatus,
    Certification,
    CycleStatus,
    DecisionLevel,
    DisclosureStatus,
    IncidentType,
    RiskIndexVariant,
    ScoreSource,
    SelfScore,
    StandardDomain,
    StateLicenseStatus,
    TeamRole,
    VisitorScore,
)

FEE_STANDARDS = [
    fx.universal_mandatory_standard(
        "SU.1", domain=StandardDomain.SUPERVISION, scoring_weight=1
    ),
    fx.universal_optional_standard("PA.2", domain=StandardDomain.AQUATICS, scoring_weight=1),
    fx.universal_optional_standard("AD.3", domain=StandardDomain.ADVENTURE, scoring_weight=1),
    fx.universal_optional_standard(
        "TR.4", domain=StandardDomain.TRANSPORTATION, scoring_weight=1
    ),
    fx.universal_optional_standard(
        "HW.5", domain=StandardDomain.HEALTH_WELLNESS, scoring_weight=1
    ),
    fx.universal_optional_standard("OM.6", domain=StandardDomain.OPERATIONS, scoring_weight=1),
]

FEE_CODES = ("SU.1", "PA.2", "AD.3", "TR.4", "HW.5", "OM.6")

FEE_TEAM = [
    {
        "key": "lead",
        "full_name": "Fee Lead",
        "home_state_code": "PA",
        "certifications": [
            Certification.LEAD_VISITOR,
            Certification.AQUATICS_SPECIALIST,
            Certification.ADVENTURE_SPECIALIST,
            Certification.HEALTH_SPECIALIST,
        ],
        "team_role": TeamRole.LEAD,
        "travel": ("2026-08-01", "2026-08-04"),
    },
    {
        "key": "member",
        "full_name": "Fee Member",
        "home_state_code": "PA",
        "certifications": [],
        "team_role": TeamRole.MEMBER,
        "travel": ("2026-08-01", "2026-08-02"),
    },
]

FEE_VERDICTS = {
    "SU.1": fx.ALL_MET_OBSERVED,
    "PA.2": fx.ALL_MET_OBSERVED,
    "AD.3": fx.ALL_MET_OBSERVED,
    "TR.4": (VisitorScore.MET, ScoreSource.DOCUMENT),
    "HW.5": fx.ALL_MET_OBSERVED,
    "OM.6": (VisitorScore.MET, ScoreSource.DOCUMENT),
}


def _camp_with_four_disclosures(api):
    """Three annual reports carry four disclosures, one of them filed after acceptance."""
    fx.reset_clock(api)
    camp = fx.register_camp(api, name="Risk Window Camp")
    fx.move_state_license(api, camp["id"], StateLicenseStatus.ACTIVE, "OH-CAMP-30001")

    report_2023 = fx.open_annual_report(api, camp["id"], 2023)
    report_2025 = fx.open_annual_report(api, camp["id"], 2025)
    report_2026 = fx.open_annual_report(api, camp["id"], 2026)

    old_death = fx.disclose_incident(
        api, camp["id"], report_2023["id"], IncidentType.DEATH, "2023-07-01T12:00:00.000Z"
    )
    filed_2025 = fx.file_annual_report(api, camp["id"], report_2025["id"], 0)
    fx.review_annual_report(
        api, report_2025["id"], AnnualReportDecision.ACCEPT, "accepted as filed"
    )
    injury = fx.disclose_incident(
        api,
        camp["id"],
        report_2026["id"],
        IncidentType.SERIOUS_INJURY,
        "2026-06-01T09:00:00.000Z",
    )
    med_error = fx.disclose_incident(
        api,
        camp["id"],
        report_2026["id"],
        IncidentType.MEDICATION_ERROR,
        "2026-06-15T09:00:00.000Z",
    )
    return {
        "camp": camp,
        "report_2025": report_2025,
        "filed_2025": filed_2025,
        "old_death": old_death,
        "injury": injury,
        "med_error": med_error,
    }


def _fee_cycle_decided(api):
    """A six-domain cycle scored entirely MET for a camp with three prior accreditations."""
    fx.reset_clock(api)
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-FEE",
        standards=FEE_STANDARDS,
        camp={"name": "Fee Domain Camp", "prior_accredited_cycle_count": 3},
        self_scores={code: SelfScore.MET for code in FEE_CODES},
        submit=True,
    )
    fx.seat_team(
        api,
        scenario,
        team=FEE_TEAM,
        window=("2026-08-01", "2026-08-07"),
        confirm=True,
    )
    fx.score_visit(api, scenario, visitor_scores=FEE_VERDICTS, clock=None)
    return fx.decide_cycle(api, scenario)


def test_a_disclosure_filed_after_acceptance_is_stamped_late_and_reopens_the_report(api):
    """PRD §3.9: "Filed against a report already in `ACCEPTED`, it is stamped
    `LATE_DISCLOSED` and reopens the report: the report moves `ACCEPTED → REOPENED`, its
    `reopen_count` increases by one, and the camp must file again."

    Design: Corner/calculations/camp_risk_index_incident_component_rounds_per_disclosure_and_honours_the_three_year_window
    """
    world = _camp_with_four_disclosures(api)
    # The 2025 season was due 2026-03-01 and filed on 2026-08-01, so it landed LATE.
    assert world["filed_2025"]["status"] == AnnualReportStatus.LATE
    assert (
        fx.read_annual_report(api, world["report_2025"]["id"])["status"]
        == AnnualReportStatus.ACCEPTED
    )

    late = fx.disclose_incident(
        api,
        world["camp"]["id"],
        world["report_2025"]["id"],
        IncidentType.HOSPITALIZATION,
        "2025-07-04T18:30:00.000Z",
    )
    assert late["status"] == DisclosureStatus.LATE_DISCLOSED
    assert late["severity_weight"] == 12
    assert late["state_notification_required"] is True
    assert late["disclosed_at"].startswith("2026-08-01T00:00:00")

    reopened = fx.read_annual_report(api, world["report_2025"]["id"])
    assert reopened["status"] == AnnualReportStatus.REOPENED
    assert reopened["reopen_count"] == 1
    assert reopened["disclosed_incident_count"] == 1

    assert world["injury"]["status"] == DisclosureStatus.REPORTED
    assert world["injury"]["severity_weight"] == 8
    assert world["injury"]["state_notification_required"] is False
    assert world["med_error"]["severity_weight"] == 4
    assert world["med_error"]["state_notification_required"] is False


def test_the_incident_component_multiplies_the_late_weight_and_drops_the_stale_year(api):
    """PRD §2.9: "Each qualifying disclosure contributes its incident weight multiplied by
    1.5 when its `status` is `LATE_DISCLOSED` and by 1.0 when its `status` is `REPORTED`,
    with that product rounded half up to two decimal places **for each disclosure
    individually before the contributions are summed**."

    Design: Corner/calculations/camp_risk_index_incident_component_rounds_per_disclosure_and_honours_the_three_year_window
    """
    world = _camp_with_four_disclosures(api)
    fx.disclose_incident(
        api,
        world["camp"]["id"],
        world["report_2025"]["id"],
        IncidentType.HOSPITALIZATION,
        "2025-07-04T18:30:00.000Z",
    )
    # The 2023 death carries the heaviest weight in the domain and still contributes nothing.
    assert world["old_death"]["severity_weight"] == 25

    components = fx.read_risk_index(api, world["camp"]["id"])
    assert_risk_index_breakdown(components)
    assert components["camp_id"] == world["camp"]["id"]
    assert components["risk_index_variant"] == RiskIndexVariant.PRE_VISIT
    # 8.00 for the injury, 4.00 for the medication error, 12 x 1.5 = 18.00 for the late one.
    assert_pct(components["incident_component"], 30.00)
    assert_pct(components["program_component"], 0.00)
    assert_pct(components["staffing_gap_penalty"], 0.00)
    assert_pct(components["license_penalty"], 0.00)
    assert_pct(components["compliance_component"], 0.00)
    assert float(components["population_multiplier"]) == 1.0
    assert_pct(components["risk_index"], 40.00)


def test_each_paying_domain_is_surcharged_once_under_the_clamped_ten_percent_discount(api):
    """PRD §3.7: "one domain surcharge for each domain present, each multiplied by one minus
    the discount fraction — 18,125 cents for `AQUATICS`, 22,125 for `ADVENTURE`, 12,125 for
    `TRANSPORTATION`, 15,125 for `HEALTH_WELLNESS`, and zero for `SUPERVISION`,
    `EMERGENCY_RESPONSE` and `OPERATIONS`, with the surcharges evaluated in exactly that
    domain order"

    Design: Corner/calculations/accreditation_fee_domain_surcharges_apply_once_per_distinct_domain_under_a_capped_discount
    """
    scenario = _fee_cycle_decided(api)

    base_line = 95000
    per_standard_line = 1890
    domain_lines = 16313 + 19913 + 10913 + 13613
    travel_line = 97200
    assert domain_lines == 60752
    assert scenario.cycle["assessed_fee_cents"] == (
        base_line + per_standard_line + domain_lines + travel_line
    )
    assert scenario.cycle["assessed_fee_cents"] == 254842

    # Six travel days: the LEAD seat's four plus the MEMBER seat's two, both COMPLETED.
    assert scenario.assignments["lead"]["travel_days"] == 4
    assert scenario.assignments["member"]["travel_days"] == 2
    assert fx.read_visitor(api, scenario.visitor_id("lead"))["committed_travel_days"] == 4
    assert fx.read_visitor(api, scenario.visitor_id("member"))["committed_travel_days"] == 2


def test_the_closed_branch_banks_the_accredited_year_after_using_the_old_count(api):
    """PRD §3.7: "A move to `ACCREDITED` on this branch additionally increments the camp's
    `prior_accredited_cycle_count` by one and sets `last_accredited_year` to the cycle's
    `cycle_year`."

    Design: Corner/calculations/accreditation_fee_domain_surcharges_apply_once_per_distinct_domain_under_a_capped_discount
    """
    scenario = _fee_cycle_decided(api)

    assert_pct(scenario.cycle["final_mandatory_pct"], 100.00)
    assert_pct(scenario.cycle["final_weighted_pct"], 100.00)
    assert scenario.cycle["decision_level"] == DecisionLevel.ACCREDITED
    assert scenario.cycle["status"] == CycleStatus.CLOSED
    assert scenario.cycle["open_deficiency_count"] == 0

    camp = fx.read_camp(api, scenario.camp_id)
    assert camp["accreditation_status"] == AccreditationStatus.ACCREDITED
    # The discount read the pre-increment 3, clamped to the two-cycle tier, then banked a 4th.
    assert camp["prior_accredited_cycle_count"] == 4
    assert camp["last_accredited_year"] == 2026
