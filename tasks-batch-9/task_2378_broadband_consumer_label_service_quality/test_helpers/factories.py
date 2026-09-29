"""Request payload builders.

Every builder returns a valid payload with the smallest set of fields the PRD
requires, and merges `**overrides` last so a test can vary exactly the one field
it is about. Codes that the PRD declares globally unique are suffixed from a
process-wide counter so repeated calls never collide by accident.
"""

from itertools import count
from typing import Any, Dict, List, Optional

from .constants import (
    REFERENCE_SAMPLES,
    REFERENCE_WINDOW_END,
    REFERENCE_WINDOW_START,
)
from .types import (
    AccessibilityConformance,
    AccessibilityNeed,
    AccessibleFormat,
    AllegationType,
    CreditBasis,
    DisclosureChannel,
    EtfProrationPolicy,
    FeeAppliesDuring,
    FeeBasis,
    FeeLabelCategory,
    FilingType,
    MetricVariant,
    NoticeType,
    Technology,
)

_SEQ = count(1)


def _next(prefix: str) -> str:
    return f"{prefix}-{next(_SEQ):04d}"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ServicePlan and FeeLineItem
# ---------------------------------------------------------------------------


def build_service_plan_payload(**overrides: Any) -> Dict[str, Any]:
    """A fibre plan advertising 300/140 Mbps with a six-month promotion."""
    return _merge(
        {
            "plan_code": _next("PLAN"),
            "display_name": "Fiber 300",
            "technology": Technology.FIBER.value,
            "advertised_download_mbps": 300,
            "advertised_upload_mbps": 140,
            "monthly_price_cents": 7999,
            "early_termination_fee_cents": 12000,
            "required_locales": ["en-US"],
            "intro_price_cents": 4999,
            "intro_term_months": 6,
            "data_allowance_gb": 1200,
            "overage_rate_cents_per_gb": 1000,
            "etf_proration_policy": EtfProrationPolicy.PRORATED_MONTHLY.value,
            "discount_program_eligible": True,
        },
        overrides,
    )


def build_plan_amendment_payload(**overrides: Any) -> Dict[str, Any]:
    """An amendment always carries a `change_justification`."""
    return _merge({"change_justification": "Annual repricing review"}, overrides)


def build_fixed_fee_payload(
    fee_code: str,
    amount_cents: int,
    label_category: str = FeeLabelCategory.MONTHLY_RECURRING.value,
    applies_during: str = FeeAppliesDuring.ALWAYS.value,
    **overrides: Any,
) -> Dict[str, Any]:
    """A `FIXED` line carries `amount_cents` and leaves `rate_pct` null."""
    return _merge(
        {
            "fee_code": fee_code,
            "description": f"Fee line {fee_code}",
            "label_category": label_category,
            "basis": FeeBasis.FIXED.value,
            "amount_cents": amount_cents,
            "applies_during": applies_during,
        },
        overrides,
    )


def build_percentage_fee_payload(
    fee_code: str,
    rate_pct: float,
    label_category: str = FeeLabelCategory.MONTHLY_RECURRING.value,
    applies_during: str = FeeAppliesDuring.ALWAYS.value,
    **overrides: Any,
) -> Dict[str, Any]:
    """A `PCT_OF_MONTHLY_CHARGE` line carries `rate_pct` and leaves
    `amount_cents` null."""
    return _merge(
        {
            "fee_code": fee_code,
            "description": f"Fee line {fee_code}",
            "label_category": label_category,
            "basis": FeeBasis.PCT_OF_MONTHLY_CHARGE.value,
            "rate_pct": rate_pct,
            "applies_during": applies_during,
        },
        overrides,
    )


#: The five fee lines of the reference plan, in the order the itemisation walks.
def build_reference_fee_payloads() -> List[Dict[str, Any]]:
    return [
        build_fixed_fee_payload(
            "EQUIP_RENTAL", 1500, description="Equipment rental"
        ),
        build_fixed_fee_payload(
            "NETWORK_ACCESS",
            700,
            applies_during=FeeAppliesDuring.POST_PROMO_ONLY.value,
            description="Network access surcharge",
        ),
        build_percentage_fee_payload(
            "REG_RECOVERY",
            0.0325,
            description="Regulatory cost recovery",
            is_regulatory_recovery=True,
        ),
        build_percentage_fee_payload(
            "STATE_USF",
            0.0211,
            label_category=FeeLabelCategory.GOVERNMENT_TAX.value,
            description="State universal service fund",
        ),
        build_fixed_fee_payload(
            "INSTALL",
            9900,
            label_category=FeeLabelCategory.ONE_TIME.value,
            description="Professional installation",
        ),
    ]


# ---------------------------------------------------------------------------
# Measurement infrastructure
# ---------------------------------------------------------------------------


def build_methodology_document_payload(**overrides: Any) -> Dict[str, Any]:
    """Peak window 19:00 inclusive to 23:00 exclusive, four samples minimum."""
    return _merge(
        {
            "doc_code": _next("MTH"),
            "version_label": "v1.0",
            "methodology_url": "https://isp.example/methodology/v1.0",
            "peak_hours_start_utc_hour": 19,
            "peak_hours_end_utc_hour": 23,
            "min_samples_required": 4,
            "max_run_duration_days": 7,
        },
        overrides,
    )


def build_measurement_probe_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "probe_code": _next("PRB"),
            "market_code": "US-TX-AUS",
            "panel_size": 75,
            "max_concurrent_windows": 2,
        },
        overrides,
    )


