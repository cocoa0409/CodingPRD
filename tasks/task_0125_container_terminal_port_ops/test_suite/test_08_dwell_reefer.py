"""Dwell time and reefer monitoring: the seconds-to-hours rounding order, the
in-yard clock fallback, the strict excursion band, and the summary aggregation.

Difficulty instances: combinatorial_formula (dwell rounding order),
dual_variant_calc (reefer excursion domain), boundary_precision_check (strict
excursion band). Corner instances: dwell-in-yard uses clock, reefer summary
empty readings zero.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["terminal_admin_headers"]
YARD = TEST_USERS["yard_planner_headers"]
GATE = TEST_USERS["gate_operator_headers"]
REEFER = TEST_USERS["reefer_technician_headers"]


# --------------------------------------------------------------------------- #
# Dwell time rounding order — combinatorial_formula
# --------------------------------------------------------------------------- #
def test_dwell_gate_in_to_gate_out_60_5_hours(api):
    """PRD §3.7: "The dwell is the difference between end and start expressed in
    hours — the total elapsed seconds divided by three thousand six hundred —
    rounded to two decimal places using round-half-up."

    Design: Difficulty/combinatorial_formula/dwell_time_seconds_to_hours_rounding_order
    """
    # Ground (GATE_IN) at 2026-02-06T08:00, gate-out (GATE_OUT) at 2026-02-08T20:30
    # => 60.5 hours exactly.
    fx.set_clock("2026-02-01T00:00:00.000Z")
    berth = fx.provision_berth(code="B-4", length_m=400, draft_m=16.0)
    vessel = fx.provision_vessel(imo_number="1000004", name="Dwell Ship", loa_m=300, draft_m=14.0, free_time_days=30)
    window = fx.create_scheduled_window(berth["id"], vessel["id"], etd="2026-02-20T00:00:00.000Z")
    fx.berth_window(window)
    container = fx.declare_container(vessel["id"], window["id"], container_number="DWLL4000040")
    slot = fx.create_yard_slot(block="A4")
    fx.set_clock("2026-02-06T08:00:00.000Z")
    fx.ground_container(container["id"], slot["id"])
    fx.customs_clear(container["id"])
    fx.set_clock("2026-02-08T20:30:00.000Z")
    fx.gate_out_container(
        container["id"],
        window_start="2026-02-08T20:00:00.000Z",
        window_end="2026-02-08T21:00:00.000Z",
        check_in_clock="2026-02-08T20:30:00.000Z",
    )
    data = validate_success(api.get_dwell(container["id"], GATE), 200)
    assert data["dwell_hours"] == 60.5


def test_dwell_in_yard_uses_clock_when_no_gate_out(api):
    """PRD §3.7: "The end of the interval is the `recorded_at` of the outbound
    receipt (direction `GATE_OUT`) if one exists; otherwise, for a container still
    in the yard, the end is the current clock instant."

    Design: Difficulty/combinatorial_formula/dwell_time_seconds_to_hours_rounding_order
    """
    fx.set_clock("2026-02-01T00:00:00.000Z")
    berth = fx.provision_berth(code="B-460", length_m=300, draft_m=14.0)
    vessel = fx.provision_vessel(imo_number="2000260", name="Dwl V", loa_m=280, draft_m=13.0, free_time_days=60)
    window = fx.create_scheduled_window(berth["id"], vessel["id"])
    fx.berth_window(window)
    container = fx.declare_container(vessel["id"], window["id"], container_number="DWLN460460")
    slot = fx.create_yard_slot(block="P")
    fx.set_clock("2026-02-06T08:00:00.000Z")
    fx.ground_container(container["id"], slot["id"])
    fx.set_clock("2026-02-06T18:30:00.000Z")  # 10.5 hours later, still in yard
    data = validate_success(api.get_dwell(container["id"], YARD), 200)
    assert data["dwell_hours"] == 10.5


def test_dwell_in_yard_uses_clock_when_no_gate_out_corner(api):
    """PRD §3.7: "otherwise, for a container still in the yard, the end is the
    current clock instant. The dwell is the difference between end and start
    expressed in hours ... rounded to two decimal places using round-half-up."

    Design: Corner/calculations/dwell_in_yard_uses_clock_when_no_gate_out
    """
    fx.set_clock("2026-02-01T00:00:00.000Z")
    berth = fx.provision_berth(code="B-460c", length_m=300, draft_m=14.0)
    vessel = fx.provision_vessel(imo_number="2000269", name="Dwl Vc", loa_m=280, draft_m=13.0, free_time_days=60)
    window = fx.create_scheduled_window(berth["id"], vessel["id"])
    fx.berth_window(window)
    container = fx.declare_container(vessel["id"], window["id"], container_number="DWLN460469")
    slot = fx.create_yard_slot(block="Pc")
    fx.set_clock("2026-02-06T08:00:00.000Z")
    fx.ground_container(container["id"], slot["id"])
    fx.set_clock("2026-02-06T18:30:00.000Z")
    data = validate_success(api.get_dwell(container["id"], YARD), 200)
    assert data["dwell_hours"] == 10.5


# --------------------------------------------------------------------------- #
# Reefer excursion — dual_variant_calc / boundary
# --------------------------------------------------------------------------- #
def test_reefer_summary_counts_excursions_and_max_deviation(api):
    """PRD §3.8: "It reports an `excursion_count` — the number of readings whose
    `is_excursion` is true — and a `max_deviation_c`, the largest absolute deviation
    between any reading's `temperature_c` and the container's `setpoint_c`".
    PRD §3.8: "flags the reading as an excursion when that deviation **strictly
    exceeds** an allowed band of 2.0 degrees Celsius."

    Design: Difficulty/dual_variant_calc/reefer_excursion_threshold_vs_demurrage_domain
    """
    container = fx.setup_reefer_container(setpoint_c=-18.0)
    fx.record_reading(container["id"], "2026-02-01T01:00:00.000Z", -15.5)  # dev 2.5 -> excursion
    fx.record_reading(container["id"], "2026-02-01T02:00:00.000Z", -16.0)  # dev 2.0 -> not
    fx.record_reading(container["id"], "2026-02-01T03:00:00.000Z", -20.5)  # dev 2.5 -> excursion
    data = validate_success(api.get_reefer_summary(container["id"], REEFER), 200)
    assert data["excursion_count"] == 2
    assert data["max_deviation_c"] == 2.5


def test_reefer_reading_excursion_flag_set_at_record_time(api):
    """PRD §3.8: "At record time the system computes the reading's `is_excursion`
    flag: it takes the absolute deviation between the measured `temperature_c` and
    the container's required `setpoint_c`, and flags the reading as an excursion
    when that deviation **strictly exceeds** an allowed band of 2.0 degrees Celsius."

    Design: Difficulty/dual_variant_calc/reefer_excursion_threshold_vs_demurrage_domain
    """
    container = fx.setup_reefer_container(setpoint_c=-18.0)
    data = validate_success(
        api.record_reefer_reading(
            container["id"], {"recorded_at": "2026-02-01T01:00:00.000Z", "temperature_c": -15.5}, REEFER
        ),
        201,
    )
    assert data["is_excursion"] is True


def test_reefer_excursion_strict_band_boundary_not_excursion(api):
    """PRD §3.8: "The boundary is strict: a deviation exactly equal to 2.0 degrees
    is **not** an excursion."

    Design: Difficulty/boundary_precision_check/reefer_excursion_strict_band_boundary
    """
    container = fx.setup_reefer_container(setpoint_c=-18.0)
    data = validate_success(
        api.record_reefer_reading(
            container["id"], {"recorded_at": "2026-02-01T01:00:00.000Z", "temperature_c": -16.0}, REEFER
        ),
        201,
    )
    # |-16.0 - (-18.0)| == 2.0 exactly -> not an excursion.
    assert data["is_excursion"] is False


def test_reefer_excursion_just_past_band_is_excursion(api):
    """PRD §3.8: "flags the reading as an excursion when that deviation **strictly
    exceeds** an allowed band of 2.0 degrees Celsius."

    Design: Difficulty/boundary_precision_check/reefer_excursion_strict_band_boundary
    """
    container = fx.setup_reefer_container(setpoint_c=-18.0)
    data = validate_success(
        api.record_reefer_reading(
            container["id"], {"recorded_at": "2026-02-01T01:00:00.000Z", "temperature_c": -15.9}, REEFER
        ),
        201,
    )
    # |-15.9 - (-18.0)| == 2.1 > 2.0 -> excursion.
    assert data["is_excursion"] is True


def test_reefer_summary_empty_readings_zero(api):
    """PRD §3.8: "a `max_deviation_c`, the largest absolute deviation ... or 0.0
    when the container has no readings at all."

    Design: Corner/calculations/reefer_summary_empty_readings_zero
    """
    container = fx.setup_reefer_container(setpoint_c=-18.0)
    data = validate_success(api.get_reefer_summary(container["id"], REEFER), 200)
    assert data["excursion_count"] == 0
    assert data["max_deviation_c"] == 0.0
