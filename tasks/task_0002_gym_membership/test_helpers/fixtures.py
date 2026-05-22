"""Composite setup helpers for the gym membership platform.

Uses get_success_data() (lenient validator) internally so setup failures surface as
"Setup failed" errors rather than obscure assertion failures.

Identity threading is mandatory per the PRD: whenever a fixture creates a Member
or Trainer, any ownership-gated call made on behalf of that role must use
make_member_headers(<actual-id>) / make_trainer_headers(<actual-id>) — never the
shared TEST_USERS fallback. The shared fallbacks would carry an X-User-ID that
does not match any real entity id, so every ownership check would reject the call.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_booking_payload,
    create_class_session_payload,
    create_coupon_payload,
    create_equipment_pool_payload,
    create_member_payload,
    create_payment_attempt_payload,
    create_subscription_payload,
    create_trainer_payload,
    iso_utc,
)
from .test_users import (
    TEST_USERS,
    make_billing_admin_headers,
    make_member_headers,
    make_store_manager_headers,
    make_trainer_headers,
)


# ──────────────────────────────────────────────────────────
# Clock & sweep helpers (PRD §2.14)
# ──────────────────────────────────────────────────────────

def advance_clock_to(to_timestamp: str) -> str:
    """Advance the server's logical clock to *to_timestamp* (ISO 8601 UTC).

    PRD §2.14: clock-advance fires every time-gated transition that became eligible.

    Returns the server's reported "now" after the advance.
    """
    data = get_success_data(
        api_client.advance_clock(to_timestamp, TEST_USERS["billing_admin_headers"])
    )
    return data.get("now")


def server_now_iso() -> str:
    """Return the server's current logical clock as an ISO 8601 UTC string.

    Calls /_clock/advance with the current wall time — advance_to only moves
    the clock forward, so passing a stale wall time is a no-op that returns
    the current server now.
    """
    wall = iso_utc(datetime.now(timezone.utc))
    return advance_clock_to(wall)


def server_now_dt() -> datetime:
    """Return the server's current logical clock as a tz-aware datetime."""
    s = server_now_iso()
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def run_sweep() -> None:
    """Run the periodic sweep (PRD §2.14): marks unattended CONFIRMED bookings NO_SHOW
    and processes pending waitlist promotions."""
    get_success_data(api_client.run_sweep(TEST_USERS["billing_admin_headers"]))


def now_iso() -> str:
    """ISO 8601 UTC for 'now' according to the server's logical clock."""
    return server_now_iso()


def future_iso(seconds_from_now: int) -> str:
    return iso_utc(server_now_dt() + timedelta(seconds=seconds_from_now))


def minutes_from_now_iso(minutes: int) -> str:
    return iso_utc(server_now_dt() + timedelta(minutes=minutes))


def hours_from_now_iso(hours: float) -> str:
    return iso_utc(server_now_dt() + timedelta(hours=hours))


# ──────────────────────────────────────────────────────────
# Store discovery — PRD §4 lists no POST /stores, so Stores are discovered.
# ──────────────────────────────────────────────────────────

def discover_or_create_store(state_code: str = "CA") -> Dict[str, Any]:
    """Pick the first Store visible in the directory matching *state_code* (PRD §3.9).

    Implementations are free to seed Stores at boot or to expose creation outside
    the documented endpoint set. If no Store with the requested state_code exists
    we fall back to the first store returned and surface that as "Setup failed".
    """
    res = api_client.list_stores(TEST_USERS["any_headers"], params={"state_code": state_code})
    payload = res.json()
    data = payload.get("data") or []
    if not data:
        # Fallback to unfiltered listing
        res2 = api_client.list_stores(TEST_USERS["any_headers"])
        data = res2.json().get("data") or []
    assert data, (
        f"Setup failed: no Store available in directory (state_code={state_code}); "
        f"the implementation must seed at least one Store at boot per PRD §3.9."
    )
    # Prefer a store matching the requested state_code.
    for s in data:
        if s.get("state_code") == state_code:
            return s
    return data[0]


# ──────────────────────────────────────────────────────────
# Tier 1: State Progression — Member and Subscription
# ──────────────────────────────────────────────────────────

