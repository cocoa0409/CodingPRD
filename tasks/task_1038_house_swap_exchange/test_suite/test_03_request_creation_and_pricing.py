"""Opening an exchange request: preconditions, ordered validation, points pricing,
and the settled-vs-available balance divergence created by the hold.
"""
from test_helpers import (
    validate_success, validate_error,
    create_exchange_request_payload,
    make_admin_headers,
    set_clock, register_member, subscribe_and_activate, verify_identity,
    create_active_listing, create_draft_listing, add_window, adjust_points,
    open_points_request, get_member,
    make_member_headers,
)

ADMIN = make_admin_headers()


def _guest_host_active_listing(ppn=100, guest_tier="PLUS", min_trust=0, verify_guest=False):
    """Guest (membership active), verified host with an ACTIVE listing + one window."""
    set_clock("2026-07-01T00:00:00Z")
    guest = register_member(full_name="Guest", home_city="Boston")
    host = register_member(full_name="Host", home_city="Denver")
    if guest_tier:
        subscribe_and_activate(guest["id"], guest_tier)
    if verify_guest:
        verify_identity(guest["id"])
    verify_identity(host["id"])
    listing = create_active_listing(host["id"], points_per_night=ppn, min_trust_score=min_trust)
    add_window(listing["id"], host["id"], "2026-07-10", "2026-07-12")
    return guest, host, listing


# ── Difficulty 1a: settled vs available diverge by the outstanding hold ───────
def test_settled_and_available_balances_before_hold_equal(api):
    """PRD §2.6: "The `settled_points_balance` is the sum of the `amount` of every
    `POSTED` entry for that member. The `available_points_balance` is the sum of the
    `amount` of every entry for that member whose status is either `POSTED` or `HELD`."

    Design: Difficulty/dual_variant_calc/member_balance_settled_vs_available_diverge_on_open_hold
    """
    guest, host, listing = _guest_host_active_listing(ppn=100, guest_tier="PLUS")
    m = get_member(guest["id"])
    # Only the WELCOME_BONUS is posted and there is no hold yet, so both agree.
    assert m["settled_points_balance"] == 1000
    assert m["available_points_balance"] == 1000


def test_open_hold_makes_available_below_settled(api):
    """PRD §2.6: "Because holds are recorded as negative amounts, a member's
    available balance is at or below their settled balance for as long as any hold
    remains outstanding."
    PRD §3.3: "the system posts a `HELD` hold ledger entry reserving the negative of
    that cost ... and recomputes the requester's available balance so the hold
    immediately reduces it."

    Design: Difficulty/dual_variant_calc/member_balance_settled_vs_available_diverge_on_open_hold
    """
    guest, host, listing = _guest_host_active_listing(ppn=100, guest_tier="PLUS")
    req = open_points_request(guest["id"], listing["id"], "2026-07-10", "2026-07-12")
    assert req["points_cost"] == 270
    m = get_member(guest["id"])
    assert m["settled_points_balance"] == 1000
    assert m["available_points_balance"] == 730
    assert m["settled_points_balance"] != m["available_points_balance"]
    assert m["settled_points_balance"] - m["available_points_balance"] == 270


# ── Difficulty 2a: per-night round-then-sum pricing ──────────────────────────
def test_points_cost_rounds_each_night_before_summing(api):
    """PRD §3.3: "Each night's charge is the listing's `points_per_night` multiplied
    by that night's season multiplier and then by one minus the tier discount, and
    that per-night charge is rounded half up to a whole number of points. The rounded
    nightly charges are then summed across all nights — the rounding is per night and
    precedes the sum."

    Design: Difficulty/combinatorial_formula/points_cost_per_night_round_then_sum_mode_b
    """
    guest, host, listing = _guest_host_active_listing(ppn=75, guest_tier="PLUS")
    # 75 * 1.5 (July PEAK) * 0.90 (PLUS) = 101.25 -> round_half_up 101 per night; 2 nights = 202.
    req = open_points_request(guest["id"], listing["id"], "2026-07-10", "2026-07-12")
    assert req["points_cost"] == 202


