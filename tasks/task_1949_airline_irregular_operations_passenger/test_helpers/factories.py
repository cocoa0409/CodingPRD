"""Payload factories — one per creatable resource, input fields only (PRD §4)."""

DEFAULTS = {
    "FULL_NAME": "Test Passenger",
    "CONTACT_EMAIL": "test@example.com",
    "FLIGHT_NUMBER": "OC100",
    "ORIGIN": "HUB",
    "DESTINATION": "DST",
    "SCHED_DEP": "2026-08-10T10:00:00Z",
    "SCHED_ARR": "2026-08-10T11:00:00Z",
    "DISTANCE_KM": 900,
    "OPERATING_CARRIER": "OC",
    "EVENT_CODE": "MECH-0001",
    "HUB": "HUB",
    "CLASSIFICATION": "MECHANICAL",
    "COST_CAP_CENTS": 1_000_000,
    "FARE_CENTS": 12000,
    "CABIN": "ECONOMY",
    "PARTY_SIZE": 1,
    "PARTNER_CARRIER": "ZZ",
    "SETTLEMENT_RATE_PCT": 60,
    "SEATS_QUOTA_PER_FLIGHT": 4,
}


def create_passenger_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["FULL_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_flight_payload(**overrides) -> dict:
    defaults = {
        "flight_number": DEFAULTS["FLIGHT_NUMBER"],
        "origin": DEFAULTS["ORIGIN"],
        "destination": DEFAULTS["DESTINATION"],
        "sched_dep_utc": DEFAULTS["SCHED_DEP"],
        "sched_arr_utc": DEFAULTS["SCHED_ARR"],
        "distance_km": DEFAULTS["DISTANCE_KM"],
        "operating_carrier": DEFAULTS["OPERATING_CARRIER"],
        "cabins": [{"cabin": "ECONOMY", "capacity": 100}],
    }
    defaults.update(overrides)
    return defaults


def create_disruption_event_payload(**overrides) -> dict:
    defaults = {
        "event_code": DEFAULTS["EVENT_CODE"],
        "hub": DEFAULTS["HUB"],
        "classification": DEFAULTS["CLASSIFICATION"],
        "cost_cap_cents": DEFAULTS["COST_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(passenger_id: str, flight_id: str = None, **overrides) -> dict:
    segments = overrides.pop("segments", None)
    if segments is None:
        segments = [{"flight_id": flight_id, "seq_no": 1}]
    defaults = {
        "passenger_id": passenger_id,
        "fare_cents": DEFAULTS["FARE_CENTS"],
        "cabin": DEFAULTS["CABIN"],
        "party_size": DEFAULTS["PARTY_SIZE"],
        "segments": segments,
    }
    defaults.update(overrides)
    return defaults


def delay_flight_payload(new_sched_dep_utc: str, new_sched_arr_utc: str,
                         expected_flight_version: int, **overrides) -> dict:
    defaults = {
        "new_sched_dep_utc": new_sched_dep_utc,
        "new_sched_arr_utc": new_sched_arr_utc,
        "expected_flight_version": expected_flight_version,
    }
    defaults.update(overrides)
    return defaults


def cancel_flight_payload(disruption_event_id: str, expected_flight_version: int) -> dict:
    return {
        "disruption_event_id": disruption_event_id,
        "expected_flight_version": expected_flight_version,
    }


def depart_payload(act_dep_utc: str) -> dict:
    return {"act_dep_utc": act_dep_utc}


def record_actuals_payload(act_arr_utc: str) -> dict:
    return {"act_arr_utc": act_arr_utc}


def generate_options_payload(include_interline: bool = False) -> dict:
    return {"include_interline": include_interline}


def commit_payload(option_id: str, expected_case_version: int) -> dict:
    return {"option_id": option_id, "expected_case_version": expected_case_version}


def create_interline_agreement_payload(**overrides) -> dict:
    defaults = {
        "partner_carrier": DEFAULTS["PARTNER_CARRIER"],
        "origin": DEFAULTS["ORIGIN"],
        "destination": DEFAULTS["DESTINATION"],
        "cabin_map": {"ECONOMY": "Y"},
        "settlement_rate_pct": DEFAULTS["SETTLEMENT_RATE_PCT"],
        "seats_quota_per_flight": DEFAULTS["SEATS_QUOTA_PER_FLIGHT"],
    }
    defaults.update(overrides)
    return defaults


def issue_voucher_payload(voucher_type: str, check_in_date: str = None) -> dict:
    payload = {"voucher_type": voucher_type}
    if check_in_date is not None:
        payload["check_in_date"] = check_in_date
    return payload


def redeem_payload(actual_amount_cents: int) -> dict:
    return {"actual_amount_cents": actual_amount_cents}


def create_crew_assignment_payload(crew_member_ref: str = "CM1",
                                   crew_role: str = "CAPTAIN",
                                   duty_start_utc: str = "2026-08-10T06:00:00Z",
                                   duty_end_utc: str = "2026-08-10T14:00:00Z",
                                   **overrides) -> dict:
    defaults = {
        "crew_member_ref": crew_member_ref,
        "crew_role": crew_role,
        "duty_start_utc": duty_start_utc,
        "duty_end_utc": duty_end_utc,
    }
    defaults.update(overrides)
    return defaults


def create_refund_election_payload(election: str = "REFUND") -> dict:
    return {"election": election}


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
