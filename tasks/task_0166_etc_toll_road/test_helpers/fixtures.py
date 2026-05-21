"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce
clear "setup failed" errors instead of confusing assertion failures.

Identity threading (PRD §2.1): the AccountHolder role is entity_backed —
any ownership-gated call must be issued with headers minted from the
real Account.id via make_account_holder_headers(account_id). Fixtures
in this module take that responsibility for tests.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AUTO_RELOAD_THRESHOLD_DEFAULT_CENTS,
    AUTO_RELOAD_TOPUP_DEFAULT_CENTS,
    TEST_DEFAULTS,
)
from .factories import (
    add_days,
    add_seconds,
    bind_transponder_payload,
    clock_advance_payload,
    create_account_payload,
    create_interop_policy_payload,
    create_reload_payload,
    create_toll_event_payload,
    create_transponder_payload,
    create_vehicle_payload,
    dispute_fine_payload,
    iso_now,
    iso_utc,
    parse_iso,
    pay_fine_payload,
    random_plate,
    random_serial,
    utcnow,
)
from .test_users import (
    TEST_USERS,
    make_account_holder_headers,
)


# ---------------------------------------------------------------------------
# Clock tracker — keeps the test process's notion of the implementation's
# logical clock in sync so absolute timestamps can be built off it.
# ---------------------------------------------------------------------------
_CLOCK_NOW: Optional[datetime] = None


def reset_clock_tracker_to(dt: datetime) -> None:
    global _CLOCK_NOW
    _CLOCK_NOW = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(
        tzinfo=timezone.utc
    )


def current_clock() -> datetime:
    global _CLOCK_NOW
    if _CLOCK_NOW is None:
        _CLOCK_NOW = utcnow()
    return _CLOCK_NOW


def current_clock_iso() -> str:
    return iso_utc(current_clock())


