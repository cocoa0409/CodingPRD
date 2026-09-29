"""Validation rules at their exact boundaries, one scenario per rule family.

Every scenario drives a single call into one numbered rule of the specification's
ladder and pins both the identifier that comes back and the rows that must not
have moved. Where two rules could plausibly answer, the loser is asserted absent
by name.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    ANALYST_ALT_USER_ID,
    ANALYST_USER_ID,
    ANALYST_ALT,
    INV_PASS,
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    REVIEW_OFFICER_ALT_USER_ID,
    REVIEW_OFFICER_USER_ID,
    REVIEWER,
    REVIEWER_ALT,
    ApiErrorId,
    activate_deployment,
    active_equipment,
    add_evidence,
    administrative_review_payload,
    advance_clock,
    api_client,
    application_payload,
    assert_depot_conservation,
    assert_fields,
    assert_inspector_minutes,
    assert_no_rows,
    assert_row_count,
    authorized_store,
    charge_letter_payload,
    charged_case,
    close_deployment_payload,
    close_period,
    cmp_payment_payload,
    conclude_payload,
    create_application,
    create_depot,
    create_deployment,
    create_inspector,
    create_owner,
    create_period,
    create_store,
    create_terminal,
    created,
    decide_application,
    decision_payload,
    deployment_payload,
    determination_payload,
    elect_cmp,
    enforce_case,
    file_reply,
    finalize_case,
    findings_payload,
    four_closed_periods,
    inventory_line,
    issue_charge_letter,
    issue_determination,
    line_item,
    make_fns_admin_headers,
    ok,
    open_case,
    open_investigation,
    owner_headers,
    owner_payload,
    pending_visit_application,
    pos_transaction_payload,
    redemption_period_payload,
    refresh_application,
    refresh_case,
    refresh_depot,
    refresh_deployment,
    refresh_inspector,
    refresh_investigation,
    refresh_owner,
    refresh_period,
    refresh_store,
    refresh_terminal,
    refresh_transaction,
    refresh_visit,
    replied_case,
    reply_payload,
    reserved_equipment,
    review_decision_payload,
    rows,
    sanction_case_payload,
    schedule_visit,
    settlement_payload,
    start_visit,
    store_visit_payload,
    submit_application,
    submit_findings,
    substantiated_ineligible_investigation,
    substantiated_trafficking_investigation,
    terminal_payload,
    validate_error,
    void_payload,
)

FEB = ("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z")

# Three staple categories carry three varieties each; meat carries eighteen
# units spread over only two varieties, which the desk variant counts as a
# breadth failure however deep the shelf is.
INV_MEAT_TOO_NARROW = INV_PASS[:9] + [
    inventory_line("MEAT_POULTRY_FISH", "CHICKEN", 9, True),
    inventory_line("MEAT_POULTRY_FISH", "TUNA_CAN", 9, False),
]

SALE_1000 = [line_item("RICE-1", "STAPLE_FOOD", 500, 2)]

ALL_INELIGIBLE = [
    line_item("BEER-1", "ALCOHOL", 1200, 1),
    line_item("HOT-1", "HOT_PREPARED", 800, 1),
    line_item("CAT-1", "NONFOOD", 3000, 1),
]


def test_uniqueness_rules_reject_duplicate_serial_period_index_and_second_open_application():
    """A repeated terminal serial, a repeated period index and a second live
    application are each refused by their own uniqueness code.

    Rule 14 of the ladder covers three separate scopes -- a serial unique across
    all non-retired terminals, a period index unique per store, and at most one
    application per store in a non-terminal status -- and each refusal leaves the
    original row as the only one of its kind. The repeated index is offered for an
    April window that overlaps nothing, so the interval family at rule 13 has
    nothing to say and only the duplicate-index code can answer.

    Design: Corner/validations/uniqueness_rules_reject_duplicate_serial_period_index_and_second_open_application
    """
    owner = create_owner()
    store = create_store(owner)
    application = create_application(owner, store)
    depot = create_depot()
    create_terminal(depot, serial_number="EBT-0001")
    create_period(
        store["id"], period_index=1, period_start=FEB[0], period_end=FEB[1]
    )

    duplicate_serial = api_client.create_ebt_terminal(
        terminal_payload(depot["id"], serial_number="EBT-0001", model="EBT_ONLY_DIAL"),
        ADMIN,
    )
    validate_error(
        duplicate_serial, ApiErrorId.ERR_DUPLICATE_TERMINAL_SERIAL.value, 409
    )

    duplicate_index = api_client.create_redemption_period(
        redemption_period_payload(
            store["id"],
            period_index=1,
            period_start="2026-04-01T00:00:00Z",
            period_end="2026-05-01T00:00:00Z",
        ),
        ANALYST,
    )
    index_body = validate_error(
        duplicate_index, ApiErrorId.ERR_DUPLICATE_PERIOD_INDEX.value, 409
    )
    assert index_body["error_id"] != ApiErrorId.ERR_REDEMPTION_PERIOD_OVERLAP.value

    current = refresh_store(store["id"])
    second_application = api_client.create_application(
        application_payload(current["id"], current["version"]), owner_headers(owner)
    )
    validate_error(
        second_application, ApiErrorId.ERR_APPLICATION_ALREADY_OPEN.value, 409
    )

    assert_row_count(
        api_client.list_ebt_terminals(ADMIN, {"depot_id": depot["id"]}), 1
    )
    assert_row_count(
        api_client.list_redemption_periods(ANALYST, {"store_id": store["id"]}), 1
    )
    assert_row_count(
        api_client.list_applications(ADMIN, {"store_id": store["id"]}), 1
    )
    assert_fields(refresh_depot(depot["id"]), {"units_in_stock": 5}, "depot")
    assert refresh_application(application["id"])["status"] == "DRAFT"


def test_overlapping_period_is_rejected_while_an_abutting_period_is_accepted():
    """A period starting inside February's window is refused; one starting exactly
    where February ends is created.

    "A new period conflicts when its start is earlier than an existing period's end
    and the existing start is earlier than the new end, reported as
    `ERR_REDEMPTION_PERIOD_OVERLAP` (409). Abutting periods -- one beginning
    exactly where the previous ends -- are accepted, which is precisely how
    consecutive monitoring periods are built." The half-open window makes the
    shared instant belong to the later period alone.

    Design: Corner/validations/overlapping_period_is_rejected_while_an_abutting_period_is_accepted
    """
    owner = create_owner()
    store = create_store(owner)
    create_period(
        store["id"], period_index=1, period_start=FEB[0], period_end=FEB[1]
    )

    overlapping = api_client.create_redemption_period(
        redemption_period_payload(
            store["id"],
            period_index=5,
            period_start="2026-02-15T00:00:00Z",
            period_end="2026-03-15T00:00:00Z",
        ),
        ANALYST,
    )
    validate_error(
        overlapping, ApiErrorId.ERR_REDEMPTION_PERIOD_OVERLAP.value, 409
    )

    abutting = created(
        api_client.create_redemption_period(
            redemption_period_payload(
                store["id"],
                period_index=6,
                period_start="2026-03-01T00:00:00Z",
                period_end="2026-04-01T00:00:00Z",
            ),
            ANALYST,
        )
    )

    assert_fields(
        abutting,
        {"status": "OPEN", "period_index": 6, "reconciliation_status": "NOT_IMPORTED"},
        "abutting period",
    )
    assert_row_count(
        api_client.list_redemption_periods(ANALYST, {"store_id": store["id"]}), 2
    )


def _two_submitted_applications_and_one_inspector():
    """One owner, two stores, two SUBMITTED applications and a single inspector
    whose 480-minute daily ceiling both bookings must share."""
    owner = create_owner()
    store_a = create_store(owner, store_name="Rio Convenience")
    store_b = create_store(owner, store_name="Rio Corner Market")
    application_a = create_application(owner, store_a)
    submit_application(application_a, owner)
    application_b = create_application(owner, store_b)
    submit_application(application_b, owner)
    return owner, application_a, application_b, create_inspector()


def test_inspector_daily_minute_ceiling_blocks_the_same_day_and_frees_the_next():
    """A 180-minute booking that would push the day to 540 minutes is refused, and
    the identical window on the following date is accepted.

    "An inspector's daily ceiling is measured over the inspector's `SCHEDULED` and
    `IN_PROGRESS` visits whose `window_start` falls on the same UTC calendar date
    as the new visit's `window_start`: the sum of those visits' minutes plus the
    new visit's minutes must be at or below the inspector's `max_daily_minutes`,
    otherwise `ERR_INSPECTOR_DAILY_LIMIT_EXCEEDED` (409)." The refused window
    starts two hours after the long visit ends, well clear of the travel buffer, so
    the conflict code cannot be the answer.

    Design: Corner/validations/inspector_daily_minute_ceiling_blocks_the_same_day_and_frees_the_next
    """
    _owner, application_a, application_b, inspector = (
        _two_submitted_applications_and_one_inspector()
    )
    long_visit = schedule_visit(
        application_a,
        inspector,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T06:00:00Z",
    )

    same_day = api_client.create_store_visit(
        store_visit_payload(
            application_b["id"],
            inspector["id"],
            window_start="2026-08-01T08:00:00Z",
            window_end="2026-08-01T11:00:00Z",
        ),
        ANALYST,
    )
    body = validate_error(
        same_day, ApiErrorId.ERR_INSPECTOR_DAILY_LIMIT_EXCEEDED.value, 409
    )
    assert body["error_id"] != ApiErrorId.ERR_INSPECTOR_WINDOW_CONFLICT.value

    next_day = created(
        api_client.create_store_visit(
            store_visit_payload(
                application_b["id"],
                inspector["id"],
                window_start="2026-08-02T08:00:00Z",
                window_end="2026-08-02T11:00:00Z",
            ),
            ANALYST,
        )
    )

    assert_fields(
        next_day, {"status": "SCHEDULED", "window_minutes": 180}, "next-day visit"
    )
    assert_inspector_minutes(refresh_inspector(inspector["id"]), 540)
    assert refresh_visit(long_visit["id"])["status"] == "SCHEDULED"
    assert refresh_application(application_b["id"])["status"] == "PENDING_VISIT"


def test_terminal_awaiting_return_cannot_be_committed_to_a_new_deployment():
    """A recalled unit sitting in PENDING_RETURN is unavailable even for an October
    window that collides with nothing.

    "A unit whose status is `PENDING_RETURN` or `RETIRED` is not available to
    commit at all, and naming one is refused with `ERR_DEPOT_STOCK_EXHAUSTED`." The
    original commitment closed on 2026-09-30, so the new closed interval overlaps
    no other commitment of that unit and the interval family at rule 13 stays
    silent while the capacity rule at 15 answers.

    Design: Corner/validations/terminal_awaiting_return_cannot_be_committed_to_a_new_deployment
    """
    context = authorized_store()
    depot = create_depot()
    terminal = create_terminal(depot)
    deployment = create_deployment(context.store, terminal)
    activate_deployment(deployment)
    ok(
        api_client.recall_deployment(
            deployment["id"], ADMIN, close_deployment_payload("RETAILER_REQUEST")
        )
    )

    response = api_client.create_terminal_deployment(
        deployment_payload(
            context.store_id,
            terminal["id"],
            deploy_start="2026-10-01T00:00:00Z",
            deploy_end="2026-10-31T00:00:00Z",
        ),
        ADMIN,
    )

    body = validate_error(response, ApiErrorId.ERR_DEPOT_STOCK_EXHAUSTED.value, 409)
    assert body["error_id"] != ApiErrorId.ERR_TERMINAL_ALREADY_COMMITTED.value
    assert refresh_terminal(terminal["id"])["status"] == "PENDING_RETURN"
    assert_depot_conservation(
        refresh_depot(depot["id"]),
        {"units_pending_return": 1, "units_in_stock": 4, "units_deployed": 0},
    )
    assert refresh_store(context.store_id)["active_terminal_count"] == 0
    assert_row_count(
        api_client.list_terminal_deployments(ADMIN, {"terminal_id": terminal["id"]}), 1
    )


def test_criterion_a_submit_with_only_three_qualifying_categories_is_rejected():
    """Eighteen units of meat across two varieties leave the desk count at three
    categories, and the submit is refused.

    "The category qualifies when it holds at least 3 distinct varieties and its
    aggregate unit count is at least 9." Breadth and depth are conjunctive, so a
    deep but narrow category earns nothing, and "an application claiming
    `CRITERION_A` requires `desk_criterion_pass` to be true, failing which the
    submit is refused with `ERR_STAPLE_STOCK_INSUFFICIENT`". The filing stays in
    DRAFT, so the retailer may restock and try again.

    Design: Corner/validations/criterion_a_submit_with_only_three_qualifying_categories_is_rejected
    """
    owner = create_owner()
    store = create_store(owner)
    application = create_application(
        owner, store, inventory_lines=INV_MEAT_TOO_NARROW
    )

    response = api_client.submit_application(application["id"], owner_headers(owner))

    validate_error(response, ApiErrorId.ERR_STAPLE_STOCK_INSUFFICIENT.value, 422)
    assert_fields(
        refresh_application(application["id"]),
        {
            "status": "DRAFT",
            "submitted_at": None,
            "desk_qualifying_categories": 3,
            "desk_criterion_pass": False,
        },
        "refused application",
    )


def test_approval_is_refused_when_the_verified_shelf_depth_is_below_the_floor():
    """Findings measuring 23 linear feet pass the on-site stock variant and still
    block the approval.

    "The latest `FINDINGS_SUBMITTED` visit of that application must have
    `depth_of_stock_pass` true -- this is where the shelf floor deferred at
    findings time is finally enforced, and a failure is refused with
    `ERR_DEPTH_OF_STOCK_INSUFFICIENT`." The measurement is within a quarter of the
    reported 30 feet, so no shelf-discrepancy flag is raised and the application
    reaches UNDER_REVIEW before the decision refuses it.

    Design: Corner/validations/approval_is_refused_when_the_verified_shelf_depth_is_below_the_floor
    """
    context = pending_visit_application()
    visit = submit_findings(
        context.visit, context.inspector, observed_staple_shelf_linear_feet=23
    )
    assert_fields(
        visit,
        {
            "depth_of_stock_pass": False,
            "shelf_discrepancy_flag": False,
            "verified_criterion_a_pass": True,
        },
        "shallow findings",
    )
    assert refresh_application(context.application_id)["status"] == "UNDER_REVIEW"

    response = api_client.decide_application(
        context.application_id, decision_payload("APPROVED"), ADMIN
    )

    validate_error(response, ApiErrorId.ERR_DEPTH_OF_STOCK_INSUFFICIENT.value, 422)
    assert_fields(
        refresh_application(context.application_id),
        {"status": "UNDER_REVIEW", "decided_at": None},
        "undecided application",
    )
    assert_fields(
        refresh_store(context.store_id),
        {"authorization_status": "NOT_AUTHORIZED", "fns_number": None},
        "unauthorized store",
    )


def test_sale_on_a_reserved_deployment_is_rejected_before_any_tender_math():
    """An all-ineligible basket rung on a merely reserved deployment answers for
    the deployment, not for the basket.

    The state gate sits at rule 9 -- "a transaction naming a deployment that is
    not active is refused with `ERR_TERMINAL_DEPLOYMENT_NOT_ACTIVE` (409)" -- and
    tender feasibility at rule 19, so the eligibility of the lines is never
    computed and nothing is written: the refusal is a validation failure, not a
    decline.

    Design: Corner/validations/sale_on_a_reserved_deployment_is_rejected_before_any_tender_math
    """
    context = authorized_store()
    equipment = reserved_equipment(context.store)

    response = api_client.create_pos_transaction(
        pos_transaction_payload(
            context.store_id,
            equipment.deployment_id,
            line_items=[line_item("BEER-1", "ALCOHOL", 1200, 1)],
            snap_benefit_available_cents=50000,
            other_tender_offered_cents=0,
        ),
        context.clerk_h,
    )

    body = validate_error(
        response, ApiErrorId.ERR_TERMINAL_DEPLOYMENT_NOT_ACTIVE.value, 409
    )
    assert body["error_id"] != ApiErrorId.ERR_NO_ELIGIBLE_ITEMS.value
    assert_no_rows(
        api_client.list_pos_transactions(ADMIN, {"store_id": context.store_id})
    )
    assert refresh_deployment(equipment.deployment_id)["status"] == "RESERVED"


def test_all_ineligible_basket_declines_with_no_eligible_items():
    """Beer, a hot deli item and cat food produce a persisted DECLINED row whose
    every tender figure is zero.

    "If `eligible_subtotal_cents` comes out at 0 -- every line in the basket is
    ineligible -- the sale is declined immediately: the transaction is created with
    `status` `DECLINED` and `decline_reason_code` `NO_ELIGIBLE_ITEMS`, all tender
    figures are recorded as 0, and the call returns `ERR_NO_ELIGIBLE_ITEMS`." The
    row survives the error response, which is what separates a decline from a
    refusal.

    Design: Corner/validations/all_ineligible_basket_declines_with_no_eligible_items
    """
    context = authorized_store()
    equipment = active_equipment(context.store)

    response = api_client.create_pos_transaction(
        pos_transaction_payload(
            context.store_id,
            equipment.deployment_id,
            line_items=ALL_INELIGIBLE,
            snap_benefit_available_cents=50000,
            other_tender_offered_cents=5000,
        ),
        context.clerk_h,
    )

    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_ITEMS.value, 422)
    declined = assert_row_count(
        api_client.list_pos_transactions(ADMIN, {"status": "DECLINED"}), 1
    )[0]
    assert_fields(
        declined,
        {
            "status": "DECLINED",
            "decline_reason_code": "NO_ELIGIBLE_ITEMS",
            "eligible_subtotal_cents": 0,
            "ebt_tender_cents": 0,
            "other_tender_cents": 0,
            "split_tender_applied": False,
            "flagged_line_skus": ["BEER-1", "HOT-1", "CAT-1"],
        },
        "declined basket",
    )


def test_closed_period_refuses_both_a_void_and_a_settlement_import():
    """Once the covering period is CLOSED, neither the sale nor the period's
    figures may be touched again.

    "Once the covering period has been `CLOSED`, the void is refused with
    `ERR_REDEMPTION_PERIOD_CLOSED`, because a closed period's figures are evidence
    and evidence does not move", and "importing into a period that has already been
    `CLOSED` is refused with `ERR_REDEMPTION_PERIOD_CLOSED`". Both doors carry the
    same code, and the frozen 1,000c stands.

    Design: Corner/validations/closed_period_refuses_both_a_void_and_a_settlement_import
    """
    context = authorized_store()
    equipment = active_equipment(context.store)
    period = create_period(context.store_id)
    sale = created(
        api_client.create_pos_transaction(
            pos_transaction_payload(
                context.store_id,
                equipment.deployment_id,
                line_items=SALE_1000,
                snap_benefit_available_cents=500000,
            ),
            context.clerk_h,
        )
    )
    advance_clock("2026-08-02T00:00:00Z")
    close_period(period["id"])

    void = api_client.void_pos_transaction(
        sale["id"], void_payload("PROCESSOR_REVERSAL"), context.clerk_h
    )
    import_attempt = api_client.import_settlement(
        period["id"], settlement_payload(imported_total_cents=999999), ANALYST
    )

    validate_error(void, ApiErrorId.ERR_REDEMPTION_PERIOD_CLOSED.value, 409)
    validate_error(import_attempt, ApiErrorId.ERR_REDEMPTION_PERIOD_CLOSED.value, 409)
    assert_fields(
        refresh_transaction(sale["id"]),
        {"status": "AUTHORIZED", "void_reason_code": None},
        "untouched sale",
    )
    assert_fields(
        refresh_period(period["id"]),
        {
            "status": "CLOSED",
            "redemption_total_cents": 1000,
            "reconciliation_status": "NOT_IMPORTED",
        },
        "frozen period",
    )


def test_period_close_is_refused_before_period_end_and_allowed_exactly_at_it():
    """A close attempted on the period's first day is refused; the same call at the
    period's end instant freezes and scores it.

    "A close is permitted only once the logical clock has reached `period_end`;
    before that it is refused with `ERR_PERIOD_NOT_ELAPSED`." The edge is
    inclusive, so the close at exactly 2026-09-01 succeeds and an empty period
    scores zero and lands on the lowest flag level rather than being rejected as
    unscoreable.

    Design: Corner/validations/period_close_is_refused_before_period_end_and_allowed_exactly_at_it
    """
    context = authorized_store()
    period = create_period(
        context.store_id,
        period_index=8,
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
    )

    early = api_client.close_redemption_period(period["id"], ANALYST)
    validate_error(early, ApiErrorId.ERR_PERIOD_NOT_ELAPSED.value, 409)
    assert refresh_period(period["id"])["status"] == "OPEN"

    advance_clock("2026-09-01T00:00:00Z")
    closed = close_period(period["id"])

    assert_fields(
        closed,
        {
            "status": "CLOSED",
            "closed_at": "2026-09-01T00:00:00Z",
            "redemption_total_cents": 0,
            "transaction_count": 0,
            "anomaly_score": 0,
            "flag_level": "FLAG_L0",
        },
        "closed period",
    )
    assert refresh_store(context.store_id)["redemption_flag_level"] == "FLAG_L0"


def test_reply_and_determination_deadlines_are_exact_complements_at_the_same_instant():
    """Before 2026-08-11 only the reply is open; at 2026-08-11 only the
    determination is.

    The two gates share one instant from opposite sides: "issuing it while the
    logical clock is still before `reply_due_at` is refused with
    `ERR_REPLY_WINDOW_OPEN`, because the retailer's right to respond has not
    expired", while "a reply filed at or after `reply_due_at` is refused with
    `ERR_REPLY_WINDOW_CLOSED`". The determination that follows sizes a first
    offence at three months and opens the ten-day review window.

    Design: Corner/validations/reply_and_determination_deadlines_are_exact_complements_at_the_same_instant
    """
    context = authorized_store()
    case = charged_case(context)

    advance_clock("2026-08-05T00:00:00Z")
    too_early = api_client.issue_determination(
        case["id"], determination_payload("TEMPORARY_DISQUALIFICATION"), ADMIN
    )
    validate_error(too_early, ApiErrorId.ERR_REPLY_WINDOW_OPEN.value, 409)

    advance_clock("2026-08-11T00:00:00Z")
    too_late = api_client.file_reply(
        case["id"], reply_payload(), context.owner_h
    )
    validate_error(too_late, ApiErrorId.ERR_REPLY_WINDOW_CLOSED.value, 409)

    determined = issue_determination(case["id"], "TEMPORARY_DISQUALIFICATION")

    assert_fields(
        determined,
        {
            "status": "DETERMINED",
            "sanction_type": "TEMPORARY_DISQUALIFICATION",
            "disqualification_months": 3,
            "prior_final_sanction_count": 0,
            "reply_received_at": None,
            "determined_at": "2026-08-11T00:00:00Z",
            "admin_review_due_at": "2026-08-21T00:00:00Z",
        },
        "determination",
    )
    assert_no_rows(api_client.list_cmp_elections(case["id"], ADMIN))


def _determined_temporary_disqualification():
    """A charged hardship case determined as a three-month temporary
    disqualification on 2026-08-11, the instant the reply window shuts."""
    context = authorized_store()
    case = charged_case(context)
    advance_clock("2026-08-11T00:00:00Z")
    return context, issue_determination(case["id"], "TEMPORARY_DISQUALIFICATION")


def _finalized_temporary_disqualification():
    """The same case finalized at its review deadline, so `effective_date` is
    thirty days out at 2026-09-20."""
    context, case = _determined_temporary_disqualification()
    advance_clock("2026-08-21T00:00:00Z")
    return context, finalize_case(case["id"])


def test_administrative_review_at_its_deadline_is_closed_and_finalize_opens():
    """At 2026-08-21 the retailer's review window has shut and the same instant
    lets the sanction become final.

    "A request filed at or after `admin_review_due_at` is refused with
    `ERR_ADMIN_REVIEW_WINDOW_CLOSED`", and finalization runs "from `DETERMINED`
    once the administrative-review window has closed without a request". The
    finalization suspends the store but leaves it short of disqualification: the
    thirty-day notice period runs to 2026-09-20.

    Design: Corner/validations/administrative_review_at_its_deadline_is_closed_and_finalize_opens
    """
    context, case = _determined_temporary_disqualification()
    advance_clock("2026-08-21T00:00:00Z")

    late_request = api_client.request_administrative_review(
        case["id"], administrative_review_payload(), context.owner_h
    )
    validate_error(
        late_request, ApiErrorId.ERR_ADMIN_REVIEW_WINDOW_CLOSED.value, 409
    )
    assert refresh_case(case["id"])["admin_review_requested_at"] is None

    finalized = finalize_case(case["id"])

    assert_fields(
        finalized,
        {
            "status": "SANCTION_FINAL",
            "final_decision_at": "2026-08-21T00:00:00Z",
            "effective_date": "2026-09-20T00:00:00Z",
        },
        "finalized case",
    )
    assert_fields(
        refresh_store(context.store_id),
        {
            "sanction_status": "SANCTION_FINAL",
            "authorization_status": "SUSPENDED",
            "permanently_disqualified": False,
            "disqualified_until": None,
        },
        "suspended store",
    )


def test_enforcement_before_the_effective_date_is_refused_and_allowed_at_it():
    """One day early the enforcement is refused; on the effective date it
    disqualifies the store and dates the exclusion period.

    "Enforcement ... is permitted ... only once the logical clock has reached
    `effective_date`, before which it is refused with `ERR_ENFORCEMENT_NOT_DUE`.
    The edge is inclusive: enforcement at exactly `effective_date` is permitted."
    For a temporary disqualification "`disqualified_until` is set to `enforced_at`
    plus the case's `disqualification_months` and `permanently_disqualified` stays
    false", so three months from 2026-09-20 lands on 2026-12-20 and the owner
    rollup is untouched.

    Design: Corner/validations/enforcement_before_the_effective_date_is_refused_and_allowed_at_it
    """
    context, case = _finalized_temporary_disqualification()

    advance_clock("2026-09-19T00:00:00Z")
    early = api_client.enforce_sanction_case(case["id"], ADMIN)
    validate_error(early, ApiErrorId.ERR_ENFORCEMENT_NOT_DUE.value, 409)
    assert refresh_store(context.store_id)["authorization_status"] == "SUSPENDED"

    advance_clock("2026-09-20T00:00:00Z")
    enforced = enforce_case(case["id"])

    assert_fields(
        enforced,
        {"status": "ENFORCED", "enforced_at": "2026-09-20T00:00:00Z"},
        "enforced case",
    )
    assert_fields(
        refresh_store(context.store_id),
        {
            "authorization_status": "DISQUALIFIED",
            "permanently_disqualified": False,
            "disqualified_until": "2026-12-20T00:00:00Z",
        },
        "disqualified store",
    )
    assert_fields(
        refresh_owner(context.owner_id),
        {"permanent_disqualification_count": 0, "sanction_flag": "CLEAR"},
        "owner rollup",
    )


def test_trafficking_case_refuses_a_temporary_disqualification_sanction_type():
    """A trafficking case may only be sized permanently, so a temporary
    disqualification is rejected outright.

    "The supplied `sanction_type` must be permitted for the case's
    `violation_type`, otherwise the determination is refused with
    `ERR_SANCTION_TYPE_NOT_ALLOWED`." The investigation behind the case scored 60
    and is SUBSTANTIATED, so nothing upstream is at fault; the case simply stays in
    CHARGE_ISSUED with no sanction on it.

    Design: Corner/validations/trafficking_case_refuses_a_temporary_disqualification_sanction_type
    """
    context = authorized_store()
    case = charged_case(context, "TRAFFICKING")
    advance_clock("2026-08-11T00:00:00Z")

    response = api_client.issue_determination(
        case["id"], determination_payload("TEMPORARY_DISQUALIFICATION"), ADMIN
    )

    validate_error(response, ApiErrorId.ERR_SANCTION_TYPE_NOT_ALLOWED.value, 422)
    investigation = rows(
        api_client.list_investigations(ANALYST, {"store_id": context.store_id})
    )[0]
    assert_fields(
        investigation,
        {"status": "SUBSTANTIATED", "trafficking_confidence_score": 60},
        "trafficking investigation",
    )
    assert_fields(
        refresh_case(case["id"]),
        {"status": "CHARGE_ISSUED", "sanction_type": None, "determined_at": None},
        "unsized case",
    )
    assert_fields(
        refresh_store(context.store_id),
        {"authorization_status": "AUTHORIZED", "sanction_status": "CHARGED"},
        "still-trading store",
    )


def test_cmp_only_sanction_never_suspends_and_cannot_be_enforced():
    """A finalized civil money penalty leaves the store trading and has no
    enforcement date to reach.

    "`effective_date` is set to thirty days after `final_decision_at` for
    disqualification sanctions only -- for `CMP_IN_LIEU` and for `WARNING` it stays
    null, because there is nothing to enforce on a date", and enforcement is
    permitted "only for a `sanction_type` of `PERMANENT_DISQUALIFICATION` or
    `TEMPORARY_DISQUALIFICATION` -- attempting it on a `WARNING` or a `CMP_IN_LIEU`
    case is refused with `ERR_SANCTION_TYPE_NOT_ALLOWED`". The debt is what the
    owner carries instead.

    Design: Corner/validations/cmp_only_sanction_never_suspends_and_cannot_be_enforced
    """
    context = authorized_store()
    four_closed_periods(context.store_id)
    case = replied_case(context, with_election=True)
    issue_determination(case["id"], "CMP_IN_LIEU")
    advance_clock("2026-08-11T00:00:00Z")
    finalize_case(case["id"])

    response = api_client.enforce_sanction_case(case["id"], ADMIN)

    validate_error(response, ApiErrorId.ERR_SANCTION_TYPE_NOT_ALLOWED.value, 422)
    assert_fields(
        refresh_case(case["id"]),
        {
            "status": "SANCTION_FINAL",
            "effective_date": None,
            "enforced_at": None,
            "cmp_amount_cents": 423456,
            "cmp_outstanding_cents": 423456,
        },
        "final penalty case",
    )
    assert_fields(
        refresh_store(context.store_id),
        {"authorization_status": "AUTHORIZED", "sanction_status": "SANCTION_FINAL"},
        "trading store",
    )
    assert_fields(
        refresh_owner(context.owner_id),
        {
            "permanent_disqualification_count": 0,
            "sanction_flag": "HAS_ACTIVE_CMP_DEBT",
        },
        "indebted owner",
    )


def _second_authorized_store(context):
    """A second store of the same owner, registered without a hardship
    designation and walked to AUTHORIZED on its own 04:00-05:00 visit."""
    store = create_store(
        context.owner,
        store_name="Rio Corner Market",
        checkout_lane_count=1,
        annual_gross_sales_cents=24000000,
        annual_staple_sales_cents=14000000,
        max_terminal_slots=1,
        tax_rate_bps=None,
        hardship_designated=None,
    )
    application = create_application(context.owner, store)
    submit_application(application, context.owner)
    visit = schedule_visit(
        application,
        context.inspector,
        window_start="2026-08-01T04:00:00Z",
        window_end="2026-08-01T05:00:00Z",
    )
    advance_clock("2026-08-01T04:00:00Z")
    start_visit(visit, context.inspector)
    submit_findings(visit, context.inspector)
    decide_application(application)
    return refresh_store(store["id"])


def test_cmp_in_lieu_is_unavailable_to_a_store_without_hardship_designation():
    """The election is timely and the case is otherwise perfect, but the store
    carries no hardship designation.

    "Three gates must hold together, and any failure is refused with
    `ERR_CMP_NOT_AVAILABLE`: the store must be `hardship_designated`; there must be
    an `ELECTED` election on the case whose `elected_at` is strictly before
    `cmp_election_due_at`; and the owner must hold no sanction case anywhere in its
    portfolio whose status is `SANCTION_FINAL` or `ENFORCED` and whose
    `violation_type` is `TRAFFICKING`." The refusal leaves the election exactly as
    filed and writes no ledger row. The second store is given four closed monitoring
    periods so the election can quote an amount at all -- the hardship conjunct is
    then the only gate left to fail.

    Design: Corner/validations/cmp_in_lieu_is_unavailable_to_a_store_without_hardship_designation
    """
    context = authorized_store()
    store_b = _second_authorized_store(context)
    four_closed_periods(store_b["id"])
    investigation = open_investigation(store_b["id"], opened_reason="ALE_REFERRAL")
    add_evidence(
        investigation["id"],
        evidence_type="HOUSEHOLD_INTERVIEW",
        observed_at="2026-07-15T00:00:00Z",
    )
    ok(
        api_client.conclude_investigation(
            investigation["id"],
            conclude_payload("INELIGIBLE_ITEM_SALES"),
            ANALYST_ALT,
        )
    )
    case = open_case(investigation["id"], "INELIGIBLE_ITEMS_HARDSHIP")
    case = issue_charge_letter(case["id"])
    elect_cmp(case, context.owner)
    file_reply(case["id"], context.owner)

    response = api_client.issue_determination(
        case["id"], determination_payload("CMP_IN_LIEU"), ADMIN
    )

    validate_error(response, ApiErrorId.ERR_CMP_NOT_AVAILABLE.value, 409)
    assert store_b["hardship_designated"] is False
    assert_fields(
        refresh_case(case["id"]),
        {"status": "REPLY_RECEIVED", "sanction_type": None},
        "undetermined case",
    )
    election = assert_row_count(api_client.list_cmp_elections(case["id"], ADMIN), 1)[0]
    assert election["status"] == "ELECTED"
    assert_no_rows(api_client.list_penalty_ledger(case["id"], ADMIN))


def test_sanction_case_cannot_be_opened_from_an_open_investigation():
    """An investigation still gathering evidence cannot carry a case.

    "The referenced investigation must be `SUBSTANTIATED`, or the case is refused
    with `ERR_INVESTIGATION_NOT_SUBSTANTIATED`." The store is already marked as
    under investigation, which is the only footprint the opened investigation was
    supposed to leave.

    Design: Corner/validations/sanction_case_cannot_be_opened_from_an_open_investigation
    """
    context = authorized_store()
    investigation = open_investigation(context.store_id, opened_reason="TIP")

    response = api_client.create_sanction_case(
        sanction_case_payload(investigation["id"], "TRAFFICKING"), ADMIN
    )

    validate_error(
        response, ApiErrorId.ERR_INVESTIGATION_NOT_SUBSTANTIATED.value, 409
    )
    assert_fields(
        refresh_investigation(investigation["id"]),
        {"status": "OPEN", "trafficking_confidence_score": 0},
        "open investigation",
    )
    assert_no_rows(
        api_client.list_sanction_cases(ADMIN, {"store_id": context.store_id})
    )
    assert refresh_store(context.store_id)["sanction_status"] == "UNDER_INVESTIGATION"


def test_second_remand_is_refused_while_a_sustained_decision_is_accepted():
    """A case already remanded once cannot be remanded again, but the same officer
    may sustain the re-issued determination.

    "A case may be remanded at most once: a second remand on a case whose
    `remand_count` is already 1 is refused with `ERR_REMAND_LIMIT_REACHED`." The
    refused attempt leaves the counter alone, and the SUSTAINED alternative keeps
    the case in ADMIN_REVIEW_REQUESTED -- "this is the one self-transition in the
    case machine" -- with the re-issued three-month sanction intact.

    Design: Corner/validations/second_remand_is_refused_while_a_sustained_decision_is_accepted
    """
    context, case = _determined_temporary_disqualification()
    ok(
        api_client.request_administrative_review(
            case["id"], administrative_review_payload(), context.owner_h
        )
    )
    ok(
        api_client.decide_administrative_review(
            case["id"],
            review_decision_payload("REMANDED", reason_code="NEW_EVIDENCE"),
            REVIEWER,
        )
    )
    issue_determination(case["id"], "TEMPORARY_DISQUALIFICATION")
    ok(
        api_client.request_administrative_review(
            case["id"], administrative_review_payload(), context.owner_h
        )
    )

    second_remand = api_client.decide_administrative_review(
        case["id"],
        review_decision_payload("REMANDED", reason_code="NEW_EVIDENCE"),
        REVIEWER,
    )
    validate_error(second_remand, ApiErrorId.ERR_REMAND_LIMIT_REACHED.value, 409)
    assert refresh_case(case["id"])["remand_count"] == 1

    sustained = ok(
        api_client.decide_administrative_review(
            case["id"], review_decision_payload("SUSTAINED"), REVIEWER
        )
    )

    assert_fields(
        sustained,
        {
            "status": "ADMIN_REVIEW_REQUESTED",
            "admin_review_outcome": "SUSTAINED",
            "admin_review_decided_by_user_id": REVIEW_OFFICER_USER_ID,
            "sanction_type": "TEMPORARY_DISQUALIFICATION",
            "disqualification_months": 3,
            "remand_count": 1,
        },
        "sustained case",
    )
    assert refresh_store(context.store_id)["sanction_status"] == "UNDER_ADMIN_REVIEW"


def test_investigation_cannot_be_concluded_by_the_analyst_who_opened_it():
    """The analyst who opened the file may not close it; a second analyst may.

    "Whichever branch is taken, the concluding user must differ from
    `opened_by_user_id`, or the conclusion is refused with
    `ERR_SEGREGATION_OF_DUTIES`." The refusal leaves the investigation in
    EVIDENCE_REVIEW with no concluding user recorded, and the independent analyst's
    identical payload substantiates it.

    Design: Corner/validations/investigation_cannot_be_concluded_by_the_analyst_who_opened_it
    """
    context = authorized_store()
    investigation = open_investigation(context.store_id, opened_reason="TIP")
    add_evidence(
        investigation["id"],
        evidence_type="HOUSEHOLD_INTERVIEW",
        observed_at="2026-07-15T00:00:00Z",
    )

    refused = api_client.conclude_investigation(
        investigation["id"], conclude_payload("INELIGIBLE_ITEM_SALES"), ANALYST
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert_fields(
        refresh_investigation(investigation["id"]),
        {"status": "EVIDENCE_REVIEW", "concluded_by_user_id": None},
        "still-open investigation",
    )

    concluded = ok(
        api_client.conclude_investigation(
            investigation["id"], conclude_payload("INELIGIBLE_ITEM_SALES"), ANALYST_ALT
        )
    )

    assert_fields(
        concluded,
        {
            "status": "SUBSTANTIATED",
            "substantiated_violation": "INELIGIBLE_ITEM_SALES",
            "opened_by_user_id": ANALYST_USER_ID,
            "concluded_by_user_id": ANALYST_ALT_USER_ID,
        },
        "concluded investigation",
    )


def test_review_officer_who_signed_the_determination_cannot_decide_the_review():
    """The independence rule compares user identifiers, not roles, so the same
    person cannot review their own determination.

    "The deciding officer's `X-User-ID` must differ from both
    `charge_issued_by_user_id` and `determined_by_user_id` on that case, otherwise
    the decision is refused with `ERR_SEGREGATION_OF_DUTIES`." Here one human wore
    the administrator's role to charge and determine, and their review decision is
    refused while a genuinely independent officer's identical decision succeeds.

    Design: Corner/validations/review_officer_who_signed_the_determination_cannot_decide_the_review
    """
    officer_as_admin = make_fns_admin_headers(REVIEW_OFFICER_USER_ID)
    context = authorized_store()
    investigation = substantiated_ineligible_investigation(context.store_id)
    case = open_case(investigation["id"], "INELIGIBLE_ITEMS_HARDSHIP")
    ok(
        api_client.issue_charge_letter(
            case["id"], charge_letter_payload(), officer_as_admin
        )
    )
    advance_clock("2026-08-11T00:00:00Z")
    ok(
        api_client.issue_determination(
            case["id"],
            determination_payload("TEMPORARY_DISQUALIFICATION"),
            officer_as_admin,
        )
    )
    ok(
        api_client.request_administrative_review(
            case["id"], administrative_review_payload(), context.owner_h
        )
    )

    refused = api_client.decide_administrative_review(
        case["id"], review_decision_payload("SUSTAINED"), REVIEWER
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert_fields(
        refresh_case(case["id"]),
        {"status": "ADMIN_REVIEW_REQUESTED", "admin_review_outcome": None},
        "undecided review",
    )

    decided = ok(
        api_client.decide_administrative_review(
            case["id"], review_decision_payload("SUSTAINED"), REVIEWER_ALT
        )
    )

    assert_fields(
        decided,
        {
            "admin_review_outcome": "SUSTAINED",
            "admin_review_decided_by_user_id": REVIEW_OFFICER_ALT_USER_ID,
            "charge_issued_by_user_id": REVIEW_OFFICER_USER_ID,
            "determined_by_user_id": REVIEW_OFFICER_USER_ID,
        },
        "independently decided case",
    )


def test_reverification_findings_cannot_be_filed_by_the_pre_authorization_inspector():
    """The inspector who verified the store before authorization may not verify it
    again on renewal.

    "On a `REVERIFICATION` visit the acting inspector must differ from the
    inspector who submitted findings on that store's `PRE_AUTHORIZATION` visit,
    otherwise the submission is refused with `ERR_SEGREGATION_OF_DUTIES`." She is
    the visit's own assigned inspector, so the ownership rule at 5 is satisfied and
    only the independence rule at 6 can answer; her sixty minutes stay committed
    because the visit is still in progress.

    Design: Corner/validations/reverification_findings_cannot_be_filed_by_the_pre_authorization_inspector
    """
    context = authorized_store()
    ok(api_client.withdraw_store(context.store_id, context.owner_h))
    store = refresh_store(context.store_id)
    application = created(
        api_client.create_application(
            application_payload(
                store["id"], store["version"], application_type="RENEWAL"
            ),
            context.owner_h,
        )
    )
    ok(api_client.submit_application(application["id"], context.owner_h))
    visit = schedule_visit(
        application,
        context.inspector,
        visit_type="REVERIFICATION",
        window_start="2026-08-01T04:00:00Z",
        window_end="2026-08-01T05:00:00Z",
    )
    advance_clock("2026-08-01T04:00:00Z")
    start_visit(visit, context.inspector)

    response = api_client.submit_findings(
        visit["id"], findings_payload(), context.inspector_h
    )

    body = validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert body["error_id"] != ApiErrorId.ERR_NOT_RESOURCE_OWNER.value
    assert_fields(
        refresh_visit(visit["id"]),
        {"status": "IN_PROGRESS", "findings_submitted_at": None},
        "unfiled visit",
    )
    assert_inspector_minutes(refresh_inspector(context.inspector_id), 60)
    assert refresh_application(application["id"])["status"] == "PENDING_VISIT"
    assert refresh_store(context.store_id)["authorization_status"] == "WITHDRAWN"


def test_another_owner_cannot_reply_or_pay_on_a_case_it_does_not_own():
    """A stranger's firm can neither answer the charge letter nor pay the penalty.

    "A `RetailerOwner` acting on a store-scoped resource must be the owner of that
    store ... otherwise `ERR_NOT_RESOURCE_OWNER` (403). This guards nine
    operations: `POST /sanction-cases/{caseId}/reply`, ...
    `POST /sanction-cases/{caseId}/cmp-payments`". Ownership sits at rule 5 and the
    penalty gates at 18, so the stranger's payment never reaches the
    overpayment arithmetic that would otherwise reject 1,000c against a zero
    balance.

    Design: Corner/validations/another_owner_cannot_reply_or_pay_on_a_case_it_does_not_own
    """
    context = authorized_store()
    case = charged_case(context)
    stranger = create_owner(legal_name="Mesa Markets LLC")

    reply = api_client.file_reply(
        case["id"], reply_payload(), owner_headers(stranger)
    )
    validate_error(reply, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    payment = api_client.create_cmp_payment(
        case["id"], cmp_payment_payload(1000), owner_headers(stranger)
    )
    body = validate_error(payment, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    assert body["error_id"] != ApiErrorId.ERR_CMP_OVERPAYMENT.value

    assert_fields(
        refresh_case(case["id"]),
        {"status": "CHARGE_ISSUED", "reply_received_at": None},
        "unanswered case",
    )
    assert_no_rows(api_client.list_penalty_ledger(case["id"], ADMIN))
    assert refresh_owner(stranger["id"])["cmp_outstanding_cents"] == 0


def test_request_without_user_headers_is_rejected_except_on_owner_registration():
    """Owner registration is the only route a headerless caller may take; a store
    read is refused whether or not the store exists.

    "Both headers are mandatory everywhere with exactly one exception -- owner
    registration, which is how an unregistered firm bootstraps itself into the
    program. A call that omits either header anywhere else is rejected with
    `ERR_MISSING_USER_CONTEXT` (HTTP 400)." User context sits at rule 1 and path
    resolution at rule 3, so the unknown identifier never reaches the
    not-found lookup.

    Design: Corner/validations/request_without_user_headers_is_rejected_except_on_owner_registration
    """
    owner = created(api_client.create_owner(owner_payload(), NO_AUTH_HEADERS))
    store = create_store(owner)

    existing = api_client.get_store(store["id"], NO_AUTH_HEADERS)
    validate_error(existing, ApiErrorId.ERR_MISSING_USER_CONTEXT.value, 400)

    unknown = api_client.get_store(NON_EXISTENT_UUID, NO_AUTH_HEADERS)
    body = validate_error(unknown, ApiErrorId.ERR_MISSING_USER_CONTEXT.value, 400)
    assert body["error_id"] != ApiErrorId.ERR_STORE_NOT_FOUND.value


def test_ownership_change_reauthorization_to_the_same_owner_is_refused():
    """A transfer to oneself passes every stock and debt check and is still refused
    at the decision.

    "The successor store's `owner_id` must actually differ from the predecessor
    store's `owner_id`, or the approval is refused with `ERR_OWNERSHIP_UNCHANGED`,
    because a paper transfer to oneself is not a change of ownership." The
    predecessor owner owes nothing, so the sibling transfer-integrity code cannot
    be the answer, and no second FNS number is minted.

    Design: Corner/validations/ownership_change_reauthorization_to_the_same_owner_is_refused
    """
    context = authorized_store()
    successor = create_store(
        context.owner,
        store_name="Rio Convenience (New Ownership)",
        predecessor_store_id=context.store_id,
    )
    application = created(
        api_client.create_application(
            application_payload(
                successor["id"],
                successor["version"],
                application_type="REAUTHORIZATION_OWNERSHIP_CHANGE",
            ),
            context.owner_h,
        )
    )
    ok(api_client.submit_application(application["id"], context.owner_h))
    visit = schedule_visit(
        application,
        context.inspector,
        window_start="2026-08-01T06:00:00Z",
        window_end="2026-08-01T07:00:00Z",
    )
    advance_clock("2026-08-01T06:00:00Z")
    start_visit(visit, context.inspector)
    submit_findings(visit, context.inspector)

    response = api_client.decide_application(
        application["id"], decision_payload("APPROVED"), ADMIN
    )

    body = validate_error(response, ApiErrorId.ERR_OWNERSHIP_UNCHANGED.value, 422)
    assert body["error_id"] != ApiErrorId.ERR_TRANSFER_CMP_OUTSTANDING.value
    assert_fields(
        refresh_application(application["id"]),
        {"status": "UNDER_REVIEW", "decided_at": None},
        "undecided transfer",
    )
    assert_fields(
        refresh_store(successor["id"]),
        {"authorization_status": "NOT_AUTHORIZED", "fns_number": None},
        "successor store",
    )
    assert_fields(
        refresh_store(context.store_id),
        {"authorization_status": "AUTHORIZED", "fns_number": "FNS-1000001"},
        "predecessor store",
    )
    assert_row_count(
        api_client.list_stores(ADMIN, {"predecessor_store_id": context.store_id}), 1
    )


def test_two_permanent_disqualifications_bar_the_owner_and_block_a_pending_decision():
    """Two enforced permanent disqualifications flip the owner to BARRED, which
    then blocks both a pending decision and a fresh filing.

    "An owner carrying a permanent disqualification may not be approved for a new
    authorization (`ERR_OWNER_PERMANENTLY_DISQUALIFIED`, 403) and an owner carrying
    two or more may not file at all (`ERR_OWNER_BARRED`, 403)." The third store's
    application was already UNDER_REVIEW when the enforcements landed, so it is
    refused at the decision, while the fourth store cannot even leave DRAFT.

    Design: Corner/validations/two_permanent_disqualifications_bar_the_owner_and_block_a_pending_decision
    """
    context = authorized_store()
    store_b = _second_authorized_store(context)
    store_c = create_store(
        context.owner,
        store_name="Rio Third Street",
        annual_gross_sales_cents=30000000,
        annual_staple_sales_cents=18000000,
        max_terminal_slots=1,
        tax_rate_bps=None,
        hardship_designated=None,
    )
    application_c = create_application(context.owner, store_c)
    submit_application(application_c, context.owner)
    visit_c = schedule_visit(
        application_c,
        context.inspector,
        window_start="2026-08-01T06:00:00Z",
        window_end="2026-08-01T07:00:00Z",
    )
    advance_clock("2026-08-01T06:00:00Z")
    start_visit(visit_c, context.inspector)
    submit_findings(visit_c, context.inspector)

    cases = [
        issue_charge_letter(
            open_case(
                substantiated_trafficking_investigation(store_id)["id"], "TRAFFICKING"
            )["id"]
        )
        for store_id in (context.store_id, store_b["id"])
    ]
    advance_clock("2026-08-12T00:00:00Z")
    for case in cases:
        issue_determination(case["id"], "PERMANENT_DISQUALIFICATION")
    advance_clock("2026-08-22T00:00:00Z")
    for case in cases:
        finalize_case(case["id"])
    advance_clock("2026-09-21T00:00:00Z")
    for case in cases:
        enforce_case(case["id"])

    store_d = create_store(
        context.owner,
        store_name="Rio Fourth Street",
        checkout_lane_count=1,
        annual_gross_sales_cents=20000000,
        annual_staple_sales_cents=12000000,
        max_terminal_slots=1,
        tax_rate_bps=None,
        hardship_designated=None,
    )
    application_d = create_application(context.owner, store_d)

    decision = api_client.decide_application(
        application_c["id"], decision_payload("APPROVED"), ADMIN
    )
    submit = api_client.submit_application(application_d["id"], context.owner_h)

    validate_error(
        decision, ApiErrorId.ERR_OWNER_PERMANENTLY_DISQUALIFIED.value, 403
    )
    validate_error(submit, ApiErrorId.ERR_OWNER_BARRED.value, 403)
    assert_fields(
        refresh_owner(context.owner_id),
        {
            "permanent_disqualification_count": 2,
            "sanction_flag": "PERMANENTLY_DISQUALIFIED",
            "status": "BARRED",
        },
        "barred owner",
    )
    assert refresh_store(context.store_id)["authorization_status"] == "DISQUALIFIED"
    assert refresh_store(store_b["id"])["authorization_status"] == "DISQUALIFIED"
    assert refresh_application(application_c["id"])["status"] == "UNDER_REVIEW"
    assert refresh_store(store_c["id"])["authorization_status"] == "NOT_AUTHORIZED"
    assert_fields(
        refresh_application(application_d["id"]),
        {"status": "DRAFT", "submitted_at": None},
        "unfiled application",
    )
