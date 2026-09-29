"""Round trips that must land exactly where they started.

Money is corrected by appending a compensating ledger row rather than by editing
the assessment; depot units and inspector minutes are released back to the pools
they were drawn from.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    INV_PASS,
    REVIEWER,
    administrative_review_payload,
    api_client,
    application_payload,
    assert_depot_conservation,
    assert_fields,
    assert_inspector_minutes,
    assert_ledger_conservation,
    assert_penalty_ledger_entry_shape,
    authorized_store,
    close_deployment_payload,
    create_deployment,
    create_depot,
    create_inspector,
    create_owner,
    create_store,
    create_terminal,
    created,
    elect_cmp,
    file_reply,
    four_closed_periods,
    issue_charge_letter,
    issue_determination,
    ledger_entries,
    note_payload,
    ok,
    open_case,
    owner_headers,
    refresh_application,
    refresh_case,
    refresh_depot,
    refresh_deployment,
    refresh_inspector,
    refresh_owner,
    refresh_store,
    refresh_terminal,
    refresh_visit,
    review_decision_payload,
    schedule_visit,
    substantiated_ineligible_investigation,
)

GROUNDS = "The household interview was recanted before the determination issued."


def _determined_hardship_case():
    """A hardship store with four closed periods, a civil money penalty of
    423,456c determined against it, and an administrative review pending."""
    context = authorized_store()
    four_closed_periods(context.store_id)
    investigation = substantiated_ineligible_investigation(context.store_id)
    case = open_case(investigation["id"], "INELIGIBLE_ITEMS_HARDSHIP")
    case = issue_charge_letter(case["id"])
    elect_cmp(case, context.owner)
    file_reply(case["id"], context.owner)
    issue_determination(case["id"], "CMP_IN_LIEU")
    ok(
        api_client.request_administrative_review(
            case["id"], administrative_review_payload(grounds_text=GROUNDS), context.owner_h
        )
    )
    return context, case


def test_reversal_appends_a_compensating_row_without_touching_the_assessment():
    """The reversal leaves the original assessment byte-identical and adds a
    second, negative row that brings the running balance to zero.

    The specification makes the ledger append-only: "There is exactly one
    exception. A `PenaltyLedgerEntry` is append-only: it carries `id` and
    `created_at` only." With no `updated_at` and no `version` there is nothing to
    mutate, so the correction has to be a new row whose `balance_after_cents`
    continues the running sum.

    Design: Difficulty/compensating_invariant/penalty_ledger_money_conservation_assess_then_abate_on_review_reversal
    """
    context, case = _determined_hardship_case()
    before = ledger_entries(case["id"])
    assert len(before) == 1
    assert_fields(
        before[0],
        {
            "entry_type": "CMP_ASSESSED",
            "amount_cents": 423456,
            "reason_code": "DETERMINATION",
            "balance_after_cents": 423456,
        },
        "assessment row",
    )

    ok(
        api_client.decide_administrative_review(
            case["id"],
            review_decision_payload(
                outcome="REVERSED", reason_code="EVIDENCE_INSUFFICIENT"
            ),
            REVIEWER,
        )
    )

    after = ledger_entries(case["id"])
    assert len(after) == 2, f"expected two ledger rows, got {len(after)}"
    assert after[0] == before[0], "the assessment row was rewritten instead of offset"
    assert_penalty_ledger_entry_shape(after[1])
    assert_fields(
        after[1],
        {
            "entry_type": "CMP_ABATEMENT",
            "amount_cents": -423456,
            "reason_code": "REVIEW_REVERSAL",
            "balance_after_cents": 0,
        },
        "abatement row",
    )
    assert sum(entry["amount_cents"] for entry in after) == 0


def test_reversed_penalty_clears_the_case_and_owner_balances_but_not_the_authorization():
    """The reversal zeroes the case balance and the owner's rollup, while the store
    keeps trading.

    The specification ties the owner's flag to the money -- its owner "carries the
    `HAS_ACTIVE_CMP_DEBT` flag until the balance reaches zero" -- so a fully abated
    penalty returns the owner to CLEAR. The store's sanction dimension records the
    reversal without ever having lost its authorization, because a civil money
    penalty in lieu of disqualification never suspends the store.

    Design: Difficulty/compensating_invariant/penalty_ledger_money_conservation_assess_then_abate_on_review_reversal
    """
    context, case = _determined_hardship_case()

    ok(
        api_client.decide_administrative_review(
            case["id"],
            review_decision_payload(
                outcome="REVERSED", reason_code="EVIDENCE_INSUFFICIENT"
            ),
            REVIEWER,
        )
    )

    final_case = refresh_case(case["id"])
    assert_fields(
        final_case,
        {
            "cmp_outstanding_cents": 0,
            "status": "SANCTION_REVERSED",
            "admin_review_outcome": "REVERSED",
            "admin_review_decided_by_user_id": "review-officer-1",
        },
        "reversed case",
    )
    assert_ledger_conservation(ledger_entries(case["id"]), final_case)
    assert_fields(
        refresh_owner(context.owner_id),
        {"cmp_outstanding_cents": 0, "sanction_flag": "CLEAR"},
        "owner after abatement",
    )
    assert_fields(
        refresh_store(context.store_id),
        {"sanction_status": "SANCTION_REVERSED", "authorization_status": "AUTHORIZED"},
        "store after abatement",
    )


def _depot_with_one_terminal():
    context = authorized_store()
    depot = create_depot(total_units_owned=5)
    terminal = create_terminal(depot)
    return context, depot, terminal


def test_depot_counters_move_between_columns_as_a_unit_is_reserved_and_activated():
    """Booking a deployment moves one unit from stock to reserved, and activating
    it moves the same unit from reserved to deployed.

    The specification states the identity that must hold at every step:
    "`units_in_stock` plus `units_reserved` plus `units_deployed` plus
    `units_pending_return` plus `units_retired` equals `total_units_owned`." No
    step may create or destroy a unit, only move it between columns.

    Design: Difficulty/compensating_invariant/depot_unit_conservation_reserve_activate_return_round_trip
    """
    context, depot, terminal = _depot_with_one_terminal()
    assert_depot_conservation(
        depot,
        {
            "units_in_stock": 5,
            "units_reserved": 0,
            "units_deployed": 0,
            "units_pending_return": 0,
            "units_retired": 0,
        },
    )

    deployment = create_deployment(context.store, terminal)

    assert_depot_conservation(
        refresh_depot(depot["id"]),
        {"units_in_stock": 4, "units_reserved": 1, "units_deployed": 0},
    )
    assert refresh_terminal(terminal["id"])["status"] == "RESERVED"

    ok(api_client.activate_deployment(deployment["id"], ADMIN))

    assert_depot_conservation(
        refresh_depot(depot["id"]),
        {"units_in_stock": 4, "units_reserved": 0, "units_deployed": 1},
    )
    assert refresh_terminal(terminal["id"])["status"] == "DEPLOYED"
    assert refresh_store(context.store_id)["active_terminal_count"] == 1


def test_returning_the_unit_restores_the_depot_to_its_opening_position():
    """After the return, all five units are back in stock and the store counts no
    active terminal, closing the round trip exactly.

    The closing action stamps the reason code and the closing instant on the
    deployment, and the physical unit becomes available again -- a returned unit
    goes back to stock rather than to the retired column, so the five counters read
    exactly as they did before the deployment was ever booked.

    Design: Difficulty/compensating_invariant/depot_unit_conservation_reserve_activate_return_round_trip
    """
    context, depot, terminal = _depot_with_one_terminal()
    deployment = create_deployment(context.store, terminal)
    ok(api_client.activate_deployment(deployment["id"], ADMIN))

    ok(
        api_client.return_deployment(
            deployment["id"],
            ADMIN,
            close_deployment_payload(close_reason_code="END_OF_TERM"),
        )
    )

    assert_depot_conservation(
        refresh_depot(depot["id"]),
        {
            "units_in_stock": 5,
            "units_reserved": 0,
            "units_deployed": 0,
            "units_pending_return": 0,
            "units_retired": 0,
        },
    )
    assert refresh_terminal(terminal["id"])["status"] == "IN_STOCK"
    assert refresh_store(context.store_id)["active_terminal_count"] == 0
    assert_fields(
        refresh_deployment(deployment["id"]),
        {
            "status": "RETURNED",
            "close_reason_code": "END_OF_TERM",
            "closed_at": "2026-08-01T00:00:00Z",
        },
        "returned deployment",
    )


def _two_applications_one_inspector():
    owner = create_owner()
    stores = [
        create_store(owner),
        create_store(
            owner,
            store_name="Rio Corner Market",
            checkout_lane_count=1,
            annual_gross_sales_cents=24000000,
            annual_staple_sales_cents=14000000,
            max_terminal_slots=1,
            tax_rate_bps=None,
            hardship_designated=None,
        ),
    ]
    applications = []
    for store in stores:
        application = created(
            api_client.create_application(
                application_payload(
                    store["id"], store["version"], reported_inventory_lines=INV_PASS
                ),
                owner_headers(owner),
            )
        )
        ok(api_client.submit_application(application["id"], owner_headers(owner)))
        applications.append(application)
    return applications, create_inspector()


def test_scheduling_two_visits_accumulates_exactly_their_window_minutes():
    """An inspector's committed minutes climb from 0 to 120 to 180 as two visits of
    two hours and one hour are booked.

    Committed minutes are the sum of the `window_minutes` of the inspector's
    scheduled and in-progress visits, and the specification is explicit that the
    travel buffer plays no part in the total: "Note that the travel buffer widens
    the *conflict* test but is never added to the *minute* total."

    Design: Difficulty/compensating_invariant/inspector_committed_minutes_conservation_schedule_then_cancel_round_trip
    """
    applications, inspector = _two_applications_one_inspector()
    assert_inspector_minutes(inspector, 0)

    first = schedule_visit(
        applications[0],
        inspector,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T02:00:00Z",
    )
    assert first["window_minutes"] == 120
    assert_inspector_minutes(refresh_inspector(inspector["id"]), 120)

    second = schedule_visit(
        applications[1],
        inspector,
        window_start="2026-08-01T04:00:00Z",
        window_end="2026-08-01T05:00:00Z",
    )
    assert second["window_minutes"] == 60
    assert_inspector_minutes(refresh_inspector(inspector["id"]), 180)


def test_cancelling_both_visits_returns_the_inspector_to_zero_committed_minutes():
    """Each cancellation gives back exactly the minutes that visit took, and the
    ceiling itself never moves.

    A cancelled visit is no longer scheduled, so it drops out of the committed
    total, and the applications it was booked for stay waiting for a visit rather
    than reverting or advancing. The inspector's `max_daily_minutes` is a declared
    input and is untouched throughout.

    Design: Difficulty/compensating_invariant/inspector_committed_minutes_conservation_schedule_then_cancel_round_trip
    """
    applications, inspector = _two_applications_one_inspector()
    first = schedule_visit(
        applications[0],
        inspector,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T02:00:00Z",
    )
    second = schedule_visit(
        applications[1],
        inspector,
        window_start="2026-08-01T04:00:00Z",
        window_end="2026-08-01T05:00:00Z",
    )

    ok(
        api_client.cancel_store_visit(
            second["id"],
            ANALYST,
            note_payload(note="Inspector reassigned to a compliance sweep."),
        )
    )
    assert_inspector_minutes(refresh_inspector(inspector["id"]), 120)

    ok(
        api_client.cancel_store_visit(
            first["id"],
            ANALYST,
            note_payload(note="Applicant asked to reschedule."),
        )
    )

    final = refresh_inspector(inspector["id"])
    assert_inspector_minutes(final, 0)
    assert final["max_daily_minutes"] == 480
    assert refresh_visit(first["id"])["status"] == "CANCELLED"
    assert refresh_visit(second["id"])["status"] == "CANCELLED"
    for application in applications:
        assert refresh_application(application["id"])["status"] == "PENDING_VISIT"
