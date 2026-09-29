"""The seat ledger is compensated exactly: 0 → 1 → 0 → 1 on a one-seat session."""

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success

ONE_SEAT_SESSION = {"seat_capacity": 1, "center_code": "C1", "room_code": "R1",
                    "starts_at": "2026-08-10T00:00:00Z", "ends_at": "2026-08-10T04:00:00Z"}
CANCELLATION = {"cancel_reason": "candidate deferred"}


def _one_seat_session_with_two_rivals(api):
    """A single-seat session and two approved candidates each holding an unscheduled
    registration on the same published form.
    """
    state = fx.pipeline_through_approved_application(api)
    rival = fx.second_candidate_application(api, state)
    session = fx.create_test_center_session(api, **ONE_SEAT_SESSION)
    registration_a = fx.create_registration(api, state.application_id, state.form_id)
    registration_b = fx.create_registration(api, rival["application"]["id"], state.form_id)
    return session, registration_a, registration_b


class TestSeatLedgerCompensation:
    """One seat, two rivals, one cancellation."""

    def test_the_first_claim_fills_the_session_and_bumps_its_version(self, api):
        """The ledger goes to one, the derived status flips to FULL, and the claim leaves
        the end-of-window snapshot on the registration.

        PRD §3.7: "On success the registration records `session_id`, writes
        `session_ends_at` as a snapshot of the chosen session's `ends_at`, the session's
        `seats_reserved` increases by 1 with its `status` recomputed — possibly flipping
        `OPEN → FULL` — and the session's `version` increments by 1."

        Design: Difficulty/compensating_invariant/seat_ledger_returns_to_zero_after_cancellation_and_the_freed_seat_is_reclaimable
        """
        session, registration_a, _registration_b = _one_seat_session_with_two_rivals(api)
        assert session["seats_reserved"] == 0
        assert session["status"] == "OPEN"

        scheduled = validate_success(api.schedule_seat(
            registration_a["id"], f.schedule_seat_payload(session["id"], session["version"]),
            fx.EXAM_OPERATIONS), 200)

        assert scheduled["seat_status"] == "SCHEDULED"
        assert scheduled["session_id"] == session["id"]
        assert str(scheduled["session_ends_at"]).startswith("2026-08-10T04:00:00")

        after = fx.read_session(api, session["id"])
        assert after["seats_reserved"] == 1
        assert after["status"] == "FULL"
        assert after["version"] == session["version"] + 1
        ax.assert_seat_ledger_within_bounds(after)

    def test_the_rival_is_refused_and_the_refusal_moves_nothing(self, api):
        """A full session turns the second claim away without touching either the ledger
        or the session's concurrency token.

        PRD §3.7: "and the session's `seats_reserved` must be strictly below its
        `seat_capacity`, or `ERR_SESSION_FULL`."

        PRD §2.9: "A session's `seats_reserved` is recounted from the registrations
        pointing at it."

        Design: Difficulty/compensating_invariant/seat_ledger_returns_to_zero_after_cancellation_and_the_freed_seat_is_reclaimable
        """
        session, registration_a, registration_b = _one_seat_session_with_two_rivals(api)
        fx.schedule_seat(api, registration_a["id"], session["id"], session["version"])
        full = fx.read_session(api, session["id"])

        refused = api.schedule_seat(
            registration_b["id"], f.schedule_seat_payload(session["id"], full["version"]),
            fx.EXAM_OPERATIONS)

        validate_error(refused, ApiErrorId.ERR_SESSION_FULL.value, 409)
        assert fx.read_registration(api, registration_b["id"])["seat_status"] == "UNSCHEDULED"
        unchanged = fx.read_session(api, session["id"])
        assert unchanged["seats_reserved"] == 1
        assert unchanged["version"] == full["version"]

    def test_cancellation_returns_the_ledger_to_exactly_zero(self, api):
        """The compensation mirrors the claim: the count is zero, never negative, and the
        derived status is OPEN again.

        PRD §3.7: "The compensating side effects mirror the claim exactly: the previously
        held session's `seats_reserved` decreases by 1 with its `status` recomputed,
        possibly flipping `FULL → OPEN`, and its `version` increments by 1."

        Design: Difficulty/compensating_invariant/seat_ledger_returns_to_zero_after_cancellation_and_the_freed_seat_is_reclaimable
        """
        session, registration_a, _registration_b = _one_seat_session_with_two_rivals(api)
        fx.schedule_seat(api, registration_a["id"], session["id"], session["version"])
        full = fx.read_session(api, session["id"])

        validate_success(api.cancel_seat_schedule(
            registration_a["id"], CANCELLATION, fx.EXAM_OPERATIONS), 200)

        freed = fx.read_session(api, session["id"])
        assert freed["seats_reserved"] == 0
        assert freed["status"] == "OPEN"
        assert freed["version"] == full["version"] + 1
        ax.assert_seat_ledger_within_bounds(freed)

    def test_cancellation_retains_the_window_snapshot_and_spares_the_score(self, api):
        """The registration returns to unscheduled with its session pointer cleared, yet
        the end-of-window snapshot survives and the score dimension never moves.

        PRD §3.7: "The registration's `session_id` is cleared, but `session_ends_at` is
        deliberately **retained**, because the retake-wait arithmetic reads it for
        sittings that were consumed rather than abandoned."

        Design: Difficulty/compensating_invariant/seat_ledger_returns_to_zero_after_cancellation_and_the_freed_seat_is_reclaimable
        """
        session, registration_a, _registration_b = _one_seat_session_with_two_rivals(api)
        fx.schedule_seat(api, registration_a["id"], session["id"], session["version"])

        cancelled = validate_success(api.cancel_seat_schedule(
            registration_a["id"], CANCELLATION, fx.EXAM_OPERATIONS), 200)

        assert cancelled["seat_status"] == "UNSCHEDULED"
        assert cancelled["session_id"] is None
        assert str(cancelled["session_ends_at"]).startswith("2026-08-10T04:00:00")
        assert cancelled["attempt_number"] == 1
        assert cancelled["score_status"] == "NOT_APPLICABLE"

    def test_the_freed_seat_is_reclaimable_and_the_ledger_reads_one_again(self, api):
        """The rival's identical claim now succeeds, which is only possible if the
        cancellation compensated the ledger precisely rather than approximately.

        PRD §3.7: "The session's `status` is `CLOSED` when the logical clock has reached
        or passed `starts_at`; otherwise it is `FULL` when `seats_reserved` is greater
        than or equal to `seat_capacity`; otherwise it is `OPEN`."

        Design: Difficulty/compensating_invariant/seat_ledger_returns_to_zero_after_cancellation_and_the_freed_seat_is_reclaimable
        """
        session, registration_a, registration_b = _one_seat_session_with_two_rivals(api)
        fx.schedule_seat(api, registration_a["id"], session["id"], session["version"])
        full = fx.read_session(api, session["id"])
        api.schedule_seat(registration_b["id"],
                          f.schedule_seat_payload(session["id"], full["version"]),
                          fx.EXAM_OPERATIONS)
        validate_success(api.cancel_seat_schedule(
            registration_a["id"], CANCELLATION, fx.EXAM_OPERATIONS), 200)
        freed = fx.read_session(api, session["id"])

        reclaimed = validate_success(api.schedule_seat(
            registration_b["id"], f.schedule_seat_payload(session["id"], freed["version"]),
            fx.EXAM_OPERATIONS), 200)

        assert reclaimed["seat_status"] == "SCHEDULED"
        retaken = fx.read_session(api, session["id"])
        assert retaken["seats_reserved"] == 1
        assert retaken["status"] == "FULL"
        assert retaken["version"] == freed["version"] + 1
