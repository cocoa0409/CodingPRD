"""Inspection-fee calculation and the state remittance surcharge.

Covers Difficulty queue: dual_variant_calc (full vs free first-reinspection fee),
combinatorial_formula (three-input nonlinear fee branching; round-per-line-then-sum
surcharge).
"""
import pytest

from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
)
from test_helpers import fixtures as F

SM = TEST_USERS["station_manager_headers"]
INSP = TEST_USERS["inspector_headers"]
RECEP = TEST_USERS["receptionist_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc — full original fee vs free first reinspection
# ===========================================================================
def test_full_first_inspection_fee_is_3700(api):
    """PRD §3.6: "Concretely, an original inspection (`reinspection_index` of 0) or a
    reinspection that is outside its window or whose index is not exactly 1 pays the
    full service subtotal plus the 200-cent fee, while a qualifying first
    reinspection pays only the 200-cent environmental fee."

    Design: Difficulty/dual_variant_calc/inspection_fee_full_vs_free_first_reinspection
    """
    # Original PASSENGER+OBD record that FAILS on safety: full fee = 2500+1000+200.
    station, profile, lane, appt, failed = F.setup_safety_failed_record(
        api, clock_iso="2026-06-10T09:00:00Z")
    assert failed["status"] == "FAILED"
    assert failed["reinspection_index"] == 0
    assert failed["fee_cents"] == 3700, \
        f"full PASSENGER+OBD fee must be 3700, got {failed['fee_cents']}"


def test_free_first_reinspection_within_window_pays_only_env_fee(api):
    """PRD §3.6: "The first reinspection within its window is granted free service:
    the relief applies precisely when the record's `reinspection_index` equals 1 and
    the elapsed time from the chain head's `created_at` to the decision instant on the
    logical clock is no greater than the profile's `reinspection_window_days`
    converted to seconds"
    PRD §3.6: "When that condition holds the service subtotal is forced to zero. A
    flat state environmental fee of two dollars (200 cents) is always added afterward
    regardless of relief."

    Design: Difficulty/dual_variant_calc/inspection_fee_full_vs_free_first_reinspection
    """
    station, profile, lane = F.setup_station_with_passenger_obd(
        api, clock_iso="2026-06-10T09:00:00Z")
    # Original record FAILS on safety.
    appt1 = F.book_and_check_in(api, lane["id"],
                                scheduled_start="2026-06-10T09:00:00Z",
                                scheduled_end="2026-06-10T09:30:00Z")
    rec1 = F.open_record(api, appt1["id"])
    F.add_checklist(api, rec1["id"], item_code="BRAKES", outcome="FAIL", severity="MAJOR")
    F.add_checklist(api, rec1["id"], item_code="LIGHTS", outcome="PASS")
    F.add_emissions(api, rec1["id"], mil_on=False, dtc_count=0)
    rec1 = F.decide_record(api, rec1["id"])
    assert rec1["fee_cents"] == 3700

    # First reinspection, same day (within 30-day window), PASSES.
    appt2 = F.add_reinspection_appointment(
        api, lane["id"], "2026-06-10T10:00:00Z", "2026-06-10T10:30:00Z")
    rec2 = F.reinspect(api, rec1["id"], appt2["id"])
    F.add_checklist(api, rec2["id"], item_code="BRAKES", outcome="PASS")
    F.add_checklist(api, rec2["id"], item_code="LIGHTS", outcome="PASS")
    F.add_emissions(api, rec2["id"], mil_on=False, dtc_count=0)
    rec2 = F.decide_record(api, rec2["id"])
    assert rec2["reinspection_index"] == 1
    assert rec2["status"] == "PASSED"
    assert rec2["fee_cents"] == 200, \
        f"free first reinspection must charge only the 200-cent env fee, got {rec2['fee_cents']}"


# ===========================================================================
# Difficulty: combinatorial_formula — three-input nonlinear fee branching
# ===========================================================================
def test_motorcycle_no_obd_passed_fee_is_1700(api):
    """PRD §3.6: "To the base it adds an emissions surcharge: when the class requires
    OBD the surcharge is ten dollars (1000 cents), and when it does not the surcharge
    is zero."
    PRD §3.5: "for a class whose `obd_required` is false, the `emissions_result` is
    `NOT_APPLICABLE`."

    Design: Difficulty/combinatorial_formula/inspection_fee_three_input_nonlinear_branching
    """
    station, profile, lane = F.setup_station_with_motorcycle_no_obd(
        api, clock_iso="2026-06-10T09:00:00Z", base_fee_cents=1500, checklist_item_count=1)
    appt = F.book_and_check_in(api, lane["id"], vehicle_vin="JH2SC82A4MM100001",
                               vehicle_class="MOTORCYCLE",
                               scheduled_end="2026-06-10T09:20:00Z")
    record = F.open_record(api, appt["id"])
    F.add_checklist(api, record["id"], item_code="BRAKES", outcome="PASS")
    decided = validate_success(api.decide_inspection_record(record["id"], INSP), 200)
    assert decided["emissions_result"] == "NOT_APPLICABLE"
    assert decided["status"] == "PASSED"
    assert decided["fee_cents"] == 1700, \
        f"MOTORCYCLE (no OBD) fee must be 1500+0+200=1700, got {decided['fee_cents']}"


def test_obd_required_branch_adds_emissions_surcharge(api):
    """PRD §3.6: "To the base it adds an emissions surcharge: when the class requires
    OBD the surcharge is ten dollars (1000 cents), and when it does not the surcharge
    is zero. The base plus the emissions surcharge forms the service subtotal."

    Design: Difficulty/combinatorial_formula/inspection_fee_three_input_nonlinear_branching
    """
    # PASSENGER (base 2500) with obd_required=true: 2500 + 1000 + 200 = 3700, the
    # OBD-true branch of the same three-input formula the motorcycle case takes false.
    station, profile, lane, appt, passed = F.setup_passed_passenger_record(
        api, clock_iso="2026-06-10T09:00:00Z")
    assert passed["status"] == "PASSED"
    assert passed["reinspection_index"] == 0
    assert passed["fee_cents"] == 3700, \
        f"PASSENGER+OBD (base 2500 + 1000 surcharge + 200 env) must be 3700, got {passed['fee_cents']}"


# ===========================================================================
# Difficulty: combinatorial_formula — state surcharge round-per-line-then-sum
# ===========================================================================
def test_state_surcharge_per_record_rounds_half_up(api):
    """PRD §3.12: "The service portion of a single fee is the line or record's
    `fee_cents` less the flat 200-cent state environmental fee, floored at zero so it
    never goes negative. That service portion is multiplied by the state remittance
    rate of 7.5 percent (0.075), and the product is rounded half-up to whole cents to
    give that line's surcharge."

    Design: Difficulty/combinatorial_formula/state_surcharge_round_per_line_then_sum
    """
    # PASSENGER+OBD PASSED record, fee 3700 => service portion 3500;
    # 3500 * 0.075 = 262.5 => round-half-up => 263.
    station, profile, lane, appt, passed = F.setup_passed_passenger_record(
        api, clock_iso="2026-06-10T09:00:00Z")
    assert passed["fee_cents"] == 3700
    data = validate_success(api.get_state_surcharge(passed["id"], SM), 200)
    assert data["service_portion_cents"] == 3500, \
        f"service portion must be 3700-200=3500, got {data['service_portion_cents']}"
    assert data["state_surcharge_cents"] == 263, \
        f"3500*0.075=262.5 rounds half-up to 263, got {data['state_surcharge_cents']}"


def test_state_surcharge_per_record_floors_service_at_zero_basis(api):
    """PRD §3.12: "The service portion of a single fee is the line or record's
    `fee_cents` less the flat 200-cent state environmental fee, floored at zero so it
    never goes negative. That service portion is multiplied by the state remittance
    rate of 7.5 percent (0.075), and the product is rounded half-up to whole cents to
    give that line's surcharge."

    Design: Difficulty/combinatorial_formula/state_surcharge_round_per_line_then_sum
    """
    # MOTORCYCLE (no OBD) PASSED record, fee 1700 => service 1500;
    # 1500 * 0.075 = 112.5 => round-half-up => 113 (a distinct per-line rounding case).
    station, profile, lane = F.setup_station_with_motorcycle_no_obd(
        api, clock_iso="2026-06-10T09:00:00Z", base_fee_cents=1500, checklist_item_count=1)
    appt = F.book_and_check_in(api, lane["id"], vehicle_vin="JH2SC82A4MM100001",
                               vehicle_class="MOTORCYCLE",
                               scheduled_end="2026-06-10T09:20:00Z")
    record = F.open_record(api, appt["id"])
    F.add_checklist(api, record["id"], item_code="BRAKES", outcome="PASS")
    passed = F.decide_record(api, record["id"])
    assert passed["fee_cents"] == 1700
    data = validate_success(api.get_state_surcharge(passed["id"], SM), 200)
    assert data["service_portion_cents"] == 1500, \
        f"service portion must be 1700-200=1500, got {data['service_portion_cents']}"
    assert data["state_surcharge_cents"] == 113, \
        f"1500*0.075=112.5 rounds half-up to 113, got {data['state_surcharge_cents']}"
