"""Composite setup helpers.

Every function builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so the DB starts
empty). Setup calls use get_success_data (lenient) so setup failures surface as
clear errors rather than confusing assertion mismatches.

Identity threading: whenever a Member acts on its own resource, headers are built
with make_member_headers(member["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_member_headers
from . import factories as F


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(iso: str):
    """Advance the logical clock (Manager-only)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, TEST_USERS["manager"]))


# --------------------------------------------------------------------------
# Primitive entity builders
# --------------------------------------------------------------------------
def make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0, **overrides):
    payload = F.create_plan_payload(
        tier=tier, monthly_fee_cents=monthly_fee_cents,
        table_discount_pct=table_discount_pct, **overrides,
    )
    return get_success_data(api_client.create_plan(payload, TEST_USERS["manager"]))


def make_member(plan_id, email=None, full_name="Test Member", handicap_rating=None, **overrides):
    kwargs = dict(plan_id=plan_id, full_name=full_name)
    kwargs["email"] = email if email is not None else F.unique_email()
    if handicap_rating is not None:
        kwargs["handicap_rating"] = handicap_rating
    kwargs.update(overrides)
    payload = F.create_member_payload(**kwargs)
    return get_success_data(api_client.create_member(payload, TEST_USERS["manager"]))


def fund_member(member_id, amount_cents):
    """Credit a member's wallet via an operator adjustment."""
    return get_success_data(
        api_client.adjust_member_wallet(member_id, {"amount_cents": amount_cents}, TEST_USERS["manager"])
    )


def make_funded_member(plan_id, amount_cents, **overrides):
    m = make_member(plan_id, **overrides)
    fund_member(m["id"], amount_cents)
    return m


def make_table(table_type="POOL_7FT", seat_capacity=4, hourly_rate_cents=1000, table_number=None, **overrides):
    if table_number is None:
        table_number = F.next_table_number()
    payload = F.create_table_payload(
        table_number=table_number, table_type=table_type,
        seat_capacity=seat_capacity, hourly_rate_cents=hourly_rate_cents, **overrides,
    )
    return get_success_data(api_client.create_table(payload, TEST_USERS["manager"]))


def make_product(category="ACCESSORY", stock_qty=5, unit_price_cents=500, sku=None, name="Test Product", **overrides):
    payload = F.create_product_payload(
        sku=sku if sku is not None else F.unique_sku(),
        name=name, category=category, unit_price_cents=unit_price_cents,
        stock_qty=stock_qty, **overrides,
    )
    return get_success_data(api_client.create_product(payload, TEST_USERS["proshop"]))


# --------------------------------------------------------------------------
# Reservations
# --------------------------------------------------------------------------
def make_reservation(member_id, table_id, start_at, end_at, party_size=2, as_frontdesk=True, headers=None):
    """Create a PENDING reservation (default actor FrontDesk on behalf of the member)."""
    if headers is None:
        headers = TEST_USERS["frontdesk"] if as_frontdesk else make_member_headers(member_id)
    payload = F.create_reservation_payload(
        member_id=member_id, table_id=table_id,
        start_at=start_at, end_at=end_at, party_size=party_size,
    )
    return get_success_data(api_client.create_reservation(payload, headers))


def make_confirmed_reservation(member_id, table_id, start_at, end_at, party_size=2):
    """Create + confirm a reservation. Returns the confirmed reservation."""
    r = make_reservation(member_id, table_id, start_at, end_at, party_size)
    return get_success_data(api_client.confirm_reservation(r["id"], TEST_USERS["frontdesk"]))


# --------------------------------------------------------------------------
# Table sessions
# --------------------------------------------------------------------------
def open_walkin_session(table_id, member_id=None):
    """Open a walk-in session (FrontDesk). member_id null = anonymous walk-in."""
    payload = F.create_session_payload(table_id=table_id)
    if member_id is not None:
        payload["member_id"] = member_id
    return get_success_data(api_client.create_session(payload, TEST_USERS["frontdesk"]))


