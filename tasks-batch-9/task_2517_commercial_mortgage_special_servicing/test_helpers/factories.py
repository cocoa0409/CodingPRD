"""Payload factories for the CMBS Special Servicing API.

Each factory returns the minimum body the PRD declares as required for the
endpoint, with realistic defaults, and lets any field be overridden by keyword.
"""

from .constants import DEFAULT_CLOCK
from .types import Json

_UNSET = object()


def _merge(base: Json, overrides: Json) -> Json:
    """Overlay overrides onto base; a value of ``None`` removes the key."""
    out = dict(base)
    for key, value in overrides.items():
        if value is None and key in out:
            del out[key]
        else:
            out[key] = value
    return out


# --------------------------------------------------------------------------
# Trust
# --------------------------------------------------------------------------
def trust_payload(**overrides) -> Json:
    """A boardable trust. Omits every optional field so defaults are observable."""
    return _merge(
        {
            "deal_name": "CMBS 2026-C1",
            "closing_date": "2026-01-15T00:00:00Z",
            "original_controlling_class_balance_usd": 40000000,
        },
        overrides,
    )


def small_controlling_class_trust_payload(**overrides) -> Json:
    """A trust whose 8,000,000.00 controlling class puts the 25% threshold at
    exactly 2,000,000.00."""
    return trust_payload(
        **_merge(
            {
                "deal_name": "CMBS 2026-T1",
                "original_controlling_class_balance_usd": 8000000,
            },
            overrides,
        )
    )


# --------------------------------------------------------------------------
# Loan
# --------------------------------------------------------------------------
def loan_payload(trust_id: str, **overrides) -> Json:
    """A 19,500,000.00 balance loan with a 118,000.00 monthly debt service."""
    return _merge(
        {
            "trust_id": trust_id,
            "loan_number": "L-001",
            "original_balance_usd": 20000000,
            "current_principal_balance_usd": 19500000,
            "accrued_unpaid_interest_usd": 0,
            "note_rate_pct": 5.75,
            "monthly_debt_service_usd": 118000,
            "maturity_date": "2029-01-01T00:00:00Z",
            "securitization_value_usd": 26000000,
        },
        overrides,
    )


def mid_size_loan_payload(trust_id: str, **overrides) -> Json:
    """A 10,000,000.00 balance loan with a 65,000.00 monthly debt service."""
    return _merge(
        {
            "trust_id": trust_id,
            "loan_number": "L-C01",
            "original_balance_usd": 12000000,
            "current_principal_balance_usd": 10000000,
            "accrued_unpaid_interest_usd": 0,
            "note_rate_pct": 6.0,
            "monthly_debt_service_usd": 65000,
            "maturity_date": "2028-06-01T00:00:00Z",
            "securitization_value_usd": 15000000,
        },
        overrides,
    )


