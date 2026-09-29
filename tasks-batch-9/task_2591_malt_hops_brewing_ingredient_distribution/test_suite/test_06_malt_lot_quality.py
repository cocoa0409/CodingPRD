"""Malt lots: the quarantine/retest loop and the pick gate that reads its result."""
import pytest

from test_helpers import (
    ANALYST_HEADERS,
    ANALYST_USER_ID,
    RELEASER_USER_ID,
    WH_HEADERS,
    add_malt_line,
    analyse_lot,
    approve_credit,
    confirm_order,
    create_brewer,
    create_lot,
    create_malt_product,
    create_order,
    create_passed_lot,
    release_lot,
    pin_clock,
    validate_error,
    validate_success,
)

QUARANTINING_SHEET = {"color_lovibond": 2.60, "extract_pct": 79.90,
                      "moisture_pct": 6.10, "protein_pct": 11.10,
                      "diastatic_power": 92.00}
CLEAN_SHEET = {"color_lovibond": 2.60, "extract_pct": 79.90,
               "moisture_pct": 4.20, "protein_pct": 11.10,
               "diastatic_power": 92.00}


@pytest.fixture
def wet_lot():
    """A RECEIVED 20,000 lb lot of BASE malt capped at 5.0 percent moisture."""
    pin_clock()
    product = create_malt_product()
    lot = create_lot(product["id"], quantity_lbs=20000, lot_code="LOT-QT-01")
    return {"product": product, "lot": lot}


def test_an_over_moisture_sheet_quarantines_the_lot_and_names_the_reason(
        api, wet_lot):
    """6.10 percent moisture against a 5.0 cap sets MOISTURE_ABOVE_MAX.

    PRD §3.6: "The lot is quarantined — `RECEIVED → QUARANTINED` — when its
    `moisture_pct` is strictly above `max_moisture_pct`, or when the product's
    `malt_class` is `BASE` and its `diastatic_power` is strictly below
    `min_diastatic_power`; quarantining sets `quarantine_reason` to
    `MOISTURE_ABOVE_MAX` or `DIASTATIC_POWER_BELOW_MIN`, with moisture evaluated
    first so that a lot failing both reports the moisture reason"

    Design: Difficulty/non_linear_state_machine/malt_lot_quarantine_retest_cycle_preserves_analysis_count
    """
    world = wet_lot
    lot = analyse_lot(world["lot"]["id"], **QUARANTINING_SHEET)

    assert lot["status"] == "QUARANTINED", (
        f"the wet sheet takes the quarantine fork, got {lot['status']}")
    assert lot["quarantine_reason"] == "MOISTURE_ABOVE_MAX", (
        f"moisture is the reason, got {lot['quarantine_reason']}")
    assert lot["analysis_count"] == 1, (
        f"the first sheet counts once, got {lot['analysis_count']}")
    assert lot["moisture_pct"] == pytest.approx(6.10, abs=0.005), (
        f"the filed figure is written onto the lot, got {lot['moisture_pct']}")
    assert lot["analyzed_by_user_id"] == ANALYST_USER_ID, (
        f"the filing operator is recorded, got {lot['analyzed_by_user_id']}")


def test_a_retest_returns_the_lot_to_received_without_resetting_the_count(
        api, wet_lot):
    """Re-entering the initial state is not a reset: analysis_count stays at 1.

    PRD §3.6: "A retest, carrying an optional `retest_reason`, moves it
    `QUARANTINED → RECEIVED` and clears `quarantine_reason` to null while leaving
    `analysis_count` and the previously recorded analysis values intact"

    Design: Difficulty/non_linear_state_machine/malt_lot_quarantine_retest_cycle_preserves_analysis_count
    """
    world = wet_lot
    analyse_lot(world["lot"]["id"], **QUARANTINING_SHEET)
    lot = validate_success(api.retest_malt_lot(
        world["lot"]["id"], {"retest_reason": "resampled after kiln re-dry"},
        ANALYST_HEADERS))

    assert lot["status"] == "RECEIVED", (
        f"the retest re-enters the initial state, got {lot['status']}")
    assert lot["quarantine_reason"] is None, (
        f"the reason is cleared, got {lot['quarantine_reason']}")
    assert lot["analysis_count"] == 1, (
        "the retest is not itself an analysis, got "
        f"{lot['analysis_count']}")
    assert lot["moisture_pct"] == pytest.approx(6.10, abs=0.005), (
        f"the prior figures survive the retest, got {lot['moisture_pct']}")


