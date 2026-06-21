"""Optimistic-concurrency guards, endpoint side effects, immediate consistency.

Corner queue: cross_cutting_complexity_layers (OCC) + endpoints + consistency_model.
"""
from test_helpers import validate_success, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    publish_price,
    register_seller,
    stage_container,
    open_ticket,
    add_line,
    create_weighed_ticket,
    open_hedge,
    create_shipped_shipment,
    dispatch_container,
    WM, YM, SA,
)
from test_helpers.api_client import api_client


# ---- OCC: container dispatch ----
def test_dispatch_stale_container_version_rejected(api):
    """PRD §2.7: "A dispatch arriving with the pre-load version is therefore acting
    on a stale view of the container's capacity and is rejected with
    `ERR_STALE_CONTAINER_VERSION` (HTTP 412); the dispatch does not occur."

    A version captured before a release bumped the container is stale at dispatch.

    Design: Corner/cross_cutting_complexity_layers/dispatch_stale_container_version_rejected
    """
    publish_price("SHRED_STEEL", "FERROUS", spot=11, mill=14)
    seller = register_seller(legal_name="OCC Co", id_type="STATE_ID", id_number="SID-OCC")
    container = stage_container("FERROUS", capacity_lb=5000)
    stale_version = container["version"]  # observed BEFORE the release bumps it
    ticket = open_ticket(seller["id"], gross_weight_lb=1500)
    add_line(ticket["id"], "SHRED_STEEL", 100)
    validate_success(api.weigh_out(ticket["id"], {"tare_weight_lb": 200}, WM))
    validate_success(api.release_ticket(ticket["id"], {"container_id": container["id"]}, WM))
    resp = api.dispatch_container(
        container["id"], {"expected_container_version": stale_version}, YM)
    validate_error(resp, ApiErrorId.ERR_STALE_CONTAINER_VERSION.value)
    after = validate_success(api.get_container(container["id"], YM))
    assert after["status"] == "STAGED", f"container must stay STAGED, got {after['status']}"


def test_dispatch_succeeds_with_current_container_version(api):
    """PRD §2.7: "Only when `expected_container_version` equals the container's
    current `version` does the dispatch proceed."
    PRD §3.6: "A successful dispatch takes the container off the staging line, makes
    it eligible for a mill shipment, and increments the container's `version`."

    Dispatching with the version observed after the load succeeds and moves to DISPATCHED.

    Design: Corner/cross_cutting_complexity_layers/container_version_increments_on_dispatch
    """
    publish_price("SHRED_STEEL", "FERROUS", spot=11, mill=14)
    seller = register_seller(legal_name="VInc Co", id_type="STATE_ID", id_number="SID-VI")
    container = stage_container("FERROUS", capacity_lb=5000)
    ticket = open_ticket(seller["id"], gross_weight_lb=1500)
    add_line(ticket["id"], "SHRED_STEEL", 100)
    validate_success(api.weigh_out(ticket["id"], {"tare_weight_lb": 200}, WM))
    validate_success(api.release_ticket(ticket["id"], {"container_id": container["id"]}, WM))
    current = validate_success(api.get_container(container["id"], YM))
    data = validate_success(
        api.dispatch_container(
            container["id"], {"expected_container_version": current["version"]}, YM)
    )
    assert data["status"] == "DISPATCHED", f"expected DISPATCHED, got {data['status']}"
    assert data["version"] == current["version"] + 1, \
        f"dispatch must increment version from {current['version']}, got {data['version']}"


