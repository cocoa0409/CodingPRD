"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "EMPLOYER_NAME": "Acme",
    "HOV_DISCOUNT_PCT": 0.50,
    "EMPLOYER_MATCH_PCT": 0.30,
    "MONTHLY_BENEFIT_CAP_CENTS": 100000,
    "GRH_ANNUAL_CAP_CENTS": 20000,
    "GRH_PER_EVENT_CAP_CENTS": 6000,
    "SUBSIDY_BUDGET_CENTS": 1000000,
    "HOME_ZONE": "Z-N",
    "WORK_ZONE": "Z-DT",
    "ORIGIN_ZONE": "Z-N",
    "DEST_ZONE": "Z-DT",
    "DEPARTURE_DAYS": ["MON", "TUE", "WED", "THU", "FRI"],
    "BASE_COST_CENTS": 2000,
    "PER_MILE_CENTS": 120,
    "SEAT_CAPACITY": 6,
    "DISTANCE_MILES": 10.0,
    "DURATION_MIN": 40,
}


def create_employer_program_payload(**overrides) -> dict:
    defaults = {
        "employer_name": DEFAULTS["EMPLOYER_NAME"],
        "hov_discount_pct": DEFAULTS["HOV_DISCOUNT_PCT"],
        "employer_match_pct": DEFAULTS["EMPLOYER_MATCH_PCT"],
        "monthly_benefit_cap_cents": DEFAULTS["MONTHLY_BENEFIT_CAP_CENTS"],
        "grh_annual_cap_cents": DEFAULTS["GRH_ANNUAL_CAP_CENTS"],
        "grh_per_event_cap_cents": DEFAULTS["GRH_PER_EVENT_CAP_CENTS"],
        "subsidy_budget_cents": DEFAULTS["SUBSIDY_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(employer_program_id, full_name="Rae", **overrides) -> dict:
    defaults = {
        "employer_program_id": employer_program_id,
        "full_name": full_name,
        "home_zone": DEFAULTS["HOME_ZONE"],
        "work_zone": DEFAULTS["WORK_ZONE"],
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(owner_member_id, plate="VAN-1", **overrides) -> dict:
    defaults = {
        "owner_member_id": owner_member_id,
        "plate": plate,
        "seat_capacity": DEFAULTS["SEAT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_pool_payload(employer_program_id, driver_member_id, vehicle_id, **overrides) -> dict:
    defaults = {
        "employer_program_id": employer_program_id,
        "driver_member_id": driver_member_id,
        "vehicle_id": vehicle_id,
        "kind": "VANPOOL",
        "origin_zone": DEFAULTS["ORIGIN_ZONE"],
        "dest_zone": DEFAULTS["DEST_ZONE"],
        "departure_days": list(DEFAULTS["DEPARTURE_DAYS"]),
        "base_cost_cents": DEFAULTS["BASE_COST_CENTS"],
        "per_mile_cents": DEFAULTS["PER_MILE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_match_request_payload(rider_member_id, **overrides) -> dict:
    defaults = {
        "rider_member_id": rider_member_id,
        "origin_zone": DEFAULTS["ORIGIN_ZONE"],
        "dest_zone": DEFAULTS["DEST_ZONE"],
        "needed_days": list(DEFAULTS["DEPARTURE_DAYS"]),
        "earliest_departure_min": 480,
        "latest_departure_min": 600,
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(pool_id, rider_member_id, expected_pool_version, **overrides) -> dict:
    defaults = {
        "pool_id": pool_id,
        "rider_member_id": rider_member_id,
        "expected_pool_version": expected_pool_version,
    }
    defaults.update(overrides)
    return defaults


def create_trip_payload(pool_id, departure_at="2026-06-09T15:00:00Z", **overrides) -> dict:
    defaults = {
        "pool_id": pool_id,
        "departure_at": departure_at,
        "duration_min": DEFAULTS["DURATION_MIN"],
        "distance_miles": DEFAULTS["DISTANCE_MILES"],
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(trip_id, rider_member_id, expected_trip_version, **overrides) -> dict:
    defaults = {
        "trip_id": trip_id,
        "rider_member_id": rider_member_id,
        "expected_trip_version": expected_trip_version,
    }
    defaults.update(overrides)
    return defaults


def create_grh_claim_payload(rider_member_id, employer_program_id, claimed_fare_cents=4000,
                             reason_code="ILLNESS", **overrides) -> dict:
    defaults = {
        "rider_member_id": rider_member_id,
        "employer_program_id": employer_program_id,
        "claimed_fare_cents": claimed_fare_cents,
        "reason_code": reason_code,
    }
    defaults.update(overrides)
    return defaults
