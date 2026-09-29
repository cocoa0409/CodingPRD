"""Two independent dimensions on one registration row: seat and score."""

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

CRITICAL_INCIDENT = {"incident_type": "CONTENT_DISCLOSURE", "severity": "CRITICAL",
                     "description": "Candidate photographed two screens"}
# A MAJOR incident places no hold, so the score dimension stays SCORED and the
# release is refused purely on the open incident rather than on its own state.
MAJOR_INCIDENT = {"incident_type": "PROCTOR_INTERRUPTION", "severity": "MAJOR",
                  "description": "Proctor interrupted the sitting twice"}


class TestCriticalHoldOnAScoredSitting:
    """A CRITICAL incident freezes the score and leaves the seat alone."""

    def test_hold_captures_the_pre_call_score_status_and_spares_the_seat(self, api):
        """Opening the incident moves the score dimension to WITHHELD while
        ``seat_status`` stays COMPLETED, the equated result stays on the row, and
        the session's occupancy is untouched.

        PRD §3.9: "When the incident is opened and the registration's
        `score_status` is either `PENDING` or `SCORED`, that pre-call value is
        captured into `score_status_before_hold`, `score_status` moves to
        `WITHHELD`, and the incident's `placed_hold` is set to true."

        PRD §3.9: "Note that the hold touches only the score dimension —
        `seat_status` is untouched, so a candidate mid-sitting is not ejected by the
        paperwork."

        Design: Difficulty/non_linear_state_machine/registration_score_dimension_holds_and_restores_while_seat_dimension_stays_completed
        """
        state = fx.pipeline_through_responses(api)
        before = fx.read_registration(api, state.registration_id)
        assert before["seat_status"] == "COMPLETED"
        assert before["score_status"] == "SCORED"
        assert before["score_status_before_hold"] is None

        incident = validate_success(api.raise_security_incident(
            state.registration_id, f.create_incident_payload(**CRITICAL_INCIDENT),
            fx.EXAM_OPERATIONS), 201)

        assert incident["status"] == "OPEN"
        assert incident["placed_hold"] is True
        ax.assert_security_incident(incident)

        held = fx.read_registration(api, state.registration_id)
        assert held["score_status"] == "WITHHELD"
        assert held["score_status_before_hold"] == "SCORED"
        assert held["seat_status"] == "COMPLETED"
        assert held["scaled_score"] == 800
        assert held["outcome"] == "PASS"

        session = fx.read_session(api, state.session_id)
        assert session["seats_reserved"] == 1
        ax.assert_seat_ledger_within_bounds(session)

    def test_release_is_blocked_while_the_incident_is_open(self, api):
        """A held score cannot be released, and the refusal leaves the row where it
        was.

        PRD §3.8: "The score must currently be `SCORED`, or `ERR_INVALID_STATE`,
        and no security incident on this registration may still be `OPEN` — an
        unresolved incident blocks release with `ERR_SCORE_UNDER_SECURITY_HOLD`."

        PRD §3.9: "The mere existence of an `OPEN` incident on a registration is
        enough to block score release with `ERR_SCORE_UNDER_SECURITY_HOLD`,
        whatever its severity."

        The incident raised here is `MAJOR`, so PRD §3.9's freeze does not apply
        and `score_status` stays `SCORED`. That isolates the security-hold rule
        at layer 21: were the score already `WITHHELD`, the earlier transition
        legality layer would answer `ERR_INVALID_STATE` first, per §2.7's
        normative ordering.

        Design: Difficulty/non_linear_state_machine/registration_score_dimension_holds_and_restores_while_seat_dimension_stays_completed
        """
        state = fx.pipeline_through_responses(api)
        incident = validate_success(api.raise_security_incident(
            state.registration_id, f.create_incident_payload(**MAJOR_INCIDENT),
            fx.EXAM_OPERATIONS), 201)
        assert incident["status"] == "OPEN"
        assert incident["placed_hold"] is False

        refused = api.report_score(state.registration_id, f.report_score_payload(),
                                   fx.EXAM_OPERATIONS)

        validate_error(refused, ApiErrorId.ERR_SCORE_UNDER_SECURITY_HOLD.value, 409)
        still_held = fx.read_registration(api, state.registration_id)
        assert still_held["score_status"] == "SCORED"
        assert still_held["seat_status"] == "COMPLETED"


class TestDismissalRestoresTheScoreDimension:
    """Dismissal is purely compensating."""

    def test_dismissal_restores_the_captured_status_and_leaves_the_candidate_alone(self, api):
        """The score returns to the value the hold captured, the capture field is
        cleared, and the candidate is not barred.

        PRD §3.9: "When the incident's `placed_hold` is true, the registration's
        `score_status` is restored to the value stored in `score_status_before_hold`
        — so a score frozen while `SCORED` returns to `SCORED` and a sitting frozen
        while `PENDING` returns to `PENDING` — and `score_status_before_hold` is
        cleared back to null."

        PRD §3.9: "The candidate's `status` is untouched by a dismissal, and no
        seats are affected."

        Design: Difficulty/non_linear_state_machine/registration_score_dimension_holds_and_restores_while_seat_dimension_stays_completed
        """
        state = fx.pipeline_through_responses(api)
        incident = validate_success(api.raise_security_incident(
            state.registration_id, f.create_incident_payload(**CRITICAL_INCIDENT),
            fx.EXAM_OPERATIONS), 201)

        dismissed = fx.adjudicate_incident(api, incident["id"], "DISMISS")

        assert dismissed["status"] == "UNSUBSTANTIATED"
        restored = fx.read_registration(api, state.registration_id)
        assert restored["score_status"] == "SCORED"
        assert restored["score_status_before_hold"] is None
        assert restored["seat_status"] == "COMPLETED"

        candidate = fx.read_candidate(api, state.candidate_id)
        assert candidate["status"] == "ACTIVE"
        assert candidate["barred_until"] is None

    def test_release_after_dismissal_reports_the_score_and_mints_the_credential(self, api):
        """With the incident resolved the score releases normally, the seat
        dimension having never moved, and the passing result mints the credential.

        PRD §3.8: "It moves `score_status` `SCORED → REPORTED`."

        PRD §3.10: "**hop one** mints a certificant for the candidate-and-program
        pair: its `candidate_id` and `program_id` are taken from the registration
        and its application rather than supplied by any client, its `status` is
        `ACTIVE`, its `publication_status` is `PUBLISHED`".

        Design: Difficulty/non_linear_state_machine/registration_score_dimension_holds_and_restores_while_seat_dimension_stays_completed
        """
        state = fx.pipeline_through_responses(api)
        incident = validate_success(api.raise_security_incident(
            state.registration_id, f.create_incident_payload(**CRITICAL_INCIDENT),
            fx.EXAM_OPERATIONS), 201)
        fx.adjudicate_incident(api, incident["id"], "DISMISS")

        reported = validate_success(api.report_score(
            state.registration_id, f.report_score_payload(), fx.EXAM_OPERATIONS), 200)

        assert reported["score_status"] == "REPORTED"
        assert reported["seat_status"] == "COMPLETED"

        certificants, _meta = validate_paginated(api.list_certificants(
            fx.PROGRAM_ADMIN, {"candidate_id": state.candidate_id}))
        assert len(certificants) == 1
        assert certificants[0]["certificate_number"] == "CPX-2026-00001"
        assert certificants[0]["status"] == "ACTIVE"
