"""The retake wait, the attempt ceiling and the two cross-entity gates on registration."""

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success


def _one_sitting_completed(api, **program_overrides):
    """A candidate whose first sitting ended at 2026-08-10T04:00:00Z and was reported."""
    return fx.pipeline_through_certificant(
        api, program_overrides=program_overrides or None)


def _registrations_of(api, application_id):
    return validate_paginated(api.list_exam_registrations(
        fx.EXAM_OPERATIONS, {"application_id": application_id}))


def _two_programmes_each_with_a_published_form(api):
    """CPX with an approved applicant, and an unrelated CPY whose form is published."""
    state = fx.pipeline_through_approved_application(api)
    other_program = fx.active_program(api, name="Certified Practitioner Y",
                                      credential_code="CPY")
    other_item = fx.operational_item(api, other_program["id"], stem="CPY operational item")
    other_form = fx.published_form(api, other_program["id"], [other_item["id"]],
                                   form_code="CPY-F1")
    assert other_form["status"] == "PUBLISHED"
    return state, other_form


class TestRetakeWaitBoundary:
    """The wait runs from the consumed sitting's end, and the comparison is strict."""

    def test_one_minute_short_of_forty_five_days_is_refused_on_the_wait(self, api):
        """At 2026-09-24T03:59:00Z the wait off a sitting that ended at 04:00:00Z has not
        elapsed, and it is the wait — not the ceiling of three, not an expired
        eligibility — that turns the registration away.

        PRD §3.7: "Then take the greatest `session_ends_at` among those same consumed
        registrations; when no attempt has been consumed there is no such instant and no
        wait applies."

        PRD §3.7: "When there is one, the registration is refused with
        `ERR_RETAKE_WAIT_ACTIVE` if the logical clock is strictly earlier than that instant
        advanced by the program's `retake_wait_days` — so a candidate whose last sitting
        ended exactly `retake_wait_days` ago is allowed through, while one an hour short is
        not."

        Design: Corner/validations/retake_wait_rejects_one_minute_early_and_admits_the_exact_forty_five_day_mark
        """
        state = _one_sitting_completed(api)
        assert fx.read_application(api, state.application_id)["attempts_consumed"] == 1
        fx.set_clock(api, "2026-09-24T03:59:00Z")

        refused = api.create_exam_registration(
            f.create_registration_payload(state.application_id, state.form_id),
            fx.EXAM_OPERATIONS)

        error = validate_error(refused, ApiErrorId.ERR_RETAKE_WAIT_ACTIVE.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_MAX_ATTEMPTS_REACHED.value
        assert error["error_id"] != ApiErrorId.ERR_ELIGIBILITY_EXPIRED.value
        assert fx.read_application(api, state.application_id)["attempts_consumed"] == 1
        _rows, meta = _registrations_of(api, state.application_id)
        assert meta["total_count"] == 1

    def test_the_exact_forty_five_day_mark_is_admitted_as_attempt_two(self, api):
        """One minute later the wait is spent to the second, so the identical body creates
        an unscheduled second attempt while the first sitting keeps its consumed status.

        PRD §3.7: "Otherwise the new registration's `attempt_number` is that count plus 1."

        PRD §3.7: "A new registration begins with `seat_status` `UNSCHEDULED`, `score_status`
        `NOT_APPLICABLE`, `form_reassignment_required` false, `session_id` and
        `session_ends_at` null, and `raw_score`, `scaled_score`, `outcome`, and
        `score_status_before_hold` all null."

        PRD §3.7: "Count the application's registrations whose `seat_status` is `COMPLETED`
        or `NO_SHOW` — that count is the application's `attempts_consumed`."

        Design: Corner/validations/retake_wait_rejects_one_minute_early_and_admits_the_exact_forty_five_day_mark
        """
        state = _one_sitting_completed(api)
        body = f.create_registration_payload(state.application_id, state.form_id)
        fx.set_clock(api, "2026-09-24T03:59:00Z")
        api.create_exam_registration(body, fx.EXAM_OPERATIONS)
        fx.set_clock(api, "2026-09-24T04:00:00Z")

        retake = validate_success(api.create_exam_registration(body, fx.EXAM_OPERATIONS), 201)

        assert retake["attempt_number"] == 2
        assert retake["seat_status"] == "UNSCHEDULED"
        assert retake["score_status"] == "NOT_APPLICABLE"
        assert retake["session_id"] is None
        ax.assert_exam_registration(retake)

        assert fx.read_registration(api, state.registration_id)["seat_status"] == "COMPLETED"
        assert fx.read_application(api, state.application_id)["attempts_consumed"] == 1


class TestAttemptCeiling:
    """With one attempt permitted and no wait, the two rules answer in ladder order."""

    def test_a_zero_day_wait_is_still_unelapsed_before_the_session_ends(self, api):
        """Even a wait of zero days is measured from the sitting's end, so the call issued
        inside the first session's window answers on the temporal rule rather than the cap.

        PRD §2.7: "32. **Retake wait.** The mandatory wait since the latest consumed
        attempt has elapsed → otherwise `ERR_RETAKE_WAIT_ACTIVE` (409)."

        PRD §2.7: "38. **Attempt ceiling.** Consumed attempts on the application are below
        the program's `max_attempts_per_cycle` → otherwise `ERR_MAX_ATTEMPTS_REACHED`
        (422)."

        Design: Corner/validations/attempt_cap_refuses_a_second_registration_once_the_only_permitted_attempt_is_consumed
        """
        state = _one_sitting_completed(api, max_attempts_per_cycle=1, retake_wait_days=0)

        refused = api.create_exam_registration(
            f.create_registration_payload(state.application_id, state.form_id),
            fx.EXAM_OPERATIONS)

        validate_error(refused, ApiErrorId.ERR_RETAKE_WAIT_ACTIVE.value, 409)
        program = fx.read_program(api, state.program_id)
        assert program["max_attempts_per_cycle"] == 1
        assert program["retake_wait_days"] == 0

    def test_once_the_wait_has_run_the_exhausted_cap_refuses_the_registration(self, api):
        """Past the session's end the wait no longer bites, and the single consumed attempt
        is exactly the ceiling, so the answer changes to the aggregate rule and no second
        row is written by either refusal.

        PRD §3.7: "If it is already greater than or equal to the program's
        `max_attempts_per_cycle`, the new registration is refused with
        `ERR_MAX_ATTEMPTS_REACHED`; under the default of 3 that means the fourth
        registration is turned away."

        PRD §3.7: "A `CANCELLED` or still-`UNSCHEDULED` registration consumes nothing and
        starts no wait, and a score that is later voided does not un-consume its attempt,
        because `seat_status` stays `COMPLETED` regardless of what happens to the score."

        Design: Corner/validations/attempt_cap_refuses_a_second_registration_once_the_only_permitted_attempt_is_consumed
        """
        state = _one_sitting_completed(api, max_attempts_per_cycle=1, retake_wait_days=0)
        body = f.create_registration_payload(state.application_id, state.form_id)
        api.create_exam_registration(body, fx.EXAM_OPERATIONS)
        fx.set_clock(api, "2026-08-10T05:00:00Z")

        refused = api.create_exam_registration(body, fx.EXAM_OPERATIONS)

        error = validate_error(refused, ApiErrorId.ERR_MAX_ATTEMPTS_REACHED.value, 422)
        assert error["error_id"] != ApiErrorId.ERR_RETAKE_WAIT_ACTIVE.value
        assert fx.read_application(api, state.application_id)["attempts_consumed"] == 1
        _rows, meta = _registrations_of(api, state.application_id)
        assert meta["total_count"] == 1
        first = fx.read_registration(api, state.registration_id)
        assert first["seat_status"] == "COMPLETED"
        assert first["score_status"] == "REPORTED"


class TestRegistrationCrossEntityGates:
    """A form from another programme, and a session whose window has already opened."""

    def test_a_published_form_from_another_programme_is_refused_on_the_mismatch(self, api):
        """Both rows are individually valid — the CPY form is PUBLISHED and the CPX
        application APPROVED — and the refusal is precisely about the pair not agreeing.

        PRD §3.7: "The cited form and the cited application must belong to the same
        certification program, or `ERR_ELIGIBILITY_PROGRAM_MISMATCH`."

        Design: Corner/validations/registration_rejects_a_form_from_another_program_and_a_session_whose_window_has_opened
        """
        state, other_form = _two_programmes_each_with_a_published_form(api)

        refused = api.create_exam_registration(
            f.create_registration_payload(state.application_id, other_form["id"]),
            fx.EXAM_OPERATIONS)

        error = validate_error(refused, ApiErrorId.ERR_ELIGIBILITY_PROGRAM_MISMATCH.value, 422)
        assert error["error_id"] != ApiErrorId.ERR_FORM_NOT_PUBLISHED.value
        assert error["error_id"] != ApiErrorId.ERR_APPLICATION_NOT_APPROVED.value
        assert fx.read_application(api, state.application_id)["status"] == "APPROVED"

    def test_the_programme_s_own_form_registers_and_the_future_session_opens_with_no_seats(
            self, api):
        """Swapping in CPX's form is accepted as attempt one, and a session created while
        the clock is still 2026-08-01 reports itself open and empty.

        PRD §3.7: "`seats_reserved` is the number of exam registrations pointing at the
        session whose `seat_status` is `SCHEDULED`, `CHECKED_IN`, or `COMPLETED`; the
        `UNSCHEDULED`, `NO_SHOW`, and `CANCELLED` states all release the seat."

        PRD §3.7: "The session's `status` is `CLOSED` when the logical clock has reached or
        passed `starts_at`; otherwise it is `FULL` when `seats_reserved` is greater than or
        equal to `seat_capacity`; otherwise it is `OPEN`."

        Design: Corner/validations/registration_rejects_a_form_from_another_program_and_a_session_whose_window_has_opened
        """
        state, other_form = _two_programmes_each_with_a_published_form(api)
        api.create_exam_registration(
            f.create_registration_payload(state.application_id, other_form["id"]),
            fx.EXAM_OPERATIONS)

        registration = validate_success(api.create_exam_registration(
            f.create_registration_payload(state.application_id, state.form_id),
            fx.EXAM_OPERATIONS), 201)
        assert registration["attempt_number"] == 1
        assert registration["seat_status"] == "UNSCHEDULED"
        assert registration["session_id"] is None

        session = validate_success(api.create_exam_session(
            f.create_test_center_session_payload(), fx.EXAM_OPERATIONS), 201)
        assert session["status"] == "OPEN"
        assert session["seats_reserved"] == 0
        ax.assert_exam_session(session)

    def test_a_session_at_exactly_its_start_is_closed_to_a_seat_claim(self, api):
        """The clock reaching `starts_at` closes the session non-strictly, so the claim is
        refused on closure with a version token nothing has invalidated and five free
        seats.

        PRD §3.7: "the session must not be closed — the logical clock must be strictly
        before its `starts_at` — or `ERR_SESSION_CLOSED`"

        PRD §3.7: "Closure wins over fullness, so a session that is both past its start and
        at capacity reports `CLOSED`."

        Design: Corner/validations/registration_rejects_a_form_from_another_program_and_a_session_whose_window_has_opened
        """
        state, _other_form = _two_programmes_each_with_a_published_form(api)
        registration = fx.create_registration(api, state.application_id, state.form_id)
        session = validate_success(api.create_exam_session(
            f.create_test_center_session_payload(), fx.EXAM_OPERATIONS), 201)
        current_version = session["version"]

        fx.set_clock(api, "2026-08-10T00:00:00Z")

        closed = fx.read_session(api, session["id"])
        assert closed["status"] == "CLOSED"
        assert closed["version"] == current_version

        refused = api.schedule_seat(
            registration["id"], f.schedule_seat_payload(session["id"], current_version),
            fx.EXAM_OPERATIONS)

        error = validate_error(refused, ApiErrorId.ERR_SESSION_CLOSED.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_STALE_VERSION.value
        assert error["error_id"] != ApiErrorId.ERR_SESSION_FULL.value
        assert fx.read_registration(api, registration["id"])["seat_status"] == "UNSCHEDULED"
        settled = fx.read_session(api, session["id"])
        assert settled["seats_reserved"] == 0
        assert settled["seat_capacity"] == 5
