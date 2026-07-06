"""Cascade and conservation tests: performance-cancel depth-3 cascade,
season close-renewal release cascade, account-credit and donor-lifetime
conservation invariants.
"""
from test_helpers import (
    get_success_data, validate_success,
    TEST_USERS, make_patron_headers,
)
import test_helpers as th

ADMIN = TEST_USERS["season_admin_headers"]
AGENT = TEST_USERS["box_office_agent_headers"]


def _setup_subscription_ticket_on_on_sale_perf(api):
    """ACTIVE subscription whose single PREMIUM seat (per_seat 30000) issued a
    PAID SUBSCRIPTION ticket on an ON_SALE performance. Returns dict:
    perf_id, ticket_id, patron_id, ss_id."""
    th.set_clock("2026-06-10T00:00:00Z")
    season = th.create_season(base_subscription_fee_cents=20000)
    production = th.create_production(season["id"])
    th.announce_production(production["id"])
    venue = th.create_venue()
    seat = th.create_seat(venue["id"], row_label="F", seat_number=1, price_tier="PREMIUM")
    patron = th.create_patron(email="casc@example.com")
    ph = make_patron_headers(patron["id"])
    sub = get_success_data(api.create_subscription(
        th.create_subscription_payload(season["id"], patron["id"]), ph))
    ss = get_success_data(api.create_subscription_seat(
        th.create_subscription_seat_payload(sub["id"], seat["id"]), ph))
    get_success_data(api.activate_subscription(sub["id"], {"expected_season_version": season["version"]}, AGENT))

    perf = th.create_performance(production["id"], venue["id"],
                                 starts_at="2026-07-01T19:30:00Z", on_sale_at="2026-06-01T00:00:00Z",
                                 demand_multiplier=1.0)
    get_success_data(api.schedule_performance(perf["id"], ADMIN))
    perf = get_success_data(api.open_sales(perf["id"], AGENT))
    ticket = get_success_data(api.create_ticket(th.create_ticket_payload(
        perf["id"], seat["id"], patron["id"], "SUBSCRIPTION", perf["version"],
        subscription_id=sub["id"]), AGENT))
    get_success_data(api.pay_ticket(ticket["id"], AGENT))
    return {"perf_id": perf["id"], "ticket_id": ticket["id"],
            "patron_id": patron["id"], "ss_id": ss["id"]}


# ==========================================================================
# Difficulty/transitive_cascade/performance_cancel_depth3_cascade
# ==========================================================================
def test_cancel_voids_and_refunds_paid_subscription_ticket(api):
    """PRD §3.2: "Every non-`VOID` ticket on the performance moves to `VOID`
    fulfillment. Each such ticket that was `PAID` additionally moves to `REFUNDED`
    payment, and that refund credits the holder by adding the ticket's `price_cents`
    to the patron's `account_credit_cents`."

    Cancelling voids the PAID SUBSCRIPTION ticket and flips its payment to REFUNDED.

    Design: Difficulty/transitive_cascade/performance_cancel_depth3_cascade
    """
    ctx = _setup_subscription_ticket_on_on_sale_perf(api)
    validate_success(api.cancel_performance(ctx["perf_id"], ADMIN), 200)
    ticket = get_success_data(api.get_ticket(ctx["ticket_id"], ADMIN))
    assert ticket["fulfillment_status"] == "VOID"
    assert ticket["payment_status"] == "REFUNDED"


def test_cancel_credits_patron_and_releases_subscription_seat(api):
    """PRD §3.2: "that refund credits the holder by adding the ticket's
    `price_cents` to the patron's `account_credit_cents`. Each voided ticket whose
    `origin` is `SUBSCRIPTION` further flips its associated subscription seat to
    `RELEASED`."

    The PREMIUM per_seat 30000 ticket credits the patron 30000 (link 2) and its
    subscription seat is RELEASED (link 3).

    Design: Difficulty/transitive_cascade/performance_cancel_depth3_cascade
    """
    ctx = _setup_subscription_ticket_on_on_sale_perf(api)
    validate_success(api.cancel_performance(ctx["perf_id"], ADMIN), 200)
    patron = get_success_data(api.get_patron(ctx["patron_id"], ADMIN))
    assert patron["account_credit_cents"] == 30000, (
        f"expected credit 30000, got {patron['account_credit_cents']}")
    ss = get_success_data(api.get_subscription_seat(ctx["ss_id"], ADMIN))
    assert ss["status"] == "RELEASED"


