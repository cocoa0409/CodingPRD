"""Phase gating, milestone ordering, the crew-start gates, the freeze terminal,
the reschedule cap, the invoice action caps and the close-out end game."""

from test_helpers import (
    ApiErrorId,
    BILLING_ADMIN,
    FREEZE_INSTANT,
    MOVE_MANAGER,
    MOVE_START,
    api_client,
    accept_vendor_assignment,
    assert_money,
    assert_same_instant,
    assign_crew,
    complete_milestone,
    confirm_assignment,
    coordination_fee_cents,
    create_invoice_line_payload,
    designate,
    drive_sort_plan_to_approved,
    freeze_and_start,
    get_success_data,
    invoice_of,
    labor_cents,
    long_carry_surcharge_cents,
    make_vendor_headers,
    milestone_by_key,
    new_crew_member,
    new_engagement,
    new_item,
    new_move_day_plan,
    new_sort_plan,
    new_vendor,
    new_vendor_assignment,
    no_show,
    read_crew_assignment,
    read_engagement,
    read_invoice,
    read_item,
    read_milestone,
    read_move_day_plan,
    read_sort_plan,
    schedule_vendor_assignment,
    set_clock,
    setup_completed_move_day,
    setup_engagement,
    setup_issued_invoice,
    setup_move_day_plan_confirmed,
    stairs_surcharge_cents,
    submit_sort_plan,
    travel_surcharge_cents,
    validate_error,
    validate_paginated,
    validate_success,
)

CHECK_OUT_2330 = "2026-06-15T23:30:00.000Z"
EXPECTED_LABOUR = labor_cents(9.50, 9500) + labor_cents(6.00, 6800)
EXPECTED_SUBTOTAL = (
    EXPECTED_LABOUR
    + travel_surcharge_cents(22)
    + stairs_surcharge_cents(2, 2)
    + long_carry_surcharge_cents(100)
)
EXPECTED_TOTAL = EXPECTED_SUBTOTAL + coordination_fee_cents(EXPECTED_SUBTOTAL)

# PRD §3.11: issuing "appends the three site surcharges and then the coordination
# fee", while a recall "removes the `COORDINATION_FEE` line that issuing had
# appended" and nothing else. Every ledger line is immutable, so a second and third
# issue append a second and third set of surcharges while only ever one coordination
# fee is present, and the pre-fee subtotal grows by one surcharge set per re-issue.
EXPECTED_SURCHARGES = (
    travel_surcharge_cents(22) + stairs_surcharge_cents(2, 2) + long_carry_surcharge_cents(100)
)


def _subtotal_after_issues(issue_count: int) -> int:
    return EXPECTED_LABOUR + issue_count * EXPECTED_SURCHARGES


def _total_after_issues(issue_count: int) -> int:
    subtotal = _subtotal_after_issues(issue_count)
    return subtotal + coordination_fee_cents(subtotal)


def test_a_move_day_plan_cannot_be_created_while_the_phase_is_assessment():
    """PRD §2.7: "The engagement's `phase` permits the operation: cataloguing an item
    and designating one require phase `ASSESSMENT` or `SORT_PLAN`; move-day plan
    creation requires phase `PACK` or `MOVE_DAY`; unpack-session and punch-list
    creation require phase `SETTLE_IN` or `CLOSE_OUT`. Otherwise
    `ERR_PHASE_NOT_PERMITTED`, HTTP 409."

    Design: Corner/validations/phase_gate_blocks_move_day_plan_before_sort_plan_approval
    """
    world = setup_engagement()
    eng_id = world["engagement_id"]
    item = new_item(eng_id, label="Old linens", category="LINENS", footprint_linear_inches=10, volume_cft=5)
    designate(item["id"], "DONATE")

    validate_error(
        api_client.create_move_day_plan(
            {
                "engagement_id": eng_id,
                "scheduled_start_utc": MOVE_START,
                "truck_capacity_cft": 1000,
                "truck_count": 1,
            },
            MOVE_MANAGER,
        ),
        ApiErrorId.ERR_PHASE_NOT_PERMITTED.value,
    )
    assert read_engagement(eng_id)["phase"] == "ASSESSMENT"
    _, meta = validate_paginated(
        api_client.list_move_day_plans(MOVE_MANAGER, params={"engagement_id": eng_id})
    )
    assert meta["total_count"] == 0


