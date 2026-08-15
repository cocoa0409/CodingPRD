"""Standby staffing, the atmospheric log, and the emergency cascades
(PRD §3.5, §3.6)."""
from test_helpers import (
    OPS,
    ApiErrorId,
    add_on_duty_attendant,
    add_on_duty_entrant,
    create_atmospheric_reading_payload,
    create_standby_assignment_payload,
    post_reading,
    read_permit,
    read_personnel,
    read_roster_entry,
    read_standby,
    schedule_standby,
    set_clock,
    setup_active_permit,
    setup_issued_permit,
    standby_checkin,
    validate_error,
    validate_paginated,
    validate_success,
)

DAY = "2026-08-03"


class TestStandbyOverlap:
    def test_standby_touching_windows_legal(self, api):
        """PRD §3.5: "Standby windows follow half-open overlap semantics: a
        new assignment conflicts with any existing `SCHEDULED`, `ON_STANDBY`,
        or `DEPLOYED` assignment of the same rescuer when the new window starts
        before the existing window ends **and** the existing window starts
        before the new window ends — touching windows, where the new start
        equals the existing end, are legal, and unlike roster scheduling no
        rest buffer applies — with violations rejected as
        `ERR_STANDBY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/standby_half_open_touching_windows
        """
        ctx = setup_issued_permit(at=f"{DAY}T06:00:00Z")
        team = ctx["team"]
        first = schedule_standby(ctx["permit"]["id"], team["lead_headers"],
                                 team["rescuer"]["id"],
                                 standby_start_at=f"{DAY}T08:00:00Z",
                                 standby_end_at=f"{DAY}T12:00:00Z")
        assert first["status"] == "SCHEDULED"
        # new_start == existing_end: half-open semantics make this legal.
        second = schedule_standby(ctx["permit"]["id"], team["lead_headers"],
                                  team["rescuer"]["id"],
                                  standby_start_at=f"{DAY}T12:00:00Z",
                                  standby_end_at=f"{DAY}T16:00:00Z")
        assert second["status"] == "SCHEDULED"

    def test_standby_strict_overlap_rejected(self, api):
        """PRD §3.5: "Standby windows follow half-open overlap semantics: a
        new assignment conflicts with any existing `SCHEDULED`, `ON_STANDBY`,
        or `DEPLOYED` assignment of the same rescuer when the new window starts
        before the existing window ends **and** the existing window starts
        before the new window ends — touching windows, where the new start
        equals the existing end, are legal, and unlike roster scheduling no
        rest buffer applies — with violations rejected as
        `ERR_STANDBY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/standby_half_open_touching_windows
        """
        ctx = setup_issued_permit(at=f"{DAY}T06:00:00Z")
        team = ctx["team"]
        schedule_standby(ctx["permit"]["id"], team["lead_headers"],
                         team["rescuer"]["id"],
                         standby_start_at=f"{DAY}T08:00:00Z",
                         standby_end_at=f"{DAY}T12:00:00Z")
        schedule_standby(ctx["permit"]["id"], team["lead_headers"],
                         team["rescuer"]["id"],
                         standby_start_at=f"{DAY}T12:00:00Z",
                         standby_end_at=f"{DAY}T16:00:00Z")
        # 11:59 < 12:00 strictly overlaps the first window.
        resp = api.create_standby_assignment(
            ctx["permit"]["id"],
            create_standby_assignment_payload(
                team["rescuer"]["id"],
                standby_start_at=f"{DAY}T11:59:00Z",
                standby_end_at=f"{DAY}T13:00:00Z"),
            team["lead_headers"])
        validate_error(resp, ApiErrorId.ERR_STANDBY_OVERLAP)
        assert resp.status_code == 409
        _, meta = validate_paginated(api.list_standby_assignments(
            OPS, params={"rescuer_id": team["rescuer"]["id"]}))
        assert meta["total_count"] == 2, (
            "exactly the two legal assignments exist after the rejection")


