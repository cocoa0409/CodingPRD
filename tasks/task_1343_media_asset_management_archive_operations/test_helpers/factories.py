"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


DEFAULTS = {
    "BATCH_NAME": "B1",
    "SOURCE_DEPARTMENT": "NEWS",
    "ASSET_TITLE": "T",
    "ASSET_DESCRIPTION": "d",
    "MEDIA_TYPE": "VIDEO",
    "FORMAT_CLASS": "DIGITAL_FILE",
    "DURATION_SECONDS": 60,
    "SIZE_GB": 5,
    "RIGHTS_HOLDER": "ACME",
    "GRANT_TYPE": "BROADCAST",
    "TERRITORY": "DOMESTIC",
    "WINDOW_START": "2026-01-01T00:00:00Z",
    "WINDOW_END": "2027-01-01T00:00:00Z",
    "PURPOSE": "BROADCAST",
    "REQUESTED_DELIVERY_BY": "2026-12-01T00:00:00Z",
    "USAGE_TYPE": "BROADCAST",
    "MARKET_SIZE": 2_000_000,
    "DURATION_SECONDS_USED": 120,
    "AIRED_AT": "2026-08-01T00:00:00Z",
    "PERIOD_START": "2026-07-01T00:00:00Z",
    "PERIOD_END": "2026-08-01T00:00:00Z",
    "SCHEDULED_EXECUTION_DATE": "2026-08-02T00:00:00Z",
    "TICKET_START": "2026-08-01T00:00:00Z",
    "TICKET_END": "2026-08-01T02:00:00Z",
    "OUTPUT_FORMAT": "PRORES_FILE",
    "TARGET_TIER": "NEARLINE",
}


def create_staff_member_payload(**overrides) -> dict:
    defaults = {
        "email": f"user{_seq()}@x.com",
        "full_name": "Test User",
        "department": "NEWS",
    }
    defaults.update(overrides)
    return defaults


def create_ingest_batch_payload(**overrides) -> dict:
    defaults = {
        "batch_name": f"{DEFAULTS['BATCH_NAME']}-{_seq()}",
        "source_department": DEFAULTS["SOURCE_DEPARTMENT"],
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(ingest_batch_id: str, **overrides) -> dict:
    defaults = {
        "ingest_batch_id": ingest_batch_id,
        "title": DEFAULTS["ASSET_TITLE"],
        "description": DEFAULTS["ASSET_DESCRIPTION"],
        "media_type": DEFAULTS["MEDIA_TYPE"],
        "format_class": DEFAULTS["FORMAT_CLASS"],
        "duration_seconds": DEFAULTS["DURATION_SECONDS"],
        "size_gb": DEFAULTS["SIZE_GB"],
        "rights_holder": DEFAULTS["RIGHTS_HOLDER"],
        "keywords": ["k"],
        "content_rating": "G",
    }
    defaults.update(overrides)
    return defaults


def create_proxy_rendition_payload(asset_id: str, **overrides) -> dict:
    defaults = {"asset_id": asset_id}
    defaults.update(overrides)
    return defaults


def create_rights_grant_payload(asset_id: str, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "grant_type": DEFAULTS["GRANT_TYPE"],
        "territory": DEFAULTS["TERRITORY"],
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_legal_hold_payload(asset_id: str, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "matter_reference": f"CASE-{_seq()}",
        "reason": "litigation",
    }
    defaults.update(overrides)
    return defaults


def create_retention_policy_payload(**overrides) -> dict:
    defaults = {
        "media_type": DEFAULTS["MEDIA_TYPE"],
        "min_retention_years": 0,
    }
    defaults.update(overrides)
    return defaults


def create_disposal_order_payload(asset_id: str, expected_asset_version: int, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "scheduled_execution_date": DEFAULTS["SCHEDULED_EXECUTION_DATE"],
        "expected_asset_version": expected_asset_version,
    }
    defaults.update(overrides)
    return defaults


def create_retrieval_request_payload(asset_id: str, requester_id: str, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "requester_id": requester_id,
        "purpose": DEFAULTS["PURPOSE"],
        "requested_delivery_by": DEFAULTS["REQUESTED_DELIVERY_BY"],
    }
    defaults.update(overrides)
    return defaults


def create_usage_event_payload(asset_id: str, reported_by_id: str, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "reported_by_id": reported_by_id,
        "usage_type": DEFAULTS["USAGE_TYPE"],
        "market_size": DEFAULTS["MARKET_SIZE"],
        "duration_seconds_used": DEFAULTS["DURATION_SECONDS_USED"],
        "aired_at": DEFAULTS["AIRED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_royalty_statement_payload(**overrides) -> dict:
    defaults = {
        "rights_holder": DEFAULTS["RIGHTS_HOLDER"],
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_migration_job_payload(asset_id: str, expected_asset_version: int, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "target_tier": DEFAULTS["TARGET_TIER"],
        "expected_asset_version": expected_asset_version,
    }
    defaults.update(overrides)
    return defaults


def create_digitization_ticket_payload(asset_id: str, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "scheduled_start": DEFAULTS["TICKET_START"],
        "scheduled_end": DEFAULTS["TICKET_END"],
        "output_format": DEFAULTS["OUTPUT_FORMAT"],
    }
    defaults.update(overrides)
    return defaults


def create_workstation_payload(**overrides) -> dict:
    defaults = {
        "name": f"WS-{_seq()}",
        "supported_formats": ["BETACAM_SP"],
    }
    defaults.update(overrides)
    return defaults
