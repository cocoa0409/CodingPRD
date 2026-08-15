"""Roster scheduling, check-in windows, capacity, rest gaps, and rotation
(PRD §3.5)."""
from test_helpers import (
    OPS,
    ApiErrorId,
    activate_permit,
    add_on_duty_attendant,
    add_on_duty_entrant,
    approve_plan,
    create_account,
    create_ops_team,
    create_permit,
    create_plan,
    create_roster_entry_payload,
    create_space,
    issue_permit,
    make_personnel,
    post_reading,
    read_roster_entry,
    roster_checkin,
    roster_checkout,
    schedule_roster,
    schedule_standby,
    set_clock,
    setup_active_permit,
    setup_issued_permit,
    standby_checkin,
    validate_error,
    validate_paginated,
)

DAY = "2026-08-03"
DAY2 = "2026-08-04"


class TestRosterSchedulingRules:
    def test_shift_duration_exceeds(self, api):
        """PRD §3.5: "The shift length must not exceed the worker's
        `max_duty_hours`, else `ERR_SHIFT_DURATION_EXCEEDS`."
        PRD §3.1: "Each worker's `max_duty_hours` caps the length of any
        single scheduled roster shift, defaulting to 12 hours when omitted."

        Design: Corner/validations/corner_shift_duration_exceeds
        """
        ctx = setup_issued_permit(at="2026-08-03T05:00:00Z", with_plan=False)
        team = ctx["team"]
        worker = make_personnel("Worker One", [])

        resp = api.create_roster_entry(
            ctx["permit"]["id"],
            create_roster_entry_payload(
                worker["id"], assignment_role="ENTRANT",
                scheduled_start_at=f"{DAY}T06:00:00Z",
                scheduled_end_at=f"{DAY}T19:00:00Z"),
            team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_SHIFT_DURATION_EXCEEDS)
        assert resp.status_code == 422, "13h exceeds the default 12h cap"

        ok = schedule_roster(ctx["permit"]["id"], team["supervisor_headers"],
                             worker["id"], assignment_role="ENTRANT",
                             scheduled_start_at=f"{DAY}T06:00:00Z",
                             scheduled_end_at=f"{DAY}T18:00:00Z")
        assert ok["status"] == "SCHEDULED", (
            "an exactly-12-hour shift is within the inclusive bound")

    def test_attendant_qualification_missing(self, api):
        """PRD §3.5: "Slots with `assignment_role` `ATTENDANT` require
        personnel holding the `ATTENDANT` qualification
        (`ERR_PERSONNEL_NOT_QUALIFIED`)."

        Design: Corner/validations/corner_attendant_qualification_missing
        """
        ctx = setup_issued_permit(at="2026-08-03T05:00:00Z", with_plan=False)
        team = ctx["team"]
        worker = make_personnel("Worker One", [])

        resp = api.create_roster_entry(
            ctx["permit"]["id"],
            create_roster_entry_payload(
                worker["id"], assignment_role="ATTENDANT",
                scheduled_start_at=f"{DAY}T06:00:00Z",
                scheduled_end_at=f"{DAY}T12:00:00Z"),
            team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_PERSONNEL_NOT_QUALIFIED)
        assert resp.status_code == 422
        _, meta = validate_paginated(api.list_roster_entries(
            OPS, params={"permit_id": ctx["permit"]["id"]}))
        assert meta["total_count"] == 0

    def test_rest_gap_masks_qualification_error(self, api):
        """PRD §2.6: "Only after these come optimistic-concurrency checks,
        state-transition legality, and then the domain safety, capacity,
        temporal, qualification, and fiscal gates described throughout §3."
        PRD §3.5: "A worker may not be scheduled with inadequate rest: a new
        entry conflicts with any existing `SCHEDULED` or `ON_DUTY` entry of the
        same personnel when the new shift starts before 8 hours after the
        existing shift ends **and** the existing shift starts before 8 hours
        after the new shift ends — a gap of exactly 8 hours is legal — and
        violations are rejected with `ERR_INSUFFICIENT_REST`."

        Design: Difficulty/priority_pair_validation_conflict/roster_rest_gap_precedes_qualification_error
        """
        ctx = setup_issued_permit(at="2026-08-03T05:00:00Z", with_plan=False,
                                  space_overrides={"max_entrants": 3})
        team = ctx["team"]
        # Worker has NO qualifications: the ATTENDANT slot below also fails
        # the qualification gate, but the temporal gate is evaluated first.
        worker = make_personnel("Worker One", [])
        schedule_roster(ctx["permit"]["id"], team["supervisor_headers"],
                        worker["id"], assignment_role="ENTRANT",
                        scheduled_start_at=f"{DAY}T06:00:00Z",
                        scheduled_end_at=f"{DAY}T12:00:00Z")

        resp = api.create_roster_entry(
            ctx["permit"]["id"],
            create_roster_entry_payload(
                worker["id"], assignment_role="ATTENDANT",
                scheduled_start_at=f"{DAY}T15:00:00Z",
                scheduled_end_at=f"{DAY}T23:00:00Z"),
            team["supervisor_headers"])
        err = validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_REST)
        assert resp.status_code == 409
        assert err["error_id"] != "ERR_PERSONNEL_NOT_QUALIFIED", (
            "15:00 < 12:00 + 8h = 20:00: the temporal gate masks the "
            "qualification gate")
        _, meta = validate_paginated(api.list_roster_entries(
            OPS, params={"personnel_id": worker["id"]}))
        assert meta["total_count"] == 1, "no second entry was created"

    def test_rest_gap_fires_alone_for_qualified_worker(self, api):
        """PRD §3.5: "A worker may not be scheduled with inadequate rest: a
        new entry conflicts with any existing `SCHEDULED` or `ON_DUTY` entry of
        the same personnel when the new shift starts before 8 hours after the
        existing shift ends **and** the existing shift starts before 8 hours
        after the new shift ends — a gap of exactly 8 hours is legal — and
        violations are rejected with `ERR_INSUFFICIENT_REST`."

        Design: Difficulty/priority_pair_validation_conflict/roster_rest_gap_precedes_qualification_error
        """
        ctx = setup_issued_permit(at="2026-08-03T05:00:00Z", with_plan=False,
                                  space_overrides={"max_entrants": 3})
        team = ctx["team"]
        # Qualified attendant: the qualification gate passes, isolating the
        # rest-gap violation.
        worker = make_personnel("Worker One", ["ATTENDANT"])
        schedule_roster(ctx["permit"]["id"], team["supervisor_headers"],
                        worker["id"], assignment_role="ATTENDANT",
                        scheduled_start_at=f"{DAY}T06:00:00Z",
                        scheduled_end_at=f"{DAY}T12:00:00Z")

        resp = api.create_roster_entry(
            ctx["permit"]["id"],
            create_roster_entry_payload(
                worker["id"], assignment_role="ATTENDANT",
                scheduled_start_at=f"{DAY}T19:59:00Z",
                scheduled_end_at=f"{DAY}T23:00:00Z"),
            team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_REST)

    def test_rest_gap_exactly_eight_hours_legal(self, api):
        """PRD §3.5: "a gap of exactly 8 hours is legal — and violations are
        rejected with `ERR_INSUFFICIENT_REST`."

        Design: Difficulty/resource_temporal_overlap/roster_rest_gap_exact_boundary
        """
        ctx = setup_issued_permit(at="2026-08-03T05:00:00Z", with_plan=False,
                                  space_overrides={"max_entrants": 3})
        team = ctx["team"]
        worker = make_personnel("Worker One", [])
        schedule_roster(ctx["permit"]["id"], team["supervisor_headers"],
                        worker["id"], assignment_role="ENTRANT",
                        scheduled_start_at=f"{DAY}T06:00:00Z",
                        scheduled_end_at=f"{DAY}T12:00:00Z")
        # 20:00 == 12:00 + 8h exactly: the boundary is legal.
        second = schedule_roster(ctx["permit"]["id"],
                                 team["supervisor_headers"], worker["id"],
                                 assignment_role="ENTRANT",
                                 scheduled_start_at=f"{DAY}T20:00:00Z",
                                 scheduled_end_at=f"{DAY}T23:00:00Z")
        assert second["status"] == "SCHEDULED"

    def test_rest_gap_one_minute_short_rejected(self, api):
        """PRD §3.5: "a new entry conflicts with any existing `SCHEDULED` or
        `ON_DUTY` entry of the same personnel when the new shift starts before
        8 hours after the existing shift ends **and** the existing shift starts
        before 8 hours after the new shift ends — a gap of exactly 8 hours is
        legal — and violations are rejected with `ERR_INSUFFICIENT_REST`."

        Design: Difficulty/resource_temporal_overlap/roster_rest_gap_exact_boundary
        """
        ctx = setup_issued_permit(at="2026-08-03T05:00:00Z", with_plan=False,
                                  space_overrides={"max_entrants": 3})
        team = ctx["team"]
        worker = make_personnel("Worker One", [])
        schedule_roster(ctx["permit"]["id"], team["supervisor_headers"],
                        worker["id"], assignment_role="ENTRANT",
                        scheduled_start_at=f"{DAY}T06:00:00Z",
                        scheduled_end_at=f"{DAY}T12:00:00Z")
        # 19:59 is one minute short of the 20:00 boundary.
        resp = api.create_roster_entry(
            ctx["permit"]["id"],
            create_roster_entry_payload(
                worker["id"], assignment_role="ENTRANT",
                scheduled_start_at=f"{DAY}T19:59:00Z",
                scheduled_end_at=f"{DAY}T23:00:00Z"),
            team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_REST)
        _, meta = validate_paginated(api.list_roster_entries(
            OPS, params={"personnel_id": worker["id"]}))
        assert meta["total_count"] == 1, (
            "only the legal shift exists after the rejected attempt")


