"""Interpreter assignment constraints: half-open overlap, fatigue runs,
per-window capacity with its pinned evaluation order, and pay rounding."""
from test_helpers import (
    ApiErrorId,
    add_interpreter,
    assert_interpreter_request,
    book_slot,
    get_success_data,
    interpreter_headers,
    request_for_booking,
    scenario_capacity,
    scenario_fatigue,
    scenario_overlap,
    scenario_pay_rounding,
    setup_family_with_students,
    setup_window_at_stage,
    validate_error,
    validate_success,
)


def test_adjacent_assignments_do_not_overlap(api, front_office_headers):
    """PRD 3.7: "The candidate must not collide with the interpreter's other
    work: its half-open interval — start instant included, end instant excluded
    — must not intersect the interval of any other `ASSIGNED` or `CONFIRMED`
    assignment of that interpreter, with back-to-back assignments where one
    starts exactly when the other ends explicitly allowed; a collision is
    rejected with `ERR_INTERPRETER_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/interpreter_half_open_adjacency_allowed_overlap_rejected
    """
    ctx = scenario_overlap()
    # r2's slot [15:20-15:40) begins exactly when r1's [15:00-15:20) ends.
    assigned = validate_success(api.assign_interpreter(
        ctx["r2"]["id"], {"interpreter_id": ctx["interpreter"]["id"]}, front_office_headers
    ))
    assert_interpreter_request(assigned)
    assert assigned["status"] == "ASSIGNED"
    assert assigned["interpreter_id"] == ctx["interpreter"]["id"]


def test_identical_interval_assignment_overlaps(api, front_office_headers):
    """PRD 3.7: "The candidate must not collide with the interpreter's other
    work: its half-open interval — start instant included, end instant excluded
    — must not intersect the interval of any other `ASSIGNED` or `CONFIRMED`
    assignment of that interpreter, with back-to-back assignments where one
    starts exactly when the other ends explicitly allowed; a collision is
    rejected with `ERR_INTERPRETER_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/interpreter_half_open_adjacency_allowed_overlap_rejected
    """
    ctx = scenario_overlap()
    # r3's slot [15:00-15:20) is the identical interval to r1's assignment.
    rejected = api.assign_interpreter(
        ctx["r3"]["id"], {"interpreter_id": ctx["interpreter"]["id"]}, front_office_headers
    )
    validate_error(rejected, ApiErrorId.ERR_INTERPRETER_OVERLAP, 409)

    request = validate_success(api.get_interpreter_request(ctx["r3"]["id"], front_office_headers))
    assert request["status"] == "REQUESTED"


def test_fatigue_error_wins_over_capacity(api, front_office_headers):
    """PRD 2.7: "When several checks could reject the same request, the server
    evaluates them in a fixed order so that the surfaced error is
    deterministic:"
    PRD 2.7: "9. **Interpreter fatigue.** The longest zero-gap run of
    assignments including the candidate must not exceed the interpreter's
    `max_consecutive_minutes`; failures yield `ERR_INTERPRETER_FATIGUE` (422)."
    PRD 2.7: "13. **Capacity.** Teacher daily caps (`ERR_TEACHER_DAY_FULL`),
    the family window cap (`ERR_FAMILY_LIMIT_REACHED`), interpreter per-window
    capacity (`ERR_INTERPRETER_CAPACITY_EXCEEDED`), and the auto-assign
    empty-pool rejection (`ERR_NO_ELIGIBLE_INTERPRETER`)."

    Design: Difficulty/priority_pair_validation_conflict/interpreter_fatigue_safety_beats_capacity
    """
    ctx = scenario_fatigue()
    # The candidate [15:20-15:40) forms a zero-gap run of 40 > 30 minutes AND
    # would also exceed capacity (20 + 20 > 30 - 0); fatigue is reported.
    rejected = api.assign_interpreter(
        ctx["r2"]["id"], {"interpreter_id": ctx["interpreter"]["id"]}, front_office_headers
    )
    validate_error(rejected, ApiErrorId.ERR_INTERPRETER_FATIGUE, 422)

    request = validate_success(api.get_interpreter_request(ctx["r2"]["id"], front_office_headers))
    assert request["status"] == "REQUESTED"
    assert request["interpreter_id"] is None


