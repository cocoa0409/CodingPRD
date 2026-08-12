"""Prescription verification cycle, refill gates, and ordering state checks."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_owner, create_pet, create_verified_vet, create_drug, create_formula,
    create_prescription, submit_for_verification, verify_prescription,
    create_lot, create_bench, create_compound_order, allocate_order,
    start_compounding, order_to_dispensed, fetch_prescription, fetch_compound_order,
    setup_verified_scenario, list_orders_for_prescription,
    TEST_USERS, make_veterinarian_headers,
)


def _clarification_loop(rx_id, vet_id, note):
    get_success_data(api_client.request_clarification(
        rx_id, {"note": note}, make_veterinarian_headers(vet_id)))
    get_success_data(api_client.resubmit_prescription(rx_id, TEST_USERS["pharmacy_tech_headers"]))


def _setup_n1():
    """Prescription submitted for vet verification (vet verified), refills 1."""
    scn = setup_verified_scenario(pet_weight_kg=4, pet_species="CAT", quantity=10,
                                  days_supply=10, refills_authorized=1)
    return scn


def test_clarification_cycle_returns_to_verified(api):
    """PRD §3.3: "Requesting clarification, accompanied by a `note`, moves it to
    `CLARIFICATION_REQUESTED` and increments `clarification_count`; a
    `PharmacyTech` may then resubmit, returning the prescription to
    `VET_VERIFICATION_PENDING` for another round."
    Two full clarification loops followed by vet-confirm land the prescription in
    VERIFIED.

    Design: Difficulty/non_linear_state_machine/prescription_clarification_cycle
    """
    scn = _setup_n1()
    # Rebuild a fresh unverified prescription to run the loop from submission.
    rx = create_prescription(scn["pet"], scn["owner"], scn["vet"], scn["formula"],
                             quantity=10, days_supply=10, refills_authorized=1)
    submit_for_verification(rx["id"])
    _clarification_loop(rx["id"], scn["vet"]["id"], "dose unclear")
    _clarification_loop(rx["id"], scn["vet"]["id"], "still unclear")
    confirmed = get_success_data(api_client.vet_confirm(
        rx["id"], make_veterinarian_headers(scn["vet"]["id"])))
    assert confirmed["status"] == "VERIFIED"


def test_clarification_count_increments_each_round(api):
    """PRD §3.3: "Requesting clarification, accompanied by a `note`, moves it to
    `CLARIFICATION_REQUESTED` and increments `clarification_count`".
    After two loops clarification_count is exactly 2.

    Design: Difficulty/non_linear_state_machine/prescription_clarification_cycle
    """
    scn = _setup_n1()
    rx = create_prescription(scn["pet"], scn["owner"], scn["vet"], scn["formula"],
                             quantity=10, days_supply=10, refills_authorized=1)
    submit_for_verification(rx["id"])
    _clarification_loop(rx["id"], scn["vet"]["id"], "dose unclear")
    _clarification_loop(rx["id"], scn["vet"]["id"], "still unclear")
    confirmed = get_success_data(api_client.vet_confirm(
        rx["id"], make_veterinarian_headers(scn["vet"]["id"])))
    assert confirmed["clarification_count"] == 2, (
        f"clarification_count expected 2, got {confirmed['clarification_count']}")


def test_vet_rejected_terminal_lockdown(api):
    """PRD §3.3: "Rejection, accompanied by a `reason`, moves it to the terminal
    `REJECTED`."
    PRD §2.9: "the generic from-state check rejects transitions invoked on a
    resource not in a permitted source state — and any further transition on a
    terminal-state resource — with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/vet_rejected_terminal_lockdown
    """
    scn = _setup_n1()
    rx = create_prescription(scn["pet"], scn["owner"], scn["vet"], scn["formula"],
                             quantity=10, days_supply=10)
    submit_for_verification(rx["id"])
    get_success_data(api_client.vet_reject(
        rx["id"], {"reason": "bad dose"}, make_veterinarian_headers(scn["vet"]["id"])))
    res = api_client.vet_confirm(rx["id"], make_veterinarian_headers(scn["vet"]["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert fetch_prescription(rx["id"])["status"] == "REJECTED"


def _setup_x1():
    """Prescription submitted and awaiting vet verification; lot and bench ready."""
    owner = create_owner()
    pet = create_pet(owner["id"], species="DOG", weight_kg=20)
    vet = create_verified_vet()
    drug = create_drug()
    formula = create_formula(drug["id"], dosage_form="CAPSULE")
    rx = create_prescription(pet, owner, vet, formula, quantity=10, days_supply=10)
    submitted = submit_for_verification(rx["id"])
    create_lot(drug["id"], received_qty=50, unit_cost_cents=100)
    bench = create_bench()
    return {"owner": owner, "pet": pet, "vet": vet, "drug": drug, "formula": formula,
            "rx": submitted, "bench": bench}


def test_order_create_blocked_until_vet_confirms(api):
    """PRD §3.4: "then prescription state — an `EXPIRED` script is reported
    distinctly as `ERR_PRESCRIPTION_EXPIRED`, any other non-`VERIFIED` status as
    `ERR_PRESCRIPTION_NOT_VERIFIED`"
    While the prescription sits in VET_VERIFICATION_PENDING the create is rejected.

    Design: Difficulty/cross_entity_state_dependency/allocate_requires_prescription_verified
    """
    scn = _setup_x1()
    res = api_client.create_compound_order(
        scn["rx"]["id"],
        {"is_refill": False, "expected_prescription_version": scn["rx"]["version"]},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(res, ApiErrorId.ERR_PRESCRIPTION_NOT_VERIFIED)


def test_order_create_and_allocate_after_vet_confirm(api):
    """PRD §3.5: "The prescription must be `VERIFIED` — otherwise
    `ERR_PRESCRIPTION_NOT_VERIFIED` — and inventory is reserved
    first-expiry-first-out."
    After the vet-confirm transition on the prescription, order creation succeeds
    and allocation moves the order to ALLOCATED.

    Design: Difficulty/cross_entity_state_dependency/allocate_requires_prescription_verified
    """
    scn = _setup_x1()
    res = api_client.create_compound_order(
        scn["rx"]["id"],
        {"is_refill": False, "expected_prescription_version": scn["rx"]["version"]},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(res, ApiErrorId.ERR_PRESCRIPTION_NOT_VERIFIED)
    confirmed = get_success_data(api_client.vet_confirm(
        scn["rx"]["id"], make_veterinarian_headers(scn["vet"]["id"])))
    order = create_compound_order(scn["rx"]["id"],
                                  expected_prescription_version=confirmed["version"])
    allocated = allocate_order(order["id"])
    assert allocated["status"] == "ALLOCATED"


def test_refills_exhausted_rejected(api):
    """PRD §3.4: "The prescription must still have `refills_remaining` above zero,
    otherwise `ERR_REFILLS_EXHAUSTED`."
    PRD §3.4: "Finally, timing: the elapsed whole days between the most recent
    `DISPENSED` fill of this prescription"
    With refills_authorized 0 the refill fails ERR_REFILLS_EXHAUSTED, ahead of the
    refill-timing check.

    Design: Corner/validations/refills_exhausted_rejected
    """
    scn = setup_verified_scenario(pet_weight_kg=6, quantity=5, days_supply=5,
                                  refills_authorized=0)
    create_compound_order(scn["rx"]["id"], expected_prescription_version=scn["rx_version"])
    res = api_client.create_compound_order(
        scn["rx"]["id"],
        {"is_refill": True,
         "expected_prescription_version": fetch_prescription(scn["rx"]["id"])["version"]},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(res, ApiErrorId.ERR_REFILLS_EXHAUSTED)


def test_order_in_progress_blocks_new_create(api):
    """PRD §3.4: "a sibling order of the same prescription sitting in `COMPOUNDING`,
    `FLAVORING`, `REWORK`, `QA_PENDING`, `READY_TO_DISPATCH`, or `RECALL_HOLD` as
    `ERR_ORDER_IN_PROGRESS`."
    PRD §3.4: "An existing sibling in `CREATED` or `ALLOCATED` is not an error: the
    new order supersedes it"

    Design: Corner/validations/order_in_progress_blocks_new_create
    """
    scn = setup_verified_scenario(pet_weight_kg=6, quantity=5, days_supply=5,
                                  refills_authorized=1)
    create_lot(scn["drug"]["id"], received_qty=50)
    bench = create_bench()
    order1 = create_compound_order(scn["rx"]["id"],
                                   expected_prescription_version=scn["rx_version"])
    allocate_order(order1["id"])
    start_compounding(order1["id"], bench["id"])
    res = api_client.create_compound_order(
        scn["rx"]["id"],
        {"is_refill": False,
         "expected_prescription_version": fetch_prescription(scn["rx"]["id"])["version"]},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(res, ApiErrorId.ERR_ORDER_IN_PROGRESS)
    assert fetch_compound_order(order1["id"])["status"] == "COMPOUNDING"


def test_expired_prescription_create_rejected(api):
    """PRD §3.4: "an `EXPIRED` script is reported distinctly as
    `ERR_PRESCRIPTION_EXPIRED`"
    PRD §3.8: "and expires every `VERIFIED` prescription whose `expiration_date`
    has passed, with the auto-ship cancellation cascade described in §3.3."
    A NON_CONTROLLED script written 2026-05-01 expires 2027-05-01; swept at
    2027-05-02 the prescription is EXPIRED and order creation fails with
    ERR_PRESCRIPTION_EXPIRED.

    Design: Corner/validations/expired_prescription_create_rejected
    """
    scn = setup_verified_scenario(pet_weight_kg=6, quantity=5, days_supply=5,
                                  refills_authorized=1)
    get_success_data(api_client.set_clock("2027-05-02T00:00:00Z",
                                          TEST_USERS["pharmacy_admin_headers"]))
    get_success_data(api_client.run_expiration_sweep(TEST_USERS["pharmacy_admin_headers"]))
    rx = fetch_prescription(scn["rx"]["id"])
    assert rx["status"] == "EXPIRED"
    res = api_client.create_compound_order(
        scn["rx"]["id"],
        {"is_refill": False, "expected_prescription_version": rx["version"]},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(res, ApiErrorId.ERR_PRESCRIPTION_EXPIRED)


def _setup_b1():
    """rx days_supply 20, refills 2; first fill fully DISPENSED at the default
    clock date 2026-05-01."""
    scn = setup_verified_scenario(pet_weight_kg=9, quantity=10, days_supply=20,
                                  refills_authorized=2)
    create_lot(scn["drug"]["id"], received_qty=100)
    bench = create_bench()
    order_to_dispensed(scn["rx"]["id"], bench["id"])
    return scn


def test_refill_day_before_threshold_rejected(api):
    """PRD §3.4: "the elapsed whole days between the most recent `DISPENSED` fill
    of this prescription — fills that were cancelled or are still in progress do
    not count — and the current logical clock date must be at least the
    prescription's `days_supply` multiplied by three-quarters and rounded up to a
    whole day; the boundary day itself is eligible, and a refill arriving earlier
    is rejected with `ERR_REFILL_TOO_EARLY`."
    days_supply 20 pins the threshold at 15 days: day 14 rejects.

    Design: Difficulty/boundary_precision_check/refill_eligibility_exact_threshold_day
    """
    scn = _setup_b1()
    get_success_data(api_client.set_clock("2026-05-15T00:00:00Z",
                                          TEST_USERS["pharmacy_admin_headers"]))
    res = api_client.create_compound_order(
        scn["rx"]["id"],
        {"is_refill": True,
         "expected_prescription_version": fetch_prescription(scn["rx"]["id"])["version"]},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(res, ApiErrorId.ERR_REFILL_TOO_EARLY)


def test_refill_exact_threshold_day_succeeds(api):
    """PRD §3.4: "the boundary day itself is eligible".
    PRD §3.4: "For a refill, the prescription's `refills_remaining` decrements by
    one"
    Day 15 (exactly ceil(0.75*20) = 15) succeeds with fill_number 2 and leaves
    refills_remaining 1.

    Design: Difficulty/boundary_precision_check/refill_eligibility_exact_threshold_day
    """
    scn = _setup_b1()
    get_success_data(api_client.set_clock("2026-05-15T00:00:00Z",
                                          TEST_USERS["pharmacy_admin_headers"]))
    early = api_client.create_compound_order(
        scn["rx"]["id"],
        {"is_refill": True,
         "expected_prescription_version": fetch_prescription(scn["rx"]["id"])["version"]},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(early, ApiErrorId.ERR_REFILL_TOO_EARLY)
    get_success_data(api_client.set_clock("2026-05-16T00:00:00Z",
                                          TEST_USERS["pharmacy_admin_headers"]))
    refill = create_compound_order(scn["rx"]["id"], is_refill=True)
    assert refill["fill_number"] == 2
    assert refill["is_refill"] is True
    assert fetch_prescription(scn["rx"]["id"])["refills_remaining"] == 1


def test_refill_ceil_threshold_noninteger(api):
    """PRD §3.4: "must be at least the prescription's `days_supply` multiplied by
    three-quarters and rounded up to a whole day; the boundary day itself is
    eligible, and a refill arriving earlier is rejected with
    `ERR_REFILL_TOO_EARLY`."
    days_supply 21 pins ceil(15.75) = 16: day 15 rejects, day 16 succeeds.

    Design: Corner/calculations/refill_ceil_threshold_noninteger
    """
    scn = setup_verified_scenario(pet_weight_kg=6, quantity=10, days_supply=21,
                                  refills_authorized=1, drug_beyond_use_days=21)
    create_lot(scn["drug"]["id"], received_qty=100)
    bench = create_bench()
    order_to_dispensed(scn["rx"]["id"], bench["id"])
    get_success_data(api_client.set_clock("2026-05-16T00:00:00Z",
                                          TEST_USERS["pharmacy_admin_headers"]))
    early = api_client.create_compound_order(
        scn["rx"]["id"],
        {"is_refill": True,
         "expected_prescription_version": fetch_prescription(scn["rx"]["id"])["version"]},
        TEST_USERS["pharmacy_tech_headers"])
    validate_error(early, ApiErrorId.ERR_REFILL_TOO_EARLY)
    get_success_data(api_client.set_clock("2026-05-17T00:00:00Z",
                                          TEST_USERS["pharmacy_admin_headers"]))
    refill = create_compound_order(scn["rx"]["id"], is_refill=True)
    assert refill["fill_number"] == 2
