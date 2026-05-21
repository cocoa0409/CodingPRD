"""Composite setup helpers — multi-step preambles tests can reuse.

Most interesting test claims require the system to be in a late state
that takes 5-15 API calls to reach. Each fixture composes the lower-
level steps so the test body can focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

    "The Visitor role is entity-backed: when X-User-Role is Visitor,
    the supplied X-User-ID is the id of the acting Visitor resource.
    Ownership checks on any resource that references a visitor ...
    compare the resource's visitor_id to X-User-ID, and confirm/cancel/
    accept/decline actions on a resource owned by another visitor are
    rejected with ERR_FORBIDDEN."

After a Visitor is created, fixtures MUST use make_visitor_headers(
visitor["id"]) when issuing visitor-scoped calls — never fall back to
the shared TEST_USERS["visitor_headers"] constant for ownership-gated
operations. The shared constant is reserved for tests that probe
auth/RBAC failure modes without exercising ownership.

CLOCK ANCHORING — PRD §2.13:

    "The system exposes a SystemOperator-only test-driving capability
    that advances the logical clock to a supplied target_iso instant,
    and a separate sweep capability that runs the deferred-action
    sweep at the current clock."

The logical clock is shared across all tests within the process. Each
fixture anchors deadlines to instants the test author can advance to.

Setup calls use get_success_data (a lenient 2xx validator), so a failed
setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_days,
    add_hours,
    add_minutes,
    add_seconds,
    clock_advance_payload,
    create_backcountry_permit_payload,
    create_backcountry_zone_payload,
    create_campground_payload,
    create_campground_reservation_payload,
    create_lottery_application_payload,
    create_lottery_permit_payload,
    create_park_payload,
    create_timed_entry_payload,
    create_visitor_payload,
    create_waitlist_payload,
    date_to_local_str,
    iso_utc,
    issue_pass_payload,
    parse_iso,
    utcnow,
    wallet_deposit_payload,
)
from .test_users import (
    TEST_USERS,
    make_park_admin_headers,
    make_park_ranger_headers,
    make_system_operator_headers,
    make_visitor_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.13
# ===========================================================================
# Tracks the test-process's view of the logical clock so absolute targets
# can be derived without re-querying the server every call.
_CLOCK_LOCK = threading.Lock()
_CURRENT_CLOCK: Optional[datetime] = None


def _seed_clock() -> datetime:
    """Seed the logical-clock tracker with wall-clock now on first
    access. Tests/fixtures that need an explicit anchor should call
    reset_clock_tracker_to(dt) at setup."""
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        if _CURRENT_CLOCK is None:
            _CURRENT_CLOCK = utcnow()
        return _CURRENT_CLOCK


def current_clock() -> datetime:
    return _seed_clock()


def current_clock_iso() -> str:
    return iso_utc(current_clock())


def advance_clock_to(
    target_dt: datetime,
    headers: Optional[Dict[str, str]] = None,
) -> str:
    """Advance the logical clock to target_dt.

    PRD §2.13: 'Advancing the clock does not by itself trigger any
    transitions; the sweep is what reconciles state with the new
    clock.'
    """
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        now = _CURRENT_CLOCK if _CURRENT_CLOCK is not None else utcnow()
        # Never go backwards — clamp to now if a caller passes earlier.
        if target_dt < now:
            target_dt = now
        target_iso = iso_utc(target_dt)
        resp = api_client.advance_clock(
            clock_advance_payload(target_iso),
            headers or TEST_USERS["system_operator_headers"],
        )
        get_success_data(resp)
        _CURRENT_CLOCK = target_dt
    return target_iso


def advance_clock_by_seconds(seconds: int,
                             headers: Optional[Dict[str, str]] = None) -> str:
    return advance_clock_to(
        current_clock() + timedelta(seconds=seconds), headers,
    )


def advance_clock_by_minutes(minutes: int,
                             headers: Optional[Dict[str, str]] = None) -> str:
    return advance_clock_to(
        current_clock() + timedelta(minutes=minutes), headers,
    )


def advance_clock_by_hours(hours: float,
                           headers: Optional[Dict[str, str]] = None) -> str:
    return advance_clock_to(
        current_clock() + timedelta(hours=hours), headers,
    )


def advance_clock_by_days(days: int,
                          headers: Optional[Dict[str, str]] = None) -> str:
    return advance_clock_to(
        current_clock() + timedelta(days=days), headers,
    )


def run_sweep(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §2.13: 'a separate sweep capability that runs the deferred-
    action sweep at the current clock'."""
    resp = api_client.run_sweep(
        headers or TEST_USERS["system_operator_headers"],
    )
    return get_success_data(resp)


