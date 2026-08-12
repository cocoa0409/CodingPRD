"""Ten positions, two ceilings and one mean: the capture floor."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    POSITION_CODES,
    ApiErrorId,
    TEST_USERS,
    assert_fingerprint_card,
    assert_position_capture,
    code_position_exception,
    make_supervisor_headers,
    pass_positions,
    score_position,
    set_clock,
    setup_checked_in_appointment,
    setup_open_card,
    validate_error,
    validate_paginated,
    validate_success,
)

VA = TEST_USERS["vendor_admin_headers"]
TECH = TEST_USERS["technician_headers"]
SUP = TEST_USERS["supervisor_headers"]


def test_opening_a_card_materialises_ten_pending_positions(api):
    """PRD 3.4: "Opening the card moves the appointment `CHECKED_IN → IN_CAPTURE`, creates the card
    at `status` `OPEN`, copies the appointment's site into the card's `site_id` for onsite
    billable-print accounting, stamps `captured_by_user_id` with the acting technician's
    `X-User-ID`, and creates all ten `PositionCapture` rows at once, each at `status` `PENDING`. The
    ten `position_code` values are fixed and complete: `R_THUMB`, `R_INDEX`, `R_MIDDLE`, `R_RING`,
    `R_LITTLE`, `L_THUMB`, `L_INDEX`, `L_MIDDLE`, `L_RING`, `L_LITTLE`."

    Design: Corner/entities/card_creation_materializes_ten_pending_positions
    """
    world = setup_checked_in_appointment(clock_start="2026-06-01T09:00:00Z")

    card = validate_success(
        api.create_card(
            {"appointment_id": world["appointment"]["id"], "device_id": world["device"]["id"]}, TECH
        ),
        201,
    )

    assert_fingerprint_card(card)
    assert card["status"] == "OPEN"
    assert card["captured_by_user_id"] == "tech-01"
    assert card["site_id"] == world["site"]["id"]

    rows, meta = validate_paginated(api.list_card_positions(card["id"], TECH))
    assert meta["total_count"] == 10
    assert sorted(row["position_code"] for row in rows) == sorted(POSITION_CODES)
    for row in rows:
        assert_position_capture(row)
        assert row["status"] == "PENDING"
        assert row["attempt_count"] == 0
        assert row["best_score"] is None

    appointment = validate_success(api.get_appointment(world["appointment"]["id"], TECH), 200)
    assert appointment["status"] == "IN_CAPTURE"


def test_a_freshly_opened_card_carries_zeroed_aggregates(api):
    """PRD 3.4: "A freshly opened card carries `positions_passed_count` 0,
    `positions_exception_count` 0, `mean_quality_score` 0.00, `worst_position_score` null,
    `submittable` false, `exception_override_by_user_id` null, `superseded_by_card_id` null,
    `free_reprint_granted` false, `taint_reason` null, and both `first_capture_at` and
    `last_capture_at` null."

    Design: Corner/entities/card_creation_materializes_ten_pending_positions
    """
    world = setup_checked_in_appointment(clock_start="2026-06-01T09:00:00Z")

    card = validate_success(
        api.create_card(
            {"appointment_id": world["appointment"]["id"], "device_id": world["device"]["id"]}, TECH
        ),
        201,
    )

    assert card["positions_passed_count"] == 0
    assert card["positions_exception_count"] == 0
    assert card["mean_quality_score"] == pytest.approx(0.00, abs=0.001)
    assert card["worst_position_score"] is None
    assert card["submittable"] is False
    assert card["exception_override_by_user_id"] is None
    assert card["superseded_by_card_id"] is None
    assert card["free_reprint_granted"] is False
    assert card["taint_reason"] is None
    assert card["first_capture_at"] is None
    assert card["last_capture_at"] is None


def test_ten_positions_at_sixty_two_leave_the_card_unsubmittable(api):
    """PRD 3.4: "Ten positions each passing at 62 give a mean of 62.00 and the card is **not**
    submittable, even though every individual position cleared the 60 pass threshold — the rejected
    reading, in which it is the lowest passing score rather than the mean that must clear a bar,
    would wave that card through, and this API does not."
    PRD 3.4: "And `mean_quality_score` must be at least 65, failing which the response is again
    `ERR_CARD_NOT_SUBMITTABLE`."

    Design: Difficulty/dual_variant_calc/card_submittability_governed_by_mean_not_worst_position
    """
    world = setup_open_card(clock_start="2026-06-01T09:00:00Z")
    pass_positions(world["card"]["id"], 62)

    response = api.finalize_card(world["card"]["id"], TECH)

    validate_error(response, ApiErrorId.ERR_CARD_NOT_SUBMITTABLE.value)


def test_the_mean_governs_even_when_every_position_cleared_the_pass_threshold(api):
    """PRD 3.4: "- `mean_quality_score` is the arithmetic mean of `best_score` over the `PASSED`
    positions only, carried to two decimal places and rounded half up. Exception-coded positions are
    excluded from both the numerator and the divisor. When no position has passed, it reads 0.00."
    PRD 3.4: "- `worst_position_score` is the smallest `best_score` among the `PASSED` positions, and
    is null when no position has passed."
    PRD 3.4: "- `submittable` is true when all three of the following hold: every one of the ten
    positions has reached `PASSED` or `EXCEPTION_CODED`; `positions_exception_count` is at most the
    applicable exception ceiling, which is 4 when `exception_override_by_user_id` is not null and 2
    otherwise; and `mean_quality_score` is at least 65."

    Design: Difficulty/dual_variant_calc/card_submittability_governed_by_mean_not_worst_position
    """
    world = setup_open_card(clock_start="2026-06-01T09:00:00Z")
    pass_positions(world["card"]["id"], 62)
    api.finalize_card(world["card"]["id"], TECH)

    card = validate_success(api.get_card(world["card"]["id"], TECH), 200)

    assert card["mean_quality_score"] == pytest.approx(62.00, abs=0.001)
    assert card["worst_position_score"] == 62
    assert card["submittable"] is False
    assert card["status"] == "CAPTURING", "a refused finalize leaves the card in capture"
    assert card["positions_passed_count"] == 10


def test_three_failing_attempts_drive_a_position_to_the_ceiling(api):
    """PRD 3.4: "A score below 60 leaves the position open at `FAILED_RETRYABLE` — moving
    `PENDING → FAILED_RETRYABLE` on the first such attempt and looping
    `FAILED_RETRYABLE → FAILED_RETRYABLE` on the second — as long as the attempt just recorded is not
    the third. The third consecutive sub-60 attempt is different: it moves the position
    `FAILED_RETRYABLE → CEILING_REACHED`, leaving `attempt_count` at 3, and any further attempt
    against that position is refused with `ERR_POSITION_ATTEMPT_CEILING_REACHED`."

    Design: Difficulty/non_linear_state_machine/position_retry_self_loop_then_ceiling_then_exception
    """
    world = setup_open_card(clock_start="2026-06-01T09:00:00Z")
    card_id = world["card"]["id"]

    score_position(card_id, "R_THUMB", 41)
    after_two = score_position(card_id, "R_THUMB", 44)
    assert after_two["status"] == "FAILED_RETRYABLE"

    after_three = score_position(card_id, "R_THUMB", 52)
    assert after_three["status"] == "CEILING_REACHED"
    assert after_three["attempt_count"] == 3
    assert after_three["best_score"] == 52

    fourth = api.record_attempt(card_id, "R_THUMB", 95, TECH)
    validate_error(fourth, ApiErrorId.ERR_POSITION_ATTEMPT_CEILING_REACHED.value)


def test_a_ceiling_reached_position_can_still_be_exception_coded(api):
    """PRD 3.4: "Exception coding supplies an `exception_code` of `AMPUTATED`, `BANDAGED` or
    `UNCLASSIFIABLE`; it is admitted from `PENDING` — including before any attempt has ever been
    scored, which is the natural path for an amputated digit — and from `FAILED_RETRYABLE` and from
    `CEILING_REACHED`. It sets `exception_code`, stamps `closed_at`, moves the position to
    `EXCEPTION_CODED`, and removes that position from the quality mean entirely."
    PRD 3.4: "- `positions_exception_count` is the number whose `status` is `EXCEPTION_CODED`."

    Design: Difficulty/non_linear_state_machine/position_retry_self_loop_then_ceiling_then_exception
    """
    world = setup_open_card(clock_start="2026-06-01T09:00:00Z")
    card_id = world["card"]["id"]
    for score in (41, 44, 52):
        score_position(card_id, "R_THUMB", score)
    api.record_attempt(card_id, "R_THUMB", 95, TECH)

    closed = validate_success(api.code_exception(card_id, "R_THUMB", "UNCLASSIFIABLE", TECH), 200)

    assert closed["status"] == "EXCEPTION_CODED"
    assert closed["exception_code"] == "UNCLASSIFIABLE"
    assert closed["attempt_count"] == 3
    assert closed["best_score"] == 52

    card = validate_success(api.get_card(card_id, TECH), 200)
    assert card["positions_exception_count"] == 1


def test_second_attempt_on_a_passed_position_is_refused(api):
    """PRD 3.4: "An attempt or an exception aimed at a position that is already `PASSED` or
    `EXCEPTION_CODED` is refused with `ERR_POSITION_ALREADY_CLOSED`; those two are the terminal
    values of the position axis."

    Design: Corner/state_machines/attempt_on_passed_position_is_rejected_as_already_closed
    """
    world = setup_open_card(clock_start="2026-06-01T09:00:00Z")
    card_id = world["card"]["id"]
    score_position(card_id, "R_THUMB", 91)

    response = api.record_attempt(card_id, "R_THUMB", 95, TECH)

    validate_error(response, ApiErrorId.ERR_POSITION_ALREADY_CLOSED.value)

    rows, _meta = validate_paginated(api.list_card_positions(card_id, TECH))
    thumb = next(row for row in rows if row["position_code"] == "R_THUMB")
    assert thumb["attempt_count"] == 1
    assert thumb["best_score"] == 91

    card = validate_success(api.get_card(card_id, TECH), 200)
    assert card["status"] == "CAPTURING"
    assert card["mean_quality_score"] == pytest.approx(91.00, abs=0.001)


def test_exception_coded_positions_leave_the_divisor_alone(api):
    """PRD 3.4: "Eight positions passing at 68 with the remaining two exception-coded give a mean of
    68.00 over a divisor of eight, not ten, and the card is submittable."
    PRD 3.4: "- `positions_passed_count` is the number of positions whose `status` is `PASSED`."

    Design: Corner/calculations/mean_quality_excludes_exception_coded_positions_from_numerator_and_divisor
    """
    world = setup_open_card(clock_start="2026-06-01T09:00:00Z")
    card_id = world["card"]["id"]
    pass_positions(card_id, 68, POSITION_CODES[:8])
    code_position_exception(card_id, "L_RING", "AMPUTATED")
    code_position_exception(card_id, "L_LITTLE", "AMPUTATED")

    finalized = validate_success(api.finalize_card(card_id, TECH), 200)

    assert finalized["status"] == "READY_FOR_SUBMISSION"
    assert finalized["mean_quality_score"] == pytest.approx(68.00, abs=0.001)
    assert finalized["positions_passed_count"] == 8
    assert finalized["positions_exception_count"] == 2
    assert finalized["worst_position_score"] == 68
    assert finalized["submittable"] is True
    assert finalized["exception_override_by_user_id"] is None


def _card_with_three_exceptions():
    world = setup_open_card(clock_start="2026-06-01T09:00:00Z")
    card_id = world["card"]["id"]
    for code in ("R_THUMB", "R_INDEX", "R_MIDDLE"):
        code_position_exception(card_id, code, "BANDAGED")
    return world


def test_the_capturing_technician_may_not_bless_their_own_card(api):
    """PRD 3.4: "The acting supervisor's `X-User-ID` must differ from the card's
    `captured_by_user_id`, or the request is `ERR_SEGREGATION_OF_DUTIES` — the technician who took
    the prints may not be the person who blesses their shortfall."

    Design: Corner/state_machines/exception_override_needs_a_third_exception_and_a_different_actor
    """
    world = _card_with_three_exceptions()

    response = api.grant_exception_override(
        world["card"]["id"], "self approval", make_supervisor_headers("tech-01")
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    card = validate_success(api.get_card(world["card"]["id"], TECH), 200)
    assert card["exception_override_by_user_id"] is None
    assert card["captured_by_user_id"] == "tech-01"


def test_a_different_supervisor_records_the_override_actor(api):
    """PRD 3.4: "Acceptance stores that `X-User-ID` in `exception_override_by_user_id` and raises the
    applicable ceiling from 2 to 4."
    PRD 3.4: "Every subsequent attempt, exception or supervisor override loops the card
    `CAPTURING → CAPTURING` and recomputes its aggregates."

    Design: Corner/state_machines/exception_override_needs_a_third_exception_and_a_different_actor
    """
    world = _card_with_three_exceptions()

    overridden = validate_success(
        api.grant_exception_override(
            world["card"]["id"], "three fingers unusable, supervisor reviewed", SUP
        ),
        200,
    )

    assert overridden["exception_override_by_user_id"] == "sup-77"
    assert overridden["positions_exception_count"] == 3
    assert overridden["status"] == "CAPTURING"


def _card_with_four_exceptions():
    world = setup_open_card(clock_start="2026-06-01T09:00:00Z")
    card_id = world["card"]["id"]
    pass_positions(card_id, 80, POSITION_CODES[:5])
    for code, reason in (
        ("L_THUMB", "BANDAGED"),
        ("L_INDEX", "BANDAGED"),
        ("L_MIDDLE", "UNCLASSIFIABLE"),
        ("L_RING", "UNCLASSIFIABLE"),
    ):
        code_position_exception(card_id, code, reason)
    return world


def test_a_fifth_exception_breaks_the_hard_ceiling(api):
    """PRD 3.4: "It is bounded by a hard ceiling that nothing can lift: if the card's
    `positions_exception_count` plus the position being coded would exceed 4, the request is refused
    with `ERR_EXCEPTION_LIMIT_EXCEEDED`."

    Design: Corner/validations/exception_ceilings_gate_both_the_fifth_exception_and_an_unapproved_finalize
    """
    world = _card_with_four_exceptions()

    response = api.code_exception(world["card"]["id"], "L_LITTLE", "AMPUTATED", TECH)

    validate_error(response, ApiErrorId.ERR_EXCEPTION_LIMIT_EXCEEDED.value)

    card = validate_success(api.get_card(world["card"]["id"], TECH), 200)
    assert card["positions_exception_count"] == 4


def test_four_exceptions_need_a_supervisor_before_finalize(api):
    """PRD 3.4: "The `positions_exception_count` must be at most 2 unless
    `exception_override_by_user_id` is set, failing which the response is
    `ERR_EXCEPTION_LIMIT_EXCEEDED`."
    PRD 3.4: "Acceptance stores that `X-User-ID` in `exception_override_by_user_id` and raises the
    applicable ceiling from 2 to 4."

    Design: Corner/validations/exception_ceilings_gate_both_the_fifth_exception_and_an_unapproved_finalize
    """
    world = _card_with_four_exceptions()
    card_id = world["card"]["id"]
    score_position(card_id, "L_LITTLE", 80)

    blocked = api.finalize_card(card_id, TECH)
    validate_error(blocked, ApiErrorId.ERR_EXCEPTION_LIMIT_EXCEEDED.value)

    validate_success(
        api.grant_exception_override(card_id, "four fingers bandaged after injury", SUP), 200
    )
    finalized = validate_success(api.finalize_card(card_id, TECH), 200)

    assert finalized["status"] == "READY_FOR_SUBMISSION"
    assert finalized["mean_quality_score"] == pytest.approx(80.00, abs=0.001)
    assert finalized["positions_exception_count"] == 4
    assert finalized["positions_passed_count"] == 6
    assert finalized["exception_override_by_user_id"] == "sup-77"


def test_attempt_against_a_card_that_does_not_exist(api):
    """PRD 2.12: "Requesting an attempt against position `R_THUMB` of a card that does not exist
    returns `ERR_CARD_NOT_FOUND` and never a position error, because the card segment is resolved
    first."

    Design: Corner/entities/attempt_on_unknown_card_returns_card_not_found
    """
    set_clock("2026-06-01T09:00:00Z")

    response = api.record_attempt(NON_EXISTENT_UUID, "R_THUMB", 70, TECH)

    error = validate_error(response, ApiErrorId.ERR_CARD_NOT_FOUND.value)
    assert error["error_id"] != ApiErrorId.ERR_REFERENCE_NOT_FOUND.value
