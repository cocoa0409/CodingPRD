"""State-machine legality, terminal lockdown, transition preconditions, and
list-filter / lifecycle endpoint behavior.

Covers queue B: state_machines instances (invalid transitions, precondition
enforcement, terminal lockdown) and endpoints instances (vendor filter, hold/resume).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    make_client_headers,
    create_vendor_payload,
    create_order_payload,
    create_moodboard_payload,
    create_punch_item_payload,
    setup_project_with_approved_room,
    create_room,
    create_specified_selection,
    create_placed_order,
    create_delivered_order,
    create_ffe_item,
    create_client,
    create_project,
    create_vendor,
    advance_project_to,
    project_version,
)

ADMIN = TEST_USERS["studio_admin_headers"]
DESIGNER = TEST_USERS["designer_headers"]
PC = TEST_USERS["procurement_coordinator_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — state_machines / place_already_ordered_order_returns_invalid_state
# ─────────────────────────────────────────────────────────────────────────────
def test_place_already_ordered_order_returns_invalid_state(api):
    """PRD §3.5: "Placing the order is the pivotal commitment, performed by a
    procurement coordinator and legal only from DRAFT."
    PRD §2.6: "the system evaluate state-machine legality (rejecting an illegal
    transition for the resource's current state with ERR_INVALID_STATE)"

    Design: Corner/state_machines/place_already_ordered_order_returns_invalid_state
    """
    s = setup_project_with_approved_room()
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="IV-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    sel = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    order = create_placed_order(pid, vid, [sel["id"]])  # now ORDERED
    validate_success(api.ship_order(order["id"], PC), 200)  # -> IN_TRANSIT
    pv = project_version(pid)
    res = api.place_order(order["id"], {"expected_project_version": pv}, PC)
    validate_error(res, "ERR_INVALID_STATE")


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — state_machines / present_second_moodboard_when_one_already_presented_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_present_second_moodboard_when_one_already_presented_rejected(api):
    """PRD §3.3: "A designer presents a draft board, moving it to PRESENTED and
    bumping its version, but only when no other board for the same room is already
    presented; if another board for the room is already in PRESENTED, the request is
    rejected with ERR_MOODBOARD_ALREADY_PRESENTED."

    Design: Corner/state_machines/present_second_moodboard_when_one_already_presented_rejected
    """
    client = create_client(email="ha.c1@x.com")
    project = create_project(client["id"], client_name="Ha", budget_cents=10000000)
    room = create_room(project["id"], name="R1")
    mb1 = get_success_data(api.create_moodboard(room["id"], create_moodboard_payload(title="mb1"), DESIGNER))
    mb2 = get_success_data(api.create_moodboard(room["id"], create_moodboard_payload(title="mb2"), DESIGNER))
    validate_success(api.present_moodboard(mb1["id"], DESIGNER), 200)
    res = api.present_moodboard(mb2["id"], DESIGNER)
    validate_error(res, "ERR_MOODBOARD_ALREADY_PRESENTED")
    mb2_after = validate_success(api.get_moodboard(mb2["id"], ADMIN), 200)
    assert mb2_after["status"] == "DRAFT", mb2_after["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — state_machines / terminal_order_cancelled_cannot_transition
# ─────────────────────────────────────────────────────────────────────────────
def test_cancelled_order_cannot_be_shipped(api):
    """PRD §3.11: "Both CANCELLED and RETURNED are terminal for the order."
    PRD §3.11: "Shipping moves an order from ORDERED to IN_TRANSIT and bumps the
    order's version."

    Design: Corner/state_machines/terminal_order_cancelled_cannot_transition
    """
    s = setup_project_with_approved_room()
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="TL-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    sel = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    order = create_placed_order(pid, vid, [sel["id"]])
    validate_success(api.cancel_order(order["id"], PC), 200)
    res = api.ship_order(order["id"], PC)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_order(order["id"], ADMIN), 200)
    assert after["status"] == "CANCELLED", after["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — state_machines / close_order_with_open_punch_items_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_close_order_with_open_punch_items_rejected(api):
    """PRD §3.11: "Closing the order moves it from DELIVERED to CLOSED and bumps its
    version, but only when no punch item on the order remains in OPEN; an attempt to
    close over open punch items is rejected with ERR_PUNCH_ITEMS_OPEN."

    Design: Corner/state_machines/close_order_with_open_punch_items_rejected
    """
    s = setup_project_with_approved_room()
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="PO-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    sel = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    order = create_delivered_order(pid, vid, [sel["id"]])
    get_success_data(api.create_punch_item(
        order["id"], create_punch_item_payload(description="scuff", severity="MINOR"), PC))
    res = api.close_order(order["id"], PC)
    validate_error(res, "ERR_PUNCH_ITEMS_OPEN")
    after = validate_success(api.get_order(order["id"], ADMIN), 200)
    assert after["status"] == "DELIVERED", after["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — state_machines / return_delivered_order_without_blocking_punch_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_return_delivered_order_without_blocking_punch_rejected(api):
    """PRD §3.11: "A coordinator may return an order only from DELIVERED, and only when
    the order carries at least one punch item of severity BLOCKING; a return without
    such justification is rejected with ERR_RETURN_NOT_JUSTIFIED."

    Design: Corner/state_machines/return_delivered_order_without_blocking_punch_rejected
    """
    s = setup_project_with_approved_room()
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="RN-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    sel = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    order = create_delivered_order(pid, vid, [sel["id"]])
    get_success_data(api.create_punch_item(
        order["id"], create_punch_item_payload(description="scuff", severity="MINOR"), PC))
    res = api.return_order(order["id"], PC)
    validate_error(res, "ERR_RETURN_NOT_JUSTIFIED")
    after = validate_success(api.get_order(order["id"], ADMIN), 200)
    assert after["status"] == "DELIVERED", after["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — endpoints / fk_reverse_filter_orders_by_vendor
# ─────────────────────────────────────────────────────────────────────────────
def test_list_orders_filtered_by_vendor(api):
    """PRD §4: "GET | /orders | List orders (filter by project_id/vendor_id)"
    PRD §2.2: "The response_type is either "object" for a single resource or "array"
    for a list of resources."

    Design: Corner/endpoints/fk_reverse_filter_orders_by_vendor
    """
    client = create_client(email="fv.c1@x.com")
    project = create_project(client["id"], client_name="Fv", budget_cents=100000000)
    v1 = create_vendor(name="V1", trade="SUPPLIER")
    v2 = create_vendor(name="V2", trade="MILLWORK")
    o1 = get_success_data(api.create_order(project["id"], create_order_payload(v1["id"]), PC))
    get_success_data(api.create_order(project["id"], create_order_payload(v2["id"]), PC))
    data, meta = validate_paginated(api.list_orders(PC, params={"vendor_id": v1["id"]}))
    assert meta["total_count"] == 1, meta["total_count"]
    assert len(data) == 1, len(data)
    assert data[0]["vendor_id"] == v1["id"], data[0]["vendor_id"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — endpoints / hold_then_resume_returns_in_design
# ─────────────────────────────────────────────────────────────────────────────
def test_hold_then_resume_returns_in_design(api):
    """PRD §3.2: "Resuming a held project is also a studio-administrator action and
    always returns the project to IN_DESIGN regardless of which status it occupied
    before the hold, again incrementing the version."

    Design: Corner/endpoints/hold_then_resume_returns_in_design
    """
    s = setup_project_with_approved_room()
    pid = s["project"]["id"]
    advance_project_to(pid, "IN_DESIGN", actor=DESIGNER)
    advance_project_to(pid, "PROCUREMENT", actor=DESIGNER)
    validate_success(api.hold_project(pid, ADMIN), 200)
    resumed = validate_success(api.resume_project(pid, ADMIN), 200)
    assert resumed["status"] == "IN_DESIGN", resumed["status"]
