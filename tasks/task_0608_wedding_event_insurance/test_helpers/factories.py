"""Payload factories — one per entity, input fields only."""
from . import constants as C


def coverage_product_payload(**overrides) -> dict:
    """A CANCELLATION/STANDARD product by default (the canonical CANC_STD product)."""
    defaults = {
        "coverage_type": "CANCELLATION",
        "tier": "STANDARD",
        "base_premium_cents": C.CANC_BASE_PREMIUM_CENTS,
        "per_guest_premium_cents": C.CANC_PER_GUEST_CENTS,
        "coverage_limit_cents": C.CANC_LIMIT_CENTS,
        "deposit_sublimit_pct": C.CANC_DEPOSIT_SUBLIMIT_PCT,
    }
    defaults.update(overrides)
    return defaults


def liability_product_payload(**overrides) -> dict:
    defaults = {
        "coverage_type": "LIABILITY",
        "tier": "STANDARD",
        "base_premium_cents": C.LIAB_BASE_PREMIUM_CENTS,
        "per_guest_premium_cents": C.LIAB_PER_GUEST_CENTS,
        "coverage_limit_cents": C.LIAB_LIMIT_CENTS,
        "deposit_sublimit_pct": C.LIAB_DEPOSIT_SUBLIMIT_PCT,
    }
    defaults.update(overrides)
    return defaults


def liquor_product_payload(**overrides) -> dict:
    defaults = {
        "coverage_type": "LIQUOR_LIABILITY",
        "tier": "STANDARD",
        "base_premium_cents": C.LIQ_BASE_PREMIUM_CENTS,
        "per_guest_premium_cents": C.LIQ_PER_GUEST_CENTS,
        "coverage_limit_cents": C.LIQ_LIMIT_CENTS,
        "deposit_sublimit_pct": 1.0,
        "liquor_required": True,
    }
    defaults.update(overrides)
    return defaults


def vendor_payload(**overrides) -> dict:
    """A VENUE vendor by default."""
    defaults = {
        "legal_name": "Grand Hall",
        "category": "VENUE",
        "deposit_paid_cents": 800000,
    }
    defaults.update(overrides)
    return defaults


def caterer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Tasty Catering",
        "category": "CATERER",
        "deposit_paid_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def force_majeure_payload(**overrides) -> dict:
    defaults = {
        "peril_name": "Hurricane Della",
        "peril_type": "NAMED_STORM",
        "cutoff_at": "2026-07-01T00:00:00Z",
        "landfall_at": "2026-08-01T19:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def policy_payload(**overrides) -> dict:
    defaults = {
        "policy_form": "SINGLE_EVENT",
        "serves_alcohol": False,
    }
    defaults.update(overrides)
    return defaults


def event_profile_payload(venue_vendor_id, **overrides) -> dict:
    defaults = {
        "event_name": "Smith Wedding",
        "venue_vendor_id": venue_vendor_id,
        "expected_attendance": C.DEFAULT_ATTENDANCE,
        "event_start_at": "2026-08-01T18:00:00Z",
        "event_end_at": "2026-08-01T23:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def coverage_payload(coverage_product_id, **overrides) -> dict:
    defaults = {"coverage_product_id": coverage_product_id}
    defaults.update(overrides)
    return defaults


def rider_payload(rider_type="RINGS", scheduled_value_cents=1200000, **overrides) -> dict:
    defaults = {
        "rider_type": rider_type,
        "scheduled_value_cents": scheduled_value_cents,
    }
    defaults.update(overrides)
    return defaults


def certificate_payload(vendor_id, additional_insured_name="Grand Hall LLC", **overrides) -> dict:
    defaults = {
        "vendor_id": vendor_id,
        "additional_insured_name": additional_insured_name,
    }
    defaults.update(overrides)
    return defaults


def endorsement_payload(endorsement_type, payload_json, **overrides) -> dict:
    defaults = {
        "endorsement_type": endorsement_type,
        "payload_json": payload_json,
    }
    defaults.update(overrides)
    return defaults


def claim_payload(coverage_id, claim_type, claimed_amount_cents, **overrides) -> dict:
    defaults = {
        "coverage_id": coverage_id,
        "claim_type": claim_type,
        "claimed_amount_cents": claimed_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def claim_document_payload(doc_type="INVOICE", file_uri="s3://docs/doc.pdf", **overrides) -> dict:
    defaults = {
        "doc_type": doc_type,
        "file_uri": file_uri,
    }
    defaults.update(overrides)
    return defaults
