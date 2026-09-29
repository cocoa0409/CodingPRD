"""Closed hold intervals, the two-day buffer, and where hold credit ends up."""

from test_helpers import (
    OPS_AGENT_HEADERS,
    api_client,
    create_active_print_plan,
    create_hold,
    create_registered_reader,
    invoice_for_cycle,
    list_holds,
    make_reader_headers,
    open_subscription,
    read_hold,
    read_subscription,
    record_payment,
    run_billing,
    set_clock_date,
    validate_error,
    validate_success,
)
from test_helpers import factories as f


def _paid_print_subscription(plan_name, reader_email):
    """A paid PRINT_DIGITAL subscription whose daily print rate is 225 cents."""
    set_clock_date("2026-09-01")
    plan = create_active_print_plan(
        name=plan_name,
        intro_price_cents=999,
        intro_cycles=1,
        standard_price_cents=1899,
        standard_from_cycle=2,
        cycle_days=30,
        print_component_cents=900,
        print_deliveries_per_cycle=4,
        print_delivery_days=["SUN"],
    )
    reader = create_registered_reader(reader_email)
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 999)
    return {
        "plan": plan,
        "reader": reader,
        "reader_headers": make_reader_headers(reader["id"]),
        "subscription": subscription,
    }


def _arrange_twenty_five_vacation_days_already_booked():
    """A 25-day vacation hold ending 2026-09-30, worth four Sundays of credit."""
    state = _paid_print_subscription("Print + Digital P6", "reader10@mail.test")
    state["hold"] = create_hold(
        state["subscription"]["id"],
        "VACATION_DELIVERY",
        "2026-09-06",
        "2026-09-30",
        state["reader_headers"],
    )
    return state


def test_buffer_violation_is_reported_ahead_of_the_vacation_day_cap():
    """A hold starting one day inside the buffer would also breach 28 days; buffer wins.

    PRD: "When more than one rule could reject a request, the rejection reported is always the one from the earliest rule in the following ladder. The ordering is normative, not incidental; a later check must never mask an earlier one."
    PRD: "For a `VACATION_DELIVERY` or `PAUSE_BILLING` hold, the request is refused with `ERR_HOLD_BUFFER_VIOLATION` when any existing hold on the same subscription whose `status` is `SCHEDULED`, `ACTIVE` or `COMPLETED` satisfies both of these: the new hold's `start_date` is on or before that hold's `end_date` advanced by two days, and that hold's `start_date` is on or before the new hold's `end_date` advanced by two days."

    Design: Difficulty/priority_pair_validation_conflict/hold_buffer_conflict_outranks_vacation_cap_rejected
    """
    state = _arrange_twenty_five_vacation_days_already_booked()

    response = api_client.create_hold(
        state["subscription"]["id"],
        f.create_hold_payload("VACATION_DELIVERY", "2026-10-01", "2026-10-06"),
        state["reader_headers"],
    )

    error = validate_error(response, "ERR_HOLD_BUFFER_VIOLATION", 409)
    assert error["error_id"] != "ERR_VACATION_DAY_CAP_EXCEEDED"


