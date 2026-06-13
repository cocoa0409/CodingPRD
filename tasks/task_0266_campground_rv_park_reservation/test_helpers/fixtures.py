"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints — the harness restarts the server (empty DB) before every test. All
setup calls go through get_success_data() so a setup break surfaces as a clear
"Setup failed" rather than a confusing downstream assertion.

Identity threading: the Guest role is entity_backed, so every ownership-gated
call (reservation create/confirm/cancel/check-out-balance, add-on, payment) is
issued with make_guest_headers(guest["id"]) — never the shared guest constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import make_operator_headers, make_guest_headers
from .factories import (
    create_park_payload,
    create_rate_plan_payload,
    create_cancellation_policy_payload,
    create_site_payload,
    create_guest_payload,
    create_reservation_payload,
    create_payment_payload,
)

OP = make_operator_headers()


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(current_utc: str):
    """Set the deterministic server clock. Returns the response body data."""
    return get_success_data(api_client.set_clock(current_utc, OP))


# ---------------------------------------------------------------------------
# Tier 1/2: base park configuration + active site
# ---------------------------------------------------------------------------
def setup_park(clock="2026-07-01T12:00:00Z", with_policy=True, **park_overrides):
    """Create park (after setting the clock) and optional cancellation policy.

    Returns the park dict. The cancellation policy is created with
    full_refund_min_days=14 / half_refund_min_days=7 unless with_policy is False.
    """
    set_clock(clock)
    park = get_success_data(api_client.create_park(create_park_payload(**park_overrides), OP))
    if with_policy:
        get_success_data(api_client.create_cancellation_policy(
            park["id"], create_cancellation_policy_payload(), OP))
    return park


def setup_rate_plan(park_id, **overrides):
    """Create a rate plan under a park. Returns the rate plan dict."""
    return get_success_data(api_client.create_rate_plan(
        park_id, create_rate_plan_payload(**overrides), OP))


def setup_site(park_id, rate_plan_id, **overrides):
    """Create a site under a park on a given rate plan. Returns the site dict."""
    return get_success_data(api_client.create_site(
        park_id, create_site_payload(rate_plan_id, **overrides), OP))


def setup_guest(email="g1@x.com", full_name="Guest One"):
    """Register a guest. Returns the guest dict (its id is the X-User-ID)."""
    return get_success_data(api_client.create_guest(
        create_guest_payload(email=email, full_name=full_name), OP))


def setup_base_scenario(clock="2026-07-01T12:00:00Z", with_policy=True,
                        park_overrides=None, rate_plan_overrides=None,
                        site_overrides=None, guest_email="g1@x.com"):
    """Active RV site + RV rate plan + park + one guest, all freshly created.

    Returns (park, rate_plan, site, guest). This is the most common preamble
    shared across the design indices. `site_overrides` lets a test control
    max_length_of_stay_nights, turnover_buffer_days, label, etc.
    """
    park = setup_park(clock=clock, with_policy=with_policy, **(park_overrides or {}))
    rate_plan = setup_rate_plan(park["id"], **(rate_plan_overrides or {}))
    site = setup_site(park["id"], rate_plan["id"], **(site_overrides or {}))
    guest = setup_guest(email=guest_email)
    return park, rate_plan, site, guest


# ---------------------------------------------------------------------------
# Site version helpers
# ---------------------------------------------------------------------------
def current_site_version(site_id):
    """Re-read a site and return its current version (for OCC-guarded writes)."""
    return get_success_data(api_client.get_site(site_id, OP))["version"]


def get_site(site_id):
    return get_success_data(api_client.get_site(site_id, OP))


def get_reservation(reservation_id, headers=None):
    return get_success_data(api_client.get_reservation(reservation_id, headers or OP))


def get_guest(guest_id):
    return get_success_data(api_client.get_guest(guest_id, OP))


# ---------------------------------------------------------------------------
# Tier 3: reservation lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_reservation(site, guest, check_in_date, check_out_date, expected_site_version=None):
    """Create a REQUESTED reservation. Uses the site's current version unless
    an explicit expected_site_version is given. Returns the reservation dict."""
    if expected_site_version is None:
        expected_site_version = current_site_version(site["id"])
    payload = create_reservation_payload(
        guest["id"], check_in_date, check_out_date, expected_site_version)
    return get_success_data(api_client.create_reservation(
        site["id"], payload, make_guest_headers(guest["id"])))


def pay_deposit(reservation, guest):
    """Record the exact-amount DEPOSIT payment for a reservation. Returns the
    payment dict."""
    amount = reservation["deposit_due_cents"]
    return get_success_data(api_client.create_payment(
        reservation["id"], create_payment_payload("DEPOSIT", amount),
        make_guest_headers(guest["id"])))


