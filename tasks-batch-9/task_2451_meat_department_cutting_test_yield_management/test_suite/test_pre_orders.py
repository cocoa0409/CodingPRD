"""Customer special orders: the pickup window, the slot counter and the deposit.

Every test here builds its own department, its own provisionally priced ribeye
and its own service-day case from scratch through the public endpoints, then
drives the logical clock onto the exact instant the rule under test pivots on.
"""

import pytest

from test_helpers import (
    CLERK,
    CUTTER,
    add_case_plan_line,
    assert_deposit_identity,
    assert_line_pounds_available,
    assert_posture,
    assert_pre_order,
    cancel_pre_order,
    confirm_pre_order,
    contain_case_failure,
    create_case_plan,
    create_department,
    create_ground_item,
    create_pre_order,
    create_primal_purchase,
    create_retail_item,
    expected_deposit_cents,
    fill_line,
    get_success_data,
    only_case_failure,
    post_reading,
    propose_price,
    publish_case_plan,
    read_case_plan,
    read_case_plan_line,
    read_department,
    read_pre_order,
    read_retail_item,
    resume_case_plan,
    set_clock,
    stage_pre_order,
    suspend_case_plan,
    transition_payload,
    validate_error,
)

# The service day every case in this file merchandises, and the instants the
# promised pickup windows are cut against.
SERVICE_DAY = "2026-08-05"
MORNING = "2026-08-05T08:00:00Z"
JUST_BEFORE_WINDOW = "2026-08-05T13:59:00Z"
WINDOW_START = "2026-08-05T14:00:00Z"
WINDOW_END = "2026-08-05T15:00:00Z"
SECOND_WINDOW_END = "2026-08-05T16:00:00Z"
AFTER_WINDOW = "2026-08-05T16:00:00Z"

# The provisional shelf tag RIB01 carries off purchase P1 (PRD §3.4): the
# invoiced 84000 cents over 98.50 net pounds over the book salable yield of
# 0.62 gives a 1375.4708 cost basis, which prices out at 2149 cents a pound.
PINNED_QUOTE_CENTS = 2149
DEPOSIT_RATE = 0.25


def _proposed_ribeye(api):
    """A department on its defaults whose RIB01 carries a provisional 2149-cent
    shelf tag off the standard 100 lb ribeye receipt."""
    department = create_department(api)
    item = create_retail_item(api, department["id"])
    purchase = create_primal_purchase(api, department["id"])
    item = propose_price(api, item["id"], purchase["id"])
    return department, item


def _filled_ribeye_case(api, department_id, item_id, filled_lb=34.0):
    """One published service-day case line on RIB01 — four facings against a
    30.0 lb forecast, so required fill is 34.50 lb — filled off the bench."""
    plan = create_case_plan(api, department_id, SERVICE_DAY)
    line = add_case_plan_line(api, plan["id"], item_id, 1, 4, 30.0)
    plan = publish_case_plan(api, plan["id"])
    fill_line(api, line["id"], filled_lb)
    return plan, read_case_plan_line(api, line["id"])


def _pick_up(api, order_id):
    """The clerk's pickup request, returned unvalidated so the caller may assert
    either the settled order or the refusal it earned."""
    return api.transition_pre_order(order_id, transition_payload("PICK_UP"), CLERK)