def test_the_predecessor_and_successor_milestone_gates_have_their_own_codes():
    """PRD §2.7: "A milestone can be completed only when the milestone whose
    `sequence_index` is one lower on the same engagement is `COMPLETE`. Otherwise
    `ERR_PREDECESSOR_MILESTONE_INCOMPLETE`, HTTP 409. Applies to
    `POST /milestones/{id}/complete`."
    PRD §2.7: "A milestone can be reopened only when no milestone of the same
    engagement with a higher `sequence_index` is `COMPLETE`. Otherwise
    `ERR_SUCCESSOR_MILESTONE_COMPLETE`, HTTP 409. Applies to
    `POST /milestones/{id}/reopen`."

    Design: Corner/validations/milestone_predecessor_and_successor_gates
    """
    world = setup_engagement()
    eng_id, party_id = world["engagement_id"], world["client_party"]["id"]
    item = new_item(eng_id, label="Old linens", category="LINENS", footprint_linear_inches=10, volume_cft=5)
    designate(item["id"], "DONATE")

    settle_in = milestone_by_key(eng_id, "SETTLE_IN")
    validate_error(
        api_client.complete_milestone(
            settle_in["id"], {"completed_by_party_id": party_id}, MOVE_MANAGER
        ),
        ApiErrorId.ERR_PREDECESSOR_MILESTONE_INCOMPLETE.value,
    )

    assessment_id = milestone_by_key(eng_id, "ASSESSMENT")["id"]
    complete_milestone(assessment_id, party_id)
    plan = new_sort_plan(eng_id)
    submit_sort_plan(plan["id"])
    get_success_data(
        api_client.approve_sort_plan(plan["id"], {"approved_by_party_id": party_id}, MOVE_MANAGER)
    )

    validate_error(
        api_client.reopen_milestone(
            assessment_id, {"reason": "Assessment was incomplete"}, MOVE_MANAGER
        ),
        ApiErrorId.ERR_SUCCESSOR_MILESTONE_COMPLETE.value,
    )
    assert read_milestone(assessment_id)["status"] == "COMPLETE"
    assert read_engagement(eng_id)["phase"] == "PACK"


def test_the_crew_lead_gate_is_reached_only_once_the_crew_minimum_is_met():
    """PRD §3.7: "Starting move day moves the plan from `FROZEN` to `IN_PROGRESS`,
    requires the clock to be at or after `scheduled_start_utc`, requires
    `crew_confirmed_count` to have reached `crew_min_required` — otherwise
    `ERR_CREW_MINIMUM_NOT_MET` — and requires at least one lead on the plan's
    non-terminal roster — otherwise `ERR_CREW_LEAD_REQUIRED`."
    PRD §2.7: "At least one of the plan's non-terminal assignments belongs to a crew
    member whose `crew_role` is `LEAD`, at start. Otherwise `ERR_CREW_LEAD_REQUIRED`,
    HTTP 422. Applies to `POST /move-day-plans/{id}/start`."

    Design: Corner/validations/crew_lead_gate_runs_after_the_crew_minimum_gate_at_start
    """
    world = setup_engagement()
    eng_id = world["engagement_id"]
    item = new_item(eng_id, label="Old linens", category="LINENS", footprint_linear_inches=10, volume_cft=5)
    designate(item["id"], "DONATE")
    drive_sort_plan_to_approved(eng_id, world["client_party"]["id"])

    plan = new_move_day_plan(eng_id)
    lead = new_crew_member("Tom Reyes", "LEAD", 9500)
    packer_one = new_crew_member("Nina Ortiz", "PACKER", 6800)
    packer_two = new_crew_member("Jo Alvarez", "PACKER", 6800)
    assignments = [
        assign_crew(plan["id"], member["id"]) for member in (lead, packer_one, packer_two)
    ]
    for assignment in assignments:
        confirm_assignment(assignment["id"])
    get_success_data(api_client.confirm_move_day_plan(plan["id"], MOVE_MANAGER))
    set_clock(FREEZE_INSTANT)
    get_success_data(api_client.freeze_move_day_plan(plan["id"], MOVE_MANAGER))
    set_clock(MOVE_START)

    no_show(assignments[0]["id"], "Lead called in sick")
    validate_error(
        api_client.start_move_day_plan(plan["id"], MOVE_MANAGER),
        ApiErrorId.ERR_CREW_LEAD_REQUIRED.value,
    )
    no_show(assignments[1]["id"], "Packer called in sick")
    validate_error(
        api_client.start_move_day_plan(plan["id"], MOVE_MANAGER),
        ApiErrorId.ERR_CREW_MINIMUM_NOT_MET.value,
    )
    frozen = read_move_day_plan(plan["id"])
    assert frozen["status"] == "FROZEN"
    assert frozen["crew_confirmed_count"] == 1


