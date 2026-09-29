"""Case-line execution: the overage cap on a fill, the dating of a first fill,
the markdown floor, the pounds a line has left to give, and the repricing
cascade that an approved bench test drives into published case-plan lines."""

import pytest

from test_helpers import (
    ANALYST,
    CUTTER,
    FIXTURE_DATE,
    MANAGER,
    add_case_plan_line,
    add_cutting_test_line,
    approve_cutting_test,
    assert_fill_status_follows_totals,
    assert_line_pounds_available,
    assert_version_incremented,
    create_case_plan,
    create_cutting_test,
    create_primal_purchase,
    create_retail_item,
    department_with_catalogue,
    fill_line,
    fill_payload,
    filled_plan_line,
    get_success_data,
    mark_down_line,
    markdown_payload,
    propose_price,
    publish_case_plan,
    published_plan,
    read_case_plan,
    read_case_plan_line,
    read_cutting_test,
    read_cutting_test_line,
    read_primal_purchase,
    read_retail_item,
    received_primal,
    set_clock,
    shrink_event_payload,
    submit_cutting_test,
    validate_error,
    write_off_line,
)


def test_a_cumulative_fill_may_land_exactly_on_the_quarter_overage_cap(api):
    """A ground line asking for 24.00 lb still takes pounds up to exactly 30.00 lb, the quarter more the case is allowed to carry.

    "The owning plan must be `PUBLISHED`, or the fill is refused with
    `ERR_CASE_PLAN_NOT_PUBLISHED`; the department must not be `SALES_HALTED`; and
    the running `actual_fill_lb` plus the new pounds must not exceed
    `required_fill_lb` multiplied by one and twenty-five hundredths, the overage
    cap that allows a quarter more than the model asked for and no more —
    exceeding it is refused with `ERR_FILL_EXCEEDS_REQUIRED`."

    Design: Difficulty/boundary_precision_check/fill_overage_cap_boundary_on_case_plan_line
    """
    ctx = received_primal(api)
    ground = propose_price(api, ctx["ground_item"]["id"], ctx["purchase"]["id"])
    assert ground["shelf_life_days"] == 2

    plan = create_case_plan(api, ctx["department"]["id"], FIXTURE_DATE)
    # 5 facings of ground beef is 20.00 presentation pounds, the forecast uplift
    # asks for 46.00 and two days of shelf life can only carry 24.00, so the
    # line settles on 24.00 lb and the cap sits at exactly 30.00 lb (PRD §3.6).
    line = add_case_plan_line(api, plan["id"], ground["id"], 1, 5, 40.0)
    assert line["required_fill_lb"] == pytest.approx(24.00, abs=0.01)
    publish_case_plan(api, plan["id"])

    fill_line(api, line["id"], 24.0)
    after_first = read_case_plan_line(api, line["id"])
    assert after_first["actual_fill_lb"] == pytest.approx(24.00, abs=0.01)
    assert after_first["line_status"] == "FILLED"

    fill_line(api, line["id"], 6.0)
    at_the_cap = read_case_plan_line(api, line["id"])
    assert at_the_cap["actual_fill_lb"] == pytest.approx(30.00, abs=0.01)
    assert at_the_cap["line_status"] == "FILLED"
    assert_line_pounds_available(at_the_cap)

    plan_after = read_case_plan(api, plan["id"])
    assert plan_after["total_required_fill_lb"] == pytest.approx(24.00, abs=0.01)
    assert plan_after["total_actual_fill_lb"] == pytest.approx(30.00, abs=0.01)
    assert plan_after["fill_status"] == "FILLED"
    assert_fill_status_follows_totals(plan_after)


