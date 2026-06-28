"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface as clear
"setup failed" errors rather than confusing assertion failures. Every helper builds its
preconditions from scratch using only PRD-declared endpoints — the test harness restarts
the server (empty DB) before each test.

Identity threading: appointment start/complete are ownership-gated on the serving Stylist,
so those calls use make_stylist_headers(stylist["id"]). Bookings and front-desk actions use
the opaque FrontDesk headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_style_service_payload, create_add_on_payload, create_membership_plan_payload,
    create_member_payload, create_stylist_payload, create_chair_payload,
    create_appointment_payload, create_event_block_payload, create_product_payload,
    create_retail_sale_payload, create_package_purchase_payload,
)
from .test_users import TEST_USERS, make_stylist_headers, make_member_headers

FD = TEST_USERS["front_desk_headers"]
FM = TEST_USERS["finance_manager_headers"]


# ─── Tier 0: primitive resource creators ──────────────────────────────────────

def create_style_service(**overrides):
    return get_success_data(api_client.create_style_service(
        create_style_service_payload(**overrides), FD))


def create_add_on(**overrides):
    return get_success_data(api_client.create_add_on(
        create_add_on_payload(**overrides), FD))


def create_membership_plan(**overrides):
    return get_success_data(api_client.create_membership_plan(
        create_membership_plan_payload(**overrides), FM))


def create_member(**overrides):
    return get_success_data(api_client.create_member(
        create_member_payload(**overrides), FD))


def create_stylist(**overrides):
    return get_success_data(api_client.create_stylist(
        create_stylist_payload(**overrides), FD))


def create_chair(**overrides):
    return get_success_data(api_client.create_chair(
        create_chair_payload(**overrides), FD))


def create_product(**overrides):
    return get_success_data(api_client.create_product(
        create_product_payload(**overrides), FD))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, FD))


# ─── Tier 1: base scenario (service + chair + stylist + member) ────────────────

def setup_base_scenario(service_overrides=None, chair_overrides=None,
                        stylist_overrides=None, member_overrides=None,
                        plan_overrides=None):
    """Create the standard four resources needed to book a standalone appointment.

    Returns dict with keys: service, chair, stylist, member, (plan if plan_overrides).
    """
    out = {}
    if plan_overrides is not None:
        plan = create_membership_plan(**plan_overrides)
        out["plan"] = plan
        member_overrides = dict(member_overrides or {})
        member_overrides.setdefault("membership_plan_id", plan["id"])
    out["service"] = create_style_service(**(service_overrides or {}))
    out["chair"] = create_chair(**(chair_overrides or {}))
    out["stylist"] = create_stylist(**(stylist_overrides or {}))
    out["member"] = create_member(**(member_overrides or {}))
    return out


def book_standalone_appointment(scenario, start_minute=600, payment_method="CREDIT",
                                **appt_overrides):
    """Book a standalone appointment against a scenario dict. Returns the appointment."""
    return get_success_data(api_client.create_appointment(
        create_appointment_payload(
            member_id=scenario["member"]["id"],
            chair_id=scenario["chair"]["id"],
            stylist_id=scenario["stylist"]["id"],
            style_service_id=scenario["service"]["id"],
            start_minute=start_minute,
            payment_method=payment_method,
            **appt_overrides),
        FD))


# ─── Tier 2: appointment lifecycle shortcuts ──────────────────────────────────

def check_in(appointment_id, arrival_status="ON_TIME", late_minutes=None):
    payload = {"arrival_status": arrival_status}
    if late_minutes is not None:
        payload["late_minutes"] = late_minutes
    return get_success_data(api_client.check_in_appointment(appointment_id, payload, FD))


def start_service(appointment_id, stylist_id):
    return get_success_data(api_client.start_appointment(
        appointment_id, make_stylist_headers(stylist_id)))


def complete_service(appointment_id, stylist_id):
    return get_success_data(api_client.complete_appointment(
        appointment_id, make_stylist_headers(stylist_id)))


def settle(appointment_id, tip_cents=0):
    return get_success_data(api_client.settle_appointment(
        appointment_id, {"tip_cents": tip_cents}, FM))


def drive_to_completed(scenario, start_minute=600, payment_method="CREDIT",
                       **appt_overrides):
    """Book → check-in (ON_TIME) → start → complete. Returns the COMPLETED appointment."""
    appt = book_standalone_appointment(
        scenario, start_minute=start_minute, payment_method=payment_method, **appt_overrides)
    sty_id = scenario["stylist"]["id"]
    check_in(appt["id"], "ON_TIME")
    start_service(appt["id"], sty_id)
    return complete_service(appt["id"], sty_id)


def setup_completed_standalone(service_price=6000, commission_tier="SENIOR",
                               payment_method="CREDIT"):
    """A COMPLETED standalone (non-member) appointment ready to settle.

    Returns (scenario, appointment). The appointment's lifecycle is COMPLETED and
    settlement is still UNSETTLED.
    """
    scenario = setup_base_scenario(
        service_overrides={"base_price_cents": service_price},
        stylist_overrides={"commission_tier": commission_tier})
    appt = drive_to_completed(scenario, payment_method=payment_method)
    return scenario, appt


def setup_completed_prepay(prepay_amount=10000, service_price=6000,
                          commission_tier="SENIOR"):
    """A member topped up to `prepay_amount`, with a COMPLETED PREPAY appointment.

    Returns (scenario, appointment). Appointment lifecycle COMPLETED, settlement UNSETTLED.
    """
    scenario = setup_base_scenario(
        service_overrides={"base_price_cents": service_price},
        stylist_overrides={"commission_tier": commission_tier})
    member_id = scenario["member"]["id"]
    get_success_data(api_client.prepay_member(member_id, {"amount_cents": prepay_amount}, FD))
    appt = drive_to_completed(scenario, payment_method="PREPAY")
    return scenario, appt


# ─── Tier 3: event-block scenarios ────────────────────────────────────────────

def setup_event_block_with_two_appointments(block_type="GROUP", party_size=2,
                                            window_start=540, window_end=900,
                                            appt_start=600,
                                            organizer_overrides=None,
                                            stylist1_tier="SENIOR",
                                            stylist2_tier="SENIOR"):
    """Create a HOLD block with two BOOKED appointments referencing it.

    Builds: service, two chairs, two stylists, organizer member + second member, a HOLD
    block reserving both chairs, then two appointments (one per chair/stylist) attached to
    the block (each carrying the up-to-date expected_event_block_version).

    Returns a dict with keys: service, chair_a, chair_b, stylist1, stylist2, organizer,
    guest, block, appt1, appt2.
    """
    service = create_style_service()
    chair_a = create_chair(label="Chair A")
    chair_b = create_chair(label="Chair B")
    stylist1 = create_stylist(full_name="S One", commission_tier=stylist1_tier)
    stylist2 = create_stylist(full_name="S Two", commission_tier=stylist2_tier)
    organizer = create_member(full_name="Organizer", **(organizer_overrides or {}))
    guest = create_member(full_name="Guest Two")

    block = get_success_data(api_client.create_event_block(
        create_event_block_payload(
            organizer_member_id=organizer["id"],
            reserved_chair_ids=[chair_a["id"], chair_b["id"]],
            block_type=block_type,
            window_start_minute=window_start,
            window_end_minute=window_end,
            party_size=party_size),
        FD))

    appt1 = get_success_data(api_client.create_appointment(
        create_appointment_payload(
            member_id=organizer["id"], chair_id=chair_a["id"],
            stylist_id=stylist1["id"], style_service_id=service["id"],
            start_minute=appt_start, payment_method="CREDIT",
            event_block_id=block["id"], expected_event_block_version=block["version"]),
        FD))

    block_v = get_success_data(api_client.get_event_block(block["id"], FD))["version"]
    appt2 = get_success_data(api_client.create_appointment(
        create_appointment_payload(
            member_id=guest["id"], chair_id=chair_b["id"],
            stylist_id=stylist2["id"], style_service_id=service["id"],
            start_minute=appt_start, payment_method="CREDIT",
            event_block_id=block["id"], expected_event_block_version=block_v),
        FD))

    return {
        "service": service, "chair_a": chair_a, "chair_b": chair_b,
        "stylist1": stylist1, "stylist2": stylist2,
        "organizer": organizer, "guest": guest,
        "block": block, "appt1": appt1, "appt2": appt2,
    }