def confirm_reservation(reservation, guest):
    """Confirm a reservation as its owner. Returns the updated reservation dict."""
    return get_success_data(api_client.confirm_reservation(
        reservation["id"], make_guest_headers(guest["id"])))


def check_in_reservation(reservation):
    """Operator checks a reservation in. Returns the updated reservation dict."""
    return get_success_data(api_client.check_in_reservation(reservation["id"], OP))


def check_out_reservation(reservation):
    """Operator checks a reservation out. Returns the updated reservation dict."""
    return get_success_data(api_client.check_out_reservation(reservation["id"], OP))


def create_deposit_paid_reservation(site, guest, check_in_date, check_out_date):
    """Reservation -> deposit paid (still REQUESTED). Returns the reservation
    dict re-read after the deposit (so deposit_due_cents/payment_status reflect
    the deposit)."""
    res = create_reservation(site, guest, check_in_date, check_out_date)
    pay_deposit(res, guest)
    return get_reservation(res["id"])


def create_confirmed_reservation(site, guest, check_in_date, check_out_date):
    """Reservation -> deposit paid -> CONFIRMED. Returns the confirmed reservation."""
    res = create_reservation(site, guest, check_in_date, check_out_date)
    pay_deposit(res, guest)
    return confirm_reservation(res, guest)


def create_checked_in_reservation(site, guest, check_in_date, check_out_date,
                                  checkin_clock=None):
    """Reservation -> deposit -> CONFIRMED -> CHECKED_IN. If checkin_clock is
    given the clock is advanced to it (must be >= check_in_date) before check-in.
    Returns the checked-in reservation."""
    res = create_reservation(site, guest, check_in_date, check_out_date)
    pay_deposit(res, guest)
    confirm_reservation(res, guest)
    if checkin_clock is not None:
        set_clock(checkin_clock)
    return check_in_reservation(res)


def create_checked_out_reservation(site, guest, check_in_date, check_out_date,
                                   checkin_clock=None, checkout_clock=None):
    """Full lifecycle to CHECKED_OUT. Returns the checked-out reservation."""
    res = create_reservation(site, guest, check_in_date, check_out_date)
    pay_deposit(res, guest)
    confirm_reservation(res, guest)
    if checkin_clock is not None:
        set_clock(checkin_clock)
    check_in_reservation(res)
    if checkout_clock is not None:
        set_clock(checkout_clock)
    return check_out_reservation(res)


def create_cancelled_reservation(site, guest, check_in_date, check_out_date):
    """Reservation created REQUESTED then immediately CANCELLED (no deposit).
    Returns the cancelled reservation dict."""
    res = create_reservation(site, guest, check_in_date, check_out_date)
    return get_success_data(api_client.cancel_reservation(
        res["id"], make_guest_headers(guest["id"])))


# ---------------------------------------------------------------------------
# Tier 1: site status progression
# ---------------------------------------------------------------------------
def put_site_in_maintenance(site_id):
    """ACTIVE -> MAINTENANCE using the current version. Returns the site dict."""
    v = current_site_version(site_id)
    return get_success_data(api_client.maintenance_site(
        site_id, {"expected_site_version": v}, OP))


def retire_site(site_id):
    """Retire a site using its current version. Returns the site dict."""
    v = current_site_version(site_id)
    return get_success_data(api_client.retire_site(
        site_id, {"expected_site_version": v}, OP))


# ---------------------------------------------------------------------------
# Tier 4: loyalty-tier accumulation (raise lifetime_spend via a prior stay)
# ---------------------------------------------------------------------------
def raise_guest_lifetime_spend_via_prior_stay(
        park, rate_plan, site, guest,
        prior_check_in, prior_check_out, prior_checkout_clock):
    """Drive `guest` through one full reservation -> CHECKED_OUT on `site` so
    its lifetime_spend_cents accumulates the final total_due_cents of that stay.

    Caller controls the prior stay's dates and the checkout clock. Returns the
    checked-out prior reservation dict. The clock is left at prior_checkout_clock;
    callers typically advance it again before the stay under test.
    """
    res = create_reservation(site, guest, prior_check_in, prior_check_out)
    pay_deposit(res, guest)
    confirm_reservation(res, guest)
    # Check-in requires the clock date to be at or after check_in_date (PRD §3.5);
    # advance the clock to the prior stay's check-in date before checking in.
    set_clock(prior_check_in + "T12:00:00Z")
    check_in_reservation(res)
    set_clock(prior_checkout_clock)
    return check_out_reservation(res)
