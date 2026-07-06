"""Pricing tests: single-ticket dynamic pricing and subscription repricing.

Covers the dual-variant pricing engine (new vs renewal subscription, flex-pass
vs paid exchange) and the combinatorial pricing formulas (three-input
non-linear single price, sum-of-floors subscription rounding).
"""
from test_helpers import (
    get_success_data, validate_success,
    api_client,
    TEST_USERS, make_patron_headers,
    create_exchange_payload,
)
import test_helpers as th

ADMIN = TEST_USERS["season_admin_headers"]
AGENT = TEST_USERS["box_office_agent_headers"]


# ==========================================================================
# Difficulty/dual_variant_calc/subscription_pricing_new_vs_renewal_variant
# ==========================================================================
def test_new_subscription_total_price_two_seats(api):
    """PRD §3.3: "for each `ASSIGNED` subscription seat, the per-seat price is
    the season's `base_subscription_fee_cents` multiplied by the tier weight for
    that seat's `price_tier` — 1.5 for `PREMIUM`, 1.0 for `STANDARD`, and 0.6 for
    `VALUE` — then floored to whole cents".
    PRD §3.3: "The subscription's `total_price_cents` is the sum of those per-seat
    figures."

    A brand-new (non-renewal) subscription over one PREMIUM (30000) and one
    STANDARD (20000) seat at base 20000 totals 50000.

    Design: Difficulty/dual_variant_calc/subscription_pricing_new_vs_renewal_variant
    """
    ctx = th.setup_draft_subscription_with_seats(
        seat_tiers=("PREMIUM", "STANDARD"),
        base_subscription_fee_cents=20000,
        loyalty_renewal_discount_pct=0.10,
    )
    resp = api.activate_subscription(
        ctx["subscription"]["id"], {"expected_season_version": ctx["season_version"]}, AGENT
    )
    data = validate_success(resp, 200)
    assert data["status"] == "ACTIVE"
    assert data["total_price_cents"] == 50000, f"expected 50000, got {data['total_price_cents']}"
    assert data["is_renewal"] is False


def test_renewal_subscription_applies_loyalty_discount(api):
    """PRD §3.3: "if the subscription is a renewal, that floored per-seat figure
    is further multiplied by one minus the season's `loyalty_renewal_discount_pct`
    and floored again."
    PRD §3.4: "Confirming the renewal flips the successor's `RENEWAL_OFFERED`
    subscription seats to `ASSIGNED` and reprices the successor through
    subscription pricing with the loyalty renewal discount applied."

    A renewal successor over the same PREMIUM+STANDARD seats reprices to
    50000 * 0.90 = 45000 (floor(30000*0.9)=27000 + floor(20000*0.9)=18000).

    Design: Difficulty/dual_variant_calc/subscription_pricing_new_vs_renewal_variant
    """
    th.set_clock("2026-04-01T00:00:00Z")
    season = th.create_season(base_subscription_fee_cents=20000, loyalty_renewal_discount_pct=0.10)
    venue = th.create_venue()
    seat_prem = th.create_seat(venue["id"], row_label="A", seat_number=1, price_tier="PREMIUM")
    seat_std = th.create_seat(venue["id"], row_label="A", seat_number=2, price_tier="STANDARD")
    patron = th.create_patron(email="renew2@example.com")
    ph = make_patron_headers(patron["id"])

    # Original subscription, activated.
    sub = get_success_data(api.create_subscription(
        th.create_subscription_payload(season["id"], patron["id"]), ph))
    for seat in (seat_prem, seat_std):
        get_success_data(api.create_subscription_seat(
            th.create_subscription_seat_payload(sub["id"], seat["id"]), ph))
    get_success_data(api.activate_subscription(sub["id"], {"expected_season_version": season["version"]}, AGENT))

    # Open renewal, offer renewal on the original.
    th.set_clock("2026-05-02T00:00:00Z")
    get_success_data(api.open_renewal(season["id"], ADMIN))
    get_success_data(api.offer_renewal(sub["id"], AGENT))

    # Successor renewal subscription over the same seats; activate it.
    succ = get_success_data(api.create_subscription(
        th.create_subscription_payload(season["id"], patron["id"], prior_subscription_id=sub["id"]), ph))
    for seat in (seat_prem, seat_std):
        get_success_data(api.create_subscription_seat(
            th.create_subscription_seat_payload(succ["id"], seat["id"]), ph))
    season_now = get_success_data(api.get_season(season["id"], ADMIN))
    succ_active = get_success_data(api.activate_subscription(
        succ["id"], {"expected_season_version": season_now["version"]}, AGENT))

    assert succ_active["is_renewal"] is True
    assert succ_active["total_price_cents"] == 45000, (
        f"renewal total should be 45000, got {succ_active['total_price_cents']}")


