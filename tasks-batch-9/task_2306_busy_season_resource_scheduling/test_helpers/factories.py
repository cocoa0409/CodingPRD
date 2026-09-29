"""Payload factories -- one per writable record type.

Each factory returns only the fields a client may supply; every derived,
system-owned and computed field is deliberately absent so the server has to
produce it. ``**overrides`` replaces or adds keys, and passing ``None`` for an
optional key removes it from the payload entirely (useful for exercising the
omitted-field default).
"""

from __future__ import annotations

from typing import Any, Dict

DEFAULTS: Dict[str, Dict[str, Any]] = {
    "client": {
        "name": "Meridian Manufacturing",
        "industry_code": "MANUFACTURING",
        "public_interest_entity": False,
        "fiscal_year_end": "2026-12-31",
    },
    "staff_member": {
        "full_name": "Sam Oyelaran",
        "level": "SENIOR",
        "service_center": "DOMESTIC",
        "industry_specialization": "MANUFACTURING",
        "cpa_licensed": True,
        "base_weekly_cap_hours": 40.00,
        "hourly_bill_rate": 180.00,
    },
    "engagement": {
        "service_line": "AUDIT",
        "busy_season_year": 2026,
        "deadline_date": "2026-10-15",
        "budget_fee_amount": 6000.00,
    },
    "engagement_phase": {
        "phase_type": "FIELDWORK",
        "expected_hours": 45.00,
        "window_start_date": "2026-08-03",
        "window_end_date": "2026-08-31",
        "required_level": "SENIOR",
        "required_industry_specialization": "MANUFACTURING",
        "requires_cpa_licensed": True,
    },
    "assignment": {
        "start_date": "2026-08-03",
        "end_date": "2026-08-10",
        "allocated_hours": 20.00,
    },
    "availability_exception": {
        "exception_type": "PTO",
        "start_date": "2026-08-03",
        "end_date": "2026-08-07",
        "available_hours_per_day": 0.00,
    },
    "time_entry": {
        "work_date": "2026-08-04",
        "hours": 4.00,
        "entry_type": "EXECUTION",
    },
    "independence_restriction": {
        "restriction_type": "FINANCIAL_INTEREST",
        "effective_start_date": "2026-08-01",
        "effective_end_date": "2026-12-31",
    },
    "review_capacity_window": {
        "week_start_date": "2026-08-03",
        "review_capacity_hours": 10.00,
    },
    "reschedule_plan": {
        "trigger_reason": "CLIENT_READINESS_SLIP",
        "shift_days": 7,
    },
    "workload_waiver": {
        "week_start_date": "2026-08-03",
        "extra_hours_allowance": 3.00,
    },
}


def _build(key: str, overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(DEFAULTS[key])
    for field, value in overrides.items():
        if value is None:
            payload.pop(field, None)
        else:
            payload[field] = value
    return payload


def create_client_payload(**overrides: Any) -> Dict[str, Any]:
    return _build("client", overrides)


def create_staff_member_payload(**overrides: Any) -> Dict[str, Any]:
    return _build("staff_member", overrides)


def create_engagement_payload(
    client_id: str, engagement_partner_staff_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = _build("engagement", overrides)
    payload["client_id"] = overrides.get("client_id", client_id)
    payload["engagement_partner_staff_id"] = overrides.get(
        "engagement_partner_staff_id", engagement_partner_staff_id
    )
    return payload


def create_engagement_phase_payload(engagement_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = _build("engagement_phase", overrides)
    payload["engagement_id"] = overrides.get("engagement_id", engagement_id)
    return payload


def create_assignment_payload(
    engagement_phase_id: str, staff_member_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = _build("assignment", overrides)
    payload["engagement_phase_id"] = overrides.get(
        "engagement_phase_id", engagement_phase_id
    )
    payload["staff_member_id"] = overrides.get("staff_member_id", staff_member_id)
    return payload


def create_availability_exception_payload(
    staff_member_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = _build("availability_exception", overrides)
    payload["staff_member_id"] = overrides.get("staff_member_id", staff_member_id)
    return payload


def create_time_entry_payload(assignment_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = _build("time_entry", overrides)
    payload["assignment_id"] = overrides.get("assignment_id", assignment_id)
    return payload


def create_independence_restriction_payload(
    client_id: str, staff_member_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = _build("independence_restriction", overrides)
    payload["client_id"] = overrides.get("client_id", client_id)
    payload["staff_member_id"] = overrides.get("staff_member_id", staff_member_id)
    return payload


def create_review_capacity_window_payload(
    reviewer_staff_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = _build("review_capacity_window", overrides)
    payload["reviewer_staff_id"] = overrides.get("reviewer_staff_id", reviewer_staff_id)
    return payload


def create_reschedule_plan_payload(engagement_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = _build("reschedule_plan", overrides)
    payload["engagement_id"] = overrides.get("engagement_id", engagement_id)
    return payload


def create_workload_waiver_payload(
    staff_member_id: str, engagement_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = _build("workload_waiver", overrides)
    payload["staff_member_id"] = overrides.get("staff_member_id", staff_member_id)
    payload["engagement_id"] = overrides.get("engagement_id", engagement_id)
    return payload


__all__ = [
    "DEFAULTS",
    "create_client_payload",
    "create_staff_member_payload",
    "create_engagement_payload",
    "create_engagement_phase_payload",
    "create_assignment_payload",
    "create_availability_exception_payload",
    "create_time_entry_payload",
    "create_independence_restriction_payload",
    "create_review_capacity_window_payload",
    "create_reschedule_plan_payload",
    "create_workload_waiver_payload",
]
