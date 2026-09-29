"""Three parents that advance under the client's feet: the machine a run creation bumps,
the purchase order a withdrawal supersedes, and the order the first allocation moves.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, declare_fiber_grade, declare_tl_140, publish_quote, register_supplier,
    register_customer, register_machine, register_permit, create_draft_po,
    create_run_payload, setup_available_lot, setup_approved_batch, schedule_run,
    start_run, complete_run, wind_roll_set, wrap_roll_set, submit_order,
    schedule_order, machine_version, order_version, po_version, sublot,
    ON_SPEC_REELS_TL_140, set_clock,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
OPERATOR = TEST_USERS["operator_headers"]
CERTIFIER = TEST_USERS["lab_cert_headers"]

PM1 = {"name": "PM1", "wire_width_mm": 5600, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 30, "steam_tph_per_ton": 2.500}
TWENTY_TWO_TON_SUBLOT = [sublot(1, 30.000, 8.000, 10.00, 2.00)]


def test_the_second_run_must_re_read_the_machine_the_first_run_bumped():
    """PRD §2.5: "Creating a production run on a paper machine must carry
    `expected_machine_version`, holding the client's last observed `version` of the target
    `PaperMachine`. A mismatch against the machine's current `version` is rejected with
    `ERR_STALE_MACHINE_VERSION` (HTTP 412). Run creation, run start, run completion and run
    abort all bump the machine's `version`, so a scheduler working from an older read is
    reasoning about an occupancy picture that has already changed."
    PRD §2.5: "Version checks are evaluated after state-machine from-state checks and before
    any business rule."

    Design: Corner/cross_cutting_complexity_layers/occ_a_second_run_cannot_be_scheduled_on_a_machine_version_the_first_run_bumped
    """
    set_clock("2026-08-01T00:00:00Z")
    machine = register_machine(**PM1)
    bundle = setup_approved_batch(
        tons_charged=20.000, measured_reject_tons=2.000,
        lot_bundle=setup_available_lot(sublots_list=TWENTY_TWO_TON_SUBLOT))
    batch_id = bundle["batch"]["id"]
    version_before = machine_version(machine["id"])
    first = schedule_run(machine["id"], "TL_140", batch_id,
                         window_start="2026-09-01T06:00:00Z",
                         window_end="2026-09-01T14:00:00Z", pulp_draw_tons=5.000)
    assert machine_version(machine["id"]) == version_before + 1

    stale = api_client.create_run(machine["id"], create_run_payload(
        "TL_140", batch_id, version_before,
        window_start="2026-09-01T12:00:00Z", window_end="2026-09-01T16:00:00Z",
        pulp_draw_tons=5.000), PLANNER)
    validate_error(stale, ApiErrorId.ERR_STALE_MACHINE_VERSION.value, 412)

    assert machine_version(machine["id"]) == version_before + 1, \
        "the refused call bumped nothing, overlapping window and all"
    refreshed = validate_success(api_client.create_run(machine["id"], create_run_payload(
        "TL_140", batch_id, machine_version(machine["id"]),
        window_start="2026-09-02T06:00:00Z", window_end="2026-09-02T10:00:00Z",
        pulp_draw_tons=5.000), PLANNER), 201)
    assert refreshed["run_status"] == "SCHEDULED"
    listing = api_client.list_machine_runs(machine["id"], PLANNER).json()
    assert listing["meta"]["total_count"] == 2
    assert {row["id"] for row in listing["data"]} == {first["id"], refreshed["id"]}
    assert machine_version(machine["id"]) == version_before + 2


def test_repricing_from_the_version_a_withdrawal_superseded_is_refused():
    """PRD §2.5: "Pricing a fiber purchase order must carry
    `expected_purchase_order_version`, holding the client's last observed `version` of that
    `FiberPurchaseOrder`. A mismatch against the order's current `version` is rejected with
    `ERR_STALE_PURCHASE_ORDER_VERSION` (HTTP 412). Withdrawing a price legitimately
    supersedes an earlier pricing run and bumps the version, so a buyer re-pricing from a
    stale read would be overwriting a revision it never saw."
    PRD §3.1: "Withdrawal requires the order to be in `PRICED` and requires
    `pricing_revision_count` to be below 2; it increments `pricing_revision_count` by one,
    clears `quoted_unit_price_per_ton`, `fuel_surcharge_per_ton`, `extended_contract_value`
    and `index_quote_month_used` back to null, and bumps `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_repricing_from_a_version_a_withdrawal_superseded_is_refused
    """
    set_clock("2026-08-01T00:00:00Z")
    declare_fiber_grade(grade_code="OCC_11", index_symbol="PPI_OCC",
                        max_contamination_pct=3.00, max_moisture_pct=12.00,
                        nominal_yield_pct=88.00, rank_order=1)
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-08",
                  published_price_per_ton=180.00)
    supplier = register_supplier(name="Delta Fiber Recovery", freight_per_ton=12.50)
    draft = create_draft_po(supplier["id"], "OCC_11", contracted_tons=400.00,
                            negotiated_delta_per_ton=5.00)
    version_at_creation = draft["version"]
    priced = validate_success(api_client.price_purchase_order(
        draft["id"], {"expected_purchase_order_version": version_at_creation}, BUYER))
    validate_success(api_client.withdraw_purchase_order_pricing(
        draft["id"], {"expected_purchase_order_version": priced["version"]}, BUYER))

    stale = api_client.price_purchase_order(
        draft["id"], {"expected_purchase_order_version": version_at_creation}, BUYER)
    validate_error(stale, ApiErrorId.ERR_STALE_PURCHASE_ORDER_VERSION.value, 412)

    withdrawn = get_success_data(api_client.get_purchase_order(draft["id"], BUYER))
    assert withdrawn["status"] == "DRAFT"
    assert withdrawn["pricing_revision_count"] == 1
    assert withdrawn["quoted_unit_price_per_ton"] is None, \
        "the refused write did not partially apply"
    assert withdrawn["index_quote_month_used"] is None
    assert withdrawn["version"] == version_at_creation + 2

    repriced = validate_success(api_client.price_purchase_order(
        draft["id"], {"expected_purchase_order_version": withdrawn["version"]}, BUYER))
    assert repriced["status"] == "PRICED"
    assert repriced["quoted_unit_price_per_ton"] == pytest.approx(199.81, abs=1e-6)


def test_the_second_roll_set_must_re_read_the_order_the_first_allocation_advanced():
    """PRD §2.5: "Allocating a roll set to a customer order must carry
    `expected_order_version`, holding the client's last observed `version` of the target
    `CustomerOrder`. If that value does not equal the order's current `version` — which
    happens whenever another allocation against the same order has already landed and moved
    the order's `allocated_tons` and `status` — the request is rejected with
    `ERR_STALE_ORDER_VERSION` (HTTP 412)."
    PRD §3.6: "The order's ledger is recomputed from the roll sets rather than accumulated:
    `allocated_tons` is the sum of `net_tons` over roll sets whose `allocated_order_id` is
    this order and whose status is `ALLOCATED` or `SHIPPED`, rounded to three decimal
    places; `shipped_tons` is the same sum restricted to sets in `SHIPPED`; and
    `shortfall_tons` is `ordered_tons` minus `allocated_tons`, floored at zero and rounded
    to three decimal places."

    Design: Corner/cross_cutting_complexity_layers/occ_the_second_roll_set_must_re_read_the_order_the_first_allocation_advanced
    """
    set_clock("2026-08-01T00:00:00Z")
    register_permit()
    declare_tl_140()
    machine = register_machine(**PM1)
    bundle = setup_approved_batch(
        tons_charged=20.000, measured_reject_tons=2.000, declare_spec=False,
        lot_bundle=setup_available_lot(sublots_list=TWENTY_TWO_TON_SUBLOT))
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       pulp_draw_tons=15.000)
    customer = register_customer(name="Great Lakes Converting",
                                 allocation_priority_tier="P1",
                                 max_roll_diameter_mm=1400, max_roll_width_mm=2400,
                                 wrap_spec="KRAFT_ONLY")
    order = submit_order(customer, "TL_140", ordered_tons=10.00, roll_width_mm=2200,
                         roll_diameter_mm=1300, wrap_spec="KRAFT_ONLY")
    schedule_order(order["id"], run["id"])
    start_run(machine["id"], run["id"])
    first_set = wind_roll_set(run["id"], slit_width_mm=2200, diameter_mm=1300,
                              roll_count=8, net_tons=6.000)
    second_set = wind_roll_set(run["id"], slit_width_mm=2200, diameter_mm=1300,
                               roll_count=6, net_tons=4.000)
    complete_run(machine["id"], run["id"], ON_SPEC_REELS_TL_140)
    wrap_roll_set(first_set["id"], "KRAFT_ONLY")
    wrap_roll_set(second_set["id"], "KRAFT_ONLY")
    validate_success(api_client.certify_run(machine["id"], run["id"], CERTIFIER))
    version_before_any_allocation = order_version(order["id"])
    validate_success(api_client.allocate_roll_set(
        first_set["id"], {"order_id": order["id"],
                          "expected_order_version": version_before_any_allocation},
        PLANNER))
    half_filled = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert half_filled["status"] == "PARTIALLY_ALLOCATED"
    assert half_filled["allocated_tons"] == pytest.approx(6.000, abs=1e-6)
    assert half_filled["shortfall_tons"] == pytest.approx(4.000, abs=1e-6)
    assert half_filled["version"] > version_before_any_allocation

    stale = api_client.allocate_roll_set(
        second_set["id"], {"order_id": order["id"],
                           "expected_order_version": version_before_any_allocation},
        PLANNER)
    validate_error(stale, ApiErrorId.ERR_STALE_ORDER_VERSION.value, 412)

    waiting = get_success_data(api_client.get_roll_set(second_set["id"], PLANNER))
    assert waiting["status"] == "WRAPPED"
    assert waiting["allocated_order_id"] is None

    landed = validate_success(api_client.allocate_roll_set(
        second_set["id"], {"order_id": order["id"],
                           "expected_order_version": order_version(order["id"])},
        PLANNER))
    assert landed["status"] == "ALLOCATED"
    assert landed["allocated_order_id"] == order["id"]
    filled = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert filled["status"] == "ALLOCATED"
    assert filled["allocated_tons"] == pytest.approx(10.000, abs=1e-6)
    assert filled["shortfall_tons"] == pytest.approx(0.000, abs=1e-6)
    assert filled["version"] > half_filled["version"]