def small_loan_payload(trust_id: str, **overrides) -> Json:
    """A 1,000,000.00 balance loan, where the absolute servicing standard floor
    dominates the relative branch."""
    return _merge(
        {
            "trust_id": trust_id,
            "loan_number": "L-SMALL",
            "original_balance_usd": 1100000,
            "current_principal_balance_usd": 1000000,
            "accrued_unpaid_interest_usd": 0,
            "note_rate_pct": 6.25,
            "monthly_debt_service_usd": 6500,
            "maturity_date": "2029-01-01T00:00:00Z",
            "securitization_value_usd": 1400000,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# ServicingTransferEvent
# --------------------------------------------------------------------------
def transfer_event_payload(loan_id: str, **overrides) -> Json:
    """A 60-day monetary default, which qualifies a loan for transfer."""
    return _merge(
        {
            "loan_id": loan_id,
            "event_code": "MONETARY_DEFAULT_60D",
            "occurred_on": "2026-07-15T00:00:00Z",
            "evidence_note": "60 days monetary delinquency",
            "days_delinquent_at_event": 60,
        },
        overrides,
    )


def bankruptcy_event_payload(loan_id: str, **overrides) -> Json:
    return _merge(
        {
            "loan_id": loan_id,
            "event_code": "BANKRUPTCY",
            "occurred_on": "2026-07-01T00:00:00Z",
            "evidence_note": "chapter 11 petition filed",
        },
        overrides,
    )


def receivership_event_payload(loan_id: str, **overrides) -> Json:
    return _merge(
        {
            "loan_id": loan_id,
            "event_code": "RECEIVERSHIP",
            "occurred_on": "2026-07-10T00:00:00Z",
            "evidence_note": "receiver appointed over the property",
        },
        overrides,
    )


def imminent_default_event_payload(loan_id: str, **overrides) -> Json:
    return _merge(
        {
            "loan_id": loan_id,
            "event_code": "IMMINENT_DEFAULT",
            "occurred_on": "2026-07-20T00:00:00Z",
            "evidence_note": "borrower certified imminent default",
            "imminent_default_certified": True,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# BorrowerRequest
# --------------------------------------------------------------------------
def modification_request_payload(loan_id: str, **overrides) -> Json:
    return _merge(
        {
            "loan_id": loan_id,
            "request_type": "MODIFICATION",
            "processing_fee_deposit_usd": 25000,
            "requested_terms_note": "rate relief to 4.50% for 24 months",
            "proposed_rate_pct": 4.5,
        },
        overrides,
    )


def assumption_request_payload(loan_id: str, **overrides) -> Json:
    return _merge(
        {
            "loan_id": loan_id,
            "request_type": "ASSUMPTION",
            "processing_fee_deposit_usd": 15000,
            "requested_terms_note": "assumption by affiliate purchaser",
            "assumption_buyer_name": "Northgate Holdings LLC",
        },
        overrides,
    )


def lease_approval_request_payload(loan_id: str, **overrides) -> Json:
    return _merge(
        {
            "loan_id": loan_id,
            "request_type": "LEASE_APPROVAL",
            "processing_fee_deposit_usd": 5000,
            "requested_terms_note": "anchor tenant, suite S-300, five year term",
            "suite_code": "S-300",
            "lease_commencement_date": "2027-01-01T00:00:00Z",
            "lease_expiration_date": "2031-12-31T00:00:00Z",
            "lease_base_rent_annual_usd": 480000,
        },
        overrides,
    )


def analysis_payload(**overrides) -> Json:
    """A 97,500.00 margin on a 19,500,000.00 balance: the standard is met."""
    return _merge(
        {
            "npv_recovery_with_request_usd": 21597500,
            "npv_recovery_without_request_usd": 21500000,
            "analysis_discount_rate_pct": 9.5,
        },
        overrides,
    )


def lease_analysis_payload(**overrides) -> Json:
    """A 100,000.00 margin against the 50,000.00 absolute floor."""
    return _merge(
        {
            "npv_recovery_with_request_usd": 9100000,
            "npv_recovery_without_request_usd": 9000000,
            "analysis_discount_rate_pct": 9.5,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Appraisal
# --------------------------------------------------------------------------
def appraisal_payload(loan_id: str, **overrides) -> Json:
    return _merge(
        {
            "loan_id": loan_id,
            "appraisal_type": "UPDATE",
            "ordered_on": DEFAULT_CLOCK,
            "appraiser_firm": "Acme Valuation",
            "valuation_valid_months": 12,
        },
        overrides,
    )


def full_narrative_appraisal_payload(loan_id: str, **overrides) -> Json:
    return appraisal_payload(loan_id, appraisal_type="FULL_NARRATIVE", **overrides)


def appraisal_received_payload(value_usd: float, as_of_date: str, **overrides) -> Json:
    return _merge(
        {"to_status": "RECEIVED", "value_usd": value_usd, "as_of_date": as_of_date},
        overrides,
    )


# --------------------------------------------------------------------------
# Advance
# --------------------------------------------------------------------------
def advance_payload(loan_id: str, **overrides) -> Json:
    return _merge(
        {
            "loan_id": loan_id,
            "advance_type": "TAX_INSURANCE_ADVANCE",
            "amount_usd": 200000,
            "advanced_on": "2026-02-01T00:00:00Z",
        },
        overrides,
    )


# --------------------------------------------------------------------------
# WorkoutPlan / WorkoutAlternative
# --------------------------------------------------------------------------
def workout_plan_payload(loan_id: str, expected_loan_version: int, **overrides) -> Json:
    return _merge(
        {
            "loan_id": loan_id,
            "discount_rate_pct": 9.5,
            "npv_basis": "CONTRACTUAL",
            "expected_loan_version": expected_loan_version,
        },
        overrides,
    )


MODIFICATION_CASH_FLOWS = [
    {"period_index": 1, "amount_usd": 900000},
    {"period_index": 2, "amount_usd": 950000},
    {"period_index": 3, "amount_usd": 1000000},
    {"period_index": 4, "amount_usd": 8576200},
]
NOTE_SALE_CASH_FLOWS = [{"period_index": 1, "amount_usd": 9100000}]
FORECLOSURE_CASH_FLOWS = [
    {"period_index": 1, "amount_usd": 0},
    {"period_index": 2, "amount_usd": 9800000},
]


def modification_alternative_payload(plan_id: str, **overrides) -> Json:
    return _merge(
        {
            "workout_plan_id": plan_id,
            "alternative_type": "MODIFICATION",
            "projected_cash_flows": [dict(cf) for cf in MODIFICATION_CASH_FLOWS],
            "upfront_cost_usd": 120000,
        },
        overrides,
    )


def note_sale_alternative_payload(plan_id: str, **overrides) -> Json:
    return _merge(
        {
            "workout_plan_id": plan_id,
            "alternative_type": "NOTE_SALE",
            "projected_cash_flows": [dict(cf) for cf in NOTE_SALE_CASH_FLOWS],
            "upfront_cost_usd": 90000,
        },
        overrides,
    )


def foreclosure_alternative_payload(plan_id: str, **overrides) -> Json:
    return _merge(
        {
            "workout_plan_id": plan_id,
            "alternative_type": "FORECLOSURE",
            "projected_cash_flows": [dict(cf) for cf in FORECLOSURE_CASH_FLOWS],
            "upfront_cost_usd": 650000,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# ConsultationRequest
# --------------------------------------------------------------------------
def plan_consultation_payload(trust_id: str, plan_id: str, **overrides) -> Json:
    return _merge(
        {
            "trust_id": trust_id,
            "subject_type": "WORKOUT_PLAN",
            "workout_plan_id": plan_id,
        },
        overrides,
    )


def request_consultation_payload(trust_id: str, request_id: str, **overrides) -> Json:
    return _merge(
        {
            "trust_id": trust_id,
            "subject_type": "BORROWER_REQUEST",
            "borrower_request_id": request_id,
        },
        overrides,
    )


def consultation_response_payload(response: str, **overrides) -> Json:
    return _merge(
        {"response": response, "response_note": f"{response.lower()} by the controlling class"},
        overrides,
    )


# --------------------------------------------------------------------------
# REOAsset
# --------------------------------------------------------------------------
def reo_asset_payload(loan_id: str, plan_id: str, **overrides) -> Json:
    return _merge(
        {
            "loan_id": loan_id,
            "source_workout_plan_id": plan_id,
            "acquisition_type": "FORECLOSURE",
            "acquired_on": DEFAULT_CLOCK,
            "initial_noi_annual_usd": 480000,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# FeeAccrual
# --------------------------------------------------------------------------
def special_servicing_fee_payload(loan_id: str, **overrides) -> Json:
    return _merge(
        {
            "loan_id": loan_id,
            "fee_type": "SPECIAL_SERVICING_FEE",
            "period_start": "2026-08-01T00:00:00Z",
            "period_end": "2026-08-31T00:00:00Z",
        },
        overrides,
    )


def workout_fee_payload(loan_id: str, **overrides) -> Json:
    return _merge(
        {"loan_id": loan_id, "fee_type": "WORKOUT_FEE"},
        overrides,
    )


# --------------------------------------------------------------------------
# DistributionReport
# --------------------------------------------------------------------------
def distribution_report_payload(
    trust_id: str, expected_trust_version: int, **overrides
) -> Json:
    return _merge(
        {
            "trust_id": trust_id,
            "report_type": "DELINQUENT_LOAN_STATUS",
            "period_end": "2026-08-31T00:00:00Z",
            "expected_trust_version": expected_trust_version,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Status transition bodies
# --------------------------------------------------------------------------
def status_payload(to_status: str, **overrides) -> Json:
    return _merge({"to_status": to_status}, overrides)


def liquidation_payload(
    gross_proceeds_usd: float,
    liquidation_expenses_usd: float,
    closing_date: str,
    to_status: str = "LIQUIDATED",
    **overrides,
) -> Json:
    return _merge(
        {
            "to_status": to_status,
            "gross_proceeds_usd": gross_proceeds_usd,
            "liquidation_expenses_usd": liquidation_expenses_usd,
            "closing_date": closing_date,
        },
        overrides,
    )