def advance_clock_to(dt: datetime, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Advance the implementation clock to dt (AgencyAdmin)."""
    hdrs = headers or TEST_USERS["agency_admin_headers"]
    iso = iso_utc(dt)
    res = api_client.advance_clock(clock_advance_payload(to_iso8601=iso), hdrs)
    reset_clock_tracker_to(dt)
    try:
        return get_success_data(res)
    except Exception:
        return {}


def advance_clock_by_days(days: int) -> None:
    advance_clock_to(add_days(current_clock(), days))


def advance_clock_by_seconds(seconds: float) -> None:
    advance_clock_to(add_seconds(current_clock(), seconds))


def run_overdue_sweep() -> Dict[str, Any]:
    res = api_client.run_sweep(TEST_USERS["agency_admin_headers"])
    try:
        return get_success_data(res)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Tier 1: Single-entity creation helpers
# ---------------------------------------------------------------------------
def create_account(home_agency_code: str = "NY_EZPASS",
                   balance_cents: Optional[int] = None,
                   auto_reload_enabled: bool = False,
                   auto_reload_threshold_cents: Optional[int] = None,
                   auto_reload_topup_cents: Optional[int] = None,
                   payment_method_token: Optional[str] = None,
                   **extra: Any) -> Dict[str, Any]:
    """Create an Account as AgencyAdmin (PRD §3.1 reserves POST /accounts
    to AgencyAdmin).

    If balance_cents is supplied (and != 0), this performs an additional
    manual reload to set the starting balance — the create endpoint only
    accepts the inputs listed in §3.1; balance must be set by reload.
    """
    payload = create_account_payload(
        home_agency_code=home_agency_code,
        auto_reload_enabled=auto_reload_enabled,
    )
    if auto_reload_enabled or payment_method_token is not None:
        payload["payment_method_token"] = (
            payment_method_token or TEST_DEFAULTS["PAYMENT_METHOD_TOKEN"]
        )
    if auto_reload_threshold_cents is not None:
        payload["auto_reload_threshold_cents"] = auto_reload_threshold_cents
    if auto_reload_topup_cents is not None:
        payload["auto_reload_topup_cents"] = auto_reload_topup_cents
    payload.update(extra)

    res = api_client.create_account(
        payload, TEST_USERS["agency_admin_headers"],
    )
    account = get_success_data(res)

    if balance_cents is not None and balance_cents > 0:
        # PRD §3.4 manual reload accepts 100..50000; for larger pre-loads
        # call repeatedly. Manual reload requires AccountHolder identity
        # to be the Account.id when called by AccountHolder; we call as
        # AgencyAdmin (also authorized per PRD §4) so opaque-id is fine.
        remaining = balance_cents
        while remaining > 0:
            chunk = min(remaining, 50000)
            # PRD §3.4: reload amount must be in [100, 50000].
            if chunk < 100:
                # Top up with one more 100-cent reload — caller asked
                # for less than the minimum, give them what we can.
                chunk = 100
                remaining = 0
            else:
                remaining -= chunk
            r = api_client.create_reload(
                account["id"],
                create_reload_payload(amount_cents=chunk),
                TEST_USERS["agency_admin_headers"],
            )
            get_success_data(r)

        # Re-fetch to capture the new balance and bumped version.
        fres = api_client.get_account(
            account["id"], TEST_USERS["agency_admin_headers"],
        )
        account = get_success_data(fres)

    return account


def create_vehicle(account_id: str,
                   plate_number: Optional[str] = None,
                   plate_state: str = "NY",
                   axle_count: int = 2,
                   hov_capable: bool = True,
                   **extra: Any) -> Dict[str, Any]:
    """Create a Vehicle on the given account, invoked as the AccountHolder
    of that account (PRD §3.2 — AccountHolder/AgencyAdmin can register a
    vehicle).
    """
    payload = create_vehicle_payload(
        plate_number=plate_number or random_plate(),
        plate_state=plate_state,
        axle_count=axle_count,
        hov_capable=hov_capable,
    )
    payload.update(extra)
    headers = make_account_holder_headers(account_id)
    res = api_client.create_vehicle(account_id, payload, headers)
    return get_success_data(res)


def create_transponder(account_id: str,
                       serial_number: Optional[str] = None,
                       **extra: Any) -> Dict[str, Any]:
    """Register a transponder on the account."""
    payload = create_transponder_payload(
        serial_number=serial_number or random_serial(),
    )
    payload.update(extra)
    headers = make_account_holder_headers(account_id)
    res = api_client.create_transponder(account_id, payload, headers)
    return get_success_data(res)


def bind_transponder_to_vehicle(account_id: str,
                                transponder_id: str,
                                vehicle_id: str) -> Dict[str, Any]:
    """Bind the transponder to the vehicle as the AccountHolder of the
    account (ownership-gated by PRD §3.2)."""
    headers = make_account_holder_headers(account_id)
    res = api_client.bind_transponder(
        account_id, transponder_id,
        bind_transponder_payload(vehicle_id=vehicle_id),
        headers,
    )
    return get_success_data(res)


def create_and_bind_transponder(account_id: str,
                                vehicle_id: str,
                                serial_number: Optional[str] = None) -> Dict[str, Any]:
    """Create transponder + bind in one step. Returns the bound transponder."""
    t = create_transponder(account_id, serial_number=serial_number)
    return bind_transponder_to_vehicle(account_id, t["id"], vehicle_id)


# ---------------------------------------------------------------------------
# Tier 2: Combined account+vehicle setups
# ---------------------------------------------------------------------------
def setup_account_with_vehicle(home_agency_code: str = "NY_EZPASS",
                               balance_cents: Optional[int] = None,
                               auto_reload_enabled: bool = False,
                               auto_reload_threshold_cents: Optional[int] = None,
                               auto_reload_topup_cents: Optional[int] = None,
                               axle_count: int = 2,
                               hov_capable: bool = True,
                               plate_state: str = "NY",
                               ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build an Account + one Vehicle.

    Returns (account, vehicle). Caller may add a transponder afterwards.
    """
    account = create_account(
        home_agency_code=home_agency_code,
        balance_cents=balance_cents,
        auto_reload_enabled=auto_reload_enabled,
        auto_reload_threshold_cents=auto_reload_threshold_cents,
        auto_reload_topup_cents=auto_reload_topup_cents,
    )
    vehicle = create_vehicle(
        account["id"],
        axle_count=axle_count,
        hov_capable=hov_capable,
        plate_state=plate_state,
    )
    return account, vehicle


def setup_account_with_bound_transponder(
    home_agency_code: str = "NY_EZPASS",
    balance_cents: Optional[int] = None,
    auto_reload_enabled: bool = False,
    auto_reload_threshold_cents: Optional[int] = None,
    auto_reload_topup_cents: Optional[int] = None,
    axle_count: int = 2,
    hov_capable: bool = True,
    plate_state: str = "NY",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Account + Vehicle + Transponder bound to vehicle.

    Returns (account, vehicle, transponder).
    """
    account, vehicle = setup_account_with_vehicle(
        home_agency_code=home_agency_code,
        balance_cents=balance_cents,
        auto_reload_enabled=auto_reload_enabled,
        auto_reload_threshold_cents=auto_reload_threshold_cents,
        auto_reload_topup_cents=auto_reload_topup_cents,
        axle_count=axle_count,
        hov_capable=hov_capable,
        plate_state=plate_state,
    )
    transponder = create_and_bind_transponder(account["id"], vehicle["id"])
    return account, vehicle, transponder


# ---------------------------------------------------------------------------
# Tier 3: Toll-event ingestion shortcuts
# ---------------------------------------------------------------------------
def ingest_toll_event(gantry_id: str = "G1",
                      agency_code: str = "NY_EZPASS",
                      base_rate_cents: int = 200,
                      read_at: Optional[str] = None,
                      transponder_serial: Optional[str] = None,
                      plate_number: Optional[str] = None,
                      plate_state: Optional[str] = None,
                      declared_occupants: int = 1,
                      hov_lane: bool = False,
                      ) -> Dict[str, Any]:
    """Ingest a single TollEvent as GantryOperator.

    Returns the response data for a 2xx, or raises on hard server
    failure. NOTE: HOV-fraud ingest returns 409 per PRD §3.3 — for
    that path, callers should issue the request directly with
    api_client.create_toll_event and pull the data from the error
    envelope, or use ingest_violated_toll_event below.
    """
    payload = create_toll_event_payload(
        gantry_id=gantry_id,
        agency_code=agency_code,
        base_rate_cents=base_rate_cents,
        read_at=read_at or current_clock_iso(),
        transponder_serial=transponder_serial,
        plate_number=plate_number,
        plate_state=plate_state,
        declared_occupants=declared_occupants,
        hov_lane=hov_lane,
    )
    res = api_client.create_toll_event(
        payload, TEST_USERS["gantry_operator_headers"],
    )
    return get_success_data(res)


def ingest_hov_fraud_event(account: Dict[str, Any],
                           vehicle: Dict[str, Any],
                           base_rate_cents: int = 200,
                           gantry_id: str = "G1",
                           agency_code: Optional[str] = None,
                           read_at: Optional[str] = None,
                           ) -> Dict[str, Any]:
    """Trigger PRD §3.3 HOV-fraud violation path on the given vehicle.

    The ingest returns HTTP 409 with ERR_HOV_FRAUD_RECORDED and a
    persisted Violation+Fine. Returns the parsed JSON body.
    """
    payload = create_toll_event_payload(
        gantry_id=gantry_id,
        agency_code=agency_code or account["home_agency_code"],
        base_rate_cents=base_rate_cents,
        read_at=read_at or current_clock_iso(),
        plate_number=vehicle["plate_number"],
        plate_state=vehicle["plate_state"],
        declared_occupants=1,
        hov_lane=True,
    )
    res = api_client.create_toll_event(
        payload, TEST_USERS["gantry_operator_headers"],
    )
    # PRD §3.3: HOV fraud returns 409 with ERR_HOV_FRAUD_RECORDED; the
    # Violation and Fine are nevertheless created. We parse the body
    # leniently so the fixture works whether the server returns 409 or
    # 2xx in edge implementations.
    try:
        body = res.json()
    except Exception:
        body = {}
    return body


def ingest_insufficient_funds_event(account: Dict[str, Any],
                                    vehicle: Dict[str, Any],
                                    base_rate_cents: int = 200,
                                    gantry_id: str = "G1",
                                    agency_code: Optional[str] = None,
                                    read_at: Optional[str] = None,
                                    ) -> Dict[str, Any]:
    """Trigger PRD §3.3 INSUFFICIENT_FUNDS_ON_PLATE_BILL violation path.

    Requires that account.auto_reload_enabled is false and the vehicle's
    plate is registered. The post returns 409 with ERR_INSUFFICIENT_FUNDS
    _ON_PLATE_BILL but persists the Violation+Fine.
    """
    payload = create_toll_event_payload(
        gantry_id=gantry_id,
        agency_code=agency_code or account["home_agency_code"],
        base_rate_cents=base_rate_cents,
        read_at=read_at or current_clock_iso(),
        plate_number=vehicle["plate_number"],
        plate_state=vehicle["plate_state"],
    )
    res = api_client.create_toll_event(
        payload, TEST_USERS["gantry_operator_headers"],
    )
    try:
        body = res.json()
    except Exception:
        body = {}
    return body


# ---------------------------------------------------------------------------
# Tier 4: Finding violation / fine for a toll event
# ---------------------------------------------------------------------------
def find_fine_for_account(account_id: str) -> Optional[Dict[str, Any]]:
    """List fines filtered by account_id and return the first one."""
    headers = make_account_holder_headers(account_id)
    res = api_client.list_fines(headers, params={"account_id": account_id})
    body = get_success_data(res) if 200 <= res.status_code < 300 else None
    # /fines is a list; both validate_paginated and list shape allowed.
    if isinstance(body, list):
        return body[0] if body else None
    if isinstance(body, dict) and "items" in body:
        items = body["items"]
        return items[0] if items else None
    # Fallback — pull the response data directly.
    try:
        parsed = res.json().get("data")
        if isinstance(parsed, list):
            return parsed[0] if parsed else None
    except Exception:
        pass
    return None


def list_fines_for_account(account_id: str) -> List[Dict[str, Any]]:
    """List all fines for the account."""
    headers = make_account_holder_headers(account_id)
    res = api_client.list_fines(headers, params={"account_id": account_id})
    if 200 <= res.status_code < 300:
        try:
            data = res.json().get("data") or []
            return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


def get_fine(fine_id: str, account_id: str) -> Dict[str, Any]:
    headers = make_account_holder_headers(account_id)
    res = api_client.get_fine(fine_id, headers)
    return get_success_data(res)


def get_account(account_id: str) -> Dict[str, Any]:
    """Re-fetch an account. AgencyAdmin headers used so the call is
    never blocked by ownership concerns."""
    res = api_client.get_account(
        account_id, TEST_USERS["agency_admin_headers"],
    )
    return get_success_data(res)


def get_vehicle(account_id: str, vehicle_id: str) -> Dict[str, Any]:
    headers = make_account_holder_headers(account_id)
    res = api_client.get_vehicle(account_id, vehicle_id, headers)
    return get_success_data(res)


def get_transponder_via_list(account_id: str,
                             transponder_id: str) -> Optional[Dict[str, Any]]:
    """No GET endpoint exists for a single transponder in PRD §4 — but
    listing endpoints exist for vehicles/reloads. For tests that need
    to inspect transponder state, callers should consult attribution
    paths or rely on the bind/unbind responses. This helper exists as
    a placeholder."""
    return None


def get_toll_event(toll_event_id: str) -> Dict[str, Any]:
    res = api_client.get_toll_event(
        toll_event_id, TEST_USERS["agency_admin_headers"],
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 5: HOV-fraud accumulation fixture — drives Account.outstanding
# above the suspension threshold (PRD §3.5 = 15000 cents).
#
# Used by the difficulty-design instances that need a SUSPENDED account
# without time-skewing the clock.
# ---------------------------------------------------------------------------
def setup_suspended_account_via_two_hov_frauds(
    home_agency_code: str = "NY_EZPASS",
    base_rate_cents: int = 200,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    """Build an account suspended by accumulating two HOV-fraud fines.

    Each HOV-fraud Fine has amount_cents = toll_component + 10000 base.
    With base_rate=200 and CLASS_2 + same-agency + plate-bill 15%
    surcharge: gross=200, interop=0, plate_surcharge=30 -> toll_comp=230;
    each fine = 230 + 10000 = 10230. Two of them = 20460 > 15000 = the
    suspension threshold, so Account.status flips to SUSPENDED.

    Returns (account, fraud_vehicles, target_vehicle, transponders).
    The `target_vehicle` is a separate ACTIVE-at-time-of-creation
    vehicle the caller can act on (e.g., for the bind-while-suspended
    test); but it will be cascaded to BLOCKED when the suspension
    fires. The optional transponder is bound to target_vehicle while
    Account is still ACTIVE — at the suspension cascade it flips to
    SUSPENDED.
    """
    account = create_account(
        home_agency_code=home_agency_code,
        balance_cents=0,
        auto_reload_enabled=False,
    )
    target_vehicle = create_vehicle(
        account["id"], plate_number=random_plate(),
        plate_state="NY", axle_count=2, hov_capable=True,
    )
    fraud_vehicle1 = create_vehicle(
        account["id"], plate_number=random_plate(),
        plate_state="NY", axle_count=2, hov_capable=True,
    )
    fraud_vehicle2 = create_vehicle(
        account["id"], plate_number=random_plate(),
        plate_state="NY", axle_count=2, hov_capable=True,
    )

    # Two HOV_FRAUD ingests to push outstanding above 15000.
    ingest_hov_fraud_event(
        account, fraud_vehicle1,
        base_rate_cents=base_rate_cents,
        agency_code=home_agency_code,
    )
    ingest_hov_fraud_event(
        account, fraud_vehicle2,
        base_rate_cents=base_rate_cents,
        agency_code=home_agency_code,
    )

    # Re-fetch the account so we get post-cascade status.
    account = get_account(account["id"])
    return account, [fraud_vehicle1, fraud_vehicle2], target_vehicle, []


# ---------------------------------------------------------------------------
# Tier 6: Posted-then-void invariant fixture (PRD §3.3, §2.8)
# ---------------------------------------------------------------------------
def setup_posted_toll_event(home_agency_code: str = "NY_EZPASS",
                            balance_cents: int = 10000,
                            base_rate_cents: int = 347,
                            auto_reload_enabled: bool = False,
                            ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create an account + bound transponder + ingest a TRANSPONDER toll
    event. Returns (account, vehicle, toll_event).

    With balance high enough that the post-debit balance stays above
    the auto-reload threshold (or auto_reload off), the event lands
    POSTED. Caller can then void within 24h to test refund invariants.
    """
    account, vehicle, transponder = setup_account_with_bound_transponder(
        home_agency_code=home_agency_code,
        balance_cents=balance_cents,
        auto_reload_enabled=auto_reload_enabled,
        # threshold default 1000; with balance_cents=10000 and small
        # base rates, post-debit stays comfortably above threshold.
    )
    event = ingest_toll_event(
        gantry_id="G1",
        agency_code=home_agency_code,
        base_rate_cents=base_rate_cents,
        transponder_serial=transponder["serial_number"],
    )
    return account, vehicle, event


# ---------------------------------------------------------------------------
# Tier 7: Dispute cycle helpers (PRD §3.6)
# ---------------------------------------------------------------------------
def open_dispute(account_id: str, fine_id: str,
                 reason: str = "I dispute this") -> Dict[str, Any]:
    headers = make_account_holder_headers(account_id)
    res = api_client.dispute_fine(
        fine_id, dispute_fine_payload(reason=reason), headers,
    )
    return get_success_data(res)


def reject_dispute(fine_id: str) -> Dict[str, Any]:
    res = api_client.reject_dispute(
        fine_id, TEST_USERS["agency_admin_headers"],
    )
    return get_success_data(res)


def uphold_dispute(fine_id: str) -> Dict[str, Any]:
    res = api_client.uphold_dispute(
        fine_id, TEST_USERS["agency_admin_headers"],
    )
    return get_success_data(res)


def pay_fine(account_id: str, fine_id: str,
             payment_method_token: str = "pmt_test_token_001") -> Dict[str, Any]:
    headers = make_account_holder_headers(account_id)
    res = api_client.pay_fine(
        fine_id, pay_fine_payload(payment_method_token=payment_method_token),
        headers,
    )
    return get_success_data(res)


__all__ = [
    # clock
    "reset_clock_tracker_to",
    "current_clock",
    "current_clock_iso",
    "advance_clock_to",
    "advance_clock_by_days",
    "advance_clock_by_seconds",
    "run_overdue_sweep",
    # single-entity helpers
    "create_account",
    "create_vehicle",
    "create_transponder",
    "bind_transponder_to_vehicle",
    "create_and_bind_transponder",
    # combined setups
    "setup_account_with_vehicle",
    "setup_account_with_bound_transponder",
    # toll-event helpers
    "ingest_toll_event",
    "ingest_hov_fraud_event",
    "ingest_insufficient_funds_event",
    # readers
    "find_fine_for_account",
    "list_fines_for_account",
    "get_fine",
    "get_account",
    "get_vehicle",
    "get_toll_event",
    "get_transponder_via_list",
    # higher-tier scenarios
    "setup_suspended_account_via_two_hov_frauds",
    "setup_posted_toll_event",
    # dispute helpers
    "open_dispute",
    "reject_dispute",
    "uphold_dispute",
    "pay_fine",
]
