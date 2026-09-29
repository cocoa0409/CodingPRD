"""Request payload builders.

Every builder returns a fresh dict of valid defaults; keyword overrides are
merged on top, and passing ``None`` for a key is not special-cased, so callers
that need a key absent should ``pop`` it from the result.
"""

from typing import Any, Dict, Optional

from .constants import (
    CA_MIN_WEEKLY_SALARY_CENTS,
    CA_RECLASS_NOTICE_DAYS,
    DEFAULT_CLOCK_UTC,
    TX_MIN_WEEKLY_SALARY_CENTS,
    TX_RECLASS_NOTICE_DAYS,
)
from .types import (
    BackWageMethod,
    CommunicationAction,
    ConversionMethod,
    CorrectionDecision,
    DiscretionLevel,
    DutiesTestVariant,
    ExemptionTest,
    FlsStatus,
    IcTest,
    LookbackPolicy,
    NoticeChannel,
    RespondentType,
    SalaryBasis,
    TriggerType,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    base.update(overrides)
    return base


def clock_payload(current_utc: str = DEFAULT_CLOCK_UTC) -> Dict[str, Any]:
    return {"current_utc": current_utc}


def california_rule_payload(**overrides: Any) -> Dict[str, Any]:
    """Jurisdiction whose weekly floor strictly exceeds the federal floor."""
    return _merge(
        {
            "state_code": "CA",
            "min_weekly_salary_cents": CA_MIN_WEEKLY_SALARY_CENTS,
            "duties_test_variant": DutiesTestVariant.QUANTITATIVE_50PCT,
            "ic_test": IcTest.ABC,
            "hce_shortcut_recognized": False,
            "reclass_notice_days": CA_RECLASS_NOTICE_DAYS,
        },
        overrides,
    )


def texas_rule_payload(**overrides: Any) -> Dict[str, Any]:
    """Jurisdiction whose weekly floor sits below the federal floor."""
    return _merge(
        {
            "state_code": "TX",
            "min_weekly_salary_cents": TX_MIN_WEEKLY_SALARY_CENTS,
            "duties_test_variant": DutiesTestVariant.FEDERAL,
            "ic_test": IcTest.ECONOMIC_REALITY,
            "reclass_notice_days": TX_RECLASS_NOTICE_DAYS,
        },
        overrides,
    )


def state_rule_payload(state_code: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "state_code": state_code,
            "min_weekly_salary_cents": CA_MIN_WEEKLY_SALARY_CENTS,
            "duties_test_variant": DutiesTestVariant.QUANTITATIVE_50PCT,
            "ic_test": IcTest.ABC,
            "hce_shortcut_recognized": False,
            "reclass_notice_days": CA_RECLASS_NOTICE_DAYS,
        },
        overrides,
    )


def audit_project_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "FY26 Classification Audit",
            "fiscal_year": 2026,
            "lookback_policy": LookbackPolicy.STANDARD_2Y,
        },
        overrides,
    )


def job_family_payload(audit_project_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "audit_project_id": audit_project_id,
            "name": "Operations Leadership",
            "code": "OPS-LEAD",
        },
        overrides,
    )


def position_payload(job_family_id: str, **overrides: Any) -> Dict[str, Any]:
    """A California supervisor whose weekly salary sits below the state floor."""
    return _merge(
        {
            "job_family_id": job_family_id,
            "title": "Shift Supervisor",
            "job_code": "SS-100",
            "current_fls_status": FlsStatus.EXEMPT,
            "claimed_exemption_test": ExemptionTest.EXECUTIVE,
            "annual_salary_cents": 5500000,
            "salary_basis": SalaryBasis.SALARY,
            "work_state_code": "CA",
            "incumbent_count": 2,
            "avg_weekly_hours": 47,
        },
        overrides,
    )


