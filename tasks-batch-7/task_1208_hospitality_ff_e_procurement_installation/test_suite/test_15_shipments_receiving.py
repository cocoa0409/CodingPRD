"""Queue B (breadth) — shipment lifecycle and receiving-event guards: cancel
compensation, the three-part RECEIVED guard chain, chronological over-receipt,
entry validation, and sealing an empty shipment.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    run_pipeline, create_shipment, transition_shipment,
    advance_po_to_ready_to_ship, create_and_post_receiving_event,
    create_consolidating_shipment_with_po,
    get_po, get_budget_line, get_po_line,
    create_receiving_event_payload,
    create_procurement_project,
    TEST_USERS,
)

PA = TEST_USERS["purchasing_agent_headers"]
WR = TEST_USERS["warehouse_receiver_headers"]

_LINE_40 = {
    "description": "Guest chair", "brand_standard_ref": "MS-GR-01",
    "quantity_per_room": 2, "room_count": 20,
    "unit_budget_cents": 15000, "unit_price_cents": 15000,
    "lead_time_days": 14,
    "quantity_ordered": 40, "declared_cube_m3": 10,
}

_LINE_10 = {
    "description": "Lamp", "brand_standard_ref": "MS-L",
    "quantity_per_room": 1, "room_count": 10,
    "unit_budget_cents": 10000, "unit_price_cents": 10000,
    "lead_time_days": 7,
    "quantity_ordered": 10, "declared_cube_m3": 5,
}


def test_shipment_cancel_detaches_pos_and_seal_from_planned_invalid(api):
    """PRD §3.5: "Any shipment move that is not legal from its current state —
    sealing from `PLANNED`, departing from `CONSOLIDATING`, receiving from
    `SEALED`, or cancelling from `SEALED` — is rejected with
    `ERR_INVALID_SHIPMENT_TRANSITION`."
    PRD §3.5: "Cancellation is available from `PLANNED` or `CONSOLIDATING`; it
    detaches everything: attached POs fall back from `CONSOLIDATED` to
    `READY_TO_SHIP` with their `shipment_id` cleared, `committed_cents` is
    recomputed, and the shipment's `version` bumps."
    The cancel compensates the attach without cancelling the order: the committed
    ledger is unchanged.

    Design: Corner/state_machines/shipment_cancel_detaches_pos_and_seal_from_planned_invalid
    """
    scenario = run_pipeline(
        name="P-S9", budgeted_cents=8_000_000,
        line_specs=[_LINE_40], attach=False, seal=False, depart=False,
    )
    po_id = scenario["po"]["id"]
    advance = scenario["project"]["id"]
    advance_po_to_ready_to_ship(po_id)

    shipment_1 = create_consolidating_shipment_with_po(advance, po_id, "CARR-1")
    shipment_2 = create_shipment(advance, "CARR-2")

    # Seal from PLANNED is an invalid transition.
    res = api_client.transition_shipment(
        shipment_2["id"], {"to_status": "SEALED"}, PA
    )
    validate_error(res, ApiErrorId.ERR_INVALID_SHIPMENT_TRANSITION,
                   expected_status=409)

    cancelled = validate_success(
        api_client.transition_shipment(
            shipment_1["id"], {"to_status": "CANCELLED"}, PA
        ),
        200,
    )
    assert cancelled["status"] == "CANCELLED"

    po_after = get_po(po_id)
    assert po_after["fulfillment_status"] == "READY_TO_SHIP"
    assert po_after["shipment_id"] is None, (
        "cancelling the shipment must clear the attached PO's shipment_id"
    )

    budget_line = get_budget_line(scenario["budget_line"]["id"])
    assert budget_line["committed_cents"] == 600000, (
        "detaching is not cancelling; the committed ledger must not drift"
    )

    # Terminal lockdown: IN_TRANSIT out of CANCELLED is rejected.
    res = api_client.transition_shipment(
        shipment_1["id"], {"to_status": "IN_TRANSIT"}, PA
    )
    validate_error(res, ApiErrorId.ERR_INVALID_SHIPMENT_TRANSITION,
                   expected_status=409)


def test_shipment_receive_guards_chain(api):
    """PRD §3.5: "The shipment must be `IN_TRANSIT` at creation, else
    `ERR_SHIPMENT_NOT_IN_TRANSIT`, and every entry's line must belong to a PO
    attached to that shipment, else `ERR_LINE_NOT_ON_SHIPMENT`."
    PRD §3.5: "It requires at least one posted receiving event on the shipment
    (else `ERR_NO_RECEIPTS_POSTED`) and no receiving event still in `DRAFT` (else
    `ERR_DRAFT_EVENTS_OUTSTANDING`)."
    The three guards are exercised in isolated scenarios: event creation while
    SEALED; RECEIVED with zero events; RECEIVED with a DRAFT event outstanding
    while a POSTED event already exists.

    Design: Corner/endpoints/shipment_receive_guards_chain
    """
    scenario = run_pipeline(
        name="P-N4", budgeted_cents=8_000_000,
        line_specs=[_LINE_10], seal=True, depart=False,
    )
    shipment_id = scenario["shipment"]["id"]
    line_id = scenario["lines"][0]["id"]

    # Guard 1: receiving-event creation while the shipment is only SEALED.
    res = api_client.create_receiving_event(
        create_receiving_event_payload(
            shipment_id,
            [{"po_line_id": line_id, "qty_received": 5, "qty_damaged": 0}],
        ),
        WR,
    )
    validate_error(res, ApiErrorId.ERR_SHIPMENT_NOT_IN_TRANSIT,
                   expected_status=409)

    transition_shipment(shipment_id, "IN_TRANSIT")

    # Guard 2: RECEIVED with no receiving events at all.
    res = api_client.transition_shipment(
        shipment_id, {"to_status": "RECEIVED"}, PA
    )
    validate_error(res, ApiErrorId.ERR_NO_RECEIPTS_POSTED, expected_status=409)

    # Guard 3: a POSTED event exists, but a DRAFT event is still outstanding.
    create_and_post_receiving_event(
        shipment_id,
        [{"po_line_id": line_id, "qty_received": 5, "qty_damaged": 0}],
    )
    draft = validate_success(
        api_client.create_receiving_event(
            create_receiving_event_payload(
                shipment_id,
                [{"po_line_id": line_id, "qty_received": 5, "qty_damaged": 0}],
            ),
            WR,
        ),
        201,
    )
    assert draft["status"] == "DRAFT"
    res = api_client.transition_shipment(
        shipment_id, {"to_status": "RECEIVED"}, PA
    )
    validate_error(res, ApiErrorId.ERR_DRAFT_EVENTS_OUTSTANDING,
                   expected_status=409)

    # All guards satisfied: posting the draft event unlocks receipt.
    validate_success(
        api_client.transition_receiving_event(
            draft["id"], {"to_status": "POSTED"}, WR
        ),
        200,
    )
    received = validate_success(
        api_client.transition_shipment(
            shipment_id, {"to_status": "RECEIVED"}, PA
        ),
        200,
    )
    assert received["status"] == "RECEIVED"
    assert get_po(scenario["po"]["id"])["fulfillment_status"] == "DELIVERED"


def test_receiving_over_receipt_chronological(api):
    """PRD §3.5: "Posting the event — `DRAFT` to `POSTED` — re-checks that the
    shipment is `IN_TRANSIT` and applies two per-entry guards: the cumulative
    `qty_received` over already-posted events for the line plus the new
    `qty_received` must not exceed the line's `quantity_ordered` (else
    `ERR_OVER_RECEIPT`, 422), and `qty_damaged` must not exceed `qty_received`
    within the entry (else `ERR_DAMAGE_EXCEEDS_RECEIPT`, 422)."
    PRD §3.4: "from `OPEN` to `PARTIALLY_RECEIVED` when a posted event leaves the
    cumulative `qty_received` below `quantity_ordered`, and to `FULLY_RECEIVED`
    when it reaches it exactly; a later post moves `PARTIALLY_RECEIVED` to
    `FULLY_RECEIVED`."
    Receipts of 7 then 3 reach exactly the 10 ordered; an interleaved 4 (7 + 4 >
    10) is rejected without disturbing the accumulator.

    Design: Corner/calculations/receiving_over_receipt_chronological
    """
    scenario = run_pipeline(
        name="P-C2", budgeted_cents=8_000_000,
        line_specs=[_LINE_10], seal=True, depart=True,
        receipts=[[(0, 7, 0)]],
    )
    shipment_id = scenario["shipment"]["id"]
    line_id = scenario["lines"][0]["id"]

    line = get_po_line(line_id)
    assert line["qty_received"] == 7
    assert line["status"] == "PARTIALLY_RECEIVED"

    over = validate_success(
        api_client.create_receiving_event(
            create_receiving_event_payload(
                shipment_id,
                [{"po_line_id": line_id, "qty_received": 4, "qty_damaged": 0}],
            ),
            WR,
        ),
        201,
    )
    res = api_client.transition_receiving_event(
        over["id"], {"to_status": "POSTED"}, WR
    )
    validate_error(res, ApiErrorId.ERR_OVER_RECEIPT, expected_status=422)
    over_after = validate_success(api_client.get_receiving_event(over["id"], WR))
    assert over_after["status"] == "DRAFT", (
        "the rejected post must leave the event in DRAFT"
    )

    create_and_post_receiving_event(
        shipment_id,
        [{"po_line_id": line_id, "qty_received": 3, "qty_damaged": 0}],
    )
    line = get_po_line(line_id)
    assert line["qty_received"] == 10
    assert line["status"] == "FULLY_RECEIVED"


def test_receiving_entry_guards(api):
    """PRD §3.5: "Creation names the `shipment_id` and a `lines` array whose
    entries each carry a `po_line_id`, a `qty_received` of at least 1, and a
    `qty_damaged` of at least 0 and no more than that entry's `qty_received`."
    PRD §3.5: "An event transition that is not legal from its current state —
    re-posting, or reversing from `DRAFT` — fails with
    `ERR_INVALID_EVENT_TRANSITION`."
    An entry with qty_damaged 5 over qty_received 4 is rejected with
    ERR_DAMAGE_EXCEEDS_RECEIPT (at creation or at posting — PRD names the error
    only for the posting guard); a valid event posts exactly once and the
    re-post is rejected without double-applying.

    Design: Corner/errors/receiving_entry_guards
    """
    scenario = run_pipeline(
        name="P-R8", budgeted_cents=8_000_000,
        line_specs=[_LINE_10], seal=True, depart=True,
    )
    shipment_id = scenario["shipment"]["id"]
    line_id = scenario["lines"][0]["id"]

    # The damage bound (qty_damaged 5 over qty_received 4) must be enforced with
    # ERR_DAMAGE_EXCEEDS_RECEIPT. PRD states the constraint in the creation
    # sentence but names the error only at posting ("Posting the event ...
    # applies two per-entry guards ... else ERR_DAMAGE_EXCEEDS_RECEIPT, 422"),
    # so the guard may fire at either point; both enforcements are faithful.
    res = api_client.create_receiving_event(
        create_receiving_event_payload(
            shipment_id,
            [{"po_line_id": line_id, "qty_received": 4, "qty_damaged": 5}],
        ),
        WR,
    )
    if res.json().get("response_type") == "error":
        validate_error(res, ApiErrorId.ERR_DAMAGE_EXCEEDS_RECEIPT,
                       expected_status=422)
        events, meta = validate_paginated(
            api_client.list_shipment_receiving_events(shipment_id, PA)
        )
        assert events == [] and meta["total_count"] == 0, (
            "the malformed entry must not persist a receiving event"
        )
    else:
        bad_event = validate_success(res, 201)
        res = api_client.transition_receiving_event(
            bad_event["id"], {"to_status": "POSTED"}, WR
        )
        validate_error(res, ApiErrorId.ERR_DAMAGE_EXCEEDS_RECEIPT,
                       expected_status=422)
        after = validate_success(api_client.get_receiving_event(bad_event["id"], WR))
        assert after["status"] == "DRAFT", (
            "the rejected post must leave the event in DRAFT"
        )

    event = validate_success(
        api_client.create_receiving_event(
            create_receiving_event_payload(
                shipment_id,
                [{"po_line_id": line_id, "qty_received": 4, "qty_damaged": 1}],
            ),
            WR,
        ),
        201,
    )
    validate_success(
        api_client.transition_receiving_event(
            event["id"], {"to_status": "POSTED"}, WR
        ),
        200,
    )
    res = api_client.transition_receiving_event(
        event["id"], {"to_status": "POSTED"}, WR
    )
    validate_error(res, ApiErrorId.ERR_INVALID_EVENT_TRANSITION,
                   expected_status=409)

    line = get_po_line(line_id)
    assert line["qty_received"] == 4, "no double application of the posted event"
    assert line["qty_damaged_unresolved"] == 1


def test_seal_empty_shipment_rejected(api):
    """PRD §3.5: "Sealing the shipment — `CONSOLIDATING` to `SEALED` — requires at
    least one attached PO (else `ERR_SHIPMENT_EMPTY`)"
    PRD §2.11: "Both `freight_mode` and `freight_total_cents` remain null until
    the shipment is sealed."

    Design: Corner/state_machines/seal_empty_shipment_rejected
    """
    base = create_procurement_project(
        name="P-S19", total_budget_cents=5_000_000, category="FREIGHT",
        budgeted_cents=1_000_000,
    )
    shipment = create_shipment(base["project"]["id"], "CARR")
    transition_shipment(shipment["id"], "CONSOLIDATING")

    res = api_client.transition_shipment(
        shipment["id"], {"to_status": "SEALED"}, PA
    )
    validate_error(res, ApiErrorId.ERR_SHIPMENT_EMPTY, expected_status=409)

    after = validate_success(api_client.get_shipment(shipment["id"], PA))
    assert after["status"] == "CONSOLIDATING"
    assert after["freight_mode"] is None
    assert after["freight_total_cents"] is None
