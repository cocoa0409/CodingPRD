"""Non-linear paths through the application loop and the store's two dimensions.

The application re-enters PENDING_VISIT twice and exits to DENIED on the third
identical failure. The store's authorization and sanction dimensions move
independently until finalization couples them.
"""
from test_helpers import (
    ADMIN,
    BASKET_SIMPLE,
    INV_DIVERGENT,
    ApiErrorId,
    active_equipment,
    advance_clock,
    api_client,
    assert_fields,
    assert_inspector_minutes,
    assert_row_count,
    authorized_store,
    created,
    documents_payload,
    file_reply,
    finalize_case,
    issue_charge_letter,
    issue_determination,
    open_case,
    ok,
    pending_visit_application,
    pos_transaction_payload,
    refresh_application,
    refresh_deployment,
    refresh_inspector,
    refresh_store,
    refresh_visit,
    schedule_visit,
    start_visit,
    submit_findings,
    substantiated_ineligible_investigation,
    validate_error,
)


def _resubmit_documents(context):
    return ok(
        api_client.submit_application_documents(
            context.application_id,
            documents_payload(reported_inventory_lines=INV_DIVERGENT),
            context.owner_h,
        )
    )


def _failing_visit(context, window_start, window_end):
    """Schedule, open and fail a further pre-authorization visit."""
    application = refresh_application(context.application_id)
    visit = schedule_visit(
        application,
        context.inspector,
        window_start=window_start,
        window_end=window_end,
    )
    advance_clock(window_start)
    start_visit(visit, context.inspector)
    submit_findings(
        visit,
        context.inspector,
        observed_inventory_lines=INV_DIVERGENT,
        observed_staple_shelf_linear_feet=30,
    )
    return visit


def test_second_failing_findings_loops_the_application_back_to_pending_documents():
    """The identical failing findings call is answered with another deficiency
    hold the second time it is made, not with a denial.

    The specification bounds the loop rather than the attempt: a store may work
    through at most three deficiency cycles, so the second failure still routes
    the application to PENDING_DOCUMENTS, only with the counter advanced.

    Design: Difficulty/non_linear_state_machine/application_deficiency_cycle_loops_twice_then_third_failure_denies
    """
    context = pending_visit_application(inventory_lines=INV_DIVERGENT)
    submit_findings(
        context.visit,
        context.inspector,
        observed_inventory_lines=INV_DIVERGENT,
        observed_staple_shelf_linear_feet=30,
    )
    assert refresh_application(context.application_id)["deficiency_cycle_count"] == 1

    _resubmit_documents(context)
    assert refresh_application(context.application_id)["status"] == "SUBMITTED"

    _failing_visit(context, "2026-08-01T04:00:00Z", "2026-08-01T06:00:00Z")

    application = refresh_application(context.application_id)
    assert_fields(
        application,
        {
            "status": "PENDING_DOCUMENTS",
            "hold_reason_code": "STAPLE_STOCK_INSUFFICIENT",
            "deficiency_cycle_count": 2,
        },
        "application after the second failure",
    )
    assert application["decided_at"] is None, (
        "a looping application has not been decided yet"
    )


def test_third_identical_failure_exhausts_the_cycles_and_denies():
    """The third byte-identical failing findings call denies the application, and
    the store is never authorized.

    Only the accumulated counter distinguishes it: the specification exhausts the
    deficiency cycles at three, so the same call that produced a hold twice now
    records a decision with the cycles-exhausted reason at the current logical
    clock, and the store keeps no FNS number.

    Design: Difficulty/non_linear_state_machine/application_deficiency_cycle_loops_twice_then_third_failure_denies
    """
    context = pending_visit_application(inventory_lines=INV_DIVERGENT)
    submit_findings(
        context.visit,
        context.inspector,
        observed_inventory_lines=INV_DIVERGENT,
        observed_staple_shelf_linear_feet=30,
    )
    _resubmit_documents(context)
    visit2 = _failing_visit(context, "2026-08-01T04:00:00Z", "2026-08-01T06:00:00Z")
    _resubmit_documents(context)
    visit3 = _failing_visit(context, "2026-08-01T08:00:00Z", "2026-08-01T10:00:00Z")

    application = refresh_application(context.application_id)
    assert_fields(
        application,
        {
            "status": "DENIED",
            "deficiency_cycle_count": 3,
            "decision_reason_code": "DEFICIENCY_CYCLES_EXHAUSTED",
            "decided_at": "2026-08-01T08:00:00Z",
            "verified_criterion_pass": False,
        },
        "denied application",
    )
    for visit in (context.visit, visit2, visit3):
        assert refresh_visit(visit["id"])["status"] == "FINDINGS_SUBMITTED"

    store = refresh_store(context.store_id)
    assert_fields(
        store,
        {"authorization_status": "NOT_AUTHORIZED", "fns_number": None},
        "never-authorized store",
    )
    assert_inspector_minutes(refresh_inspector(context.inspector_id), 0)


