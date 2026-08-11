"""Payment, wellness credits, and the credit ledger invariant."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId,
    create_owner, create_pet, create_verified_vet, create_drug, create_formula,
    create_prescription, verify_prescription,
    create_wellness_plan, create_lot, create_bench,
    create_compound_order, create_enrollment_for_pet, fetch_enrollment,
    fetch_compound_order, setup_verified_scenario, order_to_ready,
    TEST_USERS, make_owner_headers,
)

CHICKEN_FLAVOR = {"allergen_tags": ["CHICKEN"], "surcharge_cents": 250,
                  "compatible_species": ["DOG", "CAT"]}


def _setup_i2():
    """Plan 5 credits x 2000c, discount 0, covers controlled; enrollment ACTIVE;
    flavored order qty 30 QA-passed (final price 4433c)."""
    scn = setup_verified_scenario(pet_weight_kg=12, catalog_unit_cost=120,
                                  flavor=CHICKEN_FLAVOR, quantity=30, days_supply=10,
                                  directions="BID")
    create_lot(scn["drug"]["id"], received_qty=20, unit_cost_cents=110,
               expiration_date="2027-01-01")
    create_lot(scn["drug"]["id"], received_qty=200, unit_cost_cents=130,
               expiration_date="2027-06-01")
    bench = create_bench()
    plan = create_wellness_plan(name="PlanI2", monthly_fee_cents=3000,
                                included_refill_credits=5, credit_value_cents=2000,
                                discount_pct=0, covers_controlled=True)
    enrollment = create_enrollment_for_pet(scn["pet"]["id"], plan["id"],
                                           scn["owner"]["id"])
    order = order_to_ready(scn["rx"]["id"], bench["id"],
                           flavoring_id=scn["flavoring"]["id"])
    scn.update({"bench": bench, "plan": plan, "enrollment": enrollment, "order": order})
    return scn


def _pay_and_refund(scn):
    paid = get_success_data(api_client.pay_order(
        scn["order"]["id"],
        {"payment_method": "WELLNESS_CREDIT", "enrollment_id": scn["enrollment"]["id"]},
        make_owner_headers(scn["owner"]["id"])))
    after_pay = fetch_enrollment(scn["enrollment"]["id"], scn["owner"]["id"])
    refunded = get_success_data(api_client.refund_order(
        scn["order"]["id"], TEST_USERS["pharmacist_a_headers"]))
    after_refund = fetch_enrollment(scn["enrollment"]["id"], scn["owner"]["id"])
    return paid, after_pay, refunded, after_refund


def test_credit_payment_debits_exactly_one_credit(api):
    """PRD §3.6: "the credit cap is one half of the post-discount amount — the
    subtotal minus the discount — rounded half up to whole cents, so the cap keys
    on the amount after discounting; the credits used are the lesser of the
    enrollment's `credits_remaining` and the credit cap divided by
    `credit_value_cents` rounded down to a whole credit"
    PRD §3.6: "A successful credit payment debits the enrollment, reducing
    `credits_remaining` and raising `credits_consumed` by the credits used."
    Cap round_half_up(0.5*4433) = 2217 -> floor(2217/2000) = 1 credit: the ledger
    reads 5 == 4 + 1 after payment.

    Design: Difficulty/compensating_invariant/wellness_credit_ledger_invariant
    """
    scn = _setup_i2()
    paid, after_pay, _refunded, _after_refund = _pay_and_refund(scn)
    assert paid["payment_status"] == "PAID"
    assert paid["paid_via"] == "WELLNESS_CREDIT"
    assert after_pay["credits_remaining"] == 4
    assert after_pay["credits_consumed"] == 1
    assert 5 == after_pay["credits_remaining"] + after_pay["credits_consumed"]


def test_credit_refund_restores_ledger(api):
    """PRD §3.6: "when the tender was `WELLNESS_CREDIT`, the credits originally
    spent are returned to the enrollment, raising `credits_remaining` and lowering
    `credits_consumed` by the same amount."
    After refund the ledger reads 5 == 5 + 0 — the pay/refund pair conserves the
    credit ledger — and the order's payment_status is REFUNDED.

    Design: Difficulty/compensating_invariant/wellness_credit_ledger_invariant
    """
    scn = _setup_i2()
    _paid, _after_pay, refunded, after_refund = _pay_and_refund(scn)
    assert refunded["payment_status"] == "REFUNDED"
    assert after_refund["credits_remaining"] == 5
    assert after_refund["credits_consumed"] == 0
    assert 5 == after_refund["credits_remaining"] + after_refund["credits_consumed"]


def test_credit_cap_evaluated_post_discount(api):
    """PRD §3.6: "the discount is the subtotal multiplied by the plan's
    `discount_pct`, rounded half up to whole cents; the credit cap is one half of
    the post-discount amount — the subtotal minus the discount — rounded half up to
    whole cents, so the cap keys on the amount after discounting"
    Order 8600c with a 10% plan discount yields cap round(0.5 * (8600-860)) = 3870c
    and exactly 1 credit (2000c); a pre-discount cap (4300c) would wrongly allow 2.

    Design: Corner/calculations/credit_cap_evaluated_post_discount
    """
    scn = setup_verified_scenario(pet_weight_kg=2, quantity=86, days_supply=43,
                                  directions="BID")
    plan = create_wellness_plan(name="PlanC9", monthly_fee_cents=3000,
                                included_refill_credits=5, credit_value_cents=2000,
                                discount_pct=0.1, covers_controlled=False)
    enrollment = create_enrollment_for_pet(scn["pet"]["id"], plan["id"],
                                           scn["owner"]["id"])
    order = create_compound_order(scn["rx"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    assert order["provisional_price_cents"] == 8600
    paid = get_success_data(api_client.pay_order(
        order["id"],
        {"payment_method": "WELLNESS_CREDIT", "enrollment_id": enrollment["id"]},
        make_owner_headers(scn["owner"]["id"])))
    assert paid["payment_status"] == "PAID"
    assert paid["paid_via"] == "WELLNESS_CREDIT"
    enr = fetch_enrollment(enrollment["id"], scn["owner"]["id"])
    assert enr["credits_consumed"] == 1, (
        f"cap keys on post-discount amount: expected 1 credit, got {enr['credits_consumed']}")
    assert enr["credits_remaining"] == 4


def _setup_p2():
    """Plan with 0 credits; enrollment created then SUSPENDED; unpaid CREATED order."""
    scn = setup_verified_scenario(pet_weight_kg=4, pet_species="CAT", quantity=5,
                                  days_supply=5)
    plan = create_wellness_plan(name="PlanP2", monthly_fee_cents=1000,
                                included_refill_credits=0, credit_value_cents=2000,
                                discount_pct=0, covers_controlled=True)
    enrollment = create_enrollment_for_pet(scn["pet"]["id"], plan["id"],
                                           scn["owner"]["id"])
    get_success_data(api_client.suspend_enrollment(
        enrollment["id"], make_owner_headers(scn["owner"]["id"])))
    order = create_compound_order(scn["rx"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    scn.update({"plan": plan, "enrollment": enrollment, "order": order})
    return scn


def test_enrollment_state_gate_precedes_credit_limit(api):
    """PRD §3.6: "The enrollment must be `ACTIVE`, otherwise
    `ERR_ENROLLMENT_NOT_ACTIVE`."
    PRD §2.9: "and finally fiscal rules (`ERR_PAYMENT_REQUIRED`, `ERR_CREDIT_LIMIT`)
    last of all."
    Paying with a SUSPENDED enrollment that also holds zero credits reports
    ERR_ENROLLMENT_NOT_ACTIVE, not ERR_CREDIT_LIMIT.

    Design: Difficulty/priority_pair_validation_conflict/state_over_fiscal_on_credit_pay
    """
    scn = _setup_p2()
    res = api_client.pay_order(
        scn["order"]["id"],
        {"payment_method": "WELLNESS_CREDIT", "enrollment_id": scn["enrollment"]["id"]},
        make_owner_headers(scn["owner"]["id"]))
    validate_error(res, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)


def test_enrollment_state_gate_leaves_order_unpaid(api):
    """PRD §3.6: "a successful payment moves `payment_status` from `UNPAID` to
    `PAID`"
    A rejected credit attempt performs no such move: the order stays UNPAID.

    Design: Difficulty/priority_pair_validation_conflict/state_over_fiscal_on_credit_pay
    """
    scn = _setup_p2()
    res = api_client.pay_order(
        scn["order"]["id"],
        {"payment_method": "WELLNESS_CREDIT", "enrollment_id": scn["enrollment"]["id"]},
        make_owner_headers(scn["owner"]["id"]))
    validate_error(res, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)
    assert fetch_compound_order(scn["order"]["id"])["payment_status"] == "UNPAID"


def test_enrollment_pet_mismatch_on_credit_pay(api):
    """PRD §3.6: "The enrollment's pet must be the prescription's pet, otherwise
    `ERR_ENROLLMENT_PET_MISMATCH`."

    Design: Corner/validations/enrollment_pet_mismatch_on_credit_pay
    """
    owner = create_owner()
    pet1 = create_pet(owner["id"], name="One", species="DOG", weight_kg=6)
    pet2 = create_pet(owner["id"], name="Two", species="CAT", weight_kg=4)
    vet = create_verified_vet()
    drug = create_drug()
    formula = create_formula(drug["id"])
    rx = verify_prescription(create_prescription(
        pet1, owner, vet, formula, quantity=5, days_supply=5)["id"], vet["id"])
    plan = create_wellness_plan(name="PlanVB", monthly_fee_cents=2000,
                                included_refill_credits=5, credit_value_cents=2000,
                                discount_pct=0, covers_controlled=False)
    enrollment = create_enrollment_for_pet(pet2["id"], plan["id"], owner["id"])
    order = create_compound_order(rx["id"], expected_prescription_version=rx["version"])
    res = api_client.pay_order(
        order["id"],
        {"payment_method": "WELLNESS_CREDIT", "enrollment_id": enrollment["id"]},
        make_owner_headers(owner["id"]))
    validate_error(res, ApiErrorId.ERR_ENROLLMENT_PET_MISMATCH)
    assert fetch_compound_order(order["id"])["payment_status"] == "UNPAID"


def test_payment_required_before_shipment(api):
    """PRD §3.7: "the fiscal gate comes last — the order's `payment_status` must be
    `PAID`, otherwise `ERR_PAYMENT_REQUIRED`."

    Design: Corner/validations/payment_required_before_shipment
    """
    scn = setup_verified_scenario(pet_weight_kg=6, quantity=5, days_supply=5)
    create_lot(scn["drug"]["id"], received_qty=50)
    bench = create_bench()
    order = order_to_ready(scn["rx"]["id"], bench["id"])
    res = api_client.create_shipment(
        order["id"], {"carrier": "PetEx", "service_level": "STANDARD",
                      "destination_zone": "Z1"}, TEST_USERS["pharmacist_a_headers"])
    validate_error(res, ApiErrorId.ERR_PAYMENT_REQUIRED)
    data, meta = validate_paginated(api_client.list_shipments(
        TEST_USERS["pharmacy_tech_headers"], params={"compound_order_id": order["id"]}))
    assert meta["total_count"] == 0


def test_owner_cannot_pay_others_order(api):
    """PRD §2.1: "Endpoints that declare an ownership rule — veterinary
    confirmation, rejection, and clarification of a prescription; an owner paying
    for an order; an owner appealing a claim; an owner acknowledging a recall task;
    enrollment suspension, resumption, and cancellation; and auto-ship pause,
    resume, and cancellation — reject a caller whose entity-backed `X-User-ID` does
    not own the targeted resource with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/owner_cannot_pay_others_order
    """
    scn = setup_verified_scenario(pet_weight_kg=6, quantity=5, days_supply=5)
    other_owner = create_owner()
    order = create_compound_order(scn["rx"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    res = api_client.pay_order(order["id"], {"payment_method": "CARD"},
                               make_owner_headers(other_owner["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert fetch_compound_order(order["id"])["payment_status"] == "UNPAID"
