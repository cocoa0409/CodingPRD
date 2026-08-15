"""Logical-clock sweeps: permit cascades, maintenance windows, outage credits."""
from datetime import datetime

from test_helpers import (
    CO,
    FA,
    SP,
    ApiErrorId,
    api_client,
    campaign_version,
    confirm_flight,
    confirm_flight_payload,
    create_advertiser,
    create_campaign,
    create_face_with_permit,
    create_flight_payload,
    create_published_rate_card,
    create_work_order,
    face_version,
    get_success_data,
    hold_flight,
    set_clock,
    setup_booked_flight,
    setup_live_flight,
    submit_and_approve_campaign,
    transition_work_order,
    validate_error,
    validate_success,
)


def _parse_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestPermitExpiryCascade:

    def _setup_suspended_face(self):
        """LIVE flight 2026-08-10..2026-10-04 on a face whose permit expires
        2026-09-15T00:00:00Z; then sweep the clock to the expiry instant."""
        bundle = setup_live_flight(
            face_kwargs={"face_code": "F-NYC-001",
                         "permit_expires": "2026-09-15T00:00:00Z"},
            campaign_end="2026-10-31",
            flight_start="2026-08-10", flight_end="2026-10-04",
        )
        set_clock("2026-09-15T00:00:00Z")
        return bundle

    def test_permit_expiry_suspends_face(self):
        """PRD section 3.2: "Once the clock reaches `expires_on`, a permit in
        `ACTIVE` or `RENEWAL_PENDING` becomes `EXPIRED` — and the cascade
        begins: the face's `current_permit_id` is cleared to null, the face
        moves from `AVAILABLE` or `UNDER_MAINTENANCE` to `PERMIT_SUSPENDED`
        with `booking_posture` recomputed to `BLOCKED`, every flight on that
        face in `LIVE` or `HOLDOVER` has its `suspension_started_at` stamped
        with the current clock reading, and each affected flight's campaign
        has its `delivery_posture` recomputed."

        Design: Difficulty/transitive_cascade/permit_expiry_cascade_depth4
        """
        bundle = self._setup_suspended_face()
        permit = validate_success(
            api_client.get_permit(bundle["permit"]["id"], CO), 200)
        assert permit["status"] == "EXPIRED", (
            f"clock 2026-09-15T00:00:00Z >= expires_on: expected EXPIRED, "
            f"got {permit['status']}"
        )

        face = validate_success(api_client.get_face(bundle["face"]["id"], CO), 200)
        assert face["status"] == "PERMIT_SUSPENDED"
        assert face["booking_posture"] == "BLOCKED"
        assert face["current_permit_id"] is None

    def test_suspension_marks_live_flight_and_tips_campaign(self):
        """PRD section 3.2: "...every flight on that face in `LIVE` or
        `HOLDOVER` has its `suspension_started_at` stamped with the current
        clock reading, and each affected flight's campaign has its
        `delivery_posture` recomputed."
        PRD section 3.4: "Finally, `delivery_posture` compounds delivery
        health: it is `UNDER_DELIVERED` when any `COMPLETED` flight has a
        `delivery_ratio` below 0.9; otherwise `AT_RISK` when any flight sits
        in `MISSED` or `HOLDOVER`, has `suspension_started_at` set, or carries
        `suspension_days_accrued` above zero; otherwise `ON_TRACK`."

        Design: Difficulty/transitive_cascade/permit_expiry_cascade_depth4
        """
        bundle = self._setup_suspended_face()
        flight = validate_success(
            api_client.get_flight(bundle["flight"]["id"], SP), 200)
        assert flight["status"] == "LIVE", (
            f"end_date 2026-10-04 is past the 2026-09-15 clock: "
            f"expected still LIVE, got {flight['status']}"
        )
        assert flight["suspension_started_at"] is not None
        assert _parse_ts(flight["suspension_started_at"]) == \
            _parse_ts("2026-09-15T00:00:00Z"), (
            f"the stamp must be the current clock reading: "
            f"got {flight['suspension_started_at']}"
        )

        campaign = validate_success(
            api_client.get_campaign(bundle["campaign"]["id"], SP), 200)
        assert campaign["delivery_posture"] == "AT_RISK"


