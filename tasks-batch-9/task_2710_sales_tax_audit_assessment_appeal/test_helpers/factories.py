"""Payload factories — one per write endpoint, input fields only."""
import itertools

from .constants import DEFAULT_LOGICAL_CLOCK

_PERMIT_SEQ = itertools.count(100_001)

DEFAULTS = {
    "LEGAL_NAME": "Ridgeline Tools LLC",
    "NAICS_CODE": "444140",
    "FILING_FREQUENCY": "MONTHLY",
    "GROSS_RECEIPTS_CENTS": 100_000_000,
    "PROJECT_NAME": "Hardware Retail Project",
    "INDUSTRY_ERROR_RATE_BP": 3_000,
    "SIGNED_BY_NAME": "Dana Ridgeline, Controller",
    "AGREED_BY_NAME": "Dana Ridgeline, Controller",
    "VENDOR_NAME": "Northgate Supply Co",
    "PURCHASER_NAME": "Coastal Fabrication Inc",
    "PURCHASER_PERMIT_NUMBER": "STP-900001",
    "PROTEST_BASIS": "The projection overstates the taxable measure of the sample.",
}


def next_permit_number() -> str:
    """A fresh permit number: the literal prefix STP- plus exactly six digits."""
    return f"STP-{next(_PERMIT_SEQ)}"


def _compact(payload: dict) -> dict:
    """Drop keys whose value is the sentinel `...` so optional fields stay absent."""
    return {k: v for k, v in payload.items() if v is not ...}


# --- Permit holders and information returns -------------------------------

def create_taxpayer_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "permit_number": next_permit_number(),
        "industry_naics_code": DEFAULTS["NAICS_CODE"],
        "filing_frequency": DEFAULTS["FILING_FREQUENCY"],
        "gross_receipts_annual_cents": DEFAULTS["GROSS_RECEIPTS_CENTS"],
    }
    payload.update(overrides)
    return _compact(payload)


def create_information_return_payload(taxpayer_id, **overrides) -> dict:
    payload = {
        "taxpayer_id": taxpayer_id,
        "source_type": "FEDERAL_1099K",
        "period_start": "2026-01-01",
        "period_end": "2026-03-31",
        "reported_amount_cents": 40_000_000,
        "matched_return_amount_cents": 30_000_000,
    }
    payload.update(overrides)
    return _compact(payload)


def rescore_screening_payload(**overrides) -> dict:
    return _compact(dict(overrides))


# --- Industry projects and leads ------------------------------------------

def create_industry_project_payload(**overrides) -> dict:
    payload = {
        "project_name": DEFAULTS["PROJECT_NAME"],
        "industry_naics_code": DEFAULTS["NAICS_CODE"],
        "industry_error_rate_bp": DEFAULTS["INDUSTRY_ERROR_RATE_BP"],
        "selection_mode": "THRESHOLD",
        "selection_threshold_score": 0,
        "selection_quota": 5,
    }
    payload.update(overrides)
    return _compact(payload)


def decline_lead_payload(decline_reason="Taxpayer already under federal examination.", **overrides) -> dict:
    payload = {"decline_reason": decline_reason}
    payload.update(overrides)
    return _compact(payload)


def convert_lead_payload(lead_auditor_user_id, audit_type=..., **overrides) -> dict:
    payload = {"lead_auditor_user_id": lead_auditor_user_id, "audit_type": audit_type}
    payload.update(overrides)
    return _compact(payload)


# --- Audits ---------------------------------------------------------------

def scope_audit_payload(scope_period_start, scope_period_end, audit_type="DESK", **overrides) -> dict:
    payload = {
        "audit_type": audit_type,
        "scope_period_start": scope_period_start,
        "scope_period_end": scope_period_end,
    }
    payload.update(overrides)
    return _compact(payload)


def close_fieldwork_payload(fraud_indicator=..., **overrides) -> dict:
    payload = {"fraud_indicator": fraud_indicator}
    payload.update(overrides)
    return _compact(payload)


def reopen_fieldwork_payload(reopen_reason="Appeals asked for additional invoices.", **overrides) -> dict:
    payload = {"reopen_reason": reopen_reason}
    payload.update(overrides)
    return _compact(payload)


def abandon_audit_payload(abandon_reason="Limitation period has run.", **overrides) -> dict:
    payload = {"abandon_reason": abandon_reason}
    payload.update(overrides)
    return _compact(payload)


# --- Statute waivers ------------------------------------------------------

def create_statute_waiver_payload(audit_id, covers_period_end, extended_to_date, **overrides) -> dict:
    payload = {
        "audit_id": audit_id,
        "covers_period_end": covers_period_end,
        "extended_to_date": extended_to_date,
        "signed_by_name": DEFAULTS["SIGNED_BY_NAME"],
    }
    payload.update(overrides)
    return _compact(payload)


