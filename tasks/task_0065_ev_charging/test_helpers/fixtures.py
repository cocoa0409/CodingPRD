"""Composite setup helpers for the EV Charging test suite.

Most interesting test claims require a multi-step preamble: create
Operator → create StationOwner Operator → create Station → create Pile →
shelve → create PricingVersion → create Member → credit wallet → create
Session → start session → append curve point → stop. Without fixtures,
every test would repeat this chain. These helpers encapsulate those
preambles so test bodies stay focused on assertions.

Identity threading (PRD §2.1):
- StationOwner is ENTITY-BACKED by Operator. Every ownership-gated call
  (shelve / off-shelve / patch a pile, accept / reject a repair ticket)
  MUST use make_station_owner_headers(operator['id']) where operator is
  the Operator row created for the station's station_owner_id.
- EVDriver is ENTITY-BACKED by Member. Every ownership-gated call
  (create / cancel reservation, join / abandon queue, create / start /
  stop a session) MUST use make_ev_driver_headers(member['id']).
- PlatformOperator / FieldTechnician / CustomerService are opaque.

Setup helpers use get_success_data (lenient), so a broken precondition
surfaces as a clear setup error rather than a confusing assertion
failure inside the test body.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    clock_advance_payload,
    complete_repair_ticket_payload,
    create_curve_point_payload,
    create_fault_report_payload,
    create_member_payload,
    create_operator_payload,
    create_payout_payload,
    create_pile_payload,
    create_pricing_version_payload,
    create_promo_activity_payload,
    create_repair_ticket_payload,
    create_reservation_payload,
    create_session_payload,
    create_station_payload,
    emit_event_payload,
    hhmm_window,
    mark_abnormal_payload,
    patch_pile_payload,
    wallet_credit_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_service_headers,
    make_ev_driver_headers,
    make_field_technician_headers,
    make_platform_operator_headers,
    make_station_owner_headers,
)


# ===========================================================================
# Shared opaque-role header constants
# ===========================================================================
PO = TEST_USERS["platform_operator_headers"]            # PlatformOperator
PO_ALT = TEST_USERS["platform_operator_headers_alt"]
FT = TEST_USERS["field_technician_headers"]             # FieldTechnician
FT_ALT = TEST_USERS["field_technician_headers_alt"]
CS = TEST_USERS["customer_service_headers"]             # CustomerService
CS_ALT = TEST_USERS["customer_service_headers_alt"]


# ===========================================================================
# ISO 8601 helpers (PRD §2.4: three fractional digits, UTC)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """ISO 8601 UTC with millisecond precision, Z-suffixed."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_day(year: int, month: int, day: int) -> str:
    """Date-only ISO 8601 UTC midnight, Z-suffixed."""
    return iso_z(datetime(year, month, day, tzinfo=timezone.utc))


# ===========================================================================
# Test-harness wrappers (PRD §2.8)
# ===========================================================================
def advance_clock_to(to_iso: str) -> Dict[str, Any]:
    """PRD §2.8: 'advances the virtual clock ... to a supplied absolute
    instant.'"""
    return get_success_data(api_client.advance_clock(
        clock_advance_payload(to_iso=to_iso), PO,
    ))


def advance_clock_by(advance_ms: int) -> Dict[str, Any]:
    """PRD §2.8: 'steps the virtual clock forward by a supplied number of
    milliseconds.'"""
    return get_success_data(api_client.advance_clock(
        clock_advance_payload(advance_ms=advance_ms), PO,
    ))


def run_sweep() -> Dict[str, Any]:
    """PRD §3.3: 'A HELD reservation transitions to EXPIRED automatically
    when the sweep capability is invoked at an instant where now is at or
    after hold_expires_at.'"""
    return get_success_data(api_client.run_sweep(PO))


