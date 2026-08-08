"""Payload factories — one per entity, input fields only."""


def create_host_payload(**overrides) -> dict:
    payload = {"display_name": "Bounce Host", "email": "host@example.com"}
    payload.update(overrides)
    return payload


def create_traveler_payload(**overrides) -> dict:
    payload = {"email": "traveler@example.com", "full_name": "Traveler One"}
    payload.update(overrides)
    return payload


def create_insurance_plan_payload(**overrides) -> dict:
    payload = {
        "tier": "PREMIUM",
        "per_bag_coverage_cents": 50000,
        "premium_cents_per_bag_day": 200,
    }
    payload.update(overrides)
    return payload


def create_location_payload(**overrides) -> dict:
    payload = {
        "name": "Downtown",
        "address": "1 Main",
        "daily_bag_capacity": 10,
        "oversize_capacity": 5,
        "per_bag_day_rate_cents": 500,
        "oversize_surcharge_cents_per_day": 300,
    }
    payload.update(overrides)
    return payload


def bag_spec(declared_value_cents=1000, dimension_sum_cm=100) -> dict:
    """One entry for a booking's bags[] array."""
    return {"declared_value_cents": declared_value_cents, "dimension_sum_cm": dimension_sum_cm}


def create_booking_payload(location_id, traveler_id, insurance_plan_id,
                           check_in_date, check_out_date, bags,
                           expected_location_version=None, **overrides) -> dict:
    payload = {
        "location_id": location_id,
        "traveler_id": traveler_id,
        "insurance_plan_id": insurance_plan_id,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "bags": bags,
    }
    if expected_location_version is not None:
        payload["expected_location_version"] = expected_location_version
    payload.update(overrides)
    return payload


def create_extension_payload(new_check_out_date, **overrides) -> dict:
    payload = {"new_check_out_date": new_check_out_date}
    payload.update(overrides)
    return payload


def create_claim_payload(bag_id, reason="DAMAGE", description="incident",
                         claimed_amount_cents=1000, **overrides) -> dict:
    payload = {
        "bag_id": bag_id,
        "reason": reason,
        "description": description,
        "claimed_amount_cents": claimed_amount_cents,
    }
    payload.update(overrides)
    return payload


def create_rating_payload(score=5, **overrides) -> dict:
    payload = {"score": score}
    payload.update(overrides)
    return payload


def seal_entry(bag_id, seal_code, photo_url=None) -> dict:
    return {"bag_id": bag_id, "seal_code": seal_code, "photo_url": photo_url or f"http://p/{seal_code}"}
