"""Material deliveries: inspection partition, submit gate, zone window buffer."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_crew_entry,
    add_delivery,
    add_weather_observation,
    assert_delivery_partition,
    create_delivery_payload,
    get_delivery,
    make_active_project,
    make_delivery_zone,
    make_report,
    make_work_area,
    set_clock,
    submit_clock_for,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["system_admin_headers"]
_SUPT = TEST_USERS["superintendent_headers"]


class TestSubmitBlockedByUninspectedDelivery:
    def test_partial_delivery_blocks_submit_until_recount_resolved(self, api):
        """PRD section 3.9: "every material delivery on the report must be
        `INSPECTED`, so a delivery still `DELIVERED` or `PARTIAL` blocks
        submission with `ERR_DELIVERY_NOT_INSPECTED`".

        Design: Difficulty/cross_entity_state_dependency/submit_blocked_by_uninspected_delivery
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        zone = make_delivery_zone(project["id"], buffer_minutes=30)
        report = make_report(project["id"])
        add_weather_observation(report["id"])
        add_crew_entry(report["id"], area["id"], work_performed="unload")
        delivery = add_delivery(report["id"], zone["id"], delivered_qty=100)

        partial = validate_success(api.inspect_delivery(
            delivery["id"], {"accepted_qty": 60, "rejected_qty": 25}, _SUPT))
        assert partial["status"] == "PARTIAL"
        assert partial["pending_recount_qty"] == pytest.approx(15)

        set_clock(submit_clock_for(report["report_date"]))
        err = api.submit_report(report["id"], _SUPT)
        validate_error(err, ApiErrorId.ERR_DELIVERY_NOT_INSPECTED)
        assert err.status_code == 409

        resolved = validate_success(api.resolve_recount(
            delivery["id"], {"recount_accepted_qty": 15}, _SUPT))
        assert resolved["status"] == "INSPECTED"
        assert_delivery_partition(resolved)

        submitted = validate_success(api.submit_report(report["id"], _SUPT))
        assert submitted["status"] == "SUBMITTED"

    def test_uninspected_delivery_blocks_submit_until_fully_inspected(self, api):
        """PRD section 3.9: "every material delivery on the report must be
        `INSPECTED`, so a delivery still `DELIVERED` or `PARTIAL` blocks
        submission with `ERR_DELIVERY_NOT_INSPECTED`".

        Design: Difficulty/cross_entity_state_dependency/submit_blocked_by_uninspected_delivery
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        zone = make_delivery_zone(project["id"])
        report = make_report(project["id"])
        add_weather_observation(report["id"])
        add_crew_entry(report["id"], area["id"])
        delivery = add_delivery(report["id"], zone["id"], delivered_qty=10,
                                unit="EA")

        set_clock(submit_clock_for(report["report_date"]))
        err = api.submit_report(report["id"], _SUPT)
        validate_error(err, ApiErrorId.ERR_DELIVERY_NOT_INSPECTED)

        inspected = validate_success(api.inspect_delivery(
            delivery["id"], {"accepted_qty": 10, "rejected_qty": 0}, _SUPT))
        assert inspected["status"] == "INSPECTED"

        submitted = validate_success(api.submit_report(report["id"], _SUPT))
        assert submitted["status"] == "SUBMITTED"


class TestInspectionPartitionInvariant:
    def test_partition_conserved_through_partial_inspect_and_recount(self, api):
        """PRD section 3.6: "one invariant holds at all times: accepted plus
        rejected plus pending recount always equals the delivered quantity." and
        "the accepted total gains that amount, the rejected total gains whatever
        of the pending remainder remains, the pending remainder goes to zero, and
        the delivery becomes `INSPECTED`."

        Design: Difficulty/compensating_invariant/delivery_inspection_partition_conserved
        """
        project = make_active_project()
        zone = make_delivery_zone(project["id"], buffer_minutes=30)
        report = make_report(project["id"])
        delivery = add_delivery(report["id"], zone["id"], delivered_qty=100)

        assert delivery["accepted_qty"] == pytest.approx(0)
        assert delivery["rejected_qty"] == pytest.approx(0)
        assert delivery["pending_recount_qty"] == pytest.approx(100)
        assert_delivery_partition(delivery)

        partial = validate_success(api.inspect_delivery(
            delivery["id"], {"accepted_qty": 60, "rejected_qty": 25}, _SUPT))
        assert partial["accepted_qty"] == pytest.approx(60)
        assert partial["rejected_qty"] == pytest.approx(25)
        assert partial["pending_recount_qty"] == pytest.approx(15)
        assert partial["status"] == "PARTIAL"
        assert_delivery_partition(partial)

        resolved = validate_success(api.resolve_recount(
            delivery["id"], {"recount_accepted_qty": 10}, _SUPT))
        assert resolved["accepted_qty"] == pytest.approx(70)
        assert resolved["rejected_qty"] == pytest.approx(30)
        assert resolved["pending_recount_qty"] == pytest.approx(0)
        assert resolved["status"] == "INSPECTED"
        assert_delivery_partition(resolved)

    def test_full_single_inspect_lands_inspected_directly(self, api):
        """PRD section 3.6: "When the split exactly exhausts the pending
        remainder, the delivery lands in the terminal `INSPECTED` status; when
        any remainder is left, it lands in `PARTIAL` and awaits further
        inspection." and "one invariant holds at all times: accepted plus
        rejected plus pending recount always equals the delivered quantity."

        Design: Difficulty/compensating_invariant/delivery_inspection_partition_conserved
        """
        project = make_active_project()
        zone = make_delivery_zone(project["id"])
        report = make_report(project["id"])
        delivery = add_delivery(report["id"], zone["id"], delivered_qty=10,
                                unit="EA")

        inspected = validate_success(api.inspect_delivery(
            delivery["id"], {"accepted_qty": 4, "rejected_qty": 6}, _SUPT))
        assert inspected["status"] == "INSPECTED", \
            "zero remainder lands the delivery in INSPECTED directly"
        assert inspected["pending_recount_qty"] == pytest.approx(0)
        assert_delivery_partition(inspected)


class TestZoneWindowBuffer:
    def test_closed_interval_plus_buffer_gap(self, api):
        """PRD section 3.6: "windows must be separated by at least the zone's
        `buffer_minutes` on both sides, meaning a later window must begin at
        least `buffer_minutes` after the earlier window's end"; "Two windows
        that merely touch, with no buffer between them, count as a collision and
        are rejected with `ERR_DELIVERY_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/delivery_zone_window_buffer_closed_interval
        """
        project = make_active_project()
        zone = make_delivery_zone(project["id"], buffer_minutes=30)
        report = make_report(project["id"])

        add_delivery(report["id"], zone["id"], delivered_qty=10,
                     scheduled_window_start="2026-08-05T09:00:00Z",
                     scheduled_window_end="2026-08-05T10:00:00Z")

        # Gap of exactly buffer_minutes (30) passes.
        ok = validate_success(api.create_delivery(
            create_delivery_payload(
                report["id"], zone["id"], delivered_qty=5, unit="CY",
                scheduled_window_start="2026-08-05T10:30:00Z",
                scheduled_window_end="2026-08-05T11:30:00Z"),
            _SUPT), 201)
        assert ok["id"]

        # A 29-minute gap is one minute short of the buffer.
        err = api.create_delivery(
            create_delivery_payload(
                report["id"], zone["id"], delivered_qty=1, unit="EA",
                scheduled_window_start="2026-08-05T10:29:00Z",
                scheduled_window_end="2026-08-05T11:00:00Z"),
            _SUPT)
        validate_error(err, ApiErrorId.ERR_DELIVERY_WINDOW_OVERLAP)
        assert err.status_code == 409

        rows, meta = validate_paginated(api.list_deliveries(
            _SUPT, params={"report_id": report["id"]}))
        assert meta["total_count"] == 2

    def test_touching_windows_collide_and_other_zone_unaffected(self, api):
        """PRD section 3.6: "Two windows that merely touch, with no buffer
        between them, count as a collision and are rejected with
        `ERR_DELIVERY_WINDOW_OVERLAP`." and "Two deliveries in the same zone may
        not crowd each other" — the separation rule is per zone.

        Design: Difficulty/resource_temporal_overlap/delivery_zone_window_buffer_closed_interval
        """
        project = make_active_project()
        zone1 = make_delivery_zone(project["id"], buffer_minutes=30)
        zone2 = make_delivery_zone(project["id"], buffer_minutes=30)
        report = make_report(project["id"])

        add_delivery(report["id"], zone1["id"], delivered_qty=10,
                     scheduled_window_start="2026-08-05T09:00:00Z",
                     scheduled_window_end="2026-08-05T10:00:00Z")

        touching = api.create_delivery(
            create_delivery_payload(
                report["id"], zone1["id"], delivered_qty=2, unit="EA",
                scheduled_window_start="2026-08-05T10:00:00Z",
                scheduled_window_end="2026-08-05T11:00:00Z"),
            _SUPT)
        validate_error(touching, ApiErrorId.ERR_DELIVERY_WINDOW_OVERLAP)

        other_zone = validate_success(api.create_delivery(
            create_delivery_payload(
                report["id"], zone2["id"], delivered_qty=2, unit="EA",
                scheduled_window_start="2026-08-05T09:30:00Z",
                scheduled_window_end="2026-08-05T10:30:00Z"),
            _SUPT), 201)
        assert other_zone["id"], "the buffer rule applies only within a zone"


class TestInspectionBounds:
    def test_inspection_quantities_overflow_rejected(self, api):
        """PRD section 3.6: "Each inspection call supplies a non-negative
        `accepted_qty` and `rejected_qty` whose sum must not exceed the current
        `pending_recount_qty` — otherwise `ERR_INSPECTION_QTY_OVERFLOW`" and
        "the superintendent supplies `recount_accepted_qty` — non-negative and
        not exceeding the pending remainder, under the same
        `ERR_INSPECTION_QTY_OVERFLOW` guard".

        Design: Corner/errors/inspection_overflow_rejected
        """
        project = make_active_project()
        zone = make_delivery_zone(project["id"])
        report = make_report(project["id"])
        delivery = add_delivery(report["id"], zone["id"], delivered_qty=10,
                                unit="EA")
        validate_success(api.inspect_delivery(
            delivery["id"], {"accepted_qty": 6, "rejected_qty": 0}, _SUPT))
        assert get_delivery(delivery["id"])["pending_recount_qty"] == pytest.approx(4)

        err1 = api.inspect_delivery(
            delivery["id"], {"accepted_qty": 3, "rejected_qty": 2}, _SUPT)
        validate_error(err1, ApiErrorId.ERR_INSPECTION_QTY_OVERFLOW)
        assert err1.status_code == 422

        err2 = api.resolve_recount(delivery["id"], {"recount_accepted_qty": 5}, _SUPT)
        validate_error(err2, ApiErrorId.ERR_INSPECTION_QTY_OVERFLOW)
        assert err2.status_code == 422

    def test_closed_zone_rejects_delivery_until_reopened(self, api):
        """PRD section 3.1: "a hard refusal — `ERR_DELIVERY_ZONE_CLOSED` — of
        any new delivery aimed at a `CLOSED` zone."

        Design: Corner/validations/delivery_zone_closed_rejects_new_deliveries
        """
        project = make_active_project()
        zone = make_delivery_zone(project["id"])
        validate_success(api.close_delivery_zone(zone["id"], _ADMIN))
        report = make_report(project["id"])

        err = api.create_delivery(create_delivery_payload(report["id"], zone["id"],
                                                          delivered_qty=10, unit="LF"),
                                  _SUPT)
        validate_error(err, ApiErrorId.ERR_DELIVERY_ZONE_CLOSED)
        assert err.status_code == 409

        validate_success(api.reopen_delivery_zone(zone["id"], _ADMIN))
        ok = validate_success(api.create_delivery(
            create_delivery_payload(report["id"], zone["id"], delivered_qty=10,
                                    unit="LF"), _SUPT), 201)
        assert ok["status"] == "DELIVERED"
