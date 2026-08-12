"""Shipping fee, cold-chain excursion tracking, quarantine cascades, and cooler
reconditioning windows."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_lot, create_bench, create_cooler, create_wellness_plan,
    create_compound_order, create_enrollment_for_pet, fetch_enrollment,
    fetch_compound_order, fetch_shipment, fetch_cooler,
    setup_verified_scenario, order_to_ready, pay_order_card,
    create_shipment_for_order, pickup_shipment,
    create_prescription, verify_prescription,
    allocate_order, start_compounding, complete_compounding, complete_flavoring,
    qa_pass_order,
    TEST_USERS, make_owner_headers,
)

CHICKEN_FLAVOR = {"allergen_tags": ["CHICKEN"], "surcharge_cents": 250,
                  "compatible_species": ["DOG", "CAT"]}


def _setup_cold_chain_scenario(with_default_lot=True, **overrides):
    """Cold-chain verified rx (insulin-like drug 2..8 C); lot, bench, cooler."""
    params = dict(pet_weight_kg=4, pet_species="CAT", requires_cold_chain=True,
                  catalog_unit_cost=200, drug_beyond_use_days=28, quantity=5,
                  days_supply=5)
    params.update(overrides)
    scn = setup_verified_scenario(**params)
    if with_default_lot:
        scn["lot"] = create_lot(scn["drug"]["id"], received_qty=50, unit_cost_cents=190,
                                expiration_date="2027-03-01")
    scn["bench"] = create_bench()
    scn["cooler"] = create_cooler()
    return scn


def _cold_order_in_transit(scn, flavor=False, pay_credit_enrollment=None):
    flavoring_id = scn["flavoring"]["id"] if flavor else None
    order = order_to_ready(scn["rx"]["id"], scn["bench"]["id"], flavoring_id=flavoring_id)
    if pay_credit_enrollment is not None:
        get_success_data(api_client.pay_order(
            order["id"], {"payment_method": "WELLNESS_CREDIT",
                          "enrollment_id": pay_credit_enrollment["id"]},
            make_owner_headers(scn["owner"]["id"])))
    else:
        pay_order_card(order["id"], scn["owner"]["id"])
    shipment = create_shipment_for_order(order["id"], cooler_id=scn["cooler"]["id"])
    pickup_shipment(shipment["id"])
    get_success_data(api_client.mark_in_transit(shipment["id"],
                                                TEST_USERS["pharmacist_a_headers"]))
    return order, fetch_shipment(shipment["id"])


def test_shipping_fee_capped_at_3500(api):
    """PRD §3.7: "a base by service level — 500 cents for `STANDARD`, 900 for
    `EXPRESS`, 1500 for `OVERNIGHT` — plus a 1200-cent cold-chain surcharge when
    the drug requires cold chain, plus an ice-pack component computed as the zone's
    transit hours — 24 for `Z1`, 48 for `Z2`, 72 for `Z3` — divided by twenty-four
    and rounded up to a whole number of days, multiplied by 300 cents per day. The
    total is capped: the fee is the lesser of 3500 cents and the computed sum."
    OVERNIGHT + cold-chain + Z3 computes 1500 + 1200 + ceil(72/24)*300 = 3600,
    pinned to the 3500 cap.

    Design: Difficulty/combinatorial_formula/shipping_fee_multi_input_cap
    """
    scn = _setup_cold_chain_scenario(pet_weight_kg=2, pet_species="DOG", quantity=10,
                                     days_supply=10)
    order = order_to_ready(scn["rx"]["id"], scn["bench"]["id"])
    pay_order_card(order["id"], scn["owner"]["id"])
    shipment = create_shipment_for_order(order["id"], cooler_id=scn["cooler"]["id"],
                                         service_level="OVERNIGHT", destination_zone="Z3")
    assert shipment["shipping_fee_cents"] == 3500, (
        f"fee expected 3500 (capped), got {shipment['shipping_fee_cents']}")


def test_shipment_copies_temp_band_and_compliant(api):
    """PRD §3.7: "The drug's transit band is copied onto the shipment as
    `required_temp_min_celsius` and `required_temp_max_celsius`, and
    `cold_chain_status` starts as `COMPLIANT` when the drug requires cold chain,
    otherwise `NOT_REQUIRED`"

    Design: Difficulty/combinatorial_formula/shipping_fee_multi_input_cap
    """
    scn = _setup_cold_chain_scenario(pet_weight_kg=2, pet_species="DOG", quantity=10,
                                     days_supply=10)
    order = order_to_ready(scn["rx"]["id"], scn["bench"]["id"])
    pay_order_card(order["id"], scn["owner"]["id"])
    shipment = create_shipment_for_order(order["id"], cooler_id=scn["cooler"]["id"],
                                         service_level="OVERNIGHT", destination_zone="Z3")
    assert shipment["cold_chain_status"] == "COMPLIANT"
    assert shipment["required_temp_min_celsius"] == 2
    assert shipment["required_temp_max_celsius"] == 8


def _breach_readings(shipment_id):
    get_success_data(api_client.add_temperature_reading(
        shipment_id, {"recorded_at": "2026-05-01T09:00:00Z", "temp_celsius": 10},
        TEST_USERS["pharmacy_tech_headers"]))
    get_success_data(api_client.add_temperature_reading(
        shipment_id, {"recorded_at": "2026-05-01T09:30:00Z", "temp_celsius": 9},
        TEST_USERS["pharmacy_tech_headers"]))


def test_cold_chain_breach_at_exactly_30_minutes(api):
    """PRD §3.7: "The shipment's `cold_chain_status` becomes `EXCURSION_BREACH`
    once the accumulator reaches 30 minutes — exactly 30 breaches"
    PRD §3.7: "Each subsequent out-of-range reading adds the whole minutes between
    its `recorded_at` and the previous reading's `recorded_at` to
    `excursion_minutes_accumulated`"
    A single 30-minute out-of-range interval accumulates exactly 30 and breaches.

    Design: Difficulty/boundary_precision_check/cold_chain_breach_exact_30_minutes
    """
    scn = _setup_cold_chain_scenario(pet_species="CAT", pet_weight_kg=4)
    _order, shipment = _cold_order_in_transit(scn)
    _breach_readings(shipment["id"])
    after = fetch_shipment(shipment["id"])
    assert after["excursion_minutes_accumulated"] == 30
    assert after["cold_chain_status"] == "EXCURSION_BREACH"


def test_breach_auto_quarantines_transit(api):
    """PRD §3.7: "A breach moves `transit_status` to `QUARANTINED` unless the
    shipment is already `DELIVERED` or `RETURNED_TO_PHARMACY`."

    Design: Difficulty/boundary_precision_check/cold_chain_breach_exact_30_minutes
    """
    scn = _setup_cold_chain_scenario(pet_species="CAT", pet_weight_kg=4)
    _order, shipment = _cold_order_in_transit(scn)
    _breach_readings(shipment["id"])
    after = fetch_shipment(shipment["id"])
    assert after["transit_status"] == "QUARANTINED"


def _setup_c2():
    """Cold-chain flavored order qty 30 paid via 1 wellness credit; shipment
    IN_TRANSIT with cooler."""
    scn = _setup_cold_chain_scenario(with_default_lot=False, pet_species="DOG",
                                     pet_weight_kg=12, catalog_unit_cost=120,
                                     quantity=30, days_supply=10,
                                     flavor=CHICKEN_FLAVOR)
    scn["lot"] = create_lot(scn["drug"]["id"], received_qty=20, unit_cost_cents=110,
                            expiration_date="2027-01-01")
    create_lot(scn["drug"]["id"], received_qty=200, unit_cost_cents=130,
               expiration_date="2027-06-01")
    plan = create_wellness_plan(name="PlanC2", monthly_fee_cents=3000,
                                included_refill_credits=5, credit_value_cents=2000,
                                discount_pct=0, covers_controlled=True)
    scn["enrollment"] = create_enrollment_for_pet(scn["pet"]["id"], plan["id"],
                                                  scn["owner"]["id"])
    return scn


def test_breach_quarantine_refunds_paid_order(api):
    """PRD §3.7: "Quarantine carries a compensation cascade: if the order's
    `payment_status` is `PAID` it moves to `REFUNDED`"
    The reading breach quarantines the shipment (hop 1) and the quarantine refunds
    the paid order (hop 2).

    Design: Difficulty/transitive_cascade/cold_breach_refund_credit_cascade
    """
    scn = _setup_c2()
    order, shipment = _cold_order_in_transit(scn, flavor=True,
                                             pay_credit_enrollment=scn["enrollment"])
    _breach_readings(shipment["id"])
    after = fetch_shipment(shipment["id"])
    assert after["excursion_minutes_accumulated"] == 30
    assert after["cold_chain_status"] == "EXCURSION_BREACH"
    assert after["transit_status"] == "QUARANTINED"
    assert fetch_compound_order(order["id"])["payment_status"] == "REFUNDED"


def test_breach_refund_restores_enrollment_credits(api):
    """PRD §3.7: "when the tender was `WELLNESS_CREDIT` the enrollment's
    `credits_remaining` is raised and its `credits_consumed` lowered by the credits
    originally used"
    Hop 3: the refund restores the consumed credit — remaining 4 -> 5, consumed
    1 -> 0.

    Design: Difficulty/transitive_cascade/cold_breach_refund_credit_cascade
    """
    scn = _setup_c2()
    order, shipment = _cold_order_in_transit(scn, flavor=True,
                                             pay_credit_enrollment=scn["enrollment"])
    before = fetch_enrollment(scn["enrollment"]["id"], scn["owner"]["id"])
    assert before["credits_remaining"] == 4 and before["credits_consumed"] == 1
    _breach_readings(shipment["id"])
    after = fetch_enrollment(scn["enrollment"]["id"], scn["owner"]["id"])
    assert after["credits_remaining"] == 5
    assert after["credits_consumed"] == 0
    assert fetch_compound_order(order["id"])["payment_status"] == "REFUNDED"


def test_below_min_excursion_counts(api):
    """PRD §3.7: "A reading is out of range when it falls below
    `required_temp_min_celsius` or rises above `required_temp_max_celsius`;
    readings exactly at either bound are in range."
    Readings BELOW the minimum accumulate symmetrically: 0 C then 1 C over a
    30-minute interval breaches exactly like an over-max excursion.

    Design: Corner/calculations/below_min_excursion_counts
    """
    scn = _setup_cold_chain_scenario(pet_species="CAT", pet_weight_kg=4)
    _order, shipment = _cold_order_in_transit(scn)
    get_success_data(api_client.add_temperature_reading(
        shipment["id"], {"recorded_at": "2026-05-01T09:00:00Z", "temp_celsius": 0},
        TEST_USERS["pharmacy_tech_headers"]))
    get_success_data(api_client.add_temperature_reading(
        shipment["id"], {"recorded_at": "2026-05-01T09:30:00Z", "temp_celsius": 1},
        TEST_USERS["pharmacy_tech_headers"]))
    after = fetch_shipment(shipment["id"])
    assert after["excursion_minutes_accumulated"] == 30
    assert after["cold_chain_status"] == "EXCURSION_BREACH"
    assert after["transit_status"] == "QUARANTINED"


def test_ambient_shipment_rejects_readings(api):
    """PRD §3.7: "Readings are only accepted while `cold_chain_status` is something
    other than `NOT_REQUIRED` — a reading on an ambient shipment is rejected with
    `ERR_COLD_CHAIN_NOT_REQUIRED`"

    Design: Corner/state_machines/ambient_shipment_rejects_readings
    """
    scn = setup_verified_scenario(pet_weight_kg=6, quantity=5, days_supply=5)
    create_lot(scn["drug"]["id"], received_qty=50)
    bench = create_bench()
    order = order_to_ready(scn["rx"]["id"], bench["id"])
    pay_order_card(order["id"], scn["owner"]["id"])
    shipment = create_shipment_for_order(order["id"])
    assert shipment["cold_chain_status"] == "NOT_REQUIRED"
    res = api_client.add_temperature_reading(
        shipment["id"], {"recorded_at": "2026-05-01T09:00:00Z", "temp_celsius": 20},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(res, ApiErrorId.ERR_COLD_CHAIN_NOT_REQUIRED)


def test_breach_quarantined_blocks_delivery(api):
    """PRD §3.7: "Quarantine is the third terminal outcome."
    PRD §2.9: "the generic from-state check rejects transitions invoked on a
    resource not in a permitted source state — and any further transition on a
    terminal-state resource — with `ERR_INVALID_STATE`"
    A shipment auto-QUARANTINED by a cold-chain breach rejects both
    mark-out-for-delivery and mark-delivered.

    Design: Corner/state_machines/breach_quarantined_blocks_delivery
    """
    scn = _setup_cold_chain_scenario(pet_species="CAT", pet_weight_kg=4)
    _order, shipment = _cold_order_in_transit(scn)
    _breach_readings(shipment["id"])
    res1 = api_client.mark_out_for_delivery(shipment["id"], TEST_USERS["pharmacist_a_headers"])
    validate_error(res1, ApiErrorId.ERR_INVALID_STATE)
    res2 = api_client.mark_delivered(shipment["id"], TEST_USERS["pharmacist_a_headers"])
    validate_error(res2, ApiErrorId.ERR_INVALID_STATE)
    assert fetch_shipment(shipment["id"])["transit_status"] == "QUARANTINED"


def test_nonmonotonic_reading_rejected(api):
    """PRD §3.7: "each `recorded_at` must be at least the previous reading's
    `recorded_at`, with non-monotonic timestamps rejected by the same error."
    A reading at 09:00 after one at 10:00 is rejected; the accumulator stays 0.

    Design: Corner/validations/nonmonotonic_reading_rejected
    """
    scn = _setup_cold_chain_scenario(pet_species="CAT", pet_weight_kg=4)
    _order, shipment = _cold_order_in_transit(scn)
    get_success_data(api_client.add_temperature_reading(
        shipment["id"], {"recorded_at": "2026-05-01T10:00:00Z", "temp_celsius": 4},
        TEST_USERS["pharmacy_tech_headers"]))
    res = api_client.add_temperature_reading(
        shipment["id"], {"recorded_at": "2026-05-01T09:00:00Z", "temp_celsius": 4},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(res, ApiErrorId.ERR_COLD_CHAIN_NOT_REQUIRED)
    assert fetch_shipment(shipment["id"])["excursion_minutes_accumulated"] == 0


def _setup_t2():
    """Cold-chain drug; order 1 delivered at clock 2026-05-02T10:00 (cooler
    conditioning until 12:00); order 2 READY_TO_DISPATCH and paid."""
    owner_pet = dict(pet_species="CAT", pet_weight_kg=4, requires_cold_chain=True,
                     catalog_unit_cost=200, drug_beyond_use_days=28, quantity=5,
                     days_supply=5)
    scn = setup_verified_scenario(**owner_pet)
    create_lot(scn["drug"]["id"], received_qty=50, unit_cost_cents=190,
               expiration_date="2027-03-01")
    bench = create_bench()
    cooler = create_cooler()
    # Order 1: full delivery with the cooler.
    order1 = order_to_ready(scn["rx"]["id"], bench["id"])
    pay_order_card(order1["id"], scn["owner"]["id"])
    shipment1 = create_shipment_for_order(order1["id"], cooler_id=cooler["id"])
    pickup_shipment(shipment1["id"])
    get_success_data(api_client.mark_in_transit(shipment1["id"],
                                                TEST_USERS["pharmacist_a_headers"]))
    get_success_data(api_client.mark_out_for_delivery(shipment1["id"],
                                                      TEST_USERS["pharmacist_a_headers"]))
    get_success_data(api_client.set_clock("2026-05-02T10:00:00Z",
                                          TEST_USERS["pharmacy_admin_headers"]))
    get_success_data(api_client.mark_delivered(shipment1["id"],
                                               TEST_USERS["pharmacist_a_headers"]))
    # Order 2: second prescription, ready and paid.
    rx2 = verify_prescription(create_prescription(
        scn["pet"], scn["owner"], scn["vet"], scn["formula"], quantity=5,
        days_supply=5)["id"], scn["vet"]["id"])
    order2 = order_to_ready(rx2["id"], bench["id"],
                            window=("2026-05-02T10:30:00Z", "2026-05-02T11:00:00Z"))
    pay_order_card(order2["id"], scn["owner"]["id"])
    scn.update({"bench": bench, "cooler": cooler, "order2": order2})
    return scn


def test_cooler_conditioning_gap_rejects_early_attach(api):
    """PRD §3.7: "Unlike the bench's half-open adjacency, the cooler's two-hour
    reconditioning gap is mandatory: attaching before the gap elapses is rejected
    even when the prior shipment's window has ended."
    After a 10:00 delivery the cooler cannot be reattached at 11:59 —
    ERR_COOLER_CONDITIONING.

    Design: Difficulty/resource_temporal_overlap/cooler_conditioning_buffer
    """
    scn = _setup_t2()
    get_success_data(api_client.set_clock("2026-05-02T11:59:00Z",
                                          TEST_USERS["pharmacy_admin_headers"]))
    res = api_client.create_shipment(
        scn["order2"]["id"],
        {"carrier": "PetEx", "service_level": "STANDARD", "destination_zone": "Z1",
         "cooler_asset_id": scn["cooler"]["id"]},
        TEST_USERS["pharmacist_a_headers"])
    validate_error(res, ApiErrorId.ERR_COOLER_CONDITIONING)


def test_cooler_attachable_exactly_at_conditioning_end(api):
    """PRD §3.7: "A cooler is attachable when its `status` is `AVAILABLE`, or when
    it is `CONDITIONING` and the current logical clock has reached its
    `conditioning_available_at` — arriving exactly at that timestamp is
    attachable."
    At exactly 12:00 the attach succeeds and the cooler is ASSIGNED again.

    Design: Difficulty/resource_temporal_overlap/cooler_conditioning_buffer
    """
    scn = _setup_t2()
    get_success_data(api_client.set_clock("2026-05-02T11:59:00Z",
                                          TEST_USERS["pharmacy_admin_headers"]))
    early = api_client.create_shipment(
        scn["order2"]["id"],
        {"carrier": "PetEx", "service_level": "STANDARD", "destination_zone": "Z1",
         "cooler_asset_id": scn["cooler"]["id"]},
        TEST_USERS["pharmacist_a_headers"])
    validate_error(early, ApiErrorId.ERR_COOLER_CONDITIONING)
    get_success_data(api_client.set_clock("2026-05-02T12:00:00Z",
                                          TEST_USERS["pharmacy_admin_headers"]))
    shipment = create_shipment_for_order(scn["order2"]["id"], cooler_id=scn["cooler"]["id"])
    assert shipment["cooler_asset_id"] == scn["cooler"]["id"]
    assert fetch_cooler(scn["cooler"]["id"])["status"] == "ASSIGNED"
