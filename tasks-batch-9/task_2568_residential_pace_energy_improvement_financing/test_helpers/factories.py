"""Request-payload builders.

Each builder returns a valid payload for one endpoint and accepts ``**overrides``
so a test can perturb exactly the field under examination while everything else
stays admissible.  Field names are the program's own, never abbreviated.
"""

from typing import Any, List, Optional

from .constants import COUNTY_SAN_DIEGO
from .types import Payload

# ---------------------------------------------------------------------------
# Parcels
# ---------------------------------------------------------------------------

CANONICAL_APN = "06073-118-204-011"
SECOND_APN = "06073-118-204-027"
THIRD_APN = "06073-118-204-088"

CANONICAL_OWNER_NAME = "Ada Ruiz"
SECOND_OWNER_NAME = "Ben Ortiz"
THIRD_OWNER_NAME = "Cleo Marsh"


def property_payload(**overrides: Any) -> Payload:
    payload: Payload = {
        "apn": CANONICAL_APN,
        "county_code": COUNTY_SAN_DIEGO,
        "owner_full_name": CANONICAL_OWNER_NAME,
        "owner_birth_date": "1971-04-09",
        "owner_email": "ada@example.com",
        "occupancy_type": "OWNER_OCCUPIED",
        "assessed_value_cents": 40000000,
        "annual_property_tax_cents": 420000,
    }
    payload.update(overrides)
    return payload


def second_property_payload(**overrides: Any) -> Payload:
    payload = property_payload(
        apn=SECOND_APN,
        owner_full_name=SECOND_OWNER_NAME,
        owner_birth_date="1979-06-30",
        owner_email="ben@example.com",
        annual_property_tax_cents=415000,
    )
    payload.update(overrides)
    return payload


def third_property_payload(**overrides: Any) -> Payload:
    payload = property_payload(
        apn=THIRD_APN,
        owner_full_name=THIRD_OWNER_NAME,
        owner_birth_date="1968-11-02",
        owner_email="cleo@example.com",
        annual_property_tax_cents=430000,
    )
    payload.update(overrides)
    return payload


def valuation_payload(**overrides: Any) -> Payload:
    payload: Payload = {"assessed_value_cents": 40000000}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Mortgage liens
# ---------------------------------------------------------------------------


def mortgage_lien_payload(property_id: str, **overrides: Any) -> Payload:
    payload: Payload = {
        "property_id": property_id,
        "holder_name": "Harbor Federal Savings",
        "lien_position": 1,
        "current_balance_cents": 25000000,
        "recorded_on": "2019-03-14",
    }
    payload.update(overrides)
    return payload


def second_mortgage_lien_payload(property_id: str, **overrides: Any) -> Payload:
    payload = mortgage_lien_payload(
        property_id, holder_name="Cascade Mutual Bank", recorded_on="2020-08-05"
    )
    payload.update(overrides)
    return payload


def consent_response_payload(response: str = "CONSENT", **overrides: Any) -> Payload:
    payload: Payload = {"response": response}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Eligible products
# ---------------------------------------------------------------------------


def solar_product_payload(**overrides: Any) -> Payload:
    payload: Payload = {
        "product_code": "SOLAR_PV_ROOF",
        "category": "SOLAR_PV",
        "useful_life_years": 25,
        "max_annual_savings_cents": 300000,
    }
    payload.update(overrides)
    return payload


def hvac_product_payload(**overrides: Any) -> Payload:
    payload: Payload = {
        "product_code": "HVAC_HEATPUMP",
        "category": "HVAC",
        "useful_life_years": 18,
        "max_annual_savings_cents": 120000,
    }
    payload.update(overrides)
    return payload


def water_product_payload(**overrides: Any) -> Payload:
    """A ten-year product: the shortest useful life the annuity table pins."""
    payload: Payload = {
        "product_code": "WATER_FIXTURES",
        "category": "WATER_EFFICIENCY",
        "useful_life_years": 10,
        "max_annual_savings_cents": 80000,
    }
    payload.update(overrides)
    return payload


