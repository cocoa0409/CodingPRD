"""Distribution events and pickup slots: windows, overlap rules, lane buckets."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    create_distribution_slot_payload, ApiErrorId,
    set_clock, setup_campaign_intake_open, setup_backfill_eligible,
    setup_event_open_for_slots, create_event, open_event_slots, book_slot,
    get_event, make_volunteer_headers, make_platform_admin_headers,
)


def _book_raw(api, event_id, family_id, window_start, window_end, lane,
              headers=None):
    """Attempt a slot booking, returning the raw response (may be an error)."""
    event = get_event(event_id)
    payload = create_distribution_slot_payload(
        event_id, family_id, event["version"], window_start=window_start,
        window_end=window_end, lane=lane)
    return api.create_distribution_slot(
        payload, headers or make_platform_admin_headers("admin_1"))


class TestEventGating:
    def test_open_slots_rejected_while_intake_open(self, api):
        """PRD §3.9: "Opening slots — `PLANNED → OPEN_FOR_SLOTS` — requires the
        parent campaign to be in `DISTRIBUTION_PREP`." While the campaign is in
        `INTAKE_OPEN` the transition precondition fails, and the error catalogue
        maps an invalid transition request to `ERR_INVALID_STATE` (HTTP 409).

        Design: Difficulty/cross_entity_state_dependency/slot_booking_gated_by_event_state_and_campaign_state
        """
        campaign, _agency = setup_campaign_intake_open()
        event = create_event(campaign["id"])
        res = api.open_slots(event["id"],
                             make_platform_admin_headers("admin_1"))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_event(event["id"])["status"] == "PLANNED"

    def test_open_slots_succeeds_in_distribution_prep(self, api):
        """PRD §3.9: "Opening slots — `PLANNED → OPEN_FOR_SLOTS` — requires the
        parent campaign to be in `DISTRIBUTION_PREP`."

        Design: Difficulty/cross_entity_state_dependency/slot_booking_gated_by_event_state_and_campaign_state
        """
        ctx = setup_backfill_eligible(num_families=1)  # campaign now in DISTRIBUTION_PREP
        assert ctx["campaign"]["status"] == "DISTRIBUTION_PREP"
        event = create_event(ctx["campaign"]["id"])
        opened = validate_success(api.open_slots(
            event["id"], make_platform_admin_headers("admin_1")))
        assert opened["status"] == "OPEN_FOR_SLOTS"


class TestFamilyAxisOverlap:
    def test_one_minute_overlap_rejected(self, api):
        """PRD §3.9: "On the family axis, no two slots for the same family may
        have overlapping half-open windows: a new slot `[window_start,
        window_end)` is rejected if there exists another slot for the same family
        (in any lane) whose `window_start` is strictly before the new slot's
        `window_end` and whose `window_end` is strictly after the new slot's
        `window_start`." PRD §3.9: "A violation is rejected with
        `ERR_SLOT_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/family_slot_halfopen_overlap
        """
        ctx = setup_event_open_for_slots(num_families=1)
        family_id = ctx["families"][0]["id"]
        event_id = ctx["event"]["id"]
        book_slot(event_id, family_id,
                  "2026-12-18T10:00:00Z", "2026-12-18T11:00:00Z", lane="A")
        res = _book_raw(api, event_id, family_id,
                        "2026-12-18T10:59:00Z", "2026-12-18T11:30:00Z", lane="B")
        validate_error(res, ApiErrorId.ERR_SLOT_OVERLAP, expected_status=409)

    def test_adjacent_and_contained_windows(self, api):
        """PRD §3.9: "Adjacent windows, where the new slot's `window_start` equals
        an existing slot's `window_end`, are permitted." — and by the half-open
        rule, a window strictly inside an existing one overlaps and is rejected
        with `ERR_SLOT_OVERLAP` (HTTP 409).

        Design: Difficulty/resource_temporal_overlap/family_slot_halfopen_overlap
        """
        ctx = setup_event_open_for_slots(num_families=1)
        family_id = ctx["families"][0]["id"]
        event_id = ctx["event"]["id"]
        book_slot(event_id, family_id,
                  "2026-12-18T10:00:00Z", "2026-12-18T11:00:00Z", lane="A")
        # Adjacent: new start equals existing end -> permitted.
        adjacent = _book_raw(api, event_id, family_id,
                             "2026-12-18T11:00:00Z", "2026-12-18T12:00:00Z",
                             lane="B")
        slot = validate_success(adjacent, 201)
        assert slot["status"] == "RESERVED"
        # Strictly contained: 10:15-10:45 overlaps 10:00-11:00 -> rejected.
        contained = _book_raw(api, event_id, family_id,
                              "2026-12-18T10:15:00Z", "2026-12-18T10:45:00Z",
                              lane="C")
        validate_error(contained, ApiErrorId.ERR_SLOT_OVERLAP,
                       expected_status=409)


class TestLaneBucketCapacity:
    def test_fifth_slot_in_same_lane_bucket_rejected(self, api):
        """PRD §3.9: "On the lane axis, the timeline is divided into 30-minute
        buckets aligned to `:00` and `:30` UTC; within any such bucket, the count
        of slots in the same lane whose windows overlap the bucket must not exceed
        4. A violation is rejected with `ERR_LANE_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/lane_bucket_aggregate_capacity
        """
        ctx = setup_event_open_for_slots(num_families=5)
        event_id = ctx["event"]["id"]
        windows = [("2026-12-18T10:00:00Z", "2026-12-18T10:30:00Z"),
                   ("2026-12-18T10:05:00Z", "2026-12-18T10:35:00Z"),
                   ("2026-12-18T10:10:00Z", "2026-12-18T10:40:00Z"),
                   ("2026-12-18T10:15:00Z", "2026-12-18T10:45:00Z")]
        for family, (start, end) in zip(ctx["families"], windows):
            book_slot(event_id, family["id"], start, end, lane="A")
        fifth = ctx["families"][4]
        res = _book_raw(api, event_id, fifth["id"],
                        "2026-12-18T10:20:00Z", "2026-12-18T10:50:00Z", lane="A")
        validate_error(res, ApiErrorId.ERR_LANE_CAPACITY_EXCEEDED,
                       expected_status=409)

    def test_five_slots_spread_across_lanes_permitted(self, api):
        """PRD §3.9: "within any such bucket, the count of slots in the same lane
        whose windows overlap the bucket must not exceed 4" — the aggregate is
        per lane, so five same-window slots across lanes A/B/C/D/A stay at or
        below 2 per lane and all succeed.

        Design: Difficulty/resource_temporal_overlap/lane_bucket_aggregate_capacity
        """
        ctx = setup_event_open_for_slots(num_families=5)
        event_id = ctx["event"]["id"]
        for family, lane in zip(ctx["families"], ["A", "B", "C", "D", "A"]):
            slot = _book_raw(api, event_id, family["id"],
                             "2026-12-18T10:00:00Z", "2026-12-18T10:30:00Z",
                             lane=lane)
            validate_success(slot, 201)


class TestNestedOverlapSemantics:
    def test_family_adjacency_permitted_with_lane_bucket_occupied(self, api):
        """PRD §3.9: "Adjacent windows, where the new slot's `window_start` equals
        an existing slot's `window_end`, are permitted." The lane-bucket rule is
        a separate aggregate ("within any such bucket, the count of slots in the
        same lane whose windows overlap the bucket must not exceed 4"), so a
        lane-B booking adjacent on the family axis succeeds even while lane A's
        10:00-10:30 bucket is full.

        Design: Difficulty/combinatorial_formula/slot_overlap_interval_semantics_mode_b
        """
        ctx = setup_event_open_for_slots(num_families=5)
        event_id = ctx["event"]["id"]
        f1, f2, f3, f4, _f5 = [f["id"] for f in ctx["families"]]
        book_slot(event_id, f1, "2026-12-18T10:00:00Z", "2026-12-18T11:00:00Z",
                  lane="A")
        book_slot(event_id, f2, "2026-12-18T10:00:00Z", "2026-12-18T10:30:00Z",
                  lane="A")
        book_slot(event_id, f3, "2026-12-18T10:05:00Z", "2026-12-18T10:35:00Z",
                  lane="A")
        book_slot(event_id, f4, "2026-12-18T10:10:00Z", "2026-12-18T10:40:00Z",
                  lane="A")
        # Lane A bucket 10:00-10:30 now holds 4 slots. F1 books an adjacent
        # 11:00-12:00 window in lane B: family-axis adjacency is permitted and
        # lane B's bucket is empty.
        res = _book_raw(api, event_id, f1,
                        "2026-12-18T11:00:00Z", "2026-12-18T12:00:00Z", lane="B")
        slot = validate_success(res, 201)
        assert slot["status"] == "RESERVED"

    def test_fifth_lane_booking_fails_while_adjacency_would_pass(self, api):
        """PRD §3.9: "within any such bucket, the count of slots in the same lane
        whose windows overlap the bucket must not exceed 4. A violation is
        rejected with `ERR_LANE_CAPACITY_EXCEEDED` (HTTP 409)." The fifth family
        has no family-axis conflict at all, so the failure is attributable purely
        to the lane-bucket aggregate.

        Design: Difficulty/combinatorial_formula/slot_overlap_interval_semantics_mode_b
        """
        ctx = setup_event_open_for_slots(num_families=5)
        event_id = ctx["event"]["id"]
        f1, f2, f3, f4, f5 = [f["id"] for f in ctx["families"]]
        book_slot(event_id, f1, "2026-12-18T10:00:00Z", "2026-12-18T11:00:00Z",
                  lane="A")
        book_slot(event_id, f2, "2026-12-18T10:00:00Z", "2026-12-18T10:30:00Z",
                  lane="A")
        book_slot(event_id, f3, "2026-12-18T10:05:00Z", "2026-12-18T10:35:00Z",
                  lane="A")
        book_slot(event_id, f4, "2026-12-18T10:10:00Z", "2026-12-18T10:40:00Z",
                  lane="A")
        res = _book_raw(api, event_id, f5,
                        "2026-12-18T10:15:00Z", "2026-12-18T10:45:00Z", lane="A")
        validate_error(res, ApiErrorId.ERR_LANE_CAPACITY_EXCEEDED,
                       expected_status=409)


class TestSlotWindowAndEventCompletion:
    def test_checkin_before_window_rejected(self, api):
        """PRD §3.9: "a `DistributionVolunteer` checks the family in — `RESERVED →
        CHECKED_IN` — provided the current instant is at or after `window_start`
        and at or before `window_end`; a check-in outside that window is rejected
        with `ERR_OUTSIDE_SLOT_WINDOW` (HTTP 409)."

        Design: Corner/state_machines/slot_checkin_outside_window_rejected
        """
        ctx = setup_event_open_for_slots(num_families=1)
        slot = book_slot(ctx["event"]["id"], ctx["families"][0]["id"],
                         "2026-12-18T10:00:00Z", "2026-12-18T11:00:00Z", lane="A")
        set_clock("2026-12-18T09:00:00Z")  # one hour before window_start
        res = api.check_in_slot(slot["id"], make_volunteer_headers("vol_1"))
        validate_error(res, ApiErrorId.ERR_OUTSIDE_SLOT_WINDOW,
                       expected_status=409)
        after = validate_success(api.get_distribution_slot(
            slot["id"], make_platform_admin_headers("admin_1")))
        assert after["status"] == "RESERVED"

    def test_event_complete_blocked_while_slot_non_terminal(self, api):
        """PRD §3.9: "Completing — `LOCKED → COMPLETED` — requires every slot
        under the event to be in `COMPLETED`, `NO_SHOW`, or `CANCELLED`." A
        `RESERVED` slot blocks completion; the error catalogue maps the failed
        transition precondition to `ERR_INVALID_STATE` (HTTP 409).

        Design: Corner/state_machines/event_complete_cascade_completes_slots
        """
        ctx = setup_event_open_for_slots(num_families=1)
        event_id = ctx["event"]["id"]
        book_slot(event_id, ctx["families"][0]["id"],
                  "2026-12-18T10:00:00Z", "2026-12-18T11:00:00Z", lane="A")
        admin = make_platform_admin_headers("admin_1")
        validate_success(api.begin_sorting(event_id, admin))
        validate_success(api.lock_event(event_id, admin))
        res = api.complete_event(event_id, admin)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_event(event_id)["status"] == "LOCKED"
