"""Pricing engine: tiered quote selection, dual-variant provisional vs final,
add-on bundle rounding, seasonal multiplier, waiver, and the late-fee threshold.

Every test builds its own catalog + reservation from scratch.
"""
import pytest

from test_helpers import (
    validate_success, get_success_data, validate_paginated,
    TEST_USERS, make_renter_headers,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["shop_admin_headers"]
AGENT = TEST_USERS["rental_agent_headers"]


# ===========================================================================
# Queue A — dual_variant_calc
# ===========================================================================

def test_rental_provisional_vs_final_diverges_on_actual_window(api):
    """PRD §3.6: "this re-runs the tiered pricing on actual usage rather than the
    requested window — the actual-hours count is the minutes from `picked_up_at` to
    `returned_at` divided by 60 rounded up, the actual-days count those minutes
    divided by 1440 rounded up, and the multiplier is taken from the season covering
    `picked_up_at` (else 10000)."
    PRD §3.6: "The `final_total_cents` is then that rental amount plus the waiver
    plus the add-ons subtotal plus `late_fee_cents` plus the damage charge from the
    assessment, with the rental rounded before the late and damage amounts are added"
    PRD §3.6: "Because the final selection runs on actual elapsed time, it
    legitimately diverges from the provisional quote whenever the actual window
    differs from the requested one."

    Design: Difficulty/dual_variant_calc/rental_cost_provisional_vs_final_diverges_on_actual_window
    """
    # Clock with no season -> x1.0. hourly=1000 daily=3000 seasonal=20000.
    fx.set_clock("2026-04-01T09:00:00Z")
    s = fx.setup_catalog(category="KAYAK", asset_tag="KAY-1",
                         customer_overrides={"email": "dana@x.com", "skill_level": "INTERMEDIATE"})
    res = fx.create_reservation(s["customer"]["id"], s["gear_unit"]["id"], s["gear_unit"]["version"],
                                "2026-04-01T09:00:00Z", "2026-04-01T11:00:00Z", actor=AGENT)
    # Provisional: 2h -> hourly base 2000 cheapest, basis HOURLY.
    assert res["quoted_total_cents"] == 2000
    assert res["quoted_rate_basis"] == "HOURLY"

    fx.confirm_reservation(res["id"], actor=AGENT)
    fx.checkout_reservation(res["id"], "GOOD")
    fx.set_clock("2026-04-01T13:30:00Z")
    final = validate_success(
        api.checkin_reservation(res["id"], {"condition_rating": "GOOD"}, AGENT))
    # Actual 4.5h -> actual_hours=5, actual_days=1: hourly 5000, daily 3000 -> DAILY 3000.
    # late: due 11:00 + grace 15 = 11:15; return 13:30 -> 135 min -> ceil(135/60)=3 -> 3*800=2400.
    # final = 3000 + 2400 = 5400.
    assert final["late_fee_cents"] == 2400
    assert final["final_total_cents"] == 5400
    assert final["final_total_cents"] != res["quoted_total_cents"]


def test_rental_provisional_basis_hourly_recorded(api):
    """PRD §3.3: "The chosen base is the smallest of these three, and
    `quoted_rate_basis` records which tier produced it; when two or more tie for
    cheapest, the tie is broken in the order `HOURLY` before `DAILY` before `SEASONAL`."
    PRD §3.3: "the hourly base is `hourly_cents` times the started-hours count, the
    daily base is `daily_cents` times the started-days count, and the seasonal base
    is `seasonal_flat_cents` flat regardless of span."

    Design: Difficulty/dual_variant_calc/rental_cost_provisional_vs_final_diverges_on_actual_window
    """
    fx.set_clock("2026-04-01T09:00:00Z")
    s = fx.setup_catalog(category="KAYAK", asset_tag="KAY-1B",
                         customer_overrides={"email": "dana2@x.com", "skill_level": "INTERMEDIATE"})
    res = fx.create_reservation(s["customer"]["id"], s["gear_unit"]["id"], s["gear_unit"]["version"],
                                "2026-04-01T09:00:00Z", "2026-04-01T11:00:00Z", actor=AGENT)
    assert res["quoted_total_cents"] == 2000
    assert res["quoted_rate_basis"] == "HOURLY"


# ===========================================================================
# Queue A — combinatorial_formula
# ===========================================================================

def test_rate_tier_min_three_inputs_hourly_wins_tie(api):
    """PRD §3.3: "Three base figures are formed: the hourly base is `hourly_cents`
    times the started-hours count, the daily base is `daily_cents` times the
    started-days count, and the seasonal base is `seasonal_flat_cents` flat regardless
    of span."
    PRD §3.3: "The chosen base is the smallest of these three, and `quoted_rate_basis`
    records which tier produced it; when two or more tie for cheapest, the tie is
    broken in the order `HOURLY` before `DAILY` before `SEASONAL`."

    Design: Difficulty/combinatorial_formula/rate_tier_min_selection_three_inputs_nonlinear
    """
    # 3h window: base_h=1000*3=3000, base_d=3000*1=3000, base_s=20000 -> tie HOURLY wins.
    fx.set_clock("2026-05-01T08:00:00Z")
    s = fx.setup_catalog(category="SUP", asset_tag="SUP-1",
                         gear_type_overrides={"name": "Cruiser", "size_label": "11ft"},
                         customer_overrides={"email": "sam@x.com", "skill_level": "EXPERT"},
                         customer_actor="RENTER")
    res = fx.create_reservation(s["customer"]["id"], s["gear_unit"]["id"], s["gear_unit"]["version"],
                                "2026-05-01T08:00:00Z", "2026-05-01T11:00:00Z",
                                actor="RENTER")
    assert res["quoted_total_cents"] == 3000
    assert res["quoted_rate_basis"] == "HOURLY"


def test_addons_round_per_line_then_sum_bundle_discount(api):
    """PRD §3.4: "A bundle condition holds when the reservation carries at least 2
    `PACKAGE` add-on lines; when it holds, every line's snapshotted `price_cents` is
    multiplied by 0.95, a 5% bundle discount."
    PRD §3.4: "The rounding order is pinned: each line's post-discount price is
    rounded half up to whole cents **first**, and only then are the rounded line
    amounts summed — summing first and rounding the total is incorrect."

    Design: Difficulty/combinatorial_formula/addons_round_per_line_then_sum_not_sum_then_round
    """
    # Two PACKAGE add-ons at 333c -> round(333*0.95)=round(316.35)=316 each -> 632 (not 633).
    fx.set_clock("2026-05-02T08:00:00Z")
    s = fx.setup_catalog(category="SUP", asset_tag="SUP-2",
                         gear_type_overrides={"name": "Race", "size_label": "14ft"},
                         customer_overrides={"email": "ivy@x.com", "skill_level": "EXPERT"},
                         customer_actor="RENTER")
    ao1 = fx.create_addon(kind="PACKAGE", category="SUP", name="Dry Bag", price_cents=333)
    ao2 = fx.create_addon(kind="PACKAGE", category="SUP", name="Cooler", price_cents=333)
    cust_id = s["customer"]["id"]
    res = fx.create_reservation(cust_id, s["gear_unit"]["id"], s["gear_unit"]["version"],
                                "2026-05-02T08:00:00Z", "2026-05-02T10:00:00Z", actor="RENTER")
    rh = make_renter_headers(cust_id)
    get_success_data(api.attach_addon(res["id"], {"addon_id": ao1["id"]}, rh))
    get_success_data(api.attach_addon(res["id"], {"addon_id": ao2["id"]}, rh))
    final = validate_success(api.get_reservation(res["id"], rh))
    # rental 2000 (2h) + addons 632 = 2632.
    assert final["quoted_total_cents"] == 2632


# ===========================================================================
# Queue A — boundary_precision_check
# ===========================================================================

def test_late_fee_exactly_at_grace_boundary_is_on_time(api):
    """PRD §3.6: "the grace deadline is `due_at` plus the rate card's `grace_minutes`;
    if `returned_at` is at or before that deadline the return is on time and
    `late_fee_cents` is 0, and the deadline is inclusive."

    Design: Difficulty/boundary_precision_check/late_fee_exactly_at_grace_boundary_is_on_time
    """
    # due 10:00, grace 15 -> grace_end 10:15; return EXACTLY 10:15 -> on time.
    s = fx.setup_picked_up_reservation(category="SUP", clock="2026-05-09T08:00:00Z",
                                       pickup_at="2026-05-09T08:00:00Z",
                                       due_at="2026-05-09T10:00:00Z", asset_tag="SUP-5")
    fx.set_clock("2026-05-09T10:15:00Z")
    final = validate_success(
        api.checkin_reservation(s["reservation"]["id"], {"condition_rating": "GOOD"}, AGENT))
    assert final["late_fee_cents"] == 0


def test_empty_addon_set_quote_excludes_addons_subtotal(api):
    """PRD §3.3: "The provisional grand total stored as `quoted_total_cents` is the
    rental amount plus the waiver amount plus the add-ons subtotal (§3.4), and it is
    forward-looking — no late or damage charge is included."

    Design: Difficulty/boundary_precision_check/empty_addon_set_quote_excludes_addons_subtotal_zero
    """
    # No add-ons, 2h window -> rental 2000 only.
    fx.set_clock("2026-05-10T08:00:00Z")
    s = fx.setup_catalog(category="SUP", asset_tag="SUP-6",
                         customer_overrides={"email": "hal@x.com", "skill_level": "EXPERT"},
                         customer_actor="RENTER")
    res = fx.create_reservation(s["customer"]["id"], s["gear_unit"]["id"], s["gear_unit"]["version"],
                                "2026-05-10T08:00:00Z", "2026-05-10T10:00:00Z", actor="RENTER")
    assert res["quoted_total_cents"] == 2000


# ===========================================================================
# Queue B — calculations (corner)
# ===========================================================================

def test_seasonal_multiplier_applied_to_chosen_base(api):
    """PRD §3.3: "The applicable multiplier in basis points is taken from the season
    window whose half-open interval contains `pickup_at` and whose category matches the
    gear type's category; if no such season exists the multiplier is 10000."
    PRD §3.3: "The rental amount is the chosen base multiplied by the multiplier basis
    points divided by 10000, with the multiplier applied **before** rounding and the
    product then rounded half up to whole cents."

    Design: Corner/calculations/seasonal_multiplier_applied_to_chosen_base
    """
    # x1.2 season covers 2026-02-01; 2h base 2000 -> round(2000*12000/10000)=2400.
    fx.set_clock("2026-02-01T08:00:00Z")
    gt = fx.create_gear_type(category="SKI", name="Seas", size_label="170cm")
    rc = fx.create_rate_card(gt["id"])
    fx.create_season_window(category="SKI", label="Peak", starts_on="2026-01-15T00:00:00Z",
                            ends_on="2026-03-01T00:00:00Z", demand_multiplier_bp=12000)
    unit = fx.create_gear_unit(gt["id"], rc["id"], asset_tag="SEAS-1")
    cust = fx.create_customer(actor=AGENT, email="al@x.com", skill_level="EXPERT")
    res = fx.create_reservation(cust["id"], unit["id"], unit["version"],
                                "2026-02-01T08:00:00Z", "2026-02-01T10:00:00Z", actor=AGENT)
    assert res["quoted_total_cents"] == 2400
    assert res["quoted_rate_basis"] == "HOURLY"


def test_damage_waiver_per_day_added_to_quote(api):
    """PRD §3.3: "A waiver amount is added only when `damage_waiver_opted` is true,
    equal to `damage_waiver_cents_per_day` times the started-days count, and zero
    otherwise."

    Design: Corner/calculations/damage_waiver_per_day_added_to_quote
    """
    # 2h window -> span_days=1; waiver 400 -> rental 2000 + 400 = 2400.
    fx.set_clock("2026-06-11T08:00:00Z")
    s = fx.setup_catalog(category="KAYAK", asset_tag="WVQ-1",
                         customer_overrides={"email": "bea@x.com", "skill_level": "EXPERT"})
    res = fx.create_reservation(s["customer"]["id"], s["gear_unit"]["id"], s["gear_unit"]["version"],
                                "2026-06-11T08:00:00Z", "2026-06-11T10:00:00Z", actor=AGENT,
                                damage_waiver_opted=True)
    assert res["quoted_total_cents"] == 2400


def test_late_fee_one_minute_past_grace_charges_started_hour(api):
    """PRD §3.6: "Otherwise the late hours are the minutes from the grace deadline to
    `returned_at` divided by 60 and rounded up to a whole number, and `late_fee_cents`
    is `late_fee_cents_per_hour` times that started-hour count."

    Design: Corner/calculations/late_fee_one_minute_past_grace_charges_started_hour
    """
    # due 10:00, grace 15 -> grace_end 10:15; return 10:16 -> ceil(1/60)=1 -> 800.
    s = fx.setup_picked_up_reservation(category="KAYAK", clock="2026-06-12T08:00:00Z",
                                       pickup_at="2026-06-12T08:00:00Z",
                                       due_at="2026-06-12T10:00:00Z", asset_tag="LT-1")
    fx.set_clock("2026-06-12T10:16:00Z")
    final = validate_success(
        api.checkin_reservation(s["reservation"]["id"], {"condition_rating": "GOOD"}, AGENT))
    assert final["late_fee_cents"] == 800


def test_quote_read_recomputes_provisional_total(api):
    """PRD §3.3: "**Quote pricing** is computed at create time and may be recomputed on
    demand without mutating the lifecycle."
    PRD §3.3: "The provisional grand total stored as `quoted_total_cents` is the
    rental amount plus the waiver amount plus the add-ons subtotal (§3.4)"

    Design: Corner/endpoints/quote_read_recomputes_provisional_total
    """
    fx.set_clock("2026-06-16T08:00:00Z")
    s = fx.setup_catalog(category="KAYAK", asset_tag="QT-1",
                         customer_overrides={"email": "gil@x.com", "skill_level": "EXPERT"})
    res = fx.create_reservation(s["customer"]["id"], s["gear_unit"]["id"], s["gear_unit"]["version"],
                                "2026-06-16T08:00:00Z", "2026-06-16T10:00:00Z", actor=AGENT)
    quote = validate_success(api.get_reservation_quote(res["id"], AGENT))
    assert quote["quoted_total_cents"] == 2000
