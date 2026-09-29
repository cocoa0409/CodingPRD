"""Declared transitions, their preconditions, their side effects and their locks."""
from test_helpers import (
    ADMIN,
    ANALYST,
    INV_PASS,
    ApiErrorId,
    active_equipment,
    administrative_review_payload,
    advance_clock,
    api_client,
    assert_depot_conservation,
    assert_fields,
    assert_no_rows,
    assert_row_count,
    authorized_store,
    charge_letter_payload,
    cmp_election_payload,
    create_application,
    create_deployment,
    create_depot,
    create_inspector,
    create_owner,
    create_period,
    create_store,
    create_terminal,
    created,
    close_deployment_payload,
    close_period,
    documents_payload,
    elect_cmp,
    enforce_case,
    equipment_order_payload,
    finalize_case,
    four_closed_periods,
    import_settlement,
    inspector_headers,
    investigation_payload,
    issue_charge_letter,
    issue_determination,
    line_item,
    ok,
    open_case,
    order_line,
    owner_headers,
    pos_transaction_payload,
    redemption_period_payload,
    refresh_application,
    refresh_case,
    refresh_deployment,
    refresh_depot,
    refresh_inspector,
    refresh_owner,
    refresh_period,
    refresh_store,
    refresh_terminal,
    refresh_visit,
    reply_payload,
    schedule_visit,
    start_visit,
    submit_application,
    substantiated_ineligible_investigation,
    substantiated_trafficking_investigation,
    validate_error,
    validate_paginated,
)


def _submitted_application():
    owner = create_owner()
    store = create_store(owner)
    application = create_application(owner, store, inventory_lines=INV_PASS)
    return owner, store, application


def test_submit_moves_a_draft_application_to_submitted_and_stamps_the_desk_figures():
    """Submission stamps the clock instant and recomputes the three desk figures
    from the stock on file, without touching the store.

    The specification describes the successful edge: "On success the server sets
    `submitted_at` to the current logical-clock instant, recomputes the three desk
    staple figures from the stock currently on file, and clears
    `hold_reason_code`." Twelve lines across four categories, each variety at three
    or more units, qualify all four categories; dairy, fruit-and-vegetables and
    meat each carry a perishable variety among the qualifying ones, so
    `desk_perishable_categories` is three.

    Design: Corner/state_machines/application_submit_moves_draft_to_submitted_and_stamps_desk_figures
    """
    owner, store, application = _submitted_application()

    submitted = submit_application(application, owner)

    assert_fields(
        submitted,
        {
            "status": "SUBMITTED",
            "submitted_at": "2026-08-01T00:00:00Z",
            "desk_qualifying_categories": 4,
            "desk_perishable_categories": 3,
            "desk_criterion_pass": True,
            "hold_reason_code": None,
        },
        "submitted application",
    )
    assert refresh_store(store["id"])["authorization_status"] == "NOT_AUTHORIZED"


def test_visit_start_fires_at_exactly_window_start_and_keeps_the_minutes_committed():
    """With the clock sitting exactly on `window_start` the visit opens, and the
    inspector's committed minutes stay at the scheduled 120.

    The specification makes the opening edge inclusive: "the logical clock must have
    reached `window_start`, or the start is refused with
    `ERR_VISIT_WINDOW_NOT_OPEN`. The window's opening edge is inclusive -- a start
    at exactly `window_start` is permitted." An in-progress visit is still a
    commitment, so nothing is released.

    Design: Corner/state_machines/store_visit_start_moves_scheduled_to_in_progress_at_window_open
    """
    owner, _store, application = _submitted_application()
    submit_application(application, owner)
    inspector = create_inspector()
    visit = schedule_visit(application, inspector)

    started = start_visit(visit, inspector)

    assert_fields(
        started, {"status": "IN_PROGRESS", "window_minutes": 120}, "started visit"
    )
    assert refresh_inspector(inspector["id"])["committed_minutes"] == 120
    assert refresh_application(application["id"])["status"] == "PENDING_VISIT"