def test_fatigue_rejection_is_specific_to_the_loaded_interpreter(api, front_office_headers):
    """PRD 3.7: "Fatigue is also enforced: take every `ASSIGNED` or `CONFIRMED`
    assignment of the interpreter across all windows that are not `ARCHIVED`,
    add the candidate, sort the intervals by start ascending with ties broken
    by `created_at` ascending, and merge them into runs wherever the next
    interval begins exactly when the previous one ends — zero gap. The length
    of a run is the sum of its minutes, and the assignment is allowed only when
    the longest resulting run does not exceed `max_consecutive_minutes`;
    otherwise the rejection is `ERR_INTERPRETER_FATIGUE`."

    Design: Difficulty/priority_pair_validation_conflict/interpreter_fatigue_safety_beats_capacity
    """
    ctx = scenario_fatigue()
    rejected = api.assign_interpreter(
        ctx["r2"]["id"], {"interpreter_id": ctx["interpreter"]["id"]}, front_office_headers
    )
    validate_error(rejected, ApiErrorId.ERR_INTERPRETER_FATIGUE, 422)

    # A fresh interpreter with no run history accepts the same request.
    fresh = add_interpreter(full_name="I Two", max_consecutive_minutes=30,
                            base_minutes_per_window=30)
    assigned = validate_success(api.assign_interpreter(
        ctx["r2"]["id"], {"interpreter_id": fresh["id"]}, front_office_headers
    ))
    assert assigned["status"] == "ASSIGNED"
    assert assigned["interpreter_id"] == fresh["id"]


def test_capacity_fifth_assignment_rejected(api, front_office_headers):
    """PRD 3.7: "Finally comes per-window capacity, evaluated in a pinned
    order: first the interpreter's committed minutes in this window — the sum
    of `assigned_minutes` over their `ASSIGNED` and `CONFIRMED` requests here;
    then a break allowance of ten minutes for each full block of forty-five
    committed minutes, ignoring any remainder; then the capacity itself,
    `base_minutes_per_window` minus the allowance, floored at zero; then
    headroom, the capacity minus the committed minutes. The assignment is
    allowed only when the committed minutes plus the new `assigned_minutes` do
    not exceed the capacity, otherwise `ERR_INTERPRETER_CAPACITY_EXCEEDED`.
    Because the allowance depends on the committed minutes, this evaluation
    order must not be reversed."

    Design: Difficulty/combinatorial_formula/interpreter_capacity_circular_evaluation_order
    """
    ctx = scenario_capacity()
    # Committed 80, allowance 10, capacity 90: 80 + 20 exceeds 90.
    rejected = api.assign_interpreter(
        ctx["requests"][4]["id"], {"interpreter_id": ctx["interpreter"]["id"]},
        front_office_headers,
    )
    validate_error(rejected, ApiErrorId.ERR_INTERPRETER_CAPACITY_EXCEEDED, 422)

    request = validate_success(
        api.get_interpreter_request(ctx["requests"][4]["id"], front_office_headers))
    assert request["status"] == "REQUESTED"


def test_capacity_summary_exposes_pinned_arithmetic(api, front_office_headers):
    """PRD 3.9: "An interpreter's summary, also keyed by a required
    `window_id`, exposes the capacity arithmetic of §3.7 directly:
    `committed_minutes_in_window`, the `break_allowance_minutes`, the resulting
    `capacity_minutes`, and the remaining `headroom_minutes`, alongside
    `confirmed_assignments` — the count of the interpreter's `CONFIRMED`
    requests in the window — and the `pay_estimate_cents` computed by the
    per-assignment rounding rule, with the `interpreter_id` and `window_id`
    echoed."

    Design: Difficulty/combinatorial_formula/interpreter_capacity_circular_evaluation_order
    """
    ctx = scenario_capacity()
    summary = validate_success(api.get_interpreter_summary(
        ctx["interpreter"]["id"], front_office_headers,
        params={"window_id": ctx["window"]["id"]},
    ))
    assert summary["committed_minutes_in_window"] == 80
    assert summary["break_allowance_minutes"] == 10
    assert summary["capacity_minutes"] == 90
    assert summary["headroom_minutes"] == 10


def test_pay_rounds_per_assignment_then_sums(api, front_office_headers):
    """PRD 3.7: "For each of the interpreter's `CONFIRMED` requests in the
    window, the billable units are the request's `assigned_minutes` divided by
    fifteen and rounded up to a whole number of units; the pay for that
    assignment is the units times fifteen minutes times the interpreter's
    `hourly_rate_cents` divided by sixty, rounded half-up to a whole number of
    cents. The estimate `pay_estimate_cents` is the integer sum of those
    per-assignment amounts. The rounding order is pinned — round each
    assignment first, then sum; totalling minutes first and rounding once would
    yield a different total and is not used."

    Design: Difficulty/combinatorial_formula/interpreter_pay_per_assignment_rounding_order
    """
    ctx = scenario_pay_rounding()
    summary = validate_success(api.get_interpreter_summary(
        ctx["interpreter"]["id"], front_office_headers,
        params={"window_id": ctx["window"]["id"]},
    ))
    assert summary["confirmed_assignments"] == 2
    assert summary["committed_minutes_in_window"] == 40
    # 2 * round_half_up(ceil(20/15) * 15 * 6000 / 60) = 2 * 3000 = 6000.
    # The forbidden sum-then-round order would give 4500.
    assert summary["pay_estimate_cents"] == 6000