def emit_event(*, source_system: str, event_type: str,
               payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """PRD §2.8: 'an event-emission capability injects an
    ExternalEventInbox row ... and runs the dispatcher synchronously
    before returning.'"""
    return get_success_data(api_client.emit_event(
        emit_event_payload(
            source_system=source_system,
            event_type=event_type,
            payload=payload or {},
        ),
        PO,
    ))


def emit_grid_pile_offline(pile_id: str) -> Dict[str, Any]:
    """PRD §3.8: 'A GRID event with event_type grid.pile_offline ... moves
    the referenced pile's operational_state to OFFLINE.'"""
    return emit_event(
        source_system="GRID", event_type="grid.pile_offline",
        payload={"pile_id": pile_id},
    )


def emit_grid_pile_online(pile_id: str) -> Dict[str, Any]:
    """PRD §3.8: 'or back to IDLE, respectively.'"""
    return emit_event(
        source_system="GRID", event_type="grid.pile_online",
        payload={"pile_id": pile_id},
    )


def emit_payment_refunded(session_id: str) -> Dict[str, Any]:
    """PRD §3.6: 'whenever a refund event arrives ... each of the four
    ledger rows is then written with amount_cents of the opposite sign and
    reason REFUND_REVERSAL.'"""
    return emit_event(
        source_system="PAYMENT", event_type="payment.refunded",
        payload={"session_id": session_id},
    )


# ===========================================================================
# Operator
# ===========================================================================
def create_operator(*, role_kind: str = "PLATFORM",
                    **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'Operators are created exclusively by PlatformOperator
    staff.'"""
    return get_success_data(api_client.create_operator(
        create_operator_payload(role_kind=role_kind, **overrides), PO,
    ))


def create_platform_operator_row(**overrides: Any) -> Dict[str, Any]:
    """Create an Operator row with role_kind=PLATFORM, used as the
    'running operator brand' on stations."""
    return create_operator(role_kind="PLATFORM", **overrides)


def create_station_owner_operator(**overrides: Any) -> Dict[str, Any]:
    """Create an Operator row with role_kind=STATION_OWNER. The id of this
    row is what StationOwner-role calls must pass as X-User-ID per PRD
    §2.1 identity rules."""
    return create_operator(role_kind="STATION_OWNER", **overrides)


def create_roaming_partner_operator(**overrides: Any) -> Dict[str, Any]:
    """Create an Operator row with role_kind=ROAMING_PARTNER."""
    return create_operator(role_kind="ROAMING_PARTNER", **overrides)


# ===========================================================================
# Station + Pile
# ===========================================================================
def create_station(*, operator_id: str, station_owner_id: str,
                   revenue_share_bps: int = 4000,
                   **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'Stations are created by PlatformOperator or StationOwner
    actors.'

    Identity gate: PRD §2.1 — StationOwner is entity_backed. Tests
    creating stations as PlatformOperator (opaque) do not face an
    ownership gate. We use the platform-operator constant here."""
    return get_success_data(api_client.create_station(
        create_station_payload(
            operator_id=operator_id,
            station_owner_id=station_owner_id,
            revenue_share_bps=revenue_share_bps,
            **overrides,
        ),
        PO,
    ))


def create_pile(*, station_id: str, station_owner_id: str,
                **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 + §2.1: 'Add a pile to a station' is StationOwner-only.
    Owner identity must equal the station's station_owner_id."""
    return get_success_data(api_client.create_pile(
        station_id, create_pile_payload(**overrides),
        make_station_owner_headers(station_owner_id),
    ))


def shelve_pile(*, pile_id: str, station_owner_id: str,
                version: Any = "__OMIT__") -> Dict[str, Any]:
    """PRD §3.1: 'The shelving action, performed by a StationOwner, moves
    the pile from OFF_SHELF to ON_SHELF.'"""
    payload: Dict[str, Any] = {}
    if version != "__OMIT__":
        payload["version"] = version
    return get_success_data(api_client.shelve_pile(
        pile_id, make_station_owner_headers(station_owner_id), payload,
    ))


def off_shelve_pile(*, pile_id: str, station_owner_id: str,
                    version: Any = "__OMIT__") -> Dict[str, Any]:
    """PRD §3.1: 'The off-shelving action returns the pile from ON_SHELF
    back to OFF_SHELF.'"""
    payload: Dict[str, Any] = {}
    if version != "__OMIT__":
        payload["version"] = version
    return get_success_data(api_client.off_shelve_pile(
        pile_id, make_station_owner_headers(station_owner_id), payload,
    ))


def decommission_pile(*, pile_id: str,
                      version: Any = "__OMIT__") -> Dict[str, Any]:
    """PRD §3.1: 'Decommissioning, performed by a PlatformOperator, is a
    one-way transition from OFF_SHELF to DECOMMISSIONED.'"""
    payload: Dict[str, Any] = {}
    if version != "__OMIT__":
        payload["version"] = version
    return get_success_data(api_client.decommission_pile(
        pile_id, PO, payload,
    ))


def patch_pile(*, pile_id: str, station_owner_id: str,
               **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'Pile metadata ... is updated by the StationOwner
    through the pile-edit capability.'"""
    return get_success_data(api_client.patch_pile(
        pile_id, patch_pile_payload(**overrides),
        make_station_owner_headers(station_owner_id),
    ))


def get_pile(pile_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_pile(pile_id, headers or PO))


# ===========================================================================
# Member + wallet
# ===========================================================================
def create_member(*, home_operator_id: str,
                  tier: Any = "__OMIT__",
                  wallet_balance_cents: int = 0,
                  **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: 'Members are created by PlatformOperator or
    CustomerService staff.'

    If wallet_balance_cents > 0, a wallet-credit call is chained
    afterwards to bring the wallet up. PRD §3.2: 'Wallet credits ...
    increase wallet_balance_cents by a supplied amount_cents.'"""
    member = get_success_data(api_client.create_member(
        create_member_payload(
            home_operator_id=home_operator_id,
            tier=tier,
            **overrides,
        ),
        PO,
    ))
    if wallet_balance_cents > 0:
        member = credit_wallet(
            member_id=member["id"],
            amount_cents=wallet_balance_cents,
        )
    return member


def credit_wallet(*, member_id: str, amount_cents: int,
                  version: Any = "__OMIT__") -> Dict[str, Any]:
    return get_success_data(api_client.wallet_credit(
        member_id,
        wallet_credit_payload(amount_cents=amount_cents, version=version),
        PO,
    ))


def get_member(member_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_member(
        member_id, headers or PO,
    ))


# ===========================================================================
# Pricing version / promo activity
# ===========================================================================
def create_pricing_version(*, operator_id: str,
                           effective_from: Optional[str] = None,
                           effective_to: Optional[str] = None,
                           **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: 'Pricing is governed by immutable, append-only
    PricingVersion rows.'

    Default window: a wide forward-looking interval [2026-01-01,
    2030-01-01) so any test-time clock value falls inside."""
    if effective_from is None:
        effective_from = iso_day(2026, 1, 1)
    if effective_to is None:
        effective_to = iso_day(2030, 1, 1)
    return get_success_data(api_client.create_pricing_version(
        create_pricing_version_payload(
            operator_id=operator_id,
            effective_from=effective_from,
            effective_to=effective_to,
            **overrides,
        ),
        PO,
    ))


def create_promo_activity(*, operator_id: str,
                          starts_at: Optional[str] = None,
                          ends_at: Optional[str] = None,
                          **overrides: Any) -> Dict[str, Any]:
    if starts_at is None:
        starts_at = iso_day(2026, 1, 1)
    if ends_at is None:
        ends_at = iso_day(2030, 1, 1)
    return get_success_data(api_client.create_promo_activity(
        create_promo_activity_payload(
            operator_id=operator_id,
            starts_at=starts_at, ends_at=ends_at,
            **overrides,
        ),
        PO,
    ))


# ===========================================================================
# Reservation / queue
# ===========================================================================
def create_reservation(*, pile_id: str, member_id: str) -> Dict[str, Any]:
    """PRD §3.3 + §2.1: 'A driver who wants a guaranteed slot creates a
    Reservation.' EVDriver is entity_backed by Member — thread member_id
    as X-User-ID."""
    return get_success_data(api_client.create_reservation(
        create_reservation_payload(pile_id=pile_id),
        make_ev_driver_headers(member_id),
    ))


def cancel_reservation(*, reservation_id: str, member_id: str,
                       version: Any = "__OMIT__") -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version != "__OMIT__":
        payload["version"] = version
    return get_success_data(api_client.cancel_reservation(
        reservation_id, make_ev_driver_headers(member_id), payload,
    ))


def get_reservation(reservation_id: str,
                    headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    return get_success_data(api_client.get_reservation(
        reservation_id, headers or PO,
    ))


def join_queue(*, station_id: str, member_id: str) -> Dict[str, Any]:
    """PRD §3.3: 'A QueueEntry is created against a station_id with
    member_id taken from X-User-ID.'"""
    return get_success_data(api_client.create_queue_entry(
        station_id, make_ev_driver_headers(member_id),
    ))


def abandon_queue_entry(*, queue_entry_id: str, member_id: str,
                        version: Any = "__OMIT__") -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version != "__OMIT__":
        payload["version"] = version
    return get_success_data(api_client.abandon_queue_entry(
        queue_entry_id, make_ev_driver_headers(member_id), payload,
    ))


def list_queue_entries(station_id: str,
                       headers: Optional[Dict[str, str]] = None,
                       params: Optional[Dict[str, Any]] = None,
                       ) -> List[Dict[str, Any]]:
    res = api_client.list_queue_entries(
        station_id, headers or PO,
        params=params or {"limit": 100},
    )
    rows, _meta = validate_paginated(res)
    return rows


# ===========================================================================
# Session
# ===========================================================================
def create_session(*, pile_id: str, member_id: str,
                   reservation_id: Any = "__OMIT__",
                   auth_method: str = "APP") -> Dict[str, Any]:
    """PRD §3.4 + §2.1: 'A ChargingSession is created in PENDING_AUTH
    state by an EVDriver.' Thread member_id as X-User-ID."""
    return get_success_data(api_client.create_session(
        create_session_payload(
            pile_id=pile_id, member_id=member_id,
            auth_method=auth_method,
            reservation_id=reservation_id,
        ),
        make_ev_driver_headers(member_id),
    ))


def start_session(*, session_id: str, member_id: str,
                  version: Any = "__OMIT__") -> Dict[str, Any]:
    """PRD §3.4: 'The session is brought to life by the start action,
    advancing it from PENDING_AUTH to CHARGING.'"""
    payload: Dict[str, Any] = {}
    if version != "__OMIT__":
        payload["version"] = version
    return get_success_data(api_client.start_session(
        session_id, make_ev_driver_headers(member_id), payload,
    ))


def stop_session(*, session_id: str, member_id: str,
                 version: Any = "__OMIT__") -> Dict[str, Any]:
    """PRD §3.4: 'The driver (or the platform) stops the session,
    advancing it from CHARGING to SETTLING.'"""
    payload: Dict[str, Any] = {}
    if version != "__OMIT__":
        payload["version"] = version
    return get_success_data(api_client.stop_session(
        session_id, make_ev_driver_headers(member_id), payload,
    ))


def abort_session(*, session_id: str,
                  version: Any = "__OMIT__") -> Dict[str, Any]:
    """PRD §3.4: 'CustomerService may invoke an override abort.'"""
    payload: Dict[str, Any] = {}
    if version != "__OMIT__":
        payload["version"] = version
    return get_success_data(api_client.abort_session(
        session_id, CS, payload,
    ))


def append_curve_point(*, session_id: str, sampled_at: str,
                       cumulative_energy_milli: int,
                       instant_power_kw: float = 60.0,
                       window_tag: str = "FLAT") -> Dict[str, Any]:
    """PRD §3.4: 'the pile's telemetry stream appends ChargingCurvePoint
    rows tagged with a window_tag of PEAK, FLAT, or VALLEY.' Endpoint is
    PlatformOperator/FieldTechnician."""
    return get_success_data(api_client.create_curve_point(
        session_id,
        create_curve_point_payload(
            sampled_at=sampled_at,
            cumulative_energy_milli=cumulative_energy_milli,
            instant_power_kw=instant_power_kw,
            window_tag=window_tag,
        ),
        PO,
    ))


def mark_abnormal(*, session_id: str,
                  event_type: str = "OVER_TEMPERATURE") -> Dict[str, Any]:
    return get_success_data(api_client.mark_abnormal(
        session_id, mark_abnormal_payload(event_type=event_type), PO,
    ))


def get_session(session_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_session(
        session_id, headers or PO,
    ))


def get_estimate(session_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_session_estimate(
        session_id, headers or PO,
    ))


def list_session_ledger_entries(
    session_id: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    res = api_client.list_session_ledger_entries(
        session_id, headers or PO,
        params=params or {"limit": 100},
    )
    rows, _meta = validate_paginated(res)
    return rows


# ===========================================================================
# Faults and repair tickets
# ===========================================================================
def create_fault_report(*, pile_id: str, reporter_kind: str = "AUTO_DETECT",
                        severity: str = "MAJOR",
                        reporter_member_id: Any = "__OMIT__",
                        headers: Optional[Dict[str, str]] = None,
                        **overrides: Any) -> Dict[str, Any]:
    """PRD §3.5: 'A FaultReport against a pile is opened by an EVDriver
    ... by a FieldTechnician or auto-detection system ... or by a
    PlatformOperator.'"""
    return get_success_data(api_client.create_fault_report(
        create_fault_report_payload(
            pile_id=pile_id,
            reporter_kind=reporter_kind,
            severity=severity,
            reporter_member_id=reporter_member_id,
            **overrides,
        ),
        headers or PO,
    ))


def isolate_fault_report(*, fault_id: str,
                         headers: Optional[Dict[str, str]] = None,
                         version: Any = "__OMIT__") -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version != "__OMIT__":
        payload["version"] = version
    return get_success_data(api_client.isolate_fault_report(
        fault_id, headers or PO, payload,
    ))


def get_fault_report(fault_id: str,
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    return get_success_data(api_client.get_fault_report(
        fault_id, headers or PO,
    ))


def create_repair_ticket(*, fault_id: str,
                         assigned_technician_id: str) -> Dict[str, Any]:
    """PRD §3.5: 'A ticket is opened in OPEN by a PlatformOperator.'"""
    return get_success_data(api_client.create_repair_ticket(
        fault_id,
        create_repair_ticket_payload(
            assigned_technician_id=assigned_technician_id,
        ),
        PO,
    ))


def dispatch_repair_ticket(*, ticket_id: str,
                           version: Any = "__OMIT__") -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version != "__OMIT__":
        payload["version"] = version
    return get_success_data(api_client.dispatch_repair_ticket(
        ticket_id, PO, payload,
    ))


def begin_repair_ticket(*, ticket_id: str, technician_user_id: str,
                        version: Any = "__OMIT__") -> Dict[str, Any]:
    """PRD §3.5: 'Begin, invoked by a FieldTechnician, moves the ticket
    from DISPATCHED to IN_REPAIR provided assigned_technician_id matches
    X-User-ID.'"""
    payload: Dict[str, Any] = {}
    if version != "__OMIT__":
        payload["version"] = version
    return get_success_data(api_client.begin_repair_ticket(
        ticket_id,
        make_field_technician_headers(technician_user_id),
        payload,
    ))


def complete_repair_ticket(*, ticket_id: str, technician_user_id: str,
                           repair_notes: str = "OK",
                           version: Any = "__OMIT__") -> Dict[str, Any]:
    """PRD §3.5: 'Complete, invoked by the same technician, moves it from
    IN_REPAIR to AWAITING_ACCEPTANCE and records the supplied
    repair_notes.'"""
    return get_success_data(api_client.complete_repair_ticket(
        ticket_id,
        complete_repair_ticket_payload(
            repair_notes=repair_notes, version=version,
        ),
        make_field_technician_headers(technician_user_id),
    ))


def accept_repair_ticket(*, ticket_id: str, station_owner_id: str,
                         version: Any = "__OMIT__") -> Dict[str, Any]:
    """PRD §3.5: 'Acceptance by a StationOwner (whose X-User-ID matches
    the parent station's station_owner_id).'"""
    payload: Dict[str, Any] = {}
    if version != "__OMIT__":
        payload["version"] = version
    return get_success_data(api_client.accept_repair_ticket(
        ticket_id, make_station_owner_headers(station_owner_id), payload,
    ))


def reject_repair_ticket(*, ticket_id: str, station_owner_id: str,
                         version: Any = "__OMIT__") -> Dict[str, Any]:
    """PRD §3.5: 'Rejection by the same StationOwner moves the ticket
    back from AWAITING_ACCEPTANCE to IN_REPAIR.'"""
    payload: Dict[str, Any] = {}
    if version != "__OMIT__":
        payload["version"] = version
    return get_success_data(api_client.reject_repair_ticket(
        ticket_id, make_station_owner_headers(station_owner_id), payload,
    ))


# ===========================================================================
# Payout
# ===========================================================================
def create_payout(*, operator_id: str, period_start: str,
                  period_end: str) -> Dict[str, Any]:
    return get_success_data(api_client.create_payout(
        create_payout_payload(
            operator_id=operator_id,
            period_start=period_start, period_end=period_end,
        ),
        PO,
    ))


def issue_payout(*, payout_id: str,
                 version: Any = "__OMIT__") -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version != "__OMIT__":
        payload["version"] = version
    return get_success_data(api_client.issue_payout(
        payout_id, PO, payload,
    ))


def get_payout(payout_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_payout(
        payout_id, headers or PO,
    ))


# ===========================================================================
# Audit logs
# ===========================================================================
def list_audit_logs(
    *,
    event_kind: Optional[str] = None,
    entity_kind: Optional[str] = None,
    entity_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": 100}
    if event_kind is not None:
        params["event_kind"] = event_kind
    if entity_kind is not None:
        params["entity_kind"] = entity_kind
    if entity_id is not None:
        params["entity_id"] = entity_id
    res = api_client.list_audit_logs(headers or PO, params=params)
    rows, _meta = validate_paginated(res)
    return rows


# ===========================================================================
# Composite Tier 2: operator + station + pile (no shelve)
# ===========================================================================
def setup_operator_station_pile_off_shelf(
    *,
    revenue_share_bps: int = 4000,
    pile_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create an Operator (platform brand) + a StationOwner Operator + a
    Station + a Pile in OFF_SHELF state. Returns dict with keys:
    operator, station_owner, station, pile.

    PRD §3.1 anchors: 'New piles start OFF_SHELF.'"""
    operator = create_platform_operator_row()
    station_owner = create_station_owner_operator()
    station = create_station(
        operator_id=operator["id"],
        station_owner_id=station_owner["id"],
        revenue_share_bps=revenue_share_bps,
    )
    pile = create_pile(
        station_id=station["id"],
        station_owner_id=station_owner["id"],
        **(pile_overrides or {}),
    )
    return {
        "operator": operator,
        "station_owner": station_owner,
        "station": station,
        "pile": pile,
    }


def setup_operator_station_shelved_pile(
    *,
    revenue_share_bps: int = 4000,
    pile_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Tier 2: Active station with an ON_SHELF + IDLE pile.

    PRD §3.1: 'The shelving action ... moves the pile from OFF_SHELF to
    ON_SHELF provided ... the pile's operational_state is simultaneously
    set to IDLE.'"""
    ctx = setup_operator_station_pile_off_shelf(
        revenue_share_bps=revenue_share_bps,
        pile_overrides=pile_overrides,
    )
    pile = shelve_pile(
        pile_id=ctx["pile"]["id"],
        station_owner_id=ctx["station_owner"]["id"],
    )
    ctx["pile"] = pile
    return ctx


# ===========================================================================
# Composite Tier 2: shelved pile + pricing version + member with wallet
# ===========================================================================
def setup_ready_to_charge(
    *,
    revenue_share_bps: int = 4000,
    member_tier: Any = "__OMIT__",
    member_wallet_cents: int = 100000,
    pricing_overrides: Optional[Dict[str, Any]] = None,
    member_home_operator_id: Optional[str] = None,
    promo_overrides: Optional[Dict[str, Any]] = None,
    create_promo: bool = False,
    pile_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Tier 2: every precondition for a Session to start is satisfied:
    Operator + StationOwner + Station(ACTIVE) + Pile(ON_SHELF,IDLE) +
    PricingVersion + Member(wallet >= MIN_AUTH_HOLD_CENTS).

    Returns dict with keys: operator, station_owner, station, pile,
    pricing_version, member. If create_promo is True, also: promo.

    `member_home_operator_id` defaults to the station's operator (non-
    roaming). Pass a roaming partner's id for the roaming case. PRD §3.6:
    'it is roaming when the member's home_operator_id is not equal to the
    station's operator_id.'"""
    base = setup_operator_station_shelved_pile(
        revenue_share_bps=revenue_share_bps,
        pile_overrides=pile_overrides,
    )
    pricing_version = create_pricing_version(
        operator_id=base["operator"]["id"],
        **(pricing_overrides or {}),
    )
    home_operator = (
        member_home_operator_id or base["operator"]["id"]
    )
    member = create_member(
        home_operator_id=home_operator,
        tier=member_tier,
        wallet_balance_cents=member_wallet_cents,
    )
    out: Dict[str, Any] = {
        **base,
        "pricing_version": pricing_version,
        "member": member,
    }
    if create_promo:
        promo = create_promo_activity(
            operator_id=base["operator"]["id"],
            **(promo_overrides or {}),
        )
        out["promo"] = promo
    return out


# ===========================================================================
# Composite Tier 3: session in a specific lifecycle stage
# ===========================================================================
def setup_charging_session(
    *,
    revenue_share_bps: int = 4000,
    member_tier: Any = "__OMIT__",
    member_wallet_cents: int = 100000,
    pricing_overrides: Optional[Dict[str, Any]] = None,
    member_home_operator_id: Optional[str] = None,
    auth_method: str = "APP",
    use_reservation: bool = False,
    promo_overrides: Optional[Dict[str, Any]] = None,
    create_promo: bool = False,
    pile_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Tier 3: walks the chain create_session → start_session and returns
    the context with status CHARGING. Optional: route through a
    Reservation if use_reservation is True.

    PRD §3.4: 'The session is brought to life by the start action,
    advancing it from PENDING_AUTH to CHARGING.'"""
    ctx = setup_ready_to_charge(
        revenue_share_bps=revenue_share_bps,
        member_tier=member_tier,
        member_wallet_cents=member_wallet_cents,
        pricing_overrides=pricing_overrides,
        member_home_operator_id=member_home_operator_id,
        promo_overrides=promo_overrides,
        create_promo=create_promo,
        pile_overrides=pile_overrides,
    )
    reservation_id: Any = "__OMIT__"
    if use_reservation:
        reservation = create_reservation(
            pile_id=ctx["pile"]["id"],
            member_id=ctx["member"]["id"],
        )
        ctx["reservation"] = reservation
        reservation_id = reservation["id"]

    session = create_session(
        pile_id=ctx["pile"]["id"],
        member_id=ctx["member"]["id"],
        auth_method=auth_method,
        reservation_id=reservation_id,
    )
    session = start_session(
        session_id=session["id"],
        member_id=ctx["member"]["id"],
    )
    ctx["session"] = session
    return ctx


def setup_settled_session(
    *,
    revenue_share_bps: int = 4000,
    member_tier: Any = "__OMIT__",
    member_wallet_cents: int = 100000,
    pricing_overrides: Optional[Dict[str, Any]] = None,
    member_home_operator_id: Optional[str] = None,
    curve_points: Optional[List[Tuple[str, int, str]]] = None,
    pile_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Tier 3: walks the chain to SETTLED. curve_points is a list of
    (sampled_at, cumulative_energy_milli, window_tag) tuples; if omitted,
    a single FLAT 10000 milli-kWh sample is appended.

    PRD §3.4: 'Once at least one curve point with non-negative
    cumulative_energy_milli exists, the session automatically advances
    from SETTLING to SETTLED.'"""
    ctx = setup_charging_session(
        revenue_share_bps=revenue_share_bps,
        member_tier=member_tier,
        member_wallet_cents=member_wallet_cents,
        pricing_overrides=pricing_overrides,
        member_home_operator_id=member_home_operator_id,
        pile_overrides=pile_overrides,
    )
    if curve_points is None:
        # Single FLAT-window 10 kWh sample.
        curve_points = [
            ("2026-05-13T00:01:00.000Z", 10000, "FLAT"),
        ]
    for sampled_at, cum_milli, tag in curve_points:
        append_curve_point(
            session_id=ctx["session"]["id"],
            sampled_at=sampled_at,
            cumulative_energy_milli=cum_milli,
            window_tag=tag,
        )
    session = stop_session(
        session_id=ctx["session"]["id"],
        member_id=ctx["member"]["id"],
    )
    ctx["session"] = session
    return ctx


# ===========================================================================
# Composite Tier 3: fault / repair lifecycle
# ===========================================================================
def setup_repair_awaiting_acceptance(
    *,
    technician_user_id: str = "field-technician-001",
    severity: str = "MAJOR",
) -> Dict[str, Any]:
    """Tier 3: walks fault → dispatch → begin → complete so the ticket is
    in AWAITING_ACCEPTANCE. Returns context including fault and ticket.

    PRD §3.5: 'The normal walk is OPEN → DISPATCHED → IN_REPAIR →
    AWAITING_ACCEPTANCE → CLOSED.'"""
    base = setup_operator_station_shelved_pile()
    fault = create_fault_report(
        pile_id=base["pile"]["id"],
        reporter_kind="AUTO_DETECT",
        severity=severity,
    )
    ticket = create_repair_ticket(
        fault_id=fault["id"],
        assigned_technician_id=technician_user_id,
    )
    ticket = dispatch_repair_ticket(ticket_id=ticket["id"])
    ticket = begin_repair_ticket(
        ticket_id=ticket["id"],
        technician_user_id=technician_user_id,
    )
    ticket = complete_repair_ticket(
        ticket_id=ticket["id"],
        technician_user_id=technician_user_id,
    )
    return {**base, "fault": fault, "ticket": ticket,
            "technician_user_id": technician_user_id}


def setup_repair_closed(
    *,
    technician_user_id: str = "field-technician-001",
    severity: str = "MAJOR",
) -> Dict[str, Any]:
    """Tier 3: walks fault → dispatch → begin → complete → accept so the
    ticket is CLOSED and the parent fault is RESOLVED, pile back to IDLE."""
    ctx = setup_repair_awaiting_acceptance(
        technician_user_id=technician_user_id,
        severity=severity,
    )
    ticket = accept_repair_ticket(
        ticket_id=ctx["ticket"]["id"],
        station_owner_id=ctx["station_owner"]["id"],
    )
    ctx["ticket"] = ticket
    return ctx


# ===========================================================================
# Composite Tier 4: cumulative state for difficulty-design coverage
# ===========================================================================
def setup_reservation_held(
    *,
    member_wallet_cents: int = 100000,
) -> Dict[str, Any]:
    """Tier 4: a Member holds a Reservation on a shelved IDLE pile."""
    ctx = setup_ready_to_charge(
        member_wallet_cents=member_wallet_cents,
    )
    reservation = create_reservation(
        pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
    )
    ctx["reservation"] = reservation
    return ctx


def setup_two_members_one_at_queue_front(
    *,
    front_wallet_cents: int = 100000,
    late_wallet_cents: int = 100000,
) -> Dict[str, Any]:
    """Tier 4: M_first queues first (position 1), M_late queues second
    (position 2). Both members have configurable wallet balances so the
    test can isolate priority of validation rules."""
    base = setup_operator_station_shelved_pile()
    pricing = create_pricing_version(operator_id=base["operator"]["id"])
    m_first = create_member(
        home_operator_id=base["operator"]["id"],
        wallet_balance_cents=front_wallet_cents,
    )
    m_late = create_member(
        home_operator_id=base["operator"]["id"],
        wallet_balance_cents=late_wallet_cents,
    )
    q_first = join_queue(
        station_id=base["station"]["id"], member_id=m_first["id"],
    )
    q_late = join_queue(
        station_id=base["station"]["id"], member_id=m_late["id"],
    )
    return {
        **base,
        "pricing_version": pricing,
        "m_first": m_first,
        "m_late": m_late,
        "q_first": q_first,
        "q_late": q_late,
    }


def setup_settled_session_for_recipe(
    *,
    member_tier: str = "SILVER",
    member_wallet_cents: int = 100000,
    revenue_share_bps: int = 4000,
    member_home_operator_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Tier 4: SCAFFOLD_DIFFICULTY_DESIGN rule 1 / instance
    session_total_provisional_vs_final canonical setup. PricingVersion:
    peak=80, flat=50, valley=30, service_fee=20, tax_bps=1300,
    tier_discount SILVER=500. Member tier SILVER. Two curve points
    @10000 and @15000 milli-kWh in FLAT window. Returns the fully SETTLED
    session for downstream assertions.

    Expected on SETTLE (per recipe and PRD §3.4 / §3.6 math):
      - electricity_fee_cents == 750 (15000 * 50 / 1000 = 750)
      - service_fee_cents == 285 (base = 15*20 = 300; (10000-500)/10000 *
        (10000-0)/10000 = 0.95; 300 * 0.95 = 285)
      - tax_cents == 135 (1035 * 1300 / 10000 = 134.55 → 135 via
        round_half_up)
      - total_cents == 1170 (750 + 285 + 135)
    """
    pricing_overrides = dict(
        peak_rate_per_kwh_cents=80,
        flat_rate_per_kwh_cents=50,
        valley_rate_per_kwh_cents=30,
        service_fee_per_kwh_cents=20,
        tax_bps=1300,
        peak_windows=[],
        valley_windows=[],
        tier_service_fee_discount_bps={
            "BASIC": 0, "SILVER": 500, "GOLD": 1000, "PLATINUM": 1500,
        },
    )
    return setup_settled_session(
        revenue_share_bps=revenue_share_bps,
        member_tier=member_tier,
        member_wallet_cents=member_wallet_cents,
        pricing_overrides=pricing_overrides,
        member_home_operator_id=member_home_operator_id,
        curve_points=[
            ("2026-05-13T00:01:00.000Z", 10000, "FLAT"),
            ("2026-05-13T00:02:00.000Z", 15000, "FLAT"),
        ],
    )


def setup_strike_member(
    *,
    target_strikes: int,
    member_home_operator_id: Optional[str] = None,
    clock_base: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Tier 4: accumulate target_strikes no-show strikes on a Member by
    repeatedly creating + expiring + sweeping reservations.

    Each cycle:
      1. clock-advance to a fresh base instant (forward-only)
      2. create_reservation on a fresh shelved IDLE pile
      3. clock-advance past the 15-minute hold
      4. run_sweep — increments no_show_strikes by one

    `clock_base` allows callers to control the starting wall-clock so
    they can chain multiple invocations with strictly forward-moving
    clocks (avoiding any reliance on the implementation supporting a
    rewind via /_clock/advance to_iso). PRD §2.8 says 'advance_ms' /
    'to_iso' are 'idempotent on absolute time' — silent on whether
    rewinds are supported, so tests treat the clock as forward-only.

    Note: PRD §3.3 says 'A driver whose no_show_strikes has reached
    three or more is barred from reserving' — so target_strikes <= 3
    must hold if subsequent reservations are needed.

    Returns context dict: operator, station_owner, station, pile,
    pricing_version, member (with no_show_strikes >= target_strikes).
    """
    base = setup_operator_station_shelved_pile()
    pricing = create_pricing_version(operator_id=base["operator"]["id"])
    home_operator_id = member_home_operator_id or base["operator"]["id"]
    # Use a high wallet so penalty deductions don't drive clamp-at-zero.
    member = create_member(
        home_operator_id=home_operator_id,
        wallet_balance_cents=1_000_000,
    )

    base_t = clock_base or datetime(
        2026, 5, 13, 0, 0, 0, tzinfo=timezone.utc,
    )
    for i in range(target_strikes):
        cycle_base = base_t + timedelta(hours=2 * i)
        advance_clock_to(iso_z(cycle_base))
        create_reservation(
            pile_id=base["pile"]["id"], member_id=member["id"],
        )
        # Push past the 15-minute hold window.
        advance_clock_to(iso_z(cycle_base + timedelta(minutes=16)))
        run_sweep()

    member = get_member(member["id"])
    return {
        **base,
        "pricing_version": pricing,
        "member": member,
    }


def setup_session_in_payout_window(
    *,
    member_tier: str = "SILVER",
    member_wallet_cents: int = 100000,
    revenue_share_bps: int = 4000,
) -> Dict[str, Any]:
    """Tier 4: a settled session whose ended_at falls inside a payout
    window. Returns context plus a 'period_start'/'period_end' covering
    the session.

    PRD §3.7: 'the system computes three monetary totals from the
    operator's SettlementLedgerEntry rows whose source session's
    ended_at falls within [period_start, period_end).'"""
    # Anchor the virtual clock at noon on 2026-05-13 so that the session's
    # ended_at (set from now_iso() at stop time) falls inside the fixed
    # payout window [2026-05-13, 2026-05-14). The wall-clock the runner
    # started with may differ from this date.
    advance_clock_to("2026-05-13T12:00:00.000Z")
    ctx = setup_settled_session_for_recipe(
        member_tier=member_tier,
        member_wallet_cents=member_wallet_cents,
        revenue_share_bps=revenue_share_bps,
    )
    ctx["period_start"] = iso_day(2026, 5, 13)
    ctx["period_end"] = iso_day(2026, 5, 14)
    return ctx


__all__ = [
    "PO", "PO_ALT", "FT", "FT_ALT", "CS", "CS_ALT",
    "iso_z", "iso_day",
    "advance_clock_to", "advance_clock_by", "run_sweep",
    "emit_event", "emit_grid_pile_offline", "emit_grid_pile_online",
    "emit_payment_refunded",
    "create_operator",
    "create_platform_operator_row",
    "create_station_owner_operator",
    "create_roaming_partner_operator",
    "create_station",
    "create_pile", "shelve_pile", "off_shelve_pile", "decommission_pile",
    "patch_pile", "get_pile",
    "create_member", "credit_wallet", "get_member",
    "create_pricing_version", "create_promo_activity",
    "create_reservation", "cancel_reservation", "get_reservation",
    "join_queue", "abandon_queue_entry", "list_queue_entries",
    "create_session", "start_session", "stop_session", "abort_session",
    "append_curve_point", "mark_abnormal",
    "get_session", "get_estimate", "list_session_ledger_entries",
    "create_fault_report", "isolate_fault_report", "get_fault_report",
    "create_repair_ticket", "dispatch_repair_ticket",
    "begin_repair_ticket", "complete_repair_ticket",
    "accept_repair_ticket", "reject_repair_ticket",
    "create_payout", "issue_payout", "get_payout",
    "list_audit_logs",
    "setup_operator_station_pile_off_shelf",
    "setup_operator_station_shelved_pile",
    "setup_ready_to_charge",
    "setup_charging_session",
    "setup_settled_session",
    "setup_repair_awaiting_acceptance",
    "setup_repair_closed",
    "setup_reservation_held",
    "setup_two_members_one_at_queue_front",
    "setup_settled_session_for_recipe",
    "setup_strike_member",
    "setup_session_in_payout_window",
]
