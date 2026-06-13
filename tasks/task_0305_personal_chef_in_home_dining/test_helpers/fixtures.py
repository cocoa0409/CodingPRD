"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "setup failed" errors rather than confusing assertion failures.

Identity threading: every chef-owned mutation uses make_chef_headers(chef_id) and
every client-owned mutation uses make_client_headers(client_id), per PRD §2.1
(ownership compares X-User-ID against the resource's chef_id / client_id).

The test harness restarts the server (empty DB) before every test, so each fixture
builds its whole world from scratch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_chef_payload,
    create_menu_payload,
    create_travel_zone_payload,
    create_availability_block_payload,
    create_client_payload,
    create_booking_payload,
    create_payment_payload,
    create_grocery_run_payload,
    create_reschedule_request_payload,
    create_recurring_plan_payload,
)
from .test_users import make_chef_headers, make_client_headers, admin_headers


# ─── Clock ────────────────────────────────────────────────────────────────

def pin_clock(now_utc="2026-07-01T00:00:00Z"):
    """Pin the system clock (PRD §3.11). Must run before any lead-time flow."""
    get_success_data(api_client.set_clock(now_utc, admin_headers()))


# ─── Tier 1: chef catalog + activation ──────────────────────────────────────

def create_chef(chef_overrides=None):
    """Create a DRAFT chef. Returns the chef dict."""
    res = api_client.create_chef(create_chef_payload(**(chef_overrides or {})), admin_headers())
    return get_success_data(res)


def create_client(client_overrides=None):
    """Create a client. Returns the client dict."""
    res = api_client.create_client(create_client_payload(**(client_overrides or {})), admin_headers())
    return get_success_data(res)


def create_active_chef(chef_overrides=None, menu_overrides=None, zone_overrides=None):
    """Create a chef + published menu A + ZONE_A, then activate (DRAFT -> ACTIVE).

    Returns (chef, menu, zone) where chef reflects the post-activate state
    (version bumped, status ACTIVE).
    """
    chef = create_chef(chef_overrides)
    chef_id = chef["id"]
    ch = make_chef_headers(chef_id)

    menu = get_success_data(
        api_client.create_menu(create_menu_payload(chef_id, **(menu_overrides or {})), ch)
    )
    get_success_data(api_client.publish_menu(menu["id"], ch))

    zone = get_success_data(
        api_client.create_travel_zone(create_travel_zone_payload(chef_id, **(zone_overrides or {})), ch)
    )

    chef = get_success_data(api_client.activate_chef(chef_id, ch))
    return chef, menu, zone


def create_blackout(chef_id, window_start_utc, window_end_utc):
    """Create a HELD BLACKOUT block for the chef."""
    res = api_client.create_availability_block(
        create_availability_block_payload(
            chef_id, window_start_utc=window_start_utc, window_end_utc=window_end_utc
        ),
        make_chef_headers(chef_id),
    )
    return get_success_data(res)


# ─── Tier 2: REQUESTED booking on an active chef ─────────────────────────────

def create_requested_booking(chef, client, menu, booking_overrides=None):
    """Create a REQUESTED booking against an active chef. Returns the booking dict."""
    res = api_client.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], **(booking_overrides or {})),
        make_client_headers(client["id"]),
    )
    return get_success_data(res)


def setup_requested_booking(chef_overrides=None, menu_overrides=None, zone_overrides=None,
                            client_overrides=None, booking_overrides=None, pin=True):
    """Active chef (menu A + ZONE_A) + client + one REQUESTED booking.

    Returns (chef, menu, zone, client, booking). Pins the clock first by default.
    """
    if pin:
        pin_clock()
    chef, menu, zone = create_active_chef(chef_overrides, menu_overrides, zone_overrides)
    client = create_client(client_overrides)
    booking = create_requested_booking(chef, client, menu, booking_overrides)
    return chef, menu, zone, client, booking


# ─── Tier 3: CONFIRMED booking ──────────────────────────────────────────────

def confirm_booking(chef_id, booking_id, expected_chef_version):
    """Confirm a REQUESTED booking with an explicit expected_chef_version.
    Returns the confirmed booking dict."""
    res = api_client.confirm_booking(
        booking_id, {"expected_chef_version": expected_chef_version}, make_chef_headers(chef_id)
    )
    return get_success_data(res)