def test_a_held_order_reports_the_hold_rather_than_the_closed_window(api):
    """A pickup breaking both the hold rung (§2.11 rung 20) and the pickup-window rung (§2.11 rung 27) reports the hold.

    "A request that would fail three checks reports only the lowest-numbered
    one; a later, more dramatic-sounding failure never masks an earlier one."

    Design: Difficulty/priority_pair_validation_conflict/pre_order_hold_outranks_closed_pickup_window
    """
    set_clock(api, MORNING)
    department, item = _proposed_ribeye(api)
    plan, line = _filled_ribeye_case(api, department["id"], item["id"])

    order = create_pre_order(
        api, department["id"], item["id"], 5.0, WINDOW_START, WINDOW_END
    )
    order = confirm_pre_order(api, order["id"])
    order = stage_pre_order(api, order["id"], line["id"])
    assert order["status"] == "STAGED"

    # A 7.2 C reading sits at or above the critical ceiling, so a failure opens
    # immediately and the halt cascades into the plan, its line and the order.
    post_reading(api, department["id"], "CASE-A", 7.2)
    assert_posture(read_department(api, department["id"]), "SALES_HALTED")
    assert read_case_plan(api, plan["id"])["plan_status"] == "SUSPENDED"
    held_line = read_case_plan_line(api, line["id"])
    assert held_line["line_status"] == "HELD"
    assert held_line["held_from_status"] == "FILLED"
    assert read_pre_order(api, order["id"])["status"] == "HELD"

    # The promised window has closed too, so the pickup breaks both rungs at once.
    set_clock(api, AFTER_WINDOW)
    validate_error(_pick_up(api, order["id"]), "ERR_LINE_ON_HOLD", 409)

    unchanged = read_pre_order(api, order["id"])
    assert_pre_order(unchanged)
    assert unchanged["status"] == "HELD"
    assert unchanged["quoted_price_per_lb_cents"] == PINNED_QUOTE_CENTS
    assert unchanged["deposit_cents"] == 2687
    assert unchanged["deposit_cents"] == expected_deposit_cents(
        PINNED_QUOTE_CENTS, 5.0, DEPOSIT_RATE
    )
    assert unchanged["deposit_applied_cents"] == 0
    assert unchanged["deposit_refund_cents"] == 0
    assert unchanged["deposit_forfeited_cents"] == 0


def test_the_closed_window_refusal_surfaces_only_once_the_hold_is_lifted(api):
    """Containing the failure and resuming the plan clears the §2.11 rung 20 hold, leaving the rung 27 window refusal to answer the identical pickup.

    "Pickup is a `ServiceClerk` action taking the order `STAGED → PICKED_UP`,
    permitted only while the logical clock sits inside the closed pickup window,
    endpoints included; outside it the pickup is refused with
    `ERR_PICKUP_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/pre_order_hold_outranks_closed_pickup_window
    """
    set_clock(api, MORNING)
    department, item = _proposed_ribeye(api)
    plan, line = _filled_ribeye_case(api, department["id"], item["id"])

    order = create_pre_order(
        api, department["id"], item["id"], 5.0, WINDOW_START, WINDOW_END
    )
    confirm_pre_order(api, order["id"])
    stage_pre_order(api, order["id"], line["id"])

    post_reading(api, department["id"], "CASE-A", 7.2)
    assert read_pre_order(api, order["id"])["status"] == "HELD"

    # The cutter contains the failure, which relaxes the department to
    # SALES_RESTRICTED, and the manager may then resume the plan.
    failure = contain_case_failure(api, only_case_failure(api)["id"])
    assert failure["status"] == "CONTAINED"
    assert_posture(read_department(api, department["id"]), "SALES_RESTRICTED")

    resumed = resume_case_plan(api, plan["id"])
    assert resumed["plan_status"] == "PUBLISHED"
    released_line = read_case_plan_line(api, line["id"])
    assert released_line["line_status"] == "FILLED"
    assert read_pre_order(api, order["id"])["status"] == "STAGED"

    set_clock(api, AFTER_WINDOW)
    validate_error(_pick_up(api, order["id"]), "ERR_PICKUP_WINDOW_CLOSED", 422)

    still_staged = read_pre_order(api, order["id"])
    assert_pre_order(still_staged)
    assert still_staged["status"] == "STAGED"
    assert still_staged["quoted_price_per_lb_cents"] == PINNED_QUOTE_CENTS
    assert still_staged["deposit_cents"] == 2687
    assert still_staged["deposit_applied_cents"] == 0
    assert still_staged["deposit_refund_cents"] == 0
    assert still_staged["deposit_forfeited_cents"] == 0
    assert float(read_case_plan_line(api, line["id"])["staged_lb"]) == pytest.approx(
        5.00, abs=0.01
    )


