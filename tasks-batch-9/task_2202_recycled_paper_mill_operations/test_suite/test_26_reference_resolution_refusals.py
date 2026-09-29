"""Identifiers that point at nothing: a wrap that outruns its own run, a sequencing
call naming a phantom run, every collection's own not-found code, and a purchase order
whose counterparty and grade were never declared.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    NON_EXISTENT_UUID, TEST_USERS, declare_fiber_grade, publish_quote,
    register_supplier, create_purchase_order_payload,
    setup_run_ready_to_start, start_run, wind_roll_set,
    declare_tl_140, register_customer, submit_order, order_version,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
OPERATOR = TEST_USERS["operator_headers"]
ENV = TEST_USERS["env_officer_headers"]
ENERGY = TEST_USERS["energy_headers"]


def test_wrapping_a_roll_while_the_machine_is_still_making_paper_is_refused():
    """PRD §3.6: "Wrapping, `WOUND → WRAPPED`, stores the `wrap_spec` applied at the
    wrapper. It requires the set to be in `WOUND`, requires the producing run's
    `run_status` to be `COMPLETED` — an attempt before the run finishes is rejected with
    `ERR_RUN_NOT_CERTIFIED` (HTTP 409) — and re-checks the deckle limit."
    PRD §3.6: "A new set opens in `WOUND` with `rewind_count` of 0, `quarantine_reason`
    null, and `allocated_order_id` null, and its creation recomputes the run's
    `produced_tons`."

    Design: Corner/errors/wrapping_a_roll_from_a_still_running_run_hits_the_cross_entity_gate
    """
    bundle = setup_run_ready_to_start(run_overrides={"pulp_draw_tons": 20.000})
    machine, run = bundle["machine"], bundle["run"]
    start_run(machine["id"], run["id"])
    roll_set = wind_roll_set(run["id"], slit_width_mm=2400, diameter_mm=1400,
                             roll_count=4, net_tons=5.000)
    assert roll_set["status"] == "WOUND"

    response = api_client.wrap_roll_set(
        roll_set["id"], {"wrap_spec": "KRAFT_ONLY"}, OPERATOR)
    validate_error(response, ApiErrorId.ERR_RUN_NOT_CERTIFIED.value, 409)

    unwrapped = get_success_data(api_client.get_roll_set(roll_set["id"], OPERATOR))
    assert unwrapped["status"] == "WOUND"
    assert unwrapped["wrap_spec"] is None, "the wrapper never touched this set"
    assert unwrapped["rewind_count"] == 0
    assert unwrapped["allocated_order_id"] is None
    still_making_paper = get_success_data(api_client.get_run(run["id"], PLANNER))
    assert still_making_paper["run_status"] == "RUNNING"
    assert still_making_paper["quality_status"] == "PENDING"
    assert still_making_paper["produced_tons"] == pytest.approx(5.000, abs=1e-6)


def test_sequencing_an_order_onto_a_run_that_does_not_exist_is_a_link_failure():
    """PRD §2.7: "Identifiers arriving in the request *body* rather than the path have
    their own codes: an unresolvable `fiber_grade_code`, `target_product_code` or
    `product_code` yields `ERR_GRADE_CODE_NOT_FOUND`; an unresolvable `supplier_id` or
    `customer_id` yields `ERR_PARTY_NOT_FOUND`; an unresolvable `pulp_batch_id` or a
    furnish line whose `inventory_lot_id` does not resolve yields
    `ERR_FURNISH_REFERENCE_NOT_FOUND`; an unresolvable `run_id`, `from_run_id`,
    `to_run_id` or `order_id`, or one that resolves to a row of the wrong type, yields
    `ERR_LINK_TARGET_NOT_FOUND`; and an entry of `reject_stream_ids` that does not
    resolve — or that resolves to a compensating reversal row — yields
    `ERR_REJECT_STREAM_REFERENCE_INVALID` (HTTP 404)."
    PRD §3.6: "Sequencing an order onto a run, `SUBMITTED → SCHEDULED`, is a planner act
    carrying the `run_id` and `expected_order_version`."
    PRD §3.6: "Success sets `scheduled_run_id` and bumps the order's `version` by one."

    Design: Corner/errors/scheduling_an_order_onto_a_nonexistent_run_is_a_link_target_failure
    """
    declare_tl_140()
    customer = register_customer(name="Gulf Coast Box Co",
                                 allocation_priority_tier="P2",
                                 max_roll_diameter_mm=1400, max_roll_width_mm=2400,
                                 wrap_spec="KRAFT_ONLY")
    order = submit_order(customer, "TL_140", ordered_tons=10.00, roll_width_mm=2400,
                         roll_diameter_mm=1400, wrap_spec="KRAFT_ONLY")
    version_before = order_version(order["id"])

    response = api_client.schedule_customer_order(
        order["id"],
        {"run_id": NON_EXISTENT_UUID, "expected_order_version": version_before},
        PLANNER)
    validate_error(response, ApiErrorId.ERR_LINK_TARGET_NOT_FOUND.value, 404)

    unsequenced = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert unsequenced["status"] == "SUBMITTED"
    assert unsequenced["scheduled_run_id"] is None
    assert unsequenced["version"] == version_before, \
        "a link that resolves to nothing cannot bump the order"
    assert unsequenced["deschedule_count"] == 0


def test_every_collection_answers_a_bogus_path_id_with_its_own_code():
    """PRD §2.7: "The existence codes are specific to the addressed collection:
    `ERR_SUPPLIER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`,
    `ERR_RECEIPT_NOT_FOUND`, `ERR_INVENTORY_LOT_NOT_FOUND`, `ERR_PULP_BATCH_NOT_FOUND`,
    `ERR_MACHINE_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_GRADE_CHANGE_NOT_FOUND`,
    `ERR_ROLL_SET_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, and
    `ERR_STEAM_ALLOCATION_NOT_FOUND` each cover a path id of the corresponding kind,
    while `ERR_ENV_RECORD_NOT_FOUND` (HTTP 404) covers an effluent reading, sludge
    manifest, or reject stream id in the path."
    PRD §2.8: "The global ordering is: authentication and role checks first (missing
    headers, unknown role, unresolvable entity-backed identity, role not permitted,
    resource ownership), then path existence resolved left to right, then pagination and
    request-shape validation, then body-reference resolution, then optimistic-concurrency
    version checks, then state-machine from-state checks, then segregation-of-duties
    checks, then the domain's business rules — safety and environmental gates, then
    constraint and capacity gates, then temporal gates, then the fiscal and ledger
    gates."

    Design: Corner/errors/every_collection_answers_a_bogus_id_with_its_own_not_found_code
    """
    probes = [
        (api_client.get_supplier, BUYER, ApiErrorId.ERR_SUPPLIER_NOT_FOUND),
        (api_client.get_customer, PLANNER, ApiErrorId.ERR_CUSTOMER_NOT_FOUND),
        (api_client.get_purchase_order, BUYER, ApiErrorId.ERR_PURCHASE_ORDER_NOT_FOUND),
        (api_client.get_receipt, BUYER, ApiErrorId.ERR_RECEIPT_NOT_FOUND),
        # PRD §4: GET /fiber-inventory-lots/{id} is a MachineOperator / MillPlanner /
        # QualityLab read surface — a FiberBuyer is not authorised for it.
        (api_client.get_inventory_lot, OPERATOR, ApiErrorId.ERR_INVENTORY_LOT_NOT_FOUND),
        (api_client.get_pulp_batch, OPERATOR, ApiErrorId.ERR_PULP_BATCH_NOT_FOUND),
        (api_client.get_paper_machine, PLANNER, ApiErrorId.ERR_MACHINE_NOT_FOUND),
        (api_client.get_run, PLANNER, ApiErrorId.ERR_RUN_NOT_FOUND),
        (api_client.get_grade_change, PLANNER, ApiErrorId.ERR_GRADE_CHANGE_NOT_FOUND),
        (api_client.get_roll_set, PLANNER, ApiErrorId.ERR_ROLL_SET_NOT_FOUND),
        (api_client.get_customer_order, PLANNER, ApiErrorId.ERR_ORDER_NOT_FOUND),
        (api_client.get_effluent_permit, ENV, ApiErrorId.ERR_PERMIT_NOT_FOUND),
        (api_client.get_effluent_reading, ENV, ApiErrorId.ERR_ENV_RECORD_NOT_FOUND),
        (api_client.get_sludge_manifest, ENV, ApiErrorId.ERR_ENV_RECORD_NOT_FOUND),
        (api_client.get_reject_stream, ENV, ApiErrorId.ERR_ENV_RECORD_NOT_FOUND),
        (api_client.get_steam_allocation, ENERGY,
         ApiErrorId.ERR_STEAM_ALLOCATION_NOT_FOUND),
    ]

    for getter, headers, expected in probes:
        response = getter(NON_EXISTENT_UUID, headers)
        validate_error(response, expected.value, 404)
        assert response.json()["response_type"] == "error", \
            f"{expected.value} must arrive in the error envelope"


def test_a_purchase_order_for_an_undeclared_counterparty_or_grade_never_lands():
    """PRD §2.7: "Identifiers arriving in the request *body* rather than the path have
    their own codes: an unresolvable `fiber_grade_code`, `target_product_code` or
    `product_code` yields `ERR_GRADE_CODE_NOT_FOUND`; an unresolvable `supplier_id` or
    `customer_id` yields `ERR_PARTY_NOT_FOUND`; an unresolvable `pulp_batch_id` or a
    furnish line whose `inventory_lot_id` does not resolve yields
    `ERR_FURNISH_REFERENCE_NOT_FOUND`; an unresolvable `run_id`, `from_run_id`,
    `to_run_id` or `order_id`, or one that resolves to a row of the wrong type, yields
    `ERR_LINK_TARGET_NOT_FOUND`; and an entry of `reject_stream_ids` that does not
    resolve — or that resolves to a compensating reversal row — yields
    `ERR_REJECT_STREAM_REFERENCE_INVALID` (HTTP 404)."
    PRD §3.1: "A purchase order begins life in `DRAFT`. Its creator supplies the
    `supplier_id` of the counterparty, the `fiber_grade_code` being bought,
    `contracted_tons` greater than zero and not above 5000 at two decimal places, the
    `index_basis` — either `PRIOR_MONTH` or `CURRENT_MONTH` — the `priced_for_month` in
    the same year-and-month form as a quote, and a signed `negotiated_delta_per_ton`
    between negative 80 and positive 80 at two decimal places."

    Design: Corner/errors/a_purchase_order_naming_an_unknown_supplier_is_a_party_not_found
    """
    declare_fiber_grade(grade_code="OCC_11", index_symbol="PPI_OCC",
                        max_contamination_pct=3.00, max_moisture_pct=12.00,
                        nominal_yield_pct=88.00, rank_order=1)
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-08",
                  published_price_per_ton=180.00)
    supplier = register_supplier(name="Riverbend Fiber", freight_per_ton=12.50)

    no_such_party = api_client.create_purchase_order(create_purchase_order_payload(
        NON_EXISTENT_UUID, "OCC_11", contracted_tons=400.00,
        negotiated_delta_per_ton=5.00), BUYER)
    validate_error(no_such_party, ApiErrorId.ERR_PARTY_NOT_FOUND.value, 404)

    no_such_grade = api_client.create_purchase_order(create_purchase_order_payload(
        supplier["id"], "SOP_37", contracted_tons=400.00,
        negotiated_delta_per_ton=5.00), BUYER)
    validate_error(no_such_grade, ApiErrorId.ERR_GRADE_CODE_NOT_FOUND.value, 404)

    assert api_client.list_purchase_orders(BUYER).json()["meta"]["total_count"] == 0
    good = validate_success(api_client.create_purchase_order(
        create_purchase_order_payload(supplier["id"], "OCC_11",
                                      contracted_tons=400.00,
                                      negotiated_delta_per_ton=5.00), BUYER), 201)
    assert good["status"] == "DRAFT", \
        "only the two unresolvable references stood in the way"
    assert good["quoted_unit_price_per_ton"] is None
