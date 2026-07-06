"""Payload factories — one per entity, input fields only."""


def create_household_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Household",
        "address_line1": "1 Main St",
        "postal_code": "10001",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Member",
        "date_of_birth": "1990-01-01",
        "member_type": "ADULT",
        "email": "test@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_pledge_campaign_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Campaign",
        "target_amount_cents": 100_000,
        "starts_on": "2026-05-01",
        "ends_on": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_pledge_payload(**overrides) -> dict:
    defaults = {
        "pledged_amount_cents": 10_000,
        "frequency": "ONE_TIME",
        "first_expected_on": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_donation_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 5_000,
        "donation_date": "2026-06-01",
        "payment_method": "CHECK",
    }
    defaults.update(overrides)
    return defaults


def create_year_end_statement_payload(**overrides) -> dict:
    defaults = {
        "tax_year": 2026,
        "variant": "PROVISIONAL",
    }
    defaults.update(overrides)
    return defaults


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": "Sanctuary",
        "capacity": 200,
        "buffer_minutes": 0,
    }
    defaults.update(overrides)
    return defaults


def create_facility_booking_payload(**overrides) -> dict:
    defaults = {
        "booking_type": "EXTERNAL",
        "starts_at": "2026-05-10T10:00:00Z",
        "ends_at": "2026-05-10T11:00:00Z",
        "headcount": 50,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(**overrides) -> dict:
    defaults = {
        "name": "Sun 10am",
        "event_type": "SERVICE",
        "starts_at": "2026-05-10T10:00:00Z",
        "ends_at": "2026-05-10T11:00:00Z",
        "expected_attendance": 50,
        "volunteer_slots": 2,
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_assignment_payload(**overrides) -> dict:
    defaults = {
        "role_type": "USHER",
    }
    defaults.update(overrides)
    return defaults


def create_small_group_payload(**overrides) -> dict:
    defaults = {
        "name": "Bible Study",
        "ministry_area": "STUDY",
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_group_membership_payload(**overrides) -> dict:
    defaults = {
        "role": "MEMBER",
    }
    defaults.update(overrides)
    return defaults


def create_child_checkin_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults
