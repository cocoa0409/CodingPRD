"""Recalls: activation cascade, hold/resume gates, and owner notification tasks."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId,
    create_lot, create_bench,
    create_compound_order, allocate_order,
    create_schedule_for_rx, fetch_compound_order, fetch_lot, fetch_shipment,
    fetch_schedule, fetch_recall,
    setup_verified_scenario, order_to_ready, order_to_dispensed, pay_order_card,
    create_shipment_for_order,
    TEST_USERS, make_owner_headers,
)
from test_helpers.factories import create_recall_payload


def _setup_c1():
    """Verified rx qty 15 (12 kg dog, no flavor); lot 20@110 (sole FEFO source);
    order paid at READY_TO_DISPATCH with a LABEL_CREATED shipment; ACTIVE auto-ship
    schedule on the prescription; DRAFT recall scoped to the lot."""
    scn = setup_verified_scenario(pet_weight_kg=12, catalog_unit_cost=120, quantity=15,
                                  days_supply=15, refills_authorized=3, directions="BID")
    lot = create_lot(scn["drug"]["id"], received_qty=20, unit_cost_cents=110,
                     expiration_date="2027-01-01")
    bench = create_bench()
    order = order_to_ready(scn["rx"]["id"], bench["id"])
    pay_order_card(order["id"], scn["owner"]["id"])
    shipment = create_shipment_for_order(order["id"])
    schedule = create_schedule_for_rx(scn["rx"]["id"], scn["owner"]["id"],
                                      interval_days=15, next_run_date="2026-06-01")
    recall = get_success_data(api_client.create_recall(
        create_recall_payload(scope="LOT", lot_id=lot["id"], reason="contamination",
                              severity="CLASS_II"),
        TEST_USERS["compliance_officer_headers"]))
    scn.update({"lot": lot, "bench": bench, "order": order, "shipment": shipment,
                "schedule": schedule, "recall": recall})
    return scn


def test_recall_activation_quarantines_lot_and_holds_order(api):
    """PRD §3.9: "Every covered lot in `ACTIVE` status moves to `QUARANTINED` with
    its `recall_id` set to the recall."
    PRD §3.9: "Every compound order holding `RESERVED` or `CONSUMED` allocations
    from a covered lot, while in `ALLOCATED`, `COMPOUNDING`, `FLAVORING`,
    `QA_PENDING`, or `READY_TO_DISPATCH`, moves to `RECALL_HOLD` and records the
    state it came from in `hold_origin_state`"

    Design: Difficulty/transitive_cascade/recall_activation_depth4_cascade
    """
    scn = _setup_c1()
    get_success_data(api_client.activate_recall(scn["recall"]["id"],
                                                TEST_USERS["compliance_officer_headers"]))
    lot = fetch_lot(scn["lot"]["id"])
    assert lot["status"] == "QUARANTINED"
    assert lot["recall_id"] == scn["recall"]["id"]
    order = fetch_compound_order(scn["order"]["id"])
    assert order["status"] == "RECALL_HOLD"
    assert order["hold_origin_state"] == "READY_TO_DISPATCH"


def test_recall_activation_quarantines_shipment_pauses_autoship_refunds(api):
    """PRD §3.9: "the order's shipments in `LABEL_CREATED`, `PICKED_UP`,
    `IN_TRANSIT`, or `OUT_FOR_DELIVERY` move to `QUARANTINED` with the refund and
    cooler cascades of §3.7, and `ACTIVE` auto-ship schedules on the order's
    prescription move to `PAUSED`."
    PRD §3.7: "if the order's `payment_status` is `PAID` it moves to `REFUNDED`"

    Design: Difficulty/transitive_cascade/recall_activation_depth4_cascade
    """
    scn = _setup_c1()
    get_success_data(api_client.activate_recall(scn["recall"]["id"],
                                                TEST_USERS["compliance_officer_headers"]))
    assert fetch_shipment(scn["shipment"]["id"])["transit_status"] == "QUARANTINED"
    assert fetch_schedule(scn["schedule"]["id"], scn["owner"]["id"])["status"] == "PAUSED"
    assert fetch_compound_order(scn["order"]["id"])["payment_status"] == "REFUNDED"


def _setup_s8():
    """Order fully DISPENSED (paid, shipment picked up) from the lot; DRAFT recall
    scoped to that lot."""
    scn = setup_verified_scenario(pet_weight_kg=6, quantity=5, days_supply=5)
    lot = create_lot(scn["drug"]["id"], received_qty=50, unit_cost_cents=100)
    bench = create_bench()
    order, shipment = order_to_dispensed(scn["rx"]["id"], bench["id"])
    recall = get_success_data(api_client.create_recall(
        create_recall_payload(scope="LOT", lot_id=lot["id"], reason="particulates",
                              severity="CLASS_I"),
        TEST_USERS["compliance_officer_headers"]))
    scn.update({"lot": lot, "bench": bench, "order": order, "shipment": shipment,
                "recall": recall})
    return scn


def test_recall_activation_spawns_pending_task_and_gates_complete(api):
    """PRD §3.9: "Finally, for every `DISPENSED` compound order whose lots are
    covered, a **RecallTask** is created recording the `recall_id`, the
    `compound_order_id`, and the `owner_id` to notify, with `channel` defaulting to
    `EMAIL` (`PHONE` being the alternative channel) and `status` starting at
    `PENDING`."
    PRD §3.9: "A recall may be completed only once every one of its tasks stands at
    `NOTIFIED` or `ACKNOWLEDGED`"
    Activation creates exactly one PENDING task; an early complete attempt is
    rejected.

    Design: Corner/state_machines/recall_task_flow_and_complete_gate
    """
    scn = _setup_s8()
    get_success_data(api_client.activate_recall(scn["recall"]["id"],
                                                TEST_USERS["compliance_officer_headers"]))
    data, meta = validate_paginated(api_client.list_recall_tasks(
        scn["recall"]["id"], TEST_USERS["compliance_officer_headers"]))
    assert meta["total_count"] == 1
    assert data[0]["status"] == "PENDING"
    assert data[0]["compound_order_id"] == scn["order"]["id"]
    assert data[0]["owner_id"] == scn["owner"]["id"]
    res = api_client.complete_recall(scn["recall"]["id"],
                                     TEST_USERS["compliance_officer_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_recall_task_flow_completes_and_recalls_lot(api):
    """PRD §3.9: "completion moves the recall to `COMPLETED` and moves every
    covered `QUARANTINED` lot to the terminal `RECALLED`."
    PRD §3.9: "The owner acknowledges a `NOTIFIED` task, moving it to the terminal
    `ACKNOWLEDGED`; acknowledgement is ownership-guarded against the task's
    `owner_id`."

    Design: Corner/state_machines/recall_task_flow_and_complete_gate
    """
    scn = _setup_s8()
    get_success_data(api_client.activate_recall(scn["recall"]["id"],
                                                TEST_USERS["compliance_officer_headers"]))
    data, _meta = validate_paginated(api_client.list_recall_tasks(
        scn["recall"]["id"], TEST_USERS["compliance_officer_headers"]))
    task_id = data[0]["id"]
    get_success_data(api_client.mark_task_notified(task_id,
                                                   TEST_USERS["compliance_officer_headers"]))
    get_success_data(api_client.acknowledge_task(
        task_id, make_owner_headers(scn["owner"]["id"])))
    completed = get_success_data(api_client.complete_recall(
        scn["recall"]["id"], TEST_USERS["compliance_officer_headers"]))
    assert completed["status"] == "COMPLETED"
    assert fetch_lot(scn["lot"]["id"])["status"] == "RECALLED"


def test_recall_hold_blocks_action_and_resume(api):
    """PRD §3.9: "While an order sits in `RECALL_HOLD` it rejects every action
    except resume and cancel with `ERR_RECALL_HOLD_ACTIVE` — this hold rejection
    takes precedence over the generic invalid-state rejection for held orders."
    PRD §3.9: "A `Pharmacist` resumes a held order only when no `ACTIVE` recall
    still touches any of its allocated lots (`ERR_RECALL_ACTIVE_ON_LOT`)"

    Design: Corner/validations/recall_hold_blocks_action_and_resume
    """
    scn = setup_verified_scenario(pet_weight_kg=6, quantity=5, days_supply=5)
    lot = create_lot(scn["drug"]["id"], received_qty=50, unit_cost_cents=100)
    order = create_compound_order(scn["rx"]["id"],
                                  expected_prescription_version=scn["rx_version"])
    allocate_order(order["id"])
    recall = get_success_data(api_client.create_recall(
        create_recall_payload(scope="LOT", lot_id=lot["id"], reason="potency",
                              severity="CLASS_III"),
        TEST_USERS["compliance_officer_headers"]))
    get_success_data(api_client.activate_recall(recall["id"],
                                                TEST_USERS["compliance_officer_headers"]))
    held = fetch_compound_order(order["id"])
    assert held["status"] == "RECALL_HOLD"
    assert held["hold_origin_state"] == "ALLOCATED"
    res1 = api_client.qa_pass(order["id"], TEST_USERS["pharmacist_b_headers"])
    validate_error(res1, ApiErrorId.ERR_RECALL_HOLD_ACTIVE)
    res2 = api_client.resume_order(order["id"], TEST_USERS["pharmacist_a_headers"])
    validate_error(res2, ApiErrorId.ERR_RECALL_ACTIVE_ON_LOT)
    still = fetch_compound_order(order["id"])
    assert still["status"] == "RECALL_HOLD"
    assert still["hold_origin_state"] == "ALLOCATED"