class TestPermitRenewalWindowBoundary:

    def test_permit_renewal_window_boundary(self):
        """PRD section 3.2: "When the clock stands anywhere from thirty days
        before `expires_on` up to but not including `expires_on`, the sweep
        moves an `ACTIVE` permit to `RENEWAL_PENDING`."

        Design: Corner/state_machines/permit_renewal_window_boundary
        """
        _face, permit = create_face_with_permit(
            face_code="F-NYC-001", permit_expires="2026-09-15T00:00:00Z")

        set_clock("2026-08-15T23:59:00Z")
        before = validate_success(api_client.get_permit(permit["id"], CO), 200)
        assert before["status"] == "ACTIVE", (
            f"one minute before the 30-day window opens the permit stays "
            f"ACTIVE, got {before['status']}"
        )

        set_clock("2026-08-16T00:00:00Z")
        after = validate_success(api_client.get_permit(permit["id"], CO), 200)
        assert after["status"] == "RENEWAL_PENDING", (
            f"exactly thirty days before expires_on 2026-09-15 the sweep "
            f"moves the permit to RENEWAL_PENDING, got {after['status']}"
        )


class TestPermitReinstateSettlement:

    def test_permit_reinstate_restores_face_and_settles_suspension_credit(self):
        """PRD section 3.2: "Restoration runs the cascade in reverse.
        Reinstating a permit (the `EXPIRED` → `ACTIVE` transition) requires a
        new `expires_on` strictly later than the current clock reading,
        otherwise `ERR_INVALID_REQUEST`. Whenever a permit on a suspended face
        becomes `ACTIVE` — by reinstatement or by a new filing, including a
        superseding renewal — the face's `current_permit_id` is set, and the
        face leaves `PERMIT_SUSPENDED`: it returns to `AVAILABLE` (posture
        `OPEN`), or to `UNDER_MAINTENANCE` (posture `RESTRICTED`) when a work
        order on the face is currently `IN_PROGRESS`. For each flight carrying
        a set `suspension_started_at`, the number of days between that stamp
        and the restoration moment is added to `suspension_days_accrued`, the
        stamp is cleared to null, and a make-good with reason
        `PERMIT_SUSPENSION` is auto-created in `PROPOSED` status with
        `proposed_by` set to the literal `system`, its credit computed per
        §3.9."
        PRD section 3.9: "For `PERMIT_SUSPENSION`, the credit is
        `pinned_weekly_cents` multiplied by the suspension days and divided by
        seven, rounded half-up; the suspension days run from
        `suspension_started_at` until the face's restoration — or until the
        flight's `end_date` when the flight completes while still suspended."

        Design: Corner/calculations/permit_reinstate_restores_face_and_settles_suspension_credit
        """
        bundle = setup_live_flight(
            face_kwargs={"face_code": "F-NYC-001",
                         "permit_expires": "2026-09-15T00:00:00Z"},
            campaign_end="2026-10-31",
            flight_start="2026-08-10", flight_end="2026-10-04",
        )
        set_clock("2026-09-15T00:00:00Z")  # permit expires; face suspends
        set_clock("2026-09-22T00:00:00Z")  # seven suspension days accrue

        permit = validate_success(api_client.update_permit(
            bundle["permit"]["id"],
            {"status": "ACTIVE", "expires_on": "2027-03-31T00:00:00Z"},
            CO,
        ), 200)
        assert permit["status"] == "ACTIVE"

        face = validate_success(api_client.get_face(bundle["face"]["id"], CO), 200)
        assert face["status"] == "AVAILABLE"
        assert face["booking_posture"] == "OPEN"
        assert face["current_permit_id"] == permit["id"]

        flight = validate_success(
            api_client.get_flight(bundle["flight"]["id"], SP), 200)
        assert flight["suspension_days_accrued"] == 7, (
            f"2026-09-15 through 2026-09-22 is 7 suspension days: "
            f"got {flight['suspension_days_accrued']}"
        )
        assert flight["suspension_started_at"] is None

        mgs = get_success_data(api_client.list_flight_make_goods(
            bundle["flight"]["id"], FA))
        assert len(mgs) == 1, f"exactly one auto make-good expected: {mgs}"
        mg = mgs[0]
        assert mg["reason"] == "PERMIT_SUSPENSION"
        assert mg["status"] == "PROPOSED"
        assert mg["proposed_by"] == "system"
        assert mg["credit_cents"] == 287_500, (
            f"round_half_up(287500 x 7/7): expected 287500, "
            f"got {mg['credit_cents']}"
        )


