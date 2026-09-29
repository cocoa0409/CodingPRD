"""Case-plan lifecycle: required fill, the two plan dimensions, and the roll-ups.

Every scenario here is built from scratch through the public endpoints, because
the harness restarts the server before each test with the logical clock back at
its initial instant.
"""

import pytest

from test_helpers import (
    CUTTER,
    FIXTURE_DATE,
    MANAGER,
    add_case_plan_line,
    close_case_plan,
    create_case_plan,
    expected_required_fill_lb,
    fill_line,
    get_success_data,
    publish_case_plan,
    read_case_plan,
    read_case_plan_line,
    propose_price,
    read_department,
    read_retail_item,
    received_primal,
    restrict_department,
    resume_case_plan,
    seeded_department,
    suspend_case_plan,
    suspend_retail_item,
    transition_payload,
    validate_error,
)

# Department shelf lives that the per-class required-fill arithmetic reads.
WHOLE_MUSCLE_SHELF_LIFE_DAYS = 5
GROUND_SHELF_LIFE_DAYS = 2


def _department_with_two_proposed_items(api):
    """A department whose ribeye and ground items both carry a provisional
    shelf price, which is what makes them eligible for a case-plan line."""
    ctx = received_primal(api)
    ctx["whole_muscle_item"] = propose_price(
        api, ctx["whole_muscle_item"]["id"], ctx["purchase"]["id"]
    )
    ctx["ground_item"] = propose_price(
        api, ctx["ground_item"]["id"], ctx["purchase"]["id"]
    )
    return ctx


def test_required_fill_takes_the_larger_of_presentation_and_the_demand_carry_minimum(api):
    """Required fill combines facings, forecast and shelf life through a nested max-of-min, so a demand-bound line, a carry-capacity-bound line and a presentation-bound line all land on different pounds.

    "The base is the larger of the presentation pounds and the smaller of the
    demand pounds and the carrying-capacity pounds."

    Design: Difficulty/combinatorial_formula/required_fill_nested_min_max_with_posture_branch
    """
    ctx = _department_with_two_proposed_items(api)
    plan = create_case_plan(api, ctx["department"]["id"], FIXTURE_DATE)

    # The ribeye at four facings: demand 34.50 beats presentation 24.00 and sits
    # under the carrying cap of 45.00, so demand sets the pounds.
    demand_bound = add_case_plan_line(
        api, plan["id"], ctx["whole_muscle_item"]["id"], 1, 4, 30.0
    )
    # The ground item at five facings: a two-day shelf life caps carrying at
    # 24.00, well below demand's 46.00 and above presentation's 20.00.
    carry_bound = add_case_plan_line(
        api, plan["id"], ctx["ground_item"]["id"], 2, 5, 40.0
    )
    # The same ground forecast at twelve facings: presentation 48.00 strictly
    # outruns the 24.00 the demand-and-carry minimum would allow.
    presentation_bound = add_case_plan_line(
        api, plan["id"], ctx["ground_item"]["id"], 3, 12, 40.0
    )

    expected_demand_bound = expected_required_fill_lb(
        4, "WHOLE_MUSCLE", 30.0, WHOLE_MUSCLE_SHELF_LIFE_DAYS
    )
    expected_carry_bound = expected_required_fill_lb(
        5, "GROUND", 40.0, GROUND_SHELF_LIFE_DAYS
    )
    expected_presentation_bound = expected_required_fill_lb(
        12, "GROUND", 40.0, GROUND_SHELF_LIFE_DAYS
    )
    assert expected_demand_bound == pytest.approx(34.50, abs=0.01)
    assert expected_carry_bound == pytest.approx(24.00, abs=0.01)
    assert expected_presentation_bound == pytest.approx(48.00, abs=0.01)

    assert float(demand_bound["required_fill_lb"]) == pytest.approx(
        expected_demand_bound, abs=0.01
    )
    assert float(carry_bound["required_fill_lb"]) == pytest.approx(
        expected_carry_bound, abs=0.01
    )
    assert float(presentation_bound["required_fill_lb"]) == pytest.approx(
        expected_presentation_bound, abs=0.01
    )

    # The posture never left SALES_OPEN, so no line took a haircut.
    department = read_department(api, ctx["department"]["id"])
    assert department["case_posture"] == "SALES_OPEN"
    assert int(department["consecutive_out_of_spec_readings"]) == 0

    refreshed = read_case_plan(api, plan["id"])
    assert float(refreshed["total_required_fill_lb"]) == pytest.approx(106.50, abs=0.01)
    assert float(refreshed["total_expected_movement_lb"]) == pytest.approx(110.00, abs=0.01)


