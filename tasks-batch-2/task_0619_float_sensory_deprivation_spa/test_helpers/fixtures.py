"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce clear
"Setup failed" errors rather than confusing assertion failures.

Every helper builds its preconditions from scratch (the harness restarts the server with an
empty database before every test). Member-owned, ownership-gated calls thread the member's
real id via make_member_headers(member_id); all other operations run as FrontDesk/Admin.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_plan_payload,
    create_member_payload,
    create_membership_payload,
    create_tank_payload,
    create_sanitation_cycle_payload,
    create_attendant_payload,
    create_orientation_payload,
    create_booking_payload,
    create_gift_card_payload,
)
from .test_users import TEST_USERS, make_member_headers

ADMIN = TEST_USERS["admin_headers"]
FRONTDESK = TEST_USERS["frontdesk_headers"]


# ─── Logical clock ────────────────────────────────────────────────────────
def set_clock(iso_utc: str):
    """Advance the server logical clock to a supplied instant (Admin-only)."""
    return get_success_data(api_client.set_clock(iso_utc, ADMIN))


# ─── Tier 0: Single-entity creators ───────────────────────────────────────
def create_plan(**overrides) -> dict:
    return get_success_data(api_client.create_plan(create_plan_payload(**overrides), ADMIN))


def create_member(**overrides) -> dict:
    return get_success_data(api_client.create_member(create_member_payload(**overrides), FRONTDESK))


def create_attendant(**overrides) -> dict:
    return get_success_data(api_client.create_attendant(create_attendant_payload(**overrides), ADMIN))


def create_tank(**overrides) -> dict:
    return get_success_data(api_client.create_tank(create_tank_payload(**overrides), ADMIN))


def create_gift_card(**overrides) -> dict:
    return get_success_data(api_client.create_gift_card(create_gift_card_payload(**overrides), FRONTDESK))


# ─── Tier 1: State progression ────────────────────────────────────────────
def create_oriented_member(orientation_start: str, orientation_complete_at: str,
                          waiver_version: int = 1, **member_overrides) -> dict:
    """Register a member, schedule an orientation starting at `orientation_start`, advance
    the clock to `orientation_complete_at`, and complete the orientation so the member is
    oriented + waiver-signed. Returns the refreshed Member.

    Caller is responsible for clock state on entry; this helper sets the clock to
    orientation_complete_at as its last clock action.
    """
    member = create_member(**member_overrides)
    attendant = create_attendant()
    # end_utc strictly after start_utc (30-minute window).
    start = orientation_start
    end = _plus_minutes_iso(start, 30)
    ori = get_success_data(api_client.create_orientation(
        create_orientation_payload(member["id"], attendant["id"], start, end,
                                   waiver_version=waiver_version),
        FRONTDESK,
    ))
    set_clock(orientation_complete_at)
    get_success_data(api_client.complete_orientation(ori["id"], FRONTDESK))
    return get_success_data(api_client.get_member(member["id"], FRONTDESK))


def create_active_membership(member_id: str, plan_id: str) -> dict:
    """Open a PENDING membership and activate it to ACTIVE (grants included floats)."""
    ship = get_success_data(api_client.create_membership(
        create_membership_payload(member_id, plan_id), FRONTDESK))
    return get_success_data(api_client.activate_membership(ship["id"], FRONTDESK))


def create_pending_membership(member_id: str, plan_id: str) -> dict:
    return get_success_data(api_client.create_membership(
        create_membership_payload(member_id, plan_id), FRONTDESK))


# ─── Tier 2: Booking lifecycle shortcuts ──────────────────────────────────
def create_booking(member_id: str, tank_id: str, session_minutes: int, start_utc: str,
                  pay_source: str, headers=None, **overrides) -> dict:
    """Create a RESERVED booking. Defaults to FrontDesk; pass headers for a Member-owned call."""
    return get_success_data(api_client.create_booking(
        create_booking_payload(member_id, tank_id, session_minutes, start_utc, pay_source,
                               **overrides),
        headers or FRONTDESK,
    ))


def create_confirmed_booking(member_id: str, tank_id: str, session_minutes: int,
                            start_utc: str, pay_source: str, **overrides) -> dict:
    """Create a booking and confirm it (RESERVED -> CONFIRMED). Member must already be
    oriented/eligible. Returns the CONFIRMED booking."""
    bk = create_booking(member_id, tank_id, session_minutes, start_utc, pay_source, **overrides)
    return get_success_data(api_client.confirm_booking(bk["id"], FRONTDESK))


