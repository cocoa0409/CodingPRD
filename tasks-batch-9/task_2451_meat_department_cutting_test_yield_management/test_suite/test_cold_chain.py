"""Cold-chain compliance: the reading stream, the department's posture, and the
halt cascade that reaches published plans, filled case lines and staged orders
(PRD §2.7, §3.7).
"""

import pytest

from test_helpers import (
    CLERK,
    CUTTER,
    DEPARTMENT_DEFAULTS,
    MANAGER,
    MEAT_CUTTER_USER_ID,
    add_case_plan_line,
    assert_posture,
    case_plan_line_payload,
    confirm_pre_order,
    contain_case_failure,
    create_case_plan,
    create_pre_order,
    create_primal_purchase,
    create_retail_item,
    escalate_case_failure,
    expected_deposit_cents,
    expected_required_fill_lb,
    fill_line,
    halt_department,
    only_case_failure,
    post_reading,
    propose_price,
    publish_case_plan,
    published_plan,
    read_case_plan,
    read_case_plan_line,
    read_department,
    read_pre_order,
    seeded_department,
    set_clock,
    stage_pre_order,
    transition_payload,
    validate_error,
    validate_paginated,
)

WHOLE_MUSCLE_SHELF_LIFE = DEPARTMENT_DEFAULTS["shelf_life_days_whole_muscle"]


def test_a_reading_at_the_safe_ceiling_is_in_spec_and_resets_the_run(api):
    """A 4.4 C reading sits exactly on the safe ceiling and is in spec, 4.5 C is out of spec and restricts the case, and a return to 4.4 C resets the run.

    "A reading is out of spec when `reading_c` is **strictly above** the
    department's `max_safe_case_temp_c`; a reading exactly at the safe ceiling is
    in spec."

    Design: Difficulty/boundary_precision_check/temperature_out_of_spec_strict_greater_boundary_and_consecutive_threshold
    """
    department = seeded_department(api)
    department_id = department["id"]
    assert float(department["max_safe_case_temp_c"]) == pytest.approx(4.4, abs=0.01)

    on_the_ceiling = post_reading(api, department_id, "CASE-A", 4.4)
    assert on_the_ceiling["out_of_spec"] is False
    assert on_the_ceiling["consecutive_index"] == 0

    after_ceiling = read_department(api, department_id)
    assert_posture(after_ceiling, "SALES_OPEN", "4.4 C is not above the safe ceiling")
    assert after_ceiling["consecutive_out_of_spec_readings"] == 0

    one_tenth_above = post_reading(api, department_id, "CASE-A", 4.5)
    assert one_tenth_above["out_of_spec"] is True
    assert one_tenth_above["consecutive_index"] == 1

    after_excursion = read_department(api, department_id)
    assert_posture(after_excursion, "SALES_RESTRICTED", "one out-of-spec reading")
    assert after_excursion["consecutive_out_of_spec_readings"] == 1
    assert after_excursion["open_case_failure_count"] == 0
    assert after_excursion["contained_case_failure_count"] == 0

    back_in_spec = post_reading(api, department_id, "CASE-A", 4.4)
    assert back_in_spec["out_of_spec"] is False
    assert back_in_spec["consecutive_index"] == 0

    after_reset = read_department(api, department_id)
    assert_posture(after_reset, "SALES_OPEN", "an in-spec reading resets the run")
    assert after_reset["consecutive_out_of_spec_readings"] == 0

    _rows, meta = validate_paginated(
        api.list_case_failures(MANAGER, {"department_id": department_id})
    )
    assert meta["total_count"] == 0, "a single excursion is not a case failure"


def test_the_second_consecutive_out_of_spec_reading_opens_the_failure(api):
    """One out-of-spec reading only restricts the case, while the second consecutive one carries run index 2 and opens the case failure that halts the department.

    "A new case failure opens on either of two triggers: a single reading at or
    above the department's `critical_case_temp_c` — a spike, evaluated
    inclusively — or the second consecutive out-of-spec reading, meaning
    `consecutive_out_of_spec_readings` has reached 2."

    Design: Difficulty/boundary_precision_check/temperature_out_of_spec_strict_greater_boundary_and_consecutive_threshold
    """
    department = seeded_department(api)
    department_id = department["id"]

    first = post_reading(api, department_id, "CASE-A", 4.5)
    assert first["out_of_spec"] is True
    assert first["consecutive_index"] == 1

    midway = read_department(api, department_id)
    assert_posture(midway, "SALES_RESTRICTED", "the first excursion is below the threshold")
    assert midway["open_case_failure_count"] == 0

    second = post_reading(api, department_id, "CASE-A", 4.6)
    assert second["out_of_spec"] is True
    assert second["consecutive_index"] == 2

    failure = only_case_failure(api)
    assert failure["status"] == "OPEN"
    assert failure["trigger_temperature_log_id"] == second["id"]
    assert failure["case_code"] == "CASE-A"
    assert float(failure["peak_reading_c"]) == pytest.approx(4.6, abs=0.01)
    assert failure["reopen_count"] == 0
    assert failure["affected_line_count"] == 0
    assert failure["disposition"] == "NONE"
    assert failure["reported_by_user_id"] == MEAT_CUTTER_USER_ID

    halted = read_department(api, department_id)
    assert_posture(halted, "SALES_HALTED", "one open failure halts the whole department")
    assert halted["open_case_failure_count"] == 1
    assert halted["contained_case_failure_count"] == 0
    assert halted["consecutive_out_of_spec_readings"] == 2


def test_a_critical_spike_holds_the_filled_line_and_the_order_staged_on_it(api):
    """A single reading exactly at the critical threshold suspends the service-day plan, holds its filled line and holds the customer order staged against it, while the plan's fill accounting and the deposit stay exactly where they were.

    "The moment a reading drives the posture to `SALES_HALTED`, the halt cascades
    three hops."

    Design: Difficulty/transitive_cascade/critical_temperature_reading_cascade_reaches_staged_pre_order
    """
    ctx = published_plan(api)
    department_id = ctx["department"]["id"]
    plan_id = ctx["plan"]["id"]
    line_id = ctx["line"]["id"]
    fill_line(api, line_id, float(ctx["line"]["required_fill_lb"]))
    order = create_pre_order(
        api,
        department_id,
        ctx["whole_muscle_item"]["id"],
        4.0,
        "2026-08-05T14:00:00Z",
        "2026-08-05T16:00:00Z",
    )
    confirm_pre_order(api, order["id"])
    stage_pre_order(api, order["id"], line_id)
    order_id = order["id"]

    plan_before = read_case_plan(api, plan_id)
    assert plan_before["plan_status"] == "PUBLISHED"
    assert plan_before["fill_status"] == "FILLED"
    assert float(plan_before["total_actual_fill_lb"]) == pytest.approx(34.50, abs=0.01)

    line_before = read_case_plan_line(api, line_id)
    assert line_before["line_status"] == "FILLED"
    assert float(line_before["staged_lb"]) == pytest.approx(4.00, abs=0.01)

    order_before = read_pre_order(api, order_id)
    assert order_before["status"] == "STAGED"
    expected_deposit = expected_deposit_cents(
        int(order_before["quoted_price_per_lb_cents"]),
        4.0,
        DEPARTMENT_DEFAULTS["deposit_rate"],
    )
    assert expected_deposit == 1999
    assert int(order_before["deposit_cents"]) == expected_deposit

    spike = post_reading(api, department_id, "CASE-A", 7.0)
    assert spike["out_of_spec"] is True
    assert spike["consecutive_index"] == 1, "a spike needs no consecutive run"

    failure = only_case_failure(api)
    assert failure["status"] == "OPEN"
    assert failure["trigger_temperature_log_id"] == spike["id"]
    assert float(failure["peak_reading_c"]) == pytest.approx(7.0, abs=0.01)
    assert failure["reopen_count"] == 0
    assert failure["affected_line_count"] == 1

    halted = read_department(api, department_id)
    assert_posture(halted, "SALES_HALTED", "a reading at the critical threshold opens a failure")
    assert halted["open_case_failure_count"] == 1

    plan_after = read_case_plan(api, plan_id)
    assert plan_after["plan_status"] == "SUSPENDED"
    assert plan_after["fill_status"] == "FILLED", "the halt never touches the fill dimension"
    assert float(plan_after["total_actual_fill_lb"]) == pytest.approx(34.50, abs=0.01)

    line_after = read_case_plan_line(api, line_id)
    assert line_after["line_status"] == "HELD"
    assert line_after["held_from_status"] == "FILLED"
    assert float(line_after["actual_fill_lb"]) == pytest.approx(34.50, abs=0.01)
    assert float(line_after["staged_lb"]) == pytest.approx(4.00, abs=0.01)

    order_after = read_pre_order(api, order_id)
    assert order_after["status"] == "HELD"
    assert int(order_after["deposit_cents"]) == expected_deposit
    assert int(order_after["deposit_applied_cents"]) == 0
    assert int(order_after["deposit_refund_cents"]) == 0
    assert int(order_after["deposit_forfeited_cents"]) == 0


