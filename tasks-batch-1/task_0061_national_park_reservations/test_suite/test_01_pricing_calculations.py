"""Pricing and fee calculations: campground totals (tent vs group), backcountry
fee vs lottery permit fee, group-pricing combinatorics, cancellation refund
rounding, and ATB pass pricing.

Difficulty queue: dual_variant_calc, combinatorial_formula (subset).
Corner queue: calculations (atb_price, cancel_refund subset).
"""
from test_helpers import assert_created, assert_ok
from test_helpers import fixtures as fx


# --- dual_variant_camp_group_vs_tent_pricing -----------------------------
def test_camp_total_tent_two_nights(client):
    """PRD 3.6: "For a `tent` or `rv` site, the total is the campsite's
    `base_nightly_cents` multiplied by the number of nights."

    Design: Difficulty/dual_variant_calc/dual_variant_camp_group_vs_tent_pricing
    """
    park, pa = fx.base_world(client, "YOSE", park_overrides={"utc_offset_minutes": -480})
    v = fx.create_visitor(client)
    tent = fx.create_campsite(client, park["id"], pa["id"], site_number="T1",
                              site_type="tent", base_nightly_cents=4000)
    resv = fx.create_camp_reservation(client, tent["id"], v["id"],
                                      "2026-06-10", "2026-06-12", party_size=4)
    assert resv["total_cents"] == 8000  # 4000 * 2 nights


def test_camp_total_group_with_extra_persons(client):
    """PRD 3.6: "the per-night rate is then `group_base_cents` plus
    `group_extra_person_cents` multiplied by that extra-person count; and the
    total is that per-night rate multiplied by the number of nights."

    Design: Difficulty/dual_variant_calc/dual_variant_camp_group_vs_tent_pricing
    """
    park, pa = fx.base_world(client, "YOSE", park_overrides={"utc_offset_minutes": -480})
    v = fx.create_visitor(client)
    group = fx.create_campsite(client, park["id"], pa["id"], site_number="G1",
                               site_type="group", max_occupancy=30,
                               base_nightly_cents=0, group_base_cents=10000,
                               group_included_persons=10, group_extra_person_cents=500)
    resv = fx.create_camp_reservation(client, group["id"], v["id"],
                                      "2026-06-10", "2026-06-12", party_size=15)
    # (10000 + 500*5) * 2 nights = 25000
    assert resv["total_cents"] == 25000


# --- dual_variant_backcountry_fee_vs_lottery_permit_fee ------------------
def test_backcountry_fee_flat_plus_per_person_per_night(client):
    """PRD 3.4: "The permit's `fee_cents` is computed as the sum of two parts:
    a non-refundable reservation flat equal to the trailhead's
    `reservation_fee_cents`, plus a refundable variable equal to the
    trailhead's `per_person_per_night_cents` multiplied by `party_size` and
    then by `nights`."

    Design: Difficulty/dual_variant_calc/dual_variant_backcountry_fee_vs_lottery_permit_fee
    """
    park, pa = fx.base_world(client, "ZION", park_overrides={"utc_offset_minutes": -420})
    v = fx.create_visitor(client)
    th = fx.create_trailhead(client, park["id"], pa["id"],
                             reservation_fee_cents=500, per_person_per_night_cents=800)
    z = fx.create_zone(client, park["id"], pa["id"], nightly_party_quota=5)
    permit = fx.create_backcountry_permit(
        client, park["id"], v["id"], th["id"], "2026-08-01", 2, 3,
        [{"zone_id": z["id"], "date": "2026-08-01"},
         {"zone_id": z["id"], "date": "2026-08-02"}])
    assert permit["fee_cents"] == 5300  # 500 + 800*3*2


def test_lottery_application_fee_default_snapshot(client):
    """PRD 3.3: "a non-refundable `application_fee_cents` (defaulting to 1000)."
    PRD 3.3: "Its `application_fee_cents` is snapshotted from the draw".

    Design: Difficulty/dual_variant_calc/dual_variant_backcountry_fee_vs_lottery_permit_fee
    """
    park, pa = fx.base_world(client, "ZION",
                             park_overrides={"utc_offset_minutes": -420})
    v = fx.create_visitor(client)
    # Clock is inside the application window for this draw.
    draw = fx.create_draw(client, park["id"], pa["id"],
                          application_open_at="2026-05-01T00:00:00Z",
                          application_close_at="2026-07-01T00:00:00Z",
                          draw_at="2026-07-02T00:00:00Z",
                          permit_fee_per_person_cents=1500)
    app = fx.submit_application(client, draw["id"], v["id"], party_size=3)
    assert app["application_fee_cents"] == 1000  # draw default


