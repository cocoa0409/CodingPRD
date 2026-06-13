"""Payload factories — one per entity, input fields only. Each factory builds a
valid default payload and accepts **overrides for fields a test needs to
control.
"""
import uuid


def _unique_email(prefix: str = "client") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


# --- Artist (PRD §3.1) ---
def create_artist_payload(**overrides) -> dict:
    payload = {
        "display_name": "Test Artist",
        "discipline": "TATTOO",
        "hourly_rate_cents": 18000,
        "commission_pct": 0.70,
    }
    payload.update(overrides)
    return payload


# --- Client (PRD §3.2) ---
def create_client_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Client",
        "email": _unique_email(),
        "date_of_birth": "1990-01-01",
    }
    payload.update(overrides)
    return payload


def id_verification_payload(**overrides) -> dict:
    payload = {"id_document_type": "PASSPORT"}
    payload.update(overrides)
    return payload


# --- FlashDesign (PRD §3.3) ---
def create_flash_design_payload(artist_id: str, **overrides) -> dict:
    payload = {
        "artist_id": artist_id,
        "title": "Test Flash",
        "piece_price_cents": 55000,
        "estimated_minutes": 120,
    }
    payload.update(overrides)
    return payload


# --- CustomDesignRequest (PRD §3.4) ---
def create_custom_request_payload(artist_id: str, client_id: str, **overrides) -> dict:
    payload = {
        "artist_id": artist_id,
        "client_id": client_id,
        "brief": "Test custom brief",
    }
    payload.update(overrides)
    return payload


def quote_payload(**overrides) -> dict:
    payload = {
        "quoted_price_cents": 60000,
        "estimated_minutes": 180,
    }
    payload.update(overrides)
    return payload


# --- Chair (PRD §3.1) ---
def create_chair_payload(**overrides) -> dict:
    payload = {
        "label": "Test Station",
        "cleanup_buffer_minutes": 30,
    }
    payload.update(overrides)
    return payload


# --- Appointment (PRD §3.5) ---
def create_appointment_payload(artist_id: str, client_id: str, chair_id: str,
                               expected_chair_version: int, **overrides) -> dict:
    """Default builds a valid HOURLY hold (rate divisible by 4). Override
    pricing_mode / flash_design_id / custom_request_id / piece_price_cents etc.
    for PIECE or other variants."""
    payload = {
        "artist_id": artist_id,
        "client_id": client_id,
        "chair_id": chair_id,
        "expected_chair_version": expected_chair_version,
        "pricing_mode": "HOURLY",
        "hourly_rate_cents": 18000,
        "estimated_minutes": 180,
        "start_at": "2026-07-01T10:00:00Z",
        "end_at": "2026-07-01T13:00:00Z",
    }
    payload.update(overrides)
    return payload


# --- Deposit (PRD §3.6) ---
def deposit_payload(amount_cents: int, expected_appointment_version: int, **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "expected_appointment_version": expected_appointment_version,
    }
    payload.update(overrides)
    return payload


# --- ConsentWaiver (PRD §3.7) ---
def waiver_payload(client_id: str, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "medical_flags": [],
        "aftercare_acknowledged": True,
    }
    payload.update(overrides)
    return payload


# --- PortfolioItem (PRD §3.11) ---
def create_portfolio_item_payload(artist_id: str, appointment_id: str, **overrides) -> dict:
    payload = {
        "artist_id": artist_id,
        "appointment_id": appointment_id,
        "caption": "Test caption",
    }
    payload.update(overrides)
    return payload
