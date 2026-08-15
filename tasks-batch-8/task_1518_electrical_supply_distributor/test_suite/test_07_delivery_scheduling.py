"""Delivery scheduling: the half-open truck-window overlap rule, the jobsite
day bucket, the past-window temporal guard, and validation priority."""
from test_helpers import (
    DISPATCHER,
    ApiErrorId,
    api_client,
    assert_release,
    create_awarded_quote,
    create_contractor,
    create_ea_item,
    create_job_account,
    create_release,
    credit_approve_release,
    allocate_release,
    get_release,
    receive_stock,
    schedule_release,
    setup_allocated_release,
    setup_past_window_world,
    setup_truck_window_world,
    validate_error,
    validate_success,
)


class TestTruckWindowHalfOpen:

    def test_adjacent_window_at_existing_end_allowed(self):
        """PRD section 3.8: "no other release with the same `truck_id` and the
        same `delivery_date` in `SCHEDULED` or `DELIVERED` status may hold a
        window overlapping the new one — under the half-open convention a new
        window does not conflict if it ends at or before an existing window's
        start, or begins at or after the existing window's end; any tighter
        interleaving is rejected with `ERR_TRUCK_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/truck_window_half_open_overlap
        """
        world = setup_truck_window_world()
        r2 = world["releases"][1]
        resp = api_client.schedule_release(
            r2["id"],
            {"truck_id": "T1", "delivery_date": "2026-08-20",
             "window_start_hour": 12, "window_end_hour": 15},
            DISPATCHER)
        data = validate_success(resp, expected_status=200)
        assert_release(data)
        assert data["status"] == "SCHEDULED", (
            "a window beginning exactly at the existing window's end "
            "(12 == 12) is not an overlap under the half-open convention")

    def test_interleaving_window_rejected(self):
        """PRD section 3.8: "no other release with the same `truck_id` and the
        same `delivery_date` in `SCHEDULED` or `DELIVERED` status may hold a
        window overlapping the new one — under the half-open convention a new
        window does not conflict if it ends at or before an existing window's
        start, or begins at or after the existing window's end; any tighter
        interleaving is rejected with `ERR_TRUCK_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/truck_window_half_open_overlap
        """
        world = setup_truck_window_world()
        r3 = world["releases"][2]
        resp = api_client.schedule_release(
            r3["id"],
            {"truck_id": "T1", "delivery_date": "2026-08-20",
             "window_start_hour": 11, "window_end_hour": 13},
            DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_TRUCK_WINDOW_OVERLAP)
        assert get_release(r3["id"])["status"] == "ALLOCATED"


class TestJobsiteDayBucket:

    def test_jobsite_same_day_conflict_rejected(self):
        """PRD section 3.8: "And the jobsite must not already be receiving a
        delivery that day: no other release on the same job account may hold a
        `SCHEDULED` or `DELIVERED` delivery on that date, else
        `ERR_JOBSITE_DAY_CONFLICT`."

        Design: Corner/validations/jobsite_same_day_conflict_rejected
        """
        contractor = create_contractor("Day Electric", 100_000)
        item = create_ea_item()
        receive_stock(item["id"], 5)
        job = create_job_account(contractor["id"], "Day Job",
                                 jobsite_address="48 Site Rd")
        quote = create_awarded_quote(job["id"], [(item["id"], 2, 5000)])
        r1 = create_release(job["id"], quote["id"], [(item["id"], 1)])
        credit_approve_release(r1["id"])
        allocate_release(r1["id"])
        schedule_release(r1["id"], truck_id="T1", delivery_date="2026-08-20",
                         window_start_hour=8, window_end_hour=10)

        r2 = create_release(job["id"], quote["id"], [(item["id"], 1)])
        credit_approve_release(r2["id"])
        allocate_release(r2["id"])
        resp = api_client.schedule_release(
            r2["id"],
            {"truck_id": "T2", "delivery_date": "2026-08-20",
             "window_start_hour": 14, "window_end_hour": 16},
            DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_JOBSITE_DAY_CONFLICT)
        assert get_release(r2["id"])["status"] == "ALLOCATED"


class TestWindowShape:

    def test_schedule_window_inverted_rejected(self):
        """PRD section 2.9: "Every write request is first checked for
        structural validity: required fields must be present, enum fields must
        name a declared member, quantities such as `qty` must be greater than
        zero, a delivery window's `window_end_hour` must be strictly later
        than its `window_start_hour`, and the reel fields `reel_length_ft`,
        `min_cut_ft`, and `cut_charge_cents` must be present when the item's
        `sell_uom` is `FOOT` and absent when it is `EA`."

        Design: Corner/validations/schedule_window_inverted_rejected
        """
        ctx = setup_allocated_release()
        resp = api_client.schedule_release(
            ctx["release"]["id"],
            {"truck_id": "T1", "delivery_date": "2026-08-10",
             "window_start_hour": 12, "window_end_hour": 8},
            DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert get_release(ctx["release"]["id"])["status"] == "ALLOCATED"


class TestPastWindowPriority:

    def test_past_window_error_returned_when_overlap_also_present(self):
        """PRD section 2.10: "When several checks could reject the same
        request, they are evaluated in a fixed priority order so the surfaced
        error is deterministic:" with clock-relative temporal rules (7)
        evaluated before domain constraints (9).
        PRD section 3.8: "The `delivery_date` must not fall before the logical
        clock's current date, else `ERR_DELIVERY_WINDOW_PAST`."

        Design: Difficulty/priority_pair_validation_conflict/schedule_past_window_beats_truck_overlap_rejected
        """
        world = setup_past_window_world()
        r2 = world["r2"]
        # 2026-08-20 is before the 2026-08-25 clock AND window [10, 14)
        # overlaps R1's [8, 12) on truck T1 that day.
        resp = api_client.schedule_release(
            r2["id"],
            {"truck_id": "T1", "delivery_date": "2026-08-20",
             "window_start_hour": 10, "window_end_hour": 14},
            DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_PAST)
        assert get_release(r2["id"])["status"] == "ALLOCATED"

    def test_past_window_error_returned_without_any_overlap(self):
        """PRD section 3.8: "The `delivery_date` must not fall before the
        logical clock's current date, else `ERR_DELIVERY_WINDOW_PAST`."

        Design: Difficulty/priority_pair_validation_conflict/schedule_past_window_beats_truck_overlap_rejected
        """
        world = setup_past_window_world()
        r2 = world["r2"]
        # Window [13, 15) is disjoint from R1's [8, 12), isolating the
        # temporal failure on the past date.
        resp = api_client.schedule_release(
            r2["id"],
            {"truck_id": "T1", "delivery_date": "2026-08-20",
             "window_start_hour": 13, "window_end_hour": 15},
            DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_PAST)
        assert get_release(r2["id"])["status"] == "ALLOCATED"