def test_a_pickup_on_the_closing_instant_of_the_window_applies_the_deposit(api):
    """The very last instant of the promised window still belongs to it, so the pickup lands and the whole deposit is applied.

    "Unlike a grinder window, a pickup window is a **closed** interval: both
    endpoints belong to it."

    Design: Difficulty/priority_pair_validation_conflict/pre_order_hold_outranks_closed_pickup_window
    """
    set_clock(api, MORNING)
    department, item = _proposed_ribeye(api)
    plan, line = _filled_ribeye_case(api, department["id"], item["id"])

    order = create_pre_order(
        api, department["id"], item["id"], 5.0, WINDOW_START, WINDOW_END
    )
    confirm_pre_order(api, order["id"])
    stage_pre_order(api, order["id"], line["id"])

    post_reading(api, department["id"], "CASE-A", 7.2)
    contain_case_failure(api, only_case_failure(api)["id"])
    resume_case_plan(api, plan["id"])
    assert read_pre_order(api, order["id"])["status"] == "STAGED"

    # 15:00:00Z is the closing endpoint of the 14:00Z..15:00Z window, and a
    # closed interval includes it.
    set_clock(api, WINDOW_END)
    picked_up = get_success_data(_pick_up(api, order["id"]), 200)

    assert_pre_order(picked_up)
    assert picked_up["status"] == "PICKED_UP"
    assert picked_up["deposit_cents"] == 2687
    assert picked_up["deposit_applied_cents"] == 2687
    assert picked_up["deposit_refund_cents"] == 0
    assert picked_up["deposit_forfeited_cents"] == 0
    assert_deposit_identity(picked_up)

    # The five pounds leave both the reservation and the case fill total.
    emptied = read_case_plan_line(api, line["id"])
    assert float(emptied["staged_lb"]) == pytest.approx(0.00, abs=0.01)
    assert float(emptied["actual_fill_lb"]) == pytest.approx(29.00, abs=0.01)
    assert_line_pounds_available(emptied)


def test_staging_is_refused_while_the_case_line_sits_on_hold(api):
    """A suspended plan holds its filled line, and that other aggregate's state alone refuses the staging of a confirmed order.

    "It requires a `staged_case_plan_line_id` naming a case line whose
    `line_status` is `FILLED` or `MARKED_DOWN`; a line in `HELD` is refused with
    `ERR_LINE_ON_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/pre_order_staging_gated_on_case_plan_line_hold_state
    """
    set_clock(api, MORNING)
    department, item = _proposed_ribeye(api)
    plan, line = _filled_ribeye_case(api, department["id"], item["id"])
    fill_status_before = read_case_plan(api, plan["id"])["fill_status"]
    assert fill_status_before == "PARTIAL"

    order = create_pre_order(
        api, department["id"], item["id"], 5.0, WINDOW_START, WINDOW_END
    )
    order = confirm_pre_order(api, order["id"])
    assert order["status"] == "CONFIRMED"

    # The manager suspends the plan by hand; the cold chain never moved.
    suspended = suspend_case_plan(api, plan["id"])
    assert suspended["plan_status"] == "SUSPENDED"
    assert_posture(read_department(api, department["id"]), "SALES_OPEN")
    held_line = read_case_plan_line(api, line["id"])
    assert held_line["line_status"] == "HELD"
    assert held_line["held_from_status"] == "FILLED"

    refusal = api.transition_pre_order(
        order["id"],
        transition_payload("STAGE", staged_case_plan_line_id=line["id"]),
        CUTTER,
    )
    validate_error(refusal, "ERR_LINE_ON_HOLD", 409)

    unchanged = read_pre_order(api, order["id"])
    assert_pre_order(unchanged)
    assert unchanged["status"] == "CONFIRMED"
    assert float(read_case_plan_line(api, line["id"])["staged_lb"]) == pytest.approx(
        0.00, abs=0.01
    )
    assert read_case_plan(api, plan["id"])["fill_status"] == fill_status_before


def test_the_identical_staging_request_lands_once_the_plan_is_resumed(api):
    """Resuming the plan returns the line to FILLED, and the byte-identical staging request then reserves the pounds.

    "Staging adds `requested_weight_lb` to the line's `staged_lb`, which is what
    makes those pounds unavailable to markdowns and shrink events."

    Design: Difficulty/cross_entity_state_dependency/pre_order_staging_gated_on_case_plan_line_hold_state
    """
    set_clock(api, MORNING)
    department, item = _proposed_ribeye(api)
    plan, line = _filled_ribeye_case(api, department["id"], item["id"])
    fill_status_before = read_case_plan(api, plan["id"])["fill_status"]

    order = create_pre_order(
        api, department["id"], item["id"], 5.0, WINDOW_START, WINDOW_END
    )
    confirm_pre_order(api, order["id"])

    suspend_case_plan(api, plan["id"])
    assert read_case_plan_line(api, line["id"])["line_status"] == "HELD"

    resumed = resume_case_plan(api, plan["id"])
    assert resumed["plan_status"] == "PUBLISHED"
    released_line = read_case_plan_line(api, line["id"])
    assert released_line["line_status"] == "FILLED"

    staged = stage_pre_order(api, order["id"], line["id"])
    assert_pre_order(staged)
    assert staged["status"] == "STAGED"
    assert staged["staged_case_plan_line_id"] == line["id"]

    reserved = read_case_plan_line(api, line["id"])
    assert float(reserved["staged_lb"]) == pytest.approx(5.00, abs=0.01)
    assert float(reserved["actual_fill_lb"]) == pytest.approx(34.00, abs=0.01)
    assert_line_pounds_available(reserved)
    # Neither the hold nor its release touches the plan's execution dimension.
    assert read_case_plan(api, plan["id"])["fill_status"] == fill_status_before