# ==========================================================================
# Difficulty/transitive_cascade/season_close_renewal_depth2_release_cascade
# ==========================================================================
def _setup_unrenewed_offered_seat(api):
    """Season RENEWAL_OPEN with one RENEWAL_OFFERED seat whose holder never
    confirmed; clock past renewal_window_closes_at. Returns (season_id, ss_id)."""
    th.set_clock("2026-04-01T00:00:00Z")
    season = th.create_season(base_subscription_fee_cents=20000)
    venue = th.create_venue()
    seat = th.create_seat(venue["id"], row_label="G", seat_number=1, price_tier="STANDARD")
    patron = th.create_patron(email="unrenewed@example.com")
    ph = make_patron_headers(patron["id"])
    sub = get_success_data(api.create_subscription(
        th.create_subscription_payload(season["id"], patron["id"]), ph))
    ss = get_success_data(api.create_subscription_seat(
        th.create_subscription_seat_payload(sub["id"], seat["id"]), ph))
    get_success_data(api.activate_subscription(sub["id"], {"expected_season_version": season["version"]}, AGENT))
    th.set_clock("2026-05-02T00:00:00Z")
    get_success_data(api.open_renewal(season["id"], ADMIN))
    get_success_data(api.offer_renewal(sub["id"], AGENT))
    th.set_clock("2026-05-16T00:00:00Z")
    return season["id"], ss["id"]


def test_close_renewal_releases_unrenewed_seat(api):
    """PRD §3.4: "The close cascade releases every subscription seat still in
    `RENEWAL_OFFERED` to `RELEASED` — the prior holder did not renew".

    Design: Difficulty/transitive_cascade/season_close_renewal_depth2_release_cascade
    """
    season_id, ss_id = _setup_unrenewed_offered_seat(api)
    data = validate_success(api.close_renewal(season_id, ADMIN), 200)
    assert data["status"] == "ON_SALE"
    ss = get_success_data(api.get_subscription_seat(ss_id, ADMIN))
    assert ss["status"] == "RELEASED"


def test_close_renewal_increments_released_seat_count(api):
    """PRD §3.4: "and increments the season's `released_seat_count` by one for each
    such release, freeing those seats for single sale."

    The single released seat increments Season.released_seat_count to 1 (link 2).

    Design: Difficulty/transitive_cascade/season_close_renewal_depth2_release_cascade
    """
    season_id, ss_id = _setup_unrenewed_offered_seat(api)
    data = validate_success(api.close_renewal(season_id, ADMIN), 200)
    assert data["released_seat_count"] == 1, (
        f"expected released_seat_count 1, got {data['released_seat_count']}")


# ==========================================================================
# Difficulty/compensating_invariant/account_credit_refund_conservation
# ==========================================================================
def test_account_credit_equals_refunded_ticket_price(api):
    """PRD §3.8: "Refunds add to it from two sources: the `price_cents` of each of
    the patron's tickets whose payment flips from `PAID` to `REFUNDED` by a
    cancellation".
    PRD §3.2: "Each such ticket that was `PAID` additionally moves to `REFUNDED`
    payment, and that refund credits the holder by adding the ticket's `price_cents`
    to the patron's `account_credit_cents`."

    One PAID single STANDARD ticket priced 6000 leaves account_credit_cents==6000
    after cancellation and the ticket REFUNDED — refund-in equals credit-out.

    Design: Difficulty/compensating_invariant/account_credit_refund_conservation
    """
    ctx = th.setup_paid_single_ticket(price_tier="STANDARD", demand_multiplier=1.0)
    assert ctx["ticket"]["price_cents"] == 6000
    validate_success(api.cancel_performance(ctx["performance"]["id"], ADMIN), 200)
    ticket = get_success_data(api.get_ticket(ctx["ticket"]["id"], ADMIN))
    assert ticket["payment_status"] == "REFUNDED"
    patron = get_success_data(api.get_patron(ctx["patron"]["id"], ADMIN))
    assert patron["account_credit_cents"] == 6000, (
        f"credit must equal refunded price 6000, got {patron['account_credit_cents']}")


