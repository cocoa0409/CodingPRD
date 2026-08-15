"""Interpreter requests: creation rules, assignment checks, the auto-selector,
accept/decline ownership, and committed-minutes conservation."""
from test_helpers import (
    ApiErrorId,
    add_interpreter,
    assert_interpreter_request,
    book_slot,
    create_interpreter_request_payload,
    get_success_data,
    interpreter_headers,
    request_for_booking,
    scenario_decline_reassign,
    scenario_inactive_interpreter,
    scenario_round_trip,
    setup_family_with_students,
    setup_window_at_stage,
    validate_error,
    validate_success,
)


def test_language_not_covered_rejected(api, front_office_headers):
    """PRD 3.7: "The interpreter's `languages` must contain the request's
    `language` (otherwise `ERR_LANGUAGE_NOT_COVERED`), and the interpreter must
    support the required channel — `supports_in_person` for an `IN_PERSON`
    request, `supports_virtual` for a `VIRTUAL` one (otherwise
    `ERR_CHANNEL_NOT_ALLOWED`)."

    Design: Corner/validations/language_not_covered_rejected
    """
    ctx = scenario_round_trip()
    french_only = add_interpreter(full_name="I Fr", languages=["fr"])

    response = api.assign_interpreter(
        ctx["request"]["id"], {"interpreter_id": french_only["id"]}, front_office_headers
    )
    validate_error(response, ApiErrorId.ERR_LANGUAGE_NOT_COVERED, 422)

    request = validate_success(
        api.get_interpreter_request(ctx["request"]["id"], front_office_headers))
    assert request["status"] == "REQUESTED"


def test_second_interpreter_request_rejected(api, front_office_headers):
    """PRD 3.7: "Staff may also create one manually by naming a `booking_id`
    and a `language`; the booking must be `CONFIRMED`, and at most one
    non-terminal request may exist per booking — a second live request is
    rejected with `ERR_ALREADY_HAS_INTERPRETER_REQUEST`."

    Design: Corner/validations/second_interpreter_request_rejected
    """
    ctx = scenario_round_trip()
    response = api.create_interpreter_request(
        create_interpreter_request_payload(ctx["booking"]["id"], "es"),
        front_office_headers,
    )
    validate_error(response, ApiErrorId.ERR_ALREADY_HAS_INTERPRETER_REQUEST, 409)


def test_auto_assign_no_eligible_interpreter_rejected(api, front_office_headers):
    """PRD 3.7: "The auto-selector's candidate pool is every `ACTIVE`
    interpreter who covers the language, supports the required channel, and
    does not appear in the request's `declined_interpreter_ids`. Candidates are
    ranked by `committed_minutes` ascending, then `created_at` ascending, then
    the interpreter's `created_seq` — the server-assigned, strictly increasing
    global creation sequence — ascending. The selector walks that ranking and
    offers the assignment to the first candidate who passes the overlap,
    fatigue, and capacity checks; when no candidate passes, the request is
    rejected with `ERR_NO_ELIGIBLE_INTERPRETER`."

    Design: Corner/validations/auto_assign_no_eligible_interpreter_rejected
    """
    # No interpreters exist at all in this scenario.
    ctx = setup_window_at_stage("BOOKING_OPEN")
    party = setup_family_with_students(
        ctx, 1, family_overrides={"preferred_language": "es"}
    )
    slot = ctx["teacher_slots"][ctx["teachers"][0]["id"]][0]
    booking = book_slot(slot["id"], party["students"][0]["id"], party["guardian"],
                        interpreter_language="es")
    request = request_for_booking(booking["id"])

    response = api.assign_interpreter(request["id"], {}, front_office_headers)
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_INTERPRETER, 422)


def test_assign_rejected_while_interpreter_inactive(api, front_office_headers,
                                                    school_admin_headers):
    """PRD 3.7: "The checks run under the §2.7 ordering: the request must be
    `REQUESTED` and its booking still `CONFIRMED` (both otherwise
    `ERR_INVALID_STATE`); the chosen interpreter must be `ACTIVE` (otherwise
    `ERR_INVALID_STATE`)."
    PRD 3.7: "Reactivation from `INACTIVE` to `ACTIVE` has no side effects."

    Design: Difficulty/cross_entity_state_dependency/assign_requires_interpreter_active
    """
    ctx = scenario_inactive_interpreter()
    interpreter = ctx["interpreter"]

    rejected = api.assign_interpreter(
        ctx["request"]["id"], {"interpreter_id": interpreter["id"]}, front_office_headers
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_STATE, 409)

    get_success_data(api.patch_interpreter(interpreter["id"], {"status": "ACTIVE"},
                                           school_admin_headers))
    assigned = validate_success(api.assign_interpreter(
        ctx["request"]["id"], {"interpreter_id": interpreter["id"]}, front_office_headers
    ))
    assert_interpreter_request(assigned)
    assert assigned["status"] == "ASSIGNED"
    assert assigned["interpreter_id"] == interpreter["id"]