def test_required_fill_is_halved_for_a_line_opened_while_the_case_is_restricted(api):
    """A line created after a single out-of-spec case reading has restricted the department carries exactly half the pounds the same facings and forecast would have earned with the cold chain in spec.

    "When the posture is `SALES_RESTRICTED`, the base is rounded half up to two
    decimal places, then halved, then rounded half up to two decimal places
    again."

    Design: Difficulty/combinatorial_formula/required_fill_nested_min_max_with_posture_branch
    """
    ctx = _department_with_two_proposed_items(api)
    plan = create_case_plan(api, ctx["department"]["id"], FIXTURE_DATE)

    # One reading strictly above the 4.4 safe ceiling takes the run counter to 1,
    # which restricts the department without opening a case failure.
    restrict_department(api, ctx["department"]["id"])
    department = read_department(api, ctx["department"]["id"])
    assert department["case_posture"] == "SALES_RESTRICTED"
    assert int(department["consecutive_out_of_spec_readings"]) == 1

    ribeye_line = add_case_plan_line(
        api, plan["id"], ctx["whole_muscle_item"]["id"], 1, 4, 30.0
    )
    ground_line = add_case_plan_line(
        api, plan["id"], ctx["ground_item"]["id"], 2, 5, 40.0
    )

    halved_ribeye = expected_required_fill_lb(
        4, "WHOLE_MUSCLE", 30.0, WHOLE_MUSCLE_SHELF_LIFE_DAYS, "SALES_RESTRICTED"
    )
    halved_ground = expected_required_fill_lb(
        5, "GROUND", 40.0, GROUND_SHELF_LIFE_DAYS, "SALES_RESTRICTED"
    )
    assert halved_ribeye == pytest.approx(17.25, abs=0.01)
    assert halved_ground == pytest.approx(12.00, abs=0.01)

    assert float(ribeye_line["required_fill_lb"]) == pytest.approx(halved_ribeye, abs=0.01)
    assert float(ground_line["required_fill_lb"]) == pytest.approx(halved_ground, abs=0.01)

    # Each haircut is exactly half of the open-case figure for the same inputs.
    assert halved_ribeye == pytest.approx(
        expected_required_fill_lb(4, "WHOLE_MUSCLE", 30.0, WHOLE_MUSCLE_SHELF_LIFE_DAYS) / 2,
        abs=0.01,
    )
    assert halved_ground == pytest.approx(
        expected_required_fill_lb(5, "GROUND", 40.0, GROUND_SHELF_LIFE_DAYS) / 2, abs=0.01
    )

    refreshed = read_case_plan(api, plan["id"])
    assert float(refreshed["total_required_fill_lb"]) == pytest.approx(29.25, abs=0.01)
    assert float(refreshed["total_expected_movement_lb"]) == pytest.approx(70.00, abs=0.01)


def test_an_earlier_line_keeps_its_required_fill_after_the_posture_tightens(api):
    """Required fill is resolved once at line creation, so a case reading that restricts the department afterwards halves only the next line and never rewrites the pounds already booked on the earlier one.

    "A posture change *after* the line exists never retroactively rewrites
    `required_fill_lb`."

    Design: Difficulty/combinatorial_formula/required_fill_nested_min_max_with_posture_branch
    """
    ctx = _department_with_two_proposed_items(api)
    plan = create_case_plan(api, ctx["department"]["id"], FIXTURE_DATE)

    # Two facings against a 10.0 lb forecast: presentation 12.00 wins over the
    # 11.50 demand figure while the cold chain is still in spec.
    open_line = add_case_plan_line(
        api, plan["id"], ctx["whole_muscle_item"]["id"], 1, 2, 10.0
    )
    open_pounds = expected_required_fill_lb(
        2, "WHOLE_MUSCLE", 10.0, WHOLE_MUSCLE_SHELF_LIFE_DAYS
    )
    assert open_pounds == pytest.approx(12.00, abs=0.01)
    assert float(open_line["required_fill_lb"]) == pytest.approx(open_pounds, abs=0.01)

    restrict_department(api, ctx["department"]["id"])
    assert read_department(api, ctx["department"]["id"])["case_posture"] == "SALES_RESTRICTED"

    restricted_line = add_case_plan_line(
        api, plan["id"], ctx["whole_muscle_item"]["id"], 2, 2, 10.0
    )
    restricted_pounds = expected_required_fill_lb(
        2, "WHOLE_MUSCLE", 10.0, WHOLE_MUSCLE_SHELF_LIFE_DAYS, "SALES_RESTRICTED"
    )
    assert restricted_pounds == pytest.approx(6.00, abs=0.01)
    assert float(restricted_line["required_fill_lb"]) == pytest.approx(
        restricted_pounds, abs=0.01
    )

    # The first line, on identical facings and forecast, is untouched.
    reread_open_line = read_case_plan_line(api, open_line["id"])
    assert float(reread_open_line["required_fill_lb"]) == pytest.approx(12.00, abs=0.01)

    refreshed = read_case_plan(api, plan["id"])
    assert float(refreshed["total_required_fill_lb"]) == pytest.approx(18.00, abs=0.01)
    assert float(refreshed["total_expected_movement_lb"]) == pytest.approx(20.00, abs=0.01)