def test_pay_single_assignment_unit_rounding(api, front_office_headers):
    """PRD 3.7: "For each of the interpreter's `CONFIRMED` requests in the
    window, the billable units are the request's `assigned_minutes` divided by
    fifteen and rounded up to a whole number of units; the pay for that
    assignment is the units times fifteen minutes times the interpreter's
    `hourly_rate_cents` divided by sixty, rounded half-up to a whole number of
    cents."

    Design: Difficulty/combinatorial_formula/interpreter_pay_per_assignment_rounding_order
    """
    ctx = setup_window_at_stage("BOOKING_OPEN")
    interpreter = add_interpreter()
    party = setup_family_with_students(
        ctx, 1, family_overrides={"preferred_language": "es"}
    )
    slot = ctx["teacher_slots"][ctx["teachers"][0]["id"]][0]
    booking = book_slot(slot["id"], party["students"][0]["id"], party["guardian"],
                        interpreter_language="es")
    request = request_for_booking(booking["id"])
    assert request["assigned_minutes"] == 20
    get_success_data(api.assign_interpreter(
        request["id"], {"interpreter_id": interpreter["id"]}, front_office_headers))
    get_success_data(api.accept_request(request["id"], interpreter_headers(interpreter)))

    summary = validate_success(api.get_interpreter_summary(
        interpreter["id"], front_office_headers,
        params={"window_id": ctx["window"]["id"]},
    ))
    assert summary["confirmed_assignments"] == 1
    # ceil(20/15) = 2 units -> 2 * 15 * 6000 / 60 = 3000 cents.
    assert summary["pay_estimate_cents"] == 3000


def test_interpreter_pay_45min_assignment_rounding(api, front_office_headers):
    """PRD 3.7: "For each of the interpreter's `CONFIRMED` requests in the
    window, the billable units are the request's `assigned_minutes` divided by
    fifteen and rounded up to a whole number of units; the pay for that
    assignment is the units times fifteen minutes times the interpreter's
    `hourly_rate_cents` divided by sixty, rounded half-up to a whole number of
    cents. The estimate `pay_estimate_cents` is the integer sum of those
    per-assignment amounts."
    PRD 3.9: "An interpreter's summary, also keyed by a required `window_id`,
    exposes the capacity arithmetic of §3.7 directly:
    `committed_minutes_in_window`, the `break_allowance_minutes`, the resulting
    `capacity_minutes`, and the remaining `headroom_minutes`, alongside
    `confirmed_assignments` — the count of the interpreter's `CONFIRMED`
    requests in the window — and the `pay_estimate_cents` computed by the
    per-assignment rounding rule, with the `interpreter_id` and `window_id`
    echoed."

    Design: Corner/calculations/interpreter_pay_45min_assignment_rounding
    """
    ctx = setup_window_at_stage(
        "BOOKING_OPEN",
        window_overrides={
            "name": "Long",
            "format": "SECONDARY",
            "slot_length_minutes": 45,
            "buffer_minutes": 0,
            "day_windows": [{
                "date": "2026-10-05",
                "start_at": "2026-10-05T15:00:00Z",
                "end_at": "2026-10-05T18:00:00Z",
            }],
        },
        teacher_specs=[{"grade_band": "SECONDARY", "subjects": ["math"]}],
    )
    interpreter = add_interpreter()
    party = setup_family_with_students(
        ctx, 1, family_overrides={"preferred_language": "es"}, grade_levels=[9]
    )
    slot = ctx["teacher_slots"][ctx["teachers"][0]["id"]][0]
    booking = book_slot(slot["id"], party["students"][0]["id"], party["guardian"],
                        interpreter_language="es")
    request = request_for_booking(booking["id"])
    assert request["assigned_minutes"] == 45
    get_success_data(api.assign_interpreter(
        request["id"], {"interpreter_id": interpreter["id"]}, front_office_headers))
    get_success_data(api.accept_request(request["id"], interpreter_headers(interpreter)))

    summary = validate_success(api.get_interpreter_summary(
        interpreter["id"], front_office_headers,
        params={"window_id": ctx["window"]["id"]},
    ))
    assert summary["confirmed_assignments"] == 1
    # ceil(45/15) = 3 units -> 3 * 15 * 6000 / 60 = 4500 cents.
    assert summary["pay_estimate_cents"] == 4500
    assert summary["committed_minutes_in_window"] == 45
    assert summary["break_allowance_minutes"] == 10
    assert summary["capacity_minutes"] == 590
