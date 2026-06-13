"""Payload factories — one per write endpoint, input fields only.

Computed/system fields (status, kyc_tier, reserved_minor, the quote disclosure
figures, etc.) are never supplied; they are server-set.
"""
from .constants import (
    CANONICAL_MID_RATE_MICRO, CLOCK_ANCHOR_ISO, FX_EFFECTIVE_ISO,
)

# Canonical corridor C1 (US->PH) config block.
CANONICAL_CORRIDOR = {
    "name": "US->PH",
    "send_country": "US",
    "receive_country": "PH",
    "send_currency": "USD",
    "receive_currency": "PHP",
    "enabled_payout_methods": ["BANK"],
    "fx_margin_bps": 137,
    "fee_flat_minor": 199,
    "fee_pct_bps": 120,
    "fee_tier_threshold_minor": 100000,
    "fee_pct_tier2_bps": 70,
    "per_transfer_max_minor": 2000000,
    "rolling_window_hours": 24,
    "rolling_window_cap_minor": 4000000,
    "rate_lock_ttl_seconds": 1800,
}


def create_corridor_payload(**overrides) -> dict:
    defaults = dict(CANONICAL_CORRIDOR)
    defaults.update(overrides)
    return defaults


def create_fx_rate_payload(corridor_id: str, **overrides) -> dict:
    defaults = {
        "corridor_id": corridor_id,
        "mid_rate_micro": CANONICAL_MID_RATE_MICRO,
        "effective_at": FX_EFFECTIVE_ISO,
    }
    defaults.update(overrides)
    return defaults


def create_sender_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Sender",
        "country": "US",
        "date_of_birth": "1990-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_recipient_payload(sender_id: str, **overrides) -> dict:
    defaults = {
        "sender_id": sender_id,
        "full_name": "Test Recipient",
        "country": "PH",
        "payout_method": "BANK",
        "payout_account_ref": "PH-ACCT-1",
    }
    defaults.update(overrides)
    return defaults


def verify_sender_kyc_payload(kyc_tier: str = "TIER1", **overrides) -> dict:
    defaults = {"kyc_tier": kyc_tier}
    defaults.update(overrides)
    return defaults


def submit_kyc_payload(kyc_doc_ref: str = "DOC-1", **overrides) -> dict:
    defaults = {"kyc_doc_ref": kyc_doc_ref}
    defaults.update(overrides)
    return defaults


def decide_kyc_payload(decision: str = "APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_quote_payload(corridor_id: str, sender_id: str,
                         send_principal_minor: int = 50000,
                         payout_method: str = "BANK", **overrides) -> dict:
    defaults = {
        "corridor_id": corridor_id,
        "sender_id": sender_id,
        "send_principal_minor": send_principal_minor,
        "payout_method": payout_method,
    }
    defaults.update(overrides)
    return defaults


def create_transfer_payload(quote_id: str, recipient_id: str,
                            expected_quote_version: int, **overrides) -> dict:
    defaults = {
        "quote_id": quote_id,
        "recipient_id": recipient_id,
        "expected_quote_version": expected_quote_version,
    }
    defaults.update(overrides)
    return defaults


def decide_case_payload(decision: str, expected_case_version: int, **overrides) -> dict:
    defaults = {
        "decision": decision,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def provide_info_payload(note: str = "info", **overrides) -> dict:
    defaults = {"note": note}
    defaults.update(overrides)
    return defaults


def create_sanctions_list_payload(listed_name: str, listed_country: str,
                                  program: str = "OFAC-SDN", **overrides) -> dict:
    defaults = {
        "listed_name": listed_name,
        "listed_country": listed_country,
        "program": program,
    }
    defaults.update(overrides)
    return defaults


def report_outcome_payload(outcome: str, failure_reason: str = None, **overrides) -> dict:
    defaults = {"outcome": outcome}
    if failure_reason is not None:
        defaults["failure_reason"] = failure_reason
    defaults.update(overrides)
    return defaults


def create_refund_payload(transfer_id: str, reason: str, **overrides) -> dict:
    defaults = {
        "transfer_id": transfer_id,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str = CLOCK_ANCHOR_ISO, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults


def advance_clock_payload(seconds: int, **overrides) -> dict:
    defaults = {"seconds": seconds}
    defaults.update(overrides)
    return defaults
