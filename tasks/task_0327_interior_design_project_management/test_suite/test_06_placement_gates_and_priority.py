"""Order-placement gates, validation precedence, vendor-window geometry, and
cross-entity state dependencies.

Covers queue A: priority_pair_validation_conflict, boundary_precision_check
(empty-order instance), cross_entity_state_dependency, resource_temporal_overlap;
and queue B: validations that guard placement / specify / advance.
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
    create_order_payload,
    create_selection_payload,
    create_room_payload,
    setup_project_with_approved_room,
    create_room,
    create_room_with_presented_moodboard,
    create_specified_selection,
    create_draft_order_with_lines,
    create_placed_order,
    create_delivered_order,
    create_ffe_item,
    advance_project_to,
    project_version,
    create_client,
    create_project,
    create_vendor,
)

ADMIN = TEST_USERS["studio_admin_headers"]
DESIGNER = TEST_USERS["designer_headers"]
PC = TEST_USERS["procurement_coordinator_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — priority_pair_validation_conflict / frozen_beats_budget_gate_on_place
# ─────────────────────────────────────────────────────────────────────────────
def test_frozen_posture_beats_budget_gate_on_place(api):
    """PRD §3.5: "The posture gate is checked next: a FROZEN posture surfaces as
    ERR_PROJECT_FROZEN and an AMBER-driven BUDGET_REVIEW posture surfaces as
    ERR_BUDGET_GATE"
    PRD §2.8: "First, the posture is FROZEN if any punch item on any of the project's
    orders is simultaneously in status OPEN and of severity BLOCKING. Second, failing
    that, the posture is FROZEN if the project's budget_status is RED. Third, the
    posture is BUDGET_REVIEW if the budget_status is AMBER."

    Design: Difficulty/priority_pair_validation_conflict/frozen_beats_budget_gate_on_place
    """
    # budget=100000, flat_fee=15108; delivered order subtotal 64893 -> util 0.80001 (AMBER)
    # AND that order carries an OPEN BLOCKING punch (FROZEN). FROZEN must win.
    s = setup_project_with_approved_room(
        fee_overrides={"fee_model": "FLAT", "flat_fee_cents": 15108, "budget_cents": 100000})
    pid, rid = s["project"]["id"], s["room"]["id"]
    v1 = s["vendor"]
    v2 = create_vendor(name="V2", trade="MILLWORK")
    f1 = create_ffe_item(sku="FB-A", name="Chair", category="FURNITURE", list_unit_cost_cents=12999, lead_time_days=1)
    f2 = create_ffe_item(sku="FB-B", name="Lamp", category="LIGHTING", list_unit_cost_cents=4550, lead_time_days=1)
    f3 = create_ffe_item(sku="FB-C", name="Vase", category="DECOR", list_unit_cost_cents=899, lead_time_days=1)
    f4 = create_ffe_item(sku="FB-D", name="Rug", category="TEXTILE", list_unit_cost_cents=5000, lead_time_days=1)
    s1 = create_specified_selection(pid, rid, f1["id"], quantity=3, trade_discount_pct=0.125, spec_note="a")
    s2 = create_specified_selection(pid, rid, f2["id"], quantity=7, trade_discount_pct=0.175, spec_note="b")
    s3 = create_specified_selection(pid, rid, f3["id"], quantity=5, trade_discount_pct=0.0, spec_note="c")
    s4 = create_specified_selection(pid, rid, f4["id"], quantity=1, trade_discount_pct=0.0, spec_note="d")
    o1 = create_delivered_order(pid, v1["id"], [s1["id"], s2["id"], s3["id"]])
    get_success_data(api.create_punch_item(
        o1["id"], {"description": "broken", "severity": "BLOCKING"}, PC))
    project = validate_success(api.get_project(pid, ADMIN), 200)
    assert project["budget_status"] == "AMBER", project["budget_status"]
    assert project["posture"] == "FROZEN", project["posture"]
    # Second DRAFT order ready to place.
    o2 = create_draft_order_with_lines(pid, v2["id"], [s4["id"]],
                                       window_start="2026-09-01T00:00:00Z",
                                       window_end="2026-09-02T00:00:00Z")
    pv = project_version(pid)
    res = api.place_order(o2["id"], {"expected_project_version": pv}, PC)
    validate_error(res, "ERR_PROJECT_FROZEN")


def test_amber_only_budget_review_gates_place_with_budget_gate(api):
    """PRD §3.8: "An AMBER status drives the posture to BUDGET_REVIEW, which blocks the
    placement of new orders with ERR_BUDGET_GATE."

    This is the contrast case for the frozen/budget priority pair: with AMBER but NO
    blocking punch item, the gate that fires is ERR_BUDGET_GATE (not ERR_PROJECT_FROZEN).

    Design: Difficulty/priority_pair_validation_conflict/frozen_beats_budget_gate_on_place
    """
    s = setup_project_with_approved_room(
        fee_overrides={"fee_model": "FLAT", "flat_fee_cents": 15108, "budget_cents": 100000})
    pid, rid = s["project"]["id"], s["room"]["id"]
    v1 = s["vendor"]
    v2 = create_vendor(name="V2", trade="MILLWORK")
    f1 = create_ffe_item(sku="AG-A", name="Chair", category="FURNITURE", list_unit_cost_cents=12999, lead_time_days=1)
    f2 = create_ffe_item(sku="AG-B", name="Lamp", category="LIGHTING", list_unit_cost_cents=4550, lead_time_days=1)
    f3 = create_ffe_item(sku="AG-C", name="Vase", category="DECOR", list_unit_cost_cents=899, lead_time_days=1)
    f4 = create_ffe_item(sku="AG-D", name="Rug", category="TEXTILE", list_unit_cost_cents=5000, lead_time_days=1)
    s1 = create_specified_selection(pid, rid, f1["id"], quantity=3, trade_discount_pct=0.125, spec_note="a")
    s2 = create_specified_selection(pid, rid, f2["id"], quantity=7, trade_discount_pct=0.175, spec_note="b")
    s3 = create_specified_selection(pid, rid, f3["id"], quantity=5, trade_discount_pct=0.0, spec_note="c")
    s4 = create_specified_selection(pid, rid, f4["id"], quantity=1, trade_discount_pct=0.0, spec_note="d")
    create_placed_order(pid, v1["id"], [s1["id"], s2["id"], s3["id"]])  # AMBER, no punch
    project = validate_success(api.get_project(pid, ADMIN), 200)
    assert project["budget_status"] == "AMBER", project["budget_status"]
    assert project["posture"] == "BUDGET_REVIEW", project["posture"]
    o2 = create_draft_order_with_lines(pid, v2["id"], [s4["id"]],
                                       window_start="2026-09-01T00:00:00Z",
                                       window_end="2026-09-02T00:00:00Z")
    pv = project_version(pid)
    res = api.place_order(o2["id"], {"expected_project_version": pv}, PC)
    validate_error(res, "ERR_BUDGET_GATE")


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — priority_pair_validation_conflict / invalid_state_beats_vendor_suspended_on_place
# ─────────────────────────────────────────────────────────────────────────────
def test_invalid_state_beats_vendor_suspended_on_place(api):
    """PRD §2.6: "Only after these four gates pass does the system evaluate
    state-machine legality (rejecting an illegal transition for the resource's current
    state with ERR_INVALID_STATE) and then the domain-specific business rules"
    PRD §3.5: "Placing the order is the pivotal commitment, performed by a procurement
    coordinator and legal only from DRAFT."

    Re-placing an already-ORDERED order whose vendor was since suspended returns
    ERR_INVALID_STATE (state check precedes the vendor-standing business rule).

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_vendor_suspended_on_place
    """
    s = setup_project_with_approved_room()
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="IS-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=3)
    sel = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    order = create_placed_order(pid, vid, [sel["id"]])  # now ORDERED
    validate_success(api.suspend_vendor(vid, ADMIN), 200)
    pv = project_version(pid)
    res = api.place_order(order["id"], {"expected_project_version": pv}, PC)
    validate_error(res, "ERR_INVALID_STATE")


def test_place_succeeds_then_replace_is_invalid_state(api):
    """PRD §3.5: "Placing the order is the pivotal commitment, performed by a
    procurement coordinator and legal only from DRAFT."

    A second place attempt on the same (now ORDERED) order is an illegal transition.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_vendor_suspended_on_place
    """
    s = setup_project_with_approved_room()
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="IS-B", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=3)
    sel = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    order = create_placed_order(pid, vid, [sel["id"]])
    pv = project_version(pid)
    res = api.place_order(order["id"], {"expected_project_version": pv}, PC)
    validate_error(res, "ERR_INVALID_STATE")


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — boundary_precision_check / place_empty_order_zero_lines_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_place_empty_order_rejected(api):
    """PRD §3.5: "The order must hold at least one order line, or it is rejected as
    ERR_ORDER_EMPTY."

    Design: Difficulty/boundary_precision_check/place_empty_order_zero_lines_rejected
    """
    client = create_client()
    project = create_project(client["id"], budget_cents=10000000)
    vendor = create_vendor()
    order = get_success_data(api.create_order(
        project["id"], create_order_payload(vendor["id"]), PC))
    pv = project_version(project["id"])
    res = api.place_order(order["id"], {"expected_project_version": pv}, PC)
    validate_error(res, "ERR_ORDER_EMPTY")


def test_empty_order_remains_draft_after_rejected_place(api):
    """PRD §3.5: "The order must hold at least one order line, or it is rejected as
    ERR_ORDER_EMPTY."
    PRD §3.5: "the order records the project_id of its owning project, begins in
    status DRAFT"

    Design: Difficulty/boundary_precision_check/place_empty_order_zero_lines_rejected
    """
    client = create_client()
    project = create_project(client["id"], budget_cents=10000000)
    vendor = create_vendor()
    order = get_success_data(api.create_order(
        project["id"], create_order_payload(vendor["id"]), PC))
    pv = project_version(project["id"])
    api.place_order(order["id"], {"expected_project_version": pv}, PC)
    after = validate_success(api.get_order(order["id"], ADMIN), 200)
    assert after["status"] == "DRAFT", after["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — cross_entity_state_dependency / specify_selection_requires_room_approved
# ─────────────────────────────────────────────────────────────────────────────
def test_specify_selection_requires_room_approved(api):
    """PRD §3.4: "Two preconditions apply: the selection's room must be APPROVED
    (otherwise ERR_ROOM_NOT_APPROVED), and the spec_note must be non-empty"

    Design: Difficulty/cross_entity_state_dependency/specify_selection_requires_room_approved
    """
    client = create_client()
    project = create_project(client["id"], budget_cents=10000000)
    ffe = create_ffe_item(sku="CE-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    room, _mb = create_room_with_presented_moodboard(project["id"], room_name="R1")
    # Room is MOODBOARD_READY (not APPROVED).
    sel = get_success_data(api.create_selection(
        project["id"], create_selection_payload(room["id"], ffe["id"], quantity=1, spec_note="linen"), DESIGNER))
    res = api.specify_selection(sel["id"], DESIGNER)
    validate_error(res, "ERR_ROOM_NOT_APPROVED")
    sel_after = validate_success(api.get_selection(sel["id"], ADMIN), 200)
    assert sel_after["status"] == "PROPOSED", sel_after["status"]
    room_after = validate_success(api.get_room(room["id"], ADMIN), 200)
    assert room_after["status"] == "MOODBOARD_READY", room_after["status"]


def test_specify_succeeds_once_room_approved(api):
    """PRD §3.4: "Specifying a selection locks its specification, moving it from
    PROPOSED to SPECIFIED. Two preconditions apply: the selection's room must be
    APPROVED (otherwise ERR_ROOM_NOT_APPROVED), and the spec_note must be non-empty"

    Design: Difficulty/cross_entity_state_dependency/specify_selection_requires_room_approved
    """
    s = setup_project_with_approved_room()
    pid, rid = s["project"]["id"], s["room"]["id"]
    ffe = create_ffe_item(sku="CE-B", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    sel = get_success_data(api.create_selection(
        pid, create_selection_payload(rid, ffe["id"], quantity=1, spec_note="linen"), DESIGNER))
    specified = validate_success(api.specify_selection(sel["id"], DESIGNER), 200)
    assert specified["status"] == "SPECIFIED", specified["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — cross_entity_state_dependency / advance_to_procurement_requires_all_rooms_approved
# ─────────────────────────────────────────────────────────────────────────────
def test_advance_to_procurement_requires_all_rooms_approved(api):
    """PRD §3.2: "Moving from IN_DESIGN to PROCUREMENT, also driven by a designer,
    requires two conditions: every room must be APPROVED (no room may remain in
    SCOPING, MOODBOARD_READY, or REWORK, otherwise the advance is rejected with
    ERR_ROOMS_NOT_APPROVED)"

    Design: Difficulty/cross_entity_state_dependency/advance_to_procurement_requires_all_rooms_approved
    """
    s = setup_project_with_approved_room(room_name="R1")  # one APPROVED room
    pid, cid = s["project"]["id"], s["client"]["id"]
    # Add a second room left in SCOPING.
    create_room(pid, name="R2")
    advance_project_to(pid, "IN_DESIGN", actor=DESIGNER)
    res = api.advance_project(pid, {"to": "PROCUREMENT"}, DESIGNER)
    validate_error(res, "ERR_ROOMS_NOT_APPROVED")
    project = validate_success(api.get_project(pid, ADMIN), 200)
    assert project["status"] == "IN_DESIGN", project["status"]


def test_advance_to_procurement_succeeds_when_all_rooms_approved(api):
    """PRD §3.2: "Moving from IN_DESIGN to PROCUREMENT, also driven by a designer,
    requires two conditions: every room must be APPROVED"
    PRD §3.2: "Each successful advance sets the new status and increments the
    project's version."

    Design: Difficulty/cross_entity_state_dependency/advance_to_procurement_requires_all_rooms_approved
    """
    s = setup_project_with_approved_room(room_name="R1")
    pid = s["project"]["id"]
    advance_project_to(pid, "IN_DESIGN", actor=DESIGNER)
    advanced = validate_success(api.advance_project(pid, {"to": "PROCUREMENT"}, DESIGNER), 200)
    assert advanced["status"] == "PROCUREMENT", advanced["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — resource_temporal_overlap / vendor_window_strict_overlap_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_vendor_window_strict_overlap_rejected(api):
    """PRD §3.5: "the requested window must not overlap another non-terminal order on
    the same vendor; windows are treated as half-open intervals from window_start up
    to but not including window_end, so two orders whose windows merely touch at an
    endpoint do not conflict, but any genuine overlap is rejected with
    ERR_VENDOR_WINDOW_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/vendor_window_strict_overlap_rejected
    """
    s = setup_project_with_approved_room()
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="TO-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    f2 = create_ffe_item(sku="TO-B", name="Table", category="FURNITURE", list_unit_cost_cents=30000, lead_time_days=1)
    s1 = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    s2 = create_specified_selection(pid, rid, f2["id"], quantity=1, spec_note="b")
    create_placed_order(pid, vid, [s1["id"]],
                        window_start="2026-07-01T00:00:00Z", window_end="2026-07-02T00:00:00Z")
    # Second order [Jul 1 12:00, Jul 3) overlaps the first [Jul 1, Jul 2) on the SAME vendor.
    o2 = create_draft_order_with_lines(pid, vid, [s2["id"]],
                                       window_start="2026-07-01T12:00:00Z",
                                       window_end="2026-07-03T00:00:00Z")
    pv = project_version(pid)
    res = api.place_order(o2["id"], {"expected_project_version": pv}, PC)
    validate_error(res, "ERR_VENDOR_WINDOW_CONFLICT")
    after = validate_success(api.get_order(o2["id"], ADMIN), 200)
    assert after["status"] == "DRAFT", after["status"]


def test_overlapping_window_on_different_vendor_does_not_conflict(api):
    """PRD §3.5: "the requested window must not overlap another non-terminal order on
    the same vendor; windows are treated as half-open intervals from window_start up
    to but not including window_end ... but any genuine overlap is rejected with
    ERR_VENDOR_WINDOW_CONFLICT."

    The window-conflict check is scoped to the SAME vendor, so an identical, fully
    overlapping window on a different vendor places successfully.

    Design: Difficulty/resource_temporal_overlap/vendor_window_strict_overlap_rejected
    """
    s = setup_project_with_approved_room()
    pid, rid = s["project"]["id"], s["room"]["id"]
    v1 = s["vendor"]
    v2 = create_vendor(name="V2", trade="MILLWORK")
    f1 = create_ffe_item(sku="DV-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    f2 = create_ffe_item(sku="DV-B", name="Table", category="FURNITURE", list_unit_cost_cents=30000, lead_time_days=1)
    s1 = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    s2 = create_specified_selection(pid, rid, f2["id"], quantity=1, spec_note="b")
    create_placed_order(pid, v1["id"], [s1["id"]],
                        window_start="2026-07-01T00:00:00Z", window_end="2026-07-02T00:00:00Z")
    # Identical (fully overlapping) window, but on a DIFFERENT vendor v2.
    o2 = create_draft_order_with_lines(pid, v2["id"], [s2["id"]],
                                       window_start="2026-07-01T00:00:00Z",
                                       window_end="2026-07-02T00:00:00Z")
    pv = project_version(pid)
    placed = validate_success(api.place_order(o2["id"], {"expected_project_version": pv}, PC), 200)
    assert placed["status"] == "ORDERED", placed["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — resource_temporal_overlap / vendor_window_touching_endpoints_allowed_half_open
# ─────────────────────────────────────────────────────────────────────────────
def test_vendor_window_touching_endpoints_allowed(api):
    """PRD §3.5: "windows are treated as half-open intervals from window_start up to
    but not including window_end, so two orders whose windows merely touch at an
    endpoint do not conflict"

    Design: Difficulty/resource_temporal_overlap/vendor_window_touching_endpoints_allowed_half_open
    """
    s = setup_project_with_approved_room()
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="TA-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    f2 = create_ffe_item(sku="TA-B", name="Table", category="FURNITURE", list_unit_cost_cents=30000, lead_time_days=1)
    s1 = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    s2 = create_specified_selection(pid, rid, f2["id"], quantity=1, spec_note="b")
    create_placed_order(pid, vid, [s1["id"]],
                        window_start="2026-07-01T00:00:00Z", window_end="2026-07-02T00:00:00Z")
    # Second order [Jul 2, Jul 3) touches the first only at the boundary instant.
    o2 = create_draft_order_with_lines(pid, vid, [s2["id"]],
                                       window_start="2026-07-02T00:00:00Z",
                                       window_end="2026-07-03T00:00:00Z")
    pv = project_version(pid)
    placed = validate_success(api.place_order(o2["id"], {"expected_project_version": pv}, PC), 200)
    assert placed["status"] == "ORDERED", placed["status"]


def test_fully_separated_window_on_same_vendor_places(api):
    """PRD §3.5: "the requested window must not overlap another non-terminal order on
    the same vendor; windows are treated as half-open intervals from window_start up
    to but not including window_end, so two orders whose windows merely touch at an
    endpoint do not conflict"

    A window that starts strictly after the first order's window ends (a clear gap,
    no shared instant and no overlap) places successfully on the same vendor.

    Design: Difficulty/resource_temporal_overlap/vendor_window_touching_endpoints_allowed_half_open
    """
    s = setup_project_with_approved_room()
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="GP-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    f2 = create_ffe_item(sku="GP-B", name="Table", category="FURNITURE", list_unit_cost_cents=30000, lead_time_days=1)
    s1 = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    s2 = create_specified_selection(pid, rid, f2["id"], quantity=1, spec_note="b")
    create_placed_order(pid, vid, [s1["id"]],
                        window_start="2026-07-01T00:00:00Z", window_end="2026-07-02T00:00:00Z")
    # Second order [Jul 5, Jul 6) — a clear gap after the first [Jul 1, Jul 2).
    o2 = create_draft_order_with_lines(pid, vid, [s2["id"]],
                                       window_start="2026-07-05T00:00:00Z",
                                       window_end="2026-07-06T00:00:00Z")
    pv = project_version(pid)
    placed = validate_success(api.place_order(o2["id"], {"expected_project_version": pv}, PC), 200)
    assert placed["status"] == "ORDERED", placed["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — validations / create_selection_for_inactive_ffe_item_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_create_selection_for_inactive_ffe_item_rejected(api):
    """PRD §3.4: "The referenced catalog item must be active; selecting an item whose
    active is false is rejected with ERR_FFE_ITEM_INACTIVE."

    Design: Corner/validations/create_selection_for_inactive_ffe_item_rejected
    """
    client = create_client()
    project = create_project(client["id"], budget_cents=10000000)
    ffe = create_ffe_item(sku="IN-A", name="Old", category="DECOR",
                          list_unit_cost_cents=500, lead_time_days=1, active=False)
    room = create_room(project["id"], name="R1")
    res = api.create_selection(
        project["id"], create_selection_payload(room["id"], ffe["id"], quantity=1, spec_note="x"), DESIGNER)
    validate_error(res, "ERR_FFE_ITEM_INACTIVE")


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — validations / specify_without_spec_note_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_specify_without_spec_note_rejected(api):
    """PRD §3.4: "the spec_note must be non-empty (otherwise ERR_SPEC_NOTE_REQUIRED)"
    PRD §3.4: "The spec note defaults to an empty string."

    Design: Corner/validations/specify_without_spec_note_rejected
    """
    s = setup_project_with_approved_room()
    pid, rid = s["project"]["id"], s["room"]["id"]
    ffe = create_ffe_item(sku="SP-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    # Create a selection WITHOUT a spec_note (defaults to empty string).
    sel = get_success_data(api.create_selection(
        pid, {"room_id": rid, "ffe_item_id": ffe["id"], "quantity": 1}, DESIGNER))
    res = api.specify_selection(sel["id"], DESIGNER)
    validate_error(res, "ERR_SPEC_NOTE_REQUIRED")
    after = validate_success(api.get_selection(sel["id"], ADMIN), 200)
    assert after["status"] == "PROPOSED", after["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — validations / withdraw_specified_selection_on_active_order_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_withdraw_specified_selection_on_active_order_rejected(api):
    """PRD §3.4: "A designer may also withdraw a SPECIFIED selection, but only if it
    is not attached to any non-cancelled procurement order; if it is so attached, the
    withdrawal is rejected with ERR_SELECTION_ON_ORDER."

    The cited rule fires on a SPECIFIED selection that is attached to a non-cancelled
    order. A DRAFT order is non-cancelled (cancel is reachable only from ORDERED /
    IN_TRANSIT per §3.5/§3.11) and attaching a line does NOT change the selection's
    status (§3.5 names no status change on attach; the selection only moves to ORDERED
    when the order is *placed*, §3.5). So the selection stays SPECIFIED while attached
    to the DRAFT order — exactly the precondition the PRD sentence describes.

    Design: Corner/validations/withdraw_specified_selection_on_active_order_rejected
    """
    s = setup_project_with_approved_room()
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="WD-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    sel = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    # Attach to a non-cancelled DRAFT order; the selection remains SPECIFIED.
    create_draft_order_with_lines(pid, vid, [sel["id"]])
    res = api.withdraw_selection(sel["id"], DESIGNER)
    validate_error(res, "ERR_SELECTION_ON_ORDER")
    after = validate_success(api.get_selection(sel["id"], ADMIN), 200)
    assert after["status"] == "SPECIFIED", after["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — validations / attach_selection_already_on_order_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_attach_selection_already_on_order_rejected(api):
    """PRD §3.5: "a selection may be attached to at most one non-cancelled order. A
    violation of any of these — a selection already on a non-cancelled order, a
    selection not yet specified, or a room/project mismatch — is rejected with
    ERR_SELECTION_ALREADY_ORDERED."

    Design: Corner/validations/attach_selection_already_on_order_rejected
    """
    s = setup_project_with_approved_room()
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="AA-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    sel = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    create_draft_order_with_lines(pid, vid, [sel["id"]])  # O1 holds the selection
    o2 = get_success_data(api.create_order(
        pid, create_order_payload(vid, window_start="2026-08-01T00:00:00Z",
                                  window_end="2026-08-02T00:00:00Z"), PC))
    res = api.add_order_line(o2["id"], {"selection_id": sel["id"]}, PC)
    validate_error(res, "ERR_SELECTION_ALREADY_ORDERED")


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — validations / invalid_window_end_before_start_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_order_window_end_before_start_rejected(api):
    """PRD §3.5: "window_start and window_end, both ISO 8601 UTC instants, with
    window_end required to be strictly later than window_start."
    PRD §2.6: "including the rule that an order's window_end must be strictly later
    than its window_start — with violations reported as ERR_INVALID_REQUEST."

    Design: Corner/validations/invalid_window_end_before_start_rejected
    """
    client = create_client()
    project = create_project(client["id"], budget_cents=10000000)
    vendor = create_vendor()
    res = api.create_order(
        project["id"],
        {"vendor_id": vendor["id"], "window_start": "2026-07-05T00:00:00Z",
         "window_end": "2026-07-01T00:00:00Z"}, PC)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — validations / advance_to_installation_without_in_flight_order_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_advance_to_installation_without_in_flight_order_rejected(api):
    """PRD §3.2: "Moving from PROCUREMENT to INSTALLATION is driven by a procurement
    coordinator and requires that at least one procurement order be in IN_TRANSIT or
    DELIVERED status, failing which the advance is rejected with
    ERR_NO_ORDERS_IN_FLIGHT."

    Design: Corner/validations/advance_to_installation_without_in_flight_order_rejected
    """
    s = setup_project_with_approved_room()
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    advance_project_to(pid, "IN_DESIGN", actor=DESIGNER)
    advance_project_to(pid, "PROCUREMENT", actor=DESIGNER)
    f1 = create_ffe_item(sku="AI-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    sel = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    create_placed_order(pid, vid, [sel["id"]])  # ORDERED, but not IN_TRANSIT/DELIVERED
    res = api.advance_project(pid, {"to": "INSTALLATION"}, PC)
    validate_error(res, "ERR_NO_ORDERS_IN_FLIGHT")
    project = validate_success(api.get_project(pid, ADMIN), 200)
    assert project["status"] == "PROCUREMENT", project["status"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — validations / advance_to_procurement_with_open_revision_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_advance_to_procurement_with_open_revision_rejected(api):
    """PRD §3.2: "and no revision request may be in SUBMITTED or CHANGES_REQUESTED
    status (otherwise the advance is rejected with ERR_OPEN_REVISION)."

    Design: Corner/validations/advance_to_procurement_with_open_revision_rejected
    """
    s = setup_project_with_approved_room(room_name="R1")
    pid, rid, cid = s["project"]["id"], s["room"]["id"], s["client"]["id"]
    advance_project_to(pid, "IN_DESIGN", actor=DESIGNER)
    cli = make_client_headers(cid)
    rev = get_success_data(api.create_revision(
        pid, {"target_kind": "SELECTION", "target_id": rid, "note": "x"}, cli))
    get_success_data(api.submit_revision(rev["id"], cli))
    res = api.advance_project(pid, {"to": "PROCUREMENT"}, DESIGNER)
    validate_error(res, "ERR_OPEN_REVISION")
    project = validate_success(api.get_project(pid, ADMIN), 200)
    assert project["status"] == "IN_DESIGN", project["status"]
