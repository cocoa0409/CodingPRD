"""
Request-body builders.

Each factory returns a complete, valid payload for one endpoint and accepts
keyword overrides, so a test can express "the same body but with one field
changed" without restating the whole thing. Every monetary amount is an integer
number of cents and every date is a bare ``YYYY-MM-DD`` string, matching the
contract.

Passing ``None`` for an optional key removes it from the payload entirely, which
is how a test asks for the server's declared default instead of an explicit
value.
"""

from typing import Any, Dict, Optional

from .constants import (
    APPOINTMENT_EXECUTOR,
    BASIS_DATE_OF_DEATH,
    BILLING_INTERVAL_ANNUAL,
    CATEGORY_CLOUD_STORAGE,
    DIRECTIVE_WILL_PROVISION,
    DOC_DEATH_CERTIFICATE,
    ELECTION_MEMORIALIZE,
    REFUND_POLICY_NONE,
    REQUEST_TYPE_CATALOG_ACCESS,
    SCOPE_CATALOG_AND_CONTENT,
    SCOPE_CATALOG_ONLY,
    SHARE_BP_TOTAL,
    SOURCE_WILL,
)

_SENTINEL = object()


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of None removes the key from the payload."""
    out = dict(base)
    for key, value in overrides.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


# ─── Platform ────────────────────────────────────────────────────────────────
def platform_payload(**overrides: Any) -> Dict[str, Any]:
    """A participating cloud-storage provider that permits everything."""
    base = {
        "name": "CloudVault",
        "platform_type": "CLOUD_STORAGE",
        "form_code": "CV-FORM-1",
        "review_window_days": 14,
        "refund_policy": REFUND_POLICY_NONE,
        "supports_online_tool": True,
        "supports_transfer": True,
        "supports_memorialization": True,
        "supports_deletion": True,
        "requires_court_order_for_content": False,
        "license_terminates_at_death": False,
        "transfer_fee_cents": 0,
        "request_fee_cents": 0,
    }
    return _merge(base, overrides)


def subscription_platform_payload(**overrides: Any) -> Dict[str, Any]:
    """A subscription provider that refunds pro rata by the day."""
    base = {
        "name": "StreamOne",
        "platform_type": "SUBSCRIPTION",
        "form_code": "SO-FORM-4",
        "review_window_days": 14,
        "refund_policy": "PRORATA_DAILY",
        "supports_online_tool": False,
        "supports_transfer": False,
        "supports_memorialization": False,
        "supports_deletion": True,
        "requires_court_order_for_content": False,
        "license_terminates_at_death": True,
        "transfer_fee_cents": 0,
        "request_fee_cents": 0,
    }
    return _merge(base, overrides)


def financial_platform_payload(**overrides: Any) -> Dict[str, Any]:
    """A financial provider that charges both fees and demands a court order."""
    base = {
        "name": "BankTrust",
        "platform_type": "FINANCIAL",
        "form_code": "BT-FORM-2",
        "review_window_days": 21,
        "refund_policy": REFUND_POLICY_NONE,
        "supports_online_tool": True,
        "supports_transfer": True,
        "supports_memorialization": False,
        "supports_deletion": False,
        "requires_court_order_for_content": True,
        "license_terminates_at_death": False,
        "transfer_fee_cents": 2500,
        "request_fee_cents": 30000,
    }
    return _merge(base, overrides)


def loyalty_platform_payload(**overrides: Any) -> Dict[str, Any]:
    """A loyalty provider that does allow points to move."""
    base = {
        "name": "SkyMiles",
        "platform_type": "LOYALTY",
        "form_code": "SM-FORM-7",
        "review_window_days": 30,
        "refund_policy": REFUND_POLICY_NONE,
        "supports_online_tool": False,
        "supports_transfer": True,
        "supports_memorialization": False,
        "supports_deletion": True,
        "requires_court_order_for_content": False,
        "license_terminates_at_death": False,
        "transfer_fee_cents": 7500,
        "request_fee_cents": 2000,
    }
    return _merge(base, overrides)


def social_platform_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "name": "SocialHub",
        "platform_type": "SOCIAL",
        "form_code": "SH-FORM-3",
        "review_window_days": 21,
        "refund_policy": REFUND_POLICY_NONE,
        "supports_online_tool": False,
        "supports_transfer": False,
        "supports_memorialization": True,
        "supports_deletion": True,
        "requires_court_order_for_content": False,
        "license_terminates_at_death": False,
        "transfer_fee_cents": 0,
        "request_fee_cents": 0,
    }
    return _merge(base, overrides)


def platform_patch_payload(**overrides: Any) -> Dict[str, Any]:
    """A provider update carries only the fields it means to change."""
    return dict(overrides)


# ─── Estate ──────────────────────────────────────────────────────────────────
def estate_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "decedent_name": "Rowan Ives",
        "date_of_death": "2026-02-14",
        "domicile_state": "CA",
        "court_case_number": "PR-2737-000",
    }
    return _merge(base, overrides)


def close_estate_payload(**overrides: Any) -> Dict[str, Any]:
    base = {"closing_statement": "All digital assets administered and accounted for."}
    return _merge(base, overrides)


# ─── Fiduciary ───────────────────────────────────────────────────────────────
def fiduciary_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "full_name": "Dana Ives",
        "appointment_type": APPOINTMENT_EXECUTOR,
        "court_reference": "APPT-2737-000",
    }
    return _merge(base, overrides)


# ─── Document ────────────────────────────────────────────────────────────────
def document_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "doc_type": DOC_DEATH_CERTIFICATE,
        "reference_number": "DC-000",
        "issued_on": "2026-02-16",
        "jurisdiction": "CA",
    }
    return _merge(base, overrides)


def letters_document_payload(fiduciary_id: str, **overrides: Any) -> Dict[str, Any]:
    base = {
        "doc_type": "LETTERS_OF_AUTHORITY",
        "reference_number": "LOA-000",
        "issued_on": "2026-03-01",
        "jurisdiction": "CA",
        "fiduciary_id": fiduciary_id,
    }
    return _merge(base, overrides)


def court_order_document_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "doc_type": "COURT_ORDER",
        "reference_number": "CO-000",
        "issued_on": "2026-04-01",
        "jurisdiction": "CA",
    }
    return _merge(base, overrides)


def document_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ─── AuthorityDirective ──────────────────────────────────────────────────────
def directive_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "directive_type": DIRECTIVE_WILL_PROVISION,
        "scope": SCOPE_CATALOG_AND_CONTENT,
        "instrument_reference": "Will article 7.2",
        "executed_on": "2025-06-01",
    }
    return _merge(base, overrides)


# ─── DigitalAsset ────────────────────────────────────────────────────────────
def digital_asset_payload(platform_id: str, **overrides: Any) -> Dict[str, Any]:
    base = {
        "platform_id": platform_id,
        "category": CATEGORY_CLOUD_STORAGE,
        "account_handle": "vault-primary",
        "quoted_value_cents": 400033,
    }
    return _merge(base, overrides)


def transferability_review_payload(**overrides: Any) -> Dict[str, Any]:
    base = {"review_note": "Provider policy re-read after a licence change."}
    return _merge(base, overrides)


# ─── SubscriptionTerm ────────────────────────────────────────────────────────
def subscription_term_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "term_start_date": "2026-01-01",
        "term_end_date": "2026-12-31",
        "billing_interval": BILLING_INTERVAL_ANNUAL,
        "period_fee_cents": 11999,
        "auto_renew": True,
    }
    return _merge(base, overrides)


# ─── PlatformRequest ─────────────────────────────────────────────────────────
def platform_request_payload(
    platform_id: str,
    death_certificate_document_id: str,
    letters_document_id: str,
    platform_form_code: str,
    **overrides: Any,
) -> Dict[str, Any]:
    base = {
        "platform_id": platform_id,
        "request_type": REQUEST_TYPE_CATALOG_ACCESS,
        "requested_scope": SCOPE_CATALOG_ONLY,
        "death_certificate_document_id": death_certificate_document_id,
        "letters_document_id": letters_document_id,
        "platform_form_code": platform_form_code,
    }
    return _merge(base, overrides)


def request_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ─── AuthorityGrant ──────────────────────────────────────────────────────────
def grant_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ─── BeneficiaryDesignation ──────────────────────────────────────────────────
def beneficiary_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "beneficiary_name": "Ada Ives",
        "share_bp": SHARE_BP_TOTAL,
        "source": SOURCE_WILL,
    }
    return _merge(base, overrides)


# ─── DispositionElection ─────────────────────────────────────────────────────
def election_payload(expected_asset_version: int, **overrides: Any) -> Dict[str, Any]:
    base = {
        "election": ELECTION_MEMORIALIZE,
        "expected_asset_version": expected_asset_version,
    }
    return _merge(base, overrides)


def election_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ─── CancellationOrder ───────────────────────────────────────────────────────
def order_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ─── RefundClaim ─────────────────────────────────────────────────────────────
def refund_claim_payload(
    claimed_period_start: str, claimed_period_end: str, **overrides: Any
) -> Dict[str, Any]:
    base = {
        "claimed_period_start": claimed_period_start,
        "claimed_period_end": claimed_period_end,
        "pursuit_cost_cents": 0,
    }
    return _merge(base, overrides)


def claim_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ─── ValuationRun ────────────────────────────────────────────────────────────
def valuation_run_payload(expected_estate_version: int, **overrides: Any) -> Dict[str, Any]:
    base = {
        "basis": BASIS_DATE_OF_DEATH,
        "expected_estate_version": expected_estate_version,
    }
    return _merge(base, overrides)


def run_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)
