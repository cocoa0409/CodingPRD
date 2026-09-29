"""Maintenance priority classification, the SLA clocks, and the reopen cycle."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions as asserts
from test_helpers import fixtures as fx
from test_helpers import test_users as tu
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS

REPORTED_AT = "2026-09-10T09:00:00Z"


def _occupied_unit_at_the_reporting_clock(api):
    """The canonical tenancy, with the clock parked at the reporting instant."""
    state = fx.setup_occupied_lease(api)
    fx.set_clock(api, REPORTED_AT)
    return state


def test_cosmetic_order_with_no_habitability_impact_stays_routine(api):
    """A tier-one category with no floors applied keeps the thirty-day clock.

    PRD: "A `ROUTINE` order must be responded to within 120 hours — five days — and completed within 720 hours, which is thirty days."

    Design: Difficulty/combinatorial_formula/work_order_priority_nonlinear_max_bumps
    """
    state = _occupied_unit_at_the_reporting_clock(api)

    order = fx.submit_work_order(
        api,
        state["unit"]["id"],
        lease_id=state["lease"]["id"],
        category="COSMETIC",
        description="Scuffed baseboard in hallway",
        habitability_impact=False,
    )

    asserts.assert_work_order(order)
    assert order["priority_class"] == "ROUTINE"
    asserts.assert_instant_equals(order["reported_at"], REPORTED_AT)
    asserts.assert_instant_equals(order["response_due_at"], "2026-09-15T09:00:00Z")
    asserts.assert_instant_equals(order["completion_due_at"], "2026-10-10T09:00:00Z")


def test_mold_order_is_urgent_even_when_habitability_is_left_false(api):
    """The category floor alone lifts a suspected-mold order off routine.

    PRD: "This is why a suspected mold or lead order is never routine even when the reporter left `habitability_impact` false."

    Design: Difficulty/combinatorial_formula/work_order_priority_nonlinear_max_bumps
    """
    state = _occupied_unit_at_the_reporting_clock(api)

    order = fx.submit_work_order(
        api,
        state["unit"]["id"],
        lease_id=state["lease"]["id"],
        category="MOLD_SUSPECTED",
        description="Discoloured grout in guest bath",
        habitability_impact=False,
    )

    assert order["priority_class"] == "URGENT"
    asserts.assert_instant_equals(order["response_due_at"], "2026-09-11T09:00:00Z")
    asserts.assert_instant_equals(order["completion_due_at"], "2026-09-13T09:00:00Z")


def test_appliance_order_with_a_young_child_in_the_home_is_an_emergency(api):
    """Two weak inputs together outrank a stronger category on the same unit.

    PRD: "A third rule then applies, and it fires **only when both** of two conditions hold together: `habitability_impact` must be true, and the sponsor on the unit's `OCCUPIED` lease must have a full-time-custody dependent whose `relationship` is `CHILD` and whose age as of `reported_at` is under six years."

    Design: Difficulty/combinatorial_formula/work_order_priority_nonlinear_max_bumps
    """
    state = _occupied_unit_at_the_reporting_clock(api)

    order = fx.submit_work_order(
        api,
        state["unit"]["id"],
        lease_id=state["lease"]["id"],
        category="APPLIANCE",
        description="Range non-functional, no means of cooking",
        habitability_impact=True,
    )

    assert order["priority_class"] == "EMERGENCY"
    asserts.assert_instant_equals(order["response_due_at"], "2026-09-10T13:00:00Z")
    # The habitability cap and the emergency table agree at plus twenty-four hours.
    asserts.assert_instant_equals(order["completion_due_at"], "2026-09-11T09:00:00Z")
    assert order["status"] == "SUBMITTED"
    assert order["escalation_level"] == 0
    assert order["sla_breached"] is False


EMERGENCY_DUE_AT = "2026-09-11T09:00:00Z"
ONE_SECOND_EARLY = "2026-09-11T08:59:59Z"
LEVEL_TWO_ONE_SECOND_EARLY = "2026-09-12T08:59:59Z"
LEVEL_TWO_DUE_AT = "2026-09-12T09:00:00Z"
LONG_AFTER = "2026-09-20T09:00:00Z"


def _emergency_order_awaiting_response(api):
    """A no-heat emergency left in SUBMITTED, due for completion at plus 24h."""
    state = _occupied_unit_at_the_reporting_clock(api)
    order = fx.submit_work_order(
        api,
        state["unit"]["id"],
        lease_id=state["lease"]["id"],
        category="NO_HEAT",
        description="No heat in the whole unit",
        habitability_impact=True,
    )
    assert order["priority_class"] == "EMERGENCY"
    asserts.assert_instant_equals(order["completion_due_at"], EMERGENCY_DUE_AT)
    state["work_order"] = order
    return state


def test_escalation_one_second_before_the_deadline_is_refused(api):
    """Zero required overdue hours still means the deadline must arrive.

    PRD: "One second earlier, escalation is refused with `ERR_ESCALATION_NOT_DUE`."

    Design: Difficulty/boundary_precision_check/emergency_escalation_eligible_at_exact_completion_due_at
    """
    state = _emergency_order_awaiting_response(api)
    fx.set_clock(api, ONE_SECOND_EARLY)

    response = api.escalate_work_order(
        state["work_order"]["id"], TEST_USERS["property_manager_headers"]
    )

    validate_error(response, ApiErrorId.ERR_ESCALATION_NOT_DUE, 409)
    order = fx.read_work_order(api, state["work_order"]["id"])
    assert order["escalation_level"] == 0
    assert order["escalated_at"] is None


def test_escalation_at_exactly_the_deadline_is_eligible_but_not_a_breach(api):
    """The inclusive escalation edge and the strict breach edge disagree here.

    PRD: "The inclusive threshold has a visible consequence at the emergency boundary: with a required overdue figure of 0 hours, a clock standing exactly at `completion_due_at` makes escalation eligible, while `sla_breached` at that same instant would still be false because the breach comparison is strict."

    Design: Difficulty/boundary_precision_check/emergency_escalation_eligible_at_exact_completion_due_at
    """
    state = _emergency_order_awaiting_response(api)
    fx.set_clock(api, EMERGENCY_DUE_AT)

    escalated = fx.escalate_work_order(api, state["work_order"]["id"])

    assert escalated["escalation_level"] == 1
    asserts.assert_instant_equals(escalated["escalated_at"], EMERGENCY_DUE_AT)
    assert escalated["sla_breached"] is False
    assert escalated["status"] == "SUBMITTED"
    assert escalated["first_response_at"] is None
    assert escalated["completed_at"] is None


def test_second_escalation_needs_a_further_twenty_four_overdue_hours(api):
    """Level two arrives exactly a day later and the ladder then stops.

    PRD: "The required overdue hours depend on the priority class and the target level: an `EMERGENCY` order needs 0 overdue hours to reach level 1 and 24 to reach level 2; an `URGENT` order needs 24 overdue hours for level 1 and 96 for level 2; a `ROUTINE` order needs 240 overdue hours — ten days — for level 1 and 480 hours, twenty days, for level 2."

    Design: Difficulty/boundary_precision_check/emergency_escalation_eligible_at_exact_completion_due_at
    """
    state = _emergency_order_awaiting_response(api)
    order_id = state["work_order"]["id"]
    fx.set_clock(api, EMERGENCY_DUE_AT)
    fx.escalate_work_order(api, order_id)

    fx.set_clock(api, LEVEL_TWO_ONE_SECOND_EARLY)
    too_early = api.escalate_work_order(
        order_id, TEST_USERS["property_manager_headers"]
    )
    validate_error(too_early, ApiErrorId.ERR_ESCALATION_NOT_DUE, 409)
    assert fx.read_work_order(api, order_id)["escalation_level"] == 1

    fx.set_clock(api, LEVEL_TWO_DUE_AT)
    escalated = fx.escalate_work_order(api, order_id)
    assert escalated["escalation_level"] == 2
    asserts.assert_instant_equals(escalated["escalated_at"], LEVEL_TWO_DUE_AT)

    # The ladder is capped at two, so a much later attempt cannot lift it.
    fx.set_clock(api, LONG_AFTER)
    api.escalate_work_order(order_id, TEST_USERS["property_manager_headers"])
    assert fx.read_work_order(api, order_id)["escalation_level"] == 2


ROUTINE_DUE_AT = "2026-10-10T09:00:00Z"


def _routine_order_completed_once(api):
    """A routine order taken once round the loop and left in COMPLETED."""
    state = _occupied_unit_at_the_reporting_clock(api)
    order = fx.submit_work_order(
        api,
        state["unit"]["id"],
        lease_id=state["lease"]["id"],
        category="COSMETIC",
        description="Scuffed baseboard in hallway",
        habitability_impact=False,
    )
    fx.assign_work_order(api, order["id"])
    fx.start_work_order(api, order["id"])
    state["work_order"] = fx.complete_work_order(api, order["id"])
    return state


def test_first_completion_leaves_the_order_reenterable(api):
    """An unspent reopen budget means completion is not the end of the road.

    PRD: "When `reopen_count` is still below 2 the order advances `IN_PROGRESS → COMPLETED`, leaving it re-enterable."

    Design: Difficulty/non_linear_state_machine/work_order_reopen_cycle_spends_budget_then_closes_terminal
    """
    state = _routine_order_completed_once(api)
    order = state["work_order"]

    assert order["status"] == "COMPLETED"
    assert order["reopen_count"] == 0
    assert order["sla_breached"] is False

    reopened = fx.reopen_work_order(
        api,
        order["id"],
        "Paint mismatch still visible",
        tu.make_service_member_headers(state["sponsor"]["id"]),
    )
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1
    assert reopened["completed_at"] is None
    assert reopened["assigned_tech_user_id"] is None
    asserts.assert_instant_equals(reopened["completion_due_at"], ROUTINE_DUE_AT)


def test_manager_reopen_spends_the_second_and_last_budget_unit(api):
    """The manager's wider budget carries the order round a second time.

    PRD: "The reopen budgets are asymmetric on purpose: a resident may reopen only an order whose `reopen_count` is still 0 — one reopen per order, after which they must ask the housing office — while a manager may reopen an order whose `reopen_count` is still below 2."

    Design: Difficulty/non_linear_state_machine/work_order_reopen_cycle_spends_budget_then_closes_terminal
    """
    state = _routine_order_completed_once(api)
    order_id = state["work_order"]["id"]
    fx.reopen_work_order(
        api,
        order_id,
        "Paint mismatch still visible",
        tu.make_service_member_headers(state["sponsor"]["id"]),
    )
    second_tech = tu.MAINTENANCE_TECH_USER_ID_2
    second_tech_headers = tu.make_maintenance_tech_headers(second_tech)
    fx.assign_work_order(api, order_id, tech_user_id=second_tech)
    fx.start_work_order(api, order_id, headers=second_tech_headers)
    completed = fx.complete_work_order(api, order_id, headers=second_tech_headers)
    assert completed["status"] == "COMPLETED"
    assert completed["reopen_count"] == 1

    reopened = fx.reopen_work_order(
        api,
        order_id,
        "Paint peeling after two days",
        TEST_USERS["property_manager_headers"],
    )

    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 2


def test_third_completion_closes_the_order_and_locks_it(api):
    """The same completion request diverges to the terminal state.

    PRD: "When `reopen_count` has already reached 2 the reopen budget is spent, so the same request instead advances `IN_PROGRESS → CLOSED`, which is terminal."

    Design: Difficulty/non_linear_state_machine/work_order_reopen_cycle_spends_budget_then_closes_terminal
    """
    state = _routine_order_completed_once(api)
    order_id = state["work_order"]["id"]
    fx.reopen_work_order(
        api,
        order_id,
        "Paint mismatch still visible",
        tu.make_service_member_headers(state["sponsor"]["id"]),
    )
    second_tech = tu.MAINTENANCE_TECH_USER_ID_2
    fx.assign_work_order(api, order_id, tech_user_id=second_tech)
    fx.start_work_order(api, order_id, headers=tu.make_maintenance_tech_headers(second_tech))
    fx.complete_work_order(api, order_id, headers=tu.make_maintenance_tech_headers(second_tech))
    fx.reopen_work_order(
        api,
        order_id,
        "Paint peeling after two days",
        TEST_USERS["property_manager_headers"],
    )
    third_tech = tu.MAINTENANCE_TECH_USER_ID_3
    third_tech_headers = tu.make_maintenance_tech_headers(third_tech)
    fx.assign_work_order(api, order_id, tech_user_id=third_tech)
    fx.start_work_order(api, order_id, headers=third_tech_headers)

    closed = fx.complete_work_order(api, order_id, headers=third_tech_headers)

    assert closed["status"] == "CLOSED"
    assert closed["reopen_count"] == 2
    assert closed["sla_breached"] is False
    asserts.assert_instant_equals(closed["completion_due_at"], ROUTINE_DUE_AT)

    locked = api.reopen_work_order(
        order_id,
        {"reopen_reason": "Tenant still unsatisfied"},
        TEST_USERS["property_manager_headers"],
    )
    validate_error(locked, ApiErrorId.ERR_TERMINAL_STATE_LOCKED, 409)
    final = fx.read_work_order(api, order_id)
    assert final["status"] == "CLOSED"
    assert final["reopen_count"] == 2
