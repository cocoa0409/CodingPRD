"""
Composite setup helpers for shared power bank tests.

Every fixture that creates an entity-backed ``User`` or ``LocationPartner``
threads the resulting entity's ``id`` into ``make_user_headers`` /
``make_partner_headers`` whenever the next call exercises an ownership-gated
PRD rule (PRD §2.1). Falling back to a shared-constant header for those
calls would force the implementation to drop the PRD-required ownership
check in order to satisfy the test — that is a fixture bug, not an
implementation bug.

All setup calls go through ``get_success_data`` (lenient) rather than
``validate_success`` (strict envelope assert) so that a setup failure produces
a clear "setup failed" trace rather than a confusing assertion failure inside
a test that has not yet run its own logic.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_PRICING,
    LOST_DEVICE_FEE,
    MIN_DEPOSIT,
)
from .factories import (
    amount_payload,
    auto_assign_payload,
    clock_advance_to,
    create_cabinet_payload,
    create_device_payload,
    create_location_partner_payload,
    create_maintenance_window_payload,
    create_pricing_plan_payload,
    create_rental_payload,
    create_settlement_payload,
    create_user_payload,
    heartbeat_payload,
    return_payload,
    sweep_payload,
)
from .test_users import (
    ADMIN_HEADERS,
    OPERATOR_HEADERS,
    make_partner_headers,
    make_user_headers,
)


# ---------------------------------------------------------------------------
# Tier 0 — clock helpers (PRD §3.9 mentions /_clock/advance is unauthenticated)
# ---------------------------------------------------------------------------


def advance_clock_to(timestamp: str) -> None:
    """Advance the logical clock to the given ISO timestamp."""
    res = api_client.advance_clock(clock_advance_to(timestamp))
    get_success_data(res)


def advance_clock_seconds(seconds: int) -> None:
    res = api_client.advance_clock({"seconds": seconds})
    get_success_data(res)


def heartbeat(cabinet_id: str, timestamp: str) -> Dict[str, Any]:
    res = api_client.heartbeat_cabinet(
        cabinet_id, heartbeat_payload(timestamp), ADMIN_HEADERS
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 1 — single-entity creation helpers (state = creation default)
# ---------------------------------------------------------------------------


def create_pricing_plan(**overrides: Any) -> Dict[str, Any]:
    res = api_client.create_pricing_plan(
        create_pricing_plan_payload(**overrides), ADMIN_HEADERS
    )
    return get_success_data(res)


def create_location_partner(**overrides: Any) -> Dict[str, Any]:
    res = api_client.create_location_partner(
        create_location_partner_payload(**overrides), ADMIN_HEADERS
    )
    return get_success_data(res)


def create_cabinet(
    location_partner_id: str, **overrides: Any
) -> Dict[str, Any]:
    res = api_client.create_cabinet(
        create_cabinet_payload(location_partner_id, **overrides), ADMIN_HEADERS
    )
    return get_success_data(res)


def create_device(
    cabinet_id: str, slot_index: int, **overrides: Any
) -> Dict[str, Any]:
    res = api_client.create_device(
        create_device_payload(cabinet_id, slot_index, **overrides),
        ADMIN_HEADERS,
    )
    return get_success_data(res)


def create_user(**overrides: Any) -> Dict[str, Any]:
    res = api_client.create_user(create_user_payload(**overrides), ADMIN_HEADERS)
    return get_success_data(res)


def topup_wallet(user_id: str, amount: float) -> Dict[str, Any]:
    """User self-tops-up wallet — PRD §3.3 says this is a User-role endpoint,
    so we MUST use the per-user header (ownership-gated by virtue of role)."""
    res = api_client.topup_wallet(
        user_id, amount_payload(amount), make_user_headers(user_id)
    )
    return get_success_data(res)


def deposit(user_id: str, amount: float) -> Dict[str, Any]:
    res = api_client.deposit(
        user_id, amount_payload(amount), make_user_headers(user_id)
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 2 — composite "ready-to-borrow" environments
# ---------------------------------------------------------------------------


def setup_pricing_plans(cities: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    """Create one PricingPlan per supplied city (defaults to BJ only).

    Returns a dict keyed by city_code.
    """
    if cities is None:
        cities = ["BJ"]
    plans: Dict[str, Dict[str, Any]] = {}
    for city in cities:
        plan_defaults = DEFAULT_PRICING.get(city, DEFAULT_PRICING["BJ"]).copy()
        plan_defaults["city_code"] = city
        plans[city] = create_pricing_plan(**plan_defaults)
    return plans


def setup_funded_user(
    deposit_amount: float = MIN_DEPOSIT,
    wallet_amount: float = 100.00,
) -> Dict[str, Any]:
    """Create a User and fund both deposit + wallet so they may borrow.

    Identity is threaded via ``make_user_headers`` for both top-up calls
    (PRD §3.3 — wallet/deposit endpoints are User-role exclusive).
    """
    user = create_user()
    if deposit_amount > 0:
        deposit(user["id"], deposit_amount)
    if wallet_amount > 0:
        topup_wallet(user["id"], wallet_amount)
    res = api_client.get_user(user["id"], make_user_headers(user["id"]))
    return get_success_data(res)


def setup_cabinet_with_device(
    location_partner_id: Optional[str] = None,
    city_code: str = "BJ",
    model: str = "SLOT_8",
    battery_level: int = 80,
    device_slot_index: int = 0,
    heartbeat_ts: str = "2026-01-01T10:00:00Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Cabinet + LocationPartner + a single Device in slot ``device_slot_index``.

    Returns ``(partner, cabinet, device)``. Heartbeat is sent so the cabinet
    is ONLINE at clock=heartbeat_ts.
    """
    if location_partner_id is None:
        partner = create_location_partner()
    else:
        partner = {"id": location_partner_id}
    cabinet = create_cabinet(
        partner["id"], city_code=city_code, model=model
    )
    advance_clock_to(heartbeat_ts)
    heartbeat(cabinet["id"], heartbeat_ts)
    device = create_device(
        cabinet["id"], device_slot_index, battery_level=battery_level
    )
    return partner, cabinet, device