# ==========================================================================
# Difficulty/dual_variant_calc/exchange_fee_flexpass_vs_paid_variant
# ==========================================================================
def _setup_paid_exchange_premium_target():
    """perf1 STANDARD@1.0 sold single (6000); perf2 PREMIUM@1.5 free seat;
    PAID_EXCHANGE requested. Returns (exchange_id, patron_id)."""
    th.set_clock("2026-06-10T00:00:00Z")
    season = th.create_season()
    production = th.create_production(season["id"])
    th.announce_production(production["id"])
    venue = th.create_venue()
    seat_std = th.create_seat(venue["id"], row_label="B", seat_number=1, price_tier="STANDARD")
    seat_prem = th.create_seat(venue["id"], row_label="B", seat_number=2, price_tier="PREMIUM")
    perf1 = th.create_performance(production["id"], venue["id"],
                                  starts_at="2026-07-01T19:30:00Z", on_sale_at="2026-06-01T00:00:00Z",
                                  demand_multiplier=1.0)
    get_success_data(api_client.schedule_performance(perf1["id"], ADMIN))
    perf1 = get_success_data(api_client.open_sales(perf1["id"], AGENT))
    perf2 = th.create_performance(production["id"], venue["id"],
                                  starts_at="2026-07-02T19:30:00Z", on_sale_at="2026-06-01T00:00:00Z",
                                  demand_multiplier=1.5)
    get_success_data(api_client.schedule_performance(perf2["id"], ADMIN))
    get_success_data(api_client.open_sales(perf2["id"], AGENT))
    patron = th.create_patron(email="exch@example.com")
    ph = make_patron_headers(patron["id"])
    orig = th.hold_single_ticket(perf1["id"], seat_std["id"], patron["id"], perf1["version"], headers=ph)
    get_success_data(api_client.pay_ticket(orig["id"], ph))
    exch = get_success_data(api_client.create_exchange(
        create_exchange_payload(orig["id"], perf2["id"], seat_prem["id"], "PAID_EXCHANGE"), ph))
    return exch["id"], patron["id"]


def test_paid_exchange_fee_is_flat_800(api):
    """PRD §3.7: "The `fee_cents` depends on the mode: for a `PAID_EXCHANGE` it is
    always 800 cents".

    Design: Difficulty/dual_variant_calc/exchange_fee_flexpass_vs_paid_variant
    """
    exch_id, _ = _setup_paid_exchange_premium_target()
    data = validate_success(api.complete_exchange(exch_id, AGENT), 200)
    assert data["status"] == "COMPLETED"
    assert data["fee_cents"] == 800, f"PAID_EXCHANGE fee must be 800, got {data['fee_cents']}"


def test_paid_exchange_price_delta_premium_minus_standard(api):
    """PRD §3.7: "The `price_delta_cents` is the target seat's single-ticket price
    for the target performance and patron (computed exactly as in §3.5) minus the
    original ticket's `price_cents`, floored at zero so that a cheaper target never
    yields a credit."

    Target PREMIUM at demand 1.5 (floor(9000*1.5)=13500) minus original STANDARD
    6000 gives price_delta_cents=7500.

    Design: Difficulty/dual_variant_calc/exchange_fee_flexpass_vs_paid_variant
    """
    exch_id, _ = _setup_paid_exchange_premium_target()
    data = validate_success(api.complete_exchange(exch_id, AGENT), 200)
    assert data["price_delta_cents"] == 7500, (
        f"price_delta should be 13500-6000=7500, got {data['price_delta_cents']}")


