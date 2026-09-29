"""
Request-body builders.

Each builder returns a plain dict.  Optional fields are omitted entirely when
their argument is left at ``None`` so that a test can exercise a server-side
default by simply not passing the field, and can exercise an explicit value by
passing it.  All money is integer cents and all rates integer basis points, so
no builder ever produces a float.
"""

from typing import Any, Dict, Optional

from .constants import (
    CLOCK_EPOCH,
    GROUP_BY_DEMOGRAPHIC_BAND,
    MODE_LIGHT_RAIL,
    SAMPLING_SYSTEMATIC_INTERVAL,
)


def _compact(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the keys whose value was left unspecified."""
    return {key: value for key, value in payload.items() if value is not None}


# ── The logical clock ────────────────────────────────────────────────

def clock_payload(to_iso8601: str = CLOCK_EPOCH) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


# ── Fare zones and signage ───────────────────────────────────────────

def fare_zone_payload(
    zone_code: str = "ZN1",
    name: str = "Downtown POP Zone",
    required_sign_count: int = 10,
    penalty_multiplier_bps: Optional[int] = None,
    enforcement_policy: Optional[str] = None,
    max_concurrent_deployments: Optional[int] = None,
) -> Dict[str, Any]:
    return _compact(
        {
            "zone_code": zone_code,
            "name": name,
            "required_sign_count": required_sign_count,
            "penalty_multiplier_bps": penalty_multiplier_bps,
            "enforcement_policy": enforcement_policy,
            "max_concurrent_deployments": max_concurrent_deployments,
        }
    )


def signage_audit_payload(
    zone_id: str,
    audited_at: str,
    signs_verified_count: int,
    deficiency_note: Optional[str] = None,
) -> Dict[str, Any]:
    return _compact(
        {
            "zone_id": zone_id,
            "audited_at": audited_at,
            "signs_verified_count": signs_verified_count,
            "deficiency_note": deficiency_note,
        }
    )


# ── Network ──────────────────────────────────────────────────────────

def transit_line_payload(
    line_code: str = "L1",
    mode: str = MODE_LIGHT_RAIL,
    daily_boardings: int = 42000,
    baseline_evasion_rate_bps: int = 600,
) -> Dict[str, Any]:
    return {
        "line_code": line_code,
        "mode": mode,
        "daily_boardings": daily_boardings,
        "baseline_evasion_rate_bps": baseline_evasion_rate_bps,
    }


def zone_line_assignment_payload(
    zone_id: str,
    line_id: str,
    platform_segment_count: int = 4,
    effective_from: str = CLOCK_EPOCH,
) -> Dict[str, Any]:
    return {
        "zone_id": zone_id,
        "line_id": line_id,
        "platform_segment_count": platform_segment_count,
        "effective_from": effective_from,
    }


# ── Registries ───────────────────────────────────────────────────────

def inspector_payload(
    badge_number: str = "B-100",
    display_name: str = "Inspector One",
    certification_expiry: str = "2027-01-01T00:00:00Z",
    status: Optional[str] = None,
) -> Dict[str, Any]:
    return _compact(
        {
            "badge_number": badge_number,
            "display_name": display_name,
            "certification_expiry": certification_expiry,
            "status": status,
        }
    )


def rider_payload(
    rider_ref: str = "R-100",
    display_name: str = "Rider One",
    demographic_band: Optional[str] = None,
    residence_geo_tract: Optional[str] = None,
    fare_assistance_enrolled: Optional[bool] = None,
) -> Dict[str, Any]:
    return _compact(
        {
            "rider_ref": rider_ref,
            "display_name": display_name,
            "demographic_band": demographic_band,
            "residence_geo_tract": residence_geo_tract,
            "fare_assistance_enrolled": fare_assistance_enrolled,
        }
    )


# ── Deployments and encounters ───────────────────────────────────────

def deployment_payload(
    line_id: str,
    zone_id: str,
    window_start: str = "2026-08-05T06:00:00Z",
    window_end: str = "2026-08-05T14:00:00Z",
    planned_inspector_count: int = 3,
    sampling_method: str = SAMPLING_SYSTEMATIC_INTERVAL,
    target_sample_size: int = 5,
) -> Dict[str, Any]:
    return {
        "line_id": line_id,
        "zone_id": zone_id,
        "window_start": window_start,
        "window_end": window_end,
        "planned_inspector_count": planned_inspector_count,
        "sampling_method": sampling_method,
        "target_sample_size": target_sample_size,
    }


def encounter_payload(
    deployment_id: str,
    inspector_id: str,
    occurred_at: str,
    fare_media_type: str,
    rider_id: Optional[str] = None,
    media_reference: Optional[str] = None,
    media_validated_at: Optional[str] = None,
    media_expires_at: Optional[str] = None,
    media_zone_code: Optional[str] = None,
    identity_capture_method: Optional[str] = None,
) -> Dict[str, Any]:
    return _compact(
        {
            "deployment_id": deployment_id,
            "inspector_id": inspector_id,
            "rider_id": rider_id,
            "occurred_at": occurred_at,
            "fare_media_type": fare_media_type,
            "media_reference": media_reference,
            "media_validated_at": media_validated_at,
            "media_expires_at": media_expires_at,
            "media_zone_code": media_zone_code,
            "identity_capture_method": identity_capture_method,
        }
    )


def resolve_payload(disposition: str) -> Dict[str, Any]:
    return {"disposition": disposition}


# ── Citations and adjudication ───────────────────────────────────────

def citation_payload(encounter_id: str) -> Dict[str, Any]:
    return {"encounter_id": encounter_id}


def citation_payment_payload(amount_cents: int) -> Dict[str, Any]:
    return {"amount_cents": amount_cents}


def hearing_decision_payload(
    decision: str,
    reduced_penalty_cents: Optional[int] = None,
    dismissal_reason_code: Optional[str] = None,
) -> Dict[str, Any]:
    return _compact(
        {
            "decision": decision,
            "reduced_penalty_cents": reduced_penalty_cents,
            "dismissal_reason_code": dismissal_reason_code,
        }
    )


# ── Appeals ──────────────────────────────────────────────────────────

def appeal_payload(
    citation_id: str,
    hearing_id: str,
    grounds_code: str,
    statement: str = "The inspector did not state the zone.",
) -> Dict[str, Any]:
    return {
        "citation_id": citation_id,
        "hearing_id": hearing_id,
        "grounds_code": grounds_code,
        "statement": statement,
    }


def appeal_resubmit_payload(
    statement: str = "Supplemental statement with the requested material.",
) -> Dict[str, Any]:
    return {"statement": statement}


def appeal_decision_payload(
    decision: str, dismissal_reason_code: Optional[str] = None
) -> Dict[str, Any]:
    return _compact({"decision": decision, "dismissal_reason_code": dismissal_reason_code})


# ── Settlement ───────────────────────────────────────────────────────

def payment_plan_payload(
    citation_id: str,
    installment_count: int,
    down_payment_cents: int,
    expected_citation_version: int,
    supersede_alternative: Optional[bool] = None,
) -> Dict[str, Any]:
    return _compact(
        {
            "citation_id": citation_id,
            "installment_count": installment_count,
            "down_payment_cents": down_payment_cents,
            "expected_citation_version": expected_citation_version,
            "supersede_alternative": supersede_alternative,
        }
    )


def installment_payload(amount_cents: int) -> Dict[str, Any]:
    return {"amount_cents": amount_cents}


def service_assignment_payload(
    citation_id: str,
    partner_org_name: str,
    expected_citation_version: int,
) -> Dict[str, Any]:
    return {
        "citation_id": citation_id,
        "partner_org_name": partner_org_name,
        "expected_citation_version": expected_citation_version,
    }


def log_hours_payload(hours: int) -> Dict[str, Any]:
    return {"hours": hours}


# ── Report query parameters ──────────────────────────────────────────

def equity_report_params(
    window_start: str,
    window_end: str,
    group_by: str = GROUP_BY_DEMOGRAPHIC_BAND,
) -> Dict[str, Any]:
    return {
        "window_start": window_start,
        "window_end": window_end,
        "group_by": group_by,
    }


def revenue_report_params(
    window_start: str,
    window_end: str,
    basis: str,
) -> Dict[str, Any]:
    return {
        "window_start": window_start,
        "window_end": window_end,
        "basis": basis,
    }