class TestCommittedStandbyMinutes:
    def test_standby_create_raises_committed_minutes(self, api):
        """PRD §3.5: "A new assignment starts `SCHEDULED`, and its window
        minutes are added to the rescuer's `committed_standby_minutes`, which
        sums window lengths across the rescuer's assignments in `SCHEDULED`,
        `ON_STANDBY`, or `DEPLOYED` status; `RELEASED`, `CANCELLED`, and
        `NO_SHOW` assignments contribute zero."

        Design: Difficulty/compensating_invariant/standby_create_cancel_committed_minutes_invariant
        """
        ctx = setup_issued_permit(at=f"{DAY}T06:00:00Z")
        team = ctx["team"]
        rescuer_id = team["rescuer"]["id"]
        assert read_personnel(rescuer_id)["committed_standby_minutes"] == 0

        schedule_standby(ctx["permit"]["id"], team["lead_headers"], rescuer_id,
                         standby_start_at=f"{DAY}T08:00:00Z",
                         standby_end_at=f"{DAY}T16:00:00Z")
        after = read_personnel(rescuer_id)
        assert after["committed_standby_minutes"] == 480, (
            "window 08:00-16:00 = 480 minutes committed at creation")

    def test_standby_cancel_restores_committed_minutes(self, api):
        """PRD §3.5: "Cancelling a `SCHEDULED` assignment — explicitly or via
        cascade from a permit cancellation — moves it to `CANCELLED`, accrues
        no charge, and subtracts the window minutes from
        `committed_standby_minutes`."

        Design: Difficulty/compensating_invariant/standby_create_cancel_committed_minutes_invariant
        """
        ctx = setup_issued_permit(at=f"{DAY}T06:00:00Z")
        team = ctx["team"]
        rescuer_id = team["rescuer"]["id"]
        assignment = schedule_standby(ctx["permit"]["id"],
                                      team["lead_headers"], rescuer_id,
                                      standby_start_at=f"{DAY}T08:00:00Z",
                                      standby_end_at=f"{DAY}T16:00:00Z")
        assert read_personnel(rescuer_id)["committed_standby_minutes"] == 480

        cancelled = validate_success(
            api.standby_cancel(assignment["id"], team["lead_headers"]))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled.get("line_amount_cents") is None, (
            "no charge accrues for a SCHEDULED cancellation")
        assert read_personnel(rescuer_id)["committed_standby_minutes"] == 0, (
            "the create/cancel pair conserves committed_standby_minutes")


class TestStandbyLifecycle:
    def test_standby_no_show_sweep(self, api):
        """PRD §3.5: "Assignments still `SCHEDULED` more than 15 minutes past
        `standby_start_at` are swept to `NO_SHOW`, likewise releasing their
        committed minutes."

        Design: Corner/state_machines/corner_standby_no_show_sweep
        """
        ctx = setup_issued_permit(at=f"{DAY}T06:00:00Z")
        team = ctx["team"]
        rescuer_id = team["rescuer"]["id"]
        assignment = schedule_standby(ctx["permit"]["id"],
                                      team["lead_headers"], rescuer_id,
                                      standby_start_at=f"{DAY}T10:00:00Z",
                                      standby_end_at=f"{DAY}T12:00:00Z")
        assert read_personnel(rescuer_id)["committed_standby_minutes"] == 120

        set_clock(f"{DAY}T10:16:00Z")
        after = read_standby(assignment["id"])
        assert after["status"] == "NO_SHOW", (
            "10:16 is strictly more than 15 minutes past 10:00")
        assert read_personnel(rescuer_id)["committed_standby_minutes"] == 0, (
            "the no-show flip releases the 120 committed minutes")
        assert after.get("line_amount_cents") is None
        assert after.get("billed") is False, "no charge for a NO_SHOW"

    def test_release_scheduled_assignment_invalid(self, api):
        """PRD §3.5: "Releasing an `ON_STANDBY` or `DEPLOYED` assignment (a
        `RescueTeamLead` action, also fired by permit close and manual-cancel
        cascades) stamps `checked_out_at`, moves the assignment to `RELEASED`,
        computes its `billable_minutes` and `line_amount_cents`, and subtracts
        the assignment's window minutes from the rescuer's
        `committed_standby_minutes`" — release is defined only from
        `ON_STANDBY` or `DEPLOYED`, so releasing a `SCHEDULED` assignment fails
        with the assignment state error `ERR_ASSIGNMENT_INVALID_STATE`.

        Design: Corner/errors/corner_release_scheduled_assignment_invalid
        """
        ctx = setup_issued_permit(at=f"{DAY}T06:00:00Z")
        team = ctx["team"]
        assignment = schedule_standby(ctx["permit"]["id"],
                                      team["lead_headers"],
                                      team["rescuer"]["id"],
                                      standby_start_at=f"{DAY}T10:00:00Z",
                                      standby_end_at=f"{DAY}T20:00:00Z")
        resp = api.standby_release(assignment["id"], team["lead_headers"])
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE)
        after = read_standby(assignment["id"])
        assert after["status"] == "SCHEDULED"
        assert after.get("line_amount_cents") is None

    def test_rescuer_cert_insufficient(self, api):
        """PRD §3.5: "The rescuer must hold the `RESCUER` qualification and
        certifications covering the approved plan's `required_certifications`
        (`ERR_PERSONNEL_NOT_QUALIFIED`)."

        Design: Corner/validations/corner_rescuer_cert_insufficient
        """
        ctx = setup_issued_permit(
            at=f"{DAY}T06:00:00Z",
            plan_overrides={"required_certifications": ["CONFINED_SPACE_RESCUE",
                                                        "HAZMAT"]})
        team = ctx["team"]
        # The standard rescuer holds CONFINED_SPACE_RESCUE but not HAZMAT.
        resp = api.create_standby_assignment(
            ctx["permit"]["id"],
            create_standby_assignment_payload(
                team["rescuer"]["id"],
                standby_start_at=f"{DAY}T08:00:00Z",
                standby_end_at=f"{DAY}T12:00:00Z"),
            team["lead_headers"])
        validate_error(resp, ApiErrorId.ERR_PERSONNEL_NOT_QUALIFIED)
        assert resp.status_code == 422
        _, meta = validate_paginated(api.list_standby_assignments(
            OPS, params={"rescuer_id": team["rescuer"]["id"]}))
        assert meta["total_count"] == 0