def test_points_cost_hold_reduces_available_by_exact_cost(api):
    """PRD §3.3: "the system posts a `HELD` hold ledger entry reserving the negative
    of that cost".
    PRD §2.6: "The `available_points_balance` is the sum of the `amount` of every
    entry for that member whose status is either `POSTED` or `HELD`."

    Design: Difficulty/combinatorial_formula/points_cost_per_night_round_then_sum_mode_b
    """
    guest, host, listing = _guest_host_active_listing(ppn=75, guest_tier="PLUS")
    open_points_request(guest["id"], listing["id"], "2026-07-10", "2026-07-12")
    m = get_member(guest["id"])
    assert m["settled_points_balance"] == 1000
    assert m["available_points_balance"] == 1000 - 202  # 798


# ── Difficulty 6a: sufficiency boundary is >= ────────────────────────────────
def test_points_sufficiency_exact_equal_passes(api):
    """PRD §3.3: "Finally, for a points request, the requester's
    `available_points_balance` must be at least the computed `points_cost` so that
    placing the hold leaves availability at or above zero, otherwise
    `ERR_INSUFFICIENT_POINTS`."

    Design: Difficulty/boundary_precision_check/points_sufficiency_exact_equal_passes
    """
    guest, host, listing = _guest_host_active_listing(ppn=100, guest_tier="PLUS")
    adjust_points(guest["id"], -730, "leave exactly 270")   # 1000 - 730 = 270 available
    req = open_points_request(guest["id"], listing["id"], "2026-07-10", "2026-07-12")
    assert req["points_cost"] == 270
    m = get_member(guest["id"])
    assert m["available_points_balance"] == 0


def test_points_sufficiency_one_below_cost_rejected(api):
    """PRD §3.3: "the requester's `available_points_balance` must be at least the
    computed `points_cost` ... otherwise `ERR_INSUFFICIENT_POINTS`."

    Design: Difficulty/boundary_precision_check/points_sufficiency_exact_equal_passes
    """
    guest, host, listing = _guest_host_active_listing(ppn=100, guest_tier="PLUS")
    adjust_points(guest["id"], -731, "leave 269, one below cost")  # 269 available, cost 270
    res = api.create_exchange_request(
        create_exchange_request_payload(guest["id"], listing["id"], "2026-07-10", "2026-07-12", "POINTS"),
        make_member_headers(guest["id"]))
    validate_error(res, "ERR_INSUFFICIENT_POINTS")


# ── Difficulty 5a: listing-state check precedes the fiscal check ─────────────
def test_create_request_listing_state_beats_fiscal(api):
    """PRD §3.3: "First the target listing must be `ACTIVE`, otherwise
    `ERR_LISTING_NOT_ACTIVE`. Next the requester must currently hold a membership in
    `ACTIVE` status ... Finally, for a points request, the requester's
    `available_points_balance` must be at least the computed `points_cost` ...
    otherwise `ERR_INSUFFICIENT_POINTS`."

    Design: Difficulty/priority_pair_validation_conflict/create_request_listing_state_beats_fiscal
    """
    set_clock("2026-07-01T00:00:00Z")
    guest = register_member(full_name="Guest", home_city="Boston")
    host = register_member(full_name="Host", home_city="Denver")
    subscribe_and_activate(guest["id"], "PLUS")
    adjust_points(guest["id"], -1000, "zero out")   # 0 available -> fiscal would fail
    listing = create_draft_listing(host["id"])      # never activated -> listing-state fails
    res = api.create_exchange_request(
        create_exchange_request_payload(guest["id"], listing["id"], "2026-07-10", "2026-07-12", "POINTS"),
        make_member_headers(guest["id"]))
    validate_error(res, "ERR_LISTING_NOT_ACTIVE")


def test_create_request_fiscal_surfaces_when_listing_active(api):
    """PRD §3.3: "Finally, for a points request, the requester's
    `available_points_balance` must be at least the computed `points_cost` so that
    placing the hold leaves availability at or above zero, otherwise
    `ERR_INSUFFICIENT_POINTS`."

    Design: Difficulty/priority_pair_validation_conflict/create_request_listing_state_beats_fiscal
    """
    guest, host, listing = _guest_host_active_listing(ppn=100, guest_tier="PLUS")
    adjust_points(guest["id"], -1000, "zero out")   # listing ACTIVE now, only fiscal fails
    res = api.create_exchange_request(
        create_exchange_request_payload(guest["id"], listing["id"], "2026-07-10", "2026-07-12", "POINTS"),
        make_member_headers(guest["id"]))
    validate_error(res, "ERR_INSUFFICIENT_POINTS")


# ── Difficulty 7a: request depends on a different entity's ACTIVE state ───────
def test_request_against_draft_listing_rejected(api):
    """PRD §3.3: "First the target listing must be `ACTIVE`, otherwise
    `ERR_LISTING_NOT_ACTIVE`."
    PRD §3.2: "Only an `ACTIVE` listing is a valid target for an exchange request."

    Design: Difficulty/cross_entity_state_dependency/request_requires_listing_active
    """
    set_clock("2026-07-01T00:00:00Z")
    guest = register_member(full_name="Guest", home_city="Boston")
    host = register_member(full_name="Host", home_city="Denver")
    subscribe_and_activate(guest["id"], "PLUS")
    listing = create_draft_listing(host["id"])
    res = api.create_exchange_request(
        create_exchange_request_payload(guest["id"], listing["id"], "2026-07-10", "2026-07-12", "POINTS"),
        make_member_headers(guest["id"]))
    validate_error(res, "ERR_LISTING_NOT_ACTIVE")


def test_request_against_active_listing_succeeds(api):
    """PRD §3.2: "Only an `ACTIVE` listing is a valid target for an exchange request."
    PRD §3.3: "Every new request opens in `PROPOSED` status."

    Design: Difficulty/cross_entity_state_dependency/request_requires_listing_active
    """
    guest, host, listing = _guest_host_active_listing(ppn=100, guest_tier="PLUS")
    res = api.create_exchange_request(
        create_exchange_request_payload(guest["id"], listing["id"], "2026-07-10", "2026-07-12", "POINTS"),
        make_member_headers(guest["id"]))
    req = validate_success(res, 201)
    assert req["status"] == "PROPOSED"


# ── Corner validations ───────────────────────────────────────────────────────
def test_request_without_active_membership_returns_membership_inactive(api):
    """PRD §3.3: "Next the requester must currently hold a membership in `ACTIVE`
    status, otherwise `ERR_MEMBERSHIP_INACTIVE`."

    Design: Corner/validations/request_without_active_membership_returns_membership_inactive
    """
    set_clock("2026-07-01T00:00:00Z")
    guest = register_member(full_name="Guest", home_city="Boston")   # never subscribed
    host = register_member(full_name="Host", home_city="Denver")
    verify_identity(host["id"])
    listing = create_active_listing(host["id"])
    res = api.create_exchange_request(
        create_exchange_request_payload(guest["id"], listing["id"], "2026-07-10", "2026-07-12", "POINTS"),
        make_member_headers(guest["id"]))
    validate_error(res, "ERR_MEMBERSHIP_INACTIVE")


def test_request_below_min_trust_returns_trust_too_low(api):
    """PRD §3.3: "Then the requester's `trust_score` must be at least the target
    listing's `min_trust_score`, otherwise `ERR_TRUST_TOO_LOW`."

    Design: Corner/validations/request_below_min_trust_returns_trust_too_low
    """
    guest, host, listing = _guest_host_active_listing(ppn=100, guest_tier="PLUS", min_trust=60)
    # A brand-new member has trust_score 50, below the listing's 60.
    res = api.create_exchange_request(
        create_exchange_request_payload(guest["id"], listing["id"], "2026-07-10", "2026-07-12", "POINTS"),
        make_member_headers(guest["id"]))
    validate_error(res, "ERR_TRUST_TOO_LOW")