def reset_clock_tracker_to(dt: datetime) -> None:
    """Force the test-process's clock tracker to dt. Used by conftest
    between tests so absolute timestamps stay anchored to a known clock.
    """
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        _CURRENT_CLOCK = dt


# ===========================================================================
# Visitor / wallet primitives — PRD §3.1
# ===========================================================================
def create_visitor(
    full_name: Optional[str] = None,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.1: 'A visitor enters the system as a Visitor record
    minted by a SystemOperator.'"""
    payload = create_visitor_payload()
    if full_name is not None:
        payload["full_name"] = full_name
    if email is not None:
        payload["email"] = email
    resp = api_client.create_visitor(
        payload, TEST_USERS["system_operator_headers"],
    )
    return get_success_data(resp)


def deposit_wallet(visitor_id: str, amount_cents: int) -> Dict[str, Any]:
    """PRD §3.1: 'a SystemOperator tops up any visitor's wallet'."""
    resp = api_client.deposit_wallet(
        visitor_id,
        wallet_deposit_payload(amount_cents),
        TEST_USERS["system_operator_headers"],
    )
    return get_success_data(resp)


def create_visitor_with_wallet(
    wallet_cents: int = 100_000,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a Visitor and credit their wallet so confirm/accept calls
    have funds available."""
    visitor = create_visitor(full_name=full_name, email=email)
    if wallet_cents > 0:
        deposit_wallet(visitor["id"], wallet_cents)
    visitor = get_visitor(visitor["id"])
    return visitor


def get_visitor(visitor_id: str) -> Dict[str, Any]:
    """Read a visitor with their current computed wallet/strike counts.

    PRD §2.1 makes Visitor entity-backed, so ownership is verified —
    fetch as the SystemOperator to bypass ownership checks.
    """
    resp = api_client.get_visitor(
        visitor_id, TEST_USERS["system_operator_headers"],
    )
    return get_success_data(resp)


def list_visitor_ledger(visitor_id: str) -> List[Dict[str, Any]]:
    resp = api_client.list_visitor_ledger(
        visitor_id, TEST_USERS["system_operator_headers"],
    )
    body = resp.json()
    return list(body.get("data") or [])


# ===========================================================================
# Pass primitives — PRD §3.1
# ===========================================================================
def issue_pass(
    visitor_id: str,
    pass_type: str = "ANNUAL",
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.1: 'A ParkAdmin may issue an America the Beautiful Pass
    to a visitor.'"""
    resp = api_client.issue_pass(
        visitor_id,
        issue_pass_payload(
            pass_type=pass_type,
            valid_from=valid_from,
            valid_until=valid_until,
        ),
        TEST_USERS["park_admin_headers"],
    )
    return get_success_data(resp)


def revoke_pass(visitor_id: str, pass_id: str) -> Dict[str, Any]:
    """PRD §3.1: 'The ParkAdmin may also revoke an active pass'."""
    resp = api_client.revoke_pass(
        visitor_id, pass_id, TEST_USERS["park_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Park primitives — PRD §3.2, §2.7
# ===========================================================================
def create_park(**overrides) -> Dict[str, Any]:
    """PRD §3.2: 'A ParkAdmin provisions a park'."""
    resp = api_client.create_park(
        create_park_payload(**overrides), TEST_USERS["park_admin_headers"],
    )
    return get_success_data(resp)


def freeze_park(park_id: str) -> Dict[str, Any]:
    """PRD §2.7: 'Only a ParkAdmin may move a park between these statuses.'
    """
    resp = api_client.freeze_park(park_id, TEST_USERS["park_admin_headers"])
    return get_success_data(resp)


def restrict_park(park_id: str) -> Dict[str, Any]:
    resp = api_client.restrict_park(
        park_id, TEST_USERS["park_admin_headers"],
    )
    return get_success_data(resp)


def reopen_park(park_id: str) -> Dict[str, Any]:
    resp = api_client.reopen_park(park_id, TEST_USERS["park_admin_headers"])
    return get_success_data(resp)


def get_park(park_id: str) -> Dict[str, Any]:
    resp = api_client.get_park(park_id, TEST_USERS["park_admin_headers"])
    return get_success_data(resp)


# ===========================================================================
# Campground primitives — PRD §3.2
# ===========================================================================
def create_campground(park_id: str, **overrides) -> Dict[str, Any]:
    resp = api_client.create_campground(
        park_id,
        create_campground_payload(**overrides),
        TEST_USERS["park_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Backcountry zone primitives — PRD §3.2
# ===========================================================================
def create_backcountry_zone(park_id: str, **overrides) -> Dict[str, Any]:
    resp = api_client.create_backcountry_zone(
        park_id,
        create_backcountry_zone_payload(**overrides),
        TEST_USERS["park_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Lottery permit primitives — PRD §3.2, §3.6
# ===========================================================================
def create_lottery_permit(park_id: str, **overrides) -> Dict[str, Any]:
    resp = api_client.create_lottery_permit(
        park_id,
        create_lottery_permit_payload(**overrides),
        TEST_USERS["park_admin_headers"],
    )
    return get_success_data(resp)


def submit_lottery_application(
    permit_id: str, visitor: Dict[str, Any], party_size: int = 2,
) -> Dict[str, Any]:
    """PRD §3.6: 'A Visitor applies to a lottery permit'."""
    resp = api_client.create_lottery_application(
        permit_id,
        create_lottery_application_payload(party_size=party_size),
        make_visitor_headers(visitor["id"]),
    )
    return get_success_data(resp)


def draw_lottery(permit_id: str) -> Dict[str, Any]:
    """PRD §3.6: 'triggered either by a ParkAdmin or SystemOperator
    calling the draw capability'."""
    resp = api_client.draw_lottery(
        permit_id, TEST_USERS["park_admin_headers"],
    )
    return get_success_data(resp)


def get_lottery_application(application_id: str) -> Dict[str, Any]:
    """Read by listing — fetch the parent permit's applications and
    locate by id. Used because the PRD §4 endpoint table exposes a list
    endpoint but not a singleton GET; SystemOperator may list anywhere.
    """
    # We listed via the permit; tests typically have the permit_id but
    # fall back to scanning if needed. Most callers pass permit_id
    # directly — see list_lottery_applications below.
    raise NotImplementedError(
        "use list_lottery_applications(permit_id) and filter by id"
    )


def list_lottery_applications(permit_id: str) -> List[Dict[str, Any]]:
    resp = api_client.list_lottery_applications(
        permit_id, TEST_USERS["park_admin_headers"],
    )
    body = resp.json()
    return list(body.get("data") or [])


def find_lottery_application(permit_id: str,
                             application_id: str) -> Dict[str, Any]:
    """Locate a specific application by id via the permit's list."""
    for app in list_lottery_applications(permit_id):
        if app.get("id") == application_id:
            return app
    raise AssertionError(
        f"Setup failed: application {application_id} not found under permit "
        f"{permit_id}"
    )


# ===========================================================================
# Reservation primitives — PRD §3.3, §3.4, §3.7
# ===========================================================================
def create_timed_entry(park_id: str, visitor: Dict[str, Any],
                       **payload_overrides) -> Dict[str, Any]:
    resp = api_client.create_timed_entry(
        park_id,
        create_timed_entry_payload(**payload_overrides),
        make_visitor_headers(visitor["id"]),
    )
    return get_success_data(resp)


def confirm_timed_entry(park_id: str, reservation_id: str,
                        visitor: Dict[str, Any]) -> Dict[str, Any]:
    resp = api_client.confirm_timed_entry(
        park_id, reservation_id, make_visitor_headers(visitor["id"]),
    )
    return get_success_data(resp)


def cancel_timed_entry(park_id: str, reservation_id: str,
                       visitor: Dict[str, Any]) -> Dict[str, Any]:
    resp = api_client.cancel_timed_entry(
        park_id, reservation_id, make_visitor_headers(visitor["id"]),
    )
    return get_success_data(resp)


def create_campground_reservation(
    campground_id: str,
    visitor: Dict[str, Any],
    **payload_overrides,
) -> Dict[str, Any]:
    resp = api_client.create_campground_reservation(
        campground_id,
        create_campground_reservation_payload(**payload_overrides),
        make_visitor_headers(visitor["id"]),
    )
    return get_success_data(resp)


def confirm_campground_reservation(
    campground_id: str,
    reservation_id: str,
    visitor: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.confirm_campground_reservation(
        campground_id, reservation_id, make_visitor_headers(visitor["id"]),
    )
    return get_success_data(resp)


def cancel_campground_reservation(
    campground_id: str,
    reservation_id: str,
    visitor: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.cancel_campground_reservation(
        campground_id, reservation_id, make_visitor_headers(visitor["id"]),
    )
    return get_success_data(resp)


def create_backcountry_permit(zone_id: str, visitor: Dict[str, Any],
                              **payload_overrides) -> Dict[str, Any]:
    resp = api_client.create_backcountry_permit(
        zone_id,
        create_backcountry_permit_payload(**payload_overrides),
        make_visitor_headers(visitor["id"]),
    )
    return get_success_data(resp)


def confirm_backcountry_permit(zone_id: str, permit_id: str,
                               visitor: Dict[str, Any]) -> Dict[str, Any]:
    resp = api_client.confirm_backcountry_permit(
        zone_id, permit_id, make_visitor_headers(visitor["id"]),
    )
    return get_success_data(resp)


def cancel_backcountry_permit(zone_id: str, permit_id: str,
                              visitor: Dict[str, Any]) -> Dict[str, Any]:
    resp = api_client.cancel_backcountry_permit(
        zone_id, permit_id, make_visitor_headers(visitor["id"]),
    )
    return get_success_data(resp)


def create_waitlist_entry(campground_id: str, visitor: Dict[str, Any],
                          **payload_overrides) -> Dict[str, Any]:
    resp = api_client.create_waitlist_entry(
        campground_id,
        create_waitlist_payload(**payload_overrides),
        make_visitor_headers(visitor["id"]),
    )
    return get_success_data(resp)


def list_waitlist(campground_id: str) -> List[Dict[str, Any]]:
    resp = api_client.list_waitlist(
        campground_id, TEST_USERS["park_admin_headers"],
    )
    body = resp.json()
    return list(body.get("data") or [])


def list_campground_reservations(campground_id: str) -> List[Dict[str, Any]]:
    resp = api_client.list_campground_reservations(
        campground_id, TEST_USERS["park_admin_headers"],
    )
    body = resp.json()
    return list(body.get("data") or [])


# ===========================================================================
# Tier 2 — Park + visitor scenario builders
# ===========================================================================
def setup_open_park() -> Dict[str, Any]:
    """PRD §3.2: 'A newly created park starts in the OPEN status.'"""
    return create_park()


def setup_park_with_campground(
    **campground_overrides,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Park OPEN + one Campground. Returns (park, campground)."""
    park = setup_open_park()
    campground = create_campground(park["id"], **campground_overrides)
    return park, campground


def setup_park_with_backcountry_zone(
    **zone_overrides,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Park OPEN + one BackcountryZone. Returns (park, zone)."""
    park = setup_open_park()
    zone = create_backcountry_zone(park["id"], **zone_overrides)
    return park, zone


def setup_park_with_lottery_permit(
    **permit_overrides,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Park OPEN + one LotteryPermit. Returns (park, permit)."""
    park = setup_open_park()
    permit = create_lottery_permit(park["id"], **permit_overrides)
    return park, permit


# ===========================================================================
# Tier 3 — confirmed reservations / permits
# ===========================================================================
def setup_confirmed_campground_reservation(
    site_kind: str = "STANDARD",
    party_size: int = 2,
    nights: int = 2,
    days_out: int = 30,
    wallet_cents: int = 100_000,
    campground_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Create park + campground + funded visitor, hold + confirm
    a campground reservation. Returns (park, campground, visitor,
    reservation).

    PRD §3.4: 'Confirming a HELD campground reservation requires that
    the reservation still be in HELD ... the wallet is debited by
    total_fee_cents, and a LedgerEntry of kind FEE_CHARGE is appended.'
    """
    park, campground = setup_park_with_campground(
        **(campground_overrides or {}),
    )
    visitor = create_visitor_with_wallet(wallet_cents)
    check_in = date.today() + timedelta(days=days_out)
    check_out = check_in + timedelta(days=nights)
    reservation = create_campground_reservation(
        campground["id"], visitor,
        site_kind=site_kind,
        party_size=party_size,
        check_in_date_local=date_to_local_str(check_in),
        check_out_date_local=date_to_local_str(check_out),
    )
    confirmed = confirm_campground_reservation(
        campground["id"], reservation["id"], visitor,
    )
    return park, campground, visitor, confirmed


def setup_confirmed_timed_entry(
    days_out: int = 5,
    window_start_local: str = "09:00",
    wallet_cents: int = 10_000,
    pass_id: Optional[str] = None,
    park_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Park OPEN + funded visitor + confirmed timed-entry.
    Returns (park, visitor, reservation).
    """
    park = create_park(**(park_overrides or {}))
    visitor = create_visitor_with_wallet(wallet_cents)
    entry_date = date.today() + timedelta(days=days_out)
    held = create_timed_entry(
        park["id"], visitor,
        entry_date_local=date_to_local_str(entry_date),
        window_start_local=window_start_local,
        pass_id=pass_id,
    )
    confirmed = confirm_timed_entry(park["id"], held["id"], visitor)
    return park, visitor, confirmed


def setup_confirmed_backcountry_permit(
    party_size: int = 2,
    entry_hours_out: float = 240.0,
    nights: int = 1,
    wallet_cents: int = 50_000,
    zone_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Park OPEN + zone + funded visitor + confirmed backcountry permit.
    Returns (park, zone, visitor, permit).
    """
    park, zone = setup_park_with_backcountry_zone(
        **(zone_overrides or {}),
    )
    visitor = create_visitor_with_wallet(wallet_cents)
    entry = utcnow() + timedelta(hours=entry_hours_out)
    exit_dt = entry + timedelta(days=nights)
    held = create_backcountry_permit(
        zone["id"], visitor,
        party_size=party_size,
        entry_datetime_local=iso_utc(entry),
        exit_datetime_local=iso_utc(exit_dt),
    )
    confirmed = confirm_backcountry_permit(zone["id"], held["id"], visitor)
    return park, zone, visitor, confirmed


# ===========================================================================
# Tier 4 — accumulation / threshold targeting
# ===========================================================================
def setup_visitor_with_lottery_strikes(
    target_strikes: int,
    wallet_cents: int = 100_000,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build a Visitor whose lottery_strikes counter equals target_strikes.

    Strategy per PRD §3.6: each AWARDED application that expires past
    award_expires_at increments lottery_strikes by one via the sweep.
    We construct N short-window lotteries, submit one application
    each, draw, then advance past the 72h award_expires_at and run the
    sweep — accumulating one strike per loop.

    PRD §3.1: "Strikes accumulate across the calendar year and may reach 3".
    PRD §3.6: "When award_expires_at has passed on an AWARDED application,
    the sweep transitions it from AWARDED to FORFEITED, increments the
    visitor's lottery_strikes by one".

    Returns (park, visitor). The park is reused across all N lottery
    permits; the visitor's wallet is large enough to cover application
    fees.
    """
    if target_strikes < 0 or target_strikes > 3:
        raise AssertionError(
            f"Setup failed: target_strikes {target_strikes} out of 0..3"
        )
    park = setup_open_park()
    visitor = create_visitor_with_wallet(wallet_cents)
    for _ in range(target_strikes):
        # PRD §3.6: lottery_open_at must be in the past, lottery_close_at
        # must be in the future at submission time.
        now = current_clock()
        permit = create_lottery_permit(
            park["id"],
            lottery_open_at=iso_utc(now - timedelta(hours=1)),
            lottery_close_at=iso_utc(now + timedelta(hours=1)),
            draw_at=iso_utc(now + timedelta(hours=2)),
            hike_date=iso_utc(now + timedelta(days=30)),
            daily_slot_count=10,
            application_fee_cents=100,
            permit_fee_cents=100,
        )
        submit_lottery_application(permit["id"], visitor, party_size=1)
        # Advance just past lottery_close_at, then draw and let the
        # award sit unaccepted past award_expires_at.
        advance_clock_to(now + timedelta(hours=2, minutes=1))
        draw_lottery(permit["id"])
        # PRD §3.6: "award_expires_at to 72 hours after draw_at."
        advance_clock_by_hours(73)
        run_sweep()
    visitor = get_visitor(visitor["id"])
    return park, visitor


def setup_at_capacity_campground(
    standard_site_count: int = 1,
    nights: int = 2,
    days_out: int = 30,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any],
]:
    """Park OPEN + Campground with standard_site_count standard sites,
    fully filled by holder Visitor V_holder over the requested date
    range. Returns (park, campground, holder, holder_reservation,
    waitlister_visitor).

    The returned waitlister_visitor is funded but has no reservation
    yet — tests can use them to attempt a competing booking, join the
    waitlist, etc.
    """
    park, campground = setup_park_with_campground(
        standard_site_count=standard_site_count,
        group_site_count=2,
    )
    holder = create_visitor_with_wallet(wallet_cents=100_000)
    waitlister = create_visitor_with_wallet(wallet_cents=100_000)
    check_in = date.today() + timedelta(days=days_out)
    check_out = check_in + timedelta(days=nights)
    holder_reservations: List[Dict[str, Any]] = []
    for _ in range(standard_site_count):
        # Bigger party_size collisions don't happen across reservations;
        # we just need to exhaust the count.
        r = create_campground_reservation(
            campground["id"], holder,
            site_kind="STANDARD",
            party_size=2,
            check_in_date_local=date_to_local_str(check_in),
            check_out_date_local=date_to_local_str(check_out),
        )
        confirmed = confirm_campground_reservation(
            campground["id"], r["id"], holder,
        )
        holder_reservations.append(confirmed)
    return park, campground, holder, holder_reservations[0], waitlister


# ===========================================================================
# Tier 4 — backcountry overlap fixtures (difficulty-design rule 2 / 8)
# ===========================================================================
def setup_confirmed_backcountry_with_window(
    entry_dt: datetime,
    exit_dt: datetime,
    party_size: int = 2,
    wallet_cents: int = 50_000,
    zone_overrides: Optional[Dict[str, Any]] = None,
    park: Optional[Dict[str, Any]] = None,
    zone: Optional[Dict[str, Any]] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Create a confirmed backcountry permit pinned to an exact
    [entry_dt, exit_dt) window. Returns (park, zone, visitor, permit).
    Reuses provided park/zone if supplied.
    """
    if park is None or zone is None:
        park, zone = setup_park_with_backcountry_zone(
            **(zone_overrides or {}),
        )
    visitor = create_visitor_with_wallet(wallet_cents)
    held = create_backcountry_permit(
        zone["id"], visitor,
        party_size=party_size,
        entry_datetime_local=iso_utc(entry_dt),
        exit_datetime_local=iso_utc(exit_dt),
    )
    confirmed = confirm_backcountry_permit(zone["id"], held["id"], visitor)
    return park, zone, visitor, confirmed


# ===========================================================================
# Tier 5 — Difficulty-design specific composite fixtures
# ===========================================================================
def setup_two_campground_reservations_for_refund_variant(
    days_out: int = 30,
    nightly_standard_fee_cents: int = 3500,
    nightly_group_fee_cents: int = 12000,
    group_party_size: int = 10,
    group_nights: int = 3,
    standard_party_size: int = 2,
    standard_nights: int = 2,
) -> Tuple[
    Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any],
]:
    """Sets up the dual_variant_calc / campground_refund instance:
    one CONFIRMED STANDARD reservation by V1 (cheap) and one CONFIRMED
    GROUP reservation by V2 (expensive), both ready for cancel at
    >= 336h out — so the PRD §3.4 'fourteen-day' branch fires on each.

    PRD §3.4 fees: STANDARD nightly 3500, GROUP nightly 12000, fixed
    booking fee 800, tax 0.08 on the pre-tax subtotal floored after
    multiplication.

    Returns (park, campground, v1, r_std, v2, r_grp).
    """
    park, campground = setup_park_with_campground(
        standard_site_count=5,
        group_site_count=5,
        nightly_standard_fee_cents=nightly_standard_fee_cents,
        nightly_group_fee_cents=nightly_group_fee_cents,
        max_consecutive_nights=14,
    )
    v1 = create_visitor_with_wallet(wallet_cents=200_000)
    v2 = create_visitor_with_wallet(wallet_cents=200_000)
    check_in_std = date.today() + timedelta(days=days_out)
    check_out_std = check_in_std + timedelta(days=standard_nights)
    r_std_held = create_campground_reservation(
        campground["id"], v1,
        site_kind="STANDARD",
        party_size=standard_party_size,
        check_in_date_local=date_to_local_str(check_in_std),
        check_out_date_local=date_to_local_str(check_out_std),
    )
    r_std = confirm_campground_reservation(
        campground["id"], r_std_held["id"], v1,
    )
    check_in_grp = date.today() + timedelta(days=days_out + 1)
    check_out_grp = check_in_grp + timedelta(days=group_nights)
    r_grp_held = create_campground_reservation(
        campground["id"], v2,
        site_kind="GROUP",
        party_size=group_party_size,
        check_in_date_local=date_to_local_str(check_in_grp),
        check_out_date_local=date_to_local_str(check_out_grp),
    )
    r_grp = confirm_campground_reservation(
        campground["id"], r_grp_held["id"], v2,
    )
    return park, campground, v1, r_std, v2, r_grp


def setup_pass_waived_vs_paid_timed_entries(
    days_out: int = 10,
    timed_entry_window_minutes: int = 60,
    timed_entry_daily_capacity: int = 10,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """For the dual_variant_calc / timed_entry_refund instance: two
    CONFIRMED timed-entry reservations on the same park — one pass-
    waived (entry_fee_cents=0) and one paid (entry_fee_cents>0).

    Returns (park, v1_with_pass, pass_, v2_no_pass, r_pass, r_paid).
    """
    park = create_park(
        timed_entry_window_minutes=timed_entry_window_minutes,
        timed_entry_daily_capacity=timed_entry_daily_capacity,
    )
    # V1 holds an ANNUAL pass that is ACTIVE at entry_date_local.
    v1 = create_visitor_with_wallet(wallet_cents=10_000)
    pass_ = issue_pass(
        v1["id"], pass_type="ANNUAL",
        valid_from=iso_utc(utcnow() - timedelta(days=1)),
        valid_until=iso_utc(utcnow() + timedelta(days=365)),
    )
    # V2 has no pass and must pay the full entry fee. Implementations
    # decide the standard entry fee — tests will read entry_fee_cents
    # off the persisted reservation rather than predicting it.
    v2 = create_visitor_with_wallet(wallet_cents=10_000)
    entry_date = date.today() + timedelta(days=days_out)
    r_pass_held = create_timed_entry(
        park["id"], v1,
        entry_date_local=date_to_local_str(entry_date),
        window_start_local="09:00",
        pass_id=pass_["id"],
    )
    r_pass = confirm_timed_entry(park["id"], r_pass_held["id"], v1)
    r_paid_held = create_timed_entry(
        park["id"], v2,
        entry_date_local=date_to_local_str(entry_date),
        window_start_local="10:00",
    )
    r_paid = confirm_timed_entry(park["id"], r_paid_held["id"], v2)
    return park, v1, pass_, v2, r_pass, r_paid


def setup_lottery_with_three_applications(
    daily_slot_count: int = 5,
    application_fee_cents: int = 1000,
    permit_fee_cents: int = 5000,
    per_application_max_party: int = 12,
) -> Tuple[
    Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Setup the non_linear_state_machine / lottery_application_branching
    instance. PRD §3.6 ranks by rank_seed ASC — but rank_seed is system-
    minted, so deterministic rank ordering must be coerced by submitting
    applications in the order we want the rank to fall. The test asserts
    AWARDED/WAITLISTED branching based on remaining-slot vs. party_size
    arithmetic, which is independent of which application gets which
    seed — what matters is exact slot consumption.

    Returns (park, permit, v1, v2, v3, a1, a2, a3).
    """
    # Anchor open/close to the test-process clock tracker (which mirrors
    # the implementation's logical clock), not wall-clock — previous
    # tests may have advanced the server clock arbitrarily forward.
    now = current_clock()
    park, permit = setup_park_with_lottery_permit(
        daily_slot_count=daily_slot_count,
        application_fee_cents=application_fee_cents,
        permit_fee_cents=permit_fee_cents,
        per_application_max_party=per_application_max_party,
        # Make sure submission times sit inside [open, close).
        lottery_open_at=iso_utc(now - timedelta(hours=1)),
        lottery_close_at=iso_utc(now + timedelta(hours=2)),
        draw_at=iso_utc(now + timedelta(hours=3)),
        hike_date=iso_utc(now + timedelta(days=10)),
    )
    v1 = create_visitor_with_wallet(wallet_cents=100_000)
    v2 = create_visitor_with_wallet(wallet_cents=100_000)
    v3 = create_visitor_with_wallet(wallet_cents=100_000)
    a1 = submit_lottery_application(permit["id"], v1, party_size=3)
    a2 = submit_lottery_application(permit["id"], v2, party_size=4)
    a3 = submit_lottery_application(permit["id"], v3, party_size=2)
    return park, permit, v1, v2, v3, a1, a2, a3


# ===========================================================================
# Helpers for reading ledger / reservation state
# ===========================================================================
def get_campground_reservation(campground_id: str,
                               reservation_id: str) -> Dict[str, Any]:
    """Read a reservation by listing the campground's reservations
    and filtering by id. PRD §4 exposes a list endpoint but not a
    singleton GET — admin/ranger list is the supported lookup path.
    """
    for r in list_campground_reservations(campground_id):
        if r.get("id") == reservation_id:
            return r
    raise AssertionError(
        f"Setup failed: campground reservation {reservation_id} not found "
        f"under campground {campground_id}"
    )


def find_held_promoted_reservation(
    campground_id: str, visitor_id: str,
) -> Optional[Dict[str, Any]]:
    """Locate the HELD reservation created by waitlist promotion for a
    particular visitor on a campground."""
    for r in list_campground_reservations(campground_id):
        if r.get("visitor_id") == visitor_id and r.get("status") == "HELD":
            return r
    return None


__all__ = [
    # clock
    "current_clock", "current_clock_iso",
    "advance_clock_to", "advance_clock_by_seconds",
    "advance_clock_by_minutes", "advance_clock_by_hours",
    "advance_clock_by_days", "reset_clock_tracker_to",
    "run_sweep",
    # visitor / wallet
    "create_visitor", "deposit_wallet", "create_visitor_with_wallet",
    "get_visitor", "list_visitor_ledger",
    # pass
    "issue_pass", "revoke_pass",
    # park
    "create_park", "freeze_park", "restrict_park", "reopen_park", "get_park",
    "setup_open_park",
    # campground
    "create_campground",
    "create_campground_reservation",
    "confirm_campground_reservation",
    "cancel_campground_reservation",
    "create_waitlist_entry",
    "list_waitlist",
    "list_campground_reservations",
    "get_campground_reservation",
    "find_held_promoted_reservation",
    # backcountry
    "create_backcountry_zone", "create_backcountry_permit",
    "confirm_backcountry_permit", "cancel_backcountry_permit",
    "setup_confirmed_backcountry_with_window",
    # timed entry
    "create_timed_entry", "confirm_timed_entry", "cancel_timed_entry",
    # lottery
    "create_lottery_permit", "submit_lottery_application", "draw_lottery",
    "list_lottery_applications", "find_lottery_application",
    # composite tier 2
    "setup_park_with_campground",
    "setup_park_with_backcountry_zone",
    "setup_park_with_lottery_permit",
    # composite tier 3
    "setup_confirmed_campground_reservation",
    "setup_confirmed_timed_entry",
    "setup_confirmed_backcountry_permit",
    # tier 4
    "setup_visitor_with_lottery_strikes",
    "setup_at_capacity_campground",
    # tier 5 — difficulty-design composites
    "setup_two_campground_reservations_for_refund_variant",
    "setup_pass_waived_vs_paid_timed_entries",
    "setup_lottery_with_three_applications",
]
