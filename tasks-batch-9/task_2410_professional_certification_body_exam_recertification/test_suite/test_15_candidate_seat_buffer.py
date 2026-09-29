"""One candidate, two seats: the buffer decides, not the room and not the attempt."""

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success

ABUTTING_SESSION = {"starts_at": "2026-08-10T04:00:00Z", "ends_at": "2026-08-10T08:00:00Z",
                    "center_code": "C1", "room_code": "R2"}
DISTANT_SESSION = {"starts_at": "2026-08-10T09:00:00Z", "ends_at": "2026-08-10T13:00:00Z",
                   "center_code": "C1", "room_code": "R3"}


def _held_seat_and_a_second_registration(api):
    """A candidate holding a seat in the morning session, plus a second, unscheduled
    registration on the same application.
    """
    state = fx.pipeline_through_scheduled_seat(api)
    second = fx.create_registration(api, state.application_id, state.form_id)
    return state, second


class TestCandidateSeatBuffer:
    """A second sitting is barred when abutting and admitted when five hours away."""

    def test_a_second_registration_is_created_with_no_attempt_consumed(self, api):
        """A merely scheduled sitting consumes nothing, so the second registration is
        still the first attempt and neither the attempt cap nor the retake wait fires.

        PRD §3.7: "Count the application's registrations whose `seat_status` is
        `COMPLETED` or `NO_SHOW` — that count is the application's
        `attempts_consumed`."

        PRD §3.7: "A `CANCELLED` or still-`UNSCHEDULED` registration consumes nothing
        and starts no wait, and a score that is later voided does not un-consume its
        attempt, because `seat_status` stays `COMPLETED` regardless of what happens to
        the score."

        Design: Difficulty/resource_temporal_overlap/candidate_seat_buffer_bars_an_abutting_second_sitting_but_admits_a_five_hour_gap
        """
        _state, second = _held_seat_and_a_second_registration(api)

        assert second["attempt_number"] == 1
        assert second["seat_status"] == "UNSCHEDULED"
        ax.assert_exam_registration(second)

    def test_an_abutting_session_in_another_room_still_collides_on_the_buffer(self, api):
        """The second session starts exactly when the first ends and sits in a different
        room, so only the padded candidate windows can refuse it.

        PRD §3.7: "The buffered collision test pads **both** sides of **both** windows
        by 120 minutes: a conflict exists when the new session's `starts_at` less 120
        minutes is at or before the existing session's `ends_at` plus 120 minutes, and
        the existing session's `starts_at` less 120 minutes is at or before the new
        session's `ends_at` plus 120 minutes."

        PRD §3.7: "Because both comparisons are inclusive, back-to-back sittings are
        rejected outright, a 119-minute gap between two windows is rejected, and a
        121-minute gap is allowed."

        Design: Difficulty/resource_temporal_overlap/candidate_seat_buffer_bars_an_abutting_second_sitting_but_admits_a_five_hour_gap
        """
        _state, second = _held_seat_and_a_second_registration(api)
        abutting = fx.create_test_center_session(api, **ABUTTING_SESSION)

        refused = api.schedule_seat(
            second["id"], f.schedule_seat_payload(abutting["id"], abutting["version"]),
            fx.EXAM_OPERATIONS)

        validate_error(refused, ApiErrorId.ERR_CANDIDATE_WINDOW_CONFLICT.value, 409)

    def test_the_refused_claim_leaves_the_registration_and_the_session_intact(self, api):
        """The rejected claim writes nothing: the registration is still unscheduled and
        the target session's ledger and version are unmoved.

        PRD §3.7: "On success the registration records `session_id`, writes
        `session_ends_at` as a snapshot of the chosen session's `ends_at`, the session's
        `seats_reserved` increases by 1 with its `status` recomputed — possibly flipping
        `OPEN → FULL` — and the session's `version` increments by 1."

        PRD §2.9: "A session's `seats_reserved` is recounted from the registrations
        pointing at it."

        Design: Difficulty/resource_temporal_overlap/candidate_seat_buffer_bars_an_abutting_second_sitting_but_admits_a_five_hour_gap
        """
        _state, second = _held_seat_and_a_second_registration(api)
        abutting = fx.create_test_center_session(api, **ABUTTING_SESSION)
        offered_version = abutting["version"]

        api.schedule_seat(second["id"],
                          f.schedule_seat_payload(abutting["id"], offered_version),
                          fx.EXAM_OPERATIONS)

        assert fx.read_registration(api, second["id"])["seat_status"] == "UNSCHEDULED"
        after = fx.read_session(api, abutting["id"])
        assert after["seats_reserved"] == 0
        assert after["version"] == offered_version

    def test_a_five_hour_gap_admits_the_second_sitting(self, api):
        """With the windows well clear of one another the claim succeeds and snapshots
        the chosen session's end.

        PRD §3.7: "On success the registration records `session_id`, writes
        `session_ends_at` as a snapshot of the chosen session's `ends_at`, the session's
        `seats_reserved` increases by 1 with its `status` recomputed — possibly flipping
        `OPEN → FULL` — and the session's `version` increments by 1."

        Design: Difficulty/resource_temporal_overlap/candidate_seat_buffer_bars_an_abutting_second_sitting_but_admits_a_five_hour_gap
        """
        _state, second = _held_seat_and_a_second_registration(api)
        abutting = fx.create_test_center_session(api, **ABUTTING_SESSION)
        api.schedule_seat(second["id"],
                          f.schedule_seat_payload(abutting["id"], abutting["version"]),
                          fx.EXAM_OPERATIONS)
        distant = fx.create_test_center_session(api, **DISTANT_SESSION)

        scheduled = validate_success(api.schedule_seat(
            second["id"], f.schedule_seat_payload(distant["id"], distant["version"]),
            fx.EXAM_OPERATIONS), 200)

        assert scheduled["seat_status"] == "SCHEDULED"
        assert scheduled["session_id"] == distant["id"]
        assert str(scheduled["session_ends_at"]).startswith("2026-08-10T13:00:00")
        assert scheduled["score_status"] == "NOT_APPLICABLE"

    def test_the_candidate_legitimately_holds_two_distant_seats(self, api):
        """Both sittings are reserved at once, each session counting one seat, because
        the buffer bars proximity rather than plurality.

        PRD §2.7: "**Candidate window.** A candidate may not hold two seats whose
        buffered windows intersect → otherwise `ERR_CANDIDATE_WINDOW_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/candidate_seat_buffer_bars_an_abutting_second_sitting_but_admits_a_five_hour_gap
        """
        state, second = _held_seat_and_a_second_registration(api)
        distant = fx.create_test_center_session(api, **DISTANT_SESSION)

        validate_success(api.schedule_seat(
            second["id"], f.schedule_seat_payload(distant["id"], distant["version"]),
            fx.EXAM_OPERATIONS), 200)

        assert fx.read_registration(api, state.registration_id)["seat_status"] == "SCHEDULED"
        assert fx.read_session(api, state.session_id)["seats_reserved"] == 1
        assert fx.read_session(api, distant["id"])["seats_reserved"] == 1
