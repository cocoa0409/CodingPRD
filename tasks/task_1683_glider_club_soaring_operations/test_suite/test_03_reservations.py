"""Glider reservations: lifecycle, temporal windows, overlap and buffer rules,
instructor coverage, grounding gates, and reservation-create OCC."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_aircraft,
    assert_member_balance,
    assert_reservation,
    book_reservation,
    book_reservation_raw,
    cancel_reservation_as_member,
    close_ops_day,
    create_aircraft,
    create_availability,
    create_member,
    create_tier,
    get_aircraft,
    get_member,
    get_reservation,
    land_flight,
    make_instructor_headers,
    make_member_headers,
    reconcile_flight,
    set_clock,
    setup_in_flight,
    validate_error,
    validate_success,
)


class TestReservationLifecycle:
    def test_checkout_from_cancelled_reservation_rejected(self, api):
        """PRD §3.4: "Checkout demands the reservation still be `BOOKED`
        (`ERR_RESERVATION_NOT_BOOKED`)".
        PRD §3.4: "`CLOSED`, `CANCELLED`, and `NO_SHOW` are all terminal."
        PRD §3.4: "A member-initiated cancel made less than 24 hours before
        `start_at` posts the 1,500-cent late-cancel fee to the member's
        `account_balance_cents`; cancels fired by cascades (suspension,
        resignation, grounding, retirement) never charge it."

        Design: Corner/state_machines/reservation_checkout_from_cancelled_rejected
        """
        tier = create_tier(tier_code="CN", monthly_dues_cents=0)
        member = create_member(tier["id"], full_name="Cancel Pilot")
        glider = create_aircraft("N002G", "GLIDER", "2027-01-01T00:00:00Z")
        set_clock("2026-08-26T08:00:00Z")
        reservation = book_reservation(
            glider["id"], member["id"], "2026-08-30T10:00:00Z", "2026-08-30T12:00:00Z"
        )
        # Cancel four days before start: outside the 24-hour late window.
        cancel_reservation_as_member(reservation["id"], member["id"])
        assert get_reservation(reservation["id"])["status"] == "CANCELLED"

        resp = api.checkout_reservation(reservation["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_RESERVATION_NOT_BOOKED)
        assert_member_balance(get_member(member["id"]), 0)

    def test_ops_close_marks_past_booked_reservation_no_show(self, api):
        """PRD §3.9: "The close then walks the launch pipeline: any reservation
        still `BOOKED` whose `end_at` has passed is marked `NO_SHOW` with the
        2,500-cent fee posted".
        PRD §3.9: "a `ClubAdmin`-only act that sweeps every deferred obligation
        against the logical clock (§2.5) and replies with a summary carrying
        `dues_posted_count`, `aircraft_grounded_ids`,
        `no_show_reservation_ids`, and `duty_finalized_ids`."

        Design: Corner/endpoints/ops_day_close_marks_reservation_no_show
        """
        tier = create_tier(tier_code="NS", monthly_dues_cents=0)
        member = create_member(tier["id"], full_name="NoShow Pilot")
        glider = create_aircraft("N016G", "GLIDER", "2027-01-01T00:00:00Z")
        set_clock("2026-08-25T09:00:00Z")
        reservation = book_reservation(
            glider["id"], member["id"], "2026-08-25T10:00:00Z", "2026-08-25T12:00:00Z"
        )
        set_clock("2026-08-26T00:10:00Z")
        summary = close_ops_day()
        assert reservation["id"] in summary["no_show_reservation_ids"]
        assert get_reservation(reservation["id"])["status"] == "NO_SHOW"
        assert_member_balance(get_member(member["id"]), 2500)


class TestCheckoutWindow:
    def test_checkout_before_window_opens_rejected(self, api):
        """PRD §2.9: "Launch-day checkout opens 15 minutes before the
        reservation's `start_at` and remains available through `end_at`."
        PRD §3.4: "the current instant within the window that opens 15 minutes
        before `start_at` and closes at `end_at` (`ERR_INVALID_TIME_WINDOW`,
        HTTP 422)".

        Design: Corner/validations/checkout_outside_window_rejected
        """
        tier = create_tier(tier_code="TW", monthly_dues_cents=0)
        member = create_member(tier["id"], full_name="Window Pilot")
        glider = create_aircraft("N011G", "GLIDER", "2027-01-01T00:00:00Z")
        set_clock("2026-08-29T09:30:00Z")
        reservation = book_reservation(
            glider["id"], member["id"], "2026-08-29T10:00:00Z", "2026-08-29T12:00:00Z"
        )
        # 09:30 is before the window opens at 09:45 (start_at - 15 minutes).
        resp = api.checkout_reservation(reservation["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW)
        assert get_reservation(reservation["id"])["status"] == "BOOKED"


class TestLateCancelFee:
    def test_late_cancel_fee_within_24h_window(self, api):
        """PRD §3.4: "A member-initiated cancel made less than 24 hours before
        `start_at` posts the 1,500-cent late-cancel fee to the member's
        `account_balance_cents`; cancels fired by cascades (suspension,
        resignation, grounding, retirement) never charge it."

        Design: Corner/validations/late_cancel_fee_applied_within_window
        """
        tier = create_tier(tier_code="LC", monthly_dues_cents=0)
        member = create_member(tier["id"], full_name="Late Pilot")
        glider = create_aircraft("N015G", "GLIDER", "2027-01-01T00:00:00Z")
        set_clock("2026-08-31T22:00:00Z")
        late = book_reservation(
            glider["id"], member["id"], "2026-09-01T10:00:00Z", "2026-09-01T12:00:00Z"
        )
        early = book_reservation(
            glider["id"], member["id"], "2026-09-02T04:00:00Z", "2026-09-02T06:00:00Z"
        )
        # 12 hours before start: inside the 24-hour window, fee applies.
        cancel_reservation_as_member(late["id"], member["id"])
        assert get_reservation(late["id"])["status"] == "CANCELLED"
        assert_member_balance(get_member(member["id"]), 1500)
        # 30 hours before start: outside the window, no further fee.
        cancel_reservation_as_member(early["id"], member["id"])
        assert get_reservation(early["id"])["status"] == "CANCELLED"
        assert_member_balance(get_member(member["id"]), 1500)


class TestCheckoutGroundingGate:
    def _setup_grounded_with_started_reservation(self, api):
        """Reservation whose start_at precedes the grounding instant, so the
        cascade's future-only filter leaves it BOOKED on a grounded glider."""
        tier = create_tier(tier_code="GATE", monthly_dues_cents=0)
        member = create_member(tier["id"], full_name="Gate Pilot")
        glider = create_aircraft("N920G", "GLIDER")
        set_clock("2026-08-21T09:00:00Z")
        reservation = book_reservation(
            glider["id"], member["id"], "2026-08-21T10:00:00Z", "2026-08-21T12:00:00Z"
        )
        set_clock("2026-08-21T10:30:00Z")
        api.ground_aircraft(glider["id"], ADMIN)
        return member, glider, reservation

    def test_checkout_on_grounded_glider_rejected(self, api):
        """PRD §3.4: "Checkout demands the reservation still be `BOOKED`
        (`ERR_RESERVATION_NOT_BOOKED`), the airframe `AIRWORTHY` with the §2.8
        inline currency check passing (`ERR_AIRCRAFT_NOT_AIRWORTHY`)".
        PRD §3.3: "Whatever the route, grounding an airframe cancels every
        `BOOKED` reservation on that airframe whose `start_at` lies in the
        future".

        Design: Difficulty/cross_entity_state_dependency/checkout_gated_by_aircraft_airworthy
        """
        member, glider, reservation = self._setup_grounded_with_started_reservation(api)
        resp = api.checkout_reservation(reservation["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_AIRCRAFT_NOT_AIRWORTHY)

    def test_ground_leaves_started_reservation_booked(self, api):
        """PRD §3.3: "Whatever the route, grounding an airframe cancels every
        `BOOKED` reservation on that airframe whose `start_at` lies in the
        future, and — for tow planes — cancels every `SCHEDULED` tow slot
        whose `start_at` lies in the future."

        Design: Difficulty/cross_entity_state_dependency/checkout_gated_by_aircraft_airworthy
        """
        member, glider, reservation = self._setup_grounded_with_started_reservation(api)
        resp = api.checkout_reservation(reservation["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_AIRCRAFT_NOT_AIRWORTHY)
        # start_at 10:00 precedes the grounding instant 10:30: cascade spared it.
        assert_reservation(get_reservation(reservation["id"]))
        assert get_reservation(reservation["id"])["status"] == "BOOKED"
        aircraft = get_aircraft(glider["id"])
        assert_aircraft(aircraft)
        assert aircraft["status"] == "GROUNDED"
        assert aircraft["grounded_reason"] == "MANUAL"


class TestValidationPrioritySafetyBeforeTemporal:
    def _setup_grounded_and_outside_window(self, api):
        tier = create_tier(tier_code="SAF", monthly_dues_cents=0)
        member = create_member(tier["id"], full_name="Safety Pilot")
        glider = create_aircraft("N800G", "GLIDER")
        api.ground_aircraft(glider["id"], ADMIN)
        set_clock("2026-08-18T08:00:00Z")
        reservation = book_reservation(
            glider["id"], member["id"], "2026-08-18T10:00:00Z", "2026-08-18T12:00:00Z"
        )
        return member, glider, reservation

    def test_grounded_checkout_outside_window_reports_airworthiness(self, api):
        """PRD §2.11: "airworthiness including the inline currency check
        (`ERR_AIRCRAFT_NOT_AIRWORTHY`). Temporal checks follow: window ordering
        and the checkout window (`ERR_INVALID_TIME_WINDOW`, HTTP 422)".
        (At 08:00 the checkout is outside the 09:45-12:00 window AND the
        glider is GROUNDED; the airworthiness gate is earlier in the fixed
        order and must surface.)

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_priority_on_checkout
        """
        member, _, reservation = self._setup_grounded_and_outside_window(api)
        resp = api.checkout_reservation(reservation["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_AIRCRAFT_NOT_AIRWORTHY)

    def test_rejected_checkout_leaves_reservation_booked(self, api):
        """PRD §3.4: "A successful checkout moves the reservation from `BOOKED`
        to `CHECKED_OUT`." — a rejected checkout performs no such mutation.

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_priority_on_checkout
        """
        member, glider, reservation = self._setup_grounded_and_outside_window(api)
        resp = api.checkout_reservation(reservation["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_AIRCRAFT_NOT_AIRWORTHY)
        assert get_reservation(reservation["id"])["status"] == "BOOKED"
        aircraft = get_aircraft(glider["id"])
        assert aircraft["status"] == "GROUNDED"
        assert aircraft["grounded_reason"] == "MANUAL"


class TestGliderOverlapHalfOpen:
    def _setup_overlap(self):
        tier = create_tier(tier_code="OVL", monthly_dues_cents=0)
        member_a = create_member(tier["id"], full_name="Overlap A")
        member_b = create_member(tier["id"], full_name="Overlap B")
        glider = create_aircraft("N930G", "GLIDER")
        set_clock("2026-08-22T08:00:00Z")
        book_reservation(
            glider["id"], member_a["id"], "2026-08-22T10:00:00Z", "2026-08-22T12:00:00Z"
        )
        return member_b, glider

    def test_overlapping_glider_reservation_rejected(self, api):
        """PRD §3.4: "The glider must be free: any other reservation in
        `BOOKED` or `CHECKED_OUT` on the same airframe whose half-open
        interval intersects the requested one yields `ERR_GLIDER_OVERLAP`
        (HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/glider_reservation_half_open_overlap
        """
        member_b, glider = self._setup_overlap()
        # [11:00,13:00) truly intersects the existing [10:00,12:00).
        resp = book_reservation_raw(
            glider["id"], member_b["id"],
            "2026-08-22T11:00:00Z", "2026-08-22T13:00:00Z",
            get_aircraft(glider["id"])["version"],
        )
        validate_error(resp, ApiErrorId.ERR_GLIDER_OVERLAP)

    def test_back_to_back_glider_reservation_allowed(self, api):
        """PRD §2.9: "Two reservations on the same glider overlap only when
        their half-open intervals intersect; back-to-back bookings where one
        reservation's `end_at` equals the other's `start_at` do **not**
        overlap and are both permitted."

        Design: Difficulty/resource_temporal_overlap/glider_reservation_half_open_overlap
        """
        member_b, glider = self._setup_overlap()
        resp = book_reservation_raw(
            glider["id"], member_b["id"],
            "2026-08-22T12:00:00Z", "2026-08-22T14:00:00Z",
            get_aircraft(glider["id"])["version"],
        )
        adjacent = validate_success(resp, 201)
        assert_reservation(adjacent)
        assert adjacent["status"] == "BOOKED", (
            "touching endpoints are not an intersection under half-open semantics"
        )


class TestInstructorBuffer:
    def _setup_buffer(self):
        tier = create_tier(tier_code="STU3", monthly_dues_cents=0, student_tier=True)
        instructor = create_member(tier["id"], full_name="Buf CFI", is_instructor=True)
        student_a = create_member(tier["id"], full_name="Buf Stu1")
        student_b = create_member(tier["id"], full_name="Buf Stu2")
        glider_a = create_aircraft("N940G", "GLIDER")
        glider_b = create_aircraft("N941G", "GLIDER")
        set_clock("2026-08-23T07:00:00Z")
        create_availability(instructor["id"], "2026-08-23T08:00:00Z", "2026-08-23T20:00:00Z")
        book_reservation(
            glider_a["id"], student_a["id"],
            "2026-08-23T10:00:00Z", "2026-08-23T12:00:00Z",
            instructor_id=instructor["id"],
        )
        return instructor, student_b, glider_b

    def test_instructor_gap_under_30_minutes_rejected(self, api):
        """PRD §3.4: "The instructor must not sit within 30 minutes on either
        side of another `BOOKED` or `CHECKED_OUT` reservation of theirs — a
        gap of exactly 30 minutes passes, anything less fails with
        `ERR_INSTRUCTOR_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/instructor_buffered_gap_overlap
        """
        instructor, student_b, glider_b = self._setup_buffer()
        # Existing booking ends 12:00; a 12:20 start leaves a 20-minute gap.
        resp = book_reservation_raw(
            glider_b["id"], student_b["id"],
            "2026-08-23T12:20:00Z", "2026-08-23T14:00:00Z",
            get_aircraft(glider_b["id"])["version"],
            instructor_id=instructor["id"],
        )
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_DOUBLE_BOOKED)

    def test_instructor_gap_exactly_30_minutes_allowed(self, api):
        """PRD §2.9: "Instructor scheduling adds a protective buffer: an
        instructor is double-booked when another active reservation sits
        within 30 minutes on either side of a proposed one — a gap of exactly
        30 minutes is allowed, anything less is a conflict."

        Design: Difficulty/resource_temporal_overlap/instructor_buffered_gap_overlap
        """
        instructor, student_b, glider_b = self._setup_buffer()
        # Existing booking ends 12:00; a 12:30 start leaves exactly 30 minutes.
        resp = book_reservation_raw(
            glider_b["id"], student_b["id"],
            "2026-08-23T12:30:00Z", "2026-08-23T14:00:00Z",
            get_aircraft(glider_b["id"])["version"],
            instructor_id=instructor["id"],
        )
        reservation = validate_success(resp, 201)
        assert_reservation(reservation)
        assert reservation["status"] == "BOOKED"


class TestInstructorCoverageAndIntegrity:
    def test_partial_availability_coverage_rejected(self, api):
        """PRD §3.4: "And an `OPEN` availability window of that instructor must
        fully cover the requested `start_at`-to-`end_at` span, else
        `ERR_INSTRUCTOR_UNAVAILABLE`."

        Design: Corner/validations/instructor_availability_coverage_required
        """
        tier = create_tier(tier_code="AV", monthly_dues_cents=0, student_tier=True)
        instructor = create_member(tier["id"], full_name="Avail CFI", is_instructor=True)
        student = create_member(tier["id"], full_name="Avail Stu")
        glider = create_aircraft("N012G", "GLIDER", "2027-01-01T00:00:00Z")
        set_clock("2026-08-30T08:00:00Z")
        create_availability(instructor["id"], "2026-08-30T09:00:00Z", "2026-08-30T12:00:00Z")
        # [11:00,12:30) extends 30 minutes past the availability end at 12:00.
        resp = book_reservation_raw(
            glider["id"], student["id"],
            "2026-08-30T11:00:00Z", "2026-08-30T12:30:00Z",
            get_aircraft(glider["id"])["version"],
            instructor_id=instructor["id"],
        )
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_UNAVAILABLE)

    def test_referential_integrity_kind_and_flags(self, api, club_admin_headers):
        """PRD §3.4: "Finally, integrity: the reserved airframe's `kind` must
        be `GLIDER`, and a named instructor must carry `is_instructor` true —
        violations draw `ERR_REFERENTIAL_INTEGRITY` (HTTP 422)."
        PRD §3.5: "The request names the `tow_plane_id` — which must reference
        an airframe of `kind` `TOW_PLANE` — the `tow_pilot_id`, which must
        reference a member with `is_tow_pilot` true (kind and flag violations
        draw `ERR_REFERENTIAL_INTEGRITY`)".
        PRD §3.7: "Opening requires the student's tier to be a student tier
        (`student_tier` true) and the instructor to be flagged — mismatches
        fail with `ERR_REFERENTIAL_INTEGRITY`".

        Design: Corner/validations/referential_integrity_kind_and_flags
        """
        tier = create_tier(tier_code="REF", monthly_dues_cents=0)
        pilot = create_member(tier["id"], full_name="Ref Pilot")
        tow_pilot = create_member(tier["id"], full_name="Ref Tow", is_tow_pilot=True)
        instructor = create_member(tier["id"], full_name="Ref CFI", is_instructor=True)
        glider = create_aircraft("N013G", "GLIDER", "2027-01-01T00:00:00Z")
        tow_plane = create_aircraft("N014T", "TOW_PLANE", "2027-01-01T00:00:00Z")

        # Reservation against a TOW_PLANE airframe.
        resp = book_reservation_raw(
            tow_plane["id"], pilot["id"],
            "2026-08-31T10:00:00Z", "2026-08-31T12:00:00Z",
            get_aircraft(tow_plane["id"])["version"],
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)

        # Tow slot against a GLIDER airframe.
        resp = api.create_tow_slot(
            {
                "tow_plane_id": glider["id"],
                "tow_pilot_id": tow_pilot["id"],
                "start_at": "2026-08-31T09:00:00Z",
                "end_at": "2026-08-31T17:00:00Z",
                "capacity": 2,
            },
            club_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)

        # Progression record for a member whose tier is not a student tier.
        resp = api.create_progress(
            {"student_id": pilot["id"], "instructor_id": instructor["id"], "kind": "BADGE_A"},
            make_instructor_headers(instructor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)


class TestReservationCreateOCC:
    def test_reservation_create_stale_aircraft_version(self, api):
        """PRD §2.10: "A `POST /soaring/reservations` request must carry
        `expected_aircraft_version`, holding the client's last observed
        `version` of the glider."
        PRD §2.10: "If the supplied value does not match the airframe's
        current `version`, the request is rejected with
        `ERR_STALE_AIRCRAFT_VERSION` (HTTP 412)."
        PRD §3.4: "A successful create increments the airframe's `version` by
        one."

        Design: Corner/cross_cutting_layers/reservation_create_stale_aircraft_version
        """
        tier = create_tier(tier_code="OC2", monthly_dues_cents=0)
        member_a = create_member(tier["id"], full_name="Stale A")
        member_b = create_member(tier["id"], full_name="Stale B")
        glider = create_aircraft("N025G", "GLIDER", "2027-01-01T00:00:00Z")
        set_clock("2026-08-26T08:00:00Z")
        observed_version = get_aircraft(glider["id"])["version"]

        first = book_reservation_raw(
            glider["id"], member_a["id"],
            "2026-08-26T10:00:00Z", "2026-08-26T11:00:00Z", observed_version,
        )
        validate_success(first, 201)
        assert get_aircraft(glider["id"])["version"] > observed_version

        # Non-overlapping window, but the OCC token is now stale.
        second = book_reservation_raw(
            glider["id"], member_b["id"],
            "2026-08-26T14:00:00Z", "2026-08-26T15:00:00Z", observed_version,
        )
        validate_error(second, ApiErrorId.ERR_STALE_AIRCRAFT_VERSION)


class TestSuspensionCascade:
    def test_suspend_cascades_future_booked_reservations(self, api):
        """PRD §3.2: "A `ClubAdmin` may also suspend a member directly, which
        records `MANUAL`. Either way, suspension cancels every one of the
        member's `BOOKED` reservations whose `start_at` lies in the future".
        PRD §3.4: "cancels fired by cascades (suspension, resignation,
        grounding, retirement) never charge it."

        Design: Corner/endpoints/member_suspend_cascades_future_reservations
        """
        tier = create_tier(tier_code="SU", monthly_dues_cents=0)
        member = create_member(tier["id"], full_name="Susp Pilot")
        glider = create_aircraft("N017G", "GLIDER", "2027-01-01T00:00:00Z")
        set_clock("2026-08-31T12:00:00Z")
        reservation = book_reservation(
            glider["id"], member["id"], "2026-09-03T10:00:00Z", "2026-09-03T12:00:00Z"
        )
        resp = api.suspend_member(member["id"], ADMIN)
        validate_success(resp, 200)
        suspended = get_member(member["id"])
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "MANUAL"
        assert get_reservation(reservation["id"])["status"] == "CANCELLED"
        assert_member_balance(suspended, 0)


class TestResignBlockedInFlight:
    def test_resign_blocked_while_flight_in_flight(self, api):
        """PRD §3.2: "A `Member` may resign themselves, or a `ClubAdmin` may
        process it, provided the member has no flight currently `IN_FLIGHT` —
        resigning mid-air is rejected with `ERR_MEMBER_IN_FLIGHT` (HTTP 409)."

        Design: Corner/errors/member_in_flight_blocks_resign
        """
        ctx = setup_in_flight(
            tier_overrides={"tier_code": "RS", "monthly_dues_cents": 0},
            slot_start="2026-08-30T09:00:00Z", slot_end="2026-08-30T18:00:00Z",
            capacity=2,
            res_start="2026-08-30T09:30:00Z", res_end="2026-08-30T14:00:00Z",
            clock="2026-08-30T09:40:00Z",
            takeoff_at="2026-08-30T10:05:00Z",
        )
        member = ctx["pilot"]
        resp = api.resign_member(member["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_MEMBER_IN_FLIGHT)
        assert get_member(member["id"])["status"] == "ACTIVE"

        land_flight(ctx["flight"]["id"], "2026-08-30T11:00:00Z", member["id"])
        reconcile_flight(ctx["flight"]["id"], ctx["tow_pilot"]["id"])
        resp = api.resign_member(member["id"], make_member_headers(member["id"]))
        resigned = validate_success(resp, 200)
        assert resigned["status"] == "RESIGNED", (
            "once no flight is IN_FLIGHT the resignation proceeds"
        )
