"""Payload factories — one per entity, input fields only.

Defaults target a VISA DEBIT_CONSUMER program whose BIN window comfortably
contains the default server clock (2026-08-01T00:00:00Z).
"""
from typing import Any, Dict, List, Optional

DEFAULTS = {
    "PROGRAM_CODE": "PROG-1",
    "PRODUCT_CLASS": "DEBIT_CONSUMER",
    "NETWORK": "VISA",
    "CURRENCY_CODE": "USD",
    "PROGRAM_DAILY_CAP": 10_000_000,
    "BIN_PREFIX": "411111",
    "RANGE_SIZE": 1000,
    "EFFECTIVE_FROM": "2026-08-01T00:00:00Z",
    "EFFECTIVE_UNTIL": "2030-12-31T23:59:59Z",
    "ACCOUNT_CLASS": "INDIVIDUAL",
    "ACCOUNT_DAILY_CAP": 100_000,
    "EXTERNAL_ACCOUNT_REF": "ACCT-1",
    "EXPIRY_MONTH": 12,
    "EXPIRY_YEAR": 2030,
    "FORM_FACTOR": "PHYSICAL",
    "VENDOR_CODE": "VEND-1",
    "VENDOR_CAPABILITIES": ["EMV_CHIP"],
    "VENDOR_CAPACITY": 5000,
    "VENDOR_NETWORKS": ["VISA"],
    "BATCH_SCHEDULED_DATE": "2026-08-15",
    "BATCH_REQUESTED": 100,
    "BATCH_UNIT_COST": 100,
    "MANDATE_CODE": "VI-001",
    "MANDATE_TITLE": "Mandate",
    "MANDATE_EFFECTIVE_AT": "2026-09-01T00:00:00Z",
    "MANDATE_DEADLINE": "2026-12-01T00:00:00Z",
    "MANDATE_SEVERITY": "REQUIRED",
    "ACK_NOTES": "implementation notes",
    "CAMPAIGN_KIND": "EXPIRY_SWEEP",
    "CAMPAIGN_SCHEDULED_FOR": "2026-08-05T00:00:00Z",
    "CONVERSION_EXECUTION_AT": "2026-08-10T00:00:00Z",
}


def create_program_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "program_code": DEFAULTS["PROGRAM_CODE"],
        "product_class": DEFAULTS["PRODUCT_CLASS"],
        "network": DEFAULTS["NETWORK"],
        "currency_code": DEFAULTS["CURRENCY_CODE"],
        "daily_spend_cap_cents": DEFAULTS["PROGRAM_DAILY_CAP"],
    }
    defaults.update(overrides)
    return defaults


def create_bin_range_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "bin_prefix": DEFAULTS["BIN_PREFIX"],
        "range_size": DEFAULTS["RANGE_SIZE"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_until": DEFAULTS["EFFECTIVE_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "vendor_code": DEFAULTS["VENDOR_CODE"],
        "capability_flags": list(DEFAULTS["VENDOR_CAPABILITIES"]),
        "daily_capacity_cards": DEFAULTS["VENDOR_CAPACITY"],
        "supported_networks": list(DEFAULTS["VENDOR_NETWORKS"]),
        "is_active": True,
    }
    defaults.update(overrides)
    return defaults


def create_production_batch_payload(vendor_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "vendor_id": vendor_id,
        "scheduled_for_utc_date": DEFAULTS["BATCH_SCHEDULED_DATE"],
        "requested_card_count": DEFAULTS["BATCH_REQUESTED"],
        "unit_cost_cents": DEFAULTS["BATCH_UNIT_COST"],
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(program_id: str, external_account_ref: Optional[str] = None,
                            **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "program_id": program_id,
        "external_account_ref": external_account_ref or DEFAULTS["EXTERNAL_ACCOUNT_REF"],
        "account_class": DEFAULTS["ACCOUNT_CLASS"],
        "daily_spend_cap_cents": DEFAULTS["ACCOUNT_DAILY_CAP"],
    }
    defaults.update(overrides)
    return defaults


def issue_card_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "expiry_month": DEFAULTS["EXPIRY_MONTH"],
        "expiry_year": DEFAULTS["EXPIRY_YEAR"],
        "form_factor": DEFAULTS["FORM_FACTOR"],
    }
    defaults.update(overrides)
    return defaults


def create_authorization_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "amount_cents": 1000,
        "mcc": "5411",
        "country_code": "US",
    }
    defaults.update(overrides)
    return defaults


def create_velocity_rule_payload(subject_kind: str, subject_ref: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "subject_kind": subject_kind,
        "subject_ref": subject_ref,
        "rule_kind": "VELOCITY",
        "window_seconds": 60,
        "max_txn_count": 2,
        "max_amount_cents": 1_000_000,
        "priority_rank": 1,
    }
    defaults.update(overrides)
    return defaults


def create_mcc_block_rule_payload(subject_kind: str, subject_ref: str,
                                   mcc_list: Optional[List[str]] = None,
                                   **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "subject_kind": subject_kind,
        "subject_ref": subject_ref,
        "rule_kind": "MCC_BLOCK",
        "mcc_list": list(mcc_list) if mcc_list is not None else ["7995"],
        "priority_rank": 1,
    }
    defaults.update(overrides)
    return defaults


def create_mandate_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "network": DEFAULTS["NETWORK"],
        "mandate_code": DEFAULTS["MANDATE_CODE"],
        "title": DEFAULTS["MANDATE_TITLE"],
        "effective_at": DEFAULTS["MANDATE_EFFECTIVE_AT"],
        "compliance_deadline": DEFAULTS["MANDATE_DEADLINE"],
        "severity": DEFAULTS["MANDATE_SEVERITY"],
    }
    defaults.update(overrides)
    return defaults


def create_mandate_ack_payload(program_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "program_id": program_id,
        "implementation_notes": DEFAULTS["ACK_NOTES"],
    }
    defaults.update(overrides)
    return defaults


def create_reissue_campaign_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "campaign_kind": DEFAULTS["CAMPAIGN_KIND"],
        "scheduled_for": DEFAULTS["CAMPAIGN_SCHEDULED_FOR"],
        "selection_filter": {},
    }
    defaults.update(overrides)
    return defaults


def create_conversion_job_payload(target_program_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "target_program_id": target_program_id,
        "execution_at": DEFAULTS["CONVERSION_EXECUTION_AT"],
    }
    defaults.update(overrides)
    return defaults
