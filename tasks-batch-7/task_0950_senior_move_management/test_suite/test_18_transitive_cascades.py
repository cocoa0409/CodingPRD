"""Multi-hop cascades: move-day completion, sort-plan approval and the
non-monotone consignment reversal that runs backwards along the timeline."""

from test_helpers import (
    BILLING_ADMIN,
    HAUL_AUTO_ORDER_QUOTE_CENTS,
    MOVE_MANAGER,
    MOVE_START,
    PACKER_CHECK_IN,
    api_client,
    assert_exactly_one_line,
    assert_hours,
    assert_money,
    assert_two_dp,
    coordination_fee_cents,
    designate,
    drive_sort_plan_to_approved,
    get_success_data,
    invoice_lines,
    invoice_of,
    labor_cents,
    lines_of_type,
    long_carry_surcharge_cents,
    milestone_by_key,
    net_proceeds_cents,
    new_consignment_lot,
    new_item,
    new_sort_plan,
    new_vendor,
    complete_milestone,
    read_engagement,
    read_invoice,
    read_item,
    read_lot,
    read_milestone,
    read_move_day_plan,
    read_sort_plan,
    read_summary,
    setup_completed_move_day,
    setup_engagement,
    stairs_surcharge_cents,
    submit_sort_plan,
    travel_surcharge_cents,
    trip_count,
    validate_success,
)

CHECK_OUT_2330 = "2026-06-15T23:30:00.000Z"
ADDENDUM_ROOM = {"approved_addendum_linear_inches": 36}


def _completed_move_day_with_a_late_packer():
    """The LEAD checks out at 23:30; the PACKER is still CHECKED_IN at completion."""
    return setup_completed_move_day(
        room_kwargs=ADDENDUM_ROOM,
        lead_in=MOVE_START,
        packer_in=PACKER_CHECK_IN,
        lead_out=CHECK_OUT_2330,
        packer_out=None,
        complete_at=CHECK_OUT_2330,
        actual_loaded_volume_cft=2200,
    )


def test_move_day_completion_closes_the_checked_in_assignment_and_rolls_up_labour():
    """PRD §3.7: "First, every assignment still `CHECKED_IN` transitions to
    `COMPLETED`, its `checked_out_at_utc` set to the current logical clock and a
    `LABOR` time entry created spanning its `checked_in_at_utc` to that instant.
    Second, each such completion recomputes that assignment's `portal_hours`,
    `billing_hours`, `applied_hours`, `overtime_hours` and `labor_cents` from its
    non-voided entries. Third, the engagement's `accrued_labor_cents` and
    `billing_hours_total` are recomputed from those assignments."

    Design: Difficulty/transitive_cascade/move_day_complete_depth_six_cascade
    """
    world = _completed_move_day_with_a_late_packer()
    plan = read_move_day_plan(world["plan"]["id"])
    assert plan["status"] == "COMPLETED"

    packer = get_success_data(
        api_client.get_crew_assignment(world["packer_assignment"]["id"], MOVE_MANAGER)
    )
    assert packer["status"] == "COMPLETED"
    assert_hours(packer["billing_hours"], 6.00, "packer billing_hours")
    assert_money(packer["labor_cents"], labor_cents(6.00, 6800), "packer labor_cents")

    engagement = read_engagement(world["engagement_id"])
    expected_labour = labor_cents(9.50, 9500) + labor_cents(6.00, 6800)
    assert_money(engagement["accrued_labor_cents"], expected_labour, "accrued_labor_cents")
    assert_hours(engagement["billing_hours_total"], 15.50, "billing_hours_total")


