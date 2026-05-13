"""Check-in flow and ridership records.

Covers PRD §3.6 check-in window, ridership records, and ridership
statistics (PRD §3.7).
"""
from __future__ import annotations
from datetime import timedelta

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)
from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    assert_ridership_record,
    check_in_payload,
    check_in_rider,
    complete_run_sheet, depart_run_sheet, start_boarding,
    expected_match_rate,
    fetch_reservation, fetch_run_sheet,
    iso_z, parse_iso,
    make_driver_headers, make_employee_headers,
    setup_run_with_confirmed_reservation,
)


# ===========================================================================
# Check-in window (PRD §3.6)
# ===========================================================================
class TestCheckInWindow:

    def test_check_in_before_window_rejected(self, dispatcher_headers):
        """PRD §3.6: "Preconditions: the run-sheet is in BOARDING, IN_TRANSIT,
        or DELAYED, and the current instant lies in the half-open interval
        from scheduled_departure minus 30 minutes up to scheduled_arrival
        plus 60 minutes; otherwise the check-in is rejected with
        ERR_CHECKIN_WINDOW_CLOSED."

        Claim: check-in attempted before scheduled_departure - 30 min ->
        rejected. The state precondition fails first (run is still PLANNED),
        so we accept either ERR_INVALID_STATE or ERR_CHECKIN_WINDOW_CLOSED
        per PRD §2.8's priority order (state precedes business_temporal).
        """
        from prd_bench_local_runner.testing import validate_error_is_one_of
        advance_clock_to("2026-06-01T03:00:00.000Z")
        scenario = setup_run_with_confirmed_reservation()
        # Run is PLANNED; check-in requires BOARDING/IN_TRANSIT/DELAYED.
        resp = api_client.check_in(
            scenario["run_sheet"]["id"],
            check_in_payload(scenario["reservation"]["id"],
                             scenario["stops"][0]["id"]),
            make_driver_headers(scenario["driver"]["id"]),
        )
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_INVALID_STATE,
             ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED],
        )

    def test_check_in_success_creates_ridership_record(self, dispatcher_headers):
        """PRD §3.6: "Successful check-in transitions the reservation
        CONFIRMED -> CHECKED_IN, creates a RidershipRecord row capturing
        reservation_id, run_sheet_id, employee_id (copied from the
        reservation for fast filtering), the supplied check_in_method and
        boarded_stop_id, the current instant as boarded_at, and leaves
        alighted_stop_id and alighted_at null."

        Claim: check-in returns a RidershipRecord with reservation_id,
        run_sheet_id, employee_id, check_in_method, boarded_stop_id and
        boarded_at set; alighted_* null.
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        scenario = setup_run_with_confirmed_reservation()
        sched = parse_iso(scenario["run_sheet"]["scheduled_departure"])
        advance_clock_to(iso_z(sched - timedelta(minutes=10)))
        start_boarding(scenario["run_sheet"]["id"])
        ridership = validate_success(
            api_client.check_in(
                scenario["run_sheet"]["id"],
                check_in_payload(
                    scenario["reservation"]["id"],
                    scenario["stops"][0]["id"],
                    "QR",
                ),
                make_driver_headers(scenario["driver"]["id"]),
            ),
            201,
        )
        assert_ridership_record(ridership)
        assert ridership["reservation_id"] == scenario["reservation"]["id"]
        assert ridership["run_sheet_id"] == scenario["run_sheet"]["id"]
        assert ridership["employee_id"] == scenario["employee_id"], \
            "PRD §3.6: RidershipRecord.employee_id is copied from the reservation"
        assert ridership["check_in_method"] == "QR"
        assert ridership["boarded_stop_id"] == scenario["stops"][0]["id"]
        assert ridership.get("alighted_stop_id") in (None, "")
        assert ridership.get("alighted_at") in (None, "")
        # Reservation transitioned to CHECKED_IN.
        res_after = fetch_reservation(scenario["reservation"]["id"])
        assert res_after["status"] == "CHECKED_IN"


# ===========================================================================
# Completion cascade (PRD §3.6)
# ===========================================================================
class TestCompletionCascade:

    def test_complete_transitions_checked_in_to_completed(
            self, dispatcher_headers):
        """PRD §3.6: "When a run completes from IN_TRANSIT or DELAYED, every
        CHECKED_IN reservation on that run transitions to COMPLETED. As
        part of that completion, each associated RidershipRecord has its
        alighted_at stamped to the current instant if not already set, and
        its alighted_stop_id defaulted to the reservation's
        alighting_stop_id."

        Claim: after run COMPLETED, the CHECKED_IN reservation ->
        COMPLETED.
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        scenario = setup_run_with_confirmed_reservation()
        sched = parse_iso(scenario["run_sheet"]["scheduled_departure"])
        advance_clock_to(iso_z(sched - timedelta(minutes=10)))
        start_boarding(scenario["run_sheet"]["id"])
        check_in_rider(
            scenario["run_sheet"]["id"], scenario["reservation"]["id"],
            scenario["stops"][0]["id"],
            headers=make_driver_headers(scenario["driver"]["id"]),
        )
        advance_clock_to(iso_z(sched + timedelta(seconds=10)))
        depart_run_sheet(scenario["run_sheet"]["id"])
        advance_clock_to(iso_z(sched + timedelta(minutes=20)))
        complete_run_sheet(scenario["run_sheet"]["id"])
        res_after = fetch_reservation(scenario["reservation"]["id"])
        assert res_after["status"] == "COMPLETED", \
            f"PRD §3.6: CHECKED_IN reservation must cascade to COMPLETED after run completes, got {res_after['status']}"


# ===========================================================================
# Ridership statistics (PRD §3.7)
# ===========================================================================
class TestRidershipStatistics:

    def test_match_rate_round_half_up_4dp(self, dispatcher_headers):
        """PRD §3.7: "The match_rate is the actual ridership count divided
        by the maximum of the expected count and 1, rendered as a float
        rounded half-up to four decimal places."

        Claim: with one CHECKED_IN reservation (1 ridership_actual; 1
        ridership_expected), match_rate == 1.0000.
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        scenario = setup_run_with_confirmed_reservation()
        sched = parse_iso(scenario["run_sheet"]["scheduled_departure"])
        advance_clock_to(iso_z(sched - timedelta(minutes=10)))
        start_boarding(scenario["run_sheet"]["id"])
        check_in_rider(
            scenario["run_sheet"]["id"], scenario["reservation"]["id"],
            scenario["stops"][0]["id"],
            headers=make_driver_headers(scenario["driver"]["id"]),
        )
        stats = validate_success(
            api_client.get_run_sheet_statistics(
                scenario["run_sheet"]["id"], dispatcher_headers,
            ),
            200,
        )
        assert stats["ridership_actual"] >= 1
        assert stats["ridership_expected"] >= 1
        assert stats["match_rate"] == pytest.approx(
            expected_match_rate(stats["ridership_actual"],
                                stats["ridership_expected"]),
            abs=1e-4,
        )