def create_checked_in_booking(member_id: str, tank_id: str, session_minutes: int,
                             start_utc: str, pay_source: str, check_in_at: str,
                             **overrides) -> dict:
    """Create -> confirm -> advance clock to check_in_at -> check-in. Returns CHECKED_IN
    booking. Tank must be CLEAN+IN_SERVICE; funding source must cover the session."""
    bk = create_confirmed_booking(member_id, tank_id, session_minutes, start_utc,
                                  pay_source, **overrides)
    set_clock(check_in_at)
    return get_success_data(api_client.check_in_booking(bk["id"], FRONTDESK))


# ─── Tier 3: Composite scenarios for difficulty instances ─────────────────
def setup_completed_couples_giftcard_booking(plan_overrides=None, gift_card_balance=100000):
    """DUO plan + oriented member + DUAL tank + ample gift card + a couples 60-min GIFT_CARD
    booking driven all the way to COMPLETED. Used for provisional-vs-final divergence.

    Clock timeline: 2026-03-01T00:00 base; orientation completed 01:05; booking start
    2026-03-02T10:00; check-in 09:55; complete after that. Returns the COMPLETED booking.
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_plan(**(plan_overrides or {"tier": "DUO", "monthly_fee_cents": 9000,
                          "included_floats_per_cycle": 8, "rollover_cap": 6,
                          "retail_float_cents": 6000, "member_discount_pct": 0.0}))
    member = create_oriented_member("2026-03-01T01:00:00Z", "2026-03-01T01:05:00Z")
    tank = create_tank(capacity_kind="DUAL", turnover_buffer_minutes=30)
    gc = create_gift_card(initial_balance_cents=gift_card_balance)
    bk = create_checked_in_booking(
        member["id"], tank["id"], 60, "2026-03-02T10:00:00Z", "GIFT_CARD",
        "2026-03-02T09:55:00Z", is_couples=True, gift_card_id=gc["id"])
    completed = get_success_data(api_client.complete_booking(bk["id"], FRONTDESK))
    return {"plan": plan, "member": member, "tank": tank, "gift_card": gc,
            "booking": completed}


def setup_membership_for_refund():
    """ACTIVE DUO membership; member consumes 2 credits via a completed couples CREDIT
    booking this cycle; clock advanced to 15 days remaining. Returns the membership id and
    member, with the clock positioned at 2026-03-16T00:00 ready for cancel.
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_plan(tier="DUO", monthly_fee_cents=9000, included_floats_per_cycle=8,
                       rollover_cap=6, retail_float_cents=6000, member_discount_pct=0.0)
    member = create_oriented_member("2026-03-01T01:00:00Z", "2026-03-01T01:05:00Z")
    # Activate at a clean midnight so the cycle window is [2026-03-01T00:00, 2026-03-31T00:00):
    # cancelling at 2026-03-16T00:00 then leaves exactly 15 whole days remaining (proration
    # 9000*15/30 = 4500). Orientation completion (above) had nudged the clock to 01:05; reset
    # it here so the cycle boundary lands on the day boundary the proration math expects.
    set_clock("2026-03-01T00:00:00Z")
    ship = create_active_membership(member["id"], plan["id"])
    tank = create_tank(capacity_kind="DUAL", turnover_buffer_minutes=30)
    bk = create_confirmed_booking(member["id"], tank["id"], 60, "2026-03-02T10:00:00Z",
                                  "CREDIT", is_couples=True, membership_id=ship["id"])
    set_clock("2026-03-02T09:55:00Z")
    get_success_data(api_client.check_in_booking(bk["id"], FRONTDESK))
    get_success_data(api_client.complete_booking(bk["id"], FRONTDESK))
    set_clock("2026-03-16T00:00:00Z")
    return {"plan": plan, "member": member, "membership": ship, "tank": tank, "booking_id": bk["id"]}


