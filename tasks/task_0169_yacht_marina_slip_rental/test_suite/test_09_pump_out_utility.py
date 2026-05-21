"""Pump-out service and utility settlement — PRD §3.6, §3.8.

Pump-out lifecycle: schedule (against CHECKED_IN reservation),
complete (with tank_gallons_drained > 0), or cancel.

Utility settlement runs only at CHECKED_OUT when liveaboard=true, sums
readings in [check_in_date, marina.current_date), and applies the
kWh+water+sewage formula with the SEWAGE flat only when water_gallons
> 0.

The pump-out → utility-reading cascade (PRD §3.6: "when a pump-out job
on a liveaboard reservation completes, the system appends a synthetic
utility reading ...") is also verified.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to_iso,
    add_utility_reading,
    api_client,
    cancel_pump_out_as_boater,
    check_out_reservation,
    complete_pump_out,
    create_pump_out_payload,
    get_marina,
    get_reservation,
    get_settlement,
    get_success_data,
    make_boater_headers,
    schedule_pump_out,
    setup_checked_in_reservation,
    setup_checked_out_reservation,
    setup_liveaboard_pump_out_chain,
    validate_error,
)


# ===========================================================================
# Pump-out schedule — PRD §3.8
# ===========================================================================
class TestPumpOutSchedule:

    def test_overlap_on_same_slip_rejected(
        self, api, dock_master_headers,
    ):
        """PRD §3.8: "Two pump-out jobs on the same slip whose windows
        — expressed as the open-start, closed-end form
        `(scheduled_start, scheduled_end]` — share any instant cannot
        both be scheduled; the second attempt is rejected with
        `ERR_PUMP_OUT_CONFLICT`."

        Claim: scheduling a second pump-out (10:30, 11:30] while
        (10:00, 11:00] exists → ERR_PUMP_OUT_CONFLICT."""
        scenario = setup_checked_in_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-05T00:00:00.000Z",
            liveaboard=True,
            slip_liveaboard_allowed=True,
            vessel_holding_tank_gallons=60,
            clock_after_approve="2024-05-01T09:00:00.000Z",
        )
        # First pump-out 10:00-11:00.
        schedule_pump_out(
            scenario["marina"]["id"], scenario["boater"],
            scenario["reservation"]["id"],
            scheduled_start="2024-05-01T10:00:00.000Z",
            scheduled_end="2024-05-01T11:00:00.000Z",
        )
        # Second pump-out 10:30-11:30 overlaps.
        h = make_boater_headers(scenario["boater"]["id"])
        payload = create_pump_out_payload(
            reservation_id=scenario["reservation"]["id"],
            scheduled_start="2024-05-01T10:30:00.000Z",
            scheduled_end="2024-05-01T11:30:00.000Z",
        )
        resp = api.create_pump_out_job(scenario["marina"]["id"], payload, h)
        validate_error(resp, ApiErrorId.ERR_PUMP_OUT_CONFLICT.value)

    def test_adjacent_pump_outs_allowed(self, api, dock_master_headers):
        """PRD §3.8: "Two pump-out jobs on the same slip whose windows
        — expressed as the open-start, closed-end form
        `(scheduled_start, scheduled_end]` — share any instant cannot
        both be scheduled..."

        Adjacent windows (10:00, 11:00] and (11:00, 12:00] do NOT
        overlap (11:00 is closed on first, open on second). Both must
        succeed."""
        scenario = setup_checked_in_reservation(
            check_in_date="2024-05-01T00:00:00.000Z",
            check_out_date="2024-05-05T00:00:00.000Z",
            liveaboard=True,
            slip_liveaboard_allowed=True,
            vessel_holding_tank_gallons=60,
            clock_after_approve="2024-05-01T09:00:00.000Z",
        )
        schedule_pump_out(
            scenario["marina"]["id"], scenario["boater"],
            scenario["reservation"]["id"],
            scheduled_start="2024-05-01T10:00:00.000Z",
            scheduled_end="2024-05-01T11:00:00.000Z",
        )
        adjacent = schedule_pump_out(
            scenario["marina"]["id"], scenario["boater"],
            scenario["reservation"]["id"],
            scheduled_start="2024-05-01T11:00:00.000Z",
            scheduled_end="2024-05-01T12:00:00.000Z",
        )
        assert adjacent["status"] == "SCHEDULED"


# ===========================================================================
# Pump-out complete — PRD §3.8 cascade to utility reading
# ===========================================================================
class TestPumpOutComplete:

    def test_complete_appends_synthetic_utility_reading_for_liveaboard(
        self, api, dock_master_headers,
    ):
        """PRD §3.6: "when a pump-out job on a liveaboard reservation
        completes, the system appends a synthetic utility reading at
        `read_at` equal to the job's `scheduled_end`, with
        `water_gallons_delta` equal to the job's `tank_gallons_drained`
        and `kwh_delta` equal to zero."

        Claim: completing the pump-out causes the settlement at
        check-out to include the drained gallons. The visible signal is
        UtilitySettlement.water_gallons_total."""
        scenario = setup_liveaboard_pump_out_chain(
            check_in_date="2024-02-01T00:00:00.000Z",
            check_out_date="2024-02-02T00:00:00.000Z",
            pump_out_start="2024-02-01T19:00:00.000Z",
            pump_out_end="2024-02-01T19:30:00.000Z",
            kwh_reading_at="2024-02-01T18:00:00.000Z",
            kwh_delta=100,
        )
        # Complete the pump-out.
        advance_clock_to_iso(
            scenario["marina"]["id"], "2024-02-01T19:30:00.000Z",
        )
        complete_pump_out(
            scenario["marina"]["id"], scenario["job"]["id"],
            tank_gallons_drained=50,
        )
        # Check-out the reservation; settlement runs.
        advance_clock_to_iso(
            scenario["marina"]["id"], "2024-02-02T12:00:00.000Z",
        )
        check_out_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
        )
        settlement = get_settlement(
            scenario["marina"]["id"], scenario["reservation"]["id"],
        )
        assert settlement["water_gallons_total"] == 50, (
            f"Expected water_gallons_total=50 (synthetic reading from "
            f"pump-out cascade), got "
            f"{settlement['water_gallons_total']!r}"
        )

    def test_complete_with_zero_tank_gallons_drained_rejected(
        self, api, dock_master_headers,
    ):
        """PRD §3.8: "A `DockMaster` completes a `SCHEDULED` job by
        supplying `tank_gallons_drained` (which must be strictly
        greater than zero)..."

        Claim: tank_gallons_drained=0 → rejected. PRD does not pin a
        specific error_id for this; the request is malformed/invalid so
        ERR_BAD_REQUEST is the only PRD-named candidate."""
        scenario = setup_liveaboard_pump_out_chain(
            check_in_date="2024-02-01T00:00:00.000Z",
            check_out_date="2024-02-03T00:00:00.000Z",
            pump_out_start="2024-02-01T19:00:00.000Z",
            pump_out_end="2024-02-01T19:30:00.000Z",
            kwh_reading_at="2024-02-01T18:00:00.000Z",
            kwh_delta=10,
        )
        advance_clock_to_iso(
            scenario["marina"]["id"], "2024-02-01T19:30:00.000Z",
        )
        from test_helpers import complete_pump_out_payload as _pl
        resp = api.complete_pump_out_job(
            scenario["marina"]["id"], scenario["job"]["id"],
            _pl(tank_gallons_drained=0), dock_master_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)


# ===========================================================================
# Utility settlement — PRD §3.6
# ===========================================================================
class TestUtilitySettlement:

    def test_liveaboard_settlement_with_water_includes_sewage_flat(
        self, api, dock_master_headers,
    ):
        """PRD §3.6: "If `water_gallons_total` is strictly greater than
        zero, a flat sewage charge of 2500 cents (twenty-five dollars)
        is added; otherwise the sewage charge is zero. The settlement's
        `total_cents` is the sum of the kilowatt-hour charge, the water
        charge, and the sewage charge."

        Setup: kwh_total=100, water_gallons_total=50:
          kwh_charge = 100*18 = 1800
          water_charge = 50*4 = 200
          sewage_charge = 2500 (water > 0)
          total = 1800 + 200 + 2500 = 4500.
        """
        scenario = setup_liveaboard_pump_out_chain(
            check_in_date="2024-02-01T00:00:00.000Z",
            check_out_date="2024-02-02T00:00:00.000Z",
            pump_out_start="2024-02-01T19:00:00.000Z",
            pump_out_end="2024-02-01T19:30:00.000Z",
            kwh_reading_at="2024-02-01T18:00:00.000Z",
            kwh_delta=100,
        )
        advance_clock_to_iso(
            scenario["marina"]["id"], "2024-02-01T19:30:00.000Z",
        )
        complete_pump_out(
            scenario["marina"]["id"], scenario["job"]["id"],
            tank_gallons_drained=50,
        )
        advance_clock_to_iso(
            scenario["marina"]["id"], "2024-02-02T12:00:00.000Z",
        )
        check_out_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
        )
        settlement = get_settlement(
            scenario["marina"]["id"], scenario["reservation"]["id"],
        )
        assert settlement["kwh_total"] == 100
        assert settlement["water_gallons_total"] == 50
        assert settlement["sewage_charge_cents"] == 2500
        assert settlement["total_cents"] == 4500, (
            f"Expected total_cents=4500 (1800+200+2500), got "
            f"{settlement['total_cents']!r}"
        )

    def test_liveaboard_settlement_without_water_no_sewage(
        self, api, dock_master_headers,
    ):
        """PRD §3.6: "If `water_gallons_total` is strictly greater than
        zero, a flat sewage charge of 2500 cents ... is added;
        otherwise the sewage charge is zero."

        Setup: kwh_total=100, water_gallons_total=0:
          total = 100*18 + 0 + 0 = 1800."""
        scenario = setup_checked_in_reservation(
            check_in_date="2024-02-01T00:00:00.000Z",
            check_out_date="2024-02-02T00:00:00.000Z",
            liveaboard=True,
            slip_liveaboard_allowed=True,
            vessel_holding_tank_gallons=60,
            clock_after_approve="2024-02-01T10:00:00.000Z",
        )
        # One kwh-only reading; no water.
        advance_clock_to_iso(
            scenario["marina"]["id"], "2024-02-01T18:00:00.000Z",
        )
        add_utility_reading(
            scenario["marina"]["id"], scenario["reservation"]["id"],
            read_at="2024-02-01T18:00:00.000Z",
            kwh_delta=100, water_gallons_delta=0,
        )
        advance_clock_to_iso(
            scenario["marina"]["id"], "2024-02-02T12:00:00.000Z",
        )
        check_out_reservation(
            scenario["marina"]["id"], scenario["reservation"]["id"],
        )
        settlement = get_settlement(
            scenario["marina"]["id"], scenario["reservation"]["id"],
        )
        assert settlement["sewage_charge_cents"] == 0, (
            f"Sewage must be 0 when water_gallons_total=0, got "
            f"{settlement['sewage_charge_cents']!r}"
        )
        assert settlement["total_cents"] == 1800, (
            f"Expected total_cents=1800 (only kwh charge), got "
            f"{settlement['total_cents']!r}"
        )