def test_a_fill_one_cent_past_the_overage_cap_is_refused_and_changes_nothing(api):
    """A whole-muscle line asking for 34.50 lb caps at 43.125 lb, so 43.12 lb goes in and the next hundredth of a pound is turned away.

    "The fill does not push `actual_fill_lb` above the overage cap on
    `required_fill_lb` — otherwise `ERR_FILL_EXCEEDS_REQUIRED` (422)."

    Design: Difficulty/boundary_precision_check/fill_overage_cap_boundary_on_case_plan_line
    """
    ctx = published_plan(api)
    line = ctx["line"]
    assert line["required_fill_lb"] == pytest.approx(34.50, abs=0.01)

    # 34.50 x 1.25 is 43.125, so 43.12 lb still fits underneath the ceiling.
    fill_line(api, line["id"], 43.12)
    before = read_case_plan_line(api, line["id"])
    assert before["actual_fill_lb"] == pytest.approx(43.12, abs=0.01)
    assert before["line_status"] == "FILLED"

    # One more hundredth would make 43.13 lb, which is over 43.125.
    refused = api.create_fill(line["id"], fill_payload(0.01), CUTTER)
    validate_error(refused, "ERR_FILL_EXCEEDS_REQUIRED", 422)

    after = read_case_plan_line(api, line["id"])
    assert after["actual_fill_lb"] == pytest.approx(43.12, abs=0.01)
    assert after["line_status"] == "FILLED"
    assert after["version"] == before["version"]

    plan_after = read_case_plan(api, ctx["plan"]["id"])
    assert plan_after["total_actual_fill_lb"] == pytest.approx(43.12, abs=0.01)
    assert plan_after["fill_status"] == "FILLED"


def test_approving_a_second_bench_test_reprices_the_item_and_stales_the_case_line(api):
    """A re-cut that moves the measured cost basis to 1332.9828 lifts the shelf tag to 2089 against a charged 1999, a 4.5% move that flags the published line.

    "The fourth hop reaches every case-plan line of a `PUBLISHED` case plan that
    references an item just moved to `REPRICE_REQUIRED`, sets that line's
    `price_stale` flag to `true`, and increments the owning plan's
    `price_stale_line_count`."

    Design: Difficulty/transitive_cascade/cutting_test_approve_cascade_reaches_stale_case_plan_lines
    """
    ctx = published_plan(api)
    item_before = read_retail_item(api, ctx["whole_muscle_item"]["id"])
    assert item_before["price_status"] == "PRICED"
    assert item_before["active_price_per_lb_cents"] == 1999
    assert item_before["final_price_per_lb_cents"] == 1999
    assert item_before["yield_adjusted_cost_per_lb_cents"] == pytest.approx(
        1276.7419, abs=0.0001
    )

    purchase_before = read_primal_purchase(api, ctx["purchase"]["id"])
    assert purchase_before["status"] == "CUT_TESTED"
    assert purchase_before["allocated_cost_cents"] == 86000
    assert purchase_before["unallocated_cost_cents"] == 0

    line_before = read_case_plan_line(api, ctx["line"]["id"])
    assert line_before["price_stale"] is False
    plan_before = read_case_plan(api, ctx["plan"]["id"])
    assert plan_before["price_stale_line_count"] == 0

    # The primal goes back on the bench: a fresh test supersedes the first one,
    # rewinds the cost ledger and is then submitted and approved in its place.
    second = create_cutting_test(
        api, purchase_before["id"], 98.5, purchase_before["version"]
    )
    new_salable = add_cutting_test_line(
        api,
        second["id"],
        1,
        "RIBEYE_STEAK",
        "SALABLE_CUT",
        58.0,
        1450,
        retail_item_id=item_before["id"],
    )
    new_trim = add_cutting_test_line(
        api, second["id"], 2, "GRIND_TRIM_81", "GRIND_TRIM", 22.5, 420, lean_pct=78.0
    )
    new_loss = add_cutting_test_line(
        api, second["id"], 3, "FAT_AND_BONE", "FAT_BONE_LOSS", 18.0, 0
    )

    superseded = read_cutting_test(api, ctx["cutting_test"]["id"])
    assert superseded["status"] == "SUPERSEDED"
    rewound = read_cutting_test_line(api, ctx["lines"][0]["id"])
    assert rewound["allocated_cost_cents"] == 0
    assert rewound["allocated_cost_per_lb_cents"] == pytest.approx(0.0, abs=0.0001)

    submit_cutting_test(api, second["id"])
    approved = approve_cutting_test(api, second["id"])
    assert approved["status"] == "APPROVED"
    assert approved["salable_yield_pct"] == pytest.approx(0.5888, abs=0.0001)
    assert approved["trim_yield_pct"] == pytest.approx(0.2284, abs=0.0001)
    assert approved["loss_pct"] == pytest.approx(0.1827, abs=0.0001)

    # Allocation: the value base is 58.0 x 1450 + 22.5 x 420 = 93550 cents-pounds.
    allocated_salable = read_cutting_test_line(api, new_salable["id"])
    assert allocated_salable["allocated_cost_cents"] == 77313
    assert allocated_salable["allocated_cost_per_lb_cents"] == pytest.approx(
        1332.9828, abs=0.0001
    )
    allocated_trim = read_cutting_test_line(api, new_trim["id"])
    assert allocated_trim["allocated_cost_cents"] == 8687
    assert allocated_trim["allocated_cost_per_lb_cents"] == pytest.approx(
        386.0889, abs=0.0001
    )
    allocated_loss = read_cutting_test_line(api, new_loss["id"])
    assert allocated_loss["allocated_cost_cents"] == 0
    assert allocated_loss["allocated_cost_per_lb_cents"] == pytest.approx(
        0.0, abs=0.0001
    )

    # The purchase ledger closes again on the new allocation.
    purchase_after = read_primal_purchase(api, purchase_before["id"])
    assert purchase_after["allocated_cost_cents"] == 86000
    assert purchase_after["unallocated_cost_cents"] == 0
    assert purchase_after["status"] == "CUT_TESTED"
    assert_version_incremented(
        purchase_after["version"], purchase_before["version"], 2
    )

    # The item takes the measured basis, recomputes the tag and flags the shelf.
    item_after = read_retail_item(api, item_before["id"])
    assert item_after["yield_adjusted_cost_per_lb_cents"] == pytest.approx(
        1332.9828, abs=0.0001
    )
    assert item_after["final_price_per_lb_cents"] == 2089
    assert item_after["active_price_per_lb_cents"] == 1999
    assert item_after["price_status"] == "REPRICE_REQUIRED"
    assert_version_incremented(item_after["version"], item_before["version"])

    line_after = read_case_plan_line(api, line_before["id"])
    assert line_after["price_stale"] is True
    assert_version_incremented(line_after["version"], line_before["version"])

    plan_after = read_case_plan(api, plan_before["id"])
    assert plan_after["price_stale_line_count"] == 1
    assert_version_incremented(plan_after["version"], plan_before["version"])


