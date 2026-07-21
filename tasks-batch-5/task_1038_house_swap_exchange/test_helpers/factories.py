"""Payload factories — one per endpoint body, input fields only."""
import uuid


def unique_email(prefix="user") -> str:
    """A unique, non-empty email so member registration never collides."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


# --- Members -----------------------------------------------------------------
def register_member_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email("member"),
        "full_name": "Test Member",
        "home_city": "Boston",
    }
    defaults.update(overrides)
    return defaults


def points_adjustment_payload(amount: int, **overrides) -> dict:
    defaults = {"amount": amount}
    defaults.update(overrides)
    return defaults


# --- Memberships -------------------------------------------------------------
def create_membership_payload(member_id: str, tier: str = "PLUS", **overrides) -> dict:
    defaults = {"member_id": member_id, "tier": tier}
    defaults.update(overrides)
    return defaults


# --- Verifications -----------------------------------------------------------
def create_verification_payload(member_id: str, verification_type: str = "IDENTITY",
                                document_ref: str = "doc-ref", **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "verification_type": verification_type,
        "document_ref": document_ref,
    }
    defaults.update(overrides)
    return defaults


def decide_verification_payload(decision: str = "APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


# --- Home Listings -----------------------------------------------------------
def create_home_listing_payload(owner_member_id: str, **overrides) -> dict:
    defaults = {
        "owner_member_id": owner_member_id,
        "title": "Test Cabin",
        "address_city": "Denver",
        "address_country": "US",
        "points_per_night": 100,
        "max_points_per_exchange": 10000,
        "capacity": 4,
    }
    defaults.update(overrides)
    return defaults


def create_availability_window_payload(start_date: str, end_date: str, **overrides) -> dict:
    defaults = {"start_date": start_date, "end_date": end_date}
    defaults.update(overrides)
    return defaults


# --- Exchange Requests -------------------------------------------------------
def create_exchange_request_payload(requester_member_id: str, target_listing_id: str,
                                    requested_start_date: str, requested_end_date: str,
                                    exchange_type: str = "POINTS", **overrides) -> dict:
    defaults = {
        "requester_member_id": requester_member_id,
        "target_listing_id": target_listing_id,
        "exchange_type": exchange_type,
        "requested_start_date": requested_start_date,
        "requested_end_date": requested_end_date,
    }
    defaults.update(overrides)
    return defaults


def counter_payload(requested_start_date: str, requested_end_date: str, **overrides) -> dict:
    defaults = {
        "requested_start_date": requested_start_date,
        "requested_end_date": requested_end_date,
    }
    defaults.update(overrides)
    return defaults


def accept_payload(availability_window_id: str, expected_listing_version: int, **overrides) -> dict:
    defaults = {
        "availability_window_id": availability_window_id,
        "expected_listing_version": expected_listing_version,
    }
    defaults.update(overrides)
    return defaults


# --- Damage Claims -----------------------------------------------------------
def create_damage_claim_payload(claimant_member_id: str, claimed_amount: int, **overrides) -> dict:
    defaults = {"claimant_member_id": claimant_member_id, "claimed_amount": claimed_amount}
    defaults.update(overrides)
    return defaults


def adjudicate_payload(decision: str = "APPROVE", assessed_amount=None, **overrides) -> dict:
    defaults = {"decision": decision}
    if assessed_amount is not None:
        defaults["assessed_amount"] = assessed_amount
    defaults.update(overrides)
    return defaults


# --- Disputes ----------------------------------------------------------------
def create_dispute_payload(opened_by_member_id: str, penalty_points: int,
                           reason: str = "conduct grievance", **overrides) -> dict:
    defaults = {
        "opened_by_member_id": opened_by_member_id,
        "reason": reason,
        "penalty_points": penalty_points,
    }
    defaults.update(overrides)
    return defaults


def resolve_dispute_payload(decision: str, resolution_note=None, **overrides) -> dict:
    defaults = {"decision": decision}
    if resolution_note is not None:
        defaults["resolution_note"] = resolution_note
    defaults.update(overrides)
    return defaults


# --- Clock -------------------------------------------------------------------
def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
