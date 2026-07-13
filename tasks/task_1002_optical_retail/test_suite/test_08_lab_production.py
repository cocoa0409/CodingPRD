"""The lab: the remake cycle that re-enters production, the order's two parallel
dimensions, the bounded failure budget, and terminal-state lockdown."""

from test_helpers import (
    ApiErrorId,
    assert_lab_order,
    decide_warranty_approved,
    drive_lab_order_to_delivered,
    file_warranty_claim,
    qc_fail,
    qc_pass,
    read_lab_order,
    read_order,
    setup_confirmed_order,
    setup_lab_order_at_remake_limit,
    ship_lab_order,
    start_lab_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import LAB, LOW_POWER_RX


def _confirmed_selfpay_order():
    return setup_confirmed_order(
        frame={"price_cents": 9500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M150", "base_price_cents": 0, "material_index": 1.50},
        prescription=dict(LOW_POWER_RX),
    )


# ═════════════════════════════════════════════════════════════════════════════
# The production cycle: IN_PRODUCTION → REMAKE_QUEUED → IN_PRODUCTION
# ═════════════════════════════════════════════════════════════════════════════

def test_a_failed_inspection_sends_the_lab_order_back_around_the_loop(api):
    """PRD §3.7: "A `FAIL` sends it back around the loop: it advances
    `IN_PRODUCTION → REMAKE_QUEUED`, increments `remake_count` by one, records the supplied
    `failure_reason` on `qc_failure_reason`, and increments `version`."

    Design: Difficulty/non_linear_state_machine/lab_order_remake_cycle_reenters_in_production
    """
    scenario = _confirmed_selfpay_order()
    lab_id = scenario["lab_order"]["id"]
    start_lab_order(lab_id)

    resp = api.qc_lab_order(
        lab_id, {"result": "FAIL", "failure_reason": "axis off by 4 degrees"}, LAB
    )
    failed = validate_success(resp, 200)

    assert_lab_order(failed)
    assert failed["status"] == "REMAKE_QUEUED"
    assert failed["remake_count"] == 1
    assert failed["qc_failure_reason"] == "axis off by 4 degrees"


def test_restarting_from_remake_queued_re_enters_production_without_moving_the_order(api):
    """PRD §3.7: "Starting from `QUEUED` — a first run — also drives the parent order's
    fulfillment dimension `CONFIRMED → IN_LAB`, incrementing the parent order's `version`
    as well as the lab order's. Starting from `REMAKE_QUEUED` — a re-run after a failed
    inspection — closes the production cycle and touches only the lab order's own
    `version`; the parent order is already `IN_LAB` and does not move."

    The loop closes back onto a state the lab order already occupied, and the parent order
    stays pinned at IN_LAB / AUTHORIZED throughout.

    Design: Difficulty/non_linear_state_machine/lab_order_remake_cycle_reenters_in_production
    """
    scenario = _confirmed_selfpay_order()
    lab_id = scenario["lab_order"]["id"]
    order_id = scenario["order"]["id"]

    start_lab_order(lab_id)
    assert read_order(order_id)["fulfillment_status"] == "IN_LAB"
    qc_fail(lab_id, "axis off by 4 degrees")

    resp = api.start_lab_order(lab_id, LAB)
    restarted = validate_success(resp, 200)

    assert restarted["status"] == "IN_PRODUCTION", "the cycle re-entered a previously-held state"
    assert restarted["remake_count"] == 1, "the restart does not reset the failure count"
    assert restarted["qc_failure_reason"] == "axis off by 4 degrees", (
        "only a PASS clears the recorded reason"
    )

    order = read_order(order_id)
    assert order["fulfillment_status"] == "IN_LAB", "the parent order did not move"
    assert order["payment_status"] == "AUTHORIZED"


# ═════════════════════════════════════════════════════════════════════════════
# The order's two parallel dimensions
# ═════════════════════════════════════════════════════════════════════════════

def test_fulfillment_advances_twice_while_payment_stays_authorized(api):
    """PRD §3.6: "Confirmation advances the order's two parallel dimensions together on this
    one trigger: `fulfillment_status` moves `DRAFT → CONFIRMED` and `payment_status` moves
    `UNPAID → AUTHORIZED`."
    PRD §3.7: "Starting from `QUEUED` — a first run — also drives the parent order's
    fulfillment dimension `CONFIRMED → IN_LAB`, incrementing the parent order's `version` as
    well as the lab order's."
    PRD §3.7: "A `PASS` advances the lab order `IN_PRODUCTION → QC_PASSED`, clears
    `qc_failure_reason` back to null, and increments `version`."

    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_dimensions_advance_independently
    """
    scenario = _confirmed_selfpay_order()
    lab_id = scenario["lab_order"]["id"]
    order_id = scenario["order"]["id"]

    assert scenario["order"]["fulfillment_status"] == "CONFIRMED"
    assert scenario["order"]["payment_status"] == "AUTHORIZED"

    start_lab_order(lab_id)
    mid = read_order(order_id)
    assert mid["fulfillment_status"] == "IN_LAB", "the fulfillment axis moved"
    assert mid["payment_status"] == "AUTHORIZED", "the payment axis did not"

    passed = qc_pass(lab_id)
    assert passed["status"] == "QC_PASSED"
    assert passed["qc_failure_reason"] is None

    after_qc = read_order(order_id)
    assert after_qc["fulfillment_status"] == "IN_LAB", "a QC pass moves neither order axis"
    assert after_qc["payment_status"] == "AUTHORIZED"


def test_shipping_the_lab_order_captures_payment_on_the_fulfillment_trigger(api):
    """PRD §3.7: "The lab order advances `QC_PASSED → SHIPPED`, and the parent order advances
    along **both** of its parallel dimensions: `fulfillment_status` moves
    `IN_LAB → READY_FOR_PICKUP` for a `BOPIS` order or `IN_LAB → SHIPPED` for a `SHIP` order,
    while `payment_status` moves `AUTHORIZED → CAPTURED`."
    PRD §3.7: "For a `SHIP` order, `shipped_to_store_id` stays null."

    Three triggers walked the fulfillment axis DRAFT → CONFIRMED → IN_LAB → SHIPPED while the
    payment axis moved exactly once, on the third — the two are never in lock-step.

    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_dimensions_advance_independently
    """
    scenario = _confirmed_selfpay_order()
    lab_id = scenario["lab_order"]["id"]
    order_id = scenario["order"]["id"]

    start_lab_order(lab_id)
    qc_pass(lab_id)

    resp = api.ship_lab_order(lab_id, LAB)
    shipped = validate_success(resp, 200)

    assert shipped["status"] == "SHIPPED"
    assert shipped["shipped_to_store_id"] is None, "a SHIP order routes to no store"

    order = read_order(order_id)
    assert order["fulfillment_status"] == "SHIPPED"
    assert order["payment_status"] == "CAPTURED"


# ═════════════════════════════════════════════════════════════════════════════
# The bounded failure budget and terminal lockdown
# ═════════════════════════════════════════════════════════════════════════════

def test_a_third_qc_failure_exceeds_the_remake_limit(api):
    """PRD §3.7: "And the loop is bounded: a failure is only accepted while `remake_count` is
    **strictly below two**, so the first and second failures are recorded and a third is
    refused with `ERR_REMAKE_LIMIT_EXCEEDED`."

    Design: Corner/state_machines/third_qc_failure_returns_remake_limit_exceeded
    """
    scenario = setup_lab_order_at_remake_limit()
    lab_id = scenario["lab_order"]["id"]
    assert scenario["lab_order"]["status"] == "IN_PRODUCTION"
    assert scenario["lab_order"]["remake_count"] == 2

    resp = api.qc_lab_order(
        lab_id, {"result": "FAIL", "failure_reason": "third strike"}, LAB
    )
    validate_error(resp, ApiErrorId.ERR_REMAKE_LIMIT_EXCEEDED.value)

    after = read_lab_order(lab_id)
    assert after["status"] == "IN_PRODUCTION", "the refused failure left it in production"
    assert after["remake_count"] == 2
    assert after["qc_failure_reason"] == "edge chip", "the second failure's reason still stands"


def test_cancelling_a_delivered_order_is_an_invalid_state(api):
    """PRD §3.6: "Any other fulfillment state — an order already `READY_FOR_PICKUP`,
    `SHIPPED`, `DELIVERED`, or `CANCELLED` — is refused with `ERR_INVALID_STATE`."
    PRD §3.7: "`DELIVERED` and `CANCELLED` are the lab order's terminal states."

    Design: Corner/state_machines/cancelling_a_delivered_order_returns_invalid_state
    """
    scenario = _confirmed_selfpay_order()
    lab_id = scenario["lab_order"]["id"]
    order_id = scenario["order"]["id"]
    drive_lab_order_to_delivered(lab_id)

    assert read_order(order_id)["fulfillment_status"] == "DELIVERED"

    resp = api.cancel_order(order_id, {}, scenario["headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    order = read_order(order_id)
    assert order["fulfillment_status"] == "DELIVERED"
    assert order["payment_status"] == "CAPTURED"
    assert read_lab_order(lab_id)["status"] == "DELIVERED"


def test_lab_order_list_filters_the_remake_out_by_status(api):
    """PRD §3.7: "Lab orders may be read individually and listed with filters on `order_id`,
    `shipped_to_store_id`, `active_warranty_claim_id`, and `status`."
    PRD §3.9: "`APPROVED` advances it `OPEN → APPROVED` and mints a brand-new lab order
    against the same `order_id`: that replacement enters `QUEUED` with `remake_count` back at
    zero and `is_remake` set to true, and its `id` is written to the warranty claim's
    `remake_lab_order_id`."

    Design: Corner/endpoints/lab_orders_list_filters_by_status
    """
    scenario = _confirmed_selfpay_order()
    order_id = scenario["order"]["id"]
    delivered = drive_lab_order_to_delivered(scenario["lab_order"]["id"])

    warranty = file_warranty_claim(
        delivered["id"],
        scenario["customer"]["id"],
        "MANUFACTURER_DEFECT",
        delivered["version"],
    )
    decide_warranty_approved(warranty["id"])

    resp = api.list_lab_orders(
        LAB, params={"order_id": order_id, "status": "QUEUED"}
    )
    rows, meta = validate_paginated(resp)

    assert meta["total_count"] == 1
    assert rows[0]["is_remake"] is True
    assert rows[0]["order_id"] == order_id

    _all_rows, all_meta = validate_paginated(
        api.list_lab_orders(LAB, params={"order_id": order_id})
    )
    assert all_meta["total_count"] == 2, "the original and its remake"
