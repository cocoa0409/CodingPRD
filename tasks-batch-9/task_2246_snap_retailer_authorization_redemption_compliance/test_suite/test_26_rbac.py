"""Role-based access control: exclusive operations refused across roles and
granted to their owners, entity-backed identities scoped to their own store and
their own visit, role-gated reads, and the single anonymous capability.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    ANALYST_ALT,
    ANON,
    AUG_01,
    AUG_11,
    ApiErrorId,
    REVIEWER,
    active_equipment,
    administrative_review_payload,
    advance_clock,
    api_client,
    application_payload,
    assert_fields,
    assert_no_rows,
    assert_inspector_minutes,
    assert_row_count,
    authorized_store,
    charge_letter_payload,
    clerk_headers,
    clock_payload,
    cmp_election_payload,
    conclude_payload,
    create_application,
    create_depot,
    create_inspector,
    create_owner,
    create_store,
    create_terminal,
    data_ids,
    decision_payload,
    decide_application,
    depot_payload,
    deployment_payload,
    equipment_order_payload,
    evidence_payload,
    findings_payload,
    four_closed_periods,
    inspector_headers,
    inspector_payload,
    investigation_payload,
    issue_charge_letter,
    issue_determination,
    line_item,
    open_case,
    order_line,
    owner_headers,
    owner_payload,
    pending_visit_application,
    pos_transaction_payload,
    redemption_period_payload,
    refresh_application,
    refresh_case,
    refresh_inspector,
    refresh_investigation,
    refresh_store,
    refresh_visit,
    reply_payload,
    review_decision_payload,
    sanction_case_payload,
    schedule_visit,
    start_visit,
    store_payload,
    store_visit_payload,
    submit_application,
    submit_findings,
    substantiated_ineligible_investigation,
    terminal_payload,
    validate_error,
    validate_success,
    INV_PASS,
)

MILK_LINE = [line_item("MILK-GAL", "STAPLE_FOOD", 399, 1)]


def test_exclusive_operations_are_refused_to_every_other_role():
    """Six cross-role attempts on one fixture, each by an authenticated caller
    whose target is in an actionable state, are all refused with the same role code
    -- including the administrator's attempt at the review decision, so there is no
    admin override of the review seat.

    The gate is the endpoint's own role list: "2. **Role permission.**
    `X-User-Role` must appear in the called endpoint's role list -- otherwise
    `ERR_ROLE_NOT_PERMITTED` (403)." The administrator's one hole is explicit:
    "`FnsAdmin` may exercise every write endpoint in this specification and every
    read endpoint, with exactly one exclusion: it may not decide an administrative
    review." So are the two entity-backed exclusives: "Ringing up and voiding EBT
    sales are exclusive to `StoreClerk` and `FnsAdmin`." and "Starting a visit,
    submitting findings and recording no-access are exclusive to `Inspector` and
    `FnsAdmin`."

    Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role
    """
    context = authorized_store()
    equipment = active_equipment(context.store)
    under_review = pending_visit_application()
    submit_findings(under_review.visit, under_review.inspector)
    in_progress = pending_visit_application()

    investigation = substantiated_ineligible_investigation(context.store_id)
    case = open_case(investigation["id"], "INELIGIBLE_ITEMS_HARDSHIP")
    issue_charge_letter(case["id"])
    advance_clock(AUG_11)
    issue_determination(case["id"], "TEMPORARY_DISQUALIFICATION")
    validate_success(
        api_client.request_administrative_review(
            case["id"],
            administrative_review_payload(grounds_text="The interview is hearsay."),
            context.owner_h,
        )
    )
    score_before = refresh_investigation(investigation["id"])[
        "trafficking_confidence_score"
    ]

    analyst_decision = api_client.decide_application(
        under_review.application["id"], decision_payload("APPROVED"), ANALYST
    )
    admin_review_decision = api_client.decide_administrative_review(
        case["id"], review_decision_payload("SUSTAINED"), ADMIN
    )
    officer_period = api_client.create_redemption_period(
        redemption_period_payload(context.store_id, period_index=9), REVIEWER
    )
    inspector_sale = api_client.create_pos_transaction(
        pos_transaction_payload(
            context.store_id,
            equipment.deployment_id,
            line_items=MILK_LINE,
            snap_benefit_available_cents=399,
            other_tender_offered_cents=0,
            household_ebt_card_last4="9001",
        ),
        context.inspector_h,
    )
    clerk_start = api_client.start_store_visit(
        in_progress.visit["id"], clerk_headers(context.store)
    )
    owner_evidence = api_client.add_evidence(
        investigation["id"],
        evidence_payload(evidence_type="UNDERCOVER_BUY", observed_at="2026-07-20T00:00:00Z"),
        context.owner_h,
    )

    refusals = {
        "analyst decision": analyst_decision,
        "admin review decision": admin_review_decision,
        "officer period": officer_period,
        "inspector sale": inspector_sale,
        "clerk visit start": clerk_start,
        "owner evidence": owner_evidence,
    }
    for label, response in refusals.items():
        body = validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        assert body["error_id"] == ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, label

    review_body = admin_review_decision.json()["data"]
    assert (
        review_body["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value
    ), review_body
    evidence_body = owner_evidence.json()["data"]
    assert evidence_body["error_id"] != ApiErrorId.ERR_INVALID_STATE.value, evidence_body

    assert refresh_application(under_review.application["id"])["status"] == "UNDER_REVIEW"
    assert refresh_case(case["id"])["admin_review_outcome"] is None
    assert refresh_visit(in_progress.visit["id"])["status"] == "IN_PROGRESS"
    assert_no_rows(
        api_client.list_pos_transactions(ADMIN, {"store_id": context.store_id})
    )
    assert_no_rows(
        api_client.list_redemption_periods(ADMIN, {"store_id": context.store_id})
    )
    assert (
        refresh_investigation(investigation["id"])["trafficking_confidence_score"]
        == score_before
    )


def test_each_role_performs_its_own_exclusive_operations_successfully():
    """The positive mirror of the denial sweep: the clock, the authorization
    decision, inspector and hardware provisioning, the period, the sale, the
    evidence, the case, the election and the reply all land 2xx when each is issued
    by the role that owns it.

    Each role's own list is spelled out: "`FnsAdmin` may exercise every write
    endpoint in this specification and every read endpoint, with exactly one
    exclusion: it may not decide an administrative review." "An analyst opens
    monitoring periods, imports settlements, closes periods, opens investigations,
    appends evidence and concludes investigations, and schedules or cancels store
    visits." "Starting a visit, submitting findings and recording no-access are
    exclusive to `Inspector` and `FnsAdmin`." "Ringing up and voiding EBT sales are
    exclusive to `StoreClerk` and `FnsAdmin`." And for the retailer: "It is the
    exclusive holder of four operations: filing a charge-letter reply, requesting
    administrative review, filing a penalty election, and remitting a penalty
    payment."

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations_successfully
    """
    owner = validate_success(
        api_client.create_owner(owner_payload(legal_name="Rio Roles LLC"), ANON), 201
    )
    owner_h = owner_headers(owner)
    store = validate_success(
        api_client.create_store(store_payload(owner["id"]), owner_h), 201
    )
    depot = validate_success(
        api_client.create_equipment_depot(depot_payload(), ADMIN), 201
    )

    validate_success(api_client.set_clock(clock_payload(AUG_01), ADMIN))

    application = validate_success(
        api_client.create_application(
            application_payload(
                store["id"], store["version"], reported_inventory_lines=INV_PASS
            ),
            owner_h,
        ),
        201,
    )
    validate_success(api_client.submit_application(application["id"], owner_h))
    inspector = validate_success(
        api_client.create_inspector(inspector_payload(), ADMIN), 201
    )
    inspector_h = inspector_headers(inspector)
    visit = validate_success(
        api_client.create_store_visit(
            store_visit_payload(application["id"], inspector["id"]), ANALYST
        ),
        201,
    )
    validate_success(api_client.start_store_visit(visit["id"], inspector_h))
    validate_success(
        api_client.submit_findings(
            visit["id"],
            findings_payload(observed_inventory_lines=INV_PASS),
            inspector_h,
        )
    )
    validate_success(
        api_client.decide_application(
            application["id"], decision_payload("APPROVED"), ADMIN
        )
    )

    terminal = validate_success(
        api_client.create_ebt_terminal(terminal_payload(depot["id"]), ADMIN), 201
    )
    deployment = validate_success(
        api_client.create_terminal_deployment(
            deployment_payload(store["id"], terminal["id"]), ADMIN
        ),
        201,
    )
    validate_success(api_client.activate_deployment(deployment["id"], ADMIN))
    validate_success(
        api_client.create_redemption_period(
            redemption_period_payload(store["id"]), ANALYST
        ),
        201,
    )
    # The election quotes the penalty "against the election-time history", so the
    # store needs a closed monitoring pool before the retailer may file one.
    four_closed_periods(store["id"])

    sale = validate_success(
        api_client.create_pos_transaction(
            pos_transaction_payload(
                store["id"],
                deployment["id"],
                line_items=MILK_LINE,
                snap_benefit_available_cents=1000,
                other_tender_offered_cents=0,
                household_ebt_card_last4="7788",
            ),
            clerk_headers(store),
        ),
        201,
    )
    assert sale["status"] == "AUTHORIZED", sale

    investigation = validate_success(
        api_client.create_investigation(
            investigation_payload(store["id"], opened_reason="TIP"), ANALYST
        ),
        201,
    )
    validate_success(
        api_client.add_evidence(
            investigation["id"],
            evidence_payload(
                evidence_type="HOUSEHOLD_INTERVIEW", observed_at="2026-07-15T00:00:00Z"
            ),
            ANALYST,
        )
    )
    validate_success(
        api_client.conclude_investigation(
            investigation["id"], conclude_payload("INELIGIBLE_ITEM_SALES"), ANALYST_ALT
        )
    )

    case = validate_success(
        api_client.create_sanction_case(
            sanction_case_payload(investigation["id"], "INELIGIBLE_ITEMS_HARDSHIP"),
            ADMIN,
        ),
        201,
    )
    charged = validate_success(
        api_client.issue_charge_letter(case["id"], charge_letter_payload(), ADMIN)
    )
    validate_success(
        api_client.create_cmp_election(
            case["id"], cmp_election_payload(charged["version"]), owner_h
        ),
        201,
    )
    validate_success(
        api_client.file_reply(case["id"], reply_payload(), owner_h)
    )

    assert_fields(
        refresh_store(store["id"]),
        {"authorization_status": "AUTHORIZED", "sanction_status": "CHARGED"},
        "store after the full role sweep",
    )


def test_clerk_of_one_store_cannot_ring_a_sale_at_another_store():
    """A clerk carrying store B's identity is refused on store A's ACTIVE
    deployment with the ownership code -- not the role code and not the deployment
    code -- and store A's own clerk then rings the identical basket successfully.

    The clerk's identity is the store row itself: "When `X-User-Role` is
    `StoreClerk`, `X-User-ID` is the `id` of the acting `Store`; a clerk may ring up
    or void a sale only for the store whose `id` equals `X-User-ID`." Acting outside
    that scope has its own code: "When a caller holds a permitted role but is acting
    outside its own scope -- a `RetailerOwner` touching a store its firm does not
    own, a `StoreClerk` ringing up a sale for a different store, or an `Inspector`
    acting on a visit assigned to someone else -- the request is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)." And the ladder puts it before the trading
    and state checks: "5. **Resource ownership.**"

    Design: Corner/rbac/clerk_of_one_store_cannot_ring_a_sale_at_another_store
    """
    context = authorized_store()
    store_b = create_store(context.owner, store_name="Rio Convenience #2")
    application_b = create_application(context.owner, store_b)
    submit_application(application_b, context.owner)
    inspector_b = create_inspector(full_name="Miguel Santos")
    visit_b = schedule_visit(application_b, inspector_b)
    start_visit(visit_b, inspector_b)
    submit_findings(visit_b, inspector_b)
    decide_application(application_b)
    equipment = active_equipment(context.store)

    basket = pos_transaction_payload(
        context.store_id,
        equipment.deployment_id,
        line_items=MILK_LINE,
        snap_benefit_available_cents=399,
        other_tender_offered_cents=0,
        household_ebt_card_last4="4102",
    )

    foreign = api_client.create_pos_transaction(basket, clerk_headers(store_b))
    foreign_body = validate_error(
        foreign, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403
    )
    assert (
        foreign_body["error_id"] != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value
    ), foreign_body
    assert (
        foreign_body["error_id"]
        != ApiErrorId.ERR_TERMINAL_DEPLOYMENT_NOT_ACTIVE.value
    ), foreign_body
    assert_no_rows(
        api_client.list_pos_transactions(ADMIN, {"store_id": context.store_id})
    )

    own = validate_success(
        api_client.create_pos_transaction(basket, clerk_headers(context.store)), 201
    )
    assert_fields(
        own,
        {"status": "AUTHORIZED", "ebt_tender_cents": 399},
        "sale rung by the store's own clerk",
    )
    assert_row_count(
        api_client.list_pos_transactions(ADMIN, {"store_id": context.store_id}), 1
    )


def test_inspector_can_only_act_on_visits_assigned_to_itself():
    """A second ACTIVE inspector is refused on someone else's SCHEDULED visit even
    though its window is open, the refusal moves neither inspector's committed
    minutes, and the assigned inspector then starts the same visit.

    The inspector's identity is the inspector row: "When `X-User-Role` is
    `Inspector`, `X-User-ID` is the `id` of the acting `Inspector`; a visit-scoped
    action is permitted only when the visit's `inspector_id` equals `X-User-ID`."
    Out-of-scope action has its own code: "an `Inspector` acting on a visit assigned
    to someone else -- the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP
    403)." The minutes belong to the assignee alone: "An inspector's
    `committed_minutes` is the sum of `window_minutes` over that inspector's
    `SCHEDULED` and `IN_PROGRESS` visits."

    Design: Corner/rbac/inspector_can_only_act_on_visits_assigned_to_itself
    """
    owner = create_owner()
    store = create_store(owner)
    application = create_application(owner, store)
    submit_application(application, owner)
    assigned = create_inspector(full_name="Dana Ruiz")
    visit = schedule_visit(application, assigned)
    intruder = create_inspector(full_name="Miguel Santos")

    refused = api_client.start_store_visit(visit["id"], inspector_headers(intruder))
    refused_body = validate_error(
        refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403
    )
    assert (
        refused_body["error_id"] != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value
    ), refused_body

    assert refresh_visit(visit["id"])["status"] == "SCHEDULED"
    assert_inspector_minutes(refresh_inspector(intruder["id"]), 0)
    assert_inspector_minutes(refresh_inspector(assigned["id"]), 120)

    started = validate_success(
        api_client.start_store_visit(visit["id"], inspector_headers(assigned))
    )
    assert started["status"] == "IN_PROGRESS", started
    assert refresh_visit(visit["id"])["status"] == "IN_PROGRESS"


def test_read_routes_are_role_gated_and_the_review_officer_has_no_equipment_visibility():
    """All three equipment reads are refused to the review officer with the role
    code while the identical order listing succeeds for the analyst, and the officer
    keeps the case and visit reads its seat does hold.

    Reads carry role lists too: "2. **Role permission.** `X-User-Role` must appear
    in the called endpoint's role list -- otherwise `ERR_ROLE_NOT_PERMITTED` (403)."
    The officer's read surface is enumerated and equipment is not on it: "Deciding an
    administrative review is the officer's sole write capability; beyond that it
    holds read access to owners, stores, applications, store visits, transactions,
    monitoring periods, investigations, sanction cases, elections and penalty
    ledgers."

    Design: Corner/rbac/read_routes_are_role_gated_and_the_review_officer_has_no_equipment_visibility
    """
    context = authorized_store()
    depot = create_depot()
    create_terminal(depot)
    order = validate_success(
        api_client.create_equipment_order(
            equipment_order_payload(
                context.store_id, lines=[order_line("SIGNAGE_PACK", 1)]
            ),
            context.owner_h,
        ),
        201,
    )

    officer_orders = api_client.list_equipment_orders(
        REVIEWER, {"store_id": context.store_id}
    )
    officer_terminals = api_client.list_ebt_terminals(REVIEWER)
    officer_depot = api_client.get_equipment_depot(depot["id"], REVIEWER)
    for label, response in (
        ("equipment orders", officer_orders),
        ("terminals", officer_terminals),
        ("depot detail", officer_depot),
    ):
        body = validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        assert body["error_id"] == ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, label

    analyst_orders = api_client.list_equipment_orders(
        ANALYST, {"store_id": context.store_id}
    )
    assert_row_count(analyst_orders, 1)
    assert data_ids(analyst_orders) == [order["id"]]

    assert_no_rows(api_client.list_sanction_cases(REVIEWER))
    assert_row_count(api_client.list_store_visits(REVIEWER), 1)


def test_anonymous_may_only_register_an_owner():
    """Registering a firm with no identity at all succeeds, and the very next step
    of the workflow is refused under the same role, as is a plain owner read: the
    anonymous seat is write-once and read-never.

    The role has exactly one capability: "`Anonymous` is an unregistered caller and
    may do exactly one thing: create an owner record." The exemption is only for that
    one route: "Both headers are mandatory everywhere with exactly one exception --
    owner registration, which is how an unregistered firm bootstraps itself into the
    program." Everything else is decided by the endpoint's role list: "A call whose
    `X-User-Role` is not among the roles the target endpoint permits is rejected with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." A fresh firm starts clean: "A freshly
    registered owner starts with `permanent_disqualification_count` at 0,
    `cmp_outstanding_cents` at 0, `sanction_flag` at `CLEAR` and `status` at
    `ACTIVE`."

    Design: Corner/rbac/anonymous_may_only_register_an_owner
    """
    owner = validate_success(
        api_client.create_owner(
            owner_payload(legal_name="Anonymous Registrant LLC", tax_id_last4="9911"),
            ANON,
        ),
        201,
    )
    assert_fields(
        owner,
        {
            "status": "ACTIVE",
            "sanction_flag": "CLEAR",
            "permanent_disqualification_count": 0,
            "cmp_outstanding_cents": 0,
        },
        "anonymously registered owner",
    )

    store_attempt = api_client.create_store(
        store_payload(
            owner["id"],
            store_name="Anonymous Mart",
            store_type="GROCERY",
            checkout_lane_count=3,
            staple_shelf_linear_feet=80,
            annual_gross_sales_cents=50000000,
            annual_staple_sales_cents=30000000,
            tax_rate_bps=None,
            hardship_designated=None,
        ),
        ANON,
    )
    validate_error(store_attempt, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    read_attempt = api_client.get_owner(owner["id"], ANON)
    validate_error(read_attempt, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    assert_no_rows(api_client.list_stores(ADMIN))