class TestCheckInWindowsAndDuty:
    def test_checkin_window_not_open(self, api):
        """PRD §3.5: "the current time to fall inside the check-in window: no
        earlier than 15 minutes before `scheduled_start_at`
        (`ERR_CHECKIN_WINDOW_NOT_OPEN`) and no later than `scheduled_end_at`
        (`ERR_CHECKIN_WINDOW_EXPIRED`)."

        Design: Corner/validations/corner_checkin_window_not_open
        """
        ctx = setup_active_permit(at="2026-08-03T05:30:00Z")
        team = ctx["team"]
        att2 = make_personnel("Att Two", ["ATTENDANT"])
        entry = schedule_roster(ctx["permit"]["id"],
                                team["supervisor_headers"], att2["id"],
                                assignment_role="ATTENDANT",
                                scheduled_start_at=f"{DAY}T07:00:00Z",
                                scheduled_end_at=f"{DAY}T17:00:00Z")
        # 05:30 < 07:00 - 15min = 06:45: the window is not open yet.
        resp = api.roster_check_in(entry["id"], team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_CHECKIN_WINDOW_NOT_OPEN)
        assert read_roster_entry(entry["id"])["status"] == "SCHEDULED"

    def test_checkin_window_expired(self, api):
        """PRD §3.5: "no earlier than 15 minutes before `scheduled_start_at`
        (`ERR_CHECKIN_WINDOW_NOT_OPEN`) and no later than `scheduled_end_at`
        (`ERR_CHECKIN_WINDOW_EXPIRED`)."

        Design: Corner/errors/corner_checkin_window_expired
        """
        ctx = setup_active_permit(at="2026-08-03T05:30:00Z")
        team = ctx["team"]
        set_clock("2026-08-03T08:00:00Z")
        # Create an entry whose window is fully in the past (creation performs
        # no sweep).
        entry = schedule_roster(ctx["permit"]["id"],
                                team["supervisor_headers"],
                                team["attendant"]["id"],
                                assignment_role="ATTENDANT",
                                scheduled_start_at=f"{DAY}T06:00:00Z",
                                scheduled_end_at=f"{DAY}T07:00:00Z")
        resp = api.roster_check_in(entry["id"], team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_CHECKIN_WINDOW_EXPIRED)
        assert read_roster_entry(entry["id"])["status"] == "SCHEDULED", (
            "08:00 > scheduled_end 07:00; no clock-set happened after "
            "creation, so the no-show sweep has not run")

    def test_checkout_not_on_duty_invalid(self, api):
        """PRD §3.5: "An `EntrySupervisor` checks an `ON_DUTY` worker out,
        moving the entry to `COMPLETED` with `checked_out_at` stamped" —
        checking out an entry that never checked in is not a defined
        transition and is rejected with the roster state error
        `ERR_ROSTER_INVALID_STATE` ("Checking a rostered worker in requires the
        entry to be `SCHEDULED` (`ERR_ROSTER_INVALID_STATE`), the parent permit
        to be `ACTIVE` (`ERR_PERMIT_INVALID_STATE`), and the current time to
        fall inside the check-in window: no earlier than 15 minutes before
        `scheduled_start_at` (`ERR_CHECKIN_WINDOW_NOT_OPEN`) and no later than
        `scheduled_end_at` (`ERR_CHECKIN_WINDOW_EXPIRED`)").

        Design: Corner/errors/corner_checkout_not_on_duty_invalid
        """
        ctx = setup_issued_permit(at="2026-08-03T06:00:00Z", with_plan=False)
        team = ctx["team"]
        entry = schedule_roster(ctx["permit"]["id"],
                                team["supervisor_headers"],
                                team["entrant"]["id"],
                                assignment_role="ENTRANT",
                                scheduled_start_at=f"{DAY}T10:00:00Z",
                                scheduled_end_at=f"{DAY}T18:00:00Z")
        resp = api.roster_check_out(entry["id"], team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_ROSTER_INVALID_STATE)
        assert read_roster_entry(entry["id"])["status"] == "SCHEDULED"

    def test_roster_no_show_sweep(self, api):
        """PRD §3.5: "Entries still `SCHEDULED` when the logical clock passes
        15 minutes beyond their `scheduled_start_at` are swept to `NO_SHOW`;
        exactly 15 minutes past does not flip them, only strictly later."
        PRD §2.4: "Every such advance runs the system sweeps against the new
        logical time: roster entries and standby assignments still `SCHEDULED`
        past their no-show grace are flipped to `NO_SHOW`, verified isolations
        whose validity window has closed are flipped to `EXPIRED`,
        monitoring-gap suspensions fire, and exposure classifications are
        recomputed for every on-duty roster entry."

        Design: Corner/state_machines/corner_roster_no_show_sweep
        """
        ctx = setup_issued_permit(at="2026-08-03T06:00:00Z", with_plan=False)
        team = ctx["team"]
        entry = schedule_roster(ctx["permit"]["id"],
                                team["supervisor_headers"],
                                team["entrant"]["id"],
                                assignment_role="ENTRANT",
                                scheduled_start_at=f"{DAY}T10:00:00Z",
                                scheduled_end_at=f"{DAY}T12:00:00Z")

        set_clock("2026-08-03T10:15:00Z")
        mid = read_roster_entry(entry["id"])
        assert mid["status"] == "SCHEDULED", (
            "exactly start + 15 minutes does not flip (strictly-greater rule)")

        set_clock("2026-08-03T10:16:00Z")
        final = read_roster_entry(entry["id"])
        assert final["status"] == "NO_SHOW"

        resp = api.roster_check_in(entry["id"], team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_ROSTER_INVALID_STATE)

    def test_personnel_already_on_duty(self, api):
        """PRD §3.5: "The worker must not already be `ON_DUTY` on any other
        roster entry (`ERR_PERSONNEL_ALREADY_ON_DUTY`)."

        Design: Corner/validations/corner_personnel_already_on_duty
        """
        team = create_ops_team()
        rescuer2 = make_personnel("Rescuer Two", ["RESCUER"],
                                  certifications=["CONFINED_SPACE_RESCUE"])
        set_clock(f"{DAY}T05:30:00Z")
        account = create_account(name="Duty Co")

        # Permit 1 on space 1 (planned day1 only).
        space1 = create_space(account["id"], space_code="TK-D1")
        plan1 = create_plan(space1["id"], team["lead_headers"])
        approve_plan(space1["id"], plan1["id"], team["lead_headers"])
        per1 = create_permit(space1["id"], team["supervisor_headers"],
                             purpose="Duty job 1")
        issue_permit(per1["id"], team["supervisor_headers"])
        post_reading(per1["id"], team["attendant_headers"],
                     reading_kind="PRE_ENTRY")
        sa1 = schedule_standby(per1["id"], team["lead_headers"],
                               team["rescuer"]["id"])
        standby_checkin(sa1["id"], team["lead_headers"])
        activate_permit(per1["id"], team["supervisor_headers"])

        # Permit 2 on space 2 (planned window spans into day 2).
        space2 = create_space(account["id"], space_code="TK-D2")
        plan2 = create_plan(space2["id"], team["lead_headers"])
        approve_plan(space2["id"], plan2["id"], team["lead_headers"])
        per2 = create_permit(space2["id"], team["supervisor_headers"],
                             purpose="Duty job 2",
                             planned_start_at=f"{DAY}T05:00:00Z",
                             planned_end_at=f"{DAY2}T20:00:00Z")
        issue_permit(per2["id"], team["supervisor_headers"])
        post_reading(per2["id"], team["attendant_headers"],
                     reading_kind="PRE_ENTRY")
        sa2 = schedule_standby(per2["id"], team["lead_headers"],
                               rescuer2["id"],
                               standby_start_at=f"{DAY}T05:00:00Z",
                               standby_end_at=f"{DAY2}T20:00:00Z")
        standby_checkin(sa2["id"], team["lead_headers"])
        activate_permit(per2["id"], team["supervisor_headers"])

        # att1: shift1 day1 06:00-17:00 on P1; shift2 day2 06:00-12:00 on P2
        # (13h rest gap is satisfied at scheduling time).
        shift1 = schedule_roster(per1["id"], team["supervisor_headers"],
                                 team["attendant"]["id"],
                                 assignment_role="ATTENDANT",
                                 scheduled_start_at=f"{DAY}T06:00:00Z",
                                 scheduled_end_at=f"{DAY}T17:00:00Z")
        shift2 = schedule_roster(per2["id"], team["supervisor_headers"],
                                 team["attendant"]["id"],
                                 assignment_role="ATTENDANT",
                                 scheduled_start_at=f"{DAY2}T06:00:00Z",
                                 scheduled_end_at=f"{DAY2}T12:00:00Z")

        set_clock(f"{DAY}T06:00:00Z")
        roster_checkin(shift1["id"], team["supervisor_headers"])
        # att1 never checks out: ON_DUTY persists across the midnight boundary.
        set_clock(f"{DAY2}T06:00:00Z")
        resp = api.roster_check_in(shift2["id"], team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_PERSONNEL_ALREADY_ON_DUTY)
        assert read_roster_entry(shift2["id"])["status"] == "SCHEDULED"
        assert read_roster_entry(shift1["id"])["status"] == "ON_DUTY"


