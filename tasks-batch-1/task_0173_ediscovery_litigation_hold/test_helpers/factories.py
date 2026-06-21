"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "CAPTION": "Acme v. Beta",
    "BATES_PREFIX": "ABC",
    "FULL_NAME": "Alice Custodian",
    "EMAIL": "alice@example.com",
    "HOLD_TITLE": "Preservation Hold Notice",
    "HOLD_INSTRUCTIONS": "Preserve all relevant data.",
    "ACK_DEADLINE": "2026-06-10T00:00:00Z",
    "SOURCE_LABEL": "Exchange Mailbox",
    "RANGE_START": "2026-06-01T00:00:00Z",
    "RANGE_END": "2026-06-30T00:00:00Z",
    "EXPECTED_DOC_COUNT": 10,
    "CONTENT_HASH": "aa",
    "PAGE_COUNT": 1,
    "BATCH_NAME": "Review Batch 1",
    "CLAWBACK_REASON": "inadvertent privileged production",
}


def create_matter_payload(**overrides) -> dict:
    payload = {
        "caption": DEFAULTS["CAPTION"],
        "bates_prefix": DEFAULTS["BATES_PREFIX"],
    }
    payload.update(overrides)
    return payload


def create_custodian_payload(matter_id, **overrides) -> dict:
    payload = {
        "matter_id": matter_id,
        "full_name": DEFAULTS["FULL_NAME"],
        "email": DEFAULTS["EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_legal_hold_payload(matter_id, **overrides) -> dict:
    payload = {
        "matter_id": matter_id,
        "title": DEFAULTS["HOLD_TITLE"],
        "instructions": DEFAULTS["HOLD_INSTRUCTIONS"],
        "ack_deadline": DEFAULTS["ACK_DEADLINE"],
    }
    payload.update(overrides)
    return payload


def create_collection_scope_payload(matter_id, custodian_id, **overrides) -> dict:
    payload = {
        "matter_id": matter_id,
        "custodian_id": custodian_id,
        "source_label": DEFAULTS["SOURCE_LABEL"],
        "range_start": DEFAULTS["RANGE_START"],
        "range_end": DEFAULTS["RANGE_END"],
        "expected_doc_count": DEFAULTS["EXPECTED_DOC_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_document_payload(scope_id, **overrides) -> dict:
    payload = {
        "scope_id": scope_id,
        "content_hash": DEFAULTS["CONTENT_HASH"],
        "page_count": DEFAULTS["PAGE_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_processing_job_payload(matter_id, scope_id, **overrides) -> dict:
    payload = {
        "matter_id": matter_id,
        "scope_id": scope_id,
    }
    payload.update(overrides)
    return payload


def create_review_batch_payload(matter_id, **overrides) -> dict:
    payload = {
        "matter_id": matter_id,
        "name": DEFAULTS["BATCH_NAME"],
    }
    payload.update(overrides)
    return payload


def add_review_payload(document_id, **overrides) -> dict:
    payload = {"document_id": document_id}
    payload.update(overrides)
    return payload


def decide_review_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_production_set_payload(matter_id, source_batch_id, **overrides) -> dict:
    payload = {
        "matter_id": matter_id,
        "source_batch_id": source_batch_id,
    }
    payload.update(overrides)
    return payload


def add_production_item_payload(document_id, **overrides) -> dict:
    payload = {"document_id": document_id}
    payload.update(overrides)
    return payload


def create_clawback_payload(
    matter_id, production_item_id, expected_production_set_version, **overrides
) -> dict:
    payload = {
        "matter_id": matter_id,
        "production_item_id": production_item_id,
        "reason": DEFAULTS["CLAWBACK_REASON"],
        "expected_production_set_version": expected_production_set_version,
    }
    payload.update(overrides)
    return payload
