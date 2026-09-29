"""Error identifiers as a catalogue: every not-found code is per-entity, every
reference resolves before any business rule runs, shape complaints stay out of
the business codes' territory, declines are audit-bearing where refusals are not,
and each clock-driven gate names its own window.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    AUG_02,
    AUG_05,
    AUG_11,
    AUG_21,
    AUG_25,
    ApiErrorId,
    NON_EXISTENT_UUID,
    active_equipment,
    advance_clock,
    api_client,
    administrative_review_payload,
    assert_fields,
    assert_no_rows,
    assert_row_count,
    authorized_store,
    charged_case,
    create_application,
    create_inspector,
    create_owner,
    create_period,
    create_store,
    create_terminal,
    created,
    deployment_payload,
    determination_payload,
    evidence_payload,
    finalize_case,
    inspector_headers,
    investigation_payload,
    issue_determination,
    line_item,
    pos_transaction_payload,
    refresh_period,
    refresh_visit,
    reply_payload,
    schedule_visit,
    store_payload,
    store_visit_payload,
    submit_application,
    validate_error,
    void_payload,
)

TOBACCO_ONLY = [line_item("CIGS-PACK", "TOBACCO", 850, 1)]
STAPLE_AND_SOAP = [
    line_item("MILK-GAL", "STAPLE_FOOD", 399, 1),
    line_item("SOAP-BAR", "NONFOOD", 249, 1),
]
STAPLE_ONLY = [line_item("MILK-GAL", "STAPLE_FOOD", 399, 1)]
UNKNOWN_CLASS_LINE = [line_item("LOTTERY-TICKET", "LOTTERY", 200, 1)]


def test_read_endpoints_return_their_own_not_found_code_for_every_entity():
    """Eight detail reads of well-formed but absent identifiers return eight
    distinct not-found codes rather than one generic complaint.

    The catalogue is per entity: "Every identifier in the URL path must resolve to
    an existing row, checked in the order the segments appear, yielding
    `ERR_OWNER_NOT_FOUND`, `ERR_STORE_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
    `ERR_INSPECTOR_NOT_FOUND`, `ERR_STORE_VISIT_NOT_FOUND`,
    `ERR_POS_TRANSACTION_NOT_FOUND`, `ERR_REDEMPTION_PERIOD_NOT_FOUND`,
    `ERR_INVESTIGATION_NOT_FOUND`, `ERR_SANCTION_CASE_NOT_FOUND`,
    `ERR_DEPOT_NOT_FOUND`, `ERR_TERMINAL_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND` or
    `ERR_EQUIPMENT_ORDER_NOT_FOUND` as appropriate (all 404). This applies to every
    endpoint that has a path parameter."

    Design: Corner/errors/read_endpoints_return_their_own_not_found_code_for_every_entity
    """
    create_owner()

    probes = (
        (api_client.get_owner, ApiErrorId.ERR_OWNER_NOT_FOUND),
        (api_client.get_inspector, ApiErrorId.ERR_INSPECTOR_NOT_FOUND),
        (api_client.get_store_visit, ApiErrorId.ERR_STORE_VISIT_NOT_FOUND),
        (api_client.get_pos_transaction, ApiErrorId.ERR_POS_TRANSACTION_NOT_FOUND),
        (api_client.get_redemption_period, ApiErrorId.ERR_REDEMPTION_PERIOD_NOT_FOUND),
        (api_client.get_investigation, ApiErrorId.ERR_INVESTIGATION_NOT_FOUND),
        (api_client.get_terminal_deployment, ApiErrorId.ERR_DEPLOYMENT_NOT_FOUND),
        (api_client.get_equipment_order, ApiErrorId.ERR_EQUIPMENT_ORDER_NOT_FOUND),
    )

    seen = []
    for read, expected in probes:
        response = read(NON_EXISTENT_UUID, ADMIN)
        body = validate_error(response, expected.value, 404)
        assert response.json()["response_type"] == "error", response.text
        assert body["error_id"] != ApiErrorId.ERR_STORE_NOT_FOUND.value, body
        assert body["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value, body
        seen.append(body["error_id"])

    assert len(set(seen)) == 8, seen


def test_foreign_key_payloads_resolve_the_referenced_entity_before_any_business_rule():
    """Body references and nested action path ids each fail at resolution, before
    the criterion, capacity, interval or state checks the same requests would
    otherwise reach, and nothing is written.

    Body references are checked early and by field order: "Every reference supplied
    in the request body must resolve, checked in the field order the endpoint
    declares, yielding `ERR_OWNER_NOT_FOUND`, `ERR_STORE_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`, `ERR_TERMINAL_NOT_FOUND`,
    `ERR_DEPOT_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`,
    `ERR_REDEMPTION_PERIOD_NOT_FOUND` or `ERR_INVESTIGATION_NOT_FOUND` (all 404)."
    The scheduling payload's declared order puts the application first: "The
    scheduling payload names the `application_id` being verified, the `inspector_id`
    assigned". Path ids resolve on the action routes too: "This applies to every
    endpoint that has a path parameter."

    Design: Corner/errors/foreign_key_payloads_resolve_the_referenced_entity_before_any_business_rule
    """
    owner = create_owner()
    store = create_store(owner)

    phantom_owner = api_client.create_store(
        store_payload(
            NON_EXISTENT_UUID,
            store_name="Phantom Owner Mart",
            store_type="GROCERY",
            checkout_lane_count=3,
            staple_shelf_linear_feet=80,
            annual_gross_sales_cents=50000000,
            annual_staple_sales_cents=30000000,
            tax_rate_bps=None,
            hardship_designated=None,
        ),
        ADMIN,
    )
    owner_body = validate_error(
        phantom_owner, ApiErrorId.ERR_OWNER_NOT_FOUND.value, 404
    )
    assert owner_body["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value, owner_body

    phantom_visit_refs = api_client.create_store_visit(
        store_visit_payload(
            NON_EXISTENT_UUID,
            NON_EXISTENT_UUID,
            window_start="2026-08-01T02:00:00Z",
            window_end="2026-08-01T03:00:00Z",
        ),
        ANALYST,
    )
    visit_refs_body = validate_error(
        phantom_visit_refs, ApiErrorId.ERR_APPLICATION_NOT_FOUND.value, 404
    )
    assert (
        visit_refs_body["error_id"]
        != ApiErrorId.ERR_INSPECTOR_DAILY_LIMIT_EXCEEDED.value
    ), visit_refs_body
    assert visit_refs_body["error_id"] != ApiErrorId.ERR_INVALID_STATE.value

    phantom_period = api_client.create_investigation(
        investigation_payload(
            store["id"],
            opened_reason="ANOMALY_FLAG_L3",
            trigger_period_id=NON_EXISTENT_UUID,
        ),
        ANALYST,
    )
    period_body = validate_error(
        phantom_period, ApiErrorId.ERR_REDEMPTION_PERIOD_NOT_FOUND.value, 404
    )
    assert (
        period_body["error_id"] != ApiErrorId.ERR_TRIGGER_PERIOD_NOT_FLAGGED.value
    ), period_body

    validate_error(
        api_client.activate_deployment(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_DEPLOYMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.place_equipment_order(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_EQUIPMENT_ORDER_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.start_store_visit(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_STORE_VISIT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.void_pos_transaction(NON_EXISTENT_UUID, void_payload(), ADMIN),
        ApiErrorId.ERR_POS_TRANSACTION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.add_evidence(NON_EXISTENT_UUID, evidence_payload(), ANALYST),
        ApiErrorId.ERR_INVESTIGATION_NOT_FOUND.value,
        404,
    )

    assert_row_count(api_client.list_stores(ADMIN, {"owner_id": owner["id"]}), 1)


def test_malformed_requests_are_rejected_with_invalid_request_and_write_nothing():
    """A negative money input, an unknown item class, an over-max page size and a
    payment missing its amount are all shape complaints, and none of them is the
    business code that the same endpoint would otherwise raise.

    The shape gate is one rule with one code: "Required fields present, types
    correct, enum values within their declared sets, numeric bounds honoured ... --
    otherwise `ERR_INVALID_REQUEST` (400). This applies to every write endpoint."
    The bounds it enforces here are declared: "Both money inputs must be at least
    zero", "Nine item classes exist" and "`limit` controls page size: it defaults to
    10, may be no lower than 1 and no higher than 100."

    Design: Corner/errors/malformed_requests_are_rejected_with_invalid_request_and_write_nothing
    """
    context = authorized_store()
    equipment = active_equipment(context.store)
    case = charged_case(context)

    negative_tender = api_client.create_pos_transaction(
        pos_transaction_payload(
            context.store_id,
            equipment.deployment_id,
            line_items=STAPLE_ONLY,
            snap_benefit_available_cents=1000,
            other_tender_offered_cents=-100,
            household_ebt_card_last4="1234",
        ),
        context.clerk_h,
    )
    validate_error(negative_tender, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    unknown_class = api_client.create_pos_transaction(
        pos_transaction_payload(
            context.store_id,
            equipment.deployment_id,
            line_items=UNKNOWN_CLASS_LINE,
            snap_benefit_available_cents=1000,
            other_tender_offered_cents=1000,
            household_ebt_card_last4="1234",
        ),
        context.clerk_h,
    )
    class_body = validate_error(unknown_class, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert class_body["error_id"] != ApiErrorId.ERR_NO_ELIGIBLE_ITEMS.value, class_body

    over_max_limit = api_client.list_pos_transactions(
        ANALYST, {"store_id": context.store_id, "limit": 500}
    )
    validate_error(over_max_limit, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    amountless_payment = api_client.create_cmp_payment(case["id"], {}, context.owner_h)
    payment_body = validate_error(
        amountless_payment, ApiErrorId.ERR_INVALID_REQUEST.value, 400
    )
    assert payment_body["error_id"] != ApiErrorId.ERR_CMP_OVERPAYMENT.value, payment_body

    assert_no_rows(
        api_client.list_pos_transactions(ADMIN, {"store_id": context.store_id})
    )
    assert_no_rows(api_client.list_penalty_ledger(case["id"], ADMIN))


def test_declined_transactions_persist_while_rejected_ones_leave_no_trace():
    """Two declines are recorded as rows carrying their reason codes and zeroed
    tender, while the sale refused by the deployment gate writes nothing -- three
    failed sales, exactly two rows.

    A decline is a written outcome: "the transaction is created with `status`
    `DECLINED` and `decline_reason_code` `NO_ELIGIBLE_ITEMS`, all tender figures are
    recorded as 0, and the call returns `ERR_NO_ELIGIBLE_ITEMS`", and likewise "the
    transaction is created with `status` `DECLINED` and `decline_reason_code`
    `INSUFFICIENT_SPLIT_TENDER`, both `ebt_tender_cents` and `other_tender_cents`
    are recorded as 0, and the call returns `ERR_SPLIT_TENDER_SHORTFALL`." The gate
    that precedes the arithmetic is not a decline: "the named deployment's status
    must be `ACTIVE`, or the sale is refused with
    `ERR_TERMINAL_DEPLOYMENT_NOT_ACTIVE`".

    Design: Corner/errors/declined_transactions_persist_while_rejected_ones_leave_no_trace
    """
    context = authorized_store()
    equipment = active_equipment(context.store)
    second_terminal = create_terminal(
        equipment.depot, serial_number="EBT-0002", model="EBT_ONLY_DIAL"
    )
    reserved = created(
        api_client.create_terminal_deployment(
            deployment_payload(
                context.store_id,
                second_terminal["id"],
                deploy_start=AUG_05,
                deploy_end=AUG_25,
            ),
            ADMIN,
        )
    )

    no_eligible = api_client.create_pos_transaction(
        pos_transaction_payload(
            context.store_id,
            equipment.deployment_id,
            line_items=TOBACCO_ONLY,
            snap_benefit_available_cents=5000,
            other_tender_offered_cents=5000,
            household_ebt_card_last4="3300",
        ),
        context.clerk_h,
    )
    validate_error(no_eligible, ApiErrorId.ERR_NO_ELIGIBLE_ITEMS.value, 422)

    shortfall = api_client.create_pos_transaction(
        pos_transaction_payload(
            context.store_id,
            equipment.deployment_id,
            line_items=STAPLE_AND_SOAP,
            snap_benefit_available_cents=399,
            other_tender_offered_cents=100,
            household_ebt_card_last4="3300",
        ),
        context.clerk_h,
    )
    validate_error(shortfall, ApiErrorId.ERR_SPLIT_TENDER_SHORTFALL.value, 422)

    on_reserved = api_client.create_pos_transaction(
        pos_transaction_payload(
            context.store_id,
            reserved["id"],
            line_items=STAPLE_ONLY,
            snap_benefit_available_cents=399,
            other_tender_offered_cents=0,
            household_ebt_card_last4="3300",
        ),
        context.clerk_h,
    )
    validate_error(
        on_reserved, ApiErrorId.ERR_TERMINAL_DEPLOYMENT_NOT_ACTIVE.value, 409
    )

    persisted = assert_row_count(
        api_client.list_pos_transactions(ADMIN, {"store_id": context.store_id}), 2
    )
    assert [row["status"] for row in persisted] == ["DECLINED", "DECLINED"], persisted
    by_reason = {row["decline_reason_code"]: row for row in persisted}
    assert_fields(
        by_reason["NO_ELIGIBLE_ITEMS"],
        {
            "eligible_subtotal_cents": 0,
            "ineligible_subtotal_cents": 850,
            "ebt_tender_cents": 0,
            "other_tender_cents": 0,
        },
        "all-ineligible decline",
    )
    assert by_reason["NO_ELIGIBLE_ITEMS"]["flagged_line_skus"] == ["CIGS-PACK"]
    assert_fields(
        by_reason["INSUFFICIENT_SPLIT_TENDER"],
        {
            "eligible_subtotal_cents": 399,
            "ineligible_subtotal_cents": 249,
            "tax_cents": 21,
            "ebt_tender_cents": 0,
            "other_tender_cents": 0,
        },
        "split-tender decline",
    )


def test_temporal_gate_codes_are_distinct_and_each_names_its_own_window():
    """Six clock-driven refusals raised from one fixture keep six distinct
    identifiers: a visit before its window, a period before its end, a determination
    while the reply window is open, a reply after it shut, a review request past its
    deadline, and an enforcement before its effective date.

    The clock rules are one paragraph with several edges: "All three windows are
    **exclusive at the closing edge**: an action permitted "before" a deadline is
    refused when the logical clock has reached the deadline instant exactly.
    Conversely, actions gated on a start instant are **inclusive**: a visit may be
    started when the clock is at or after `window_start`, a monitoring period may be
    closed when the clock is at or after `period_end`, and enforcement may proceed
    when the clock is at or after `effective_date`." The deadlines themselves are
    fixed at their triggering events: "A charge letter fixes `reply_due_at` and
    `cmp_election_due_at` at ten days after `charge_letter_sent_at`. A determination
    fixes `admin_review_due_at` at ten days after `determined_at`. Finalization of a
    disqualification fixes `effective_date` at thirty days after
    `final_decision_at`."

    Design: Corner/errors/temporal_gate_codes_are_distinct_and_each_names_its_own_window
    """
    context = authorized_store()
    period = create_period(context.store_id)
    case = charged_case(context)

    other_owner = create_owner(legal_name="Rio Fresh Foods LLC")
    other_store = create_store(other_owner, store_name="Rio Grocery Annex")
    other_application = create_application(other_owner, other_store)
    submit_application(other_application, other_owner)
    other_inspector = create_inspector(full_name="Dana Ruiz")
    tomorrow_visit = schedule_visit(
        other_application,
        other_inspector,
        window_start=AUG_02,
        window_end="2026-08-02T02:00:00Z",
    )

    early_start = api_client.start_store_visit(
        tomorrow_visit["id"], inspector_headers(other_inspector)
    )
    visit_body = validate_error(
        early_start, ApiErrorId.ERR_VISIT_WINDOW_NOT_OPEN.value, 409
    )
    assert refresh_visit(tomorrow_visit["id"])["status"] == "SCHEDULED"

    early_close = api_client.close_redemption_period(period["id"], ANALYST)
    period_body = validate_error(
        early_close, ApiErrorId.ERR_PERIOD_NOT_ELAPSED.value, 409
    )
    assert refresh_period(period["id"])["status"] == "OPEN"

    early_determination = api_client.issue_determination(
        case["id"], determination_payload("TEMPORARY_DISQUALIFICATION"), ADMIN
    )
    reply_open_body = validate_error(
        early_determination, ApiErrorId.ERR_REPLY_WINDOW_OPEN.value, 409
    )

    advance_clock(AUG_11)
    late_reply = api_client.file_reply(
        case["id"], reply_payload(reply_text="Late reply."), context.owner_h
    )
    reply_closed_body = validate_error(
        late_reply, ApiErrorId.ERR_REPLY_WINDOW_CLOSED.value, 409
    )

    issue_determination(case["id"], "TEMPORARY_DISQUALIFICATION")
    advance_clock(AUG_21)
    late_review = api_client.request_administrative_review(
        case["id"],
        administrative_review_payload(grounds_text="Filed one day late."),
        context.owner_h,
    )
    review_body = validate_error(
        late_review, ApiErrorId.ERR_ADMIN_REVIEW_WINDOW_CLOSED.value, 409
    )

    finalize_case(case["id"])
    early_enforcement = api_client.enforce_sanction_case(case["id"], ADMIN)
    enforce_body = validate_error(
        early_enforcement, ApiErrorId.ERR_ENFORCEMENT_NOT_DUE.value, 409
    )

    codes = [
        visit_body["error_id"],
        period_body["error_id"],
        reply_open_body["error_id"],
        reply_closed_body["error_id"],
        review_body["error_id"],
        enforce_body["error_id"],
    ]
    assert len(set(codes)) == 6, codes