class TestAttendantEntrantInterlock:
    def test_entrant_checkin_requires_attendant(self, api):
        """PRD §3.5: "An entrant may only check in while at least one
        attendant of the same permit is `ON_DUTY`
        (`ERR_NO_ATTENDANT_ON_DUTY`)".

        Design: Corner/state_machines/corner_entrant_checkin_requires_attendant
        """
        ctx = setup_active_permit(at="2026-08-03T05:30:00Z")
        team = ctx["team"]
        att_entry = schedule_roster(ctx["permit"]["id"],
                                    team["supervisor_headers"],
                                    team["attendant"]["id"],
                                    assignment_role="ATTENDANT")
        ent_entry = schedule_roster(ctx["permit"]["id"],
                                    team["supervisor_headers"],
                                    team["entrant"]["id"],
                                    assignment_role="ENTRANT")

        resp = api.roster_check_in(ent_entry["id"],
                                   team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_NO_ATTENDANT_ON_DUTY)

        roster_checkin(att_entry["id"], team["supervisor_headers"])
        checked = roster_checkin(ent_entry["id"], team["supervisor_headers"])
        assert checked["status"] == "ON_DUTY", (
            "with an attendant ON_DUTY the entrant check-in succeeds")

    def test_attendant_checkout_blocked_with_entrants(self, api):
        """PRD §3.5: "An `EntrySupervisor` checks an `ON_DUTY` worker out,
        moving the entry to `COMPLETED` with `checked_out_at` stamped — except
        that an attendant may not check out while any entrant of the same
        permit remains `ON_DUTY` (`ERR_ENTRANTS_STILL_INSIDE`)."

        Design: Corner/state_machines/corner_attendant_checkout_blocked_with_entrants
        """
        ctx = setup_active_permit(at="2026-08-03T05:30:00Z")
        team = ctx["team"]
        att_entry = add_on_duty_attendant(ctx)
        ent_entry = add_on_duty_entrant(ctx)

        resp = api.roster_check_out(att_entry["id"],
                                    team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_ENTRANTS_STILL_INSIDE)

        roster_checkout(ent_entry["id"], team["supervisor_headers"])
        checked_out = roster_checkout(att_entry["id"],
                                      team["supervisor_headers"])
        assert checked_out["status"] == "COMPLETED"

    def test_max_entrants_second_checkin_succeeds(self, api):
        """PRD §3.5: "An entrant may only check in while at least one
        attendant of the same permit is `ON_DUTY`
        (`ERR_NO_ATTENDANT_ON_DUTY`), and while the count of on-duty entrant
        entries on the permit remains below the space's `max_entrants` — a
        check-in arriving when the count already equals `max_entrants` is
        rejected with `ERR_MAX_ENTRANTS_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/max_entrants_inclusive_capacity_boundary
        """
        ctx = setup_active_permit(at="2026-08-03T05:30:00Z",
                                  space_overrides={"max_entrants": 2})
        add_on_duty_attendant(ctx)
        ent2 = make_personnel("Ent Two", [])

        first = add_on_duty_entrant(ctx)  # count 0 < 2 before adding
        assert first["status"] == "ON_DUTY"
        second = add_on_duty_entrant(ctx, entrant=ent2)  # count 1 < 2
        assert second["status"] == "ON_DUTY", (
            "the inclusive boundary admits the second entrant")

    def test_max_entrants_third_checkin_rejected(self, api):
        """PRD §3.5: "a check-in arriving when the count already equals
        `max_entrants` is rejected with `ERR_MAX_ENTRANTS_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/max_entrants_inclusive_capacity_boundary
        """
        ctx = setup_active_permit(at="2026-08-03T05:30:00Z",
                                  space_overrides={"max_entrants": 2})
        team = ctx["team"]
        add_on_duty_attendant(ctx)
        ent2 = make_personnel("Ent Two", [])
        ent3 = make_personnel("Ent Three", [])
        add_on_duty_entrant(ctx)
        add_on_duty_entrant(ctx, entrant=ent2)

        third_entry = schedule_roster(ctx["permit"]["id"],
                                      team["supervisor_headers"], ent3["id"],
                                      assignment_role="ENTRANT")
        resp = api.roster_check_in(third_entry["id"],
                                   team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_MAX_ENTRANTS_EXCEEDED)
        assert resp.status_code == 409, (
            "count 2 >= max_entrants 2: the boundary rejects the third")
        assert read_roster_entry(third_entry["id"])["status"] == "SCHEDULED"
        # The ON_DUTY attendant never counted toward max_entrants: had it
        # counted, the second entrant's check-in above would already have met
        # count 2 >= 2 and been rejected.
        entrants, meta = validate_paginated(api.list_roster_entries(
            OPS, params={"permit_id": ctx["permit"]["id"],
                         "assignment_role": "ENTRANT", "status": "ON_DUTY"}))
        assert meta["total_count"] == 2


