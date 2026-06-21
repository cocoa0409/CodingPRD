"""Dual-variant pricing and combinatorial quote logic.

Covers the provisional-vs-settled admission divergence on group confirm, the
estimate-vs-scale pumpkin divergence across the heavy breakpoint, and the
tier-selected group quote. Every test builds its own farm + policy + window.
"""
from test_helpers import validate_success
from test_helpers import fixtures as fx
from test_helpers.test_users import make_group_leader_headers
from test_helpers.api_client import api_client


# ===========================================================================
# Queue A — dual_variant_calc / admission provisional vs settled
# ===========================================================================

def test_admission_provisional_no_discount_at_create(api):
    """PRD §3.5: "The **provisional** variant is computed at create and re-pinned
    at confirm into `admission_charge_cents`, and it reads the group's status as
    of that moment — a reservation created before its group is `CONFIRMED`
    carries no discount."

    Design: Difficulty/dual_variant_calc/admission_provisional_vs_settled_diverge_on_group_confirm
    """
    fx.set_clock("2026-10-10T12:00:00Z")
    farm = fx.create_farm(name="Harvest Hollow", parking_fee_cents=1000, window_buffer_minutes=30)
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=40)
    leader = fx.create_visitor(email="leader@x.com", full_name="Glenda Leader")
    visitor = fx.create_visitor(email="vera@x.com", full_name="Vera Visitor")
    fx.create_group(farm["id"], window["id"], leader["id"], "FIELD_TRIP",
                    adult_count=6, child_count=12)

    # Reservation created while the group is still QUOTED -> no discount.
    res = fx.create_pending_reservation(window["id"], visitor["id"], window["version"],
                                        adult_count=2, child_count=1,
                                        group_booking_id=None)
    # 2*2000 + 1*1200 = 5200, no discount applied at create.
    assert res["admission_charge_cents"] == 5200, (
        f"provisional admission should be 5200 (no discount), got {res['admission_charge_cents']}"
    )


def test_admission_settled_diverges_after_group_confirmed(api):
    """PRD §3.5: "The **settled** variant is recomputed at check-in into
    `settled_charge_cents`, re-evaluating the group's status as of check-in; a
    reservation whose group became `CONFIRMED` between create and check-in is
    discounted at settle though it was not at create, so the two figures
    legitimately differ for the same party."
    PRD §3.5: "the rate is the policy's `school_discount_pct` when the group's
    `kind` is `SCHOOL`, and the policy's `group_discount_pct` otherwise; the
    discounted base is the base multiplied by one minus that rate, rounded
    half-up to whole cents exactly once after the multiply."

    Design: Difficulty/dual_variant_calc/admission_provisional_vs_settled_diverge_on_group_confirm
    """
    fx.set_clock("2026-10-10T12:00:00Z")
    farm = fx.create_farm(name="Harvest Hollow", parking_fee_cents=1000, window_buffer_minutes=30)
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=40)
    leader = fx.create_visitor(email="leader@x.com", full_name="Glenda Leader")
    visitor = fx.create_visitor(email="vera@x.com", full_name="Vera Visitor")
    group = fx.create_group(farm["id"], window["id"], leader["id"], "FIELD_TRIP",
                            adult_count=6, child_count=12)

    res = fx.create_pending_reservation(window["id"], visitor["id"], window["version"],
                                        adult_count=2, child_count=1,
                                        group_booking_id=group["id"])
    assert res["admission_charge_cents"] == 5200

    # Confirm the reservation while the group is still QUOTED so the provisional
    # re-pin at confirm reads the group as un-confirmed (PRD §3.5: the provisional
    # variant "reads the group's status as of that moment") and stays 5200. Only
    # afterwards confirm the group and check in, so the settled variant re-reads
    # the now-CONFIRMED group and diverges.
    fx.confirm_reservation(res["id"], visitor["id"])
    win_v1 = fx.window_version(window["id"])
    fx.confirm_group(group["id"], leader["id"], win_v1)
    fx.sign_waiver(res["id"], visitor["id"], "Adult One")
    fx.sign_waiver(res["id"], visitor["id"], "Adult Two")
    fx.sign_waiver(res["id"], visitor["id"], "Child One", is_minor=True, guardian_name="Adult One")
    checked_in = fx.check_in_reservation(res["id"])

    # round_half_up(5200 * (1 - 0.20)) = 4160.
    assert checked_in["settled_charge_cents"] == 4160, (
        f"settled admission should be 4160 (20% group discount), got {checked_in['settled_charge_cents']}"
    )
    assert checked_in["admission_charge_cents"] == 5200
    assert checked_in["settled_charge_cents"] != checked_in["admission_charge_cents"], (
        "settled and provisional must diverge once the group is confirmed at check-in"
    )


# ===========================================================================
# Queue A — dual_variant_calc / pumpkin estimate vs scale
# ===========================================================================

