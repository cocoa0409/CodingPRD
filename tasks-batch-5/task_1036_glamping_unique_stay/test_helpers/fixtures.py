"""Composite setup helpers.

Every fixture builds its preconditions from scratch against an empty database
(the runner restarts the server before each test) using only PRD-declared
endpoints. All setup calls use the lenient get_success_data() validator so a
broken precondition surfaces as a clear "Setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .test_users import (
    TEST_USERS,
    make_host_headers,
    make_guest_headers,
    make_permit_reviewer_headers,
    make_platform_admin_headers,
)
from . import factories as f

ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["permit_reviewer_headers"]

# Canonical July window used by most setups (covers all sample stay dates).
JULY_START = "2026-07-01T00:00:00Z"
SEP_START = "2026-09-01T00:00:00Z"
AUG_START = "2026-08-01T00:00:00Z"


# --------------------------------------------------------------------------
# Primitive helpers (single API call each, ownership-threaded)
# --------------------------------------------------------------------------
def onboard_host(**overrides):
    resp = api.create_host(f.create_host_payload(**overrides), ADMIN)
    return get_success_data(resp)


def onboard_guest(**overrides):
    resp = api.create_guest(f.create_guest_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_listing(host_id, **overrides):
    resp = api.create_listing(f.create_listing_payload(host_id, **overrides),
                              make_host_headers(host_id))
    return get_success_data(resp)


def file_permit(host_id, listing_id, **overrides):
    resp = api.create_permit(listing_id, f.create_permit_payload(listing_id, **overrides),
                             make_host_headers(host_id))
    return get_success_data(resp)


def submit_permit(host_id, permit_id):
    return get_success_data(api.submit_permit(permit_id, make_host_headers(host_id)))


def decide_permit(permit_id, outcome="APPROVE", review_notes=None):
    payload = {"outcome": outcome}
    if review_notes is not None:
        payload["review_notes"] = review_notes
    return get_success_data(api.decide_permit(permit_id, payload, REVIEWER))


def add_rate(host_id, listing_id, start_date, end_date, nightly_rate_cents, **overrides):
    resp = api.create_seasonal_rate(
        listing_id,
        f.create_seasonal_rate_payload(listing_id, start_date, end_date,
                                       nightly_rate_cents, **overrides),
        make_host_headers(host_id),
    )
    return get_success_data(resp)


def reprice_rate(host_id, rate_id, **payload):
    return get_success_data(api.reprice_seasonal_rate(rate_id, payload,
                                                      make_host_headers(host_id)))


def publish(host_id, listing_id):
    return get_success_data(api.publish_listing(listing_id, make_host_headers(host_id)))


def suspend(host_id, listing_id):
    return get_success_data(api.suspend_listing(listing_id, make_host_headers(host_id)))


def create_add_on(host_id, listing_id, **overrides):
    resp = api.create_add_on(listing_id, f.create_add_on_payload(listing_id, **overrides),
                             make_host_headers(host_id))
    return get_success_data(resp)


def create_slot(host_id, add_on_id, slot_date, max_participants, **overrides):
    resp = api.create_slot(add_on_id,
                           f.create_slot_payload(add_on_id, slot_date, max_participants,
                                                 **overrides),
                           make_host_headers(host_id))
    return get_success_data(resp)


def set_clock(to_iso8601):
    return get_success_data(api.set_clock(to_iso8601, make_platform_admin_headers()))


def read_listing_version(listing_id, guest_id):
    """Read the listing's current version through a guest (as a guest would
    before quoting a stay)."""
    data = get_success_data(api.get_listing(listing_id, make_guest_headers(guest_id)))
    return data["version"]


def request_booking(listing_id, guest_id, check_in, check_out, guest_count=2,
                    version=None):
    """Request a booking. If version is None, reads the current listing version
    first so the OCC check passes."""
    if version is None:
        version = read_listing_version(listing_id, guest_id)
    resp = api.create_booking(
        listing_id,
        f.create_booking_payload(listing_id, guest_id, check_in, check_out, version,
                                 guest_count=guest_count),
        make_guest_headers(guest_id),
    )
    return get_success_data(resp)


def accept_booking(host_id, booking_id):
    return get_success_data(api.accept_booking(booking_id, make_host_headers(host_id)))


def check_in_booking(host_id, booking_id):
    return get_success_data(api.check_in_booking(booking_id, make_host_headers(host_id)))


def complete_booking(host_id, booking_id):
    return get_success_data(api.complete_booking(booking_id, make_host_headers(host_id)))


def get_payout(host_id, booking_id):
    """Return the single payout object for a booking (or None)."""
    data = get_success_data(api.get_payout(booking_id, make_host_headers(host_id)))
    return data[0] if isinstance(data, list) and data else None


# --------------------------------------------------------------------------
# Composite: a LISTED listing with an approved permit + rate window(s)
# --------------------------------------------------------------------------
def setup_listed_listing(
    site_type="CABIN",
    max_guests=4,
    min_nights=None,
    base_nightly_rate_cents=20000,
    cleaning_fee_cents=None,
    cancellation_policy=None,
    permit_type="STRUCTURE",
    rate_windows=None,
    rate_cents=20000,
    rate_start=JULY_START,
    rate_end=SEP_START,
):
    """Onboard a host + guest, create a listing, clear the permit gate, add
    seasonal rate window(s), and publish -> listing is LISTED.

    rate_windows, when given, is a list of dicts:
        {start_date, end_date, nightly_rate_cents, [min_nights_override]}
    Otherwise a single window [rate_start, rate_end) @ rate_cents is used.

    Returns a dict: host, guest, listing (post-publish snapshot), permit, rates.
    """
    host = onboard_host()
    guest = onboard_guest()

    listing_over = {
        "site_type": site_type,
        "max_guests": max_guests,
        "base_nightly_rate_cents": base_nightly_rate_cents,
    }
    if min_nights is not None:
        listing_over["min_nights"] = min_nights
    if cleaning_fee_cents is not None:
        listing_over["cleaning_fee_cents"] = cleaning_fee_cents
    if cancellation_policy is not None:
        listing_over["cancellation_policy"] = cancellation_policy
    listing = create_listing(host["id"], **listing_over)

    permit = file_permit(host["id"], listing["id"], permit_type=permit_type)
    submit_permit(host["id"], permit["id"])
    permit = decide_permit(permit["id"], outcome="APPROVE")

    rates = []
    if rate_windows is None:
        rate_windows = [{
            "start_date": rate_start, "end_date": rate_end,
            "nightly_rate_cents": rate_cents,
        }]
    for w in rate_windows:
        extra = {}
        if "min_nights_override" in w:
            extra["min_nights_override"] = w["min_nights_override"]
        rates.append(add_rate(host["id"], listing["id"], w["start_date"], w["end_date"],
                              w["nightly_rate_cents"], **extra))

    listing = publish(host["id"], listing["id"])
    return {"host": host, "guest": guest, "listing": listing, "permit": permit,
            "rates": rates}


# --------------------------------------------------------------------------
# Composite: a CONFIRMED booking (LISTED listing + requested + accepted)
# --------------------------------------------------------------------------
def setup_confirmed_booking(
    check_in="2026-07-10T00:00:00Z",
    check_out="2026-07-13T00:00:00Z",
    guest_count=2,
    **listing_kwargs,
):
    """Build a LISTED listing, request a booking, and accept it -> CONFIRMED.

    Returns a dict: host, guest, listing, booking (accepted snapshot), payout.
    """
    env = setup_listed_listing(**listing_kwargs)
    booking = request_booking(env["listing"]["id"], env["guest"]["id"],
                              check_in, check_out, guest_count=guest_count)
    booking = accept_booking(env["host"]["id"], booking["id"])
    payout = get_payout(env["host"]["id"], booking["id"])
    env["booking"] = booking
    env["payout"] = payout
    return env


def setup_completed_booking(
    check_in="2026-07-10T00:00:00Z",
    check_out="2026-07-13T00:00:00Z",
    checkin_clock="2026-07-11T00:00:00Z",
    guest_count=2,
    **listing_kwargs,
):
    """Build a CONFIRMED booking, advance the clock, check in and complete it.

    Returns a dict: host, guest, listing, booking (completed snapshot), payout.
    """
    env = setup_confirmed_booking(check_in=check_in, check_out=check_out,
                                  guest_count=guest_count, **listing_kwargs)
    set_clock(checkin_clock)
    check_in_booking(env["host"]["id"], env["booking"]["id"])
    booking = complete_booking(env["host"]["id"], env["booking"]["id"])
    env["booking"] = booking
    env["payout"] = get_payout(env["host"]["id"], booking["id"])
    return env
