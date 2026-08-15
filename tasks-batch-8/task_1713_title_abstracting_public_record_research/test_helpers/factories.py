"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "PROPERTY_ADDRESS": "100 Test St",
    "COUNTY": "Travis",
    "STATE_CODE": "TX",
    "LEGAL_DESCRIPTION": "LOT 1 BLK A",
    "SEARCH_PERIOD_YEARS": 30,
    "EFFECTIVE_DATE": "2026-01-15",
    "SEARCH_TYPE": "CHAIN_OF_TITLE",
    "WINDOW_START": "2026-08-01T09:00:00Z",
    "WINDOW_END": "2026-08-01T17:00:00Z",
    "INSTRUMENT_TYPE": "DEED",
    "GRANTOR": "A Smith",
    "GRANTEE": "B Jones",
    "RECORDING_DATE": "2010-01-01",
    "SURVEY_REFERENCE": "SURV-2026-001",
    "REPORT_TITLE": "Abstract Report",
    "REVIEW_SLOT_START": "2026-08-02T10:00:00Z",
    "REVIEW_SLOT_END": "2026-08-02T11:00:00Z",
    "CURATIVE_DESCRIPTION": "Cure the noted title defect",
    "RETRIEVAL_COUNTY": "Travis",
    "FEE_MODE": "PER_DOCUMENT",
}

_instrument_seq = {"n": 0}


def _next_instrument_number() -> str:
    _instrument_seq["n"] += 1
    return f"INST-{_instrument_seq['n']:05d}"


def create_order_payload(client_ref: str, **overrides) -> dict:
    """Required intake fields plus any optional tier overrides (PRD §3.1)."""
    defaults = {
        "client_ref": client_ref,
        "property_address": DEFAULTS["PROPERTY_ADDRESS"],
        "county": DEFAULTS["COUNTY"],
        "state_code": DEFAULTS["STATE_CODE"],
        "legal_description_text": DEFAULTS["LEGAL_DESCRIPTION"],
        "search_period_years": DEFAULTS["SEARCH_PERIOD_YEARS"],
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(order_id: str, abstracter_ref: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "abstracter_ref": abstracter_ref,
        "search_type": DEFAULTS["SEARCH_TYPE"],
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(order_id: str, assignment_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "assignment_id": assignment_id,
        "instrument_type": DEFAULTS["INSTRUMENT_TYPE"],
        "grantor_name": DEFAULTS["GRANTOR"],
        "grantee_name": DEFAULTS["GRANTEE"],
        "instrument_number": _next_instrument_number(),
        "recording_date": DEFAULTS["RECORDING_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_legal_check_payload(order_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "survey_reference": DEFAULTS["SURVEY_REFERENCE"],
        "checked_legal_description": DEFAULTS["LEGAL_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(order_id: str, expected_abstract_order_version: int, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "title": DEFAULTS["REPORT_TITLE"],
        "expected_abstract_order_version": expected_abstract_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_curative_payload(order_id: str, description: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "description": description,
    }
    defaults.update(overrides)
    return defaults


def create_retrieval_payload(order_id: str, record_document_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "record_document_id": record_document_id,
        "county": DEFAULTS["RETRIEVAL_COUNTY"],
        "fee_mode": DEFAULTS["FEE_MODE"],
    }
    defaults.update(overrides)
    return defaults
