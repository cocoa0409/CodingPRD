"""A substantiated critical incident reaches three entities the adjudication never
names, and a raw score is bounded by the form rather than by the sitting.
"""

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

SIBLING_SESSION = {"starts_at": "2026-08-10T09:00:00Z", "ends_at": "2026-08-10T13:00:00Z",
                   "center_code": "C1", "room_code": "R3"}
CRITICAL_INCIDENT = {"incident_type": "IMPERSONATION", "severity": "CRITICAL",
                     "description": "Photo identification did not match the seated "
                                    "test taker"}
BAR_ENDS = "2028-08-09"


def _sitting_with_a_sibling_seat_and_a_critical_incident(api):
    """A completed, scored sitting whose candidate also holds a second scheduled seat,
    with a critical incident raised against the first sitting.
    """
    state = fx.pipeline_through_scheduled_seat(api)
    sibling_session = fx.create_test_center_session(api, **SIBLING_SESSION)
    sibling_registration = fx.create_registration(api, state.application_id, state.form_id)
    fx.schedule_seat(api, sibling_registration["id"], sibling_session["id"],
                     sibling_session["version"])
    fx.set_clock(api, "2026-08-10T00:00:00Z")
    fx.check_in(api, state.registration_id)
    fx.submit_responses(api, state.registration_id, 1)
    incident = fx.raise_incident(api, state.registration_id, **CRITICAL_INCIDENT)
    return state, sibling_session, sibling_registration, incident


class TestCriticalSubstantiationCascade:
    """Four hops out of one adjudication."""

    def test_hop_one_voids_the_score_and_leaves_the_seat_completed(self, api):
        """The score dimension is voided and its computed fields cleared, while the seat
        dimension is untouched.

        PRD §3.9: "**Hop one**, which always runs: the registration's `score_status` moves
        to `VOIDED` and both `scaled_score` and `outcome` are cleared to null."

        PRD §3.9: "Note that the hold touches only the score dimension — `seat_status` is
        untouched, so a candidate mid-sitting is not ejected by the paperwork."

        Design: Corner/state_machines/critical_incident_substantiation_bars_the_candidate_and_cancels_the_sibling_seat
        """
        state, _sibling_session, _sibling_registration, incident = (
            _sitting_with_a_sibling_seat_and_a_critical_incident(api))
        assert incident["placed_hold"] is True

        adjudicated = validate_success(api.adjudicate_security_incident(
            incident["id"],
            f.adjudicate_incident_payload("SUBSTANTIATE",
                                          outcome_note="Identity fraud confirmed"),
            fx.EXAM_OPERATIONS), 200)

        assert adjudicated["status"] == "SUBSTANTIATED"
        assert adjudicated["placed_hold"] is True
        registration = fx.read_registration(api, state.registration_id)
        assert registration["score_status"] == "VOIDED"
        assert registration["scaled_score"] is None
        assert registration["outcome"] is None
        assert registration["seat_status"] == "COMPLETED"
        ax.assert_security_incident(adjudicated)

    def test_hops_two_and_three_bar_the_candidate_and_cancel_the_sibling_seat(self, api):
        """The candidate is barred for two years and the *other* scheduled registration is
        cancelled with its session pointer cleared, though the adjudication named neither.

        PRD §3.9: "**Hop two:** because the score was voided, the candidate's `status`
        becomes `BARRED` with `bar_reason` `SECURITY_INCIDENT` and `barred_until` set to
        the current logical-clock instant advanced by 730 days — a two-year exclusion from
        testing."

        PRD §3.9: "**Hop three:** because the candidate is barred, every *other* exam
        registration of that candidate whose `seat_status` is `SCHEDULED` moves to
        `CANCELLED` with its `session_id` cleared."

        Design: Corner/state_machines/critical_incident_substantiation_bars_the_candidate_and_cancels_the_sibling_seat
        """
        state, _sibling_session, sibling_registration, incident = (
            _sitting_with_a_sibling_seat_and_a_critical_incident(api))

        validate_success(api.adjudicate_security_incident(
            incident["id"], f.adjudicate_incident_payload("SUBSTANTIATE"),
            fx.EXAM_OPERATIONS), 200)

        candidate = fx.read_candidate(api, state.candidate_id)
        assert candidate["status"] == "BARRED"
        assert candidate["bar_reason"] == "SECURITY_INCIDENT"
        assert str(candidate["barred_until"]).startswith(BAR_ENDS)

        sibling = fx.read_registration(api, sibling_registration["id"])
        assert sibling["seat_status"] == "CANCELLED"
        assert sibling["session_id"] is None

    def test_hop_four_recounts_the_freed_ledger_and_nothing_is_minted(self, api):
        """The sibling session recounts to zero while the completed sitting's session
        still holds its occupied seat, and a voided score mints no credential.

        PRD §3.9: "**Hop four:** because those seats were released, each affected exam
        session recounts `seats_reserved` and recomputes its `status`, possibly flipping
        `FULL → OPEN`."

        PRD §3.7: "`seats_reserved` is the number of exam registrations pointing at the
        session whose `seat_status` is `SCHEDULED`, `CHECKED_IN`, or `COMPLETED`; the
        `UNSCHEDULED`, `NO_SHOW`, and `CANCELLED` states all release the seat."

        Design: Corner/state_machines/critical_incident_substantiation_bars_the_candidate_and_cancels_the_sibling_seat
        """
        state, sibling_session, _sibling_registration, incident = (
            _sitting_with_a_sibling_seat_and_a_critical_incident(api))

        validate_success(api.adjudicate_security_incident(
            incident["id"], f.adjudicate_incident_payload("SUBSTANTIATE"),
            fx.EXAM_OPERATIONS), 200)

        freed = fx.read_session(api, sibling_session["id"])
        assert freed["seats_reserved"] == 0
        assert fx.read_session(api, state.session_id)["seats_reserved"] == 1
        _rows, meta = validate_paginated(api.list_certificants(
            fx.PROGRAM_ADMIN, {"candidate_id": state.candidate_id}))
        assert meta["total_count"] == 0


