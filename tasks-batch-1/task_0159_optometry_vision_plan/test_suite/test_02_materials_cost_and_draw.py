"""Materials cost and draw: tiered frame cap, provisional vs final reconciliation.

Covers the materials_cost_and_draw calculation at placement (PRD §3.5) and the
re-evaluation at dispense (PRD §3.6).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    setup_active_rx,
    place_lab_order,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]


def test_premium_tier_frame_cap_covers_full_frame(api):
    """PRD §3.5: "It then scales a base frame allowance of 13,000 cents by a tier
    multiplier — 1.00 for `STANDARD`, 1.20 for `PREMIUM`, and 1.50 for `DESIGNER` —
    and rounds that product half up to whole cents to get the frame cap. The
    carrier-covered frame amount is the smaller of the actual `frame_charge_cents` and
    that frame cap. The desired draw is the covered frame amount plus the full
    `lens_charge_cents`."

    PREMIUM cap = round(13000 * 1.20) = 15600 >= 15000 frame; draw = 15000 + 8000 = 23000;
    patient_materials = 23000 retail - 23000 draw = 0.

    Design: Difficulty/combinatorial_formula/materials_tiered_min_cap_nonlinear_mode_a
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "VSP"},
                          elig=True, elig_overrides={"materials_allowance_cents": 40000})
    order = validate_success(api.create_lab_order({
        "prescription_id": ctx["rx"]["id"],
        "eligibility_id": ctx["elig"]["id"],
        "expected_eligibility_version": ctx["elig_v0"],
        "frame_charge_cents": 15000,
        "lens_charge_cents": 8000,
        "frame_brand_tier": "PREMIUM",
    }, ctx["opt_h"]), 201)

    assert order["materials_draw_cents"] == 23000
    assert order["patient_materials_cost_cents"] == 0


def test_standard_tier_frame_cap_leaves_patient_remainder(api):
    """PRD §3.5: "The carrier-covered frame amount is the smaller of the actual
    `frame_charge_cents` and that frame cap. The desired draw is the covered frame
    amount plus the full `lens_charge_cents`."

    STANDARD cap = round(13000 * 1.00) = 13000 < 15000 frame; draw = 13000 + 8000 = 21000;
    patient_materials = 23000 retail - 21000 = 2000.

    Design: Difficulty/combinatorial_formula/materials_tiered_min_cap_nonlinear_mode_a
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "VSP"},
                          elig=True, elig_overrides={"materials_allowance_cents": 40000})
    order = validate_success(api.create_lab_order({
        "prescription_id": ctx["rx"]["id"],
        "eligibility_id": ctx["elig"]["id"],
        "expected_eligibility_version": ctx["elig_v0"],
        "frame_charge_cents": 15000,
        "lens_charge_cents": 8000,
        "frame_brand_tier": "STANDARD",
    }, ctx["opt_h"]), 201)

    assert order["materials_draw_cents"] == 21000
    assert order["patient_materials_cost_cents"] == 2000


def test_designer_tier_frame_cap_constant_applied(api):
    """PRD §3.5: "It then scales a base frame allowance of 13,000 cents by a tier
    multiplier — 1.00 for `STANDARD`, 1.20 for `PREMIUM`, and 1.50 for `DESIGNER` —
    and rounds that product half up to whole cents to get the frame cap. The
    carrier-covered frame amount is the smaller of the actual `frame_charge_cents` and
    that frame cap."

    DESIGNER cap = round(13000 * 1.50) = 19500; 25000 frame capped at 19500; draw =
    19500 + 8000 = 27500; patient_materials = 33000 retail - 27500 = 5500.

    Design: Corner/calculations/designer_tier_frame_cap_constant_applied
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "VSP"},
                          elig=True, elig_overrides={"materials_allowance_cents": 40000})
    order = validate_success(api.create_lab_order({
        "prescription_id": ctx["rx"]["id"],
        "eligibility_id": ctx["elig"]["id"],
        "expected_eligibility_version": ctx["elig_v0"],
        "frame_charge_cents": 25000,
        "lens_charge_cents": 8000,
        "frame_brand_tier": "DESIGNER",
    }, ctx["opt_h"]), 201)

    assert order["materials_draw_cents"] == 27500
    assert order["patient_materials_cost_cents"] == 5500


