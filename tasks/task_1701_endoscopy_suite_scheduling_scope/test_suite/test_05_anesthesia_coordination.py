"""Anesthesia assignments: coverage gates, closed-interval conflicts, ledger."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_clock,
    assert_anesthesia_assignment,
    assert_instants_equal,
    assess_prep,
    check_in,
    confirm_assignment,
    confirm_prep,
    create_anesthesia_provider,
    create_assignment,
    create_booking,
    create_booking_payload,
    create_colono_type,
    create_egd_type,
    create_in_progress_booking,
    create_patient,
    create_provider,
    create_room,
    create_scope,
    get_anesthesia_provider,
    get_assignment,
    get_booking,
    get_scope,
    make_anesthesia_provider_headers,
    make_endoscopist_headers,
    make_registry,
    setup_two_assignment_ledger,
    start_procedure,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["unit_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


def _mac_booking_checked_in(reg, start="2026-08-05T09:00:00Z", anesthesia="MAC"):
    booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                             reg["ptype"]["id"], reg["room"]["id"],
                             scheduled_start=start, anesthesia_type=anesthesia)
    confirm_prep(booking["id"])
    advance_clock(start)
    check_in(booking["id"])
    return booking


class TestConfirmedCoverageGate:
    def test_start_without_assignment_rejected(self, api):
        """PRD §3.4: "whenever `anesthesia_type` is not `NONE`, a `CONFIRMED`
        AnesthesiaAssignment for the booking must already exist
        (`ERR_ANESTHESIA_NOT_CONFIRMED`)".

        Design: Difficulty/cross_entity_state_dependency/booking_start_requires_confirmed_anesthesia_assignment
        """
        reg = make_registry(mrn="M7001", serial="SC-A1")
        booking = _mac_booking_checked_in(reg)
        resp = api.start_booking(booking["id"], {"scope_id": reg["scope"]["id"]},
                                 make_endoscopist_headers(reg["provider"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ANESTHESIA_NOT_CONFIRMED)
        assert get_booking(booking["id"])["status"] == "CHECKED_IN"

    def test_assigned_is_not_enough_confirmed_unblocks(self, api):
        """PRD §3.4: "whenever `anesthesia_type` is not `NONE`, a `CONFIRMED`
        AnesthesiaAssignment for the booking must already exist
        (`ERR_ANESTHESIA_NOT_CONFIRMED`)".
        PRD §3.3: "A new assignment is born in `ASSIGNED`".

        Design: Difficulty/cross_entity_state_dependency/booking_start_requires_confirmed_anesthesia_assignment
        """
        reg = make_registry(mrn="M7002", serial="SC-A2")
        ap1 = create_anesthesia_provider()
        booking = _mac_booking_checked_in(reg)
        assignment = create_assignment(booking["id"], ap1["id"])
        assert assignment["status"] == "ASSIGNED"
        resp = api.start_booking(booking["id"], {"scope_id": reg["scope"]["id"]},
                                 make_endoscopist_headers(reg["provider"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ANESTHESIA_NOT_CONFIRMED)
        confirm_assignment(assignment["id"], ap1["id"])
        data = validate_success(api.start_booking(
            booking["id"], {"scope_id": reg["scope"]["id"]},
            make_endoscopist_headers(reg["provider"]["id"])), 200)
        assert data["status"] == "IN_PROGRESS"
        assert get_scope(reg["scope"]["id"])["status"] == "IN_USE"
        assert get_assignment(assignment["id"])["status"] == "CONFIRMED"


class TestClosedIntervalConflict:
    def _three_room_scenario(self):
        patient = create_patient(mrn="M8101", date_of_birth="1990-05-05")
        provider = create_provider("Dr R")
        t_col = create_colono_type()
        rooms = {n: create_room(name=n) for n in ("RA", "RB", "RC")}
        ap1 = create_anesthesia_provider()
        bc = create_booking(patient["id"], provider["id"], t_col["id"],
                            rooms["RA"]["id"], scheduled_start="2026-08-03T09:00:00Z",
                            anesthesia_type="MAC")
        ac = create_assignment(bc["id"], ap1["id"])
        bd = create_booking(patient["id"], provider["id"], t_col["id"],
                            rooms["RB"]["id"], scheduled_start="2026-08-03T09:50:00Z",
                            anesthesia_type="MAC")
        be = create_booking(patient["id"], provider["id"], t_col["id"],
                            rooms["RC"]["id"], scheduled_start="2026-08-03T09:51:00Z",
                            anesthesia_type="MAC")
        return {"ap1": ap1, "ac": ac, "bd": bd, "be": be, "bc": bc}

    def test_anesthesia_conflict_closed_interval_touching_rejected(self, api):
        """PRD §3.3: "An assignment inherits the booking's scheduled procedure
        window, and a new assignment conflicts with any existing `ASSIGNED` or
        `CONFIRMED` assignment of the same anesthesia provider whenever the two
        windows share any instant — the intervals are closed, so assignments whose
        windows merely touch at an endpoint conflict and are refused with
        `ERR_ANESTHESIA_TIME_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/anesthesia_conflict_closed_interval_touching_rejected
        """
        fx = self._three_room_scenario()
        resp = api.create_anesthesia_assignment(
            {"booking_id": fx["bd"]["id"], "anesthesia_provider_id": fx["ap1"]["id"]},
            SCHED)
        validate_error(resp, ApiErrorId.ERR_ANESTHESIA_TIME_CONFLICT)

    def test_anesthesia_one_minute_gap_permitted(self, api):
        """PRD §3.3: "the intervals are closed, so assignments whose windows
        merely touch at an endpoint conflict and are refused with
        `ERR_ANESTHESIA_TIME_CONFLICT`."
        PRD §3.3: "Those snapshots feed the `scheduled_minutes` ledger on each
        AnesthesiaProvider, which at any moment equals the sum of `minutes` over
        that provider's assignments in `ASSIGNED` or `CONFIRMED` status."

        Design: Difficulty/resource_temporal_overlap/anesthesia_conflict_closed_interval_touching_rejected
        """
        fx = self._three_room_scenario()
        ae = validate_success(api.create_anesthesia_assignment(
            {"booking_id": fx["be"]["id"], "anesthesia_provider_id": fx["ap1"]["id"]},
            SCHED), 201)
        assert_anesthesia_assignment(ae)
        # 50 (09:00-09:50 booking) + 50 (09:51-10:41 booking); the rejected
        # touching attempt contributed nothing.
        assert get_anesthesia_provider(fx["ap1"]["id"])["scheduled_minutes"] == 100


class TestAbortCascade:
    def _abort_scenario(self):
        fx = setup_two_assignment_ledger()
        sca = create_scope(serial_number="SC-A")
        ba = fx["ba"]
        confirm_prep(ba["id"])
        advance_clock("2026-08-06T09:00:00Z")
        check_in(ba["id"])
        confirm_assignment(fx["aa"]["id"], fx["ap1"]["id"])
        start_procedure(ba["id"], fx["provider"]["id"], sca["id"])
        assess_prep(ba["id"], fx["provider"]["id"], 1, 2, 2)
        fx["sca"] = sca
        return fx

    def test_inadequate_prep_abort_cascades_to_assignment(self, api):
        """PRD §3.5: "The same scope and anesthesia cascades apply — the scope
        goes to `AWAITING_REPROCESS` when an active usage exists, and an
        `ASSIGNED` or `CONFIRMED` assignment is cancelled with its minutes
        released."

        Design: Difficulty/transitive_cascade/inadequate_prep_abort_cascades_to_anesthesia_minutes
        """
        fx = self._abort_scenario()
        assert get_anesthesia_provider(fx["ap1"]["id"])["scheduled_minutes"] == 85
        data = validate_success(api.abort_booking(
            fx["ba"]["id"], {"reason": "prep inadequate"},
            make_endoscopist_headers(fx["provider"]["id"])), 200)
        assert data["status"] == "ABORTED_PREP_INADEQUATE"
        assert get_assignment(fx["aa"]["id"])["status"] == "CANCELLED", (
            "cancelled by the booking transition, not by a direct call")

    def test_inadequate_prep_abort_releases_minutes_and_scope(self, api):
        """PRD §3.5: "an `ASSIGNED` or `CONFIRMED` assignment is cancelled with
        its minutes released."
        PRD §3.3: "Creating an assignment adds its minutes to the ledger;
        completion or cancellation releases them."

        Design: Difficulty/transitive_cascade/inadequate_prep_abort_cascades_to_anesthesia_minutes
        """
        fx = self._abort_scenario()
        validate_success(api.abort_booking(
            fx["ba"]["id"], {"reason": "prep inadequate"},
            make_endoscopist_headers(fx["provider"]["id"])), 200)
        assert get_anesthesia_provider(fx["ap1"]["id"])["scheduled_minutes"] == 35, (
            "85 - 50 released; the other booking's 35 remain")
        assert get_scope(fx["sca"]["id"])["status"] == "AWAITING_REPROCESS"


class TestLedgerCompensation:
    def test_booking_cancel_cascade_releases_minutes(self, api):
        """PRD §3.3: "When a booking is cancelled, marked no-show, aborted, or
        rescheduled — or when its `anesthesia_type` is amended to `NONE` — every
        `ASSIGNED` or `CONFIRMED` assignment on that booking moves to `CANCELLED`
        and its minutes are released."

        Design: Difficulty/compensating_invariant/anesthesia_scheduled_minutes_ledger_compensation
        """
        fx = setup_two_assignment_ledger()
        assert get_anesthesia_provider(fx["ap1"]["id"])["scheduled_minutes"] == 85
        validate_success(api.cancel_booking(fx["bb"]["id"],
                                            {"reason": "patient request"}, SCHED), 200)
        assert get_assignment(fx["ab"]["id"])["status"] == "CANCELLED"
        # 85 - 35 released (bb is the 35-minute EGD); the COLONO's 50 remain.
        assert get_anesthesia_provider(fx["ap1"]["id"])["scheduled_minutes"] == 50

    def test_reschedule_cascade_and_reassignment_snapshot(self, api):
        """PRD §3.5: "a brand-new booking is created with its `rescheduled_from_id`
        pointing back at the old one, its axis at `SCHEDULED`, its prep axis at
        `PREP_PENDING`, and version 1 — the response carries the new booking with
        a 201 status. The old booking's active anesthesia assignment is cancelled,
        releasing minutes."
        PRD §3.3: "Each assignment stores a `minutes` field: a snapshot of the
        booking's `procedure_minutes` taken at creation and never recomputed".

        Design: Difficulty/compensating_invariant/anesthesia_scheduled_minutes_ledger_compensation
        """
        fx = setup_two_assignment_ledger()
        validate_success(api.cancel_booking(fx["bb"]["id"],
                                            {"reason": "patient request"}, SCHED), 200)
        # 85 - 35 released (bb is the 35-minute EGD); the COLONO's 50 remain.
        assert get_anesthesia_provider(fx["ap1"]["id"])["scheduled_minutes"] == 50
        new_booking = validate_success(api.reschedule_booking(
            fx["ba"]["id"], {"expected_booking_version": fx["ba"]["version"],
                             "new_scheduled_start": "2026-08-07T09:00:00Z"}, SCHED), 201)
        assert new_booking["rescheduled_from_id"] == fx["ba"]["id"]
        assert new_booking["status"] == "SCHEDULED"
        assert new_booking["prep_status"] == "PREP_PENDING", "reschedule resets prep"
        assert new_booking["version"] == 1
        assert get_booking(fx["ba"]["id"])["status"] == "RESCHEDULED"
        assert get_assignment(fx["aa"]["id"])["status"] == "CANCELLED"
        assert get_anesthesia_provider(fx["ap1"]["id"])["scheduled_minutes"] == 0
        ac2 = create_assignment(new_booking["id"], fx["ap1"]["id"])
        assert ac2["minutes"] == 50, "snapshot of the replacement's procedure_minutes"
        assert get_anesthesia_provider(fx["ap1"]["id"])["scheduled_minutes"] == 50


class TestAssignmentLifecycle:
    def test_assignment_double_confirm_rejected(self, api):
        """PRD §3.3: "only an `ASSIGNED` assignment can be confirmed
        (`ERR_ASSIGNMENT_STATE_INVALID`)".

        Design: Corner/state_machines/assignment_double_confirm_rejected
        """
        reg = make_registry(mrn="MRN-DC", serial="SC-DC", with_scope=False)
        ap1 = create_anesthesia_provider()
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-03T09:00:00Z",
                                 anesthesia_type="MAC")
        a1 = create_assignment(booking["id"], ap1["id"])
        confirm_assignment(a1["id"], ap1["id"])
        resp = api.confirm_anesthesia_assignment(
            a1["id"], make_anesthesia_provider_headers(ap1["id"]))
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_STATE_INVALID)
        assert get_assignment(a1["id"])["status"] == "CONFIRMED"

    def test_assignment_direct_cancel_releases_minutes(self, api):
        """PRD §3.3: "An explicit cancellation may be filed by a
        `SchedulingCoordinator` or by the anesthesia provider, accepts an optional
        `reason` that is stored into `cancel_reason`, and is legal only from
        `ASSIGNED` or `CONFIRMED` (`ERR_ASSIGNMENT_STATE_INVALID`); it releases
        the assignment's minutes from the ledger."

        Design: Corner/state_machines/assignment_direct_cancel_releases_minutes
        """
        reg = make_registry(mrn="MRN-AX", serial="SC-AX", with_scope=False)
        ap1 = create_anesthesia_provider()
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-03T09:00:00Z",
                                 anesthesia_type="MAC")
        a1 = create_assignment(booking["id"], ap1["id"])
        assert get_anesthesia_provider(ap1["id"])["scheduled_minutes"] == 50
        data = validate_success(api.cancel_anesthesia_assignment(
            a1["id"], {"reason": "provider unavailable"}, SCHED), 200)
        assert data["status"] == "CANCELLED"
        assert data["cancel_reason"] == "provider unavailable"
        assert get_anesthesia_provider(ap1["id"])["scheduled_minutes"] == 0

    def test_anesthesia_assignment_requires_non_none_type(self, api):
        """PRD §3.3: "Creation is refused outright when the booking's
        `anesthesia_type` is `NONE` — there is nothing to staff — with
        `ERR_ANESTHESIA_TYPE_NONE`".

        Design: Corner/validations/anesthesia_assignment_requires_non_none_type
        """
        reg = make_registry(mrn="MRN-AN", serial="SC-AN", with_scope=False)
        ap1 = create_anesthesia_provider()
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-03T09:00:00Z",
                                 anesthesia_type="NONE")
        resp = api.create_anesthesia_assignment(
            {"booking_id": booking["id"], "anesthesia_provider_id": ap1["id"]}, SCHED)
        validate_error(resp, ApiErrorId.ERR_ANESTHESIA_TYPE_NONE)

    def test_anesthesia_provider_suspended_blocks_assignment(self, api):
        """PRD §3.3: "and refused with `ERR_ANESTHESIA_PROVIDER_SUSPENDED` when the
        named anesthesia provider is `SUSPENDED`."

        Design: Corner/errors/anesthesia_provider_suspended_blocks_assignment
        """
        reg = make_registry(mrn="MRN-AS", serial="SC-AS", with_scope=False)
        ap1 = create_anesthesia_provider()
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-03T09:00:00Z",
                                 anesthesia_type="MAC")
        validate_success(api.patch_anesthesia_provider(
            ap1["id"], {"credential_status": "SUSPENDED"}, ADMIN), 200)
        resp = api.create_anesthesia_assignment(
            {"booking_id": booking["id"], "anesthesia_provider_id": ap1["id"]}, SCHED)
        validate_error(resp, ApiErrorId.ERR_ANESTHESIA_PROVIDER_SUSPENDED)

    def test_anesthesia_provider_cannot_confirm_others_assignment(self, api):
        """PRD §3.3: "Confirmation belongs to the assigned anesthesia provider
        alone: the caller's `X-User-ID` must equal the assignment's
        `anesthesia_provider_id` (`ERR_ANESTHESIA_OWNERSHIP_MISMATCH` otherwise)".

        Design: Corner/rbac/anesthesia_provider_cannot_confirm_others_assignment
        """
        reg = make_registry(mrn="MRN-AO", serial="SC-AO", with_scope=False)
        ap1 = create_anesthesia_provider("Ann One")
        ap2 = create_anesthesia_provider("Ann Two")
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-03T09:00:00Z",
                                 anesthesia_type="MAC")
        a1 = create_assignment(booking["id"], ap1["id"])
        resp = api.confirm_anesthesia_assignment(
            a1["id"], make_anesthesia_provider_headers(ap2["id"]))
        validate_error(resp, ApiErrorId.ERR_ANESTHESIA_OWNERSHIP_MISMATCH)
        assert get_assignment(a1["id"])["status"] == "ASSIGNED"

    def test_assignment_minutes_snapshot_survives_anesthesia_patch(self, api):
        """PRD §3.3: "Each assignment stores a `minutes` field: a snapshot of the
        booking's `procedure_minutes` taken at creation and never recomputed, even
        if the booking is amended later."
        PRD §3.5: "Changing `anesthesia_type` recomputes the whole time window —
        `procedure_minutes`, `scheduled_end`, and `room_block_end` — and re-runs
        the lead-time, room-overlap, and day-capacity validations of §3.2 against
        the new figure".

        Design: Corner/calculations/assignment_minutes_snapshot_survives_anesthesia_patch
        """
        reg = make_registry(mrn="MRN-SN2", serial="SC-SN2", with_scope=False)
        ap1 = create_anesthesia_provider()
        booking = create_booking(reg["patient"]["id"], reg["provider"]["id"],
                                 reg["ptype"]["id"], reg["room"]["id"],
                                 scheduled_start="2026-08-05T09:00:00Z",
                                 anesthesia_type="MAC")
        a1 = create_assignment(booking["id"], ap1["id"])
        assert a1["minutes"] == 50
        patched = validate_success(api.patch_booking(
            booking["id"], {"expected_booking_version": booking["version"],
                            "anesthesia_type": "GENERAL"}, SCHED), 200)
        assert patched["procedure_minutes"] == 55, "40 + GENERAL 15"
        assert patched["version"] == booking["version"] + 1
        assert_instants_equal(patched["room_block_end"], "2026-08-05T10:10:00Z")
        assert get_assignment(a1["id"])["minutes"] == 50, "snapshot not recomputed"
        assert get_anesthesia_provider(ap1["id"])["scheduled_minutes"] == 50

    def test_anesthesia_assignment_not_found_returns_404(self, api):
        """
        PRD §2.6: "Each unresolved reference maps to its own error:
        `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_PROCEDURE_TYPE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND` (also raised for an
        unresolvable `new_room_id`), `ERR_ANESTHESIA_PROVIDER_NOT_FOUND`,
        `ERR_SCOPE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_SCOPE_USAGE_NOT_FOUND`,
        `ERR_REPROCESSING_CYCLE_NOT_FOUND`, `ERR_CULTURE_TEST_NOT_FOUND`,
        `ERR_QUARANTINE_CASE_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`,
        `ERR_QUALITY_REPORT_NOT_FOUND`, and `ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND`,
        all HTTP 404."

        Design: Corner/errors/anesthesia_assignment_not_found_returns_404
        """
        resp = api.get_anesthesia_assignment(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND)
