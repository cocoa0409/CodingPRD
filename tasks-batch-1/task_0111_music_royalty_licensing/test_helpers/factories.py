"""Payload factories — one per entity, input fields only.

Required fields (no PRD default) are always present; optional fields
(minimum_payout_cents, withholding_pct, recoupment_pct, gross_revenue_cents,
counter_fee_cents) are only included when supplied as overrides.
"""

_ISWC_SEQ = [0]
_ISRC_SEQ = [0]


def next_iswc() -> str:
    _ISWC_SEQ[0] += 1
    return f"T-{_ISWC_SEQ[0]:09d}-0"


def next_isrc() -> str:
    _ISRC_SEQ[0] += 1
    return f"USTST{_ISRC_SEQ[0]:07d}"


def create_rightsholder_payload(**overrides) -> dict:
    """Required: legal_name, party_type, payee_country.
    Optional: minimum_payout_cents (default 5000), withholding_pct (default 0)."""
    defaults = {
        "legal_name": "Test Party",
        "party_type": "WRITER",
        "payee_country": "US",
    }
    defaults.update(overrides)
    return defaults


def create_work_payload(**overrides) -> dict:
    """Required: title, iswc, pro_affiliation, duration_seconds."""
    defaults = {
        "title": "Test Work",
        "iswc": next_iswc(),
        "pro_affiliation": "ASCAP",
        "duration_seconds": 180,
    }
    defaults.update(overrides)
    return defaults


def create_composition_share_payload(**overrides) -> dict:
    """Required: work_id, rightsholder_id, role, split_bps."""
    defaults = {
        "role": "WRITER",
        "split_bps": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_recording_payload(**overrides) -> dict:
    """Required: work_id, isrc, title, release_type, duration_seconds."""
    defaults = {
        "isrc": next_isrc(),
        "title": "Test Recording",
        "release_type": "STREAMING",
        "duration_seconds": 180,
    }
    defaults.update(overrides)
    return defaults


def create_recording_share_payload(**overrides) -> dict:
    """Required: recording_id, rightsholder_id, split_bps."""
    defaults = {
        "split_bps": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_rights_window_payload(**overrides) -> dict:
    """Required: recording_id, territory, rights_type, term_start, term_end."""
    defaults = {
        "territory": "US",
        "rights_type": "PERFORMANCE",
        "term_start": "2026-01-01T00:00:00.000Z",
        "term_end": "2026-02-01T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_usage_event_payload(**overrides) -> dict:
    """Required: recording_id, usage_type, territory, occurred_at, quantity.
    Optional: gross_revenue_cents (used for PERFORMANCE; ignored for MECHANICAL)."""
    defaults = {
        "usage_type": "PERFORMANCE",
        "territory": "US",
        "occurred_at": "2026-01-15T00:00:00.000Z",
        "quantity": 1000,
        "gross_revenue_cents": 200000,
    }
    defaults.update(overrides)
    return defaults


def create_sync_license_payload(**overrides) -> dict:
    """Required: recording_id, licensee_id, media_type, territory, term_months, base_fee_cents."""
    defaults = {
        "media_type": "FILM",
        "territory": "US",
        "term_months": 24,
        "base_fee_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_advance_payload(**overrides) -> dict:
    """Required: rightsholder_id, principal_cents.
    Optional: recoupment_pct (default 1.0)."""
    defaults = {
        "principal_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(**overrides) -> dict:
    """Required: rightsholder_id, period_start, period_end."""
    defaults = {
        "period_start": "2026-01-01T00:00:00.000Z",
        "period_end": "2026-02-01T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults
