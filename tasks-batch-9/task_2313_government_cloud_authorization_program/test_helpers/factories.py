"""Request payload builders.

Every factory returns a valid payload with domain-plausible defaults and accepts
``**overrides`` to vary one field at a time. Passing ``OMIT`` as an override
value deletes the key, which is how required-field-missing cases are built.
"""

from typing import Any, Dict, List, Optional

from .constants import SPONSORSHIP_CAPACITY_DEFAULT
from .test_users import ASSESSOR_1


class _Omit:
    """Sentinel meaning "delete this key from the payload"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


#: Sentinel: ``build_offering_payload(name=OMIT)`` produces a payload with no
#: ``name`` key at all, rather than a ``name`` of ``None``.
OMIT = _Omit()


def _finish(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload.update(overrides)
    return {k: v for k, v in payload.items() if not isinstance(v, _Omit)}


# ---------------------------------------------------------------------------
# Reference registries
# ---------------------------------------------------------------------------


def build_clock_payload(to_iso8601: str, **overrides) -> dict:
    """Payload for POST /_clock/set_current_utc."""
    return _finish({"to_iso8601": to_iso8601}, overrides)


def build_agency_payload(
    name: str = "Department of Transportation",
    agency_code: str = "DOT",
    **overrides,
) -> dict:
    """Payload for POST /agencies."""
    return _finish(
        {
            "name": name,
            "agency_code": agency_code,
            "sponsorship_capacity": SPONSORSHIP_CAPACITY_DEFAULT,
        },
        overrides,
    )


def build_family(
    family_code: str, required_control_count: int, priority_rank: int
) -> dict:
    """One element of a control baseline's ``families`` array."""
    return {
        "family_code": family_code,
        "required_control_count": required_control_count,
        "priority_rank": priority_rank,
    }


#: The two-family MODERATE shape used by most workflow fixtures: three required
#: controls in total, so three documented implementations reach 100.00 coverage.
MODERATE_FAMILIES = [build_family("AC", 2, 1), build_family("SC", 1, 2)]

#: The shape whose pinned two-step rounding yields 33.34 rather than 33.33.
SPLIT_ROUNDING_FAMILIES = [build_family("AC", 3, 1), build_family("SC", 6, 2)]


