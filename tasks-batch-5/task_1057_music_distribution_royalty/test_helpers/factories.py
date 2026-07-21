"""Payload factories - one per entity, input fields only."""
from .constants import (
    DEFAULT_RELEASE_DATE, DEFAULT_EFFECTIVE_FROM, DEFAULT_SCHEDULED_SEND_AT, isrc, upc,
)


def create_subscription_plan_payload(**overrides) -> dict:
    defaults = {
        "code": "PRO",
        "name": "Pro",
        "annual_fee_cents": 2000,
        "included_release_slots": 5,
        "commission_bps": 1500,
        "allows_content_id": True,
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(**overrides) -> dict:
    defaults = {
        "code": "SPOTIFY",
        "name": "Spotify",
        "delivery_lead_days": 5,
        "requires_isrc": True,
        "requires_explicit_flag": True,
        "surcharge_bps": 0,
        "max_concurrent_deliveries": 2,
    }
    defaults.update(overrides)
    return defaults


def create_artist_payload(**overrides) -> dict:
    defaults = {
        "display_name": "Nova",
        "legal_name": "Nova LLC",
        "country_code": "US",
        "email": "nova@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(artist_id, plan_id, **overrides) -> dict:
    defaults = {"artist_id": artist_id, "plan_id": plan_id, "auto_renew": True}
    defaults.update(overrides)
    return defaults


def create_release_payload(artist_id, **overrides) -> dict:
    defaults = {
        "artist_id": artist_id,
        "title": "Aurora",
        "release_date": DEFAULT_RELEASE_DATE,
        "primary_genre": "Pop",
        "label_name": "Nova Rec",
    }
    defaults.update(overrides)
    return defaults


def create_track_payload(**overrides) -> dict:
    defaults = {
        "title": "Dawn",
        "duration_seconds": 210,
        "track_number": 1,
        "isrc": isrc(1),
        "explicit": False,
    }
    defaults.update(overrides)
    return defaults


def create_collaborator_payload(artist_id, **overrides) -> dict:
    defaults = {
        "artist_id": artist_id,
        "name": "Rae",
        "email": "rae@example.com",
        "country_code": "US",
        "tax_form_status": "VERIFIED",
        "payout_method": "PAYPAL",
    }
    defaults.update(overrides)
    return defaults


def create_split_sheet_payload(track_id, expected_track_version, **overrides) -> dict:
    defaults = {
        "track_id": track_id,
        "effective_from": DEFAULT_EFFECTIVE_FROM,
        "expected_track_version": expected_track_version,
    }
    defaults.update(overrides)
    return defaults


def create_split_share_payload(collaborator_id, share_bps, **overrides) -> dict:
    defaults = {"collaborator_id": collaborator_id, "share_bps": share_bps}
    defaults.update(overrides)
    return defaults


def create_delivery_payload(store_id, **overrides) -> dict:
    defaults = {"store_id": store_id, "scheduled_send_at": DEFAULT_SCHEDULED_SEND_AT}
    defaults.update(overrides)
    return defaults


def create_royalty_statement_payload(artist_id, period_start, period_end, **overrides) -> dict:
    defaults = {
        "artist_id": artist_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def royalty_line_payload(track_id, store_id, gross_cents, reported_at,
                         source="STREAMING", units=1000, **overrides) -> dict:
    defaults = {
        "track_id": track_id,
        "store_id": store_id,
        "units": units,
        "gross_cents": gross_cents,
        "source": source,
        "reported_at": reported_at,
    }
    defaults.update(overrides)
    return defaults


def create_tax_form_payload(collaborator_id, tax_year=2026, **overrides) -> dict:
    defaults = {"collaborator_id": collaborator_id, "tax_year": tax_year}
    defaults.update(overrides)
    return defaults


__all__ = [
    "create_subscription_plan_payload", "create_store_payload", "create_artist_payload",
    "create_subscription_payload", "create_release_payload", "create_track_payload",
    "create_collaborator_payload", "create_split_sheet_payload", "create_split_share_payload",
    "create_delivery_payload", "create_royalty_statement_payload", "royalty_line_payload",
    "create_tax_form_payload", "isrc", "upc",
]
