"""Payload factories — one per entity, input fields only.

Every factory accepts **overrides so tests can steer exactly the values the
PRD rules hinge on (thresholds, NOI, dates, fee basis) while sensible defaults
cover everything else.
"""

_DEFAULT_BORROWER = {
    "legal_name": "Test Borrower LLC",
    "contact_email": "borrower@example.com",
}

_DEFAULT_LOAN = {
    "loan_number": "LN-0001",
    "original_principal_cents": 1_000_000_000,
    "note_rate": 0.06,
    "origination_date": "2025-01-01T00:00:00Z",
    "maturity_date": "2028-06-30T00:00:00Z",
    "dscr_covenant_threshold": 1.0,
    "ltv_covenant_threshold": 0.90,
    "dscr_basis": "TTM",
    "assumption_fee_basis": "OUTSTANDING",
}

_DEFAULT_PROPERTY = {
    "address": "1 Test Way",
    "property_type": "OFFICE",
    "appraised_value_cents": 2_000_000_000,
    "appraisal_date": "2026-06-01T00:00:00Z",
}

_DEFAULT_LEASE = {
    "tenant_name": "Test Tenant",
    "suite_ref": "STE-100",
    "commencement_date": "2026-09-01T00:00:00Z",
    "expiry_date": "2027-08-31T00:00:00Z",
    "base_rent_cents_monthly": 100_000,
    "sqft": 1_000,
    "term_months": 12,
}

_DEFAULT_INSPECTOR = {
    "full_name": "Test Inspector",
    "license_no": "LIC-0001",
}

_DEFAULT_INSPECTION = {
    "scheduled_start": "2026-08-03T09:00:00Z",
    "scheduled_end": "2026-08-03T11:00:00Z",
}

_DEFAULT_POLICY = {
    "coverage_type": "PROPERTY",
    "start_date": "2026-01-01T00:00:00Z",
    "end_date": "2026-12-31T00:00:00Z",
}

_DEFAULT_ASSUMPTION = {
    "proposed_assumptor_name": "Acquirer LLC",
    "proposed_assumptor_tax_id": "TX-ACQ-1",
    "proposed_net_worth_cents": 5_000_000_000,
}

_DEFAULT_OPTION = {
    "option_seq": 1,
    "exercise_window_start": "2026-12-01T00:00:00Z",
    "exercise_window_end": "2027-03-01T00:00:00Z",
    "extension_months": 12,
    "fee_pct": 0.0025,
}


def create_borrower_payload(tax_id="TX-0001", **overrides) -> dict:
    defaults = dict(_DEFAULT_BORROWER)
    defaults["tax_id"] = tax_id
    defaults.update(overrides)
    return defaults


def create_loan_payload(borrower_id, **overrides) -> dict:
    defaults = dict(_DEFAULT_LOAN)
    defaults["borrower_id"] = borrower_id
    defaults.update(overrides)
    return defaults


def create_property_payload(**overrides) -> dict:
    defaults = dict(_DEFAULT_PROPERTY)
    defaults.update(overrides)
    return defaults


def appraise_payload(appraised_value_cents, appraisal_date, **overrides) -> dict:
    defaults = {"appraised_value_cents": appraised_value_cents,
                "appraisal_date": appraisal_date}
    defaults.update(overrides)
    return defaults


def create_statement_payload(statement_type, period_start, period_end,
                             net_operating_income_cents=None,
                             occupancy_pct=None, **overrides) -> dict:
    payload = {"statement_type": statement_type,
               "period_start": period_start,
               "period_end": period_end}
    if net_operating_income_cents is not None:
        payload["net_operating_income_cents"] = net_operating_income_cents
    if occupancy_pct is not None:
        payload["occupancy_pct"] = occupancy_pct
    payload.update(overrides)
    return payload


def create_reserve_account_payload(account_type="TI_LC", target_balance_cents=0,
                                   **overrides) -> dict:
    defaults = {"account_type": account_type,
                "target_balance_cents": target_balance_cents}
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(purpose, line_items, expected_reserve_account_version,
                                retainage_pct=None, **overrides) -> dict:
    payload = {"purpose": purpose,
               "line_items": line_items,
               "expected_reserve_account_version": expected_reserve_account_version}
    if retainage_pct is not None:
        payload["retainage_pct"] = retainage_pct
    payload.update(overrides)
    return payload


def line_item(description, amount_cents) -> dict:
    return {"description": description, "amount_cents": amount_cents}


def create_lease_payload(**overrides) -> dict:
    defaults = dict(_DEFAULT_LEASE)
    defaults.update(overrides)
    return defaults


def create_inspector_payload(license_no="LIC-0001", **overrides) -> dict:
    defaults = dict(_DEFAULT_INSPECTOR)
    defaults["license_no"] = license_no
    defaults.update(overrides)
    return defaults


def schedule_inspection_payload(inspector_id, **overrides) -> dict:
    defaults = dict(_DEFAULT_INSPECTION)
    defaults["inspector_id"] = inspector_id
    defaults.update(overrides)
    return defaults


def create_insurance_policy_payload(coverage_amount_cents, **overrides) -> dict:
    defaults = dict(_DEFAULT_POLICY)
    defaults["coverage_amount_cents"] = coverage_amount_cents
    defaults.update(overrides)
    return defaults


def create_assumption_payload(expected_loan_version, **overrides) -> dict:
    defaults = dict(_DEFAULT_ASSUMPTION)
    defaults["expected_loan_version"] = expected_loan_version
    defaults.update(overrides)
    return defaults


def create_extension_option_payload(**overrides) -> dict:
    defaults = dict(_DEFAULT_OPTION)
    defaults.update(overrides)
    return defaults
