"""Charge calculations: provisional vs finalized service charges, loss vs damage
fees, the combinatorial finalized formula, emblem setup, and the damage tier
boundary.

Every test here translates exactly one design-index instance.
"""
import pytest
from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    setup_provisional_finalized_visit,
    setup_assigned_garment,
    setup_garment_with_soil_strikes,
    make_account,
    make_garment_type,
    make_wash_station,
    make_wearer,
    make_garment,
    make_assignment,
    setup_route_stop_for_account,
    make_service_visit,
    wash_garment,
    list_account_charges,
    reconcile_payload,
    pickup_payload,
    apply_emblem_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
MANAGER = TEST_USERS["account_manager_headers"]
DRIVER = TEST_USERS["route_driver_headers"]


def _charges_of_type(account_id, charge_type):
    return [c for c in list_account_charges(account_id) if c["charge_type"] == charge_type]


# ─── Queue A: dual_variant_calc ───────────────────────────────────────────

def test_provisional_charge_bills_every_assigned_garment(api):
    """PRD §3.9: "Its rental portion is the sum, over every garment of the account
    whose `lifecycle_status` is `ASSIGNED` at delivery time (garments that have been
    lost or retired are excluded), of that garment's type's `weekly_rate_cents` — the
    full weekly rate is charged for each assigned garment regardless of whether it
    actually cycled through the wash."

    Design: Difficulty/dual_variant_calc/provisional_vs_finalized_service_charge_on_visit
    """
    ctx = setup_provisional_finalized_visit(grace=2, weekly_rate_cents=1200,
                                            num_garments=3, num_washed=1, actual_soil_count=1)
    visit = ctx["visit"]
    # 3 ASSIGNED garments x 1200 = 3600; shortage shortfall = max(0, 3-1-2) = 0.
    assert visit["provisional_charge_cents"] == 3600, (
        f"provisional should bill all 3 ASSIGNED garments at full rate, got "
        f"{visit['provisional_charge_cents']}"
    )


def test_finalized_charge_bills_only_washed_garment(api):
    """PRD §3.10: "the rental portion sums the type `weekly_rate_cents` only over the
    account's garments that are `ASSIGNED` **and** whose `cycled_through_wash_this_visit`
    flag is true — that is, only garments that actually completed a full wash cycle this
    visit are billed rent, whereas the provisional variant billed every assigned garment."

    Design: Difficulty/dual_variant_calc/provisional_vs_finalized_service_charge_on_visit
    """
    ctx = setup_provisional_finalized_visit(grace=2, weekly_rate_cents=1200,
                                            num_garments=3, num_washed=1, actual_soil_count=1)
    visit = ctx["visit"]
    reconciled = get_success_data(
        api.reconcile_visit(visit["id"], reconcile_payload(ctx["delivered_version"]), ADMIN)
    )
    # Only 1 garment cycled wash -> rental 1200; reconciled shortfall 0 -> finalized 1200.
    assert reconciled["finalized_charge_cents"] == 1200, (
        f"finalized should bill only the 1 washed garment, got "
        f"{reconciled['finalized_charge_cents']}"
    )
    assert reconciled["finalized_charge_cents"] != reconciled["provisional_charge_cents"], (
        "finalized total must diverge from provisional on identical pickup data"
    )


def test_loss_fee_is_full_replacement_cost(api):
    """PRD §3.6: "When a garment is declared lost, the fee is simply the full
    `replacement_cost_cents` of the garment's type, with no tiering."

    Design: Difficulty/dual_variant_calc/loss_full_replacement_vs_damage_tiered_fee
    """
    acct, wearer, gt, g, asg = setup_assigned_garment(
        grace=0, replacement_cost_cents=8000, weekly_rate_cents=1000, category="JACKET"
    )
    validate_success(api.declare_loss(asg["id"], MANAGER), 200)
    loss_charges = _charges_of_type(acct["id"], "LOSS")
    assert len(loss_charges) == 1, f"exactly one LOSS charge expected, got {len(loss_charges)}"
    assert loss_charges[0]["amount_cents"] == 8000, (
        f"LOSS fee must equal full replacement 8000, got {loss_charges[0]['amount_cents']}"
    )


def test_damage_fee_light_tier_floored(api):
    """PRD §3.6: "Otherwise — fewer than two strikes — the multiplier is 0.25. The raw
    fee is the floor of the replacement cost multiplied by the chosen fraction, and the
    final damage fee is the smaller of that raw figure and the full replacement cost."

    Design: Difficulty/dual_variant_calc/loss_full_replacement_vs_damage_tiered_fee
    """
    acct, wearer, gt, g, asg = setup_assigned_garment(
        grace=0, replacement_cost_cents=8000, weekly_rate_cents=1000, category="JACKET"
    )
    # soil_strikes == 0 (< 2) -> 0.25 tier: floor(8000*0.25) = 2000.
    validate_success(api.declare_damage(asg["id"], MANAGER), 200)
    damage_charges = _charges_of_type(acct["id"], "DAMAGE")
    assert len(damage_charges) == 1, f"exactly one DAMAGE charge expected, got {len(damage_charges)}"
    assert damage_charges[0]["amount_cents"] == 2000, (
        f"DAMAGE at 0 strikes must be floor(8000*0.25)=2000, got {damage_charges[0]['amount_cents']}"
    )