def build_sample(
    observed_at: str,
    download_mbps: float,
    upload_mbps: float,
    latency_ms: int,
) -> Dict[str, Any]:
    return {
        "observed_at": observed_at,
        "download_mbps": download_mbps,
        "upload_mbps": upload_mbps,
        "latency_ms": latency_ms,
    }


def build_test_run_payload(
    probe_id: str,
    plan_id: str,
    methodology_doc_id: str,
    window_start: str = REFERENCE_WINDOW_START,
    window_end: str = REFERENCE_WINDOW_END,
    samples: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "probe_id": probe_id,
            "plan_id": plan_id,
            "methodology_doc_id": methodology_doc_id,
            "window_start": window_start,
            "window_end": window_end,
            "samples": [dict(s) for s in (samples or REFERENCE_SAMPLES)],
        },
        overrides,
    )


def build_invalidate_run_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"reason": "Probe firmware defect invalidates the window"}, overrides)


def build_attestation_payload(
    plan_id: str,
    methodology_doc_id: str,
    expected_plan_version: int,
    metric_variant: str = MetricVariant.PEAK_HOUR_MEDIAN.value,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "plan_id": plan_id,
            "methodology_doc_id": methodology_doc_id,
            "metric_variant": metric_variant,
            "expected_plan_version": expected_plan_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


def build_label_version_payload(
    plan_id: str,
    effective_from: str,
    expected_plan_version: int,
    accessibility_conformance: str = AccessibilityConformance.WCAG_AA.value,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "plan_id": plan_id,
            "effective_from": effective_from,
            "accessibility_conformance": accessibility_conformance,
            "expected_plan_version": expected_plan_version,
        },
        overrides,
    )


def build_translation_payload(locale: str = "en-US", **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "locale": locale,
            "translated_summary": "Fiber 300 broadband consumer label",
            "machine_translated": False,
        },
        overrides,
    )


def build_withdraw_label_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"reason": "Published in error"}, overrides)


# ---------------------------------------------------------------------------
# Retail surface
# ---------------------------------------------------------------------------


def build_subscriber_account_payload(
    plan_id: str,
    service_start_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "account_code": _next("ACC"),
            "plan_id": plan_id,
            "preferred_locale": "en-US",
            "service_start_date": service_start_date,
            "accessibility_need": AccessibilityNeed.NONE.value,
            "discount_program_enrolled": True,
        },
        overrides,
    )


def build_disclosure_payload(
    channel: str = DisclosureChannel.ACCOUNT_PORTAL.value,
    locale: str = "en-US",
    accessible_format: str = AccessibleFormat.STANDARD_WEB.value,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "channel": channel,
            "locale": locale,
            "accessible_format": accessible_format,
        },
        overrides,
    )


def build_plan_change_notice_payload(
    account_id: str,
    target_plan_id: str,
    effective_date: str,
    notice_type: str = NoticeType.PLAN_CHANGE.value,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "account_id": account_id,
            "target_plan_id": target_plan_id,
            "notice_type": notice_type,
            "effective_date": effective_date,
            "reason": "Moving the account to the successor plan",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Complaints and credits
# ---------------------------------------------------------------------------


def build_complaint_payload(
    account_id: str,
    disputed_label_version_id: str,
    service_observed_date: str,
    allegation_type: str = AllegationType.SPEED_SHORTFALL.value,
    affected_days: int = 15,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "account_id": account_id,
        "disputed_label_version_id": disputed_label_version_id,
        "allegation_type": allegation_type,
        "service_observed_date": service_observed_date,
        "affected_days": affected_days,
        "narrative": "Delivered speed fell well below the disclosed typical figure",
    }
    if allegation_type == AllegationType.SPEED_SHORTFALL.value:
        payload["measured_download_mbps"] = 120
    return _merge(payload, overrides)


def build_triage_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"priority_note": "Severe speed allegation"}, overrides)


def build_request_info_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"info_request_note": "Please supply router logs for the affected days"},
        overrides,
    )


def build_uphold_payload(
    credit_basis: str = CreditBasis.PRORATA_DAYS.value, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "finding": "UPHELD",
            "resolution_note": "Shortfall confirmed against the disclosed figure",
            "credit_basis": credit_basis,
        },
        overrides,
    )


def build_dismiss_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "finding": "DISMISSED",
            "resolution_note": "Measurement did not corroborate the allegation",
        },
        overrides,
    )


def build_reopen_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"reopen_reason": "New evidence supplied by the consumer"}, overrides)


def build_withdraw_complaint_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"withdraw_reason": "Service restored to advertised levels"}, overrides)


def build_void_credit_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"void_reason": "Credit issued against the wrong account"}, overrides)


# ---------------------------------------------------------------------------
# Regulator dockets
# ---------------------------------------------------------------------------


def build_regulator_inquiry_payload(
    complaint_id: str,
    response_due_at: str = "2026-09-30T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "complaint_id": complaint_id,
            "docket_number": _next("FCC-2026"),
            "regulator_code": "FCC",
            "response_due_at": response_due_at,
        },
        overrides,
    )


def build_filing_payload(
    filing_type: str = FilingType.TECHNICAL_PACKET.value,
    evidence_ref: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "filing_type": filing_type,
            "evidence_ref": evidence_ref or _next("EVD"),
            "summary": f"{filing_type} lodged with the regulator",
        },
        overrides,
    )


def build_close_inquiry_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"closure_note": "Both filings on record; docket answered"}, overrides)
