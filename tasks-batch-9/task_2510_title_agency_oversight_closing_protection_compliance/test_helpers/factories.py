"""Request payload builders.

Every builder emits a complete, PRD-valid body and accepts keyword overrides so
a test can perturb exactly one field. Fields the PRD marks unique — `tax_id`,
`state_code`, `account_ref`, `policy_number`, `order_number`, `transaction_ref`
and `license_number` — are drawn from module-level sequences so that a fixture
building several sibling rows never collides with itself.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS

# ---------------------------------------------------------------------------
# Unique-key sequences
# ---------------------------------------------------------------------------

_tax_ids = itertools.count(1)
_order_numbers = itertools.count(1)
_policy_numbers = itertools.count(1)
_transaction_refs = itertools.count(1)
_account_refs = itertools.count(1)
_license_numbers = itertools.count(1)
_legal_names = itertools.count(1)
_bank_names = itertools.count(1)

# "It is keyed by a two-letter `state_code`, unique across all state programs".
# The pool spans the whole two-letter space so a long session never exhausts it,
# and it cycles because uniqueness only has to hold within one server lifetime —
# the harness reboots the server (and therefore wipes every state program)
# before each test.
_STATE_CODE_POOL = [
    a + b
    for a in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for b in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
]
_state_codes = itertools.cycle(_STATE_CODE_POOL)


def next_tax_id() -> str:
    return f"TAX-{next(_tax_ids):05d}"


def next_state_code() -> str:
    """A fresh two-letter state code from the pool."""
    return next(_state_codes)


def next_order_number() -> str:
    return f"ORD-{next(_order_numbers):05d}"


def next_policy_number() -> str:
    return f"POL-{next(_policy_numbers):05d}"


def next_transaction_ref() -> str:
    return f"TXN-{next(_transaction_refs):05d}"


def next_account_ref() -> str:
    return f"ESCROW-{next(_account_refs):05d}"


def next_license_number() -> str:
    return f"LIC-{next(_license_numbers):05d}"


def next_legal_name() -> str:
    return f"Harbor Title Agency {next(_legal_names):03d}"


def next_bank_name() -> str:
    return f"First Trust Bank {next(_bank_names):03d}"


# ---------------------------------------------------------------------------
# Agencies (PRD §3.1)
# ---------------------------------------------------------------------------


def create_agency_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": next_legal_name(),
        "tax_id": next_tax_id(),
        "underwriting_authority_limit_cents": TEST_DEFAULTS[
            "UNDERWRITING_AUTHORITY_LIMIT_CENTS"
        ],
    }
    payload.update(overrides)
    return payload


def financial_review_payload(**overrides) -> Dict[str, Any]:
    """The four staged figures of PRD §3.1."""
    payload: Dict[str, Any] = {
        "submitted_eo_policy_limit_cents": TEST_DEFAULTS[
            "SUBMITTED_EO_POLICY_LIMIT_CENTS"
        ],
        "submitted_eo_expires_on": TEST_DEFAULTS["SUBMITTED_EO_EXPIRES_ON"],
        "submitted_net_worth_cents": TEST_DEFAULTS["SUBMITTED_NET_WORTH_CENTS"],
        "submitted_fidelity_bond_cents": TEST_DEFAULTS[
            "SUBMITTED_FIDELITY_BOND_CENTS"
        ],
    }
    payload.update(overrides)
    return payload


def financial_review_decision_payload(
    decision: str = "ACCEPT", note: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return payload


def appointment_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# State programs (PRD §3.2)
# ---------------------------------------------------------------------------


def create_state_program_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "state_code": overrides.pop("state_code", None) or next_state_code(),
        "cpl_permitted": True,
        "cpl_coverage_cap_cents": TEST_DEFAULTS["CPL_COVERAGE_CAP_CENTS"],
        "cpl_scope_allowed": ["FULL_SETTLEMENT", "LENDER_ONLY", "SELLER_PROCEEDS"],
        "premium_split_agency_pct": TEST_DEFAULTS["PREMIUM_SPLIT_AGENCY_PCT"],
        "policy_issuance_deadline_days": TEST_DEFAULTS[
            "POLICY_ISSUANCE_DEADLINE_DAYS"
        ],
        "three_way_tolerance_cents": TEST_DEFAULTS["THREE_WAY_TOLERANCE_CENTS"],
        "counsel_referral_threshold_cents": TEST_DEFAULTS[
            "COUNSEL_REFERRAL_THRESHOLD_CENTS"
        ],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Appointments (PRD §3.2)
# ---------------------------------------------------------------------------


def create_appointment_payload(
    agency_id: str, state_program_id: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "agency_id": agency_id,
        "state_program_id": state_program_id,
        "license_number": next_license_number(),
        "license_expires_on": TEST_DEFAULTS["LICENSE_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def license_verification_payload(decision: str = "VERIFY", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if decision == "VERIFY":
        payload["verified_license_number"] = overrides.pop(
            "verified_license_number", next_license_number()
        )
        payload["verified_expires_on"] = overrides.pop(
            "verified_expires_on", TEST_DEFAULTS["VERIFIED_EXPIRES_ON"]
        )
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Closing protection letters (PRD §3.3)
# ---------------------------------------------------------------------------


def request_letter_payload(
    agency_id: str,
    state_program_id: str,
    expected_agency_version: int,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "agency_id": agency_id,
        "state_program_id": state_program_id,
        "transaction_ref": next_transaction_ref(),
        "coverage_scope": "FULL_SETTLEMENT",
        "requested_coverage_cents": 30_000_000,
        "closing_date": "2026-08-20",
        "lender_name": "Bay Federal",
        "complex_title_flag": False,
        "expected_agency_version": expected_agency_version,
    }
    payload.update(overrides)
    return payload


def letter_state_payload(to_state: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Policy files (PRD §3.4)
# ---------------------------------------------------------------------------


def create_policy_file_payload(
    agency_id: str,
    state_program_id: str,
    expected_agency_version: int,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "agency_id": agency_id,
        "state_program_id": state_program_id,
        "order_number": next_order_number(),
        "closing_date": "2026-07-10",
        "liability_amount_cents": 40_000_000,
        "gross_premium_cents": 33_333,
        "complex_title_flag": False,
        "expected_agency_version": expected_agency_version,
    }
    payload.update(overrides)
    return payload


def issuance_state_payload(to_state: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


def transfer_state_payload(to_state: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Remittance (PRD §3.5)
# ---------------------------------------------------------------------------


def create_statement_payload(
    agency_id: str,
    period_start: str,
    period_end: str,
    expected_agency_version: int,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "agency_id": agency_id,
        "period_start": period_start,
        "period_end": period_end,
        "expected_agency_version": expected_agency_version,
    }
    payload.update(overrides)
    return payload


def create_line_payload(
    policy_file_id: str, reported_gross_premium_cents: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "policy_file_id": policy_file_id,
        "reported_gross_premium_cents": reported_gross_premium_cents,
    }
    payload.update(overrides)
    return payload


def statement_state_payload(to_state: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Escrow accounts and snapshots (PRD §3.6)
# ---------------------------------------------------------------------------


def create_escrow_account_payload(agency_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "agency_id": agency_id,
        "bank_name": next_bank_name(),
        "account_ref": next_account_ref(),
    }
    payload.update(overrides)
    return payload


def balance_snapshot_payload(**overrides) -> Dict[str, Any]:
    """A perfectly reconciled snapshot: every leg agrees, no unidentified funds."""
    payload: Dict[str, Any] = {
        "book_balance_cents": 10_000_000,
        "bank_balance_cents": 10_000_000,
        "outstanding_items_cents": 0,
        "trial_balance_cents": 10_000_000,
        "unidentified_funds_cents": 0,
        "aged_unidentified_over_90_cents": 0,
        "snapshot_as_of": "2026-07-31",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Escrow audits and findings (PRD §3.6, §3.7)
# ---------------------------------------------------------------------------


def create_escrow_audit_payload(
    agency_id: str, escrow_account_id: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "agency_id": agency_id,
        "escrow_account_id": escrow_account_id,
        "audit_type": "SCHEDULED",
        "as_of_date": "2026-07-31",
    }
    payload.update(overrides)
    return payload


def audit_state_payload(to_state: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


def create_finding_payload(
    code: str, exposure_cents: int, narrative: str = "Auditor narrative", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code,
        "exposure_cents": exposure_cents,
        "narrative": narrative,
    }
    payload.update(overrides)
    return payload


def finding_state_payload(to_state: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Claims (PRD §3.8)
# ---------------------------------------------------------------------------


def create_claim_payload(
    agency_id: str,
    policy_file_id: str,
    cause_code: str = "AGENCY_ERROR",
    loss_amount_cents: int = 40_000_000,
    notice_date: str = "2026-07-28",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "agency_id": agency_id,
        "policy_file_id": policy_file_id,
        "cause_code": cause_code,
        "loss_amount_cents": loss_amount_cents,
        "notice_date": notice_date,
    }
    payload.update(overrides)
    return payload


def claim_state_payload(to_state: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def without(payload: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    """A copy of `payload` with `keys` removed, for required-field probes."""
    return {k: v for k, v in payload.items() if k not in keys}


def scopes(*values: str) -> List[str]:
    """A `cpl_scope_allowed` array built from the three permitted members."""
    return list(values)
