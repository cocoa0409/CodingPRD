"""Request payload factories.

Every factory emits only the fields the endpoint accepts — no server-derived
value is ever supplied, because a POST body containing an unknown field is
refused with `ERR_INVALID_REQUEST`. Optional fields default to the sentinel
``...`` and are stripped by the client, so omitting an argument omits the key.
"""

from typing import Any, Dict, List, Optional

from .types import (
    ActivityType,
    AssessmentType,
    ClosureAction,
    PriorityBasis,
    SanctionedLevel,
    SurfaceType,
    TaskType,
    WeatherCondition,
)

# ---------------------------------------------------------------------------
# Field
# ---------------------------------------------------------------------------


def make_field_payload(
    name: str = "Grass Main 1",
    surface_type: str = SurfaceType.NATURAL_GRASS,
    installed_on_date: str = "2018-04-15",
    expected_life_years: int = 12,
    area_sq_ft: int = 80000,
    sanctioned_level: str = SanctionedLevel.STATE,
    warranty_expires_on: Any = ...,
    infill_depth_mm: Any = ...,
    predecessor_field_id: Any = ...,
) -> Dict[str, Any]:
    """Registration payload for `POST /turf/fields`."""
    return {
        "name": name,
        "surface_type": surface_type,
        "installed_on_date": installed_on_date,
        "expected_life_years": expected_life_years,
        "area_sq_ft": area_sq_ft,
        "sanctioned_level": sanctioned_level,
        "warranty_expires_on": warranty_expires_on,
        "infill_depth_mm": infill_depth_mm,
        "predecessor_field_id": predecessor_field_id,
    }


def make_natural_grass_field_payload(
    name: str = "Grass Main 1",
    installed_on_date: str = "2018-04-15",
    expected_life_years: int = 12,
    area_sq_ft: int = 80000,
    sanctioned_level: str = SanctionedLevel.STATE,
    warranty_expires_on: Any = "2026-04-15",
    predecessor_field_id: Any = ...,
) -> Dict[str, Any]:
    """A grass field carries no `infill_depth_mm` at all."""
    return make_field_payload(
        name=name,
        surface_type=SurfaceType.NATURAL_GRASS,
        installed_on_date=installed_on_date,
        expected_life_years=expected_life_years,
        area_sq_ft=area_sq_ft,
        sanctioned_level=sanctioned_level,
        warranty_expires_on=warranty_expires_on,
        predecessor_field_id=predecessor_field_id,
    )


def make_synthetic_field_payload(
    name: str = "Synthetic Stadium 1",
    installed_on_date: str = "2016-06-01",
    expected_life_years: int = 10,
    area_sq_ft: int = 70000,
    sanctioned_level: str = SanctionedLevel.REGIONAL,
    warranty_expires_on: Any = "2024-06-01",
    infill_depth_mm: float = 34.0,
    predecessor_field_id: Any = ...,
) -> Dict[str, Any]:
    """A synthetic field requires `infill_depth_mm`."""
    return make_field_payload(
        name=name,
        surface_type=SurfaceType.SYNTHETIC_TURF,
        installed_on_date=installed_on_date,
        expected_life_years=expected_life_years,
        area_sq_ft=area_sq_ft,
        sanctioned_level=sanctioned_level,
        warranty_expires_on=warranty_expires_on,
        infill_depth_mm=infill_depth_mm,
        predecessor_field_id=predecessor_field_id,
    )


def make_closure_order_payload(
    action: str = ClosureAction.CLOSE_ADMIN,
    reason_code: str = "IRRIGATION_MAIN_BREAK",
) -> Dict[str, Any]:
    """Payload for `POST /turf/fields/{id}/closure-order`."""
    return {"action": action, "reason_code": reason_code}


# ---------------------------------------------------------------------------
# StaffMember
# ---------------------------------------------------------------------------


def make_staff_member_payload(
    full_name: str = "Dana Reyes",
    roles: Optional[List[str]] = None,
    employment_status: Any = ...,
) -> Dict[str, Any]:
    """Payload for `POST /turf/staff-members`."""
    return {
        "full_name": full_name,
        "roles": list(roles) if roles is not None else ["FacilitiesDirector"],
        "employment_status": employment_status,
    }


# ---------------------------------------------------------------------------
# MaintenanceTask
# ---------------------------------------------------------------------------