def setup_borrow_environment(
    city_code: str = "BJ",
    extra_cities: Optional[List[str]] = None,
    rented_at: str = "2026-01-01T10:00:00Z",
) -> Dict[str, Any]:
    """Single-cabinet environment a User can borrow from.

    Returns a dict containing: partner, cabinet, device, user, plans, clock.
    Clock is advanced to ``rented_at`` and a fresh heartbeat is sent.
    """
    cities = [city_code] + (extra_cities or [])
    plans = setup_pricing_plans(cities)
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code=city_code)
    advance_clock_to(rented_at)
    heartbeat(cabinet["id"], rented_at)
    device = create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    return {
        "partner": partner,
        "cabinet": cabinet,
        "device": device,
        "user": user,
        "plans": plans,
        "clock": rented_at,
    }


# ---------------------------------------------------------------------------
# Tier 3 — full lifecycle shortcuts (borrow / return / refund chains)
# ---------------------------------------------------------------------------


def borrow_for(user: Dict[str, Any], cabinet_id: str) -> Dict[str, Any]:
    """Issue POST /rentals as the supplied user. Identity-threaded."""
    res = api_client.create_rental(
        create_rental_payload(cabinet_id), make_user_headers(user["id"])
    )
    return get_success_data(res)


def return_for(
    user: Dict[str, Any], rental_id: str, return_cabinet_id: str
) -> Dict[str, Any]:
    res = api_client.return_rental(
        rental_id, return_payload(return_cabinet_id), make_user_headers(user["id"])
    )
    return get_success_data(res)


def borrow_return_cycle(
    rented_at: str = "2026-01-01T10:00:00Z",
    returned_at: str = "2026-01-01T11:00:00Z",
    city_code: str = "BJ",
) -> Dict[str, Any]:
    """Full ACTIVE → RETURNED cycle on a single cabinet, single user.

    Returns a dict with the same keys as ``setup_borrow_environment`` plus
    ``rental`` (post-return).
    """
    env = setup_borrow_environment(city_code=city_code, rented_at=rented_at)
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    advance_clock_to(returned_at)
    heartbeat(env["cabinet"]["id"], returned_at)
    final = return_for(env["user"], rental["id"], env["cabinet"]["id"])
    env["rental"] = final
    return env


