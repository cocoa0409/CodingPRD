"""Difficulty: resource_temporal_overlap — aggregate slot counts vs per-assignment geometry."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    book_reservation,
    create_slot,
    get_slot,
    make_vendor_spec,
    setup_confirmed_assignment,
    setup_curated_multi,
    validate_error,
    validate_paginated,
)

OPS = TEST_USERS["ops_headers"]


def _setup_two_confirmed():
    specs = [
        make_vendor_spec("Agg A", "FOOD_HOT"),
        make_vendor_spec("Agg B", "FOOD_COLD"),
    ]
    return setup_curated_multi(specs, name="Aggregate Fest", zone_power=200, zone_water=2)


class TestSlotAggregateSemantics:
    def test_overlapping_windows_from_different_assignments_both_admitted(self, api):
        """PRD §3.5: "A slot's `reserved_vehicle_count` is the sum of
        `vehicle_count` over its reservations in `BOOKED` or `CHECKED_IN`."
        PRD §3.5: "Two windows never overlap for the same assignment".

        Design: Difficulty/resource_temporal_overlap/slot_aggregate_capacity_semantics
        """
        scen = _setup_two_confirmed()
        slot = create_slot(scen["festival"]["id"], max_vehicles=5)
        # Different assignments, fully overlapping windows — the slot only sums vehicles.
        ra = book_reservation(scen["assignments"][0]["id"], slot["id"], vehicle_count=2)
        rb = book_reservation(scen["assignments"][1]["id"], slot["id"], vehicle_count=3)
        assert ra["status"] == "BOOKED" and rb["status"] == "BOOKED"
        assert get_slot(slot["id"])["reserved_vehicle_count"] == 5, "2 + 3 == 5 == max"

    def test_slot_lists_both_reservations_booked(self, api):
        """PRD §3.5: "A successful booking enters `BOOKED` and raises the slot's
        reserved count. The reservation list filters by `assignment_id`,
        `slot_id`, `festival_id`, and `status`."

        Design: Difficulty/resource_temporal_overlap/slot_aggregate_capacity_semantics
        """
        scen = _setup_two_confirmed()
        slot = create_slot(scen["festival"]["id"], max_vehicles=5)
        book_reservation(scen["assignments"][0]["id"], slot["id"], vehicle_count=2)
        book_reservation(scen["assignments"][1]["id"], slot["id"], vehicle_count=3)
        data, meta = validate_paginated(api.list_reservations(OPS, params={"slot_id": slot["id"]}))
        assert meta["total_count"] == 2
        assert all(r["status"] == "BOOKED" for r in data), (
            "no geometric check at the slot level — count is the only currency"
        )


class TestAssignmentHalfOpenOverlap:
    def _setup_three_slots(self):
        scen = setup_confirmed_assignment(name="HalfOpen Fest")
        s1 = create_slot(scen["festival"]["id"], gate="GATE_A",
                         window_start="2026-07-10T08:00:00Z", window_end="2026-07-10T11:00:00Z")
        s2 = create_slot(scen["festival"]["id"], gate="GATE_B",
                         window_start="2026-07-10T11:00:00Z", window_end="2026-07-10T13:00:00Z")
        s3 = create_slot(scen["festival"]["id"], gate="GATE_C",
                         window_start="2026-07-10T10:30:00Z", window_end="2026-07-10T12:00:00Z")
        return scen, s1, s2, s3

    def test_adjacent_windows_are_not_an_overlap(self, api):
        """PRD §3.5: "under half-open semantics where adjacency (one window's
        close equal to the other's open) is not an overlap".

        Design: Difficulty/resource_temporal_overlap/assignment_halfopen_overlap_adjacency
        """
        scen, s1, s2, _ = self._setup_three_slots()
        asg_id = scen["assignment"]["id"]
        book_reservation(asg_id, s1["id"], vehicle_count=1)
        r2 = book_reservation(asg_id, s2["id"], vehicle_count=1)
        assert r2["status"] == "BOOKED", "S1.end == S2.start is NOT an overlap (half-open)"

    def test_strictly_overlapping_window_is_rejected(self, api):
        """PRD §3.5: "overlap exists exactly when the existing window starts
        before the new window ends and the new window starts before the existing
        window ends, under half-open semantics where adjacency (one window's
        close equal to the other's open) is not an overlap; a violation is
        rejected with `ERR_VEHICLE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/assignment_halfopen_overlap_adjacency
        """
        scen, s1, s2, s3 = self._setup_three_slots()
        asg_id = scen["assignment"]["id"]
        book_reservation(asg_id, s1["id"], vehicle_count=1)
        book_reservation(asg_id, s2["id"], vehicle_count=1)
        # S3 10:30-12:00: S1.start 08:00 < S3.end 12:00 AND S3.start 10:30 < S1.end 11:00.
        resp = api.create_reservation(
            {"assignment_id": asg_id, "slot_id": s3["id"], "vehicle_count": 1}, OPS
        )
        validate_error(resp, ApiErrorId.ERR_VEHICLE_WINDOW_OVERLAP)
        data, meta = validate_paginated(api.list_reservations(OPS, params={"assignment_id": asg_id}))
        assert meta["total_count"] == 2, "exactly the two admitted reservations remain"
        assert all(r["status"] == "BOOKED" for r in data)
