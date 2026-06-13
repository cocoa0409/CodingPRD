"""Endpoint-level role exclusivity and list-envelope behavior.

Queue B (Corner): rbac/* (exclusive-operation denial) and endpoints/* (list envelopes).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_venue, create_product, create_transfer_payload, create_inventory_lot_payload,
)
from test_helpers.fixtures import (
    create_event, create_stand, setup_two_stands_one_event, setup_paid_order,
    create_lot, current_stand_version,
)

MANAGER = TEST_USERS["manager_headers"]
RUNNER = TEST_USERS["runner_headers"]
OPERATOR = TEST_USERS["operator_headers"]


# ===========================================================================
# Queue B — rbac
# ===========================================================================
def test_stand_operator_cannot_dispatch_transfer(api):
    """PRD §2.1: "A StockRunner moves inventory — initial stocking, replenishment
    picking and delivery, transfers between stands, expiry sweeps, and waste
    logging."
    PRD §4 (POST /concessions/transfers/{id}/dispatch authorized role): "StockRunner".

    A StandOperator calling the StockRunner-exclusive dispatch -> ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/standoperator_cannot_dispatch_transfer
    """
    base = setup_two_stands_one_event(source_lot_qty=100, lot_unit_cost=30)
    transfer = validate_success(api.create_transfer(create_transfer_payload(
        base["stand_a"]["id"], base["stand_b"]["id"], base["product"]["id"], qty=10), RUNNER), 201)
    sa_v = validate_success(api.get_stand(base["stand_a"]["id"], RUNNER), 200)["version"]
    resp = api.dispatch_transfer(transfer["id"], {"expected_from_stand_version": sa_v}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_concessions_manager_cannot_ready_order(api):
    """PRD §2.1: "A StandOperator runs an individual stand, opening, suspending, and
    closing it, readying and handing off order pickups, and checking staff shifts in
    and out."
    PRD §4 (POST /concessions/orders/{id}/ready authorized role): "StandOperator".

    A ConcessionsManager calling the StandOperator-exclusive ready -> ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/concessionsmanager_cannot_ready_order
    """
    state = setup_paid_order(
        line_qtys=(1,),
        product_overrides={"sku": "WATER", "name": "Water", "base_price_cents": 100, "unit_cost_cents": 10},
    )
    sv = current_stand_version(state["stand"]["id"])
    resp = api.ready_order(state["order"]["id"], {"expected_stand_version": sv}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


# ===========================================================================
# Queue B — endpoints (list envelopes / pagination)
# ===========================================================================
def test_list_event_stands_returns_paginated_envelope(api):
    """PRD §2.3: "Every list-style response carries the pagination fields limit,
    offset, total_count, and has_more inside the envelope's meta object, where
    total_count is the number of matching resources before pagination and has_more
    indicates whether further items remain beyond the current page."

    Two stands under one event -> total_count 2, has_more false at the default limit.

    Design: Corner/endpoints/list_event_stands_paginated_envelope
    """
    venue = create_venue()
    event = create_event(venue["id"])
    create_stand(event["id"], name="S26a")
    create_stand(event["id"], name="S26b")
    resp = api.list_event_stands(event["id"], MANAGER)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False


def test_list_waste_records_filtered_by_lot(api):
    """PRD §3.5: "a waste record with reason EXPIRY is created for the lot's
    remaining units (costed per the venue's spoilage policy, §3.6)".
    PRD §4 (GET /concessions/waste-records): "List waste records, filterable by
    stand, product, or lot".

    Expiring a 30-unit @30c lot creates one EXPIRY waste record (cost 900) findable
    via the lot_id filter.

    Design: Corner/endpoints/list_waste_records_filtered_by_lot
    """
    venue = create_venue()
    product = create_product(venue["id"], sku="BUN", name="Bun", base_price_cents=0, unit_cost_cents=30, perishable=True)
    api.set_clock("2026-07-27T17:00:00.000Z", MANAGER)
    event = create_event(venue["id"])
    stand = create_stand(event["id"])
    lot = create_lot(stand["id"], product["id"], received_qty=30, unit_cost_cents=30,
                     par_level=60, reorder_point=10, expires_at="2026-07-27T19:00:00.000Z")
    api.set_clock("2026-07-27T20:00:00.000Z", MANAGER)
    validate_success(api.expire_lots(stand["id"], RUNNER), 200)
    resp = api.list_waste_records(RUNNER, params={"lot_id": lot["id"]})
    data, _meta = validate_paginated(resp)
    matching = [w for w in data if w.get("lot_id") == lot["id"]]
    assert len(matching) == 1, f"expected one EXPIRY waste record for the lot, got {data}"
    assert matching[0]["reason"] == "EXPIRY"
    assert matching[0]["qty"] == 30
    assert matching[0]["cost_cents"] == 900