def setup_completed_single_credit_booking(retail=5000, discount=0.20, session_minutes=90):
    """SOLO plan with member discount + oriented active member with ACTIVE membership +
    SINGLE tank; a CREDIT booking taken to COMPLETED. Used for nested-branch final charge.
    Returns the COMPLETED booking.
    """
    set_clock("2026-04-01T00:00:00Z")
    plan = create_plan(tier="SOLO", monthly_fee_cents=8000, included_floats_per_cycle=4,
                       rollover_cap=4, retail_float_cents=retail, member_discount_pct=discount)
    member = create_oriented_member("2026-04-01T01:00:00Z", "2026-04-01T01:05:00Z")
    ship = create_active_membership(member["id"], plan["id"])
    tank = create_tank(capacity_kind="SINGLE", turnover_buffer_minutes=30)
    bk = create_checked_in_booking(
        member["id"], tank["id"], session_minutes, "2026-04-02T10:00:00Z", "CREDIT",
        "2026-04-02T09:55:00Z", membership_id=ship["id"])
    completed = get_success_data(api_client.complete_booking(bk["id"], FRONTDESK))
    return {"plan": plan, "member": member, "membership": ship, "tank": tank,
            "booking": completed}


def setup_active_membership_for_rollover(included=10, rollover_cap=6):
    """Plan with included floats > rollover_cap; member with an ACTIVE membership freshly
    activated (credit_balance == included). Returns the ACTIVE membership ready to renew.
    """
    set_clock("2026-05-01T00:00:00Z")
    plan = create_plan(tier="ROLL", monthly_fee_cents=7000, included_floats_per_cycle=included,
                       rollover_cap=rollover_cap, retail_float_cents=5000, member_discount_pct=0.0)
    member = create_member()
    ship = create_active_membership(member["id"], plan["id"])
    return {"plan": plan, "member": member, "membership": ship}


def setup_confirmed_couples_cash_booking_for_noshow():
    """Oriented member + DUAL tank + couples CASH booking CONFIRMED; clock advanced past
    start + grace so a no-show is allowed. Returns the CONFIRMED booking (clock at past-grace).
    """
    set_clock("2026-06-01T00:00:00Z")
    create_plan(tier="DUO", monthly_fee_cents=9000, included_floats_per_cycle=8,
                rollover_cap=6, retail_float_cents=6000)
    member = create_oriented_member("2026-06-01T01:00:00Z", "2026-06-01T01:05:00Z")
    tank = create_tank(capacity_kind="DUAL", turnover_buffer_minutes=30)
    bk = create_confirmed_booking(member["id"], tank["id"], 60, "2026-06-03T10:00:00Z",
                                  "CASH", is_couples=True)
    set_clock("2026-06-03T10:20:00Z")
    return {"member": member, "tank": tank, "booking": bk}


def setup_confirmed_cash_booking_future():
    """Oriented member + SINGLE tank + CASH 60-min booking CONFIRMED with start far in the
    future (2026-07-10). Clock at 2026-07-01. Returns the CONFIRMED booking. Used for the
    reschedule cycle.
    """
    set_clock("2026-07-01T00:00:00Z")
    create_plan(tier="SOLO", monthly_fee_cents=8000, included_floats_per_cycle=4,
                rollover_cap=4, retail_float_cents=5000)
    member = create_oriented_member("2026-07-01T01:00:00Z", "2026-07-01T01:05:00Z")
    tank = create_tank(capacity_kind="SINGLE", turnover_buffer_minutes=30)
    bk = create_confirmed_booking(member["id"], tank["id"], 60, "2026-07-10T10:00:00Z", "CASH")
    return {"member": member, "tank": tank, "booking": bk}


def setup_tank_in_maintenance(base_clock="2026-07-15T00:00:00Z"):
    """A SINGLE tank put into MAINTENANCE (operational axis), sanitation still CLEAN.
    Returns the tank after the maintenance transition."""
    set_clock(base_clock)
    tank = create_tank(name="Pod-Par", capacity_kind="SINGLE", turnover_buffer_minutes=30)
    tank = get_success_data(api_client.tank_maintenance(tank["id"], ADMIN))
    return {"tank": tank}


