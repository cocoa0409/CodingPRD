"""Compression-garment classification and DME dispensing: L-code derivation, the
dispense state/referential/stock guards, stock conservation on return, and return
idempotency.

Queue A: combinatorial_garment_class_lcode, cross_dispense_requires_garment_order_approved,
compensating_dme_stock_conserves_units.
Queue B: garment_classification_leg_class4_custom, error_dme_lcode_mismatch_on_dispense,
error_dme_insufficient_stock_on_dispense, return_already_returned_dispense_returns_invalid_state.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    validate_success,
    validate_error,
    get_success_data,
    create_patient,
    create_finalized_evaluation,
    create_garment_order,
    create_dispense,
    setup_approved_order_and_item,
    setup_draft_order_and_item,
)

CLINICIAN = TEST_USERS["clinician_headers"]
DME = TEST_USERS["dme_coordinator_headers"]


# ---- Queue A: combinatorial_garment_class_lcode (>=2 tests) ----

def test_arm_stage2_bump_yields_class3_l8100(api):
    """PRD §3.6: "The base class is bumped up by one when the excess volume reaches or
    exceeds the group's volume-bump threshold — 150 ml for the arm group ... a SLEEVE is
    L8100 off-the-shelf and L8102 custom."

    Design: Difficulty/combinatorial_formula/combinatorial_garment_class_lcode
    """
    patient = create_patient()
    evaluation = create_finalized_evaluation(
        patient["id"], body_region="LEFT_ARM", isl_stage="STAGE_II",
    )  # excess_volume_ml == 152.4 (>= 150 arm bump), base 2 -> 3
    order = create_garment_order(patient["id"], evaluation["id"])
    assert order["compression_class"] == "CLASS_3"
    assert order["l_code"] == "L8100"


def test_arm_stage2_order_is_sleeve_off_the_shelf(api):
    """PRD §3.6: "LEFT_ARM and RIGHT_ARM yield SLEEVE ... it is true when the capped
    compression class equals 4, or when the excess volume reaches or exceeds the group's
    custom threshold — 400 ml for the arm group."

    Design: Difficulty/combinatorial_formula/combinatorial_garment_class_lcode
    """
    patient = create_patient()
    evaluation = create_finalized_evaluation(
        patient["id"], body_region="LEFT_ARM", isl_stage="STAGE_II",
    )  # excess 152.4 < 400 arm custom threshold, class 3 != 4 -> not custom
    order = create_garment_order(patient["id"], evaluation["id"])
    assert order["garment_type"] == "SLEEVE"
    assert order["custom_fabrication"] is False


# ---- Queue B: leg class-4 custom classification ----

def test_leg_stage3_high_excess_yields_class4_custom_stocking(api):
    """PRD §3.6: "The bumped class is then capped at 4 ... Whether the garment must be
    custom-fabricated ... is true when the capped compression class equals 4 ... a
    STOCKING is L8110 off-the-shelf and L8112 custom."

    Design: Corner/calculations/garment_classification_leg_class4_custom
    """
    patient = create_patient()
    evaluation = create_finalized_evaluation(
        patient["id"], body_region="LEFT_LEG", isl_stage="STAGE_III", interval_cm=4,
        circumferences_cm=[40, 45, 50, 55, 60], contralateral_circumferences_cm=[30, 32, 34, 36, 38],
    )  # excess_volume_ml == 1746.8
    order = create_garment_order(patient["id"], evaluation["id"])
    assert order["compression_class"] == "CLASS_4"
    assert order["l_code"] == "L8112"
    assert order["garment_type"] == "STOCKING"
    assert order["custom_fabrication"] is True


# ---- Queue A: cross_dispense_requires_garment_order_approved (>=2 tests) ----

def test_dispense_rejected_when_order_not_approved(api):
    """PRD §3.7: "The referenced garment order must be APPROVED, otherwise
    ERR_GARMENT_ORDER_NOT_APPROVED."

    Design: Difficulty/cross_entity_state_dependency/cross_dispense_requires_garment_order_approved
    """
    ctx = setup_draft_order_and_item(initial_stock_qty=10, item_l_code="L8100")
    resp = api.create_dispense(
        {"garment_order_id": ctx["garment_order"]["id"], "dme_item_id": ctx["dme_item"]["id"], "quantity": 1},
        DME,
    )
    validate_error(resp, ApiErrorId.ERR_GARMENT_ORDER_NOT_APPROVED)


def test_dispense_rejection_leaves_stock_untouched(api):
    """PRD §3.7: "A successful dispense is created in status DISPENSED ... increases the
    item's outstanding_dispensed_qty by the dispensed quantity, and decreases its
    on_hand_qty by the same amount."

    Design: Difficulty/cross_entity_state_dependency/cross_dispense_requires_garment_order_approved
    """
    ctx = setup_draft_order_and_item(initial_stock_qty=10, item_l_code="L8100")
    api.create_dispense(
        {"garment_order_id": ctx["garment_order"]["id"], "dme_item_id": ctx["dme_item"]["id"], "quantity": 1},
        DME,
    )
    item = get_success_data(api.get_dme_item(ctx["dme_item"]["id"], DME))
    assert item["on_hand_qty"] == 10


# ---- Queue A: compensating_dme_stock_conserves_units (>=2 tests) ----

def test_dispense_decrements_on_hand_stock(api):
    """PRD §3.7: "A successful dispense is created in status DISPENSED ... increases the
    item's outstanding_dispensed_qty by the dispensed quantity, and decreases its
    on_hand_qty by the same amount."

    Design: Difficulty/compensating_invariant/compensating_dme_stock_conserves_units
    """
    ctx = setup_approved_order_and_item(initial_stock_qty=10, item_l_code="L8100")
    create_dispense(ctx["garment_order"]["id"], ctx["dme_item"]["id"], quantity=3)
    item = get_success_data(api.get_dme_item(ctx["dme_item"]["id"], DME))
    assert item["on_hand_qty"] == 7
    assert item["outstanding_dispensed_qty"] == 3


def test_return_restores_on_hand_stock(api):
    """PRD §3.7: "A return is compensating: the item's outstanding_dispensed_qty decreases
    by the returned quantity and its on_hand_qty increases by the same amount, restoring
    the stock."

    Design: Difficulty/compensating_invariant/compensating_dme_stock_conserves_units
    """
    ctx = setup_approved_order_and_item(initial_stock_qty=10, item_l_code="L8100")
    dispense = create_dispense(ctx["garment_order"]["id"], ctx["dme_item"]["id"], quantity=3)
    get_success_data(api.return_dispense(dispense["id"], DME))
    item = get_success_data(api.get_dme_item(ctx["dme_item"]["id"], DME))
    assert item["on_hand_qty"] == 10
    assert item["outstanding_dispensed_qty"] == 0


# ---- Queue B: dispense referential / stock / idempotency ----

def test_dispense_lcode_mismatch_rejected(api):
    """PRD §3.7: "The chosen DME item's l_code must equal the garment order's l_code,
    otherwise ERR_DME_LCODE_MISMATCH."

    Design: Corner/validations/error_dme_lcode_mismatch_on_dispense
    """
    ctx = setup_approved_order_and_item(initial_stock_qty=10, item_l_code="L8110")
    resp = api.create_dispense(
        {"garment_order_id": ctx["garment_order"]["id"], "dme_item_id": ctx["dme_item"]["id"], "quantity": 1},
        DME,
    )
    validate_error(resp, ApiErrorId.ERR_DME_LCODE_MISMATCH)


def test_dispense_exceeding_stock_rejected(api):
    """PRD §3.7: "The dispensed quantity must not exceed the item's on_hand_qty, otherwise
    ERR_DME_INSUFFICIENT_STOCK."

    Design: Corner/validations/error_dme_insufficient_stock_on_dispense
    """
    ctx = setup_approved_order_and_item(initial_stock_qty=1, item_l_code="L8100")
    resp = api.create_dispense(
        {"garment_order_id": ctx["garment_order"]["id"], "dme_item_id": ctx["dme_item"]["id"], "quantity": 5},
        DME,
    )
    validate_error(resp, ApiErrorId.ERR_DME_INSUFFICIENT_STOCK)
    item = get_success_data(api.get_dme_item(ctx["dme_item"]["id"], DME))
    assert item["on_hand_qty"] == 1


def test_return_already_returned_dispense_invalid_state(api):
    """PRD §3.7: "A DMECoordinator may reverse a dispense by returning it, which requires
    the dispense to be DISPENSED (otherwise ERR_INVALID_STATE) and advances it DISPENSED
    → RETURNED."

    Design: Corner/state_machines/return_already_returned_dispense_returns_invalid_state
    """
    ctx = setup_approved_order_and_item(initial_stock_qty=10, item_l_code="L8100")
    dispense = create_dispense(ctx["garment_order"]["id"], ctx["dme_item"]["id"], quantity=2)
    get_success_data(api.return_dispense(dispense["id"], DME))
    validate_error(api.return_dispense(dispense["id"], DME), ApiErrorId.ERR_INVALID_STATE)
    item = get_success_data(api.get_dme_item(ctx["dme_item"]["id"], DME))
    assert item["on_hand_qty"] == 10
