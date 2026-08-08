"""Payload factories — one per entity, input fields only."""


def create_therapist_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Therapist", "discipline": "MUSIC", "credential": "MT-BC"}
    defaults.update(overrides)
    return defaults


def create_insurance_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Insurance Client",
        "dob": "2015-01-01",
        "payer_type": "INSURANCE",
        "insurance_payer_name": "BlueCo",
        "insurance_coinsurance_pct": 0.20,
        "insurance_contracted_rate_cents": 12503,
        "insurance_visits_authorized": 5,
    }
    defaults.update(overrides)
    return defaults


def create_self_pay_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Self Pay Client",
        "dob": "2015-01-01",
        "payer_type": "SELF_PAY",
        "household_income_cents": 4_000_000,
        "household_size": 2,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "referral_source": "School",
        "reason": "presenting reason",
        "referred_discipline": "MUSIC",
    }
    defaults.update(overrides)
    return defaults


def assess_payload(**overrides) -> dict:
    defaults = {"recommendation": "THERAPY_RECOMMENDED", "baseline_score": 40}
    defaults.update(overrides)
    return defaults


def create_plan_payload(referral_id, expected_client_version, **overrides) -> dict:
    defaults = {
        "referral_id": referral_id,
        "discipline": "MUSIC",
        "weekly_frequency": 1,
        "expected_client_version": expected_client_version,
    }
    defaults.update(overrides)
    return defaults


def create_goal_payload(**overrides) -> dict:
    defaults = {"description": "Goal statement", "target_sessions": 6, "weight": 1.0}
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {"name": "Room A", "capacity": 3}
    defaults.update(overrides)
    return defaults


def create_material_payload(**overrides) -> dict:
    defaults = {
        "name": "Djembe",
        "category": "INSTRUMENT",
        "on_hand_quantity": 5,
        "unit_charge_cents": 300,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "party_name": "Lincoln Elementary",
        "contract_type": "SCHOOL",
        "budget_cents": 100000,
        "rate_cents_per_session": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(therapist_id, room_id, plan_id, goal_id, **overrides) -> dict:
    defaults = {
        "therapist_id": therapist_id,
        "room_id": room_id,
        "plan_id": plan_id,
        "goal_id": goal_id,
        "modality": "INDIVIDUAL",
        "start_utc": "2026-06-01T09:00:00Z",
        "end_utc": "2026-06-01T10:00:00Z",
        "capacity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_progress_note_payload(**overrides) -> dict:
    defaults = {"narrative": "Clinical narrative", "rubric_score": 55, "outcome_rating": "MAINTAINED"}
    defaults.update(overrides)
    return defaults
