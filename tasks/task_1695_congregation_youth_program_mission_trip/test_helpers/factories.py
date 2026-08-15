"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PROGRAM_NAME": "Youth 2026",
    "MINISTRY_YEAR": "2026-2027",
    "CODE_OF_CONDUCT": "Code of conduct v1",
    "DISCIPLINE_POLICY": "Progressive discipline plan v1",
    # Canonical mission trip shape used across tests: an international trip in
    # June 2027 with the registration window open at the default clock.
    "TRIP_NAME": "Alpha",
    "DESTINATION_NAME": "Lima",
    "DESTINATION_TYPE": "INTERNATIONAL",
    "START_DATE": "2027-06-15",
    "END_DATE": "2027-06-25",
    "CAPACITY_YOUTH": 30,
    "BASE_COST_CENTS": 200000,
    "DEPOSIT_CENTS": 50000,
    "CHAPERONE_RATIO": 5,
    "REGISTRATION_OPEN_AT": "2026-08-01T00:00:00Z",
    "REGISTRATION_CLOSE_AT": "2026-12-01T00:00:00Z",
    "DEPOSIT_DUE_AT": "2027-01-15T00:00:00Z",
    "FINAL_PAYMENT_DUE_AT": "2027-05-01T00:00:00Z",
    "EMERGENCY_PROTOCOL": "Emergency protocol v1",
    "BIRTH_DATE": "2011-01-01",
    "SIGNED_AT": "2026-08-02T10:00:00Z",
}


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "ministry_year": DEFAULTS["MINISTRY_YEAR"],
        "scholarship_fund_total_cents": 0,
        "code_of_conduct_text": DEFAULTS["CODE_OF_CONDUCT"],
        "discipline_policy_text": DEFAULTS["DISCIPLINE_POLICY"],
    }
    defaults.update(overrides)
    return defaults


def create_trip_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": DEFAULTS["TRIP_NAME"],
        "destination_name": DEFAULTS["DESTINATION_NAME"],
        "destination_type": DEFAULTS["DESTINATION_TYPE"],
        "start_date": DEFAULTS["START_DATE"],
        "end_date": DEFAULTS["END_DATE"],
        "capacity_youth": DEFAULTS["CAPACITY_YOUTH"],
        "base_cost_cents": DEFAULTS["BASE_COST_CENTS"],
        "deposit_cents": DEFAULTS["DEPOSIT_CENTS"],
        "chaperone_ratio": DEFAULTS["CHAPERONE_RATIO"],
        "registration_open_at": DEFAULTS["REGISTRATION_OPEN_AT"],
        "registration_close_at": DEFAULTS["REGISTRATION_CLOSE_AT"],
        "deposit_due_at": DEFAULTS["DEPOSIT_DUE_AT"],
        "final_payment_due_at": DEFAULTS["FINAL_PAYMENT_DUE_AT"],
        "emergency_protocol_text": DEFAULTS["EMERGENCY_PROTOCOL"],
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "family_key": "fam-1",
        "first_name": "Pat",
        "last_name": "One",
        "birth_date": DEFAULTS["BIRTH_DATE"],
        "grade": 10,
        "annual_income_bracket": "BAND_B",
        "household_size": 3,
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(trip_id, participant_id, **overrides) -> dict:
    defaults = {
        "trip_id": trip_id,
        "participant_id": participant_id,
        "insurance_tier": "INTERNATIONAL",
        "fundraising_goal_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_consent_form_payload(form_type, **overrides) -> dict:
    defaults = {
        "form_type": form_type,
        "signed_by_name": "Guardian G",
        "signed_at": DEFAULTS["SIGNED_AT"],
    }
    if form_type == "MEDICAL_RELEASE":
        defaults["medical_notes"] = "no known allergies"
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": 50000, "method": "CASH"}
    defaults.update(overrides)
    return defaults


def create_donation_payload(**overrides) -> dict:
    defaults = {"donor_name": "Donor D", "amount_cents": 10000,
                "channel": "CASH"}
    defaults.update(overrides)
    return defaults


def create_scholarship_application_payload(registration_id, **overrides) -> dict:
    defaults = {"registration_id": registration_id, "requested_cents": 100000}
    defaults.update(overrides)
    return defaults


def create_chaperone_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "first_name": "Ada",
        "last_name": "Lead",
        "email": "ada@example.org",
        "phone": "555-0100",
    }
    defaults.update(overrides)
    return defaults


def create_chaperone_assignment_payload(trip_id, chaperone_id,
                                        **overrides) -> dict:
    defaults = {"trip_id": trip_id, "chaperone_id": chaperone_id,
                "role": "LEAD"}
    defaults.update(overrides)
    return defaults


def create_itinerary_item_payload(**overrides) -> dict:
    defaults = {
        "segment_type": "SERVICE",
        "title": "Service block",
        "start_at": "2027-06-15T08:00:00Z",
        "end_at": "2027-06-15T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_lodging_reservation_payload(**overrides) -> dict:
    defaults = {
        "site_name": "host",
        "room_code": "R1",
        "check_in_date": DEFAULTS["START_DATE"],
        "check_out_date": DEFAULTS["END_DATE"],
        "room_capacity": 30,
        "cost_cents": 0,
    }
    defaults.update(overrides)
    return defaults
