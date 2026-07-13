"""Payload factories — one per entity, input fields only."""


def create_contributor_payload(**overrides) -> dict:
    payload = {"display_name": "Test Contributor", "country_code": "US"}
    payload.update(overrides)
    return payload


def create_tax_form_payload(**overrides) -> dict:
    payload = {"form_type": "W9", "tax_id": "TAX-0001"}
    payload.update(overrides)
    return payload


def create_model_release_payload(**overrides) -> dict:
    payload = {"release_type": "MODEL", "releaser_name": "Jane Model"}
    payload.update(overrides)
    return payload


def create_asset_payload(contributor_id, **overrides) -> dict:
    payload = {
        "contributor_id": contributor_id,
        "title": "Test Asset",
        "media_type": "PHOTO",
        "content_category": "COMMERCIAL",
        "keywords": ["nature"],
        "perceptual_hash": "aaaa",
        "requires_release": False,
    }
    payload.update(overrides)
    return payload


def create_license_tier_payload(**overrides) -> dict:
    payload = {"code": "STANDARD", "base_price_cents": 1000}
    payload.update(overrides)
    return payload


def create_download_payload(asset_id, **overrides) -> dict:
    payload = {"asset_id": asset_id, "license_tier_code": "STANDARD", "buyer_reference": "buy-1"}
    payload.update(overrides)
    return payload


def create_exclusivity_window_payload(**overrides) -> dict:
    payload = {"start_at": "2026-03-01T00:00:00Z", "end_at": "2027-03-01T00:00:00Z"}
    payload.update(overrides)
    return payload


def create_earning_adjustment_payload(**overrides) -> dict:
    payload = {"amount_cents": 10000, "reason": "bonus"}
    payload.update(overrides)
    return payload


def create_payout_payload(expected_contributor_version, **overrides) -> dict:
    payload = {"expected_contributor_version": expected_contributor_version}
    payload.update(overrides)
    return payload


def create_takedown_payload(**overrides) -> dict:
    payload = {"claim_type": "COPYRIGHT", "claimant_name": "Acme Legal"}
    payload.update(overrides)
    return payload


def create_review_payload(**overrides) -> dict:
    payload = {"decision": "ACCEPT"}
    payload.update(overrides)
    return payload