def execute_waiver_payload(signed_date, **overrides) -> dict:
    payload = {"signed_date": signed_date}
    payload.update(overrides)
    return _compact(payload)


def void_waiver_payload(void_reason="Signature page was unsigned.", **overrides) -> dict:
    payload = {"void_reason": void_reason}
    payload.update(overrides)
    return _compact(payload)


# --- Sampling agreements --------------------------------------------------

def stratum(period_start, period_end, population_base_amount_cents, population_unit_count) -> dict:
    return {
        "period_start": period_start,
        "period_end": period_end,
        "population_base_amount_cents": population_base_amount_cents,
        "population_unit_count": population_unit_count,
    }


def create_sampling_agreement_payload(
    audit_id,
    expected_audit_version,
    strata,
    methodology="RATIO_ESTIMATION",
    confidence_level_bp=9_500,
    minimum_sample_size=1,
    supersedes_agreement_id=...,
    **overrides,
) -> dict:
    payload = {
        "audit_id": audit_id,
        "expected_audit_version": expected_audit_version,
        "methodology": methodology,
        "confidence_level_bp": confidence_level_bp,
        "minimum_sample_size": minimum_sample_size,
        "strata": strata,
        "supersedes_agreement_id": supersedes_agreement_id,
    }
    payload.update(overrides)
    return _compact(payload)


def counter_agreement_payload(
    counter_note="The sample is too small to be representative.",
    requested_minimum_sample_size=...,
    **overrides,
) -> dict:
    payload = {
        "counter_note": counter_note,
        "requested_minimum_sample_size": requested_minimum_sample_size,
    }
    payload.update(overrides)
    return _compact(payload)


def revise_agreement_payload(**overrides) -> dict:
    return _compact(dict(overrides))


def agree_agreement_payload(agreed_by_name=None, **overrides) -> dict:
    payload = {"agreed_by_name": agreed_by_name or DEFAULTS["AGREED_BY_NAME"]}
    payload.update(overrides)
    return _compact(payload)


# --- Sample units ---------------------------------------------------------

def create_sample_unit_payload(
    sampling_agreement_id,
    stratum_index,
    invoice_date,
    invoice_amount_cents,
    invoice_reference="INV-1001",
    error_class=...,
    declared_error_amount_cents=...,
    exempt_sale_amount_cents=...,
    **overrides,
) -> dict:
    payload = {
        "sampling_agreement_id": sampling_agreement_id,
        "stratum_index": stratum_index,
        "invoice_reference": invoice_reference,
        "invoice_date": invoice_date,
        "invoice_amount_cents": invoice_amount_cents,
        "exempt_sale_amount_cents": exempt_sale_amount_cents,
        "error_class": error_class,
        "declared_error_amount_cents": declared_error_amount_cents,
    }
    payload.update(overrides)
    return _compact(payload)


def redetermine_sample_unit_payload(error_class, declared_error_amount_cents=..., **overrides) -> dict:
    payload = {
        "error_class": error_class,
        "declared_error_amount_cents": declared_error_amount_cents,
    }
    payload.update(overrides)
    return _compact(payload)


# --- Exemption certificates ----------------------------------------------

def create_exemption_certificate_payload(
    audit_id,
    covered_sale_amount_cents=2_000_000,
    claimed_exemption_type="RESALE",
    purchaser_permit_number=None,
    received_before_sale=True,
    form_complete=True,
    claimed_exemption_matches_purchaser_business=True,
    sample_unit_id=...,
    **overrides,
) -> dict:
    payload = {
        "audit_id": audit_id,
        "purchaser_name": DEFAULTS["PURCHASER_NAME"],
        "purchaser_permit_number": (
            DEFAULTS["PURCHASER_PERMIT_NUMBER"]
            if purchaser_permit_number is None
            else purchaser_permit_number
        ),
        "claimed_exemption_type": claimed_exemption_type,
        "covered_sale_amount_cents": covered_sale_amount_cents,
        "received_before_sale": received_before_sale,
        "form_complete": form_complete,
        "claimed_exemption_matches_purchaser_business": (
            claimed_exemption_matches_purchaser_business
        ),
        "sample_unit_id": sample_unit_id,
    }
    payload.update(overrides)
    return _compact(payload)


def review_certificate_payload(determination, review_note=..., **overrides) -> dict:
    payload = {"determination": determination, "review_note": review_note}
    payload.update(overrides)
    return _compact(payload)


def cure_certificate_payload(**overrides) -> dict:
    return _compact(dict(overrides))


# --- Use-tax purchases ---------------------------------------------------

