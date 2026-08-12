"""The invoice dispute cycle, the two uncredited lot exits, the hourly ledger
line and the milestone / punch-list re-entry loops."""

from datetime import timedelta

from test_helpers import (
    BILLING_ADMIN,
    MOVE_MANAGER,
    MOVE_START,
    PUNCH_SLA_HOURS,
    api_client,
    assert_exactly_one_line,
    assert_hours,
    assert_money,
    assert_no_line_of_type,
    assert_same_instant,
    assert_two_dp,
    complete_unpack_session,
    coordination_fee_cents,
    designate,
    disposal_fee_cents,
    get_success_data,
    invoice_lines,
    labor_cents,
    long_carry_surcharge_cents,
    make_client_headers,
    milestone_by_key,
    new_item,
    new_punch_item,
    new_unpack_session,
    parse_instant,
    read_engagement,
    read_invoice,
    read_item,
    read_lot,
    read_milestone,
    read_move_day_plan,
    read_punch_item,
    read_summary,
    read_unpack_session,
    resolve_punch_item,
    set_clock,
    setup_completed_move_day,
    setup_consignment_lot,
    setup_engagement,
    setup_issued_invoice,
    setup_settle_in,
    stairs_surcharge_cents,
    start_unpack_session,
    travel_surcharge_cents,
    validate_paginated,
    validate_success,
    make_vendor_headers,
)

CHECK_OUT_2330 = "2026-06-15T23:30:00.000Z"
DONATE_SPEC = {
    "label": "Old linens",
    "category": "LINENS",
    "footprint_linear_inches": 10,
    "volume_cft": 5,
}
EXPECTED_LABOUR = labor_cents(9.50, 9500) + labor_cents(6.00, 6800)
EXPECTED_SUBTOTAL = (
    EXPECTED_LABOUR
    + travel_surcharge_cents(22)
    + stairs_surcharge_cents(2, 2)
    + long_carry_surcharge_cents(100)
)
EXPECTED_TOTAL = EXPECTED_SUBTOTAL + coordination_fee_cents(EXPECTED_SUBTOTAL)


def test_the_dispute_cycle_returns_the_invoice_to_issued_before_finalisation():
    """PRD §3.11: "The client, a power of attorney or a family member may dispute it,
    supplying a `reason` stored as `dispute_reason` and a `raised_by_party_id` that
    must resolve to a seat on the engagement; the dispute raises `dispute_count` and
    is capped at two, with the recall and dispute caps both reported through
    `ERR_INVOICE_ACTION_LIMIT`. Billing then resolves the dispute with a
    `resolution`, returning the invoice to `ISSUED` and clearing `dispute_reason` to null."
    PRD §3.11: "Finalisation is terminal. It is reachable from `ISSUED`, requires
    `balance_due_cents` to be less than or equal to zero — otherwise
    `ERR_BALANCE_OUTSTANDING` — and requires that no consignment lot of the
    engagement sits in `SOLD` or `SETTLED` with `credited` true and `reversed` false
    pending a return."

    Design: Corner/state_machines/invoice_dispute_cycle_then_finalization
    """
    world = setup_issued_invoice(
        other_items=[dict(DONATE_SPEC)],
        lead_in=MOVE_START,
        packer_in="2026-06-15T17:30:00.000Z",
        lead_out=CHECK_OUT_2330,
        packer_out=None,
        complete_at=CHECK_OUT_2330,
        actual_loaded_volume_cft=2200,
    )
    invoice_id = world["invoice"]["id"]
    disputed = validate_success(
        api_client.dispute_invoice(
            invoice_id,
            {"reason": "Overtime looks wrong", "raised_by_party_id": world["client_party"]["id"]},
            make_client_headers(world["client"]["id"]),
        )
    )
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_count"] == 1
    assert disputed["dispute_reason"] == "Overtime looks wrong"

    resolved = validate_success(
        api_client.resolve_invoice_dispute(
            invoice_id,
            {"resolution": "Overtime confirmed against the signed timesheet"},
            BILLING_ADMIN,
        )
    )
    assert resolved["status"] == "ISSUED"
    assert resolved["dispute_reason"] is None

    validate_success(
        api_client.record_payment(
            invoice_id, {"amount_cents": EXPECTED_TOTAL, "paid_on": "2026-06-18"}, BILLING_ADMIN
        )
    )
    paid = read_invoice(invoice_id)
    assert_money(paid["payments_cents"], EXPECTED_TOTAL, "payments_cents")
    assert_money(paid["balance_due_cents"], 0, "balance_due_cents")

    validate_success(api_client.finalize_invoice(invoice_id, BILLING_ADMIN))
    assert read_invoice(invoice_id)["status"] == "FINALIZED"
    assert read_engagement(world["engagement_id"])["billing_hold"] is False


