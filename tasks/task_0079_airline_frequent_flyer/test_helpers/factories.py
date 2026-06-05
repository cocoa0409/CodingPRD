"""Payload factories — one per entity, input fields only.

Each call uses a per-call nonce for unique fields (member email) so repeated
factory use within a test does not collide.
"""
import itertools

_counter = itertools.count(1)


def _nonce():
    return next(_counter)


def create_member_payload(**overrides):
    n = _nonce()
    payload = {
        "email": f"member{n}@air.test",
        "full_name": f"Member {n}",
        "home_airport": "SFO",
    }
    payload.update(overrides)
    return payload


def create_flight_segment_payload(member_id, **overrides):
    payload = {
        "member_id": member_id,
        "origin": "SFO",
        "destination": "LAX",
        "fare_class": "ECONOMY",
        "distance_miles": 340,
        "base_fare_usd": 200,
        "scheduled_departure": "2026-01-05T08:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_award_booking_payload(member_id, **overrides):
    payload = {
        "member_id": member_id,
        "route_code": "SFO-NRT",
        "cabin": "ECONOMY",
        "pricing_mode": "FIXED",
    }
    payload.update(overrides)
    return payload


def create_flight_pool_payload(**overrides):
    payload = {
        "flight_number": "UA837",
        "departure_at": "2026-04-10T08:00:00.000Z",
        "premium_capacity": 1,
    }
    payload.update(overrides)
    return payload


def create_upgrade_request_payload(member_id, flight_pool_id, expected_flightpool_version, **overrides):
    payload = {
        "member_id": member_id,
        "flight_pool_id": flight_pool_id,
        "booked_fare_class": "ECONOMY",
        "expected_flightpool_version": expected_flightpool_version,
    }
    payload.update(overrides)
    return payload


def create_companion_certificate_payload(member_id, **overrides):
    payload = {
        "member_id": member_id,
        "valid_from": "2026-01-01T00:00:00.000Z",
        "valid_until": "2026-12-31T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_points_gift_payload(sender_id, recipient_id, amount=100, **overrides):
    payload = {
        "sender_id": sender_id,
        "recipient_id": recipient_id,
        "amount": amount,
    }
    payload.update(overrides)
    return payload


def create_status_match_payload(member_id, rival_tier="GOLD", valid_until="2026-12-31T23:59:59.000Z", **overrides):
    payload = {
        "member_id": member_id,
        "rival_tier": rival_tier,
        "valid_until": valid_until,
    }
    payload.update(overrides)
    return payload
