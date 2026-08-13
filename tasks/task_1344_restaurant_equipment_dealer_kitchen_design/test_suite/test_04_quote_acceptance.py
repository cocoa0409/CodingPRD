"""Quote acceptance: cross-entity gates, cascades, OCC, credit/suspension."""
from test_helpers import (
    TEST_USERS,
    accept_quote_flow,
    create_customer,
    create_project,
    get_success_data,
    make_customer_headers,
    setup_project_with_approved_layout,
    setup_quote_accepted,
    setup_quote_presented,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["project_manager_headers"]
SR = TEST_USERS["sales_rep_headers"]
KD = TEST_USERS["kitchen_designer_headers"]


def test_quote_create_rejected_when_layout_not_approved(api):
    """PRD §3.3: "A `SalesRep` creates a `Quote` against a specific layout
    revision by passing `layout_id`; the referenced layout must be `APPROVED`
    or creation fails with `ERR_LAYOUT_NOT_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/layout_not_approved_state_beats_hood_safety_check
    """
    from test_helpers import create_layout, add_equipment_item

    customer = create_customer()
    project = create_project(customer["id"])
    # hood_required=true with a non-hood item; layout left in DRAFT.
    layout = create_layout(project["id"], hood_required=True)
    add_equipment_item(
        project["id"], layout["id"], model_no="OVEN", requires_hood=False
    )

    res = api.create_quote(project["id"], layout["id"], SR)
    validate_error(res, "ERR_LAYOUT_NOT_APPROVED", expected_status=409)


def test_quote_create_rejected_for_draft_layout_plain(api):
    """PRD §3.3: "the referenced layout must be `APPROVED` or creation fails
    with `ERR_LAYOUT_NOT_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/layout_not_approved_state_beats_hood_safety_check
    """
    from test_helpers import create_layout, add_equipment_item

    customer = create_customer()
    project = create_project(customer["id"])
    layout = create_layout(project["id"])
    add_equipment_item(project["id"], layout["id"])

    res = api.create_quote(project["id"], layout["id"], SR)
    validate_error(res, "ERR_LAYOUT_NOT_APPROVED", expected_status=409)


def test_quote_present_gated_on_layout_approved(api):
    """PRD §3.3: "the referenced layout must be `APPROVED`
    (`ERR_LAYOUT_NOT_APPROVED`)". Quote creation itself enforces the gate.

    Design: Difficulty/cross_entity_state_dependency/quote_present_gated_on_layout_approved
    """
    from test_helpers import create_layout, add_equipment_item

    customer = create_customer()
    project = create_project(customer["id"])
    layout = create_layout(project["id"])
    add_equipment_item(project["id"], layout["id"], model_no="OVEN")

    res = api.create_quote(project["id"], layout["id"], SR)
    validate_error(res, "ERR_LAYOUT_NOT_APPROVED", expected_status=409)


def test_quote_present_moves_project_to_quoted(api):
    """PRD §3.3: "On success the quote's pricing fields are recomputed under
    the `PROVISIONAL` variant (still reading the creation-time layout
    snapshot, not current item prices), the quote moves `DRAFT` → `PRESENTED`,
    and the project moves `DESIGN` → `QUOTED`."

    Design: Difficulty/cross_entity_state_dependency/quote_present_gated_on_layout_approved
    """
    customer, project, layout, items, quote = setup_quote_presented()
    assert quote["status"] == "PRESENTED"
    project_after = get_success_data(api.get_project(project["id"], PM))
    assert project_after["status"] == "QUOTED"


def test_quote_accept_rejected_when_project_cancelled(api):
    """PRD §3.3: "the quote must be in `PRESENTED` (`ERR_QUOTE_NOT_PRESENTED`),
    the project must be in `QUOTED` (`ERR_PROJECT_NOT_QUOTED`)". PRD §3.9:
    "Every non-terminal quote becomes `SUPERSEDED`" on cancellation.

    Design: Corner/state_machines/quote_accept_rejected_when_project_already_completed
    """
    customer, project, layout, items, quote = setup_quote_presented()
    validate_success(api.cancel_project(project["id"], PM), 200)

    fresh = get_success_data(api.get_project(project["id"], PM))
    res = api.accept_quote(
        project["id"], quote["id"], fresh["version"],
        make_customer_headers(customer["id"]),
    )
    validate_error_is_one_of(
        res,
        [
            "ERR_PROJECT_NOT_QUOTED",
            "ERR_PROJECT_ALREADY_TERMINAL",
            "ERR_QUOTE_NOT_PRESENTED",
        ],
    )


def test_delivery_terminal_lockdown(api):
    """PRD §3.6: "A coordinator may also cancel a job in `PLANNED` or
    `DISPATCHED` (any other state fails with `ERR_JOB_NOT_CANCELLABLE`)".

    Design: Corner/state_machines/delivery_terminal_lockdown
    """
    from test_helpers import create_delivery_job_payload

    customer, project, layout, items, quote = setup_quote_accepted()
    job = get_success_data(
        api.create_delivery_job(
            project["id"], create_delivery_job_payload(),
            TEST_USERS["logistics_coordinator_headers"],
        )
    )
    get_success_data(
        api.dispatch_delivery_job(
            project["id"], job["id"], TEST_USERS["logistics_coordinator_headers"]
        )
    )
    get_success_data(
        api.mark_site_complete(
            project["id"], job["id"], TEST_USERS["logistics_coordinator_headers"]
        )
    )

    res = api.cancel_delivery_job(
        project["id"], job["id"], TEST_USERS["logistics_coordinator_headers"]
    )
    validate_error(res, "ERR_JOB_NOT_CANCELLABLE", expected_status=409)


def test_quote_accept_cascade_items_ordered_and_fab_spawned(api):
    """PRD §3.3: "Every equipment item on the referenced layout moves from
    `SCHEDULED` to `ORDERED`, and for each item whose `item_kind` is
    `CUSTOM_FABRICATION` the system spawns a `FabricationOrder` in
    `PENDING_SHOP_DRAWING` referencing that item."

    Design: Difficulty/transitive_cascade/quote_accept_cascade_depth2
    """
    customer, project, layout, items, quote = setup_quote_accepted(
        item_overrides_list=[
            {"model_no": "RANGE", "item_kind": "STOCK", "quantity": 1,
             "unit_price_cents": 500_000, "lead_time_days": 7},
            {"model_no": "CUSTOM-SUITE", "item_kind": "CUSTOM_FABRICATION",
             "quantity": 1, "unit_price_cents": 5_000_000, "lead_time_days": 60},
        ]
    )
    stock_item, custom_item = items

    for item in (stock_item, custom_item):
        refreshed = get_success_data(
            api.get_equipment_item(project["id"], item["id"], PM)
        )
        assert refreshed["status"] == "ORDERED"

    fabs = get_success_data(api.list_fabrication_orders(project["id"], PM))
    assert len(fabs) == 1
    assert fabs[0]["status"] == "PENDING_SHOP_DRAWING"
    assert fabs[0]["equipment_item_id"] == custom_item["id"]


def test_quote_accept_supersedes_siblings(api):
    """PRD §3.3: "The quote becomes `ACCEPTED`; every sibling quote on the
    project in `DRAFT` or `PRESENTED` becomes `SUPERSEDED`."

    Design: Difficulty/transitive_cascade/quote_accept_cascade_depth2
    """
    customer, project, layout, items, quote = setup_quote_presented()
    # Second (sibling) quote against the same approved layout, left in DRAFT.
    sibling = get_success_data(api.create_quote(project["id"], layout["id"], SR))

    accepted = accept_quote_flow(project, quote, customer)
    assert accepted["status"] == "ACCEPTED"
    sibling_after = get_success_data(
        api.get_quote(project["id"], sibling["id"], SR)
    )
    assert sibling_after["status"] == "SUPERSEDED"


def test_occ_stale_project_version_rejected(api):
    """PRD §2.6: "If the supplied value does not equal the project's current
    `version`, the request is rejected with `ERR_STALE_PROJECT_VERSION`
    (HTTP 412) and no state changes are applied."

    Design: Corner/cross_cutting_layers/occ_stale_project_version_rejected
    """
    customer, project, layout, items, quote = setup_quote_presented()
    fresh = get_success_data(api.get_project(project["id"], SR))
    res = api.accept_quote(
        project["id"], quote["id"], fresh["version"] - 1,
        make_customer_headers(customer["id"]),
    )
    validate_error(res, "ERR_STALE_PROJECT_VERSION", expected_status=412)


def test_occ_correct_version_succeeds_and_bumps(api):
    """PRD §3.3: "The project freezes `quote_baseline_cents` to the final
    `grand_total_cents`, computes `retainage_held_cents` as the baseline
    multiplied by `retainage_pct` rounded half-up to whole cents, and moves
    from `QUOTED` to `CONTRACTED`, incrementing the project's `version` by 1."

    Design: Corner/cross_cutting_layers/occ_correct_version_succeeds_and_bumps
    """
    customer, project, layout, items, quote = setup_quote_presented()
    v_pre = get_success_data(api.get_project(project["id"], SR))["version"]

    accepted = validate_success(
        api.accept_quote(
            project["id"], quote["id"], v_pre,
            make_customer_headers(customer["id"]),
        ),
        200,
    )
    assert accepted["status"] == "ACCEPTED"
    project_after = get_success_data(api.get_project(project["id"], PM))
    assert project_after["version"] == v_pre + 1
    assert project_after["status"] == "CONTRACTED"


def test_accept_returns_final_variant_in_same_response(api):
    """PRD §3.3: "The quote's `variant` flips from `PROVISIONAL` to `FINAL`
    and every monetary field is recomputed against current item state at that
    instant." PRD §2.5: "A quote that flips to the `FINAL` variant at
    acceptance is fully recomputed against the current `unit_price_cents`,
    `item_kind`, and item composition at the moment the acceptance call runs."

    Design: Corner/consistency_model/accept_returns_final_variant_in_same_response
    """
    customer, project, layout, items, quote = setup_quote_presented(
        item_overrides_list=[
            {"model_no": "A", "quantity": 1, "unit_price_cents": 100_000,
             "lead_time_days": 1}
        ]
    )
    accepted = accept_quote_flow(project, quote, customer)
    # Same response object shows the FINAL recomputation — no async lag.
    assert accepted["variant"] == "FINAL"
    assert accepted["status"] == "ACCEPTED"
    assert accepted["grand_total_cents"] == 611_000


def test_credit_limit_exceeded_at_quote_accept(api):
    """PRD §3.3: "the credit guard must pass: the customer's current
    `outstanding_exposure_cents` plus this quote's `grand_total_cents` must be
    less than or equal to `credit_limit_cents`, otherwise
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Corner/validations/credit_limit_exceeded_at_quote_accept
    """
    customer, project, layout, items, quote = setup_quote_presented(
        customer_overrides={"credit_limit_cents": 1000},
        item_overrides_list=[
            {"model_no": "A", "quantity": 1, "unit_price_cents": 100_000,
             "lead_time_days": 1}
        ],
    )
    fresh = get_success_data(api.get_project(project["id"], PM))
    res = api.accept_quote(
        project["id"], quote["id"], fresh["version"],
        make_customer_headers(customer["id"]),
    )
    validate_error(res, "ERR_CREDIT_LIMIT_EXCEEDED", expected_status=402)


def test_customer_suspended_blocks_quote_accept(api):
    """PRD §3.1: "suspension flips `status` to `SUSPENDED` and, as described
    in §3.3, blocks any further quote acceptances with
    `ERR_CUSTOMER_SUSPENDED` until lifted."

    Design: Corner/validations/customer_suspended_blocks_quote_accept
    """
    customer, project, layout, items, quote = setup_quote_presented()
    validate_success(api.suspend_customer(customer["id"], ADMIN), 200)

    fresh = get_success_data(api.get_project(project["id"], PM))
    res = api.accept_quote(
        project["id"], quote["id"], fresh["version"],
        make_customer_headers(customer["id"]),
    )
    validate_error(res, "ERR_CUSTOMER_SUSPENDED", expected_status=402)


def test_error_quote_not_presented(api):
    """PRD §3.3: "the quote must be in `PRESENTED` (`ERR_QUOTE_NOT_PRESENTED`)".
    PRD §2.8: "then state-machine legality for the target resource".

    Design: Corner/errors/error_quote_not_presented
    """
    # Quote created but never presented -> still DRAFT.
    customer, project, layout, items = setup_project_with_approved_layout()
    quote = get_success_data(api.create_quote(project["id"], layout["id"], SR))
    assert quote["status"] == "DRAFT"

    fresh = get_success_data(api.get_project(project["id"], PM))
    res = api.accept_quote(
        project["id"], quote["id"], fresh["version"],
        make_customer_headers(customer["id"]),
    )
    validate_error(res, "ERR_QUOTE_NOT_PRESENTED", expected_status=409)


def test_kitchen_designer_cannot_present_quote(api):
    """PRD §2.1: "`SalesRep` owns quote creation and presentation." and "When
    the supplied role is not authorized for the attempted operation the
    request fails with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/roles/kitchen_designer_cannot_present_quote
    """
    customer, project, layout, items = setup_project_with_approved_layout()
    quote = get_success_data(api.create_quote(project["id"], layout["id"], SR))

    res = api.present_quote(project["id"], quote["id"], KD)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_project_list_filter_by_status(api, project_manager_headers):
    """PRD §3.1: "Project listings accept `customer_id` and `status` filters."

    Design: Corner/endpoints/project_list_filter_by_status
    """
    from test_helpers import validate_paginated

    customer = create_customer()
    create_project(customer["id"], project_name="P1")
    create_project(customer["id"], project_name="P2")

    data, meta = validate_paginated(
        api.list_projects(project_manager_headers, params={"status": "DESIGN"})
    )
    assert meta["total_count"] == 2
    for p in data:
        assert p["status"] == "DESIGN"