def setup_two_bookings_for_cascade():
    """Oriented member + SINGLE tank buffer 30m. Booking#1 CASH 60m start 10:00 driven to
    CHECKED_IN; Booking#2 CASH 60m start 11:30 RESERVED (non-overlapping at creation). Clock
    advanced to 11:45 so completing #1 starts a cycle ending 12:15 > #2.start 11:30.
    Returns both booking ids and the tank.
    """
    set_clock("2026-08-01T00:00:00Z")
    create_plan(tier="SOLO", monthly_fee_cents=8000, included_floats_per_cycle=4,
                rollover_cap=4, retail_float_cents=5000)
    member = create_oriented_member("2026-08-01T01:00:00Z", "2026-08-01T01:05:00Z")
    tank = create_tank(capacity_kind="SINGLE", turnover_buffer_minutes=30)
    bk1 = create_booking(member["id"], tank["id"], 60, "2026-08-02T10:00:00Z", "CASH")
    bk2 = create_booking(member["id"], tank["id"], 60, "2026-08-02T11:30:00Z", "CASH")
    get_success_data(api_client.confirm_booking(bk1["id"], FRONTDESK))
    set_clock("2026-08-02T09:55:00Z")
    get_success_data(api_client.check_in_booking(bk1["id"], FRONTDESK))
    set_clock("2026-08-02T11:45:00Z")
    return {"member": member, "tank": tank, "bk1": bk1, "bk2": bk2}


def setup_active_membership_simple(included=4, base_clock="2026-08-10T00:00:00Z"):
    """ACTIVE membership with credit_balance == included (granted floats, none consumed).
    No orientation needed (no booking). Returns the ACTIVE membership."""
    set_clock(base_clock)
    plan = create_plan(tier="SOLO", monthly_fee_cents=8000, included_floats_per_cycle=included,
                       rollover_cap=included, retail_float_cents=5000)
    member = create_member()
    ship = create_active_membership(member["id"], plan["id"])
    return {"plan": plan, "member": member, "membership": ship}


def setup_reserved_credit_booking_zero_balance():
    """Oriented member; ACTIVE membership but credit_balance == 0 (plan included 0); SINGLE
    tank CLEAN. A CREDIT booking left RESERVED (never confirmed). Clock at 09:55 on the
    booking day so a check-in attempt is time-eligible. Returns the RESERVED booking.
    """
    set_clock("2026-09-01T00:00:00Z")
    plan = create_plan(tier="ZERO", monthly_fee_cents=8000, included_floats_per_cycle=0,
                       rollover_cap=0, retail_float_cents=5000)
    member = create_oriented_member("2026-09-01T01:00:00Z", "2026-09-01T01:05:00Z")
    ship = create_active_membership(member["id"], plan["id"])
    tank = create_tank(capacity_kind="SINGLE", turnover_buffer_minutes=30)
    bk = create_booking(member["id"], tank["id"], 60, "2026-09-02T10:00:00Z", "CREDIT",
                        membership_id=ship["id"])
    set_clock("2026-09-02T09:55:00Z")
    return {"plan": plan, "member": member, "membership": ship, "tank": tank, "booking": bk}


def setup_confirmed_credit_booking_tank_in_cycle(zero_balance=True):
    """Oriented member; ACTIVE membership (credit_balance 0 if zero_balance else 4); SINGLE
    tank put IN_CYCLE by a DEEP_CLEAN; a CREDIT booking CONFIRMED on that tank. Clock at
    09:55 on the booking day so check-in is time-eligible. Returns the CONFIRMED booking.
    """
    set_clock("2026-09-10T00:00:00Z")
    included = 0 if zero_balance else 4
    plan = create_plan(tier="ZERO" if zero_balance else "SOLO", monthly_fee_cents=8000,
                       included_floats_per_cycle=included, rollover_cap=included,
                       retail_float_cents=5000)
    member = create_oriented_member("2026-09-10T01:00:00Z", "2026-09-10T01:05:00Z")
    ship = create_active_membership(member["id"], plan["id"])
    tank = create_tank(capacity_kind="SINGLE", turnover_buffer_minutes=30)
    bk = create_confirmed_booking(member["id"], tank["id"], 60, "2026-09-11T10:00:00Z",
                                  "CREDIT", membership_id=ship["id"])
    get_success_data(api_client.create_sanitation_cycle(
        create_sanitation_cycle_payload(tank["id"], kind="DEEP_CLEAN", duration_minutes=60),
        FRONTDESK))
    set_clock("2026-09-11T09:55:00Z")
    return {"plan": plan, "member": member, "membership": ship, "tank": tank, "booking": bk}