def test_a_frozen_sort_plan_can_never_be_reopened_however_much_budget_remains():
    """PRD §2.7: "A sort plan in status `FROZEN` can never be reopened, regardless of
    its `reopen_count`. Otherwise `ERR_SORT_PLAN_FROZEN`, HTTP 409. Applies to
    `POST /sort-plans/{id}/reopen`."
    PRD §3.6: "`FROZEN` is the plan's terminal state and is never reached by a user
    action."

    Design: Corner/validations/sort_plan_frozen_can_never_be_reopened
    """
    world = setup_move_day_plan_confirmed(
        keep_items=[], other_items=[{"label": "Old linens", "category": "LINENS", "footprint_linear_inches": 10, "volume_cft": 5}]
    )
    set_clock(FREEZE_INSTANT)
    get_success_data(api_client.freeze_move_day_plan(world["plan"]["id"], MOVE_MANAGER))

    validate_error(
        api_client.reopen_sort_plan(
            world["sort_plan"]["id"], {"reason": "Client changed her mind"}, MOVE_MANAGER
        ),
        ApiErrorId.ERR_SORT_PLAN_FROZEN.value,
    )
    plan = read_sort_plan(world["sort_plan"]["id"])
    assert plan["status"] == "FROZEN"
    assert plan["reopen_count"] == 0
    assert_same_instant(plan["frozen_at_utc"], FREEZE_INSTANT, "frozen_at_utc")
    assert read_item(world["items"][0]["id"])["disposition_locked"] is True


def test_only_one_reschedule_is_permitted_and_it_reverts_the_whole_roster():
    """PRD §2.7: "The move-day plan's `reschedule_count` is strictly less than 1, and
    `new_start_utc` is strictly after the current logical clock. Otherwise
    `ERR_RESCHEDULE_LIMIT`, HTTP 409. Applies to
    `POST /move-day-plans/{id}/reschedule`."
    PRD §3.7: "Only one reschedule is permitted per plan; a second attempt, or a
    `new_start_utc` that is not strictly after the clock, is refused with
    `ERR_RESCHEDULE_LIMIT`."

    Design: Corner/validations/reschedule_limit_and_recrew_cascade
    """
    world = setup_move_day_plan_confirmed(
        keep_items=[], other_items=[{"label": "Old linens", "category": "LINENS", "footprint_linear_inches": 10, "volume_cft": 5}]
    )
    plan_id = world["plan"]["id"]
    validate_success(
        api_client.reschedule_move_day_plan(
            plan_id,
            {"new_start_utc": "2026-06-22T14:00:00.000Z", "reason": "Elevator reservation moved"},
            MOVE_MANAGER,
        )
    )
    plan = read_move_day_plan(plan_id)
    assert plan["status"] == "DRAFT"
    assert plan["reschedule_count"] == 1
    assert_same_instant(plan["scheduled_start_utc"], "2026-06-22T14:00:00.000Z", "scheduled_start_utc")
    assert_same_instant(plan["freeze_at_utc"], "2026-06-19T14:00:00.000Z", "freeze_at_utc")
    assert plan["crew_confirmed_count"] == 0
    assert read_crew_assignment(world["lead_assignment"]["id"])["status"] == "ASSIGNED"
    assert read_crew_assignment(world["packer_assignment"]["id"])["status"] == "ASSIGNED"

    # PRD §3.7: rescheduling is reachable only from CONFIRMED and FROZEN, and the
    # first reschedule left the plan in DRAFT with every assignment back at ASSIGNED.
    # Rung 48 (originating set) precedes rung 59 (the reschedule cap), so the roster
    # is re-confirmed and the plan driven back to CONFIRMED before the cap is probed.
    confirm_assignment(world["lead_assignment"]["id"])
    confirm_assignment(world["packer_assignment"]["id"])
    validate_success(api_client.confirm_move_day_plan(plan_id, MOVE_MANAGER))
    assert read_move_day_plan(plan_id)["status"] == "CONFIRMED"

    validate_error(
        api_client.reschedule_move_day_plan(
            plan_id,
            {"new_start_utc": "2026-06-29T14:00:00.000Z", "reason": "Elevator reservation moved again"},
            MOVE_MANAGER,
        ),
        ApiErrorId.ERR_RESCHEDULE_LIMIT.value,
    )


