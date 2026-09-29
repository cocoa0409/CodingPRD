"""Request payload builders.

Each builder returns a valid payload for one endpoint and accepts keyword
overrides, so a test that probes one field states only that field.
"""

from typing import Any, Dict, Optional

from . import constants as C


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit:
    """Sentinel: pass ``OMIT`` for a field to drop it from the payload."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


_OMIT = _Omit()
OMIT = _OMIT


# --------------------------------------------------------------------------- #
# Clock
# --------------------------------------------------------------------------- #
def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# --------------------------------------------------------------------------- #
# Forecast cycles and scenarios
# --------------------------------------------------------------------------- #
def cycle_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "fiscal_year": C.FISCAL_YEAR,
            "cycle_type": "BASELINE",
            "reconciliation_policy": "MIDPOINT_AVERAGE",
            "enacted_appropriation_cents": C.ENACTED_APPROPRIATION_CENTS,
            "prior_recurring_baseline_cents": C.PRIOR_RECURRING_BASELINE_CENTS,
        },
        overrides,
    )


def revision_cycle_payload(supersedes_cycle_id: str, **overrides: Any) -> Dict[str, Any]:
    return cycle_payload(
        cycle_type="REVISION", supersedes_cycle_id=supersedes_cycle_id, **overrides
    )


def scenario_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(dict(C.SCENARIO_BASELINE), overrides)


# --------------------------------------------------------------------------- #
# Revenue sources and policy adjustments
# --------------------------------------------------------------------------- #
def pit_source_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Personal Income Tax",
            "tax_type": "PIT",
            "base_year_receipts_cents": C.PIT_BASE_RECEIPTS_CENTS,
            "elasticity_employment_bps": C.PIT_ELASTICITY_EMPLOYMENT_BPS,
            "elasticity_wage_income_bps": C.PIT_ELASTICITY_WAGE_BPS,
            "elasticity_retail_bps": C.PIT_ELASTICITY_RETAIL_BPS,
            "elasticity_asset_bps": C.PIT_ELASTICITY_ASSET_BPS,
            "volatility_class": "MEDIUM",
        },
        overrides,
    )


def cgt_source_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Capital Gains Tax",
            "tax_type": "CAPITAL_GAINS",
            "base_year_receipts_cents": C.CGT_BASE_RECEIPTS_CENTS,
            "elasticity_employment_bps": C.CGT_ELASTICITY_EMPLOYMENT_BPS,
            "elasticity_wage_income_bps": C.CGT_ELASTICITY_WAGE_BPS,
            "elasticity_retail_bps": C.CGT_ELASTICITY_RETAIL_BPS,
            "elasticity_asset_bps": C.CGT_ELASTICITY_ASSET_BPS,
            "volatility_class": "HIGH",
        },
        overrides,
    )


source_payload = pit_source_payload


def policy_adjustment_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "statute_code": "SB-2026-14",
            "policy_category": "RATE_CHANGE",
            "adjustment_kind": "INCREASE",
            "annualized_amount_cents": 20_000_000,
            "effective_start_date": "2026-07-01",
            "effective_end_date": None,
            "phase_in_type": "FULL",
            "first_effective_fiscal_year": C.FISCAL_YEAR,
            "cap_amount_cents": 0,
        },
        overrides,
    )


def pit_policy_adjustment_payload(**overrides: Any) -> Dict[str, Any]:
    """A prorated decrease spanning nine months of the canonical fiscal year."""
    return policy_adjustment_payload(
        statute_code="SB-2026-14",
        policy_category="RATE_CHANGE",
        adjustment_kind="DECREASE",
        annualized_amount_cents=C.PIT_POLICY_ANNUALIZED_CENTS,
        effective_start_date=C.PIT_POLICY_START_DATE,
        effective_end_date=C.PIT_POLICY_END_DATE,
        phase_in_type="PRORATED",
        first_effective_fiscal_year=C.FISCAL_YEAR,
        cap_amount_cents=0,
        **overrides,
    )


def cgt_policy_adjustment_payload(**overrides: Any) -> Dict[str, Any]:
    """A tiered increase in its first effective year, bitten by its own cap."""
    return policy_adjustment_payload(
        statute_code="SB-2026-21",
        policy_category="BASE_CHANGE",
        adjustment_kind="INCREASE",
        annualized_amount_cents=C.CGT_POLICY_ANNUALIZED_CENTS,
        effective_start_date="2026-07-01",
        effective_end_date=None,
        phase_in_type="TIERED",
        first_effective_fiscal_year=C.FISCAL_YEAR,
        cap_amount_cents=C.CGT_POLICY_CAP_CENTS,
        **overrides,
    )


# --------------------------------------------------------------------------- #
# One-time items
# --------------------------------------------------------------------------- #
def one_time_item_payload(cycle_id: str, source_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "cycle_id": cycle_id,
            "source_id": source_id,
            "item_type": "SETTLEMENT",
            "amount_cents": C.ONE_TIME_AMOUNT_CENTS,
            "description": "Multistate tax litigation settlement receipt",
        },
        overrides,
    )


# --------------------------------------------------------------------------- #
# Consensus rounds, estimates and resolutions
# --------------------------------------------------------------------------- #
def round_payload(cycle_id: str, expected_cycle_version: int, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "cycle_id": cycle_id,
            "expected_cycle_version": expected_cycle_version,
            "variance_tolerance_bps": C.VARIANCE_TOLERANCE_BPS,
            "per_source_tolerance_bps": C.PER_SOURCE_TOLERANCE_BPS,
        },
        overrides,
    )


def estimate_payload(round_id: str, source_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "round_id": round_id,
            "source_id": source_id,
            "judgmental_adjustment_cents": 0,
        },
        overrides,
    )


def resolution_payload(
    resolution_method: str,
    resolved_amount_cents: Optional[int] = None,
    rationale: str = C.VALID_RATIONALE,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "resolution_method": resolution_method,
        "rationale": rationale,
    }
    if resolved_amount_cents is not None:
        payload["resolved_amount_cents"] = resolved_amount_cents
    return _merge(payload, overrides)


# --------------------------------------------------------------------------- #
# Reserve funds, deposits and reversals
# --------------------------------------------------------------------------- #
def fund_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Budget Stabilization Fund",
            "cap_pct_bps": C.FUND_CAP_PCT_BPS,
            "trend_growth_rate_bps": C.FUND_TREND_GROWTH_RATE_BPS,
            "capture_rate_bps": C.FUND_CAPTURE_RATE_BPS,
            "deposit_rule_variant": "GROWTH_ABOVE_TREND",
            "eligible_seats": C.FUND_ELIGIBLE_SEATS,
            "annual_withdrawal_cap_pct_bps": C.FUND_ANNUAL_WITHDRAWAL_CAP_PCT_BPS,
            "cooling_off_days": C.FUND_COOLING_OFF_DAYS,
            "opening_balance_cents": C.FUND_OPENING_BALANCE_CENTS,
        },
        overrides,
    )


def deposit_payload(amount_cents: int, memo: str = C.VALID_MEMO, **overrides: Any) -> Dict[str, Any]:
    return _merge({"amount_cents": amount_cents, "memo": memo}, overrides)


def reversal_payload(rationale: str = C.VALID_RATIONALE, **overrides: Any) -> Dict[str, Any]:
    return _merge({"rationale": rationale}, overrides)


# --------------------------------------------------------------------------- #
# Withdrawal requests and ballots
# --------------------------------------------------------------------------- #
def withdrawal_request_payload(
    fund_id: str,
    cycle_id: str,
    expected_fund_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "fund_id": fund_id,
            "cycle_id": cycle_id,
            "expected_fund_version": expected_fund_version,
            "requested_amount_cents": 10_000_000,
            "justification_type": "SUPERMAJORITY_VOTE",
            "deadline_date": "2026-12-31",
        },
        overrides,
    )


def vote_payload(vote: str = "YES", **overrides: Any) -> Dict[str, Any]:
    return _merge({"vote": vote}, overrides)


# --------------------------------------------------------------------------- #
# Actual collections
# --------------------------------------------------------------------------- #
def actual_collection_payload(
    source_id: str,
    fiscal_year: int,
    actual_amount_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "source_id": source_id,
            "fiscal_year": fiscal_year,
            "actual_amount_cents": actual_amount_cents,
        },
        overrides,
    )


# --------------------------------------------------------------------------- #
# Rating agency briefings
# --------------------------------------------------------------------------- #
def briefing_payload(fund_id: str, cycle_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "fund_id": fund_id,
            "cycle_id": cycle_id,
            "narrative": C.VALID_NARRATIVE,
        },
        overrides,
    )


def publish_payload(refresh_snapshot: Optional[bool] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if refresh_snapshot is not None:
        payload["refresh_snapshot"] = refresh_snapshot
    return _merge(payload, overrides)