# --- combinatorial_group_pricing_three_inputs_nonlinear ------------------
def test_group_pricing_below_included_no_surcharge(client):
    """PRD 3.6: "first compute the number of extra persons as the party size
    minus `group_included_persons`, floored at zero (never negative)".

    Design: Difficulty/combinatorial_formula/combinatorial_group_pricing_three_inputs_nonlinear
    """
    park, pa = fx.base_world(client, "GRCA", park_overrides={"utc_offset_minutes": -420})
    v = fx.create_visitor(client)
    group = fx.create_campsite(client, park["id"], pa["id"], site_number="G9",
                               site_type="group", max_occupancy=30,
                               base_nightly_cents=0, group_base_cents=10000,
                               group_included_persons=10, group_extra_person_cents=500)
    resv = fx.create_camp_reservation(client, group["id"], v["id"],
                                      "2026-06-10", "2026-06-13", party_size=8)
    assert resv["total_cents"] == 30000  # max(0, 8-10)=0 -> (10000 + 0) * 3 nights


def test_group_pricing_above_included_with_surcharge(client):
    """PRD 3.6: "the per-night rate is then `group_base_cents` plus
    `group_extra_person_cents` multiplied by that extra-person count; and the
    total is that per-night rate multiplied by the number of nights."

    Design: Difficulty/combinatorial_formula/combinatorial_group_pricing_three_inputs_nonlinear
    """
    park, pa = fx.base_world(client, "GRCA", park_overrides={"utc_offset_minutes": -420})
    v = fx.create_visitor(client)
    group = fx.create_campsite(client, park["id"], pa["id"], site_number="G9",
                               site_type="group", max_occupancy=30,
                               base_nightly_cents=0, group_base_cents=10000,
                               group_included_persons=10, group_extra_person_cents=500)
    resv = fx.create_camp_reservation(client, group["id"], v["id"],
                                      "2026-06-10", "2026-06-13", party_size=14)
    # max(0,14-10)=4 -> (10000 + 500*4) * 3 nights = 36000
    assert resv["total_cents"] == 36000


# --- combinatorial_cancel_refund_pct_then_round_half_up ------------------
def test_backcountry_cancel_refund_25pct_round_half_up(client):
    """PRD 3.6: "when D is between 2 and 6 inclusive, 25 percent ... The refund
    in cents is the refundable base multiplied by that percentage and divided
    by 100, rounded half up to a whole cent at that single multiplication."
    PRD 3.4: "the refundable base is the permit's `fee_cents` minus the
    trailhead's `reservation_fee_cents` (the reservation flat is never refunded)."

    Design: Difficulty/combinatorial_formula/combinatorial_cancel_refund_pct_then_round_half_up
    """
    park, pa = fx.base_world(client, "SEKI", park_overrides={"utc_offset_minutes": -480})
    v = fx.create_visitor(client)
    th = fx.create_trailhead(client, park["id"], pa["id"],
                             reservation_fee_cents=500, per_person_per_night_cents=333)
    z = fx.create_zone(client, park["id"], pa["id"], nightly_party_quota=5)
    # now = 2026-06-01; entry_date 2026-06-05 => D=4 => 25% band.
    permit = fx.create_backcountry_permit(
        client, park["id"], v["id"], th["id"], "2026-06-05", 1, 3,
        [{"zone_id": z["id"], "date": "2026-06-05"}])
    assert permit["fee_cents"] == 1499  # 500 + 333*3*1
    fx.confirm_backcountry_permit(client, permit["id"], v["id"])
    cancelled = assert_ok(
        client.post(f"/v1/backcountry-permits/{permit['id']}/cancel",
                    role="visitor", user_id=v["id"]), 200)
    # refundable_base = 1499-500 = 999; 25% = 249.75 -> round_half_up 250
    assert cancelled["refunded_cents"] == 250
    acct = assert_ok(client.get(f"/v1/accounts/{v['id']}", role="visitor",
                                user_id=v["id"]), 200)
    assert acct["credit_balance_cents"] == 250


