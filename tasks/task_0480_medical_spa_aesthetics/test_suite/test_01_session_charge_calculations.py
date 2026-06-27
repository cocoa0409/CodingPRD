"""Session-charge calculation tests: member-vs-non-member divergence, the
load-bearing round-per-line-then-sum order, the loyalty floor + deposit
allocation interaction, and immediate-consistency on commit.

All charges are computed at COMMIT (§3.6).
"""
from test_helpers import (
    validate_success,
    setup_committed_session,
    setup_booked_session,
    commit_session,
    make_provider_headers,
)


def test_member_session_charge_applies_discount(api):
    """PRD §3.6: "That line's cost is the `actual_units` multiplied by the plan's
    `list_price_per_unit_cents` multiplied by one minus the discount fraction,
    rounded half up to whole cents." PRD §3.6: "The applicable discount fraction
    is the patient's membership `member_discount_pct` if the patient has a
    membership, or 0 if the patient has no membership."

    PLUS member, 30u @1333, 15% discount: round_half_up(30*1333*0.85)=33992.

    Design: Difficulty/dual_variant_calc/session_charge_member_vs_nonmember_diverges
    """
    sc = setup_committed_session(member=True, member_discount_pct=0.15,
                                 list_price_per_unit_cents=1333, planned_units=30,
                                 actual_units=30, max_units_authorized=60)
    data = validate_success(api.get_treatment_session(
        sc.session_id, make_provider_headers(sc.injector_id)))
    assert data["final_charge_cents"] == 33992, (
        f"member charge should be 33992, got {data['final_charge_cents']}")
    assert data["points_earned_cents_basis"] == 339, (
        f"points basis floor(33992/100)=339, got {data['points_earned_cents_basis']}")


def test_nonmember_session_charge_no_discount(api):
    """PRD §3.6: "The applicable discount fraction is the patient's membership
    `member_discount_pct` if the patient has a membership, or 0 if the patient has
    no membership." PRD §3.6: "That line's cost is the `actual_units` multiplied by
    the plan's `list_price_per_unit_cents` multiplied by one minus the discount
    fraction, rounded half up to whole cents."

    Non-member, 30u @1333, 0% discount: 30*1333=39990 (no discount applied).

    Design: Difficulty/dual_variant_calc/session_charge_member_vs_nonmember_diverges
    """
    sc = setup_committed_session(member=False, list_price_per_unit_cents=1333,
                                 planned_units=30, actual_units=30,
                                 max_units_authorized=60)
    data = validate_success(api.get_treatment_session(
        sc.session_id, make_provider_headers(sc.injector_id)))
    assert data["final_charge_cents"] == 39990, (
        f"non-member charge should be 39990, got {data['final_charge_cents']}")


def test_round_per_line_then_sum_order_is_pinned(api):
    """PRD §3.6: "That line's cost is the `actual_units` multiplied by the plan's
    `list_price_per_unit_cents` multiplied by one minus the discount fraction,
    rounded half up to whole cents." PRD §3.6: "This per-line-then-sum order is
    deliberate and load-bearing — sum-then-round would diverge by cents on
    fractional-cent lines."

    30u @1333 @15% = 33991.5 -> round_half_up -> 33992 (not 33991).

    Design: Difficulty/combinatorial_formula/session_charge_round_per_line_then_sum_order_pinned
    """
    sc = setup_committed_session(member=True, member_discount_pct=0.15,
                                 list_price_per_unit_cents=1333, planned_units=30,
                                 actual_units=30, max_units_authorized=30)
    data = validate_success(api.get_treatment_session(
        sc.session_id, make_provider_headers(sc.injector_id)))
    assert data["final_charge_cents"] == 33992, (
        f"round_half_up per line should yield 33992 not 33991, "
        f"got {data['final_charge_cents']}")