def test_fills_advance_the_plan_fill_dimension_while_it_stays_published(api):
    """Pounds arriving in the case walk the plan from UNFILLED through PARTIAL to FILLED while its publication dimension never budges from PUBLISHED.

    "Its `fill_status` (`UNFILLED`, `PARTIAL`, `FILLED`) is the execution
    dimension, derived purely from `total_actual_fill_lb` against
    `total_required_fill_lb`."

    Design: Difficulty/non_linear_state_machine/case_plan_publication_and_fill_dimensions_advance_independently
    """
    ctx = _department_with_two_proposed_items(api)
    plan = create_case_plan(api, ctx["department"]["id"], FIXTURE_DATE)
    ribeye_line = add_case_plan_line(
        api, plan["id"], ctx["whole_muscle_item"]["id"], 1, 4, 30.0
    )
    ground_line = add_case_plan_line(
        api, plan["id"], ctx["ground_item"]["id"], 2, 5, 40.0
    )
    published = publish_case_plan(api, plan["id"])

    total_required = expected_required_fill_lb(
        4, "WHOLE_MUSCLE", 30.0, WHOLE_MUSCLE_SHELF_LIFE_DAYS
    ) + expected_required_fill_lb(5, "GROUND", 40.0, GROUND_SHELF_LIFE_DAYS)
    assert total_required == pytest.approx(58.50, abs=0.01)
    assert published["plan_status"] == "PUBLISHED"
    assert published["fill_status"] == "UNFILLED"
    assert float(published["total_required_fill_lb"]) == pytest.approx(
        total_required, abs=0.01
    )
    assert float(published["total_actual_fill_lb"]) == pytest.approx(0.00, abs=0.01)

    fill_line(api, ribeye_line["id"], 34.0)
    after_first = read_case_plan(api, plan["id"])
    assert float(after_first["total_actual_fill_lb"]) == pytest.approx(34.00, abs=0.01)
    assert after_first["fill_status"] == "PARTIAL"
    assert after_first["plan_status"] == "PUBLISHED"

    fill_line(api, ground_line["id"], 24.5)
    after_second = read_case_plan(api, plan["id"])
    assert float(after_second["total_actual_fill_lb"]) == pytest.approx(58.50, abs=0.01)
    assert after_second["fill_status"] == "FILLED"
    assert after_second["plan_status"] == "PUBLISHED"

    # Each first fill dated its own line off the item's merchandising class.
    assert read_case_plan_line(api, ribeye_line["id"])["sell_by_date"] == "2026-08-10"
    assert read_case_plan_line(api, ground_line["id"])["sell_by_date"] == "2026-08-07"