def make_maintenance_task_payload(
    field_id: str,
    assigned_staff_member_id: str,
    task_type: str = TaskType.AERATION,
    scheduled_start_utc: str = "2026-08-10T08:00:00Z",
    scheduled_end_utc: str = "2026-08-10T10:00:00Z",
    nitrogen_lb_per_1000_sq_ft: Any = ...,
    planned_for_certification_window: Any = ...,
) -> Dict[str, Any]:
    """Payload for `POST /turf/maintenance-tasks`."""
    return {
        "field_id": field_id,
        "assigned_staff_member_id": assigned_staff_member_id,
        "task_type": task_type,
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_end_utc": scheduled_end_utc,
        "nitrogen_lb_per_1000_sq_ft": nitrogen_lb_per_1000_sq_ft,
        "planned_for_certification_window": planned_for_certification_window,
    }


def make_task_start_payload() -> Dict[str, Any]:
    """`START` carries no other value; `started_at_utc` comes from the clock."""
    return {"action": "START"}


def make_task_complete_payload(completed_at_utc: str) -> Dict[str, Any]:
    """`COMPLETE` requires a `completed_at_utc` in the body."""
    return {"action": "COMPLETE", "completed_at_utc": completed_at_utc}


def make_task_cancel_payload(
    cancellation_reason: str = "CONTRACTOR_UNAVAILABLE",
) -> Dict[str, Any]:
    """`CANCEL` requires a `cancellation_reason` in the body."""
    return {"action": "CANCEL", "cancellation_reason": cancellation_reason}


# ---------------------------------------------------------------------------
# SafetyAssessment
# ---------------------------------------------------------------------------


def make_impact_assessment_payload(
    field_id: str,
    inspector_staff_member_id: str,
    gmax_readings: Optional[List[float]] = None,
    assessed_at_utc: str = "2026-08-01T00:00:00Z",
) -> Dict[str, Any]:
    """An `IMPACT_ATTENUATION` test carries three readings and no declared result."""
    return {
        "field_id": field_id,
        "inspector_staff_member_id": inspector_staff_member_id,
        "assessment_type": AssessmentType.IMPACT_ATTENUATION,
        "assessed_at_utc": assessed_at_utc,
        "gmax_readings": list(gmax_readings) if gmax_readings is not None else [120.0, 120.0, 120.0],
        "declared_result": None,
    }


def make_inspection_assessment_payload(
    field_id: str,
    inspector_staff_member_id: str,
    assessment_type: str = AssessmentType.STRIPING_LAYOUT,
    declared_result: str = "PASS",
    assessed_at_utc: str = "2026-08-01T00:00:00Z",
) -> Dict[str, Any]:
    """A `GOAL_ANCHORING` or `STRIPING_LAYOUT` verdict carries no readings."""
    return {
        "field_id": field_id,
        "inspector_staff_member_id": inspector_staff_member_id,
        "assessment_type": assessment_type,
        "assessed_at_utc": assessed_at_utc,
        "gmax_readings": None,
        "declared_result": declared_result,
    }


def make_void_payload(void_reason: str = "CALIBRATION_DEFECT") -> Dict[str, Any]:
    """Payload for `POST /turf/safety-assessments/{id}/void`."""
    return {"void_reason": void_reason}


# ---------------------------------------------------------------------------
# RemediationOrder
# ---------------------------------------------------------------------------


def make_submit_verification_payload(
    verification_assessment_id: str,
    submitted_by_staff_member_id: str,
    remediation_notes: str = "Infill topped up and re-groomed across the goal mouths.",
) -> Dict[str, Any]:
    """Payload for `POST /turf/remediation-orders/{id}/submit-verification`."""
    return {
        "verification_assessment_id": verification_assessment_id,
        "submitted_by_staff_member_id": submitted_by_staff_member_id,
        "remediation_notes": remediation_notes,
    }


def make_decide_verification_payload(
    decision: str = "ACCEPT", decision_notes: Any = ...
) -> Dict[str, Any]:
    """Payload for `POST /turf/remediation-orders/{id}/decide-verification`."""
    return {"decision": decision, "decision_notes": decision_notes}


# ---------------------------------------------------------------------------
# UsageBooking
# ---------------------------------------------------------------------------


def make_usage_booking_payload(
    field_id: str,
    requested_by_staff_member_id: str,
    activity_type: str = ActivityType.GAME,
    window_start_utc: str = "2026-08-02T19:00:00Z",
    window_end_utc: str = "2026-08-02T23:00:00Z",
    expected_participant_count: int = 60,
) -> Dict[str, Any]:
    """Payload for `POST /turf/usage-bookings`."""
    return {
        "field_id": field_id,
        "requested_by_staff_member_id": requested_by_staff_member_id,
        "activity_type": activity_type,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "expected_participant_count": expected_participant_count,
    }


