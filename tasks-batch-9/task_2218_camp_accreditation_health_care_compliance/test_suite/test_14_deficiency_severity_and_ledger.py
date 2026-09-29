"""One closing pass that produces all three deficiency severities under a single shared
tier, and the controlled-substance ledger holding its balance through three refusals."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_pct, find_by
from test_helpers.factories import medication_record_payload
from test_helpers.test_users import make_health_care_staff_headers
from test_helpers.types import (
    AdministeredByRole,
    Certification,
    ComplianceFlag,
    CompliancePosture,
    DeficiencySeverity,
    DeficiencyStatus,
    HealthIntakeStatus,
    HealthStaffingLevel,
    MedRecordStatus,
    MedicationClass,
    RiskIndexVariant,
    SelfScore,
    StandardDomain,
    TeamRole,
    VisitStatus,
)
from prd_bench_local_runner.testing import validate_error

SEVERITY_STANDARDS = [
    fx.universal_mandatory_standard(
        "HW.1", domain=StandardDomain.HEALTH_WELLNESS, scoring_weight=1
    ),
    fx.universal_mandatory_standard(
        "SU.2", domain=StandardDomain.SUPERVISION, scoring_weight=1
    ),
    fx.universal_optional_standard("OM.3", domain=StandardDomain.OPERATIONS, scoring_weight=1),
]

SEVERITY_CODES = ("HW.1", "SU.2", "OM.3")

SEVERITY_TEAM = [
    {
        "key": "lead",
        "full_name": "Severity Lead",
        "home_state_code": "PA",
        "certifications": [Certification.LEAD_VISITOR, Certification.HEALTH_SPECIALIST],
        "team_role": TeamRole.LEAD,
    },
    {
        "key": "member",
        "full_name": "Severity Member",
        "home_state_code": "PA",
        "certifications": [],
        "team_role": TeamRole.MEMBER,
    },
]


def _visit_scored_not_met_across_three_domains(api):
    """Every applicable row is found NOT_MET in one closing pass."""
    fx.reset_clock(api)
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-SEV",
        standards=SEVERITY_STANDARDS,
        camp={"name": "Severity Split Camp"},
        self_scores={code: SelfScore.PARTIAL for code in SEVERITY_CODES},
        submit=True,
    )
    fx.seat_team(
        api,
        scenario,
        team=SEVERITY_TEAM,
        window=("2026-08-01", "2026-08-07"),
        travel=("2026-08-01", "2026-08-03"),
        confirm=True,
    )
    return fx.score_visit(
        api,
        scenario,
        visitor_scores={code: fx.NOT_MET_OBSERVED for code in SEVERITY_CODES},
        clock=None,
    )


def _camp_holding_thirteen_controlled_units(api):
    """Twenty units taken into stock, seven of them already dispensed on two records."""
    camp = fx.register_camp(
        api, name="Ledger Camp", health_staffing_level=HealthStaffingLevel.RN_ONSITE
    )
    fx.receive_controlled_stock(api, camp["id"], 20)

    first = fx.administer_medication(
        api,
        camp["id"],
        camper_reference="CR-A",
        medication_class=MedicationClass.CONTROLLED,
        dose_units=3,
        administered_at="2026-08-01T08:00:00.000Z",
        administered_by_role=AdministeredByRole.RN,
        second_signature_present=True,
    )
    second = fx.administer_medication(
        api,
        camp["id"],
        camper_reference="CR-B",
        medication_class=MedicationClass.CONTROLLED,
        dose_units=4,
        administered_at="2026-08-01T09:00:00.000Z",
        administered_by_role=AdministeredByRole.PHYSICIAN,
        second_signature_present=True,
    )
    return {"camp": camp, "first": first, "second": second}


def _dose_attempt(api, camp_id, **overrides):
    """Post one medication record as the camp's health care staff and return the response."""
    return api.create_medication_record(
        medication_record_payload(camp_id, **overrides),
        make_health_care_staff_headers(camp_id),
    )


def test_one_batch_splits_into_critical_mandatory_and_scored_findings(api):
    """PRD §3.6: "Severity carries points — 8 for `MANDATORY_CRITICAL`, 5 for `MANDATORY`, 2
    for `SCORED` — and the finding's `base_points` is that figure multiplied by the row's
    pinned `scoring_weight`."

    Design: Corner/calculations/deficiency_severity_splits_three_ways_in_one_finalize_batch
    """
    scenario = _visit_scored_not_met_across_three_domains(api)
    assert scenario.visit["status"] == VisitStatus.SCORED
    # Two mandatory rows sit in the provisional denominator and neither is MET.
    assert_pct(scenario.visit["provisional_mandatory_pct"], 0.00)

    assert len(scenario.deficiencies) == 3
    findings = {
        code: find_by(scenario.deficiencies, standard_id=scenario.standards[code]["id"])
        for code in SEVERITY_CODES
    }

    # Mandatory and HEALTH_WELLNESS: a critical domain.
    assert findings["HW.1"]["severity"] == DeficiencySeverity.MANDATORY_CRITICAL
    assert findings["HW.1"]["base_points"] == 8
    assert findings["HW.1"]["penalty_points"] == 10
    # Mandatory but SUPERVISION is not a critical domain.
    assert findings["SU.2"]["severity"] == DeficiencySeverity.MANDATORY
    assert findings["SU.2"]["base_points"] == 5
    assert findings["SU.2"]["penalty_points"] == 7
    # Not mandatory at all.
    assert findings["OM.3"]["severity"] == DeficiencySeverity.SCORED
    assert findings["OM.3"]["base_points"] == 2
    assert findings["OM.3"]["penalty_points"] == 4

    for finding in findings.values():
        # Batch base total 8 + 5 + 2 = 15 selects tier 1: one +2 surcharge, a 60-day window.
        assert finding["status"] == DeficiencyStatus.OPEN
        assert finding["correction_due_date"] == "2026-09-30"
        assert finding["plan_revision_count"] == 0


