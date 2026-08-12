"""Therapist assignment business rules: license-before-double-booking
precedence, buffer-extended temporal overlap, and chair release."""
from test_helpers import (
    assign_therapist,
    create_event_booking,
    create_therapist,
    create_therapist_license,
    get_chair,
    open_booking,
    setup_region_account_therapist,
    setup_scheduling_booking,
    validate_error,
    validate_success,
)


class TestLicenseVsDoubleBookedPrecedence:
    def test_license_invalid_reported_when_both_license_and_overlap_fail(self, api):
        """PRD §3.4: "Three business checks then run in a fixed order — daily
        cap first, license second, double-booking third."
        PRD §3.4: "Second, license validity: the candidate must hold a license
        in the booking's delivery region that is `ACTIVE` and whose
        `expires_on` falls on or after the `event_date`, otherwise
        `ERR_LICENSE_INVALID`."
        PRD §3.4: "Third, the double-booking scan: the candidate must have no
        other chair in `ASSIGNED`, `EN_ROUTE`, or `ON_SITE` status on any
        booking sharing the same `event_date` whose time window overlaps this
        booking's window, where each window is extended by the
        `setup_buffer_minutes` before it and the `teardown_buffer_minutes`
        after it of the region in which that booking is delivered."

        Design: Difficulty/priority_pair_validation_conflict/license_invalid_vs_double_booked_on_assign
        """
        ctx = setup_region_account_therapist(
            therapist_overrides={"max_minutes_per_day": 2000},
        )
        t1 = ctx["therapist"]["id"]
        # B1: 600..720 (extended 570..750), T1 assigned.
        b1 = create_event_booking(ctx, site_address="B1", window_start_minutes=600)
        b1, b1_chairs = open_booking(ctx, b1["id"])
        assign_therapist(ctx, b1_chairs[0]["id"], t1)
        # B2: 700..820 (extended 670..850) — genuinely overlaps B1 extended.
        b2 = create_event_booking(ctx, site_address="B2", window_start_minutes=700)
        b2, b2_chairs = open_booking(ctx, b2["id"])
        # Suspend T1's license AFTER the B1 assignment: the B2 assignment now
        # fails BOTH the license check and the double-booking scan.
        validate_success(
            api.suspend_therapist_license(
                ctx["license"]["id"], {"reason": "audit"}, ctx["admin"],
            )
        )
        resp = api.assign_chair_slot(
            b2_chairs[0]["id"], {"therapist_id": t1}, ctx["organizer"],
        )
        validate_error(resp, "ERR_LICENSE_INVALID", expected_status=422)
        assert get_chair(ctx, b2_chairs[0]["id"])["status"] == "UNASSIGNED"

    def test_licensed_non_overlapping_candidate_assigns_successfully(self, api):
        """PRD §3.4: "Three business checks then run in a fixed order — daily
        cap first, license second, double-booking third."
        PRD §3.4: "On success the chair transitions `UNASSIGNED` → `ASSIGNED`,
        its `assigned_at` timestamp is set, and its `version` increments."

        Design: Difficulty/priority_pair_validation_conflict/license_invalid_vs_double_booked_on_assign
        """
        ctx = setup_region_account_therapist(
            therapist_overrides={"max_minutes_per_day": 2000},
        )
        t2 = create_therapist(ctx["region"]["id"], email="t2@test")
        create_therapist_license(t2["id"], ctx["region"]["id"], license_number="LIC-2")
        b1 = create_event_booking(ctx, site_address="B1", window_start_minutes=600)
        b1, b1_chairs = open_booking(ctx, b1["id"])
        assign_therapist(ctx, b1_chairs[0]["id"], ctx["therapist"]["id"])
        # Different therapist (valid license, no overlap): control case succeeds.
        b2 = create_event_booking(ctx, site_address="B2", window_start_minutes=700)
        b2, b2_chairs = open_booking(ctx, b2["id"])
        chair = assign_therapist(ctx, b2_chairs[0]["id"], t2["id"])
        assert chair["status"] == "ASSIGNED"
        assert chair["therapist_id"] == t2["id"]
        assert chair["assigned_at"], "assigned_at must be stamped on assignment"