def test_the_second_sheet_passes_the_lot_and_the_count_reads_two(api, wet_lot):
    """A clean re-sample carries the lot to RELEASED with a monotone count of 2.

    PRD §3.6: "A passed lot is released for picking by a `WarehouseOperator` with
    an optional `release_note`, moving `PASSED → RELEASED`, which is also
    terminal, and recording `released_by_user_id` as the releasing `X-User-ID`."

    Design: Difficulty/non_linear_state_machine/malt_lot_quarantine_retest_cycle_preserves_analysis_count
    """
    world = wet_lot
    analyse_lot(world["lot"]["id"], **QUARANTINING_SHEET)
    validate_success(api.retest_malt_lot(
        world["lot"]["id"], {"retest_reason": "resampled after kiln re-dry"},
        ANALYST_HEADERS))
    passed = analyse_lot(world["lot"]["id"], **CLEAN_SHEET)

    assert passed["status"] == "PASSED", (
        f"the dry sheet takes the passing fork, got {passed['status']}")
    assert passed["analysis_count"] == 2, (
        "the count is monotone across the loop, got "
        f"{passed['analysis_count']}")
    assert passed["moisture_pct"] == pytest.approx(4.20, abs=0.005), (
        f"the second sheet overwrites the figures, got {passed['moisture_pct']}")
    assert passed["quarantine_reason"] is None, (
        f"passing clears the reason, got {passed['quarantine_reason']}")

    released = release_lot(world["lot"]["id"], release_note="cleared on retest")
    assert released["status"] == "RELEASED", (
        f"release is terminal, got {released['status']}")
    assert released["analysis_count"] == 2, (
        f"release does not touch the count, got {released['analysis_count']}")
    assert released["analyzed_by_user_id"] == ANALYST_USER_ID, (
        f"the analyst is still recorded, got {released['analyzed_by_user_id']}")
    assert released["released_by_user_id"] == RELEASER_USER_ID, (
        f"a second operator released it, got {released['released_by_user_id']}")
    assert released["version"] == 5, (
        "receipt, two sheets, a retest and a release are five writes, got "
        f"version {released['version']}")


@pytest.fixture
def order_waiting_on_a_passed_lot():
    """A CONFIRMED, credit-APPROVED malt order drawing on a lot still only PASSED."""
    pin_clock()
    brewer = create_brewer(name="Held Lot Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=False, legacy_trailing_lbs=0)
    product = create_malt_product()
    lot = create_passed_lot(product["id"], quantity_lbs=20000,
                            lot_code="LOT-2607")
    order = create_order(brewer["id"],
                         requested_ship_date="2026-09-20T00:00:00Z",
                         purchase_order_ref="PO-LOT")
    add_malt_line(order["id"], brewer["id"], lot["id"], 1000)
    add_malt_line(order["id"], brewer["id"], lot["id"], 1000)
    order = confirm_order(order["id"], brewer["id"])
    order = approve_credit(order["id"])
    return {"brewer": brewer, "product": product, "lot": lot, "order": order}


def test_the_pick_is_refused_because_a_different_entity_is_one_transition_short(
        api, order_waiting_on_a_passed_lot):
    """Everything about the order is in order; the lot is merely PASSED.

    PRD §3.8: "every `MALT` line's lot must be in `RELEASED`, otherwise
    `ERR_MALT_LOT_NOT_RELEASED`"

    Design: Difficulty/cross_entity_state_dependency/order_pick_gated_on_malt_lot_release_state
    """
    world = order_waiting_on_a_passed_lot
    lot = validate_success(api.get_malt_lot(world["lot"]["id"], WH_HEADERS))
    assert lot["status"] == "PASSED", (
        f"the lot must be one transition short, got {lot['status']}")
    assert lot["released_by_user_id"] is None, (
        f"nobody has released it, got {lot['released_by_user_id']}")

    assert world["order"]["fulfillment_status"] == "CONFIRMED", (
        f"the order is ready to pick, got {world['order']['fulfillment_status']}")
    assert world["order"]["credit_status"] == "APPROVED", (
        f"credit is cleared, got {world['order']['credit_status']}")
    assert world["order"]["total_cents"] == 171000, (
        f"137000 + 25000 freight + 9000 pallet breaks = 171000, got "
        f"{world['order']['total_cents']}")

    blocked = api.pick_order(world["order"]["id"], WH_HEADERS)
    validate_error(blocked, "ERR_MALT_LOT_NOT_RELEASED", expected_status=409)

    order = validate_success(api.get_sales_order(world["order"]["id"], WH_HEADERS))
    assert order["fulfillment_status"] == "CONFIRMED", (
        f"the refusal moves nothing, got {order['fulfillment_status']}")
    assert order["credit_status"] == "APPROVED", (
        f"credit is untouched by the refusal, got {order['credit_status']}")


def test_releasing_the_lot_with_a_second_operator_unblocks_the_same_pick(
        api, order_waiting_on_a_passed_lot):
    """Only an act on the lot — by a different user — can clear the gate.

    PRD §3.6: "The releasing user may not be the user recorded in
    `analyzed_by_user_id`, per §2.9."

    Design: Difficulty/cross_entity_state_dependency/order_pick_gated_on_malt_lot_release_state
    """
    world = order_waiting_on_a_passed_lot
    validate_error(api.pick_order(world["order"]["id"], WH_HEADERS),
                   "ERR_MALT_LOT_NOT_RELEASED", expected_status=409)

    released = release_lot(world["lot"]["id"],
                           release_note="QA sign-off by second operator")
    assert released["status"] == "RELEASED", (
        f"the second operator releases the lot, got {released['status']}")
    assert released["released_by_user_id"] == RELEASER_USER_ID, (
        f"the releasing operator is recorded, got {released['released_by_user_id']}")
    assert released["analyzed_by_user_id"] == ANALYST_USER_ID, (
        "the two recorded operators must differ, got "
        f"{released['analyzed_by_user_id']} and {released['released_by_user_id']}")

    picked = validate_success(api.pick_order(world["order"]["id"], WH_HEADERS))
    assert picked["fulfillment_status"] == "PICKED", (
        f"the same pick now succeeds, got {picked['fulfillment_status']}")
    assert picked["credit_status"] == "APPROVED", (
        f"the credit dimension never moved, got {picked['credit_status']}")
    assert picked["total_cents"] == 171000, (
        f"picking reprices nothing, got {picked['total_cents']}")