class TestRotation:
    def test_rotation_relief_checkin(self, api):
        """PRD §3.5: "When `relief_of_entry_id` is set, the named target must
        currently be `ON_DUTY` (`ERR_RELIEF_TARGET_NOT_ON_DUTY`); on success
        the target transitions from `ON_DUTY` to `RELIEVED` with its
        `checked_out_at` set to the relieving entry's `checked_in_at`."
        PRD §3.5: "The roster list endpoint supports filtering by `permit_id`,
        `personnel_id`, `status`, `assignment_role`, and
        `relief_of_entry_id`."

        Design: Corner/state_machines/corner_rotation_relief_checkin
        """
        ctx = setup_active_permit(at="2026-08-03T05:30:00Z")
        team = ctx["team"]
        add_on_duty_attendant(ctx)
        entry_a = add_on_duty_entrant(
            ctx, scheduled_start_at=f"{DAY}T05:00:00Z",
            scheduled_end_at=f"{DAY}T12:00:00Z")
        ent_b = make_personnel("Ent B", [])
        entry_b = schedule_roster(ctx["permit"]["id"],
                                  team["supervisor_headers"], ent_b["id"],
                                  assignment_role="ENTRANT",
                                  scheduled_start_at=f"{DAY}T05:00:00Z",
                                  scheduled_end_at=f"{DAY}T12:00:00Z",
                                  relief_of_entry_id=entry_a["id"])

        checked_b = roster_checkin(entry_b["id"], team["supervisor_headers"])
        assert checked_b["status"] == "ON_DUTY"
        entry_a_after = read_roster_entry(entry_a["id"])
        assert entry_a_after["status"] == "RELIEVED"
        assert entry_a_after["checked_out_at"] == checked_b["checked_in_at"], (
            "rotation handoff: A's checked_out_at equals B's checked_in_at")

        reliefs, meta = validate_paginated(api.list_roster_entries(
            OPS, params={"relief_of_entry_id": entry_a["id"]}))
        assert [r["id"] for r in reliefs] == [entry_b["id"]], (
            "self-referential FK reverse lookup finds exactly the relief entry")

    def test_relief_target_not_on_duty_rejected(self, api):
        """PRD §3.5: "When `relief_of_entry_id` is set, the named target must
        currently be `ON_DUTY` (`ERR_RELIEF_TARGET_NOT_ON_DUTY`)".

        Design: Corner/state_machines/corner_relief_target_not_on_duty_rejected
        """
        ctx = setup_active_permit(at="2026-08-03T05:30:00Z")
        team = ctx["team"]
        add_on_duty_attendant(ctx)
        entry_a = add_on_duty_entrant(
            ctx, scheduled_start_at=f"{DAY}T05:00:00Z",
            scheduled_end_at=f"{DAY}T12:00:00Z")
        ent_b = make_personnel("Ent B", [])
        entry_b = schedule_roster(ctx["permit"]["id"],
                                  team["supervisor_headers"], ent_b["id"],
                                  assignment_role="ENTRANT",
                                  scheduled_start_at=f"{DAY}T05:00:00Z",
                                  scheduled_end_at=f"{DAY}T12:00:00Z",
                                  relief_of_entry_id=entry_a["id"])
        # The target checks out (COMPLETED) before the relief checks in.
        roster_checkout(entry_a["id"], team["supervisor_headers"])

        resp = api.roster_check_in(entry_b["id"], team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_RELIEF_TARGET_NOT_ON_DUTY)
        assert read_roster_entry(entry_b["id"])["status"] == "SCHEDULED"
