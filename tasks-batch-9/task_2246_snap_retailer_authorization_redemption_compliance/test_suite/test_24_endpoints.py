"""Endpoint-shaped behaviour: the CRUD cycle, the action routes, the junction
write, the computed sub-resource read and the response envelope itself.

Each test walks one route family end to end and pins what the specification says
the route returns, including the values a neighbouring route must *not* have
disturbed.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    AUG_01,
    AUG_05,
    AUG_25,
    ApiErrorId,
    NON_EXISTENT_UUID,
    active_equipment,
    advance_clock,
    api_client,
    assert_depot_conservation,
    assert_fields,
    assert_inspector_minutes,
    assert_instant,
    assert_ledger_conservation,
    assert_row_count,
    assert_timestamp,
    authorized_store,
    cancel_order_payload,
    close_period,
    cmp_payment_payload,
    create_application,
    create_depot,
    create_inspector,
    create_owner,
    create_period,
    create_store,
    create_terminal,
    created,
    data_ids,
    decide_application,
    deployment_payload,
    equipment_order_payload,
    four_closed_periods,
    issue_determination,
    line_item,
    ok,
    order_line,
    owner_headers,
    pending_visit_application,
    pos_transaction_payload,
    refresh_application,
    refresh_case,
    refresh_depot,
    refresh_inspector,
    refresh_order,
    refresh_owner,
    refresh_period,
    refresh_store,
    refresh_terminal,
    refresh_transaction,
    replied_case,
    SEP_01,
    schedule_visit,
    start_visit,
    store_patch_payload,
    store_payload,
    submit_application,
    submit_findings,
    validate_error,
    validate_paginated,
    validate_success,
    void_payload,
)

# The five-line basket of the endpoint recipe: two staple lines, one seed line
# and three ineligible classes, in request order.
BASKET_FIVE_LINE = [
    line_item("MILK-GAL", "STAPLE_FOOD", 399, 2),
    line_item("BEER-6PK", "ALCOHOL", 1099, 1),
    line_item("SOAP-BAR", "NONFOOD", 249, 3),
    line_item("TOMATO-SEED", "SEED_PLANT", 199, 1),
    line_item("ROTISSERIE", "HOT_PREPARED", 899, 1),
]

SALE_VOID = [line_item("RICE-5LB", "STAPLE_FOOD", 600, 1)]
SALE_KEEP = [line_item("RICE-1", "STAPLE_FOOD", 500, 2)]


def _authorize(owner, store):
    """Walk an already-registered store to APPROVED, which is what the pricing
    freeze test needs after its order is already on file."""
    application = create_application(owner, refresh_store(store["id"]))
    submit_application(application, owner)
    inspector = create_inspector()
    visit = schedule_visit(application, inspector)
    start_visit(visit, inspector)
    submit_findings(visit, inspector)
    decide_application(application)
    return refresh_store(store["id"])


def test_store_crud_round_trip_recomputes_criterion_b_and_bumps_the_version():
    """Registering, reading, editing and listing the one editable entity: the edit
    drives the staple share from 5,555 basis points to exactly 5,000, which flips
    the sales-share criterion off because the boundary is exclusive.

    The specification derives the share on registration -- "`staple_sales_bps` is
    the store's staple share of sales in basis points: take the annual staple
    sales figure, multiply by 10,000, divide by the annual gross sales figure, and
    take the floor of the result. `criterion_b_pass` is true exactly when
    `staple_sales_bps` is **strictly greater** than 5,000" -- and re-derives it on
    the edit: "A successful edit recomputes `staple_sales_bps` and
    `criterion_b_pass` from the new sales figures and advances the store's
    `version` by one". 18,000,000 of 36,000,000 is exactly 5,000 basis points, and
    "A store sitting at exactly 5,000 basis points **fails**".

    Design: Corner/endpoints/store_crud_round_trip_recomputes_criterion_b_and_bumps_the_version
    """
    owner = create_owner()
    owner_h = owner_headers(owner)

    store = validate_success(
        api_client.create_store(store_payload(owner["id"]), owner_h), 201
    )
    assert_fields(
        store,
        {"staple_sales_bps": 5555, "criterion_b_pass": True, "version": 1},
        "registered store",
    )

    read = validate_success(api_client.get_store(store["id"], owner_h))
    assert_fields(
        read,
        {
            "id": store["id"],
            "store_name": "Rio Convenience",
            "tax_rate_bps": 825,
            "hardship_designated": True,
            "staple_sales_bps": 5555,
            "criterion_b_pass": True,
        },
        "store read",
    )

    patched = validate_success(
        api_client.update_store(
            store["id"],
            store_patch_payload(
                store["version"],
                store_name="Rio Convenience #1",
                annual_staple_sales_cents=18000000,
            ),
            owner_h,
        )
    )
    assert_fields(
        patched,
        {
            "staple_sales_bps": 5000,
            "criterion_b_pass": False,
            "store_name": "Rio Convenience #1",
            "version": store["version"] + 1,
        },
        "patched store",
    )
    assert_instant(patched["updated_at"], AUG_01, "patched store updated_at")

    listed = api_client.list_stores(
        owner_h,
        {
            "owner_id": owner["id"],
            "store_type": "CONVENIENCE",
            "limit": 10,
            "offset": 0,
        },
    )
    page, meta = validate_paginated(listed)
    assert meta["total_count"] == 1, meta
    assert meta["has_more"] is False, meta
    assert page[0]["store_name"] == "Rio Convenience #1", page[0]


def test_equipment_order_action_endpoints_place_fulfill_and_cancel():
    """Two orders on one authorized store exercise all three order actions: the
    unsubsidized register order is placed and then fulfilled, while the receipt
    paper order that carries the handling fee is cancelled straight out of DRAFT.

    The specification fixes the catalogue -- "a `COMMERCIAL_POS_INTEGRATION` at
    $1,850.00 ... and a `RECEIPT_PAPER_CASE` at $40.00" -- excludes both from the
    subsidy: "Commercial point-of-sale integration and receipt paper are never
    subsidized." The fee follows the pre-subsidy-adjusted net: "`handling_fee_cents`
    is 0 when `net_equipment_cents` is 0, 0 when `net_equipment_cents` is at least
    $250.00, and $15.00 otherwise." And the actions differ in what they accept:
    "A placed order may then be marked shipped, moving to `FULFILLED`. An order in
    either `DRAFT` or `PLACED` may be cancelled".

    Design: Corner/endpoints/equipment_order_action_endpoints_place_fulfill_and_cancel
    """
    context = authorized_store()

    register_order = created(
        api_client.create_equipment_order(
            equipment_order_payload(
                context.store_id, [order_line("COMMERCIAL_POS_INTEGRATION", 1)]
            ),
            context.owner_h,
        )
    )
    paper_order = created(
        api_client.create_equipment_order(
            equipment_order_payload(
                context.store_id, [order_line("RECEIPT_PAPER_CASE", 2)]
            ),
            context.owner_h,
        )
    )
    assert_fields(
        register_order,
        {
            "subtotal_cents": 185000,
            "subsidy_cents": 0,
            "net_equipment_cents": 185000,
            "handling_fee_cents": 0,
            "total_due_cents": 185000,
        },
        "register order",
    )
    assert_fields(
        paper_order,
        {
            "subtotal_cents": 8000,
            "subsidy_cents": 0,
            "net_equipment_cents": 8000,
            "handling_fee_cents": 1500,
            "total_due_cents": 9500,
        },
        "paper order",
    )

    ok(api_client.place_equipment_order(register_order["id"], context.owner_h))
    fulfilled = ok(api_client.fulfill_equipment_order(register_order["id"], ADMIN))
    cancelled = ok(
        api_client.cancel_equipment_order(
            paper_order["id"], cancel_order_payload(), context.owner_h
        )
    )

    assert fulfilled["status"] == "FULFILLED", fulfilled
    assert_instant(fulfilled["placed_at"], AUG_01, "fulfilled order placed_at")
    assert_fields(
        cancelled,
        {
            "status": "CANCELLED",
            "cancel_reason_code": "RETAILER_REQUEST",
            "placed_at": None,
        },
        "cancelled order",
    )

    filtered = api_client.list_equipment_orders(
        context.owner_h, {"store_id": context.store_id, "status": "FULFILLED"}
    )
    assert data_ids(filtered) == [register_order["id"]], "FULFILLED filter"
    assert_row_count(filtered, 1)


def test_order_pricing_is_computed_at_draft_and_frozen_by_place_not_re_derived():
    """An order drafted while the store was unauthorized keeps its unsubsidized
    price through the authorization and the later placement, while an identical
    order drafted afterwards is fully subsidized.

    The subsidy test reads the store as it stands at pricing time -- "the store's
    `authorization_status` must be `AUTHORIZED` **and** its
    `annual_gross_sales_cents` must be at or below $5,000,000.00 ... When either
    conjunct fails, `subsidy_cents` is 0" -- and placement neither re-prices nor
    proceeds without authorization: it "requires the store's
    `authorization_status` to be `AUTHORIZED` -- otherwise
    `ERR_STORE_NOT_AUTHORIZED` ... and **freezes** `subtotal_cents`,
    `subsidy_cents`, `net_equipment_cents`, `handling_fee_cents` and
    `total_due_cents` as they stood."

    Design: Corner/endpoints/order_pricing_is_computed_at_draft_and_frozen_by_place_not_re_derived
    """
    owner = create_owner()
    owner_h = owner_headers(owner)
    store = create_store(owner)

    early_order = created(
        api_client.create_equipment_order(
            equipment_order_payload(
                store["id"], [order_line("EBT_ONLY_WIRELESS_TERMINAL", 1)]
            ),
            owner_h,
        )
    )
    unpriced_snapshot = {
        "subtotal_cents": 42500,
        "subsidy_cents": 0,
        "net_equipment_cents": 42500,
        "handling_fee_cents": 0,
        "total_due_cents": 42500,
    }
    assert_fields(early_order, unpriced_snapshot, "order drafted before authorization")

    refused = api_client.place_equipment_order(early_order["id"], owner_h)
    validate_error(refused, ApiErrorId.ERR_STORE_NOT_AUTHORIZED.value, 403)
    assert refresh_order(early_order["id"])["status"] == "DRAFT"

    _authorize(owner, store)

    placed = ok(api_client.place_equipment_order(early_order["id"], owner_h))
    assert placed["status"] == "PLACED", placed
    assert_fields(placed, unpriced_snapshot, "frozen order")

    late_order = created(
        api_client.create_equipment_order(
            equipment_order_payload(
                store["id"], [order_line("EBT_ONLY_WIRELESS_TERMINAL", 1)]
            ),
            owner_h,
        )
    )
    assert_fields(
        late_order,
        {
            "subtotal_cents": 42500,
            "subsidy_cents": 42500,
            "net_equipment_cents": 0,
            "handling_fee_cents": 0,
            "total_due_cents": 0,
        },
        "order drafted after authorization",
    )


def test_terminal_deployment_links_store_and_terminal_and_needs_both_to_exist():
    """The junction write validates each side on its own -- an unknown terminal and
    an unknown store each draw their own 404 -- and the surviving link is reachable
    from both list directions with the unit and the depot counters moved.

    Both codes come from the reference-existence rule: "Every reference supplied in
    the request body must resolve, checked in the field order the endpoint
    declares, yielding `ERR_OWNER_NOT_FOUND`, `ERR_STORE_NOT_FOUND`, ...
    `ERR_TERMINAL_NOT_FOUND` ... (all 404)." The successful write is specified as
    "A new commitment lands in `RESERVED`. If this is the unit's first open
    commitment, the unit moves from `IN_STOCK` to `RESERVED` and the depot counters
    are recomputed", where "Each of the four named counters is the count of that
    depot's terminals in the matching status, and `units_in_stock` is the
    residual", and activation -- which alone "increments the store's
    `active_terminal_count`" -- has not happened.

    Design: Corner/endpoints/terminal_deployment_links_store_and_terminal_and_needs_both_to_exist
    """
    context = authorized_store()
    depot = create_depot()
    terminal = create_terminal(depot)

    unknown_terminal = api_client.create_terminal_deployment(
        deployment_payload(
            context.store_id,
            NON_EXISTENT_UUID,
            deploy_start=AUG_05,
            deploy_end=AUG_25,
        ),
        ADMIN,
    )
    validate_error(unknown_terminal, ApiErrorId.ERR_TERMINAL_NOT_FOUND.value, 404)

    unknown_store = api_client.create_terminal_deployment(
        deployment_payload(
            NON_EXISTENT_UUID,
            terminal["id"],
            deploy_start=AUG_05,
            deploy_end=AUG_25,
        ),
        ADMIN,
    )
    validate_error(unknown_store, ApiErrorId.ERR_STORE_NOT_FOUND.value, 404)

    deployment = created(
        api_client.create_terminal_deployment(
            deployment_payload(
                context.store_id,
                terminal["id"],
                deploy_start=AUG_05,
                deploy_end=AUG_25,
            ),
            ADMIN,
        )
    )
    assert_fields(
        deployment, {"status": "RESERVED", "activated_at": None}, "new deployment"
    )

    by_store = api_client.list_terminal_deployments(
        ADMIN, {"store_id": context.store_id}
    )
    assert data_ids(by_store) == [deployment["id"]], "store direction"
    assert_row_count(by_store, 1)
    by_terminal = api_client.list_terminal_deployments(
        ADMIN, {"terminal_id": terminal["id"], "status": "RESERVED"}
    )
    assert data_ids(by_terminal) == [deployment["id"]], "terminal direction"
    assert_row_count(by_terminal, 1)

    assert refresh_terminal(terminal["id"])["status"] == "RESERVED"
    assert_depot_conservation(
        refresh_depot(depot["id"]),
        {"units_reserved": 1, "units_in_stock": 4, "units_deployed": 0},
    )
    assert refresh_store(context.store_id)["active_terminal_count"] == 0


def test_penalty_ledger_is_a_computed_read_that_matches_the_case_balance():
    """The ledger sub-resource returns the assessment and the remittance in
    creation order with their running balances, filters by entry type, and agrees
    with both the case's and the owner's outstanding balance.

    The specification pins the row contents -- "an `entry_type` of `CMP_ASSESSED`,
    `CMP_PAYMENT` or `CMP_ABATEMENT`, a signed `amount_cents` -- positive for an
    assessment, negative for a payment or an abatement -- a `reason_code` of
    `DETERMINATION`, `RETAILER_REMITTANCE` or `REVIEW_REVERSAL`, and a
    `balance_after_cents` giving the running balance through that row" -- and the
    two rollups: "A case's `cmp_outstanding_cents` always equals the sum of
    `amount_cents` over that case's ledger entries. An owner's
    `cmp_outstanding_cents` always equals the sum of `cmp_outstanding_cents` over
    every sanction case attached to any store that owner controls."

    Design: Corner/endpoints/penalty_ledger_is_a_computed_read_that_matches_the_case_balance
    """
    context = authorized_store()
    four_closed_periods(context.store_id)
    case = replied_case(context, with_election=True)
    issue_determination(case["id"], "CMP_IN_LIEU")
    created(
        api_client.create_cmp_payment(
            case["id"], cmp_payment_payload(100000), context.owner_h
        )
    )

    unfiltered = api_client.list_penalty_ledger(
        case["id"], context.owner_h, {"limit": 10, "offset": 0}
    )
    entries, meta = validate_paginated(unfiltered)
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is False, meta
    assert_fields(
        entries[0],
        {
            "entry_type": "CMP_ASSESSED",
            "amount_cents": 423456,
            "reason_code": "DETERMINATION",
            "balance_after_cents": 423456,
        },
        "assessment row",
    )
    assert_fields(
        entries[1],
        {
            "entry_type": "CMP_PAYMENT",
            "amount_cents": -100000,
            "reason_code": "RETAILER_REMITTANCE",
            "balance_after_cents": 323456,
        },
        "remittance row",
    )

    payments = api_client.list_penalty_ledger(
        case["id"], ANALYST, {"entry_type": "CMP_PAYMENT"}
    )
    payment_rows = assert_row_count(payments, 1)
    assert payment_rows[0]["id"] == entries[1]["id"], payment_rows

    final_case = refresh_case(case["id"])
    assert final_case["cmp_outstanding_cents"] == 323456, final_case
    assert_ledger_conservation(entries, final_case)
    assert refresh_owner(context.owner_id)["cmp_outstanding_cents"] == 323456


def test_pos_basket_is_written_atomically_with_flagged_lines_in_request_order():
    """The five-line basket is scored in one shot: the tax rate is applied once to
    the ineligible sum, the household is charged only what the sale requires out of
    a larger offer, and the flagged skus come back in the order they arrived.

    The specification pins the order of operations -- "`tax_cents` is the ineligible
    subtotal multiplied by the store's `tax_rate_bps`, divided by 10,000, and
    rounded half up to whole cents ... the ineligible extended amounts are summed
    first and the rate is applied once to that sum, never per line" -- and the
    clamp: "`other_tender_cents` is set to the **required** amount, not to the
    amount offered -- the register takes what it needs and no more". Benefits fill
    the eligible bucket first: "`ebt_tender_cents` is the **lesser** of
    `eligible_subtotal_cents` and `snap_benefit_available_cents`."

    Design: Corner/endpoints/pos_basket_is_written_atomically_with_flagged_lines_in_request_order
    """
    context = authorized_store()
    equipment = active_equipment(context.store)

    sale = created(
        api_client.create_pos_transaction(
            pos_transaction_payload(
                context.store_id,
                equipment.deployment_id,
                line_items=BASKET_FIVE_LINE,
                snap_benefit_available_cents=997,
                other_tender_offered_cents=5000,
                household_ebt_card_last4="6120",
            ),
            context.clerk_h,
        )
    )

    assert_fields(
        sale,
        {
            "status": "AUTHORIZED",
            "eligible_subtotal_cents": 997,
            "ineligible_subtotal_cents": 2745,
            "tax_cents": 226,
            "ebt_tender_cents": 997,
            "other_tender_cents": 2971,
            "split_tender_applied": True,
        },
        "five-line basket",
    )
    assert sale["flagged_line_skus"] == ["BEER-6PK", "SOAP-BAR", "ROTISSERIE"], sale[
        "flagged_line_skus"
    ]
    assert_row_count(
        api_client.list_pos_transactions(ADMIN, {"store_id": context.store_id}), 1
    )


def test_no_access_action_releases_the_inspector_and_holds_the_application():
    """The alternate visit outcome is its own action: the visit ends in a terminal
    state with none of the findings figures computed, the inspector's hour comes
    back, and the application burns a deficiency cycle.

    The specification says "When an inspector cannot gain entry, the visit advances
    from `IN_PROGRESS` to `NO_ACCESS` ... This releases the visit's minutes from the
    inspector's `committed_minutes` and consumes a deficiency cycle exactly as a
    failed finding does -- pushing the application to `PENDING_DOCUMENTS` with
    `hold_reason_code` set to `NO_ACCESS` while cycles remain", and the minute
    arithmetic is exact: "cancelling the visit, submitting its findings, or
    recording no-access lowers it by exactly the same amount."

    Design: Corner/endpoints/no_access_action_releases_the_inspector_and_holds_the_application
    """
    context = pending_visit_application()

    visit = ok(api_client.record_no_access(context.visit["id"], context.inspector_h))

    assert_fields(
        visit,
        {
            "status": "NO_ACCESS",
            "findings_submitted_at": None,
            "verified_criterion_a_pass": None,
            "depth_of_stock_pass": None,
            "shelf_discrepancy_bps": None,
        },
        "no-access visit",
    )
    assert_inspector_minutes(refresh_inspector(context.inspector["id"]), 0)
    assert_fields(
        refresh_application(context.application["id"]),
        {
            "status": "PENDING_DOCUMENTS",
            "deficiency_cycle_count": 1,
            "hold_reason_code": "NO_ACCESS",
        },
        "held application",
    )
    assert_row_count(
        api_client.list_store_visits(
            ANALYST,
            {"application_id": context.application["id"], "status": "NO_ACCESS"},
        ),
        1,
    )


def test_void_action_is_conditional_on_the_covering_period_still_being_open():
    """The same void request that succeeds against the open August period is
    refused once that period closes, and the surviving sale keeps its authorized
    status while the voided one drops out of the period's own aggregates.

    Voiding is gated by the period: "An authorized transaction cannot be voided
    once its covering period is closed and a settlement cannot be imported into a
    closed period (`ERR_REDEMPTION_PERIOD_CLOSED`, 409)". The aggregate is defined
    over survivors only -- "transactions belonging to that store, whose `status` is
    `AUTHORIZED` -- declined and voided rows are excluded outright ... Over that
    set, `pos_derived_total_cents` is the sum of `ebt_tender_cents`".

    Design: Corner/endpoints/void_action_is_conditional_on_the_covering_period_still_being_open
    """
    context = authorized_store()
    equipment = active_equipment(context.store)
    period = create_period(context.store_id)
    doomed_sale = created(
        api_client.create_pos_transaction(
            pos_transaction_payload(
                context.store_id,
                equipment.deployment_id,
                line_items=SALE_VOID,
                snap_benefit_available_cents=600,
                other_tender_offered_cents=0,
                household_ebt_card_last4="7781",
            ),
            context.clerk_h,
        )
    )
    surviving_sale = created(
        api_client.create_pos_transaction(
            pos_transaction_payload(
                context.store_id,
                equipment.deployment_id,
                line_items=SALE_KEEP,
                snap_benefit_available_cents=500000,
                other_tender_offered_cents=0,
            ),
            context.clerk_h,
        )
    )

    voided = ok(
        api_client.void_pos_transaction(
            doomed_sale["id"], void_payload("CLERK_ERROR"), context.clerk_h
        )
    )
    assert_fields(
        voided, {"status": "VOIDED", "void_reason_code": "CLERK_ERROR"}, "voided sale"
    )

    advance_clock(SEP_01)
    close_period(period["id"])

    late_void = api_client.void_pos_transaction(
        surviving_sale["id"], void_payload("CLERK_ERROR"), context.clerk_h
    )
    validate_error(late_void, ApiErrorId.ERR_REDEMPTION_PERIOD_CLOSED.value, 409)

    assert_fields(
        refresh_transaction(surviving_sale["id"]),
        {"status": "AUTHORIZED", "void_reason_code": None},
        "surviving sale",
    )
    assert_fields(
        refresh_period(period["id"]),
        {"pos_derived_total_cents": 1000, "pos_derived_transaction_count": 1},
        "closed August period",
    )
    voided_rows = api_client.list_pos_transactions(
        ADMIN, {"store_id": context.store_id, "status": "VOIDED"}
    )
    assert data_ids(voided_rows) == [doomed_sale["id"]], "VOIDED filter"
    assert_row_count(voided_rows, 1)


def test_nested_action_paths_reject_a_well_formed_but_unknown_resource_id():
    """Two unrelated nested action routes each answer with their own not-found code
    for a syntactically valid identifier that names nothing, rather than with a
    state or a schema complaint.

    Path resolution runs first and names the code: "Every identifier in the URL path
    must resolve to an existing row, checked in the order the segments appear,
    yielding `ERR_OWNER_NOT_FOUND`, `ERR_STORE_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, ... `ERR_SANCTION_CASE_NOT_FOUND` ... as
    appropriate (all 404). This applies to every endpoint that has a path
    parameter."

    Design: Corner/endpoints/nested_action_paths_reject_a_well_formed_but_unknown_resource_id
    """
    owner = create_owner()

    unknown_application = api_client.submit_application(
        NON_EXISTENT_UUID, owner_headers(owner)
    )
    application_body = validate_error(
        unknown_application, ApiErrorId.ERR_APPLICATION_NOT_FOUND.value, 404
    )
    unknown_case = api_client.finalize_sanction_case(NON_EXISTENT_UUID, ADMIN)
    case_body = validate_error(
        unknown_case, ApiErrorId.ERR_SANCTION_CASE_NOT_FOUND.value, 404
    )

    for body in (application_body, case_body):
        assert body["error_id"] != ApiErrorId.ERR_INVALID_STATE.value, body
        assert body["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value, body


def test_every_write_and_read_returns_the_declared_envelope():
    """One object write, one list read and one not-found read, checked against the
    three declared envelope shapes and the two meta fields every response carries.

    The specification declares the success envelope with "`response_type` is either
    "object" for a single resource or "array" for a list of resources" and
    "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`,
    `has_more`) are included for list endpoints", the error envelope with
    `response_type` `error` plus "The `error_id` is a unique, machine-readable
    string that identifies the specific error. The `message` provides a
    human-readable explanation of what went wrong.", and requires of both that
    "The `api_request_id` is a server-generated unique identifier for the request
    that starts with `req_`."

    Design: Corner/endpoints/every_write_and_read_returns_the_declared_envelope
    """
    owner = create_owner()

    write_response = api_client.create_store(store_payload(owner["id"]), ADMIN)
    assert write_response.status_code == 201, write_response.text
    write_body = write_response.json()
    assert write_body["response_type"] == "object", write_body
    assert write_body["data"]["id"], write_body

    list_response = api_client.list_stores(ADMIN, {"limit": 1, "offset": 0})
    assert list_response.status_code == 200, list_response.text
    list_body = list_response.json()
    assert list_body["response_type"] == "array", list_body
    assert_fields(
        list_body["meta"],
        {"limit": 1, "offset": 0, "total_count": 1, "has_more": False},
        "list meta",
    )

    missing_response = api_client.get_store(NON_EXISTENT_UUID, ADMIN)
    assert missing_response.status_code == 404, missing_response.text
    missing_body = missing_response.json()
    assert missing_body["response_type"] == "error", missing_body
    assert (
        missing_body["data"]["error_id"] == ApiErrorId.ERR_STORE_NOT_FOUND.value
    ), missing_body
    assert missing_body["data"]["message"], missing_body

    for label, body in (
        ("write", write_body),
        ("list", list_body),
        ("error", missing_body),
    ):
        assert body["meta"]["api_request_id"].startswith("req_"), (label, body["meta"])
        assert_timestamp(
            body["meta"]["api_request_timestamp"], f"{label} api_request_timestamp"
        )
