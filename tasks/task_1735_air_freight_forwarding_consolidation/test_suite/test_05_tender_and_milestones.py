"""Tender gating, FINAL re-rate, milestone rank rules, booking bubble-up (PRD §3.2, §3.5, §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_master_waybill,
    assert_milestone_event,
    assert_money_equal,
    assert_weight_equal,
    clear_hwb,
    consolidate_hwb,
    create_booking,
    create_hwb,
    create_mawb,
    get_booking,
    get_hwb,
    get_mawb,
    measure_hwb,
    open_mawb,
    record_milestone,
    setup_consolidated,
    setup_lane,
    setup_tendered,
    set_clock,
    tender_mawb,
    tender_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

DELIVERED_UTC = "2026-08-11T09:00:00Z"


class TestTenderGates:
    def test_tender_without_measured_volume_returns_missing(
        self, api, capacity_planner_headers
    ):
        """PRD §3.6: "every attached `CONSOLIDATED` waybill must have
        `measured_volume_m3` recorded, else `ERR_MEASURED_VOLUME_MISSING`"

        Design: Corner/validations/tender_without_measured_volume_returns_missing
        """
        ctx = setup_consolidated()  # consolidated but never measured
        resp = api.tender_master_waybill(
            ctx["mawb"]["id"], tender_payload(), capacity_planner_headers
        )
        validate_error(resp, ApiErrorId.ERR_MEASURED_VOLUME_MISSING)
        assert get_mawb(ctx["mawb"]["id"])["status"] == "OPEN_FOR_CONSOLIDATION"
        hwb = get_hwb(ctx["hwb"]["id"])
        assert hwb["status"] == "CONSOLIDATED"
        assert hwb["weight_basis"] == "QUOTED"

    def test_tender_empty_mawb_returns_no_consolidated(
        self, api, capacity_planner_headers
    ):
        """PRD §3.6: "at least one attached waybill must be in `CONSOLIDATED` state,
        else `ERR_NO_CONSOLIDATED_HOUSE_WAYBILLS`"

        Design: Corner/validations/tender_empty_mawb_returns_no_consolidated
        """
        booking = create_booking()
        mawb = create_mawb(booking["id"])
        open_mawb(mawb["id"])
        resp = api.tender_master_waybill(mawb["id"], tender_payload(), capacity_planner_headers)
        validate_error(resp, ApiErrorId.ERR_NO_CONSOLIDATED_HOUSE_WAYBILLS)
        assert get_mawb(mawb["id"])["status"] == "OPEN_FOR_CONSOLIDATION"


class TestQuotedVsFinal:
    def test_quoted_rating_at_consolidation_from_declared_volume(self, api):
        """PRD §3.5: "The rule exists in two variants differing only in volume source:
        the `QUOTED` variant, computed at consolidation, uses the shipper's
        `declared_volume_m3`; the `FINAL` variant, computed at master-waybill tender,
        uses the warehouse-measured `measured_volume_m3`."

        Design: Difficulty/dual_variant_calc/quoted_vs_final_chargeable_weight
        """
        ctx = setup_consolidated()  # 80.0 kg gross, 0.60 m3 declared
        hwb = ctx["hwb"]
        assert hwb["weight_basis"] == "QUOTED"
        # QUOTED: 0.60 / 0.006 = 100.0 kg dimensional beats 80.0 kg gross
        assert_weight_equal(hwb["chargeable_weight_kg"], 100.0, "chargeable_weight_kg")
        # 4.00 x 100.0 = 400.00 freight; 50.00 fuel; 25.00 security; no spot
        assert_money_equal(hwb["freight_amount"], 400.00, "freight_amount")
        assert_money_equal(hwb["total_charge_amount"], 475.00, "total_charge_amount")

    def test_final_rating_at_tender_from_measured_volume(self, api):
        """PRD §3.5: "the `FINAL` variant, computed at master-waybill tender, uses the
        warehouse-measured `measured_volume_m3`. Because every downstream charge
        derives from chargeable weight, a measurement delta between declared and
        measured volume reprices the entire waybill at tender."
        PRD §3.6: "for each attached `CONSOLIDATED` waybill: `weight_basis` becomes
        `FINAL`, `chargeable_weight_kg` is recomputed from the measured volume, all
        charge lines are recomputed through the same rate agreement, the locked spot
        flag is left untouched, and the waybill's status becomes `TENDERED`."

        Design: Difficulty/dual_variant_calc/quoted_vs_final_chargeable_weight
        """
        ctx = setup_consolidated()
        measure_hwb(ctx["hwb"]["id"], 0.90)
        mawb = tender_mawb(ctx["mawb"]["id"])
        # FINAL: 0.90 / 0.006 = 150.0 kg
        assert_weight_equal(
            mawb["total_chargeable_weight_kg"], 150.0, "mawb total_chargeable_weight_kg"
        )
        assert_money_equal(mawb["total_freight_amount"], 700.00, "mawb total_freight_amount")

        hwb = get_hwb(ctx["hwb"]["id"])
        assert hwb["status"] == "TENDERED"
        assert hwb["weight_basis"] == "FINAL"
        assert_weight_equal(hwb["chargeable_weight_kg"], 150.0, "chargeable_weight_kg")
        # 4.00 x 150.0 = 600.00 freight; 75.00 fuel; 25.00 security; spot stays 0
        assert_money_equal(hwb["freight_amount"], 600.00, "freight_amount")
        assert_money_equal(hwb["fuel_surcharge_amount"], 75.00, "fuel_surcharge_amount")
        assert_money_equal(hwb["security_fee_amount"], 25.00, "security_fee_amount")
        assert_money_equal(hwb["spot_surcharge_amount"], 0.00, "spot_surcharge_amount")
        assert_money_equal(hwb["total_charge_amount"], 700.00, "total_charge_amount")

        booking = get_booking(ctx["booking"]["id"])
        assert_weight_equal(booking["consumed_weight_kg"], 150.0, "consumed_weight_kg")


class TestTenderWindowBuffer:
    def _setup_two_mawbs_ready(self):
        ctx = setup_lane()
        mawb2 = create_mawb(ctx["booking"]["id"], "180-22222222")
        open_mawb(mawb2["id"])
        hwb_a = create_hwb(ctx["shipper"]["id"], "HWB-A")
        clear_hwb(hwb_a["id"])
        consolidate_hwb(ctx["mawb"]["id"], hwb_a["id"])
        measure_hwb(hwb_a["id"], 0.60)
        hwb_b = create_hwb(
            ctx["shipper"]["id"], "HWB-B", pieces=1, gross_weight_kg=10.0,
            declared_volume_m3=0.05,
        )
        clear_hwb(hwb_b["id"])
        consolidate_hwb(mawb2["id"], hwb_b["id"])
        measure_hwb(hwb_b["id"], 0.05)
        return ctx, mawb2

    def test_tender_window_conflict_within_buffer(self, api, capacity_planner_headers):
        """PRD §3.6: "the requested window must respect a 30-minute buffer against
        every other `TENDERED` master waybill on the same booking — a conflict exists
        exactly when the new window's start falls before an existing window's end plus
        30 minutes and the new window's end falls after that existing window's start
        minus 30 minutes — with conflicts rejected as `ERR_TENDER_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/tender_window_buffer_gap
        """
        ctx, mawb2 = self._setup_two_mawbs_ready()
        first = tender_mawb(ctx["mawb"]["id"], "2026-08-09T10:00:00Z", "2026-08-09T11:00:00Z")
        assert first["status"] == "TENDERED"

        # 11:00 start < 11:00 + 30min: touching the existing window is NOT enough
        resp = api.tender_master_waybill(
            mawb2["id"],
            tender_payload("2026-08-09T11:00:00Z", "2026-08-09T12:00:00Z"),
            capacity_planner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TENDER_WINDOW_CONFLICT)
        assert get_mawb(mawb2["id"])["status"] == "OPEN_FOR_CONSOLIDATION"

    def test_tender_window_exactly_30_min_gap_allowed(self, api):
        """PRD §3.6: "a conflict exists exactly when the new window's start falls
        before an existing window's end plus 30 minutes and the new window's end falls
        after that existing window's start minus 30 minutes — with conflicts rejected
        as `ERR_TENDER_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/tender_window_buffer_gap
        """
        ctx, mawb2 = self._setup_two_mawbs_ready()
        tender_mawb(ctx["mawb"]["id"], "2026-08-09T10:00:00Z", "2026-08-09T11:00:00Z")

        # 11:30 start == 11:00 + 30min: "falls before" is false at exactly the gap
        second = tender_mawb(mawb2["id"], "2026-08-09T11:30:00Z", "2026-08-09T12:30:00Z")
        assert second["status"] == "TENDERED"


class TestMilestoneRankRule:
    def test_out_of_order_milestone_recorded_without_transition(
        self, api, forwarder_ops_headers
    ):
        """PRD §3.6: "An event whose rank is not exactly the current rank plus one is
        still recorded — with `out_of_order` set to true — but causes no transition"

        Design: Corner/state_machines/out_of_order_milestone_recorded_without_transition
        """
        ctx = setup_tendered()

        skip_ahead = validate_success(
            api.record_milestone_event(
                ctx["mawb"]["id"],
                {"event_code": "DELIVERED", "event_time_utc": DELIVERED_UTC},
                forwarder_ops_headers,
            ),
            expected_status=201,
        )
        assert skip_ahead["out_of_order"] is True, (
            "DELIVERED (rank 3) while TENDERED (rank 0) is out of order"
        )
        assert get_mawb(ctx["mawb"]["id"])["status"] == "TENDERED"

        in_order = validate_success(
            api.record_milestone_event(
                ctx["mawb"]["id"],
                {"event_code": "DEPARTED", "event_time_utc": "2026-08-10T10:00:00Z"},
                forwarder_ops_headers,
            ),
            expected_status=201,
        )
        assert in_order["out_of_order"] is False
        assert get_mawb(ctx["mawb"]["id"])["status"] == "IN_TRANSIT"
        assert get_hwb(ctx["hwb"]["id"])["status"] == "IN_TRANSIT"

        repeat = validate_success(
            api.record_milestone_event(
                ctx["mawb"]["id"],
                {"event_code": "DEPARTED", "event_time_utc": "2026-08-10T10:05:00Z"},
                forwarder_ops_headers,
            ),
            expected_status=201,
        )
        assert repeat["out_of_order"] is True, (
            "a second DEPARTED repeats rank 1 while the waybill sits at rank 1"
        )
        assert get_mawb(ctx["mawb"]["id"])["status"] == "IN_TRANSIT"

        events, meta = validate_paginated(
            api.list_milestone_events(ctx["mawb"]["id"], forwarder_ops_headers)
        )
        assert meta["total_count"] == 3
        assert [e["out_of_order"] for e in events] == [True, False, True]

    def test_exception_milestone_requires_exception_code(
        self, api, forwarder_ops_headers
    ):
        """PRD §3.6: "The exception code is required to be non-`NONE` exactly when the
        event code is `EXCEPTION` and must be `NONE` for every other code; a mismatch
        is `ERR_INVALID_REQUEST`."
        PRD §3.6: "`EXCEPTION` events never transition anything."

        Design: Corner/state_machines/exception_milestone_requires_exception_code
        """
        ctx = setup_tendered()

        missing = api.record_milestone_event(
            ctx["mawb"]["id"],
            {"event_code": "EXCEPTION", "event_time_utc": "2026-08-09T14:00:00Z"},
            forwarder_ops_headers,
        )
        validate_error(missing, ApiErrorId.ERR_INVALID_REQUEST)

        misplaced = api.record_milestone_event(
            ctx["mawb"]["id"],
            {
                "event_code": "DEPARTED",
                "event_time_utc": "2026-08-10T10:00:00Z",
                "exception_code": "DAMAGE",
            },
            forwarder_ops_headers,
        )
        validate_error(misplaced, ApiErrorId.ERR_INVALID_REQUEST)

        recorded = validate_success(
            api.record_milestone_event(
                ctx["mawb"]["id"],
                {
                    "event_code": "EXCEPTION",
                    "event_time_utc": "2026-08-09T14:00:00Z",
                    "exception_code": "CUSTOMS_HOLD",
                    "note": "held at export",
                },
                forwarder_ops_headers,
            ),
            expected_status=201,
        )
        assert_milestone_event(recorded)
        assert recorded["exception_code"] == "CUSTOMS_HOLD"
        assert get_mawb(ctx["mawb"]["id"])["status"] == "TENDERED", (
            "an EXCEPTION event must not transition the master waybill"
        )


class TestMilestoneEventShape:
    def test_milestone_event_immutable_no_common_version_fields(
        self, api, forwarder_ops_headers
    ):
        """PRD §2.4: "The milestone event is the deliberate exception: it is an
        append-only audit entry and carries only `id` and `created_at`. Both
        `updated_at` and `version` are absent from milestone events — a recorded
        milestone is never modified, so there is nothing to version."

        Design: Corner/entities/milestone_event_immutable_no_common_version_fields
        """
        ctx = setup_tendered()
        event = validate_success(
            api.record_milestone_event(
                ctx["mawb"]["id"],
                {"event_code": "DEPARTED", "event_time_utc": "2026-08-10T10:00:00Z"},
                forwarder_ops_headers,
            ),
            expected_status=201,
        )
        assert_milestone_event(event)

        events, meta = validate_paginated(
            api.list_milestone_events(ctx["mawb"]["id"], forwarder_ops_headers)
        )
        assert meta["total_count"] == 1
        assert events[0]["out_of_order"] is False
        assert_milestone_event(events[0])


class TestTerminalLockdown:
    def test_milestone_on_closed_mawb_returns_invalid_state(
        self, api, forwarder_ops_headers, capacity_planner_headers
    ):
        """PRD §3.6: "Recording milestones against a `CLOSED` or `VOID` master waybill
        is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/milestone_on_closed_mawb_returns_invalid_state
        """
        ctx = setup_tendered()
        for code, ts in (
            ("DEPARTED", "2026-08-10T10:00:00Z"),
            ("ARRIVED", "2026-08-10T22:00:00Z"),
            ("DELIVERED", DELIVERED_UTC),
        ):
            record_milestone(ctx["mawb"]["id"], code, ts)

        closed = validate_success(api.close_master_waybill(ctx["mawb"]["id"], capacity_planner_headers))
        assert closed["status"] == "CLOSED"

        resp = api.record_milestone_event(
            ctx["mawb"]["id"],
            {"event_code": "ARRIVED", "event_time_utc": "2026-08-10T23:00:00Z"},
            forwarder_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        _events, meta = validate_paginated(
            api.list_milestone_events(ctx["mawb"]["id"], forwarder_ops_headers)
        )
        assert meta["total_count"] == 3, "the rejected event must not be recorded"


class TestBookingAutoDeparture:
    def test_booking_auto_departs_when_all_mawbs_departed(self, api):
        """PRD §3.2: "The bubble-up to `DEPARTED` fires only from `CUTOFF_CLOSED` and
        only when two counts both hold: at least one master waybill of the booking is
        in `IN_TRANSIT`, `ARRIVED`, `DELIVERED`, or `CLOSED`, and no master waybill of
        the booking remains in `DRAFT`, `OPEN_FOR_CONSOLIDATION`, or `TENDERED`."

        Design: Corner/state_machines/booking_auto_departs_when_all_mawbs_departed
        """
        ctx = setup_tendered()
        set_clock("2026-08-09T10:00:00Z")  # exactly the cutoff: booking CUTOFF_CLOSED
        assert get_booking(ctx["booking"]["id"])["status"] == "CUTOFF_CLOSED"

        record_milestone(ctx["mawb"]["id"], "DEPARTED", "2026-08-10T10:00:00Z")
        assert get_mawb(ctx["mawb"]["id"])["status"] == "IN_TRANSIT"
        assert get_booking(ctx["booking"]["id"])["status"] == "DEPARTED", (
            "with the only non-VOID master waybill in IN_TRANSIT and none left in an "
            "assembly state, the booking bubble-up fires with no direct booking call"
        )