def test_a_suspend_and_resume_round_trip_leaves_the_fill_dimension_at_filled(api):
    """A manager suspending and then resuming a filled plan moves only the publication dimension: the lines are held and released while the plan stays FILLED and every pound in the case remains accounted for.

    "Neither dimension constrains the other: suspending a published plan holds
    its lines but leaves `fill_status` exactly where it was, and a plan reaching
    `FILLED` says nothing about whether it has been closed."

    Design: Difficulty/non_linear_state_machine/case_plan_publication_and_fill_dimensions_advance_independently
    """
    ctx = _department_with_two_proposed_items(api)
    plan = create_case_plan(api, ctx["department"]["id"], FIXTURE_DATE)
    ribeye_line = add_case_plan_line(
        api, plan["id"], ctx["whole_muscle_item"]["id"], 1, 4, 30.0
    )
    ground_line = add_case_plan_line(
        api, plan["id"], ctx["ground_item"]["id"], 2, 5, 40.0
    )
    publish_case_plan(api, plan["id"])
    fill_line(api, ribeye_line["id"], 34.0)
    fill_line(api, ground_line["id"], 24.5)

    filled_plan = read_case_plan(api, plan["id"])
    assert filled_plan["fill_status"] == "FILLED"
    assert filled_plan["plan_status"] == "PUBLISHED"

    suspended = suspend_case_plan(api, plan["id"])
    assert suspended["plan_status"] == "SUSPENDED"
    assert suspended["fill_status"] == "FILLED"
    assert float(suspended["total_actual_fill_lb"]) == pytest.approx(58.50, abs=0.01)

    held_ribeye = read_case_plan_line(api, ribeye_line["id"])
    held_ground = read_case_plan_line(api, ground_line["id"])
    assert held_ribeye["line_status"] == "HELD"
    assert held_ribeye["held_from_status"] == "FILLED"
    assert held_ground["line_status"] == "HELD"
    assert held_ground["held_from_status"] == "FILLED"
    assert float(held_ribeye["actual_fill_lb"]) == pytest.approx(34.00, abs=0.01)
    assert float(held_ground["actual_fill_lb"]) == pytest.approx(24.50, abs=0.01)

    resumed = resume_case_plan(api, plan["id"])
    assert resumed["plan_status"] == "PUBLISHED"
    assert resumed["fill_status"] == "FILLED"
    assert float(resumed["total_actual_fill_lb"]) == pytest.approx(58.50, abs=0.01)

    released_ribeye = read_case_plan_line(api, ribeye_line["id"])
    released_ground = read_case_plan_line(api, ground_line["id"])
    assert released_ribeye["line_status"] == "FILLED"
    assert released_ground["line_status"] == "FILLED"
    assert float(released_ribeye["actual_fill_lb"]) == pytest.approx(34.00, abs=0.01)
    assert float(released_ground["actual_fill_lb"]) == pytest.approx(24.50, abs=0.01)


def test_publishing_a_plan_with_no_lines_is_refused(api):
    """A service-day plan carrying no merchandised lines cannot be published, and the refusal leaves the plan in DRAFT with both roll-up totals still at zero.

    "Publishing a plan takes it `DRAFT → PUBLISHED`, requires at least one line,
    requires that the department's posture not be `SALES_HALTED`, and requires
    that every line's retail item sit in `PROPOSED` or `PRICED`."

    Design: Corner/state_machines/case_plan_publish_without_lines_is_rejected
    """
    department = seeded_department(api)
    plan = create_case_plan(api, department["id"], FIXTURE_DATE)

    response = api.transition_case_plan(plan["id"], transition_payload("PUBLISH"), MANAGER)
    validate_error(response, "ERR_INVALID_STATE_TRANSITION", 409)

    unchanged = read_case_plan(api, plan["id"])
    assert unchanged["plan_status"] == "DRAFT"
    assert unchanged["fill_status"] == "UNFILLED"
    assert float(unchanged["total_required_fill_lb"]) == pytest.approx(0.00, abs=0.01)
    assert float(unchanged["total_expected_movement_lb"]) == pytest.approx(0.00, abs=0.01)
    assert float(unchanged["total_actual_fill_lb"]) == pytest.approx(0.00, abs=0.01)
    assert not unchanged.get("published_by_user_id")


