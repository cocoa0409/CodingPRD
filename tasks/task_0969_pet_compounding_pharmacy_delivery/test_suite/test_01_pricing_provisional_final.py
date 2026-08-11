"""Compound-order pricing: provisional estimate vs final price, weight tiers."""
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_lot, create_bench, setup_verified_scenario,
    create_pet, create_verified_vet, create_drug, create_formula,
    create_prescription, verify_prescription,
    create_compound_order, allocate_order, start_compounding, complete_compounding,
    complete_flavoring, qa_pass_order, fetch_compound_order,
    TEST_USERS,
)

CHICKEN_FLAVOR = {"allergen_tags": ["CHICKEN"], "surcharge_cents": 250,
                  "compatible_species": ["DOG", "CAT"]}


def _setup_d1():
    """Verified non-controlled rx qty 30, days_supply 10, 12 kg dog, chicken flavor;
    lots L1 20@110 exp 2027-01-01 (FEFO-first), L2 200@130 exp 2027-06-01."""
    scn = setup_verified_scenario(pet_weight_kg=12, catalog_unit_cost=120,
                                  flavor=CHICKEN_FLAVOR, quantity=30, days_supply=10,
                                  directions="BID")
    scn["lot1"] = create_lot(scn["drug"]["id"], received_qty=20, unit_cost_cents=110,
                             expiration_date="2027-01-01")
    scn["lot2"] = create_lot(scn["drug"]["id"], received_qty=200, unit_cost_cents=130,
                             expiration_date="2027-06-01")
    scn["bench"] = create_bench()
    return scn