class TestAtmosphericLog:
    def test_reading_out_of_range_rejected(self, api):
        """PRD §3.6: "`o2_pct` (oxygen percent, plausibly 0.0 to 30.0),
        `lel_pct` (percent of lower explosive limit, 0 to 100), `h2s_ppm`
        (hydrogen sulfide, 0 to 500), and `co_ppm` (carbon monoxide, 0 to
        2000). Values outside these plausibility ranges are rejected with
        `ERR_READING_OUT_OF_RANGE`."

        Design: Corner/validations/corner_reading_out_of_range_rejected
        """
        ctx = setup_issued_permit(at=f"{DAY}T06:00:00Z", with_plan=False)
        payload = create_atmospheric_reading_payload(
            reading_kind="PRE_ENTRY", o2_pct=31.0)
        resp = api.create_atmospheric_reading(
            ctx["permit"]["id"], payload, ctx["team"]["attendant_headers"])
        validate_error(resp, ApiErrorId.ERR_READING_OUT_OF_RANGE)
        assert resp.status_code == 422, (
            "o2 31.0 exceeds the plausibility ceiling: rejected, not alarmed")
        _, meta = validate_paginated(api.list_atmospheric_readings(
            OPS, params={"permit_id": ctx["permit"]["id"]}))
        assert meta["total_count"] == 0, "no reading persisted"

    def test_reading_kind_state_rejected(self, api):
        """PRD §3.6: "The reading kind is gated by permit state: `PRE_ENTRY`
        readings are allowed only while the permit is `ISSUED` or `SUSPENDED`,
        and `CONTINUOUS` readings only while `ACTIVE` — otherwise
        `ERR_READING_KIND_NOT_ALLOWED`."

        Design: Corner/validations/corner_reading_kind_state_rejected
        """
        ctx = setup_issued_permit(at=f"{DAY}T05:30:00Z")
        team = ctx["team"]
        permit_id = ctx["permit"]["id"]

        # Trigger 1: CONTINUOUS on an ISSUED permit.
        resp = api.create_atmospheric_reading(
            permit_id,
            create_atmospheric_reading_payload(reading_kind="CONTINUOUS"),
            team["attendant_headers"])
        validate_error(resp, ApiErrorId.ERR_READING_KIND_NOT_ALLOWED)

        # A legal PRE_ENTRY reading, then full activation.
        post_reading(permit_id, team["attendant_headers"],
                     reading_kind="PRE_ENTRY")
        standby = schedule_standby(permit_id, team["lead_headers"],
                                   team["rescuer"]["id"])
        standby_checkin(standby["id"], team["lead_headers"])
        activated = validate_success(
            api.activate_permit(permit_id, team["supervisor_headers"]))
        assert activated["status"] == "ACTIVE"

        # Trigger 2: PRE_ENTRY on an ACTIVE permit.
        resp2 = api.create_atmospheric_reading(
            permit_id,
            create_atmospheric_reading_payload(reading_kind="PRE_ENTRY"),
            team["attendant_headers"])
        validate_error(resp2, ApiErrorId.ERR_READING_KIND_NOT_ALLOWED)

        _, meta = validate_paginated(
            api.list_atmospheric_readings(OPS, params={"permit_id": permit_id}))
        assert meta["total_count"] == 1, (
            "only the accepted PRE_ENTRY reading was persisted")


