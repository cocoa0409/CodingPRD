"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "COORD_NAME": "Casey Coord",
    "COORD_LICENSE": "TC-1001",
    "AGENT_BROKERAGE": "Berkshire",
    "MONTHLY_FEE_CENTS": 29900,
    "INCLUDED_FILES_QUOTA": 1,
    "OVERAGE_FEE_CENTS": 34900,
    "PROPERTY_ADDRESS": "1 Main St",
    "EFFECTIVE_DATE": "2026-08-03",
    "CLOSING_DATE": "2026-08-31",
    "LIST_PRICE_CENTS": 45000000,
    "INSPECTION_OFFSET_DAYS": 7,
    "APPRAISAL_OFFSET_DAYS": 14,
    "FINANCING_OFFSET_DAYS": 21,
    "AMENDMENT_EFFECTIVE_FROM": "2026-08-10",
    "AMENDMENT_EFFECTIVE_TO": "2026-08-15",
    "COMM_BODY": "Please send the executed contract",
}

_counter = {"n": 0}


def _unique_email(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']}@tc.example"


def create_coordinator_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["COORD_NAME"],
        "email": _unique_email("coord"),
        "license_number": DEFAULTS["COORD_LICENSE"],
    }
    defaults.update(overrides)
    return defaults


def create_agent_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Seller Sam",
        "email": _unique_email("agent"),
        "brokerage": DEFAULTS["AGENT_BROKERAGE"],
    }
    defaults.update(overrides)
    return defaults


def create_template_payload(**overrides) -> dict:
    defaults = {
        "state_code": "TX",
        "contract_type": "LISTING_ONLY",
        "milestone_defs": [{"name": "Listing Paperwork", "offset_days": 5, "mandatory": False}],
        "required_doc_types": [],
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(**overrides) -> dict:
    defaults = {
        "monthly_fee_cents": DEFAULTS["MONTHLY_FEE_CENTS"],
        "included_files_quota": DEFAULTS["INCLUDED_FILES_QUOTA"],
        "overage_fee_cents": DEFAULTS["OVERAGE_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_file_payload(**overrides) -> dict:
    """Default is a PER_FILE LISTING_ONLY cash file (no financing offset)."""
    defaults = {
        "billing_model": "PER_FILE",
        "state_code": "TX",
        "contract_type": "LISTING_ONLY",
        "property_address": DEFAULTS["PROPERTY_ADDRESS"],
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
        "closing_date": DEFAULTS["CLOSING_DATE"],
        "list_price_cents": DEFAULTS["LIST_PRICE_CENTS"],
        "inspection_offset_days": DEFAULTS["INSPECTION_OFFSET_DAYS"],
        "appraisal_offset_days": DEFAULTS["APPRAISAL_OFFSET_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_purchase_file_payload(**overrides) -> dict:
    """PURCHASE_SALE variant with buyer agent and financing contingency."""
    defaults = create_file_payload(
        contract_type="PURCHASE_SALE",
        financing_offset_days=DEFAULTS["FINANCING_OFFSET_DAYS"],
    )
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides) -> dict:
    defaults = {"file_id": None, "doc_type": "EXECUTED_CONTRACT"}
    defaults.update(overrides)
    return defaults


def create_communication_payload(**overrides) -> dict:
    defaults = {
        "file_id": None,
        "party": "SELLER_AGENT",
        "direction": "OUTBOUND",
        "body": DEFAULTS["COMM_BODY"],
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(**overrides) -> dict:
    defaults = {
        "file_id": None,
        "expected_file_version": None,
        "effective_from": DEFAULTS["AMENDMENT_EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["AMENDMENT_EFFECTIVE_TO"],
    }
    defaults.update(overrides)
    return defaults