def test_a_third_intersecting_pickup_window_exhausts_the_slot_capacity(api):
    """Two confirmed windows that merely touch at an endpoint both count against a third window intersecting each of them.

    "Capacity is also checked: the count of already `CONFIRMED` or `STAGED`
    pre-orders in the department whose own closed pickup interval intersects the
    requested interval must be strictly below the department's
    `pickup_slot_capacity`, and reaching that ceiling is refused with
    `ERR_PICKUP_SLOT_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/pickup_slot_capacity_over_closed_intervals
    """
    set_clock(api, MORNING)
    department, item = _proposed_ribeye(api)
    assert int(department["pickup_slot_capacity"]) == 2

    first = create_pre_order(
        api, department["id"], item["id"], 5.0, WINDOW_START, WINDOW_END
    )
    second = create_pre_order(
        api, department["id"], item["id"], 4.0, WINDOW_END, SECOND_WINDOW_END
    )
    third = create_pre_order(
        api, department["id"], item["id"], 3.0, WINDOW_END, "2026-08-05T15:30:00Z"
    )

    # Nothing collides with the first window yet.
    first = confirm_pre_order(api, first["id"])
    assert first["status"] == "CONFIRMED"
    assert first["deposit_cents"] == 2687

    # 15:00Z..16:00Z touches the first window's closed end, so it does collide —
    # but a single collision is still strictly below the capacity of two.
    second = confirm_pre_order(api, second["id"])
    assert second["status"] == "CONFIRMED"
    assert second["deposit_cents"] == 2149
    assert second["deposit_cents"] == expected_deposit_cents(
        PINNED_QUOTE_CENTS, 4.0, DEPOSIT_RATE
    )

    # 15:00Z..15:30Z touches the first at 15:00Z and overlaps the second, so the
    # counter has both slots taken.
    refusal = api.transition_pre_order(
        third["id"], transition_payload("CONFIRM"), CLERK
    )
    validate_error(refusal, "ERR_PICKUP_SLOT_CAPACITY_EXCEEDED", 409)

    unchanged = read_pre_order(api, third["id"])
    assert_pre_order(unchanged)
    assert unchanged["status"] == "REQUESTED"
    assert unchanged["quoted_price_per_lb_cents"] == 0
    assert unchanged["pinned_retail_item_version"] == 0
    assert unchanged["deposit_cents"] == 0


def test_a_window_touching_only_one_confirmed_interval_still_confirms(api):
    """A fourth window that meets only one of the two confirmed intervals leaves a slot free, so it confirms and pins its own quote.

    "Confirmation pins the quote so later repricing cannot move it:
    `quoted_price_per_lb_cents` takes the item's `active_price_per_lb_cents` as
    of that instant and `pinned_retail_item_version` takes the item's
    `version`."

    Design: Difficulty/resource_temporal_overlap/pickup_slot_capacity_over_closed_intervals
    """
    set_clock(api, MORNING)
    department, item = _proposed_ribeye(api)

    first = create_pre_order(
        api, department["id"], item["id"], 5.0, WINDOW_START, WINDOW_END
    )
    second = create_pre_order(
        api, department["id"], item["id"], 4.0, WINDOW_END, SECOND_WINDOW_END
    )
    fourth = create_pre_order(
        api, department["id"], item["id"], 6.0, SECOND_WINDOW_END, "2026-08-05T17:00:00Z"
    )
    confirm_pre_order(api, first["id"])
    confirm_pre_order(api, second["id"])

    # 16:00Z..17:00Z meets the second window at 16:00Z and misses the first
    # entirely, so only one of the two slots is taken.
    confirmed = confirm_pre_order(api, fourth["id"])
    assert_pre_order(confirmed)
    assert confirmed["status"] == "CONFIRMED"

    tagged_item = read_retail_item(api, item["id"])
    assert confirmed["quoted_price_per_lb_cents"] == PINNED_QUOTE_CENTS
    assert (
        confirmed["quoted_price_per_lb_cents"]
        == tagged_item["active_price_per_lb_cents"]
    )
    assert confirmed["pinned_retail_item_version"] == tagged_item["version"]
    assert confirmed["deposit_cents"] == 3224
    assert confirmed["deposit_cents"] == expected_deposit_cents(
        PINNED_QUOTE_CENTS, 6.0, DEPOSIT_RATE
    )