def test_pumpkin_estimate_per_lb_below_breakpoint(api):
    """PRD §3.5: "a pumpkin below the breakpoint is charged per pound, its weight
    multiplied by `pumpkin_per_lb_cents` and rounded half-up to whole cents."
    PRD §3.5: "The **estimate** variant runs at add using the visitor-declared
    `estimated_weight_lb` and stores into `charge_cents` while the purchase is
    `ESTIMATED`".

    Design: Difficulty/dual_variant_calc/pumpkin_estimate_vs_scale_diverge_across_breakpoint
    """
    s = fx.setup_checked_in(capacity=10, adult_count=1, child_count=0)
    res = s["reservation"]
    pk = fx.add_pumpkin(res["id"], s["visitor"]["id"], estimated_weight_lb=18)
    # 18 < 20 -> round_half_up(18 * 150) = 2700.
    assert pk["charge_cents"] == 2700, f"estimate per-lb should be 2700, got {pk['charge_cents']}"
    assert pk["status"] == "ESTIMATED"


def test_pumpkin_scale_flips_to_flat_each_across_breakpoint(api):
    """PRD §3.5: "a pumpkin whose weight is at or above the breakpoint is a heavy
    pumpkin and is charged the flat `pumpkin_flat_each_cents` regardless of exact
    weight".
    PRD §3.5: "If the scale weight crosses the breakpoint that the estimate
    missed, the same physical pumpkin flips from per-pound to flat-each and the
    two charges diverge."

    Design: Difficulty/dual_variant_calc/pumpkin_estimate_vs_scale_diverge_across_breakpoint
    """
    s = fx.setup_checked_in(capacity=10, adult_count=1, child_count=0)
    res = s["reservation"]
    pk = fx.add_pumpkin(res["id"], s["visitor"]["id"], estimated_weight_lb=18)
    assert pk["charge_cents"] == 2700

    weighed = fx.weigh_out(pk["id"], scale_weight_lb=21)
    # 21 >= 20 -> flat 2500, diverging from the 2700 estimate.
    assert weighed["charge_cents"] == 2500, f"scale flat-each should be 2500, got {weighed['charge_cents']}"
    assert weighed["status"] == "WEIGHED"
    assert weighed["charge_cents"] != 2700, "scale charge must diverge from the per-lb estimate"


# ===========================================================================
# Queue A — combinatorial_formula / group_quote tier select
# ===========================================================================

def test_group_quote_school_tier_discount_above_threshold(api):
    """PRD §3.7: "The group qualifies for a discount only when its `headcount` is
    at least the policy's `group_rate_min_headcount`; if it qualifies, the rate
    is `school_discount_pct` when the `kind` is `SCHOOL` and `group_discount_pct`
    otherwise, and if it does not qualify the rate is zero."
    PRD §3.7: "The `quoted_total_cents` is the per-head base multiplied by one
    minus that rate, rounded half-up to whole cents exactly once after the
    multiply — the sum is rounded, not each head individually."

    Design: Difficulty/combinatorial_formula/group_quote_school_tier_select_above_threshold
    """
    farm = fx.create_farm(name="School Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=50)
    leader = fx.create_visitor(email="principal@x.com", full_name="Pat Principal")

    group = fx.create_group(farm["id"], window["id"], leader["id"], "SCHOOL",
                            adult_count=5, child_count=25)
    # per_head_base = 5*2000 + 25*1200 = 40000; headcount 30 >= 15, SCHOOL -> 0.35.
    # round_half_up(40000 * 0.65) = 26000.
    assert group["headcount"] == 30
    assert group["quoted_total_cents"] == 26000, (
        f"SCHOOL quote should be 26000, got {group['quoted_total_cents']}"
    )


def test_group_quote_no_discount_below_threshold(api):
    """PRD §3.7: "The group qualifies for a discount only when its `headcount` is
    at least the policy's `group_rate_min_headcount`; if it qualifies, the rate
    is `school_discount_pct` when the `kind` is `SCHOOL` and `group_discount_pct`
    otherwise, and if it does not qualify the rate is zero."

    Design: Difficulty/combinatorial_formula/group_quote_school_tier_select_above_threshold
    """
    farm = fx.create_farm(name="Small School Farm")
    fx.create_active_policy(farm["id"])
    window = fx.create_window(farm["id"], capacity=50)
    leader = fx.create_visitor(email="small@x.com", full_name="Sam Small")

    # headcount 12 < 15 -> no discount; SCHOOL kind does not matter below threshold.
    group = fx.create_group(farm["id"], window["id"], leader["id"], "SCHOOL",
                            adult_count=4, child_count=8)
    # per_head_base = 4*2000 + 8*1200 = 17600; rate 0 -> 17600.
    assert group["headcount"] == 12
    assert group["quoted_total_cents"] == 17600, (
        f"below-threshold quote should be 17600 (no discount), got {group['quoted_total_cents']}"
    )
