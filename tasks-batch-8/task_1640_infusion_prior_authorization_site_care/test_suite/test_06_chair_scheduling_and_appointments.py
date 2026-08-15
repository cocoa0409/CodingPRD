"""Chair scheduling: parent-approval gate, validity-window bounds, site
match, buffered half-open overlap, occupancy conservation, confirmation
gates, and the clock-driven appointment endings."""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_timestamp_equals,
    book_appointment,
    chair_occupied_count,
    create_appointment_payload,
    create_chair,
    create_draft_request,
    create_patient,
    create_policy,
    setup_approved_request,
    setup_approved_with_chair,
    setup_approved_with_cleared_clearance_and_chair,
    setup_approved_with_clearance,
    setup_submitted_request,
    setup_superseded_request,
    validate_error,
    validate_success,
    SCHEDULER_HEADERS,
)


class TestParentApprovalGate:
    def test_appointment_on_draft_request_rejected(self, api):
        """PRD §3.7: "A `Scheduler` books an infusion on an `APPROVED` request
        by naming a `chair_id` and the infusion's `scheduled_start` and
        `scheduled_end`. Booking enforces a stack of gates: the parent request
        must be `APPROVED` (otherwise `ERR_AUTH_NOT_APPROVED`)"

        Design: Difficulty/cross_entity_state_dependency/appointment_create_requires_auth_approved
        """
        policy = create_policy(drug_code="J9061", regimen_name="XDepA")
        chair = create_chair(site_type="OFFICE", label="CH-XA")
        patient = create_patient(member_id="M801", full_name="X Pat")
        auth = create_draft_request(patient["id"], policy["id"])
        assert auth["status"] == "DRAFT"

        resp = api.create_appointment(
            auth["id"],
            create_appointment_payload(chair["id"], "2026-08-10T10:00:00Z",
                                       "2026-08-10T11:00:00Z"),
            SCHEDULER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_AUTH_NOT_APPROVED)

        appointments = validate_success(
            api.list_appointments(auth["id"], SCHEDULER_HEADERS))
        assert appointments == [], "No appointment is created"

    def test_appointment_on_submitted_request_rejected(self, api):
        """PRD §2.9: "**State preconditions and cross-entity state gates** —
        the parent-approval gate surfaces as `ERR_AUTH_NOT_APPROVED` (409) on
        appointment booking, dose-change creation, clearance creation, and
        clearance recompute; every other from-state violation, including any
        write aimed at a resource in a terminal state, surfaces as
        `ERR_INVALID_STATE` (409)."

        Design: Difficulty/cross_entity_state_dependency/appointment_create_requires_auth_approved
        """
        ws = setup_submitted_request(drug_code="J9061", member_id="M802")
        chair = create_chair(site_type="OFFICE", label="CH-XA2")
        assert ws["auth"]["status"] == "SUBMITTED"

        resp = api.create_appointment(
            ws["auth"]["id"],
            create_appointment_payload(chair["id"], "2026-08-10T10:00:00Z",
                                       "2026-08-10T11:00:00Z"),
            SCHEDULER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_AUTH_NOT_APPROVED)


