"""Payload factories — one per resource, input fields only."""

DEFAULTS = {
    "RATE_CARD_NAME": "RC-MOVE",
    "POLICY_NAME": "IP-BASIC",
    "TRUCK_NAME": "TK",
    "CUSTOMER_NAME": "Cust",
    "CUSTOMER_EMAIL": "c@x.com",
    "HELPER_NAME": "Helper",
    "HELPER_EMAIL": "h@x.com",
    "BASE_HOURLY_RATE_CENTS": 6000,
    "HELPER_PAY_RATE_CENTS": 4000,
}


def create_customer_payload(**overrides) -> dict:
    payload = {"display_name": DEFAULTS["CUSTOMER_NAME"], "email": DEFAULTS["CUSTOMER_EMAIL"]}
    payload.update(overrides)
    return payload


def create_helper_payload(**overrides) -> dict:
    payload = {
        "display_name": DEFAULTS["HELPER_NAME"],
        "email": DEFAULTS["HELPER_EMAIL"],
        "base_hourly_rate_cents": DEFAULTS["HELPER_PAY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_rate_card_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["RATE_CARD_NAME"],
        "job_type": "MOVE",
        "base_hourly_rate_cents": DEFAULTS["BASE_HOURLY_RATE_CENTS"],
        "min_billable_hours": 2.0,
        "crew_surcharge_pct": 0.10,
        "peak_surge_multiplier": 1.25,
        "truck_fee_cents": 8000,
    }
    payload.update(overrides)
    return payload


def create_insurance_policy_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["POLICY_NAME"],
        "tier": "BASIC",
        "coverage_cap_cents": 200000,
        "deductible_cents": 10000,
        "coverage_pct": 1.0,
    }
    payload.update(overrides)
    return payload


def create_truck_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["TRUCK_NAME"],
        "capacity_cuft": 800,
        "daily_rate_cents": 20000,
    }
    payload.update(overrides)
    return payload


def create_job_payload(rate_card_id, insurance_policy_id, **overrides) -> dict:
    payload = {
        "rate_card_id": rate_card_id,
        "insurance_policy_id": insurance_policy_id,
        "job_type": "MOVE",
        "crew_size": 1,
        "estimated_hours": 3.0,
        "window_start": "2026-03-11T09:00:00Z",
        "window_end": "2026-03-11T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_addon_payload(addon_type, quantity, unit_fee_cents) -> dict:
    return {"addon_type": addon_type, "quantity": quantity, "unit_fee_cents": unit_fee_cents}


def book_payload(quote_id, expected_job_version) -> dict:
    return {"quote_id": quote_id, "expected_job_version": expected_job_version}


def reschedule_payload(window_start, window_end) -> dict:
    return {"window_start": window_start, "window_end": window_end}


def complete_payload(actual_hours) -> dict:
    return {"actual_hours": actual_hours}


def vet_payload(decision) -> dict:
    return {"decision": decision}


def assign_truck_payload(truck_id) -> dict:
    return {"truck_id": truck_id}


def create_assignment_payload(job_id, helper_id, **overrides) -> dict:
    payload = {"job_id": job_id, "helper_id": helper_id}
    payload.update(overrides)
    return payload


def create_claim_payload(job_id, claimed_amount_cents, **overrides) -> dict:
    payload = {
        "job_id": job_id,
        "damage_description": "damage",
        "claimed_amount_cents": claimed_amount_cents,
    }
    payload.update(overrides)
    return payload


def create_rating_payload(job_id, helper_id, stars, **overrides) -> dict:
    payload = {"job_id": job_id, "helper_id": helper_id, "stars": stars}
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