def borrow_and_overdue(
    rented_at: str = "2026-01-01T00:00:00Z",
    overdue_at: str = "2026-01-02T01:00:00Z",
    city_code: str = "BJ",
) -> Dict[str, Any]:
    """Borrow then run overdue sweep so rental_status flips to OVERDUE.

    Returns env dict with ``rental`` post-sweep.
    """
    env = setup_borrow_environment(city_code=city_code, rented_at=rented_at)
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    advance_clock_to(overdue_at)
    heartbeat(env["cabinet"]["id"], overdue_at)
    get_success_data(api_client.run_sweep(sweep_payload("overdue")))
    rental_after = get_success_data(
        api_client.get_rental(rental["id"], make_user_headers(env["user"]["id"]))
    )
    env["rental"] = rental_after
    return env


def borrow_and_lost(
    rented_at: str = "2026-01-01T00:00:00Z",
    overdue_at: str = "2026-01-02T01:00:00Z",
    lost_at: str = "2026-01-08T00:00:00Z",
    city_code: str = "BJ",
) -> Dict[str, Any]:
    """Borrow → overdue sweep → lost sweep. Returns env with terminal rental."""
    env = borrow_and_overdue(
        rented_at=rented_at, overdue_at=overdue_at, city_code=city_code
    )
    advance_clock_to(lost_at)
    heartbeat(env["cabinet"]["id"], lost_at)
    get_success_data(api_client.run_sweep(sweep_payload("lost")))
    rental_after = get_success_data(
        api_client.get_rental(
            env["rental"]["id"], make_user_headers(env["user"]["id"])
        )
    )
    env["rental"] = rental_after
    return env


def borrow_return_refund(
    rented_at: str = "2026-01-01T10:00:00Z",
    returned_at: str = "2026-01-01T11:00:00Z",
) -> Dict[str, Any]:
    """ACTIVE → RETURNED → REFUNDED cycle. Returns env with rental REFUNDED."""
    env = borrow_return_cycle(rented_at=rented_at, returned_at=returned_at)
    refunded = get_success_data(
        api_client.refund_rental(env["rental"]["id"], ADMIN_HEADERS)
    )
    env["rental"] = refunded
    return env


# ---------------------------------------------------------------------------
# Tier 4 — counter accumulation (refund_count_30d / borrow_count_24h)
# ---------------------------------------------------------------------------


def setup_user_with_refund_count(
    target_refund_count: int,
    base_clock: str = "2026-01-01T00:00:00Z",
) -> Dict[str, Any]:
    """Create a user whose refund_count_30d == target_refund_count.

    Each refund cycle: borrow → wait 1h → return → refund. Each cycle bumps
    refund_count_30d by 1 and borrow_count_24h by 1; we then advance the
    clock past 24h between cycles so borrow_count_24h drops back to 0
    before the next borrow (PRD §3.7 says counters are trailing-window).
    """
    plans = setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    # Use a 24-slot cabinet so we have room for many sequential rentals.
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_24")
    advance_clock_to(base_clock)
    heartbeat(cabinet["id"], base_clock)
    # Pre-populate slots with healthy devices.
    devices: List[Dict[str, Any]] = []
    for idx in range(min(24, target_refund_count + 1)):
        devices.append(
            create_device(
                cabinet["id"], idx, battery_level=80
            )
        )
    user = setup_funded_user(deposit_amount=99.00, wallet_amount=10_000.00)

    cur_clock = base_clock
    for cycle in range(target_refund_count):
        # Cycle starts at cur_clock, advance 1h for return, then 25h for next borrow.
        cur_dt_h = _iso_add_hours(cur_clock, 0)
        heartbeat(cabinet["id"], cur_dt_h)
        rental = borrow_for(user, cabinet["id"])
        ret_clock = _iso_add_hours(cur_clock, 1)
        advance_clock_to(ret_clock)
        heartbeat(cabinet["id"], ret_clock)
        return_for(user, rental["id"], cabinet["id"])
        get_success_data(api_client.refund_rental(rental["id"], ADMIN_HEADERS))
        # Skip 25 hours so borrow_count_24h drops back to 0 by next iteration.
        cur_clock = _iso_add_hours(cur_clock, 26)
        advance_clock_to(cur_clock)
        heartbeat(cabinet["id"], cur_clock)

    final_user = get_success_data(
        api_client.get_user(user["id"], make_user_headers(user["id"]))
    )
    return {
        "partner": partner,
        "cabinet": cabinet,
        "user": final_user,
        "plans": plans,
        "clock": cur_clock,
        "devices": devices,
    }