def create_use_tax_purchase_payload(
    audit_id,
    invoice_date,
    purchase_price_cents,
    asset_class="CONSUMABLE",
    in_state_usage_pct_bp=...,
    first_use_outside_state=...,
    months_used_outside_state=...,
    fair_market_value_at_entry_cents=...,
    tax_paid_other_state_cents=...,
    **overrides,
) -> dict:
    payload = {
        "audit_id": audit_id,
        "vendor_name": DEFAULTS["VENDOR_NAME"],
        "invoice_date": invoice_date,
        "purchase_price_cents": purchase_price_cents,
        "asset_class": asset_class,
        "in_state_usage_pct_bp": in_state_usage_pct_bp,
        "first_use_outside_state": first_use_outside_state,
        "months_used_outside_state": months_used_outside_state,
        "fair_market_value_at_entry_cents": fair_market_value_at_entry_cents,
        "tax_paid_other_state_cents": tax_paid_other_state_cents,
    }
    payload.update(overrides)
    return _compact(payload)


def reclassify_use_tax_purchase_payload(asset_class, **overrides) -> dict:
    payload = {"asset_class": asset_class}
    payload.update(overrides)
    return _compact(payload)


# --- Assessments ---------------------------------------------------------

def create_assessment_payload(audit_id, supersedes_assessment_id=..., **overrides) -> dict:
    payload = {
        "audit_id": audit_id,
        "supersedes_assessment_id": supersedes_assessment_id,
    }
    payload.update(overrides)
    return _compact(payload)


def issue_assessment_payload(notice_mailed_date, **overrides) -> dict:
    payload = {"notice_mailed_date": notice_mailed_date}
    payload.update(overrides)
    return _compact(payload)


def abate_penalty_payload(abatement_factors, **overrides) -> dict:
    payload = {"abatement_factors": list(abatement_factors)}
    payload.update(overrides)
    return _compact(payload)


def collection_referral_payload(referral_note="Balance unpaid past the demand date.", **overrides) -> dict:
    payload = {"referral_note": referral_note}
    payload.update(overrides)
    return _compact(payload)


# --- Ledger --------------------------------------------------------------

def create_assessment_adjustment_payload(
    assessment_id, expected_assessment_version, amount_cents, kind="PAYMENT", **overrides
) -> dict:
    payload = {
        "assessment_id": assessment_id,
        "expected_assessment_version": expected_assessment_version,
        "kind": kind,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return _compact(payload)


def reverse_adjustment_payload(reversal_reason="Posted against the wrong notice.", **overrides) -> dict:
    payload = {"reversal_reason": reversal_reason}
    payload.update(overrides)
    return _compact(payload)


# --- Appeal proceedings --------------------------------------------------

def create_appeal_proceeding_payload(
    assessment_id,
    forum="INFORMAL_CONFERENCE",
    protest_basis=None,
    predecessor_proceeding_id=...,
    **overrides,
) -> dict:
    payload = {
        "assessment_id": assessment_id,
        "forum": forum,
        "protest_basis": protest_basis or DEFAULTS["PROTEST_BASIS"],
        "predecessor_proceeding_id": predecessor_proceeding_id,
    }
    payload.update(overrides)
    return _compact(payload)


def decision_payload(outcome, reduction_amount_cents=..., decision_rationale=..., **overrides) -> dict:
    payload = {
        "outcome": outcome,
        "reduction_amount_cents": reduction_amount_cents,
        "decision_rationale": decision_rationale,
    }
    payload.update(overrides)
    return _compact(payload)


# --- Payment arrangements ------------------------------------------------

def installment_plan_payload(
    assessment_id, monthly_installment_cents, term_months, hardship_documented=..., **overrides
) -> dict:
    payload = {
        "assessment_id": assessment_id,
        "arrangement_type": "INSTALLMENT_PLAN",
        "monthly_installment_cents": monthly_installment_cents,
        "term_months": term_months,
        "hardship_documented": hardship_documented,
    }
    payload.update(overrides)
    return _compact(payload)


def offer_in_compromise_payload(
    assessment_id, offer_amount_cents, hardship_documented=..., **overrides
) -> dict:
    payload = {
        "assessment_id": assessment_id,
        "arrangement_type": "OFFER_IN_COMPROMISE",
        "offer_amount_cents": offer_amount_cents,
        "hardship_documented": hardship_documented,
    }
    payload.update(overrides)
    return _compact(payload)


def arrangement_payment_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return _compact(payload)


def default_arrangement_payload(default_reason="Three consecutive installments missed.", **overrides) -> dict:
    payload = {"default_reason": default_reason}
    payload.update(overrides)
    return _compact(payload)


# --- Logical clock -------------------------------------------------------

def set_clock_payload(to_iso8601=DEFAULT_LOGICAL_CLOCK, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return _compact(payload)