def test_returning_a_sold_but_uncredited_lot_writes_no_ledger_line_at_all():
    """PRD §3.8: "Returning a lot that was sold but never credited is structurally
    different despite using the same operation: no ledger line is written because
    nothing was credited, and `reversed` stays false."
    PRD §3.8: "Hauling the lot away is the last exit and is reachable from `UNSOLD`
    and from `RETURNED`; from `UNSOLD` it requires the engagement's invoice not to be
    `FINALIZED`, and the returned leg behaves identically in every respect."

    Design: Corner/state_machines/uncredited_sold_lot_returns_without_a_reversal_then_is_hauled
    """
    specs = [
        {
            "label": "Armoire",
            "category": "FURNITURE",
            "footprint_linear_inches": 60,
            "volume_cft": 70,
            "appraised_value_cents": 90000,
            "appraisal_source": "APPRAISED",
        },
        {
            "label": "Sideboard",
            "category": "FURNITURE",
            "footprint_linear_inches": 50,
            "volume_cft": 35,
            "appraised_value_cents": 60000,
            "appraisal_source": "APPRAISED",
        },
    ]
    world = setup_consignment_lot(item_specs=specs, list_price_cents=240000)
    lot_id = world["lot"]["id"]
    get_success_data(api_client.mark_down_lot(lot_id, MOVE_MANAGER))
    get_success_data(
        api_client.record_lot_sale(
            lot_id, {"gross_sale_price_cents": 192000, "sold_on": "2026-05-20"}, MOVE_MANAGER
        )
    )

    validate_success(
        api_client.return_lot_to_client(
            lot_id, {"reason": "Buyer rescinded before settlement"}, MOVE_MANAGER
        )
    )
    returned = read_lot(lot_id)
    assert returned["status"] == "RETURNED"
    assert returned["reversed"] is False
    assert returned["credited"] is False
    invoice = read_invoice(world["invoice"]["id"])
    assert_money(invoice["credits_cents"], 0, "credits_cents")
    assert_no_line_of_type(invoice_lines(world["invoice"]["id"]), "CONSIGNMENT_REVERSAL")

    validate_success(api_client.haul_away_lot(lot_id, MOVE_MANAGER))
    hauled = read_lot(lot_id)
    assert hauled["status"] == "HAULED"
    expected_fee = disposal_fee_cents(105)
    assert_money(hauled["disposal_fee_cents"], expected_fee, "disposal_fee_cents")
    assert_exactly_one_line(invoice_lines(world["invoice"]["id"]), "DISPOSAL_FEE", expected_fee)

    member = read_item(world["items"][0]["id"])
    assert member["handling_state"] == "REMOVED"
    assert member["disposition"] == "HAUL_AWAY"