def setup_user_with_borrow_count(
    target_borrow_count: int,
    base_clock: str = "2026-01-01T00:00:00Z",
) -> Dict[str, Any]:
    """Create a user with exactly ``target_borrow_count`` borrows in trailing 24h.

    Each iteration: borrow → return ~1m later → keep clock inside the 24h
    window (PRD §3.7 says borrow_count_24h is the trailing 24-hour count).
    """
    plans = setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_24")
    advance_clock_to(base_clock)
    heartbeat(cabinet["id"], base_clock)
    devices: List[Dict[str, Any]] = []
    for idx in range(min(24, target_borrow_count + 1)):
        devices.append(create_device(cabinet["id"], idx, battery_level=80))
    user = setup_funded_user(deposit_amount=99.00, wallet_amount=10_000.00)

    cur_clock = base_clock
    for cycle in range(target_borrow_count):
        heartbeat(cabinet["id"], cur_clock)
        rental = borrow_for(user, cabinet["id"])
        cur_clock = _iso_add_minutes(cur_clock, 1)
        advance_clock_to(cur_clock)
        heartbeat(cabinet["id"], cur_clock)
        return_for(user, rental["id"], cabinet["id"])
        cur_clock = _iso_add_minutes(cur_clock, 1)
        advance_clock_to(cur_clock)
        heartbeat(cabinet["id"], cur_clock)

    final_user = get_success_data(
        api_client.get_user(user["id"], make_user_headers(user["id"]))
    )
    return {
        "partner": partner,
        "cabinet": cabinet,
        "user": final_user,
        "plans": plans,
        "clock": cur_clock,
        "devices": devices,
    }


# ---------------------------------------------------------------------------
# Tier 5 — multi-rental settlement universes
# ---------------------------------------------------------------------------


def setup_settlement_universe(
    n_users: int = 3,
    revenue_share_pct: float = 0.335,
    rental_hours: float = 1.0,
    base_clock: str = "2026-01-01T10:00:00Z",
) -> Dict[str, Any]:
    """Create a partner-period universe of N completed rentals.

    All rentals start and return on the same cabinet (single city, no
    cross-city surcharge), each with the same 1-hour duration so each
    rental's ``charged_amount`` is equal. Returns dict with partner,
    cabinet, users, rentals, plans, clock.
    """
    plans = setup_pricing_plans(["BJ"])
    partner = create_location_partner(revenue_share_pct=revenue_share_pct)
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_24")
    advance_clock_to(base_clock)
    heartbeat(cabinet["id"], base_clock)
    devices: List[Dict[str, Any]] = []
    for idx in range(n_users):
        devices.append(create_device(cabinet["id"], idx, battery_level=80 - idx))
    users: List[Dict[str, Any]] = []
    rentals: List[Dict[str, Any]] = []
    cur_clock = base_clock
    for i in range(n_users):
        u = setup_funded_user()
        users.append(u)
        heartbeat(cabinet["id"], cur_clock)
        r = borrow_for(u, cabinet["id"])
        ret_clock = _iso_add_hours(cur_clock, rental_hours)
        advance_clock_to(ret_clock)
        heartbeat(cabinet["id"], ret_clock)
        r_final = return_for(u, r["id"], cabinet["id"])
        rentals.append(r_final)
        cur_clock = _iso_add_minutes(ret_clock, 1)
        advance_clock_to(cur_clock)
    return {
        "partner": partner,
        "cabinet": cabinet,
        "users": users,
        "rentals": rentals,
        "plans": plans,
        "clock": cur_clock,
        "devices": devices,
    }


# ---------------------------------------------------------------------------
# Tier 6 — anomaly-cascade fixtures (sweep → ticket → device → slot → task)
# ---------------------------------------------------------------------------


def trigger_anomaly_cascade(
    base_clock: str = "2026-01-01T10:00:00Z",
    battery_level: int = 4,
) -> Dict[str, Any]:
    """Plant a low-battery device in an OCCUPIED slot, run the anomaly sweep,
    and return the resulting cascade entities.

    PRD §3.6: anomaly sweep targets ``status==AVAILABLE``,
    ``battery_level < 5``, slot ``OCCUPIED`` devices.

    Returns dict: partner, cabinet, device (post-cascade FAULTY), slot, ticket,
    operator_task, plans, clock.
    """
    plans = setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to(base_clock)
    heartbeat(cabinet["id"], base_clock)
    device = create_device(
        cabinet["id"], 0, battery_level=battery_level
    )
    # Run the anomaly sweep — this should create a ticket and cascade.
    get_success_data(api_client.run_sweep(sweep_payload("anomaly")))
    return {
        "partner": partner,
        "cabinet": cabinet,
        "device": device,
        "plans": plans,
        "clock": base_clock,
    }


