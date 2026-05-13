"""Payload factories — one factory per input-bearing endpoint.

Each factory emits ONLY the fields PRD §3 declares as input for the
relevant endpoint. Tests override via kwargs. Field names mirror PRD
prose exactly — no abbreviation, no guessing.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Unique-name helpers
# ---------------------------------------------------------------------------
def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


def unique_operator_name(prefix: str = "Operator") -> str:
    return f"{prefix} {unique_suffix()}"


def unique_station_name(prefix: str = "Station") -> str:
    return f"{prefix} {unique_suffix()}"


def unique_pricing_label(prefix: str = "PV") -> str:
    return f"{prefix}-{unique_suffix().upper()}"


def unique_promo_name(prefix: str = "Promo") -> str:
    return f"{prefix} {unique_suffix()}"


def unique_member_name(prefix: str = "Member") -> str:
    return f"{prefix} {unique_suffix()}"


def unique_tax_id(prefix: str = "TAX") -> str:
    return f"{prefix}-{unique_suffix().upper()}"


def unique_symptom_code(prefix: str = "SYMPT") -> str:
    return f"{prefix}-{unique_suffix().upper()}"


# ---------------------------------------------------------------------------
# Operator  POST /operators  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_operator_payload(
    *,
    name: Optional[str] = None,
    role_kind: str = "PLATFORM",
    tax_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'each carrying a name (one to one hundred twenty
    characters, globally unique), a role_kind (one of PLATFORM,
    STATION_OWNER, ROAMING_PARTNER), and a tax_id (one to forty
    characters).'"""
    payload: Dict[str, Any] = {
        "name": name or unique_operator_name(),
        "role_kind": role_kind,
        "tax_id": tax_id or unique_tax_id(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Station  POST /stations  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_station_payload(
    *,
    operator_id: str,
    station_owner_id: str,
    name: Optional[str] = None,
    latitude: float = 30.000000,
    longitude: float = 120.000000,
    revenue_share_bps: int = 4000,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'A Station carries a display name ... an operator_id ...
    a station_owner_id ... a latitude and longitude, a revenue_share_bps
    between zero and ten thousand basis points.'"""
    payload: Dict[str, Any] = {
        "name": name or unique_station_name(),
        "operator_id": operator_id,
        "station_owner_id": station_owner_id,
        "latitude": latitude,
        "longitude": longitude,
        "revenue_share_bps": revenue_share_bps,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Pile  POST /stations/{id}/piles  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_pile_payload(
    *,
    model_code: str = "MODEL-X",
    rated_power_kw: float = 60.0,
    connector_type: str = "GBT_DC",
    firmware_version: str = "1.0.0",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: pile body inputs — model_code (1..64 chars), rated_power_kw
    (>0, <=360, 1 fractional digit max), connector_type (GBT_DC | GBT_AC |
    CCS2 | CHADEMO), firmware_version (MAJOR.MINOR.PATCH integers)."""
    payload: Dict[str, Any] = {
        "model_code": model_code,
        "rated_power_kw": rated_power_kw,
        "connector_type": connector_type,
        "firmware_version": firmware_version,
    }
    payload.update(overrides)
    return payload


def patch_pile_payload(
    *,
    model_code: Any = "__OMIT__",
    rated_power_kw: Any = "__OMIT__",
    firmware_version: Any = "__OMIT__",
    version: Any = "__OMIT__",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'Pile metadata (model_code, firmware_version,
    rated_power_kw) is updated by the StationOwner through the pile-edit
    capability and accepts an optional version for optimistic
    concurrency.'"""
    payload: Dict[str, Any] = {}
    if model_code != "__OMIT__":
        payload["model_code"] = model_code
    if rated_power_kw != "__OMIT__":
        payload["rated_power_kw"] = rated_power_kw
    if firmware_version != "__OMIT__":
        payload["firmware_version"] = firmware_version
    if version != "__OMIT__":
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Member  POST /members  (PRD §3.2)
# ---------------------------------------------------------------------------
def create_member_payload(
    *,
    home_operator_id: str,
    display_name: Optional[str] = None,
    tier: Any = "__OMIT__",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'A Member carries a display_name ... a home_operator_id
    ... a tier of BASIC, SILVER, GOLD, or PLATINUM defaulting to BASIC.'

    The Member's wallet_balance_cents starts at zero. Tests that need a
    positive balance must call wallet-credit after create."""
    payload: Dict[str, Any] = {
        "display_name": display_name or unique_member_name(),
        "home_operator_id": home_operator_id,
    }
    if tier != "__OMIT__":
        payload["tier"] = tier
    payload.update(overrides)
    return payload


def wallet_credit_payload(*, amount_cents: int,
                          version: Any = "__OMIT__",
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: 'Wallet credits ... increase wallet_balance_cents by a
    supplied amount_cents and accept an optional version for
    concurrency.'"""
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    if version != "__OMIT__":
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Pricing version  POST /pricing-versions  (PRD §3.2)
# ---------------------------------------------------------------------------
def create_pricing_version_payload(
    *,
    operator_id: str,
    version_label: Optional[str] = None,
    effective_from: str,
    effective_to: str,
    peak_rate_per_kwh_cents: int = 80,
    flat_rate_per_kwh_cents: int = 50,
    valley_rate_per_kwh_cents: int = 30,
    service_fee_per_kwh_cents: int = 20,
    tax_bps: int = 1300,
    peak_windows: Optional[List[Dict[str, Any]]] = None,
    valley_windows: Optional[List[Dict[str, Any]]] = None,
    tier_service_fee_discount_bps: Optional[Dict[str, int]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: pricing-version inputs — operator_id, version_label,
    effective_from (inclusive), effective_to (exclusive, strictly greater
    than effective_from), peak/flat/valley rates per kWh in cents,
    service_fee_per_kwh_cents, tax_bps in basis points,
    peak_windows/valley_windows (half-open hhmm intervals),
    tier_service_fee_discount_bps map."""
    payload: Dict[str, Any] = {
        "operator_id": operator_id,
        "version_label": version_label or unique_pricing_label(),
        "effective_from": effective_from,
        "effective_to": effective_to,
        "peak_rate_per_kwh_cents": peak_rate_per_kwh_cents,
        "flat_rate_per_kwh_cents": flat_rate_per_kwh_cents,
        "valley_rate_per_kwh_cents": valley_rate_per_kwh_cents,
        "service_fee_per_kwh_cents": service_fee_per_kwh_cents,
        "tax_bps": tax_bps,
        "peak_windows": (
            peak_windows if peak_windows is not None else []
        ),
        "valley_windows": (
            valley_windows if valley_windows is not None else []
        ),
        "tier_service_fee_discount_bps": (
            tier_service_fee_discount_bps
            if tier_service_fee_discount_bps is not None
            else {"BASIC": 0, "SILVER": 500, "GOLD": 1000, "PLATINUM": 1500}
        ),
    }
    payload.update(overrides)
    return payload


def hhmm_window(start_hhmm: str, end_hhmm: str) -> Dict[str, str]:
    """PRD §3.2: 'half-open {start_hhmm, end_hhmm} intervals within a
    calendar day'."""
    return {"start_hhmm": start_hhmm, "end_hhmm": end_hhmm}


# ---------------------------------------------------------------------------
# Promo activity  POST /promo-activities  (PRD §3.2)
# ---------------------------------------------------------------------------
def create_promo_activity_payload(
    *,
    operator_id: str,
    name: Optional[str] = None,
    starts_at: str,
    ends_at: str,
    service_fee_discount_bps: int = 500,
    applies_to_tiers: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'each promo has a name ... inclusive starts_at and
    exclusive ends_at ... a service_fee_discount_bps between zero and five
    thousand inclusive (applied on top of the member's tier discount), and
    an applies_to_tiers list — a non-empty subset of {BASIC, SILVER, GOLD,
    PLATINUM}.'"""
    payload: Dict[str, Any] = {
        "operator_id": operator_id,
        "name": name or unique_promo_name(),
        "starts_at": starts_at,
        "ends_at": ends_at,
        "service_fee_discount_bps": service_fee_discount_bps,
        "applies_to_tiers": (
            applies_to_tiers if applies_to_tiers is not None
            else ["SILVER", "GOLD", "PLATINUM"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reservation  POST /reservations  (PRD §3.3)
# ---------------------------------------------------------------------------
def create_reservation_payload(*, pile_id: str,
                               **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: 'A driver who wants a guaranteed slot creates a
    Reservation against a pile_id.'"""
    payload: Dict[str, Any] = {"pile_id": pile_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Session  POST /sessions  (PRD §3.4)
# ---------------------------------------------------------------------------
def create_session_payload(
    *,
    pile_id: str,
    member_id: str,
    auth_method: str = "APP",
    reservation_id: Any = "__OMIT__",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'A ChargingSession is created in PENDING_AUTH state by an
    EVDriver against a target pile_id, with the driver's member_id, an
    auth_method (one of APP, RFID, PLUG_AND_CHARGE), and an optional
    reservation_id linking the session to a pre-existing hold.'"""
    payload: Dict[str, Any] = {
        "pile_id": pile_id,
        "member_id": member_id,
        "auth_method": auth_method,
    }
    if reservation_id != "__OMIT__":
        payload["reservation_id"] = reservation_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Curve point  POST /sessions/{id}/curve-points  (PRD §3.4)
# ---------------------------------------------------------------------------
def create_curve_point_payload(
    *,
    sampled_at: str,
    instant_power_kw: float,
    cumulative_energy_milli: int,
    window_tag: str = "FLAT",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'each point carries session_id, sampled_at (strictly
    increasing per session), instant_power_kw (non-negative, at most two
    fractional digits), and cumulative_energy_milli (non-negative,
    monotonically non-decreasing per session).'"""
    payload: Dict[str, Any] = {
        "sampled_at": sampled_at,
        "instant_power_kw": instant_power_kw,
        "cumulative_energy_milli": cumulative_energy_milli,
        "window_tag": window_tag,
    }
    payload.update(overrides)
    return payload


def mark_abnormal_payload(*, event_type: str = "OVER_TEMPERATURE",
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: 'Abnormal events ... are appended to the session's
    abnormal_events array via the mark-abnormal capability, supplying an
    event_type (e.g., OVER_TEMPERATURE, COMMUNICATION_LOSS).'"""
    payload: Dict[str, Any] = {"event_type": event_type}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Fault report  POST /fault-reports  (PRD §3.5)
# ---------------------------------------------------------------------------
def create_fault_report_payload(
    *,
    pile_id: str,
    reporter_kind: str,
    symptom_code: Optional[str] = None,
    severity: str = "MAJOR",
    reporter_member_id: Any = "__OMIT__",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'each report captures the offending pile_id, a free-text
    symptom_code (one to forty characters), and a severity of MINOR,
    MAJOR, or CRITICAL.'"""
    payload: Dict[str, Any] = {
        "pile_id": pile_id,
        "reporter_kind": reporter_kind,
        "symptom_code": symptom_code or unique_symptom_code(),
        "severity": severity,
    }
    if reporter_member_id != "__OMIT__":
        payload["reporter_member_id"] = reporter_member_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Repair ticket  POST /fault-reports/{id}/repair-tickets  (PRD §3.5)
# ---------------------------------------------------------------------------
def create_repair_ticket_payload(
    *,
    assigned_technician_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'The repair ticket carries an assigned_technician_id
    (set by the dispatching PlatformOperator).'"""
    payload: Dict[str, Any] = {
        "assigned_technician_id": assigned_technician_id,
    }
    payload.update(overrides)
    return payload


def complete_repair_ticket_payload(*, repair_notes: str = "",
                                   version: Any = "__OMIT__",
                                   **overrides: Any) -> Dict[str, Any]:
    """PRD §3.5: 'Complete ... moves it from IN_REPAIR to
    AWAITING_ACCEPTANCE and records the supplied repair_notes.'"""
    payload: Dict[str, Any] = {"repair_notes": repair_notes}
    if version != "__OMIT__":
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Payout  POST /payouts  (PRD §3.7)
# ---------------------------------------------------------------------------
def create_payout_payload(
    *,
    operator_id: str,
    period_start: str,
    period_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: 'A PlatformOperator creates a payout draft against a
    target operator_id, an inclusive period_start, and an exclusive
    period_end strictly greater than period_start.'"""
    payload: Dict[str, Any] = {
        "operator_id": operator_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-harness payloads (PRD §2.8)
# ---------------------------------------------------------------------------
def clock_advance_payload(*, advance_ms: Any = "__OMIT__",
                          to_iso: Any = "__OMIT__",
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §2.8: 'a clock-advance capability steps the virtual clock
    forward by a supplied number of milliseconds (advance_ms) or to a
    supplied absolute instant (to_iso); it is idempotent on absolute
    time.'"""
    payload: Dict[str, Any] = {}
    if advance_ms != "__OMIT__":
        payload["advance_ms"] = advance_ms
    if to_iso != "__OMIT__":
        payload["to_iso"] = to_iso
    payload.update(overrides)
    return payload


def emit_event_payload(*, source_system: str, event_type: str,
                       payload: Optional[Dict[str, Any]] = None,
                       **overrides: Any) -> Dict[str, Any]:
    """PRD §2.8: 'an event-emission capability injects an
    ExternalEventInbox row with caller-supplied source_system, event_type,
    and payload.'"""
    body: Dict[str, Any] = {
        "source_system": source_system,
        "event_type": event_type,
        "payload": payload if payload is not None else {},
    }
    body.update(overrides)
    return body


__all__ = [
    "unique_suffix",
    "unique_operator_name", "unique_station_name",
    "unique_pricing_label", "unique_promo_name",
    "unique_member_name", "unique_tax_id", "unique_symptom_code",
    "create_operator_payload",
    "create_station_payload",
    "create_pile_payload", "patch_pile_payload",
    "create_member_payload", "wallet_credit_payload",
    "create_pricing_version_payload", "hhmm_window",
    "create_promo_activity_payload",
    "create_reservation_payload",
    "create_session_payload",
    "create_curve_point_payload", "mark_abnormal_payload",
    "create_fault_report_payload",
    "create_repair_ticket_payload", "complete_repair_ticket_payload",
    "create_payout_payload",
    "clock_advance_payload", "emit_event_payload",
]
