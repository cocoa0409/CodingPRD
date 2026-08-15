"""Payload factories — one per writable endpoint, input fields only (PRD §3)."""
from .constants import CERTIFYING_BODY, TEST_DEFAULTS


def create_business_unit_payload(**overrides) -> dict:
    """POST /api/v1/business-units input: name, code, lead_user_id
    (+ optional inclusion_min_diverse_bidders)."""
    defaults = {
        "name": TEST_DEFAULTS["BU_NAME"],
        "code": TEST_DEFAULTS["BU_CODE"],
        "lead_user_id": TEST_DEFAULTS["BU_LEAD"],
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(**overrides) -> dict:
    """POST /api/v1/suppliers input: legal_name, tax_id, kind, contact_email."""
    defaults = {
        "legal_name": "Diverse Parts Co",
        "tax_id": "T-100",
        "kind": "DIVERSE",
        "contact_email": "d@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(**overrides) -> dict:
    """POST /api/v1/suppliers/{id}/certifications input: cert_type,
    certifying_body, certificate_number, valid_from, valid_to."""
    cert_type = overrides.get("cert_type", "MBE")
    defaults = {
        "cert_type": cert_type,
        "certifying_body": CERTIFYING_BODY.get(cert_type, "NMSDC"),
        "certificate_number": "C-100",
        "valid_from": TEST_DEFAULTS["VALID_FROM"],
        "valid_to": TEST_DEFAULTS["VALID_TO"],
    }
    defaults.update(overrides)
    return defaults


def resubmit_certification_payload(**overrides) -> dict:
    """POST /api/v1/certifications/{id}/resubmit input: certificate_number,
    valid_from, valid_to."""
    defaults = {
        "certificate_number": "C-100-R",
        "valid_from": TEST_DEFAULTS["VALID_FROM"],
        "valid_to": TEST_DEFAULTS["VALID_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_spend_record_payload(supplier_id, business_unit_id, **overrides) -> dict:
    """POST /api/v1/spend-records input: supplier_id, business_unit_id,
    amount_cents, transaction_date, payment_date (+ optional po_number)."""
    defaults = {
        "supplier_id": supplier_id,
        "business_unit_id": business_unit_id,
        "amount_cents": 100000,
        "transaction_date": "2026-02-01",
        "payment_date": "2026-02-01",
    }
    defaults.update(overrides)
    return defaults


def tier2_line(diverse_supplier_id, gross_subcontract_cents=100000,
               diverse_share_pct=100.00) -> dict:
    """One tier-2 report line: diverse_supplier_id, gross_subcontract_cents,
    diverse_share_pct."""
    return {
        "diverse_supplier_id": diverse_supplier_id,
        "gross_subcontract_cents": gross_subcontract_cents,
        "diverse_share_pct": diverse_share_pct,
    }


def create_tier2_report_payload(prime_supplier_id, business_unit_id,
                                **overrides) -> dict:
    """POST /api/v1/tier-2-reports input: prime_supplier_id, business_unit_id,
    reporting_period, lines."""
    defaults = {
        "prime_supplier_id": prime_supplier_id,
        "business_unit_id": business_unit_id,
        "reporting_period": TEST_DEFAULTS["PERIOD"],
        "lines": [],
    }
    defaults.update(overrides)
    return defaults


def replace_lines_payload(lines) -> dict:
    """PUT /api/v1/tier-2-reports/{id} input: lines."""
    return {"lines": lines}


def create_goal_payload(expected_business_unit_version, **overrides) -> dict:
    """POST /api/v1/business-units/{id}/goals input: fiscal_year, cert_category,
    goal_type, target_value (+ optional include_tier2),
    expected_business_unit_version (OCC field required by PRD §2.7)."""
    defaults = {
        "fiscal_year": 2026,
        "cert_category": "ALL",
        "goal_type": "PERCENT_OF_SPEND",
        "target_value": 50.00,
        "expected_business_unit_version": expected_business_unit_version,
    }
    defaults.update(overrides)
    return defaults


def generate_scorecard_payload(**overrides) -> dict:
    """POST /api/v1/business-units/{id}/scorecards input: reporting_period,
    attribution_basis."""
    defaults = {
        "reporting_period": TEST_DEFAULTS["PERIOD"],
        "attribution_basis": "ACCRUAL",
    }
    defaults.update(overrides)
    return defaults


def create_sourcing_event_payload(business_unit_id, **overrides) -> dict:
    """POST /api/v1/sourcing-events input: business_unit_id, title,
    estimated_value_cents (+ optional required_diverse_bidders)."""
    defaults = {
        "business_unit_id": business_unit_id,
        "title": "Sourcing event",
        "estimated_value_cents": TEST_DEFAULTS["ESTIMATED_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_invitation_payload(supplier_id, **overrides) -> dict:
    """POST /api/v1/sourcing-events/{id}/invitations input: supplier_id."""
    defaults = {"supplier_id": supplier_id}
    defaults.update(overrides)
    return defaults


def respond_invitation_payload(response="BID_SUBMITTED") -> dict:
    """POST /api/v1/invitations/{id}/respond input: response."""
    return {"response": response}


def award_event_payload(award_supplier_id, award_amount_cents,
                        inclusion_waiver_reason=None) -> dict:
    """POST /api/v1/sourcing-events/{id}/award input: award_supplier_id,
    award_amount_cents (+ optional inclusion_waiver_reason)."""
    payload = {
        "award_supplier_id": award_supplier_id,
        "award_amount_cents": award_amount_cents,
    }
    if inclusion_waiver_reason is not None:
        payload["inclusion_waiver_reason"] = inclusion_waiver_reason
    return payload


def create_engagement_payload(**overrides) -> dict:
    """POST /api/v1/suppliers/{id}/development-engagements input: track,
    start_date, end_date, mentor_name, capacity_score_before."""
    defaults = {
        "track": "MENTORING",
        "start_date": "2026-03-01",
        "end_date": "2026-06-30",
        "mentor_name": "Mentor A",
        "capacity_score_before": 40,
    }
    defaults.update(overrides)
    return defaults


def complete_engagement_payload(capacity_score_after=75) -> dict:
    """POST /api/v1/development-engagements/{id}/complete input:
    capacity_score_after."""
    return {"capacity_score_after": capacity_score_after}


def create_audit_case_payload(supplier_id, certification_id, **overrides) -> dict:
    """POST /api/v1/audit-cases input: supplier_id, certification_id, reason."""
    defaults = {
        "supplier_id": supplier_id,
        "certification_id": certification_id,
        "reason": "RANDOM_SAMPLE",
    }
    defaults.update(overrides)
    return defaults


def record_outcome_payload(outcome="CONFIRMED") -> dict:
    """POST /api/v1/audit-cases/{id}/record-outcome input: outcome."""
    return {"outcome": outcome}


def set_clock_payload(to_iso8601) -> dict:
    """POST /api/v1/_clock/set_current_utc input: to_iso8601."""
    return {"to_iso8601": to_iso8601}
