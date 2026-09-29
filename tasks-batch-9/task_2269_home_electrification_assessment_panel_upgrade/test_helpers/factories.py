"""Request-payload builders.

Every builder returns a valid payload for the endpoint it names and accepts
`**overrides` so a test can perturb exactly one field. Field names and defaults
follow §3.1-§3.9 and the endpoint table of §4.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .constants import (
    MEASURE_ENV_INS,
    MEASURE_HP_DUCT,
    MEASURE_HP_HVAC,
    MEASURE_HPWH,
    MEASURE_PANEL_200A,
    MEASURE_PANEL_400A,
    MEASURE_STOVE,
)
from .types import (
    AssessmentDecision,
    CombinedCapGroup,
    EnrollmentDecision,
    IncomeVerificationDecision,
    InspectionResult,
    InspectionType,
    MeasureCategory,
    ProgramStatus,
    ProjectReviewDecision,
    SuspensionAction,
)

# --------------------------------------------------------------------------- #
# Programs (§3.1)
# --------------------------------------------------------------------------- #


def build_program_payload(**overrides: Any) -> Dict[str, Any]:
    """Minimal valid program: only `name`, `state_code` and `budget_total_cents`.

    Everything else is left out so the documented defaults apply.
    """
    payload: Dict[str, Any] = {
        "name": "HEEHRA 2026",
        "state_code": "CO",
        "budget_total_cents": 50000000,
    }
    payload.update(overrides)
    return payload


def build_full_program_payload(**overrides: Any) -> Dict[str, Any]:
    """Program payload spelling out every overridable parameter explicitly."""
    payload: Dict[str, Any] = {
        "name": "HEEHRA 2026",
        "state_code": "CO",
        "budget_total_cents": 50000000,
        "program_year": 2026,
        "reservation_ttl_days": 120,
        "extension_window_days": 30,
        "max_extension_days": 60,
        "max_extensions_per_reservation": 1,
        "low_tier_cap_cents": 1400000,
        "moderate_tier_cap_cents": 800000,
        "standard_tier_cap_cents": 300000,
        "low_tier_cost_share_pct": 1.00,
        "moderate_tier_cost_share_pct": 0.50,
        "standard_tier_cost_share_pct": 0.30,
        "ami_low_threshold_pct": 80.0,
        "ami_moderate_threshold_pct": 150.0,
        "group_cap_cents": 800000,
        "panel_upgrade_cap_cents": 400000,
        "federal_credit_pct": 0.30,
        "federal_credit_cap_cents": 200000,
        "max_combined_benefit_pct": 1.00,
        "max_remediations_per_project": 1,
        "quality_suspension_threshold": 70,
        "recertification_threshold": 75,
    }
    payload.update(overrides)
    return payload


def build_status_payload(new_status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"new_status": new_status}
    payload.update(overrides)
    return payload


def build_open_status_payload(**overrides: Any) -> Dict[str, Any]:
    return build_status_payload(ProgramStatus.OPEN, **overrides)


# --------------------------------------------------------------------------- #
# Measure catalog items (§3.1)
# --------------------------------------------------------------------------- #


def build_catalog_item_payload(**overrides: Any) -> Dict[str, Any]:
    """A ducted heat pump: HVAC, 800000 unit and cap, HVAC_GROUP, anchor, 200 A."""
    payload: Dict[str, Any] = {
        "measure_code": MEASURE_HP_HVAC,
        "measure_name": "Ducted air-source heat pump",
        "category": MeasureCategory.HVAC,
        "unit_incentive_cents": 800000,
        "measure_cap_cents": 800000,
        "max_quantity": 1,
        "combined_cap_group": CombinedCapGroup.HVAC_GROUP,
        "required_panel_capacity_amps": 200,
        "qualifies_as_appliance_anchor": True,
        "sort_order": 10,
    }
    payload.update(overrides)
    return payload


def build_hvac_heat_pump_payload(**overrides: Any) -> Dict[str, Any]:
    return build_catalog_item_payload(**overrides)


def build_duct_payload(**overrides: Any) -> Dict[str, Any]:
    """Duct sealing: HVAC_GROUP, 250000, 100 A, prerequisite HP-HVAC-01."""
    payload: Dict[str, Any] = {
        "measure_code": MEASURE_HP_DUCT,
        "measure_name": "Duct replacement and sealing",
        "category": MeasureCategory.HVAC,
        "unit_incentive_cents": 250000,
        "measure_cap_cents": 250000,
        "max_quantity": 1,
        "combined_cap_group": CombinedCapGroup.HVAC_GROUP,
        "required_panel_capacity_amps": 100,
        "prerequisite_measure_code": MEASURE_HP_HVAC,
        "sort_order": 15,
    }
    payload.update(overrides)
    return payload


def build_water_heater_payload(**overrides: Any) -> Dict[str, Any]:
    """Heat pump water heater: WATER_GROUP, 175000, 125 A, anchor."""
    payload: Dict[str, Any] = {
        "measure_code": MEASURE_HPWH,
        "measure_name": "Heat pump water heater",
        "category": MeasureCategory.WATER_HEATING,
        "unit_incentive_cents": 175000,
        "measure_cap_cents": 175000,
        "max_quantity": 1,
        "combined_cap_group": CombinedCapGroup.WATER_GROUP,
        "required_panel_capacity_amps": 125,
        "qualifies_as_appliance_anchor": True,
        "standard_tier_eligible": True,
        "sort_order": 20,
    }
    payload.update(overrides)
    return payload


def build_panel_200a_payload(**overrides: Any) -> Dict[str, Any]:
    """200 A service upgrade: ELECTRICAL_GROUP, panel upgrade requiring an anchor."""
    payload: Dict[str, Any] = {
        "measure_code": MEASURE_PANEL_200A,
        "measure_name": "200 A panel and service upgrade",
        "category": MeasureCategory.ELECTRICAL_INFRASTRUCTURE,
        "unit_incentive_cents": 400000,
        "measure_cap_cents": 400000,
        "max_quantity": 1,
        "combined_cap_group": CombinedCapGroup.ELECTRICAL_GROUP,
        "required_panel_capacity_amps": 0,
        "upgraded_capacity_amps": 200,
        "is_panel_upgrade": True,
        "requires_qualifying_appliance": True,
        "standard_tier_eligible": True,
        "sort_order": 30,
    }
    payload.update(overrides)
    return payload


def build_panel_400a_payload(**overrides: Any) -> Dict[str, Any]:
    """400 A service upgrade: ELECTRICAL_GROUP, panel upgrade requiring an anchor."""
    payload: Dict[str, Any] = {
        "measure_code": MEASURE_PANEL_400A,
        "measure_name": "400 A panel and service upgrade",
        "category": MeasureCategory.ELECTRICAL_INFRASTRUCTURE,
        "unit_incentive_cents": 900000,
        "measure_cap_cents": 900000,
        "max_quantity": 1,
        "combined_cap_group": CombinedCapGroup.ELECTRICAL_GROUP,
        "required_panel_capacity_amps": 0,
        "upgraded_capacity_amps": 400,
        "is_panel_upgrade": True,
        "requires_qualifying_appliance": True,
        "standard_tier_eligible": True,
        "sort_order": 35,
    }
    payload.update(overrides)
    return payload


def build_induction_stove_payload(**overrides: Any) -> Dict[str, Any]:
    """Induction range: APPLIANCE_GROUP, 84000, 150 A, anchor."""
    payload: Dict[str, Any] = {
        "measure_code": MEASURE_STOVE,
        "measure_name": "Induction range",
        "category": MeasureCategory.APPLIANCE,
        "unit_incentive_cents": 84000,
        "measure_cap_cents": 84000,
        "max_quantity": 1,
        "combined_cap_group": CombinedCapGroup.APPLIANCE_GROUP,
        "required_panel_capacity_amps": 150,
        "qualifies_as_appliance_anchor": True,
        "standard_tier_eligible": True,
        "sort_order": 40,
    }
    payload.update(overrides)
    return payload


def build_insulation_payload(**overrides: Any) -> Dict[str, Any]:
    """Envelope insulation: no group, no capacity requirement, standard-tier eligible."""
    payload: Dict[str, Any] = {
        "measure_code": MEASURE_ENV_INS,
        "measure_name": "Attic and wall insulation",
        "category": MeasureCategory.ENVELOPE,
        "unit_incentive_cents": 100000,
        "measure_cap_cents": 100000,
        "max_quantity": 1,
        "combined_cap_group": CombinedCapGroup.NONE,
        "required_panel_capacity_amps": 0,
        "standard_tier_eligible": True,
        "sort_order": 50,
    }
    payload.update(overrides)
    return payload


def build_retirement_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"retirement_note": "Superseded by the 2027 schedule"}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Households and income verification (§3.2)
# --------------------------------------------------------------------------- #


def build_household_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "applicant_name": "Ada Rivera",
        "email": "ada@example.com",
        "service_address_line1": "12 Alder St",
        "county_code": "CO-031",
        "utility_territory_code": "XCEL-CO",
        "household_size": 4,
        "existing_panel_amps": 200,
    }
    payload.update(overrides)
    return payload


def build_income_verification_payload(**overrides: Any) -> Dict[str, Any]:
    """A packet landing at exactly 80.0 percent AMI, so tier LOW."""
    payload: Dict[str, Any] = {
        "annual_household_income_cents": 8000000,
        "county_median_income_cents": 10000000,
        "household_size_attested": 4,
        "document_reference": "DOC-A1",
    }
    payload.update(overrides)
    return payload


def build_verify_decision_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": IncomeVerificationDecision.VERIFY,
        "reviewer_notes": "Pay stubs and 1040 on file",
    }
    payload.update(overrides)
    return payload


def build_reject_income_decision_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": IncomeVerificationDecision.REJECT,
        "reviewer_notes": "Documentation incomplete",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Contractors and inspectors (§3.3)
# --------------------------------------------------------------------------- #


def build_contractor_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "business_name": "Peak Electric",
        "license_number": "EC-4471",
        "license_expires_on": "2027-06-30",
        "insurance_expires_on": "2027-06-30",
        "crew_capacity": 2,
    }
    payload.update(overrides)
    return payload


def build_enrollment_decision_payload(
    decision: str = EnrollmentDecision.APPROVE, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def build_suspension_payload(
    action: str = SuspensionAction.SUSPEND, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def build_inspector_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "inspector_name": "Nia Osei",
        "certification_id": "INS-77",
        "certification_expires_on": "2027-12-31",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Assessments (§3.4)
# --------------------------------------------------------------------------- #


def build_assessment_measure(
    measure_code: str, proposed_quantity: int = 1, estimated_cost_cents: int = 1000000
) -> Dict[str, Any]:
    return {
        "measure_code": measure_code,
        "proposed_quantity": proposed_quantity,
        "estimated_cost_cents": estimated_cost_cents,
    }


def build_assessment_payload(
    household_id: str,
    contractor_id: str,
    expected_household_version: int,
    measures: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "household_id": household_id,
        "contractor_id": contractor_id,
        "assessed_panel_amps": 200,
        "expected_household_version": expected_household_version,
        "assessment_notes": "Site visit complete",
        "measures": measures
        if measures is not None
        else [build_assessment_measure(MEASURE_HP_HVAC)],
    }
    payload.update(overrides)
    return payload


def build_assessment_decision_payload(
    decision: str = AssessmentDecision.APPROVE, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Rebate projects (§3.5)
# --------------------------------------------------------------------------- #


def build_project_measure(
    measure_code: str, planned_quantity: int = 1, estimated_cost_cents: int = 1000000
) -> Dict[str, Any]:
    return {
        "measure_code": measure_code,
        "planned_quantity": planned_quantity,
        "estimated_cost_cents": estimated_cost_cents,
    }


def build_project_payload(
    household_id: str,
    assessment_id: str,
    contractor_id: str,
    income_verification_id: str,
    measures: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "household_id": household_id,
        "assessment_id": assessment_id,
        "contractor_id": contractor_id,
        "income_verification_id": income_verification_id,
        "estimated_project_cost_cents": 1000000,
        "measures": measures
        if measures is not None
        else [build_project_measure(MEASURE_HP_HVAC)],
    }
    payload.update(overrides)
    return payload


def build_project_review_payload(
    decision: str = ProjectReviewDecision.APPROVE, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if decision == ProjectReviewDecision.RETURN_INCOMPLETE:
        payload["incomplete_reason"] = "Missing signed scope of work"
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Reservations (§3.6)
# --------------------------------------------------------------------------- #


def build_reservation_payload(expected_program_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_program_version": expected_program_version,
        "reservation_notes": "Full electrification package",
    }
    payload.update(overrides)
    return payload


def build_extension_payload(additional_days: int = 30, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "additional_days": additional_days,
        "extension_reason": "Equipment lead time",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Installation (§3.7)
# --------------------------------------------------------------------------- #


def build_measure_result(
    measure_code: str, verified_quantity: int = 1, actual_cost_cents: int = 700000
) -> Dict[str, Any]:
    return {
        "measure_code": measure_code,
        "verified_quantity": verified_quantity,
        "actual_cost_cents": actual_cost_cents,
    }


def build_installation_payload(
    measure_results: Optional[List[Dict[str, Any]]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "install_start_date": "2026-08-10",
        "install_end_date": "2026-08-20",
        "installed_panel_amps": 200,
        "actual_project_cost_cents": 1000000,
        "measure_results": measure_results
        if measure_results is not None
        else [build_measure_result(MEASURE_HP_HVAC)],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Stacking, payment and remediation (§3.9, §3.8)
# --------------------------------------------------------------------------- #


def build_stacking_payload(utility_rebate_cents: int = 100000, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "utility_program_name": "Xcel Home Electrification",
        "utility_rebate_cents": utility_rebate_cents,
    }
    payload.update(overrides)
    return payload


def build_payment_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"payment_reference": "WARRANT-0001"}
    payload.update(overrides)
    return payload


def build_remediation_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"remediation_notes": "Deficiencies corrected"}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Inspections (§3.8)
# --------------------------------------------------------------------------- #


def build_inspection_payload(
    project_id: str,
    inspector_id: str,
    inspection_type: str = InspectionType.POST_INSTALL,
    scheduled_start: str = "2026-08-21T09:00:00Z",
    scheduled_end: str = "2026-08-21T11:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "inspector_id": inspector_id,
        "inspection_type": inspection_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def build_pass_result_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "result": InspectionResult.PASS,
        "deficiency_count": 0,
        "deficiency_severity_max": 0,
    }
    payload.update(overrides)
    return payload


def build_conditional_pass_result_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "result": InspectionResult.CONDITIONAL_PASS,
        "deficiency_count": 2,
        "deficiency_severity_max": 2,
        "notes": "Two minor commissioning items",
    }
    payload.update(overrides)
    return payload


def build_fail_result_payload(
    rejected_measure_codes: Optional[List[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "result": InspectionResult.FAIL,
        "deficiency_count": 1,
        "deficiency_severity_max": 4,
        "rejected_measure_codes": rejected_measure_codes
        if rejected_measure_codes is not None
        else [],
    }
    payload.update(overrides)
    return payload


def build_cancellation_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cancellation_reason": "Rescheduled at owner request"}
    payload.update(overrides)
    return payload


__all__ = [
    "build_program_payload",
    "build_full_program_payload",
    "build_status_payload",
    "build_open_status_payload",
    "build_catalog_item_payload",
    "build_hvac_heat_pump_payload",
    "build_duct_payload",
    "build_water_heater_payload",
    "build_panel_200a_payload",
    "build_panel_400a_payload",
    "build_induction_stove_payload",
    "build_insulation_payload",
    "build_retirement_payload",
    "build_household_payload",
    "build_income_verification_payload",
    "build_verify_decision_payload",
    "build_reject_income_decision_payload",
    "build_contractor_payload",
    "build_enrollment_decision_payload",
    "build_suspension_payload",
    "build_inspector_payload",
    "build_assessment_measure",
    "build_assessment_payload",
    "build_assessment_decision_payload",
    "build_project_measure",
    "build_project_payload",
    "build_project_review_payload",
    "build_reservation_payload",
    "build_extension_payload",
    "build_measure_result",
    "build_installation_payload",
    "build_stacking_payload",
    "build_payment_payload",
    "build_remediation_payload",
    "build_inspection_payload",
    "build_pass_result_payload",
    "build_conditional_pass_result_payload",
    "build_fail_result_payload",
    "build_cancellation_payload",
]