def current_block_version(block_id):
    return get_success_data(api_client.get_event_block(block_id, FD))["version"]


def pay_deposit(block_id, amount_cents):
    return get_success_data(api_client.deposit_event_block(
        block_id, {"amount_cents": amount_cents}, FD))


def confirm_block(block_id, expected_version=None):
    if expected_version is None:
        expected_version = current_block_version(block_id)
    return get_success_data(api_client.confirm_event_block(
        block_id, {"expected_event_block_version": expected_version}, FD))


def setup_confirmed_block(block_type="GROUP", deposit_cents=4000,
                         stylist1_tier="SENIOR", stylist2_tier="SENIOR"):
    """A CONFIRMED block with two BOOKED appointments and deposit met.

    Returns the same dict as setup_event_block_with_two_appointments, with the block now
    CONFIRMED (and the dict's 'block' value refreshed to the confirmed state).
    """
    ctx = setup_event_block_with_two_appointments(
        block_type=block_type, stylist1_tier=stylist1_tier, stylist2_tier=stylist2_tier)
    pay_deposit(ctx["block"]["id"], deposit_cents)
    ctx["block"] = confirm_block(ctx["block"]["id"])
    return ctx


# ─── Tier 4: no-show / suspension accumulation ────────────────────────────────

def setup_member_with_no_show_strikes(num_strikes, clock_iso="2026-01-01T11:00:00Z"):
    """Drive a member to `num_strikes` NO_SHOW outcomes.

    Sets the logical clock past the appointment start so each no-show is eligible, then
    books and no-shows `num_strikes` appointments for one member. Returns (scenario, member)
    where member is the freshly-read member record.
    """
    scenario = setup_base_scenario()
    set_clock(clock_iso)
    member_id = scenario["member"]["id"]
    for _ in range(num_strikes):
        appt = book_standalone_appointment(scenario, start_minute=600)
        get_success_data(api_client.no_show_appointment(appt["id"], FD))
    member = get_success_data(api_client.get_member(member_id, FD))
    return scenario, member


# ─── Tier 5: retail sale scenarios ────────────────────────────────────────────

def setup_sold_retail_sale(initial_stock=10, quantity=3, unit_price=2500,
                           attributed=False, commission_pct=0.10):
    """A product with a SOLD sale of `quantity` units. Returns (product, member, sale).

    If attributed=True, a stylist is created and credited; the returned tuple becomes
    (product, member, sale, stylist).
    """
    prod = create_product(unit_price_cents=unit_price, initial_stock=initial_stock,
                          retail_commission_pct=commission_pct)
    member = create_member(full_name="Buyer")
    if attributed:
        stylist = create_stylist(full_name="Retail Stylist")
        sale = get_success_data(api_client.create_retail_sale(
            create_retail_sale_payload(prod["id"], member["id"], quantity=quantity,
                                       attributed_stylist_id=stylist["id"]), FD))
        return prod, member, sale, stylist
    sale = get_success_data(api_client.create_retail_sale(
        create_retail_sale_payload(prod["id"], member["id"], quantity=quantity), FD))
    return prod, member, sale


# ─── re-exports for convenience in test files ─────────────────────────────────

__all__ = [
    "FD", "FM",
    "create_style_service", "create_add_on", "create_membership_plan", "create_member",
    "create_stylist", "create_chair", "create_product", "set_clock",
    "setup_base_scenario", "book_standalone_appointment",
    "check_in", "start_service", "complete_service", "settle", "drive_to_completed",
    "setup_completed_standalone", "setup_completed_prepay",
    "setup_event_block_with_two_appointments", "current_block_version", "pay_deposit",
    "confirm_block", "setup_confirmed_block",
    "setup_member_with_no_show_strikes", "setup_sold_retail_sale",
    "make_stylist_headers", "make_member_headers",
]
