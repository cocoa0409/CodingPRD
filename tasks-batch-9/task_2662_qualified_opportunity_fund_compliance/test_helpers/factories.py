"""
Request payload factories.

Each factory returns only the fields a client may supply for that endpoint —
never a server-computed field. Money amounts are emitted as JSON numbers with
two decimals and percentages as JSON numbers with four decimals, matching the
PRD's rounding rules; they are never emitted as strings.

Pass `OMIT` as an override value to delete a key from the payload, which is how
"required field missing" and "forbidden field supplied" probes are built:

    create_fund_payload(manager_user_id=OMIT)
"""

from typing import Any, Dict, List, Optional

from .constants import CLOCK_ORIGIN


class _Omit:
    """Sentinel marking a key that must be absent from the payload."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


OMIT = _Omit()


def _apply(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge overrides into base, dropping any key whose override is OMIT."""
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, _Omit):
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


# =========================================================================
# Investor
# =========================================================================


def create_investor_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /qof/investors — optional inputs omitted so defaults apply."""
    return _apply(
        {
            "legal_name": "Marisol Vantiff",
            "taxpayer_type": "INDIVIDUAL",
        },
        overrides,
    )


def investor_attestation_payload(
    compliance_attestation_status: str = "ATTESTED", **overrides: Any
) -> Dict[str, Any]:
    """PATCH /qof/investors/{id}/attestation."""
    return _apply(
        {"compliance_attestation_status": compliance_attestation_status}, overrides
    )


# =========================================================================
# Fund
# =========================================================================


def create_fund_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /qof/funds — valuation method omitted so the default applies."""
    return _apply(
        {
            "name": "Halvard Renewal Opportunity Fund I",
            "entity_type": "PARTNERSHIP",
            "manager_user_id": "mgr-fund-1",
        },
        overrides,
    )


def self_certify_payload(
    first_taxable_month_iso8601: str = "2026-01-01T00:00:00Z", **overrides: Any
) -> Dict[str, Any]:
    """
    POST /qof/funds/{id}/self-certify.

    The month is supplied as the first instant of a calendar month: day 1 at
    00:00:00.000Z exactly.
    """
    return _apply(
        {"first_taxable_month_iso8601": first_taxable_month_iso8601}, overrides
    )


def decertify_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /qof/funds/{id}/decertify — reason_note is optional."""
    return _apply({"reason_note": "Compliance review concluded."}, overrides)


# =========================================================================
# EligibleGain
# =========================================================================


def create_eligible_gain_payload(investor_id: str, **overrides: Any) -> Dict[str, Any]:
    """
    POST /qof/eligible-gains.

    Defaults to SALE_DATE, for which pass_through_year_end is forbidden and so
    is absent. For the other two bases, supply pass_through_year_end explicitly.
    """
    return _apply(
        {
            "investor_id": investor_id,
            "gain_character": "LONG_TERM_CAPITAL",
            "eligible_amount": 100000.00,
            "realization_date": "2026-07-01T00:00:00Z",
            "deadline_basis": "SALE_DATE",
        },
        overrides,
    )


# =========================================================================
# DeferralElection
# =========================================================================


def create_deferral_election_payload(
    eligible_gain_id: str,
    fund_id: str,
    expected_fund_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /qof/deferral-elections — expected_fund_version is mandatory."""
    return _apply(
        {
            "eligible_gain_id": eligible_gain_id,
            "fund_id": fund_id,
            "elected_amount": 100000.00,
            "expected_fund_version": expected_fund_version,
        },
        overrides,
    )


def revoke_election_payload(
    revoked_reason_code: str = "INVESTOR_WITHDRAWAL", **overrides: Any
) -> Dict[str, Any]:
    """POST /qof/deferral-elections/{id}/revoke."""
    return _apply({"revoked_reason_code": revoked_reason_code}, overrides)


def create_inclusion_event_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /qof/deferral-elections/{id}/inclusion-events."""
    return _apply(
        {
            "event_type": "PARTIAL_REDEMPTION",
            "included_fraction": 0.5000,
        },
        overrides,
    )


def create_step_up_election_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /qof/deferral-elections/{id}/step-up-elections."""
    return _apply({"claimed_fmv": 400000.00}, overrides)


# =========================================================================
# FundAsset
# =========================================================================


def create_fund_asset_payload(fund_id: str, **overrides: Any) -> Dict[str, Any]:
    """
    POST /qof/fund-assets.

    Defaults to original-use QOZ business property, which is born QUALIFIED.
    qoz_business_id is absent, which is what every class other than
    QOZB_EQUITY requires.
    """
    return _apply(
        {
            "fund_id": fund_id,
            "asset_class": "QOZ_BUSINESS_PROPERTY",
            "acquisition_date": "2026-02-01T00:00:00Z",
            "unadjusted_cost_basis": 600000.00,
            "afs_fair_value": 700000.00,
            "original_use_in_zone": True,
        },
        overrides,
    )


def dispose_fund_asset_payload(
    proceeds_amount: float = 800000.00, **overrides: Any
) -> Dict[str, Any]:
    """POST /qof/fund-assets/{id}/dispose."""
    return _apply({"proceeds_amount": proceeds_amount}, overrides)


# =========================================================================
# QOZBusiness
# =========================================================================


