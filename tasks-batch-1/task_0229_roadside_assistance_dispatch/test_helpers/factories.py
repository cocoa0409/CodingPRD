"""Payload factories — one per entity, input fields only (Roadside Assistance Dispatch)."""

# A canonical "covers everything" PLUS plan used across most setups.
PLUS_PLAN_DEFAULTS = {
    "tier": "PLUS",
    "annual_service_limit": 4,
    "per_incident_mileage_cap_miles": 5,
    "overage_rate_cents_per_mile": 200,
    "priority_weight": 20,
    "covered_service_types": ["TOW", "JUMP", "LOCKOUT", "FUEL", "TIRE"],
    "base_service_fee_cents": 7500,
}


def create_membership_plan_payload(**overrides) -> dict:
    payload = dict(PLUS_PLAN_DEFAULTS)
    payload.update(overrides)
    return payload


def create_member_payload(plan_id, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "full_name": "Mia Member",
        "home_lat": 0.0,
        "home_lng": 0.0,
    }
    payload.update(overrides)
    return payload


def create_service_provider_payload(**overrides) -> dict:
    payload = {
        "company_name": "Ace Tow",
        "current_lat": 0.0,
        "current_lng": 0.1,
        "capabilities": ["TOW"],
        "rating": 4.5,
    }
    payload.update(overrides)
    return payload


def create_shift_payload(shift_start, shift_end, **overrides) -> dict:
    payload = {"shift_start": shift_start, "shift_end": shift_end}
    payload.update(overrides)
    return payload


def create_depot_payload(**overrides) -> dict:
    payload = {
        "name": "North Depot",
        "lat": 0.0,
        "lng": 0.2,
        "bay_count": 1,
        "cleanup_buffer_minutes": 0,
    }
    payload.update(overrides)
    return payload


def create_bay_reservation_payload(service_call_id, reserved_from, reserved_until, **overrides) -> dict:
    payload = {
        "service_call_id": service_call_id,
        "reserved_from": reserved_from,
        "reserved_until": reserved_until,
    }
    payload.update(overrides)
    return payload


def create_service_call_payload(member_id, service_type="TOW", **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "service_type": service_type,
        "breakdown_lat": 0.0,
        "breakdown_lng": 0.0,
    }
    if service_type == "TOW":
        payload["dropoff_lat"] = 0.0
        payload["dropoff_lng"] = 0.2
    payload.update(overrides)
    return payload


def create_offer_payload(provider_id, expected_service_call_version, **overrides) -> dict:
    payload = {
        "provider_id": provider_id,
        "expected_service_call_version": expected_service_call_version,
    }
    payload.update(overrides)
    return payload


def complete_payload(final_towed_miles=None, **overrides) -> dict:
    payload = {}
    if final_towed_miles is not None:
        payload["final_towed_miles"] = final_towed_miles
    payload.update(overrides)
    return payload


def create_claim_payload(member_id, service_call_id, claimed_amount_cents, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "service_call_id": service_call_id,
        "claimed_amount_cents": claimed_amount_cents,
    }
    payload.update(overrides)
    return payload