def test_pre_order_amend_cycle_releases_quote_until_the_amend_budget_runs_out(api):
    """Each amendment hands the pinned quote and the deposit back, and the third amendment is refused outright.

    "The amendment budget is two: amending is permitted only while `amend_count`
    is below 2, and the third attempt is refused with
    `ERR_REVISION_LIMIT_REACHED`."

    Design: Corner/state_machines/pre_order_amend_cycle_releases_quote_until_the_amend_budget_runs_out
    """
    set_clock(api, MORNING)
    department, item = _proposed_ribeye(api)
    pinned_version = read_retail_item(api, item["id"])["version"]

    order = create_pre_order(
        api, department["id"], item["id"], 5.0, WINDOW_START, WINDOW_END
    )
    assert order["status"] == "REQUESTED"
    assert order["amend_count"] == 0
    assert order["quoted_price_per_lb_cents"] == 0
    assert order["deposit_cents"] == 0

    for expected_amend_count in (0, 1):
        confirmed = confirm_pre_order(api, order["id"])
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["quoted_price_per_lb_cents"] == PINNED_QUOTE_CENTS
        assert confirmed["pinned_retail_item_version"] == pinned_version
        assert confirmed["deposit_cents"] == 2687
        assert confirmed["amend_count"] == expected_amend_count

        amended = get_success_data(
            api.transition_pre_order(order["id"], transition_payload("AMEND"), CLERK),
            200,
        )
        assert_pre_order(amended)
        assert amended["status"] == "REQUESTED"
        assert amended["amend_count"] == expected_amend_count + 1
        assert amended["quoted_price_per_lb_cents"] == 0
        assert amended["pinned_retail_item_version"] == 0
        assert amended["deposit_cents"] == 0

    # The budget is spent, so the third confirmation may no longer be undone.
    third = confirm_pre_order(api, order["id"])
    assert third["status"] == "CONFIRMED"
    assert third["amend_count"] == 2
    assert third["quoted_price_per_lb_cents"] == PINNED_QUOTE_CENTS
    assert third["deposit_cents"] == 2687

    refusal = api.transition_pre_order(order["id"], transition_payload("AMEND"), CLERK)
    validate_error(refusal, "ERR_REVISION_LIMIT_REACHED", 422)

    intact = read_pre_order(api, order["id"])
    assert_pre_order(intact)
    assert intact["status"] == "CONFIRMED"
    assert intact["amend_count"] == 2
    assert intact["quoted_price_per_lb_cents"] == PINNED_QUOTE_CENTS
    assert intact["pinned_retail_item_version"] == pinned_version
    assert intact["deposit_cents"] == 2687