def create_qoz_business_payload(fund_id: str, **overrides: Any) -> Dict[str, Any]:
    """POST /qof/qoz-businesses — zone_tract_code is exactly 11 characters."""
    return _apply(
        {
            "fund_id": fund_id,
            "legal_name": "Ridgewater Fabrication LLC",
            "zone_tract_code": "36047123400",
            "declared_nqfp_amount": 20000.00,
            "total_asset_value": 1000000.00,
            "total_tangible_property_basis": 800000.00,
        },
        overrides,
    )


def reported_figures_payload(**overrides: Any) -> Dict[str, Any]:
    """PATCH /qof/qoz-businesses/{id}/reported-figures — all fields optional."""
    return _apply({"declared_nqfp_amount": 200000.00}, overrides)


# =========================================================================
# BusinessTest
# =========================================================================


def create_business_test_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /qof/qoz-businesses/{id}/business-tests — testing_date only."""
    return _apply({"testing_date": "2026-06-30T00:00:00Z"}, overrides)


def measure_business_test_payload(**overrides: Any) -> Dict[str, Any]:
    """
    POST /qof/business-tests/{id}/measure.

    Defaults to the GROSS_INCOME_ACTUAL branch, which uses neither
    hours_zone_pct nor amounts_paid_zone_pct, so both are absent.
    """
    return _apply(
        {
            "safe_harbor_used": "GROSS_INCOME_ACTUAL",
            "gross_income_zone_amount": 300000.00,
            "gross_income_total_amount": 800000.00,
            "intangibles_zone_use_amount": 300000.00,
            "intangibles_total_amount": 1000000.00,
            "total_asset_value_measured": 1000000.00,
        },
        overrides,
    )


# =========================================================================
# AssetTest
# =========================================================================


def create_asset_test_payload(**overrides: Any) -> Dict[str, Any]:
    """
    POST /qof/funds/{id}/asset-tests.

    The testing period is half-open; valuation_method_override is absent so the
    test inherits the fund's default variant.
    """
    return _apply(
        {
            "measurement_date": "2026-06-30T00:00:00Z",
            "period_start": "2026-01-01T00:00:00Z",
            "period_end": "2026-07-01T00:00:00Z",
        },
        overrides,
    )


# =========================================================================
# ImprovementProject
# =========================================================================


def create_improvement_project_payload(
    fund_asset_id: str, **overrides: Any
) -> Dict[str, Any]:
    """
    POST /qof/improvement-projects.

    Defaults to ASSET_BY_ASSET, for which group_key is forbidden and absent.
    """
    return _apply(
        {
            "fund_asset_id": fund_asset_id,
            "window_start": "2026-08-01T00:00:00Z",
            "aggregation_method": "ASSET_BY_ASSET",
        },
        overrides,
    )


def create_project_expenditure_payload(
    expected_project_version: int, **overrides: Any
) -> Dict[str, Any]:
    """
    POST /qof/improvement-projects/{id}/expenditures.

    expected_project_version is mandatory. CAPITALIZED_IMPROVEMENT is the only
    kind that counts toward basis.
    """
    return _apply(
        {
            "amount": 200000.00,
            "expenditure_kind": "CAPITALIZED_IMPROVEMENT",
            "expected_project_version": expected_project_version,
        },
        overrides,
    )


# =========================================================================
# WorkingCapitalPlan
# =========================================================================


def spend_schedule(*planned_amounts: float) -> List[Dict[str, Any]]:
    """Build a spend_schedule whose month_index values run 1..N in order."""
    return [
        {"month_index": index, "planned_amount": amount}
        for index, amount in enumerate(planned_amounts, start=1)
    ]


def create_wcsh_plan_payload(qoz_business_id: str, **overrides: Any) -> Dict[str, Any]:
    """
    POST /qof/wcsh-plans.

    The default schedule's planned amounts sum to covered_amount, which is what
    the schedule check requires.
    """
    return _apply(
        {
            "qoz_business_id": qoz_business_id,
            "window_start": "2026-01-01T00:00:00Z",
            "covered_amount": 300000.00,
            "written_plan_reference": "WCSH-2662-A",
            "schedule_month_count": 3,
            "spend_schedule": spend_schedule(100000.00, 100000.00, 100000.00),
        },
        overrides,
    )


def create_wcsh_expenditure_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /qof/wcsh-plans/{id}/expenditures — no version field is accepted."""
    return _apply(
        {
            "amount": 120000.00,
            "expenditure_kind": "OPERATING_WORKING_CAPITAL",
        },
        overrides,
    )


def evaluate_checkpoint_payload(
    checkpoint_month_index: int = 1, **overrides: Any
) -> Dict[str, Any]:
    """POST /qof/wcsh-plans/{id}/evaluate-checkpoint."""
    return _apply({"checkpoint_month_index": checkpoint_month_index}, overrides)


# =========================================================================
# PenaltyAssessment
# =========================================================================


def cure_request_payload(
    cure_basis: str = "REASONABLE_CAUSE",
    narrative_reference: str = "CURE-2662-A",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /qof/penalty-assessments/{id}/cure-requests."""
    return _apply(
        {
            "cure_basis": cure_basis,
            "narrative_reference": narrative_reference,
        },
        overrides,
    )


def cure_decision_payload(decision: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    """POST /qof/penalty-assessments/{id}/cure-decisions."""
    return _apply({"decision": decision}, overrides)


# =========================================================================
# Logical clock
# =========================================================================


def set_clock_payload(current_utc: str = CLOCK_ORIGIN, **overrides: Any) -> Dict[str, Any]:
    """POST /qof/_clock/set_current_utc."""
    return _apply({"current_utc": current_utc}, overrides)