def test_a_reprice_inside_two_percent_leaves_the_shelf_tag_and_the_case_line_alone(api):
    """A re-cut that moves the measured cost basis to 1295.7167 lifts the recomputed tag only to 2029 against a charged 1999, a 1.5% move that leaves the item PRICED.

    "The third hop looks at each such item whose `price_status` is `PRICED` and
    recomputes its `final_price_per_lb_cents` under the final-price rules of
    §3.4; when the recomputed price differs from the currently charged
    `active_price_per_lb_cents` by more than two percent of that charged price,
    the item moves `PRICED → REPRICE_REQUIRED`, keeping the stale price live at
    the scale while flagging that the shelf tag is wrong."

    Design: Difficulty/transitive_cascade/cutting_test_approve_cascade_reaches_stale_case_plan_lines
    """
    ctx = published_plan(api)
    item_before = read_retail_item(api, ctx["whole_muscle_item"]["id"])
    assert item_before["price_status"] == "PRICED"
    assert item_before["active_price_per_lb_cents"] == 1999
    assert item_before["yield_adjusted_cost_per_lb_cents"] == pytest.approx(
        1276.7419, abs=0.0001
    )

    purchase_before = read_primal_purchase(api, ctx["purchase"]["id"])
    line_before = read_case_plan_line(api, ctx["line"]["id"])
    plan_before = read_case_plan(api, ctx["plan"]["id"])
    assert line_before["price_stale"] is False
    assert plan_before["price_stale_line_count"] == 0

    # A second break of the same primal, barely different at the bench: the
    # value base becomes 60.0 x 1450 + 22.0 x 420 = 96240 cents-pounds.
    second = create_cutting_test(
        api, purchase_before["id"], 98.5, purchase_before["version"]
    )
    new_salable = add_cutting_test_line(
        api,
        second["id"],
        1,
        "RIBEYE_STEAK",
        "SALABLE_CUT",
        60.0,
        1450,
        retail_item_id=item_before["id"],
    )
    new_trim = add_cutting_test_line(
        api, second["id"], 2, "GRIND_TRIM_81", "GRIND_TRIM", 22.0, 420, lean_pct=78.0
    )
    add_cutting_test_line(
        api, second["id"], 3, "FAT_AND_BONE", "FAT_BONE_LOSS", 16.5, 0
    )
    submit_cutting_test(api, second["id"])
    approved = approve_cutting_test(api, second["id"])
    assert approved["total_yield_weight_lb"] == pytest.approx(98.50, abs=0.01)
    assert approved["unaccounted_lb"] == pytest.approx(0.00, abs=0.01)
    assert approved["salable_yield_pct"] == pytest.approx(0.6091, abs=0.0001)
    assert approved["trim_yield_pct"] == pytest.approx(0.2234, abs=0.0001)
    assert approved["loss_pct"] == pytest.approx(0.1675, abs=0.0001)

    allocated_salable = read_cutting_test_line(api, new_salable["id"])
    assert allocated_salable["allocated_cost_cents"] == 77743
    assert allocated_salable["allocated_cost_per_lb_cents"] == pytest.approx(
        1295.7167, abs=0.0001
    )
    allocated_trim = read_cutting_test_line(api, new_trim["id"])
    assert allocated_trim["allocated_cost_cents"] == 8257
    assert allocated_trim["allocated_cost_per_lb_cents"] == pytest.approx(
        375.3182, abs=0.0001
    )

    purchase_after = read_primal_purchase(api, purchase_before["id"])
    assert purchase_after["allocated_cost_cents"] == 86000
    assert purchase_after["unallocated_cost_cents"] == 0
    assert purchase_after["status"] == "CUT_TESTED"

    # 2029 against the charged 1999 is a 1.5% move, inside the two percent that
    # would otherwise condemn the shelf tag, so the item stays PRICED.
    item_after = read_retail_item(api, item_before["id"])
    assert item_after["yield_adjusted_cost_per_lb_cents"] == pytest.approx(
        1295.7167, abs=0.0001
    )
    assert item_after["final_price_per_lb_cents"] == 2029
    assert item_after["active_price_per_lb_cents"] == 1999
    assert item_after["price_status"] == "PRICED"
    assert_version_incremented(item_after["version"], item_before["version"])

    # The fourth hop never runs: the published line and its plan are untouched.
    line_after = read_case_plan_line(api, line_before["id"])
    assert line_after["price_stale"] is False
    assert line_after["version"] == line_before["version"]
    plan_after = read_case_plan(api, plan_before["id"])
    assert plan_after["price_stale_line_count"] == 0
    assert plan_after["version"] == plan_before["version"]