def setup_confirmed_cash_booking_at_cancel_boundary():
    """Oriented member; SINGLE tank; CASH 60m booking CONFIRMED start 2026-10-02T10:00Z.
    Clock set to exactly 2026-10-01T10:00:00Z (start - 24h, the inclusive timely boundary).
    Returns the CONFIRMED booking.
    """
    set_clock("2026-10-01T00:00:00Z")
    create_plan(tier="SOLO", monthly_fee_cents=8000, included_floats_per_cycle=4,
                rollover_cap=4, retail_float_cents=5000)
    member = create_oriented_member("2026-10-01T00:30:00Z", "2026-10-01T00:35:00Z")
    tank = create_tank(capacity_kind="SINGLE", turnover_buffer_minutes=30)
    bk = create_confirmed_booking(member["id"], tank["id"], 60, "2026-10-02T10:00:00Z", "CASH")
    set_clock("2026-10-01T10:00:00Z")
    return {"member": member, "tank": tank, "booking": bk}


def setup_confirmed_couples_giftcard_depletion():
    """Gift card initial 16000 (deposit 4000 + provisional 12000 of a couples 60m DUO
    booking). Oriented member; DUAL tank CLEAN; couples GIFT_CARD booking CONFIRMED. Clock at
    09:55 on the booking day. Returns the CONFIRMED booking and the gift card.
    """
    set_clock("2026-10-20T00:00:00Z")
    create_plan(tier="DUO", monthly_fee_cents=9000, included_floats_per_cycle=8,
                rollover_cap=6, retail_float_cents=6000)
    member = create_oriented_member("2026-10-20T01:00:00Z", "2026-10-20T01:05:00Z")
    tank = create_tank(capacity_kind="DUAL", turnover_buffer_minutes=30)
    gc = create_gift_card(initial_balance_cents=16000)
    bk = create_confirmed_booking(member["id"], tank["id"], 60, "2026-10-21T10:00:00Z",
                                  "GIFT_CARD", is_couples=True, gift_card_id=gc["id"])
    set_clock("2026-10-21T09:55:00Z")
    return {"member": member, "tank": tank, "gift_card": gc, "booking": bk}


def setup_reserved_cash_booking_unoriented():
    """Member who has NOT completed orientation; SINGLE tank; CASH booking RESERVED.
    Returns the RESERVED booking and the member. No clock advance needed (confirm has no
    timing gate)."""
    set_clock("2026-11-01T00:00:00Z")
    create_plan(tier="SOLO", monthly_fee_cents=8000, included_floats_per_cycle=4,
                rollover_cap=4, retail_float_cents=5000)
    member = create_member()
    tank = create_tank(capacity_kind="SINGLE", turnover_buffer_minutes=30)
    bk = create_booking(member["id"], tank["id"], 60, "2026-11-05T10:00:00Z", "CASH")
    return {"member": member, "tank": tank, "booking": bk}


def setup_single_tank_with_first_booking(buffer=30, base_clock="2026-12-01T00:00:00Z"):
    """SINGLE tank buffer `buffer`; Booking#1 60m at 10:00 exists (occupies
    [10:00, 11:00 + buffer)). Returns the tank, member, and Booking#1. For overlap tests."""
    set_clock(base_clock)
    create_plan(tier="SOLO", monthly_fee_cents=8000, included_floats_per_cycle=4,
                rollover_cap=4, retail_float_cents=5000)
    member = create_member()
    tank = create_tank(capacity_kind="SINGLE", turnover_buffer_minutes=buffer)
    bk1 = create_booking(member["id"], tank["id"], 60, "2026-12-02T10:00:00Z", "CASH")
    return {"member": member, "tank": tank, "bk1": bk1}


def setup_attendant_with_orientation(base_clock="2026-12-04T00:00:00Z"):
    """Attendant with one SCHEDULED orientation 2026-12-05T09:00-10:00 for member A; a
    second member B available. Returns the attendant, members, and orientation A.
    """
    set_clock(base_clock)
    member_a = create_member()
    member_b = create_member()
    att = create_attendant()
    ori_a = get_success_data(api_client.create_orientation(
        create_orientation_payload(member_a["id"], att["id"],
                                   "2026-12-05T09:00:00Z", "2026-12-05T10:00:00Z"),
        FRONTDESK))
    return {"member_a": member_a, "member_b": member_b, "attendant": att, "orientation_a": ori_a}


