"""Bookings: seat gate ordering, exact-fill waitlist flip, enrolment gate,
duplicates, participant overlap, and cancel-promote conservation."""
from test_helpers import (
    ApiErrorId,
    apply_to_study,
    approve_application,
    book_session,
    create_remote_session,
    create_study,
    enroll_participant,
    get_booking,
    get_pending_signature,
    get_session,
    get_success_data,
    make_participant_headers,
    register_participant,
    set_clock,
    setup_study_with_published_nda,
    sign_signature,
    start_review,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
RESEARCHER = TEST_USERS["researcher_headers"]


def _enroll_all(study_id, participants):
    for p in participants:
        enroll_participant(study_id, p)


def _setup_two_enrolled(emails=("cf3-a@x.com", "cf3-b@x.com")):
    study, nda = setup_study_with_published_nda()
    participants = [register_participant(email=e, age_years=25 + i)
                    for i, e in enumerate(emails)]
    _enroll_all(study["id"], participants)
    return study, participants


def _setup_approved_not_enrolled():
    """Participant APPROVED (PENDING signature, unsigned) — not ENROLLED."""
    study, nda = setup_study_with_published_nda(code="CE1")
    participant = register_participant(email="ce1-p@x.com")
    app = start_review(apply_to_study(study["id"], participant["id"])["id"])
    app = approve_application(app["id"])
    assert app["status"] == "APPROVED"
    session = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                                    "2026-08-10T11:00:00Z", seat_capacity=5)
    return study, participant, session


class TestSeatGateEvaluationOrder:
    def test_second_booking_on_capacity_two_lands_booked(self, api):
        """PRD §3.5: "The seat gate is evaluated before the booking is
        inserted: if `seats_taken` is strictly below `seat_capacity`, the
        booking lands `BOOKED` and `seats_taken` increments by one; otherwise
        it lands `WAITLISTED` and no seat is consumed."

        Design: Difficulty/combinatorial_formula/seat_gate_evaluation_order_pinned
        """
        study, (pa, pb) = _setup_two_enrolled()
        session = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                                        "2026-08-10T11:00:00Z", seat_capacity=2)
        first = book_session(session["id"], pa["id"])
        assert first["status"] == "BOOKED", "seats_taken 0 < 2"
        # The gate reads seats_taken BEFORE insert: 1 < 2 -> BOOKED.
        # An insert-then-evaluate order would wrongly waitlist this booking.
        second = book_session(session["id"], pb["id"])
        assert second["status"] == "BOOKED", "gate evaluated on the pre-insert count"
        assert get_session(session["id"])["seats_taken"] == 2

    def test_seats_taken_matches_seat_holding_booking_count(self, api):
        """PRD §3.5: "`seats_taken` always counts bookings in `BOOKED`,
        `PROMOTED`, `ATTENDED`, or `NO_SHOW`."

        Design: Difficulty/combinatorial_formula/seat_gate_evaluation_order_pinned
        """
        study, (pa, pb) = _setup_two_enrolled()
        session = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                                        "2026-08-10T11:00:00Z", seat_capacity=2)
        book_session(session["id"], pa["id"])
        book_session(session["id"], pb["id"])
        seat_holding = get_success_data(api.list_bookings(
            ADMIN, params={"session_id": session["id"]}))
        holders = [b for b in seat_holding
                   if b["status"] in ("BOOKED", "PROMOTED", "ATTENDED", "NO_SHOW")]
        assert len(holders) == 2
        assert get_session(session["id"])["seats_taken"] == len(holders)


class TestSeatCapacityExactFill:
    def _setup_capacity_one(self):
        study, (pa, pb) = _setup_two_enrolled(emails=("bp1-a@x.com", "bp1-b@x.com"))
        session = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                                        "2026-08-10T11:00:00Z", seat_capacity=1)
        return session, pa, pb

    def test_booking_at_exact_capacity_flips_to_waitlist(self, api):
        """PRD §3.5: "if `seats_taken` is strictly below `seat_capacity`, the
        booking lands `BOOKED` and `seats_taken` increments by one; otherwise
        it lands `WAITLISTED` and no seat is consumed."

        Design: Difficulty/boundary_precision_check/seat_capacity_exact_fill_flips_to_waitlist
        """
        session, pa, pb = self._setup_capacity_one()
        first = book_session(session["id"], pa["id"])
        assert first["status"] == "BOOKED", "seats_taken 0 < 1"
        # Boundary: seats_taken == seat_capacity (1 == 1) -> WAITLISTED, not an error.
        second = validate_success(api.create_booking(
            {"session_id": session["id"]}, make_participant_headers(pb["id"])),
            expected_status=201)
        assert second["status"] == "WAITLISTED"

    def test_waitlisted_booking_consumes_no_seat(self, api):
        """PRD §3.5: "otherwise it lands `WAITLISTED` and no seat is consumed.
        `seats_taken` always counts bookings in `BOOKED`, `PROMOTED`,
        `ATTENDED`, or `NO_SHOW`."

        Design: Difficulty/boundary_precision_check/seat_capacity_exact_fill_flips_to_waitlist
        """
        session, pa, pb = self._setup_capacity_one()
        book_session(session["id"], pa["id"])
        book_session(session["id"], pb["id"])
        assert get_booking(get_success_data(api.list_bookings(
            ADMIN, params={"session_id": session["id"], "status": "WAITLISTED"}))[0]["id"]
        )["status"] == "WAITLISTED"
        assert get_session(session["id"])["seats_taken"] == 1, (
            "waitlist entries never occupy a seat")


