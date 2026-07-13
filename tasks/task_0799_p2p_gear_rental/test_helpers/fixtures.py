"""Composite setup helpers.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the harness restarts the server and wipes the DB before each test). Helpers use
get_success_data() so setup failures surface as clear "Setup failed" errors.

Ownership threading: Owner/Renter are entity-backed, so any ownership-gated call
uses make_owner_headers(owner_id) / make_renter_headers(renter_id) with the real
User id — never a shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .factories import (
    create_user_payload, create_verification_payload, create_listing_payload,
    create_booking_payload, create_handoff_payload, create_condition_report_payload,
    create_claim_payload,
)
from .test_users import make_owner_headers, make_renter_headers, platform_headers


def _date_part(iso: str) -> str:
    return iso[:10]


def _slot(iso: str, start="T09:00:00Z", end="T09:30:00Z"):
    d = _date_part(iso)
    return d + start, d + end


# --- Primitives --------------------------------------------------------------

def register_user(api, **overrides) -> dict:
    resp = api.create_user(create_user_payload(**overrides))
    return get_success_data(resp)


def create_owner(api, **overrides) -> dict:
    return register_user(api, **overrides)


def create_verified_renter(api, **overrides) -> dict:
    """Register a user and drive them to verification_status VERIFIED."""
    renter = register_user(api, **overrides)
    rid = renter["id"]
    rhead = make_renter_headers(rid)
    ver = get_success_data(
        api.create_verification(rid, create_verification_payload(), rhead)
    )
    api.decide_verification(ver["id"], {"decision": "APPROVE"}, platform_headers())
    # Re-fetch for the updated verification_status.
    return get_success_data(api.get_user(rid, platform_headers()))


def create_draft_listing(api, owner_id, **overrides) -> dict:
    return get_success_data(
        api.create_listing(create_listing_payload(owner_id, **overrides),
                           make_owner_headers(owner_id))
    )


def create_active_listing(api, owner_id, **overrides) -> dict:
    listing = create_draft_listing(api, owner_id, **overrides)
    return get_success_data(
        api.activate_listing(listing["id"], make_owner_headers(owner_id))
    )


def current_listing_version(api, listing_id, headers) -> int:
    return get_success_data(api.get_listing(listing_id, headers))["version"]


def create_requested_booking(api, listing_id, renter_id, start_date, end_date,
                             expected_listing_version=None) -> dict:
    rhead = make_renter_headers(renter_id)
    if expected_listing_version is None:
        expected_listing_version = current_listing_version(api, listing_id, rhead)
    payload = create_booking_payload(
        listing_id, renter_id, start_date, end_date, expected_listing_version
    )
    return get_success_data(api.create_booking(payload, rhead))


def schedule_and_complete_handoff(api, booking_id, owner_id, htype, slot_start, slot_end) -> dict:
    ohead = make_owner_headers(owner_id)
    h = get_success_data(
        api.create_handoff(booking_id, create_handoff_payload(htype, slot_start, slot_end), ohead)
    )
    api.complete_handoff(h["id"], ohead)
    return h


def add_condition_report(api, booking_id, owner_id, phase) -> dict:
    ohead = make_owner_headers(owner_id)
    return get_success_data(
        api.create_condition_report(booking_id, create_condition_report_payload(phase), ohead)
    )


# --- Composite scenarios -----------------------------------------------------

def setup_active_booking(api, *, base_daily_rate_cents=10000, deposit_cents=50000,
                         declared_value_cents=90000, quantity=1, demand_multiplier_bps=None,
                         start_date="2026-06-01T00:00:00Z", end_date="2026-06-08T00:00:00Z") -> dict:
    """Verified renter + ACTIVE listing + booking driven through pickup to ACTIVE.

    Returns a scenario dict with owner/renter/listing/booking and their headers.
    """
    owner = create_owner(api)
    renter = create_verified_renter(api)
    listing_overrides = dict(
        base_daily_rate_cents=base_daily_rate_cents,
        deposit_cents=deposit_cents,
        declared_value_cents=declared_value_cents,
        quantity=quantity,
    )
    if demand_multiplier_bps is not None:
        listing_overrides["demand_multiplier_bps"] = demand_multiplier_bps
    listing = create_active_listing(api, owner["id"], **listing_overrides)

    ohead = make_owner_headers(owner["id"])
    booking = create_requested_booking(api, listing["id"], renter["id"], start_date, end_date)
    api.approve_booking(booking["id"], ohead)

    ps, pe = _slot(start_date)
    schedule_and_complete_handoff(api, booking["id"], owner["id"], "PICKUP", ps, pe)
    add_condition_report(api, booking["id"], owner["id"], "PICKUP")
    booking = get_success_data(api.pickup_booking(booking["id"], ohead))

    return {
        "owner": owner, "renter": renter, "listing": listing, "booking": booking,
        "owner_id": owner["id"], "renter_id": renter["id"],
        "listing_id": listing["id"], "booking_id": booking["id"],
        "owner_headers": ohead, "renter_headers": make_renter_headers(renter["id"]),
    }


def setup_returned_booking(api, *, base_daily_rate_cents=10000, deposit_cents=50000,
                           declared_value_cents=90000, quantity=1,
                           start_date="2026-06-01T00:00:00Z", end_date="2026-06-08T00:00:00Z",
                           late_to=None) -> dict:
    """Drive a booking all the way to RETURNED (creating the Deposit and Payout).

    If ``late_to`` (ISO instant) is given, advance the clock and run the late sweep
    so the booking passes through LATE before return.
    Returns the active-booking scenario dict augmented with deposit and payout data.
    """
    sc = setup_active_booking(
        api, base_daily_rate_cents=base_daily_rate_cents, deposit_cents=deposit_cents,
        declared_value_cents=declared_value_cents, quantity=quantity,
        start_date=start_date, end_date=end_date,
    )
    booking_id = sc["booking_id"]
    owner_id = sc["owner_id"]
    ohead = sc["owner_headers"]

    return_anchor = end_date
    if late_to is not None:
        api.set_clock({"to_iso8601": late_to}, platform_headers())
        api.detect_late_returns(platform_headers())
        return_anchor = late_to

    rs, re = _slot(return_anchor)
    schedule_and_complete_handoff(api, booking_id, owner_id, "RETURN", rs, re)
    add_condition_report(api, booking_id, owner_id, "RETURN")
    booking = get_success_data(api.return_booking(booking_id, ohead))

    deposit = get_success_data(api.get_deposit(booking_id, ohead))[0]
    payout = get_success_data(api.get_payout(booking_id, ohead))[0]
    sc.update({"booking": booking, "deposit": deposit, "payout": payout,
               "payout_id": payout["id"]})
    return sc


def setup_open_claim(api, *, claimed_amount_cents=30000, claim_type="DAMAGE",
                     deposit_cents=50000, declared_value_cents=90000,
                     late_to=None, **overrides) -> dict:
    """Returned booking + one OPEN claim. Returns scenario dict incl claim + deposit_version."""
    sc = setup_returned_booking(api, deposit_cents=deposit_cents,
                                declared_value_cents=declared_value_cents,
                                late_to=late_to, **overrides)
    owner_id = sc["owner_id"]
    ohead = sc["owner_headers"]
    claim = get_success_data(
        api.create_claim(sc["booking_id"],
                         create_claim_payload(claim_type, claimed_amount_cents), ohead)
    )
    deposit = get_success_data(api.get_deposit(sc["booking_id"], ohead))[0]
    sc.update({"claim": claim, "claim_id": claim["id"], "deposit": deposit,
               "deposit_version": deposit["version"]})
    return sc


def setup_claim_under_review(api, *, claimed_amount_cents=30000, claim_type="DAMAGE",
                             deposit_cents=50000, declared_value_cents=90000,
                             late_to=None, **overrides) -> dict:
    """Returned booking + one claim moved to UNDER_REVIEW. Returns scenario dict
    with claim_id and the current deposit_version (for the OCC-guarded resolve)."""
    sc = setup_open_claim(api, claimed_amount_cents=claimed_amount_cents,
                          claim_type=claim_type, deposit_cents=deposit_cents,
                          declared_value_cents=declared_value_cents,
                          late_to=late_to, **overrides)
    api.review_claim(sc["claim_id"], platform_headers())
    deposit = get_success_data(api.get_deposit(sc["booking_id"], sc["owner_headers"]))[0]
    sc["deposit"] = deposit
    sc["deposit_version"] = deposit["version"]
    return sc
