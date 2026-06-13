"""Retrieval-request lifecycle and storage box flows: the refuse-return cycle,
the fulfill-drives-box cascade, the box-state precondition on fulfill, and the
storage-invoice pay action.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    setup_pending_retrieval,
    setup_delivered_retrieval,
    setup_return_pending_retrieval,
    setup_ingested_box,
    setup_stored_box,
    create_retrieval,
)

CO = TEST_USERS["compliance_officer_headers"]
AM = TEST_USERS["account_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]


# ===========================================================================
# non_linear_state_machine / retrieval_request_refuse_return_cycle
# ===========================================================================
def test_refuse_return_cycles_back_to_delivered(api):
    """PRD §3.9: "Alternatively, if the returned box fails inspection - for
    instance, a broken seal - a PlantOperator may refuse the return, cycling
    RETURN_PENDING back to DELIVERED and leaving the box OUT_FOR_RETRIEVAL, so the
    customer must restart the return."

    A RETURN_PENDING request refused returns to DELIVERED with the box still out.

    Design: Difficulty/non_linear_state_machine/retrieval_request_refuse_return_cycle
    """
    state = setup_return_pending_retrieval(priority="STANDARD")
    refused = validate_success(api.refuse_return(state["request"]["id"], PO), 200)
    assert refused["status"] == "DELIVERED", f"got {refused['status']}"
    box = validate_success(api.get_retention_box(state["box"]["id"], AM), 200)
    assert box["status"] == "OUT_FOR_RETRIEVAL", f"got {box['status']}"


def test_refuse_return_leaves_box_out_for_retrieval(api):
    """PRD §3.9: "cycling RETURN_PENDING back to DELIVERED and leaving the box
    OUT_FOR_RETRIEVAL, so the customer must restart the return."

    After a refused return the box stays OUT_FOR_RETRIEVAL rather than returning
    to STORED.

    Design: Difficulty/non_linear_state_machine/retrieval_request_refuse_return_cycle
    """
    state = setup_return_pending_retrieval(priority="STANDARD")
    validate_success(api.refuse_return(state["request"]["id"], PO), 200)
    box = validate_success(api.get_retention_box(state["box"]["id"], AM), 200)
    assert box["status"] == "OUT_FOR_RETRIEVAL"


# ===========================================================================
# transitive_cascade / fulfill_request_drives_box_depth2
# ===========================================================================
def test_fulfill_delivers_request_and_drives_box_out(api):
    """PRD §3.9: "The computed amount is snapshotted onto retrieval_charge_cents,
    delivered_period is set to the account's current current_period_index
    (pinning which storage invoice the charge lands on), and the box moves from
    STORED to OUT_FOR_RETRIEVAL."

    A STANDARD fulfillment delivers the request, snapshots charge 4000, and drives
    the box STORED -> OUT_FOR_RETRIEVAL.

    Design: Difficulty/transitive_cascade/fulfill_request_drives_box_depth2
    """
    state = setup_pending_retrieval(priority="STANDARD")
    delivered = validate_success(api.fulfill_retrieval(state["request"]["id"], PO), 200)
    assert delivered["status"] == "DELIVERED", f"got {delivered['status']}"
    assert delivered["retrieval_charge_cents"] == 4000, f"got {delivered['retrieval_charge_cents']}"
    box = validate_success(api.get_retention_box(state["box"]["id"], AM), 200)
    assert box["status"] == "OUT_FOR_RETRIEVAL", f"got {box['status']}"


def test_fulfill_standard_charge_is_base_fee(api):
    """PRD §3.9: "the base is retrieval_fee_cents, and for a STANDARD request the
    charge is exactly that base."

    A STANDARD retrieval is charged the flat base fee of 4000.

    Design: Difficulty/transitive_cascade/fulfill_request_drives_box_depth2
    """
    state = setup_pending_retrieval(priority="STANDARD")
    delivered = validate_success(api.fulfill_retrieval(state["request"]["id"], PO), 200)
    assert delivered["retrieval_charge_cents"] == 4000


# ===========================================================================
# cross_entity_state_dependency / retrieval_fulfill_requires_box_stored
# ===========================================================================
def test_fulfill_rejected_when_box_not_stored(api):
    """PRD §3.9: "Fulfillment is defined only when the request is in PENDING
    (otherwise ERR_REQUEST_NOT_PENDING), only when the target box is in STORED
    (otherwise ERR_BOX_NOT_STORED)."

    A PENDING request whose box is still INGESTED (never shelved) cannot be
    fulfilled; the request remains PENDING.

    Design: Difficulty/cross_entity_state_dependency/retrieval_fulfill_requires_box_stored
    """
    state = setup_ingested_box(barcode="BX-1")
    request = create_retrieval(state["box"]["id"], state["account"]["id"], priority="STANDARD")
    validate_error(api.fulfill_retrieval(request["id"], PO),
                   ApiErrorId.ERR_BOX_NOT_STORED.value)
    after = validate_success(api.get_retrieval_request(request["id"], AM), 200)
    assert after["status"] == "PENDING", "unchanged after rejected fulfill"


def test_fulfill_on_ingested_box_leaves_request_pending(api):
    """PRD §3.9: "only when the target box is in STORED (otherwise
    ERR_BOX_NOT_STORED)."

    The rejected fulfill does not advance the request past PENDING.

    Design: Difficulty/cross_entity_state_dependency/retrieval_fulfill_requires_box_stored
    """
    state = setup_ingested_box(barcode="BX-1")
    request = create_retrieval(state["box"]["id"], state["account"]["id"], priority="STANDARD")
    validate_error(api.fulfill_retrieval(request["id"], PO),
                   ApiErrorId.ERR_BOX_NOT_STORED.value)
    assert validate_success(api.get_retrieval_request(request["id"], AM), 200)["status"] == "PENDING"


# ===========================================================================
# Corner: endpoints / pay_storage_invoice_action
# ===========================================================================
def test_pay_storage_invoice_transitions_to_paid(api):
    """PRD §3.8: "A ComplianceOfficer may later mark a storage invoice paid,
    moving its status from ISSUED to PAID."

    The ISSUED invoice emitted by advance-period transitions to PAID.

    Design: Corner/endpoints/pay_storage_invoice_action
    """
    state = setup_stored_box(barcode="BX-1")
    inv = validate_success(api.advance_period(state["account"]["id"], CO), 201)
    assert inv["status"] == "ISSUED"
    paid = validate_success(api.pay_storage_invoice(inv["id"], CO), 200)
    assert paid["status"] == "PAID", f"got {paid['status']}"