def build_baseline_payload(
    impact_level: str = "MODERATE",
    families: Optional[List[dict]] = None,
    effective_from: str = "2026-01-01T00:00:00Z",
    **overrides,
) -> dict:
    """Payload for POST /control-baselines."""
    return _finish(
        {
            "impact_level": impact_level,
            "version_label": f"Rev5-{impact_level}",
            "effective_from": effective_from,
            "families": list(families) if families is not None else list(MODERATE_FAMILIES),
            "retired": False,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Offering intake
# ---------------------------------------------------------------------------


def build_offering_payload(
    name: str = "GovCloud Compute",
    assessment_budget_usd: float = 400000.00,
    **overrides,
) -> dict:
    """Payload for POST /offerings."""
    return _finish(
        {
            "name": name,
            "provider_name": "Aurora Cloud",
            "service_model": "IAAS",
            "deployment_model": "GOV_COMMUNITY",
            "assessment_budget_usd": assessment_budget_usd,
        },
        overrides,
    )


def build_data_category_payload(
    category_code: str = "PII",
    confidentiality_impact: str = "MODERATE",
    integrity_impact: str = "MODERATE",
    availability_impact: str = "LOW",
    **overrides,
) -> dict:
    """Payload for POST /offerings/{id}/data-categories."""
    return _finish(
        {
            "category_code": category_code,
            "confidentiality_impact": confidentiality_impact,
            "integrity_impact": integrity_impact,
            "availability_impact": availability_impact,
        },
        overrides,
    )


def build_category_decision_payload(decision: str = "CONFIRM", **overrides) -> dict:
    """Payload for POST /data-categories/{id}/confirm."""
    return _finish({"decision": decision}, overrides)


def build_path_selection_payload(
    authorization_path: str = "AGENCY_SPONSORED",
    sponsor_agency_id: Optional[str] = None,
    **overrides,
) -> dict:
    """Payload for POST /offerings/{id}/path-selection.

    On the PROGRAM_BOARD branch ``sponsor_agency_id`` must be absent, so it is
    omitted whenever it is not supplied.
    """
    payload: Dict[str, Any] = {"authorization_path": authorization_path}
    if sponsor_agency_id is not None:
        payload["sponsor_agency_id"] = sponsor_agency_id
    return _finish(payload, overrides)


# ---------------------------------------------------------------------------
# Control implementations
# ---------------------------------------------------------------------------

DEFAULT_CRM_TEXT = "Customer must configure MFA for all privileged console users."


def build_control_implementation_payload(
    offering_id: str,
    control_id: str = "AC-2",
    family_code: str = "AC",
    implementation_status: str = "IMPLEMENTED",
    crm_documented: bool = True,
    **overrides,
) -> dict:
    """Payload for POST /control-implementations."""
    payload: Dict[str, Any] = {
        "offering_id": offering_id,
        "control_id": control_id,
        "family_code": family_code,
        "implementation_status": implementation_status,
        "crm_documented": crm_documented,
    }
    if crm_documented:
        payload["customer_responsibility_text"] = DEFAULT_CRM_TEXT
    return _finish(payload, overrides)


# ---------------------------------------------------------------------------
# Assessment engagement
# ---------------------------------------------------------------------------


def build_engagement_payload(
    offering_id: str,
    contracted_hours: float = 200.00,
    labor_cost_usd: float = 120000.00,
    assessor_user_id: str = ASSESSOR_1,
    **overrides,
) -> dict:
    """Payload for POST /assessment-engagements."""
    return _finish(
        {
            "offering_id": offering_id,
            "assessor_org_name": "Delta Assessors LLC",
            "assessor_user_id": assessor_user_id,
            "contracted_hours": contracted_hours,
            "labor_cost_usd": labor_cost_usd,
        },
        overrides,
    )


def build_plan_payload(
    planned_test_start: str = "2026-03-01T00:00:00Z",
    planned_test_end: str = "2026-03-31T00:00:00Z",
    **overrides,
) -> dict:
    """Payload for POST /assessment-engagements/{id}/plan."""
    return _finish(
        {
            "planned_test_start": planned_test_start,
            "planned_test_end": planned_test_end,
        },
        overrides,
    )


def build_plan_decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    """Payload for POST /assessment-engagements/{id}/plan-approval."""
    return _finish({"decision": decision}, overrides)


def build_test_slot_payload(
    engagement_id: str,
    start_at: str = "2026-03-02T09:00:00Z",
    end_at: str = "2026-03-02T17:00:00Z",
    hours: float = 8.00,
    family_code: str = "AC",
    **overrides,
) -> dict:
    """Payload for POST /test-slots."""
    return _finish(
        {
            "engagement_id": engagement_id,
            "family_code": family_code,
            "start_at": start_at,
            "end_at": end_at,
            "hours": hours,
        },
        overrides,
    )


def build_finding(
    control_id: str = "AC-2",
    severity: str = "MODERATE",
    detected_at: str = "2026-03-01T00:00:00Z",
) -> dict:
    """One element of the assessment report's ``findings`` array."""
    return {
        "control_id": control_id,
        "severity": severity,
        "detected_at": detected_at,
    }


def build_report_payload(findings: Optional[List[dict]] = None, **overrides) -> dict:
    """Payload for POST /assessment-engagements/{id}/report.

    The ``findings`` array may legally be empty, so the default is an empty list
    rather than a sample finding.
    """
    return _finish({"findings": list(findings) if findings else []}, overrides)


# ---------------------------------------------------------------------------
# Findings, deviations
# ---------------------------------------------------------------------------


def build_poam_item_payload(
    offering_id: str,
    control_id: str = "AC-2",
    severity: str = "MODERATE",
    detected_at: str = "2026-02-01T00:00:00Z",
    **overrides,
) -> dict:
    """Payload for POST /poam-items."""
    return _finish(
        {
            "offering_id": offering_id,
            "control_id": control_id,
            "severity": severity,
            "detected_at": detected_at,
            "source": "SELF_IDENTIFIED",
        },
        overrides,
    )


def build_remediation_payload(action: str, **overrides) -> dict:
    """Payload for POST /poam-items/{id}/remediation."""
    return _finish({"action": action}, overrides)


def build_deviation_payload(
    poam_item_id: str,
    kind: str = "OPERATIONAL_REQUIREMENT",
    requested_extension_days: int = 0,
    **overrides,
) -> dict:
    """Payload for POST /deviation-requests."""
    return _finish(
        {
            "poam_item_id": poam_item_id,
            "kind": kind,
            "justification": "Mitigating compensating controls are already in place.",
            "requested_extension_days": requested_extension_days,
        },
        overrides,
    )


def build_route_payload(review_queue: str = "BOARD", **overrides) -> dict:
    """Payload for POST /deviation-requests/{id}/route."""
    return _finish({"review_queue": review_queue}, overrides)


def build_deviation_decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    """Payload for POST /deviation-requests/{id}/decision."""
    return _finish({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# Package lifecycle
# ---------------------------------------------------------------------------


def build_package_payload(
    offering_id: str,
    engagement_id: str,
    expected_offering_version: int,
    **overrides,
) -> dict:
    """Payload for POST /authorization-packages."""
    return _finish(
        {
            "offering_id": offering_id,
            "engagement_id": engagement_id,
            "expected_offering_version": expected_offering_version,
        },
        overrides,
    )


def build_revision_request_payload(
    revision_note: str = "Round 1: control narrative incomplete.", **overrides
) -> dict:
    """Payload for POST /authorization-packages/{id}/revision-request."""
    return _finish({"revision_note": revision_note}, overrides)


def build_package_decision_payload(
    decision: str = "AUTHORIZE",
    risk_acceptance_note: str = "Agency accepts the residual risk.",
    **overrides,
) -> dict:
    """Payload for POST /authorization-packages/{id}/decision."""
    return _finish(
        {"decision": decision, "risk_acceptance_note": risk_acceptance_note}, overrides
    )


# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------


def build_monitoring_period_payload(period_month: str, **overrides) -> dict:
    """Payload for POST /authorizations/{id}/monitoring-periods."""
    return _finish({"period_month": period_month}, overrides)


def build_scan_submission_payload(
    scan_types: Optional[List[str]] = None, **overrides
) -> dict:
    """Payload for POST /monitoring-periods/{id}/scan-submissions.

    The default carries the three mandatory scan types and omits the optional
    ``CONTAINER``.
    """
    return _finish(
        {
            "scan_types": list(scan_types)
            if scan_types is not None
            else ["INFRASTRUCTURE", "WEB_APP", "DATABASE"]
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Significant changes and reuse
# ---------------------------------------------------------------------------


def build_change_request_payload(
    offering_id: str,
    window_start: str,
    window_end: str,
    change_kind: str = "TECH_REFRESH",
    **overrides,
) -> dict:
    """Payload for POST /significant-change-requests."""
    return _finish(
        {
            "offering_id": offering_id,
            "change_kind": change_kind,
            "description": "Rolling hypervisor refresh across the boundary.",
            "window_start": window_start,
            "window_end": window_end,
            "added_service_count": 0,
        },
        overrides,
    )


def build_change_decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    """Payload for POST /significant-change-requests/{id}/decision."""
    return _finish({"decision": decision}, overrides)


def build_reuse_grant_payload(
    authorization_id: str,
    agency_id: str,
    expected_authorization_version: int,
    **overrides,
) -> dict:
    """Payload for POST /reuse-grants."""
    return _finish(
        {
            "authorization_id": authorization_id,
            "agency_id": agency_id,
            "expected_authorization_version": expected_authorization_version,
        },
        overrides,
    )


def build_incremental_review_payload(
    decision: str = "ACCEPT", findings_count: int = 0, **overrides
) -> dict:
    """Payload for POST /reuse-grants/{id}/incremental-review."""
    return _finish({"decision": decision, "findings_count": findings_count}, overrides)


def build_revoke_payload(reason: str = "AGENCY_REQUEST", **overrides) -> dict:
    """Payload for POST /reuse-grants/{id}/revoke."""
    return _finish({"reason": reason}, overrides)