def test_publishing_a_plan_whose_item_has_been_suspended_is_refused(api):
    """The publish gate re-reads every line's retail item at transition time, so a line laid in while the ribeye was still proposed becomes unpublishable once a manager suspends that item.

    "The referenced retail item's `price_status` is one of `PROPOSED`, `PRICED`
    or `REPRICE_REQUIRED` — otherwise `ERR_ITEM_NOT_PRICED` (409)."

    Design: Corner/state_machines/case_plan_publish_blocked_by_suspended_item_price_status
    """
    ctx = received_primal(api)
    item = propose_price(api, ctx["whole_muscle_item"]["id"], ctx["purchase"]["id"])
    plan = create_case_plan(api, ctx["department"]["id"], FIXTURE_DATE)
    line = add_case_plan_line(api, plan["id"], item["id"], 1, 4, 30.0)

    suspend_retail_item(api, item["id"])
    assert read_retail_item(api, item["id"])["price_status"] == "SUSPENDED"

    response = api.transition_case_plan(plan["id"], transition_payload("PUBLISH"), MANAGER)
    validate_error(response, "ERR_ITEM_NOT_PRICED", 409)

    unchanged_plan = read_case_plan(api, plan["id"])
    assert unchanged_plan["plan_status"] == "DRAFT"
    assert not unchanged_plan.get("published_by_user_id")

    unchanged_line = read_case_plan_line(api, line["id"])
    assert unchanged_line["line_status"] == "PLANNED"
    assert float(unchanged_line["required_fill_lb"]) == pytest.approx(
        expected_required_fill_lb(4, "WHOLE_MUSCLE", 30.0, WHOLE_MUSCLE_SHELF_LIFE_DAYS),
        abs=0.01,
    )
    assert float(unchanged_line["required_fill_lb"]) == pytest.approx(34.50, abs=0.01)


def test_closing_a_plan_with_a_planned_line_is_refused_until_that_line_is_filled(api):
    """A plan whose second line has never seen a pound cannot be closed, and the close succeeds only after that line is filled too.

    "Closing a plan takes it `PUBLISHED → CLOSED` and requires that no line
    still sit in `line_status` `PLANNED`; an unfilled line blocks the close with
    `ERR_CASE_PLAN_HAS_UNFILLED_LINES`."

    Design: Corner/state_machines/case_plan_close_with_a_planned_line_is_rejected
    """
    ctx = received_primal(api)
    item = propose_price(api, ctx["whole_muscle_item"]["id"], ctx["purchase"]["id"])
    plan = create_case_plan(api, ctx["department"]["id"], FIXTURE_DATE)
    big_line = add_case_plan_line(api, plan["id"], item["id"], 1, 4, 30.0)
    small_line = add_case_plan_line(api, plan["id"], item["id"], 2, 2, 10.0)
    publish_case_plan(api, plan["id"])
    fill_line(api, big_line["id"], 34.0)

    idle_line = read_case_plan_line(api, small_line["id"])
    assert idle_line["line_status"] == "PLANNED"
    assert float(idle_line["required_fill_lb"]) == pytest.approx(
        expected_required_fill_lb(2, "WHOLE_MUSCLE", 10.0, WHOLE_MUSCLE_SHELF_LIFE_DAYS),
        abs=0.01,
    )
    assert float(idle_line["required_fill_lb"]) == pytest.approx(12.00, abs=0.01)

    refused = api.transition_case_plan(plan["id"], transition_payload("CLOSE"), MANAGER)
    validate_error(refused, "ERR_CASE_PLAN_HAS_UNFILLED_LINES", 422)
    assert read_case_plan(api, plan["id"])["plan_status"] == "PUBLISHED"

    # 15.00 lb is exactly the quarter-over ceiling on a 12.00 lb requirement.
    fill_line(api, small_line["id"], 15.0)
    now_filled = read_case_plan_line(api, small_line["id"])
    assert now_filled["line_status"] == "FILLED"
    assert float(now_filled["actual_fill_lb"]) == pytest.approx(15.00, abs=0.01)

    closed = close_case_plan(api, plan["id"])
    assert closed["plan_status"] == "CLOSED"
    assert float(closed["total_required_fill_lb"]) == pytest.approx(46.50, abs=0.01)
    assert float(closed["total_actual_fill_lb"]) == pytest.approx(49.00, abs=0.01)
    assert closed["fill_status"] == "FILLED"


