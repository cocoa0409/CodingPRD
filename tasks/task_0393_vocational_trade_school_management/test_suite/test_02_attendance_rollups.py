"""Attendance state transitions and clock-hour rollup recomputation.

Covers corner queue B:
  - state_machines / excuse_attendance_keeps_denominator_drops_completed
  - state_machines / void_attendance_excludes_from_denominator
  - state_machines / externship_complete_bubbles_externship_hours_via_system_entry
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["system_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
ADVISOR = TEST_USERS["academic_advisor_headers"]


# --------------------------------------------------------------------------
# corner: excuse_attendance_keeps_denominator_drops_completed
# --------------------------------------------------------------------------
def test_excuse_keeps_scheduled_in_denominator_drops_completed(api):
    """PRD §3.4: "Excusing an entry moves it POSTED → EXCUSED: ... the side effect
    forces the row's attended_hours to 0 while the row stays in the attendance
    denominator, dropping the agreement's clock_hours_completed by the row's prior
    attended hours, recomputing the rollups, and incrementing the agreement's
    version."
    PRD §3.4: "scheduled_hours_to_date — the attendance denominator — is the sum
    of scheduled_hours over the agreement's rows whose status is POSTED or
    EXCUSED."

    Design: Corner/state_machines/excuse_attendance_keeps_denominator_drops_completed
    """
    _, _, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 0},
        agreement_overrides={"contract_tuition_cents": 0},
    )
    entry = fx.post_attendance(agreement["id"], kind="THEORY", scheduled_hours=10, attended_hours=8, term_index=1)
    validate_success(api.excuse_attendance_entry(entry["id"], ADVISOR))
    agr = validate_success(api.get_agreement(agreement["id"], ADVISOR))
    assert agr["clock_hours_completed"] == pytest.approx(0.0, abs=1e-9), agr
    assert agr["scheduled_hours_to_date"] == pytest.approx(10.0, abs=1e-9), agr
    assert agr["attendance_pct"] == pytest.approx(0.0, abs=1e-9), agr


# --------------------------------------------------------------------------
# corner: void_attendance_excludes_from_denominator
# --------------------------------------------------------------------------
def test_void_excludes_row_from_denominator_empty_yields_one(api):
    """PRD §3.4: "A voided row is excluded from every sum and from the
    denominator. Voiding a POSTED row therefore removes it from both the completed
    sums and the denominator, then recomputes the rollups and attendance_pct and
    bumps the agreement's version ..."
    PRD §3.4: "when scheduled_hours_to_date is 0 the attendance_pct is exactly 1.0
    rather than a division by zero."

    Design: Corner/state_machines/void_attendance_excludes_from_denominator
    """
    _, _, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 0},
        agreement_overrides={"contract_tuition_cents": 0},
    )
    entry = fx.post_attendance(agreement["id"], kind="THEORY", scheduled_hours=10, attended_hours=8, term_index=1)
    validate_success(api.void_attendance_entry(entry["id"], ADVISOR))
    agr = validate_success(api.get_agreement(agreement["id"], ADVISOR))
    assert agr["scheduled_hours_to_date"] == pytest.approx(0.0, abs=1e-9), agr
    assert agr["attendance_pct"] == pytest.approx(1.0, abs=1e-9), agr


# --------------------------------------------------------------------------
# corner: externship_complete_bubbles_externship_hours_via_system_entry
# --------------------------------------------------------------------------
def test_externship_complete_credits_verified_and_bubbles_hours(api):
    """PRD §3.8: "On completion the assignment's verified_hours is set to
    actual_hours, the system creates an attendance entry on the agreement of kind
    EXTERNSHIP and status POSTED with both scheduled_hours and attended_hours
    equal to actual_hours and term_index equal to the clock's current_term_index,
    the agreement's externship and clock-hour rollups and attendance_pct are
    recomputed, the agreement's version increments, the site's
    active_assignment_count decreases by 1, and the site's version increments."

    Design: Corner/state_machines/externship_complete_bubbles_externship_hours_via_system_entry
    """
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 0},
        cohort_overrides={"start_term_index": 0, "end_term_index": 8},
        agreement_overrides={"contract_tuition_cents": 0},
    )
    site = fx.create_active_site(daily_slot_capacity=5)
    assignment = fx.place_assignment(agreement["id"], site["id"], start_term_index=0,
                                     end_term_index=4, planned_hours=120)
    fx.advance_clock_to(1)
    validate_success(api.begin_assignment(assignment["id"], ADVISOR))
    completed = validate_success(
        api.complete_assignment(assignment["id"], {"actual_hours": 120}, ADVISOR))
    assert completed["verified_hours"] == pytest.approx(120.0, abs=1e-9), completed

    agr = validate_success(api.get_agreement(agreement["id"], ADVISOR))
    assert agr["externship_hours_completed"] == pytest.approx(120.0, abs=1e-9), agr
    assert agr["clock_hours_completed"] == pytest.approx(120.0, abs=1e-9), agr