def test_an_unsold_lot_returned_to_the_client_frees_its_member_items():
    """PRD §3.8: "Returning a lot that was declared unsold clears
    `consignment_lot_id` to null on each member item."
    PRD §3.4: "An item already attached to a lot may not be designated to anything
    other than `SELL`, and the attempt is refused with `ERR_ITEM_ALREADY_CONSIGNED`."

    Design: Corner/state_machines/unsold_lot_returns_to_client_and_frees_its_items
    """
    world = setup_consignment_lot(
        item_specs=[
            {
                "label": "Mantel clock",
                "category": "MISC",
                "footprint_linear_inches": 12,
                "volume_cft": 3,
                "appraised_value_cents": 45000,
                "appraisal_source": "APPRAISED",
            }
        ],
        list_price_cents=90000,
    )
    lot_id = world["lot"]["id"]
    set_clock("2026-06-04T00:00:00.000Z")

    validate_success(
        api_client.declare_lot_unsold(lot_id, make_vendor_headers(world["vendor"]["id"]))
    )
    declared = read_lot(lot_id)
    assert declared["status"] == "UNSOLD"
    assert declared["markdown_round"] == 0

    validate_success(
        api_client.return_lot_to_client(lot_id, {"reason": "Client wants it back"}, MOVE_MANAGER)
    )
    assert read_lot(lot_id)["status"] == "RETURNED"
    freed = read_item(world["items"][0]["id"])
    assert freed["consignment_lot_id"] is None

    validate_success(
        api_client.designate_item(
            world["items"][0]["id"], {"disposition": "HAUL_AWAY"}, MOVE_MANAGER
        )
    )
    redesignated = read_item(world["items"][0]["id"])
    assert redesignated["disposition"] == "HAUL_AWAY"
    assert redesignated["redesignation_count"] == 1
    assert_two_dp(
        read_engagement(world["engagement_id"])["haul_volume_cft"], 3.00, "haul_volume_cft"
    )


def test_the_hourly_ledger_carries_exactly_one_line_equal_to_the_accrued_rollup():
    """PRD §3.11: "Under `HOURLY` exactly one `HOURLY_LABOR` line is appended, and
    its `amount_cents` is the engagement's `accrued_labor_cents` — crew hours times
    role rates, with the minimum call-out floor and the overtime multiplier already
    baked in by §3.7, and with no base line and no included allowance anywhere in the
    picture."
    PRD §3.7: "`crew_min_required` is read from the engagement's `home_tier` and never
    from its `package_tier`: two crew for a `STUDIO`, three for `ONE_BED`, four for
    `TWO_BED` and six for a `HOUSE`."

    Design: Corner/calculations/hourly_pipeline_labor_charge_equals_the_accrued_rollup
    """
    world = setup_completed_move_day(
        other_items=[dict(DONATE_SPEC)],
        lead_in=MOVE_START,
        packer_in="2026-06-15T17:30:00.000Z",
        lead_out=CHECK_OUT_2330,
        packer_out=None,
        complete_at=CHECK_OUT_2330,
        actual_loaded_volume_cft=2200,
    )
    lines, meta = validate_paginated(
        api_client.list_invoice_lines(BILLING_ADMIN, params={"invoice_id": world["invoice"]["id"]})
    )
    assert meta["total_count"] == 1
    assert lines[0]["line_type"] == "HOURLY_LABOR"
    assert_money(lines[0]["amount_cents"], EXPECTED_LABOUR, "HOURLY_LABOR amount_cents")
    assert_money(
        read_engagement(world["engagement_id"])["accrued_labor_cents"],
        EXPECTED_LABOUR,
        "accrued_labor_cents",
    )
    assert read_move_day_plan(world["plan"]["id"])["crew_min_required"] == 2

    summary = read_summary(world["engagement_id"])
    assert_money(summary["accrued_labor_cents"], EXPECTED_LABOUR, "summary accrued_labor_cents")
    assert_hours(summary["billing_hours_total"], 15.50, "summary billing_hours_total")
    assert summary["progress_pct"] == 80


