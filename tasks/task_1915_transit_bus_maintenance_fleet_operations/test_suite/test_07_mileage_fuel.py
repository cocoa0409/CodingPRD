"""Mileage/fuel logs: monotonicity, future-date guard, MPG anomaly boundary,
and void compensation."""
from test_helpers import (
    ApiErrorId,
    assert_defect_report,
    assert_mileage_fuel_log,
    create_mileage_log_payload,
    get_success_data,
    new_bus,
    post_log,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


def test_odometer_regression_rejected(api):
    """PRD §3.7: "Odometer monotonicity is enforced: the new `odometer_end`
    must be strictly greater than the bus's current `odometer_miles`,
    otherwise the post is rejected with `ERR_ODOMETER_REGRESSION`."

    Design: Corner/validations/odometer_regression_rejected
    """
    bus = new_bus(fleet_number="Y9", vin="VINY9", model_year=2021,
                  initial_odometer_miles=500)
    res = api.create_mileage_fuel_log(
        create_mileage_log_payload(bus["id"], log_date="2026-08-01",
                                   odometer_end=500, fuel_gallons=40),
        fx.OP,
    )
    validate_error(res, ApiErrorId.ERR_ODOMETER_REGRESSION)
    after = get_success_data(api.get_bus(bus["id"], fx.FM))
    assert after["odometer_miles"] == 500, "a rejected post must not move the odometer"


def test_log_date_in_future_rejected(api):
    """PRD §3.7: "An `Operator` submits the log with the `bus_id`, the service
    `log_date` (an ISO date, which must not be after the logical clock date —
    otherwise `ERR_LOG_DATE_IN_FUTURE`), the end-of-day `odometer_end`, and the
    whole-gallon `fuel_gallons` dispensed (which must be strictly greater than
    zero)."
    PRD §2.5: "At server startup, the logical clock reads exactly
    `2026-08-01T00:00:00Z`; it never falls back to wall-clock time."

    Design: Corner/validations/log_date_in_future_rejected
    """
    bus = new_bus(fleet_number="Y10", vin="VINY10", model_year=2021,
                  initial_odometer_miles=100)
    res = api.create_mileage_fuel_log(
        create_mileage_log_payload(bus["id"], log_date="2026-08-02",
                                   odometer_end=900, fuel_gallons=40),
        fx.OP,
    )
    validate_error(res, ApiErrorId.ERR_LOG_DATE_IN_FUTURE)


class TestFuelMpgAnomaly:
    """Integer cross-multiplied anomaly boundary at exactly 85% of baseline."""

    def _setup_baseline(self, fleet_number, vin):
        """Three logs of 600 mi / 50 gal each: aggregate baseline 12 mpg."""
        bus = new_bus(fleet_number=fleet_number, vin=vin, model_year=2023,
                      initial_odometer_miles=0)
        post_log(bus["id"], "2026-07-26", 600, 50)
        post_log(bus["id"], "2026-07-27", 1_200, 50)
        post_log(bus["id"], "2026-07-28", 1_800, 50)
        return bus

    def test_exactly_85_percent_not_flagged_then_below_flagged(self, api):
        """PRD §3.7: "The comparison is performed in integer cross-multiplied
        form to avoid floating-point drift: an anomaly fires when the new log's
        `miles_driven` multiplied by the baseline's total `fuel_gallons`
        multiplied by 100 is strictly less than 85 multiplied by the baseline's
        total `miles_driven` multiplied by the new log's `fuel_gallons`.
        Equality at exactly 85 percent is not an anomaly. On an anomaly the log
        transitions from `POSTED` to `FLAGGED`, and the system auto-creates a
        `DefectReport` for the bus with `severity` `MAJOR`, `defect_code`
        `FUEL_SYSTEM`, `odometer_at_report` set to the log's `odometer_end`,
        `flagged_by_log_id` pointing at the new log, and `status` `OPEN`."

        L4: 510*150*100 == 85*1800*50 (exactly 85%) -> POSTED.
        L5 baseline slides to L2..L4: 480*150*100 < 85*1710*50 -> FLAGGED.

        Design: Corner/calculations/fuel_mpg_anomaly_exact_85_percent_not_flagged_then_flagged
        """
        bus = self._setup_baseline("F1", "VINF1")

        log4 = post_log(bus["id"], "2026-07-29", 2_310, 50)
        assert_mileage_fuel_log(log4)
        assert log4["status"] == "POSTED", "exactly 85% of baseline is not an anomaly"
        assert log4["miles_driven"] == 510

        log5 = post_log(bus["id"], "2026-07-30", 2_790, 50)
        assert log5["status"] == "FLAGGED", (
            "9.6 mpg is below 85% of the sliding 11.4 mpg baseline"
        )
        defects = get_success_data(api.list_log_defect_reports(log5["id"], fx.FM))
        assert len(defects) == 1, "exactly one auto defect for the flagged log"
        defect = defects[0]
        assert_defect_report(defect)
        assert defect["severity"] == "MAJOR"
        assert defect["defect_code"] == "FUEL_SYSTEM"
        assert defect["status"] == "OPEN"
        assert defect["flagged_by_log_id"] == log5["id"]
        assert defect["odometer_at_report"] == 2_790

    def test_flagged_log_void_recomputes_odometer_and_withdraws_defect(self, api):
        """PRD §3.7: "On a successful void the log moves to `VOIDED`; the
        bus's `odometer_miles` is recomputed as the maximum `odometer_end` over
        the remaining non-voided logs, or `initial_odometer_miles` if none
        remain; `pm_due_status` is recomputed; and any auto-created defect
        still in `OPEN` status (one whose `flagged_by_log_id` is this log) is
        automatically withdrawn with `resolution` `AUTO_VOIDED`."

        Design: Corner/calculations/flagged_log_void_recomputes_odometer_and_withdraws_defect
        """
        bus = self._setup_baseline("F2", "VINF2")
        post_log(bus["id"], "2026-07-29", 2_310, 50)
        log5 = post_log(bus["id"], "2026-07-30", 2_790, 50)
        assert log5["status"] == "FLAGGED"
        defect = get_success_data(api.list_log_defect_reports(log5["id"], fx.FM))[0]

        voided = validate_success(
            api.void_mileage_fuel_log(log5["id"],
                                      {"void_reason": "faulty pump meter"}, fx.FM)
        )
        assert voided["status"] == "VOIDED"

        bus_after = get_success_data(api.get_bus(bus["id"], fx.FM))
        assert bus_after["odometer_miles"] == 2_310, (
            "odometer recomputes to the max odometer_end over remaining logs"
        )
        defect_after = get_success_data(api.get_defect_report(defect["id"], fx.FM))
        assert defect_after["status"] == "WITHDRAWN"
        assert defect_after["resolution"] == "AUTO_VOIDED"


def test_void_non_latest_log_rejected(api):
    """PRD §3.7: "Logs may be voided as a compensating action, but only the
    latest one: a `FleetManager` may void a log only when it is the bus's most
    recent non-voided log ordered by `log_date` descending with ties broken by
    `created_at` descending, otherwise the void is rejected with
    `ERR_LOG_NOT_LATEST`."

    Design: Corner/validations/void_non_latest_log_rejected
    """
    bus = new_bus(fleet_number="Y36", vin="VINY36", model_year=2023,
                  initial_odometer_miles=0)
    log1 = post_log(bus["id"], "2026-07-30", 600, 50)
    log2 = post_log(bus["id"], "2026-07-31", 1_200, 50)

    res = api.void_mileage_fuel_log(log1["id"], {"void_reason": "out of order"}, fx.FM)
    validate_error(res, ApiErrorId.ERR_LOG_NOT_LATEST)

    voided = validate_success(
        api.void_mileage_fuel_log(log2["id"], {"void_reason": "bad entry"}, fx.FM)
    )
    assert voided["status"] == "VOIDED"
    bus_after = get_success_data(api.get_bus(bus["id"], fx.FM))
    assert bus_after["odometer_miles"] == 600, (
        "after voiding the latest log, odometer recomputes to L1's odometer_end"
    )
