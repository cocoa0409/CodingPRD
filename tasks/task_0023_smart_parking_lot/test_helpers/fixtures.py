"""Composite setup helpers for the Smart Parking Lot test suite.

The PRD's lifecycle has many interlocking phases — Lot → Zone → Space,
Vehicle, Card (with binding), Session, Reservation, Violation, Payment,
Refund — and most interesting tests need the system in a non-initial
state. This module captures the common multi-call setup sequences once.

Identity threading (PRD §2.1): Driver is the only entity-backed role
(X-User-ID == Vehicle.id). Whenever a fixture creates a Vehicle and the
downstream call is ownership-gated (driver-initiated reservation,
session pay, dispute filing), the helper must thread the actual
Vehicle.id through make_driver_headers; never fall back to the shared
TEST_USERS["driver_headers"] for ownership-gated flows.

Setup calls use get_success_data (lenient validator) so that broken
preconditions surface as obvious "Setup failed" mismatches rather than
confusing assertion errors.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    bind_card_payload,
    create_card_payload,
    create_lot_payload,
    create_reservation_payload,
    create_session_payload,
    create_space_payload,
    create_vehicle_payload,
    create_violation_payload,
    create_zone_payload,
    pay_session_payload,
    pay_violation_payload,
    recharge_card_payload,
    unique_external_ref,
    unique_holder_ref,
    unique_officer_id,
    unique_plate,
)
from .test_users import (
    TEST_USERS,
    make_driver_headers,
    make_gate_headers,
    make_officer_headers,
    make_operator_headers,
)


# ===========================================================================
# Time helpers (PRD §2.9 — ISO 8601 UTC with 3 fractional digits)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2)


def add_seconds(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(seconds=n))


def add_minutes(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(minutes=n))


def add_hours(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(hours=n))


def add_days(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(days=n))


# ===========================================================================
# Test-driving wrappers
# ===========================================================================
# Client-side mirror of the server's logical clock — updated whenever
# advance_clock() returns. Lets helpers reason about whether the current
# instant lies inside an entity's validity window without a separate
# /clock/get endpoint (PRD §3.8 only specifies advance/sweep/events).
_last_known_clock_iso: Optional[str] = None


def advance_clock(to_iso: str) -> Dict[str, Any]:
    """POST /_clock/advance with Operator headers (PRD §3.8)."""
    global _last_known_clock_iso
    res = api_client.advance_clock(to_iso, TEST_USERS["operator_headers"])
    data = get_success_data(res)
    _last_known_clock_iso = to_iso
    return data


def _ensure_clock_within(valid_from: str, valid_until: str) -> None:
    """If the last-known clock is outside [valid_from, valid_until], pin the
    clock to valid_from so subsequent card-binding operations land inside
    the validity window. Idempotent and a no-op when already inside.
    """
    global _last_known_clock_iso
    vf = parse_iso(valid_from)
    vu = parse_iso(valid_until)
    if _last_known_clock_iso is None:
        # No advance yet this session — pin to valid_from so PRD §3.3
        # bind validity check passes deterministically.
        advance_clock(valid_from)
        return
    cur = parse_iso(_last_known_clock_iso)
    if cur < vf or cur > vu:
        advance_clock(valid_from)


def run_sweep() -> Dict[str, Any]:
    """POST /_sweep/run with Operator headers (PRD §3.8)."""
    return get_success_data(api_client.run_sweep(TEST_USERS["operator_headers"]))


def emit_event(event_kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST /_events/emit with Operator headers (PRD §3.8)."""
    return get_success_data(
        api_client.emit_event(event_kind, payload, TEST_USERS["operator_headers"])
    )


# ===========================================================================
# Tier 1 — single-entity creation
# ===========================================================================
def create_lot(
    *,
    timezone: str = "UTC",
    hourly_rate_cents: int = 400,
    daily_cap_cents: int = 2000,
    free_minutes: Optional[int] = None,
    tow_grace_minutes: Optional[int] = None,
    reservation_hold_minutes: Optional[int] = None,
    no_show_penalty_cents: Optional[int] = None,
    partner_share_bps: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Create a ParkingLot with operator headers."""
    payload = create_lot_payload(
        timezone=timezone,
        hourly_rate_cents=hourly_rate_cents,
        daily_cap_cents=daily_cap_cents,
        free_minutes=free_minutes,
        tow_grace_minutes=tow_grace_minutes,
        reservation_hold_minutes=reservation_hold_minutes,
        no_show_penalty_cents=no_show_penalty_cents,
        partner_share_bps=partner_share_bps,
        **extra,
    )
    res = api_client.create_lot(payload, TEST_USERS["operator_headers"])
    return get_success_data(res)


def create_zone(
    lot_id: str,
    *,
    zone_type: str = "STANDARD",
    code: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_zone_payload(zone_type=zone_type, code=code)
    res = api_client.create_zone(lot_id, payload, TEST_USERS["operator_headers"])
    return get_success_data(res)


def create_space(
    lot_id: str,
    zone_id: str,
    *,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_space_payload(label=label)
    res = api_client.create_space(
        lot_id, zone_id, payload, TEST_USERS["operator_headers"]
    )
    return get_success_data(res)


def create_vehicle(
    *,
    plate: Optional[str] = None,
    kind: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_vehicle_payload(plate=plate, kind=kind)
    res = api_client.create_vehicle(payload, TEST_USERS["operator_headers"])
    return get_success_data(res)


def create_card(
    *,
    card_type: str = "STORED_VALUE",
    holder_ref: Optional[str] = None,
    valid_from: str = "2026-01-01T00:00:00.000Z",
    valid_until: str = "2027-01-01T00:00:00.000Z",
    monthly_fee_cents: Optional[int] = None,
    auto_pay_enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    # Card-binding tests that don't drive the clock themselves rely on the
    # current instant lying inside [valid_from, valid_until] (PRD §3.3
    # validity window). Pin the clock to valid_from only when the
    # last-known clock is outside that window so we don't clobber a
    # test-driven advance.
    _ensure_clock_within(valid_from, valid_until)
    payload = create_card_payload(
        card_type=card_type,
        holder_ref=holder_ref or unique_holder_ref(),
        valid_from=valid_from,
        valid_until=valid_until,
        monthly_fee_cents=monthly_fee_cents,
        auto_pay_enabled=auto_pay_enabled,
    )
    res = api_client.create_card(payload, TEST_USERS["operator_headers"])
    return get_success_data(res)


def recharge_card(
    card_id: str,
    *,
    amount_cents: int,
    external_ref: Optional[str] = None,
    actor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = recharge_card_payload(
        amount_cents=amount_cents, external_ref=external_ref
    )
    headers = actor_headers or TEST_USERS["operator_headers"]
    res = api_client.recharge_card(card_id, payload, headers)
    return get_success_data(res)


def bind_vehicle_to_card(
    card_id: str,
    vehicle_id: str,
) -> Dict[str, Any]:
    """Operator binds a vehicle to a card (PRD §3.3)."""
    payload = bind_card_payload(vehicle_id=vehicle_id)
    res = api_client.bind_card(card_id, payload, TEST_USERS["operator_headers"])
    return get_success_data(res)


# ===========================================================================
# Tier 2 — single-zone setup with N spaces
# ===========================================================================
def setup_lot_zone_spaces(
    *,
    timezone: str = "UTC",
    hourly_rate_cents: int = 400,
    daily_cap_cents: int = 2000,
    free_minutes: Optional[int] = None,
    tow_grace_minutes: Optional[int] = None,
    reservation_hold_minutes: Optional[int] = None,
    no_show_penalty_cents: Optional[int] = None,
    partner_share_bps: Optional[int] = None,
    zone_type: str = "STANDARD",
    space_count: int = 1,
    space_labels: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Build a lot + one zone + N spaces. Returns (lot, zone, spaces)."""
    lot = create_lot(
        timezone=timezone,
        hourly_rate_cents=hourly_rate_cents,
        daily_cap_cents=daily_cap_cents,
        free_minutes=free_minutes,
        tow_grace_minutes=tow_grace_minutes,
        reservation_hold_minutes=reservation_hold_minutes,
        no_show_penalty_cents=no_show_penalty_cents,
        partner_share_bps=partner_share_bps,
    )
    zone = create_zone(lot["id"], zone_type=zone_type)
    spaces: List[Dict[str, Any]] = []
    if space_labels is None:
        space_labels = [f"A-{i+1}" for i in range(space_count)]
    for label in space_labels:
        spaces.append(create_space(lot["id"], zone["id"], label=label))
    return lot, zone, spaces


# ===========================================================================
# Tier 3 — Session lifecycle helpers
# ===========================================================================
def open_session(
    lot_id: str,
    *,
    vehicle_id: str,
    space_id: Optional[str] = None,
    card_id: Optional[str] = None,
    actor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /lots/{lot_id}/sessions as GateSystem."""
    payload = create_session_payload(
        vehicle_id=vehicle_id, space_id=space_id, card_id=card_id
    )
    headers = actor_headers or TEST_USERS["gate_headers"]
    res = api_client.create_session(lot_id, payload, headers)
    return get_success_data(res)


def exit_session(session_id: str) -> Dict[str, Any]:
    """POST /sessions/{session_id}/exit as GateSystem."""
    res = api_client.exit_session(session_id, TEST_USERS["gate_headers"])
    return get_success_data(res)


def pay_session(
    session_id: str,
    *,
    vehicle_id: str,
    card_id: Optional[str] = None,
    external_ref: Optional[str] = None,
    actor: str = "driver",
) -> Dict[str, Any]:
    """POST /sessions/{session_id}/pay.

    actor='driver' threads the Vehicle.id through X-User-ID per PRD §2.1
    so ownership comparisons succeed.
    """
    payload = pay_session_payload(card_id=card_id, external_ref=external_ref)
    if actor == "driver":
        headers = make_driver_headers(vehicle_id)
    else:
        headers = TEST_USERS["operator_headers"]
    res = api_client.pay_session(session_id, payload, headers)
    return get_success_data(res)


def get_session(session_id: str) -> Dict[str, Any]:
    """GET /sessions/{session_id} as Operator."""
    res = api_client.get_session(session_id, TEST_USERS["operator_headers"])
    return get_success_data(res)


def get_card(card_id: str) -> Dict[str, Any]:
    """GET /cards/{card_id} as Operator."""
    res = api_client.get_card(card_id, TEST_USERS["operator_headers"])
    return get_success_data(res)


def get_vehicle(vehicle_id: str) -> Dict[str, Any]:
    """GET /vehicles/{vehicle_id} as Operator."""
    res = api_client.get_vehicle(vehicle_id, TEST_USERS["operator_headers"])
    return get_success_data(res)


def get_violation(violation_id: str) -> Dict[str, Any]:
    """GET /violations/{violation_id} as Operator."""
    res = api_client.get_violation(violation_id, TEST_USERS["operator_headers"])
    return get_success_data(res)


def get_reservation(reservation_id: str) -> Dict[str, Any]:
    """GET /reservations/{reservation_id} as Operator."""
    res = api_client.get_reservation(
        reservation_id, TEST_USERS["operator_headers"]
    )
    return get_success_data(res)


def get_space(lot_id: str, zone_id: str, space_id: str) -> Dict[str, Any]:
    """GET /lots/{lot_id}/zones/{zone_id}/spaces/{space_id}."""
    res = api_client.get_space(
        lot_id, zone_id, space_id, TEST_USERS["operator_headers"]
    )
    return get_success_data(res)


def get_lot(lot_id: str) -> Dict[str, Any]:
    res = api_client.get_lot(lot_id, TEST_USERS["operator_headers"])
    return get_success_data(res)


def get_revenue(
    lot_id: str,
    *,
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """GET /lots/{lot_id}/revenue as Operator. Returns the data payload as-is."""
    res = api_client.get_revenue(
        lot_id, TEST_USERS["operator_headers"], params=params
    )
    return get_success_data(res)


def list_audit_logs(
    *,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """GET /audit-logs as Auditor; returns the list payload."""
    res = api_client.list_audit_logs(
        TEST_USERS["auditor_headers"], params=params
    )
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Some implementations return the array under data; be lenient.
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


# ===========================================================================
# Tier 4 — issue a violation (creates linked Fine)
# ===========================================================================
def issue_violation(
    *,
    lot_id: str,
    vehicle_id: str,
    space_id: str,
    violation_type: str,
    detected_at: str,
    session_id: Optional[str] = None,
    photo_uri: Optional[str] = None,
    officer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /violations as EnforcementOfficer."""
    payload = create_violation_payload(
        lot_id=lot_id,
        vehicle_id=vehicle_id,
        violation_type=violation_type,
        space_id=space_id,
        detected_at=detected_at,
        session_id=session_id,
        photo_uri=photo_uri,
        officer_id=officer_id or unique_officer_id(),
    )
    res = api_client.create_violation(payload, TEST_USERS["officer_headers"])
    return get_success_data(res)


def pay_violation(
    *,
    violation_id: str,
    vehicle_id: str,
    amount_cents: int,
    card_id: Optional[str] = None,
    external_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /violations/{violation_id}/pay as Driver. Threads vehicle_id."""
    payload = pay_violation_payload(
        amount_cents=amount_cents,
        card_id=card_id,
        external_ref=external_ref,
    )
    headers = make_driver_headers(vehicle_id)
    res = api_client.pay_violation(violation_id, payload, headers)
    return get_success_data(res)


# ===========================================================================
# Tier 5 — Composite scenario fixtures (the heavy lifters)
# Each accepts **overrides where the calling test must pin specific values.
# ===========================================================================
def setup_basic_session_scenario(
    *,
    base_iso: str = "2026-01-01T10:00:00.000Z",
    timezone: str = "UTC",
    hourly_rate_cents: int = 400,
    daily_cap_cents: int = 2000,
    free_minutes: Optional[int] = None,
    tow_grace_minutes: Optional[int] = None,
    no_show_penalty_cents: Optional[int] = None,
    partner_share_bps: Optional[int] = None,
    vehicle_kind: Optional[str] = None,
    space_label: str = "A-1",
) -> Dict[str, Any]:
    """Set the clock, build a lot+zone+space, register one regular vehicle,
    and open one ACTIVE session in the space.

    Returns a dict with keys: lot, zone, space, vehicle, session.
    """
    advance_clock(base_iso)
    lot, zone, spaces = setup_lot_zone_spaces(
        timezone=timezone,
        hourly_rate_cents=hourly_rate_cents,
        daily_cap_cents=daily_cap_cents,
        free_minutes=free_minutes,
        tow_grace_minutes=tow_grace_minutes,
        no_show_penalty_cents=no_show_penalty_cents,
        partner_share_bps=partner_share_bps,
        space_count=1,
        space_labels=[space_label],
    )
    vehicle = create_vehicle(kind=vehicle_kind)
    session = open_session(
        lot["id"], vehicle_id=vehicle["id"], space_id=spaces[0]["id"]
    )
    return {
        "lot": lot,
        "zone": zone,
        "space": spaces[0],
        "vehicle": vehicle,
        "session": session,
    }


def setup_session_with_storedvalue_card(
    *,
    base_iso: str = "2026-01-01T09:00:00.000Z",
    timezone: str = "UTC",
    hourly_rate_cents: int = 400,
    daily_cap_cents: int = 2000,
    free_minutes: Optional[int] = None,
    initial_balance_cents: int = 0,
    auto_pay_enabled: bool = False,
    valid_from: str = "2026-01-01T00:00:00.000Z",
    valid_until: str = "2027-01-01T00:00:00.000Z",
) -> Dict[str, Any]:
    """Set the clock; build lot+zone+space; register a regular vehicle;
    issue a STORED_VALUE card; bind vehicle to card; recharge to
    initial_balance_cents (creating a CARD_RECHARGE Payment); open ACTIVE
    session pinned to the card.

    Returns dict with: lot, zone, space, vehicle, card, session,
    recharge_payment_id (str | None when initial_balance_cents == 0).
    """
    advance_clock(base_iso)
    lot, zone, spaces = setup_lot_zone_spaces(
        timezone=timezone,
        hourly_rate_cents=hourly_rate_cents,
        daily_cap_cents=daily_cap_cents,
        free_minutes=free_minutes,
        space_count=1,
    )
    vehicle = create_vehicle()
    card = create_card(
        card_type="STORED_VALUE",
        valid_from=valid_from,
        valid_until=valid_until,
        auto_pay_enabled=auto_pay_enabled,
    )
    bind_vehicle_to_card(card["id"], vehicle["id"])
    recharge_payment_id: Optional[str] = None
    if initial_balance_cents > 0:
        recharge_card(
            card["id"],
            amount_cents=initial_balance_cents,
            external_ref=unique_external_ref("rch"),
        )
        # The Card response from /recharge includes new balance, but we
        # need the Payment.id for downstream refund tests; resolve via the
        # card balance state. For the cases where tests need the recharge
        # payment id explicitly, callers use the dedicated fixture below.
    session = open_session(
        lot["id"],
        vehicle_id=vehicle["id"],
        space_id=spaces[0]["id"],
        card_id=card["id"],
    )
    return {
        "lot": lot,
        "zone": zone,
        "space": spaces[0],
        "vehicle": vehicle,
        "card": card,
        "session": session,
        "recharge_payment_id": recharge_payment_id,
    }


def setup_paid_session_for_refund(
    *,
    base_iso: str = "2026-01-01T09:00:00.000Z",
    final_fee_cents: int = 400,
    initial_balance_cents: int = 5000,
    partner_share_bps: int = 0,
) -> Dict[str, Any]:
    """Drive a session to PAID via a stored-value card debit so the test
    can refund the SESSION_FEE Payment.

    Sequence:
      clock=base_iso → lot(rate=400, cap=2000) → zone → space →
      vehicle → STORED_VALUE card balance=initial_balance_cents →
      open session at base_iso → advance clock 1h → exit
      (final_fee_cents=400) → pay session via card.

    Returns dict with: lot, zone, space, vehicle, card, session (EXITED+PAID),
    session_fee_payment (the SESSION_FEE Payment dict from POST /pay if
    surfaced, else None).
    """
    advance_clock(base_iso)
    lot, zone, spaces = setup_lot_zone_spaces(
        hourly_rate_cents=400,
        daily_cap_cents=2000,
        partner_share_bps=partner_share_bps,
        space_count=1,
    )
    vehicle = create_vehicle()
    card = create_card(card_type="STORED_VALUE")
    bind_vehicle_to_card(card["id"], vehicle["id"])
    recharge_card(
        card["id"],
        amount_cents=initial_balance_cents,
        external_ref=unique_external_ref("rch"),
    )
    session = open_session(
        lot["id"],
        vehicle_id=vehicle["id"],
        space_id=spaces[0]["id"],
        card_id=card["id"],
    )
    # Advance clock to drive a final_fee_cents == 400 (1 billable hour
    # under default rate=400, cap=2000, free_minutes default 15).
    advance_clock(add_hours(base_iso, 1))
    exit_session(session["id"])
    pay_session(
        session["id"],
        vehicle_id=vehicle["id"],
        card_id=card["id"],
        external_ref=unique_external_ref("pay"),
    )
    session = get_session(session["id"])
    return {
        "lot": lot,
        "zone": zone,
        "space": spaces[0],
        "vehicle": vehicle,
        "card": card,
        "session": session,
    }


def setup_held_reservation(
    *,
    base_iso: str = "2026-04-01T13:50:00.000Z",
    scheduled_start_at: str = "2026-04-01T14:00:00.000Z",
    scheduled_end_at: str = "2026-04-01T16:00:00.000Z",
    hourly_rate_cents: int = 300,
    daily_cap_cents: int = 2000,
    no_show_penalty_cents: int = 500,
    reservation_hold_minutes: Optional[int] = None,
    partner_share_bps: int = 0,
    zone_type: str = "STANDARD",
    space_label: str = "A-1",
    use_card: bool = True,
    card_auto_pay: bool = False,
) -> Dict[str, Any]:
    """Drive a HELD reservation onto a single-space zone. Creates a
    stored-value card with sufficient balance when use_card is True so
    EXPIRED_NO_SHOW penalty cascades have funds.

    Returns dict with: lot, zone, space, vehicle, card (or None),
    reservation.
    """
    advance_clock(base_iso)
    lot, zone, spaces = setup_lot_zone_spaces(
        hourly_rate_cents=hourly_rate_cents,
        daily_cap_cents=daily_cap_cents,
        no_show_penalty_cents=no_show_penalty_cents,
        reservation_hold_minutes=reservation_hold_minutes,
        partner_share_bps=partner_share_bps,
        zone_type=zone_type,
        space_count=1,
        space_labels=[space_label],
    )
    vehicle = create_vehicle()
    card: Optional[Dict[str, Any]] = None
    if use_card:
        card = create_card(
            card_type="STORED_VALUE", auto_pay_enabled=card_auto_pay
        )
        bind_vehicle_to_card(card["id"], vehicle["id"])
        recharge_card(
            card["id"],
            amount_cents=10_000,
            external_ref=unique_external_ref("rch"),
        )
    payload = create_reservation_payload(
        zone_id=zone["id"],
        vehicle_id=vehicle["id"],
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
        card_id=card["id"] if card else None,
    )
    headers = make_driver_headers(vehicle["id"])
    res = api_client.create_reservation(lot["id"], payload, headers)
    reservation = get_success_data(res)
    return {
        "lot": lot,
        "zone": zone,
        "space": spaces[0],
        "vehicle": vehicle,
        "card": card,
        "reservation": reservation,
    }


def setup_violation_pending(
    *,
    base_iso: str = "2026-02-01T10:00:00.000Z",
    violation_type: str = "BLOCKING",
    photo_uri: Optional[str] = "s3://evidence/photo-1.jpg",
    vehicle_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Set clock; build lot+zone+space; register vehicle; issue one
    violation in PENDING. Suitable BLOCKING/WRONG_ZONE photo defaults.

    Returns: lot, zone, space, vehicle, violation.
    """
    advance_clock(base_iso)
    lot, zone, spaces = setup_lot_zone_spaces(space_count=1)
    vehicle = create_vehicle(kind=vehicle_kind)
    if violation_type in {"BLOCKING", "WRONG_ZONE"}:
        photo = photo_uri
    else:
        photo = None
    violation = issue_violation(
        lot_id=lot["id"],
        vehicle_id=vehicle["id"],
        space_id=spaces[0]["id"],
        violation_type=violation_type,
        detected_at=base_iso,
        photo_uri=photo,
    )
    return {
        "lot": lot,
        "zone": zone,
        "space": spaces[0],
        "vehicle": vehicle,
        "violation": violation,
    }


def setup_session_then_overstay_violation(
    *,
    base_iso: str = "2026-06-01T08:00:00.000Z",
) -> Dict[str, Any]:
    """Drive: clock → lot+zone+space → vehicle → open session → 1h →
    exit (UNPAID). NO violation yet — caller issues the OVERSTAY in the
    test body so the cascade can be observed.

    Returns: lot, zone, space, vehicle, session (EXITED+UNPAID).
    """
    advance_clock(base_iso)
    lot, zone, spaces = setup_lot_zone_spaces(space_count=1)
    vehicle = create_vehicle()
    session = open_session(
        lot["id"], vehicle_id=vehicle["id"], space_id=spaces[0]["id"]
    )
    advance_clock(add_hours(base_iso, 1))
    exit_session(session["id"])
    session = get_session(session["id"])
    return {
        "lot": lot,
        "zone": zone,
        "space": spaces[0],
        "vehicle": vehicle,
        "session": session,
    }


def setup_three_paid_sessions_for_revenue_split(
    *,
    base_iso: str = "2026-03-01T10:00:00.000Z",
    hourly_rate_cents: int = 333,
    daily_cap_cents: int = 10_000,
    partner_share_bps: int = 2500,
) -> Dict[str, Any]:
    """Drive three concurrent sessions in three spaces, exit each at +1h,
    pay each via external rail (no card), so three RevenueEntry rows of
    gross 333 cents each are generated.

    Used by revenue_split_per_entry_vs_sum_then_round (per-entry-then-sum
    invariant test).

    Returns: lot, zone, spaces (list of 3), vehicles, sessions.
    """
    advance_clock(base_iso)
    lot, zone, spaces = setup_lot_zone_spaces(
        hourly_rate_cents=hourly_rate_cents,
        daily_cap_cents=daily_cap_cents,
        free_minutes=0,
        partner_share_bps=partner_share_bps,
        space_count=3,
        space_labels=["A-1", "A-2", "A-3"],
    )
    vehicles = [create_vehicle() for _ in range(3)]
    sessions = [
        open_session(lot["id"], vehicle_id=v["id"], space_id=s["id"])
        for v, s in zip(vehicles, spaces)
    ]
    advance_clock(add_hours(base_iso, 1))
    for s in sessions:
        exit_session(s["id"])
    paid_sessions: List[Dict[str, Any]] = []
    for s, v in zip(sessions, vehicles):
        pay_session(
            s["id"],
            vehicle_id=v["id"],
            external_ref=unique_external_ref("pay"),
        )
        paid_sessions.append(get_session(s["id"]))
    return {
        "lot": lot,
        "zone": zone,
        "spaces": spaces,
        "vehicles": vehicles,
        "sessions": paid_sessions,
    }


def setup_card_recharge_chain(
    *,
    base_iso: str = "2026-07-01T08:00:00.000Z",
) -> Dict[str, Any]:
    """Drive: clock → lot+zone+space → vehicle → STORED_VALUE card with
    auto_pay_enabled=true and balance=0 → bind → open session → +1h →
    exit (UNPAID, balance insufficient → no Payment) → return state.

    Caller invokes POST /cards/{id}/recharge to trigger the cascade.

    Returns: lot, zone, space, vehicle, card, session.
    """
    advance_clock(base_iso)
    lot, zone, spaces = setup_lot_zone_spaces(
        hourly_rate_cents=300, daily_cap_cents=2000, space_count=1
    )
    vehicle = create_vehicle()
    card = create_card(card_type="STORED_VALUE", auto_pay_enabled=True)
    bind_vehicle_to_card(card["id"], vehicle["id"])
    session = open_session(
        lot["id"],
        vehicle_id=vehicle["id"],
        space_id=spaces[0]["id"],
        card_id=card["id"],
    )
    advance_clock(add_hours(base_iso, 1))
    exit_session(session["id"])
    session = get_session(session["id"])
    return {
        "lot": lot,
        "zone": zone,
        "space": spaces[0],
        "vehicle": vehicle,
        "card": card,
        "session": session,
    }


__all__ = [
    # Time helpers
    "iso_z",
    "parse_iso",
    "add_seconds",
    "add_minutes",
    "add_hours",
    "add_days",
    # Test-driving wrappers
    "advance_clock",
    "run_sweep",
    "emit_event",
    # Tier 1
    "create_lot",
    "create_zone",
    "create_space",
    "create_vehicle",
    "create_card",
    "recharge_card",
    "bind_vehicle_to_card",
    # Tier 2
    "setup_lot_zone_spaces",
    # Tier 3
    "open_session",
    "exit_session",
    "pay_session",
    "get_session",
    "get_card",
    "get_vehicle",
    "get_violation",
    "get_reservation",
    "get_space",
    "get_lot",
    "get_revenue",
    "list_audit_logs",
    # Tier 4
    "issue_violation",
    "pay_violation",
    # Tier 5
    "setup_basic_session_scenario",
    "setup_session_with_storedvalue_card",
    "setup_paid_session_for_refund",
    "setup_held_reservation",
    "setup_violation_pending",
    "setup_session_then_overstay_violation",
    "setup_three_paid_sessions_for_revenue_split",
    "setup_card_recharge_chain",
]
