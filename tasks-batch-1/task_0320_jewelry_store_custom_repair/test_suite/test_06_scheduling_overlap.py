"""Resource temporal-overlap depth tests: the two scheduling disciplines — half-open
bench windows (no buffer) and closed appraiser slots (with a 30-minute buffer).

Translates queue-A difficulty instances under rule_id resource_temporal_overlap.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    create_repair_ticket,
    create_workbench,
    create_inventory_item,
    schedule_repair_ticket,
    ApiErrorId,
    TEST_USERS,
)

SA = TEST_USERS["sales_associate_headers"]
GS = TEST_USERS["goldsmith_headers"]
SM = TEST_USERS["store_manager_headers"]


class TestBenchHalfOpenOverlap:
    def test_overlapping_bench_window_rejected(self, api):
        """PRD §2.10: "Two windows on the same bench conflict only if the new window starts
        strictly before the other's end and the other starts strictly before the new
        window's end."
        PRD §2.10: "Any conflict rejects the reservation with `ERR_BENCH_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/bench_window_half_open_overlap_rejected
        """
        bench = create_workbench()
        t1, customer_id = create_repair_ticket(repair_kind="POLISH")
        schedule_repair_ticket(
            t1, bench["id"], "2026-07-03T10:00:00Z", "2026-07-03T11:00:00Z"
        )
        t2, _ = create_repair_ticket(customer_id=customer_id, repair_kind="POLISH")
        res = api.schedule_repair_ticket(
            t2["id"],
            {"bench_id": bench["id"], "scheduled_start": "2026-07-03T10:30:00Z",
             "scheduled_end": "2026-07-03T11:30:00Z", "expected_version": t2["version"]},
            GS,
        )
        validate_error(res, ApiErrorId.ERR_BENCH_CONFLICT.value, expected_status=409)

    def test_adjacent_bench_window_allowed(self, api):
        """PRD §2.10: "Because the interval is half-open, adjacency is permitted — a window
        that ends exactly when another begins does not conflict."

        Design: Difficulty/resource_temporal_overlap/bench_window_half_open_overlap_rejected
        """
        bench = create_workbench()
        t1, customer_id = create_repair_ticket(repair_kind="POLISH")
        schedule_repair_ticket(
            t1, bench["id"], "2026-07-03T10:00:00Z", "2026-07-03T11:00:00Z"
        )
        t2, _ = create_repair_ticket(customer_id=customer_id, repair_kind="POLISH")
        # [11:00, 12:00) begins exactly when [10:00, 11:00) ends -> no conflict.
        scheduled = validate_success(
            api.schedule_repair_ticket(
                t2["id"],
                {"bench_id": bench["id"], "scheduled_start": "2026-07-03T11:00:00Z",
                 "scheduled_end": "2026-07-03T12:00:00Z", "expected_version": t2["version"]},
                GS,
            ),
            200,
        )
        assert scheduled["scheduled_start"] is not None


class TestAppraiserClosedBufferOverlap:
    def test_appointment_within_buffer_rejected(self, api):
        """PRD §2.10: "in addition a 30-minute buffer must separate consecutive appointments
        for the same appraiser. Effectively, an existing appointment occupies the window from
        30 minutes before its `appointment_start` to 30 minutes after its `appointment_end`."
        PRD §2.10: "Any conflict rejects creation with `ERR_APPRAISAL_SLOT_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/appraisal_slot_closed_plus_buffer_overlap_rejected
        """
        item = create_inventory_item()
        first = validate_success(
            api.create_appraisal(
                {"inventory_item_id": item["id"], "appraiser_name": "GIA-B",
                 "appointment_start": "2026-06-02T10:00:00Z",
                 "appointment_end": "2026-06-02T11:00:00Z", "market_value_cents": 300000},
                SM,
            ),
            201,
        )
        assert first["status"] == "DRAFT"
        # 11:15 is only 15 minutes after the prior 11:00 end -> within the 30-min buffer.
        res = api.create_appraisal(
            {"inventory_item_id": item["id"], "appraiser_name": "GIA-B",
             "appointment_start": "2026-06-02T11:15:00Z",
             "appointment_end": "2026-06-02T11:45:00Z", "market_value_cents": 300000},
            SM,
        )
        validate_error(res, ApiErrorId.ERR_APPRAISAL_SLOT_CONFLICT.value, expected_status=409)

    def test_appointment_beyond_buffer_for_same_appraiser_allowed(self, api):
        """PRD §2.10: "A new appointment conflicts with an existing one for the same
        `appraiser_name` if the new appointment's start is at or before the existing end plus
        the buffer, and the existing start minus the buffer is at or before the new
        appointment's end."

        Design: Difficulty/resource_temporal_overlap/appraisal_slot_closed_plus_buffer_overlap_rejected
        """
        item = create_inventory_item()
        validate_success(
            api.create_appraisal(
                {"inventory_item_id": item["id"], "appraiser_name": "GIA-B",
                 "appointment_start": "2026-06-02T10:00:00Z",
                 "appointment_end": "2026-06-02T11:00:00Z", "market_value_cents": 300000},
                SM,
            ),
            201,
        )
        # Start 11:31 is more than 30 minutes after the 11:00 end -> clears the buffer.
        second = validate_success(
            api.create_appraisal(
                {"inventory_item_id": item["id"], "appraiser_name": "GIA-B",
                 "appointment_start": "2026-06-02T11:31:00Z",
                 "appointment_end": "2026-06-02T12:00:00Z", "market_value_cents": 300000},
                SM,
            ),
            201,
        )
        assert second["status"] == "DRAFT"