def test_camp_cancel_refund_full_band_exact(client):
    """PRD 3.6: "when D is 14 or more, 100 percent". For a campground stay the
    refundable base is the full `total_cents`.

    Design: Difficulty/combinatorial_formula/combinatorial_cancel_refund_pct_then_round_half_up
    """
    park, pa = fx.base_world(client, "SEKI")
    v = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="TF",
                              site_type="tent", base_nightly_cents=4000)
    # now=2026-06-01; check_in 2026-06-15 => D=14 => 100%.
    resv = fx.create_camp_reservation(client, site["id"], v["id"],
                                      "2026-06-15", "2026-06-17", party_size=2)
    assert resv["total_cents"] == 8000
    fx.confirm_camp_reservation(client, resv["id"], v["id"])
    cancelled = assert_ok(
        client.post(f"/v1/camp-reservations/{resv['id']}/cancel",
                    role="visitor", user_id=v["id"]), 200)
    assert cancelled["refunded_cents"] == 8000


# --- Corner: calculations -------------------------------------------------
def test_atb_price_senior_annual(client):
    """PRD 3.1: "a `senior_annual` costs 2000 cents ... The expiry `valid_to`
    is computed as the day exactly 365 days after `valid_from` for `annual`,
    `senior_annual`, `military`, and `access`".

    Design: Corner/calculations/atb_price_senior_annual_correct
    """
    fx.set_clock(client, "2026-06-01T00:00:00Z")
    v = fx.create_visitor(client, birth_date="1958-01-01")
    pass_ = fx.buy_pass(client, v["id"], "senior_annual", "2026-06-01")
    assert pass_["price_cents"] == 2000
    assert pass_["valid_to"] == "2027-06-01"


def test_atb_price_senior_lifetime_never_expires(client):
    """PRD 3.1: "a `senior_lifetime` costs 8000 cents ... for `senior_lifetime`
    it is null, meaning the pass never expires."

    Design: Corner/calculations/atb_price_senior_lifetime_never_expires
    """
    fx.set_clock(client, "2026-06-01T00:00:00Z")
    v = fx.create_visitor(client, birth_date="1955-01-01")
    pass_ = fx.buy_pass(client, v["id"], "senior_lifetime", "2026-06-01")
    assert pass_["price_cents"] == 8000
    assert pass_["valid_to"] is None


def test_camp_cancel_refund_band_full_100pct(client):
    """PRD 3.6: "when D is 14 or more, 100 percent ... for a campground stay
    the refundable base is the full `total_cents`".

    Design: Corner/calculations/cancel_refund_band_full_100pct
    """
    park, pa = fx.base_world(client, "RF01")
    v = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="TM",
                              site_type="tent", base_nightly_cents=4000)
    resv = fx.create_camp_reservation(client, site["id"], v["id"],
                                      "2026-06-15", "2026-06-17", party_size=2)
    fx.confirm_camp_reservation(client, resv["id"], v["id"])
    cancelled = assert_ok(
        client.post(f"/v1/camp-reservations/{resv['id']}/cancel",
                    role="visitor", user_id=v["id"]), 200)
    assert cancelled["refunded_cents"] == 8000
    acct = assert_ok(client.get(f"/v1/accounts/{v['id']}", role="visitor",
                                user_id=v["id"]), 200)
    assert acct["credit_balance_cents"] == 8000


def test_refund_band_edge_below_full_is_50pct(client):
    """PRD 3.6: "when D is between 7 and 13 inclusive, 50 percent".

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_refund_band_edge_below_full
    """
    park, pa = fx.base_world(client, "CC03")
    v = fx.create_visitor(client)
    site = fx.create_campsite(client, park["id"], pa["id"], site_number="THH",
                              site_type="tent", base_nightly_cents=4000)
    # now=2026-06-01; check_in 2026-06-14 => D=13 => 50%.
    resv = fx.create_camp_reservation(client, site["id"], v["id"],
                                      "2026-06-14", "2026-06-16", party_size=2)
    fx.confirm_camp_reservation(client, resv["id"], v["id"])
    cancelled = assert_ok(
        client.post(f"/v1/camp-reservations/{resv['id']}/cancel",
                    role="visitor", user_id=v["id"]), 200)
    assert cancelled["refunded_cents"] == 4000  # 8000 * 50%
