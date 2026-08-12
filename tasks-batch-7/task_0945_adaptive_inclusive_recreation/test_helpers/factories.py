"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "SESSION_START": "2026-06-10T14:00:00Z",
    "SESSION_END": "2026-06-10T16:00:00Z",
    "ASSESSED_ON": "2026-04-01",
    "EFFECTIVE_FROM": "2026-04-01T00:00:00Z",
}


def fee_scale_band_payload(**overrides):
    payload = {
        "household_size_min": 1,
        "household_size_max": 6,
        "income_band": "BAND_C",
        "per_session_cents": 4000,
        "series_cents": 24000,
    }
    payload.update(overrides)
    return payload


def operating_period_payload(**overrides):
    payload = {"name": "FY26", "starts_on": "2026-01-01", "ends_on": "2026-12-31"}
    payload.update(overrides)
    return payload


def activity_program_payload(**overrides):
    payload = {
        "name": "Inclusive Yoga",
        "activity_type": "FITNESS",
        "risk_tier": "LOW",
        "pricing_mode": "PER_SESSION",
        "rounding_policy": "ROUND_ON_TOTAL",
        "waitlist_policy": "FIFO",
        "fee_multiplier_bp": 10000,
        "scheduled_session_count": 1,
        "required_consent_types": [],
        "required_certification_types": [],
        "requires_medication_admin": False,
    }
    payload.update(overrides)
    return payload


def program_session_payload(program_id, **overrides):
    payload = {
        "program_id": program_id,
        "start_at": DEFAULTS["SESSION_START"],
        "end_at": DEFAULTS["SESSION_END"],
        "slot_capacity": 2,
        "one_to_one_pool_size": 0,
    }
    payload.update(overrides)
    return payload


def participant_payload(**overrides):
    payload = {
        "legal_name": "Ada Rivera",
        "date_of_birth": "2010-03-04",
        "household_id": "HH-1",
        "household_size": 3,
        "income_band": "BAND_C",
        "weight_kg": 40,
        "mobility_profile": "AMBULATORY",
        "guardianship_status": "GUARDIAN_REQUIRED",
    }
    payload.update(overrides)
    return payload


def caregiver_payload(participant_id, **overrides):
    payload = {
        "participant_id": participant_id,
        "full_name": "Rosa Rivera",
        "relationship": "PARENT",
        "is_legal_guardian": True,
        "contact_phone": "555-0100",
    }
    payload.update(overrides)
    return payload


def support_assessment_payload(participant_id, expected_participant_version, **overrides):
    payload = {
        "participant_id": participant_id,
        "assessed_on": DEFAULTS["ASSESSED_ON"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "support_tier": "INDEPENDENT",
        "expected_participant_version": expected_participant_version,
    }
    payload.update(overrides)
    return payload


def consent_payload(participant_id, **overrides):
    payload = {
        "participant_id": participant_id,
        "consent_type": "EMERGENCY_MEDICAL",
        "expires_on": "2026-12-31",
    }
    payload.update(overrides)
    return payload


def staff_member_payload(**overrides):
    payload = {"full_name": "Dana Lead", "role_title": "Recreation Therapist"}
    payload.update(overrides)
    return payload


def staff_certification_payload(staff_member_id, **overrides):
    payload = {
        "staff_member_id": staff_member_id,
        "certification_type": "CPR",
        "issued_on": "2025-06-01",
        "expires_on": "2027-06-01",
    }
    payload.update(overrides)
    return payload


def staff_assignment_payload(session_id, staff_member_id, **overrides):
    payload = {
        "session_id": session_id,
        "staff_member_id": staff_member_id,
        "assignment_role": "GROUP",
    }
    payload.update(overrides)
    return payload


def equipment_item_payload(**overrides):
    payload = {
        "item_kind": "SERIALIZED",
        "model_code": "TRIKE_ADAPT",
        "size_code": "M",
        "weight_capacity_kg": 100,
        "serial_number": "TA-0001",
        "inspection_due_date": "2026-12-31",
        "pooled_total": 1,
    }
    payload.update(overrides)
    # A pooled row carries no serial number and no inspection cycle; both inputs
    # are optional and default to null, so they are simply omitted.
    if payload.get("item_kind") == "POOLED":
        for optional in ("serial_number", "inspection_due_date"):
            if payload.get(optional) is None:
                payload.pop(optional, None)
    return payload


def transport_run_payload(session_id, **overrides):
    payload = {
        "session_id": session_id,
        "pickup_start_at": "2026-06-10T13:00:00Z",
        "pickup_end_at": "2026-06-10T13:45:00Z",
        "fare_mode": "FLAT",
        "flat_fare_cents": 1000,
        "route_miles_x10": 0,
        "accessible_positions": 1,
        "ambulatory_seats": 1,
    }
    payload.update(overrides)
    return payload


def funding_source_payload(operating_period_id, **overrides):
    payload = {
        "operating_period_id": operating_period_id,
        "name": "Access Fund",
        "source_kind": "GENERAL_FUND",
        "priority_rank": 2,
        "award_mode": "FLAT_CAP",
        "award_pct_bp": 0,
        "flat_award_cents": 5000,
        "total_budget_cents": 20000,
    }
    payload.update(overrides)
    return payload


def goal_payload(participant_id, **overrides):
    payload = {
        "participant_id": participant_id,
        "title": "Independent transfers",
        "measure": "transfers rated 1-5",
        "baseline_value": 1,
        "target_value": 5,
        "mastery_mode": "N_OF_M",
        "mastery_criterion_score": 4,
        "mastery_window_m": 3,
        "mastery_hits_n": 2,
        "review_due_on": "2026-09-01",
    }
    payload.update(overrides)
    return payload