# ---------------------------------------------------------------------------
# Tier 7 — return-failure / stuck rental
# ---------------------------------------------------------------------------


def setup_stuck_rental(
    rented_at: str = "2026-01-01T10:00:00Z",
    return_at: str = "2026-01-01T11:00:00Z",
) -> Dict[str, Any]:
    """Build a STUCK rental by returning at a cabinet whose only slot is FAULTY.

    Approach: build cabinet C2 with ONE slot (SLOT_8 has 8; we occupy them all
    by registering 8 devices). Then user borrows from C1, advances clock,
    attempts return at C2 — the eligible-empty-slot set is empty → return-
    failure. Returns dict with rental in STUCK + the attempted-return slot's
    state.
    """
    plans = setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet1 = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    cabinet2 = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to(rented_at)
    heartbeat(cabinet1["id"], rented_at)
    heartbeat(cabinet2["id"], rented_at)
    # Borrow from C1 — one device.
    create_device(cabinet1["id"], 0, battery_level=80)
    # Fill C2 entirely so its slots are all OCCUPIED.
    for idx in range(8):
        create_device(cabinet2["id"], idx, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet1["id"])
    advance_clock_to(return_at)
    heartbeat(cabinet1["id"], return_at)
    heartbeat(cabinet2["id"], return_at)
    # Attempt return at C2 — all slots OCCUPIED, expect ERR_RETURN_FAILED + STUCK.
    api_client.return_rental(
        rental["id"],
        return_payload(cabinet2["id"]),
        make_user_headers(user["id"]),
    )
    rental_after = get_success_data(
        api_client.get_rental(rental["id"], make_user_headers(user["id"]))
    )
    return {
        "partner": partner,
        "cabinet1": cabinet1,
        "cabinet2": cabinet2,
        "user": user,
        "rental": rental_after,
        "plans": plans,
        "clock": return_at,
    }


# ---------------------------------------------------------------------------
# Date helpers (no external deps)
# ---------------------------------------------------------------------------


def _iso_add_hours(iso: str, hours: float) -> str:
    """Add ``hours`` to an ISO 8601 UTC timestamp ending in 'Z'."""
    from datetime import datetime, timedelta, timezone

    # Accept both '...Z' and '...+00:00' shapes.
    base = iso.replace("Z", "+00:00")
    dt = datetime.fromisoformat(base).astimezone(timezone.utc)
    new = dt + timedelta(hours=hours)
    return new.strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_add_minutes(iso: str, minutes: float) -> str:
    return _iso_add_hours(iso, minutes / 60.0)


def iso_add_hours(iso: str, hours: float) -> str:
    return _iso_add_hours(iso, hours)


def iso_add_minutes(iso: str, minutes: float) -> str:
    return _iso_add_minutes(iso, minutes)


# ---------------------------------------------------------------------------
# Tier 8 — settlement creation shortcut
# ---------------------------------------------------------------------------


def create_settlement_for(
    location_partner_id: str,
    period_start: str,
    period_end: str,
) -> Dict[str, Any]:
    res = api_client.create_settlement(
        create_settlement_payload(
            location_partner_id, period_start, period_end
        ),
        ADMIN_HEADERS,
    )
    return get_success_data(res)


def approve_and_invoice(settlement_id: str) -> Dict[str, Any]:
    """Walk DRAFT → APPROVED → INVOICED."""
    get_success_data(api_client.approve_settlement(settlement_id, ADMIN_HEADERS))
    res = api_client.issue_invoice(settlement_id, ADMIN_HEADERS)
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 9 — maintenance window scheduling shortcut
# ---------------------------------------------------------------------------


def schedule_maintenance(
    cabinet_id: str, window_start: str, window_end: str
) -> Dict[str, Any]:
    res = api_client.create_maintenance_window(
        create_maintenance_window_payload(cabinet_id, window_start, window_end),
        ADMIN_HEADERS,
    )
    return get_success_data(res)