def test_a_second_election_supersedes_the_first_and_leaves_one_elected_row():
    """Re-filing drives the earlier row to SUPERSEDED, and only the new row is
    still ELECTED.

    The specification allows exactly one live election: "Filing a second election on
    the same case drives the previous `ELECTED` row to `SUPERSEDED`, so at most one
    election on a case is ever `ELECTED`. Each election advances the case's
    `version` by one." Because the first election moved the version, the second must
    quote the refreshed one. Each election "quotes the penalty as it stands at
    election time", so the store is given four closed monitoring periods first --
    without a closed pool no quote can be produced at all.

    Design: Corner/state_machines/cmp_election_refiled_supersedes_the_earlier_election_row
    """
    context = authorized_store()
    four_closed_periods(context.store_id)
    investigation = substantiated_ineligible_investigation(context.store_id)
    case = issue_charge_letter(
        open_case(investigation["id"], "INELIGIBLE_ITEMS_HARDSHIP")["id"]
    )
    first = elect_cmp(case, context.owner)

    second = created(
        api_client.create_cmp_election(
            case["id"],
            cmp_election_payload(
                refresh_case(case["id"])["version"],
                hardship_ownership_change_pending=True,
            ),
            context.owner_h,
        )
    )

    rows, _meta = validate_paginated(api_client.list_cmp_elections(case["id"], ADMIN))
    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["status"] == "SUPERSEDED"
    assert_fields(
        by_id[second["id"]],
        {"status": "ELECTED", "hardship_ownership_change_pending": True},
        "re-filed election",
    )
    assert_row_count(
        api_client.list_cmp_elections(case["id"], ADMIN, {"status": "ELECTED"}), 1
    )


def test_a_visit_cannot_be_started_before_its_window_opens():
    """A visit scheduled for tomorrow refuses to open today, and its minutes stay
    committed.

    The temporal gate is its own validation rule: "visit starts only at or after
    `window_start` ... yielding ... `ERR_VISIT_WINDOW_NOT_OPEN` ... (all 409)." A
    refused start is not a cancellation, so the inspector is still booked.

    Design: Corner/state_machines/visit_start_before_window_start_cannot_open_the_visit
    """
    owner, _store, application = _submitted_application()
    submit_application(application, owner)
    inspector = create_inspector()
    visit = schedule_visit(
        application,
        inspector,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T02:00:00Z",
    )

    response = api_client.start_store_visit(
        visit["id"], inspector_headers(inspector)
    )

    validate_error(response, ApiErrorId.ERR_VISIT_WINDOW_NOT_OPEN.value, 409)
    assert refresh_visit(visit["id"])["status"] == "SCHEDULED"
    assert refresh_inspector(inspector["id"])["committed_minutes"] == 120


