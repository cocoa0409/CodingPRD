"""Mediation sessions: dual confirmation, calendar overlap rules, capacity and caseload."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_mediation_session,
    complete_session,
    confirm_session,
    create_mediation_session_payload,
    drive_to_mediation_active,
    file_complaint,
    get_complaint,
    get_mediator,
    make_business_headers,
    make_consumer_headers,
    make_mediator_headers,
    notify_business,
    offer_mediation,
    propose_session,
    register_business,
    register_case_parties,
    register_consumer,
    register_mediation_room,
    register_mediator,
    review_response,
    screen_accept,
    set_clock,
    setup_mediation_active_case,
    submit_response,
    validate_error,
    validate_success,
)

OFFICER_1 = TEST_USERS["intake_officer_headers"]
DIRECTOR_1 = TEST_USERS["unit_director_headers"]


def _overdue_complaint(consumer, business, officer=OFFICER_1, **overrides):
    """File -> accept -> notify, then advance the clock strictly past the 30-day
    in-state deadline so the sweep flips the case to RESPONSE_OVERDUE (PRD §2.6)."""
    complaint = file_complaint(consumer, business, **overrides)
    screen_accept(complaint["id"], officer)
    notify_business(complaint["id"], officer)
    return complaint


class TestDualConfirmation:
    def test_second_party_confirmation_lifts_complaint_to_active(self, api):
        """PRD §3.4: "When the second confirmation lands and both flags stand true, the session becomes `CONFIRMED` — and the complaint advances with it, from `MEDIATION_OFFERED` to `MEDIATION_ACTIVE` the first time, or from `MEDIATION_IMPASSE` back to `MEDIATION_ACTIVE` on re-engagement — and a `SESSION_CONFIRMED` event is written."
        PRD §3.3: "from `RESPONSE_OVERDUE` it may proceed with no adequate response at all; either path lands the complaint in `MEDIATION_OFFERED`"
        PRD §3.4: "A `Consumer` caller sets only `consumer_confirmed`; a `Business` caller sets only `business_confirmed`"

        Design: Corner/state_machines/c_sm_session_dual_confirmation
        """
        parties = register_case_parties(
            consumer_overrides={"full_name": "DC", "email": "dc@x.com"},
            business_overrides={"legal_name": "DcCo"},
        )
        set_clock("2026-08-01T00:00:00Z")
        complaint = _overdue_complaint(
            parties["consumer"], parties["business"], category="OTHER", description="dc"
        )
        set_clock("2026-08-31T00:00:01Z")  # strictly past the 2026-08-31T00:00:00Z deadline
        assert get_complaint(complaint["id"])["case_status"] == "RESPONSE_OVERDUE"

        offered = offer_mediation(complaint["id"])
        assert offered["case_status"] == "MEDIATION_OFFERED"
        session = propose_session(
            complaint["id"], parties["mediator"], parties["room"],
            starts_at="2026-09-05T10:00:00Z", ends_at="2026-09-05T11:00:00Z",
        )

        first = confirm_session(session["id"], make_consumer_headers(parties["consumer"]["id"]))
        assert first["session_status"] == "PROPOSED", "quorum incomplete after first confirm"
        assert first["consumer_confirmed"] is True
        assert first["business_confirmed"] is False

        second = confirm_session(session["id"], make_business_headers(parties["business"]["id"]))
        assert second["session_status"] == "CONFIRMED"
        assert second["consumer_confirmed"] is True
        assert second["business_confirmed"] is True
        assert get_complaint(complaint["id"])["case_status"] == "MEDIATION_ACTIVE"


class TestMediatorBufferOverlap:
    def _setup_active_with_booked_mediator(self, api):
        """Complaint MEDIATION_ACTIVE; mediator CONFIRMED 10:00-11:00; a second empty room."""
        ctx = setup_mediation_active_case(
            consumer_overrides={"full_name": "C M", "email": "cm@x.com"},
            business_overrides={"legal_name": "BufCo"},
            session_starts_at="2026-08-10T10:00:00Z",
            session_ends_at="2026-08-10T11:00:00Z",
        )
        room2 = register_mediation_room(room_name="Room M2", capacity=6, location="Salem")
        return ctx, room2

    def test_mediator_buffer_rejects_start_inside_turnover_window(self, api):
        """PRD §3.4: "The mediator's own calendar uses a half-open rule with a thirty-minute turnover buffer: a proposed session conflicts with an existing one when the proposed `starts_at` falls before the existing session's `ends_at` plus thirty minutes, and the existing session's `starts_at` falls before the proposed `ends_at` plus thirty minutes"

        Design: Difficulty/resource_temporal_overlap/d_overlap_mediator_buffer_semantics
        """
        ctx, room2 = self._setup_active_with_booked_mediator(api)
        # Existing 10:00-11:00; new start 11:00 falls before 11:00 + 30 minutes.
        resp = api.create_mediation_session(
            ctx["complaint"]["id"],
            create_mediation_session_payload(
                ctx["mediator"]["id"], room2["id"],
                starts_at="2026-08-10T11:00:00Z", ends_at="2026-08-10T11:30:00Z",
            ),
            make_mediator_headers(ctx["mediator"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEDIATOR_TIME_CONFLICT)

    def test_mediator_buffer_allows_start_exactly_at_turnover(self, api):
        """PRD §3.4: "so a mediator may start a new session exactly at the instant a previous one ends plus the buffer, but no earlier"
        PRD §3.4: "A mediator's `active_case_count` is exactly the number of their own sessions in `PROPOSED` or `CONFIRMED`"

        Design: Difficulty/resource_temporal_overlap/d_overlap_mediator_buffer_semantics
        """
        ctx, room2 = self._setup_active_with_booked_mediator(api)
        # New start 11:30 is exactly 11:00 + 30 minutes: the buffer is satisfied.
        session = propose_session(
            ctx["complaint"]["id"], ctx["mediator"], room2,
            starts_at="2026-08-10T11:30:00Z", ends_at="2026-08-10T12:00:00Z",
        )
        assert session["session_status"] == "PROPOSED"
        mediator = get_mediator(ctx["mediator"]["id"])
        assert mediator["active_case_count"] == 2, "CONFIRMED s1 + PROPOSED s3 both count"


class TestRoomClosedIntervalOverlap:
    def _setup_two_active_cases_sharing_room(self, api):
        """Two complaints MEDIATION_ACTIVE: ka via med1 08-12 10:00-11:00 in room R,
        kb via med2 08-13 10:00-11:00 in room R."""
        consumer = register_consumer(full_name="C O", email="co@x.com", state_code="OR")
        business = register_business(legal_name="RoomCo", home_state="OR", operates_in_states=["OR"])
        med1 = register_mediator(full_name="Med O1", employee_ref="EMP-13")
        med2 = register_mediator(full_name="Med O2", employee_ref="EMP-14")
        room = register_mediation_room(room_name="Room O", capacity=6, location="Salem")
        set_clock("2026-08-01T00:00:00Z")
        ka = drive_to_mediation_active(
            consumer, business, med1, room,
            complaint_overrides={"incident_date": "2026-07-01", "description": "ra"},
            session_starts_at="2026-08-12T10:00:00Z", session_ends_at="2026-08-12T11:00:00Z",
        )
        kb = drive_to_mediation_active(
            consumer, business, med2, room,
            complaint_overrides={"incident_date": "2026-07-02", "description": "rb"},
            session_starts_at="2026-08-13T10:00:00Z", session_ends_at="2026-08-13T11:00:00Z",
        )
        return consumer, business, med1, med2, room, ka, kb

    def test_room_closed_interval_rejects_shared_boundary_instant(self, api):
        """PRD §3.4: "Room bookings use a stricter closed-interval rule with no buffer at all: a conflict exists whenever the proposed `starts_at` falls at or before an existing booking's `ends_at` and that booking's `starts_at` falls at or before the proposed `ends_at`, which means two sessions that merely touch at the exact boundary instant already conflict."

        Design: Difficulty/resource_temporal_overlap/d_overlap_room_closed_interval
        """
        _, _, _, med2, room, ka, kb = self._setup_two_active_cases_sharing_room(api)
        # Existing booking [10:00, 11:00] on 08-12; proposed [11:00, 12:00] shares 11:00.
        resp = api.create_mediation_session(
            kb["complaint"]["id"],
            create_mediation_session_payload(
                med2["id"], room["id"],
                starts_at="2026-08-12T11:00:00Z", ends_at="2026-08-12T12:00:00Z",
            ),
            make_mediator_headers(med2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ROOM_TIME_CONFLICT)

    def test_room_allows_start_one_second_after_boundary(self, api):
        """PRD §3.4: "a conflict exists whenever the proposed `starts_at` falls at or before an existing booking's `ends_at` and that booking's `starts_at` falls at or before the proposed `ends_at`"
        PRD §3.4: "Both checks consider only sessions in `PROPOSED` or `CONFIRMED` belonging to that mediator or that room."

        Design: Difficulty/resource_temporal_overlap/d_overlap_room_closed_interval
        """
        _, _, _, med2, room, ka, kb = self._setup_two_active_cases_sharing_room(api)
        # Proposed start 11:00:01 is not "at or before" the 11:00 end: no shared instant.
        session = propose_session(
            kb["complaint"]["id"], med2, room,
            starts_at="2026-08-12T11:00:01Z", ends_at="2026-08-12T12:00:00Z",
        )
        assert session["session_status"] == "PROPOSED"
        occupying = validate_success(
            api.get_mediation_session(ka["session"]["id"], make_mediator_headers(ka["session"]["mediator_id"]))
        )
        assert occupying["session_status"] == "CONFIRMED"


class TestSessionGates:
    def test_conflicted_mediator_cannot_take_case(self, api):
        """PRD §3.4: "the complaint's business must not appear in the mediator's `conflicted_business_ids` (`ERR_MEDIATOR_CONFLICT_OF_INTEREST`)"

        Design: Corner/validations/c_val_mediator_conflict_of_interest_rejected
        """
        consumer = register_consumer(full_name="CI", email="ci2@x.com", state_code="OR")
        business = register_business(legal_name="CoiCo", home_state="OR", operates_in_states=["OR"])
        mediator = register_mediator(
            full_name="Med CI", employee_ref="EMP-25", conflicted_business_ids=[business["id"]]
        )
        room = register_mediation_room(room_name="Room CI", capacity=4, location="Salem")
        set_clock("2026-08-01T00:00:00Z")
        complaint = file_complaint(consumer, business, category="OTHER", description="coi")
        screen_accept(complaint["id"])
        notify_business(complaint["id"])
        response = submit_response(complaint["id"], business)
        review_response(response["id"], "SUFFICIENT")
        offer_mediation(complaint["id"])

        resp = api.create_mediation_session(
            complaint["id"],
            create_mediation_session_payload(
                mediator["id"], room["id"],
                starts_at="2026-08-10T10:00:00Z", ends_at="2026-08-10T11:00:00Z",
            ),
            make_mediator_headers(mediator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEDIATOR_CONFLICT_OF_INTEREST)

    def test_caseload_cap_blocks_second_session(self, api):
        """PRD §3.4: "creation is refused once the count has reached the mediator's `max_concurrent_cases`"
        PRD §2.12: "8. Uniqueness and capacity: duplicate-complaint detection, registration uniqueness, the stale-version guard, mediator and room calendar conflicts, the caseload cap"

        Design: Corner/validations/c_val_caseload_cap_rejected
        """
        consumer = register_consumer(full_name="CL", email="cl2@x.com", state_code="OR")
        business = register_business(legal_name="LoadCapCo", home_state="OR", operates_in_states=["OR"])
        mediator = register_mediator(full_name="Med CL", employee_ref="EMP-26", max_concurrent_cases=1)
        room = register_mediation_room(room_name="Room CL", capacity=4, location="Salem")
        room2 = register_mediation_room(room_name="Room CL2", capacity=4, location="Salem")
        set_clock("2026-08-01T00:00:00Z")
        ka = _overdue_complaint(consumer, business, incident_date="2026-07-01", description="ca")
        kb = _overdue_complaint(consumer, business, incident_date="2026-07-02", description="cb")
        set_clock("2026-08-31T00:00:01Z")  # sweep flips both to RESPONSE_OVERDUE
        offer_mediation(ka["id"])
        offer_mediation(kb["id"])

        first = propose_session(
            ka["id"], mediator, room,
            starts_at="2026-09-05T10:00:00Z", ends_at="2026-09-05T11:00:00Z",
        )
        assert first["session_status"] == "PROPOSED"

        resp = api.create_mediation_session(
            kb["id"],
            create_mediation_session_payload(
                mediator["id"], room2["id"],
                starts_at="2026-09-05T12:00:00Z", ends_at="2026-09-05T13:00:00Z",
            ),
            make_mediator_headers(mediator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEDIATOR_CASELOAD_FULL)
        unaffected = validate_success(
            api.get_mediation_session(first["id"], make_mediator_headers(mediator["id"]))
        )
        assert unaffected["session_status"] == "PROPOSED", "first session unaffected"

    def test_inactive_mediator_cannot_take_new_sessions(self, api):
        """PRD §3.1: "Deactivation moves `mediator_status` to `INACTIVE`: sessions already on their calendar are untouched, but any attempt to schedule them anew is rejected with `ERR_REFERENCED_ENTITY_INACTIVE`."

        Design: Corner/validations/c_val_inactive_mediator_rejected
        """
        ctx = setup_mediation_active_case(
            consumer_overrides={"full_name": "IA", "email": "ia@x.com"},
            business_overrides={"legal_name": "IaCo"},
            mediator_overrides={"full_name": "Med IA", "employee_ref": "EMP-27"},
        )
        # Deactivate after the first session exists; existing session is untouched.
        deactivated = validate_success(api.deactivate_mediator(ctx["mediator"]["id"], DIRECTOR_1))
        assert deactivated["mediator_status"] == "INACTIVE"

        resp = api.create_mediation_session(
            ctx["complaint"]["id"],
            create_mediation_session_payload(
                ctx["mediator"]["id"], ctx["room"]["id"],
                starts_at="2026-08-12T10:00:00Z", ends_at="2026-08-12T11:00:00Z",
            ),
            make_mediator_headers(ctx["mediator"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCED_ENTITY_INACTIVE)

    def test_session_starting_in_past_rejected(self, api):
        """PRD §3.4: "the proposed start must lie strictly in the future (`ERR_SESSION_IN_PAST`)"
        PRD §2.12: "10. Clock rules: sessions must start in the future"

        Design: Corner/errors/c_err_session_in_past_rejected
        """
        parties = register_case_parties(
            consumer_overrides={"full_name": "SP", "email": "sp@x.com"},
            business_overrides={"legal_name": "SpCo"},
        )
        set_clock("2026-08-01T00:00:00Z")
        complaint = file_complaint(parties["consumer"], parties["business"], category="OTHER")
        screen_accept(complaint["id"])
        notify_business(complaint["id"])
        response = submit_response(complaint["id"], parties["business"])
        review_response(response["id"], "SUFFICIENT")
        offer_mediation(complaint["id"])

        resp = api.create_mediation_session(
            complaint["id"],
            create_mediation_session_payload(
                parties["mediator"]["id"], parties["room"]["id"],
                starts_at="2026-07-01T10:00:00Z", ends_at="2026-07-01T11:00:00Z",
            ),
            make_mediator_headers(parties["mediator"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_IN_PAST)


class TestMediatorCaseloadInvariant:
    def _setup_two_complaints_one_active(self, api):
        """Mediator (default cap 10); complaint A MEDIATION_ACTIVE via session A;
        complaint B MEDIATION_OFFERED."""
        parties = register_case_parties(
            consumer_overrides={"full_name": "C L", "email": "cl@x.com"},
            business_overrides={"legal_name": "LoadCo"},
            mediator_overrides={"full_name": "Med L", "employee_ref": "EMP-16"},
        )
        set_clock("2026-08-01T00:00:00Z")
        driven_a = drive_to_mediation_active(
            parties["consumer"], parties["business"], parties["mediator"], parties["room"],
            complaint_overrides={"incident_date": "2026-07-01", "description": "la"},
            session_starts_at="2026-08-10T10:00:00Z", session_ends_at="2026-08-10T11:00:00Z",
        )
        kb = file_complaint(
            parties["consumer"], parties["business"],
            incident_date="2026-07-02", description="lb",
        )
        screen_accept(kb["id"])
        notify_business(kb["id"])
        rb = submit_response(kb["id"], parties["business"])
        review_response(rb["id"], "SUFFICIENT")
        offer_mediation(kb["id"])
        return parties, driven_a, kb

    def test_caseload_count_balances_create_cancel_and_complete(self, api):
        """PRD §3.4: "Creation adds one to the count; decline, cancellation, and completion each subtract one; confirmation leaves it unchanged, because both `PROPOSED` and `CONFIRMED` already count."
        PRD §3.4: "the owning mediator or a `UnitDirector` may cancel a session in `PROPOSED` or `CONFIRMED`, moving it to `CANCELLED`"

        Design: Difficulty/compensating_invariant/d_invariant_mediator_caseload
        """
        parties, driven_a, kb = self._setup_two_complaints_one_active(api)
        med = parties["mediator"]
        sa = driven_a["session"]
        assert get_mediator(med["id"])["active_case_count"] == 1, "create +1"

        sb = propose_session(
            kb["id"], med, parties["room"],
            starts_at="2026-08-10T12:00:00Z", ends_at="2026-08-10T13:00:00Z",
        )
        assert get_mediator(med["id"])["active_case_count"] == 2, "second proposal +1"

        validate_success(api.cancel_session(sb["id"], make_mediator_headers(med["id"])))
        assert get_mediator(med["id"])["active_case_count"] == 1, "cancel compensates the create"

        completed = complete_session(sa["id"], med, {"outcome": "PROGRESS"}, at_clock="2026-08-10T10:30:00Z")
        assert completed["session_status"] == "COMPLETED"
        assert get_mediator(med["id"])["active_case_count"] == 0, "complete compensates the first create"

    def test_confirmation_is_caseload_neutral_and_progress_keeps_complaint_active(self, api):
        """PRD §3.4: "confirmation leaves it unchanged, because both `PROPOSED` and `CONFIRMED` already count"
        PRD §3.4: "an `IMPASSE` result also drops the complaint from `MEDIATION_ACTIVE` to `MEDIATION_IMPASSE`, while the other two results leave the complaint where it stands"

        Design: Difficulty/compensating_invariant/d_invariant_mediator_caseload
        """
        parties, driven_a, kb = self._setup_two_complaints_one_active(api)
        med = parties["mediator"]
        sa = driven_a["session"]
        assert sa["session_status"] == "CONFIRMED", "fixture dual-confirms session A"
        assert get_mediator(med["id"])["active_case_count"] == 1, (
            "PROPOSED -> CONFIRMED left the count unchanged at 1"
        )
        complete_session(sa["id"], med, {"outcome": "PROGRESS"}, at_clock="2026-08-10T10:30:00Z")
        complaint = get_complaint(driven_a["complaint"]["id"])
        assert complaint["case_status"] == "MEDIATION_ACTIVE", "PROGRESS leaves the complaint where it stands"
