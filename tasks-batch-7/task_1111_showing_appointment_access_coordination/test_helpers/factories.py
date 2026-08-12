"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_seller_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Seller {_n()}",
        "contact_email": f"seller{_n()}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_agent_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "full_name": f"Agent {i}",
        "license_number": f"LIC-{i:05d}",
        "brokerage_name": f"Brokerage {i}",
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(seller_id: str, **overrides) -> dict:
    defaults = {
        "seller_id": seller_id,
        "address": f"{_n()} Test Lane",
        "occupancy_type": "VACANT",
    }
    defaults.update(overrides)
    return defaults


def create_verification_case_payload(**overrides) -> dict:
    defaults = {"license_document_ref": f"doc-{_n()}"}
    defaults.update(overrides)
    return defaults


def create_blackout_window_payload(start_at: str, end_at: str, **overrides) -> dict:
    defaults = {"start_at": start_at, "end_at": end_at}
    defaults.update(overrides)
    return defaults


def create_showing_request_payload(listing_id: str, start_at: str, end_at: str, **overrides) -> dict:
    defaults = {"listing_id": listing_id, "start_at": start_at, "end_at": end_at}
    defaults.update(overrides)
    return defaults


def create_access_credential_payload(**overrides) -> dict:
    defaults = {"credential_type": "LOCKBOX_CODE"}
    defaults.update(overrides)
    return defaults


def create_feedback_payload(**overrides) -> dict:
    defaults = {"q1": 5, "q2": 5, "q3": 5, "q4": 5, "q5": 5}
    defaults.update(overrides)
    return defaults


def create_review_payload(decision: str = "APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults
