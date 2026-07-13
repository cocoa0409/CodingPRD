"""Lifecycle & state machines: the warranty redo cycle (cyclic WorkOrder), the
APPROVED<->SUSPENDED application cycle, initial states, and invalid/terminal transitions."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    ProApplicationStatus, WorkOrderStatus, TEST_USERS,
    new_zone, new_approved_pro, setup_catalog, new_draft_work_order,
    setup_completed_order, request_redo, dispatch_order,
    make_retailer_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/workorder_warranty_redo_cycle_reenters_dispatched
# ---------------------------------------------------------------------------
def test_request_redo_moves_completed_order_to_redo_requested(api):
    """PRD §3.8: "A redo request advances the order from `COMPLETED` to `REDO_REQUESTED`,
    increments the order's `redo_count` by 1, moves the order's payout from `PENDING` to `HELD`,
    and recomputes the pro's `pending_payout_cents` (which now excludes the held payout)."

    Design: Difficulty/non_linear_state_machine/workorder_warranty_redo_cycle_reenters_dispatched
    """
    ctx = setup_completed_order(api, base_price_cents=12000, clock="2026-03-05T09:30:00Z")
    wo = request_redo(api, ctx["wo"]["id"], ctx["customer"]["id"])
    assert wo["status"] == WorkOrderStatus.REDO_REQUESTED.value
    assert wo["redo_count"] == 1, f"expected redo_count 1, got {wo['redo_count']}"


def test_redo_requested_order_reenters_dispatched(api):
    """PRD §3.8: "From `REDO_REQUESTED` the order is dispatched again (§3.4), flows through
    `DISPATCHED` → `IN_PROGRESS` → `COMPLETED`, and this closes the warranty redo cycle."

    Design: Difficulty/non_linear_state_machine/workorder_warranty_redo_cycle_reenters_dispatched
    """
    ctx = setup_completed_order(api, base_price_cents=12000, clock="2026-03-05T09:30:00Z")
    redo_wo = request_redo(api, ctx["wo"]["id"], ctx["customer"]["id"])
    wo = dispatch_order(api, ctx["wo"]["id"], redo_wo["version"])
    assert wo["status"] == WorkOrderStatus.DISPATCHED.value
    assert wo["redo_count"] == 1, f"redo_count stays 1 across re-dispatch, got {wo['redo_count']}"


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/proapplication_approved_suspended_reinstate_cycle
# ---------------------------------------------------------------------------
def test_approved_application_can_be_suspended(api):
    """PRD §3.2: "An `APPROVED` application can be suspended by an admin, moving it to `SUSPENDED`;
    a suspended pro is dispatch-ineligible."

    Design: Difficulty/non_linear_state_machine/proapplication_approved_suspended_reinstate_cycle
    """
    zone = new_zone(api)
    _, app = new_approved_pro(api, zone["id"])
    data = validate_success(api.suspend_application(app["id"], ADMIN), 200)
    assert data["status"] == ProApplicationStatus.SUSPENDED.value


def test_suspended_application_reinstates_to_approved(api):
    """PRD §3.2: "A `SUSPENDED` application can be reinstated back to `APPROVED`, which restores the
    pro's dispatch eligibility while leaving `approved_at` and `expires_at` unchanged."

    Design: Difficulty/non_linear_state_machine/proapplication_approved_suspended_reinstate_cycle
    """
    zone = new_zone(api)
    _, app = new_approved_pro(api, zone["id"])
    suspended = validate_success(api.suspend_application(app["id"], ADMIN), 200)
    reinstated = validate_success(api.reinstate_application(app["id"], ADMIN), 200)
    assert reinstated["status"] == ProApplicationStatus.APPROVED.value
    # approved_at/expires_at unchanged across the cycle.
    assert reinstated["approved_at"] == suspended["approved_at"]
    assert reinstated["expires_at"] == suspended["expires_at"]


# ---------------------------------------------------------------------------
# Corner/state_machines/workorder_initial_state_is_draft
# ---------------------------------------------------------------------------
def test_new_work_order_is_draft_version_one(api):
    """PRD §3.3: "A freshly created order has `status` `DRAFT`, an empty `selected_addon_ids`, a
    `quoted_price_cents` and `final_price_cents` of 0, and a null `appointment_pro_id`."
    PRD §2.4: "an integer `version` that starts at 1 on creation and increments by 1 on every
    mutation to that resource."

    Design: Corner/state_machines/workorder_initial_state_is_draft
    """
    ctx = setup_catalog(api)
    wo = new_draft_work_order(api, ctx["retailer"]["id"], ctx["customer"]["id"],
                              ctx["task"]["id"], ctx["zone"]["id"])
    assert wo["status"] == WorkOrderStatus.DRAFT.value
    assert wo["version"] == 1


# ---------------------------------------------------------------------------
# Corner/state_machines/cancel_already_cancelled_returns_invalid_state
# ---------------------------------------------------------------------------
def test_cancel_already_cancelled_order_returns_already_terminal(api):
    """PRD §3.8: "The order's from-state must be one the cancel supports (`DRAFT`, `SCHEDULED`,
    `DISPATCHED`, or `COMPLETED`); an order already `CANCELLED` or `CLOSED` is terminal and yields
    `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/cancel_already_cancelled_returns_invalid_state
    """
    ctx = setup_catalog(api)
    ret_id = ctx["retailer"]["id"]
    wo = new_draft_work_order(api, ret_id, ctx["customer"]["id"], ctx["task"]["id"], ctx["zone"]["id"])
    validate_success(api.cancel_work_order(wo["id"], {"reason": "first"}, make_retailer_headers(ret_id)), 200)
    resp = api.cancel_work_order(wo["id"], {"reason": "second"}, make_retailer_headers(ret_id))
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


# ---------------------------------------------------------------------------
# Corner/state_machines/approve_already_approved_returns_invalid_state
# ---------------------------------------------------------------------------
def test_approve_already_approved_application_returns_invalid_state(api):
    """PRD §3.2: "Attempting either transition on an application not in `PENDING_REVIEW` is refused
    with `ERR_INVALID_STATE`; attempting it on an already-terminal application yields
    `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/approve_already_approved_returns_invalid_state
    """
    zone = new_zone(api)
    _, app = new_approved_pro(api, zone["id"])
    resp = api.approve_application(app["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
