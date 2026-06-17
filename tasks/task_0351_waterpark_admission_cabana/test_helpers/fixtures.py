"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: every ownership-gated Guest call uses make_guest_headers(guest_id)
with the real Guest id — never the shared TEST_USERS["guest_headers"] constant —
because a Guest's X-User-ID must equal the resource's guest_id (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_park_payload, create_pricing_policy_payload, create_entry_window_payload,
    create_cabana_payload, create_locker_payload, create_guest_payload,
    create_order_payload, assign_window_payload, bind_guest_payload,
    create_cabana_rental_payload, weather_payload, clock_payload,
)
from .test_users import TEST_USERS, make_guest_headers

PM = TEST_USERS["park_manager_headers"]
GA = TEST_USERS["gate_agent_headers"]
FC = TEST_USERS["finance_clerk_headers"]


# ─── primitive creators ────────────────────────────────────────────────

def create_park(**overrides):
    """Create a park as ParkManager. Returns the park dict."""
    return get_success_data(api_client.create_park(create_park_payload(**overrides), PM))


def set_clock(iso_instant):
    """Set the server logical clock as ParkManager. Returns ClockState."""
    return get_success_data(api_client.set_clock(clock_payload(iso_instant), PM))


def create_policy(park_id, **overrides):
    """Create/supersede an active pricing policy as ParkManager."""
    return get_success_data(
        api_client.create_pricing_policy(create_pricing_policy_payload(park_id, **overrides), PM)
    )


def create_window(park_id, **overrides):
    """Create an OPEN entry window under a park as ParkManager."""
    return get_success_data(
        api_client.create_entry_window(park_id, create_entry_window_payload(**overrides), PM)
    )


def create_cabana(park_id, **overrides):
    """Create a cabana under a park as ParkManager."""
    return get_success_data(api_client.create_cabana(park_id, create_cabana_payload(**overrides), PM))


def create_locker(park_id, **overrides):
    """Create a locker under a park as ParkManager."""
    return get_success_data(api_client.create_locker(park_id, create_locker_payload(**overrides), PM))


def create_guest(**overrides):
    """Register a guest. Returns the guest dict."""
    return get_success_data(api_client.create_guest(create_guest_payload(**overrides), TEST_USERS["guest_headers"]))


def create_order(park_id, guest_id, **overrides):
    """Create a PENDING/UNFULFILLED order owned by guest_id."""
    return get_success_data(
        api_client.create_order(create_order_payload(park_id, guest_id, **overrides),
                                make_guest_headers(guest_id))
    )


def get_window(window_id):
    """Read an entry window (as ParkManager) — used to capture its current version."""
    return get_success_data(api_client.get_entry_window(window_id, PM))


# ─── Tier 1/2: pricing-ready setup ─────────────────────────────────────

def setup_park_with_policy(product_type="DAY_TICKET", clock=None, park_overrides=None,
                           policy_overrides=None):
    """Park + active pricing policy (+ optional clock). Returns (park, guest-less).

    Returns the park dict. The most common base for pricing tests.
    """
    park = create_park(**(park_overrides or {}))
    if clock is not None:
        set_clock(clock)
    create_policy(park["id"], product_type=product_type, **(policy_overrides or {}))
    return park


def setup_paid_order(product_type="DAY_TICKET", party_size=1, clock=None,
                     park_overrides=None, policy_overrides=None, order_overrides=None,
                     guest_overrides=None):
    """Park + policy + guest + PAID order (quote already run).

    Returns (park, guest, order_after_pay).
    """
    park = create_park(**(park_overrides or {}))
    if clock is not None:
        set_clock(clock)
    create_policy(park["id"], product_type=product_type, **(policy_overrides or {}))
    guest = create_guest(**(guest_overrides or {}))
    order = create_order(park["id"], guest["id"], product_type=product_type,
                         party_size=party_size, **(order_overrides or {}))
    paid = get_success_data(api_client.pay_order(order["id"], make_guest_headers(guest["id"])))
    return park, guest, paid


# ─── Tier 3: admission lifecycle shortcuts ─────────────────────────────

def setup_confirmed_admission(product_type="DAY_TICKET", party_size=1, clock=None,
                              window_overrides=None, policy_overrides=None,
                              park_overrides=None, guest_overrides=None, order_overrides=None):
    """Full chain to ONE CONFIRMED admission assigned to an OPEN window.

    park -> [clock] -> policy -> window -> guest -> order -> pay -> fulfill ->
    fetch admission -> bind-guest -> assign-window.

    Returns dict with keys: park, guest, order, window, admission.
    The admission is CONFIRMED, guest_id bound, holding one reserved slot.
    """
    park = create_park(**(park_overrides or {}))
    if clock is not None:
        set_clock(clock)
    create_policy(park["id"], product_type=product_type, **(policy_overrides or {}))
    window = create_window(park["id"], **(window_overrides or {}))
    guest = create_guest(**(guest_overrides or {}))
    gh = make_guest_headers(guest["id"])
    order = create_order(park["id"], guest["id"], product_type=product_type,
                         party_size=party_size, **(order_overrides or {}))
    get_success_data(api_client.pay_order(order["id"], gh))
    order = get_success_data(api_client.fulfill_order(order["id"], gh))
    admissions = get_success_data(api_client.list_order_admissions(order["id"], gh))
    admission = admissions[0]
    get_success_data(api_client.bind_guest(admission["id"], bind_guest_payload(guest["id"]), gh))
    fresh_window = get_window(window["id"])
    admission = get_success_data(
        api_client.assign_window(
            admission["id"],
            assign_window_payload(window["id"], fresh_window["version"]),
            gh,
        )
    )
    window = get_window(window["id"])
    return {"park": park, "guest": guest, "order": order, "window": window, "admission": admission}


