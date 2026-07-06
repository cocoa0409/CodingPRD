"""Payload factories — one per create endpoint, input fields only."""


def create_mobile_unit_payload(**overrides) -> dict:
    defaults = {"name": "Van A", "modality": "MAMMOGRAPHY", "daily_capacity": 10}
    defaults.update(overrides)
    return defaults


def create_staff_payload(**overrides) -> dict:
    defaults = {"full_name": "Staff Member", "role_type": "TECHNOLOGIST", "modality": "MAMMOGRAPHY"}
    defaults.update(overrides)
    return defaults


def create_sponsor_payload(**overrides) -> dict:
    defaults = {"name": "Acme", "sponsor_type": "EMPLOYER", "viewer_user_id": "sv1"}
    defaults.update(overrides)
    return defaults


def create_grant_payload(sponsor_id, **overrides) -> dict:
    defaults = {"sponsor_id": sponsor_id, "name": "Wellness Fund", "total_budget_cents": 10000}
    defaults.update(overrides)
    return defaults


def create_event_payload(sponsor_id, mobile_unit_id, **overrides) -> dict:
    defaults = {
        "sponsor_id": sponsor_id,
        "mobile_unit_id": mobile_unit_id,
        "modality": "MAMMOGRAPHY",
        "site_label": "Lot 1",
        "event_date": "2026-06-10",
        "window_start_min": 540,
        "window_end_min": 720,
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Participant", "date_of_birth": "1980-01-01", "pay_type": "SELF_PAY"}
    defaults.update(overrides)
    return defaults


def create_appointment_payload(event_id, participant_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "participant_id": participant_id,
        "slot_start_min": 560,
        "slot_duration_min": 30,
    }
    defaults.update(overrides)
    return defaults


def create_reminder_payload(appointment_id, **overrides) -> dict:
    defaults = {"appointment_id": appointment_id, "send_at_min": 500, "channel": "SMS"}
    defaults.update(overrides)
    return defaults


def deliver_result_payload(result="NORMAL", **overrides) -> dict:
    defaults = {"result": result}
    defaults.update(overrides)
    return defaults
