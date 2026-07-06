"""Payload factories — one per entity, input fields only."""

from .constants import (
    DEFAULT_NEIGHBORHOOD_CENTER_LAT,
    DEFAULT_NEIGHBORHOOD_CENTER_LNG,
    DEFAULT_NEIGHBORHOOD_RADIUS_M,
)


def create_neighborhood_payload(**overrides) -> dict:
    payload = {
        "name": "Test Neighborhood",
        "state_code": "CA",
        "center_lat": DEFAULT_NEIGHBORHOOD_CENTER_LAT,
        "center_lng": DEFAULT_NEIGHBORHOOD_CENTER_LNG,
        "radius_meters": DEFAULT_NEIGHBORHOOD_RADIUS_M,
    }
    payload.update(overrides)
    return payload


def create_resident_payload(neighborhood_id: str, **overrides) -> dict:
    payload = {
        "email": "resident@example.com",
        "display_name": "Test Resident",
        "home_address_line": "1 Test Ave",
        "home_lat": DEFAULT_NEIGHBORHOOD_CENTER_LAT,
        "home_lng": DEFAULT_NEIGHBORHOOD_CENTER_LNG,
        "primary_neighborhood_id": neighborhood_id,
    }
    payload.update(overrides)
    return payload


def create_verification_request_payload(resident_id: str, neighborhood_id: str, **overrides) -> dict:
    payload = {
        "resident_id": resident_id,
        "neighborhood_id": neighborhood_id,
        "proof_type": "UTILITY_BILL",
        "proof_reference": "proof-abc-123",
    }
    payload.update(overrides)
    return payload


def create_post_payload(author_resident_id: str, neighborhood_id: str, **overrides) -> dict:
    payload = {
        "author_resident_id": author_resident_id,
        "neighborhood_id": neighborhood_id,
        "category": "GENERAL",
        "title": "Test Post",
        "body": "Post body",
    }
    payload.update(overrides)
    return payload


def create_marketplace_listing_payload(seller_resident_id: str, neighborhood_id: str, **overrides) -> dict:
    payload = {
        "seller_resident_id": seller_resident_id,
        "neighborhood_id": neighborhood_id,
        "title": "Chair",
        "price_cents": 1000,
        "kind": "FOR_SALE",
    }
    payload.update(overrides)
    return payload


def create_incident_payload(reporter_resident_id: str, neighborhood_id: str, **overrides) -> dict:
    payload = {
        "reporter_resident_id": reporter_resident_id,
        "neighborhood_id": neighborhood_id,
        "incident_lat": DEFAULT_NEIGHBORHOOD_CENTER_LAT,
        "incident_lng": DEFAULT_NEIGHBORHOOD_CENTER_LNG,
        "severity": "WARNING",
        "category": "TRAFFIC_HAZARD",
        "description": "test incident",
        "occurred_at": "2026-06-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_civic_notice_payload(neighborhood_id: str, **overrides) -> dict:
    payload = {
        "neighborhood_id": neighborhood_id,
        "title": "Test Notice",
        "body": "Notice body",
        "notice_kind": "POLICE",
        "effective_from": "2026-06-10T00:00:00Z",
        "effective_until": "2026-06-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_flag_report_payload(reporter_resident_id: str, target_type: str, target_id: str, **overrides) -> dict:
    payload = {
        "reporter_resident_id": reporter_resident_id,
        "target_type": target_type,
        "target_id": target_id,
        "reason": "SPAM",
    }
    payload.update(overrides)
    return payload


def create_moderation_decision_payload(moderator_resident_id: str, flag_report_id: str,
                                       decision: str, expected_target_version: int,
                                       **overrides) -> dict:
    payload = {
        "moderator_resident_id": moderator_resident_id,
        "flag_report_id": flag_report_id,
        "decision": decision,
        "rationale": "test rationale",
        "expected_target_version": expected_target_version,
    }
    payload.update(overrides)
    return payload


def create_business_payload(owner_resident_id: str, neighborhood_id: str, **overrides) -> dict:
    payload = {
        "owner_resident_id": owner_resident_id,
        "name": "Test Business",
        "address_line": "1 Main St",
        "business_lat": DEFAULT_NEIGHBORHOOD_CENTER_LAT,
        "business_lng": DEFAULT_NEIGHBORHOOD_CENTER_LNG,
        "primary_neighborhood_id": neighborhood_id,
    }
    payload.update(overrides)
    return payload


def create_local_ad_payload(business_id: str, target_neighborhood_ids: list, **overrides) -> dict:
    payload = {
        "business_id": business_id,
        "target_neighborhood_ids": target_neighborhood_ids,
        "budget_cents": 5000,
        "bid_cents_per_impression": 100,
        "start_at": "2026-06-01T00:00:00Z",
        "end_at": "2026-06-30T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_group_payload(creator_resident_id: str, neighborhood_id: str, **overrides) -> dict:
    payload = {
        "creator_resident_id": creator_resident_id,
        "neighborhood_id": neighborhood_id,
        "name": "Test Group",
        "is_private": False,
    }
    payload.update(overrides)
    return payload


def create_event_payload(group_id: str, neighborhood_id: str, **overrides) -> dict:
    payload = {
        "group_id": group_id,
        "neighborhood_id": neighborhood_id,
        "title": "Test Event",
        "venue_lat": DEFAULT_NEIGHBORHOOD_CENTER_LAT,
        "venue_lng": DEFAULT_NEIGHBORHOOD_CENTER_LNG,
        "starts_at": "2026-06-10T12:00:00Z",
        "ends_at": "2026-06-10T14:00:00Z",
        "capacity": 10,
    }
    payload.update(overrides)
    return payload


def create_event_rsvp_payload(event_id: str, resident_id: str, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "resident_id": resident_id,
        "rsvp_status": "YES",
    }
    payload.update(overrides)
    return payload