class TestSafetyBeatsConstraintOnBooking:

    def _setup_suspended_with_live_flight(self):
        bundle = setup_live_flight(
            face_kwargs={"face_code": "F-NYC-001",
                         "permit_expires": "2026-08-20T00:00:00Z"},
        )
        set_clock("2026-08-20T00:00:00Z")  # permit expires; face BLOCKED
        face = validate_success(api_client.get_face(bundle["face"]["id"], SP), 200)
        assert face["status"] == "PERMIT_SUSPENDED"
        assert face["booking_posture"] == "BLOCKED"
        campaign2 = create_campaign(bundle["advertiser"]["id"], name="C2",
                                    start_date="2026-08-01",
                                    end_date="2026-10-31")
        return bundle, face, campaign2

    def test_bookability_error_masks_overlap_error(self):
        """PRD section 2.9: "A failure in an earlier family is reported
        immediately and masks every later family — a client never sees a
        business-rule rejection for a request whose body was malformed, and
        never sees a body-shape error for a resource that does not exist."
        PRD section 2.9: "7. **Face bookability** — the face's
        `booking_posture` is `OPEN` and a current permit exists
        (`ERR_FACE_NOT_BOOKABLE`)." and "10. **Static-face overlap and
        changeover** — (`ERR_FACE_OVERLAP`)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_booking
        """
        bundle, face, campaign2 = self._setup_suspended_with_live_flight()
        # The window 2026-08-25..2026-09-21 both violates face bookability
        # (posture BLOCKED) and overlaps the LIVE flight 2026-08-10..2026-09-06
        # with no changeover day.
        resp = api_client.create_flight(
            create_flight_payload(campaign2["id"], face["id"],
                                  bundle["rate_card"]["id"],
                                  expected_face_version=face["version"],
                                  start_date="2026-08-25",
                                  end_date="2026-09-21"),
            SP,
        )
        validate_error(resp, ApiErrorId.ERR_FACE_NOT_BOOKABLE)

    def test_rejected_creation_persists_no_flight(self):
        """PRD section 2.9: "A failure in an earlier family is reported
        immediately and masks every later family — a client never sees a
        business-rule rejection for a request whose body was malformed, and
        never sees a body-shape error for a resource that does not exist."
        PRD section 3.5: "...the face must stand at `booking_posture` `OPEN`
        with a current permit in force (otherwise `ERR_FACE_NOT_BOOKABLE`)..."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_booking
        """
        bundle, face, campaign2 = self._setup_suspended_with_live_flight()
        before = get_success_data(api_client.list_face_flights(face["id"], SP))

        resp = api_client.create_flight(
            create_flight_payload(campaign2["id"], face["id"],
                                  bundle["rate_card"]["id"],
                                  expected_face_version=face["version"],
                                  start_date="2026-08-25",
                                  end_date="2026-09-21"),
            SP,
        )
        validate_error(resp, ApiErrorId.ERR_FACE_NOT_BOOKABLE)

        after = get_success_data(api_client.list_face_flights(face["id"], SP))
        assert len(after) == len(before) == 1, (
            f"a rejected hold must persist nothing: before={len(before)}, "
            f"after={len(after)}"
        )
        assert after[0]["id"] == bundle["flight"]["id"]