def test_auto_assign_skips_inactive_interpreter(api, front_office_headers):
    """PRD 3.7: "The auto-selector's candidate pool is every `ACTIVE`
    interpreter who covers the language, supports the required channel, and
    does not appear in the request's `declined_interpreter_ids`. Candidates are
    ranked by `committed_minutes` ascending, then `created_at` ascending, then
    the interpreter's `created_seq` — the server-assigned, strictly increasing
    global creation sequence — ascending. The selector walks that ranking and
    offers the assignment to the first candidate who passes the overlap,
    fatigue, and capacity checks; when no candidate passes, the request is
    rejected with `ERR_NO_ELIGIBLE_INTERPRETER`."

    Design: Difficulty/cross_entity_state_dependency/assign_requires_interpreter_active
    """
    # The only interpreter covering 'es' is INACTIVE, so the pool is empty.
    ctx = scenario_inactive_interpreter()
    response = api.assign_interpreter(ctx["request"]["id"], {}, front_office_headers)
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_INTERPRETER, 422)


def test_decline_releases_minutes_and_marks_declined(api, front_office_headers):
    """PRD 3.7: "Declining moves the request from `ASSIGNED` back to
    `REQUESTED` under the same ownership rule, optionally carrying a free-text
    `reason`: the interpreter's `id` is appended to `declined_interpreter_ids`
    — which excludes them from future auto-assignment for this request —
    `interpreter_id` is cleared back to null, and the interpreter's
    `committed_minutes` lose the request's `assigned_minutes`."
    PRD 3.7: "Candidates are ranked by `committed_minutes` ascending, then
    `created_at` ascending, then the interpreter's `created_seq` — the
    server-assigned, strictly increasing global creation sequence — ascending."

    Design: Difficulty/non_linear_state_machine/interpreter_request_decline_reassign_cycle
    """
    ctx = scenario_decline_reassign()
    request_id = ctx["request"]["id"]

    # Both interpreters have committed_minutes 0; the earlier-created wins.
    first = validate_success(api.assign_interpreter(request_id, {}, front_office_headers))
    assert first["status"] == "ASSIGNED"
    assert first["interpreter_id"] == ctx["i1"]["id"]

    declined = validate_success(api.decline_request(
        request_id, {"reason": "unavailable"}, interpreter_headers(ctx["i1"])
    ))
    assert declined["status"] == "REQUESTED"
    assert declined["interpreter_id"] is None
    assert ctx["i1"]["id"] in declined["declined_interpreter_ids"]

    interpreter_one = validate_success(api.get_interpreter(ctx["i1"]["id"], front_office_headers))
    assert interpreter_one["committed_minutes"] == 0


def test_second_auto_assign_excludes_declined_interpreter(api, front_office_headers):
    """PRD 3.7: "Declining moves the request from `ASSIGNED` back to
    `REQUESTED` under the same ownership rule, optionally carrying a free-text
    `reason`: the interpreter's `id` is appended to `declined_interpreter_ids`
    — which excludes them from future auto-assignment for this request —
    `interpreter_id` is cleared back to null, and the interpreter's
    `committed_minutes` lose the request's `assigned_minutes`."
    PRD 3.7: "Accepting — `ASSIGNED` to `CONFIRMED` — is permitted only to the
    interpreter whose `id` matches the request's `interpreter_id` (otherwise
    `ERR_FORBIDDEN`) and only from `ASSIGNED` status (otherwise
    `ERR_INVALID_STATE`)."

    Design: Difficulty/non_linear_state_machine/interpreter_request_decline_reassign_cycle
    """
    ctx = scenario_decline_reassign()
    request_id = ctx["request"]["id"]

    get_success_data(api.assign_interpreter(request_id, {}, front_office_headers))
    get_success_data(api.decline_request(
        request_id, {"reason": "unavailable"}, interpreter_headers(ctx["i1"])
    ))

    # The declined interpreter still ranks first on ties, but is excluded.
    second = validate_success(api.assign_interpreter(request_id, {}, front_office_headers))
    assert second["status"] == "ASSIGNED"
    assert second["interpreter_id"] == ctx["i2"]["id"]

    accepted = validate_success(api.accept_request(
        request_id, interpreter_headers(ctx["i2"])
    ))
    assert accepted["status"] == "CONFIRMED"

    interpreter_one = validate_success(api.get_interpreter(ctx["i1"]["id"], front_office_headers))
    assert interpreter_one["committed_minutes"] == 0


