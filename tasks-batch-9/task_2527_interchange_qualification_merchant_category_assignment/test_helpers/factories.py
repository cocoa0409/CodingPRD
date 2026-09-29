"""Payload factories.

Every factory returns ONLY client-supplied input fields, exactly as the PRD
workflow narratives declare them. Server-owned fields (`id`, `created_at`,
`updated_at`, `version`, statuses, counters, derived money) are never included
— the service owns them and a test that sends them is testing the wrong thing.
"""
from .constants import TEST_DEFAULTS


def _apply(payload: dict, overrides: dict) -> dict:
    """Merge overrides, and let a caller delete a field by passing None for a
    key whose absence is what the test is exercising."""
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    """Sentinel: pass `OMIT` as an override value to drop the field entirely."""

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "OMIT"


_OMIT = _Omit()
OMIT = _OMIT


# --- Section 3.1: reference data -------------------------------------------

def make_processing_platform_payload(**overrides) -> dict:
    return _apply(
        {
            "name": TEST_DEFAULTS["PLATFORM_NAME"],
            "region_code": TEST_DEFAULTS["REGION_CODE"],
            "max_concurrent_windows": TEST_DEFAULTS["MAX_CONCURRENT_WINDOWS"],
            "blackout_buffer_days": TEST_DEFAULTS["BLACKOUT_BUFFER_DAYS"],
        },
        overrides,
    )


def make_acquirer_payload(platform_id: str, **overrides) -> dict:
    return _apply(
        {
            "name": TEST_DEFAULTS["ACQUIRER_NAME"],
            "bin_prefix": TEST_DEFAULTS["BIN_PREFIX"],
            "platform_id": platform_id,
            "country_code": TEST_DEFAULTS["COUNTRY_CODE"],
            "settlement_currency": TEST_DEFAULTS["SETTLEMENT_CURRENCY"],
        },
        overrides,
    )


def make_mcc_definition_payload(
    mcc_code: str = "5411",
    business_type_key: str = TEST_DEFAULTS["BUSINESS_TYPE_KEY"],
    **overrides,
) -> dict:
    return _apply(
        {
            "mcc_code": mcc_code,
            "description": f"Category {mcc_code}",
            "business_type_key": business_type_key,
            "program_eligibility": [],
            "requires_documentation": False,
            "high_risk": False,
        },
        overrides,
    )


def make_fx_rate_payload(
    base_currency: str,
    quote_currency: str,
    effective_from: str,
    **overrides,
) -> dict:
    return _apply(
        {
            "base_currency": base_currency,
            "quote_currency": quote_currency,
            "rate": 1.0,
            "markup_bps": 0,
            "effective_from": effective_from,
        },
        overrides,
    )


# --- Section 3.2: rate programs, versions, implementation windows ----------

def make_rate_program_payload(
    program_code: str = "CPS_RETAIL_STD",
    category: str = "CPS_RETAIL",
    eligible_mcc_codes=None,
    **overrides,
) -> dict:
    return _apply(
        {
            "program_code": program_code,
            "name": f"Program {program_code}",
            "category": category,
            "eligible_mcc_codes": (
                ["5411"] if eligible_mcc_codes is None else eligible_mcc_codes
            ),
            "base_rate_bps": 165,
            "per_item_fee_cents": 4,
            "requires_data_elements": [],
            "max_clearing_delay_hours": 48,
        },
        overrides,
    )


def make_standard_program_payload(eligible_mcc_codes=None, **overrides) -> dict:
    """The mandatory `STANDARD` fallback tier of PRD Section 3.2."""
    return make_rate_program_payload(
        program_code=overrides.pop("program_code", "STANDARD_FALLBACK"),
        category="STANDARD",
        eligible_mcc_codes=eligible_mcc_codes,
        **_apply(
            {
                "base_rate_bps": 200,
                "per_item_fee_cents": 0,
                "requires_data_elements": [],
                "max_clearing_delay_hours": 8760,
            },
            overrides,
        ),
    )


def make_rate_program_version_payload(
    publication_quarter: str,
    effective_from: str,
    effective_to: str,
    implementation_deadline: str,
    **overrides,
) -> dict:
    return _apply(
        {
            "publication_quarter": publication_quarter,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "base_rate_bps": 170,
            "per_item_fee_cents": 5,
            "implementation_deadline": implementation_deadline,
        },
        overrides,
    )


def make_implementation_window_payload(
    acquirer_id: str,
    rate_program_version_id: str,
    platform_id: str,
    window_start: str,
    window_end: str,
    **overrides,
) -> dict:
    return _apply(
        {
            "acquirer_id": acquirer_id,
            "rate_program_version_id": rate_program_version_id,
            "platform_id": platform_id,
            "window_start": window_start,
            "window_end": window_end,
        },
        overrides,
    )


def make_window_completion_payload(**overrides) -> dict:
    return _apply({"completion_note": "Rates deployed to all endpoints."}, overrides)


# --- Sections 3.3 and 3.4: merchants and reclassification ------------------

def make_merchant_payload(
    acquirer_id: str,
    business_type_key: str = TEST_DEFAULTS["BUSINESS_TYPE_KEY"],
    **overrides,
) -> dict:
    return _apply(
        {
            "legal_name": TEST_DEFAULTS["MERCHANT_NAME"],
            "business_type_key": business_type_key,
            "acquirer_id": acquirer_id,
            "home_country_code": TEST_DEFAULTS["COUNTRY_CODE"],
        },
        overrides,
    )