def test_pre_order_cancellation_splits_the_deposit_at_the_window_boundary(api):
    """Cancelling a minute before the promised window returns the whole deposit, while cancelling on the opening instant returns half and forfeits the residual.

    "Cancelling at or after that instant refunds half: `deposit_refund_cents` is
    `deposit_cents` multiplied by one half and rounded half up to a whole cent,
    and `deposit_forfeited_cents` takes the residual, the deposit minus that
    refund."

    Design: Corner/calculations/pre_order_cancellation_splits_the_deposit_at_the_window_boundary
    """
    set_clock(api, MORNING)
    department, item = _proposed_ribeye(api)

    early = create_pre_order(
        api, department["id"], item["id"], 5.0, WINDOW_START, WINDOW_END
    )
    late = create_pre_order(
        api, department["id"], item["id"], 4.0, WINDOW_END, SECOND_WINDOW_END
    )
    early = confirm_pre_order(api, early["id"])
    late = confirm_pre_order(api, late["id"])

    # 2149 x 5.0 x 0.25 is exactly 2686.25 and the deposit is rounded up, never
    # half up; 2149 x 4.0 x 0.25 is exactly 2149 and needs no rounding at all.
    assert early["deposit_cents"] == 2687
    assert late["deposit_cents"] == 2149

    set_clock(api, JUST_BEFORE_WINDOW)
    cancelled_early = cancel_pre_order(api, early["id"])
    assert_pre_order(cancelled_early)
    assert cancelled_early["status"] == "CANCELLED"
    assert cancelled_early["deposit_refund_cents"] == 2687
    assert cancelled_early["deposit_forfeited_cents"] == 0
    assert cancelled_early["deposit_applied_cents"] == 0
    assert_deposit_identity(cancelled_early)

    # 15:00:00Z is the second order's own opening instant, which belongs to the
    # half-refund branch.
    set_clock(api, WINDOW_END)
    cancelled_late = cancel_pre_order(api, late["id"])
    assert_pre_order(cancelled_late)
    assert cancelled_late["status"] == "CANCELLED"
    assert cancelled_late["deposit_refund_cents"] == 1075
    assert cancelled_late["deposit_forfeited_cents"] == 1074
    assert cancelled_late["deposit_applied_cents"] == 0
    assert_deposit_identity(cancelled_late)


def test_staging_a_pre_order_on_an_expired_case_line_is_rejected(api):
    """A ground line packed on the service day cannot be staged three days later, even though the customer's pickup window is still open.

    "The line must also still be saleable — its `sell_by_date` must not be
    earlier than the logical clock's current date, or the staging is refused
    with `ERR_SELL_BY_EXPIRED`."

    Design: Corner/validations/staging_a_pre_order_on_an_expired_case_line_is_rejected
    """
    set_clock(api, MORNING)
    department = create_department(api)
    ground = create_ground_item(api, department["id"])
    purchase = create_primal_purchase(api, department["id"])
    ground = propose_price(api, ground["id"], purchase["id"])
    assert ground["active_price_per_lb_cents"] == PINNED_QUOTE_CENTS
    assert int(ground["shelf_life_days"]) == 2

    plan = create_case_plan(api, department["id"], SERVICE_DAY)
    line = add_case_plan_line(api, plan["id"], ground["id"], 1, 3, 20.0)
    assert float(line["required_fill_lb"]) == pytest.approx(12.00, abs=0.01)
    publish_case_plan(api, plan["id"])
    fill_line(api, line["id"], 12.0)
    line = read_case_plan_line(api, line["id"])
    assert line["line_status"] == "FILLED"
    assert line["pack_date"] == "2026-08-05"
    assert line["sell_by_date"] == "2026-08-07"

    order = create_pre_order(
        api,
        department["id"],
        ground["id"],
        5.0,
        "2026-08-08T14:00:00Z",
        "2026-08-08T15:00:00Z",
    )
    order = confirm_pre_order(api, order["id"])
    assert order["status"] == "CONFIRMED"
    assert order["quoted_price_per_lb_cents"] == PINNED_QUOTE_CENTS
    assert order["deposit_cents"] == 2687

    # Three days on, the customer's window has opened but the ground beef in the
    # case is a day past its sell-by date.
    set_clock(api, "2026-08-08T09:00:00Z")
    refusal = api.transition_pre_order(
        order["id"],
        transition_payload("STAGE", staged_case_plan_line_id=line["id"]),
        CUTTER,
    )
    validate_error(refusal, "ERR_SELL_BY_EXPIRED", 422)

    unchanged = read_pre_order(api, order["id"])
    assert_pre_order(unchanged)
    assert unchanged["status"] == "CONFIRMED"
    assert not unchanged.get("staged_case_plan_line_id")
    untouched_line = read_case_plan_line(api, line["id"])
    assert untouched_line["line_status"] == "FILLED"
    assert float(untouched_line["actual_fill_lb"]) == pytest.approx(12.00, abs=0.01)
    assert float(untouched_line["staged_lb"]) == pytest.approx(0.00, abs=0.01)