class TestMaintenanceWindowConflict:

    def _setup(self):
        bundle = setup_booked_flight()
        order = create_work_order(bundle["face"]["id"],
                                  order_type="VEGETATION_CLEARANCE",
                                  description="tree trim")
        return bundle, order

    def test_window_touching_booked_dates_rejected(self):
        """PRD section 3.3: "The planned window is half-open — it covers the
        calendar dates from the date of `scheduled_start` through the date one
        second before `scheduled_end` — and it must not touch any date
        occupied by a flight on the same face in `BOOKED`, `ART_CLEARED`,
        `LIVE`, `MISSED`, or `HOLDOVER`; a touch is rejected with
        `ERR_MAINTENANCE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/maintenance_window_half_open_datetime_conflict
        """
        _bundle, order = self._setup()
        mid = api_client.update_work_order(
            order["id"],
            {"status": "SCHEDULED",
             "scheduled_start": "2026-08-20T06:00:00Z",
             "scheduled_end": "2026-08-20T18:00:00Z"},
            CO,
        )
        validate_error(mid, ApiErrorId.ERR_MAINTENANCE_WINDOW_CONFLICT)

        edge = api_client.update_work_order(
            order["id"],
            {"status": "SCHEDULED",
             "scheduled_start": "2026-09-06T12:00:00Z",
             "scheduled_end": "2026-09-07T00:00:00Z"},
            CO,
        )
        validate_error(edge, ApiErrorId.ERR_MAINTENANCE_WINDOW_CONFLICT)

    def test_window_after_last_booked_day_accepted(self):
        """PRD section 3.3: "The planned window is half-open — it covers the
        calendar dates from the date of `scheduled_start` through the date one
        second before `scheduled_end` — and it must not touch any date
        occupied by a flight on the same face in `BOOKED`, `ART_CLEARED`,
        `LIVE`, `MISSED`, or `HOLDOVER`; a touch is rejected with
        `ERR_MAINTENANCE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/maintenance_window_half_open_datetime_conflict
        """
        _bundle, order = self._setup()
        scheduled = validate_success(api_client.update_work_order(
            order["id"],
            {"status": "SCHEDULED",
             "scheduled_start": "2026-09-07T00:00:00Z",
             "scheduled_end": "2026-09-08T00:00:00Z"},
            CO,
        ), 200)
        assert scheduled["status"] == "SCHEDULED", (
            f"[2026-09-07T00:00:00Z, 2026-09-08T00:00:00Z) occupies only "
            f"2026-09-07, one day past the flight's 2026-09-06 end: "
            f"got {scheduled['status']}"
        )


class TestWorkOrderReopenCycle:

    def test_work_order_reopen_cycle_and_downtime(self):
        """PRD section 3.3: "Starting work (the `SCHEDULED` → `IN_PROGRESS`
        transition) stamps `started_at` with the clock and moves the face from
        `AVAILABLE` to `UNDER_MAINTENANCE`, recomputing its posture to
        `RESTRICTED`. Completing work stamps `completed_at`, computes
        `downtime_hours` as the elapsed hours between `started_at` and
        `completed_at` rounded to 2 decimal places, and returns the face from
        `UNDER_MAINTENANCE` to `AVAILABLE` — but only when zero sibling work
        orders on that face remain `IN_PROGRESS`."
        PRD section 3.3: "Reopening (the `COMPLETED` → `REOPENED` transition)
        increments `reopen_count` by 1 — this cycle counter is the only
        exception to the terminal-state lockdown noted in §2.9. Driving a
        reopened order back to `IN_PROGRESS` re-stamps `started_at`, clears
        `completed_at` and `downtime_hours` to null, and puts the face back
        into `UNDER_MAINTENANCE`."

        Design: Corner/state_machines/work_order_reopen_cycle_and_downtime
        """
        face, _permit = create_face_with_permit(face_code="F-NYC-001")
        order = create_work_order(face["id"])
        transition_work_order(order["id"], "SCHEDULED",
                              scheduled_start="2026-08-05T06:00:00Z",
                              scheduled_end="2026-08-05T18:00:00Z")

        set_clock("2026-08-05T06:00:00Z")
        transition_work_order(order["id"], "IN_PROGRESS")
        face_mid = validate_success(api_client.get_face(face["id"], CO), 200)
        assert face_mid["status"] == "UNDER_MAINTENANCE"

        set_clock("2026-08-05T10:30:00Z")
        done = transition_work_order(order["id"], "COMPLETED")
        assert done["downtime_hours"] == 4.5, (
            f"06:00 -> 10:30 is 4.5 hours: got {done['downtime_hours']}"
        )

        reopened = transition_work_order(order["id"], "REOPENED")
        assert reopened["reopen_count"] == 1

        set_clock("2026-08-06T08:00:00Z")
        transition_work_order(order["id"], "IN_PROGRESS")
        set_clock("2026-08-06T09:15:00Z")
        done2 = transition_work_order(order["id"], "COMPLETED")
        assert done2["downtime_hours"] == 1.25, (
            f"second cycle recomputes from the new stamps 08:00 -> 09:15: "
            f"expected 1.25, got {done2['downtime_hours']}"
        )
        assert done2["reopen_count"] == 1

        face_final = validate_success(api_client.get_face(face["id"], CO), 200)
        assert face_final["status"] == "AVAILABLE", (
            f"zero sibling work orders remain IN_PROGRESS at completion: "
            f"got {face_final['status']}"
        )


