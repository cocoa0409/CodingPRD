"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "DISTRICT_NAME": "Test TIF",
    "MUNICIPALITY_NAME": "Test Town",
    "BASE_TAX_YEAR": 2025,
    "BASE_EAV_CENTS": 1_000_000_000,
    "TERM_YEARS": 23,
}


def create_district_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["DISTRICT_NAME"],
        "municipality_name": DEFAULTS["MUNICIPALITY_NAME"],
        "base_tax_year": DEFAULTS["BASE_TAX_YEAR"],
        "base_eav_cents": DEFAULTS["BASE_EAV_CENTS"],
        "term_years": DEFAULTS["TERM_YEARS"],
    }
    payload.update(overrides)
    return payload


def create_taxing_body_payload(**overrides) -> dict:
    payload = {
        "name": "School District 200",
        "body_type": "SCHOOL",
        "tax_rate": 0.05,
    }
    payload.update(overrides)
    return payload


def create_developer_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Acme Redevelopment LLC",
        "contact_email": "contact@acme.example",
    }
    payload.update(overrides)
    return payload


def create_obligation_payload(district_id, obligation_type, **overrides) -> dict:
    payload = {
        "district_id": district_id,
        "obligation_type": obligation_type,
        "principal_cents": 5_000_000,
        "interest_rate_bps": 0,
        "issue_tax_year": 2026,
        "final_maturity_tax_year": 2035,
    }
    payload.update(overrides)
    return payload


def register_obligation_payload(priority_rank, expected_district_version, **overrides) -> dict:
    payload = {
        "priority_rank": priority_rank,
        "expected_district_version": expected_district_version,
    }
    payload.update(overrides)
    return payload


def accrue_interest_payload(accrual_tax_year, **overrides) -> dict:
    payload = {"accrual_tax_year": accrual_tax_year}
    payload.update(overrides)
    return payload


def create_disbursement_payload(amount_cents, disbursement_tax_year,
                                expected_fund_version, **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "disbursement_tax_year": disbursement_tax_year,
        "expected_fund_version": expected_fund_version,
    }
    payload.update(overrides)
    return payload


def create_increment_record_payload(tax_year, current_eav_cents, **overrides) -> dict:
    payload = {"tax_year": tax_year, "current_eav_cents": current_eav_cents}
    payload.update(overrides)
    return payload


def finalize_increment_payload(collection_rate, **overrides) -> dict:
    payload = {"collection_rate": collection_rate}
    payload.update(overrides)
    return payload


def create_annual_report_payload(report_tax_year, **overrides) -> dict:
    payload = {"report_tax_year": report_tax_year}
    payload.update(overrides)
    return payload


def accept_report_payload(expected_fund_version, **overrides) -> dict:
    payload = {"expected_fund_version": expected_fund_version}
    payload.update(overrides)
    return payload


def create_surplus_agreement_payload(taxing_body_id, start_tax_year, end_tax_year,
                                     surplus_share_ppm_override, **overrides) -> dict:
    payload = {
        "taxing_body_id": taxing_body_id,
        "start_tax_year": start_tax_year,
        "end_tax_year": end_tax_year,
        "surplus_share_ppm_override": surplus_share_ppm_override,
    }
    payload.update(overrides)
    return payload


def decertify_payload(termination_type, termination_tax_year, **overrides) -> dict:
    payload = {
        "termination_type": termination_type,
        "termination_tax_year": termination_tax_year,
    }
    payload.update(overrides)
    return payload