class TestO2BoundaryAlarmFlip:
    def test_o2_at_lower_bound_within_limits(self, api):
        """PRD §3.6: "computes `within_limits`: true exactly when `o2_pct` is
        at least 19.5 and at most 23.5, `lel_pct` is at most 10, `h2s_ppm` is
        at most 10, and `co_ppm` is at most 35 — all bounds inclusive."

        Design: Difficulty/boundary_precision_check/o2_inclusive_lower_boundary_alarm_flip
        """
        ctx = setup_active_permit(at=f"{DAY}T05:30:00Z")
        reading = post_reading(ctx["permit"]["id"],
                               ctx["team"]["attendant_headers"],
                               reading_kind="CONTINUOUS", o2_pct=19.5)
        assert reading["within_limits"] is True, (
            "19.5 satisfies the inclusive lower bound")
        assert read_permit(ctx["permit"]["id"])["status"] == "ACTIVE", (
            "an in-limits reading fires no cascade")

    def test_o2_below_lower_bound_fires_alarm(self, api):
        """PRD §3.6: "computes `within_limits`: true exactly when `o2_pct` is
        at least 19.5 and at most 23.5, `lel_pct` is at most 10, `h2s_ppm` is
        at most 10, and `co_ppm` is at most 35 — all bounds inclusive." and
        "When a `CONTINUOUS` reading arrives out of limits on an `ACTIVE`
        permit, a three-link cascade fires automatically. Link one: the permit
        transitions `ACTIVE` to `SUSPENDED`, incrementing `suspension_count`
        and stamping `last_suspended_at`."

        Design: Difficulty/boundary_precision_check/o2_inclusive_lower_boundary_alarm_flip
        """
        ctx = setup_active_permit(at=f"{DAY}T05:30:00Z")
        in_bounds = post_reading(ctx["permit"]["id"],
                                 ctx["team"]["attendant_headers"],
                                 reading_kind="CONTINUOUS", o2_pct=19.5)
        assert in_bounds["within_limits"] is True
        assert read_permit(ctx["permit"]["id"])["status"] == "ACTIVE"

        # One 0.01 step below the inclusive bound flips the outcome.
        out = post_reading(ctx["permit"]["id"],
                           ctx["team"]["attendant_headers"],
                           reading_kind="CONTINUOUS", o2_pct=19.49)
        assert out["within_limits"] is False
        permit = read_permit(ctx["permit"]["id"])
        assert permit["status"] == "SUSPENDED", (
            "the out-of-limits CONTINUOUS reading fires the alarm cascade")
        assert permit["suspension_count"] == 1


class TestAlarmCascade:
    def _setup_alarm_scene(self):
        ctx = setup_active_permit(at=f"{DAY}T05:30:00Z")
        att_entry = add_on_duty_attendant(ctx)
        ent_entry = add_on_duty_entrant(ctx)
        return ctx, att_entry, ent_entry

    def test_alarm_cascade_permit_roster_standby(self, api):
        """PRD §3.6: "When a `CONTINUOUS` reading arrives out of limits on an
        `ACTIVE` permit, a three-link cascade fires automatically. Link one:
        the permit transitions `ACTIVE` to `SUSPENDED`, incrementing
        `suspension_count` and stamping `last_suspended_at`. Link two: every
        on-duty roster entry of the permit is evacuated — `ON_DUTY` to
        `EVACUATED` with `checked_out_at` stamped and exposure finalized. Link
        three: when any entry becomes `EVACUATED`, that permit's standby
        assignments in `ON_STANDBY` move to `DEPLOYED` with `deployed_at`
        stamped."

        Design: Difficulty/transitive_cascade/alarm_reading_three_hop_cascade
        """
        ctx, att_entry, ent_entry = self._setup_alarm_scene()
        reading = post_reading(ctx["permit"]["id"],
                               ctx["team"]["attendant_headers"],
                               reading_kind="CONTINUOUS", o2_pct=21.0,
                               lel_pct=5, h2s_ppm=20, co_ppm=10)
        assert reading["within_limits"] is False, "h2s 20 > 10"

        permit = read_permit(ctx["permit"]["id"])
        assert permit["status"] == "SUSPENDED", "hop 1: permit suspended"
        assert permit["suspension_count"] == 1

        ent_after = read_roster_entry(ent_entry["id"])
        att_after = read_roster_entry(att_entry["id"])
        assert ent_after["status"] == "EVACUATED", "hop 2: entrants evacuated"
        assert att_after["status"] == "EVACUATED", "hop 2: attendants too"
        assert ent_after["checked_out_at"] == reading["recorded_at"]

        standby_after = read_standby(ctx["standby"]["id"])
        assert standby_after["status"] == "DEPLOYED", (
            "hop 3: evacuation deploys the ON_STANDBY rescuer")
        assert standby_after["deployed_at"] is not None

    def test_alarm_cascade_autocreates_incident(self, api):
        """PRD §3.6: "The alarm path additionally auto-creates an `Incident`
        with `kind` `ATMOSPHERE`, `reported_by` taken from the reading's
        `recorded_by`, and `severity` `CRITICAL` when any of the following
        holds — oxygen below 16 percent, oxygen above 25 percent, LEL at or
        above 25, hydrogen sulfide at or above 20 ppm, or carbon monoxide at or
        above 100 ppm — and `SERIOUS` otherwise."

        Design: Difficulty/transitive_cascade/alarm_reading_three_hop_cascade
        """
        ctx, _, _ = self._setup_alarm_scene()
        reading = post_reading(ctx["permit"]["id"],
                               ctx["team"]["attendant_headers"],
                               reading_kind="CONTINUOUS", o2_pct=21.0,
                               lel_pct=5, h2s_ppm=20, co_ppm=10)
        assert reading["within_limits"] is False

        incidents, meta = validate_paginated(api.list_incidents(
            OPS, params={"permit_id": ctx["permit"]["id"]}))
        assert meta["total_count"] == 1, "exactly one incident is auto-created"
        incident = incidents[0]
        assert incident["kind"] == "ATMOSPHERE"
        assert incident["severity"] == "CRITICAL", (
            "h2s 20 is at or above the 20 ppm CRITICAL floor")
        assert incident["status"] == "REPORTED"
        assert incident["reported_by"] == ctx["team"]["attendant"]["id"], (
            "reported_by is taken from the reading's recorded_by")