def setup_credit_consumption_invariant():
    """SOLO plan included 4; oriented active member; ACTIVE membership balance 4; SINGLE tank
    CLEAN. A CREDIT 60m booking CONFIRMED. Clock at 09:55 on the booking day ready for
    check-in. Returns the membership and CONFIRMED booking.
    """
    set_clock("2027-01-01T00:00:00Z")
    plan = create_plan(tier="SOLO", monthly_fee_cents=8000, included_floats_per_cycle=4,
                       rollover_cap=4, retail_float_cents=5000)
    member = create_oriented_member("2027-01-01T01:00:00Z", "2027-01-01T01:05:00Z")
    ship = create_active_membership(member["id"], plan["id"])
    tank = create_tank(capacity_kind="SINGLE", turnover_buffer_minutes=30)
    bk = create_confirmed_booking(member["id"], tank["id"], 60, "2027-01-02T10:00:00Z",
                                  "CREDIT", membership_id=ship["id"])
    set_clock("2027-01-02T09:55:00Z")
    return {"plan": plan, "member": member, "membership": ship, "tank": tank, "booking": bk}


def setup_giftcard_reserved_booking_for_cancel():
    """Gift card initial 10000; oriented-not-required member; SINGLE tank; GIFT_CARD 60m
    booking RESERVED start 2027-02-10T10:00Z. Clock well before the 24h cutoff. Returns the
    RESERVED booking and gift card.
    """
    set_clock("2027-02-01T00:00:00Z")
    create_plan(tier="SOLO", monthly_fee_cents=8000, included_floats_per_cycle=4,
                rollover_cap=4, retail_float_cents=5000)
    member = create_member()
    tank = create_tank(capacity_kind="SINGLE", turnover_buffer_minutes=30)
    gc = create_gift_card(initial_balance_cents=10000)
    bk = create_booking(member["id"], tank["id"], 60, "2027-02-10T10:00:00Z", "GIFT_CARD",
                        gift_card_id=gc["id"])
    return {"member": member, "tank": tank, "gift_card": gc, "booking": bk}


# ─── Tier 4: Corner-design simple scenarios ───────────────────────────────
def setup_member_and_tank(base_clock="2026-01-05T00:00:00Z"):
    """One member + one SINGLE tank. Common corner setup. Returns both."""
    set_clock(base_clock)
    member = create_member()
    tank = create_tank(capacity_kind="SINGLE")
    return {"member": member, "tank": tank}


def setup_completed_credit_booking():
    """A booking driven all the way to COMPLETED (oriented member, CREDIT, SINGLE tank).
    Returns the COMPLETED booking. Used for terminal-state lockdown tests.
    """
    set_clock("2026-02-01T00:00:00Z")
    plan = create_plan(tier="SOLO", monthly_fee_cents=8000, included_floats_per_cycle=4,
                       rollover_cap=4, retail_float_cents=5000)
    member = create_oriented_member("2026-02-01T01:00:00Z", "2026-02-01T01:05:00Z")
    ship = create_active_membership(member["id"], plan["id"])
    tank = create_tank(capacity_kind="SINGLE")
    bk = create_checked_in_booking(member["id"], tank["id"], 60, "2026-02-03T10:00:00Z",
                                   "CREDIT", "2026-02-03T09:55:00Z", membership_id=ship["id"])
    completed = get_success_data(api_client.complete_booking(bk["id"], FRONTDESK))
    return {"plan": plan, "member": member, "membership": ship, "tank": tank,
            "booking": completed}


def setup_deep_clean_in_progress(start_clock, complete_clock, duration_minutes=60):
    """A SINGLE tank with an IN_PROGRESS DEEP_CLEAN started at `start_clock` (ends start +
    duration). Clock advanced to `complete_clock`. Returns the tank and cycle.
    """
    set_clock(start_clock)
    tank = create_tank(capacity_kind="SINGLE")
    cyc = get_success_data(api_client.create_sanitation_cycle(
        create_sanitation_cycle_payload(tank["id"], kind="DEEP_CLEAN",
                                        duration_minutes=duration_minutes),
        FRONTDESK))
    set_clock(complete_clock)
    return {"tank": tank, "cycle": cyc}