def test_move_day_completion_appends_the_labour_line_and_advances_the_timeline():
    """PRD §3.7: "Fourth, the engagement's `DRAFT` invoice receives the pipeline
    labour line: an `HOURLY_LABOR` line under the hourly pipeline, or an
    `OVERAGE_LABOR` line under the package pipeline when `billing_hours_total`
    exceeds the tier allowance. Fifth, the invoice's `subtotal_cents`,
    `coordination_fee_cents`, `total_cents` and `balance_due_cents` are recomputed
    and the invoice's `version` rises by one. Sixth, the `MOVE_DAY` milestone moves
    from `IN_PROGRESS` to `COMPLETE`, which starts the `SETTLE_IN` milestone and
    therefore moves the engagement's `phase` to `SETTLE_IN`."
    PRD §3.7: "The actual variant, stored in `actual_trip_count`, is computed at
    completion and uses `actual_loaded_volume_cft`, which includes packing-material
    displacement and therefore usually exceeds the keep volume."

    Design: Difficulty/transitive_cascade/move_day_complete_depth_six_cascade
    """
    world = _completed_move_day_with_a_late_packer()
    expected_labour = labor_cents(9.50, 9500) + labor_cents(6.00, 6800)

    lines = invoice_lines(world["invoice"]["id"])
    assert_exactly_one_line(lines, "HOURLY_LABOR", expected_labour)
    assert_money(
        read_invoice(world["invoice"]["id"])["subtotal_cents"],
        expected_labour,
        "subtotal_cents",
    )

    assert milestone_by_key(world["engagement_id"], "MOVE_DAY")["status"] == "COMPLETE"
    assert read_engagement(world["engagement_id"])["phase"] == "SETTLE_IN"
    assert read_move_day_plan(world["plan"]["id"])["actual_trip_count"] == trip_count(
        2200, 1000, 1
    )


def _submitted_sort_plan_with_haul_items(second_haul_volume):
    """One 40 cft KEEP item, two HAUL_AWAY items and a registered junk hauler."""
    world = setup_engagement(with_residence=True, room_kwargs=ADDENDUM_ROOM)
    eng_id = world["engagement_id"]
    world["junk_hauler"] = new_vendor(
        "Northside Junk Haul", "JUNK_HAUL", "2027-01-31", daily_capacity=3, holdback_pct=0.1
    )
    keeper = new_item(eng_id, label="Walnut sideboard", footprint_linear_inches=96, volume_cft=40)
    haul_one = new_item(eng_id, label="Garage shelving", category="MISC", footprint_linear_inches=60, volume_cft=150)
    haul_two = new_item(
        eng_id,
        label="Basement cartons",
        category="MISC",
        footprint_linear_inches=50,
        volume_cft=second_haul_volume,
    )
    designate(keeper["id"], "KEEP", world["room"]["id"])
    designate(haul_one["id"], "HAUL_AWAY")
    designate(haul_two["id"], "HAUL_AWAY")

    assessment = milestone_by_key(eng_id, "ASSESSMENT")
    complete_milestone(assessment["id"], world["client_party"]["id"])
    plan = new_sort_plan(eng_id)
    submit_sort_plan(plan["id"])
    world.update({"sort_plan": plan, "keeper": keeper, "haul_one": haul_one, "haul_two": haul_two})
    return world


def test_sort_plan_approval_locks_dispositions_and_recomputes_the_haul_volume():
    """PRD §3.6: "First, every item of the engagement whose disposition is not
    `UNDECIDED` has `disposition_locked` set to true, and the plan's
    `locked_item_count` is refreshed to the number of the engagement's items now
    locked. Second, for every newly locked item whose disposition is `HAUL_AWAY`,
    the engagement's `haul_volume_cft` is recomputed."

    Design: Difficulty/transitive_cascade/sort_plan_approve_depth_four_cascade
    """
    world = _submitted_sort_plan_with_haul_items(120)
    validate_success(
        api_client.approve_sort_plan(
            world["sort_plan"]["id"],
            {"approved_by_party_id": world["client_party"]["id"]},
            MOVE_MANAGER,
        )
    )
    plan = read_sort_plan(world["sort_plan"]["id"])
    assert plan["status"] == "APPROVED"
    assert plan["locked_item_count"] == 3
    assert read_item(world["haul_one"]["id"])["disposition_locked"] is True

    engagement = read_engagement(world["engagement_id"])
    assert_two_dp(engagement["haul_volume_cft"], 270.00, "haul_volume_cft")
    assert_two_dp(engagement["keep_volume_cft"], 40.00, "keep_volume_cft")


