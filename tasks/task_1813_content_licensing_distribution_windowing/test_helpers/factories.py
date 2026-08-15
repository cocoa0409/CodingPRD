"""Payload factories — one per creatable resource, input fields only."""

from .constants import (
    DEFAULT_METADATA_SPEC,
    DEFAULT_SELLABLE_FROM,
    DEFAULT_SELLABLE_TO,
    TEST_DEFAULTS,
)


def create_title_payload(**overrides) -> dict:
    defaults = {
        "title_code": "T1",
        "name": "Test Title",
        "content_type": "FILM",
        "original_language": "en",
        "production_year": 2024,
    }
    defaults.update(overrides)
    return defaults


def create_rights_holder_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Holder",
        "payee_reference": "PAY-1",
        "royalty_share_pct": TEST_DEFAULTS["HOLDER_SHARE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_platform_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Platform",
        "platform_type": "SVOD",
        "metadata_spec_version": DEFAULT_METADATA_SPEC,
        "required_asset_profiles": ["4K_HDR"],
    }
    defaults.update(overrides)
    return defaults


def create_rights_slot_payload(title_id, rights_holder_id, **overrides) -> dict:
    defaults = {
        "title_id": title_id,
        "rights_holder_id": rights_holder_id,
        "territory_code": "US",
        "language_code": "en",
        "window_type": "SVOD",
        "sellable_from": DEFAULT_SELLABLE_FROM,
        "sellable_to": DEFAULT_SELLABLE_TO,
    }
    defaults.update(overrides)
    return defaults


def package_line_payload(slot_id, **overrides) -> dict:
    """One embedded offer line: proposed license terms for a slot."""
    defaults = {
        "slot_id": slot_id,
        "license_start": "2026-09-01T00:00:00Z",
        "license_end": "2026-12-01T00:00:00Z",
        "exclusive": False,
        "fee_model": "FLAT_FEE",
        "flat_fee_cents": TEST_DEFAULTS["FLAT_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_avail_package_payload(platform_id, lines, **overrides) -> dict:
    defaults = {
        "platform_id": platform_id,
        "name": "Test Package",
        "offer_expires_at": TEST_DEFAULTS["OFFER_EXPIRES_AT"],
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(slot_id, platform_id, **overrides) -> dict:
    defaults = {
        "slot_id": slot_id,
        "platform_id": platform_id,
        "license_start": "2026-09-01T00:00:00Z",
        "license_end": "2026-12-01T00:00:00Z",
        "exclusive": False,
        "fee_model": "FLAT_FEE",
        "flat_fee_cents": TEST_DEFAULTS["FLAT_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_delivery_batch_payload(license_id, **overrides) -> dict:
    defaults = {
        "license_id": license_id,
        "asset_manifest": ["4K_HDR"],
        "metadata_spec_version": DEFAULT_METADATA_SPEC,
    }
    defaults.update(overrides)
    return defaults


def resubmit_delivery_batch_payload(asset_manifest, metadata_spec_version) -> dict:
    return {
        "asset_manifest": asset_manifest,
        "metadata_spec_version": metadata_spec_version,
    }


def create_revenue_report_payload(period_start, period_end, gross_revenue_cents,
                                  expected_license_version) -> dict:
    return {
        "period_start": period_start,
        "period_end": period_end,
        "gross_revenue_cents": gross_revenue_cents,
        "expected_license_version": expected_license_version,
    }


def create_royalty_statement_payload(rights_holder_id, period_start, period_end,
                                     attribution_mode="BY_REPORT_DATE") -> dict:
    return {
        "rights_holder_id": rights_holder_id,
        "period_start": period_start,
        "period_end": period_end,
        "attribution_mode": attribution_mode,
    }
