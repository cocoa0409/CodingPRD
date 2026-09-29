"""Request payload builders.

Each builder returns a valid request body for one endpoint and accepts keyword
overrides. Only fields the PRD declares are ever emitted; passing ``None`` for an
optional field omits it so the server's own default applies.
"""
from .constants import CLOCK_START


def _compact(payload: dict, overrides: dict) -> dict:
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


# ---------------------------------------------------------------------------
# MemberBank
# ---------------------------------------------------------------------------

def member_bank_payload(
    name: str = "Harbor Savings",
    charter_type: str = "THRIFT",
    total_assets_cents: int = 8_000_000_000,
    credit_rating_tier=1,
    cdfi_certified=None,
    **overrides,
) -> dict:
    return _compact(
        {
            "name": name,
            "charter_type": charter_type,
            "total_assets_cents": total_assets_cents,
            "credit_rating_tier": credit_rating_tier,
            "cdfi_certified": cdfi_certified,
        },
        overrides,
    )


def condition_payload(membership_status=None, credit_rating_tier=None, **overrides) -> dict:
    return _compact(
        {
            "membership_status": membership_status,
            "credit_rating_tier": credit_rating_tier,
        },
        overrides,
    )


def pledge_agreement_payload(
    pledge_mode: str = "BLANKET_LIEN",
    effective_date: str = CLOCK_START,
    **overrides,
) -> dict:
    return _compact(
        {"pledge_mode": pledge_mode, "effective_date": effective_date}, overrides
    )


# ---------------------------------------------------------------------------
# StockSubscription
# ---------------------------------------------------------------------------