def _run_d1_pipeline(scn):
    order = create_compound_order(scn["rx"]["id"], flavoring_id=scn["flavoring"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    allocate_order(order["id"])
    start_compounding(order["id"], scn["bench"]["id"])
    complete_compounding(order["id"])
    complete_flavoring(order["id"])
    final = qa_pass_order(order["id"])
    return order, final


def test_provisional_price_sum_then_round(api):
    """PRD §3.4: "If a flavoring was chosen, its `surcharge_cents` is added."
    PRD §3.4: "The multiplied result is rounded half up to whole cents, once, after
    summing and multiplying."
    qty 30 @ catalog 120 with a 250-cent flavor on a 12 kg dog (tier 1.15):
    round_half_up((30*120 + 250) * 1.15) = round_half_up(4427.5) = 4428.

    Design: Difficulty/dual_variant_calc/compound_price_provisional_vs_final
    """
    scn = _setup_d1()
    order, _final = _run_d1_pipeline(scn)
    assert order["provisional_price_cents"] == 4428, (
        f"provisional expected 4428, got {order['provisional_price_cents']}")


def test_final_price_per_line_rounding_diverges(api):
    """PRD §3.5: "a line amount is computed as the `qty_consumed` multiplied by that
    lot's actual `unit_cost_cents` and uplifted by a three percent waste-shrink
    allowance, with each line rounded half up to whole cents before the lines are
    summed into a lot component."
    PRD §3.5: "Because the final price rounds per line before summing while the
    provisional price rounds once after summing — and because actual lot costs may
    differ from catalog cost — the two figures legitimately diverge on identical
    fill data."
    Lines round(20*110*1.03)=2266 and round(10*130*1.03)=1339; (3605+250)*1.15 =
    4433.25 -> 4433, diverging from the provisional 4428.

    Design: Difficulty/dual_variant_calc/compound_price_provisional_vs_final
    """
    scn = _setup_d1()
    order, final = _run_d1_pipeline(scn)
    assert final["status"] == "READY_TO_DISPATCH"
    assert final["final_price_cents"] == 4433, (
        f"final expected 4433, got {final['final_price_cents']}")
    assert final["final_price_cents"] != order["provisional_price_cents"]


def _setup_f1():
    """Verified rx qty 10, 2 kg dog, NO flavor; lots 7@115 exp 2027-01-01 and
    50@115 exp 2027-06-01."""
    scn = setup_verified_scenario(pet_weight_kg=2, catalog_unit_cost=115, quantity=10,
                                  days_supply=10)
    create_lot(scn["drug"]["id"], received_qty=7, unit_cost_cents=115,
               expiration_date="2027-01-01")
    create_lot(scn["drug"]["id"], received_qty=50, unit_cost_cents=115,
               expiration_date="2027-06-01")
    scn["bench"] = create_bench()
    return scn


def test_final_price_per_line_round_then_sum(api):
    """PRD §3.5: "with each line rounded half up to whole cents before the lines are
    summed into a lot component."
    Two consumed lines at 115 cents: round(7*115*1.03)=829 and round(3*115*1.03)=355
    sum to 1184; the sum-then-round alternative would give 1185 and is not the
    pinned order.

    Design: Difficulty/combinatorial_formula/final_price_per_line_rounding_order
    """
    scn = _setup_f1()
    order = create_compound_order(scn["rx"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    allocate_order(order["id"])
    start_compounding(order["id"], scn["bench"]["id"])
    complete_compounding(order["id"])
    final = qa_pass_order(order["id"])
    assert final["final_price_cents"] == 1184, (
        f"final expected 1184 (per-line round then sum), got {final['final_price_cents']}")
    assert final["final_price_cents"] != 1185


def test_provisional_price_rounds_once_after_sum(api):
    """PRD §2.6: "the provisional order estimate rounds once, after summing and
    multiplying; the final order price rounds each lot line before summing".
    qty 10 @ 115 on a 2 kg dog (tier 1.00): provisional = 10*115 = 1150, while the
    same fill's final price (1184) differs through per-line rounding.

    Design: Difficulty/combinatorial_formula/final_price_per_line_rounding_order
    """
    scn = _setup_f1()
    order = create_compound_order(scn["rx"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    assert order["provisional_price_cents"] == 1150, (
        f"provisional expected 1150, got {order['provisional_price_cents']}")
    allocate_order(order["id"])
    start_compounding(order["id"], scn["bench"]["id"])
    complete_compounding(order["id"])
    final = qa_pass_order(order["id"])
    assert final["final_price_cents"] != order["provisional_price_cents"]


def test_weight_tier_boundary_15kg_inclusive(api):
    """PRD §3.4: "The sum is then multiplied by a weight-tier multiplier read from
    the pet's `weight_kg`: 1.00 when the pet weighs under 5 kilograms; 1.15 from 5
    kilograms up to but not including 15; 1.30 from 15 up to but not including 30;
    and 1.50 at 30 kilograms and above — each tier's lower bound is inclusive."
    14.99 kg prices qty 10 @ 100 at 1.15 -> 1150; exactly 15.0 kg prices at 1.30
    -> 1300.

    Design: Corner/calculations/weight_tier_boundary_inclusive_15kg
    """
    owner = get_success_data(api_client.create_owner(
        {"full_name": "Owen C3", "email": "c3x@x.com", "phone": "556-21",
         "ship_to_address": "33 Main St"}, TEST_USERS["pharmacy_admin_headers"]))
    pet_a = create_pet(owner["id"], name="Lite", species="DOG", weight_kg=14.99, allergies=[])
    pet_b = create_pet(owner["id"], name="Hevy", species="DOG", weight_kg=15.0, allergies=[])
    vet = create_verified_vet()
    drug = create_drug(unit_cost_cents=100)
    formula = create_formula(drug["id"])
    rx_a = verify_prescription(create_prescription(
        pet_a, owner, vet, formula, quantity=10, days_supply=10)["id"], vet["id"])
    rx_b = verify_prescription(create_prescription(
        pet_b, owner, vet, formula, quantity=10, days_supply=10)["id"], vet["id"])
    order_a = create_compound_order(rx_a["id"], expected_prescription_version=rx_a["version"])
    order_b = create_compound_order(rx_b["id"], expected_prescription_version=rx_b["version"])
    assert order_a["provisional_price_cents"] == 1150, (
        f"14.99 kg expected tier 1.15 -> 1150, got {order_a['provisional_price_cents']}")
    assert order_b["provisional_price_cents"] == 1300, (
        f"15.0 kg expected tier 1.30 -> 1300, got {order_b['provisional_price_cents']}")


def test_create_response_carries_provisional_price(api):
    """PRD §3.4: "The order's `provisional_price_cents` is estimated at creation."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."
    The 201 create response already carries provisional_price_cents 1150 — no
    re-fetch needed.

    Design: Corner/consistency_model/create_response_contains_computed_price
    """
    scn = setup_verified_scenario(pet_weight_kg=2, catalog_unit_cost=115, quantity=10,
                                  days_supply=10)
    order = create_compound_order(scn["rx"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    assert order["provisional_price_cents"] == 1150


def test_final_price_null_before_qa_pass(api):
    """PRD §3.4: "The `final_price_cents` remains null until quality assurance
    passes."
    A freshly created order shows final_price_cents null while
    provisional_price_cents is already populated.

    Design: Corner/endpoints/final_price_null_before_qa
    """
    scn = setup_verified_scenario(pet_weight_kg=2, catalog_unit_cost=115, quantity=10,
                                  days_supply=10)
    order = create_compound_order(scn["rx"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    fetched = fetch_compound_order(order["id"])
    assert fetched["final_price_cents"] is None
    assert fetched["provisional_price_cents"] == 1150