def test_provisional_draw_capped_at_remaining_pool(api):
    """PRD §3.5: "Because this order has no draw committed yet at placement, the room
    available to it is simply the `MATERIALS` pool's current `remaining_cents`; the
    actual draw committed, recorded on the order as `materials_draw_cents`, is the
    smaller of the desired draw and that available room, so a draw can never exceed the
    room left in the pool."

    Sibling A draws 21000 leaving 19000; order B's desired 21000 is capped to 19000
    provisionally; patient_materials = 23000 - 19000 = 4000.

    Design: Difficulty/dual_variant_calc/materials_provisional_vs_final_diverges_on_laborder_domain
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "VSP"},
                          elig=True, elig_overrides={"materials_allowance_cents": 40000})
    rx_id, opt_h, elig_id = ctx["rx"]["id"], ctx["opt_h"], ctx["elig"]["id"]

    place_lab_order(rx_id, opt_h, eligibility_id=elig_id,
                    expected_eligibility_version=ctx["elig_v0"], frame_charge_cents=15000,
                    lens_charge_cents=8000, frame_brand_tier="STANDARD")
    elig_v1 = get_success_data(api.get_eligibility(elig_id, FRONT_DESK))["version"]

    order_b = validate_success(api.create_lab_order({
        "prescription_id": rx_id,
        "eligibility_id": elig_id,
        "expected_eligibility_version": elig_v1,
        "frame_charge_cents": 15000,
        "lens_charge_cents": 8000,
        "frame_brand_tier": "STANDARD",
    }, opt_h), 201)

    assert order_b["materials_draw_cents"] == 19000
    assert order_b["patient_materials_cost_cents"] == 4000


def test_final_draw_recomputed_upward_after_sibling_cancel(api):
    """PRD §3.6: "For this final recompute, the room available to the order is the
    pool's current `remaining_cents` plus this order's own already-committed draw,
    conceptually returning the order's existing draw to the pool before re-drawing; the
    new draw is again the smaller of the desired draw and that available room. The
    difference between the new draw and the previously committed `materials_draw_cents`
    is the delta by which the pool's `consumed_cents` is adjusted, and
    `materials_draw_cents`, `remaining_cents`, and the order's
    `patient_materials_cost_cents` are reconciled to the final figures."

    After sibling A is cancelled (freeing 21000), order B re-draws its full desired
    21000 at dispense; patient_materials drops from 4000 to 2000.

    Design: Difficulty/dual_variant_calc/materials_provisional_vs_final_diverges_on_laborder_domain
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "VSP"},
                          elig=True, elig_overrides={"materials_allowance_cents": 40000})
    rx_id, opt_h, opt_id, elig_id = ctx["rx"]["id"], ctx["opt_h"], ctx["opt"]["id"], ctx["elig"]["id"]

    order_a = place_lab_order(rx_id, opt_h, eligibility_id=elig_id,
                              expected_eligibility_version=ctx["elig_v0"],
                              frame_charge_cents=15000, lens_charge_cents=8000,
                              frame_brand_tier="STANDARD")
    elig_v1 = get_success_data(api.get_eligibility(elig_id, FRONT_DESK))["version"]
    order_b = place_lab_order(rx_id, opt_h, eligibility_id=elig_id,
                              expected_eligibility_version=elig_v1, frame_charge_cents=15000,
                              lens_charge_cents=8000, frame_brand_tier="STANDARD")
    assert order_b["materials_draw_cents"] == 19000  # provisional

    get_success_data(api.cancel_lab_order(order_a["id"], opt_h))
    get_success_data(api.send_lab_order_to_lab(order_b["id"], opt_h))
    dispensed = validate_success(api.dispense_lab_order(
        order_b["id"], {"dispensing_optician_id": opt_id}, opt_h), 200)

    assert dispensed["materials_draw_cents"] == 21000
    assert dispensed["patient_materials_cost_cents"] == 2000


def test_lab_order_draw_visible_in_create_response(api):
    """PRD §3.5: "The pool's `consumed_cents` is then increased by that committed draw
    and its `remaining_cents` recomputed. The patient's out-of-pocket for materials,
    recorded as `patient_materials_cost_cents`, is the retail total minus the committed
    draw."

    STANDARD frame 15000 capped at 13000 + lens 8000 = 21000 draw; retail 23000 -
    21000 = 2000 patient materials, both present in the create response.

    Design: Corner/consistency_model/immediate_visibility_of_draw_on_create_response
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "VSP"},
                          elig=True, elig_overrides={"materials_allowance_cents": 40000})
    order = validate_success(api.create_lab_order({
        "prescription_id": ctx["rx"]["id"],
        "eligibility_id": ctx["elig"]["id"],
        "expected_eligibility_version": ctx["elig_v0"],
        "frame_charge_cents": 15000,
        "lens_charge_cents": 8000,
        "frame_brand_tier": "STANDARD",
    }, ctx["opt_h"]), 201)

    assert order["materials_draw_cents"] == 21000
    assert order["patient_materials_cost_cents"] == 2000
