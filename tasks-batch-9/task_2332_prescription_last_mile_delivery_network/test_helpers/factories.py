"""Request-payload builders.

Each builder returns only the client-supplied fields of one write endpoint;
derived values such as ``masked_name``, ``handling_class``, ``reserved_slots``
or any money line are never sent. Every builder accepts keyword overrides so a
test can vary exactly one input and leave the rest at a valid baseline.
"""

from typing import Any, Dict, List, Optional

from .constants import ZONE_Z1, utc_ts

Payload = Dict[str, Any]


def _merged(base: Payload, overrides: Payload) -> Payload:
    """Apply overrides; an ``OMIT`` value drops the field from the body entirely.

    ``OMIT`` works both as a named argument (it lands in ``base``) and as a
    keyword override, so ``courier_payload(cold_chain_equipped=OMIT)`` and
    ``courier_payload(**{"cold_chain_equipped": OMIT})`` behave identically.
    """
    merged = dict(base)
    for key, value in overrides.items():
        merged[key] = value
    return {k: v for k, v in merged.items() if v is not _OMIT}


class _Omit:
    """Sentinel meaning 'leave this optional field out of the body entirely'."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<omit>"


_OMIT = _Omit()
OMIT = _OMIT


# ─── Reference data ───────────────────────────────────


def health_plan_payload(
    name: str = "Meridian Health",
    payer_type: str = "COMMERCIAL",
    member_cost_share_pct: float = 0.10,
    **overrides: Any,
) -> Payload:
    return _merged(
        {
            "name": name,
            "payer_type": payer_type,
            "member_cost_share_pct": member_cost_share_pct,
        },
        overrides,
    )


def plan_grant_payload(
    health_plan_id: str,
    benefit_year: int = 2026,
    grant_budget_cents: int = 100_000,
    per_delivery_cap_cents: int = 150,
    **overrides: Any,
) -> Payload:
    return _merged(
        {
            "health_plan_id": health_plan_id,
            "benefit_year": benefit_year,
            "grant_budget_cents": grant_budget_cents,
            "per_delivery_cap_cents": per_delivery_cap_cents,
        },
        overrides,
    )


def pharmacy_payload(
    name: str = "Cedar Rx",
    state_code: str = "WA",
    cold_chain_certified: bool = True,
    controlled_license_tier: str = "CII_V",
    return_window_minutes: int = 240,
    **overrides: Any,
) -> Payload:
    return _merged(
        {
            "name": name,
            "state_code": state_code,
            "cold_chain_certified": cold_chain_certified,
            "controlled_license_tier": controlled_license_tier,
            "return_window_minutes": return_window_minutes,
        },
        overrides,
    )


def delivery_zone_payload(**overrides: Any) -> Payload:
    """A zone carrying the standard Z1 fee schedule unless overridden."""
    return _merged(dict(ZONE_Z1), overrides)


def patient_payload(
    full_name: str = "Dana Reyes",
    date_of_birth: str = "1970-04-12",
    phone_last4: str = "4417",
    address_line: str = "881 Alder St",
    zone_code: str = "Z1",
    hipaa_consent_status: str = "GRANTED",
    **overrides: Any,
) -> Payload:
    return _merged(
        {
            "full_name": full_name,
            "date_of_birth": date_of_birth,
            "phone_last4": phone_last4,
            "address_line": address_line,
            "zone_code": zone_code,
            "hipaa_consent_status": hipaa_consent_status,
        },
        overrides,
    )


def consent_payload(hipaa_consent_status: str = "REVOKED", **overrides: Any) -> Payload:
    return _merged({"hipaa_consent_status": hipaa_consent_status}, overrides)


def courier_payload(
    display_name: str = "Ray Ortiz",
    mode: str = "SCHEDULED",
    served_zone_codes: Optional[List[str]] = None,
    cold_chain_equipped: bool = True,
    controlled_certified: bool = True,
    **overrides: Any,
) -> Payload:
    return _merged(
        {
            "display_name": display_name,
            "mode": mode,
            "served_zone_codes": list(served_zone_codes) if served_zone_codes else ["Z1"],
            "cold_chain_equipped": cold_chain_equipped,
            "controlled_certified": controlled_certified,
        },
        overrides,
    )


def courier_status_payload(target_status: str, **overrides: Any) -> Payload:
    return _merged({"target_status": target_status}, overrides)


def delivery_window_payload(
    zone_id: str,
    courier_mode: str = "SCHEDULED",
    window_start: str = utc_ts(3, 14),
    window_end: str = utc_ts(3, 16),
    capacity_slots: int = 1,
    **overrides: Any,
) -> Payload:
    return _merged(
        {
            "zone_id": zone_id,
            "courier_mode": courier_mode,
            "window_start": window_start,
            "window_end": window_end,
            "capacity_slots": capacity_slots,
        },
        overrides,
    )


# ─── Orders and deliveries ────────────────────────────


def pharmacy_order_payload(
    pharmacy_id: str,
    patient_id: str,
    health_plan_id: Optional[str] = None,
    rx_line_count: int = 2,
    cold_chain_required: bool = False,
    controlled_schedule: str = "NONE",
    total_rx_value_cents: int = 1000,
    **overrides: Any,
) -> Payload:
    return _merged(
        {
            "pharmacy_id": pharmacy_id,
            "patient_id": patient_id,
            "health_plan_id": health_plan_id,
            "rx_line_count": rx_line_count,
            "cold_chain_required": cold_chain_required,
            "controlled_schedule": controlled_schedule,
            "total_rx_value_cents": total_rx_value_cents,
        },
        overrides,
    )


def delivery_payload(
    order_id: str,
    window_id: str,
    expected_window_version: int,
    **overrides: Any,
) -> Payload:
    return _merged(
        {
            "order_id": order_id,
            "window_id": window_id,
            "expected_window_version": expected_window_version,
        },
        overrides,
    )


def reschedule_payload(window_id: str, **overrides: Any) -> Payload:
    return _merged({"window_id": window_id}, overrides)


def dispatch_payload(courier_id: Optional[str] = None, **overrides: Any) -> Payload:
    """An explicit ``courier_id`` is the operator override; omitting it invokes the selector."""
    body: Payload = {} if courier_id is None else {"courier_id": courier_id}
    return _merged(body, overrides)


def pickup_payload(cold_chain_seal_id: Optional[str] = "SEAL-4471", **overrides: Any) -> Payload:
    body: Payload = {} if cold_chain_seal_id is None else {"cold_chain_seal_id": cold_chain_seal_id}
    return _merged(body, overrides)


def attempt_payload(
    requested_outcome: str,
    id_verification_method: Optional[str] = None,
    signature_captured: Optional[bool] = None,
    recipient_relationship: Optional[str] = None,
    pod_photo_ref: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    body: Payload = {"requested_outcome": requested_outcome}
    if id_verification_method is not None:
        body["id_verification_method"] = id_verification_method
    if signature_captured is not None:
        body["signature_captured"] = signature_captured
    if recipient_relationship is not None:
        body["recipient_relationship"] = recipient_relationship
    if pod_photo_ref is not None:
        body["pod_photo_ref"] = pod_photo_ref
    return _merged(body, overrides)


def delivered_attempt_payload(
    id_verification_method: str = "GOVT_ID_SCAN",
    signature_captured: bool = True,
    recipient_relationship: str = "SELF",
    **overrides: Any,
) -> Payload:
    """A door-step run that clears both proof gates for any handling class."""
    return _merged(
        {
            "requested_outcome": "DELIVERED",
            "id_verification_method": id_verification_method,
            "signature_captured": signature_captured,
            "recipient_relationship": recipient_relationship,
        },
        overrides,
    )


# ─── Exception cases ──────────────────────────────────


def exception_case_payload(
    delivery_id: str,
    exception_type: str = "ATTEMPTS_EXHAUSTED",
    notes: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    body: Payload = {"delivery_id": delivery_id, "exception_type": exception_type}
    if notes is not None:
        body["notes"] = notes
    return _merged(body, overrides)


def adjudication_payload(
    disposition: str,
    expected_delivery_version: int,
    reship_window_id: Optional[str] = None,
    notes: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    body: Payload = {
        "disposition": disposition,
        "expected_delivery_version": expected_delivery_version,
    }
    if reship_window_id is not None:
        body["reship_window_id"] = reship_window_id
    if notes is not None:
        body["notes"] = notes
    return _merged(body, overrides)


# ─── Clock ────────────────────────────────────────────


def clock_payload(current_utc: str, **overrides: Any) -> Payload:
    return _merged({"current_utc": current_utc}, overrides)