def _ring_up(context, equipment):
    return api_client.create_pos_transaction(
        pos_transaction_payload(
            context.store_id,
            equipment.deployment_id,
            line_items=BASKET_SIMPLE,
            snap_benefit_available_cents=1000,
            other_tender_offered_cents=0,
            household_ebt_card_last4="8821",
        ),
        context.clerk_h,
    )


def _charged_hardship_case(context):
    investigation = substantiated_ineligible_investigation(context.store_id)
    case = open_case(investigation["id"], "INELIGIBLE_ITEMS_HARDSHIP")
    case = issue_charge_letter(case["id"])
    file_reply(case["id"], context.owner)
    return case


def test_sanction_dimension_walks_while_the_store_keeps_trading():
    """Opening an investigation, charging the store and issuing a determination
    all move only the sanction dimension: the store stays AUTHORIZED and its
    sales keep clearing.

    The specification keeps the two dimensions apart -- "A store trades normally
    through investigation, charge letter, reply, determination and administrative
    review." -- and confines the investigation's equipment cascade to reservations,
    so an ACTIVE deployment is untouched.

    Design: Difficulty/non_linear_state_machine/store_parallel_dimensions_move_independently_and_pair_gates_pos_sales
    """
    context = authorized_store()
    equipment = active_equipment(context.store)
    case = _charged_hardship_case(context)

    store = refresh_store(context.store_id)
    assert_fields(
        store,
        {"authorization_status": "AUTHORIZED", "sanction_status": "CHARGED"},
        "charged but trading store",
    )
    assert refresh_deployment(equipment.deployment_id)["status"] == "ACTIVE"

    first_sale = created(_ring_up(context, equipment))
    assert_fields(
        first_sale,
        {
            "status": "AUTHORIZED",
            "ebt_tender_cents": 758,
            "split_tender_applied": False,
        },
        "sale before the determination",
    )

    issue_determination(case["id"], "TEMPORARY_DISQUALIFICATION")

    second_sale = created(_ring_up(context, equipment))
    assert second_sale["status"] == "AUTHORIZED", (
        "a determined case does not yet stop the store from trading"
    )
    assert refresh_store(context.store_id)["authorization_status"] == "AUTHORIZED"


def test_finalization_couples_the_dimensions_and_blocks_the_identical_sale():
    """Finalizing the temporary disqualification suspends the store, and the sale
    that cleared twice before is now refused -- without leaving a row behind.

    The specification is explicit that finalization is the coupling point: the
    store "stops trading the moment a disqualification is finalized, because
    finalization suspends it", while the hardware stays put until enforcement.

    Design: Difficulty/non_linear_state_machine/store_parallel_dimensions_move_independently_and_pair_gates_pos_sales
    """
    context = authorized_store()
    equipment = active_equipment(context.store)
    case = _charged_hardship_case(context)
    created(_ring_up(context, equipment))
    case = issue_determination(case["id"], "TEMPORARY_DISQUALIFICATION")
    created(_ring_up(context, equipment))

    advance_clock("2026-08-12T00:00:00Z")
    case = finalize_case(case["id"])

    assert_fields(
        case,
        {
            "disqualification_months": 3,
            "final_decision_at": "2026-08-12T00:00:00Z",
            "effective_date": "2026-09-11T00:00:00Z",
        },
        "finalized case",
    )
    store = refresh_store(context.store_id)
    assert_fields(
        store,
        {
            "authorization_status": "SUSPENDED",
            "sanction_status": "SANCTION_FINAL",
            "active_terminal_count": 1,
        },
        "suspended store",
    )

    validate_error(
        _ring_up(context, equipment),
        ApiErrorId.ERR_STORE_NOT_AUTHORIZED.value,
        403,
    )
    assert_row_count(
        api_client.list_pos_transactions(ADMIN, {"store_id": context.store_id}), 2
    )