class TestValidityWindowBounds:
    def test_start_exactly_at_valid_to_allowed_one_second_late_rejected(
            self, api):
        """PRD §3.4: "The window is a closed interval: an appointment
        satisfies it when its `scheduled_start` falls on or after
        `auth_valid_from` and on or before `auth_valid_to`; either bound
        exactly is acceptable."

        Design: Difficulty/boundary_precision_check/appointment_at_validity_end_inclusive
        """
        ws = setup_approved_with_chair(
            drug_code="J9052", member_id="M702",
            policy_overrides={"validity_days": 30, "max_course_days": 60})
        assert ws["auth"]["auth_valid_to"] is not None
        assert_timestamp_equals(
            ws["auth"]["auth_valid_to"], "2026-08-31T00:00:00Z")

        at_bound = validate_success(api.create_appointment(
            ws["auth"]["id"],
            create_appointment_payload(ws["chair"]["id"],
                                       "2026-08-31T00:00:00Z",
                                       "2026-08-31T01:00:00Z"),
            SCHEDULER_HEADERS), 201)
        assert at_bound["status"] == "SCHEDULED", (
            "scheduled_start exactly equal to auth_valid_to is inside the "
            "closed window")

        past = api.create_appointment(
            ws["auth"]["id"],
            create_appointment_payload(ws["chair"]["id"],
                                       "2026-08-31T00:00:01Z",
                                       "2026-08-31T01:00:01Z"),
            SCHEDULER_HEADERS)
        validate_error(past, ApiErrorId.ERR_OUTSIDE_VALIDITY_WINDOW)

    def test_start_exactly_at_valid_from_allowed_one_second_early_rejected(
            self, api):
        """PRD §3.4: "The window is a closed interval: an appointment
        satisfies it when its `scheduled_start` falls on or after
        `auth_valid_from` and on or before `auth_valid_to`; either bound
        exactly is acceptable."

        Design: Difficulty/boundary_precision_check/appointment_at_validity_end_inclusive
        """
        ws = setup_approved_with_chair(drug_code="J9053", member_id="M703")
        assert_timestamp_equals(
            ws["auth"]["auth_valid_from"], "2026-08-01T00:00:00Z")

        at_bound = validate_success(api.create_appointment(
            ws["auth"]["id"],
            create_appointment_payload(ws["chair"]["id"],
                                       "2026-08-01T00:00:00Z",
                                       "2026-08-01T01:00:00Z"),
            SCHEDULER_HEADERS), 201)
        assert at_bound["status"] == "SCHEDULED"

        early = api.create_appointment(
            ws["auth"]["id"],
            create_appointment_payload(ws["chair"]["id"],
                                       "2026-07-31T23:59:59Z",
                                       "2026-08-01T00:30:00Z"),
            SCHEDULER_HEADERS)
        validate_error(early, ApiErrorId.ERR_OUTSIDE_VALIDITY_WINDOW)