def test_three_lines_filled_the_same_day_get_three_different_sell_by_dates(api):
    """Whole muscle, ground and vac-packed pounds packed on 2026-08-05 date out five, two and fourteen days later off the one pack date.

    "On the **first** fill only, `pack_date` is stamped with the logical clock's
    current date and `sell_by_date` is set to that pack date plus the item's
    `shelf_life_days`, which is itself the department shelf life matching the
    item's merchandising class."

    Design: Corner/calculations/sell_by_date_uses_the_shelf_life_of_each_product_class
    """
    ctx = department_with_catalogue(api)
    department_id = ctx["department"]["id"]
    set_clock(api, "2026-08-05T09:00:00Z")

    vac_packed = create_retail_item(
        api,
        department_id,
        item_code="VAC10",
        subprimal_code="TENDERLOIN_PSMO",
        product_class="VAC_PACKED",
    )
    whole_muscle_primal = create_primal_purchase(api, department_id)
    # A vac-packed item may only be proposed against a vac-packed primal.
    vac_packed_primal = create_primal_purchase(
        api,
        department_id,
        primal_code="BEEF_STRIP_LOIN",
        product_class="VAC_PACKED",
        gross_weight_lb=40.0,
        invoice_cost_cents=36000,
        freight_cost_cents=0,
        vendor_allowance_cents=0,
        receiving_shrink_lb=0.0,
    )

    whole_muscle = propose_price(
        api, ctx["whole_muscle_item"]["id"], whole_muscle_primal["id"]
    )
    ground = propose_price(api, ctx["ground_item"]["id"], whole_muscle_primal["id"])
    vac_packed = propose_price(api, vac_packed["id"], vac_packed_primal["id"])
    assert whole_muscle["shelf_life_days"] == 5
    assert ground["shelf_life_days"] == 2
    assert vac_packed["shelf_life_days"] == 14

    plan = create_case_plan(api, department_id, "2026-08-05")
    whole_muscle_line = add_case_plan_line(api, plan["id"], whole_muscle["id"], 1, 4, 30.0)
    ground_line = add_case_plan_line(api, plan["id"], ground["id"], 2, 3, 20.0)
    vac_packed_line = add_case_plan_line(api, plan["id"], vac_packed["id"], 3, 2, 10.0)
    assert whole_muscle_line["required_fill_lb"] == pytest.approx(34.50, abs=0.01)
    assert ground_line["required_fill_lb"] == pytest.approx(12.00, abs=0.01)
    assert vac_packed_line["required_fill_lb"] == pytest.approx(16.00, abs=0.01)
    publish_case_plan(api, plan["id"])

    fill_line(api, whole_muscle_line["id"], 30.0)
    fill_line(api, ground_line["id"], 12.0)
    fill_line(api, vac_packed_line["id"], 16.0)

    dated_whole_muscle = read_case_plan_line(api, whole_muscle_line["id"])
    dated_ground = read_case_plan_line(api, ground_line["id"])
    dated_vac_packed = read_case_plan_line(api, vac_packed_line["id"])
    for dated in (dated_whole_muscle, dated_ground, dated_vac_packed):
        assert dated["pack_date"] == "2026-08-05"
        assert dated["line_status"] == "FILLED"
    assert dated_whole_muscle["sell_by_date"] == "2026-08-10"
    assert dated_ground["sell_by_date"] == "2026-08-07"
    assert dated_vac_packed["sell_by_date"] == "2026-08-19"

    plan_after = read_case_plan(api, plan["id"])
    assert plan_after["total_required_fill_lb"] == pytest.approx(62.50, abs=0.01)
    assert plan_after["total_actual_fill_lb"] == pytest.approx(58.00, abs=0.01)
    assert plan_after["fill_status"] == "PARTIAL"
    assert_fill_status_follows_totals(plan_after)