def setup_confirmed_booking(chef_overrides=None, menu_overrides=None, zone_overrides=None,
                            client_overrides=None, booking_overrides=None, pin=True):
    """Active chef + client + a CONFIRMED party-6 booking (default menu A).

    Returns (chef, menu, zone, client, booking) where `chef` is the post-confirm
    chef (version bumped) and `booking` is CONFIRMED with the frozen quote/deposit.
    """
    chef, menu, zone, client, booking = setup_requested_booking(
        chef_overrides, menu_overrides, zone_overrides, client_overrides, booking_overrides, pin
    )
    booking = confirm_booking(chef["id"], booking["id"], chef["version"])
    chef = get_success_data(api_client.get_chef(chef["id"], make_chef_headers(chef["id"])))
    return chef, menu, zone, client, booking


# ─── Tier 4: grocery run / payments / lifecycle shortcuts ────────────────────

def open_grocery_run(chef_id, booking_id, line_items):
    """Open an OPEN grocery run for a CONFIRMED booking. Returns the run dict."""
    res = api_client.create_grocery_run(
        create_grocery_run_payload(booking_id, line_items=line_items), make_chef_headers(chef_id)
    )
    return get_success_data(res)


def finalize_grocery_run(chef_id, grocery_run_id):
    """Finalize an OPEN grocery run. Returns the finalized run dict."""
    res = api_client.finalize_grocery_run(grocery_run_id, make_chef_headers(chef_id))
    return get_success_data(res)


def setup_confirmed_with_finalized_grocery(line_items=None, **setup_kwargs):
    """CONFIRMED booking + a FINALIZED grocery run.

    Default line_items sum to 25000 raw which, at the canonical 0.18 locked rate
    (party 6 / menu A), produce actual_grocery_total 29500 and quote 88500.
    Returns (chef, menu, zone, client, booking_after_finalize, grocery_run).
    """
    if line_items is None:
        line_items = [
            {"label": "produce", "actual_cost_cents": 10000},
            {"label": "protein", "actual_cost_cents": 10000},
            {"label": "dairy", "actual_cost_cents": 5000},
        ]
    chef, menu, zone, client, booking = setup_confirmed_booking(**setup_kwargs)
    run = open_grocery_run(chef["id"], booking["id"], line_items)
    run = finalize_grocery_run(chef["id"], run["id"])
    booking = get_success_data(api_client.get_booking(booking["id"], make_chef_headers(chef["id"])))
    return chef, menu, zone, client, booking, run


def pay_deposit(client_id, booking_id, amount_cents):
    """Make a DEPOSIT payment. Returns the payment dict."""
    res = api_client.create_payment(
        create_payment_payload(booking_id, "DEPOSIT", amount_cents), make_client_headers(client_id)
    )
    return get_success_data(res)


def pay_balance(client_id, booking_id, amount_cents):
    """Make a BALANCE payment. Returns the payment dict."""
    res = api_client.create_payment(
        create_payment_payload(booking_id, "BALANCE", amount_cents), make_client_headers(client_id)
    )
    return get_success_data(res)


def setup_confirmed_with_deposit_paid(deposit_cents=26196, **setup_kwargs):
    """CONFIRMED party-6 booking with the deposit paid (default 26196).

    Returns (chef, menu, zone, client, booking_after_deposit, payment).
    """
    chef, menu, zone, client, booking = setup_confirmed_booking(**setup_kwargs)
    payment = pay_deposit(client["id"], booking["id"], deposit_cents)
    booking = get_success_data(api_client.get_booking(booking["id"], make_client_headers(client["id"])))
    return chef, menu, zone, client, booking, payment


def setup_in_prep_booking(deposit_cents=26196, grocery_line_items=None, **setup_kwargs):
    """CONFIRMED -> deposit paid -> grocery finalized -> start-prep (IN_PREP), balance unpaid.

    Default grocery lines sum to 24000 raw which, at menu-A 0.18 rate (party 6),
    yield actual_grocery_total 28320 and quote 87320 (balance 61124 after deposit).
    Returns (chef, menu, zone, client, booking, grocery_run).
    """
    if grocery_line_items is None:
        grocery_line_items = [
            {"label": "a", "actual_cost_cents": 8001},
            {"label": "b", "actual_cost_cents": 8001},
            {"label": "c", "actual_cost_cents": 7998},
        ]
    chef, menu, zone, client, booking = setup_confirmed_booking(**setup_kwargs)
    pay_deposit(client["id"], booking["id"], deposit_cents)
    run = open_grocery_run(chef["id"], booking["id"], grocery_line_items)
    run = finalize_grocery_run(chef["id"], run["id"])
    get_success_data(api_client.start_prep_booking(booking["id"], make_chef_headers(chef["id"])))
    booking = get_success_data(api_client.get_booking(booking["id"], make_chef_headers(chef["id"])))
    return chef, menu, zone, client, booking, run


