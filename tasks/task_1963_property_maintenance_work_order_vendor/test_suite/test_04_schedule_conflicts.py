"""Calendar conflicts: technician half-open overlap and vendor travel buffer."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_property,
    create_resident,
    create_technician,
    create_vendor,
    create_work_order,
    dispatch_in_house,
    dispatch_payload,
    dispatch_to_vendor,
    get_work_order,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _setup_technician_with_first_job(api):
    """Technician with an ASSIGNED job in window 2026-08-01T10:00-12:00, plus a spare TRIAGED order."""
    prop = create_property("Tech Overlap Property")
    resident = create_resident(prop["id"], unit_number="115", full_name="R Fifteen",
                               email="r15@x.com")
    tech = create_technician(prop["id"], full_name="T One", trade="PLUMBING")
    wo1 = create_work_order(prop["id"], resident["id"], description="Job 1")
    dispatch_in_house(wo1["id"], tech["id"],
                      scheduled_start_at="2026-08-01T10:00:00Z",
                      scheduled_end_at="2026-08-01T12:00:00Z")
    wo2 = create_work_order(prop["id"], resident["id"], description="Job 2")
    return prop, resident, tech, wo1, wo2


class TestTechnicianHalfOpenAdjacency:
    def test_adjacent_window_starting_at_previous_end_allowed(self, api):
        """PRD §3.3: "Adjacent windows — one ending exactly when the next begins — are allowed, because the overlap test is strict on both sides."

        Design: Difficulty/resource_temporal_overlap/technician_half_open_adjacency
        """
        _, _, tech, _, wo2 = _setup_technician_with_first_job(api)
        data = validate_success(
            api.dispatch_work_order(
                wo2["id"],
                dispatch_payload(
                    assignment_type="IN_HOUSE",
                    technician_id=tech["id"],
                    scheduled_start_at="2026-08-01T12:00:00Z",
                    scheduled_end_at="2026-08-01T14:00:00Z",
                    entry_authorization="RESIDENT_CONSENT",
                ),
                DISPATCHER,
            ),
            200,
        )
        assert data["status"] == "ASSIGNED", "12:00 start == 12:00 end is not an overlap"

    def test_genuine_overlap_rejected(self, api):
        """PRD §3.3: "The technician's calendar is then checked under a half-open overlap rule: dispatch is rejected with `ERR_TECHNICIAN_SCHEDULE_CONFLICT` (HTTP 409) if any other work order assigned to the same technician in `ASSIGNED` or `IN_PROGRESS` status has an existing window that starts before the new window ends and ends after the new window starts."

        Design: Difficulty/resource_temporal_overlap/technician_half_open_adjacency
        """
        _, _, tech, _, wo2 = _setup_technician_with_first_job(api)
        resp = api.dispatch_work_order(
            wo2["id"],
            dispatch_payload(
                assignment_type="IN_HOUSE",
                technician_id=tech["id"],
                scheduled_start_at="2026-08-01T11:00:00Z",
                scheduled_end_at="2026-08-01T13:00:00Z",
                entry_authorization="RESIDENT_CONSENT",
            ),
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_SCHEDULE_CONFLICT)
        assert get_work_order(wo2["id"])["status"] == "TRIAGED"


def _setup_vendor_with_first_job(api):
    """Vendor (buffer 60 by default) with an ASSIGNED job 2026-08-01T10:00-12:00, plus a spare TRIAGED order."""
    prop = create_property("Vendor Buffer Property", vendor_travel_buffer_minutes=60)
    resident = create_resident(prop["id"], unit_number="116", full_name="R Sixteen",
                               email="r16@x.com")
    vendor = create_vendor(prop["id"], company_name="V Co", trade="PLUMBING",
                           insurance_valid_until="2027-01-01T00:00:00Z")
    wo1 = create_work_order(prop["id"], resident["id"], description="Vendor job 1")
    dispatch_to_vendor(wo1["id"], vendor["id"],
                       scheduled_start_at="2026-08-01T10:00:00Z",
                       scheduled_end_at="2026-08-01T12:00:00Z")
    wo2 = create_work_order(prop["id"], resident["id"], description="Vendor job 2")
    return prop, resident, vendor, wo1, wo2


class TestVendorTravelBufferGap:
    def test_gap_exactly_equal_to_buffer_allowed(self, api):
        """PRD §3.3: "concretely, the new window must start no earlier than the existing window's end plus the buffer, or end no later than the existing window's start minus the buffer. A gap of exactly the buffer duration is allowed."

        Design: Difficulty/resource_temporal_overlap/vendor_travel_buffer_gap
        """
        _, _, vendor, _, wo2 = _setup_vendor_with_first_job(api)
        data = validate_success(
            api.dispatch_work_order(
                wo2["id"],
                dispatch_payload(
                    assignment_type="VENDOR",
                    vendor_id=vendor["id"],
                    scheduled_start_at="2026-08-01T13:00:00Z",
                    scheduled_end_at="2026-08-01T15:00:00Z",
                    entry_authorization="RESIDENT_CONSENT",
                ),
                DISPATCHER,
            ),
            200,
        )
        assert data["status"] == "ASSIGNED", "13:00 >= 12:00 + 60min buffer exactly"

    def test_gap_smaller_than_buffer_rejected(self, api):
        """PRD §3.3: "The vendor's calendar is then checked under a travel-buffer rule rather than raw overlap: dispatch is rejected with `ERR_VENDOR_SCHEDULE_CONFLICT` (HTTP 409) if any other work order assigned to the same vendor in `ASSIGNED` or `IN_PROGRESS` status sits closer to the new window than the property's `vendor_travel_buffer_minutes` — concretely, the new window must start no earlier than the existing window's end plus the buffer, or end no later than the existing window's start minus the buffer."

        Design: Difficulty/resource_temporal_overlap/vendor_travel_buffer_gap
        """
        _, _, vendor, _, wo2 = _setup_vendor_with_first_job(api)
        # 12:30 start is only 30 minutes after the 12:00 end: raw windows do not
        # overlap, but the 60-minute travel buffer rejects it.
        resp = api.dispatch_work_order(
            wo2["id"],
            dispatch_payload(
                assignment_type="VENDOR",
                vendor_id=vendor["id"],
                scheduled_start_at="2026-08-01T12:30:00Z",
                scheduled_end_at="2026-08-01T14:00:00Z",
                entry_authorization="RESIDENT_CONSENT",
            ),
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_VENDOR_SCHEDULE_CONFLICT)
        assert get_work_order(wo2["id"])["status"] == "TRIAGED"
