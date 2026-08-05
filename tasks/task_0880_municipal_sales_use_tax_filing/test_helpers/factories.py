"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LEGAL_NAME": "Test Business",
    "EMAIL_DOMAIN": "example.com",
    "JURISDICTION_CODE": "CITY",
    "JURISDICTION_NAME": "City",
    "RATE_BPS": 850,
    "PERIOD_KEY": "2026-Q1",
    "PERIOD_START": "2026-01-01T00:00:00Z",
    "PERIOD_END": "2026-03-31T00:00:00Z",
    "FILING_DUE": "2026-04-20T00:00:00Z",
}

_email_seq = [0]


def _unique_email(prefix="tp"):
    _email_seq[0] += 1
    return f"{prefix}{_email_seq[0]}@{DEFAULTS['EMAIL_DOMAIN']}"


def create_taxpayer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "entity_type": "LLC",
        "email": _unique_email(),
        "filing_frequency": "QUARTERLY",
    }
    defaults.update(overrides)
    return defaults


def create_jurisdiction_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["JURISDICTION_CODE"],
        "name": DEFAULTS["JURISDICTION_NAME"],
        "rate_bps": DEFAULTS["RATE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_return_line(jurisdiction_id, gross_sales_cents=1000000,
                       exempt_sales_cents=0, deduction_cents=0) -> dict:
    return {
        "jurisdiction_id": jurisdiction_id,
        "gross_sales_cents": gross_sales_cents,
        "exempt_sales_cents": exempt_sales_cents,
        "deduction_cents": deduction_cents,
    }


def create_return_payload(taxpayer_id, jurisdiction_id=None, lines=None,
                          **overrides) -> dict:
    if lines is None:
        if jurisdiction_id is None:
            raise ValueError("create_return_payload needs jurisdiction_id or lines")
        lines = [create_return_line(jurisdiction_id)]
    defaults = {
        "taxpayer_id": taxpayer_id,
        "period_key": DEFAULTS["PERIOD_KEY"],
        "period_start_date": DEFAULTS["PERIOD_START"],
        "period_end_date": DEFAULTS["PERIOD_END"],
        "filing_due_date": DEFAULTS["FILING_DUE"],
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(taxpayer_id, **overrides) -> dict:
    defaults = {
        "taxpayer_id": taxpayer_id,
        "exemption_type": "RESALE",
        "certificate_number": "R-1",
        "effective_date": "2026-01-01T00:00:00Z",
        "expiry_date": "2026-07-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_remittance_payload(taxpayer_id, amount_cents=100000,
                              remittance_type="PAYMENT", **overrides) -> dict:
    defaults = {
        "taxpayer_id": taxpayer_id,
        "remittance_type": remittance_type,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(taxpayer_id, audit_type="FIELD_AUDIT",
                         period_key="2026-Q1", **overrides) -> dict:
    defaults = {
        "taxpayer_id": taxpayer_id,
        "audit_type": audit_type,
        "period_key": period_key,
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(taxpayer_id, tax_deficiency_cents=100000,
                              assessment_type="LATE_FILING",
                              original_due_date="2026-01-20T00:00:00Z",
                              **overrides) -> dict:
    defaults = {
        "taxpayer_id": taxpayer_id,
        "assessment_type": assessment_type,
        "tax_deficiency_cents": tax_deficiency_cents,
        "original_due_date": original_due_date,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(assessment_id, grounds="Dispute the assessment.",
                          **overrides) -> dict:
    defaults = {
        "assessment_id": assessment_id,
        "grounds": grounds,
    }
    defaults.update(overrides)
    return defaults


def create_refund_claim_payload(taxpayer_id, return_id, expected_return_version,
                                claim_amount_cents=5000, reason="TAXPAYER_ERROR",
                                overpayment_date="2026-04-01T00:00:00Z",
                                **overrides) -> dict:
    defaults = {
        "taxpayer_id": taxpayer_id,
        "return_id": return_id,
        "claim_amount_cents": claim_amount_cents,
        "reason": reason,
        "overpayment_date": overpayment_date,
        "expected_return_version": expected_return_version,
    }
    defaults.update(overrides)
    return defaults