def setup_scheduled_orientation(start_utc, complete_clock=None, waiver_version=1,
                               base_clock="2026-03-01T08:00:00Z"):
    """A SCHEDULED orientation at `start_utc`. If complete_clock is given the clock is moved
    there as the last action. Returns the member and orientation.
    """
    set_clock(base_clock)
    member = create_member()
    att = create_attendant()
    end = _plus_minutes_iso(start_utc, 30)
    ori = get_success_data(api_client.create_orientation(
        create_orientation_payload(member["id"], att["id"], start_utc, end,
                                   waiver_version=waiver_version),
        FRONTDESK))
    if complete_clock:
        set_clock(complete_clock)
    return {"member": member, "attendant": att, "orientation": ori}


def setup_inactive_plan_pending_membership():
    """An inactive plan (active=false) and a PENDING membership on it. Returns the membership."""
    set_clock("2026-01-05T00:00:00Z")
    plan = create_plan(tier="OLD", monthly_fee_cents=8000, included_floats_per_cycle=4,
                       rollover_cap=4, retail_float_cents=5000, active=False)
    member = create_member()
    ship = create_pending_membership(member["id"], plan["id"])
    return {"plan": plan, "member": member, "membership": ship}


def setup_void_gift_card():
    """A VOID gift card; a member; a SINGLE tank. Returns all three."""
    set_clock("2026-01-05T00:00:00Z")
    member = create_member()
    tank = create_tank(capacity_kind="SINGLE")
    gc = create_gift_card(code="GC-VOID", initial_balance_cents=5000)
    get_success_data(api_client.void_gift_card(gc["id"], TEST_USERS["admin_headers"]))
    return {"member": member, "tank": tank, "gift_card": gc}


def setup_renewed_membership():
    """An ACTIVE membership; one successful renew already advanced its version. Returns the
    membership id, the version observed at activation (now stale), and the current version.
    """
    set_clock("2026-01-05T00:00:00Z")
    plan = create_plan(tier="SOLO", monthly_fee_cents=8000, included_floats_per_cycle=4,
                       rollover_cap=4, retail_float_cents=5000)
    member = create_member()
    ship = create_active_membership(member["id"], plan["id"])
    v_act = ship["version"]
    renewed = get_success_data(api_client.renew_membership(
        ship["id"], {"expected_membership_version": v_act}, FRONTDESK))
    return {"membership": ship, "v_act": v_act, "v_after": renewed["version"],
            "renewed": renewed}


def setup_confirmed_cash_booking_for_reschedule_cutoff():
    """Oriented member; SINGLE tank; CONFIRMED CASH booking start 2026-05-10T10:00Z; clock at
    2026-05-10T00:00Z (10h before, inside the 12h cutoff). Returns the CONFIRMED booking.
    """
    set_clock("2026-05-09T00:00:00Z")
    create_plan(tier="SOLO", monthly_fee_cents=8000, included_floats_per_cycle=4,
                rollover_cap=4, retail_float_cents=5000)
    member = create_oriented_member("2026-05-09T01:00:00Z", "2026-05-09T01:05:00Z")
    tank = create_tank(capacity_kind="SINGLE")
    bk = create_confirmed_booking(member["id"], tank["id"], 60, "2026-05-10T10:00:00Z", "CASH")
    set_clock("2026-05-10T00:00:00Z")
    return {"member": member, "tank": tank, "booking": bk}


def setup_confirmed_cash_booking_for_late_cancel():
    """Oriented member; SINGLE tank; CONFIRMED CASH single booking start 2026-05-20T10:00Z;
    clock at 2026-05-19T20:00Z (14h before, inside the 24h cutoff -> late). Returns the
    CONFIRMED booking.
    """
    set_clock("2026-05-19T00:00:00Z")
    create_plan(tier="SOLO", monthly_fee_cents=8000, included_floats_per_cycle=4,
                rollover_cap=4, retail_float_cents=5000)
    member = create_oriented_member("2026-05-19T01:00:00Z", "2026-05-19T01:05:00Z")
    tank = create_tank(capacity_kind="SINGLE")
    bk = create_confirmed_booking(member["id"], tank["id"], 60, "2026-05-20T10:00:00Z", "CASH")
    set_clock("2026-05-19T20:00:00Z")
    return {"member": member, "tank": tank, "booking": bk}


