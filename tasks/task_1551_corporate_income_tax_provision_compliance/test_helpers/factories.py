"""Payload factories — one per entity, input fields only.

Defaults mirror the canonical FY2026 scenario used across the test suite:
fiscal year 2026-01-01..2026-12-31, enacted federal rate 2100 bp,
pretax book income 100,000,000 cents, prior-year tax 8,000,000 cents.
"""

FY2026_DEFAULTS = {
    "fiscal_year_label": "FY2026",
    "period_start_date": "2026-01-01",
    "period_end_date": "2026-12-31",
    "enacted_federal_rate_bp": 2100,
    "pretax_book_income_cents": 100000000,
    "prior_year_total_tax_cents": 8000000,
}

US_FED_DEFAULTS = {
    "code": "US-FED",
    "name": "United States Federal",
    "level": "FEDERAL",
    "statutory_rate_bp": 2100,
    "apportionment_pct_bp": 10000,
    "return_due_month": 4,
    "return_due_day": 15,
    "extension_months": 6,
}


def create_tax_year_payload(**overrides) -> dict:
    defaults = dict(FY2026_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_jurisdiction_payload(**overrides) -> dict:
    defaults = dict(US_FED_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_difference_payload(tax_year_id, jurisdiction_id=None,
                              description="accrued warranty",
                              book_amount_cents=5000000,
                              tax_amount_cents=2000000,
                              difference_type="TEMPORARY",
                              **overrides) -> dict:
    defaults = {
        "tax_year_id": tax_year_id,
        "description": description,
        "book_amount_cents": book_amount_cents,
        "tax_amount_cents": tax_amount_cents,
        "difference_type": difference_type,
    }
    if jurisdiction_id is not None:
        defaults["jurisdiction_id"] = jurisdiction_id
    defaults.update(overrides)
    return defaults


def create_valuation_allowance_payload(tax_year_id, expected_tax_year_version,
                                       more_likely_than_not=False,
                                       projected_taxable_income_cents=0,
                                       reversing_dtl_cents=0,
                                       assessment_note=None,
                                       **overrides) -> dict:
    defaults = {
        "tax_year_id": tax_year_id,
        "more_likely_than_not": more_likely_than_not,
        "projected_taxable_income_cents": projected_taxable_income_cents,
        "reversing_dtl_cents": reversing_dtl_cents,
        "expected_tax_year_version": expected_tax_year_version,
    }
    if assessment_note is not None:
        defaults["assessment_note"] = assessment_note
    defaults.update(overrides)
    return defaults


def create_utp_payload(tax_year_id, jurisdiction_id,
                       description="transfer pricing",
                       position_amount_cents=1000000,
                       **overrides) -> dict:
    defaults = {
        "tax_year_id": tax_year_id,
        "jurisdiction_id": jurisdiction_id,
        "description": description,
        "position_amount_cents": position_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_generate_schedule_payload(tax_year_id, jurisdiction_id,
                                     method="CURRENT_YEAR_ANNUALIZED",
                                     **overrides) -> dict:
    defaults = {
        "tax_year_id": tax_year_id,
        "jurisdiction_id": jurisdiction_id,
        "method": method,
    }
    defaults.update(overrides)
    return defaults


def create_estimated_payment_payload(tax_year_id, jurisdiction_id,
                                     quarter_index=1,
                                     period_start_date="2026-01-01",
                                     period_end_date="2026-03-31",
                                     due_date="2026-04-15",
                                     method="CURRENT_YEAR_ANNUALIZED",
                                     scheduled_amount_cents=552537,
                                     **overrides) -> dict:
    defaults = {
        "tax_year_id": tax_year_id,
        "jurisdiction_id": jurisdiction_id,
        "quarter_index": quarter_index,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "due_date": due_date,
        "method": method,
        "scheduled_amount_cents": scheduled_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_filing_payload(tax_year_id, jurisdiction_id,
                          original_due_date="2027-04-15",
                          **overrides) -> dict:
    defaults = {
        "tax_year_id": tax_year_id,
        "jurisdiction_id": jurisdiction_id,
        "original_due_date": original_due_date,
    }
    defaults.update(overrides)
    return defaults


def create_notice_payload(jurisdiction_id, audit_case_id=None,
                          notice_type="INFORMATION_REQUEST",
                          received_on="2026-01-10",
                          response_due_on="2026-02-09",
                          **overrides) -> dict:
    defaults = {
        "jurisdiction_id": jurisdiction_id,
        "notice_type": notice_type,
        "received_on": received_on,
        "response_due_on": response_due_on,
    }
    if audit_case_id is not None:
        defaults["audit_case_id"] = audit_case_id
    defaults.update(overrides)
    return defaults


def create_audit_payload(tax_year_id, jurisdiction_id,
                         exam_period_start="2026-01-01",
                         exam_period_end="2027-01-01",
                         **overrides) -> dict:
    defaults = {
        "tax_year_id": tax_year_id,
        "jurisdiction_id": jurisdiction_id,
        "exam_period_start": exam_period_start,
        "exam_period_end": exam_period_end,
    }
    defaults.update(overrides)
    return defaults