def stock_subscription_payload(
    member_bank_id: str,
    amount_cents: int,
    subscription_type: str = "MEMBERSHIP",
    **overrides,
) -> dict:
    return _compact(
        {
            "member_bank_id": member_bank_id,
            "subscription_type": subscription_type,
            "amount_cents": amount_cents,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# CollateralAsset
# ---------------------------------------------------------------------------

def collateral_asset_payload(
    member_bank_id: str,
    asset_class: str = "SF_MORTGAGE",
    market_value_cents: int = 21_000_000,
    appraisal_date: str = "2026-06-01T00:00:00Z",
    unpaid_principal_balance_cents=20_000_000,
    ltv_bps=7_500,
    delinquency_days=None,
    documentation_status=None,
    custody_location=None,
    **overrides,
) -> dict:
    return _compact(
        {
            "member_bank_id": member_bank_id,
            "asset_class": asset_class,
            "market_value_cents": market_value_cents,
            "appraisal_date": appraisal_date,
            "unpaid_principal_balance_cents": unpaid_principal_balance_cents,
            "ltv_bps": ltv_bps,
            "delinquency_days": delinquency_days,
            "documentation_status": documentation_status,
            "custody_location": custody_location,
        },
        overrides,
    )


def documentation_patch_payload(
    documentation_status=None,
    custody_location=None,
    delinquency_days=None,
    market_value_cents=None,
    ltv_bps=None,
    appraisal_date=None,
    **overrides,
) -> dict:
    return _compact(
        {
            "documentation_status": documentation_status,
            "custody_location": custody_location,
            "delinquency_days": delinquency_days,
            "market_value_cents": market_value_cents,
            "ltv_bps": ltv_bps,
            "appraisal_date": appraisal_date,
        },
        overrides,
    )


def substitution_payload(
    expected_member_bank_version: int,
    asset_class: str = "SF_MORTGAGE",
    market_value_cents: int = 21_000_000,
    appraisal_date: str = "2026-06-01T00:00:00Z",
    unpaid_principal_balance_cents=20_000_000,
    ltv_bps=7_500,
    delinquency_days=None,
    documentation_status=None,
    custody_location=None,
    **overrides,
) -> dict:
    return _compact(
        {
            "expected_member_bank_version": expected_member_bank_version,
            "asset_class": asset_class,
            "market_value_cents": market_value_cents,
            "appraisal_date": appraisal_date,
            "unpaid_principal_balance_cents": unpaid_principal_balance_cents,
            "ltv_bps": ltv_bps,
            "delinquency_days": delinquency_days,
            "documentation_status": documentation_status,
            "custody_location": custody_location,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# SafekeepingReceipt
# ---------------------------------------------------------------------------

def safekeeping_receipt_payload(
    file_count: int = 12,
    delivery_date: str = "2026-08-10T00:00:00Z",
    return_date: str = "2026-08-20T00:00:00Z",
    **overrides,
) -> dict:
    return _compact(
        {
            "file_count": file_count,
            "delivery_date": delivery_date,
            "return_date": return_date,
        },
        overrides,
    )


def confirm_receipt_payload(outcome: str = "RECEIVED", exception_note=None, **overrides) -> dict:
    return _compact({"outcome": outcome, "exception_note": exception_note}, overrides)


# ---------------------------------------------------------------------------
# CollateralVerificationReview / ReviewFinding
# ---------------------------------------------------------------------------

def verification_review_payload(
    member_bank_id: str,
    window_start: str = "2026-08-01T00:00:00Z",
    window_end: str = "2026-08-20T00:00:00Z",
    sample_size: int = 40,
    **overrides,
) -> dict:
    return _compact(
        {
            "member_bank_id": member_bank_id,
            "window_start": window_start,
            "window_end": window_end,
            "sample_size": sample_size,
        },
        overrides,
    )


def review_finding_payload(
    collateral_asset_id: str,
    finding_type: str = "MISSING_NOTE",
    severity: str = "MAJOR",
    **overrides,
) -> dict:
    return _compact(
        {
            "collateral_asset_id": collateral_asset_id,
            "finding_type": finding_type,
            "severity": severity,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# AdvanceProduct / Advance
# ---------------------------------------------------------------------------

def advance_product_payload(
    product_code: str = "FT-450",
    structure: str = "FIXED_TERM",
    min_term_days: int = 30,
    max_term_days: int = 1_095,
    rate_bps: int = 425,
    prepayment_fee_method: str = "YIELD_MAINTENANCE",
    activity_stock_pct_bps: int = 450,
    min_principal_cents: int = 1_000_000,
    flat_prepayment_fee_bps=None,
    symmetric_credit_enabled=None,
    requires_collateral_delivery=None,
    community_program_flag=None,
    **overrides,
) -> dict:
    return _compact(
        {
            "product_code": product_code,
            "structure": structure,
            "min_term_days": min_term_days,
            "max_term_days": max_term_days,
            "rate_bps": rate_bps,
            "prepayment_fee_method": prepayment_fee_method,
            "activity_stock_pct_bps": activity_stock_pct_bps,
            "min_principal_cents": min_principal_cents,
            "flat_prepayment_fee_bps": flat_prepayment_fee_bps,
            "symmetric_credit_enabled": symmetric_credit_enabled,
            "requires_collateral_delivery": requires_collateral_delivery,
            "community_program_flag": community_program_flag,
        },
        overrides,
    )


def advance_payload(
    member_bank_id: str,
    advance_product_id: str,
    expected_member_bank_version: int,
    term_days: int = 360,
    requested_net_proceeds_cents: int = 5_000_000,
    fund_stock_from_advance=None,
    community_program_allocation_id=None,
    community_bucket=None,
    requested_subsidy_cents=None,
    **overrides,
) -> dict:
    return _compact(
        {
            "member_bank_id": member_bank_id,
            "advance_product_id": advance_product_id,
            "term_days": term_days,
            "requested_net_proceeds_cents": requested_net_proceeds_cents,
            "expected_member_bank_version": expected_member_bank_version,
            "fund_stock_from_advance": fund_stock_from_advance,
            "community_program_allocation_id": community_program_allocation_id,
            "community_bucket": community_bucket,
            "requested_subsidy_cents": requested_subsidy_cents,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# PrepaymentEvent
# ---------------------------------------------------------------------------

def prepayment_quote_payload(
    prepay_amount_cents: int, prepay_kind: str = "FULL", **overrides
) -> dict:
    return _compact(
        {"prepay_kind": prepay_kind, "prepay_amount_cents": prepay_amount_cents},
        overrides,
    )


# ---------------------------------------------------------------------------
# CommunityProgramAllocation
# ---------------------------------------------------------------------------

def allocation_payload(
    program_code: str = "CIP",
    fiscal_year: int = 2026,
    total_pool_cents: int = 400_000,
    subsidy_rate_bps: int = 75,
    **overrides,
) -> dict:
    return _compact(
        {
            "program_code": program_code,
            "fiscal_year": fiscal_year,
            "total_pool_cents": total_pool_cents,
            "subsidy_rate_bps": subsidy_rate_bps,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Administrative test-driving capabilities
# ---------------------------------------------------------------------------

def clock_payload(now: str = CLOCK_START) -> dict:
    return {"now": now}


def market_rate_payload(market_rate_bps: int) -> dict:
    return {"market_rate_bps": market_rate_bps}
