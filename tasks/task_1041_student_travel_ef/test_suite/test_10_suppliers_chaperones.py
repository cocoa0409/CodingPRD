"""Resource temporal-overlap conflicts: supplier half-open windows and chaperone rest
buffer (queue-A rule 8)."""
from test_helpers import (
    validate_success, validate_error, OPERATOR,
    ApiErrorId,
    set_clock, make_tour, make_group_leader, make_departure, open_departure,
    make_supplier, make_supplier_booking, make_chaperone,
    create_supplier_booking_payload, create_chaperone_payload,
)


class TestSupplierHalfOpenOverlap:
    """Design: Difficulty/resource_temporal_overlap/supplier_booking_halfopen_overlap_rejects_but_adjacency_allowed"""

    def _supplier_with_first_booking(self, api):
        set_clock(api, "2026-07-15T00:00:00Z")
        tour = make_tour(api)
        gl = make_group_leader(api)
        dep = make_departure(api, tour["id"], gl["id"])
        dep = open_departure(api, dep["id"])
        sup = make_supplier(api, name="Hotel Colosseo")
        # existing HELD booking [2026-11-01, 2026-11-04)
        make_supplier_booking(api, dep["id"], sup["id"], "2026-11-01T00:00:00Z", "2026-11-04T00:00:00Z",
                              room_block=10, cost_cents=500000)
        return dep, sup

    def test_overlapping_window_rejected(self, api):
        """PRD §3.9: "A booking is refused with ERR_SUPPLIER_DOUBLE_BOOKED when its window
        overlaps any non-cancelled booking already held on the same supplier_id; because the
        interval is half-open, two bookings that merely touch — one ending exactly when the
        next begins — are adjacent rather than overlapping and are allowed."

        Design: Difficulty/resource_temporal_overlap/supplier_booking_halfopen_overlap_rejects_but_adjacency_allowed
        """
        dep, sup = self._supplier_with_first_booking(api)
        # [2026-11-03, 2026-11-06) overlaps [2026-11-01, 2026-11-04)
        payload = create_supplier_booking_payload(dep["id"], sup["id"], "2026-11-03T00:00:00Z",
                                                  "2026-11-06T00:00:00Z", room_block=5, cost_cents=250000)
        resp = api.create_supplier_booking(payload, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_DOUBLE_BOOKED.value, expected_status=409)

    def test_adjacent_window_accepted(self, api):
        """PRD §3.9: "because the interval is half-open, two bookings that merely touch —
        one ending exactly when the next begins — are adjacent rather than overlapping and
        are allowed."

        Design: Difficulty/resource_temporal_overlap/supplier_booking_halfopen_overlap_rejects_but_adjacency_allowed
        """
        dep, sup = self._supplier_with_first_booking(api)
        # [2026-11-04, 2026-11-06) starts exactly when [.., 2026-11-04) ends -> adjacent
        payload = create_supplier_booking_payload(dep["id"], sup["id"], "2026-11-04T00:00:00Z",
                                                  "2026-11-06T00:00:00Z", room_block=5, cost_cents=250000)
        data = validate_success(api.create_supplier_booking(payload, OPERATOR), expected_status=201)
        assert data["status"] == "HELD"


class TestChaperoneRestBuffer:
    """Design: Difficulty/resource_temporal_overlap/chaperone_closed_interval_buffer_rejects_adjacent_departure"""

    CHAP_EMAIL = "chap@x.com"

    def _leader_with_departure_a_chaperone(self, api):
        set_clock(api, "2026-07-15T00:00:00Z")
        tour = make_tour(api)
        gl = make_group_leader(api)
        dep_a = make_departure(api, tour["id"], gl["id"],
                               depart_date="2026-11-01T00:00:00Z", return_date="2026-11-08T00:00:00Z")
        make_chaperone(api, dep_a["id"], full_name="Chap Person", email=self.CHAP_EMAIL, role_type="ADULT")
        return tour, gl

    def test_same_email_within_rest_buffer_rejected(self, api):
        """PRD §3.8: "A chaperone is refused with ERR_CHAPERONE_UNAVAILABLE when the same
        email is already a confirmed chaperone on another departure whose travel interval
        sits within a one-day rest buffer of this departure's interval; concretely, the
        conflict holds when the new departure's depart_date is on or before the other
        departure's return_date plus one day, and the other departure's depart_date is on or
        before the new departure's return_date plus one day."

        Design: Difficulty/resource_temporal_overlap/chaperone_closed_interval_buffer_rejects_adjacent_departure
        """
        tour, gl = self._leader_with_departure_a_chaperone(api)
        # Departure B [11-09, 11-16]: depart 11-09 <= returnA 11-08 + 1 day = 11-09 -> conflict
        dep_b = make_departure(api, tour["id"], gl["id"],
                               depart_date="2026-11-09T00:00:00Z", return_date="2026-11-16T00:00:00Z")
        payload = create_chaperone_payload(dep_b["id"], full_name="Chap Person", email=self.CHAP_EMAIL, role_type="ADULT")
        resp = api.create_chaperone(payload, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_CHAPERONE_UNAVAILABLE.value, expected_status=409)

    def test_same_email_outside_rest_buffer_accepted(self, api):
        """PRD §3.8: "the conflict holds when the new departure's depart_date is on or before
        the other departure's return_date plus one day, and the other departure's depart_date
        is on or before the new departure's return_date plus one day."

        Design: Difficulty/resource_temporal_overlap/chaperone_closed_interval_buffer_rejects_adjacent_departure
        """
        tour, gl = self._leader_with_departure_a_chaperone(api)
        # Departure C [11-10, 11-17]: depart 11-10 is AFTER returnA 11-08 + 1 day = 11-09 -> no conflict
        dep_c = make_departure(api, tour["id"], gl["id"],
                               depart_date="2026-11-10T00:00:00Z", return_date="2026-11-17T00:00:00Z")
        payload = create_chaperone_payload(dep_c["id"], full_name="Chap Person", email=self.CHAP_EMAIL, role_type="ADULT")
        data = validate_success(api.create_chaperone(payload, OPERATOR), expected_status=201)
        assert data["status"] == "CONFIRMED"