def register_member(
    *,
    state_code: str = "CA",
    home_store_id: Optional[str] = None,
    referred_by_member_id: Optional[str] = None,
    email: Optional[str] = None,
    password: str = "TestPassw0rd!",
    plan: Optional[str] = None,
    billing_cycle: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a Member via POST /members (PRD §3.1)."""
    if home_store_id is None:
        store = discover_or_create_store(state_code)
        home_store_id = store["id"]
    payload = create_member_payload(
        home_store_id=home_store_id,
        state_code=state_code,
        email=email,
        password=password,
        referred_by_member_id=referred_by_member_id,
        plan=plan,
        billing_cycle=billing_cycle,
        **overrides,
    )
    return get_success_data(api_client.create_member(payload, TEST_USERS["any_headers"]))


def create_subscription_for_member(
    member: Dict[str, Any],
    *,
    plan: str = "PLUS",
    billing_cycle: str = "MONTHLY",
    auto_renew: Optional[bool] = None,
    applied_coupon_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a Subscription owned by *member* (PRD §3.2). Uses the member's own
    headers so the ownership check on POST /members/{memberId}/subscriptions
    passes per PRD §2.1."""
    headers = make_member_headers(member["id"])
    payload = create_subscription_payload(
        plan=plan,
        billing_cycle=billing_cycle,
        auto_renew=auto_renew,
        applied_coupon_code=applied_coupon_code,
    )
    return get_success_data(api_client.create_subscription(member["id"], payload, headers))


def submit_payment_attempt(
    member: Dict[str, Any],
    subscription: Dict[str, Any],
    *,
    outcome: str = "SUCCESS",
    idempotency_key: Optional[str] = None,
    gateway_txn_id: Optional[str] = None,
    failure_reason: Optional[str] = None,
    amount_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Submit a PaymentAttempt against *subscription*. PRD §4: roles are system /
    BillingAdmin, so by default the BillingAdmin headers are used."""
    if headers is None:
        headers = TEST_USERS["billing_admin_headers"]
    payload = create_payment_attempt_payload(
        outcome=outcome,
        idempotency_key=idempotency_key,
        gateway_txn_id=gateway_txn_id,
        failure_reason=failure_reason,
        amount_cents=amount_cents,
    )
    return get_success_data(
        api_client.create_payment_attempt(member["id"], subscription["id"], payload, headers)
    )


def activate_subscription(
    member: Dict[str, Any],
    subscription: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Submit the first SUCCESS payment so subscription → ACTIVE (PRD §3.2)."""
    attempt = submit_payment_attempt(member, subscription, outcome="SUCCESS")
    refreshed_sub = get_success_data(
        api_client.get_subscription(
            member["id"], subscription["id"], make_member_headers(member["id"])
        )
    )
    return refreshed_sub, attempt


def setup_active_member_with_subscription(
    *,
    state_code: str = "CA",
    plan: str = "PLUS",
    billing_cycle: str = "MONTHLY",
    auto_renew: Optional[bool] = None,
    referred_by_member_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Full state-progression: register member → create subscription → activate.

    Returns (active_member, active_subscription) after the activation cascade.
    PRD §3.1: tier is server-set from subscription plan once a subscription activates,
    so the returned member's `tier` equals `plan`.
    """
    member = register_member(
        state_code=state_code, referred_by_member_id=referred_by_member_id
    )
    sub = create_subscription_for_member(
        member, plan=plan, billing_cycle=billing_cycle, auto_renew=auto_renew
    )
    active_sub, _attempt = activate_subscription(member, sub)
    active_member = get_success_data(
        api_client.get_member(member["id"], make_member_headers(member["id"]))
    )
    return active_member, active_sub


# ──────────────────────────────────────────────────────────
# Tier 1: Trainer / EquipmentPool / ClassSession state progression
# ──────────────────────────────────────────────────────────

def register_trainer(
    *,
    home_store_id: str,
    full_name: str = "Test Trainer",
    certifications: Optional[List[str]] = None,
    hourly_rate_cents: int = 8000,
) -> Dict[str, Any]:
    """Create a Trainer (PRD §3.5). StoreManager/BillingAdmin can do this."""
    payload = create_trainer_payload(
        home_store_id=home_store_id,
        full_name=full_name,
        certifications=certifications,
        hourly_rate_cents=hourly_rate_cents,
    )
    return get_success_data(
        api_client.create_trainer(payload, TEST_USERS["store_manager_headers"])
    )


def create_equipment_pool(
    store: Dict[str, Any],
    *,
    equipment_type: str = "SPIN_BIKE",
    total_units: int = 10,
    maintenance_window_start: Optional[str] = None,
    maintenance_window_end: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an EquipmentPool under *store* (PRD §3.5)."""
    payload = create_equipment_pool_payload(
        equipment_type=equipment_type,
        total_units=total_units,
        maintenance_window_start=maintenance_window_start,
        maintenance_window_end=maintenance_window_end,
    )
    return get_success_data(
        api_client.create_equipment_pool(
            store["id"], payload, TEST_USERS["store_manager_headers"]
        )
    )


def schedule_class_session(
    store: Dict[str, Any],
    trainer: Dict[str, Any],
    *,
    class_type: str = "YOGA",
    starts_at: Optional[str] = None,
    ends_at: Optional[str] = None,
    duration_minutes: int = 60,
    capacity: int = 10,
    minimum_tier: Optional[str] = None,
    equipment_pool_id: Optional[str] = None,
    equipment_units_required: Optional[int] = None,
    starts_in_hours: float = 48.0,
) -> Dict[str, Any]:
    """Schedule a ClassSession via POST /stores/{storeId}/class-sessions (PRD §3.5).

    If starts_at/ends_at are omitted, defaults to `starts_in_hours` from the
    server's logical clock with the given duration. Using the server clock —
    not wall time — keeps the session in the future even when prior fixtures
    have advanced the clock (e.g. through delinquency cascades).
    """
    if starts_at is None:
        starts_dt = server_now_dt() + timedelta(hours=starts_in_hours)
        starts_at = iso_utc(starts_dt)
    else:
        starts_dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
    if ends_at is None:
        ends_at = iso_utc(starts_dt + timedelta(minutes=duration_minutes))

    payload = create_class_session_payload(
        class_type=class_type,
        trainer_id=trainer["id"],
        starts_at=starts_at,
        ends_at=ends_at,
        capacity=capacity,
        minimum_tier=minimum_tier,
        equipment_pool_id=equipment_pool_id,
        equipment_units_required=equipment_units_required,
    )
    return get_success_data(
        api_client.create_class_session(
            store["id"], payload, TEST_USERS["store_manager_headers"]
        )
    )


# ──────────────────────────────────────────────────────────
# Tier 2: Entity Hierarchy
# ──────────────────────────────────────────────────────────

def setup_basic_scenario(
    *,
    state_code: str = "CA",
    plan: str = "PLUS",
    class_type: str = "YOGA",
    capacity: int = 10,
    starts_in_hours: float = 48.0,
) -> Dict[str, Any]:
    """Most common seed: active member with active subscription, a store, a trainer,
    and one scheduled class session. Returns a dict {member, subscription, store,
    trainer, class_session}."""
    store = discover_or_create_store(state_code)
    trainer = register_trainer(home_store_id=store["id"])
    member, subscription = setup_active_member_with_subscription(
        state_code=state_code, plan=plan
    )
    session = schedule_class_session(
        store,
        trainer,
        class_type=class_type,
        capacity=capacity,
        starts_in_hours=starts_in_hours,
    )
    return {
        "member": member,
        "subscription": subscription,
        "store": store,
        "trainer": trainer,
        "class_session": session,
    }


def create_booking_for_member(
    member: Dict[str, Any],
    *,
    booking_kind: str = "GROUP_CLASS",
    class_session: Optional[Dict[str, Any]] = None,
    trainer: Optional[Dict[str, Any]] = None,
    starts_at: Optional[str] = None,
    ends_at: Optional[str] = None,
    applied_coupon_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a Booking on behalf of *member* using the member's own headers
    (PRD §2.1 ownership rule)."""
    headers = make_member_headers(member["id"])
    payload = create_booking_payload(
        booking_kind=booking_kind,
        class_session_id=class_session["id"] if class_session is not None else None,
        trainer_id=trainer["id"] if trainer is not None else None,
        starts_at=starts_at
        if starts_at is not None
        else (class_session["starts_at"] if class_session is not None else None),
        ends_at=ends_at
        if ends_at is not None
        else (class_session["ends_at"] if class_session is not None else None),
        applied_coupon_id=applied_coupon_id,
    )
    return get_success_data(api_client.create_booking(member["id"], payload, headers))


# ──────────────────────────────────────────────────────────
# Tier 3: Full Lifecycle Shortcuts
# ──────────────────────────────────────────────────────────

def reach_subscription_past_due(
    member: Dict[str, Any], subscription: Dict[str, Any]
) -> Dict[str, Any]:
    """Force *subscription* into PAST_DUE by advancing past current_period_end and
    submitting a FAILED first attempt of the new period (PRD §3.2)."""
    # Advance clock just past current_period_end so a new period rolls.
    period_end = subscription.get("current_period_end")
    assert period_end, "Setup failed: subscription has no current_period_end"
    period_end_dt = datetime.fromisoformat(period_end.replace("Z", "+00:00"))
    advance_clock_to(iso_utc(period_end_dt + timedelta(seconds=1)))
    # First attempt of the new period FAILS → PAST_DUE.
    submit_payment_attempt(member, subscription, outcome="FAILED")
    return get_success_data(
        api_client.get_subscription(
            member["id"], subscription["id"], make_member_headers(member["id"])
        )
    )


def reach_subscription_grace(
    member: Dict[str, Any], subscription: Dict[str, Any]
) -> Dict[str, Any]:
    """Walk a PAST_DUE subscription to GRACE by issuing two more FAILED attempts
    (RETRY_LIMIT=3 per PRD §3.2)."""
    past_due = reach_subscription_past_due(member, subscription)
    assert past_due["status"] == "PAST_DUE", (
        f"Setup failed: expected PAST_DUE, got {past_due['status']}"
    )
    submit_payment_attempt(member, subscription, outcome="FAILED")
    submit_payment_attempt(member, subscription, outcome="FAILED")
    return get_success_data(
        api_client.get_subscription(
            member["id"], subscription["id"], make_member_headers(member["id"])
        )
    )


def reach_subscription_delinquent(
    member: Dict[str, Any], subscription: Dict[str, Any]
) -> Dict[str, Any]:
    """Walk a GRACE subscription to DELINQUENT by advancing past grace_period_end
    without any SUCCESS (PRD §3.2)."""
    grace = reach_subscription_grace(member, subscription)
    assert grace["status"] == "GRACE", (
        f"Setup failed: expected GRACE, got {grace['status']}"
    )
    grace_end = grace.get("grace_period_end")
    assert grace_end, "Setup failed: grace_period_end is missing on GRACE subscription"
    grace_end_dt = datetime.fromisoformat(grace_end.replace("Z", "+00:00"))
    advance_clock_to(iso_utc(grace_end_dt + timedelta(seconds=1)))
    return get_success_data(
        api_client.get_subscription(
            member["id"], subscription["id"], make_member_headers(member["id"])
        )
    )


def cancel_class_session_admin(store: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    """Cancel a ClassSession via the StoreManager endpoint (PRD §3.5)."""
    return get_success_data(
        api_client.cancel_class_session(
            store["id"], session_id, TEST_USERS["store_manager_headers"]
        )
    )


def get_booking_fresh(member: Dict[str, Any], booking_id: str) -> Dict[str, Any]:
    """Re-fetch a booking with member-owned headers."""
    return get_success_data(
        api_client.get_booking(member["id"], booking_id, make_member_headers(member["id"]))
    )


def get_member_fresh(member_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_member(member_id, make_member_headers(member_id))
    )


def get_subscription_fresh(member_id: str, sub_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_subscription(member_id, sub_id, make_member_headers(member_id))
    )


def get_class_session_fresh(store_id: str, session_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_class_session(store_id, session_id, TEST_USERS["any_headers"])
    )


# ──────────────────────────────────────────────────────────
# Tier 4: Coupon helpers
# ──────────────────────────────────────────────────────────

def mint_coupon(
    *,
    kind: str = "PERCENT_OFF",
    value: int = 10,
    applicable_to: str = "BOTH",
    max_redemptions: int = 100,
    code: Optional[str] = None,
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a promotional Coupon (PRD §3.8). BillingAdmin only."""
    payload = create_coupon_payload(
        kind=kind,
        value=value,
        applicable_to=applicable_to,
        max_redemptions=max_redemptions,
        code=code,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    return get_success_data(
        api_client.create_coupon(payload, TEST_USERS["billing_admin_headers"])
    )


# ──────────────────────────────────────────────────────────
# Tier 5: Specialised composite scenarios for difficulty design
# ──────────────────────────────────────────────────────────

def setup_member_in_billing_state(
    state_code: str = "CA",
    *,
    target_billing_status: str = "PAST_DUE",
    plan: str = "PLUS",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive a freshly registered Member to the requested billing_status by walking
    through subscription failures. Returns (member, subscription)."""
    member, sub = setup_active_member_with_subscription(state_code=state_code, plan=plan)
    if target_billing_status == "PAST_DUE":
        sub = reach_subscription_past_due(member, sub)
    elif target_billing_status == "GRACE":
        sub = reach_subscription_grace(member, sub)
    elif target_billing_status == "DELINQUENT":
        sub = reach_subscription_delinquent(member, sub)
    elif target_billing_status in ("CURRENT", "REINSTATED"):
        # Already CURRENT after activation; REINSTATED requires PAST_DUE/GRACE then SUCCESS.
        if target_billing_status == "REINSTATED":
            sub = reach_subscription_past_due(member, sub)
            submit_payment_attempt(member, sub, outcome="SUCCESS")
            sub = get_subscription_fresh(member["id"], sub["id"])
    else:
        raise AssertionError(
            f"Unsupported target_billing_status: {target_billing_status!r}"
        )
    member = get_member_fresh(member["id"])
    return member, sub


def setup_member_with_existing_booking(
    *,
    state_code: str = "CA",
    starts_in_hours: float = 1.5,
    duration_minutes: int = 60,
    class_type: str = "YOGA",
    capacity: int = 10,
    plan: str = "PLUS",
) -> Dict[str, Any]:
    """Create a member, a session at `starts_in_hours`, and book it (status RESERVED).
    Returns {member, subscription, store, trainer, class_session, booking}."""
    scen = setup_basic_scenario(
        state_code=state_code,
        plan=plan,
        class_type=class_type,
        capacity=capacity,
        starts_in_hours=starts_in_hours,
    )
    # Lengthen the session if requested duration is different.
    if duration_minutes != 60:
        # Replace the default session with one having the requested duration.
        starts_dt = server_now_dt() + timedelta(hours=starts_in_hours)
        scen["class_session"] = schedule_class_session(
            scen["store"],
            scen["trainer"],
            class_type=class_type,
            starts_at=iso_utc(starts_dt),
            ends_at=iso_utc(starts_dt + timedelta(minutes=duration_minutes)),
            capacity=capacity,
        )
    booking = create_booking_for_member(
        scen["member"],
        booking_kind="GROUP_CLASS",
        class_session=scen["class_session"],
    )
    scen["booking"] = booking
    return scen


def setup_full_capacity_with_waitlist(
    *,
    state_code: str = "CA",
    class_type: str = "YOGA",
    capacity: int = 1,
    waitlist_count: int = 2,
    starts_in_hours: float = 48.0,
) -> Dict[str, Any]:
    """Build a ClassSession at capacity with a waitlist, used for waitlist promotion
    tests (PRD §3.6, §3.7).

    Returns {store, trainer, class_session, reserved: [member, booking], waitlist: [(member, booking)]}.
    The reserved member is the first to book (status RESERVED); each waitlist member
    is appended in FIFO order.
    """
    store = discover_or_create_store(state_code)
    trainer = register_trainer(home_store_id=store["id"])
    session = schedule_class_session(
        store,
        trainer,
        class_type=class_type,
        capacity=capacity,
        starts_in_hours=starts_in_hours,
    )

    reserved_members: List[Dict[str, Any]] = []
    reserved_bookings: List[Dict[str, Any]] = []
    for _ in range(capacity):
        m, _s = setup_active_member_with_subscription(state_code=state_code, plan="PLUS")
        b = create_booking_for_member(m, booking_kind="GROUP_CLASS", class_session=session)
        reserved_members.append(m)
        reserved_bookings.append(b)

    waitlist_pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for _ in range(waitlist_count):
        m, _s = setup_active_member_with_subscription(state_code=state_code, plan="PLUS")
        b = create_booking_for_member(m, booking_kind="GROUP_CLASS", class_session=session)
        waitlist_pairs.append((m, b))

    return {
        "store": store,
        "trainer": trainer,
        "class_session": session,
        "reserved": list(zip(reserved_members, reserved_bookings)),
        "waitlist": waitlist_pairs,
    }


def setup_equipment_pool_saturated(
    *,
    state_code: str = "CA",
    total_units: int = 2,
    starts_in_hours: float = 48.0,
    duration_minutes: int = 60,
    equipment_type: str = "SPIN_BIKE",
) -> Dict[str, Any]:
    """Build an EquipmentPool whose units are fully claimed by SCHEDULED sessions in
    an overlapping window. Returns {store, trainer, pool, sessions, starts_at, ends_at}.

    Used by the equipment-pool boundary and overlap difficulty instances.
    """
    store = discover_or_create_store(state_code)
    trainer1 = register_trainer(home_store_id=store["id"])
    pool = create_equipment_pool(
        store, equipment_type=equipment_type, total_units=total_units
    )

    starts_dt = server_now_dt() + timedelta(hours=starts_in_hours)
    starts_at = iso_utc(starts_dt)
    ends_at = iso_utc(starts_dt + timedelta(minutes=duration_minutes))

    sessions: List[Dict[str, Any]] = []
    # Create distinct trainers for each saturating session so trainer-availability
    # does not collide with equipment-availability tests.
    saturating_trainers = [trainer1]
    for _ in range(total_units - 1):
        saturating_trainers.append(register_trainer(home_store_id=store["id"]))
    for t in saturating_trainers:
        sess = schedule_class_session(
            store,
            t,
            class_type="SPIN",
            starts_at=starts_at,
            ends_at=ends_at,
            capacity=10,
            equipment_pool_id=pool["id"],
            equipment_units_required=1,
        )
        sessions.append(sess)

    return {
        "store": store,
        "trainer": trainer1,
        "pool": pool,
        "sessions": sessions,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }


def setup_trainer_with_pt_booking(
    *,
    state_code: str = "CA",
    starts_in_hours: float = 48.0,
    duration_minutes: int = 30,
    hourly_rate_cents: int = 8000,
    plan: str = "PLUS",
) -> Dict[str, Any]:
    """Trainer with one PERSONAL_TRAINING booking at [T0, T0+duration). Returns
    {store, trainer, existing_member, existing_booking, starts_at, ends_at}."""
    store = discover_or_create_store(state_code)
    trainer = register_trainer(
        home_store_id=store["id"], hourly_rate_cents=hourly_rate_cents
    )
    member, _sub = setup_active_member_with_subscription(state_code=state_code, plan=plan)
    starts_dt = server_now_dt() + timedelta(hours=starts_in_hours)
    starts_at = iso_utc(starts_dt)
    ends_at = iso_utc(starts_dt + timedelta(minutes=duration_minutes))
    booking = create_booking_for_member(
        member,
        booking_kind="PERSONAL_TRAINING",
        trainer=trainer,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    return {
        "store": store,
        "trainer": trainer,
        "existing_member": member,
        "existing_booking": booking,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }


def freeze_member_via_delinquency(
    state_code: str = "CA", plan: str = "PLUS"
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Walk a member through GRACE → DELINQUENT so access_status becomes FROZEN
    via the cascade (PRD §3.2). Returns the refreshed (member, subscription).

    This is the canonical "FROZEN" setup for posture-frozen tests.
    """
    member, sub = setup_active_member_with_subscription(state_code=state_code, plan=plan)
    sub = reach_subscription_delinquent(member, sub)
    member = get_member_fresh(member["id"])
    return member, sub


def suspend_member_voluntarily(
    member: Dict[str, Any], requested_days: Optional[int] = None
) -> Dict[str, Any]:
    """Voluntarily suspend *member* — assumes subscription is ACTIVE and no future
    bookings exist (PRD §3.4)."""
    headers = make_member_headers(member["id"])
    payload = {"requested_days": requested_days} if requested_days is not None else None
    return get_success_data(api_client.suspend_member(member["id"], payload, headers))