def test_the_publish_transition_answers_with_the_plan_itself(api):
    """The publish transition answers 200 with the case plan it just wrote — stamped operator, bumped counter and refreshed roll-ups — while the lines it governs stay PLANNED because publication fills nothing.

    "It stamps `published_by_user_id`, recomputes `total_expected_movement_lb`
    and `total_required_fill_lb`, and leaves `fill_status` alone on its own
    dimension — a freshly published plan is still `UNFILLED` until pounds
    arrive."

    Design: Corner/endpoints/case_plan_publish_action_endpoint_returns_the_mutated_aggregate
    """
    ctx = received_primal(api)
    item = propose_price(api, ctx["whole_muscle_item"]["id"], ctx["purchase"]["id"])
    plan = create_case_plan(api, ctx["department"]["id"], "2026-08-06")
    created_version = int(plan["version"])
    big_line = add_case_plan_line(api, plan["id"], item["id"], 1, 4, 30.0)
    small_line = add_case_plan_line(api, plan["id"], item["id"], 2, 2, 10.0)

    published = get_success_data(
        api.transition_case_plan(plan["id"], transition_payload("PUBLISH"), MANAGER), 200
    )

    assert published["id"] == plan["id"]
    assert published["plan_status"] == "PUBLISHED"
    assert published["fill_status"] == "UNFILLED"
    assert published["published_by_user_id"] == MANAGER["X-User-ID"]
    assert float(published["total_expected_movement_lb"]) == pytest.approx(40.00, abs=0.01)
    assert float(published["total_required_fill_lb"]) == pytest.approx(46.50, abs=0.01)
    assert float(published["total_actual_fill_lb"]) == pytest.approx(0.00, abs=0.01)
    assert int(published["price_stale_line_count"]) == 0
    assert created_version == 1
    assert int(published["version"]) > created_version

    for line, facings, movement, pounds in (
        (big_line, 4, 30.0, 34.50),
        (small_line, 2, 10.0, 12.00),
    ):
        reread = read_case_plan_line(api, line["id"], CUTTER)
        assert reread["line_status"] == "PLANNED"
        assert float(reread["required_fill_lb"]) == pytest.approx(
            expected_required_fill_lb(
                facings, "WHOLE_MUSCLE", movement, WHOLE_MUSCLE_SHELF_LIFE_DAYS
            ),
            abs=0.01,
        )
        assert float(reread["required_fill_lb"]) == pytest.approx(pounds, abs=0.01)


def test_plan_roll_ups_are_rederived_after_every_line_and_fill(api):
    """The plan's three roll-up totals are re-derived from the lines it actually holds at every event, so a two-facing line raises the required total by its own 12.00 lb rather than by the first line's 34.50.

    "Every new line refreshes the plan's `total_expected_movement_lb` and
    `total_required_fill_lb` as the sums of its lines' `expected_movement_lb`
    and `required_fill_lb`."

    Design: Corner/cross_cutting_complexity_layers/case_plan_roll_ups_reconcile_after_every_line_event
    """
    ctx = received_primal(api)
    item = propose_price(api, ctx["whole_muscle_item"]["id"], ctx["purchase"]["id"])
    plan = create_case_plan(api, ctx["department"]["id"], FIXTURE_DATE)

    assert float(plan["total_expected_movement_lb"]) == pytest.approx(0.00, abs=0.01)
    assert float(plan["total_required_fill_lb"]) == pytest.approx(0.00, abs=0.01)
    assert float(plan["total_actual_fill_lb"]) == pytest.approx(0.00, abs=0.01)

    big_line = add_case_plan_line(api, plan["id"], item["id"], 1, 4, 30.0)
    after_first_line = read_case_plan(api, plan["id"])
    assert float(after_first_line["total_expected_movement_lb"]) == pytest.approx(
        30.00, abs=0.01
    )
    assert float(after_first_line["total_required_fill_lb"]) == pytest.approx(34.50, abs=0.01)

    small_line = add_case_plan_line(api, plan["id"], item["id"], 2, 2, 10.0)
    after_second_line = read_case_plan(api, plan["id"])
    assert float(after_second_line["total_expected_movement_lb"]) == pytest.approx(
        40.00, abs=0.01
    )
    assert float(after_second_line["total_required_fill_lb"]) == pytest.approx(
        46.50, abs=0.01
    )
    # The increment is the second line's own capped requirement, not the first's.
    assert float(after_second_line["total_required_fill_lb"]) - float(
        after_first_line["total_required_fill_lb"]
    ) == pytest.approx(12.00, abs=0.01)

    publish_case_plan(api, plan["id"])

    fill_line(api, big_line["id"], 34.5)
    after_first_fill = read_case_plan(api, plan["id"])
    assert float(after_first_fill["total_actual_fill_lb"]) == pytest.approx(34.50, abs=0.01)
    assert after_first_fill["fill_status"] == "PARTIAL"

    fill_line(api, small_line["id"], 12.0)
    after_second_fill = read_case_plan(api, plan["id"])
    assert float(after_second_fill["total_actual_fill_lb"]) == pytest.approx(46.50, abs=0.01)
    assert after_second_fill["fill_status"] == "FILLED"
    assert float(after_second_fill["total_actual_fill_lb"]) == pytest.approx(
        float(after_second_fill["total_required_fill_lb"]), abs=0.01
    )
