"""Payload factories — one per entity, input fields only."""
import uuid

from .constants import WINDOW_OPEN, WINDOW_CLOSE, BENEFIT_START, BENEFIT_END


def unique_email(prefix="user"):
    """Generate a globally-unique email so a single test never collides on
    the consumer email uniqueness constraint."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def unique_case_id(prefix="CASE"):
    return f"{prefix}_{uuid.uuid4().hex[:8].upper()}"


def create_program_payload(**overrides) -> dict:
    """Input fields for POST /programs.

    Optional fields (eligibility_min_purchase_cents, requires_proof,
    min_documents) are included with typical values here; tests that exercise
    default-application omit them explicitly.
    """
    defaults = {
        "name": "Test Program",
        "settlement_case_id": unique_case_id(),
        "category": "PRODUCT_REBATE",
        "distribution_method": "FIXED",
        "fund_total_cents": 100000,
        "advertised_amount_cents": 20000,
        "per_claim_cap_cents": 30000,
        "eligibility_min_purchase_cents": 5000,
        "requires_proof": True,
        "min_documents": 1,
        "claim_window_open_at": WINDOW_OPEN,
        "claim_window_close_at": WINDOW_CLOSE,
    }
    defaults.update(overrides)
    return defaults


def create_consumer_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email(),
        "full_name": "Test Consumer",
    }
    defaults.update(overrides)
    return defaults


def create_match_payload(consumer_id, program_id, **overrides) -> dict:
    defaults = {"consumer_id": consumer_id, "program_id": program_id}
    defaults.update(overrides)
    return defaults


def create_claim_payload(consumer_id, program_id, **overrides) -> dict:
    defaults = {
        "consumer_id": consumer_id,
        "program_id": program_id,
        "benefit_period_start": BENEFIT_START,
        "benefit_period_end": BENEFIT_END,
        "claimed_amount_cents": 25000,
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides) -> dict:
    defaults = {"doc_type": "RECEIPT", "file_ref": "receipt-ref"}
    defaults.update(overrides)
    return defaults


def create_fraud_flag_payload(**overrides) -> dict:
    defaults = {"reason": "SUSPICIOUS_DOCS"}
    defaults.update(overrides)
    return defaults
