"""Payload factories — one per entity, input fields only (PRD §3 narratives)."""
import itertools

_seq = itertools.count(1)


def _unique(tag: str) -> str:
    return f"{tag}-{next(_seq)}"


def create_consumer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Consumer",
        "email": f"{_unique('consumer')}@example.com",
        "state_code": "OR",
    }
    defaults.update(overrides)
    return defaults


def create_business_payload(**overrides) -> dict:
    defaults = {
        "legal_name": _unique("Biz"),
        "home_state": "OR",
        "operates_in_states": ["OR"],
        "naics_code": "454110",
    }
    defaults.update(overrides)
    return defaults


def create_mediator_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Mediator",
        "employee_ref": _unique("EMP"),
    }
    defaults.update(overrides)
    return defaults


def create_mediation_room_payload(**overrides) -> dict:
    defaults = {
        "room_name": _unique("Room"),
        "capacity": 6,
        "location": "Salem",
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(consumer_id: str, business_id: str, **overrides) -> dict:
    defaults = {
        "consumer_id": consumer_id,
        "business_id": business_id,
        "incident_date": "2026-07-01",
        "incident_state": "OR",
        "category": "REFUND_REFUSAL",
        "description": "consumer complaint narrative",
        "amount_in_dispute_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_business_response_payload(**overrides) -> dict:
    defaults = {"response_text": "we will make it right"}
    defaults.update(overrides)
    return defaults


def create_review_payload(verdict: str = "SUFFICIENT") -> dict:
    return {"verdict": verdict}


def create_screen_payload(decision: str = "ACCEPT", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_mediation_session_payload(mediator_id: str, room_id: str, **overrides) -> dict:
    defaults = {
        "mediator_id": mediator_id,
        "room_id": room_id,
        "starts_at": "2026-08-10T10:00:00Z",
        "ends_at": "2026-08-10T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_settlement_offer_payload(offered_by_role: str, expected_complaint_version: int, **overrides) -> dict:
    defaults = {
        "offered_by_role": offered_by_role,
        "restitution_amount_cents": 1000,
        "expected_complaint_version": expected_complaint_version,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(expected_complaint_version: int) -> dict:
    return {"expected_complaint_version": expected_complaint_version}


def create_close_unresolved_payload(**overrides) -> dict:
    defaults = {
        "alternative_options": ["SMALL_CLAIMS"],
        "closure_summary": "mediation could not resolve the dispute",
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(**overrides) -> dict:
    defaults = {"reason": "pattern of harm under review"}
    defaults.update(overrides)
    return defaults


def create_restitution_payment_payload(business_id: str, amount_cents: int, **overrides) -> dict:
    defaults = {"business_id": business_id, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_scam_alert_payload(**overrides) -> dict:
    defaults = {
        "title": _unique("Alert"),
        "body": "public education content",
        "scam_category": "TECH_SUPPORT",
        "severity": "HIGH",
    }
    defaults.update(overrides)
    return defaults


def create_rating_method_payload(rating_method: str) -> dict:
    return {"rating_method": rating_method}