def test_the_halt_passes_over_a_plan_whose_service_date_has_gone_by(api):
    """The halt suspends only the published plan whose service date has not passed, so a plan served yesterday keeps its filled line and the failure counts just the one line it held.

    "Every case plan of the department whose `plan_status` is `PUBLISHED` and
    whose `service_date` is not earlier than the logical clock's current date
    moves `PUBLISHED → SUSPENDED`."

    Design: Difficulty/transitive_cascade/critical_temperature_reading_cascade_reaches_staged_pre_order
    """
    ctx = published_plan(api)
    department_id = ctx["department"]["id"]
    item_id = ctx["whole_muscle_item"]["id"]
    today_plan_id = ctx["plan"]["id"]
    today_line_id = ctx["line"]["id"]
    fill_line(api, today_line_id, float(ctx["line"]["required_fill_lb"]))

    yesterday_plan = create_case_plan(api, department_id, "2026-08-04")
    yesterday_line = add_case_plan_line(api, yesterday_plan["id"], item_id, 1, 4, 30.0)
    publish_case_plan(api, yesterday_plan["id"])
    fill_line(api, yesterday_line["id"], 34.50)
    assert read_case_plan_line(api, yesterday_line["id"])["line_status"] == "FILLED"

    spike = post_reading(api, department_id, "CASE-A", 7.5)
    assert spike["out_of_spec"] is True

    halted = read_department(api, department_id)
    assert_posture(halted, "SALES_HALTED", "a spike opens a failure at once")

    today_plan = read_case_plan(api, today_plan_id)
    assert today_plan["plan_status"] == "SUSPENDED"
    assert today_plan["fill_status"] == "FILLED"
    today_line = read_case_plan_line(api, today_line_id)
    assert today_line["line_status"] == "HELD"
    assert today_line["held_from_status"] == "FILLED"

    stale_plan = read_case_plan(api, yesterday_plan["id"])
    assert stale_plan["plan_status"] == "PUBLISHED", "yesterday's service day is out of reach"
    assert stale_plan["fill_status"] == "FILLED"
    stale_line = read_case_plan_line(api, yesterday_line["id"])
    assert stale_line["line_status"] == "FILLED"
    assert not stale_line.get("held_from_status")

    failure = only_case_failure(api)
    assert failure["affected_line_count"] == 1, "only the line inside the suspended plan is held"


def test_escalating_before_four_hours_have_elapsed_is_refused(api):
    """A manager escalating an open case failure at 239 minutes is refused, and the same escalation at exactly four hours after the failure opened is accepted while the department stays halted.

    "A manager may instead escalate an open failure, moving it
    `OPEN → ESCALATED`, but only once the logical clock has reached or passed
    four hours after `opened_at`; escalating earlier is refused with
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/case_failure_escalate_before_window_elapses_is_rejected
    """
    department = seeded_department(api)
    department_id = department["id"]
    halt_department(api, department_id)

    failure = only_case_failure(api)
    assert failure["status"] == "OPEN"
    assert failure["opened_at"][:19] == "2026-08-05T08:00:00"

    set_clock(api, "2026-08-05T11:59:00Z")
    too_early = api.transition_case_failure(
        failure["id"], transition_payload("ESCALATE"), MANAGER
    )
    validate_error(too_early, "ERR_INVALID_STATE_TRANSITION", 409)

    still_open = read_department(api, department_id)
    assert_posture(still_open, "SALES_HALTED", "the refusal changes nothing")
    unchanged = only_case_failure(api)
    assert unchanged["status"] == "OPEN"
    assert not unchanged.get("escalated_at")

    set_clock(api, "2026-08-05T12:00:00Z")
    escalated = escalate_case_failure(api, failure["id"])
    assert escalated["status"] == "ESCALATED"
    assert escalated["escalated_at"][:19] == "2026-08-05T12:00:00"

    after = read_department(api, department_id)
    assert_posture(after, "SALES_HALTED", "an escalated failure still counts as open")
    assert after["open_case_failure_count"] == 1
    assert after["contained_case_failure_count"] == 0


def test_a_reopened_case_failure_re_halts_the_department(api):
    """A contained failure relaxes the department to restricted trading, and a fresh out-of-spec reading on the same case reopens that same failure — lifting its reopen count, refreshing its peak reading and halting the department again.

    "Should another out-of-spec reading land on the same `case_code`, the failure
    reopens as described above, `open_case_failure_count` rises again,
    `contained_case_failure_count` falls, and the department returns to
    `SALES_HALTED`; that `OPEN → CONTAINED → OPEN` loop is unbounded and each
    traversal re-halts the department."

    Design: Corner/state_machines/case_failure_reopen_cycle_rehalts_the_department
    """
    department = seeded_department(api)
    department_id = department["id"]
    halt_department(api, department_id)

    opened = only_case_failure(api)
    contained = contain_case_failure(
        api, opened["id"], "product transferred to the backup case; unit iced down"
    )
    assert contained["status"] == "CONTAINED"
    assert contained["reopen_count"] == 0
    assert float(contained["peak_reading_c"]) == pytest.approx(4.6, abs=0.01)

    relaxed = read_department(api, department_id)
    assert_posture(relaxed, "SALES_RESTRICTED", "no failure is open once it is contained")
    assert relaxed["open_case_failure_count"] == 0
    assert relaxed["contained_case_failure_count"] == 1

    reopening_reading = post_reading(api, department_id, "CASE-A", 5.1)
    assert reopening_reading["out_of_spec"] is True
    assert reopening_reading["consecutive_index"] == 2, "the run counter is capped at two"

    reopened = only_case_failure(api)
    assert reopened["id"] == opened["id"], "the failure is reopened rather than duplicated"
    assert reopened["status"] == "OPEN"
    assert reopened["reopen_count"] == 1
    assert float(reopened["peak_reading_c"]) == pytest.approx(5.1, abs=0.01)

    _rows, meta = validate_paginated(
        api.list_case_failures(MANAGER, {"department_id": department_id})
    )
    assert meta["total_count"] == 1

    re_halted = read_department(api, department_id)
    assert_posture(re_halted, "SALES_HALTED", "the reopened failure halts sales again")
    assert re_halted["open_case_failure_count"] == 1
    assert re_halted["contained_case_failure_count"] == 0


def test_a_halted_department_refuses_a_new_case_line_until_the_failure_is_contained(api):
    """While a failure is open the department refuses a new case-plan line outright, and once the cutter has contained it the very same line is accepted with its required fill halved under restricted trading (PRD §3.6).

    "Creating a line while the department's `case_posture` is `SALES_HALTED` is
    refused with `ERR_POSTURE_SALES_HALTED`."

    Design: Corner/validations/sales_halted_posture_blocks_new_case_lines_until_containment
    """
    department = seeded_department(api)
    department_id = department["id"]
    item = create_retail_item(api, department_id)
    purchase = create_primal_purchase(api, department_id)
    item = propose_price(api, item["id"], purchase["id"])
    assert item["price_status"] == "PROPOSED"

    plan = create_case_plan(api, department_id, "2026-08-06")
    halt_department(api, department_id)

    halted = read_department(api, department_id)
    assert_posture(halted, "SALES_HALTED", "two consecutive excursions opened a failure")
    assert read_case_plan(api, plan["id"])["plan_status"] == "DRAFT"

    refused = api.create_case_plan_line(
        plan["id"], case_plan_line_payload(item["id"], 1, 4, 30.0), MANAGER
    )
    validate_error(refused, "ERR_POSTURE_SALES_HALTED", 409)

    _rows, meta = validate_paginated(
        api.list_case_plan_lines(MANAGER, {"case_plan_id": plan["id"]})
    )
    assert meta["total_count"] == 0, "the refused line was never written"

    failure = only_case_failure(api)
    contain_case_failure(api, failure["id"], "product moved to the backup case")

    restricted = read_department(api, department_id)
    assert_posture(restricted, "SALES_RESTRICTED", "containment relaxes the halt")
    assert restricted["open_case_failure_count"] == 0
    assert restricted["contained_case_failure_count"] == 1

    line = add_case_plan_line(api, plan["id"], item["id"], 1, 4, 30.0)
    expected_fill = expected_required_fill_lb(
        4, "WHOLE_MUSCLE", 30.0, WHOLE_MUSCLE_SHELF_LIFE, "SALES_RESTRICTED"
    )
    assert expected_fill == pytest.approx(17.25, abs=0.01)
    assert float(line["required_fill_lb"]) == pytest.approx(expected_fill, abs=0.01)
    assert line["line_status"] == "PLANNED"

    plan_after = read_case_plan(api, plan["id"])
    assert float(plan_after["total_required_fill_lb"]) == pytest.approx(expected_fill, abs=0.01)