def test_refused_hold_leaves_the_booked_vacation_days_and_pending_credit_alone():
    """One hold row survives, still carrying four credited Sundays and 25 booked days.

    PRD: "Vacation days are capped at twenty-eight per rolling year — four weeks: `vacation_days_used_365`, which is the sum of the inclusive day counts of `VACATION_DELIVERY` holds whose `status` is `SCHEDULED`, `ACTIVE` or `COMPLETED` and whose `start_date` falls on or after the clock date less 365 days, plus the requested hold's own inclusive day count, must not exceed 28, otherwise `ERR_VACATION_DAY_CAP_EXCEEDED` (HTTP 422)."
    PRD: "Creating a hold recomputes the subscription's `pending_credit_cents` upward — that field is the sum of `credit_cents` over holds on the subscription whose `status` is `SCHEDULED`, `ACTIVE` or `COMPLETED` and whose `credit_applied` is false — and recomputes `vacation_days_used_365` for a vacation hold."

    Design: Difficulty/priority_pair_validation_conflict/hold_buffer_conflict_outranks_vacation_cap_rejected
    """
    state = _arrange_twenty_five_vacation_days_already_booked()
    api_client.create_hold(
        state["subscription"]["id"],
        f.create_hold_payload("VACATION_DELIVERY", "2026-10-01", "2026-10-06"),
        state["reader_headers"],
    )

    holds = list_holds(state["subscription"]["id"])
    assert len(holds) == 1
    hold = read_hold(state["hold"]["id"])
    assert hold["delivery_days_credited"] == 4
    assert hold["credit_cents"] == 900
    subscription = read_subscription(state["subscription"]["id"])
    assert subscription["vacation_days_used_365"] == 25
    assert subscription["pending_credit_cents"] == 900


def _arrange_one_vacation_hold_ending_on_the_thirteenth():
    """A hold occupying the closed interval 2026-09-06 through 2026-09-13."""
    state = _paid_print_subscription("Print + Digital P7", "reader11@mail.test")
    state["hold"] = create_hold(
        state["subscription"]["id"],
        "VACATION_DELIVERY",
        "2026-09-06",
        "2026-09-13",
        state["reader_headers"],
    )
    return state


def test_hold_starting_exactly_two_days_after_the_previous_end_is_refused():
    """2026-09-15 is the last day inside the buffer, so near-adjacency is refused.

    PRD: "Holds are additionally separated by a two-day buffer, so back-to-back and near-adjacent holds are both refused (§3.7)."
    PRD: "Back-to-back holds and holds separated by only a day or two are therefore both refused."

    Design: Difficulty/resource_temporal_overlap/hold_closed_interval_plus_buffer_admits_and_rejects
    """
    state = _arrange_one_vacation_hold_ending_on_the_thirteenth()

    response = api_client.create_hold(
        state["subscription"]["id"],
        f.create_hold_payload("VACATION_DELIVERY", "2026-09-15", "2026-09-18"),
        state["reader_headers"],
    )

    validate_error(response, "ERR_HOLD_BUFFER_VIOLATION", 409)
    assert len(list_holds(state["subscription"]["id"])) == 1


def test_hold_starting_one_day_beyond_the_buffer_is_admitted_with_its_own_frozen_credit():
    """2026-09-16 clears the buffer and credits the single Sunday it covers.

    PRD: "A hold begins in `status` `SCHEDULED`, and its states are `SCHEDULED`, `ACTIVE`, `COMPLETED` and `RELEASED`, of which the last two are terminal."
    PRD: "For the two print types, the daily print rate is the plan's `print_component_cents` divided by its `print_deliveries_per_cycle`, rounded half up to whole cents **once**; `delivery_days_credited` is the number of dates in the closed interval from `start_date` through `end_date` inclusive whose weekday code appears in the plan's `print_delivery_days`; and `credit_cents` is that rounded daily rate multiplied by `delivery_days_credited`, with no further rounding."

    Design: Difficulty/resource_temporal_overlap/hold_closed_interval_plus_buffer_admits_and_rejects
    """
    state = _arrange_one_vacation_hold_ending_on_the_thirteenth()

    admitted = validate_success(
        api_client.create_hold(
            state["subscription"]["id"],
            f.create_hold_payload("VACATION_DELIVERY", "2026-09-16", "2026-09-22"),
            state["reader_headers"],
        ),
        201,
    )

    assert admitted["status"] == "SCHEDULED"
    assert admitted["delivery_days_credited"] == 1
    assert admitted["credit_cents"] == 225
    first = read_hold(state["hold"]["id"])
    assert first["delivery_days_credited"] == 2
    assert first["credit_cents"] == 450
    assert len(list_holds(state["subscription"]["id"])) == 2
    subscription = read_subscription(state["subscription"]["id"])
    assert subscription["pending_credit_cents"] == 675
    assert subscription["vacation_days_used_365"] == 15


