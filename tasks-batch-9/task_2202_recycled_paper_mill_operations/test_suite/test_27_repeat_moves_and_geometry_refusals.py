"""Second attempts at moves that already landed, and a roll wound two hundred
millimetres too wide for the order it was meant to fill.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, declare_fiber_grade, declare_tl_140, publish_quote,
    register_supplier, register_customer, register_machine, register_permit,
    create_draft_po, create_confirmed_po, record_receipt, disposition,
    lots_of_receipt, po_version, order_version, sublot,
    setup_approved_batch, schedule_run, start_run, complete_run, wind_roll_set,
    wrap_roll_set, submit_order, schedule_order, ON_SPEC_REELS_TL_140, set_clock,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
OPERATOR = TEST_USERS["operator_headers"]
SAMPLER = TEST_USERS["lab_sampler_headers"]
DISPOSER = TEST_USERS["lab_dispo_headers"]
CERTIFIER = TEST_USERS["lab_cert_headers"]

PM1 = {"name": "PM1", "wire_width_mm": 5600, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 30, "steam_tph_per_ton": 2.500}
MILL_PERMIT = {"permit_number": "MILL-NPDES-1", "bod_limit_kg_per_day": 500.00,
               "tss_limit_kg_per_day": 400.00, "flow_limit_m3_per_day": 9000.00,
               "rolling_window_days": 30}
CLEAN_TRUCK = [sublot(1, 30.000, 8.000, 10.00, 2.00)]


def _declared_market():
    declare_fiber_grade(grade_code="OCC_11", index_symbol="PPI_OCC",
                        max_contamination_pct=3.00, max_moisture_pct=12.00,
                        nominal_yield_pct=88.00, rank_order=1)
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-08",
                  published_price_per_ton=180.00)
    return register_supplier(name="Delta Fiber Recovery", freight_per_ton=12.50)


def test_pricing_an_order_that_is_already_priced_is_refused_on_its_state():
    """PRD §3.1: "Pricing moves the order `DRAFT → PRICED` and is the buyer's act. It is
    refused with `ERR_PURCHASE_ORDER_INVALID_STATE` unless the order is currently in
    `DRAFT`, refused with `ERR_SUPPLIER_SUSPENDED` when the counterparty's
    `qualification_status` is `SUSPENDED`, and refused with `ERR_INDEX_QUOTE_MISSING`
    (HTTP 422) when no non-superseded quote exists for the resolved symbol and month."
    PRD §3.1: "Each successful pricing bumps the order's `version` by one."
    PRD §3.1: "Withdrawal requires the order to be in `PRICED` and requires
    `pricing_revision_count` to be below 2; it increments `pricing_revision_count` by
    one, clears `quoted_unit_price_per_ton`, `fuel_surcharge_per_ton`,
    `extended_contract_value` and `index_quote_month_used` back to null, and bumps
    `version` by one."

    Design: Corner/errors/pricing_an_already_priced_purchase_order_is_refused_on_state
    """
    set_clock("2026-08-01T00:00:00Z")
    supplier = _declared_market()
    draft = create_draft_po(supplier["id"], "OCC_11", contracted_tons=400.00,
                            negotiated_delta_per_ton=5.00)
    priced = validate_success(api_client.price_purchase_order(
        draft["id"], {"expected_purchase_order_version": draft["version"]}, BUYER))
    assert priced["status"] == "PRICED"
    fresh_token = po_version(draft["id"])

    response = api_client.price_purchase_order(
        draft["id"], {"expected_purchase_order_version": fresh_token}, BUYER)
    validate_error(response, ApiErrorId.ERR_PURCHASE_ORDER_INVALID_STATE.value, 409)

    unchanged = get_success_data(api_client.get_purchase_order(draft["id"], BUYER))
    assert unchanged["status"] == "PRICED"
    assert unchanged["quoted_unit_price_per_ton"] == pytest.approx(199.81, abs=1e-6), \
        "the stored number is the first computation, not a second one"
    assert unchanged["pricing_revision_count"] == 0, \
        "only a withdrawal moves that counter"
    assert unchanged["index_quote_month_used"] == "2026-08"
    assert unchanged["version"] == fresh_token, \
        "a state refusal is not an optimistic-concurrency refusal"


def test_a_truck_already_accepted_cannot_be_judged_a_second_time():
    """PRD §3.2: "All three branches require the receipt to be in `SAMPLED`, failing which
    the request is rejected with `ERR_RECEIPT_INVALID_STATE` (HTTP 409), and all three
    enforce segregation of duties: the acting `X-User-ID` must differ from the receipt's
    `sampled_by_user_id`, and an operator attempting to disposition the truck they sampled
    is rejected with `ERR_SOD_SAME_SAMPLER` (HTTP 409)."
    PRD §3.2: "Acceptance sets `accepted_grade_code` equal to `declared_grade_code` and
    creates exactly one fiber inventory lot whose `grade_code` is that accepted grade,
    whose `tons_received` is the receipt's `net_tons`, whose `contamination_pct` is copied
    from the receipt's `weighted_contamination_pct`, and whose lot `status` is
    `AVAILABLE`."
    PRD §3.2: "The receipt's `net_tons` is added into the parent order's
    `received_net_tons`, which is what drives the order's own advance to
    `PARTIALLY_RECEIVED` or `CLOSED`."
    PRD §3.2: "The supplier's `contamination_strike_count` is left untouched — a clean
    truck costs the supplier nothing."

    Design: Corner/errors/dispositioning_an_accepted_truck_a_second_time_is_refused_on_state
    """
    set_clock("2026-08-01T00:00:00Z")
    supplier = _declared_market()
    po = create_confirmed_po(supplier["id"], "OCC_11", contracted_tons=400.00,
                             negotiated_delta_per_ton=5.00)
    receipt = record_receipt(po["id"], CLEAN_TRUCK, truck_reference="TRK-0001",
                             sampler_headers=SAMPLER)
    accepted = disposition(receipt["id"], "ACCEPT", headers=DISPOSER)
    assert accepted["status"] == "ACCEPTED"

    for verb in ("ACCEPT", "REJECT"):
        again = api_client.disposition_receipt(
            receipt["id"], {"disposition": verb}, CERTIFIER)
        validate_error(again, ApiErrorId.ERR_RECEIPT_INVALID_STATE.value, 409)

    settled = get_success_data(api_client.get_receipt(receipt["id"], BUYER))
    assert settled["status"] == "ACCEPTED"
    assert settled["accepted_grade_code"] == "OCC_11"
    assert settled["dispositioned_by_user_id"] == "ql_dispo", \
        "the refused attempts may not overwrite the officer of record"
    assert len(lots_of_receipt(receipt["id"])) == 1, \
        "one truck mints exactly one lot however many times it is judged"
    posture = get_success_data(api_client.get_supplier(supplier["id"], BUYER))
    assert posture["contamination_strike_count"] == 0
    assert posture["qualification_status"] == "QUALIFIED"
    booked = get_success_data(api_client.get_purchase_order(po["id"], BUYER))
    assert booked["received_net_tons"] == pytest.approx(22.00, abs=1e-6), \
        "22.00 tons arrived once, not twice"


def test_a_roll_two_hundred_millimetres_too_wide_cannot_fill_the_order():
    """PRD §3.6: "Its checks run in this order: the set must be in `WRAPPED`, or
    `ERR_ROLL_SET_INVALID_STATE` (HTTP 409); the producing run's `quality_status` must be
    `CERTIFIED`, or `ERR_RUN_NOT_CERTIFIED`; the target order's `status` must be
    `IN_PRODUCTION` or `PARTIALLY_ALLOCATED`, or `ERR_ORDER_INVALID_STATE`; the order's
    `product_code` must equal the producing run's `product_code`, or
    `ERR_PRODUCT_MISMATCH`; `expected_order_version` must match the order's current
    `version`, or `ERR_STALE_ORDER_VERSION` (HTTP 412); and the geometry must fit the
    order exactly — the set's `slit_width_mm` must **equal** the order's `roll_width_mm`,
    the set's `diameter_mm` must be no greater than the order's `roll_diameter_mm`, and
    the set's `wrap_spec` must equal the order's `wrap_spec` — with any deviation rejected
    as `ERR_ROLL_SPEC_MISMATCH` (HTTP 409)."
    PRD §3.6: "The order's ledger is recomputed from the roll sets rather than
    accumulated: `allocated_tons` is the sum of `net_tons` over roll sets whose
    `allocated_order_id` is this order and whose status is `ALLOCATED` or `SHIPPED`,
    rounded to three decimal places; `shipped_tons` is the same sum restricted to sets in
    `SHIPPED`; and `shortfall_tons` is `ordered_tons` minus `allocated_tons`, floored at
    zero and rounded to three decimal places."

    Design: Corner/errors/a_roll_two_hundred_millimetres_wider_than_the_order_cannot_be_allocated
    """
    register_permit(**MILL_PERMIT)
    declare_tl_140()
    machine = register_machine(**PM1)
    bundle = setup_approved_batch(declare_spec=False)
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       pulp_draw_tons=20.000)
    customer = register_customer(name="Boxworks Packaging",
                                 allocation_priority_tier="P2",
                                 max_roll_diameter_mm=1300, max_roll_width_mm=2400,
                                 wrap_spec="POLY_COATED")
    order = submit_order(customer, "TL_140", ordered_tons=10.00, roll_width_mm=2000,
                         roll_diameter_mm=1200, wrap_spec="POLY_COATED")
    schedule_order(order["id"], run["id"])
    start_run(machine["id"], run["id"])
    roll_set = wind_roll_set(run["id"], slit_width_mm=2200, diameter_mm=1200,
                             roll_count=4, net_tons=6.000)
    complete_run(machine["id"], run["id"], ON_SPEC_REELS_TL_140)
    wrap_roll_set(roll_set["id"], "POLY_COATED")
    certified = validate_success(api_client.certify_run(
        machine["id"], run["id"], CERTIFIER))
    assert certified["quality_status"] == "CERTIFIED"

    response = api_client.allocate_roll_set(
        roll_set["id"],
        {"order_id": order["id"], "expected_order_version": order_version(order["id"])},
        PLANNER)
    validate_error(response, ApiErrorId.ERR_ROLL_SPEC_MISMATCH.value, 409)

    unallocated = get_success_data(api_client.get_roll_set(roll_set["id"], OPERATOR))
    assert unallocated["status"] == "WRAPPED"
    assert unallocated["allocated_order_id"] is None
    assert unallocated["slit_width_mm"] == 2200
    still_open = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert still_open["status"] == "IN_PRODUCTION"
    assert still_open["allocated_tons"] == pytest.approx(0.000, abs=1e-6)
    assert still_open["shortfall_tons"] == pytest.approx(10.000, abs=1e-6), \
        "the width equality is exact, so nothing of this set counts"
