"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared endpoints
and returns the created resources. Setup calls use get_success_data() so a broken
precondition surfaces as a clear "Setup failed" rather than a confusing assertion.

The test harness restarts the server (empty DB, logical clock reset to the
2026-07-01 startup default) before every test, so these helpers never assume any
pre-existing state.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_member_headers
from . import factories as f

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
ANON = TEST_USERS["anonymous_headers"]


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------

def set_clock(api, iso):
    return get_success_data(api.set_clock(iso, ADMIN))


def create_active_member(api, tier=None):
    """Register a member and activate it. Returns (member, member_headers)."""
    payload = f.member_payload()
    if tier is not None:
        payload["membership_tier"] = tier
    member = get_success_data(api.register_member(payload, ANON))
    member = get_success_data(api.activate_member(member["id"], STAFF))
    return member, make_member_headers(member["id"])


def create_pending_member(api, tier=None):
    payload = f.member_payload()
    if tier is not None:
        payload["membership_tier"] = tier
    member = get_success_data(api.register_member(payload, ANON))
    return member, make_member_headers(member["id"])


def create_product(api, **overrides):
    return get_success_data(api.create_product(f.product_payload(**overrides), ADMIN))


def create_rentable_product(api, **overrides):
    return get_success_data(api.create_product(f.rentable_product_payload(**overrides), ADMIN))


def create_rental_unit(api, product_id, **overrides):
    return get_success_data(api.create_rental_unit(f.rental_unit_payload(product_id, **overrides), ADMIN))


def create_guide(api, certifications=None):
    return get_success_data(api.create_guide(f.guide_payload(certifications=certifications or []), ADMIN))


def create_trip(api, **overrides):
    return get_success_data(api.create_trip(f.trip_payload(**overrides), ADMIN))


# --------------------------------------------------------------------------
# Rental scenarios
# --------------------------------------------------------------------------

def setup_reservation(api, tier=None, product_overrides=None, member_id=None,
                      member_headers=None, start_date="2026-07-10T00:00:00Z",
                      end_date="2026-07-13T00:00:00Z"):
    """Active member + rentable product + one AVAILABLE unit + a RESERVED reservation.
    Returns (member, member_headers, product, unit, reservation)."""
    if member_id is None:
        member, member_headers = create_active_member(api, tier=tier)
        member_id = member["id"]
    else:
        member = None
    product = create_rentable_product(api, **(product_overrides or {}))
    unit = create_rental_unit(api, product["id"])
    res = get_success_data(api.create_reservation(
        f.reservation_payload(member_id, unit["id"], start_date, end_date), member_headers))
    return member, member_headers, product, unit, res


def setup_reservation_with_unit(api, tier=None, base_daily_rate_cents=3000,
                                replacement_value_cents=100000):
    """Active member + rentable product + one AVAILABLE unit (no reservation yet).
    Returns (member, member_headers, product, unit)."""
    member, member_headers = create_active_member(api, tier=tier)
    product = create_rentable_product(
        api, base_daily_rate_cents=base_daily_rate_cents,
        replacement_value_cents=replacement_value_cents)
    unit = create_rental_unit(api, product["id"])
    return member, member_headers, product, unit


def setup_picked_up_reservation(api, base_daily_rate_cents=4000, replacement_value_cents=200000,
                                start_date="2026-07-05T00:00:00Z", end_date="2026-07-07T00:00:00Z"):
    """Reservation advanced to PICKED_UP (unit RENTED_OUT).
    Returns (member, member_headers, product, unit, reservation)."""
    member, member_headers = create_active_member(api)
    product = create_rentable_product(
        api, base_daily_rate_cents=base_daily_rate_cents,
        replacement_value_cents=replacement_value_cents)
    unit = create_rental_unit(api, product["id"])
    res = get_success_data(api.create_reservation(
        f.reservation_payload(member["id"], unit["id"], start_date, end_date), member_headers))
    res = get_success_data(api.pickup_reservation(res["id"], STAFF))
    return member, member_headers, product, unit, res


# --------------------------------------------------------------------------
# Trip / booking scenarios
# --------------------------------------------------------------------------

def setup_open_trip(api, capacity=5, price_cents=5000, required_certification="NONE",
                    guide_certs=None, start_time="2026-08-01T09:00:00Z",
                    end_time="2026-08-01T17:00:00Z"):
    """Guide-assigned OPEN trip. Returns (trip, guide)."""
    guide = create_guide(api, certifications=guide_certs or [])
    trip = create_trip(api, capacity=capacity, price_cents=price_cents,
                       required_certification=required_certification,
                       start_time=start_time, end_time=end_time)
    get_success_data(api.assign_guide(trip["id"], {"guide_id": guide["id"]}, ADMIN))
    trip = get_success_data(api.open_trip(trip["id"], ADMIN))
    return trip, guide


def setup_draft_trip_with_guide(api, capacity=5, price_cents=5000, required_certification="NONE",
                                start_time="2026-08-02T09:00:00Z", end_time="2026-08-02T17:00:00Z"):
    """Guide-assigned but not-yet-opened (DRAFT) trip. Returns (trip, guide)."""
    guide = create_guide(api, certifications=[])
    trip = create_trip(api, capacity=capacity, price_cents=price_cents,
                       required_certification=required_certification,
                       start_time=start_time, end_time=end_time)
    get_success_data(api.assign_guide(trip["id"], {"guide_id": guide["id"]}, ADMIN))
    trip = get_success_data(api.get_trip(trip["id"], ADMIN))
    return trip, guide