def setup_issued_admission(product_type="DAY_TICKET", party_size=1, clock=None,
                           window_overrides=None, policy_overrides=None,
                           park_overrides=None, guest_overrides=None, order_overrides=None,
                           make_window=True):
    """Full chain to a FULFILLED order with admissions still ISSUED (unassigned).

    Returns dict with keys: park, guest, order, window (or None), admissions (list).
    """
    park = create_park(**(park_overrides or {}))
    if clock is not None:
        set_clock(clock)
    create_policy(park["id"], product_type=product_type, **(policy_overrides or {}))
    window = create_window(park["id"], **(window_overrides or {})) if make_window else None
    guest = create_guest(**(guest_overrides or {}))
    gh = make_guest_headers(guest["id"])
    order = create_order(park["id"], guest["id"], product_type=product_type,
                         party_size=party_size, **(order_overrides or {}))
    get_success_data(api_client.pay_order(order["id"], gh))
    order = get_success_data(api_client.fulfill_order(order["id"], gh))
    admissions = get_success_data(api_client.list_order_admissions(order["id"], gh))
    return {"park": park, "guest": guest, "order": order, "window": window,
            "admissions": admissions}


def setup_checked_in_admission(clock="2026-07-01T10:00:00Z", height_cm=150,
                               window_overrides=None):
    """One CHECKED_IN admission. Clock is set inside the default window.

    Returns dict with keys: park, guest, order, window, admission (CHECKED_IN).
    """
    ctx = setup_confirmed_admission(
        clock=clock,
        guest_overrides={"height_cm": height_cm},
        window_overrides=window_overrides,
    )
    admission = get_success_data(api_client.check_in_admission(ctx["admission"]["id"], GA))
    ctx["admission"] = admission
    ctx["window"] = get_window(ctx["window"]["id"])
    return ctx


# ─── Tier 4: season-pass freeze setup ──────────────────────────────────

def setup_season_pass_confirmed(clock="2026-06-01T00:00:00Z", window_overrides=None):
    """A CONFIRMED SEASON_PASS admission on an OPEN long-lived window.

    Returns dict with keys: park, guest, order, window, admission (CONFIRMED season pass).
    """
    wo = window_overrides or {
        "starts_at": "2026-06-01T09:00:00Z",
        "ends_at": "2026-12-31T23:00:00Z",
        "window_capacity": 50,
    }
    return setup_confirmed_admission(
        product_type="SEASON_PASS",
        clock=clock,
        policy_overrides={"base_price_cents": 30000},
        window_overrides=wo,
    )


# ─── Tier 5: weather rain-out / rain-check setup ───────────────────────

def setup_rained_out_admission(rain_check_value_cents=4000,
                               clock="2026-07-01T08:00:00Z"):
    """A window rained out with one CONFIRMED admission -> RAINED_OUT + rain-check.

    Drives: confirmed admission -> park weather RAINED_OUT -> window rain-out.
    Returns dict with keys: park, guest, order, window, admission, rain_checks (list).
    """
    ctx = setup_confirmed_admission(
        clock=clock,
        park_overrides={"rain_check_value_cents": rain_check_value_cents},
    )
    get_success_data(api_client.set_park_weather(ctx["park"]["id"], weather_payload("RAINED_OUT"), PM))
    get_success_data(api_client.rain_out_entry_window(ctx["window"]["id"], PM))
    rain_checks = get_success_data(
        api_client.list_rain_checks(PM, params={"park_id": ctx["park"]["id"]})
    )
    ctx["window"] = get_window(ctx["window"]["id"])
    ctx["rain_checks"] = rain_checks
    return ctx


def setup_held_cabana_rental(daily_rate_cents=9000, turnover_buffer_minutes=None,
                             rental_starts="2026-07-01T10:00:00Z",
                             rental_ends="2026-07-01T14:00:00Z",
                             clock=None, window_overrides=None):
    """A PAID order with one HELD cabana rental holding one reserved slot.

    Returns dict with keys: park, guest, order, window, cabana, rental.
    """
    park = create_park()
    if clock is not None:
        set_clock(clock)
    create_policy(park["id"], product_type="DAY_TICKET")
    wo = window_overrides or {"starts_at": "2026-07-01T09:00:00Z",
                              "ends_at": "2026-07-01T20:00:00Z", "window_capacity": 50}
    window = create_window(park["id"], **wo)
    cabana_kwargs = {"daily_rate_cents": daily_rate_cents}
    if turnover_buffer_minutes is not None:
        cabana_kwargs["turnover_buffer_minutes"] = turnover_buffer_minutes
    cabana = create_cabana(park["id"], **cabana_kwargs)
    guest = create_guest()
    gh = make_guest_headers(guest["id"])
    order = create_order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=1)
    get_success_data(api_client.pay_order(order["id"], gh))
    fresh = get_window(window["id"])
    rental = get_success_data(
        api_client.create_cabana_rental(
            create_cabana_rental_payload(cabana["id"], order["id"], window["id"],
                                         rental_starts, rental_ends, fresh["version"]),
            gh,
        )
    )
    window = get_window(window["id"])
    return {"park": park, "guest": guest, "order": order, "window": window,
            "cabana": cabana, "rental": rental}
