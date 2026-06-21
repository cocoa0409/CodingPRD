"""Provider-schedule overlap (half-open intervals) and vaccine dose spacing."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
    set_clock,
    create_provider,
    create_patient,
    create_visit,
)

FD = TEST_USERS["frontdesk_headers"]


# ─── Queue A: resource_temporal_overlap / provider_slot_half_open_overlap ───

def test_overlapping_slot_rejected(api):
    """PRD §3.4: "A new visit is rejected with `ERR_SLOT_OVERLAP` if its slot overlaps
    any existing visit of the same provider that is not cancelled and not a no-show."

    Design: Difficulty/resource_temporal_overlap/provider_slot_half_open_overlap
    """
    provider = create_provider()
    patient1 = create_patient()
    patient2 = create_patient(sex="F")
    create_visit(patient1["id"], provider["id"],
                 scheduled_start="2026-06-01T09:00:00Z", scheduled_end="2026-06-01T09:30:00Z")
    # 09:15-09:45 overlaps 09:00-09:30 (shared 09:15-09:30).
    res = api.create_visit({
        "patient_id": patient2["id"], "provider_id": provider["id"],
        "visit_type": "CONSULTATION",
        "scheduled_start": "2026-06-01T09:15:00Z", "scheduled_end": "2026-06-01T09:45:00Z",
    }, FD)
    validate_error(res, "ERR_SLOT_OVERLAP")


def test_back_to_back_touching_slots_allowed(api):
    """PRD §3.4: "Because slots are half-open, two visits that merely touch at an
    endpoint — one ending exactly when the next begins — do not overlap and are both
    allowed."

    Design: Difficulty/resource_temporal_overlap/provider_slot_half_open_overlap
    """
    provider = create_provider()
    patient1 = create_patient()
    patient2 = create_patient(sex="F")
    create_visit(patient1["id"], provider["id"],
                 scheduled_start="2026-06-01T09:00:00Z", scheduled_end="2026-06-01T09:30:00Z")
    # 09:30-10:00 touches the prior end at 09:30; half-open => no overlap => allowed.
    res = api.create_visit({
        "patient_id": patient2["id"], "provider_id": provider["id"],
        "visit_type": "CONSULTATION",
        "scheduled_start": "2026-06-01T09:30:00Z", "scheduled_end": "2026-06-01T10:00:00Z",
    }, FD)
    second = validate_success(res, 201)
    assert second["status"] == "SCHEDULED"


# ─── Queue A: resource_temporal_overlap / vaccine_minimum_gap_spacing ───

def test_second_flu_dose_within_28_days_rejected_on_checkin(api):
    """PRD §3.5: "When a `VACCINATION` visit is checked in, the system rejects it with
    `ERR_VACCINE_INTERVAL_VIOLATION` if the same patient already has another visit for
    the same `vaccine_code` that has reached `CHECKED_IN` or a later status and whose
    `scheduled_start` falls within the 28 days immediately before this visit's
    `scheduled_start`."

    Design: Difficulty/resource_temporal_overlap/vaccine_minimum_gap_spacing
    """
    set_clock("2026-06-01T08:00:00Z")
    provider = create_provider(specialty="PEDIATRICS")
    patient = create_patient(date_of_birth="2021-01-01", sex="M")
    v1 = create_visit(patient["id"], provider["id"], visit_type="VACCINATION",
                      scheduled_start="2026-06-01T09:00:00Z",
                      scheduled_end="2026-06-01T09:15:00Z", vaccine_code="FLU")
    validate_success(api.check_in_visit(v1["id"], FD), 200)
    # Second FLU dose 9 days later (< 28).
    v2 = create_visit(patient["id"], provider["id"], visit_type="VACCINATION",
                      scheduled_start="2026-06-10T09:00:00Z",
                      scheduled_end="2026-06-10T09:15:00Z", vaccine_code="FLU")
    res = api.check_in_visit(v2["id"], FD)
    validate_error(res, "ERR_VACCINE_INTERVAL_VIOLATION")


def test_second_flu_dose_keeps_visit_scheduled_when_rejected(api):
    """PRD §3.5: "two doses of the same vaccine for one patient must be spaced at least
    28 days apart; a second dose whose scheduled start is fewer than 28 days after a
    prior administered dose is blocked at check-in."

    Design: Difficulty/resource_temporal_overlap/vaccine_minimum_gap_spacing
    """
    set_clock("2026-06-01T08:00:00Z")
    provider = create_provider(specialty="PEDIATRICS")
    patient = create_patient(date_of_birth="2021-01-01", sex="M")
    v1 = create_visit(patient["id"], provider["id"], visit_type="VACCINATION",
                      scheduled_start="2026-06-01T09:00:00Z",
                      scheduled_end="2026-06-01T09:15:00Z", vaccine_code="FLU")
    validate_success(api.check_in_visit(v1["id"], FD), 200)
    v2 = create_visit(patient["id"], provider["id"], visit_type="VACCINATION",
                      scheduled_start="2026-06-10T09:00:00Z",
                      scheduled_end="2026-06-10T09:15:00Z", vaccine_code="FLU")
    api.check_in_visit(v2["id"], FD)
    after = validate_success(api.get_visit(v2["id"], FD), 200)
    assert after["status"] == "SCHEDULED", (
        f"a blocked vaccination check-in must leave the visit SCHEDULED, got {after['status']}"
    )


# ─── Queue A: priority_pair_validation_conflict / vaccine_safety_beats_slot_overlap_is_distinct_pair ───

def test_vaccine_interval_violation_fires_on_checkin(api):
    """PRD §3.5: "When a `VACCINATION` visit is checked in, the system rejects it with
    `ERR_VACCINE_INTERVAL_VIOLATION` if the same patient already has another visit for
    the same `vaccine_code` that has reached `CHECKED_IN` or a later status and whose
    `scheduled_start` falls within the 28 days immediately before this visit's
    `scheduled_start`."

    Design: Difficulty/priority_pair_validation_conflict/vaccine_safety_beats_slot_overlap_is_distinct_pair
    """
    set_clock("2026-06-01T08:00:00Z")
    provider = create_provider(specialty="PEDIATRICS")
    patient = create_patient(date_of_birth="2021-01-01", sex="M")
    v1 = create_visit(patient["id"], provider["id"], visit_type="VACCINATION",
                      scheduled_start="2026-06-01T09:00:00Z",
                      scheduled_end="2026-06-01T09:15:00Z", vaccine_code="FLU")
    validate_success(api.check_in_visit(v1["id"], FD), 200)
    v2 = create_visit(patient["id"], provider["id"], visit_type="VACCINATION",
                      scheduled_start="2026-06-10T09:00:00Z",
                      scheduled_end="2026-06-10T09:15:00Z", vaccine_code="FLU")
    res = api.check_in_visit(v2["id"], FD)
    validate_error(res, "ERR_VACCINE_INTERVAL_VIOLATION")


def test_different_vaccine_code_not_blocked_by_interval(api):
    """PRD §3.5: "the system rejects it with `ERR_VACCINE_INTERVAL_VIOLATION` if the
    same patient already has another visit for the same `vaccine_code` that has reached
    `CHECKED_IN` or a later status and whose `scheduled_start` falls within the 28 days
    immediately before this visit's `scheduled_start`."

    Design: Difficulty/priority_pair_validation_conflict/vaccine_safety_beats_slot_overlap_is_distinct_pair
    """
    set_clock("2026-06-01T08:00:00Z")
    provider = create_provider(specialty="PEDIATRICS")
    patient = create_patient(date_of_birth="2021-01-01", sex="M")
    v1 = create_visit(patient["id"], provider["id"], visit_type="VACCINATION",
                      scheduled_start="2026-06-01T09:00:00Z",
                      scheduled_end="2026-06-01T09:15:00Z", vaccine_code="FLU")
    validate_success(api.check_in_visit(v1["id"], FD), 200)
    # A different vaccine code 9 days later: interval rule keys on the same vaccine_code,
    # so MMR is not blocked by the prior FLU dose.
    v2 = create_visit(patient["id"], provider["id"], visit_type="VACCINATION",
                      scheduled_start="2026-06-10T10:00:00Z",
                      scheduled_end="2026-06-10T10:15:00Z", vaccine_code="MMR")
    checked_in = validate_success(api.check_in_visit(v2["id"], FD), 200)
    assert checked_in["status"] == "CHECKED_IN"