def test_account_credit_floored_nonnegative_after_refund(api):
    """PRD §3.8: "A patron's `account_credit_cents` is a conserved-quantity ledger
    and is never negative — it is floored at zero."

    After a single refund the conserved ledger holds exactly the refunded amount
    and never drops below zero.

    Design: Difficulty/compensating_invariant/account_credit_refund_conservation
    """
    ctx = th.setup_paid_single_ticket(price_tier="STANDARD", demand_multiplier=1.0)
    validate_success(api.cancel_performance(ctx["performance"]["id"], ADMIN), 200)
    patron = get_success_data(api.get_patron(ctx["patron"]["id"], ADMIN))
    assert patron["account_credit_cents"] == 6000
    assert patron["account_credit_cents"] >= 0


# ==========================================================================
# Difficulty/compensating_invariant/donor_lifetime_fulfill_refund_conservation
# ==========================================================================
def test_refund_returns_lifetime_to_zero(api):
    """PRD §3.6: "Refunding a fulfilled donation, also a `BoxOfficeAgent` action,
    advances it from `FULFILLED` to the terminal `REFUNDED` state and removes its
    `amount_cents` from the lifetime total".
    PRD §3.6: "The patron's `lifetime_donation_cents` is the sum of `amount_cents`
    over that patron's `FULFILLED` donations only".

    Fulfilling a 25000 gift then refunding it returns lifetime_donation_cents to 0.

    Design: Difficulty/compensating_invariant/donor_lifetime_fulfill_refund_conservation
    """
    th.set_clock("2026-06-10T00:00:00Z")
    patron = th.create_patron(email="dcons@example.com")
    donation = get_success_data(api.create_donation(
        th.create_donation_payload(patron["id"], 25000), AGENT))
    get_success_data(api.fulfill_donation(donation["id"], AGENT))
    refunded = validate_success(api.refund_donation(donation["id"], AGENT), 200)
    assert refunded["status"] == "REFUNDED"
    patron_after = get_success_data(api.get_patron(patron["id"], ADMIN))
    assert patron_after["lifetime_donation_cents"] == 0, (
        f"lifetime should return to 0, got {patron_after['lifetime_donation_cents']}")


def test_refund_demotes_donor_level_to_none(api):
    """PRD §3.6: "removes its `amount_cents` from the lifetime total, recomputing
    `donor_level`, which may demote the patron".
    PRD §3.6: "otherwise `FRIEND` when it is at least 25000 cents, and otherwise
    `NONE`."

    Refunding the only 25000 gift demotes donor_level FRIEND->NONE.

    Design: Difficulty/compensating_invariant/donor_lifetime_fulfill_refund_conservation
    """
    th.set_clock("2026-06-10T00:00:00Z")
    patron = th.create_patron(email="ddemote@example.com")
    donation = get_success_data(api.create_donation(
        th.create_donation_payload(patron["id"], 25000), AGENT))
    get_success_data(api.fulfill_donation(donation["id"], AGENT))
    before = get_success_data(api.get_patron(patron["id"], ADMIN))
    assert before["donor_level"] == "FRIEND"
    get_success_data(api.refund_donation(donation["id"], AGENT))
    after = get_success_data(api.get_patron(patron["id"], ADMIN))
    assert after["donor_level"] == "NONE", f"expected demotion to NONE, got {after['donor_level']}"