def test_an_inactive_inspector_cannot_open_a_visit_it_still_holds():
    """Deactivating the assigned inspector after scheduling blocks the start while
    leaving the booking, and the commitment, in place.

    The precondition lives on a different entity than the one transitioning: "the
    assigned inspector's own `status` must be `ACTIVE`, or the start is refused with
    `ERR_INVALID_STATE`", and "An `INACTIVE` inspector keeps whatever visits are
    already booked but may not start one."

    Design: Corner/state_machines/visit_start_with_inactive_inspector_cannot_open_the_visit
    """
    owner, _store, application = _submitted_application()
    submit_application(application, owner)
    inspector = create_inspector()
    visit = schedule_visit(application, inspector)
    ok(api_client.update_inspector(inspector["id"], {"status": "INACTIVE"}, ADMIN))

    response = api_client.start_store_visit(
        visit["id"], inspector_headers(inspector)
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert refresh_visit(visit["id"])["status"] == "SCHEDULED"
    assert_fields(
        refresh_inspector(inspector["id"]),
        {"status": "INACTIVE", "committed_minutes": 120},
        "deactivated inspector",
    )


def test_a_reservation_may_be_booked_for_an_unauthorized_store_but_never_activated():
    """The booking succeeds, the activation does not, and the unit stays in the
    reserved column.

    Activation is the moment the trading gate bites: "Activation moves the
    deployment from `RESERVED` to `ACTIVE`, and it requires the store's
    `authorization_status` to be `AUTHORIZED`, failing which it is refused with
    `ERR_STORE_NOT_AUTHORIZED`."

    Design: Corner/state_machines/deployment_activation_on_unauthorized_store_is_rejected
    """
    owner = create_owner()
    store = create_store(owner)
    depot = create_depot(total_units_owned=5)
    terminal = create_terminal(depot)
    deployment = create_deployment(
        store,
        terminal,
        deploy_start="2026-08-01T00:00:00Z",
        deploy_end="2026-09-30T00:00:00Z",
    )

    response = api_client.activate_deployment(deployment["id"], ADMIN)

    validate_error(response, ApiErrorId.ERR_STORE_NOT_AUTHORIZED.value, 403)
    assert_fields(
        refresh_deployment(deployment["id"]),
        {"status": "RESERVED", "activated_at": None},
        "unactivated deployment",
    )
    assert refresh_terminal(terminal["id"])["status"] == "RESERVED"
    assert_depot_conservation(
        refresh_depot(depot["id"]),
        {"units_reserved": 1, "units_deployed": 0, "units_in_stock": 4},
    )
    assert refresh_store(store["id"])["active_terminal_count"] == 0


def test_one_scheduling_call_books_the_visit_commits_minutes_and_advances_the_file():
    """A single POST produces three effects across three entities.

    Committed minutes are the inspector-side consequence of a booking, and the
    application-side consequence is the move out of SUBMITTED: the file is now
    waiting on the field visit rather than on the applicant.

    Design: Corner/state_machines/scheduling_a_visit_commits_inspector_minutes_and_advances_the_application
    """
    owner, _store, application = _submitted_application()
    submit_application(application, owner)
    inspector = create_inspector()
    assert inspector["committed_minutes"] == 0

    visit = schedule_visit(application, inspector)

    assert_fields(
        visit, {"status": "SCHEDULED", "window_minutes": 120}, "scheduled visit"
    )
    assert refresh_inspector(inspector["id"])["committed_minutes"] == 120
    assert refresh_application(application["id"])["status"] == "PENDING_VISIT"


def test_approval_mints_the_first_fns_number_and_authorizes_the_store():
    """The decision writes into the store as well as the application, and only the
    authorization dimension moves.

    The specification spells out the reach-across: "when the store has no
    `fns_number` yet, one is minted; the store's `authorization_status` moves from
    `NOT_AUTHORIZED` ... to `AUTHORIZED`; `authorized_at` is set to the current
    logical-clock instant", and "the first store ever authorized by the system
    carries `FNS-1000001`".

    Design: Corner/state_machines/approval_mints_the_fns_number_and_authorizes_the_store
    """
    context = authorized_store()

    application = refresh_application(context.application_id)

    assert_fields(
        application,
        {
            "status": "APPROVED",
            "decision_reason_code": "APPROVED_CRITERION_A",
            "decided_at": "2026-08-01T00:00:00Z",
        },
        "approved application",
    )
    assert_fields(
        refresh_store(context.store_id),
        {
            "fns_number": "FNS-1000001",
            "authorization_status": "AUTHORIZED",
            "authorized_at": "2026-08-01T00:00:00Z",
            "sanction_status": "NONE",
        },
        "authorized store",
    )


def test_the_charge_letter_fixes_both_ten_day_windows_and_charges_the_store():
    """Issuing the letter stamps two identical deadlines, records the issuing user
    and moves only the sanction dimension.

    The specification computes both at once: "A charge letter fixes `reply_due_at`
    and `cmp_election_due_at` at ten days after `charge_letter_sent_at`." Charging a
    store does not stop it trading, because "Only the authorization dimension gates
    trading".

    Design: Corner/state_machines/charge_letter_sets_both_ten_day_deadlines_and_flags_the_store_charged
    """
    context = authorized_store()
    investigation = substantiated_ineligible_investigation(context.store_id)
    case = open_case(investigation["id"], "INELIGIBLE_ITEMS_HARDSHIP")

    charged = ok(
        api_client.issue_charge_letter(case["id"], charge_letter_payload(), ADMIN)
    )

    assert_fields(
        charged,
        {
            "status": "CHARGE_ISSUED",
            "charge_letter_sent_at": "2026-08-01T00:00:00Z",
            "reply_due_at": "2026-08-11T00:00:00Z",
            "cmp_election_due_at": "2026-08-11T00:00:00Z",
            "charge_issued_by_user_id": "fns-admin-1",
        },
        "charge-issued case",
    )
    assert_fields(
        refresh_store(context.store_id),
        {"sanction_status": "CHARGED", "authorization_status": "AUTHORIZED"},
        "charged store",
    )


def test_a_reply_cannot_be_filed_before_the_charge_letter_exists():
    """A reply on a draft case is refused for its state, with no deadline yet in
    existence to violate.

    A reply is declared only out of CHARGE_ISSUED, and the state rule refuses
    anything else: "The target row must be in a state from which the requested
    transition is declared, otherwise `ERR_INVALID_STATE` (409)." The store is still
    merely under investigation.

    Design: Corner/state_machines/reply_to_a_charge_draft_case_is_rejected_as_invalid_state
    """
    context = authorized_store()
    investigation = substantiated_ineligible_investigation(context.store_id)
    case = open_case(investigation["id"], "INELIGIBLE_ITEMS_HARDSHIP")

    response = api_client.file_reply(
        case["id"],
        reply_payload(reply_text="Filed before the charge letter arrived."),
        context.owner_h,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert_fields(
        refresh_case(case["id"]),
        {"status": "CHARGE_DRAFT", "reply_text": None, "reply_received_at": None},
        "draft case",
    )
    assert refresh_store(context.store_id)["sanction_status"] == "UNDER_INVESTIGATION"


def test_a_released_deployment_can_never_be_activated():
    """Release is terminal, so the activation is refused and the unit that went back
    to stock is not re-reserved.

    The specification closes both exits: "`RETURNED` and `RELEASED` are the two
    terminal statuses of a deployment", and release itself moves "the unit from
    `RESERVED` back to `IN_STOCK` when no other open commitment remains."

    Design: Corner/state_machines/activating_a_released_deployment_is_rejected_as_invalid_state
    """
    owner = create_owner()
    store = create_store(owner)
    depot = create_depot(total_units_owned=5)
    terminal = create_terminal(depot)
    deployment = create_deployment(
        store,
        terminal,
        deploy_start="2026-08-01T00:00:00Z",
        deploy_end="2026-09-30T00:00:00Z",
    )
    ok(
        api_client.release_deployment(
            deployment["id"], ADMIN, close_deployment_payload("RETAILER_REQUEST")
        )
    )

    response = api_client.activate_deployment(deployment["id"], ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert_fields(
        refresh_deployment(deployment["id"]),
        {"status": "RELEASED", "activated_at": None},
        "released deployment",
    )
    assert refresh_terminal(terminal["id"])["status"] == "IN_STOCK"
    assert_depot_conservation(
        refresh_depot(depot["id"]), {"units_in_stock": 5, "units_reserved": 0}
    )


def test_four_machines_each_land_on_their_declared_initial_state():
    """A deployment, an investigation, a monitoring period and an equipment order
    each start where the specification says, with no status supplied by the caller.

    Each initial state is declared separately: a deployment begins as a reservation;
    "Opening lands the investigation in `OPEN` with `trafficking_confidence_score` at
    0 ... and `opened_by_user_id` recording the acting analyst's `X-User-ID`"; "A new
    period lands `OPEN` with `reconciliation_status` `NOT_IMPORTED`"; and "An order is
    created in `DRAFT` with its five money figures computed." Opening the
    investigation then sweeps the store's reservation, which is why the deployment is
    read before that call.

    Design: Corner/state_machines/freshly_created_rows_land_on_their_declared_initial_states
    """
    context = authorized_store()
    depot = create_depot(total_units_owned=5)
    terminal = create_terminal(depot)

    deployment = create_deployment(
        context.store,
        terminal,
        deploy_start="2026-08-01T00:00:00Z",
        deploy_end="2026-09-30T00:00:00Z",
    )
    assert deployment["status"] == "RESERVED"

    investigation = created(
        api_client.create_investigation(
            investigation_payload(context.store_id, opened_reason="ALE_REFERRAL"),
            ANALYST,
        )
    )
    period = created(
        api_client.create_redemption_period(
            redemption_period_payload(
                context.store_id,
                period_index=9,
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-09-01T00:00:00Z",
            ),
            ANALYST,
        )
    )
    order = created(
        api_client.create_equipment_order(
            equipment_order_payload(
                context.store_id, lines=[order_line("SIGNAGE_PACK", 1)]
            ),
            context.owner_h,
        )
    )

    assert_fields(
        investigation,
        {
            "status": "OPEN",
            "trafficking_confidence_score": 0,
            "opened_by_user_id": "fns-analyst-1",
        },
        "new investigation",
    )
    assert_fields(
        period,
        {"status": "OPEN", "reconciliation_status": "NOT_IMPORTED"},
        "new period",
    )
    assert_fields(order, {"status": "DRAFT", "placed_at": None}, "new order")
    assert refresh_store(context.store_id)["sanction_status"] == "UNDER_INVESTIGATION"


def test_a_sanction_case_opens_in_charge_draft_with_every_later_field_still_empty():
    """Opening a case from a substantiated investigation writes nothing but the
    linkage: no sanction, no deadlines, no penalty and no charge on the store yet.

    A case only reaches the store's sanction dimension when the charge letter goes
    out, so at creation the store is still merely under investigation, and every
    deadline the later transitions compute is still null.

    Design: Corner/state_machines/sanction_case_is_created_in_charge_draft_from_a_substantiated_investigation
    """
    context = authorized_store()
    investigation = substantiated_ineligible_investigation(context.store_id)

    case = open_case(investigation["id"], "INELIGIBLE_ITEMS_HARDSHIP")

    assert_fields(
        case,
        {
            "status": "CHARGE_DRAFT",
            "sanction_type": None,
            "disqualification_months": None,
            "reply_due_at": None,
            "cmp_election_due_at": None,
            "admin_review_due_at": None,
            "remand_count": 0,
            "cmp_outstanding_cents": 0,
        },
        "draft case",
    )
    assert refresh_store(context.store_id)["sanction_status"] == "UNDER_INVESTIGATION"


def test_a_declined_basket_is_persisted_straight_into_its_terminal_state():
    """A basket short 165c of the required other tender is written as DECLINED on
    creation, with both tender figures zeroed and the tobacco line still flagged.

    The specification writes the row and then answers with an error: "the transaction
    is created with `status` `DECLINED` and `decline_reason_code`
    `INSUFFICIENT_SPLIT_TENDER`, both `ebt_tender_cents` and `other_tender_cents` are
    recorded as 0, and the call returns `ERR_SPLIT_TENDER_SHORTFALL`." `DECLINED` is
    never reached from `AUTHORIZED`: it "is terminal from birth".

    Design: Corner/state_machines/declined_pos_transaction_is_created_directly_in_its_terminal_state
    """
    context = authorized_store()
    equipment = active_equipment(context.store)

    response = api_client.create_pos_transaction(
        pos_transaction_payload(
            context.store_id,
            equipment.deployment_id,
            line_items=[
                line_item("MILK-1", "STAPLE_FOOD", 500, 2),
                line_item("CIG-1", "TOBACCO", 1000, 2),
            ],
            snap_benefit_available_cents=5000,
            other_tender_offered_cents=2000,
            household_ebt_card_last4="4417",
        ),
        context.clerk_h,
    )

    validate_error(response, ApiErrorId.ERR_SPLIT_TENDER_SHORTFALL.value, 422)
    declined = assert_row_count(
        api_client.list_pos_transactions(
            ADMIN, {"store_id": context.store_id, "status": "DECLINED"}
        ),
        1,
    )[0]
    assert_fields(
        declined,
        {
            "status": "DECLINED",
            "decline_reason_code": "INSUFFICIENT_SPLIT_TENDER",
            "eligible_subtotal_cents": 1000,
            "ineligible_subtotal_cents": 2000,
            "tax_cents": 165,
            "ebt_tender_cents": 0,
            "other_tender_cents": 0,
            "split_tender_applied": False,
            "flagged_line_skus": ["CIG-1"],
        },
        "declined sale",
    )


def test_an_enforced_case_refuses_both_a_second_enforcement_and_a_late_review():
    """Enforcement is the end of the road: a repeat enforce and a belated review
    request both answer for the state, not for the deadline.

    The state rule sits above the deadline family in the ladder, so the review
    attempt cannot surface a window-closed code even though the clock is far past
    `admin_review_due_at`. The owner's rollup counts the case once: it is "the number
    of sanction cases, across every store the owner controls, whose case status is
    either `SANCTION_FINAL` or `ENFORCED` and whose `sanction_type` is
    `PERMANENT_DISQUALIFICATION`".

    Design: Corner/state_machines/enforced_case_refuses_further_enforcement_and_further_review
    """
    context = authorized_store()
    investigation = substantiated_trafficking_investigation(context.store_id)
    case = issue_charge_letter(open_case(investigation["id"], "TRAFFICKING")["id"])
    advance_clock("2026-08-11T00:00:00Z")
    issue_determination(case["id"], "PERMANENT_DISQUALIFICATION")
    advance_clock("2026-08-21T00:00:00Z")
    finalize_case(case["id"])
    advance_clock("2026-09-20T00:00:00Z")
    enforce_case(case["id"])

    reenforce = api_client.enforce_sanction_case(case["id"], ADMIN)
    late_review = api_client.request_administrative_review(
        case["id"],
        administrative_review_payload(grounds_text="Requesting review after enforcement."),
        context.owner_h,
    )

    validate_error(reenforce, ApiErrorId.ERR_INVALID_STATE.value, 409)
    body = validate_error(late_review, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert body["error_id"] != ApiErrorId.ERR_ADMIN_REVIEW_WINDOW_CLOSED.value
    assert_fields(
        refresh_case(case["id"]),
        {
            "status": "ENFORCED",
            "enforced_at": "2026-09-20T00:00:00Z",
            "admin_review_requested_at": None,
        },
        "enforced case",
    )
    assert_fields(
        refresh_store(context.store_id),
        {"authorization_status": "DISQUALIFIED", "permanently_disqualified": True},
        "disqualified store",
    )
    assert_fields(
        refresh_owner(context.owner_id),
        {
            "permanent_disqualification_count": 1,
            "sanction_flag": "PERMANENTLY_DISQUALIFIED",
            "status": "ACTIVE",
        },
        "owner after one disqualification",
    )


def test_withdrawing_an_application_cancels_the_visit_and_locks_the_file():
    """Withdrawal releases the inspector and then refuses submit, documents and
    decision alike.

    The specification pairs the two effects: withdrawal "drives the application to
    `WITHDRAWN` with `decision_reason_code` set to `WITHDRAWN_BY_APPLICANT`. It also
    cancels every one of the application's still-`SCHEDULED` field visits, which
    releases each cancelled visit's minutes back from the assigned inspector's
    `committed_minutes`." WITHDRAWN is one of the three terminal statuses.

    Design: Corner/state_machines/withdrawn_application_refuses_submit_documents_and_decision
    """
    owner, store, application = _submitted_application()
    submit_application(application, owner)
    inspector = create_inspector()
    visit = schedule_visit(application, inspector)
    ok(api_client.withdraw_application(application["id"], owner_headers(owner)))

    resubmit = api_client.submit_application(application["id"], owner_headers(owner))
    redocs = api_client.submit_application_documents(
        application["id"],
        documents_payload(reported_inventory_lines=INV_PASS),
        owner_headers(owner),
    )
    redecide = api_client.decide_application(
        application["id"], {"outcome": "APPROVED"}, ADMIN
    )

    for response in (resubmit, redocs, redecide):
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert_fields(
        refresh_application(application["id"]),
        {"status": "WITHDRAWN", "decision_reason_code": "WITHDRAWN_BY_APPLICANT"},
        "withdrawn application",
    )
    assert refresh_visit(visit["id"])["status"] == "CANCELLED"
    assert refresh_inspector(inspector["id"])["committed_minutes"] == 0
    assert_fields(
        refresh_store(store["id"]),
        {"authorization_status": "NOT_AUTHORIZED", "fns_number": None},
        "never-authorized store",
    )


def test_replaying_submit_and_close_is_refused_rather_than_silently_absorbed():
    """Neither action endpoint is idempotent by replay: both second calls answer 409
    and neither re-stamps its timestamp.

    Replaying a completed transition is simply a transition that is not declared from
    the current state, so the state rule answers. A second close in particular must
    not re-run the close-time scoring, which would risk a second investigation
    against a store whose only period scored nothing.

    Design: Corner/state_machines/repeating_submit_and_close_does_not_double_apply_the_transition
    """
    owner, store, application = _submitted_application()
    submit_application(application, owner)
    period = create_period(
        store["id"],
        period_index=1,
        period_start="2026-02-01T00:00:00Z",
        period_end="2026-03-01T00:00:00Z",
    )
    import_settlement(
        period["id"],
        imported_total_cents=1234567,
        imported_transaction_count=40,
        imported_large_transaction_cents=0,
        imported_even_dollar_transaction_count=0,
    )
    close_period(period["id"])

    resubmit = api_client.submit_application(application["id"], owner_headers(owner))
    reclose = api_client.close_redemption_period(period["id"], ANALYST)

    validate_error(resubmit, ApiErrorId.ERR_INVALID_STATE.value, 409)
    validate_error(reclose, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert_fields(
        refresh_application(application["id"]),
        {"status": "SUBMITTED", "submitted_at": "2026-08-01T00:00:00Z"},
        "still-submitted application",
    )
    assert_fields(
        refresh_period(period["id"]),
        {
            "status": "CLOSED",
            "closed_at": "2026-08-01T00:00:00Z",
            "flag_level": "FLAG_L0",
            "anomaly_score": 0,
        },
        "still-closed period",
    )
    assert_no_rows(api_client.list_investigations(ADMIN, {"store_id": store["id"]}))