def product_payload(
    product_code: str,
    category: str,
    useful_life_years: int,
    max_annual_savings_cents: int,
    **overrides: Any
) -> Payload:
    payload: Payload = {
        "product_code": product_code,
        "category": category,
        "useful_life_years": useful_life_years,
        "max_annual_savings_cents": max_annual_savings_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Contractors
# ---------------------------------------------------------------------------

CANONICAL_CONTRACTOR_NAME = "Ridgeline Retrofit LLC"
CANONICAL_LICENSE_NUMBER = "CSLB-884120"


def contractor_payload(**overrides: Any) -> Payload:
    payload: Payload = {
        "legal_name": CANONICAL_CONTRACTOR_NAME,
        "license_number": CANONICAL_LICENSE_NUMBER,
        "license_expires_on": "2030-06-30",
        "workmanship_warranty_years": 10,
        "counties_served": [COUNTY_SAN_DIEGO],
    }
    payload.update(overrides)
    return payload


def second_contractor_payload(**overrides: Any) -> Payload:
    payload = contractor_payload(
        legal_name="Sunward Mechanical Inc", license_number="CSLB-771905"
    )
    payload.update(overrides)
    return payload


def reinstate_payload(note: str = "Remedy verified and standing restored", **overrides: Any) -> Payload:
    payload: Payload = {"note": note}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Applications and measures
# ---------------------------------------------------------------------------


def application_payload(
    property_id: str, contractor_id: str, requested_term_years: int = 20, **overrides: Any
) -> Payload:
    payload: Payload = {
        "property_id": property_id,
        "contractor_id": contractor_id,
        "requested_term_years": requested_term_years,
    }
    payload.update(overrides)
    return payload


def measure_payload(
    product_id: str,
    expected_application_version: int,
    installed_cost_cents: int,
    estimated_annual_savings_cents: int,
    **overrides: Any
) -> Payload:
    payload: Payload = {
        "product_id": product_id,
        "installed_cost_cents": installed_cost_cents,
        "estimated_annual_savings_cents": estimated_annual_savings_cents,
        "expected_application_version": expected_application_version,
    }
    payload.update(overrides)
    return payload


def solar_measure_payload(
    product_id: str, expected_application_version: int, **overrides: Any
) -> Payload:
    return measure_payload(
        product_id, expected_application_version, 3000000, 220000, **overrides
    )


def hvac_measure_payload(
    product_id: str, expected_application_version: int, **overrides: Any
) -> Payload:
    return measure_payload(
        product_id, expected_application_version, 1200000, 100000, **overrides
    )


def underwrite_proceed_payload(valuation_basis: str = "ASSESSED", **overrides: Any) -> Payload:
    payload: Payload = {"decision": "PROCEED", "valuation_basis": valuation_basis}
    payload.update(overrides)
    return payload


def underwrite_cure_payload(
    cure_reason_codes: Optional[List[str]] = None, **overrides: Any
) -> Payload:
    payload: Payload = {
        "decision": "CURE",
        "cure_reason_codes": list(cure_reason_codes or ["MEASURE_SIR_FAIL"]),
    }
    payload.update(overrides)
    return payload


def underwrite_decline_payload(decline_reason_code: str = "SIR_FLOOR", **overrides: Any) -> Payload:
    payload: Payload = {"decision": "DECLINE", "decline_reason_code": decline_reason_code}
    payload.update(overrides)
    return payload


def cure_payload(note: str = "Measure set amended", **overrides: Any) -> Payload:
    payload: Payload = {"note": note}
    payload.update(overrides)
    return payload


def approve_payload(note: str = "Consent file complete", **overrides: Any) -> Payload:
    payload: Payload = {"note": note}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Financing agreements
# ---------------------------------------------------------------------------


def agreement_payload(
    application_id: str,
    expected_application_version: int,
    term_years: int = 20,
    apr_bps: int = 800,
    **overrides: Any
) -> Payload:
    payload: Payload = {
        "application_id": application_id,
        "term_years": term_years,
        "apr_bps": apr_bps,
        "expected_application_version": expected_application_version,
    }
    payload.update(overrides)
    return payload


def sign_agreement_payload(signature_name: str, **overrides: Any) -> Payload:
    payload: Payload = {"signature_name": signature_name}
    payload.update(overrides)
    return payload


def oral_confirmation_payload(
    oral_confirmation_reference: str = "CALL-20260812-0417", **overrides: Any
) -> Payload:
    payload: Payload = {"oral_confirmation_reference": oral_confirmation_reference}
    payload.update(overrides)
    return payload


def rescind_payload(
    reason: str = "Owner reconsidered after reading the disclosure packet", **overrides: Any
) -> Payload:
    payload: Payload = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Completion certificates and disbursements
# ---------------------------------------------------------------------------


def certificate_payload(
    application_id: str, measure_ids: List[str], certified_cost_cents: int, **overrides: Any
) -> Payload:
    payload: Payload = {
        "application_id": application_id,
        "measure_ids": list(measure_ids),
        "certified_cost_cents": certified_cost_cents,
        "contractor_attestation_note": "All listed measures installed and operational",
    }
    payload.update(overrides)
    return payload


def sign_certificate_payload(homeowner_signature_name: str, **overrides: Any) -> Payload:
    payload: Payload = {"homeowner_signature_name": homeowner_signature_name}
    payload.update(overrides)
    return payload


def verify_certificate_payload(decision: str = "APPROVE", **overrides: Any) -> Payload:
    payload: Payload = {"decision": decision}
    payload.update(overrides)
    return payload


def disbursement_payload(
    application_id: str,
    completion_certificate_id: str,
    contractor_id: str,
    amount_cents: int,
    **overrides: Any
) -> Payload:
    payload: Payload = {
        "application_id": application_id,
        "completion_certificate_id": completion_certificate_id,
        "contractor_id": contractor_id,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def reverse_payload(
    reversal_reason: str = "Unremedied severe defect escalated to contractor recourse",
    **overrides: Any
) -> Payload:
    payload: Payload = {"reversal_reason": reversal_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Workmanship complaints
# ---------------------------------------------------------------------------


def complaint_payload(
    application_id: str,
    contractor_id: str,
    severity: str = "MINOR",
    category: str = "WORKMANSHIP_DEFECT",
    description: str = "Array racking loose at two mounts and flashing lifted",
    **overrides: Any
) -> Payload:
    payload: Payload = {
        "application_id": application_id,
        "contractor_id": contractor_id,
        "category": category,
        "severity": severity,
        "description": description,
    }
    payload.update(overrides)
    return payload


def uphold_payload(remedy_deadline_on: str, note: str = "Re-anchor racking and replace flashing", **overrides: Any) -> Payload:
    payload: Payload = {
        "decision": "UPHOLD_REMEDY",
        "remedy_deadline_on": remedy_deadline_on,
        "note": note,
    }
    payload.update(overrides)
    return payload


def adjudicate_payload(decision: str, **overrides: Any) -> Payload:
    payload: Payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Assessments, installments, transfers and roll runs
# ---------------------------------------------------------------------------


def assessment_payload(application_id: str, first_tax_year: int = 2027, **overrides: Any) -> Payload:
    payload: Payload = {
        "application_id": application_id,
        "first_tax_year": first_tax_year,
    }
    payload.update(overrides)
    return payload


def installment_payment_payload(amount_cents: int, **overrides: Any) -> Payload:
    payload: Payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def prepayment_payload(
    amount_cents: int, expected_assessment_version: int, **overrides: Any
) -> Payload:
    payload: Payload = {
        "amount_cents": amount_cents,
        "expected_assessment_version": expected_assessment_version,
    }
    payload.update(overrides)
    return payload


def transfer_quote_payload(
    assessment_id: str,
    closing_date: str,
    mode: str = "ASSUME_WITH_PROPERTY",
    buyer_full_name: str = "Cara Vela",
    buyer_birth_date: str = "1984-02-11",
    **overrides: Any
) -> Payload:
    payload: Payload = {
        "assessment_id": assessment_id,
        "mode": mode,
        "closing_date": closing_date,
        "buyer_full_name": buyer_full_name,
        "buyer_birth_date": buyer_birth_date,
    }
    payload.update(overrides)
    return payload


def roll_run_payload(tax_year: int, effective_date: str, **overrides: Any) -> Payload:
    payload: Payload = {"tax_year": tax_year, "effective_date": effective_date}
    payload.update(overrides)
    return payload
