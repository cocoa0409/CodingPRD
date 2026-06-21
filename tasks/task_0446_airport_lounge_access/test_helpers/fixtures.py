"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims in this PRD require the system to be in a specific state
that takes several API calls to reach: create plan -> lounge -> member -> card ->
open a hold -> check in -> complete -> settle, plus clock-driven flows (no-show
sweep, day-pass expiry, year roll). These helpers encapsulate those preambles so
tests focus on assertions.

Every helper uses get_success_data() (lenient validator) internally so setup
failures surface as clear "Setup step failed" errors rather than confusing
assertion mismatches. Each test starts against an empty database (the harness
restarts the server before every test), so every fixture builds its state from
scratch using only PRD-declared endpoints.

Identity threading: LoungeAgent and Member are entity_backed roles. Any
ownership-gated agent call uses make_lounge_agent_headers(lounge["id"]) and any
ownership-gated member call uses make_member_headers(member["id"]), each with the
real entity id. NetworkAdmin is opaque, so admin-driven setup uses the shared
constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_plan_payload,
    create_lounge_payload,
    create_member_payload,
    create_card_payload,
    create_visit_payload,
    create_day_pass_payload,
    close_lounge_payload,
    create_shower_suite_payload,
    create_shower_reservation_payload,
)
from .test_users import (
    TEST_USERS,
    make_lounge_agent_headers,
    make_member_headers,
)

ADMIN = TEST_USERS["network_admin_headers"]


# ─── Clock helpers ───────────────────────────────────────────────────────────
def set_clock(iso8601: str):
    """Set the server logical clock (NetworkAdmin-only)."""
    return get_success_data(api_client.set_clock(iso8601, ADMIN))


# ─── Tier 1: base inventory ──────────────────────────────────────────────────
def create_plan(**overrides) -> dict:
    """Create a membership plan as NetworkAdmin. Returns the plan entity."""
    return get_success_data(api_client.create_plan(create_plan_payload(**overrides), ADMIN))


def create_lounge(**overrides) -> dict:
    """Create a lounge as NetworkAdmin. Returns the lounge entity."""
    return get_success_data(api_client.create_lounge(create_lounge_payload(**overrides), ADMIN))


def create_member(plan_id: str, **overrides) -> dict:
    """Enrol a member on a plan as NetworkAdmin. Returns the member entity whose
    id is used as X-User-ID for ownership-gated member actions."""
    return get_success_data(
        api_client.create_member(create_member_payload(plan_id, **overrides), ADMIN)
    )


def create_card(member_id: str, **overrides) -> dict:
    """Issue an eligibility card to a member as NetworkAdmin. Becomes active."""
    return get_success_data(
        api_client.create_card(create_card_payload(member_id, **overrides), ADMIN)
    )


def create_shower_suite(lounge_id: str, **overrides) -> dict:
    """Add a shower suite to a lounge as NetworkAdmin."""
    return get_success_data(
        api_client.create_shower_suite(create_shower_suite_payload(lounge_id, **overrides), ADMIN)
    )


def get_lounge(lounge_id: str) -> dict:
    """Fresh read of a lounge (e.g. to capture its current version)."""
    return get_success_data(api_client.get_lounge(lounge_id, ADMIN))


def get_member(member_id: str) -> dict:
    """Fresh read of a member (live usage/standing/wallet)."""
    return get_success_data(api_client.get_member(member_id, ADMIN))


# ─── Tier 2: a member ready to transact ──────────────────────────────────────
def setup_plan_lounge_member(
    plan_overrides=None,
    lounge_overrides=None,
    member_overrides=None,
    card_overrides=None,
    with_card=True,
    clock="2026-06-01T00:00:00Z",
):
    """Most common base: a plan, a lounge, a member enrolled on it, and (by
    default) an active eligibility card, with the logical clock pinned.

    Returns (plan, lounge, member, card). card is None when with_card is False.
    """
    if clock is not None:
        set_clock(clock)
    plan = create_plan(**(plan_overrides or {}))
    lounge = create_lounge(**(lounge_overrides or {}))
    member = create_member(plan["id"], **(member_overrides or {}))
    card = None
    if with_card:
        card = create_card(member["id"], **(card_overrides or {}))
    return plan, lounge, member, card


# ─── Tier 3: hold / check-in / complete lifecycle shortcuts ──────────────────
def open_hold(lounge_id, member_id=None, expected_version=None, as_admin=True, **overrides):
    """Open a HELD visit. expected_version defaults to a fresh read of the
    lounge's version. Returns the visit entity.

    When member_id is given it is included; pass guest_count / guest_names /
    day_pass_id via **overrides.
    """
    if expected_version is None:
        expected_version = get_lounge(lounge_id)["version"]
    payload = create_visit_payload(lounge_id, expected_version, **overrides)
    if member_id is not None:
        payload["member_id"] = member_id
    return get_success_data(api_client.create_visit(payload, ADMIN))


def check_in(visit_id, lounge_id):
    """Check in a held visit as the lounge agent staffing lounge_id (ownership
    threaded). Returns the checked-in visit."""
    return get_success_data(
        api_client.check_in(visit_id, make_lounge_agent_headers(lounge_id))
    )


def complete_visit(visit_id, lounge_id):
    """Complete a checked-in visit as the staffing lounge agent. Returns the
    completed visit."""
    return get_success_data(
        api_client.complete_visit(visit_id, make_lounge_agent_headers(lounge_id))
    )