class TestChairOverlap:
    def test_buffered_interval_adjacency_allowed_inside_rejected(self, api):
        """PRD §3.7: "Overlap is judged on buffered, half-open intervals: a
        new appointment occupies the interval from its `scheduled_start` up to
        but not including its `scheduled_end` extended by the chair's
        `turnover_buffer_minutes`."
        PRD §3.7: "Back-to-back adjacency — a new start exactly equal to an
        existing buffered end — is permitted."
        PRD §3.7: "The booking conflicts with any existing appointment on the
        same chair whose status is neither `CANCELLED` nor `MISSED` when the
        new start falls before the existing appointment's buffered end and the
        existing start falls before the new appointment's buffered end; such a
        booking is rejected with `ERR_CHAIR_SCHEDULE_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/chair_half_open_interval_with_turnover_buffer
        """
        ws = setup_approved_with_chair(
            drug_code="J9071", member_id="M901",
            chair_overrides={"turnover_buffer_minutes": 15})
        chair_id = ws["chair"]["id"]
        book_appointment(ws["auth"]["id"], chair_id,
                         "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")

        adjacent = validate_success(api.create_appointment(
            ws["auth"]["id"],
            create_appointment_payload(chair_id, "2026-08-10T11:15:00Z",
                                       "2026-08-10T12:00:00Z"),
            SCHEDULER_HEADERS), 201)
        assert adjacent["status"] == "SCHEDULED", (
            "Start exactly at buffered end (11:00 + 15m) is permitted")

        inside = api.create_appointment(
            ws["auth"]["id"],
            create_appointment_payload(chair_id, "2026-08-10T11:14:00Z",
                                       "2026-08-10T12:00:00Z"),
            SCHEDULER_HEADERS)
        validate_error(inside, ApiErrorId.ERR_CHAIR_SCHEDULE_CONFLICT)

    def test_cancelled_appointment_frees_the_slot(self, api):
        """PRD §3.7: "The booking conflicts with any existing appointment on
        the same chair whose status is neither `CANCELLED` nor `MISSED` when
        the new start falls before the existing appointment's buffered end and
        the existing start falls before the new appointment's buffered end;
        such a booking is rejected with `ERR_CHAIR_SCHEDULE_CONFLICT` (409)."
        PRD §3.7: "A `Scheduler` may cancel a `SCHEDULED` or `CONFIRMED`
        appointment, moving it to `CANCELLED` and releasing the chair
        occupation"

        Design: Difficulty/resource_temporal_overlap/chair_half_open_interval_with_turnover_buffer
        """
        ws = setup_approved_with_chair(drug_code="J9074", member_id="M904")
        chair_id = ws["chair"]["id"]
        first = book_appointment(ws["auth"]["id"], chair_id,
                                 "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
        cancelled = validate_success(
            api.cancel_appointment(first["id"], SCHEDULER_HEADERS))
        assert cancelled["status"] == "CANCELLED"

        overlapping = validate_success(api.create_appointment(
            ws["auth"]["id"],
            create_appointment_payload(chair_id, "2026-08-10T10:30:00Z",
                                       "2026-08-10T11:30:00Z"),
            SCHEDULER_HEADERS), 201)
        assert overlapping["status"] == "SCHEDULED", (
            "A CANCELLED appointment no longer occupies the chair")


class TestChairOccupancyConservation:
    def test_create_then_cancel_conserves_occupied_count(self, api):
        """PRD §3.7: "Chair occupancy is a conserved quantity. The occupied
        count of a chair is the number of its appointments in `SCHEDULED`,
        `CONFIRMED`, or `COMPLETED` status, and every booking or cancellation
        keeps that count honest — a cancellation releases the occupation and
        decreases the count by one."

        Design: Difficulty/compensating_invariant/appointment_create_cancel_conserves_chair_load
        """
        ws = setup_approved_with_chair(drug_code="J9081", member_id="M1001")
        chair_id = ws["chair"]["id"]

        before = validate_success(
            api.list_chair_appointments(chair_id, SCHEDULER_HEADERS))
        assert chair_occupied_count(before) == 0

        appt = book_appointment(ws["auth"]["id"], chair_id,
                                "2026-08-12T10:00:00Z", "2026-08-12T11:00:00Z")
        after_create = validate_success(
            api.list_chair_appointments(chair_id, SCHEDULER_HEADERS))
        assert chair_occupied_count(after_create) == 1, (
            "Booking raises the occupied count by one")

        cancelled = validate_success(
            api.cancel_appointment(appt["id"], SCHEDULER_HEADERS))
        assert cancelled["status"] == "CANCELLED"
        after_cancel = validate_success(
            api.list_chair_appointments(chair_id, SCHEDULER_HEADERS))
        assert chair_occupied_count(after_cancel) == 0, (
            "Cancellation returns the occupied count to its pre-create value")

    def test_confirm_then_cancel_conserves_occupied_count(self, api):
        """PRD §3.7: "A `Scheduler` may cancel a `SCHEDULED` or `CONFIRMED`
        appointment, moving it to `CANCELLED` and releasing the chair
        occupation; the same `CANCELLED` landing also arrives by cascade when
        the parent request is superseded (§3.8)."

        Design: Difficulty/compensating_invariant/appointment_create_cancel_conserves_chair_load
        """
        ws = setup_approved_with_cleared_clearance_and_chair(
            drug_code="J9084", member_id="M1004")
        chair_id = ws["chair"]["id"]

        appt = book_appointment(ws["auth"]["id"], chair_id,
                                "2026-08-12T10:00:00Z", "2026-08-12T11:00:00Z")
        confirmed = validate_success(
            api.confirm_appointment(appt["id"], SCHEDULER_HEADERS))
        assert confirmed["status"] == "CONFIRMED"
        assert chair_occupied_count(validate_success(
            api.list_chair_appointments(chair_id, SCHEDULER_HEADERS))) == 1

        cancelled = validate_success(
            api.cancel_appointment(appt["id"], SCHEDULER_HEADERS))
        assert cancelled["status"] == "CANCELLED"
        assert chair_occupied_count(validate_success(
            api.list_chair_appointments(chair_id, SCHEDULER_HEADERS))) == 0, (
            "Cancelling a CONFIRMED appointment also releases the occupation")


class TestValidationPriorityPairs:
    def test_state_gate_beats_window_on_superseded_request(self, api):
        """PRD §2.9: "Validation runs as a fixed pipeline, and an earlier
        failure masks every later check."
        PRD §2.9: "6. **State preconditions and cross-entity state gates** —
        the parent-approval gate surfaces as `ERR_AUTH_NOT_APPROVED` (409) on
        appointment booking, dose-change creation, clearance creation, and
        clearance recompute"
        PRD §2.9: "15.–16. **Temporal gates** — the authorization validity
        window (`ERR_OUTSIDE_VALIDITY_WINDOW`, 422) before the appeal deadline
        (`ERR_APPEAL_WINDOW_CLOSED`, 422)."

        Design: Difficulty/priority_pair_validation_conflict/appointment_create_state_beats_temporal
        """
        ws = setup_superseded_request(
            drug_code="J9041", member_id="M601",
            policy_overrides={"validity_days": 30, "max_course_days": 60})
        chair = create_chair(site_type="OFFICE", label="CH-PA")
        assert ws["auth"]["status"] == "SUPERSEDED"
        # The old window ended 2026-08-31; the 2026-09-15 start is also
        # outside it — yet the state gate fires first.
        resp = api.create_appointment(
            ws["auth"]["id"],
            create_appointment_payload(chair["id"], "2026-09-15T10:00:00Z",
                                       "2026-09-15T11:00:00Z"),
            SCHEDULER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_AUTH_NOT_APPROVED)

    def test_state_gate_beats_window_on_expired_request(self, api):
        """PRD §2.9: "Validation runs as a fixed pipeline, and an earlier
        failure masks every later check."
        PRD §3.4: "When the logical clock advances past `auth_valid_to`, an
        `APPROVED` request becomes `EXPIRED`, incrementing `version`."

        Design: Difficulty/priority_pair_validation_conflict/appointment_create_state_beats_temporal
        """
        ws = setup_approved_with_chair(
            drug_code="J9043", member_id="M603",
            policy_overrides={"validity_days": 30, "max_course_days": 60})
        advance_clock("2026-09-01T00:00:00Z")

        resp = api.create_appointment(
            ws["auth"]["id"],
            create_appointment_payload(ws["chair"]["id"],
                                       "2026-09-20T10:00:00Z",
                                       "2026-09-20T11:00:00Z"),
            SCHEDULER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_AUTH_NOT_APPROVED)

    def test_window_gate_beats_site_mismatch(self, api):
        """PRD §2.9: "Validation runs as a fixed pipeline, and an earlier
        failure masks every later check."
        PRD §2.9: "15.–16. **Temporal gates** — the authorization validity
        window (`ERR_OUTSIDE_VALIDITY_WINDOW`, 422) before the appeal deadline
        (`ERR_APPEAL_WINDOW_CLOSED`, 422)."
        PRD §2.9: "17.–20. **Constraint checks** — chair site match
        (`ERR_SITE_NOT_ALLOWED`, 422), chair schedule overlap
        (`ERR_CHAIR_SCHEDULE_CONFLICT`, 409), reviewer slot overlap
        (`ERR_REVIEWER_SLOT_CONFLICT`, 409), then policy uniqueness
        (`ERR_DUPLICATE_POLICY`, 409)."

        Design: Difficulty/priority_pair_validation_conflict/appointment_create_temporal_beats_site_constraint
        """
        ws = setup_approved_request(
            drug_code="J9042", member_id="M602",
            policy_overrides={"validity_days": 30, "max_course_days": 60})
        home_chair = create_chair(site_type="HOME", label="CH-PB")
        # Recommended site is the requested OFFICE (NO_STEERING); the HOME
        # chair mismatches AND the start is past auth_valid_to 2026-08-31.
        resp = api.create_appointment(
            ws["auth"]["id"],
            create_appointment_payload(home_chair["id"],
                                       "2026-09-15T10:00:00Z",
                                       "2026-09-15T11:00:00Z"),
            SCHEDULER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_VALIDITY_WINDOW)

    def test_window_gate_beats_site_mismatch_before_window(self, api):
        """PRD §2.9: "Validation runs as a fixed pipeline, and an earlier
        failure masks every later check."
        PRD §3.4: "The window is a closed interval: an appointment satisfies
        it when its `scheduled_start` falls on or after `auth_valid_from` and
        on or before `auth_valid_to`; either bound exactly is acceptable."

        Design: Difficulty/priority_pair_validation_conflict/appointment_create_temporal_beats_site_constraint
        """
        ws = setup_approved_request(
            drug_code="J9044", member_id="M604",
            policy_overrides={"validity_days": 30, "max_course_days": 60})
        home_chair = create_chair(site_type="HOME", label="CH-PB2")
        # Start before auth_valid_from 2026-08-01 AND a mismatched HOME chair.
        resp = api.create_appointment(
            ws["auth"]["id"],
            create_appointment_payload(home_chair["id"],
                                       "2026-07-15T10:00:00Z",
                                       "2026-07-15T11:00:00Z"),
            SCHEDULER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_VALIDITY_WINDOW)


class TestConfirmationGate:
    def test_confirm_without_cleared_clearance_rejected(self, api):
        """PRD §3.7: "A `Scheduler` confirms a `SCHEDULED` appointment only
        when the parent request is still `APPROVED` (`ERR_AUTH_NOT_APPROVED`
        otherwise), when the request's financial clearance is `CLEARED`"
        PRD §3.7: "so an `ON_HOLD` clearance fails this gate with
        `ERR_CLEARANCE_NOT_CLEARED` (422)"

        Design: Corner/validations/confirm_without_cleared_clearance_rejected
        """
        ws = setup_approved_with_clearance(drug_code="J9155",
                                           member_id="M1155")
        chair = create_chair(site_type="OFFICE", label="CH-NCF")
        appt = book_appointment(ws["auth"]["id"], chair["id"],
                                "2026-08-12T10:00:00Z", "2026-08-12T11:00:00Z")

        resp = api.confirm_appointment(appt["id"], SCHEDULER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_CLEARANCE_NOT_CLEARED)

        appointments = validate_success(
            api.list_appointments(ws["auth"]["id"], SCHEDULER_HEADERS))
        assert appointments[0]["status"] == "SCHEDULED", (
            "The appointment remains SCHEDULED")


class TestClockDrivenEndings:
    def test_unconfirmed_appointment_becomes_missed(self, api):
        """PRD §2.4: "a `SCHEDULED` appointment still unconfirmed sixty
        minutes past its `scheduled_start` becomes `MISSED`"

        Design: Corner/state_machines/appointment_missed_auto_transition
        """
        ws = setup_approved_with_chair(drug_code="J9113", member_id="M1113")
        appt = book_appointment(ws["auth"]["id"], ws["chair"]["id"],
                                "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")

        advance_clock("2026-08-10T11:01:00Z")
        appointments = validate_success(
            api.list_appointments(ws["auth"]["id"], SCHEDULER_HEADERS))
        by_id = {a["id"]: a for a in appointments}
        assert by_id[appt["id"]]["status"] == "MISSED", (
            "11:01 is sixty-plus minutes past the 10:00 start")

    def test_confirmed_appointment_completes_at_scheduled_end(self, api):
        """PRD §2.4: "a `CONFIRMED` appointment whose `scheduled_end` has been
        reached becomes `COMPLETED`"

        Design: Corner/state_machines/appointment_completed_auto_transition
        """
        ws = setup_approved_with_cleared_clearance_and_chair(
            drug_code="J9114", member_id="M1114")
        appt = book_appointment(ws["auth"]["id"], ws["chair"]["id"],
                                "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
        confirmed = validate_success(
            api.confirm_appointment(appt["id"], SCHEDULER_HEADERS))
        assert confirmed["status"] == "CONFIRMED"

        advance_clock("2026-08-10T11:00:00Z")
        appointments = validate_success(
            api.list_appointments(ws["auth"]["id"], SCHEDULER_HEADERS))
        by_id = {a["id"]: a for a in appointments}
        assert by_id[appt["id"]]["status"] == "COMPLETED", (
            "At clock == scheduled_end the appointment completes "
            "(inclusive bound)")