def setup_completed_booking(deposit_cents=26196, balance_cents=61124, grocery_line_items=None,
                            **setup_kwargs):
    """Full lifecycle through COMPLETED (deposit + grocery + balance + start-prep + complete).

    Default grocery lines sum to 24000 raw -> actual_grocery 28320 -> quote 87320 ->
    balance after 26196 deposit = 61124.
    Returns (chef, menu, zone, client, booking).
    """
    if grocery_line_items is None:
        grocery_line_items = [
            {"label": "a", "actual_cost_cents": 8001},
            {"label": "b", "actual_cost_cents": 8001},
            {"label": "c", "actual_cost_cents": 7998},
        ]
    chef, menu, zone, client, booking = setup_confirmed_booking(**setup_kwargs)
    pay_deposit(client["id"], booking["id"], deposit_cents)
    run = open_grocery_run(chef["id"], booking["id"], grocery_line_items)
    finalize_grocery_run(chef["id"], run["id"])
    pay_balance(client["id"], booking["id"], balance_cents)
    get_success_data(api_client.start_prep_booking(booking["id"], make_chef_headers(chef["id"])))
    get_success_data(api_client.complete_booking(booking["id"], make_chef_headers(chef["id"])))
    booking = get_success_data(api_client.get_booking(booking["id"], make_chef_headers(chef["id"])))
    return chef, menu, zone, client, booking


# ─── Tier 5: recurring plans / reschedule ────────────────────────────────────

def setup_recurring_plan(chef_overrides=None, menu_overrides=None, client_overrides=None,
                         plan_overrides=None, publish_menu=True, with_zone=True, pin=True):
    """Active (or basic) chef + client + an ACTIVE recurring plan.

    Returns (chef, menu, client, plan). Plan creation does not require the chef to be
    active, so callers may skip publish/zone if they only need plan-axis behaviour.
    """
    if pin:
        pin_clock()
    chef = create_chef(chef_overrides)
    ch = make_chef_headers(chef["id"])
    menu = get_success_data(
        api_client.create_menu(
            create_menu_payload(
                chef["id"],
                base_price_per_guest_cents=7000,
                estimated_ingredient_per_guest_cents=3000,
                max_party_size=8,
                **(menu_overrides or {}),
            ),
            ch,
        )
    )
    if publish_menu:
        get_success_data(api_client.publish_menu(menu["id"], ch))
    if with_zone:
        get_success_data(api_client.create_travel_zone(
            create_travel_zone_payload(chef["id"], travel_fee_cents=4000), ch))
        chef = get_success_data(api_client.activate_chef(chef["id"], ch))
    client = create_client(client_overrides)
    plan = get_success_data(
        api_client.create_recurring_plan(
            create_recurring_plan_payload(chef["id"], client["id"], menu["id"], **(plan_overrides or {})),
            make_client_headers(client["id"]),
        )
    )
    return chef, menu, client, plan


def generate_occurrence(client_id, plan_id, occurrence_date):
    """Spawn a REQUESTED occurrence from an ACTIVE plan. Returns the spawned booking."""
    res = api_client.generate_occurrence(
        plan_id, {"occurrence_date": occurrence_date}, make_client_headers(client_id)
    )
    return get_success_data(res)


def propose_reschedule(actor_id, actor_role, booking_id, proposed_start, proposed_end):
    """Propose a reschedule (actor_role is 'CHEF' or 'CLIENT'). Returns the request dict."""
    if actor_role == "CHEF":
        headers = make_chef_headers(actor_id)
    else:
        headers = make_client_headers(actor_id)
    res = api_client.create_reschedule_request(
        create_reschedule_request_payload(
            booking_id, proposed_event_start_utc=proposed_start, proposed_event_end_utc=proposed_end
        ),
        headers,
    )
    return get_success_data(res)