class TestIlluminationOutageCredit:

    def test_illumination_outage_make_good_credit(self):
        """PRD section 3.3: "One exemption exists: an `ILLUMINATION_OUTAGE`
        order is a reactive outage report rather than a planned booking, so it
        schedules without the window check."
        PRD section 3.3: "Completion carries a revenue side effect for lit
        faces: when an `ILLUMINATION_OUTAGE` order completes on an
        `illuminated` face, every flight on that face in `LIVE`, `MISSED`, or
        `HOLDOVER` whose booked dates intersect the outage span (the calendar
        dates from `started_at` through `completed_at`) receives an
        auto-created make-good with reason `ILLUMINATION_OUTAGE`, status
        `PROPOSED`, and `proposed_by` set to `system`."
        PRD section 3.9: "For `ILLUMINATION_OUTAGE`, which applies only when
        the face is `illuminated`, the credit is `pinned_weekly_cents`
        multiplied by fifteen percent (0.15), multiplied by the number of
        outage days, and divided by seven, rounded half-up; the outage days
        are the flight's booked dates intersecting the span from the calendar
        date of the work order's `started_at` through the calendar date of its
        `completed_at`."

        Design: Corner/calculations/illumination_outage_make_good_credit
        """
        bundle = setup_live_flight()
        order = create_work_order(bundle["face"]["id"],
                                  order_type="ILLUMINATION_OUTAGE",
                                  description="ballast failure")

        scheduled = validate_success(api_client.update_work_order(
            order["id"],
            {"status": "SCHEDULED",
             "scheduled_start": "2026-08-20T08:00:00Z",
             "scheduled_end": "2026-08-22T17:00:00Z"},
            CO,
        ), 200)
        assert scheduled["status"] == "SCHEDULED", (
            f"ILLUMINATION_OUTAGE schedules without the window check despite "
            f"the LIVE flight: got {scheduled['status']}"
        )

        set_clock("2026-08-20T08:00:00Z")
        transition_work_order(order["id"], "IN_PROGRESS")
        set_clock("2026-08-22T17:00:00Z")
        transition_work_order(order["id"], "COMPLETED")

        mgs = get_success_data(api_client.list_flight_make_goods(
            bundle["flight"]["id"], FA))
        assert len(mgs) == 1, f"exactly one auto make-good expected: {mgs}"
        mg = mgs[0]
        assert mg["reason"] == "ILLUMINATION_OUTAGE"
        assert mg["status"] == "PROPOSED"
        assert mg["proposed_by"] == "system"
        assert mg["credit_cents"] == 18_482, (
            f"round_half_up(287500 x 0.15 x 3/7) for outage dates "
            f"2026-08-20..2026-08-22: expected 18482, got {mg['credit_cents']}"
        )
