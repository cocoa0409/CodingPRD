"""Unit-occupancy closed-interval overlap and landlord-calendar buffer conflicts."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    set_clock, new_landlord, new_leaseholder, new_applicant, new_verified_lease,
    new_open_listing, new_matched_application, draft_agreement, collect_signatures,
    make_leaseholder_headers, make_landlord_headers,
    setup_scenario,
)


class TestUnitOccupancyClosedIntervalAdjacency:
    """Difficulty: resource_temporal_overlap — occupancy overlap on the lease unit is
    judged on the closed interval, so touching endpoints conflict."""

    def _setup_executed_A_plus_matched_B(self, api, b_move_in, b_move_out):
        set_clock(api)
        landlord = new_landlord(api)
        leaseholder = new_leaseholder(api)
        ap1 = new_applicant(api, name="AP1", email="ap1@x.com")
        ap2 = new_applicant(api, name="AP2", email="ap2@x.com")
        lease = new_verified_lease(api, landlord, leaseholder, allows_sublet=True)

        listing_a = new_open_listing(api, lease, leaseholder, landlord, min_term_months=2)
        app_a = new_matched_application(api, listing_a, ap1,
                                        proposed_move_in_date="2026-06-01", proposed_move_out_date="2026-08-31")
        agr_a, _ = draft_agreement(api, listing_a, app_a, leaseholder,
                                   occupancy_start_date="2026-06-01", occupancy_end_date="2026-08-31")
        collect_signatures(api, agr_a, landlord, leaseholder, ap1)  # -> EXECUTED, occupancy 06-01..08-31

        listing_b = new_open_listing(api, lease, leaseholder, landlord, min_term_months=1)
        app_b = new_matched_application(api, listing_b, ap2,
                                        proposed_move_in_date=b_move_in, proposed_move_out_date=b_move_out)
        return lease, leaseholder, listing_b, app_b

    def test_adjacent_occupancy_start_equals_prior_end_rejected(self, api):
        """PRD §3.4: "Overlap is judged on the closed interval, so two occupancies that
        merely touch at an endpoint still conflict; a collision yields
        `ERR_OCCUPANCY_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/unit_occupancy_closed_interval_adjacency
        """
        lease, leaseholder, listing_b, app_b = self._setup_executed_A_plus_matched_B(
            api, "2026-08-31", "2026-10-31")
        version = validate_success(api.get_listing(listing_b["id"], TEST_USERS["admin_headers"]))["version"]
        resp = api.create_agreement(
            {"application_id": app_b["id"], "expected_listing_version": version,
             "occupancy_start_date": "2026-08-31", "occupancy_end_date": "2026-10-31"},
            make_leaseholder_headers(leaseholder["id"]))
        validate_error(resp, ApiErrorId.ERR_OCCUPANCY_OVERLAP.value)

    def test_non_adjacent_occupancy_accepted(self, api):
        """PRD §2.8: "A lease's `active_occupancy_count` always equals the number of
        agreements on that lease whose status is EXECUTED or ACTIVE."
        PRD §3.4: "the occupancy interval must not overlap any EXECUTED or ACTIVE
        agreement already on the same lease."

        Design: Difficulty/resource_temporal_overlap/unit_occupancy_closed_interval_adjacency
        """
        lease, leaseholder, listing_b, app_b = self._setup_executed_A_plus_matched_B(
            api, "2026-09-01", "2026-10-31")
        version = validate_success(api.get_listing(listing_b["id"], TEST_USERS["admin_headers"]))["version"]
        data = validate_success(api.create_agreement(
            {"application_id": app_b["id"], "expected_listing_version": version,
             "occupancy_start_date": "2026-09-01", "occupancy_end_date": "2026-10-31"},
            make_leaseholder_headers(leaseholder["id"])), 201)
        assert data["status"] == "DRAFT", "an occupancy one day after the prior end must not overlap"


class TestHandoffAppointmentBufferConflict:
    """Difficulty: resource_temporal_overlap — the landlord-calendar buffer rejects a new
    appointment within 120 minutes of an existing SCHEDULED one, even without interval overlap."""

    def _setup_with_first_appointment(self, api):
        ctx = setup_scenario(api, stage="executed")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        validate_success(api.create_appointment(
            {"agreement_id": ctx["agreement"]["id"],
             "scheduled_start": "2026-06-20T10:00:00Z", "scheduled_end": "2026-06-20T11:00:00Z"}, ll), 201)
        return ctx, ll

    def test_appointment_within_buffer_rejected(self, api):
        """PRD §3.7: "The appointment must also clear a two-hour buffer: its time must not
        fall within 120 minutes of any other `SCHEDULED` appointment on the same
        landlord's calendar. If the new appointment sits closer than that buffer to an
        existing scheduled one, it is rejected with `ERR_APPOINTMENT_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/handoff_appointment_buffer_conflict
        """
        ctx, ll = self._setup_with_first_appointment(api)
        # 12:30 start is only 90 minutes after the 11:00 end — inside the 120-minute buffer.
        resp = api.create_appointment(
            {"agreement_id": ctx["agreement"]["id"],
             "scheduled_start": "2026-06-20T12:30:00Z", "scheduled_end": "2026-06-20T13:30:00Z"}, ll)
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_CONFLICT.value)

    def test_appointment_clearing_buffer_accepted(self, api):
        """PRD §3.7: "The appointment must also clear a two-hour buffer: its time must not
        fall within 120 minutes of any other `SCHEDULED` appointment on the same
        landlord's calendar."

        Design: Difficulty/resource_temporal_overlap/handoff_appointment_buffer_conflict
        """
        ctx, ll = self._setup_with_first_appointment(api)
        # 14:00 start is 180 minutes after the 11:00 end — clear of the 120-minute buffer.
        data = validate_success(api.create_appointment(
            {"agreement_id": ctx["agreement"]["id"],
             "scheduled_start": "2026-06-20T14:00:00Z", "scheduled_end": "2026-06-20T15:00:00Z"}, ll), 201)
        assert data["status"] == "SCHEDULED", "an appointment clearing the buffer must be SCHEDULED"
