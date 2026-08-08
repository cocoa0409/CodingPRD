"""Tiered, capped self-pay refill pricing — provisional vs final variants (PRD §3.6)."""
from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
    setup_plan_with_prescription, create_refill,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def test_refill_provisional_charge_from_requested_units(api):
    """PRD §3.6: "The number of units is `requested_quantity_units` for the provisional
    charge computed at create time and `dispensed_quantity_units` for the final charge
    computed at dispense time."
    PRD §3.6: "the first 4 units are each billed at the prescription's full
    `unit_price_cents`; the next 6 units — those numbered 5 through 10 — are each
    billed at the `unit_price_cents` multiplied by 0.90 and rounded half up to a whole
    cent; and every unit beyond the tenth is billed at the `unit_price_cents`
    multiplied by 0.80 and rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/refill_charge_provisional_vs_final
    """
    ctx = setup_plan_with_prescription()  # PLUS discount 0.25, unit_price 5000, controlled
    refill = create_refill(ctx, requested_quantity_units=8)
    # gross = 4*5000 + 4*4500 = 38000; +1500 surcharge; -round(38000*0.25)=9500 => 30000
    assert refill["provisional_charge_cents"] == 30000


def test_refill_final_charge_differs_from_provisional(api):
    """PRD §3.6: "The provisional variant stores its result in `provisional_charge_cents`;
    the final variant stores it in `final_charge_cents`, which may differ from the
    provisional figure when the dispensed quantity differs from the requested quantity."

    Design: Difficulty/dual_variant_calc/refill_charge_provisional_vs_final
    """
    ctx = setup_plan_with_prescription()
    refill = create_refill(ctx, requested_quantity_units=8)
    dispensed = validate_success(
        api.dispense_refill_order(refill["id"], {"dispensed_quantity_units": 10}, ctx["pharmacist_headers"]), 200
    )
    # gross = 4*5000 + 6*4500 = 47000; +1500 surcharge; -round(47000*0.25)=11750 => 36750
    assert dispensed["final_charge_cents"] == 36750
    assert refill["provisional_charge_cents"] != dispensed["final_charge_cents"]
    assert refill["provisional_charge_cents"] == 30000


def test_refill_tiered_cost_with_surcharge_dispensed_ten(api):
    """PRD §3.6: "If the prescription is controlled (`is_controlled` true), add a flat
    controlled-substance surcharge of 1500 cents; otherwise add nothing. Compute the
    member discount as the gross drug cost multiplied by the `refill_discount_pct` of
    the plan tied to the refill order's membership, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/refill_tiered_cost_with_caps_mode_a
    """
    ctx = setup_plan_with_prescription()
    refill = create_refill(ctx, requested_quantity_units=8)
    dispensed = validate_success(
        api.dispense_refill_order(refill["id"], {"dispensed_quantity_units": 10}, ctx["pharmacist_headers"]), 200
    )
    assert dispensed["final_charge_cents"] == 36750


def test_refill_charge_clamped_to_floor(api):
    """PRD §3.6: "The final charge is the subtotal clamped to a floor of 1000 cents and
    a ceiling of 100000 cents — that is, a subtotal below 1000 becomes 1000 and a
    subtotal above 100000 becomes 100000."

    Design: Difficulty/combinatorial_formula/refill_tiered_cost_with_caps_mode_a
    """
    ctx = setup_plan_with_prescription(rx_overrides={"unit_price_cents": 100, "is_controlled": False})
    refill = create_refill(ctx, requested_quantity_units=1)
    # gross = 1*100 = 100; surcharge 0; discount round(100*0.25)=25; subtotal 75 -> clamped to 1000
    assert refill["provisional_charge_cents"] == 1000
