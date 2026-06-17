"""Order lifecycle branches, revision cycle, and multi-hop compensation cascades.

Covers queue A: non_linear_state_machine, transitive_cascade, compensating_invariant;
and queue B: state_machines cascade/side-effect instances (room approval cascade,
blocking-punch freeze).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_client_headers,
    create_vendor_payload,
    create_revision_payload,
    create_punch_item_payload,
    create_moodboard_payload,
    setup_project_with_approved_room,
    create_room,
    create_specified_selection,
    create_placed_order,
    create_delivered_order,
    create_ffe_item,
    add_deposit,
    advance_project_to,
    project_version,
)

ADMIN = TEST_USERS["studio_admin_headers"]
DESIGNER = TEST_USERS["designer_headers"]
PC = TEST_USERS["procurement_coordinator_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — non_linear_state_machine / revision_resubmit_cycle_increments_round_no
# ─────────────────────────────────────────────────────────────────────────────
def _project_in_design_with_changes_requested_revision():
    s = setup_project_with_approved_room()
    pid, rid, cid = s["project"]["id"], s["room"]["id"], s["client"]["id"]
    advance_project_to(pid, "IN_DESIGN", actor=DESIGNER)
    cli = make_client_headers(cid)
    rev = get_success_data(api_client.create_revision(
        pid, create_revision_payload("ROOM", rid, note="change drapes"), cli))
    get_success_data(api_client.submit_revision(rev["id"], cli))
    get_success_data(api_client.request_changes_revision(rev["id"], DESIGNER))
    return s, rev


def test_revision_resubmit_returns_to_submitted(api):
    """PRD §3.7: "The client resubmits a CHANGES_REQUESTED request — again only while
    the project is IN_DESIGN or PROCUREMENT, otherwise ERR_INVALID_STATE — which
    returns it to SUBMITTED, increments the round counter round_no by one to track the
    cycle, and increments the version."

    Design: Difficulty/non_linear_state_machine/revision_resubmit_cycle_increments_round_no
    """
    s, rev = _project_in_design_with_changes_requested_revision()
    cli = make_client_headers(s["client"]["id"])
    resubmitted = validate_success(api.submit_revision(rev["id"], cli), 200)
    assert resubmitted["status"] == "SUBMITTED", resubmitted["status"]


def test_revision_resubmit_increments_round_no(api):
    """PRD §3.7: "which returns it to SUBMITTED, increments the round counter round_no
    by one to track the cycle, and increments the version."
    PRD §3.7: "The request records the project_id of its owning project, starts in
    status DRAFT, and starts with a round_no of one."

    Design: Difficulty/non_linear_state_machine/revision_resubmit_cycle_increments_round_no
    """
    s, rev = _project_in_design_with_changes_requested_revision()
    cli = make_client_headers(s["client"]["id"])
    resubmitted = validate_success(api.submit_revision(rev["id"], cli), 200)
    assert resubmitted["round_no"] == 2, resubmitted["round_no"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — non_linear_state_machine / order_branch_deliver_vs_cancel_divergent_side_effects
# ─────────────────────────────────────────────────────────────────────────────
def _two_placed_orders_flat():
    s = setup_project_with_approved_room()
    pid, rid = s["project"]["id"], s["room"]["id"]
    v1 = s["vendor"]
    v2 = get_success_data(api_client.create_vendor(create_vendor_payload(name="V2", trade="MILLWORK"), PC))
    f1 = create_ffe_item(sku="BR-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=3)
    f2 = create_ffe_item(sku="BR-B", name="Table", category="FURNITURE", list_unit_cost_cents=30000, lead_time_days=3)
    s1 = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    s2 = create_specified_selection(pid, rid, f2["id"], quantity=1, spec_note="b")
    o1 = create_placed_order(pid, v1["id"], [s1["id"]])
    o2 = create_placed_order(pid, v2["id"], [s2["id"]])
    return s, o1, s1, o2, s2


def test_order_ship_branch_keeps_selection_ordered(api):
    """PRD §3.11: "Shipping moves an order from ORDERED to IN_TRANSIT and bumps the
    order's version."
    PRD §3.5: "every selection attached to the order moves from SPECIFIED to ORDERED"

    Design: Difficulty/non_linear_state_machine/order_branch_deliver_vs_cancel_divergent_side_effects
    """
    s, o1, s1, o2, s2 = _two_placed_orders_flat()
    shipped = validate_success(api.ship_order(o1["id"], PC), 200)
    assert shipped["status"] == "IN_TRANSIT", shipped["status"]
    sel1 = validate_success(api.get_selection(s1["id"], ADMIN), 200)
    assert sel1["status"] == "ORDERED", sel1["status"]


def test_order_cancel_branch_reverts_selection_and_recomputes_committed(api):
    """PRD §3.11: "Cancelling moves the order to CANCELLED and runs a compensation
    cascade: every selection attached to the order reverts from ORDERED back to
    SPECIFIED; the project's committed_cents is recomputed (the order having left the
    committed set)"

    Design: Difficulty/non_linear_state_machine/order_branch_deliver_vs_cancel_divergent_side_effects
    """
    s, o1, s1, o2, s2 = _two_placed_orders_flat()
    pid = s["project"]["id"]
    validate_success(api.ship_order(o1["id"], PC), 200)  # O1 -> IN_TRANSIT
    cancelled = validate_success(api.cancel_order(o2["id"], PC), 200)
    assert cancelled["status"] == "CANCELLED", cancelled["status"]
    sel2 = validate_success(api.get_selection(s2["id"], ADMIN), 200)
    assert sel2["status"] == "SPECIFIED", sel2["status"]
    project = validate_success(api.get_project(pid, ADMIN), 200)
    # only O1 (20000) remains committed; O2's 30000 removed.
    assert project["committed_cents"] == 20000, project["committed_cents"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — transitive_cascade / revision_resolve_to_room_rework_to_moodboard_superseded
# ─────────────────────────────────────────────────────────────────────────────
def _project_with_submitted_room_revision_on_approved_room():
    s = setup_project_with_approved_room()
    pid, rid, cid = s["project"]["id"], s["room"]["id"], s["client"]["id"]
    advance_project_to(pid, "IN_DESIGN", actor=DESIGNER)
    cli = make_client_headers(cid)
    rev = get_success_data(api_client.create_revision(
        pid, create_revision_payload("ROOM", rid, note="redo palette"), cli))
    get_success_data(api_client.submit_revision(rev["id"], cli))
    return s, rev


def test_resolve_room_revision_reverts_approved_room_to_rework(api):
    """PRD §3.7: "if the request targeted a room (target_kind is ROOM) and that target
    room is currently APPROVED, resolving triggers the compensation hop described in
    §3.3 — the room reverts from APPROVED to REWORK, which itself cascades the accepted
    board to SUPERSEDED and clears approved_moodboard_id"

    Design: Difficulty/transitive_cascade/revision_resolve_to_room_rework_to_moodboard_superseded
    """
    s, rev = _project_with_submitted_room_revision_on_approved_room()
    resolved = validate_success(api.resolve_revision(rev["id"], DESIGNER), 200)
    assert resolved["status"] == "RESOLVED", resolved["status"]
    room = validate_success(api.get_room(s["room"]["id"], ADMIN), 200)
    assert room["status"] == "REWORK", room["status"]
    assert room["approved_moodboard_id"] is None, room["approved_moodboard_id"]


def test_resolve_room_revision_cascades_accepted_moodboard_to_superseded(api):
    """PRD §3.3: "when a room-targeted revision is resolved against an
    already-approved room, the system itself drives that room from APPROVED back to
    REWORK as a compensation hop: the room's approved_moodboard_id is cleared to null,
    the board that had been accepted is moved to SUPERSEDED, and the room's version
    increments."

    Design: Difficulty/transitive_cascade/revision_resolve_to_room_rework_to_moodboard_superseded
    """
    s, rev = _project_with_submitted_room_revision_on_approved_room()
    validate_success(api.resolve_revision(rev["id"], DESIGNER), 200)
    mb = validate_success(api.get_moodboard(s["moodboard"]["id"], ADMIN), 200)
    assert mb["status"] == "SUPERSEDED", mb["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — transitive_cascade / order_return_to_selection_revert_and_punch_waive
# ─────────────────────────────────────────────────────────────────────────────
def _delivered_order_with_blocking_punch():
    s = setup_project_with_approved_room()
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="RT-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=3)
    sel = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    order = create_delivered_order(pid, vid, [sel["id"]])
    punch = get_success_data(api_client.create_punch_item(
        order["id"], create_punch_item_payload(description="cracked frame", severity="BLOCKING"), PC))
    return s, order, sel, punch


def test_order_return_waives_open_punch_and_reverts_selection(api):
    """PRD §3.11: "Returning moves the order to RETURNED and runs a comparable
    compensation cascade: every attached selection reverts from ORDERED back to
    SPECIFIED; every punch item still OPEN on the order is moved to WAIVED"

    Design: Difficulty/transitive_cascade/order_return_to_selection_revert_and_punch_waive
    """
    s, order, sel, punch = _delivered_order_with_blocking_punch()
    returned = validate_success(api.return_order(order["id"], PC), 200)
    assert returned["status"] == "RETURNED", returned["status"]
    punch_after = validate_success(api.get_punch_item(punch["id"], ADMIN), 200)
    assert punch_after["status"] == "WAIVED", punch_after["status"]
    sel_after = validate_success(api.get_selection(sel["id"], ADMIN), 200)
    assert sel_after["status"] == "SPECIFIED", sel_after["status"]


def test_order_return_removes_order_from_committed_and_lifts_freeze(api):
    """PRD §3.11: "the project's committed_cents, budget_status, and posture are
    recomputed"
    PRD §2.8: "First, the posture is FROZEN if any punch item on any of the project's
    orders is simultaneously in status OPEN and of severity BLOCKING."

    Design: Difficulty/transitive_cascade/order_return_to_selection_revert_and_punch_waive
    """
    s, order, sel, punch = _delivered_order_with_blocking_punch()
    pid = s["project"]["id"]
    before = validate_success(api.get_project(pid, ADMIN), 200)
    assert before["posture"] == "FROZEN", before["posture"]
    validate_success(api.return_order(order["id"], PC), 200)
    after = validate_success(api.get_project(pid, ADMIN), 200)
    assert after["committed_cents"] == 0, after["committed_cents"]
    assert after["posture"] == "OPEN", after["posture"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — compensating_invariant / order_cancel_restores_committed_cents_invariant
# ─────────────────────────────────────────────────────────────────────────────
def test_cancel_restores_committed_cents_to_pre_place_value(api):
    """PRD §3.11: "Cancelling moves the order to CANCELLED and runs a compensation
    cascade: every selection attached to the order reverts from ORDERED back to
    SPECIFIED; the project's committed_cents is recomputed (the order having left the
    committed set)"
    PRD §3.6: "The project's committed_cents is the sum of order_subtotal_cents over
    every procurement order of the project whose status is ORDERED, IN_TRANSIT, or
    DELIVERED."

    Design: Difficulty/compensating_invariant/order_cancel_restores_committed_cents_invariant
    """
    s = setup_project_with_approved_room()
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="CI-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    sel = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    order = create_placed_order(pid, vid, [sel["id"]])
    before = validate_success(api.get_project(pid, ADMIN), 200)
    assert before["committed_cents"] == 20000, before["committed_cents"]
    validate_success(api.cancel_order(order["id"], PC), 200)
    after = validate_success(api.get_project(pid, ADMIN), 200)
    assert after["committed_cents"] == 0, after["committed_cents"]


def test_cancel_reverts_selection_so_it_can_be_reordered(api):
    """PRD §3.11: "every selection attached to the order reverts from ORDERED back to
    SPECIFIED"

    Design: Difficulty/compensating_invariant/order_cancel_restores_committed_cents_invariant
    """
    s = setup_project_with_approved_room()
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="CI-B", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    sel = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    order = create_placed_order(pid, vid, [sel["id"]])
    validate_success(api.cancel_order(order["id"], PC), 200)
    sel_after = validate_success(api.get_selection(sel["id"], ADMIN), 200)
    assert sel_after["status"] == "SPECIFIED", sel_after["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — compensating_invariant / deposit_cancel_conserves_total_allocated_plus_credit
# ─────────────────────────────────────────────────────────────────────────────
def _two_orders_with_full_deposit():
    """O1(64893, first) + O2(40000); deposit 114893 fully allocated (O1=64893, O2=40000, credit=10000)."""
    s = setup_project_with_approved_room()
    pid, rid = s["project"]["id"], s["room"]["id"]
    v1 = s["vendor"]
    v2 = get_success_data(api_client.create_vendor(create_vendor_payload(name="V2", trade="MILLWORK"), PC))
    f1 = create_ffe_item(sku="DC-A", name="Chair", category="FURNITURE", list_unit_cost_cents=12999, lead_time_days=1)
    f2 = create_ffe_item(sku="DC-B", name="Lamp", category="LIGHTING", list_unit_cost_cents=4550, lead_time_days=1)
    f3 = create_ffe_item(sku="DC-C", name="Vase", category="DECOR", list_unit_cost_cents=899, lead_time_days=1)
    f4 = create_ffe_item(sku="DC-D", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    s1 = create_specified_selection(pid, rid, f1["id"], quantity=3, trade_discount_pct=0.125, spec_note="a")
    s2 = create_specified_selection(pid, rid, f2["id"], quantity=7, trade_discount_pct=0.175, spec_note="b")
    s3 = create_specified_selection(pid, rid, f3["id"], quantity=5, trade_discount_pct=0.0, spec_note="c")
    s4 = create_specified_selection(pid, rid, f4["id"], quantity=2, trade_discount_pct=0.0, spec_note="d")
    o1 = create_placed_order(pid, v1["id"], [s1["id"], s2["id"], s3["id"]])  # 64893, created first
    o2 = create_placed_order(pid, v2["id"], [s4["id"]],
                             window_start="2026-08-01T00:00:00Z", window_end="2026-08-02T00:00:00Z")  # 40000
    add_deposit(pid, 114893)
    return s, o1, o2


def test_deposit_waterfall_fills_orders_in_created_order(api):
    """PRD §3.10: "The outstanding orders are those in ORDERED, IN_TRANSIT, or
    DELIVERED status, sorted by their created_at timestamp ascending, with the
    earlier-created order always taking precedence."
    PRD §3.10: "Whatever pool remains after every outstanding order is filled becomes
    the project's client_credit_cents, the unallocated remainder."

    Design: Difficulty/compensating_invariant/deposit_cancel_conserves_total_allocated_plus_credit
    """
    s, o1, o2 = _two_orders_with_full_deposit()
    pid = s["project"]["id"]
    o1_after = validate_success(api.get_order(o1["id"], ADMIN), 200)
    o2_after = validate_success(api.get_order(o2["id"], ADMIN), 200)
    project = validate_success(api.get_project(pid, ADMIN), 200)
    assert o1_after["amount_paid_cents"] == 64893, o1_after["amount_paid_cents"]
    assert o2_after["amount_paid_cents"] == 40000, o2_after["amount_paid_cents"]
    assert project["client_credit_cents"] == 10000, project["client_credit_cents"]


def test_cancel_releases_allocation_back_to_client_credit(api):
    """PRD §3.11: "any deposit money previously allocated to this order is released
    back into the project's client_credit_cents by re-running the deposit waterfall
    over the new outstanding set"
    PRD §3.10: "Any order not in the outstanding set has an amount_paid_cents of zero."

    Design: Difficulty/compensating_invariant/deposit_cancel_conserves_total_allocated_plus_credit
    """
    s, o1, o2 = _two_orders_with_full_deposit()
    pid = s["project"]["id"]
    validate_success(api.cancel_order(o2["id"], PC), 200)
    o1_after = validate_success(api.get_order(o1["id"], ADMIN), 200)
    project = validate_success(api.get_project(pid, ADMIN), 200)
    assert o1_after["amount_paid_cents"] == 64893, o1_after["amount_paid_cents"]
    # O2's 40000 released; credit = 10000 + 40000 = 50000.
    assert project["client_credit_cents"] == 50000, project["client_credit_cents"]
    # Conservation: sum(amount_paid over live orders) + credit == 114893.
    assert o1_after["amount_paid_cents"] + project["client_credit_cents"] == 114893


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — state_machines / room_approve_cascades_sibling_moodboards_superseded
# ─────────────────────────────────────────────────────────────────────────────
def test_room_approve_accepts_presented_and_supersedes_siblings(api):
    """PRD §3.3: "approval moves the room to APPROVED, transitions that single
    presented board to ACCEPTED, supersedes every other board for the room that was
    in DRAFT or PRESENTED (moving each to SUPERSEDED), sets approved_moodboard_id to
    the id of the newly accepted board, and increments the room's version."

    Design: Corner/state_machines/room_approve_cascades_sibling_moodboards_superseded
    """
    # Build a MOODBOARD_READY room with one PRESENTED + one DRAFT sibling board.
    from test_helpers import create_client, create_project
    client = create_client()
    project = create_project(client["id"])
    room = create_room(project["id"], name="R1")
    mb1 = get_success_data(api.create_moodboard(room["id"], create_moodboard_payload(title="mb1"), DESIGNER))
    mb2 = get_success_data(api.create_moodboard(room["id"], create_moodboard_payload(title="mb2"), DESIGNER))
    get_success_data(api.present_moodboard(mb1["id"], DESIGNER))
    get_success_data(api.present_moodboard_room(room["id"], DESIGNER))
    approved = validate_success(api.approve_room(room["id"], make_client_headers(client["id"])), 200)
    assert approved["status"] == "APPROVED"
    assert approved["approved_moodboard_id"] == mb1["id"], approved["approved_moodboard_id"]
    mb1_after = validate_success(api.get_moodboard(mb1["id"], ADMIN), 200)
    mb2_after = validate_success(api.get_moodboard(mb2["id"], ADMIN), 200)
    assert mb1_after["status"] == "ACCEPTED", mb1_after["status"]
    assert mb2_after["status"] == "SUPERSEDED", mb2_after["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — state_machines / blocking_punch_item_freezes_project_posture
# ─────────────────────────────────────────────────────────────────────────────
def test_blocking_punch_freezes_then_resolve_lifts_posture(api):
    """PRD §3.12: "because a BLOCKING item that is OPEN is the highest-priority freeze
    condition, logging a blocking defect drives the project to FROZEN."
    PRD §3.12: "A procurement coordinator resolves an item, moving it from OPEN to
    RESOLVED; the resolution recomputes the project's posture, and clearing the last
    open blocking item may be what lifts a FROZEN posture."

    Design: Corner/state_machines/blocking_punch_item_freezes_project_posture
    """
    s = setup_project_with_approved_room()
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="FZ-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    sel = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    order = create_delivered_order(pid, vid, [sel["id"]])
    punch = get_success_data(api.create_punch_item(
        order["id"], create_punch_item_payload(description="broken leg", severity="BLOCKING"), PC))
    before = validate_success(api.get_project(pid, ADMIN), 200)
    assert before["posture"] == "FROZEN", before["posture"]
    resolved = validate_success(api.resolve_punch_item(punch["id"], PC), 200)
    assert resolved["status"] == "RESOLVED", resolved["status"]
    after = validate_success(api.get_project(pid, ADMIN), 200)
    assert after["posture"] == "OPEN", after["posture"]