class TestMonitoringGap:
    def test_monitoring_gap_auto_suspend(self, api):
        """PRD §3.6: "when the gap since the latest `CONTINUOUS` reading's
        `recorded_at` — or since `actual_entry_at` if no continuous reading
        exists — is **strictly greater** than 15 minutes, the permit is
        suspended with the same emergency cascade (roster evacuated, standby
        deployed). A gap of exactly 15 minutes does not suspend, and unlike the
        alarm path no incident is auto-created by the gap path."

        Design: Corner/state_machines/corner_monitoring_gap_auto_suspend
        """
        ctx = setup_active_permit(
            at=f"{DAY}T05:30:00Z",
            space_overrides={"requires_continuous_monitoring": True})
        att_entry = add_on_duty_attendant(ctx)
        post_reading(ctx["permit"]["id"], ctx["team"]["attendant_headers"],
                     reading_kind="CONTINUOUS", h2s_ppm=1)

        set_clock(f"{DAY}T05:45:00Z")
        mid = read_permit(ctx["permit"]["id"])
        assert mid["status"] == "ACTIVE", (
            "a gap of exactly 15 minutes does not suspend")

        set_clock(f"{DAY}T05:46:00Z")
        final = read_permit(ctx["permit"]["id"])
        assert final["status"] == "SUSPENDED", "gap 16:00 > 15:00 suspends"
        assert final["suspension_count"] == 1
        assert read_roster_entry(att_entry["id"])["status"] == "EVACUATED"
        assert read_standby(ctx["standby"]["id"])["status"] == "DEPLOYED"
        _, meta = validate_paginated(api.list_incidents(
            OPS, params={"permit_id": ctx["permit"]["id"]}))
        assert meta["total_count"] == 0, (
            "the gap path auto-creates no incident, unlike the alarm path")

    def test_immediate_read_after_write(self, api):
        """PRD §3.6: "When a `CONTINUOUS` reading arrives out of limits on an
        `ACTIVE` permit, a three-link cascade fires automatically." — the
        cascade's effects are visible in the same logical instant: the reading
        response carries `within_limits` computed, and the immediately
        following GETs observe the suspended permit, evacuated roster, and
        deployed standby with no clock movement in between.

        Design: Corner/consistency_model/corner_immediate_read_after_write
        """
        ctx = setup_active_permit(at=f"{DAY}T05:30:00Z")
        att_entry = add_on_duty_attendant(ctx)
        reading = post_reading(ctx["permit"]["id"],
                               ctx["team"]["attendant_headers"],
                               reading_kind="CONTINUOUS", o2_pct=24.0)
        assert reading["within_limits"] is False, (
            "o2 24.0 > 23.5, computed in the same response")

        permit = read_permit(ctx["permit"]["id"])
        assert permit["status"] == "SUSPENDED", (
            "immediate consistency: no delay, no reconciliation window")
        assert read_roster_entry(att_entry["id"])["status"] == "EVACUATED"
        assert read_standby(ctx["standby"]["id"])["status"] == "DEPLOYED"
