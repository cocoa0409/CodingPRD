"""State machines and lifecycles: cyclic weather loop, parallel enrollment
dimensions, invalid transitions, initial states, terminal lockdown, and the
certification-card issuance side effect.

Queue A: rule_id=non_linear_state_machine. Queue B: section=state_machines.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, TEST_USERS,
    setup_catalog, create_student_with_waiver, create_school, create_student,
    create_equipment, create_paid_enrollment, create_enrollment,
    create_session, book, attend_session, set_clock, create_rental,
    ApiErrorId,
)

ADMIN = TEST_USERS["admin_headers"]


# ============================================================================
# rule_id=non_linear_state_machine
# ============================================================================
class TestSessionWeatherLoop:
    """Session is cyclic: SCHEDULED<->WEATHER_HOLD may repeat."""

    def _scheduled_session(self):
        cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
        s = create_session(cat["school"]["id"], cat["level"]["id"], cat["instructor"]["id"],
                          starts_at="2026-03-10T09:00:00Z", ends_at="2026-03-10T10:00:00Z",
                          tide_window_start="2026-03-10T08:00:00Z",
                          tide_window_end="2026-03-10T12:00:00Z", capacity=4)
        return s["id"]

    def test_loop_returns_to_scheduled_after_two_cycles(self, api):
        """PRD §3.6: "From `WEATHER_HOLD` the administrator may clear the hold
        back to `SCHEDULED`, provided the school is not storm-closed
        (`storm_advisory_active` must be false); this reopens check-in and
        start, and the hold-and-clear cycle may repeat any number of times
        before the session starts."

        Design: Difficulty/non_linear_state_machine/session_cyclic_scheduled_weatherhold_loop
        """
        sid = self._scheduled_session()
        get_success_data(api.weather_hold_session(sid, ADMIN))
        get_success_data(api.clear_hold_session(sid, ADMIN))
        get_success_data(api.weather_hold_session(sid, ADMIN))
        data = validate_success(api.clear_hold_session(sid, ADMIN), 200)
        assert data["status"] == "SCHEDULED", \
            f"after hold/clear/hold/clear the status returns to SCHEDULED: got {data['status']}"

    def test_weather_hold_moves_to_held_state(self, api):
        """PRD §3.6: "An administrator may place a `SCHEDULED` session on
        `WEATHER_HOLD`; this releases no bookings but blocks check-in and start
        while held."

        Design: Difficulty/non_linear_state_machine/session_cyclic_scheduled_weatherhold_loop
        """
        sid = self._scheduled_session()
        data = validate_success(api.weather_hold_session(sid, ADMIN), 200)
        assert data["status"] == "WEATHER_HOLD", \
            f"weather-hold moves SCHEDULED -> WEATHER_HOLD: got {data['status']}"


class TestEnrollmentParallelDimensions:
    """progress_status and payment_status advance independently on one row."""

    def _active_unpaid_enrollment(self):
        cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
        school, level = cat["school"], cat["level"]
        student = create_student_with_waiver(school["id"])
        return create_enrollment(school["id"], student["id"], level["id"],
                                 planned_sessions=1, party_size=1)

    def test_withdraw_progress_leaves_paid_payment(self, api):
        """PRD §3.5: "An enrollment evolves along two dimensions that move
        independently of one another on the same record."

        Design: Difficulty/non_linear_state_machine/enrollment_parallel_progress_and_payment_dimensions
        """
        enr = self._active_unpaid_enrollment()
        get_success_data(api.pay_enrollment(enr["id"], ADMIN))
        data = validate_success(api.withdraw_enrollment(enr["id"], ADMIN), 200)
        assert data["progress_status"] == "WITHDRAWN"
        assert data["payment_status"] == "PAID", \
            "withdrawing the progress dimension must leave payment_status PAID"

    def test_pay_payment_leaves_progress_active(self, api):
        """PRD §3.5: "Paying an enrollment is permitted by an administrator or
        the owning student. It requires that `payment_status` be `UNPAID` and
        that `progress_status` is not `WITHDRAWN`; it moves `payment_status` to
        `PAID` and leaves `progress_status` untouched."

        Design: Difficulty/non_linear_state_machine/enrollment_parallel_progress_and_payment_dimensions
        """
        enr = self._active_unpaid_enrollment()
        data = validate_success(api.pay_enrollment(enr["id"], ADMIN), 200)
        assert data["payment_status"] == "PAID"
        assert data["progress_status"] == "ACTIVE", \
            "paying must leave progress_status untouched at ACTIVE"


# ============================================================================
# Queue B (Corner) — section: state_machines
# ============================================================================
def _completed_session(api):
    set_clock("2026-03-05T08:30:00Z")
    cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
    s = create_session(cat["school"]["id"], cat["level"]["id"], cat["instructor"]["id"],
                      starts_at="2026-03-05T09:00:00Z", ends_at="2026-03-05T10:00:00Z",
                      tide_window_start="2026-03-05T08:00:00Z",
                      tide_window_end="2026-03-05T12:00:00Z", capacity=4)
    get_success_data(api.start_session(s["id"], ADMIN))
    get_success_data(api.complete_session(s["id"], ADMIN))
    return s["id"]


def test_cancel_completed_session_invalid_state(api):
    """PRD §3.6: "Cancelling a session is an administrator action available
    while the session is `SCHEDULED` or `WEATHER_HOLD`."

    Design: Corner/state_machines/cancel_session_from_completed_returns_invalid_state
    """
    sid = _completed_session(api)
    validate_error(api.cancel_session(sid, ADMIN), ApiErrorId.ERR_INVALID_STATE.value)


def test_start_session_before_tide_window_invalid_state(api):
    """PRD §3.6: "It requires the session to be `SCHEDULED`, the school to be
    `OPEN` (a storm-closed school blocks the start with
    `ERR_SCHOOL_STORM_CLOSED`), and the logical clock to fall within the tide
    window — at or after `tide_window_start` and strictly before
    `tide_window_end`."

    Design: Corner/state_machines/start_session_outside_tide_window_returns_invalid_state
    """
    set_clock("2026-03-05T06:00:00Z")
    cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
    s = create_session(cat["school"]["id"], cat["level"]["id"], cat["instructor"]["id"],
                      starts_at="2026-03-05T09:00:00Z", ends_at="2026-03-05T10:00:00Z",
                      tide_window_start="2026-03-05T08:00:00Z",
                      tide_window_end="2026-03-05T12:00:00Z", capacity=4)
    validate_error(api.start_session(s["id"], ADMIN), ApiErrorId.ERR_INVALID_STATE.value)


def test_session_initial_state_scheduled(api):
    """PRD §3.6: "A new session opens with `status` `SCHEDULED`, an
    `enrolled_count` of 0, a `required_instructors` of 0, and it increments the
    parent school's `open_session_count`."

    Design: Corner/state_machines/session_initial_state_scheduled
    """
    cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
    res = api.create_session(
        {"school_id": cat["school"]["id"], "course_level_id": cat["level"]["id"],
         "instructor_id": cat["instructor"]["id"],
         "starts_at": "2026-03-10T09:00:00Z", "ends_at": "2026-03-10T10:00:00Z",
         "tide_window_start": "2026-03-10T08:00:00Z",
         "tide_window_end": "2026-03-10T12:00:00Z", "capacity": 4}, ADMIN)
    data = validate_success(res, 201)
    assert data["status"] == "SCHEDULED"


def test_returned_rental_cannot_be_cancelled(api):
    """PRD §3.9: "Cancelling a rental, available while it is `RESERVED` or
    `ACTIVE`, moves it to `CANCELLED`."

    Design: Corner/state_machines/terminal_returned_rental_cannot_be_cancelled
    """
    set_clock("2026-03-03T00:00:00Z")
    school = create_school(name="Rt School")
    student = create_student(school["id"], full_name="Leo")
    equipment = create_equipment(school["id"], equipment_type="BOARD",
                                 asset_tag="B-1", hourly_rate_cents=1000, deposit_cents=0)
    rental = create_rental(school["id"], student["id"], equipment["id"], equipment["version"],
                           starts_at="2026-03-02T09:00:00Z", ends_at="2026-03-02T12:00:00Z")
    get_success_data(api.checkout_rental(rental["id"], ADMIN))
    get_success_data(api.return_rental(rental["id"], ADMIN))
    validate_error(api.cancel_rental(rental["id"], ADMIN), ApiErrorId.ERR_INVALID_STATE.value)


def test_clear_hold_from_scheduled_invalid_state(api):
    """PRD §3.6: "A hold or clear attempted from the wrong status is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/clear_hold_from_scheduled_returns_invalid_state
    """
    cat = setup_catalog(level_overrides={"max_students_per_instructor": 4})
    s = create_session(cat["school"]["id"], cat["level"]["id"], cat["instructor"]["id"],
                      starts_at="2026-03-10T09:00:00Z", ends_at="2026-03-10T10:00:00Z",
                      tide_window_start="2026-03-10T08:00:00Z",
                      tide_window_end="2026-03-10T12:00:00Z", capacity=4)
    validate_error(api.clear_hold_session(s["id"], ADMIN), ApiErrorId.ERR_INVALID_STATE.value)


def test_certification_card_issued_on_completion(api):
    """PRD §3.5: "if the parent course's `kind` is `CERTIFICATION` and no card
    has yet been issued for this enrollment — a certification card is issued as
    a cross-entity cascade (see §3.9)."
    PRD §3.9: "The card records the `student_id`, the `enrollment_id`, the
    `course_level_id`, and the `discipline` copied from the course at issuance."

    Design: Corner/state_machines/certification_card_issued_on_certification_course_completion
    """
    set_clock("2026-03-01T00:00:00Z")
    cat = setup_catalog(
        course_overrides={"discipline": "SAIL", "title": "Cert Sail", "kind": "CERTIFICATION"},
        level_overrides={"max_students_per_instructor": 4, "base_price_cents": 5000,
                         "min_age": 0, "requires_swim_test": False,
                         "required_equipment_type": "NONE"},
        instructor_overrides={"full_name": "Ana", "certified_disciplines": ["SAIL"]})
    school, level, inst = cat["school"], cat["level"], cat["instructor"]
    student = create_student_with_waiver(school["id"])
    enr = create_paid_enrollment(school["id"], student["id"], level["id"],
                                 planned_sessions=1, party_size=1)
    sess = create_session(school["id"], level["id"], inst["id"],
                         starts_at="2026-03-05T09:00:00Z", ends_at="2026-03-05T10:00:00Z",
                         tide_window_start="2026-03-05T08:00:00Z",
                         tide_window_end="2026-03-05T12:00:00Z", capacity=4)
    bk = book(sess["id"], enr["id"], sess["version"])
    attend_session(sess["id"], [bk["id"]], "2026-03-05T08:30:00Z")
    get_success_data(api.complete_enrollment(enr["id"], ADMIN))
    data, meta = validate_paginated(
        api.list_certification_cards(ADMIN, params={"enrollment_id": enr["id"]}))
    assert len(data) == 1, f"exactly one card issued for this enrollment: got {len(data)}"
    assert data[0]["discipline"] == "SAIL", \
        f"card discipline copied from the SAIL course: got {data[0]['discipline']}"
