"""Payload factories — one per creatable entity, input fields only (PRD §3)."""
from .constants import PARTIES, STANDARD


def create_file_payload(**overrides) -> dict:
    """PRD §3.1 create-file inputs; insurer_user_id is optional."""
    defaults = {
        "property_address": STANDARD["property_address"],
        "closing_date": STANDARD["closing_date"],
        "buyer_user_id": PARTIES["buyer"],
        "seller_user_id": PARTIES["seller"],
        "lender_user_id": PARTIES["lender"],
        "insurer_user_id": PARTIES["insurer"],
    }
    defaults.update(overrides)
    return defaults


def create_holdback_payload(**overrides) -> dict:
    """PRD §3.1 holdback agreement terms (escrow_file_id supplied by caller)."""
    defaults = {
        "escrow_file_id": overrides.pop("escrow_file_id", None),
        "repair_scope": STANDARD["repair_scope"],
        "repair_estimate_cents": STANDARD["repair_estimate_cents"],
        "contingency_pct": STANDARD["contingency_pct"],
        "funding_source": STANDARD["funding_source"],
        "overrun_responsibility": STANDARD["overrun_responsibility"],
        "expiration_terms": STANDARD["expiration_terms"],
        "work_deadline_date": STANDARD["work_deadline_date"],
        "hard_stop_date": STANDARD["hard_stop_date"],
        "exterior_work_flag": STANDARD["exterior_work_flag"],
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(**overrides) -> dict:
    """PRD §3.3 bid inputs."""
    defaults = {
        "holdback_id": overrides.pop("holdback_id", None),
        "amount_cents": STANDARD["bid_amount_cents"],
        "scope_text": STANDARD["bid_scope_text"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    """PRD §3.4 inspection scheduling inputs."""
    defaults = {
        "holdback_id": overrides.pop("holdback_id", None),
        "inspector_user_id": PARTIES["inspector"],
        "purpose": "DRAW_VERIFICATION",
        "scheduled_start": "2026-08-20T10:00:00Z",
        "scheduled_end": "2026-08-20T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_draw_request_payload(**overrides) -> dict:
    """PRD §3.5 draw request inputs."""
    defaults = {
        "holdback_id": overrides.pop("holdback_id", None),
        "amount_cents": 50000,
        "description": "Stage 1",
        "is_final": False,
    }
    defaults.update(overrides)
    return defaults


def create_extension_request_payload(**overrides) -> dict:
    """PRD §3.6 extension request inputs."""
    defaults = {
        "holdback_id": overrides.pop("holdback_id", None),
        "reason": "WEATHER_EXTERIOR",
        "requested_days": 5,
        "evidence_ref": "NOAA storm log",
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    """PRD §3.7 dispute inputs."""
    defaults = {
        "holdback_id": overrides.pop("holdback_id", None),
        "category": "WORK_QUALITY",
        "claimed_amount_cents": 50000,
        "statement": "Work not to code",
    }
    defaults.update(overrides)
    return defaults
