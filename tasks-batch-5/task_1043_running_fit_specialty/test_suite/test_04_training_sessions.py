"""Training sessions: coach vs. store-room calendar contention, enrollment
preconditions, waitlist promotion cascade, and session-cancel cascade."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_member_headers,
    TEST_USERS,
    fixtures as fx,
)
import test_helpers.factories as f

SM = TEST_USERS["store_manager_headers"]


def test_second_overlapping_session_exceeds_room_count_rejected(api):
    """PRD §3.4: "A new session is admitted only while the number of existing
    `SCHEDULED` sessions at that store whose half-open windows overlap the requested
    window is strictly less than `session_room_count`; if admitting it would meet or
    exceed that room count, the request is rejected with `ERR_SESSION_ROOM_CONFLICT`
    (409)."

    Design: Difficulty/resource_temporal_overlap/session_aggregate_room_conflict_on_store
    """
    store = fx.new_store(api, session_room_count=1)
    c1 = fx.new_staff(api, store["id"], role_type="COACH")
    c2 = fx.new_staff(api, store["id"], role_type="COACH")
    fx.new_session(api, c1["id"], store["id"], level="BEGINNER",
                   start_at="2026-07-12T10:00:00Z", end_at="2026-07-12T11:00:00Z", capacity=10)
    resp = api.create_session(
        f.create_session_payload(c2["id"], store["id"], level="INTERMEDIATE",
                                 start_at="2026-07-12T10:30:00Z", end_at="2026-07-12T11:30:00Z", capacity=10),
        SM,
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_ROOM_CONFLICT, 409)


def test_non_overlapping_session_admitted_within_room_count(api):
    """PRD §3.4: "A new session is admitted only while the number of existing
    `SCHEDULED` sessions at that store whose half-open windows overlap the requested
    window is strictly less than `session_room_count`; if admitting it would meet or
    exceed that room count, the request is rejected with `ERR_SESSION_ROOM_CONFLICT`
    (409)."

    Design: Difficulty/resource_temporal_overlap/session_aggregate_room_conflict_on_store
    """
    store = fx.new_store(api, session_room_count=1)
    c1 = fx.new_staff(api, store["id"], role_type="COACH")
    c2 = fx.new_staff(api, store["id"], role_type="COACH")
    fx.new_session(api, c1["id"], store["id"], level="BEGINNER",
                   start_at="2026-07-12T10:00:00Z", end_at="2026-07-12T11:00:00Z", capacity=10)
    # Back-to-back window does not overlap, so no room is occupied at its time.
    data = validate_success(
        api.create_session(
            f.create_session_payload(c2["id"], store["id"], level="INTERMEDIATE",
                                     start_at="2026-07-12T11:00:00Z", end_at="2026-07-12T12:00:00Z", capacity=10),
            SM,
        ),
        201,
    )
    assert data["status"] == "SCHEDULED"


def test_same_coach_overlap_rejected(api):
    """PRD §3.4: "if any other `SCHEDULED` session led by the same coach has a
    half-open window `[start_at, end_at)` that overlaps the requested window, the
    request is rejected with `ERR_COACH_UNAVAILABLE` (409); back-to-back sessions
    that merely touch at an endpoint do not overlap and are allowed."

    Design: Corner/validations/coach_overlap_returns_coach_unavailable
    """
    store = fx.new_store(api, session_room_count=5)
    c1 = fx.new_staff(api, store["id"], role_type="COACH")
    fx.new_session(api, c1["id"], store["id"], level="BEGINNER",
                   start_at="2026-07-12T10:00:00Z", end_at="2026-07-12T11:00:00Z", capacity=10)
    resp = api.create_session(
        f.create_session_payload(c1["id"], store["id"], level="BEGINNER",
                                 start_at="2026-07-12T10:30:00Z", end_at="2026-07-12T11:30:00Z", capacity=10),
        SM,
    )
    validate_error(resp, ApiErrorId.ERR_COACH_UNAVAILABLE, 409)


def test_enroll_into_cancelled_session_rejected(api):
    """PRD §3.4: "Enrollment requires the parent session to be `SCHEDULED`; an
    enrollment attempt against a session that is not `SCHEDULED` is rejected with
    `ERR_SESSION_NOT_SCHEDULED` (409)."

    Design: Difficulty/cross_entity_state_dependency/enroll_requires_parent_session_scheduled
    """
    store = fx.new_store(api)
    coach = fx.new_staff(api, store["id"], role_type="COACH")
    member = fx.new_member(api)
    session = fx.new_session(api, coach["id"], store["id"], capacity=2,
                             start_at="2026-07-12T09:00:00Z", end_at="2026-07-12T10:00:00Z")
    from test_helpers import get_success_data
    get_success_data(api.cancel_session(session["id"], SM))
    resp = api.create_enrollment(session["id"], f.create_enrollment_payload(member["id"]), make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_SCHEDULED, 409)


def test_enroll_into_scheduled_session_creates_enrolled(api):
    """PRD §3.4: "When the session has room — `enrolled_count` is strictly less than
    `capacity` — the new enrollment is created `ENROLLED` and `enrolled_count`
    increments by one."

    Design: Difficulty/cross_entity_state_dependency/enroll_requires_parent_session_scheduled
    """
    store = fx.new_store(api)
    coach = fx.new_staff(api, store["id"], role_type="COACH")
    member = fx.new_member(api)
    session = fx.new_session(api, coach["id"], store["id"], capacity=2,
                             start_at="2026-07-12T09:00:00Z", end_at="2026-07-12T10:00:00Z")
    data = validate_success(
        api.create_enrollment(session["id"], f.create_enrollment_payload(member["id"]), make_member_headers(member["id"])),
        201,
    )
    assert data["status"] == "ENROLLED"


def test_enrolled_cancel_promotes_waitlisted_count_preserved(api):
    """PRD §3.4: "Cancelling an `ENROLLED` seat decrements the session's
    `enrolled_count` by one and then, if any `WAITLISTED` enrollment exists for that
    session, promotes the one with the earliest `created_at` from `WAITLISTED` to
    `ENROLLED`, which itself re-increments `enrolled_count` by one — a net-zero swap
    that hands the freed seat to the longest-waiting member."

    Design: Difficulty/transitive_cascade/enrollment_cancel_cascades_waitlist_promotion
    """
    store = fx.new_store(api)
    coach = fx.new_staff(api, store["id"], role_type="COACH")
    m1 = fx.new_member(api)
    m2 = fx.new_member(api)
    session = fx.new_session(api, coach["id"], store["id"], capacity=1,
                             start_at="2026-07-12T09:00:00Z", end_at="2026-07-12T10:00:00Z")
    en1 = fx.enroll(api, session["id"], m1["id"])
    fx.enroll(api, session["id"], m2["id"])
    from test_helpers import get_success_data
    cancelled = get_success_data(api.cancel_enrollment(en1["id"], make_member_headers(m1["id"])))
    assert cancelled["status"] == "CANCELLED"
    assert fx.get_session(api, session["id"])["enrolled_count"] == 1


def test_enrolled_cancel_promotes_earliest_waitlisted(api):
    """PRD §3.4: "Cancelling an `ENROLLED` seat decrements the session's
    `enrolled_count` by one and then, if any `WAITLISTED` enrollment exists for that
    session, promotes the one with the earliest `created_at` from `WAITLISTED` to
    `ENROLLED`, which itself re-increments `enrolled_count` by one — a net-zero swap
    that hands the freed seat to the longest-waiting member."

    Design: Difficulty/transitive_cascade/enrollment_cancel_cascades_waitlist_promotion
    """
    store = fx.new_store(api)
    coach = fx.new_staff(api, store["id"], role_type="COACH")
    m1 = fx.new_member(api)
    m2 = fx.new_member(api)
    session = fx.new_session(api, coach["id"], store["id"], capacity=1,
                             start_at="2026-07-12T09:00:00Z", end_at="2026-07-12T10:00:00Z")
    en1 = fx.enroll(api, session["id"], m1["id"])
    en2 = fx.enroll(api, session["id"], m2["id"])
    from test_helpers import get_success_data
    get_success_data(api.cancel_enrollment(en1["id"], make_member_headers(m1["id"])))
    assert fx.get_enrollment(api, en2["id"])["status"] == "ENROLLED"


def test_session_cancel_cascades_all_enrollments(api):
    """PRD §3.4: "Cancellation cascades: every enrollment of that session currently
    in `ENROLLED` or `WAITLISTED` transitions to `CANCELLED`, and the session's
    `enrolled_count` is set to 0."

    Design: Corner/state_machines/session_cancel_cascades_all_enrollments_to_cancelled
    """
    store = fx.new_store(api)
    coach = fx.new_staff(api, store["id"], role_type="COACH")
    ma = fx.new_member(api)
    mb = fx.new_member(api)
    session = fx.new_session(api, coach["id"], store["id"], capacity=2,
                             start_at="2026-07-12T09:00:00Z", end_at="2026-07-12T10:00:00Z")
    ena = fx.enroll(api, session["id"], ma["id"])
    enb = fx.enroll(api, session["id"], mb["id"])
    from test_helpers import get_success_data
    cancelled = get_success_data(api.cancel_session(session["id"], SM))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["enrolled_count"] == 0
    assert fx.get_enrollment(api, ena["id"])["status"] == "CANCELLED"
    assert fx.get_enrollment(api, enb["id"])["status"] == "CANCELLED"