def _arrange_released_hold_then_a_swept_hold():
    """One hold released early, a second one completed and swept onto cycle 2."""
    state = _paid_print_subscription("Print + Digital P8", "reader12@mail.test")
    first = create_hold(
        state["subscription"]["id"],
        "VACATION_DELIVERY",
        "2026-09-06",
        "2026-09-13",
        state["reader_headers"],
    )
    validate_success(api_client.release_hold(first["id"], OPS_AGENT_HEADERS), 200)
    second = create_hold(
        state["subscription"]["id"],
        "VACATION_DELIVERY",
        "2026-09-16",
        "2026-09-27",
        state["reader_headers"],
    )
    set_clock_date("2026-09-16")
    run_billing("HOLDS_ONLY")
    set_clock_date("2026-09-28")
    run_billing("HOLDS_ONLY")
    set_clock_date("2026-10-01")
    run_billing("BILLING_ONLY")
    return {
        **state,
        "released": read_hold(first["id"]),
        "swept": read_hold(second["id"]),
        "subscription": read_subscription(state["subscription"]["id"]),
        "invoice": invoice_for_cycle(state["subscription"]["id"], 2),
    }


def test_released_hold_reverses_its_credit_while_the_lifetime_total_only_ever_grows():
    """The released hold keeps its frozen figure but contributes to neither total.

    PRD: "Release sets `status` to `RELEASED` and recomputes `pending_credit_cents` downward by exactly this hold's `credit_cents`, leaving `lifetime_credit_cents` — which is the sum of `credit_cents` over holds whose `credit_applied` is true, and which never decreases — completely untouched."
    PRD: "The distinction between the two exits is the money: a hold that runs to `COMPLETED` keeps its credit, while a hold that exits to `RELEASED` has its credit reversed."

    Design: Difficulty/compensating_invariant/hold_credit_money_conserved_across_release_and_sweep
    """
    state = _arrange_released_hold_then_a_swept_hold()

    released = state["released"]
    assert released["status"] == "RELEASED"
    assert released["credit_cents"] == 450
    assert released["credit_applied"] is False
    assert state["subscription"]["pending_credit_cents"] == 0
    assert state["subscription"]["lifetime_credit_cents"] == 450
    assert state["subscription"]["vacation_days_used_365"] == 12


def test_completed_hold_credit_is_swept_onto_the_next_invoice_and_banked_once():
    """The surviving 450 lands on cycle 2 exactly once, taking the total to 1449.

    PRD: "Every hold swept in step 6 has its `credit_applied` set to true and its `credit_applied_cycle_index` set to the cycle this invoice bills, which is also what moves that money out of `pending_credit_cents` and into `lifetime_credit_cents`. When the discount fraction was greater than zero, `retention_discount_cycles_remaining` is decremented by one."
    PRD: "Completing a print hold drives the print dimension `HELD → SCHEDULED` or `INTERRUPTED → SCHEDULED`, provided no other hold with `hold_type` `VACATION_DELIVERY` or `DELIVERY_INTERRUPTION` is still `ACTIVE` on that subscription."

    Design: Difficulty/compensating_invariant/hold_credit_money_conserved_across_release_and_sweep
    """
    state = _arrange_released_hold_then_a_swept_hold()

    swept = state["swept"]
    assert swept["status"] == "COMPLETED"
    assert swept["delivery_days_credited"] == 2
    assert swept["credit_cents"] == 450
    assert swept["credit_applied"] is True
    assert swept["credit_applied_cycle_index"] == 2

    invoice = state["invoice"]
    assert invoice["base_line_cents"] == 1899
    assert invoice["discount_line_cents"] == 0
    assert invoice["credit_line_cents"] == 450
    assert invoice["total_cents"] == 1449
    assert invoice["status"] == "OPEN"
    assert state["subscription"]["print_fulfillment_status"] == "SCHEDULED"
