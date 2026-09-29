"""Request-payload builders.

Each builder returns a payload that satisfies the PRD's request screen on its own,
and accepts `**overrides` so a test can vary exactly the one field it is about.
Passing `None` for an override removes the key, which is how a test exercises the
PRD's documented defaults for optional inputs.
"""

from __future__ import annotations

from typing import Any, Dict


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    """Sentinel meaning 'leave this optional field out of the request body'."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "OMIT"


_OMIT = _Omit()
OMIT = _OMIT


# --- Partnership ----------------------------------------------------------


def partnership_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "university_name": "Riverbend State University",
            "university_ipeds_id": "224554",
            "partner_org_name": "Cadence Online Partners",
            "contract_structure": "REVENUE_SHARE",
            "term_months": 84,
            "effective_date": "2026-08-01",
            "revenue_recognition_method": "PERIOD_STRAIGHT_LINE",
            "marketing_budget_cents": 4000000,
            "exclusivity_cip_codes": ["52.0201"],
            "bundled_services_exception_claimed": True,
        },
        overrides,
    )


def contract_action_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# --- Program --------------------------------------------------------------


def program_payload(partnership_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "partnership_id": partnership_id,
            "program_name": "MBA Online",
            "cip_code": "52.0201",
            "delivery_modality": "ASYNCHRONOUS",
            "credential_level": "MASTERS",
            "tuition_per_credit_cents": 62500,
            "credits_to_complete": 36,
            "enrollment_cap": 40,
            "projected_annual_enrollments": 300,
            "competitor_program_count": 3,
            "regional_wage_premium_pct": 25.0,
            "employer_partner_count": 2,
            "prior_year_inquiry_volume": 1750,
            "launch_window_start": "2026-08-01",
            "launch_window_end": "2026-12-31",
            "required_service_domains": ["MARKETING"],
        },
        overrides,
    )


def lifecycle_action_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# --- Course ---------------------------------------------------------------


def course_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "course_code": "MBA-501",
            "title": "Foundations of Analytics",
            "credits": 3,
            "content_owner": "UNIVERSITY",
            "design_cost_cents": 1500000,
            "required_for_launch": True,
        },
        overrides,
    )


def design_action_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# --- Service scope --------------------------------------------------------


def service_scope_payload(service_domain: str = "MARKETING", **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "service_domain": service_domain,
            "responsible_party": "PARTNER",
            "sla_response_hours": 24,
            "cost_bearer": "PARTNER",
        },
        overrides,
    )


# --- Enrollment counselor -------------------------------------------------


def counselor_payload(partnership_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "partnership_id": partnership_id,
            "full_name": "Rosa Vento",
            "employer": "PARTNER",
            "monthly_base_salary_cents": 500000,
        },
        overrides,
    )


def compensation_plan_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "comp_plan_type": "SALARY_PLUS_QUALITATIVE",
            "annual_base_cents": 6000000,
            "variable_component_cents": 100000,
            "variable_basis": "QUALITATIVE_MULTI_FACTOR",
        },
        overrides,
    )


def compliance_review_payload(decision: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "decision": decision,
            "reviewer_note": "Qualitative multi-factor plan under the bundled-services exception.",
        },
        overrides,
    )


def performance_run_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"window_start": "2026-08-01", "window_end": "2026-08-31"}, overrides)


# --- Lead and enrollment --------------------------------------------------


def lead_payload(program_id: str, counselor_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "counselor_id": counselor_id,
            "source_channel": "PAID_SEARCH",
            "prospect_external_id": "P-1001",
        },
        overrides,
    )


def advance_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


def enroll_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "student_external_id": "S-2001",
            "credits_enrolled": 9,
            "term_start_date": "2026-09-01",
            "term_end_date": "2026-12-15",
        },
        overrides,
    )


def academic_action_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# --- Ledgers --------------------------------------------------------------


def tuition_payment_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "entry_type": "PAYMENT",
            "amount_cents": 562500,
            "posted_date": "2026-09-05",
            "reference_note": "Fall 2026 term payment in full",
        },
        overrides,
    )


def marketing_spend_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "entry_type": "SPEND",
            "channel": "PAID_SEARCH",
            "amount_cents": 300000,
            "spend_date": "2026-09-05",
        },
        overrides,
    )


# --- Settlement -----------------------------------------------------------


def statement_payload(expected_partnership_version: int, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "expected_partnership_version": expected_partnership_version,
        },
        overrides,
    )


def statement_action_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# --- Teach-out ------------------------------------------------------------


def teach_out_plan_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "teach_out_end_date": "2027-06-30",
            "student_notification_date": "2026-09-01",
            "asset_transfer_scope": "COURSE_CONTENT_ONLY",
        },
        overrides,
    )


def certify_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "asset_transfer_confirmed": True,
            "certification_note": "Teach-out obligations reviewed and accepted.",
        },
        overrides,
    )