def create_purchase(api, member_id, line_items, points_redeemed=None):
    payload = f.purchase_payload(member_id, line_items)
    if points_redeemed is not None:
        payload["points_redeemed"] = points_redeemed
    return get_success_data(api.create_purchase(payload, STAFF))


# --------------------------------------------------------------------------
# Trade-in scenarios
# --------------------------------------------------------------------------

def setup_offered_trade_in(api, retail_price_cents=100000, condition_grade="A"):
    """Active member + product + a SUBMITTED trade-in advanced to OFFERED.
    Returns (member, member_headers, product, trade_in)."""
    member, member_headers = create_active_member(api)
    product = create_product(api, retail_price_cents=retail_price_cents)
    ti = get_success_data(api.create_trade_in(
        f.trade_in_payload(member["id"], product["id"], condition_grade), member_headers))
    ti = get_success_data(api.offer_trade_in(ti["id"], STAFF))
    return member, member_headers, product, ti


def setup_submitted_trade_in(api, retail_price_cents=80000, condition_grade="A"):
    """Active member + product + a SUBMITTED trade-in (never offered).
    Returns (member, member_headers, product, trade_in)."""
    member, member_headers = create_active_member(api)
    product = create_product(api, retail_price_cents=retail_price_cents)
    ti = get_success_data(api.create_trade_in(
        f.trade_in_payload(member["id"], product["id"], condition_grade), member_headers))
    return member, member_headers, product, ti


def setup_trade_in_at_round_cap(api, retail_price_cents=60000, condition_grade="B"):
    """A trade-in looped offer/counter 3 times (rounds==3), currently OFFERED.
    Returns (member, member_headers, product, trade_in)."""
    member, member_headers = create_active_member(api)
    product = create_product(api, retail_price_cents=retail_price_cents)
    ti = get_success_data(api.create_trade_in(
        f.trade_in_payload(member["id"], product["id"], condition_grade), member_headers))
    for ask in (30000, 31000, 32000):
        get_success_data(api.offer_trade_in(ti["id"], STAFF))
        get_success_data(api.counter_trade_in(ti["id"], {"counter_ask_cents": ask}, member_headers))
    ti = get_success_data(api.offer_trade_in(ti["id"], STAFF))
    return member, member_headers, product, ti


# --------------------------------------------------------------------------
# Repair scenarios
# --------------------------------------------------------------------------

def setup_diagnosed_repair(api, purchase_date="2020-01-01T00:00:00Z",
                           labor_cents=5000, parts_cents=0):
    """Repair order diagnosed (out-of-warranty when purchase_date old).
    Returns (member, member_headers, product, repair_order)."""
    member, member_headers = create_active_member(api)
    product = create_product(api, retail_price_cents=40000)
    ro = get_success_data(api.create_repair_order(
        f.repair_order_payload(member["id"], product["id"], purchase_date), STAFF))
    ro = get_success_data(api.diagnose_repair_order(
        ro["id"], {"labor_cents": labor_cents, "parts_cents": parts_cents}, STAFF))
    return member, member_headers, product, ro


# --------------------------------------------------------------------------
# Special-order scenarios
# --------------------------------------------------------------------------

def setup_requested_special_order(api, retail_price_cents=50000, quantity=1):
    """Active member + product + a REQUESTED special order.
    Returns (member, member_headers, product, special_order)."""
    member, member_headers = create_active_member(api)
    product = create_product(api, retail_price_cents=retail_price_cents)
    so = get_success_data(api.create_special_order(
        f.special_order_payload(member["id"], product["id"], quantity), member_headers))
    return member, member_headers, product, so


def setup_quoted_special_order(api, quoted_price_cents=50000, quantity=1):
    """A special order advanced to QUOTED (version advanced by the quote).
    Returns (member, member_headers, product, special_order_after_quote, initial_version)."""
    member, member_headers, product, so = setup_requested_special_order(api, quantity=quantity)
    v0 = so["version"]
    so_q = get_success_data(api.quote_special_order(
        so["id"], {"quoted_price_cents": quoted_price_cents,
                   "expected_special_order_version": v0}, STAFF))
    return member, member_headers, product, so_q, v0


# --------------------------------------------------------------------------
# Dividend scenarios
# --------------------------------------------------------------------------

def setup_member_with_eligible_spend(api, spend_cents, tier=None):
    """Active member with a single COMPLETED purchase giving eligible_spend_cents == spend_cents.
    Returns (member, member_headers, product, purchase)."""
    member, member_headers = create_active_member(api, tier=tier)
    product = create_product(api, retail_price_cents=spend_cents)
    purchase = create_purchase(
        api, member["id"],
        [{"product_id": product["id"], "quantity": 1, "unit_price_cents": spend_cents}])
    return member, member_headers, product, purchase


def create_draft_declaration(api, year=2026, declared_rate=0.08):
    return get_success_data(api.create_declaration(
        f.declaration_payload(year=year, declared_rate=declared_rate), ADMIN))