def test_the_batch_balance_freezes_the_camp_and_drives_the_post_visit_index(api):
    """PRD §2.7: "The posture is `FROZEN` when the camp's `penalty_point_balance` is at least
    12, or its `state_license_status` is `SUSPENDED`, or at least one deficiency of the camp
    sits in `ESCALATED`."

    Design: Corner/calculations/deficiency_severity_splits_three_ways_in_one_finalize_batch
    """
    scenario = _visit_scored_not_met_across_three_domains(api)

    camp = fx.read_camp(api, scenario.camp_id)
    assert camp["penalty_point_balance"] == 21
    assert camp["compliance_posture"] == CompliancePosture.FROZEN
    assert camp["health_intake_status"] == HealthIntakeStatus.SUSPENDED

    components = fx.read_risk_index(api, scenario.camp_id)
    assert components["risk_index_variant"] == RiskIndexVariant.POST_VISIT
    # Two of two applicable mandatory rows carry an open mandatory finding: 2 x 30 / 2.
    assert_pct(components["compliance_component"], 30.00)
    assert_pct(components["license_penalty"], 6.00)
    assert_pct(components["staffing_gap_penalty"], 0.00)
    assert_pct(components["risk_index"], 46.00)


def test_the_role_witness_and_stock_rules_each_refuse_without_touching_the_ledger(api):
    """PRD §3.9: "Then stock: `dose_units` on a `CONTROLLED` record may not exceed the camp's
    `controlled_on_hand_units`, or the write is refused with
    `ERR_CONTROLLED_STOCK_INSUFFICIENT`."

    Design: Corner/calculations/controlled_ledger_conserves_units_and_rejects_overdraw_role_and_signature_violations
    """
    world = _camp_holding_thirteen_controlled_units(api)
    camp_id = world["camp"]["id"]
    stocked = fx.read_camp(api, camp_id)
    assert stocked["controlled_intake_units"] == 20
    assert stocked["controlled_on_hand_units"] == 13

    validate_error(
        _dose_attempt(
            api,
            camp_id,
            camper_reference="CR-C",
            medication_class=MedicationClass.CONTROLLED,
            dose_units=2,
            administered_at="2026-08-01T10:00:00.000Z",
            administered_by_role=AdministeredByRole.LPN,
            second_signature_present=True,
        ),
        ApiErrorId.MED_ROLE_NOT_PERMITTED,
        422,
    )
    validate_error(
        _dose_attempt(
            api,
            camp_id,
            camper_reference="CR-C",
            medication_class=MedicationClass.CONTROLLED,
            dose_units=2,
            administered_at="2026-08-01T10:00:00.000Z",
            administered_by_role=AdministeredByRole.RN,
        ),
        ApiErrorId.CONTROLLED_SECOND_SIGNATURE_REQUIRED,
        422,
    )
    validate_error(
        _dose_attempt(
            api,
            camp_id,
            camper_reference="CR-C",
            medication_class=MedicationClass.CONTROLLED,
            dose_units=14,
            administered_at="2026-08-01T10:00:00.000Z",
            administered_by_role=AdministeredByRole.RN,
            second_signature_present=True,
        ),
        ApiErrorId.CONTROLLED_STOCK_INSUFFICIENT,
        422,
    )

    settled = fx.read_camp(api, camp_id)
    assert settled["controlled_intake_units"] == 20
    assert settled["controlled_on_hand_units"] == 13


def test_an_unlicensed_designee_may_not_hand_out_even_an_over_the_counter_dose(api):
    """PRD §3.9: "`UNLICENSED_DESIGNEE` is never permitted for any class. A violation is
    `ERR_MED_ROLE_NOT_PERMITTED`."

    Design: Corner/calculations/controlled_ledger_conserves_units_and_rejects_overdraw_role_and_signature_violations
    """
    world = _camp_holding_thirteen_controlled_units(api)
    camp_id = world["camp"]["id"]

    validate_error(
        _dose_attempt(
            api,
            camp_id,
            camper_reference="CR-D",
            medication_class=MedicationClass.OTC,
            dose_units=1,
            administered_at="2026-08-01T11:00:00.000Z",
            administered_by_role=AdministeredByRole.UNLICENSED_DESIGNEE,
        ),
        ApiErrorId.MED_ROLE_NOT_PERMITTED,
        422,
    )

    camp = fx.read_camp(api, camp_id)
    assert camp["controlled_intake_units"] == 20
    assert camp["controlled_on_hand_units"] == 13

    for record in (world["first"], world["second"]):
        assert record["record_status"] == MedRecordStatus.RECORDED
        assert record["compliance_flag"] == ComplianceFlag.COMPLIANT