def test_sort_plan_approval_raises_the_junk_haul_order_and_completes_the_milestone():
    """PRD §3.6: "Third, when that recomputed haul volume reaches 250 cubic feet and
    no haul-away vendor assignment already exists for the engagement, one is
    auto-created in status `REQUESTED` against the first vendor whose `vendor_type`
    is `JUNK_HAUL` ordered by `created_at` ascending, with `service_kind` of
    `HAUL_AWAY`, a `quoted_cents` of 45000 and a `service_date` equal to the UTC
    calendar date of the engagement's `scheduled_move_start_utc`; where no junk-haul
    vendor exists at all, no assignment is created and the approval still succeeds.
    Fourth, the `SORT_PLAN` milestone moves from `IN_PROGRESS` to `COMPLETE`, which
    starts the `PACK` milestone and therefore moves the engagement's `phase` to `PACK`."

    Design: Difficulty/transitive_cascade/sort_plan_approve_depth_four_cascade
    """
    world = _submitted_sort_plan_with_haul_items(120)
    validate_success(
        api_client.approve_sort_plan(
            world["sort_plan"]["id"],
            {"approved_by_party_id": world["client_party"]["id"]},
            MOVE_MANAGER,
        )
    )
    body = api_client.list_vendor_assignments(
        MOVE_MANAGER, params={"engagement_id": world["engagement_id"]}
    ).json()
    rows = body["data"]
    assert body["meta"]["total_count"] == 1, "exactly one junk-haul order is auto-created"
    order = rows[0]
    assert order["vendor_id"] == world["junk_hauler"]["id"]
    assert order["service_kind"] == "HAUL_AWAY"
    assert order["status"] == "REQUESTED"
    assert_money(order["quoted_cents"], HAUL_AUTO_ORDER_QUOTE_CENTS, "quoted_cents")
    assert order["service_date"] == "2026-06-15"

    assert milestone_by_key(world["engagement_id"], "SORT_PLAN")["status"] == "COMPLETE"
    assert read_engagement(world["engagement_id"])["phase"] == "PACK"


def test_one_cubic_foot_short_of_the_minimum_load_raises_no_junk_haul_order():
    """PRD §3.6: "Third, when that recomputed haul volume reaches 250 cubic feet and
    no haul-away vendor assignment already exists for the engagement, one is
    auto-created in status `REQUESTED` against the first vendor whose `vendor_type`
    is `JUNK_HAUL` ordered by `created_at` ascending, with `service_kind` of
    `HAUL_AWAY`, a `quoted_cents` of 45000 and a `service_date` equal to the UTC
    calendar date of the engagement's `scheduled_move_start_utc`; where no junk-haul
    vendor exists at all, no assignment is created and the approval still succeeds."

    Design: Difficulty/transitive_cascade/haul_auto_order_leg_does_not_fire_below_the_minimum_load
    """
    world = _submitted_sort_plan_with_haul_items(99)
    validate_success(
        api_client.approve_sort_plan(
            world["sort_plan"]["id"],
            {"approved_by_party_id": world["client_party"]["id"]},
            MOVE_MANAGER,
        )
    )
    engagement = read_engagement(world["engagement_id"])
    assert_two_dp(engagement["haul_volume_cft"], 249.00, "haul_volume_cft")

    body = api_client.list_vendor_assignments(
        MOVE_MANAGER, params={"engagement_id": world["engagement_id"]}
    ).json()
    assert body["meta"]["total_count"] == 0, (
        "249.00 cubic feet is below the 250 cubic foot minimum load, so no order fires"
    )