def test_round_per_line_then_sum_points_basis_derived_from_rounded_charge(api):
    """PRD §3.6: "That line's cost is the `actual_units` multiplied by the plan's
    `list_price_per_unit_cents` multiplied by one minus the discount fraction,
    rounded half up to whole cents." PRD §3.6: "The loyalty basis
    `points_earned_cents_basis` is `final_charge_cents` divided by 100, taking the
    floor (one point per whole dollar)."

    The rounded line (33992) drives the points basis floor(33992/100)=339; a
    sum-then-round implementation (33991) would yield the same 339 only if the
    rounded charge is exactly 33992, so the basis pins the per-line rounding.

    Design: Difficulty/combinatorial_formula/session_charge_round_per_line_then_sum_order_pinned
    """
    sc = setup_committed_session(member=True, member_discount_pct=0.15,
                                 list_price_per_unit_cents=1333, planned_units=30,
                                 actual_units=30, max_units_authorized=30)
    data = validate_success(api.get_treatment_session(
        sc.session_id, make_provider_headers(sc.injector_id)))
    assert data["final_charge_cents"] == 33992
    assert data["points_earned_cents_basis"] == 339, (
        f"points basis from rounded charge should be 339, "
        f"got {data['points_earned_cents_basis']}")


def test_loyalty_floor_and_deposit_allocation_interaction(api):
    """PRD §3.6: "The `final_charge_cents` is the subtotal minus the loyalty
    redemption, floored at 0 so it can never go negative." PRD §3.6: "The deposit
    allocated to this session is the smaller of `final_charge_cents` and the plan's
    `deposit_paid_cents`; `balance_due_cents` is `final_charge_cents` minus that
    allocated deposit, but never less than 0."

    Non-member 30u @1333 (subtotal 39990), loyalty_redeemed=0, deposit_paid=25000
    -> final 39990, balance_due = 39990 - min(39990,25000) = 14990.

    Design: Difficulty/combinatorial_formula/session_charge_loyalty_floor_and_deposit_alloc_nonlinear
    """
    sc = setup_committed_session(member=False, list_price_per_unit_cents=1333,
                                 planned_units=30, actual_units=30,
                                 max_units_authorized=30, required_deposit_cents=25000)
    data = validate_success(api.get_treatment_session(
        sc.session_id, make_provider_headers(sc.injector_id)))
    assert data["final_charge_cents"] == 39990, (
        f"final_charge should be 39990, got {data['final_charge_cents']}")
    assert data["balance_due_cents"] == 14990, (
        f"balance_due should be 14990 (39990 - 25000 allocated), "
        f"got {data['balance_due_cents']}")


def test_loyalty_redemption_subtracted_from_subtotal(api):
    """PRD §3.6: "The loyalty redemption is the session's `loyalty_points_redeemed`
    multiplied by the per-point value, where one point is worth one cent." PRD
    §3.6: "The `final_charge_cents` is the subtotal minus the loyalty redemption,
    floored at 0 so it can never go negative."

    PLUS member 20u @1333 @15%: line round_half_up(20*1333*0.85)=22661;
    redeem 200 -> final 22461.

    Design: Difficulty/combinatorial_formula/session_charge_loyalty_floor_and_deposit_alloc_nonlinear
    """
    sc = setup_committed_session(member=True, member_discount_pct=0.15,
                                 list_price_per_unit_cents=1333, planned_units=20,
                                 actual_units=20, max_units_authorized=30,
                                 loyalty_points_redeemed=200, open_loyalty=True)
    data = validate_success(api.get_treatment_session(
        sc.session_id, make_provider_headers(sc.injector_id)))
    assert data["final_charge_cents"] == 22461, (
        f"final_charge should be 22661 subtotal - 200 redeemed = 22461, "
        f"got {data['final_charge_cents']}")


def test_commit_response_carries_charge_immediately(api):
    """PRD §3.6: "Committing advances a session from `BOOKED` to `COMMITTED`." PRD
    §3.6: "That line's cost is the `actual_units` multiplied by the plan's
    `list_price_per_unit_cents` multiplied by one minus the discount fraction,
    rounded half up to whole cents."

    The commit response itself carries `final_charge_cents` and `status`==`COMMITTED`.
    Non-member 20u @1000 -> 20000.

    Design: Corner/consistency_model/immediate_consistency_commit_reflects_charge_in_same_response
    """
    sc = setup_booked_session(member=False, list_price_per_unit_cents=1000,
                              planned_units=20, max_units_authorized=30)
    data = commit_session(sc.session_id, sc.injector_id)
    assert data["status"] == "COMMITTED"
    assert data["final_charge_cents"] == 20000, (
        f"commit response charge should be 20000, got {data['final_charge_cents']}")