def test_two_recalls_are_permitted_and_the_third_hits_the_invoice_action_cap():
    """PRD §3.11: "Billing may recall the invoice to `DRAFT` with a `reason`, but
    only while `payments_cents` is exactly zero and `recall_count` is below two; the
    recall raises `recall_count` and removes the `COORDINATION_FEE` line that issuing
    had appended."
    PRD §2.7: "The invoice's `recall_count` is below 2 and its `dispute_count` is
    below 2. Otherwise `ERR_INVOICE_ACTION_LIMIT`, HTTP 409. Applies to
    `POST /invoices/{id}/recall` and `POST /invoices/{id}/dispute`."

    Design: Corner/validations/invoice_recall_dispute_caps_and_reopen_cap
    """
    world = setup_issued_invoice(
        keep_items=[],
        other_items=[{"label": "Old linens", "category": "LINENS", "footprint_linear_inches": 10, "volume_cft": 5}],
        lead_in=MOVE_START,
        packer_in="2026-06-15T17:30:00.000Z",
        lead_out=CHECK_OUT_2330,
        packer_out=None,
        complete_at=CHECK_OUT_2330,
        actual_loaded_volume_cft=2200,
    )
    invoice_id = world["invoice"]["id"]

    validate_success(api_client.recall_invoice(invoice_id, {"reason": "Wrong mileage on file"}, BILLING_ADMIN))
    validate_success(api_client.issue_invoice(invoice_id, BILLING_ADMIN))
    assert read_invoice(invoice_id)["recall_count"] == 1

    validate_success(api_client.recall_invoice(invoice_id, {"reason": "Wrong stairs count"}, BILLING_ADMIN))
    validate_success(api_client.issue_invoice(invoice_id, BILLING_ADMIN))
    validate_error(
        api_client.recall_invoice(invoice_id, {"reason": "Third correction"}, BILLING_ADMIN),
        ApiErrorId.ERR_INVOICE_ACTION_LIMIT.value,
    )
    invoice = read_invoice(invoice_id)
    assert invoice["recall_count"] == 2
    assert invoice["status"] == "ISSUED"
    assert_money(invoice["total_cents"], _total_after_issues(3), "total_cents")

    assessment_id = milestone_by_key(world["engagement_id"], "ASSESSMENT")["id"]
    validate_error(
        api_client.reopen_milestone(assessment_id, {"reason": "First reopen"}, MOVE_MANAGER),
        ApiErrorId.ERR_SUCCESSOR_MILESTONE_COMPLETE.value,
    )


