"""Payload factories — one per creatable entity, input fields only (PRD §3)."""


def create_horse_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Horse",
        "sex": "MARE",
        "breed_class": "LIGHT",
        "estimated_weight_lbs": 1000,
        "age_years": 6,
        "body_condition_score": 5,
        "training_level": "GREEN",
    }
    defaults.update(overrides)
    return defaults


def create_intake_evaluation_payload(horse_id, **overrides) -> dict:
    defaults = {
        "horse_id": horse_id,
        "evaluation_type": "MEDICAL",
        "scheduled_date": "2026-08-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def complete_evaluation_payload(**overrides) -> dict:
    defaults = {"outcome": "PASS"}
    defaults.update(overrides)
    return defaults


def daily_health_log_payload(horse_id, **overrides) -> dict:
    defaults = {
        "horse_id": horse_id,
        "temp_f": 101.0,
        "appetite": "NORMAL",
    }
    defaults.update(overrides)
    return defaults


def rehabilitation_plan_payload(horse_id, expected_horse_version, **overrides) -> dict:
    defaults = {
        "horse_id": horse_id,
        "expected_horse_version": expected_horse_version,
        "goals": "restore condition",
        "target_body_condition_score": 6,
        "planned_weeks": 8,
    }
    defaults.update(overrides)
    return defaults


def practitioner_payload(**overrides) -> dict:
    defaults = {"name": "Dr Test", "specialty": "VETERINARIAN"}
    defaults.update(overrides)
    return defaults


def appointment_payload(horse_id, practitioner_id, **overrides) -> dict:
    defaults = {
        "horse_id": horse_id,
        "practitioner_id": practitioner_id,
        "service_type": "VET_EXAM",
        "scheduled_start": "2026-08-16T09:00:00Z",
        "scheduled_end": "2026-08-16T09:45:00Z",
    }
    defaults.update(overrides)
    return defaults


def stall_payload(**overrides) -> dict:
    defaults = {"stall_code": "S-01", "barn_zone": "MAIN_BARN"}
    defaults.update(overrides)
    return defaults


def stall_assignment_payload(horse_id, stall_id, **overrides) -> dict:
    defaults = {
        "horse_id": horse_id,
        "stall_id": stall_id,
        "start_date": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def adopter_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Adopter",
        "contact_email": "adopter@example.com",
        "experience_level": "EXPERT",
        "has_stall_facility": True,
    }
    defaults.update(overrides)
    return defaults


def adoption_application_payload(adopter_id, horse_id, **overrides) -> dict:
    defaults = {
        "adopter_id": adopter_id,
        "horse_id": horse_id,
        "proposed_pickup_date": "2026-08-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def home_check_payload(application_id, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "scheduled_date": "2026-08-15T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def sponsor_payload(**overrides) -> dict:
    defaults = {"name": "Test Sponsor", "contact_email": "sponsor@example.com"}
    defaults.update(overrides)
    return defaults


def sponsorship_payload(sponsor_id, horse_id, **overrides) -> dict:
    defaults = {
        "sponsor_id": sponsor_id,
        "horse_id": horse_id,
        "monthly_pledge_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def sanctuary_care_plan_payload(horse_id, expected_horse_version, **overrides) -> dict:
    defaults = {
        "horse_id": horse_id,
        "expected_horse_version": expected_horse_version,
        "variant": "STRAIGHT_LINE",
    }
    defaults.update(overrides)
    return defaults


def purchase_order_payload(**overrides) -> dict:
    defaults = {
        "feed_type": "GRASS_HAY",
        "quantity_lbs": 100,
        "unit_cents_per_lb": 10,
    }
    defaults.update(overrides)
    return defaults


def receipt_payload(**overrides) -> dict:
    defaults = {
        "quantity_received_lbs": 50,
        "expiry_date": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def volunteer_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Volunteer",
        "contact_email": "volunteer@example.com",
        "skills": ["FEEDING"],
    }
    defaults.update(overrides)
    return defaults


def barn_shift_payload(**overrides) -> dict:
    defaults = {
        "shift_date": "2026-08-05T00:00:00Z",
        "start_time": "06:00",
        "end_time": "08:00",
        "barn_zone": "MAIN_BARN",
        "required_skill": "FEEDING",
    }
    defaults.update(overrides)
    return defaults


def euthanasia_case_payload(horse_id, **overrides) -> dict:
    defaults = {
        "horse_id": horse_id,
        "clinical_summary": "chronic unresolvable pain",
        "suffering_score": 5,
    }
    defaults.update(overrides)
    return defaults