class TestBookingRequiresEnrolledApplication:
    def test_approved_but_unsigned_participant_cannot_book(self, api):
        """PRD §3.5: "the participant must hold an `ENROLLED` application in
        the session's study (`ERR_NOT_ENROLLED`)"

        Design: Difficulty/cross_entity_state_dependency/booking_requires_enrolled_application
        """
        _study, participant, session = _setup_approved_not_enrolled()
        resp = api.create_booking({"session_id": session["id"]},
                                  make_participant_headers(participant["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_ENROLLED)

    def test_rejected_booking_creates_nothing_and_holds_no_seat(self, api):
        """PRD §3.5: "the participant must hold an `ENROLLED` application in
        the session's study (`ERR_NOT_ENROLLED`)"
        PRD §2.5: "All state changes are atomic and immediately consistent"

        Design: Difficulty/cross_entity_state_dependency/booking_requires_enrolled_application
        """
        _study, participant, session = _setup_approved_not_enrolled()
        validate_error(api.create_booking(
            {"session_id": session["id"]},
            make_participant_headers(participant["id"])), ApiErrorId.ERR_NOT_ENROLLED)
        bookings = get_success_data(api.list_bookings(
            ADMIN, params={"session_id": session["id"]}))
        assert bookings == [], "no booking was created"
        assert get_session(session["id"])["seats_taken"] == 0


def test_booking_into_cancelled_session_returns_not_bookable(api):
    """PRD §3.5: "The session must be `SCHEDULED` (`ERR_SESSION_NOT_BOOKABLE`)"
    PRD §2.9: "`ERR_SESSION_NOT_BOOKABLE` for a booking into a session that is
    not `SCHEDULED`"

    Design: Corner/validations/booking_into_cancelled_session_returns_not_bookable
    """
    study, nda = setup_study_with_published_nda(code="NB1")
    participant = register_participant(email="nb-p@x.com")
    enroll_participant(study["id"], participant)
    session = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                                    "2026-08-10T11:00:00Z", seat_capacity=5)
    get_success_data(api.cancel_session(session["id"], ADMIN))
    resp = api.create_booking({"session_id": session["id"]},
                              make_participant_headers(participant["id"]))
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_BOOKABLE)


def test_duplicate_booking_rejected(api):
    """PRD §3.5: "no non-terminal booking may already exist for the pair —
    `BOOKED`, `WAITLISTED`, or `PROMOTED` all block with
    `ERR_DUPLICATE_BOOKING`"

    Design: Corner/validations/duplicate_booking_rejected
    """
    study, nda = setup_study_with_published_nda(code="DB1")
    participant = register_participant(email="db-p@x.com")
    enroll_participant(study["id"], participant)
    session = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                                    "2026-08-10T11:00:00Z", seat_capacity=5)
    book_session(session["id"], participant["id"])
    resp = api.create_booking({"session_id": session["id"]},
                              make_participant_headers(participant["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BOOKING)


def test_participant_touching_sessions_conflict(api):
    """PRD §2.8: "A **participant** is occupied by sessions on which they hold
    a booking in `BOOKED` or `PROMOTED` under closed-interval semantics: a new
    window conflicts whenever its `starts_at` falls at or before the existing
    window's `ends_at` and the existing window's `starts_at` falls at or before
    the new window's `ends_at`. Unlike stations, touching endpoints do conflict
    here, and violations are rejected with `ERR_PARTICIPANT_CONFLICT`."

    Design: Corner/validations/participant_touching_sessions_conflict
    """
    study, nda = setup_study_with_published_nda(code="PC1")
    participant = register_participant(email="pc-p@x.com")
    enroll_participant(study["id"], participant)
    s1 = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                               "2026-08-10T11:00:00Z", seat_capacity=5)
    s2 = create_remote_session(study["id"], "2026-08-10T11:00:00Z",
                               "2026-08-10T12:00:00Z", seat_capacity=5)
    book_session(s1["id"], participant["id"])
    # Closed intervals: s2.starts_at == s1.ends_at touches -> conflict.
    resp = api.create_booking({"session_id": s2["id"]},
                              make_participant_headers(participant["id"]))
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_CONFLICT)


class TestCancelPromoteConservesSeats:
    def _setup_booked_plus_waitlisted(self):
        study, (pa, pb) = _setup_two_enrolled(emails=("ci1-a@x.com", "ci1-b@x.com"))
        session = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                                        "2026-08-10T11:00:00Z", seat_capacity=1)
        bk_a = book_session(session["id"], pa["id"])
        bk_b = book_session(session["id"], pb["id"])
        assert bk_a["status"] == "BOOKED" and bk_b["status"] == "WAITLISTED"
        assert get_session(session["id"])["seats_taken"] == 1
        return session, pa, pb, bk_a, bk_b

    def test_cancel_promotes_waitlisted_and_conserves_seats(self, api):
        """PRD §3.5: "Cancelling a held seat decrements `seats_taken` by one
        and then promotes the earliest-created eligible waitlisted booking on
        the same session"
        PRD §3.5: "A promotion moves that booking `WAITLISTED` → `PROMOTED` and
        increments `seats_taken` by one, so a cancel-plus-promotion pair leaves
        `seats_taken` unchanged"

        Design: Difficulty/compensating_invariant/cancel_promote_conserves_seats_taken
        """
        session, pa, _pb, bk_a, bk_b = self._setup_booked_plus_waitlisted()
        cancelled = validate_success(api.cancel_booking(
            bk_a["id"], make_participant_headers(pa["id"])))
        assert cancelled["status"] == "CANCELLED"
        assert get_booking(bk_b["id"])["status"] == "PROMOTED"
        assert get_session(session["id"])["seats_taken"] == 1, (
            "the cancel + promote pair conserves seats_taken")

    def test_seats_taken_reconciles_with_booking_states_after_promotion(self, api):
        """PRD §3.5: "`seats_taken` always counts bookings in `BOOKED`,
        `PROMOTED`, `ATTENDED`, or `NO_SHOW`."

        Design: Difficulty/compensating_invariant/cancel_promote_conserves_seats_taken
        """
        session, pa, _pb, bk_a, bk_b = self._setup_booked_plus_waitlisted()
        get_success_data(api.cancel_booking(bk_a["id"], make_participant_headers(pa["id"])))
        all_bookings = get_success_data(api.list_bookings(
            ADMIN, params={"session_id": session["id"]}))
        holders = [b for b in all_bookings
                   if b["status"] in ("BOOKED", "PROMOTED", "ATTENDED", "NO_SHOW")]
        assert len(holders) == 1 and holders[0]["id"] == bk_b["id"]
        assert get_session(session["id"])["seats_taken"] == len(holders)


