"""ServiceOrder operating rules: service days, switching frequency cap,
possession half-open overlap, and the one-hour buffer (PRD §3.5).
"""
from test_helpers import (
    SHIPPER,
    ApiErrorId,
    assert_service_order,
    create_service_order_payload,
    make_service_order,
    setup_agreement_with_segment,
    validate_error,
    validate_success,
)
from test_helpers import constants as C


def _order_payload(agr_id, seg_id, order_type, service_date, start, end):
    return create_service_order_payload(
        agr_id,
        seg_id,
        order_type=order_type,
        service_date=service_date,
        start_hour=start,
        end_hour=end,
    )


class TestServiceDays:
    def test_tuesday_switching_order_rejected(self, api):
        """PRD §3.5: "A `SWITCHING` order may only be scheduled on a day of the
        week — derived from `service_date` in UTC — that appears in the
        agreement's `service_days_of_week`, otherwise `ERR_NOT_A_SERVICE_DAY`."

        Design: Corner/validations/tuesday_switching_order_rejected
        """
        ctx = setup_agreement_with_segment()
        # 2026-08-04 is a Tuesday; the agreement serves MON/WED/FRI only.
        res = api.create_service_order(
            _order_payload(
                ctx["agreement"]["id"], ctx["segment"]["id"],
                "SWITCHING", C.TUESDAY_DATE, 8, 10,
            ),
            SHIPPER,
        )
        validate_error(res, ApiErrorId.ERR_NOT_A_SERVICE_DAY, 409)


class TestSwitchFrequencyCap:
    def test_second_switch_same_day_rejected(self, api):
        """PRD §3.5: "Finally, the number of non-`CANCELLED` `SWITCHING` orders
        on a segment for a given `service_date` must stay below the agreement's
        `max_switches_per_day`; at the cap the request fails with
        `ERR_SWITCH_LIMIT_EXCEEDED`."

        Design: Corner/validations/second_switch_same_day_rejected
        """
        ctx = setup_agreement_with_segment()
        agr_id = ctx["agreement"]["id"]
        seg_id = ctx["segment"]["id"]
        first = make_service_order(agr_id, seg_id, "SWITCHING", C.MONDAY_DATE, 8, 10)
        assert_service_order(first)
        assert first["status"] == "REQUESTED"
        res = api.create_service_order(
            _order_payload(agr_id, seg_id, "SWITCHING", C.MONDAY_DATE, 10, 12),
            SHIPPER,
        )
        validate_error(res, ApiErrorId.ERR_SWITCH_LIMIT_EXCEEDED, 409)


class TestPossessionOverlap:
    def test_adjacent_possessions_allowed_half_open(self, api):
        """PRD §3.5: "Two `MAINTENANCE_POSSESSION` orders on the same segment
        and service date may not overlap under the half-open rule (touching
        endpoints are allowed), or the request fails with
        `ERR_POSSESSION_OVERLAP`."
        PRD §3.5: "Windows are half-open — an order occupying hours 8 to 11
        conflicts with one starting at 10 but not with one starting at 11."

        Design: Difficulty/resource_temporal_overlap/possession_half_open_adjacency_and_overlap
        """
        ctx = setup_agreement_with_segment()
        agr_id = ctx["agreement"]["id"]
        seg_id = ctx["segment"]["id"]
        first = make_service_order(
            agr_id, seg_id, "MAINTENANCE_POSSESSION", C.WEDNESDAY_DATE, 8, 12
        )
        assert first["status"] == "REQUESTED"
        # The 12:00 start touches the 12:00 end — allowed under half-open.
        second = validate_success(
            api.create_service_order(
                _order_payload(
                    agr_id, seg_id, "MAINTENANCE_POSSESSION",
                    C.WEDNESDAY_DATE, 12, 14,
                ),
                SHIPPER,
            ),
            201,
        )
        assert second["status"] == "REQUESTED"

    def test_overlapping_possession_rejected(self, api):
        """PRD §3.5: "Two `MAINTENANCE_POSSESSION` orders on the same segment
        and service date may not overlap under the half-open rule (touching
        endpoints are allowed), or the request fails with
        `ERR_POSSESSION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/possession_half_open_adjacency_and_overlap
        """
        ctx = setup_agreement_with_segment()
        agr_id = ctx["agreement"]["id"]
        seg_id = ctx["segment"]["id"]
        make_service_order(
            agr_id, seg_id, "MAINTENANCE_POSSESSION", C.WEDNESDAY_DATE, 8, 12
        )
        make_service_order(
            agr_id, seg_id, "MAINTENANCE_POSSESSION", C.WEDNESDAY_DATE, 12, 14
        )
        # 11:00-13:00 intersects both existing windows.
        res = api.create_service_order(
            _order_payload(
                agr_id, seg_id, "MAINTENANCE_POSSESSION", C.WEDNESDAY_DATE, 11, 13
            ),
            SHIPPER,
        )
        validate_error(res, ApiErrorId.ERR_POSSESSION_OVERLAP, 409)


class TestPossessionBuffer:
    def test_possession_buffer_conflict_and_edge(self, api):
        """PRD §3.5: "Switching and possessions are kept apart by a one-hour
        buffer in both directions: a `SWITCHING` window may not intersect any
        possession on the same segment and date expanded by one hour on each
        side, and symmetrically a new possession may not intersect existing
        switching windows so expanded — violations are rejected with
        `ERR_POSSESSION_BUFFER_CONFLICT`."
        PRD §3.5: "Windows are half-open — an order occupying hours 8 to 11
        conflicts with one starting at 10 but not with one starting at 11."

        Design: Corner/validations/possession_buffer_conflict_and_edge
        """
        ctx = setup_agreement_with_segment()
        agr_id = ctx["agreement"]["id"]
        seg_id = ctx["segment"]["id"]
        make_service_order(
            agr_id, seg_id, "MAINTENANCE_POSSESSION", C.WEDNESDAY_DATE, 8, 12
        )
        # The possession buffered one hour each way spans [07:00, 13:00);
        # a 12:00-13:00 switching window falls inside it.
        blocked = api.create_service_order(
            _order_payload(agr_id, seg_id, "SWITCHING", C.WEDNESDAY_DATE, 12, 13),
            SHIPPER,
        )
        validate_error(blocked, ApiErrorId.ERR_POSSESSION_BUFFER_CONFLICT, 409)
        # 13:00-14:00 starts exactly at the buffer's end: half-open, so allowed.
        ok = api.create_service_order(
            _order_payload(agr_id, seg_id, "SWITCHING", C.WEDNESDAY_DATE, 13, 14),
            SHIPPER,
        )
        order = validate_success(ok, 201)
        assert order["status"] == "REQUESTED"