def test_the_other_three_approval_hops_still_fire_below_the_minimum_load():
    """PRD §3.6: "First, every item of the engagement whose disposition is not
    `UNDECIDED` has `disposition_locked` set to true, and the plan's
    `locked_item_count` is refreshed to the number of the engagement's items now locked."
    PRD §2.11: "An engagement's `total_inventory_volume_cft` always equals the sum of
    `volume_cft` over every one of its items regardless of disposition, and no
    designation ever changes it."

    Design: Difficulty/transitive_cascade/haul_auto_order_leg_does_not_fire_below_the_minimum_load
    """
    world = _submitted_sort_plan_with_haul_items(99)
    validate_success(
        api_client.approve_sort_plan(
            world["sort_plan"]["id"],
            {"approved_by_party_id": world["client_party"]["id"]},
            MOVE_MANAGER,
        )
    )
    plan = read_sort_plan(world["sort_plan"]["id"])
    assert plan["status"] == "APPROVED"
    assert plan["locked_item_count"] == 3
    assert read_item(world["haul_one"]["id"])["disposition_locked"] is True

    engagement = read_engagement(world["engagement_id"])
    assert_two_dp(engagement["keep_volume_cft"], 40.00, "keep_volume_cft")
    assert_two_dp(
        engagement["total_inventory_volume_cft"], 289.00, "total_inventory_volume_cft"
    )
    assert milestone_by_key(world["engagement_id"], "SORT_PLAN")["status"] == "COMPLETE"
    assert engagement["phase"] == "PACK"


SELL_SPECS = [
    {
        "label": "Silver tea service",
        "category": "MISC",
        "footprint_linear_inches": 24,
        "volume_cft": 6,
        "appraised_value_cents": 90000,
        "appraisal_source": "APPRAISED",
    },
    {
        "label": "Oil landscape",
        "category": "ARTWORK",
        "footprint_linear_inches": 40,
        "volume_cft": 8,
        "appraised_value_cents": 120000,
        "appraisal_source": "APPRAISED",
    },
    {
        "label": "Mantel clock",
        "category": "MISC",
        "footprint_linear_inches": 12,
        "volume_cft": 3,
        "appraised_value_cents": 45000,
        "appraisal_source": "APPRAISED",
    },
]

EXPECTED_LABOUR = labor_cents(9.50, 9500) + labor_cents(6.00, 6800)
EXPECTED_SUBTOTAL = (
    EXPECTED_LABOUR
    + travel_surcharge_cents(22)
    + stairs_surcharge_cents(2, 2)
    + long_carry_surcharge_cents(100)
)
EXPECTED_FEE = coordination_fee_cents(EXPECTED_SUBTOTAL)
EXPECTED_NET = net_proceeds_cents(250000, 3)


def _settled_lot_on_a_fully_closed_timeline():
    world = setup_completed_move_day(
        other_items=[dict(spec, disposition="SELL") for spec in SELL_SPECS],
        lead_in=MOVE_START,
        packer_in=PACKER_CHECK_IN,
        lead_out=CHECK_OUT_2330,
        packer_out=None,
        complete_at=CHECK_OUT_2330,
        actual_loaded_volume_cft=900,
    )
    eng_id = world["engagement_id"]
    vendor = new_vendor("Hollis Estate Gallery", "CONSIGNMENT", "2027-01-31")
    sell_ids = [item["id"] for item in world["items"] if item["disposition"] == "SELL"]
    lot = new_consignment_lot(eng_id, vendor["id"], 240000, "2026-05-05", sell_ids)
    lot = get_success_data(
        api_client.record_lot_sale(
            lot["id"],
            {"gross_sale_price_cents": 250000, "sold_on": "2026-05-20"},
            MOVE_MANAGER,
        )
    )
    invoice_id = world["invoice"]["id"]
    get_success_data(api_client.issue_invoice(invoice_id, BILLING_ADMIN))
    get_success_data(api_client.settle_lot(lot["id"], BILLING_ADMIN))
    get_success_data(
        api_client.record_payment(
            invoice_id,
            {"amount_cents": EXPECTED_SUBTOTAL + EXPECTED_FEE - EXPECTED_NET, "paid_on": "2026-06-16"},
            BILLING_ADMIN,
        )
    )
    for key in ("SETTLE_IN", "CLOSE_OUT"):
        milestone = milestone_by_key(eng_id, key)
        complete_milestone(milestone["id"], world["client_party"]["id"])
    world["lot"] = lot
    world["sell_ids"] = sell_ids
    world["close_out_milestone_id"] = milestone_by_key(eng_id, "CLOSE_OUT")["id"]
    return world