def test_the_markdown_floor_holds_at_cost_and_each_give_up_rounds_on_its_own(api):
    """A ribeye line whose measured cost is 1276.7419 a pound refuses 1403 and takes 1404, and two 2.5 lb events give up 998 cents each rather than 1995 together.

    "The price floor protects cost: the floor in cents is the item's
    `yield_adjusted_cost_per_lb_cents` multiplied by one plus the department's
    `markdown_floor_pct`, rounded half up to a whole cent, and a
    `markdown_price_per_lb_cents` strictly below that floor is refused with
    `ERR_MARKDOWN_BELOW_FLOOR` while a price exactly at the floor is accepted."

    Design: Corner/calculations/markdown_floor_comes_from_yield_adjusted_cost_and_give_up_rounds_per_event
    """
    ctx = filled_plan_line(api, filled_lb=34.0)
    line_id = ctx["line"]["id"]
    item = read_retail_item(api, ctx["whole_muscle_item"]["id"])
    assert item["yield_adjusted_cost_per_lb_cents"] == pytest.approx(
        1276.7419, abs=0.0001
    )
    assert item["active_price_per_lb_cents"] == 1999

    # The floor is round_half_up(1276.7419 x 1.10) = 1404 cents a pound.
    refused = api.create_markdown(line_id, markdown_payload(2.5, 1403), ANALYST)
    validate_error(refused, "ERR_MARKDOWN_BELOW_FLOOR", 422)
    untouched = read_case_plan_line(api, line_id)
    assert untouched["markdown_lb"] == pytest.approx(0.00, abs=0.01)
    assert untouched["markdown_dollars_cents"] == 0
    assert untouched["line_status"] == "FILLED"

    mark_down_line(api, line_id, 2.5, 1600)
    after_one = read_case_plan_line(api, line_id)
    assert after_one["markdown_lb"] == pytest.approx(2.50, abs=0.01)
    assert after_one["markdown_dollars_cents"] == 998
    assert after_one["line_status"] == "MARKED_DOWN"

    # 2.5 x 399 is 997.5, which rounds to 998 on each event; summing the exact
    # give-up of both events first would have produced 1995 cents (PRD §2.5).
    mark_down_line(api, line_id, 2.5, 1600)
    after_two = read_case_plan_line(api, line_id)
    assert after_two["markdown_lb"] == pytest.approx(5.00, abs=0.01)
    assert after_two["markdown_dollars_cents"] == 1996

    mark_down_line(api, line_id, 1.0, 1404)
    at_the_floor = read_case_plan_line(api, line_id)
    assert at_the_floor["markdown_price_per_lb_cents"] == 1404
    assert at_the_floor["markdown_lb"] == pytest.approx(6.00, abs=0.01)
    assert at_the_floor["markdown_dollars_cents"] == 2591
    assert at_the_floor["line_status"] == "MARKED_DOWN"
    assert at_the_floor["actual_fill_lb"] == pytest.approx(34.00, abs=0.01)