class TestRawScoreRangeAndTheBarThatFollows:
    """The form bounds the score, and the bar outranks the temporal rules."""

    def test_a_raw_score_above_the_forms_scored_positions_is_refused(self, api):
        """Two marks on a one-position form is out of range, and the refusal leaves both
        status dimensions and the attempt counter exactly where they were.

        PRD §3.8: "The operator supplies the `raw_score`, the number-correct count on the
        form's scored positions, which must be at least 0 and at most the form's
        `scored_item_count` — otherwise `ERR_RAW_SCORE_OUT_OF_RANGE`."

        PRD §2.7: "**Raw score range.** The submitted `raw_score` is at least 0 and at
        most the form's `scored_item_count` → otherwise `ERR_RAW_SCORE_OUT_OF_RANGE`
        (422)."

        Design: Corner/state_machines/an_out_of_range_raw_score_is_refused_and_a_substantiated_critical_incident_bars_the_candidate
        """
        state = fx.pipeline_through_check_in(api)
        assert fx.read_form(api, state.form_id)["scored_item_count"] == 1

        refused = api.submit_responses(
            state.registration_id, f.submit_responses_payload(2), fx.EXAM_OPERATIONS)

        validate_error(refused, ApiErrorId.ERR_RAW_SCORE_OUT_OF_RANGE.value, 422)
        registration = fx.read_registration(api, state.registration_id)
        assert registration["seat_status"] == "CHECKED_IN"
        assert registration["score_status"] == "PENDING"
        assert registration["scaled_score"] is None
        assert fx.read_application(api, state.application_id)["attempts_consumed"] == 0

    def test_an_in_range_score_completes_the_sitting_and_consumes_the_attempt(self, api):
        """One mark on a one-position form equates to the top of the band and consumes the
        application's first attempt.

        PRD §3.8: "On success `seat_status` moves `CHECKED_IN → COMPLETED`, `score_status`
        moves `PENDING → SCORED`, the equated score and outcome are computed, and the
        owning application's `attempts_consumed` increases by 1."

        PRD §3.8: "The anchoring is exact by construction: a `raw_score` equal to the cut
        maps to precisely 500 and passes, one mark below the cut lands below 500 and
        fails, a `raw_score` of 0 maps to precisely 200, and a `raw_score` equal to the
        total maps to precisely 800."

        Design: Corner/state_machines/an_out_of_range_raw_score_is_refused_and_a_substantiated_critical_incident_bars_the_candidate
        """
        state = fx.pipeline_through_check_in(api)
        api.submit_responses(state.registration_id, f.submit_responses_payload(2),
                             fx.EXAM_OPERATIONS)

        scored = validate_success(api.submit_responses(
            state.registration_id, f.submit_responses_payload(1),
            fx.EXAM_OPERATIONS), 200)

        assert scored["seat_status"] == "COMPLETED"
        assert scored["score_status"] == "SCORED"
        assert scored["scaled_score"] == 800
        assert scored["outcome"] == "PASS"
        assert fx.read_application(api, state.application_id)["attempts_consumed"] == 1

    def test_a_critical_hold_withholds_the_score_before_it_is_ever_voided(self, api):
        """Raising the incident freezes the score dimension at once, capturing the
        pre-call value, and the incident opens with the hold recorded.

        PRD §3.9: "When the incident is opened and the registration's `score_status` is
        either `PENDING` or `SCORED`, that pre-call value is captured into
        `score_status_before_hold`, `score_status` moves to `WITHHELD`, and the incident's
        `placed_hold` is set to true."

        Design: Corner/state_machines/an_out_of_range_raw_score_is_refused_and_a_substantiated_critical_incident_bars_the_candidate
        """
        state = fx.pipeline_through_responses(api)

        incident = validate_success(api.raise_security_incident(
            state.registration_id, f.create_incident_payload(**CRITICAL_INCIDENT),
            fx.EXAM_OPERATIONS), 201)

        assert incident["status"] == "OPEN"
        assert incident["placed_hold"] is True
        registration = fx.read_registration(api, state.registration_id)
        assert registration["score_status"] == "WITHHELD"
        assert registration["score_status_before_hold"] == "SCORED"

    def test_the_bar_refuses_a_fresh_registration_ahead_of_the_retake_wait(self, api):
        """Once the candidate is barred, a new registration is turned away on the bar at
        priority 20 rather than on the retake wait at priority 32 or the attempt ceiling at
        priority 38.

        PRD §2.7: "**Candidate bar.** A `BARRED` candidate may neither register, claim a
        seat, nor check in → otherwise `ERR_CANDIDATE_BARRED` (409)."

        PRD §2.7: "**The first violated rule wins and its error is returned; no later rule
        is evaluated.**"

        Design: Corner/state_machines/an_out_of_range_raw_score_is_refused_and_a_substantiated_critical_incident_bars_the_candidate
        """
        state = fx.pipeline_through_responses(api)
        incident = fx.raise_incident(api, state.registration_id, **CRITICAL_INCIDENT)
        validate_success(api.adjudicate_security_incident(
            incident["id"], f.adjudicate_incident_payload("SUBSTANTIATE"),
            fx.EXAM_OPERATIONS), 200)
        assert fx.read_candidate(api, state.candidate_id)["status"] == "BARRED"

        refused = api.create_exam_registration(
            f.create_registration_payload(state.application_id, state.form_id),
            fx.EXAM_OPERATIONS)

        error = validate_error(refused, ApiErrorId.ERR_CANDIDATE_BARRED.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_RETAKE_WAIT_ACTIVE.value
        assert error["error_id"] != ApiErrorId.ERR_MAX_ATTEMPTS_REACHED.value
        _rows, meta = validate_paginated(api.list_exam_registrations(
            fx.EXAM_OPERATIONS, {"application_id": state.application_id}))
        assert meta["total_count"] == 1