def test_returning_a_settled_lot_reverses_the_credit_and_restores_the_total():
    """PRD §3.8: "Returning a lot that was settled runs four hops: a
    `CONSIGNMENT_REVERSAL` ledger line whose `amount_cents` is the positive
    `net_proceeds_cents` is appended and `reversed` is set to true; the invoice's
    `credits_cents`, `total_cents` and `balance_due_cents` are recomputed and its
    `version` rises by one; the engagement's `billing_hold` is recomputed, becoming
    true when the recomputed `balance_due_cents` is greater than zero while the
    invoice is `ISSUED` or `DISPUTED`; and because a live `billing_hold` blocks
    close-out, a `CLOSE_OUT` milestone that was already `COMPLETE` moves to `REOPENED`."

    Design: Difficulty/transitive_cascade/consignment_reversal_reopens_the_close_out_milestone_through_billing_hold
    """
    world = _settled_lot_on_a_fully_closed_timeline()
    invoice_id = world["invoice"]["id"]
    before = read_invoice(invoice_id)
    assert before["status"] == "ISSUED"
    assert_money(before["credits_cents"], -EXPECTED_NET, "credits_cents before the return")
    assert_money(before["balance_due_cents"], 0, "balance_due_cents before the return")
    assert read_engagement(world["engagement_id"])["phase"] == "DONE"

    validate_success(
        api_client.return_lot_to_client(
            world["lot"]["id"],
            {"reason": "Buyer rescinded, the gallery returned the lot"},
            MOVE_MANAGER,
        )
    )
    lines = invoice_lines(invoice_id)
    assert_exactly_one_line(lines, "CONSIGNMENT_REVERSAL", EXPECTED_NET)
    assert read_lot(world["lot"]["id"])["reversed"] is True

    after = read_invoice(invoice_id)
    assert_money(after["credits_cents"], 0, "credits_cents after the reversal")
    assert_money(after["total_cents"], EXPECTED_SUBTOTAL + EXPECTED_FEE, "total_cents")
    assert_money(after["balance_due_cents"], EXPECTED_NET, "balance_due_cents")
    assert after["version"] == before["version"] + 1


def test_the_reversal_flips_billing_hold_and_reopens_the_close_out_milestone():
    """PRD §3.1: "and `billing_hold` is true exactly when the invoice's
    `balance_due_cents` is greater than zero while the invoice is `ISSUED` or `DISPUTED`."
    PRD §3.10: "`progress_pct` is a weighted score over milestones whose status is
    exactly `COMPLETE` — 10 for assessment, 25 for the sort plan, 15 for packing, 30
    for move day, 15 for settle-in and 5 for close-out, six weights summing to
    exactly 100 — with `REOPENED` and `IN_PROGRESS` milestones contributing nothing."

    Design: Difficulty/transitive_cascade/consignment_reversal_reopens_the_close_out_milestone_through_billing_hold
    """
    world = _settled_lot_on_a_fully_closed_timeline()
    assert read_engagement(world["engagement_id"])["billing_hold"] is False

    validate_success(
        api_client.return_lot_to_client(
            world["lot"]["id"],
            {"reason": "Buyer rescinded, the gallery returned the lot"},
            MOVE_MANAGER,
        )
    )
    engagement = read_engagement(world["engagement_id"])
    assert engagement["billing_hold"] is True
    assert engagement["phase"] == "CLOSE_OUT"

    close_out = read_milestone(world["close_out_milestone_id"])
    assert close_out["status"] == "IN_PROGRESS"
    assert close_out["reopen_count"] == 1
    assert close_out["completed_at_utc"] is None

    summary = read_summary(world["engagement_id"])
    assert summary["progress_pct"] == 95

    lot = read_lot(world["lot"]["id"])
    assert lot["status"] == "RETURNED"
    assert lot["credited"] is True
    assert read_item(world["sell_ids"][0])["disposition"] == "SELL"

    invoice = read_invoice(world["invoice"]["id"])
    assert_money(invoice["subtotal_cents"], EXPECTED_SUBTOTAL, "subtotal_cents")
    assert_money(invoice["coordination_fee_cents"], EXPECTED_FEE, "coordination_fee_cents")
