"""Signing sessions and tickets: open/close/reconcile, admit gates, bonus math."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    assert_ticket,
    create_session_payload,
    create_ticket_payload,
    make_school,
    make_publisher,
    make_author,
    make_fair,
    make_fair_open,
    make_confirmed_booking,
    make_travel_booked_booking,
    make_session,
    TEST_USERS,
)

ORG = TEST_USERS["organizer_headers"]
LINESTAFF = TEST_USERS["linestaff_headers"]


def _open_fair_with_booking(bonus_threshold=3, bonus_base=1000, bonus_per=100):
    """Fair OPEN; author booking TRAVEL_BOOKED; returns (school, pub, author, fair, agr, lines, booking)."""
    school = make_school()
    pub = make_publisher()
    author = make_author()
    fair, agr, lines = make_fair_open(school["id"], pub["id"])
    booking = make_travel_booked_booking(
        fair["id"], author["id"],
        bonus_threshold_attendees=bonus_threshold,
        bonus_base_cents=bonus_base,
        bonus_per_attendee_cents=bonus_per,
    )
    return school, pub, author, fair, agr, lines, booking


class TestTicketResourceShape:
    def test_signing_ticket_immutable_no_version_field(self, api):
        """PRD §2.4: "The single exception is the `SigningTicket`: tickets are
        high-volume line entitlements and carry only `id` and `created_at` —
        both `updated_at` and `version` are absent from ticket resources."
        PRD §3.5: "The issued record's `kind` is derived from the session's
        `mode` at issue time — `TICKET` for a `TICKETED` session, `WRISTBAND`
        for a `FREE` one — and its status starts `ISSUED`."

        Design: Corner/entities/signing_ticket_immutable_no_version_field
        """
        school, pub, author, fair, agr, lines, booking = _open_fair_with_booking()
        session = make_session(booking["id"], fair["id"], mode="TICKETED")
        ticket = validate_success(api.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name="Kid One"),
            LINESTAFF,
        ), expected_status=201)
        assert ticket["kind"] == "TICKET"
        assert ticket["status"] == "ISSUED"
        assert ticket["id"]
        assert ticket["created_at"]
        assert "version" not in ticket
        assert "updated_at" not in ticket

    def test_signing_ticket_kind_derived_from_free_session(self, api):
        """PRD §3.5: "The issued record's `kind` is derived from the session's
        `mode` at issue time — `TICKET` for a `TICKETED` session, `WRISTBAND`
        for a `FREE` one"

        Design: Corner/entities/signing_ticket_immutable_no_version_field
        """
        school, pub, author, fair, agr, lines, booking = _open_fair_with_booking()
        session = make_session(booking["id"], fair["id"], mode="FREE")
        ticket = validate_success(api.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name="Kid One"),
            LINESTAFF,
        ), expected_status=201)
        assert ticket["kind"] == "WRISTBAND"
        assert_ticket(ticket)


class TestOpenSigning:
    def test_session_open_requires_booking_travel_booked(self, api):
        """PRD §3.5: "the session's booking must be `TRAVEL_BOOKED`
        (`ERR_BOOKING_NOT_TRAVEL_READY`, HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/session_open_requires_booking_travel_booked
        """
        school = make_school()
        pub = make_publisher()
        author = make_author()
        fair, agr, lines = make_fair_open(school["id"], pub["id"])
        # Booking accepted but travel NOT booked -> CONFIRMED
        booking = make_confirmed_booking(fair["id"], author["id"])
        session = make_session(
            booking["id"], fair["id"],
            start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T11:00:00Z",
        )
        validate_success(api.set_clock({"to_iso8601": "2026-08-10T10:05:00Z"}, ORG))
        resp = api.open_signing(session["id"], LINESTAFF)
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_TRAVEL_READY)
        after = validate_success(api.get_session(session["id"], ORG))
        assert after["status"] == "SCHEDULED"

    def test_session_open_succeeds_when_booking_travel_booked(self, api):
        """PRD §3.5: "the session's booking must be `TRAVEL_BOOKED`
        (`ERR_BOOKING_NOT_TRAVEL_READY`, HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/session_open_requires_booking_travel_booked
        """
        school, pub, author, fair, agr, lines, booking = _open_fair_with_booking()
        session = make_session(
            booking["id"], fair["id"],
            start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T11:00:00Z",
        )
        validate_success(api.set_clock({"to_iso8601": "2026-08-10T10:05:00Z"}, ORG))
        ok = validate_success(api.open_signing(session["id"], LINESTAFF))
        assert ok["status"] == "OPEN_FOR_SIGNING"

    def test_open_signing_outside_window_rejected(self, api):
        """PRD §3.5: "the logical clock must fall within the session's
        `start_at`-to-`end_at` window with both endpoints included
        (`ERR_OUTSIDE_SIGNING_WINDOW`, HTTP 409)"

        Design: Corner/cross_cutting_complexity_layers/open_signing_outside_window_rejected
        """
        school, pub, author, fair, agr, lines, booking = _open_fair_with_booking()
        session = make_session(
            booking["id"], fair["id"],
            start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T11:00:00Z",
        )
        # 09:05 is outside the window
        validate_success(api.set_clock({"to_iso8601": "2026-08-10T09:05:00Z"}, ORG))
        resp = api.open_signing(session["id"], LINESTAFF)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_SIGNING_WINDOW)
        # Exactly at window start (inclusive) succeeds
        validate_success(api.set_clock({"to_iso8601": "2026-08-10T10:00:00Z"}, ORG))
        ok = validate_success(api.open_signing(session["id"], LINESTAFF))
        assert ok["status"] == "OPEN_FOR_SIGNING"


class TestFloorCapacity:
    def test_signing_session_closed_interval_aggregate_capacity(self, api):
        """PRD §2.8: "Creating a session is rejected with
        `ERR_SIGNING_FLOOR_CAPACITY_EXCEEDED` (HTTP 409) when the sum of
        `line_space_units` over the fair's non-`CANCELLED` sessions whose closed
        windows intersect the candidate's closed window, plus the candidate's
        own `line_space_units`, would exceed the fair's
        `signing_floor_capacity_units`. Two sessions whose windows merely touch
        at an endpoint do overlap under this regime — the opposite of the
        venue-calendar rule."

        Design: Difficulty/resource_temporal_overlap/signing_session_closed_interval_aggregate_capacity
        """
        school = make_school()
        pub = make_publisher()
        author = make_author()
        fair, agr, lines = make_fair_open(
            school["id"], pub["id"], signing_floor_capacity_units=10
        )
        booking = make_travel_booked_booking(fair["id"], author["id"])
        session1 = make_session(
            booking["id"], fair["id"], mode="TICKETED",
            start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T11:00:00Z",
            line_space_units=6,
        )
        # 5 units touching at 11:00 — closed interval counts this as overlap: 6+5=11 > 10
        resp_over = api.create_session(
            create_session_payload(
                booking_id=booking["id"], fair_id=fair["id"], mode="FREE",
                start_at="2026-08-10T11:00:00Z", end_at="2026-08-10T12:00:00Z",
                line_space_units=5, capacity_seats=20, admit_concurrent_cap=10,
            ), ORG,
        )
        validate_error(resp_over, ApiErrorId.ERR_SIGNING_FLOOR_CAPACITY_EXCEEDED)

        # 4 units at the same window: 6+4=10 <= 10 — equality admitted
        resp_ok = api.create_session(
            create_session_payload(
                booking_id=booking["id"], fair_id=fair["id"], mode="FREE",
                start_at="2026-08-10T11:00:00Z", end_at="2026-08-10T12:00:00Z",
                line_space_units=4, capacity_seats=20, admit_concurrent_cap=10,
            ), ORG,
        )
        data_ok = validate_success(resp_ok, expected_status=201)
        assert data_ok["status"] == "SCHEDULED"

        after1 = validate_success(api.get_session(session1["id"], ORG))
        assert after1["status"] == "SCHEDULED"

    def test_signing_session_capacity_disjoint_windows(self, api):
        """PRD §2.8: "Creating a session is rejected with
        `ERR_SIGNING_FLOOR_CAPACITY_EXCEEDED` (HTTP 409) when the sum of
        `line_space_units` over the fair's non-`CANCELLED` sessions whose closed
        windows intersect the candidate's closed window, plus the candidate's
        own `line_space_units`, would exceed the fair's
        `signing_floor_capacity_units`."

        Design: Difficulty/resource_temporal_overlap/signing_session_closed_interval_aggregate_capacity
        """
        school = make_school()
        pub = make_publisher()
        author = make_author()
        fair, agr, lines = make_fair_open(
            school["id"], pub["id"], signing_floor_capacity_units=10
        )
        booking = make_travel_booked_booking(fair["id"], author["id"])
        make_session(
            booking["id"], fair["id"], mode="TICKETED",
            start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T11:00:00Z",
            line_space_units=10,
        )
        # A disjoint window does not intersect; full 10 units admitted
        resp = api.create_session(
            create_session_payload(
                booking_id=booking["id"], fair_id=fair["id"], mode="FREE",
                start_at="2026-08-10T12:00:00Z", end_at="2026-08-10T13:00:00Z",
                line_space_units=10, capacity_seats=20, admit_concurrent_cap=10,
            ), ORG,
        )
        validate_success(resp, expected_status=201)


class TestAdmitGates:
    def test_admit_rejected_when_session_not_signing(self, api):
        """PRD §3.5: "first the **payload** session's state — it must be
        `OPEN_FOR_SIGNING` (`ERR_SESSION_NOT_SIGNING`, HTTP 409)"

        Design: Corner/errors/admit_rejected_when_session_not_signing
        """
        school, pub, author, fair, agr, lines, booking = _open_fair_with_booking()
        session = make_session(booking["id"], fair["id"], mode="TICKETED")
        ticket = validate_success(api.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name="Kid One"),
            LINESTAFF,
        ), expected_status=201)
        # Session still SCHEDULED (never opened)
        resp = api.admit_ticket(ticket["id"], {"session_id": session["id"]}, LINESTAFF)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_SIGNING)
        after = validate_success(api.get_ticket(ticket["id"], ORG))
        assert after["status"] == "ISSUED"

    def test_admit_wrong_session_referential_clean_leg(self, api):
        """PRD §3.5: "and only then the referential match — the payload
        `session_id` must equal the ticket's own `session_id`
        (`ERR_TICKET_SESSION_MISMATCH`, HTTP 409)."

        Design: Corner/errors/admit_wrong_session_referential_clean_leg
        """
        school, pub, author, fair, agr, lines, booking = _open_fair_with_booking()
        session1 = make_session(
            booking["id"], fair["id"],
            start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T11:00:00Z",
        )
        session2 = make_session(
            booking["id"], fair["id"],
            start_at="2026-08-10T12:00:00Z", end_at="2026-08-10T13:00:00Z",
        )
        validate_success(api.set_clock({"to_iso8601": "2026-08-10T10:05:00Z"}, ORG))
        validate_success(api.open_signing(session1["id"], LINESTAFF))
        ticket2 = validate_success(api.create_ticket(
            create_ticket_payload(session_id=session2["id"], holder_name="Kid Two"),
            LINESTAFF,
        ), expected_status=201)
        # Payload session is session1 (open, cap free) but ticket belongs to session2
        resp = api.admit_ticket(ticket2["id"], {"session_id": session1["id"]}, LINESTAFF)
        validate_error(resp, ApiErrorId.ERR_TICKET_SESSION_MISMATCH)
        after = validate_success(api.get_ticket(ticket2["id"], ORG))
        assert after["status"] == "ISSUED"

    def test_admit_safety_beats_referential(self, api):
        """PRD §3.5: "the checks run in a pinned order: first the **payload**
        session's state — it must be `OPEN_FOR_SIGNING`
        (`ERR_SESSION_NOT_SIGNING`, HTTP 409); then the fire-marshal safety cap
        on that same payload session — the count of its tickets currently
        `ADMITTED` must be below its `admit_concurrent_cap`
        (`ERR_LINE_CAPACITY_EXCEEDED`, HTTP 409); and only then the referential
        match — the payload `session_id` must equal the ticket's own
        `session_id` (`ERR_TICKET_SESSION_MISMATCH`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/admit_safety_beats_referential
        """
        school, pub, author, fair, agr, lines, booking = _open_fair_with_booking()
        session1 = make_session(
            booking["id"], fair["id"],
            start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T11:00:00Z",
            capacity_seats=4, admit_concurrent_cap=1,
        )
        session2 = make_session(
            booking["id"], fair["id"],
            start_at="2026-08-10T12:00:00Z", end_at="2026-08-10T13:00:00Z",
            capacity_seats=4, admit_concurrent_cap=1,
        )
        validate_success(api.set_clock({"to_iso8601": "2026-08-10T10:05:00Z"}, ORG))
        validate_success(api.open_signing(session1["id"], LINESTAFF))
        t1 = validate_success(api.create_ticket(
            create_ticket_payload(session_id=session1["id"], holder_name="Kid One"),
            LINESTAFF,
        ), expected_status=201)
        t2 = validate_success(api.create_ticket(
            create_ticket_payload(session_id=session2["id"], holder_name="Kid Two"),
            LINESTAFF,
        ), expected_status=201)
        # Fill the payload session's ADMITTED cap
        validate_success(api.admit_ticket(t1["id"], {"session_id": session1["id"]}, LINESTAFF))
        # Admitting t2 against session1 violates BOTH the cap and the referential
        # match; the safety check (priority 10) must fire first.
        resp = api.admit_ticket(t2["id"], {"session_id": session1["id"]}, LINESTAFF)
        validate_error(resp, ApiErrorId.ERR_LINE_CAPACITY_EXCEEDED)
        after = validate_success(api.get_ticket(t2["id"], ORG))
        assert after["status"] == "ISSUED"

    def test_admit_line_capacity_exceeded_clean(self, api):
        """PRD §3.5: "the fire-marshal safety cap on that same payload session —
        the count of its tickets currently `ADMITTED` must be below its
        `admit_concurrent_cap` (`ERR_LINE_CAPACITY_EXCEEDED`, HTTP 409)"

        Design: Difficulty/priority_pair_validation_conflict/admit_safety_beats_referential
        """
        school, pub, author, fair, agr, lines, booking = _open_fair_with_booking()
        session = make_session(
            booking["id"], fair["id"],
            capacity_seats=4, admit_concurrent_cap=1,
        )
        validate_success(api.set_clock({"to_iso8601": "2026-08-10T10:05:00Z"}, ORG))
        validate_success(api.open_signing(session["id"], LINESTAFF))
        t1 = validate_success(api.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name="Kid One"),
            LINESTAFF,
        ), expected_status=201)
        t2 = validate_success(api.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name="Kid Two"),
            LINESTAFF,
        ), expected_status=201)
        validate_success(api.admit_ticket(t1["id"], {"session_id": session["id"]}, LINESTAFF))
        # Same-session ticket, cap full
        resp = api.admit_ticket(t2["id"], {"session_id": session["id"]}, LINESTAFF)
        validate_error(resp, ApiErrorId.ERR_LINE_CAPACITY_EXCEEDED)


class TestCloseAndRedeem:
    def test_redeem_allowed_after_session_close(self, api):
        """PRD §3.5: "an `ADMITTED` ticket becomes `REDEEMED` while its session
        is `OPEN_FOR_SIGNING` or `CLOSED_FOR_SIGNING`"

        Design: Corner/state_machines/redeem_allowed_after_session_close
        """
        school, pub, author, fair, agr, lines, booking = _open_fair_with_booking()
        session = make_session(booking["id"], fair["id"], mode="TICKETED")
        validate_success(api.set_clock({"to_iso8601": "2026-08-10T10:05:00Z"}, ORG))
        validate_success(api.open_signing(session["id"], LINESTAFF))
        ticket = validate_success(api.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name="Kid One"),
            LINESTAFF,
        ), expected_status=201)
        validate_success(api.admit_ticket(ticket["id"], {"session_id": session["id"]}, LINESTAFF))
        validate_success(api.close_signing(session["id"], LINESTAFF))
        redeemed = validate_success(api.redeem_ticket(ticket["id"], LINESTAFF))
        assert redeemed["status"] == "REDEEMED"
        after_session = validate_success(api.get_session(session["id"], ORG))
        assert after_session["attendance_count"] == 1

    def test_close_signing_no_show_sweep(self, api):
        """PRD §3.5: "Two things happen atomically: every ticket still `ISSUED`
        is swept to `NO_SHOW`, and `attendance_count` is frozen as the number of
        `ADMITTED` tickets plus the number of `REDEEMED` tickets at that
        moment."
        PRD §3.5: "a `FREE` session always earns zero"

        Design: Corner/state_machines/close_signing_no_show_sweep
        """
        school, pub, author, fair, agr, lines, booking = _open_fair_with_booking()
        session = make_session(booking["id"], fair["id"], mode="FREE")
        validate_success(api.set_clock({"to_iso8601": "2026-08-10T10:05:00Z"}, ORG))
        validate_success(api.open_signing(session["id"], LINESTAFF))
        t1 = validate_success(api.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name="Kid One"),
            LINESTAFF,
        ), expected_status=201)
        t2 = validate_success(api.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name="Kid Two"),
            LINESTAFF,
        ), expected_status=201)
        validate_success(api.admit_ticket(t1["id"], {"session_id": session["id"]}, LINESTAFF))
        closed = validate_success(api.close_signing(session["id"], LINESTAFF))
        assert closed["attendance_count"] == 1
        after_t1 = validate_success(api.get_ticket(t1["id"], ORG))
        assert after_t1["status"] == "ADMITTED"
        assert after_t1["kind"] == "WRISTBAND"
        after_t2 = validate_success(api.get_ticket(t2["id"], ORG))
        assert after_t2["status"] == "NO_SHOW"
        reconciled = validate_success(api.reconcile_session(session["id"], ORG))
        assert reconciled["bonus_cents"] == 0
        assert reconciled["status"] == "RECONCILED"


class TestSigningBonus:
    def test_signing_bonus_attendance_exact_threshold(self, api):
        """PRD §3.5: "a `TICKETED` session earns zero when the frozen
        `attendance_count` is below the booking's `bonus_threshold_attendees`,
        and otherwise earns `bonus_base_cents` plus `bonus_per_attendee_cents`
        multiplied by the excess of attendance over the threshold — attendance
        exactly equal to the threshold triggers the bonus."

        Design: Difficulty/boundary_precision_check/signing_bonus_attendance_exact_threshold
        """
        school, pub, author, fair, agr, lines, booking = _open_fair_with_booking(
            bonus_threshold=3, bonus_base=1000, bonus_per=100
        )
        s1 = make_session(
            booking["id"], fair["id"], mode="TICKETED",
            start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T11:00:00Z",
            capacity_seats=10, admit_concurrent_cap=10,
        )
        s2 = make_session(
            booking["id"], fair["id"], mode="TICKETED",
            start_at="2026-08-10T12:00:00Z", end_at="2026-08-10T13:00:00Z",
            capacity_seats=10, admit_concurrent_cap=10,
        )
        # session1: 3 admitted
        validate_success(api.set_clock({"to_iso8601": "2026-08-10T10:05:00Z"}, ORG))
        validate_success(api.open_signing(s1["id"], LINESTAFF))
        for i in range(3):
            t = validate_success(api.create_ticket(
                create_ticket_payload(session_id=s1["id"], holder_name=f"Kid {i+1}"),
                LINESTAFF,
            ), expected_status=201)
            validate_success(api.admit_ticket(t["id"], {"session_id": s1["id"]}, LINESTAFF))
        validate_success(api.close_signing(s1["id"], LINESTAFF))

        # session2: 2 admitted
        validate_success(api.set_clock({"to_iso8601": "2026-08-10T12:05:00Z"}, ORG))
        validate_success(api.open_signing(s2["id"], LINESTAFF))
        for i in range(2):
            t = validate_success(api.create_ticket(
                create_ticket_payload(session_id=s2["id"], holder_name=f"Kid {i+4}"),
                LINESTAFF,
            ), expected_status=201)
            validate_success(api.admit_ticket(t["id"], {"session_id": s2["id"]}, LINESTAFF))
        validate_success(api.close_signing(s2["id"], LINESTAFF))

        rec1 = validate_success(api.reconcile_session(s1["id"], ORG))
        rec2 = validate_success(api.reconcile_session(s2["id"], ORG))
        assert rec1["attendance_count"] == 3
        assert rec1["bonus_cents"] == 1000
        assert rec2["attendance_count"] == 2
        assert rec2["bonus_cents"] == 0

        booking_after = validate_success(api.get_booking(booking["id"], ORG))
        assert booking_after["accrued_bonus_cents"] == 1000

    def test_signing_bonus_bubbles_to_booking_version(self, api):
        """PRD §3.5: "The computed bonus bubbles up: the booking's
        `accrued_bonus_cents` grows by `bonus_cents`, a mutation that bumps the
        booking's `version`."

        Design: Difficulty/boundary_precision_check/signing_bonus_attendance_exact_threshold
        """
        school, pub, author, fair, agr, lines, booking = _open_fair_with_booking(
            bonus_threshold=3, bonus_base=1000, bonus_per=100
        )
        session = make_session(
            booking["id"], fair["id"], mode="TICKETED",
            capacity_seats=10, admit_concurrent_cap=10,
        )
        before = validate_success(api.get_booking(booking["id"], ORG))
        validate_success(api.set_clock({"to_iso8601": "2026-08-10T10:05:00Z"}, ORG))
        validate_success(api.open_signing(session["id"], LINESTAFF))
        for i in range(4):
            t = validate_success(api.create_ticket(
                create_ticket_payload(session_id=session["id"], holder_name=f"Kid {i+1}"),
                LINESTAFF,
            ), expected_status=201)
            validate_success(api.admit_ticket(t["id"], {"session_id": session["id"]}, LINESTAFF))
        validate_success(api.close_signing(session["id"], LINESTAFF))
        rec = validate_success(api.reconcile_session(session["id"], ORG))
        # attendance 4, threshold 3: 1000 + 100 * (4 - 3) == 1100
        assert rec["bonus_cents"] == 1100
        after = validate_success(api.get_booking(booking["id"], ORG))
        assert after["accrued_bonus_cents"] == 1100
        assert after["version"] > before["version"]


class TestEntitlementConservation:
    def test_ticket_issue_void_entitlement_conservation(self, api):
        """PRD §3.5: "Issuance is capacity-capped: the number of the session's
        live entitlements — tickets in `ISSUED`, `ADMITTED`, or `REDEEMED` —
        must remain below `capacity_seats`, so an issue that would reach the cap
        is refused with `ERR_SIGNING_CAPACITY_EXCEEDED` (HTTP 409)."
        PRD §3.5: "Line staff may also void an `ISSUED` or `ADMITTED` ticket
        outright, moving it to `VOIDED` and releasing the live entitlement — the
        session's live-entitlement count decreases by one."

        Design: Difficulty/compensating_invariant/ticket_issue_void_entitlement_conservation
        """
        school, pub, author, fair, agr, lines, booking = _open_fair_with_booking()
        session = make_session(
            booking["id"], fair["id"], mode="TICKETED",
            capacity_seats=2, admit_concurrent_cap=2,
        )
        t1 = validate_success(api.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name="Kid One"),
            LINESTAFF,
        ), expected_status=201)
        t2 = validate_success(api.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name="Kid Two"),
            LINESTAFF,
        ), expected_status=201)
        # Third issue exceeds capacity 2
        resp_full = api.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name="Kid Three"),
            LINESTAFF,
        )
        validate_error(resp_full, ApiErrorId.ERR_SIGNING_CAPACITY_EXCEEDED)
        # Void t1 to free a slot
        validate_success(api.void_ticket(t1["id"], LINESTAFF))
        t3 = validate_success(api.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name="Kid Three"),
            LINESTAFF,
        ), expected_status=201)
        assert t3["status"] == "ISSUED"
        after_t1 = validate_success(api.get_ticket(t1["id"], ORG))
        assert after_t1["status"] == "VOIDED"

    def test_ticket_issue_at_capacity_exact_boundary(self, api):
        """PRD §3.5: "the number of the session's live entitlements — tickets in
        `ISSUED`, `ADMITTED`, or `REDEEMED` — must remain below
        `capacity_seats`, so an issue that would reach the cap is refused with
        `ERR_SIGNING_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/compensating_invariant/ticket_issue_void_entitlement_conservation
        """
        school, pub, author, fair, agr, lines, booking = _open_fair_with_booking()
        session = make_session(
            booking["id"], fair["id"], mode="TICKETED",
            capacity_seats=2, admit_concurrent_cap=2,
        )
        # Two issues succeed (2 < 2 is false only after the second; the cap is "remain below")
        validate_success(api.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name="Kid One"),
            LINESTAFF,
        ), expected_status=201)
        validate_success(api.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name="Kid Two"),
            LINESTAFF,
        ), expected_status=201)
        resp = api.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name="Kid Three"),
            LINESTAFF,
        )
        validate_error(resp, ApiErrorId.ERR_SIGNING_CAPACITY_EXCEEDED)