def checkin_reservation(reservation_id):
    """Check in a CONFIRMED reservation; returns the opened TableSession."""
    return get_success_data(api_client.checkin_reservation(reservation_id, TEST_USERS["frontdesk"]))


# --------------------------------------------------------------------------
# Tournaments
# --------------------------------------------------------------------------
def make_tournament(name="Test Cup", fmt="SINGLE_ELIM", entry_fee_cents=0, max_entries=8,
                    handicap_mode=None, open_registration=False):
    payload = F.create_tournament_payload(
        name=name, format=fmt, entry_fee_cents=entry_fee_cents, max_entries=max_entries,
    )
    if handicap_mode is not None:
        payload["handicap_mode"] = handicap_mode
    t = get_success_data(api_client.create_tournament(payload, TEST_USERS["manager"]))
    if open_registration:
        t = get_success_data(api_client.open_tournament(t["id"], TEST_USERS["manager"]))
    return t


def enter_tournament(tournament_id, member_id):
    """Member enters a tournament (acts on own member_id)."""
    payload = F.create_tournament_entry_payload(tournament_id=tournament_id, member_id=member_id)
    return get_success_data(
        api_client.create_tournament_entry(payload, make_member_headers(member_id))
    )


def setup_tournament_with_entries(ratings, entry_fee_cents=0, max_entries=8, handicap_mode=None,
                                  fund_each=0, name="Test Cup", fmt="SINGLE_ELIM"):
    """Create a REGISTRATION_OPEN tournament with one entered member per rating.

    Returns (tournament, members, entries) where members/entries are lists aligned
    to `ratings`. Members are funded `fund_each` cents each (so entry fees clear).
    """
    plan = make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0)
    t = make_tournament(name=name, fmt=fmt, entry_fee_cents=entry_fee_cents,
                        max_entries=max_entries, handicap_mode=handicap_mode,
                        open_registration=True)
    members, entries = [], []
    for rating in ratings:
        m = make_member(plan["id"], handicap_rating=rating)
        if fund_each:
            fund_member(m["id"], fund_each)
        e = enter_tournament(t["id"], m["id"])
        members.append(m)
        entries.append(e)
    return t, members, entries


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------
def make_event(host_member_id, table_count, start_at, end_at):
    payload = F.create_event_payload(
        host_member_id=host_member_id, table_count=table_count,
        start_at=start_at, end_at=end_at,
    )
    return get_success_data(api_client.create_event(payload, make_member_headers(host_member_id)))


def setup_quoted_event(table_count, start_at, end_at, host_funded=100_000, num_tables=None,
                       table_type="POOL_9FT", seat_capacity=8, hourly_rate_cents=1200):
    """Create N ACTIVE tables, a funded GOLD host, and an event advanced to QUOTED.

    Returns (host, event, tables). num_tables defaults to table_count.
    """
    if num_tables is None:
        num_tables = table_count
    plan = make_plan(tier="GOLD", monthly_fee_cents=8000, table_discount_pct=0.20)
    host = make_funded_member(plan["id"], host_funded)
    tables = [make_table(table_type=table_type, seat_capacity=seat_capacity,
                         hourly_rate_cents=hourly_rate_cents) for _ in range(num_tables)]
    ev = make_event(host["id"], table_count, start_at, end_at)
    ev = get_success_data(api_client.quote_event(ev["id"], TEST_USERS["manager"]))
    return host, ev, tables


def setup_booked_event(table_count, start_at, end_at, host_funded=100_000,
                       hourly_rate_cents=1200):
    """Advance an event through QUOTED -> deposit paid -> BOOKED.

    Returns (host, event, tables). Deposit is paid (payment_status DEPOSIT_PAID),
    then tables are booked (CONFIRMED reservations created with the event_id).
    """
    host, ev, tables = setup_quoted_event(table_count, start_at, end_at, host_funded=host_funded,
                                          hourly_rate_cents=hourly_rate_cents)
    hh = make_member_headers(host["id"])
    ev = get_success_data(api_client.pay_deposit_event(ev["id"], hh))
    ev = get_success_data(api_client.book_event(ev["id"], hh))
    return host, ev, tables
