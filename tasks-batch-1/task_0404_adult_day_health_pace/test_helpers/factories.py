"""Payload factories — one per entity, input fields only."""


def create_program_payload(**overrides) -> dict:
    """Required: name, state_code, daily_census_capacity, max_roster,
    medicaid_monthly_rate_cents, medicare_monthly_rate_cents.
    Optional: medicare_only_supplement_cents, lock_in_days, loc_validity_days."""
    defaults = {
        "name": "Test PACE Center",
        "state_code": "CA",
        "daily_census_capacity": 50,
        "max_roster": 100,
        "medicaid_monthly_rate_cents": 350000,
        "medicare_monthly_rate_cents": 280000,
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(program_id, **overrides) -> dict:
    """Required: program_id, full_name, date_of_birth, dual_eligible."""
    defaults = {
        "program_id": program_id,
        "full_name": "Test Participant",
        "date_of_birth": "1955-01-01",
        "dual_eligible": True,
    }
    defaults.update(overrides)
    return defaults


def create_loc_assessment_payload(participant_id, **overrides) -> dict:
    """Required: participant_id, nf_score, assessed_on. Optional: nf_threshold."""
    defaults = {
        "participant_id": participant_id,
        "nf_score": 75,
        "assessed_on": "2026-05-01",
    }
    defaults.update(overrides)
    return defaults


def create_care_plan_payload(participant_id, **overrides) -> dict:
    """Required: participant_id. Optional: supersedes_care_plan_id, required_disciplines."""
    defaults = {"participant_id": participant_id}
    defaults.update(overrides)
    return defaults


def create_care_plan_goal_payload(**overrides) -> dict:
    """Required: discipline, description. Optional: target_attendance_days."""
    defaults = {"discipline": "RN", "description": "Mobility goal"}
    defaults.update(overrides)
    return defaults


def create_attendance_day_payload(participant_id, service_date, **overrides) -> dict:
    """Required: participant_id, service_date.
    Optional: meals_provided, activities_count, transport_required."""
    defaults = {"participant_id": participant_id, "service_date": service_date}
    defaults.update(overrides)
    return defaults


def create_transport_leg_payload(attendance_day_id, **overrides) -> dict:
    """Required: attendance_day_id, direction, window_start_min, window_end_min, vehicle_id."""
    defaults = {
        "attendance_day_id": attendance_day_id,
        "direction": "PICKUP",
        "window_start_min": 480,
        "window_end_min": 540,
        "vehicle_id": "VAN1",
    }
    defaults.update(overrides)
    return defaults


def create_medication_order_payload(participant_id, care_plan_id, **overrides) -> dict:
    """Required: participant_id, care_plan_id, drug_name, daily_doses."""
    defaults = {
        "participant_id": participant_id,
        "care_plan_id": care_plan_id,
        "drug_name": "Metformin",
        "daily_doses": 2,
    }
    defaults.update(overrides)
    return defaults


def create_medication_administration_payload(medication_order_id, attendance_day_id, **overrides) -> dict:
    """Required: medication_order_id, attendance_day_id, outcome, administered_at."""
    defaults = {
        "medication_order_id": medication_order_id,
        "attendance_day_id": attendance_day_id,
        "outcome": "GIVEN",
        "administered_at": "2026-06-02T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_capitation_payment_payload(participant_id, service_month, **overrides) -> dict:
    """Required: participant_id, service_month. Optional: proration_mode."""
    defaults = {"participant_id": participant_id, "service_month": service_month}
    defaults.update(overrides)
    return defaults


def create_disenrollment_request_payload(participant_id, **overrides) -> dict:
    """Required: participant_id, kind, reason_code, requested_effective_date."""
    defaults = {
        "participant_id": participant_id,
        "kind": "VOLUNTARY",
        "reason_code": "MOVED",
        "requested_effective_date": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults
