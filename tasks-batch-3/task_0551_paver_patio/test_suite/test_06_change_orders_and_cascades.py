"""Change-order pricing/approval, the permit-raise revert cascade, OCC, and cancellation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, assert_balance_consistent, change_order_payload,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["project_manager_headers"]
DESIGN = TEST_USERS["design_consultant_headers"]


def test_change_order_recompute_delta_equals_new_minus_old_contract(api):
    """PRD §3.8: "The `price_delta_cents` is that recomputed valuation minus the project's
    `contract_value_cents` as it stood before approval. The recomputed valuation becomes the new
    `contract_value_cents`, and `balance_due_cents` is recomputed as contract value minus amount
    paid."

    Design: Difficulty/dual_variant_calc/change_order_recompute_vs_line_delta
    """
    ctx = fx.setup_change_order_ready(api)
    pid = ctx["project_id"]
    old_contract = validate_success(api.get_project(pid, PM))["contract_value_cents"]
    co = validate_success(api.create_change_order(
        change_order_payload(pid, ctx["product"]["id"], ctx["sign_version"],
                             add_measured_quantity=100, description="add 100 sqft paver"), PM), 201)
    approved = validate_success(api.approve_change_order(co["id"], PM))
    new_contract = validate_success(api.get_project(pid, PM))["contract_value_cents"]
    assert approved["status"] == "APPROVED", f"expected APPROVED, got {approved['status']}"
    assert new_contract > old_contract, "adding scope must raise the recomputed contract value"
    assert approved["price_delta_cents"] == new_contract - old_contract, (
        f"price_delta {approved['price_delta_cents']} must equal new contract {new_contract} "
        f"minus old contract {old_contract}"
    )


def test_change_order_approval_creates_change_order_line_and_updates_balance(api):
    """PRD §3.8: "Approval creates a new line item (`origin` `CHANGE_ORDER`) from `add_product_id`
    and `add_measured_quantity`, immediately setting that line's `pinned_unit_price_cents` to the
    product's current `unit_price_cents`."

    Design: Difficulty/dual_variant_calc/change_order_recompute_vs_line_delta
    """
    ctx = fx.setup_change_order_ready(api)
    pid = ctx["project_id"]
    co = validate_success(api.create_change_order(
        change_order_payload(pid, ctx["product"]["id"], ctx["sign_version"],
                             add_measured_quantity=100, description="add 100 sqft paver"), PM), 201)
    validate_success(api.approve_change_order(co["id"], PM))
    lines, _meta = validate_paginated(api.list_project_line_items(pid, PM))
    origins = [ln["origin"] for ln in lines]
    assert "CHANGE_ORDER" in origins, f"approval must add a CHANGE_ORDER-origin line; saw {origins}"
    project = validate_success(api.get_project(pid, PM))
    assert_balance_consistent(project)


def test_change_order_permit_raise_reverts_project_to_pending_approvals(api):
    """PRD §3.8: "If the added line raises a wall — `add_wall_height_in` of at least 48 inches — and
    the project did not previously require a permit (`permit_required` was false before approval),
    the project reverts: it moves from `CONTRACTED` or `IN_PRODUCTION` back to `PENDING_APPROVALS`.
    The revert sets `permit_required` to true, creates a `PREPARING` permit if none exists, and
    cascades to the crews: every work phase currently in `SCHEDULED` or `IN_PROGRESS` on that project
    is moved to `BLOCKED`, and each such block decrements the holding crew's `active_booking_count`
    by one."

    Design: Difficulty/transitive_cascade/change_order_permit_raise_blocks_phase_and_releases_crew
    """
    ctx = fx.setup_permit_revert_scenario(api)
    validate_success(api.approve_change_order(ctx["change_order_id"], PM))
    project = validate_success(api.get_project(ctx["project_id"], PM))
    assert project["status"] == "PENDING_APPROVALS", f"expected revert to PENDING_APPROVALS, got {project['status']}"
    assert project["permit_required"] is True, "the permit raise must set permit_required true"


def test_change_order_permit_raise_blocks_phase_and_releases_crew(api):
    """PRD §3.8: "...cascades to the crews: every work phase currently in `SCHEDULED` or
    `IN_PROGRESS` on that project is moved to `BLOCKED`, and each such block decrements the holding
    crew's `active_booking_count` by one."

    Design: Difficulty/transitive_cascade/change_order_permit_raise_blocks_phase_and_releases_crew
    """
    ctx = fx.setup_permit_revert_scenario(api)
    validate_success(api.approve_change_order(ctx["change_order_id"], PM))
    phase = validate_success(api.get_work_phase(ctx["phase_id"], PM))
    crew = validate_success(api.get_crew(ctx["crew_id"], PM))
    assert phase["status"] == "BLOCKED", f"scheduled phase must be BLOCKED by the revert, got {phase['status']}"
    assert crew["active_booking_count"] == 0, \
        f"blocking the phase must release the crew; count={crew['active_booking_count']}"


def test_stale_change_order_version_conflict(api):
    """PRD §2.7: "If the project's current `version` has advanced past that value — because another
    change order, draw, payment, or refund has since touched the ledger — the create is rejected with
    `ERR_STALE_VERSION` (412), and no resource is created."

    Design: Corner/cross_cutting/stale_change_order_version_returns_conflict
    """
    ctx = fx.setup_stale_change_order(api)
    resp = api.create_change_order(
        change_order_payload(ctx["project_id"], ctx["product"]["id"], ctx["stale_version"],
                             add_measured_quantity=10, description="second CO with stale version"), PM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_cancel_cascade_releases_crew_booking(api):
    """PRD §3.8: "From `CONTRACTED` or `IN_PRODUCTION`, cancellation also cascades down: every
    non-terminal material order moves to `CANCELLED`; every work phase in `PLANNED`, `SCHEDULED`,
    `IN_PROGRESS`, or `BLOCKED` moves to `CANCELLED`, releasing its crew (a phase that was
    `SCHEDULED` or `IN_PROGRESS` decrements that crew's `active_booking_count`, while phases that were
    `PLANNED` or `BLOCKED` release nothing further); and every `PENDING` progress draw moves to
    `VOID`."

    Design: Difficulty/compensating_invariant/crew_capacity_conservation_schedule_then_cancel
    """
    ctx = fx.setup_scheduled_phase_contracted(api)
    validate_success(api.cancel_project(ctx["project_id"], PM))
    crew = validate_success(api.get_crew(ctx["crew_id"], PM))
    assert crew["active_booking_count"] == 0, \
        f"cancel cascade must release the crew booking; count={crew['active_booking_count']}"


def test_cancel_cascade_cancels_phase_and_project(api):
    """PRD §3.8: "From `CONTRACTED` or `IN_PRODUCTION`, cancellation also cascades down: ... every
    work phase in `PLANNED`, `SCHEDULED`, `IN_PROGRESS`, or `BLOCKED` moves to `CANCELLED`, releasing
    its crew..."

    Design: Difficulty/compensating_invariant/crew_capacity_conservation_schedule_then_cancel
    """
    ctx = fx.setup_scheduled_phase_contracted(api)
    project = validate_success(api.cancel_project(ctx["project_id"], PM))
    phase = validate_success(api.get_work_phase(ctx["phase_id"], PM))
    assert project["status"] == "CANCELLED", f"expected CANCELLED, got {project['status']}"
    assert phase["status"] == "CANCELLED", f"scheduled phase must be CANCELLED by cascade, got {phase['status']}"


def test_cancel_cancelled_project_invalid_state(api):
    """PRD §3.8: "Cancellation is available to a `ProjectManager` from any non-terminal posture —
    that is, any status other than `COMPLETED` or `CANCELLED` — moving the project to `CANCELLED`."
    PRD §2.5: "The target resource must sit in a state from which the transition is legal. A generic
    violation is `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/cancel_already_cancelled_returns_invalid_state
    """
    customer = fx.make_customer(api, email="ot@example.com")
    project = fx.make_project(api, customer["id"], site_address="29 Yard Ln")
    validate_success(api.cancel_project(project["id"], PM))
    resp = api.cancel_project(project["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