def test_close_out_walks_the_balance_the_milestones_and_the_finalisation_lockdown():
    """PRD §3.11: "Closing out the engagement is the move manager's final act and
    takes a `signed_off_by_party_id`. It requires the engagement to be `ACTIVE`, the
    `CLOSE_OUT` milestone to be `COMPLETE`, no punch-list item to be `OPEN` or
    `REOPENED`, and `billing_hold` to be false; a failure on any of those reports
    `ERR_CLOSE_OUT_BLOCKED`."
    PRD §3.11: "It stamps `finalized_at_utc`, and from that instant the ninth gate is
    closed for the whole engagement: no ledger line may be appended, no payment
    recorded, no dispute raised, no recall taken, and no consignment settlement,
    reversal, disposal fee or vendor payout may post."

    Design: Corner/endpoints/close_out_end_to_end_with_balance_and_finalization_gates
    """
    world = setup_issued_invoice(
        keep_items=[],
        other_items=[{"label": "Old linens", "category": "LINENS", "footprint_linear_inches": 10, "volume_cft": 5}],
        lead_in=MOVE_START,
        packer_in="2026-06-15T17:30:00.000Z",
        lead_out=CHECK_OUT_2330,
        packer_out=None,
        complete_at=CHECK_OUT_2330,
        actual_loaded_volume_cft=2200,
    )
    eng_id, invoice_id, party_id = (
        world["engagement_id"],
        world["invoice"]["id"],
        world["client_party"]["id"],
    )
    vendor = new_vendor("Bright Path Cleaning", "CLEANING", "2027-01-31", daily_capacity=3, holdback_pct=0.1)
    vendor_assignment = new_vendor_assignment(eng_id, vendor["id"], "CLEANING", "2026-06-16", 85000)
    accept_vendor_assignment(vendor_assignment["id"], vendor["id"])
    schedule_vendor_assignment(vendor_assignment["id"])

    validate_error(
        api_client.finalize_invoice(invoice_id, BILLING_ADMIN),
        ApiErrorId.ERR_BALANCE_OUTSTANDING.value,
    )
    validate_success(
        api_client.record_payment(
            invoice_id, {"amount_cents": EXPECTED_TOTAL, "paid_on": "2026-06-18"}, BILLING_ADMIN
        )
    )
    paid = read_invoice(invoice_id)
    assert_money(paid["payments_cents"], EXPECTED_TOTAL, "payments_cents")
    assert_money(paid["balance_due_cents"], 0, "balance_due_cents")

    validate_error(
        api_client.close_out_engagement(eng_id, {"signed_off_by_party_id": party_id}, MOVE_MANAGER),
        ApiErrorId.ERR_CLOSE_OUT_BLOCKED.value,
    )
    for key in ("SETTLE_IN", "CLOSE_OUT"):
        complete_milestone(milestone_by_key(eng_id, key)["id"], party_id)

    validate_success(api_client.finalize_invoice(invoice_id, BILLING_ADMIN))
    assert read_invoice(invoice_id)["status"] == "FINALIZED"

    validate_error(
        api_client.create_invoice_line(
            create_invoice_line_payload(
                invoice_id, "MANUAL_ADJUSTMENT", 5000, "Late correction", read_invoice(invoice_id)["version"]
            ),
            BILLING_ADMIN,
        ),
        ApiErrorId.ERR_INVOICE_FINALIZED.value,
    )
    validate_error(
        api_client.perform_vendor_assignment(
            vendor_assignment["id"], {"performed_at_utc": "2026-06-16T10:00:00.000Z"}, MOVE_MANAGER
        ),
        ApiErrorId.ERR_BILLING_CLOSED.value,
    )

    validate_success(
        api_client.close_out_engagement(eng_id, {"signed_off_by_party_id": party_id}, MOVE_MANAGER)
    )
    engagement = read_engagement(eng_id)
    assert engagement["status"] == "CLOSED"
    assert_same_instant(engagement["closed_at_utc"], CHECK_OUT_2330, "closed_at_utc")

    validate_error(
        api_client.create_inventory_item(
            {
                "engagement_id": eng_id,
                "label": "Late addition",
                "category": "MISC",
                "footprint_linear_inches": 4,
                "volume_cft": 1,
            },
            MOVE_MANAGER,
        ),
        ApiErrorId.ERR_ENGAGEMENT_CLOSED.value,
    )
    assert read_engagement(eng_id)["inventory_item_count"] == 1
