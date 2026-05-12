"""Payload factories — one per input-bearing endpoint.

Each factory emits ONLY the fields PRD §3 declares as input (source: input)
for the corresponding endpoint. Tests override via kwargs.

Field names mirror PRD prose exactly — no abbreviation, no guessing.

A sentinel '__OMIT__' lets callers explicitly drop an optional field from
the payload, distinct from passing None (which sends a literal null).
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# Sentinel: keep optional fields out of the payload entirely.
_OMIT = "__OMIT__"


def unique_suffix() -> str:
    return uuid.uuid4().hex[:8]


def random_external_user_id(prefix: str = "ext") -> str:
    return f"{prefix}_{unique_suffix()}"


def random_payment_ref(prefix: str = "pay") -> str:
    return f"{prefix}_{unique_suffix()}"


def random_cert_id(kind: str = "calib") -> str:
    return f"cert-{kind}-{unique_suffix()}"


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop fields whose value is the explicit _OMIT sentinel."""
    return {k: v for k, v in payload.items() if v != _OMIT}


# ---------------------------------------------------------------------------
# Lab  POST /labs  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_lab_payload(
    *,
    name: Optional[str] = None,
    institution: str = "school-alpha",
    department: str = "dept-alpha",
    contact_user_id: Optional[str] = None,
    revenue_share_bps: int = 8000,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'A PlatformAdmin registers a Lab by supplying a display
    name, an institution code, a department code, the contact_user_id
    of the User who will administer the lab, and a revenue_share_bps
    figure between 0 and 10000 inclusive'."""
    payload: Dict[str, Any] = {
        "name": name or f"Lab {unique_suffix()}",
        "institution": institution,
        "department": department,
        "contact_user_id": contact_user_id or f"user-{unique_suffix()}",
        "revenue_share_bps": revenue_share_bps,
    }
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# User  POST /users  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_user_payload(
    *,
    external_user_id: Optional[str] = None,
    full_name: Optional[str] = None,
    department: str = "dept-default",
    affiliation: str = "WITHIN_SCHOOL",
    training_certificates: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'The create payload carries an external_user_id, a
    full_name, the user's department code, an affiliation chosen from
    WITHIN_SCHOOL, INTER_SCHOOL, or EXTERNAL, and a training_certificates
    array'."""
    payload: Dict[str, Any] = {
        "external_user_id": external_user_id or random_external_user_id(),
        "full_name": full_name or f"Test User {unique_suffix()}",
        "department": department,
        "affiliation": affiliation,
        "training_certificates": (
            training_certificates if training_certificates is not None
            else ["T1"]
        ),
    }
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Equipment  POST /equipment  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_equipment_payload(
    *,
    lab_id: str,
    model: Optional[str] = None,
    specification: str = "spec-default",
    value_tier: str = "STANDARD",
    sharing_scope: str = "WITHIN_SCHOOL",
    slot_granularity: str = "HOUR",
    lead_time_hours: int = 0,
    single_user_duration_limit_hours: int = 8,
    peak_window_start_hour: int = 22,
    peak_window_end_hour: int = 23,
    calibration_cert_id: Optional[str] = None,
    calibration_expires_at: str = "2099-01-01T00:00:00.000Z",
    safety_inspection_cert_id: Optional[str] = None,
    safety_inspection_expires_at: str = "2099-01-01T00:00:00.000Z",
    photo_uri: str = "https://example.com/photo.jpg",
    operation_manual_uri: str = "https://example.com/manual.pdf",
    required_training_codes: Optional[List[str]] = None,
    allowed_sample_types: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'The payload supplies lab_id, the instrument's model and
    free-form specification, a value_tier ..., a sharing_scope ..., the
    slot_granularity ..., a lead_time_hours integer no less than 0, a
    single_user_duration_limit_hours cap, the peak window bounds
    peak_window_start_hour and peak_window_end_hour, the two certificate
    identifiers and expiry timestamps ..., asset pointers photo_uri and
    operation_manual_uri, ... required_training_codes ... and
    allowed_sample_types'."""
    payload: Dict[str, Any] = {
        "lab_id": lab_id,
        "model": model or f"model-{unique_suffix()}",
        "specification": specification,
        "value_tier": value_tier,
        "sharing_scope": sharing_scope,
        "slot_granularity": slot_granularity,
        "lead_time_hours": lead_time_hours,
        "single_user_duration_limit_hours": single_user_duration_limit_hours,
        "peak_window_start_hour": peak_window_start_hour,
        "peak_window_end_hour": peak_window_end_hour,
        "calibration_cert_id": (
            calibration_cert_id or random_cert_id("calib")
        ),
        "calibration_expires_at": calibration_expires_at,
        "safety_inspection_cert_id": (
            safety_inspection_cert_id or random_cert_id("safety")
        ),
        "safety_inspection_expires_at": safety_inspection_expires_at,
        "photo_uri": photo_uri,
        "operation_manual_uri": operation_manual_uri,
        "required_training_codes": (
            required_training_codes if required_training_codes is not None
            else ["T1"]
        ),
        "allowed_sample_types": (
            allowed_sample_types if allowed_sample_types is not None
            else ["S"]
        ),
    }
    payload.update(overrides)
    return _prune(payload)


def update_equipment_payload(
    *,
    status: Any = _OMIT,
    single_user_duration_limit_hours: Any = _OMIT,
    peak_window_start_hour: Any = _OMIT,
    peak_window_end_hour: Any = _OMIT,
    version: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'profile-edit operation that accepts a version field for
    optimistic concurrency' — caller controls which optional fields land
    in the body."""
    payload: Dict[str, Any] = {
        "status": status,
        "single_user_duration_limit_hours": single_user_duration_limit_hours,
        "peak_window_start_hour": peak_window_start_hour,
        "peak_window_end_hour": peak_window_end_hour,
        "version": version,
    }
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# BillingRule  POST /equipment/{id}/billing-rules  (PRD §3.5)
# ---------------------------------------------------------------------------
def create_billing_rule_payload(
    *,
    mode: str = "BY_TIME",
    internal_rate_per_hour_cents: int = 10000,
    external_rate_per_hour_cents: int = 20000,
    inter_school_rate_per_hour_cents: int = 15000,
    internal_rate_per_sample_cents: int = 500,
    external_rate_per_sample_cents: int = 800,
    inter_school_rate_per_sample_cents: int = 600,
    peak_multiplier_bps: int = 12500,
    consumables_flat_cents: int = 500,
    platform_fee_bps: int = 1000,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'A LabOwner drafts a rule by supplying its mode (...),
    three time-based rates ..., three sample-based rates ..., the
    peak_multiplier_bps applied to the time portion when peak overlap is
    non-zero ..., a consumables_flat_cents per-checkout flat fee ..., and
    a platform_fee_bps representing the platform service fee in basis
    points charged on the equipment-fee subtotal'."""
    payload: Dict[str, Any] = {
        "mode": mode,
        "internal_rate_per_hour_cents": internal_rate_per_hour_cents,
        "external_rate_per_hour_cents": external_rate_per_hour_cents,
        "inter_school_rate_per_hour_cents": inter_school_rate_per_hour_cents,
        "internal_rate_per_sample_cents": internal_rate_per_sample_cents,
        "external_rate_per_sample_cents": external_rate_per_sample_cents,
        "inter_school_rate_per_sample_cents":
            inter_school_rate_per_sample_cents,
        "peak_multiplier_bps": peak_multiplier_bps,
        "consumables_flat_cents": consumables_flat_cents,
        "platform_fee_bps": platform_fee_bps,
    }
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# MaintenanceWindow  POST /equipment/{id}/maintenance-windows  (PRD §3.7)
# ---------------------------------------------------------------------------
def create_maintenance_window_payload(
    *,
    kind: str = "PERIODIC",
    start_at: str,
    end_at: str,
    maintenance_notes: str = "scheduled service",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: 'The payload supplies start_at, end_at, and free-form
    maintenance_notes'; kind is PERIODIC or AD_HOC."""
    payload: Dict[str, Any] = {
        "kind": kind,
        "start_at": start_at,
        "end_at": end_at,
        "maintenance_notes": maintenance_notes,
    }
    payload.update(overrides)
    return _prune(payload)


def accept_maintenance_window_payload(
    *,
    acceptance_notes: str = "ok",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: 'attaches the optional acceptance_notes text'."""
    payload: Dict[str, Any] = {"acceptance_notes": acceptance_notes}
    payload.update(overrides)
    return _prune(payload)


def reject_maintenance_window_payload(
    *,
    acceptance_notes: str = "rework required",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: 'records the supplied acceptance_notes describing why
    acceptance was withheld'."""
    payload: Dict[str, Any] = {"acceptance_notes": acceptance_notes}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Authorization  POST /equipment/{id}/authorizations  (PRD §3.2)
# ---------------------------------------------------------------------------
def create_authorization_payload(
    *,
    user_id: str,
    sample_type: str = "S",
    urgency: str = "NORMAL",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'The end user opens the request directly against the
    target instrument by supplying their own user_id (which must equal
    X-User-ID), the sample_type they intend to run, and an urgency of
    either NORMAL or URGENT'."""
    payload: Dict[str, Any] = {
        "user_id": user_id,
        "sample_type": sample_type,
        "urgency": urgency,
    }
    payload.update(overrides)
    return _prune(payload)


def reject_authorization_payload(
    *,
    rejection_reason: Any = "not approved",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'the request optionally carries a rejection_reason string'.
    """
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Reservation  POST /equipment/{id}/reservations  (PRD §3.3)
# ---------------------------------------------------------------------------
def create_reservation_payload(
    *,
    user_id: str,
    authorization_id: str,
    start_at: str,
    end_at: str,
    requested_sample_count: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'The request supplies user_id (matching X-User-ID), the
    authorization_id of the approved authorization, the window start_at
    and end_at, and a requested_sample_count'."""
    payload: Dict[str, Any] = {
        "user_id": user_id,
        "authorization_id": authorization_id,
        "start_at": start_at,
        "end_at": end_at,
        "requested_sample_count": requested_sample_count,
    }
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Check-out  POST /reservations/{id}/check-out  (PRD §3.6)
# ---------------------------------------------------------------------------
def check_out_payload(
    *,
    actual_sample_count: int = 0,
    status_handover: str = "NORMAL",
    abnormal_event_code: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.6: 'The check-out payload supplies actual_sample_count, a
    status_handover of either NORMAL or ABNORMAL, and an optional
    abnormal_event_code describing the incident; whenever an
    abnormal_event_code is supplied the system requires status_handover
    to be ABNORMAL'."""
    payload: Dict[str, Any] = {
        "actual_sample_count": actual_sample_count,
        "status_handover": status_handover,
        "abnormal_event_code": abnormal_event_code,
    }
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Test-harness clock + event hooks (PRD §3.8)
# ---------------------------------------------------------------------------
def clock_payload(target_time: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: '/_clock/advance ... accepts a target_time ISO timestamp'.
    """
    payload: Dict[str, Any] = {"target_time": target_time}
    payload.update(overrides)
    return payload


def payment_confirmed_payload(
    *,
    reservation_id: str,
    external_payment_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: 'idempotent on the combination of reservation_id and
    external_payment_id'."""
    payload: Dict[str, Any] = {
        "reservation_id": reservation_id,
        "external_payment_id": (
            external_payment_id or random_payment_ref()
        ),
    }
    payload.update(overrides)
    return payload


def identity_verified_payload(
    *,
    external_user_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1/§3.8: 'idempotent on external_user_id'."""
    payload: Dict[str, Any] = {"external_user_id": external_user_id}
    payload.update(overrides)
    return payload


def im_notified_payload(
    *,
    audit_event_id: str,
    im_delivery_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: 'IM-delivery acknowledgement ... an audit_event_id
    referencing a previously written audit row and an im_delivery_id'."""
    payload: Dict[str, Any] = {
        "audit_event_id": audit_event_id,
        "im_delivery_id": im_delivery_id or f"im-{unique_suffix()}",
    }
    payload.update(overrides)
    return payload


__all__ = [
    "unique_suffix", "random_external_user_id", "random_payment_ref",
    "random_cert_id",
    "create_lab_payload",
    "create_user_payload",
    "create_equipment_payload", "update_equipment_payload",
    "create_billing_rule_payload",
    "create_maintenance_window_payload",
    "accept_maintenance_window_payload",
    "reject_maintenance_window_payload",
    "create_authorization_payload",
    "reject_authorization_payload",
    "create_reservation_payload",
    "check_out_payload",
    "clock_payload",
    "payment_confirmed_payload",
    "identity_verified_payload",
    "im_notified_payload",
]
