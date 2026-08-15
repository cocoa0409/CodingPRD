"""Crew scheduling and concurrency control: half-open shift overlap, season
windows, the staff-release compensation cascade, and the three OCC handshakes
(PRD sections 2.6, 3.2, 3.3, 3.4).

Covers design instances:
  Difficulty/resource_temporal_overlap/crew_shift_half_open_overlap_on_staff
  Corner/validations/crew_shift_season_window_enforced_per_role
  Corner/cross_cutting_layers/staff_release_cascades_cancel_future_shifts_and_locks_identity
  Corner/cross_cutting_layers/occ_crew_shift_stale_staff_version_rejected
  Corner/cross_cutting_layers/occ_permit_approve_stale_fair_version_then_recovery
  Corner/cross_cutting_layers/occ_checklist_countersign_stale_version_rejected
"""
from test_helpers import (
    ApiErrorId,
    create_shift_payload,
    make_crew_headers,
    make_inspector_headers,
    make_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


class TestCrewShiftHalfOpenOverlap:
    def test_back_to_back_shifts_touching_endpoints_are_legal(self, api):
        """PRD section 3.3: "shifts occupy the half-open interval from their
        start hour up to but not including their end hour, so back-to-back
        shifts whose endpoints merely touch do not conflict" and "Booking a
        shift is itself a mutation of the staff ledger: it advances the staff
        member's `version` by one."

        A 10:00 start right after a 06:00-10:00 shift is legal; each accepted
        booking advances the staff OCC version by exactly one.

        Design: Difficulty/resource_temporal_overlap/crew_shift_half_open_overlap_on_staff
        """
        ctx = fx.setup_fair_with_staff("Q")
        sup = ctx["sup"]
        crew = fx.create_staff_via_manager(sup, "Crew Q", ["CREW"])
        v1 = crew["version"]
        fx.book_setup_shift(sup, crew, work_date="2026-08-01",
                            start_hour=6, end_hour=10)
        v2 = fx.get_staff_member(sup, crew["id"])["version"]
        assert v2 == v1 + 1
        sh2 = validate_success(api.create_shift(
            create_shift_payload(crew["id"], v2, work_date="2026-08-01",
                                 start_hour=10, end_hour=14, shift_role="SETUP"),
            make_manager_headers(sup["id"])), 201)
        assert sh2["status"] == "SCHEDULED"
        v3 = fx.get_staff_member(sup, crew["id"])["version"]
        assert v3 == v1 + 2, "exactly two accepted bookings must bump the version twice"

    def test_intersecting_shift_rejected_without_version_drift(self, api):
        """PRD section 3.3: "A new shift that intersects an existing
        `SCHEDULED`, `CONFIRMED`, or `COMPLETED` shift of the same worker on
        the same date is rejected with `ERR_STAFF_SHIFT_OVERLAP`."

        A 09:00-12:00 shift intersects the existing 06:00-10:00 shift under
        half-open semantics; the rejection creates nothing and does not advance
        the staff version.

        Design: Difficulty/resource_temporal_overlap/crew_shift_half_open_overlap_on_staff
        """
        ctx = fx.setup_fair_with_staff("Qb")
        sup = ctx["sup"]
        crew = fx.create_staff_via_manager(sup, "Crew Qb", ["CREW"])
        fx.book_setup_shift(sup, crew, work_date="2026-08-01",
                            start_hour=6, end_hour=10)
        v2 = fx.get_staff_member(sup, crew["id"])["version"]
        resp = api.create_shift(
            create_shift_payload(crew["id"], v2, work_date="2026-08-01",
                                 start_hour=9, end_hour=12, shift_role="SETUP"),
            make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_STAFF_SHIFT_OVERLAP, 409)
        assert fx.get_staff_member(sup, crew["id"])["version"] == v2
        data, meta = validate_paginated(api.list_shifts(
            make_manager_headers(sup["id"]), params={"staff_id": crew["id"]}))
        assert meta["total_count"] == 1 and len(data) == 1


class TestCrewShiftSeasonWindow:
    def test_shift_outside_role_season_window_rejected(self, api):
        """PRD section 3.3: "`SETUP` shifts run from `setup_start_date` through
        the day before `opening_date`; `OPERATIONS` shifts run from
        `opening_date` through `closing_date`, both inclusive; `TEARDOWN`
        shifts run from the day after `closing_date` through
        `teardown_end_date`, both inclusive — and a date in the past or outside
        the window is rejected with `ERR_SHIFT_OUT_OF_SEASON`."

        On opening day 2026-08-03 itself: TEARDOWN is before its window and
        SETUP has just exited its half-open window — both fail.

        Design: Corner/validations/crew_shift_season_window_enforced_per_role
        """
        ctx = fx.setup_fair_with_staff("V4")
        sup = ctx["sup"]
        crew = fx.create_staff_via_manager(sup, "Crew V4", ["CREW"])
        v1 = crew["version"]
        for role in ("TEARDOWN", "SETUP"):
            resp = api.create_shift(
                create_shift_payload(crew["id"], v1, work_date="2026-08-03",
                                     start_hour=6, end_hour=10, shift_role=role),
                make_manager_headers(sup["id"]))
            validate_error(resp, ApiErrorId.ERR_SHIFT_OUT_OF_SEASON, 422)
        assert fx.get_staff_member(sup, crew["id"])["version"] == v1, (
            "rejected bookings must not advance the staff version")


class TestStaffReleaseCascade:
    def test_release_cancels_future_shifts_and_locks_identity(self, api):
        """PRD section 3.3: "Release stamps `released_at` from the logical
        clock, moves the worker to `RELEASED`, and triggers a compensation
        cascade: every `CrewShift` of that worker in `SCHEDULED` or `CONFIRMED`
        status whose `work_date` is the current date or later is moved to
        `CANCELLED`, while past-dated shifts are left untouched for the
        record." Also: "releasing someone already `RELEASED` is
        `ERR_STAFF_INVALID_STATE`" and "Every transition requires the shift to
        be in the status the action expects, else `ERR_SHIFT_INVALID_STATE`;
        `COMPLETED`, `NO_SHOW`, and `CANCELLED` are terminal." PRD section
        2.1: "Any failure of this scoping — wrong function, a `RELEASED` staff
        member, or a cross-fair call — is `ERR_FORBIDDEN`."

        Design: Corner/cross_cutting_layers/staff_release_cascades_cancel_future_shifts_and_locks_identity
        """
        ctx = fx.setup_fair_with_staff("CC4")
        sup = ctx["sup"]
        crew = fx.create_staff_via_manager(sup, "Crew CC4", ["CREW"])
        ride = fx.create_ride(sup, serial_number="SN-CC4-1")
        sh1 = fx.book_setup_shift(sup, crew, work_date="2026-08-01")
        v = fx.get_staff_member(sup, crew["id"])["version"]
        sh2 = validate_success(api.create_shift(
            create_shift_payload(crew["id"], v, work_date="2026-08-02",
                                 start_hour=6, end_hour=10, shift_role="SETUP"),
            make_manager_headers(sup["id"])), 201)
        validate_success(api.cancel_shift(sh2["id"], {}, make_manager_headers(sup["id"])))
        resp = api.confirm_shift(sh2["id"], {}, make_crew_headers(crew["id"]))
        validate_error(resp, ApiErrorId.ERR_SHIFT_INVALID_STATE, 409)
        released = validate_success(api.release_staff(crew["id"], {},
                                                      make_manager_headers(sup["id"])))
        assert released["status"] == "RELEASED"
        assert released["released_at"] is not None
        sh1_after = fx.get_shift(sup, sh1["id"])
        assert sh1_after["status"] == "CANCELLED", (
            "today's SCHEDULED shift must be cancelled by the release cascade")
        resp = api.release_staff(crew["id"], {}, make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_STAFF_INVALID_STATE, 409)
        resp = api.verify_assembly(ride["id"], {}, make_crew_headers(crew["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


class TestOptimisticConcurrency:
    def test_crew_shift_stale_staff_version_rejected_then_recovers(self, api):
        """PRD section 2.6: "Creating a crew shift (`POST /midway/crew-shifts`)
        requires `expected_staff_version` carrying the client's last observed
        `version` of the target `StaffMember`. A mismatch is rejected with
        `ERR_STALE_STAFF_VERSION` (HTTP 412)."

        After one accepted booking bumps the staff version, replaying the stale
        version fails 412; re-reading and resubmitting succeeds.

        Design: Corner/cross_cutting_layers/occ_crew_shift_stale_staff_version_rejected
        """
        ctx = fx.setup_fair_with_staff("CC1")
        sup = ctx["sup"]
        crew = fx.create_staff_via_manager(sup, "Crew CC1", ["CREW"])
        v1 = crew["version"]
        validate_success(api.create_shift(
            create_shift_payload(crew["id"], v1, work_date="2026-08-01",
                                 start_hour=6, end_hour=10, shift_role="SETUP"),
            make_manager_headers(sup["id"])), 201)
        resp = api.create_shift(
            create_shift_payload(crew["id"], v1, work_date="2026-08-01",
                                 start_hour=12, end_hour=16, shift_role="SETUP"),
            make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_STAFF_VERSION, 412)
        v2 = fx.get_staff_member(sup, crew["id"])["version"]
        assert v2 == v1 + 1
        sh2 = validate_success(api.create_shift(
            create_shift_payload(crew["id"], v2, work_date="2026-08-01",
                                 start_hour=12, end_hour=16, shift_role="SETUP"),
            make_manager_headers(sup["id"])), 201)
        assert sh2["status"] == "SCHEDULED"
        data, meta = validate_paginated(api.list_shifts(
            make_manager_headers(sup["id"]), params={"staff_id": crew["id"]}))
        assert meta["total_count"] == 2, "the 412 rejection must create nothing"

    def test_permit_approve_stale_fair_version_then_recovery(self, api):
        """PRD section 2.6: "Approving a permit
        (`POST /midway/permits/{id}/approve`) requires `expected_fair_version`
        carrying the client's last observed `version` of the parent `Fair`. A
        mismatch is rejected with `ERR_STALE_FAIR_VERSION` (HTTP 412). Ride
        registration and the request-permit transition both advance the fair's
        version". PRD section 3.2: "`INSTALLED` and `DISMANTLED` rides never
        qualify" and "Approval requires the permit to be `PENDING`
        (`ERR_PERMIT_INVALID_STATE`)".

        Design: Corner/cross_cutting_layers/occ_permit_approve_stale_fair_version_then_recovery
        """
        ctx = fx.setup_permit_requested("CC2")
        sup = ctx["sup"]
        approver = ctx["inspectors"][1]
        appt = fx.schedule_fair_wide(sup)
        fx.set_clock(fx.INSPECTION_CLOCK_ISO)
        fx.complete_appointment(appt, outcome="PASS")
        fair = fx.get_success_data(api.get_fair(sup["fair_id"],
                                                make_manager_headers(sup["id"])))
        v_stale = fair["version"]
        # Registering another ride advances the fair's version (inventory sync).
        fx.create_ride(sup, name="Late Ride", ride_class="KIDDIE",
                       capacity_per_cycle=6, min_rider_height_in=30,
                       max_rider_height_in=60, wind_limit_mph=35,
                       cycle_inspection_interval=10, serial_number="SN-CC2-2")
        resp = api.approve_permit(ctx["permit"]["id"],
                                  {"expected_fair_version": v_stale},
                                  make_inspector_headers(approver["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_FAIR_VERSION, 412)
        v_fresh = fx.get_success_data(api.get_fair(sup["fair_id"],
                                                   make_manager_headers(sup["id"])))["version"]
        approved = validate_success(api.approve_permit(
            ctx["permit"]["id"], {"expected_fair_version": v_fresh},
            make_inspector_headers(approver["id"])))
        assert approved["status"] == "APPROVED"
        assert approved["final_fee_cents"] == 39000, (
            "only the SETUP_VERIFIED THRILL ride qualifies; the INSTALLED "
            "KIDDIE ride is excluded: 25000 + 14000")
        v_latest = fx.get_success_data(api.get_fair(sup["fair_id"],
                                                    make_manager_headers(sup["id"])))["version"]
        resp = api.approve_permit(ctx["permit"]["id"],
                                  {"expected_fair_version": v_latest},
                                  make_inspector_headers(approver["id"]))
        validate_error(resp, ApiErrorId.ERR_PERMIT_INVALID_STATE, 409)

    def test_checklist_countersign_stale_version_rejected(self, api):
        """PRD section 2.6: "Countersigning a daily checklist
        (`POST /midway/daily-checklists/{id}/countersign`) requires
        `expected_checklist_version` carrying the countersigner's last observed
        `version` of the `DailyChecklist`. A mismatch is rejected with
        `ERR_STALE_CHECKLIST_VERSION` (HTTP 412)."

        The creation-time version is stale once submission advances it; the
        post-submit version countersigns successfully.

        Design: Corner/cross_cutting_layers/occ_checklist_countersign_stale_version_rejected
        """
        ctx = fx.setup_permitted_fair("CC3")
        fx.begin_day(ctx)
        op, sup = ctx["op"], ctx["sup"]
        chk = fx.open_checklist(op, ctx["ride"]["id"], ctx["day"]["id"], items_total=5)
        v_created = chk["version"]
        chk = fx.submit_checklist(op, chk["id"], 5)
        v_submitted = chk["version"]
        assert v_submitted == v_created + 1
        resp = api.countersign_checklist(
            chk["id"], {"expected_checklist_version": v_created},
            make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_CHECKLIST_VERSION, 412)
        chk = validate_success(api.countersign_checklist(
            chk["id"], {"expected_checklist_version": v_submitted},
            make_manager_headers(sup["id"])))
        assert chk["status"] == "COUNTERSIGNED"
        assert chk["version"] == v_submitted + 1