def test_selector_auto_assign_least_loaded(api, front_office_headers):
    """PRD 3.7: "Candidates are ranked by `committed_minutes` ascending, then
    `created_at` ascending, then the interpreter's `created_seq` — the
    server-assigned, strictly increasing global creation sequence — ascending."

    Design: Corner/complexity_layers/selector_auto_assign_least_loaded
    """
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher_id = ctx["teachers"][0]["id"]
    slots = ctx["teacher_slots"][teacher_id]
    interpreter_one = add_interpreter(full_name="I1")
    interpreter_two = add_interpreter(full_name="I2")
    party = setup_family_with_students(
        ctx, 2, family_overrides={"preferred_language": "es"}, grade_levels=[3, 4]
    )
    booking_one = book_slot(slots[0]["id"], party["students"][0]["id"],
                            party["guardian"], interpreter_language="es")
    booking_two = book_slot(slots[2]["id"], party["students"][1]["id"],
                            party["guardian"], interpreter_language="es")
    request_one = request_for_booking(booking_one["id"])
    request_two = request_for_booking(booking_two["id"])

    # Load the earlier-created interpreter with 20 committed minutes.
    get_success_data(api.assign_interpreter(
        request_one["id"], {"interpreter_id": interpreter_one["id"]}, front_office_headers))
    loaded = validate_success(api.get_interpreter(interpreter_one["id"], front_office_headers))
    assert loaded["committed_minutes"] == 20

    # Auto-assign prefers the zero-committed interpreter despite creation order.
    picked = validate_success(api.assign_interpreter(request_two["id"], {}, front_office_headers))
    assert picked["interpreter_id"] == interpreter_two["id"]


def test_assign_adds_assigned_minutes_to_committed(api, front_office_headers):
    """PRD 3.7: "An interpreter is born `ACTIVE` with `committed_minutes` at 0.
    The `committed_minutes` figure is computed as the sum of `assigned_minutes`
    over the interpreter's requests in `ASSIGNED` or `CONFIRMED` status whose
    window is neither `COMPLETED` nor `ARCHIVED`."
    PRD 3.7: "A successful assignment sets `interpreter_id` and adds
    `assigned_minutes` to the interpreter's `committed_minutes`."

    Design: Difficulty/compensating_invariant/interpreter_committed_minutes_round_trip
    """
    ctx = scenario_round_trip()
    interpreter = ctx["interpreter"]

    baseline = validate_success(api.get_interpreter(interpreter["id"], front_office_headers))
    assert baseline["committed_minutes"] == 0

    get_success_data(api.assign_interpreter(
        ctx["request"]["id"], {"interpreter_id": interpreter["id"]}, front_office_headers))
    after = validate_success(api.get_interpreter(interpreter["id"], front_office_headers))
    # The underlying slot is 20 minutes long.
    assert after["committed_minutes"] == 20


def test_cancel_of_assigned_request_returns_committed_to_baseline(api, front_office_headers):
    """PRD 3.7: "When the cancelled request was `ASSIGNED`, the interpreter's
    `committed_minutes` are decremented by `assigned_minutes`."
    PRD 3.7: "An interpreter is born `ACTIVE` with `committed_minutes` at 0.
    The `committed_minutes` figure is computed as the sum of `assigned_minutes`
    over the interpreter's requests in `ASSIGNED` or `CONFIRMED` status whose
    window is neither `COMPLETED` nor `ARCHIVED`."

    Design: Difficulty/compensating_invariant/interpreter_committed_minutes_round_trip
    """
    ctx = scenario_round_trip()
    interpreter = ctx["interpreter"]

    get_success_data(api.assign_interpreter(
        ctx["request"]["id"], {"interpreter_id": interpreter["id"]}, front_office_headers))
    get_success_data(api.cancel_request(ctx["request"]["id"], {}, front_office_headers))

    after = validate_success(api.get_interpreter(interpreter["id"], front_office_headers))
    assert after["committed_minutes"] == 0
