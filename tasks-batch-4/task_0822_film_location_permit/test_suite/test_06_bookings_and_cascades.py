"""Road-closure booking conflicts and the multi-hop issue / reject / withdraw cascades."""
import test_helpers as th
from test_helpers import validate_success, validate_error, get_success_data, ApiErrorId


class TestIssueCascadeDepth3:
    def test_confirm_blocks_competitor_booking(self, api):
        """PRD §3.5: "First, bookings are confirmed (Cascade B): every RoadClosureBooking for
        the application whose status is PENDING transitions to CONFIRMED."
        PRD §3.5: "Each newly confirmed booking then blocks its competitors — the second hop of
        Cascade B: every other RoadClosureBooking on the same street_segment_id that is still
        PENDING and whose buffer-expanded window (again, 60 minutes on each side) overlaps the
        just-confirmed booking transitions to BLOCKED."

        Design: Difficulty/transitive_cascade/issue_cascade_depth3
        """
        ctx = th.setup_issue_cascade_scenario(api)
        th.issue_app(api, ctx["app1_id"], ctx["issue_version"])
        assert th.read_booking(api, ctx["b1_id"])["status"] == "CONFIRMED"
        assert th.read_booking(api, ctx["b2_id"])["status"] == "BLOCKED"

    def test_blocked_booking_cancels_losing_officer_assignment(self, api):
        """PRD §3.5: "Being blocked triggers the third hop: for each booking newly moved to
        BLOCKED, every OfficerAssignment belonging to that blocked booking's application whose
        status is PROPOSED transitions to CANCELLED, since the losing applicant no longer needs
        those officers."

        Design: Difficulty/transitive_cascade/issue_cascade_depth3
        """
        ctx = th.setup_issue_cascade_scenario(api)
        th.issue_app(api, ctx["app1_id"], ctx["issue_version"])
        assert th.read_assignment(api, ctx["oa2_id"])["status"] == "CANCELLED"


class TestRejectCascadeDepth2:
    def _under_review_two_bookings(self, api, company_name):
        th.set_clock(api, th.DEFAULT_CLOCK)
        pc = th.make_company(api, legal_name=company_name, contact_email=f"{company_name}@x.test", primary_contact="C")
        dept = th.make_department(api)
        seg1 = th.make_segment(api, segment_code="S1", name="S1", length_m=70)
        seg2 = th.make_segment(api, segment_code="S2", name="S2", length_m=70)
        app = th.make_application(api, pc["id"], title=company_name, synopsis="x",
                                  shoot_start_at="2026-06-01T06:00:00Z",
                                  shoot_end_at="2026-06-01T20:00:00Z",
                                  crew_size=5, requires_road_closure=True)
        th.add_location(api, app["id"], pc["id"],
                        requested_start_at="2026-06-01T06:00:00Z",
                        requested_end_at="2026-06-01T20:00:00Z", uses_road_closure=True)
        b1 = th.add_booking(api, app["id"], pc["id"], seg1["id"],
                            closure_start_at="2026-06-01T08:00:00Z", closure_end_at="2026-06-01T12:00:00Z")
        b2 = th.add_booking(api, app["id"], pc["id"], seg2["id"],
                            closure_start_at="2026-06-01T08:00:00Z", closure_end_at="2026-06-01T12:00:00Z")
        th.submit_app(api, app["id"], pc["id"])
        rev = th.get_review(api, app["id"], dept["id"])
        return {"pc_id": pc["id"], "app_id": app["id"], "dept_id": dept["id"],
                "rev_id": rev["id"], "b1_id": b1["id"], "b2_id": b2["id"]}

    def test_reject_drives_revision_required(self, api):
        """PRD §3.3: "A REJECT moves the review from PENDING to REJECTED and kicks off
        Cascade A: the parent application transitions from UNDER_REVIEW to REVISION_REQUIRED."

        Design: Difficulty/transitive_cascade/reject_cascade_depth2
        """
        ctx = self._under_review_two_bookings(api, "RejACo")
        th.decide_review(api, ctx["rev_id"], ctx["dept_id"], "REJECT")
        app = get_success_data(api.get_application(ctx["app_id"], th.make_coordinator_headers()))
        assert app["status"] == "REVISION_REQUIRED"

    def test_reject_releases_all_pending_bookings(self, api):
        """PRD §3.3: "As the second link of Cascade A, every RoadClosureBooking for that
        application whose status is PENDING or CONFIRMED is transitioned to RELEASED, and the
        application's version increments."

        Design: Difficulty/transitive_cascade/reject_cascade_depth2
        """
        ctx = self._under_review_two_bookings(api, "RejBCo")
        th.decide_review(api, ctx["rev_id"], ctx["dept_id"], "REJECT")
        assert th.read_booking(api, ctx["b1_id"])["status"] == "RELEASED"
        assert th.read_booking(api, ctx["b2_id"])["status"] == "RELEASED"


class TestRoadClosureBufferOverlap:
    def test_booking_within_buffer_of_confirmed_rejected(self, api):
        """PRD §3.5: "The candidate window is expanded by a setup buffer of 60 minutes on each
        side, and if that buffer-expanded window overlaps any booking on the same segment that
        is already CONFIRMED, the new booking is rejected with ERR_SEGMENT_DOUBLE_BOOKED
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/road_closure_buffer_overlap
        """
        ctx = th.setup_confirmed_booking_on_segment(api)
        resp = api.create_road_closure_booking(
            {"application_id": ctx["app2_id"], "street_segment_id": ctx["seg_id"],
             "closure_start_at": "2026-06-01T12:30:00Z", "closure_end_at": "2026-06-01T14:00:00Z"},
            th.make_production_company_headers(ctx["pc2_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGMENT_DOUBLE_BOOKED.value)

    def test_booking_outside_buffer_accepted(self, api):
        """PRD §3.5: "The candidate window is expanded by a setup buffer of 60 minutes on each
        side, and if that buffer-expanded window overlaps any booking on the same segment that
        is already CONFIRMED, the new booking is rejected with ERR_SEGMENT_DOUBLE_BOOKED
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/road_closure_buffer_overlap
        """
        ctx = th.setup_confirmed_booking_on_segment(api)
        # Confirmed B1 is [08:00,12:00); a candidate at [13:30,15:00) is well clear of the
        # 60-minute buffer on either window, so it must be accepted.
        resp = api.create_road_closure_booking(
            {"application_id": ctx["app2_id"], "street_segment_id": ctx["seg_id"],
             "closure_start_at": "2026-06-01T13:30:00Z", "closure_end_at": "2026-06-01T15:00:00Z"},
            th.make_production_company_headers(ctx["pc2_id"]),
        )
        data = validate_success(resp, 201)
        assert data["status"] == "PENDING"


class TestOfficerAssignmentHalfOpenAdjacent:
    def _under_review_with_shift(self, api, company_name):
        ctx = th.setup_under_review_single_review(api, company_name=company_name,
                                                  app_overrides={"shoot_start_at": "2026-06-01T06:00:00Z",
                                                                 "shoot_end_at": "2026-06-01T20:00:00Z"})
        officer = th.make_officer(api, full_name="Ofc Adj", badge_number="B-2")
        th.add_assignment(api, ctx["app_id"], officer["id"],
                          shift_start_at="2026-06-01T08:00:00Z", shift_end_at="2026-06-01T12:00:00Z")
        ctx["officer_id"] = officer["id"]
        return ctx

    def test_shift_touching_at_end_boundary_accepted(self, api):
        """PRD §3.6: "These windows are half-open intervals [start, end), so two shifts that
        merely touch — one ending exactly when the next begins — do not conflict, and no setup
        buffer is applied."

        Design: Difficulty/resource_temporal_overlap/officer_assignment_halfopen_adjacent_ok
        """
        ctx = self._under_review_with_shift(api, "P8bCo")
        resp = api.create_officer_assignment(
            {"application_id": ctx["app_id"], "officer_id": ctx["officer_id"],
             "shift_start_at": "2026-06-01T12:00:00Z", "shift_end_at": "2026-06-01T14:00:00Z"},
            th.make_coordinator_headers(),
        )
        data = validate_success(resp, 201)
        assert data["status"] == "PROPOSED"

    def test_shift_touching_at_start_boundary_accepted(self, api):
        """PRD §3.6: "These windows are half-open intervals [start, end), so two shifts that
        merely touch — one ending exactly when the next begins — do not conflict, and no setup
        buffer is applied."

        Design: Difficulty/resource_temporal_overlap/officer_assignment_halfopen_adjacent_ok
        """
        ctx = self._under_review_with_shift(api, "P8b2Co")
        resp = api.create_officer_assignment(
            {"application_id": ctx["app_id"], "officer_id": ctx["officer_id"],
             "shift_start_at": "2026-06-01T06:00:00Z", "shift_end_at": "2026-06-01T08:00:00Z"},
            th.make_coordinator_headers(),
        )
        data = validate_success(resp, 201)
        assert data["status"] == "PROPOSED"


class TestSegmentBookingConservation:
    def test_withdraw_restores_blocked_competitor_to_pending(self, api):
        """PRD §3.9: "When a booking that had been holding a segment is RELEASED, any
        RoadClosureBooking on the same street_segment_id that is BLOCKED and that no longer
        overlaps any remaining CONFIRMED booking on that segment (using the same 60-minute
        buffer-expanded comparison) is restored from BLOCKED to PENDING."

        Design: Difficulty/compensating_invariant/segment_active_booking_count_conservation
        """
        ctx = th.setup_block_restore_scenario(api)
        assert th.read_booking(api, ctx["b2_id"])["status"] == "BLOCKED"
        get_success_data(api.withdraw_application(ctx["app1_id"], {}, th.make_production_company_headers(ctx["pc1_id"])))
        assert th.read_booking(api, ctx["b2_id"])["status"] == "PENDING"

    def test_withdraw_releases_confirmed_booking(self, api):
        """PRD §3.9: "From ISSUED — a surrender of a live permit — withdrawal releases every
        CONFIRMED RoadClosureBooking for the application, cancels every CONFIRMED
        OfficerAssignment, and refunds any remaining deposit ..."

        Design: Difficulty/compensating_invariant/segment_active_booking_count_conservation
        """
        ctx = th.setup_block_restore_scenario(api)
        get_success_data(api.withdraw_application(ctx["app1_id"], {}, th.make_production_company_headers(ctx["pc1_id"])))
        assert th.read_booking(api, ctx["b1_id"])["status"] == "RELEASED"


def test_officer_double_booked_overlap(api):
    """PRD §3.6: "The shift window is then checked against the officer's existing schedule: it
    must not overlap any other assignment for the same officer_id that is still in a
    non-terminal status (PROPOSED or CONFIRMED); a conflict is rejected with
    ERR_OFFICER_DOUBLE_BOOKED (HTTP 409)."

    Design: Corner/validations/officer_double_booked_overlap
    """
    ctx = th.setup_under_review_single_review(api, company_name="Dbl Co",
                                              app_overrides={"shoot_start_at": "2026-06-01T06:00:00Z",
                                                             "shoot_end_at": "2026-06-01T20:00:00Z"})
    officer = th.make_officer(api, full_name="Ofc Dbl", badge_number="B-D")
    th.add_assignment(api, ctx["app_id"], officer["id"],
                      shift_start_at="2026-06-01T08:00:00Z", shift_end_at="2026-06-01T12:00:00Z")
    resp = api.create_officer_assignment(
        {"application_id": ctx["app_id"], "officer_id": officer["id"],
         "shift_start_at": "2026-06-01T10:00:00Z", "shift_end_at": "2026-06-01T13:00:00Z"},
        th.make_coordinator_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_OFFICER_DOUBLE_BOOKED.value)