def make_verify_category_payload(
    documentation_ref: str = "DOC-2026-0001", **overrides
) -> dict:
    return _apply({"documentation_ref": documentation_ref}, overrides)


def make_reclassification_request_payload(
    merchant_id: str,
    requested_mcc: str,
    expected_merchant_version: int,
    **overrides,
) -> dict:
    return _apply(
        {
            "merchant_id": merchant_id,
            "requested_mcc": requested_mcc,
            "justification": "The outlet trades as a restaurant, not a grocer.",
            "expected_merchant_version": expected_merchant_version,
        },
        overrides,
    )


def make_request_info_payload(**overrides) -> dict:
    return _apply(
        {"info_request_note": "Please attach the signed lease agreement."}, overrides
    )


def make_resubmit_payload(supporting_doc_ref: str = "DOC-LEASE-1", **overrides) -> dict:
    return _apply({"supporting_doc_ref": supporting_doc_ref}, overrides)


def make_decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    return _apply(
        {"decision": decision, "decision_note": "Independent approval."}, overrides
    )


# --- Sections 3.5 to 3.7: clearing ----------------------------------------

def make_settlement_batch_payload(
    acquirer_id: str,
    batch_date: str = "2026-08-01",
    currency_code: str = TEST_DEFAULTS["SETTLEMENT_CURRENCY"],
    **overrides,
) -> dict:
    return _apply(
        {
            "acquirer_id": acquirer_id,
            "batch_date": batch_date,
            "currency_code": currency_code,
        },
        overrides,
    )


def make_transaction_record_payload(
    merchant_id: str,
    amount_cents: int,
    expected_batch_version: int,
    auth_code: str = "A00800",
    auth_timestamp: str = "2026-08-01T00:00:00.000Z",
    clearing_timestamp: str = "2026-08-01T00:00:00.000Z",
    data_elements=None,
    transaction_currency: str = TEST_DEFAULTS["SETTLEMENT_CURRENCY"],
    **overrides,
) -> dict:
    return _apply(
        {
            "merchant_id": merchant_id,
            "amount_cents": amount_cents,
            "transaction_currency": transaction_currency,
            "auth_code": auth_code,
            "auth_timestamp": auth_timestamp,
            "clearing_timestamp": clearing_timestamp,
            "data_elements": [] if data_elements is None else data_elements,
            "expected_batch_version": expected_batch_version,
        },
        overrides,
    )


def make_reversal_payload(reversal_type: str, **overrides) -> dict:
    return _apply(
        {
            "reversal_type": reversal_type,
            "reversal_reason": "Cardholder disputed the transaction.",
        },
        overrides,
    )


# --- Section 3.8: incentive programs and enrollments -----------------------

def make_incentive_program_payload(
    program_name: str = "Volume Incentive 2026",
    eligible_mcc_codes=None,
    total_capacity_cents: int = 1_000_000_000,
    min_commitment_cents: int = 5_000_000,
    reopen_threshold_cents: int = 5_000_000,
    performance_threshold_pct: float = 80.00,
    **overrides,
) -> dict:
    return _apply(
        {
            "program_name": program_name,
            "eligible_mcc_codes": (
                ["5411"] if eligible_mcc_codes is None else eligible_mcc_codes
            ),
            "total_capacity_cents": total_capacity_cents,
            "min_commitment_cents": min_commitment_cents,
            "reopen_threshold_cents": reopen_threshold_cents,
            "performance_threshold_pct": performance_threshold_pct,
        },
        overrides,
    )


def make_incentive_enrollment_payload(
    incentive_program_id: str,
    merchant_id: str,
    committed_volume_cents: int,
    expected_incentive_program_version: int,
    **overrides,
) -> dict:
    return _apply(
        {
            "incentive_program_id": incentive_program_id,
            "merchant_id": merchant_id,
            "committed_volume_cents": committed_volume_cents,
            "expected_incentive_program_version": expected_incentive_program_version,
        },
        overrides,
    )


def make_evaluate_performance_payload(basis: str = "TRAILING", **overrides) -> dict:
    return _apply({"basis": basis}, overrides)


def make_withdrawal_payload(**overrides) -> dict:
    return _apply({"withdrawal_reason": "Merchant exited the programme."}, overrides)


# --- Section 3.9: merchant category audits --------------------------------

def make_audit_payload(
    merchant_id: str, trigger_reason: str = "COMPLAINT", **overrides
) -> dict:
    return _apply(
        {"merchant_id": merchant_id, "trigger_reason": trigger_reason}, overrides
    )


def make_fieldwork_payload(
    fieldwork_start: str, fieldwork_end: str, **overrides
) -> dict:
    return _apply(
        {"fieldwork_start": fieldwork_start, "fieldwork_end": fieldwork_end}, overrides
    )


def make_sustain_findings_payload(correct_mcc: str, **overrides) -> dict:
    return _apply(
        {
            "correct_mcc": correct_mcc,
            "findings_note": "Outlet trades under a different category.",
        },
        overrides,
    )


def make_clear_findings_payload(**overrides) -> dict:
    return _apply(
        {"findings_note": "Category confirmed as declared; no misrepresentation."},
        overrides,
    )