def test_case_line_events_wait_for_publication_and_for_pounds_that_are_still_free(api):
    """Pounds cannot go into an unpublished plan, and once 20.00 of a line's 34.00 lb are marked down only 14.00 lb are left to write off.

    "Pounds requested against a case line are actually available, meaning
    `markdown_lb`, `shrink_lb` and staged pounds together never exceed
    `actual_fill_lb` — otherwise `ERR_LINE_POUNDS_UNAVAILABLE` (422)."

    Design: Corner/validations/case_line_events_need_a_published_plan_and_unencumbered_pounds
    """
    ctx = received_primal(api)
    item = propose_price(api, ctx["whole_muscle_item"]["id"], ctx["purchase"]["id"])
    assert item["price_status"] == "PROPOSED"
    assert item["active_price_per_lb_cents"] == 2149
    # No bench test has been approved, so the cost floor on a markdown is 0.
    assert item["yield_adjusted_cost_per_lb_cents"] == pytest.approx(0.0, abs=0.0001)

    plan = create_case_plan(api, ctx["department"]["id"], FIXTURE_DATE)
    line = add_case_plan_line(api, plan["id"], item["id"], 1, 4, 30.0)
    assert line["required_fill_lb"] == pytest.approx(34.50, abs=0.01)
    assert line["line_status"] == "PLANNED"

    too_early = api.create_fill(line["id"], fill_payload(34.0), CUTTER)
    validate_error(too_early, "ERR_CASE_PLAN_NOT_PUBLISHED", 409)
    still_empty = read_case_plan_line(api, line["id"])
    assert still_empty["actual_fill_lb"] == pytest.approx(0.00, abs=0.01)
    assert still_empty["line_status"] == "PLANNED"

    publish_case_plan(api, plan["id"])
    fill_line(api, line["id"], 34.0)
    filled = read_case_plan_line(api, line["id"])
    assert filled["actual_fill_lb"] == pytest.approx(34.00, abs=0.01)
    assert filled["line_status"] == "FILLED"

    mark_down_line(api, line["id"], 20.0, 1600)
    marked = read_case_plan_line(api, line["id"])
    assert marked["markdown_lb"] == pytest.approx(20.00, abs=0.01)

    # 20.00 marked down plus 20.00 written off would be 40.00 of 34.00 pounds.
    over_committed = api.create_shrink_event(
        line["id"], shrink_event_payload(20.0), MANAGER
    )
    validate_error(over_committed, "ERR_LINE_POUNDS_UNAVAILABLE", 422)
    unchanged = read_case_plan_line(api, line["id"])
    assert unchanged["shrink_lb"] == pytest.approx(0.00, abs=0.01)
    assert unchanged["markdown_lb"] == pytest.approx(20.00, abs=0.01)

    write_off_line(api, line["id"], 14.0)
    settled = read_case_plan_line(api, line["id"])
    assert settled["shrink_lb"] == pytest.approx(14.00, abs=0.01)
    assert settled["markdown_lb"] == pytest.approx(20.00, abs=0.01)
    assert settled["actual_fill_lb"] == pytest.approx(34.00, abs=0.01)
    assert_line_pounds_available(settled)


def test_the_fill_response_carries_the_dating_and_the_plan_roll_up_is_already_there(api):
    """The 34.50 lb fill answers for its own pack date, sell-by date, pounds and status, and the very next read of the plan already shows it FILLED.

    "Derived fields are reconciled immediately, in the same request that causes
    them to move, and they cascade transitively."

    Design: Corner/consistency_model/a_fill_response_already_carries_every_field_it_derived
    """
    ctx = received_primal(api)
    set_clock(api, "2026-08-05T09:00:00Z")
    item = propose_price(api, ctx["whole_muscle_item"]["id"], ctx["purchase"]["id"])
    assert item["active_price_per_lb_cents"] == 2149

    plan = create_case_plan(api, ctx["department"]["id"], "2026-08-05")
    line = add_case_plan_line(api, plan["id"], item["id"], 1, 4, 30.0)
    assert line["required_fill_lb"] == pytest.approx(34.50, abs=0.01)
    publish_case_plan(api, plan["id"])

    filled = get_success_data(
        api.create_fill(line["id"], fill_payload(34.5), CUTTER), 201
    )
    assert filled["actual_fill_lb"] == pytest.approx(34.50, abs=0.01)
    assert filled["pack_date"] == "2026-08-05"
    assert filled["sell_by_date"] == "2026-08-10"
    assert filled["line_status"] == "FILLED"

    plan_now = read_case_plan(api, plan["id"])
    assert plan_now["total_actual_fill_lb"] == pytest.approx(34.50, abs=0.01)
    assert plan_now["fill_status"] == "FILLED"
    assert_fill_status_follows_totals(plan_now)
