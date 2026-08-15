"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import TEST_DEFAULTS


def create_photographer_payload(**overrides) -> dict:
    """PRD §3.1: onboarding carries full_name, email, photographer_type,
    day_rate_cents, per_image_fee_cents, royalty_rate_per_use_cents;
    rights_reversion_months optional."""
    defaults = {
        "full_name": "Sam Staff",
        "email": "sam@acme.news",
        "photographer_type": "STAFF",
        "day_rate_cents": TEST_DEFAULTS["STAFF_DAY_RATE"],
        "per_image_fee_cents": TEST_DEFAULTS["STAFF_PER_IMAGE_FEE"],
        "royalty_rate_per_use_cents": TEST_DEFAULTS["ROYALTY_RATE_PER_USE"],
    }
    defaults.update(overrides)
    return defaults


def create_story_request_payload(**overrides) -> dict:
    """PRD §3.2: headline, slug (unique), needed_by, budget_cents."""
    defaults = {
        "headline": "Bridge fire",
        "slug": "bridge-fire",
        "needed_by": "2026-09-01T00:00:00Z",
        "budget_cents": TEST_DEFAULTS["STORY_BUDGET"],
    }
    defaults.update(overrides)
    return defaults


def commission_decision_payload(photographer_id: str, **overrides) -> dict:
    """PRD §3.2 COMMISSION branch: photographer_id, brief, shoot_start, shoot_end
    required; min_image_count / max_image_count optional."""
    defaults = {
        "decision": "COMMISSION",
        "photographer_id": photographer_id,
        "brief": "Cover the scene",
        "shoot_start": "2026-08-10T09:00:00Z",
        "shoot_end": "2026-08-11T17:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def wire_stock_decision_payload(image_id: str, **overrides) -> dict:
    """PRD §3.2 WIRE_STOCK branch: image_id referencing an existing cleared image."""
    defaults = {"decision": "WIRE_STOCK", "image_id": image_id}
    defaults.update(overrides)
    return defaults


def assignment_image_payload(**overrides) -> dict:
    """PRD §3.4: submission carries caption, credit_line, optionally keywords,
    has_identifiable_people, has_private_property, embargo_until."""
    defaults = {
        "caption": "Firefighters at dawn on the bridge",
        "credit_line": "Sam Staff / ACME News",
    }
    defaults.update(overrides)
    return defaults


def ingest_image_payload(**overrides) -> dict:
    """PRD §3.3: wire/stock ingest carries source_type, agency_name (required for
    WIRE/STOCK), base_license_fee_cents; caption/credit_line optional at ingest."""
    defaults = {
        "source_type": "WIRE",
        "agency_name": "WireCo",
        "base_license_fee_cents": TEST_DEFAULTS["WIRE_BASE_FEE"],
        "caption": "Flooded main street looking north",
        "credit_line": "WireCo Staff / WireCo",
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(expected_image_version: int, **overrides) -> dict:
    """PRD §3.5: usage_scope, valid_from, valid_to plus the OCC field
    expected_image_version (§2.7); territory/exclusive/story_request_id optional."""
    defaults = {
        "usage_scope": "DIGITAL",
        "valid_from": "2026-08-01T00:00:00Z",
        "valid_to": "2026-08-31T23:59:59Z",
        "expected_image_version": expected_image_version,
    }
    defaults.update(overrides)
    return defaults


def usage_run_payload(license_id: str, **overrides) -> dict:
    """PRD §3.7: license_id, channel, story_slug, published_at."""
    defaults = {
        "license_id": license_id,
        "channel": "DIGITAL",
        "story_slug": "flood-day-one",
        "published_at": "2026-08-03T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_release_payload(**overrides) -> dict:
    """PRD §3.6: subject_type, subject_name, document_ref, signed_at, expires_at?."""
    defaults = {
        "subject_type": "MODEL",
        "subject_name": "Actor A",
        "document_ref": "doc-123",
        "signed_at": "2026-07-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(image_id: str, **overrides) -> dict:
    """PRD §3.8: image_id, claimant_name, claim_type, description, claimed_amount_cents."""
    defaults = {
        "image_id": image_id,
        "claimant_name": "Pix Agency",
        "claim_type": "UNLICENSED_USE",
        "description": "Alleged unlicensed use",
        "claimed_amount_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_payment_run_payload(expected_photographer_version: int, **overrides) -> dict:
    """PRD §3.9: period_start, period_end plus the OCC field
    expected_photographer_version (§2.7)."""
    defaults = {
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
        "expected_photographer_version": expected_photographer_version,
    }
    defaults.update(overrides)
    return defaults
