"""Bench reservations, compounding/flavoring/QA workflow, and the rework cycle."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId,
    create_owner, create_pet, create_verified_vet, create_drug, create_formula,
    create_prescription, verify_prescription,
    create_lot, create_bench, create_flavoring,
    create_compound_order, allocate_order, start_compounding, complete_compounding,
    complete_flavoring, qa_pass_order, fetch_compound_order, fetch_lot,
    setup_verified_scenario, assert_lot_quantities,
    TEST_USERS,
)


def _setup_n2():
    """Verified rx qty 10 (2 kg dog, no flavor); one lot 10@100; order in QA_PENDING."""
    scn = setup_verified_scenario(pet_weight_kg=2, catalog_unit_cost=100, quantity=10,
                                  days_supply=10)
    lot = create_lot(scn["drug"]["id"], received_qty=10, unit_cost_cents=100)
    bench = create_bench()
    order = create_compound_order(scn["rx"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    allocate_order(order["id"])
    start_compounding(order["id"], bench["id"])
    complete_compounding(order["id"])
    scn.update({"lot": lot, "bench": bench, "order": order})
    return scn


def _run_n2_rework_cycle(scn):
    failed = get_success_data(api_client.qa_fail(
        scn["order"]["id"], {"waste_qty": 2}, TEST_USERS["pharmacist_b_headers"]))
    start_compounding(scn["order"]["id"], scn["bench"]["id"],
                      window=("2026-05-01T11:00:00Z", "2026-05-01T12:00:00Z"))
    complete_compounding(scn["order"]["id"])
    passed = qa_pass_order(scn["order"]["id"])
    return failed, passed


def test_qa_fail_moves_to_rework_then_recovers(api):
    """PRD §3.5: "A failed review moves the order from `QA_PENDING` to `REWORK` and
    optionally writes off wasted material"
    PRD §3.5: "From `REWORK`, starting compounding again is permitted once the
    remaining `RESERVED` allocations cover `quantity_snapshot` minus the wasted
    units, under the same bench-overlap and recall rules as the first start"
    The reworked pass consumes only the surviving 8 reserved units: final price
    round(8*100*1.03) = 824.

    Design: Difficulty/non_linear_state_machine/compound_order_qa_rework_cycle
    """
    scn = _setup_n2()
    failed, passed = _run_n2_rework_cycle(scn)
    assert failed["status"] == "REWORK"
    assert passed["status"] == "READY_TO_DISPATCH"
    assert passed["final_price_cents"] == 824, (
        f"final expected 824, got {passed['final_price_cents']}")


def test_rework_waste_updates_lot_quantities(api):
    """PRD §3.5: "any positive amount reduces the `qty_allocated` of the order's
    `RESERVED` allocations in allocation creation order, decreases each affected
    lot's `qty_reserved`, increases its `qty_wasted`"
    PRD §3.2: "A lot whose `qty_on_hand` and `qty_reserved` both reach zero
    automatically transitions to `EXHAUSTED`"
    After the reworked QA pass the 10-unit lot shows wasted 2, dispensed 8,
    on-hand 0, reserved 0, status EXHAUSTED.

    Design: Difficulty/non_linear_state_machine/compound_order_qa_rework_cycle
    """
    scn = _setup_n2()
    _run_n2_rework_cycle(scn)
    lot = fetch_lot(scn["lot"]["id"])
    assert_lot_quantities(lot, on_hand=0, reserved=0, dispensed=8, wasted=2)
    assert lot["status"] == "EXHAUSTED"


def _setup_t1():
    """Three verified prescriptions (same pet/drug/formula), three allocated
    orders A/B/C, one shared bench."""
    owner = create_owner()
    pet = create_pet(owner["id"], species="DOG", weight_kg=6)
    vet = create_verified_vet()
    drug = create_drug()
    formula = create_formula(drug["id"], dosage_form="CHEW")
    rxs = []
    for _ in range(3):
        rx = create_prescription(pet, owner, vet, formula, quantity=5, days_supply=5)
        rxs.append(verify_prescription(rx["id"], vet["id"]))
    create_lot(drug["id"], received_qty=100)
    bench = create_bench()
    orders = [create_compound_order(rx["id"], expected_prescription_version=rx["version"])
              for rx in rxs]
    for o in orders:
        allocate_order(o["id"])
    return {"bench": bench, "orders": orders}


def test_bench_half_open_adjacency_accepted(api):
    """PRD §3.5: "reservation intervals are half-open — a conflict exists when the
    existing reservation starts before the new one ends and the new one starts
    before the existing one ends, so back-to-back bookings where the new `start_at`
    exactly equals the existing `end_at` are permitted"
    A 10:00-11:00 reservation touching the existing 09:00-10:00 reservation at the
    boundary is accepted.

    Design: Difficulty/resource_temporal_overlap/bench_half_open_adjacency
    """
    scn = _setup_t1()
    a, b, _c = scn["orders"]
    start_compounding(a["id"], scn["bench"]["id"],
                      window=("2026-05-01T09:00:00Z", "2026-05-01T10:00:00Z"))
    res = api_client.start_compounding(
        b["id"], {"bench_id": scn["bench"]["id"], "start_at": "2026-05-01T10:00:00Z",
                  "end_at": "2026-05-01T11:00:00Z"}, TEST_USERS["pharmacist_a_headers"])
    started = validate_success(res, 200)
    assert started["status"] == "COMPOUNDING"


def test_bench_overlap_rejected(api):
    """PRD §3.5: "a genuine overlap is rejected with `ERR_BENCH_OVERLAP`."
    A 09:30-10:30 reservation overlaps both existing windows and is rejected; the
    order stays ALLOCATED.

    Design: Difficulty/resource_temporal_overlap/bench_half_open_adjacency
    """
    scn = _setup_t1()
    a, b, c = scn["orders"]
    start_compounding(a["id"], scn["bench"]["id"],
                      window=("2026-05-01T09:00:00Z", "2026-05-01T10:00:00Z"))
    start_compounding(b["id"], scn["bench"]["id"],
                      window=("2026-05-01T10:00:00Z", "2026-05-01T11:00:00Z"))
    res = api_client.start_compounding(
        c["id"], {"bench_id": scn["bench"]["id"], "start_at": "2026-05-01T09:30:00Z",
                  "end_at": "2026-05-01T10:30:00Z"}, TEST_USERS["pharmacist_a_headers"])
    validate_error(res, ApiErrorId.ERR_BENCH_OVERLAP)
    assert fetch_compound_order(c["id"])["status"] == "ALLOCATED"


def test_complete_flavoring_invalid_from_compounding(api):
    """PRD §3.5: "Completing flavoring, likewise restricted to the compounding
    pharmacist, moves the order from `FLAVORING` to `QA_PENDING`."
    PRD §2.9: "the generic from-state check rejects transitions invoked on a
    resource not in a permitted source state — and any further transition on a
    terminal-state resource — with `ERR_INVALID_STATE`"
    Invoking complete-flavoring while COMPOUNDING fails with ERR_INVALID_STATE.

    Design: Corner/state_machines/complete_flavoring_invalid_from_compounding
    """
    scn = setup_verified_scenario(
        pet_weight_kg=6, quantity=5, days_supply=5,
        flavor={"name": "FishS3", "allergen_tags": ["FISH"], "surcharge_cents": 300,
                "compatible_species": ["DOG", "CAT"]})
    create_lot(scn["drug"]["id"], received_qty=50)
    bench = create_bench()
    order = create_compound_order(scn["rx"]["id"], flavoring_id=scn["flavoring"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    allocate_order(order["id"])
    start_compounding(order["id"], bench["id"])
    res = api_client.complete_flavoring(order["id"], TEST_USERS["pharmacist_a_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert fetch_compound_order(order["id"])["status"] == "COMPOUNDING"


def test_segregation_of_duties_on_qa(api):
    """PRD §3.5: "both the pass and the fail decision require a reviewer whose
    identifier differs from `compounding_pharmacist_id`, and a self-review is
    rejected with `ERR_SEGREGATION_OF_DUTIES`."
    qa-pass with the compounding pharmacist's own identifier fails; a different
    pharmacist passes and is recorded as qa_pharmacist_id.

    Design: Corner/validations/segregation_of_duties_on_qa
    """
    scn = setup_verified_scenario(pet_weight_kg=6, quantity=5, days_supply=5)
    create_lot(scn["drug"]["id"], received_qty=50)
    bench = create_bench()
    order = create_compound_order(scn["rx"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    allocate_order(order["id"])
    start_compounding(order["id"], bench["id"])
    complete_compounding(order["id"])
    res = api_client.qa_pass(order["id"], TEST_USERS["pharmacist_a_headers"])
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert fetch_compound_order(order["id"])["status"] == "QA_PENDING"
    passed = qa_pass_order(order["id"])
    assert passed["status"] == "READY_TO_DISPATCH"
    assert passed["qa_pharmacist_id"] == "pharm-b"


def test_bench_controlled_capability_rejected(api):
    """PRD §3.5: "For a controlled order the bench's `supports_controlled` must be
    true, otherwise `ERR_BENCH_NOT_CONTROLLED_CAPABLE`."

    Design: Corner/validations/bench_controlled_capability_rejected
    """
    scn = setup_verified_scenario(pet_weight_kg=6, drug_schedule="C_IV",
                                  catalog_unit_cost=350, drug_beyond_use_days=30,
                                  quantity=5, days_supply=5, directions="BID")
    create_lot(scn["drug"]["id"], received_qty=50, unit_cost_cents=300)
    bench = create_bench(supports_controlled=False)
    order = create_compound_order(scn["rx"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    allocate_order(order["id"])
    res = api_client.start_compounding(
        order["id"], {"bench_id": bench["id"], "start_at": "2026-05-01T09:00:00Z",
                      "end_at": "2026-05-01T10:00:00Z"}, TEST_USERS["pharmacist_a_headers"])
    validate_error(res, ApiErrorId.ERR_BENCH_NOT_CONTROLLED_CAPABLE)
    assert fetch_compound_order(order["id"])["status"] == "ALLOCATED"


def test_fk_reverse_allocations_empty_on_fresh_order(api):
    """PRD §2.3: "Paginated list responses include `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."
    PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects."
    A CREATED order with no allocations yet returns a 200 array envelope with
    total_count 0, not a 404.

    Design: Corner/endpoints/fk_reverse_allocations_empty_on_fresh_order
    """
    scn = setup_verified_scenario(pet_weight_kg=2, quantity=10, days_supply=10)
    order = create_compound_order(scn["rx"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    data, meta = validate_paginated(api_client.list_order_allocations(
        order["id"], TEST_USERS["pharmacy_tech_headers"]))
    assert data == []
    assert meta["total_count"] == 0
