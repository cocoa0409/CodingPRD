"""Payload factories — one per entity, input fields only."""


def create_driver_record_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Driver",
        "date_of_birth": "1986-01-01",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_examiner_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Examiner",
        "certified_classes": ["D"],
        "opaque_user_id": "exu-test",
    }
    defaults.update(overrides)
    return defaults


def create_knowledge_test_payload(driver_record_id, **overrides) -> dict:
    defaults = {
        "driver_record_id": driver_record_id,
        "scheduled_period": 0,
    }
    defaults.update(overrides)
    return defaults


def create_road_test_appointment_payload(driver_record_id, examiner_id, **overrides) -> dict:
    defaults = {
        "driver_record_id": driver_record_id,
        "examiner_id": examiner_id,
        "license_class": "D",
        "slot_start_period": 0,
        "slot_end_period": 1,
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(driver_record_id, road_test_appointment_id, **overrides) -> dict:
    defaults = {
        "driver_record_id": driver_record_id,
        "road_test_appointment_id": road_test_appointment_id,
        "license_class": "D",
    }
    defaults.update(overrides)
    return defaults


def renew_license_payload(driver_record_id, expected_driver_record_version, **overrides) -> dict:
    defaults = {
        "driver_record_id": driver_record_id,
        "license_class": "D",
        "expected_driver_record_version": expected_driver_record_version,
    }
    defaults.update(overrides)
    return defaults


def create_violation_payload(driver_record_id, **overrides) -> dict:
    defaults = {
        "driver_record_id": driver_record_id,
        "code": "SPEEDING_10_OVER",
        "points": 4,
        "occurred_period": 0,
    }
    defaults.update(overrides)
    return defaults


def create_cdl_endorsement_payload(driver_record_id, **overrides) -> dict:
    defaults = {
        "driver_record_id": driver_record_id,
        "endorsement_code": "H",
    }
    defaults.update(overrides)
    return defaults


def create_medical_card_payload(driver_record_id, **overrides) -> dict:
    defaults = {
        "driver_record_id": driver_record_id,
        "issued_period": 0,
        "valid_through_period": 100,
    }
    defaults.update(overrides)
    return defaults


def create_fee_payment_payload(driver_record_id, purpose, amount_cents, **overrides) -> dict:
    defaults = {
        "driver_record_id": driver_record_id,
        "purpose": purpose,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def maneuver_auto(maneuver, weight, auto_score) -> dict:
    """A proctor-phase maneuver item (carries auto_score)."""
    return {"maneuver": maneuver, "weight": weight, "auto_score": auto_score}


def maneuver_scored(maneuver, weight, score) -> dict:
    """A score-phase maneuver item (carries examiner-adjusted score)."""
    return {"maneuver": maneuver, "weight": weight, "score": score}