def setup_confirmed_credit_booking_zero_balance_clean_tank():
    """Oriented member; ACTIVE membership credit_balance 0 (plan included 0); CLEAN SINGLE
    tank; CONFIRMED CREDIT booking. Clock at 09:55 on the booking day. No higher-priority
    gate fires. Returns the CONFIRMED booking.
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_plan(tier="ZERO", monthly_fee_cents=8000, included_floats_per_cycle=0,
                       rollover_cap=0, retail_float_cents=5000)
    member = create_oriented_member("2026-06-15T01:00:00Z", "2026-06-15T01:05:00Z")
    ship = create_active_membership(member["id"], plan["id"])
    tank = create_tank(capacity_kind="SINGLE")
    bk = create_confirmed_booking(member["id"], tank["id"], 60, "2026-06-16T10:00:00Z",
                                  "CREDIT", membership_id=ship["id"])
    set_clock("2026-06-16T09:55:00Z")
    return {"plan": plan, "member": member, "membership": ship, "tank": tank, "booking": bk}


def setup_member_owned_confirmed_credit_booking():
    """A CONFIRMED CREDIT booking created and confirmed by the Member themselves (ownership
    threaded). Clock at 09:55 on the booking day. Returns the member id and CONFIRMED booking.
    Used for RBAC: Member cannot check-in.
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_plan(tier="SOLO", monthly_fee_cents=8000, included_floats_per_cycle=4,
                       rollover_cap=4, retail_float_cents=5000)
    member = create_oriented_member("2026-06-15T01:00:00Z", "2026-06-15T01:05:00Z")
    ship = create_active_membership(member["id"], plan["id"])
    tank = create_tank(capacity_kind="SINGLE")
    member_headers = make_member_headers(member["id"])
    bk = get_success_data(api_client.create_booking(
        create_booking_payload(member["id"], tank["id"], 60, "2026-06-16T10:00:00Z",
                               "CREDIT", membership_id=ship["id"]),
        member_headers))
    get_success_data(api_client.confirm_booking(bk["id"], member_headers))
    set_clock("2026-06-16T09:55:00Z")
    return {"member": member, "membership": ship, "tank": tank, "booking": bk,
            "member_headers": member_headers}


def setup_confirmed_cash_booking_for_noshow_strike():
    """Oriented active member; SINGLE tank; CONFIRMED CASH booking; clock past start+grace.
    Returns the member and CONFIRMED booking. For the no-show strike-increment test.
    """
    set_clock("2026-07-01T00:00:00Z")
    create_plan(tier="SOLO", monthly_fee_cents=8000, included_floats_per_cycle=4,
                rollover_cap=4, retail_float_cents=5000)
    member = create_oriented_member("2026-07-01T01:00:00Z", "2026-07-01T01:05:00Z")
    tank = create_tank(capacity_kind="SINGLE")
    bk = create_confirmed_booking(member["id"], tank["id"], 60, "2026-07-03T10:00:00Z", "CASH")
    set_clock("2026-07-03T10:20:00Z")
    return {"member": member, "tank": tank, "booking": bk}


# ─── Internal time helper ─────────────────────────────────────────────────
def _plus_minutes_iso(iso_utc: str, minutes: int) -> str:
    """Add `minutes` to an ISO 8601 UTC instant of the form YYYY-MM-DDTHH:MM:SSZ."""
    from datetime import datetime, timedelta, timezone
    dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    dt += timedelta(minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Payment / ledger lookup helpers ──────────────────────────────────────
def get_payments_for_booking(booking_id: str) -> list:
    data, _meta = _list_all(api_client.list_payments, {"booking_id": booking_id})
    return data


def get_payments_for_gift_card(gift_card_id: str) -> list:
    data, _meta = _list_all(api_client.list_payments, {"gift_card_id": gift_card_id})
    return data


def get_ledger_for_membership(membership_id: str) -> list:
    data, _meta = _list_all(api_client.list_credit_ledger, {"membership_id": membership_id})
    return data


def get_all_payments() -> list:
    """All payment rows (no filter). For looking up booking_id=null refunds."""
    data, _meta = _list_all(api_client.list_payments, {})
    return data


def _list_all(list_fn, base_params: dict) -> tuple:
    """Page through a list endpoint, returning (all_items, last_meta). Uses Admin headers."""
    from prd_bench_local_runner.testing import validate_paginated
    items = []
    offset = 0
    limit = 100
    last_meta = {}
    while True:
        params = dict(base_params)
        params["limit"] = limit
        params["offset"] = offset
        data, meta = validate_paginated(list_fn(ADMIN, params=params))
        items.extend(data)
        last_meta = meta
        if not meta.get("has_more"):
            break
        offset += limit
    return items, last_meta