# ==========================================================================
# Corner/calculations/exchange_flexpass_subscription_fee_zero
# ==========================================================================
def test_flexpass_on_subscription_ticket_waives_fee(api):
    """PRD §3.7: "for a `FLEX_PASS` it is waived to 0 only when the original
    ticket's `origin` is `SUBSCRIPTION`".

    Design: Corner/calculations/exchange_flexpass_subscription_fee_zero
    """
    th.set_clock("2026-06-10T00:00:00Z")
    season = th.create_season(base_subscription_fee_cents=20000)
    production = th.create_production(season["id"])
    th.announce_production(production["id"])
    venue = th.create_venue()
    seat1 = th.create_seat(venue["id"], row_label="T", seat_number=1, price_tier="STANDARD")
    seat2 = th.create_seat(venue["id"], row_label="T", seat_number=2, price_tier="STANDARD")
    patron = th.create_patron(email="flexsub@example.com")
    ph = make_patron_headers(patron["id"])
    sub = get_success_data(api.create_subscription(
        th.create_subscription_payload(season["id"], patron["id"]), ph))
    get_success_data(api.create_subscription_seat(
        th.create_subscription_seat_payload(sub["id"], seat1["id"]), ph))
    get_success_data(api.activate_subscription(sub["id"], {"expected_season_version": season["version"]}, AGENT))

    perf1 = th.create_performance(production["id"], venue["id"],
                                  starts_at="2026-07-01T19:30:00Z", on_sale_at="2026-06-01T00:00:00Z",
                                  demand_multiplier=1.0)
    get_success_data(api.schedule_performance(perf1["id"], ADMIN))
    perf1 = get_success_data(api.open_sales(perf1["id"], AGENT))
    perf2 = th.create_performance(production["id"], venue["id"],
                                  starts_at="2026-07-02T19:30:00Z", on_sale_at="2026-06-01T00:00:00Z",
                                  demand_multiplier=1.0)
    get_success_data(api.schedule_performance(perf2["id"], ADMIN))
    get_success_data(api.open_sales(perf2["id"], AGENT))

    orig = get_success_data(api.create_ticket(th.create_ticket_payload(
        perf1["id"], seat1["id"], patron["id"], "SUBSCRIPTION", perf1["version"],
        subscription_id=sub["id"]), AGENT))
    get_success_data(api.pay_ticket(orig["id"], AGENT))
    exch = get_success_data(api.create_exchange(
        create_exchange_payload(orig["id"], perf2["id"], seat2["id"], "FLEX_PASS"), ph))

    data = validate_success(api.complete_exchange(exch["id"], AGENT), 200)
    assert data["status"] == "COMPLETED"
    assert data["fee_cents"] == 0, f"FLEX_PASS on subscription ticket waives fee, got {data['fee_cents']}"
    assert data["price_delta_cents"] == 0


# ==========================================================================
# Difficulty/combinatorial_formula/single_ticket_three_input_nonlinear_pricing
# ==========================================================================
def test_single_ticket_premium_demand_patron_discount(api):
    """PRD §3.5: "The tier base price — 9000 cents for `PREMIUM`, 6000 cents for
    `STANDARD`, 3500 cents for `VALUE` — is multiplied first by the demand
    multiplier to give a demand-adjusted raw amount. Then the donor discount for
    the patron's level — 0.0 for `NONE`, 0.05 for `FRIEND`, 0.10 for `PATRON`, and
    0.20 for `BENEFACTOR` — is applied by multiplying the raw amount by one minus
    that discount fraction, and the result is floored to whole cents to give
    `price_cents`."

    PREMIUM at demand 1.5 for a PATRON: floor(9000*1.5*0.90)=12150.

    Design: Difficulty/combinatorial_formula/single_ticket_three_input_nonlinear_pricing
    """
    th.set_clock("2026-06-10T00:00:00Z")
    patron = th.create_patron_at_donor_level(100000, email="patronlvl@example.com")
    assert patron["donor_level"] == "PATRON"
    ctx = th.setup_on_sale_performance(clock=None, seats=[{"price_tier": "PREMIUM", "row_label": "C"}],
                                       demand_multiplier=1.5)
    seat = ctx["seats"][0]
    ticket = th.hold_single_ticket(
        ctx["performance"]["id"], seat["id"], patron["id"], ctx["performance_version"])
    assert ticket["price_cents"] == 12150, f"expected 12150, got {ticket['price_cents']}"


def test_single_ticket_no_discount_buyer_pays_undiscounted(api):
    """PRD §3.5: "The tier base price — 9000 cents for `PREMIUM`, 6000 cents for
    `STANDARD`, 3500 cents for `VALUE` — is multiplied first by the demand
    multiplier to give a demand-adjusted raw amount. Then the donor discount for
    the patron's level — 0.0 for `NONE`, 0.05 for `FRIEND`, 0.10 for `PATRON`, and
    0.20 for `BENEFACTOR` — is applied".

    A NONE-level (no fulfilled donations) buyer of the same PREMIUM seat at demand
    1.5 pays floor(9000*1.5*1.0)=13500 — isolating the donor input as the term that
    drops the price to 12150 for a PATRON.

    Design: Difficulty/combinatorial_formula/single_ticket_three_input_nonlinear_pricing
    """
    th.set_clock("2026-06-10T00:00:00Z")
    patron = th.create_patron(email="nonedonor@example.com")
    assert patron["donor_level"] == "NONE"
    ctx = th.setup_on_sale_performance(clock=None, seats=[{"price_tier": "PREMIUM", "row_label": "C"}],
                                       demand_multiplier=1.5)
    seat = ctx["seats"][0]
    ticket = th.hold_single_ticket(
        ctx["performance"]["id"], seat["id"], patron["id"], ctx["performance_version"])
    assert ticket["price_cents"] == 13500, f"expected undiscounted 13500, got {ticket['price_cents']}"


def test_single_ticket_benefactor_discount_value(api):
    """PRD §3.5: "Then the donor discount for the patron's level — 0.0 for `NONE`,
    0.05 for `FRIEND`, 0.10 for `PATRON`, and 0.20 for `BENEFACTOR` — is applied by
    multiplying the raw amount by one minus that discount fraction, and the result
    is floored to whole cents to give `price_cents`."

    A BENEFACTOR buying STANDARD at demand 1.0: floor(6000*1.0*0.80)=4800.

    Design: Corner/calculations/single_ticket_benefactor_discount_value
    """
    th.set_clock("2026-06-10T00:00:00Z")
    patron = th.create_patron_at_donor_level(500000, email="benefactor@example.com")
    assert patron["donor_level"] == "BENEFACTOR"
    ctx = th.setup_on_sale_performance(clock=None, seats=[{"price_tier": "STANDARD", "row_label": "S"}],
                                       demand_multiplier=1.0)
    seat = ctx["seats"][0]
    ticket = th.hold_single_ticket(
        ctx["performance"]["id"], seat["id"], patron["id"], ctx["performance_version"])
    assert ticket["price_cents"] == 4800, f"expected 4800, got {ticket['price_cents']}"


# ==========================================================================
# Difficulty/combinatorial_formula/subscription_pricing_round_per_seat_then_sum_order
# ==========================================================================
def test_subscription_per_seat_floor_value_seat(api):
    """PRD §3.3: "for each `ASSIGNED` subscription seat, the per-seat price is the
    season's `base_subscription_fee_cents` multiplied by the tier weight for that
    seat's `price_tier` — 1.5 for `PREMIUM`, 1.0 for `STANDARD`, and 0.6 for
    `VALUE` — then floored to whole cents".

    base 3333 * 0.6 = 1999.8 -> floor 1999 per VALUE seat.

    Design: Difficulty/combinatorial_formula/subscription_pricing_round_per_seat_then_sum_order
    """
    ctx = th.setup_draft_subscription_with_seats(
        seat_tiers=("VALUE", "VALUE"), base_subscription_fee_cents=3333)
    get_success_data(api.activate_subscription(
        ctx["subscription"]["id"], {"expected_season_version": ctx["season_version"]}, AGENT))
    ss = get_success_data(api.get_subscription_seat(ctx["subscription_seats"][0]["id"], ADMIN))
    assert ss["per_seat_price_cents"] == 1999, f"expected 1999, got {ss['per_seat_price_cents']}"


def test_subscription_total_is_sum_of_floors_not_floor_of_sum(api):
    """PRD §3.3: "The flooring happens per seat first and the floored per-seat
    amounts are then summed — this is a sum of floors, not a floor of the sum, and
    the per-seat floor is the pinned rounding boundary."

    Two VALUE seats at base 3333: floor(1999.8)=1999 each, total 3998 — NOT the
    3999 a floor-of-sum would give.

    Design: Difficulty/combinatorial_formula/subscription_pricing_round_per_seat_then_sum_order
    """
    ctx = th.setup_draft_subscription_with_seats(
        seat_tiers=("VALUE", "VALUE"), base_subscription_fee_cents=3333)
    data = validate_success(api.activate_subscription(
        ctx["subscription"]["id"], {"expected_season_version": ctx["season_version"]}, AGENT), 200)
    assert data["total_price_cents"] == 3998, (
        f"sum-of-floors must be 3998 not 3999, got {data['total_price_cents']}")