# ─── Queue A: combinatorial_formula ───────────────────────────────────────

def test_finalized_charge_combines_eligibility_shortfall_and_forgiveness(api):
    """PRD §3.10: "The reconciled shortfall is computed exactly as the provisional
    shortfall — the larger of zero and `expected_soil_count` minus `actual_soil_count`
    minus the account's `shortage_grace_units` — but one additional unit is then forgiven
    when the account is in good standing: if the account's `billing_status` is `CURRENT`,
    one is subtracted, and otherwise nothing is forgiven."

    Design: Difficulty/combinatorial_formula/finalized_charge_nested_min_and_conditional_forgiveness
    """
    # grace=0, 4 garments rate 1000, only g1 washed, pickup actual=1 against expected=4.
    acct = make_account(shortage_grace_units=0)
    gt = make_garment_type(weekly_rate_cents=1000, replacement_cost_cents=8000)
    ws = make_wash_station(capacity=5)
    wearer = make_wearer(acct["id"])
    garments = [make_garment(acct["id"], gt["id"]) for _ in range(4)]
    for g in garments:
        make_assignment(g["id"], wearer["id"])
    route, stop = setup_route_stop_for_account(acct["id"])
    visit = make_service_visit(stop["id"], week_index=0)
    get_success_data(api.pickup_visit(visit["id"], pickup_payload(1), DRIVER))
    wash_garment(garments[0]["id"], ws["id"])
    delivered = get_success_data(api.deliver_visit(visit["id"], DRIVER))
    reconciled = get_success_data(
        api.reconcile_visit(visit["id"], reconcile_payload(delivered["version"]), ADMIN)
    )
    # rental = 1000 (g1 only); shortfall = max(0,4-1-0)=3, forgiven=1 -> units=2 -> 3000;
    # finalized = 1000 + 3000 = 4000.
    assert reconciled["finalized_charge_cents"] == 4000, (
        f"finalized should be rental 1000 + shortage 3000 = 4000, got "
        f"{reconciled['finalized_charge_cents']}"
    )


def test_finalized_forgiveness_withheld_when_not_in_good_standing(api):
    """PRD §3.10: "if the account's `billing_status` is `CURRENT`, one is subtracted, and
    otherwise nothing is forgiven. The billable shortage units are the larger of zero and
    the reconciled shortfall minus that forgiveness, and the shortage portion is those
    units multiplied by 1,500 cents each."

    Design: Difficulty/combinatorial_formula/finalized_charge_nested_min_and_conditional_forgiveness
    """
    # Same shape as the CURRENT case, but a prior 60000 LOSS on the SAME account drives it
    # PAST_DUE so the good-standing rebate is withheld: forgiven=0 -> units=3 -> 4500;
    # rental still 1000 (g1 only); finalized = 1000 + 4500 = 5500.
    acct = make_account(shortage_grace_units=0)
    gt = make_garment_type(weekly_rate_cents=1000, replacement_cost_cents=8000)
    gt_cov = make_garment_type(category="COVERALL", replacement_cost_cents=60000)
    ws = make_wash_station(capacity=5)
    wearer = make_wearer(acct["id"])
    garments = [make_garment(acct["id"], gt["id"]) for _ in range(4)]
    for g in garments:
        make_assignment(g["id"], wearer["id"])
    # Drive the account PAST_DUE via a separate 60000 LOSS before reconciliation.
    debt_garment = make_garment(acct["id"], gt_cov["id"])
    debt_asg = make_assignment(debt_garment["id"], wearer["id"])
    get_success_data(api.declare_loss(debt_asg["id"], MANAGER))
    route, stop = setup_route_stop_for_account(acct["id"])
    visit = make_service_visit(stop["id"], week_index=0)
    get_success_data(api.pickup_visit(visit["id"], pickup_payload(1), DRIVER))
    wash_garment(garments[0]["id"], ws["id"])
    delivered = get_success_data(api.deliver_visit(visit["id"], DRIVER))
    reconciled = get_success_data(
        api.reconcile_visit(visit["id"], reconcile_payload(delivered["version"]), ADMIN)
    )
    assert reconciled["finalized_charge_cents"] == 5500, (
        f"without the good-standing rebate finalized should be 1000 + 4500 = 5500, got "
        f"{reconciled['finalized_charge_cents']}"
    )