# ---- OCC: shipment settle against a hedge ----
def test_settle_stale_hedge_version_rejected(api):
    """PRD §2.7: "A settlement arriving with the stale hedge version is rejected with
    `ERR_STALE_HEDGE_VERSION` (HTTP 412), so it cannot over-realize a position whose
    capacity has already been consumed."

    Shipment B carries the hedge version observed before shipment A's settlement
    advanced it.

    Design: Corner/cross_cutting_complexity_layers/settle_stale_hedge_version_rejected
    """
    publish_price("SHRED_STEEL", "FERROUS", spot=11, mill=14)
    seller = register_seller(legal_name="OCC2 Co", id_type="STATE_ID", id_number="SID-OCC2")
    hedge = open_hedge(category="FERROUS", hedged_weight_lb=5000, locked_price=90)
    stale_hedge_version = hedge["version"]  # observed before any realization
    # Shipment A realizes against the hedge, advancing its version.
    ship_a = create_shipped_shipment(
        grade_code="SHRED_STEEL", category="FERROUS", spot=11, mill=14,
        weight_lb=100, gross_weight_lb=1000, tare_weight_lb=400,
        capacity_lb=5000, hedge_id=hedge["id"],
    )
    validate_success(
        api.settle_mill_shipment(
            ship_a["shipment"]["id"],
            {"final_settlement_cents": 50000, "expected_hedge_version": stale_hedge_version},
            SA,
        )
    )
    # Shipment B carries the now-stale pre-realization hedge version.
    ship_b = create_shipped_shipment(
        grade_code="SHRED_STEEL", category="FERROUS", spot=11, mill=14,
        weight_lb=100, gross_weight_lb=1000, tare_weight_lb=400,
        capacity_lb=5000, hedge_id=hedge["id"],
    )
    resp = api.settle_mill_shipment(
        ship_b["shipment"]["id"],
        {"final_settlement_cents": 50000, "expected_hedge_version": stale_hedge_version},
        SA,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_HEDGE_VERSION.value)
    after = validate_success(api.get_mill_shipment(ship_b["shipment"]["id"], SA))
    assert after["status"] == "SHIPPED", f"shipment B must stay SHIPPED, got {after['status']}"


# ---- endpoints: side effects + reverse reachability ----
def test_release_loads_container_weight_side_effect(api):
    """PRD §3.4: "On a successful release the ticket is assigned to the container and
    the container's `loaded_weight_lb` increases by the ticket's `net_weight_lb`."

    Releasing a net-1300 ticket raises loaded_weight_lb from 0 to 1300.

    Design: Corner/endpoints/release_loads_container_weight_side_effect
    """
    built = create_weighed_ticket(grade_code="SHRED_STEEL", category="FERROUS",
                                  spot=11, mill=14, weight_lb=100)
    container = stage_container("FERROUS", capacity_lb=5000)
    data = validate_success(
        api.release_ticket(built["ticket"]["id"], {"container_id": container["id"]}, WM)
    )
    assert data["status"] == "RELEASED", f"expected RELEASED, got {data['status']}"
    cont_after = validate_success(api.get_container(container["id"], YM))
    assert cont_after["loaded_weight_lb"] == 1300, \
        f"expected loaded_weight_lb 1300, got {cont_after['loaded_weight_lb']}"


def test_get_ticket_line_items_reverse_reachability(api):
    """PRD §2.6: "Detail and list reads are available for every resource, including
    reverse lookups: the line items of a ticket and the line items referencing a
    given commodity price are both reachable".

    GET /yard/tickets/{id}/line-items returns the ticket's two line items.

    Design: Corner/endpoints/get_ticket_line_items_reverse_reachability
    """
    publish_price("CU_BARE_BRIGHT", "NON_FERROUS", spot=375, mill=410)
    seller = register_seller(legal_name="RR Co", id_type="STATE_ID", id_number="SID-RR")
    ticket = open_ticket(seller["id"], gross_weight_lb=1500)
    add_line(ticket["id"], "CU_BARE_BRIGHT", 5)
    add_line(ticket["id"], "CU_BARE_BRIGHT", 7)
    rows, meta = validate_paginated(api.list_ticket_line_items(ticket["id"], WM))
    assert meta["total_count"] == 2, f"expected 2 line items, got {meta['total_count']}"
    assert len(rows) == 2, f"expected 2 rows, got {len(rows)}"


# ---- consistency model ----
def test_gross_valuation_visible_in_same_weighout_response(api):
    """PRD §3.3: "On success the ticket advances `DRAFT → WEIGHED`: the system sets
    `net_weight_lb` ... and freezes `gross_valuation_cents`."
    PRD §2.2: "operations that create or modify a resource will return the created or
    updated resource object in the data field."

    The frozen gross_valuation_cents is present in the weigh-out response body itself.

    Design: Corner/consistency_model/gross_valuation_visible_in_same_weighout_response
    """
    publish_price("SHRED_STEEL", "FERROUS", spot=11, mill=14)
    seller = register_seller(legal_name="Imm2 Co", id_type="STATE_ID", id_number="SID-IM2")
    ticket = open_ticket(seller["id"], gross_weight_lb=1500)
    add_line(ticket["id"], "SHRED_STEEL", 100)
    data = validate_success(api.weigh_out(ticket["id"], {"tare_weight_lb": 200}, WM))
    assert data["gross_valuation_cents"] == 1100, \
        f"gross_valuation_cents must be in the weigh-out response, got {data.get('gross_valuation_cents')}"
