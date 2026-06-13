"""Composite setup helpers for multi-step test prerequisites.

Each test runs against a fresh, empty database, so every fixture builds its
preconditions from scratch using only PRD-declared endpoints. Fixtures use the
lenient get_success_data() validator so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_stylist_payload,
    create_fitting_room_payload,
    create_bridal_party_payload,
    create_appointment_payload,
    create_fitting_room_booking_payload,
    create_gown_order_payload,
    create_accessory_addon_payload,
    create_alteration_job_payload,
    create_payment_plan_payload,
    post_payment_payload,
)
from .test_users import TEST_USERS

MANAGER = TEST_USERS["shop_manager_headers"]
CONSULTANT = TEST_USERS["bridal_consultant_headers"]
SEAMSTRESS = TEST_USERS["seamstress_headers"]
CLERK = TEST_USERS["finance_clerk_headers"]


# ─── Tier 1: Standing resources (stylists, rooms, parties) ──────────────────

def create_stylist(**overrides):
    """Create a stylist. Returns the stylist entity."""
    return get_success_data(api_client.create_stylist(create_stylist_payload(**overrides), MANAGER))


def create_fitting_room(**overrides):
    """Create a fitting room. Returns the room entity."""
    return get_success_data(
        api_client.create_fitting_room(create_fitting_room_payload(**overrides), MANAGER)
    )


def create_bridal_party(**overrides):
    """Create a FORMING bridal party. Returns the party entity."""
    return get_success_data(
        api_client.create_bridal_party(create_bridal_party_payload(**overrides), CONSULTANT)
    )


def create_locked_party(**overrides):
    """Create a party and lock it (FORMING -> LOCKED). Returns the locked party."""
    party = create_bridal_party(**overrides)
    return get_success_data(api_client.lock_bridal_party(party["id"], MANAGER))


# ─── Tier 2: Appointments and bookings ──────────────────────────────────────

def create_booked_appointment(stylist_id=None, **overrides):
    """Create a BOOKED appointment (creates a stylist if none given).
    Returns (appointment, stylist_id)."""
    if stylist_id is None:
        stylist_id = create_stylist()["id"]
    appt = get_success_data(
        api_client.create_appointment(create_appointment_payload(stylist_id, **overrides), CONSULTANT)
    )
    return appt, stylist_id


def create_checked_in_appointment(stylist_id=None, **overrides):
    """Create a BOOKED appointment then check it in. Returns (appointment, stylist_id)."""
    appt, stylist_id = create_booked_appointment(stylist_id, **overrides)
    appt = get_success_data(api_client.check_in_appointment(appt["id"], CONSULTANT))
    return appt, stylist_id


def create_held_booking(room_id, appointment_id, **overrides):
    """Create a HELD fitting-room booking. Returns the booking entity."""
    return get_success_data(
        api_client.create_fitting_room_booking(
            create_fitting_room_booking_payload(appointment_id, room_id, **overrides), CONSULTANT
        )
    )


# ─── Tier 3: Gown orders, plans, payments ───────────────────────────────────

def create_draft_order(**overrides):
    """Create a DRAFT gown order. Returns the order entity."""
    return get_success_data(api_client.create_gown_order(create_gown_order_payload(**overrides), CONSULTANT))


def create_active_accessory(gown_order_id, **overrides):
    """Attach an ACTIVE accessory to an order. Returns the accessory entity."""
    return get_success_data(
        api_client.create_accessory_addon(
            create_accessory_addon_payload(gown_order_id, **overrides), CONSULTANT
        )
    )


def create_plan(gown_order_id, **overrides):
    """Create a PaymentPlan for an order. Returns the plan entity (status DEPOSIT_DUE)."""
    return get_success_data(
        api_client.create_payment_plan(create_payment_plan_payload(gown_order_id, **overrides), CLERK)
    )


def create_order_with_plan(order_overrides=None, plan_overrides=None):
    """DRAFT order + a PaymentPlan (no payment yet). Returns (order, plan)."""
    order = create_draft_order(**(order_overrides or {}))
    plan = create_plan(order["id"], **(plan_overrides or {}))
    return order, plan


def post_payment(plan_id, amount_cents, expected_plan_version):
    """Post a payment with the given amount and OCC version. Returns the payment entity."""
    return get_success_data(
        api_client.post_payment(plan_id, post_payment_payload(amount_cents, expected_plan_version), CLERK)
    )


def get_plan(plan_id):
    """Fetch a plan (ledger recomputed). Returns the plan entity."""
    return get_success_data(api_client.get_payment_plan(plan_id, CLERK))


def get_order(order_id):
    """Fetch an order. Returns the order entity."""
    return get_success_data(api_client.get_gown_order(order_id, MANAGER))


# ─── Tier 4: Fulfillment-lifecycle shortcuts ────────────────────────────────

def create_ordered_order(order_overrides=None, plan_overrides=None):
    """Order advanced DRAFT -> ORDERED (plan created, submitted). Returns (order, plan)."""
    order, plan = create_order_with_plan(order_overrides, plan_overrides)
    order = get_success_data(api_client.submit_gown_order(order["id"], CONSULTANT))
    return order, plan


def create_received_order(order_overrides=None, plan_overrides=None):
    """Order advanced through RECEIVED (final_total_cents stamped). Returns (order, plan)."""
    order, plan = create_ordered_order(order_overrides, plan_overrides)
    order = get_success_data(api_client.receive_gown_order(order["id"], MANAGER))
    return order, plan


def pay_deposit(order_id, plan):
    """Post the plan's exact deposit amount, advancing plan -> ACTIVE / order -> DEPOSIT_PAID.
    Returns the refreshed plan."""
    fresh = get_plan(plan["id"])
    post_payment(plan["id"], fresh["deposit_cents"], fresh["version"])
    return get_plan(plan["id"])


def pay_in_full(plan):
    """Post payments until the plan balance reaches zero (PAID_IN_FULL).
    Re-reads the plan version before each post to satisfy the OCC guard.
    Returns the refreshed plan."""
    fresh = get_plan(plan["id"])
    while fresh["balance_due_cents"] > 0:
        amount = fresh["balance_due_cents"] if fresh["amount_paid_cents"] >= fresh["deposit_cents"] \
            else max(fresh["deposit_cents"], 1)
        # Never overshoot the balance.
        amount = min(amount, fresh["balance_due_cents"])
        post_payment(plan["id"], amount, fresh["version"])
        fresh = get_plan(plan["id"])
    return fresh


def create_ready_order(order_overrides=None, plan_overrides=None, fully_paid=True):
    """Order through RECEIVED -> READY (no alterations). Optionally fully paid first.
    Returns (order, plan)."""
    order, plan = create_received_order(order_overrides, plan_overrides)
    if fully_paid:
        plan = pay_in_full(plan)
    order = get_success_data(api_client.mark_ready_gown_order(order["id"], SEAMSTRESS))
    return order, plan


def create_deposit_paid_ready_order(order_overrides=None, plan_overrides=None):
    """Order through RECEIVED -> READY with only the deposit paid (DEPOSIT_PAID, balance > 0).
    Returns (order, plan)."""
    order, plan = create_received_order(order_overrides, plan_overrides)
    plan = pay_deposit(order["id"], plan)
    order = get_success_data(api_client.mark_ready_gown_order(order["id"], SEAMSTRESS))
    return order, plan


def create_picked_up_order(order_overrides=None, plan_overrides=None):
    """Full happy path through PICKED_UP. Returns (order, plan)."""
    order, plan = create_ready_order(order_overrides, plan_overrides, fully_paid=True)
    order = get_success_data(
        api_client.pickup_gown_order(order["id"], {"final_steam_done": True}, CONSULTANT)
    )
    return order, plan


def create_cancelled_order_with_deposit(order_overrides=None, plan_overrides=None):
    """Order with a deposit paid, then cancelled (plan retained because money was taken).
    Returns (order, plan)."""
    order, plan = create_order_with_plan(order_overrides, plan_overrides)
    plan = pay_deposit(order["id"], plan)
    get_success_data(api_client.cancel_gown_order(order["id"], MANAGER))
    return order, plan


# ─── Tier 5: Alteration jobs ────────────────────────────────────────────────

def create_queued_job(gown_order_id, **overrides):
    """Create a QUEUED alteration job. Returns the job entity."""
    return get_success_data(
        api_client.create_alteration_job(
            create_alteration_job_payload(gown_order_id, **overrides), SEAMSTRESS
        )
    )


def create_fitting_job(order_overrides=None, plan_overrides=None, job_overrides=None):
    """RECEIVED order + alteration job started into FITTING. Returns (order, job)."""
    order, _ = create_received_order(order_overrides, plan_overrides)
    job = create_queued_job(order["id"], **(job_overrides or {}))
    job = get_success_data(api_client.start_fitting_alteration_job(job["id"], SEAMSTRESS))
    return order, job


def create_received_order_with_queued_job(order_overrides=None, plan_overrides=None, job_overrides=None):
    """RECEIVED order + alteration job still QUEUED. Returns (order, job)."""
    order, _ = create_received_order(order_overrides, plan_overrides)
    job = create_queued_job(order["id"], **(job_overrides or {}))
    return order, job


def setup_fitting_job_on_room(room_capacity=4):
    """RECEIVED order + a HELD room booking + an AlterationJob in FITTING on that same room.

    Builds: room (capacity) -> stylist -> FITTING appointment -> HELD booking filling the
    room -> RECEIVED order -> alteration job (fitting_room_id = room) -> start fitting.
    Returns (order, job, booking, room).
    """
    room = create_fitting_room(room_label="Suite A", capacity=room_capacity)
    stylist = create_stylist(full_name="Dana")
    appt, _ = create_booked_appointment(
        stylist["id"], appointment_type="FITTING",
        start_at="2026-07-01T15:00:00.000Z", end_at="2026-07-01T16:00:00.000Z",
    )
    booking = create_held_booking(
        room["id"], appt["id"], party_size=room_capacity,
        slot_start_at="2026-07-01T15:00:00.000Z", slot_end_at="2026-07-01T16:00:00.000Z",
    )
    order, _ = create_received_order(order_overrides={"base_price_cents": 160000, "ordered_size": 12,
                                                      "standard_lead_days": 60})
    job = create_queued_job(order["id"], estimated_labor_minutes=40, fitting_room_id=room["id"])
    job = get_success_data(api_client.start_fitting_alteration_job(job["id"], SEAMSTRESS))
    return order, job, booking, room