def test_damage_fee_floor_applied_before_clamp(api):
    """PRD §3.6: "the system first selects the tier multiplier from the garment's
    accumulated `soil_strikes`, then multiplies the replacement cost by that multiplier,
    then floors the product to a whole number of cents, and finally clamps the result so
    it can never exceed the full replacement cost (a damaged garment never costs more
    than a lost one)."

    Design: Difficulty/combinatorial_formula/damage_fee_floor_then_clamp_rounding_order
    """
    # replacement 8001, soil_strikes driven to 4 (HEAVY 0.75): floor(8001*0.75)=floor(6000.75)=6000.
    acct, wearer, gt, g, asg, stop = setup_garment_with_soil_strikes(
        target_strikes=4, replacement_cost_cents=8001
    )
    garment = get_success_data(api.get_garment(g["id"], ADMIN))
    assert garment["soil_strikes"] == 4, f"expected 4 strikes, got {garment['soil_strikes']}"
    validate_success(api.declare_damage(asg["id"], MANAGER), 200)
    damage_charges = _charges_of_type(acct["id"], "DAMAGE")
    assert len(damage_charges) == 1, f"exactly one DAMAGE charge expected, got {len(damage_charges)}"
    assert damage_charges[0]["amount_cents"] == 6000, (
        f"floor(8001*0.75)=6000 proves floor-before-clamp, got {damage_charges[0]['amount_cents']}"
    )


def test_damage_fee_floor_truncates_fractional_cent(api):
    """PRD §3.6: "then multiplies the replacement cost by that multiplier, then floors the
    product to a whole number of cents, and finally clamps the result so it can never
    exceed the full replacement cost (a damaged garment never costs more than a lost one)."

    Design: Difficulty/combinatorial_formula/damage_fee_floor_then_clamp_rounding_order
    """
    # replacement 8002 at HEAVY 0.75: floor(8002*0.75)=floor(6001.5)=6001 — the floor drops
    # the fractional half-cent rather than rounding up to 6002.
    acct, wearer, gt, g, asg, stop = setup_garment_with_soil_strikes(
        target_strikes=4, replacement_cost_cents=8002
    )
    validate_success(api.declare_damage(asg["id"], MANAGER), 200)
    damage_charges = _charges_of_type(acct["id"], "DAMAGE")
    assert len(damage_charges) == 1, f"exactly one DAMAGE charge expected, got {len(damage_charges)}"
    assert damage_charges[0]["amount_cents"] == 6001, (
        f"floor(8002*0.75) must truncate to 6001, not round to 6002, got "
        f"{damage_charges[0]['amount_cents']}"
    )


# ─── Queue B: calculations section ────────────────────────────────────────

def test_first_emblem_charges_setup_reapply_is_free(api):
    """PRD §3.5: "the **first** emblem ever applied to a garment — the boundary where
    `emblem_text` transitions from null to a non-null value — incurs the garment type's
    one-time `emblem_setup_cents` as an `EMBLEM_SETUP` `ServiceCharge`, whereas
    re-applying or changing the text on a garment that already carries an emblem charges
    nothing because the setup has already been amortized."

    Design: Corner/calculations/emblem_first_setup_then_free_reapply
    """
    acct = make_account()
    gt = make_garment_type(emblem_setup_cents=1500)
    g = make_garment(acct["id"], gt["id"])
    # First apply (null -> "ACME") incurs the 1500 setup.
    validate_success(api.apply_emblem(g["id"], apply_emblem_payload("ACME"), MANAGER), 200)
    # Second apply (already emblazoned) changes text but raises no new charge.
    second = validate_success(api.apply_emblem(g["id"], apply_emblem_payload("ACME-2"), MANAGER), 200)
    assert second["emblem_text"] == "ACME-2", f"emblem_text should update, got {second['emblem_text']}"
    setup_charges = _charges_of_type(acct["id"], "EMBLEM_SETUP")
    assert len(setup_charges) == 1, (
        f"only the first emblem should charge setup, found {len(setup_charges)} EMBLEM_SETUP charges"
    )
    assert setup_charges[0]["amount_cents"] == 1500, (
        f"EMBLEM_SETUP must equal the type's emblem_setup_cents 1500, got "
        f"{setup_charges[0]['amount_cents']}"
    )


def test_damage_fee_moderate_tier_at_strike_boundary(api):
    """PRD §3.6: "The tier is chosen by threshold against `soil_strikes`. If the garment's
    `soil_strikes` is at least 4, the multiplier is 0.75. Otherwise, if its `soil_strikes`
    is at least 2, the multiplier is 0.50. Otherwise — fewer than two strikes — the
    multiplier is 0.25."

    Design: Corner/calculations/damage_light_tier_at_strike_boundary
    """
    # soil_strikes == 2 exactly (LIGHT_STRIKE_THRESHOLD): 0.50 tier -> floor(8000*0.50)=4000.
    acct, wearer, gt, g, asg, stop = setup_garment_with_soil_strikes(
        target_strikes=2, replacement_cost_cents=8000
    )
    garment = get_success_data(api.get_garment(g["id"], ADMIN))
    assert garment["soil_strikes"] == 2, f"expected 2 strikes, got {garment['soil_strikes']}"
    validate_success(api.declare_damage(asg["id"], MANAGER), 200)
    damage_charges = _charges_of_type(acct["id"], "DAMAGE")
    assert len(damage_charges) == 1, f"exactly one DAMAGE charge expected, got {len(damage_charges)}"
    assert damage_charges[0]["amount_cents"] == 4000, (
        f"at 2 strikes the 0.50 tier gives floor(8000*0.50)=4000, got "
        f"{damage_charges[0]['amount_cents']}"
    )