def test_completing_a_milestone_auto_starts_its_successor_and_a_reopen_re_enters():
    """PRD §3.10: "On the progress axis, a milestone starts `PENDING` and is moved to
    `IN_PROGRESS` by the system — the first one at engagement creation, and each of
    the others when its predecessor completes — which recomputes the engagement's
    `phase` to that milestone's key."
    PRD §3.10: "`REOPENED` never rests: in the same request the milestone returns to
    `IN_PROGRESS`, recomputing `phase` again."

    Design: Corner/endpoints/milestone_auto_start_and_reopen_return_to_in_progress
    """
    world = setup_engagement(with_residence=True)
    eng_id, party_id = world["engagement_id"], world["client_party"]["id"]
    keeper = new_item(eng_id, label="Walnut sideboard", footprint_linear_inches=96, volume_cft=40)
    designate(keeper["id"], "KEEP", world["room"]["id"])
    donor = new_item(eng_id, **DONATE_SPEC)
    designate(donor["id"], "DONATE")

    assessment_id = milestone_by_key(eng_id, "ASSESSMENT")["id"]
    validate_success(
        api_client.complete_milestone(
            assessment_id, {"completed_by_party_id": party_id}, MOVE_MANAGER
        )
    )
    assert milestone_by_key(eng_id, "SORT_PLAN")["status"] == "IN_PROGRESS"
    assert milestone_by_key(eng_id, "PACK")["status"] == "PENDING"
    assert read_engagement(eng_id)["phase"] == "SORT_PLAN"

    validate_success(
        api_client.reopen_milestone(
            assessment_id, {"reason": "Walkthrough missed the basement"}, MOVE_MANAGER
        )
    )
    reopened = read_milestone(assessment_id)
    assert reopened["status"] == "IN_PROGRESS"
    assert reopened["reopen_count"] == 1
    assert reopened["completed_at_utc"] is None
    assert reopened["overdue_status"] == "ON_TIME"
    assert read_engagement(eng_id)["phase"] == "ASSESSMENT"


def test_a_reopened_punch_item_can_be_resolved_again_and_its_session_restarted():
    """PRD §3.9: "Resolving it moves it to `RESOLVED` and is reachable from `OPEN`
    and from `REOPENED`; it is open to the move manager and the crew lead, requires a
    non-empty `resolution_note`, and — on the leg out of `OPEN` — recomputes
    `breached_sla`."
    PRD §3.9: "A session moves from `COMPLETED` back to `REOPENED` only as a cascade
    from a punch-list reopen that names it, and that cascade is capped at two reopens."

    Design: Corner/endpoints/punch_list_resolve_reopen_resolve_cycle_closes_out
    """
    world = setup_settle_in(settle_in_clock="2026-06-20T10:00:00.000Z")
    eng_id = world["engagement_id"]
    session = new_unpack_session(eng_id, "2026-06-20T10:00:00.000Z", "ESSENTIALS")
    start_unpack_session(session["id"])
    complete_unpack_session(session["id"])
    punch = new_punch_item(
        eng_id, "Dresser drawer sticks", "MINOR", unpack_session_id=session["id"]
    )
    resolve_punch_item(punch["id"], "Planed the runner")

    expected_due = parse_instant(punch["created_at"]) + timedelta(hours=PUNCH_SLA_HOURS["MINOR"])
    assert_same_instant(
        punch["due_at_utc"], expected_due.isoformat().replace("+00:00", "Z"), "due_at_utc"
    )

    validate_success(
        api_client.reopen_punch_list_item(
            punch["id"],
            {"reason": "Still sticking"},
            make_client_headers(world["client"]["id"]),
        )
    )
    assert read_punch_item(punch["id"])["status"] == "REOPENED"
    assert read_unpack_session(session["id"])["status"] == "REOPENED"

    validate_success(api_client.start_unpack_session(session["id"], MOVE_MANAGER))
    assert read_unpack_session(session["id"])["status"] == "IN_PROGRESS"

    validate_success(
        api_client.resolve_punch_list_item(
            punch["id"], {"resolution_note": "Replaced the runner"}, MOVE_MANAGER
        )
    )
    validate_success(api_client.complete_unpack_session(session["id"], MOVE_MANAGER))

    final_punch = read_punch_item(punch["id"])
    assert final_punch["status"] == "RESOLVED"
    assert final_punch["reopen_count"] == 1
    assert final_punch["breached_sla"] is False
    final_session = read_unpack_session(session["id"])
    assert final_session["status"] == "COMPLETED"
    assert final_session["reopen_count"] == 1
