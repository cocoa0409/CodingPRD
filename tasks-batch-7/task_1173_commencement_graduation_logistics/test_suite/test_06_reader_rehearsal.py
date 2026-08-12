"""Reader cards, rehearsal sessions, and the conduct strike policy."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_ceremony, setup_ceremony_with_graduates, import_and_audit,
    create_reader_card, get_graduate_reader_card, create_rehearsal_session,
    register_for_session, complete_session, get_graduate, set_clock,
    create_reader_card_payload, create_rehearsal_session_payload,
    make_graduate_headers, make_coordinator_headers, TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
COORDINATOR = TEST_USERS["venue_coordinator_headers"]
COORD_A = "coord-a"
COORD_B = "coord-b"


class TestRehearsalVenueOverlap:
    def _setup_venue_and_ceremony(self):
        return setup_ceremony(venue_capacity=50, venue_accessible=4)

    def test_half_open_adjacent_sessions_coexist(self, api):
        """PRD §3.6: "Sessions at the same venue are treated as half-open
        intervals: a new `SCHEDULED` session conflicts with an existing
        `SCHEDULED` session at that venue only when their windows truly
        intersect, and back-to-back sessions — one's `end_utc` equal to the
        other's `start_utc` — are allowed; a genuine overlap is rejected with
        `ERR_VENUE_TIME_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rehearsal_half_open_adjacency
        """
        ctx = self._setup_venue_and_ceremony()
        ceremony_id, venue_id = ctx["ceremony"]["id"], ctx["venue"]["id"]
        s1 = create_rehearsal_session(ceremony_id, venue_id,
                                      start_utc="2026-05-25T10:00:00Z",
                                      end_utc="2026-05-25T11:00:00Z")
        s2 = create_rehearsal_session(ceremony_id, venue_id,
                                      start_utc="2026-05-25T11:00:00Z",
                                      end_utc="2026-05-25T12:00:00Z")
        assert s1["id"] != s2["id"]
        assert s1["status"] == "SCHEDULED" and s2["status"] == "SCHEDULED"

    def test_genuinely_intersecting_session_rejected(self, api):
        """PRD §3.6: "Sessions at the same venue are treated as half-open
        intervals: a new `SCHEDULED` session conflicts with an existing
        `SCHEDULED` session at that venue only when their windows truly
        intersect, and back-to-back sessions — one's `end_utc` equal to the
        other's `start_utc` — are allowed; a genuine overlap is rejected with
        `ERR_VENUE_TIME_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/rehearsal_half_open_adjacency
        """
        ctx = self._setup_venue_and_ceremony()
        ceremony_id, venue_id = ctx["ceremony"]["id"], ctx["venue"]["id"]
        create_rehearsal_session(ceremony_id, venue_id,
                                 start_utc="2026-05-25T10:00:00Z",
                                 end_utc="2026-05-25T11:00:00Z")
        create_rehearsal_session(ceremony_id, venue_id,
                                 start_utc="2026-05-25T11:00:00Z",
                                 end_utc="2026-05-25T12:00:00Z")
        res = api.create_rehearsal_session(
            ceremony_id,
            create_rehearsal_session_payload(
                venue_id, start_utc="2026-05-25T10:30:00Z",
                end_utc="2026-05-25T11:30:00Z"),
            COORDINATOR)
        validate_error(res, ApiErrorId.ERR_VENUE_TIME_OVERLAP)
        assert res.status_code == 409


class TestReaderCards:
    def test_reader_card_double_approve_returns_invalid_state(self, api):
        """PRD §3.6: "a `CommitteeChair` may approve it, moving it to
        `APPROVED` and stamping `approved_by_user_id` with the approver."
        PRD §2.11: "The target entity's own state machine permits the
        transition from its current state, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/reader_card_double_approve_returns_invalid_state
        """
        ctx = setup_ceremony_with_graduates(
            [{"full_name": "Card Carl", "email": "carl@x.edu"}], posture="AUDIT_OPEN")
        graduate = ctx["graduates"][0]
        card = create_reader_card(graduate["id"], "KARL")
        approved = validate_success(api.approve_reader_card(card["id"], CHAIR), 200)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "test-chair-1"

        res = api.approve_reader_card(card["id"], CHAIR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert res.status_code == 409
        after = get_graduate_reader_card(graduate["id"])
        assert after["status"] == "APPROVED"
        assert after["approved_by_user_id"] == "test-chair-1"

    def test_mark_ready_requires_and_locks_reader_cards(self, api):
        """PRD §3.1: "Marking the ceremony ready moves `AUDIT_LOCKED` to
        `READY` and is permitted only when no non-`WITHDRAWN` graduate remains
        in `PENDING_AUDIT` or `APPEALING` status and every graduate in
        `ELIGIBLE`, `ELIGIBLE_ON_APPEAL`, or `CONFIRMED` has a reader card in
        `SUBMITTED` or `APPROVED` status; either failure is rejected with
        `ERR_CEREMONY_POSTURE_FORBIDS`."
        PRD §3.1: "Marking ready also cascades through the reader-card
        population, moving every `SUBMITTED` or `APPROVED` card for the
        ceremony's graduates to `LOCKED`."

        Design: Corner/state_machines/mark_ready_requires_and_locks_reader_cards
        """
        ctx = setup_ceremony_with_graduates(
            [{"full_name": "Ready Rex", "email": "rex@x.edu"}], posture="AUDIT_LOCKED")
        ceremony_id = ctx["ceremony"]["id"]
        graduate = ctx["graduates"][0]

        res = api.mark_ready(ceremony_id, CHAIR)
        validate_error(res, ApiErrorId.ERR_CEREMONY_POSTURE_FORBIDS)
        assert res.status_code == 409  # graduate lacks a reader card

        card = create_reader_card(graduate["id"], "REH-dee REKS")
        ceremony = validate_success(api.mark_ready(ceremony_id, CHAIR), 200)
        assert ceremony["readiness_posture"] == "READY"
        assert get_graduate_reader_card(graduate["id"])["status"] == "LOCKED"

    def test_duplicate_reader_card_returns_reader_card_exists(self, api):
        """PRD §3.6: "Each graduate may file exactly one reader card." and
        submission "is refused outright if a card already exists for the
        graduate (`ERR_READER_CARD_EXISTS`)".

        Design: Corner/validations/duplicate_reader_card_returns_reader_card_exists
        """
        ctx = setup_ceremony_with_graduates(
            [{"full_name": "Card Cara", "email": "cara@x.edu"}], posture="AUDIT_OPEN")
        graduate = ctx["graduates"][0]
        create_reader_card(graduate["id"], "KAR-uh")
        res = api.create_reader_card(
            graduate["id"], create_reader_card_payload("KEHR-uh"),
            make_graduate_headers(graduate["id"]))
        validate_error(res, ApiErrorId.ERR_READER_CARD_EXISTS)
        assert res.status_code == 409

    def test_reader_card_after_pronunciation_deadline_returns_error(self, api):
        """PRD §2.10: "a reader card submitted strictly after the
        `pronunciation_deadline` is rejected with
        `ERR_PRONUNCIATION_DEADLINE_PASSED`".

        Design: Corner/validations/reader_card_after_pronunciation_deadline_returns_error
        """
        ctx = setup_ceremony_with_graduates(
            [{"full_name": "Late Lena", "email": "lena@x.edu"}], posture="AUDIT_OPEN")
        graduate = ctx["graduates"][0]
        set_clock("2026-05-21T00:00:00Z")  # pronunciation_deadline is 2026-05-20
        res = api.create_reader_card(
            graduate["id"], create_reader_card_payload("LEH-nah"),
            make_graduate_headers(graduate["id"]))
        validate_error(res, ApiErrorId.ERR_PRONUNCIATION_DEADLINE_PASSED)
        assert res.status_code == 422
        assert get_graduate_reader_card(graduate["id"]) is None


class TestRehearsalRegistration:
    def test_rehearsal_registration_full_returns_rehearsal_full(self, api):
        """PRD §3.6: "registration is refused when the graduate already holds a
        `REGISTERED` or `ATTENDED` attendance for that session
        (`ERR_DUPLICATE_REGISTRATION`) and when the session's
        `registered_count` has reached its `capacity` (`ERR_REHEARSAL_FULL`)".

        Design: Corner/validations/rehearsal_registration_full_returns_rehearsal_full
        """
        ctx = setup_ceremony_with_graduates(
            [{"full_name": "Reg A", "email": "ra@x.edu"},
             {"full_name": "Reg B", "email": "rb@x.edu"}],
            posture="AUDIT_OPEN", venue_capacity=50, venue_accessible=4)
        session = create_rehearsal_session(ctx["ceremony"]["id"], ctx["venue"]["id"],
                                           capacity=1)
        ga, gb = ctx["graduates"]
        register_for_session(session["id"], ga["id"])
        res = api.register_for_session(session["id"], make_graduate_headers(gb["id"]))
        validate_error(res, ApiErrorId.ERR_REHEARSAL_FULL)
        assert res.status_code == 422

    def test_duplicate_rehearsal_registration_returns_duplicate(self, api):
        """PRD §3.6: "registration is refused when the graduate already holds a
        `REGISTERED` or `ATTENDED` attendance for that session
        (`ERR_DUPLICATE_REGISTRATION`)".
        PRD §3.6: "A successful registration creates the attendance in
        `REGISTERED` status — its `rehearsal_session_id` pointing at the
        session and its `graduate_id` taken from the caller's own identity —
        and raises the session's `registered_count` by one."

        Design: Corner/validations/duplicate_rehearsal_registration_returns_duplicate
        """
        ctx = setup_ceremony_with_graduates(
            [{"full_name": "Dup Dan", "email": "dan@x.edu"}],
            posture="AUDIT_OPEN", venue_capacity=50, venue_accessible=4)
        session = create_rehearsal_session(ctx["ceremony"]["id"], ctx["venue"]["id"],
                                           capacity=2)
        graduate = ctx["graduates"][0]
        register_for_session(session["id"], graduate["id"])
        res = api.register_for_session(session["id"], make_graduate_headers(graduate["id"]))
        validate_error(res, ApiErrorId.ERR_DUPLICATE_REGISTRATION)
        assert res.status_code == 409
        after = validate_success(api.get_rehearsal_session(session["id"], COORDINATOR), 200)
        assert after["registered_count"] == 1


class TestConductStrikePolicy:
    def test_strike_threshold_revocation_and_restore(self, api):
        """PRD §3.6: "`walk_privilege_revoked` becomes true the moment the
        count reaches at least two: exactly two unexcused strikes already
        revokes."
        PRD §3.6: "a `VenueCoordinator` waives an `ABSENT` attendance to
        `EXCUSED`, which subtracts one from the graduate's
        `conduct_strike_count` and stamps `waived_by_user_id`".
        PRD §3.6: "When a `VenueCoordinator` completes a `SCHEDULED` session,
        every attendance still `REGISTERED` flips to `ABSENT` with
        `recorded_by_user_id` set to the completing coordinator, and each such
        absence adds one to the graduate's `conduct_strike_count`."

        Design: Corner/calculations/strike_threshold_revocation_and_restore
        """
        ctx = setup_ceremony(open_audit=True, venue_capacity=50, venue_accessible=4)
        ceremony_id, venue_id = ctx["ceremony"]["id"], ctx["venue"]["id"]
        graduate, _ = import_and_audit(ceremony_id, full_name="Strike Stan",
                                       email="stan@x.edu")
        s1 = create_rehearsal_session(ceremony_id, venue_id,
                                      start_utc="2026-05-25T10:00:00Z",
                                      end_utc="2026-05-25T11:00:00Z")
        s2 = create_rehearsal_session(ceremony_id, venue_id,
                                      start_utc="2026-05-26T10:00:00Z",
                                      end_utc="2026-05-26T11:00:00Z")
        att1 = register_for_session(s1["id"], graduate["id"])
        register_for_session(s2["id"], graduate["id"])

        complete_session(s1["id"], coordinator_id=COORD_A)
        after_one = get_graduate(graduate["id"])
        assert after_one["conduct_strike_count"] == 1
        assert after_one["walk_privilege_revoked"] is False  # below threshold

        complete_session(s2["id"], coordinator_id=COORD_A)
        after_two = get_graduate(graduate["id"])
        assert after_two["conduct_strike_count"] == 2
        assert after_two["walk_privilege_revoked"] is True  # >= 2 boundary

        waived = validate_success(
            api.waive_attendance(att1["id"], make_coordinator_headers(COORD_B)), 200)
        assert waived["status"] == "EXCUSED"
        assert waived["waived_by_user_id"] == COORD_B
        after_waive = get_graduate(graduate["id"])
        assert after_waive["conduct_strike_count"] == 1
        assert after_waive["walk_privilege_revoked"] is False

    def test_sod_attendance_waive_by_recorder_returns_segregation_error(self, api):
        """PRD §2.7: "A rehearsal absence may be waived only by a
        `VenueCoordinator` whose identifier differs from the attendance's
        `recorded_by_user_id`."
        PRD §2.7: "In each pair, the second step is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the same `X-User-ID`
        performs both".

        Design: Corner/validations/sod_attendance_waive_by_recorder_returns_segregation_error
        """
        ctx = setup_ceremony(open_audit=True, venue_capacity=50, venue_accessible=4)
        ceremony_id, venue_id = ctx["ceremony"]["id"], ctx["venue"]["id"]
        graduate, _ = import_and_audit(ceremony_id, full_name="Waive Wendy",
                                       email="wendy@x.edu")
        session = create_rehearsal_session(ceremony_id, venue_id)
        attendance = register_for_session(session["id"], graduate["id"])
        complete_session(session["id"], coordinator_id=COORD_A)

        res = api.waive_attendance(attendance["id"], make_coordinator_headers(COORD_A))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert res.status_code == 403  # waver == recorded_by_user_id

        attendances = validate_success(
            api.list_session_attendances(session["id"], COORDINATOR), 200)
        assert attendances[0]["status"] == "ABSENT"
        assert attendances[0]["recorded_by_user_id"] == COORD_A
        assert get_graduate(graduate["id"])["conduct_strike_count"] == 1