def cancel_visit_as_member(visit_id, member_id):
    """Cancel a held visit as its owning member (ownership threaded)."""
    return get_success_data(
        api_client.cancel_visit(visit_id, make_member_headers(member_id))
    )


def setup_checked_in_visit(
    plan_overrides=None,
    lounge_overrides=None,
    member_overrides=None,
    card_overrides=None,
    visit_overrides=None,
    clock="2026-06-01T00:00:00Z",
):
    """Plan + lounge + member + card + a hold checked in.

    Returns (plan, lounge, member, card, visit). visit is the CHECKED_IN visit.
    """
    plan, lounge, member, card = setup_plan_lounge_member(
        plan_overrides, lounge_overrides, member_overrides, card_overrides, clock=clock
    )
    visit = open_hold(lounge["id"], member_id=member["id"], **(visit_overrides or {}))
    visit = check_in(visit["id"], lounge["id"])
    return plan, lounge, member, card, visit


def setup_completed_visit(
    plan_overrides=None,
    lounge_overrides=None,
    member_overrides=None,
    card_overrides=None,
    visit_overrides=None,
    clock="2026-06-01T00:00:00Z",
):
    """Plan + lounge + member + card + a hold checked in and completed (producing
    a PAYABLE settlement).

    Returns (plan, lounge, member, card, visit). visit is the COMPLETED visit.
    """
    plan, lounge, member, card, visit = setup_checked_in_visit(
        plan_overrides, lounge_overrides, member_overrides, card_overrides,
        visit_overrides, clock=clock,
    )
    visit = complete_visit(visit["id"], lounge["id"])
    return plan, lounge, member, card, visit


def get_settlement_for_visit(visit_id):
    """Return the single Settlement row generated by a completed visit."""
    data = get_success_data(
        api_client.list_settlements(ADMIN, params={"visit_id": visit_id})
    )
    return data[0]


# ─── Tier 4: clock-driven accrual (no-show, suspension, expiry) ──────────────
def accrue_no_show_strikes(lounge, member, count, base_clock="2026-06-01T00:00:00Z"):
    """Drive `count` no-show strikes onto a GOOD member by opening `count` holds
    and sweeping them past expiry. Each strike comes from a swept HELD->NO_SHOW.

    Returns the member entity after the sweeps. Note: when count reaches the
    suspend threshold the member flips to SUSPENDED as a side effect.
    """
    set_clock(base_clock)
    for _ in range(count):
        open_hold(lounge["id"], member_id=member["id"])
    # Advance well past the 30-minute hold TTL, then sweep.
    set_clock("2026-06-01T01:00:00Z")
    get_success_data(api_client.sweep_lounge(lounge["id"], ADMIN))
    return get_member(member["id"])


def setup_suspended_member(
    plan_overrides=None, lounge_overrides=None, member_overrides=None, card_overrides=None,
):
    """Plan + lounge + member + card, with the member driven to SUSPENDED via
    three swept no-shows.

    Returns (plan, lounge, member_after, card).
    """
    plan, lounge, member, card = setup_plan_lounge_member(
        plan_overrides or {"included_visits_per_year": 50},
        lounge_overrides, member_overrides, card_overrides,
    )
    member_after = accrue_no_show_strikes(lounge, member, 3)
    return plan, lounge, member_after, card


# ─── Tier 5: day-pass flows ──────────────────────────────────────────────────
def purchase_day_pass_for_member(lounge_id, member_id, expected_version=None, **overrides):
    """Purchase a day pass for a member (member-initiated, ownership threaded).
    Returns the day pass entity."""
    if expected_version is None:
        expected_version = get_lounge(lounge_id)["version"]
    payload = create_day_pass_payload(expected_version, member_id=member_id, **overrides)
    return get_success_data(
        api_client.purchase_day_pass(lounge_id, payload, make_member_headers(member_id))
    )


# ─── Tier 6: lounge state ────────────────────────────────────────────────────
def close_lounge(lounge_id, expected_version=None):
    """Close a lounge as NetworkAdmin (OCC-guarded). Returns the closed lounge."""
    if expected_version is None:
        expected_version = get_lounge(lounge_id)["version"]
    return get_success_data(
        api_client.close_lounge(lounge_id, close_lounge_payload(expected_version), ADMIN)
    )


# ─── Tier 7: shower amenity ──────────────────────────────────────────────────
def setup_shower_ready_visit(
    suite_overrides=None,
    clock="2026-06-01T09:00:00Z",
):
    """Plan + lounge + member + card + a checked-in visit + a shower suite at the
    same lounge — the precondition for booking a shower reservation.

    Returns (lounge, member, visit, suite).
    """
    plan, lounge, member, card = setup_plan_lounge_member(clock=clock)
    suite = create_shower_suite(lounge["id"], **(suite_overrides or {}))
    visit = open_hold(lounge["id"], member_id=member["id"])
    visit = check_in(visit["id"], lounge["id"])
    return lounge, member, visit, suite


def book_shower(suite_id, visit_id, member_id, start_at, end_at):
    """Book a shower reservation as the owning member (ownership threaded)."""
    payload = create_shower_reservation_payload(suite_id, visit_id, start_at, end_at)
    return get_success_data(
        api_client.create_shower_reservation(payload, make_member_headers(member_id))
    )