def test_the_department_read_reports_the_posture_its_readings_imply(api):
    """A plain department read returns the posture and failure counters recomputed from the reading stream alone, moving from open to restricted to halted although no client ever wrote to the department.

    "Posture is never set directly by a client; it is recomputed from the
    department's temperature-reading history and its open case-failure counts,
    and it gates merchandising operations across the whole department rather than
    on a single case or item."

    Design: Corner/endpoints/department_read_recomputes_the_posture_from_the_reading_stream
    """
    department = seeded_department(api)
    department_id = department["id"]

    opening = read_department(api, department_id, CLERK)
    assert_posture(opening, "SALES_OPEN", "a department is born trading normally")
    assert opening["open_case_failure_count"] == 0
    assert opening["contained_case_failure_count"] == 0
    assert opening["consecutive_out_of_spec_readings"] == 0

    on_the_ceiling = post_reading(api, department_id, "CASE-A", 4.4, CLERK)
    assert on_the_ceiling["out_of_spec"] is False
    assert on_the_ceiling["taken_at"][:19] == "2026-08-05T08:00:00"

    set_clock(api, "2026-08-05T08:30:00Z")
    first_excursion = post_reading(api, department_id, "CASE-A", 4.5, CUTTER)
    assert first_excursion["out_of_spec"] is True
    assert first_excursion["consecutive_index"] == 1
    assert first_excursion["taken_at"][:19] == "2026-08-05T08:30:00", (
        "the reading is stamped from the logical clock"
    )

    after_one = read_department(api, department_id, CLERK)
    assert_posture(after_one, "SALES_RESTRICTED", "one excursion restricts but opens no failure")
    assert after_one["open_case_failure_count"] == 0
    assert after_one["consecutive_out_of_spec_readings"] == 1

    second_excursion = post_reading(api, department_id, "CASE-A", 4.6, CUTTER)
    assert second_excursion["consecutive_index"] == 2

    after_two = read_department(api, department_id, CLERK)
    assert_posture(after_two, "SALES_HALTED", "the second consecutive excursion opens a failure")
    assert after_two["open_case_failure_count"] == 1
    assert after_two["version"] > opening["version"], (
        "the derived counters moved with no write against the department"
    )

    rows, meta = validate_paginated(
        api.list_department_temperature_logs(
            department_id, CUTTER, {"out_of_spec": "true", "case_code": "CASE-A"}
        )
    )
    assert meta["total_count"] == 2, "the reading on the safe ceiling is in spec"
    assert all(row["out_of_spec"] is True for row in rows)


def test_the_halt_cascade_is_visible_to_the_very_next_request(api):
    """The reading that trips the consecutive threshold reports its own run index, and the failure, the halted posture, the suspended plan and the held line are all already settled in the requests that follow it.

    "Derived fields are reconciled immediately, in the same request that causes
    them to move, and they cascade transitively."

    Design: Corner/consistency_model/a_posture_cascade_is_visible_to_the_next_request
    """
    ctx = published_plan(api)
    department_id = ctx["department"]["id"]
    plan_id = ctx["plan"]["id"]
    line_id = ctx["line"]["id"]
    fill_line(api, line_id, float(ctx["line"]["required_fill_lb"]))
    assert read_case_plan_line(api, line_id)["line_status"] == "FILLED"

    first = post_reading(api, department_id, "CASE-A", 4.5)
    assert first["consecutive_index"] == 1
    assert read_case_plan(api, plan_id)["plan_status"] == "PUBLISHED"

    tripping = post_reading(api, department_id, "CASE-A", 4.6)
    assert tripping["out_of_spec"] is True
    assert tripping["consecutive_index"] == 2

    halted = read_department(api, department_id)
    assert_posture(halted, "SALES_HALTED", "the halt lands in the reading's own request")
    assert halted["open_case_failure_count"] == 1

    plan_after = read_case_plan(api, plan_id)
    assert plan_after["plan_status"] == "SUSPENDED"
    assert plan_after["fill_status"] == "FILLED", "the execution dimension is preserved"

    line_after = read_case_plan_line(api, line_id)
    assert line_after["line_status"] == "HELD"
    assert line_after["held_from_status"] == "FILLED"

    rows, meta = validate_paginated(
        api.list_case_failures(
            MANAGER,
            {"department_id": department_id, "case_code": "CASE-A", "status": "OPEN"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["trigger_temperature_log_id"] == tripping["id"]
    assert float(rows[0]["peak_reading_c"]) == pytest.approx(4.6, abs=0.01)
    assert rows[0]["affected_line_count"] == 1
