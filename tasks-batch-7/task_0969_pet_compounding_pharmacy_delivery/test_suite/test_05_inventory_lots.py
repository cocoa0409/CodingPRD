"""Inventory lots: FEFO allocation, waste bounds, mass balance, and the DEA log."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId,
    create_owner, create_pet, create_verified_vet, create_drug, create_formula,
    create_prescription, verify_prescription,
    create_lot, create_bench,
    create_compound_order, allocate_order, start_compounding, complete_compounding,
    qa_pass_order, fetch_lot, fetch_compound_order, setup_verified_scenario,
    assert_lot_quantities,
    order_to_ready, pay_order_card, create_shipment_for_order, pickup_shipment,
    TEST_USERS,
)


def _setup_i1():
    """One lot of 50 @100; two verified prescriptions qty 30 and qty 10."""
    owner = create_owner()
    pet = create_pet(owner["id"], species="DOG", weight_kg=3)
    vet = create_verified_vet()
    drug = create_drug()
    formula = create_formula(drug["id"])
    rx1 = verify_prescription(create_prescription(
        pet, owner, vet, formula, quantity=30, days_supply=30)["id"], vet["id"])
    rx2 = verify_prescription(create_prescription(
        pet, owner, vet, formula, quantity=10, days_supply=10)["id"], vet["id"])
    lot = create_lot(drug["id"], received_qty=50, unit_cost_cents=100)
    bench = create_bench()
    return {"owner": owner, "pet": pet, "vet": vet, "drug": drug, "formula": formula,
            "rx1": rx1, "rx2": rx2, "lot": lot, "bench": bench}


def _run_i1(scn):
    order1 = create_compound_order(scn["rx1"]["id"],
                                   expected_prescription_version=scn["rx1"]["version"])
    allocate_order(order1["id"])
    after_reserve = fetch_lot(scn["lot"]["id"])
    start_compounding(order1["id"], scn["bench"]["id"])
    complete_compounding(order1["id"])
    qa_pass_order(order1["id"])
    after_consume = fetch_lot(scn["lot"]["id"])
    order2 = create_compound_order(scn["rx2"]["id"],
                                   expected_prescription_version=scn["rx2"]["version"])
    allocate_order(order2["id"])
    get_success_data(api_client.cancel_order(order2["id"], TEST_USERS["pharmacy_tech_headers"]))
    after_release = fetch_lot(scn["lot"]["id"])
    return order1, order2, after_reserve, after_consume, after_release


def test_lot_mass_balance_reserve_and_consume(api):
    """PRD §3.5: "each touched lot's `qty_reserved` rises by the allocated amount
    and its `qty_on_hand` falls by the same"
    PRD §3.5: "each lot's `qty_reserved` decreases and `qty_dispensed` increases by
    the consumed amount"
    A 50-unit lot shows (on_hand 20, reserved 30) after reserving 30 and
    (20, 0, dispensed 30, wasted 0) after QA consumption.

    Design: Difficulty/compensating_invariant/lot_mass_balance_invariant
    """
    scn = _setup_i1()
    _o1, _o2, after_reserve, after_consume, _rel = _run_i1(scn)
    assert_lot_quantities(after_reserve, on_hand=20, reserved=30, dispensed=0, wasted=0)
    assert 50 == 20 + 30 + 0 + 0
    assert_lot_quantities(after_consume, on_hand=20, reserved=0, dispensed=30, wasted=0)
    assert 50 == 20 + 0 + 30 + 0


def test_lot_mass_balance_release_by_cancel(api):
    """PRD §3.5: "From `ALLOCATED`, cancellation additionally releases every
    `RESERVED` allocation — each moves to `RELEASED`, and each lot's `qty_reserved`
    decreases and `qty_on_hand` increases by the released amount"
    A second order's 10-unit reserve is released by cancellation, returning the lot
    to (on_hand 20, reserved 0, dispensed 30, wasted 0) — zero drift — and the
    cancelled order's allocations are RELEASED.

    Design: Difficulty/compensating_invariant/lot_mass_balance_invariant
    """
    scn = _setup_i1()
    _o1, order2, _r, _c, after_release = _run_i1(scn)
    assert_lot_quantities(after_release, on_hand=20, reserved=0, dispensed=30, wasted=0)
    assert fetch_compound_order(order2["id"])["status"] == "CANCELLED"
    data, _meta = validate_paginated(api_client.list_lot_allocations(
        TEST_USERS["pharmacy_tech_headers"], params={"compound_order_id": order2["id"]}))
    assert len(data) == 1
    assert data[0]["status"] == "RELEASED"


def test_fefo_expiration_ordering_and_split(api):
    """PRD §3.5: "Candidates are walked in `expiration_date` ascending order, ties
    broken by `created_at` ascending; from each lot the system reserves the lesser
    of the remaining need and that lot's `qty_on_hand`."
    A qty-15 order draws all 10 units from the earlier-expiring lot before taking
    5 from the later one.

    Design: Corner/calculations/fefo_expiration_ordering_and_split
    """
    scn = setup_verified_scenario(pet_weight_kg=6, quantity=15, days_supply=15)
    lot1 = create_lot(scn["drug"]["id"], received_qty=10, unit_cost_cents=100,
                      expiration_date="2027-01-15")
    lot2 = create_lot(scn["drug"]["id"], received_qty=10, unit_cost_cents=100,
                      expiration_date="2027-02-01")
    order = create_compound_order(scn["rx"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    allocate_order(order["id"])
    data, meta = validate_paginated(api_client.list_order_allocations(
        order["id"], TEST_USERS["pharmacy_tech_headers"]))
    assert meta["total_count"] == 2
    by_lot = {a["lot_id"]: a["qty_allocated"] for a in data}
    assert by_lot[lot1["id"]] == 10, "earlier-expiring lot must be fully drawn first"
    assert by_lot[lot2["id"]] == 5, "later lot takes only the spillover"


def test_shortdated_lot_excluded_from_fefo(api):
    """PRD §3.5: "Candidate lots are those stocking the formula's drug, in `ACTIVE`
    status, whose `expiration_date` is at least the prescription's `days_supply`
    days beyond the current logical clock date."
    PRD §3.5: "If the total reservable across all candidates falls short of
    `quantity_snapshot`, the allocation is rejected with
    `ERR_INSUFFICIENT_INVENTORY` and no partial allocation persists."
    A lot expiring 2026-05-03 cannot cover a days_supply 10 script at the
    2026-05-01 clock, so allocation fails despite 100 units physically on hand.

    Design: Corner/calculations/shortdated_lot_excluded_from_fefo
    """
    scn = setup_verified_scenario(pet_weight_kg=6, quantity=5, days_supply=10)
    create_lot(scn["drug"]["id"], received_qty=100, expiration_date="2026-05-03")
    order = create_compound_order(scn["rx"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    res = api_client.allocate_order(order["id"], TEST_USERS["pharmacy_tech_headers"])
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)
    assert fetch_compound_order(order["id"])["status"] == "CREATED"
    data, meta = validate_paginated(api_client.list_order_allocations(
        order["id"], TEST_USERS["pharmacy_tech_headers"]))
    assert meta["total_count"] == 0


def test_waste_exact_balance_vs_excess(api):
    """PRD §3.2: "The write-off is rejected with `ERR_WASTE_EXCEEDS_ON_HAND` when
    the quantity exceeds the lot's on-hand units or would drive the lot's
    controlled running balance below zero."
    PRD §3.2: "A lot whose `qty_on_hand` and `qty_reserved` both reach zero
    automatically transitions to `EXHAUSTED`"
    Waste of 51 on a 50-unit lot rejects; waste of exactly 50 succeeds and drives
    the lot to EXHAUSTED.

    Design: Corner/calculations/waste_exact_balance_vs_excess
    """
    drug = create_drug()
    lot = create_lot(drug["id"], received_qty=50)
    res = api_client.waste_lot(lot["id"], {"qty": 51, "reason": "over"},
                               TEST_USERS["compliance_officer_headers"])
    validate_error(res, ApiErrorId.ERR_WASTE_EXCEEDS_ON_HAND)
    after = get_success_data(api_client.waste_lot(
        lot["id"], {"qty": 50, "reason": "exact"}, TEST_USERS["compliance_officer_headers"]))
    assert_lot_quantities(after, on_hand=0, reserved=0, dispensed=0, wasted=50)
    assert after["status"] == "EXHAUSTED"


def test_duplicate_lot_number_rejected(api):
    """PRD §3.2: "a manufacturer `lot_number` that must be unique per drug — a
    duplicate is rejected with `ERR_DUPLICATE_LOT_NUMBER`"
    The same lot_number on a different drug is accepted (uniqueness is per drug).

    Design: Corner/validations/duplicate_lot_number_rejected
    """
    drug1 = create_drug()
    drug2 = create_drug(unit_cost_cents=150)
    create_lot(drug1["id"], lot_number="L-DUP", received_qty=50)
    dup = api_client.create_lot(
        {"drug_catalog_item_id": drug1["id"], "lot_number": "L-DUP", "received_qty": 50,
         "unit_cost_cents": 100, "expiration_date": "2027-02-01"},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_LOT_NUMBER)
    ok = api_client.create_lot(
        {"drug_catalog_item_id": drug2["id"], "lot_number": "L-DUP", "received_qty": 50,
         "unit_cost_cents": 150, "expiration_date": "2027-02-01"},
        TEST_USERS["pharmacy_tech_headers"])
    validate_success(ok, 201)


def test_controlled_entry_system_computed(api):
    """PRD §3.2: "Receiving a lot of a controlled drug writes a `RECEIVE` entry to
    the controlled-substance log."
    PRD §3.2: "a signed `qty_delta` (positive for `RECEIVE` and `RETURN`, negative
    for `DISPENSE` and `WASTE`)"
    PRD §2.4: "Two resources are exceptions: a `TemperatureReading` and a
    `ControlledSubstanceEntry` are append-only records that carry only `id` and
    `created_at`; both `updated_at` and `version` are absent from them."
    Receiving 60 controlled units writes one RECEIVE entry with qty_delta 60 and
    running_balance 60, with no version/updated_at on the entry.

    Design: Corner/entities/controlled_entry_system_computed
    """
    drug = create_drug(schedule="C_IV", unit_cost_cents=350, default_beyond_use_days=30)
    lot = create_lot(drug["id"], received_qty=60, unit_cost_cents=300)
    data, meta = validate_paginated(api_client.list_controlled_substance_entries(
        TEST_USERS["compliance_officer_headers"], params={"lot_id": lot["id"]}))
    assert meta["total_count"] == 1
    entry = data[0]
    assert entry["entry_type"] == "RECEIVE"
    assert entry["qty_delta"] == 60
    assert entry["running_balance"] == 60
    assert entry.get("recorded_by")
    assert entry.get("recorded_at")
    assert "version" not in entry and "updated_at" not in entry


def test_controlled_log_signed_running_balance(api):
    """PRD §3.2: "The log is replayed per lot in `recorded_at` ascending order,
    ties broken by `created_at` ascending, starting from a genesis balance of zero;
    each entry's `running_balance` is the previous balance plus its `qty_delta`."
    PRD §3.2: "At all times the latest `running_balance` for a lot equals that
    lot's `qty_on_hand` plus its `qty_reserved`."
    PRD §3.7: "a `DISPENSE` log entry is written for each consumed controlled lot"
    RECEIVE +60 -> 60, WASTE -5 -> 55, DISPENSE -10 -> 45; final balance 45 equals
    lot.qty_on_hand (45) + qty_reserved (0).

    Design: Corner/calculations/controlled_log_signed_running_balance
    """
    scn = setup_verified_scenario(pet_weight_kg=6, drug_schedule="C_IV",
                                  catalog_unit_cost=350, drug_beyond_use_days=30,
                                  quantity=10, days_supply=10, refills_authorized=1,
                                  directions="BID")
    lot = create_lot(scn["drug"]["id"], received_qty=60, unit_cost_cents=300)
    bench = create_bench()
    get_success_data(api_client.waste_lot(lot["id"], {"qty": 5, "reason": "broken vials"},
                                          TEST_USERS["compliance_officer_headers"]))
    order = order_to_ready(scn["rx"]["id"], bench["id"])
    pay_order_card(order["id"], scn["owner"]["id"])
    shipment = create_shipment_for_order(order["id"])
    pickup_shipment(shipment["id"])
    data, meta = validate_paginated(api_client.list_controlled_substance_entries(
        TEST_USERS["compliance_officer_headers"], params={"lot_id": lot["id"]}))
    assert meta["total_count"] == 3
    by_type = {e["entry_type"]: e for e in data}
    assert by_type["RECEIVE"]["qty_delta"] == 60
    assert by_type["RECEIVE"]["running_balance"] == 60
    assert by_type["WASTE"]["qty_delta"] == -5
    assert by_type["WASTE"]["running_balance"] == 55
    assert by_type["DISPENSE"]["qty_delta"] == -10
    assert by_type["DISPENSE"]["running_balance"] == 45
    lot_after = fetch_lot(lot["id"])
    assert by_type["DISPENSE"]["running_balance"] == (
        lot_after["qty_on_hand"] + lot_after["qty_reserved"])
    assert lot_after["qty_dispensed"] == 10
    assert lot_after["qty_wasted"] == 5