def test_waitlist_promotion_fifo_order(api):
    """PRD §3.5: "Cancelling a held seat decrements `seats_taken` by one and
    then promotes the earliest-created eligible waitlisted booking on the same
    session: eligible means `WAITLISTED` with an owning participant still
    `ACTIVE`, ranked by `created_at` ascending, with ties impossible because
    creation timestamps are server-stamped and distinct."

    Design: Corner/state_machines/waitlist_promotion_fifo_order
    """
    study, (pa, pb, pc) = _setup_two_enrolled(
        emails=("fifo-a@x.com", "fifo-b@x.com", "fifo-c@x.com"))
    session = create_remote_session(study["id"], "2026-08-10T10:00:00Z",
                                    "2026-08-10T11:00:00Z", seat_capacity=1)
    bk_a = book_session(session["id"], pa["id"])
    bk_b = book_session(session["id"], pb["id"])  # earliest waitlisted
    bk_c = book_session(session["id"], pc["id"])  # later waitlisted
    assert bk_b["status"] == "WAITLISTED" and bk_c["status"] == "WAITLISTED"
    get_success_data(api.cancel_booking(bk_a["id"], make_participant_headers(pa["id"])))
    assert get_booking(bk_b["id"])["status"] == "PROMOTED", (
        "the earliest-created waitlisted booking wins the freed seat")
    assert get_booking(bk_c["id"])["status"] == "WAITLISTED", (
        "the later arrival keeps waiting")