class TestTherapistWindowOverlap:
    def test_adjacent_raw_windows_overlap_after_buffer_extension(self, api):
        """PRD §3.4: "Third, the double-booking scan: the candidate must have
        no other chair in `ASSIGNED`, `EN_ROUTE`, or `ON_SITE` status on any
        booking sharing the same `event_date` whose time window overlaps this
        booking's window, where each window is extended by the
        `setup_buffer_minutes` before it and the `teardown_buffer_minutes`
        after it of the region in which that booking is delivered. Windows
        are treated as half-open intervals, so back-to-back engagements where
        one extended window ends exactly when the other begins are permitted;
        a genuine overlap is rejected with `ERR_THERAPIST_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/therapist_window_overlap_with_buffers
        """
        ctx = setup_region_account_therapist(
            therapist_overrides={"max_minutes_per_day": 2000},
        )
        t1 = ctx["therapist"]["id"]
        # B1: 600..720 raw, extended 570..750 with 30-minute buffers.
        b1 = create_event_booking(
            ctx, site_address="B1", window_start_minutes=600,
            window_duration_minutes=120,
        )
        b1, b1_chairs = open_booking(ctx, b1["id"])
        assign_therapist(ctx, b1_chairs[0]["id"], t1)
        # B2: 720..840 raw — back-to-back with B1 raw, but extended 690..870
        # overlaps B1's extended 570..750.
        b2 = create_event_booking(
            ctx, site_address="B2", window_start_minutes=720,
            window_duration_minutes=120,
        )
        b2, b2_chairs = open_booking(ctx, b2["id"])
        resp = api.assign_chair_slot(
            b2_chairs[0]["id"], {"therapist_id": t1}, ctx["organizer"],
        )
        validate_error(resp, "ERR_THERAPIST_DOUBLE_BOOKED", expected_status=422)
        assert get_chair(ctx, b2_chairs[0]["id"])["status"] == "UNASSIGNED"

    def test_extended_windows_touching_endpoints_are_permitted(self, api):
        """PRD §3.4: "Windows are treated as half-open intervals, so
        back-to-back engagements where one extended window ends exactly when
        the other begins are permitted; a genuine overlap is rejected with
        `ERR_THERAPIST_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/therapist_window_overlap_with_buffers
        """
        ctx = setup_region_account_therapist(
            therapist_overrides={"max_minutes_per_day": 2000},
        )
        t1 = ctx["therapist"]["id"]
        # B1: 600..720 raw, extended 570..750.
        b1 = create_event_booking(
            ctx, site_address="B1", window_start_minutes=600,
            window_duration_minutes=120,
        )
        b1, b1_chairs = open_booking(ctx, b1["id"])
        assign_therapist(ctx, b1_chairs[0]["id"], t1)
        # B2: 780..900 raw, extended 750..930 — B1's extended window ends
        # exactly when B2's begins; half-open semantics permit this.
        b2 = create_event_booking(
            ctx, site_address="B2", window_start_minutes=780,
            window_duration_minutes=120,
        )
        b2, b2_chairs = open_booking(ctx, b2["id"])
        chair = assign_therapist(ctx, b2_chairs[0]["id"], t1)
        assert chair["status"] == "ASSIGNED", (
            "Extended windows that merely touch (end == start) must be permitted"
        )


class TestChairRelease:
    def test_chair_slot_release_action_endpoint(self, api):
        """PRD §3.4: "An `Organizer` may also release an `ASSIGNED` chair
        while the booking is `SCHEDULING` or `CONFIRMED`, moving it to
        `RELEASED`. The chair retains its `therapist_id` for audit and may be
        assigned anew; the therapist's booked-minutes tally for the
        `event_date` is decremented; and if the released therapist has no
        other `ASSIGNED` chair remaining on the booking, that therapist's
        `PLANNED` travel leg for the booking transitions to `WAIVED`."

        Design: Corner/endpoints/chair_slot_release_action_endpoint
        """
        ctx = setup_scheduling_booking(assign=True)
        chair = ctx["chairs"][0]
        resp = api.release_chair_slot(chair["id"], ctx["organizer"])
        released = validate_success(resp, expected_status=200)
        assert released["status"] == "RELEASED"
        assert released["therapist_id"] == ctx["therapist"]["id"], (
            "therapist_id is retained for audit after release"
        )
