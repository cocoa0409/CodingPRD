"""Who may act: endpoint authorization, staff identity, ownership and segregation of duties."""

from test_helpers import (
    ApiErrorId,
    assert_money_equals,
    create_allowance_item_payload,
    create_change_order,
    create_client,
    create_project_payload,
    make_client_headers,
    make_project_manager_headers,
    open_draw,
    post_and_approve_cost_entry,
    read_change_order,
    read_cost_entry,
    read_draw_request,
    read_project,
    read_schedule_task,
    release_task,
    setup_job,
    setup_priced_change_order,
    setup_submitted_change_order,
    validate_error,
    validate_paginated,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_request_without_auth_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to this API must carry two headers: `X-User-ID`, identifying
    the acting principal, and `X-User-Role`, naming the capacity in which that principal is
    acting. If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.10: "1. **Headers present.** `X-User-Role` and `X-User-ID` must both be present and
    non-empty on every request, or `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/create_project_missing_auth_headers_returns_unauthenticated
    """
    client = create_client()

    response = api.create_project(create_project_payload(client["id"]), {})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    rows, meta = validate_paginated(
        api.list_projects(ADMIN, params={"client_id": client["id"]})
    )
    assert meta["total_count"] == 0, "an unauthenticated request may create nothing"


def test_estimator_may_not_submit_a_change_order(api):
    """PRD §2.1: "Once the headers are accepted, the role must appear on the authorization list
    of the endpoint being called; when it does not, the request is refused with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.3: "Submission is a `ProjectManager` action that advances a change order `PRICED →
    SUBMITTED`."

    Design: Corner/rbac/estimator_cannot_submit_a_change_order
    """
    ctx = setup_job()
    change_order = setup_priced_change_order(
        ctx,
        origin="CLIENT_REQUEST",
        scope_description="Add a wine room",
        direct_cost=3000.00,
        schedule_impact_days=0,
    )

    response = api.submit_change_order(change_order["id"], ctx["estimator_headers"])
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    stored = read_change_order(change_order["id"])
    assert stored["status"] == "PRICED"
    assert stored["submitted_by_staff_id"] is None


def test_client_may_not_price_a_change_order(api):
    """PRD §2.1: "Once the headers are accepted, the role must appear on the authorization list
    of the endpoint being called; when it does not, the request is refused with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.3: "Pricing is the estimator's craft, and both an `Estimator` and a `ProjectManager`
    may perform it."

    Design: Corner/rbac/client_cannot_price_a_change_order
    """
    ctx = setup_job()
    change_order = create_change_order(
        ctx,
        origin="CLIENT_REQUEST",
        scope_description="Add a wine room",
        direct_cost=3000.00,
        schedule_impact_days=0,
    )

    response = api.price_change_order(change_order["id"], {}, ctx["client_headers"])
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    stored = read_change_order(change_order["id"])
    assert stored["status"] == "DRAFT"
    assert stored["priced_amount"] is None


def test_project_manager_role_with_an_estimator_identifier_is_refused(api):
    """PRD §2.1: "For these three roles the server additionally requires that the `StaffMember`
    so identified carries a `staff_function` matching the acting role — `ProjectManager`
    requires `PROJECT_MANAGER`, `Estimator` requires `ESTIMATOR`, and `Controller` requires
    `CONTROLLER`. A `X-User-ID` that does not resolve to a `StaffMember` at all, or that
    resolves to one whose `staff_function` names a different function than the acting role, is
    rejected with `ERR_ROLE_IDENTITY_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/project_manager_role_with_an_estimator_user_id_is_rejected
    """
    ctx = setup_job(start_construction=False, create_allowance=False, create_task=False)
    impersonating_headers = make_project_manager_headers(ctx["estimator"]["id"])

    response = api.create_allowance_item(
        create_allowance_item_payload(ctx["project"]["id"]), impersonating_headers
    )
    validate_error(response, ApiErrorId.ERR_ROLE_IDENTITY_MISMATCH, 403)

    rows, meta = validate_paginated(
        api.list_allowance_items(ADMIN, params={"project_id": ctx["project"]["id"]})
    )
    assert meta["total_count"] == 0


def test_a_foreign_homeowner_may_not_decide_another_jobs_change_order(api):
    """PRD §2.1: "**`Client`** is the homeowner. When `X-User-Role` is `Client`, `X-User-ID` is
    the `id` of the acting `Client` record; ownership checks on any resource that references a
    `Client` compare the resource's foreign-key field to `X-User-ID`, which in practice means
    that the `client_id` of the project owning the target row must equal `X-User-ID`."
    PRD §2.1: "Whenever a `Client`, `Lender`, or `Subcontractor` principal acts on a resource
    that these comparisons say it does not own, the request is refused with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/foreign_client_cannot_decide_another_projects_change_order
    """
    ctx = setup_job()
    outsider = create_client(full_name="Sam Okafor", email="sam@example.com")
    change_order = setup_submitted_change_order(
        ctx,
        origin="CLIENT_REQUEST",
        scope_description="Add a wine room",
        direct_cost=3000.00,
        schedule_impact_days=0,
    )

    response = api.decide_change_order(
        change_order["id"], {"decision": "APPROVE"}, make_client_headers(outsider["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

    assert read_change_order(change_order["id"])["status"] == "SUBMITTED"
    assert_money_equals(
        read_project(ctx["project"]["id"])["approved_change_order_total"],
        0.00,
        "approved_change_order_total",
    )


def test_a_trade_may_not_start_another_trades_task(api):
    """PRD §2.1: "**`Subcontractor`** is the trade contractor. When `X-User-Role` is
    `Subcontractor`, `X-User-ID` is the `id` of the acting `Subcontractor` record; ownership
    checks compare the target row's own trade reference to `X-User-ID` — the `subcontractor_id`
    of a schedule task, the `subcontractor_id` of a lien waiver, or the
    `responsible_subcontractor_id` of a defect ticket, depending on which resource is being
    acted upon."
    PRD §3.4: "Field progress belongs to the trade itself, and a `Subcontractor` supplies an
    `action` to move its own task. Starting advances `RELEASED → IN_PROGRESS`; a task carrying a
    `material_ready_at` may not be started before that instant, and an early start earns
    `ERR_MATERIAL_NOT_READY`."

    Design: Corner/rbac/subcontractor_cannot_start_another_subcontractors_task
    """
    ctx = setup_job(with_plumbing=True)
    release_task(ctx, ctx["task_frame"]["id"])

    response = api.progress_schedule_task(
        ctx["task_frame"]["id"], {"action": "START"}, ctx["sub_plumb_headers"]
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

    task = read_schedule_task(ctx["task_frame"]["id"])
    assert task["status"] == "RELEASED"
    assert task["actual_start"] is None


def test_the_pricer_may_not_also_submit_the_change_order(api):
    """PRD §2.7: "The first governs change orders: the `StaffMember` submitting a priced change
    order to the homeowner must not be the same `StaffMember` recorded in `priced_by_staff_id`.
    Because a `ProjectManager` is permitted to price change orders as well as submit them, this
    rule is genuinely reachable — a project manager who prices a change order themselves cannot
    then submit it, and must hand it to a colleague."
    PRD §2.7: "Two operations in this system require that two different builder employees have
    touched the record, and both are enforced with the same rejection,
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/same_staff_member_cannot_price_and_submit_the_same_change_order
    """
    ctx = setup_job()
    change_order = setup_priced_change_order(
        ctx,
        priced_by="project_manager",
        origin="CLIENT_REQUEST",
        scope_description="Add a wine room",
        direct_cost=3000.00,
        schedule_impact_days=0,
    )
    assert change_order["priced_by_staff_id"] == ctx["pm"]["id"]

    response = api.submit_change_order(change_order["id"], ctx["pm_headers"])
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    stored = read_change_order(change_order["id"])
    assert stored["status"] == "PRICED"
    assert stored["priced_by_staff_id"] == ctx["pm"]["id"]
    assert stored["submitted_by_staff_id"] is None


def test_the_cost_approver_may_not_submit_the_draw_that_bills_it(api):
    """PRD §2.7: "The second governs draws: the `StaffMember` submitting a draw request to the
    lender must not equal the `approved_by_staff_id` of any cost entry that the submission would
    pull into the draw. A controller who approved even one of the eligible invoices is barred
    from submitting the draw that bills for it."
    PRD §3.5: "Approving advances the entry `PENDING → APPROVED`, stamps `approved_by_staff_id`
    with the acting controller's identifier and `approved_at` with the logical clock now, and
    recomputes the project's `cost_to_date` and `eligible_cost_pool` followed by
    `budget_posture`."

    Design: Corner/rbac/controller_cannot_submit_a_draw_containing_costs_they_approved
    """
    ctx = setup_job()
    entry = post_and_approve_cost_entry(
        ctx, amount=10000.10, incurred_at="2026-08-10T00:00:00.000Z", approver="a"
    )
    draw = open_draw(ctx, controller="a")

    response = api.submit_draw_request(draw["id"], ctx["controller_a_headers"])
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    assert read_draw_request(draw["id"])["status"] == "DRAFT"
    stored_entry = read_cost_entry(entry["id"])
    assert stored_entry["status"] == "APPROVED"
    assert stored_entry["approved_by_staff_id"] == ctx["controller_a"]["id"]