def duty_statement_payload(position_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "position_id": position_id,
            "duty_code": "D-1",
            "description": "Directs the shift",
            "claimed_time_pct": 60.0,
            "is_exempt_duty": True,
            "discretion_level": DiscretionLevel.INDEPENDENT_JUDGMENT,
        },
        overrides,
    )


def interview_payload(
    position_id: str,
    interviewer_user_id: str,
    scheduled_start_at: str,
    scheduled_end_at: str,
    respondent_type: str = RespondentType.MANAGER,
    respondent_ref: str = "MGR-1",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "position_id": position_id,
            "respondent_type": respondent_type,
            "respondent_ref": respondent_ref,
            "interviewer_user_id": interviewer_user_id,
            "scheduled_start_at": scheduled_start_at,
            "scheduled_end_at": scheduled_end_at,
        },
        overrides,
    )


def interview_completion_payload(
    reported_exempt_duty_pct: float,
    reported_weekly_hours: float,
    supervises_headcount: int,
    has_hire_fire_influence: bool,
) -> Dict[str, Any]:
    return {
        "reported_exempt_duty_pct": reported_exempt_duty_pct,
        "reported_weekly_hours": reported_weekly_hours,
        "supervises_headcount": supervises_headcount,
        "has_hire_fire_influence": has_hire_fire_influence,
    }


def exemption_analysis_payload(
    position_id: str, expected_position_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "position_id": position_id,
            "applied_test": ExemptionTest.EXECUTIVE,
            "expected_position_version": expected_position_version,
        },
        overrides,
    )


def reclassification_case_payload(position_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "position_id": position_id,
            "effective_date": "2026-10-01",
            "effective_end_date": "2026-10-31",
            "conversion_method": ConversionMethod.SALARY_DIV_2080,
        },
        overrides,
    )


def back_wage_estimate_payload(
    reclassification_case_id: str,
    expected_reclassification_case_version: int,
    method: str = BackWageMethod.FULL_RATE,
) -> Dict[str, Any]:
    return {
        "reclassification_case_id": reclassification_case_id,
        "method": method,
        "expected_reclassification_case_version": expected_reclassification_case_version,
    }


def voluntary_correction_payload(
    reclassification_case_id: str,
    proposed_amount_cents: int,
    decision: str = CorrectionDecision.SELF_CORRECT_FULL,
) -> Dict[str, Any]:
    return {
        "reclassification_case_id": reclassification_case_id,
        "decision": decision,
        "proposed_amount_cents": proposed_amount_cents,
    }


def correction_approval_payload(approved_amount_cents: int) -> Dict[str, Any]:
    return {"disposition": "APPROVE", "approved_amount_cents": approved_amount_cents}


def correction_rejection_payload(rejection_reason: str) -> Dict[str, Any]:
    return {"disposition": "REJECT", "rejection_reason": rejection_reason}


def communication_payload(
    action: str = CommunicationAction.SEND_NOTICE,
    notice_channel: Optional[str] = NoticeChannel.EMAIL,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if notice_channel is not None:
        payload["notice_channel"] = notice_channel
    return _merge(payload, overrides)


def contractor_review_payload(audit_project_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "audit_project_id": audit_project_id,
            "vendor_name": "Northline Logistics",
            "engagement_state_code": "CA",
            "free_from_control": False,
            "outside_usual_course": False,
            "independent_trade": True,
        },
        overrides,
    )


def economic_reality_factors(**overrides: Any) -> Dict[str, bool]:
    return _merge(
        {
            "control_by_worker": True,
            "opportunity_for_profit_or_loss": True,
            "worker_investment": True,
            "relationship_is_project_based": True,
            "skill_and_initiative": True,
            "not_integral_to_business": False,
        },
        overrides,
    )


def job_change_trigger_payload(
    position_id: str, trigger_type: str = TriggerType.SALARY_CHANGE, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"position_id": position_id, "trigger_type": trigger_type}, overrides)


def project_status_payload(target_status: str) -> Dict[str, Any]:
    return {"target_status": target_status}