def make_close_out_payload(
    outcome: str = "PLAYED",
    actual_duration_hours: float = 4.00,
    actual_participant_count: int = 60,
    weather_condition: str = WeatherCondition.DRY,
) -> Dict[str, Any]:
    """Payload for `POST /turf/usage-bookings/{id}/close-out`; all four required."""
    return {
        "outcome": outcome,
        "actual_duration_hours": actual_duration_hours,
        "actual_participant_count": actual_participant_count,
        "weather_condition": weather_condition,
    }


# ---------------------------------------------------------------------------
# CertificationPacket
# ---------------------------------------------------------------------------


def make_certification_packet_payload(
    field_id: str,
    governing_assessment_id: str,
    expected_field_version: int,
    competition_season_label: str = "2026-2027 Autumn",
) -> Dict[str, Any]:
    """Payload for `POST /turf/certification-packets`."""
    return {
        "field_id": field_id,
        "governing_assessment_id": governing_assessment_id,
        "competition_season_label": competition_season_label,
        "expected_field_version": expected_field_version,
    }


def make_packet_submit_payload(submitted_by_staff_member_id: str) -> Dict[str, Any]:
    """Payload for `POST /turf/certification-packets/{id}/submit`."""
    return {"submitted_by_staff_member_id": submitted_by_staff_member_id}


def make_packet_decide_payload(
    decision: str,
    decided_by_staff_member_id: str,
    decision_notes: Any = ...,
) -> Dict[str, Any]:
    """Payload for `POST /turf/certification-packets/{id}/decide`."""
    return {
        "decision": decision,
        "decided_by_staff_member_id": decided_by_staff_member_id,
        "decision_notes": decision_notes,
    }


# ---------------------------------------------------------------------------
# CapitalBudget and ReplacementPlan
# ---------------------------------------------------------------------------


def make_capital_budget_payload(
    fiscal_year: int = 2027, total_authorized_amount_cents: int = 5825556
) -> Dict[str, Any]:
    """Payload for `POST /turf/capital-budgets`."""
    return {
        "fiscal_year": fiscal_year,
        "total_authorized_amount_cents": total_authorized_amount_cents,
    }


def make_replacement_plan_payload(
    field_id: str,
    capital_budget_id: str,
    expected_field_version: int,
    target_surface_type: str = SurfaceType.SYNTHETIC_TURF,
    area_sq_ft: int = 70000,
    priority_basis: str = PriorityBasis.CONDITION_RISK,
    planned_install_year: int = 2027,
) -> Dict[str, Any]:
    """Payload for `POST /turf/replacement-plans`."""
    return {
        "field_id": field_id,
        "capital_budget_id": capital_budget_id,
        "target_surface_type": target_surface_type,
        "area_sq_ft": area_sq_ft,
        "priority_basis": priority_basis,
        "planned_install_year": planned_install_year,
        "expected_field_version": expected_field_version,
    }


def make_plan_submit_payload(submitted_by_staff_member_id: str) -> Dict[str, Any]:
    """Payload for `POST /turf/replacement-plans/{id}/submit`."""
    return {"submitted_by_staff_member_id": submitted_by_staff_member_id}


def make_plan_decide_payload(
    decision: str,
    decided_by_staff_member_id: str,
    decision_notes: Any = ...,
) -> Dict[str, Any]:
    """Payload for `POST /turf/replacement-plans/{id}/decide`."""
    return {
        "decision": decision,
        "decided_by_staff_member_id": decided_by_staff_member_id,
        "decision_notes": decision_notes,
    }


def make_disposal_manifest_payload(
    manifest_reference: str = "MAN-2027-0001",
    disposal_facility_name: str = "Rivergate Polymer Recovery",
    diverted_tonnage: float = 46.0,
    total_tonnage: float = 50.0,
) -> Dict[str, Any]:
    """Payload for `POST /turf/replacement-plans/{id}/disposal-manifest`."""
    return {
        "manifest_reference": manifest_reference,
        "disposal_facility_name": disposal_facility_name,
        "diverted_tonnage": diverted_tonnage,
        "total_tonnage": total_tonnage,
    }


def make_disposal_complete_payload(completed_at_utc: str) -> Dict[str, Any]:
    """Payload for `POST /turf/replacement-plans/{id}/complete`."""
    return {"completed_at_utc": completed_at_utc}
