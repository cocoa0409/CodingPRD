"""Payload factories — one per entity, input fields only."""

# Statement shapes referenced across the suite. All money in integer cents.
STATEMENT_SHAPES = {
    # dscr_standard 1.2982 / dscr_stress 0.7010 on a 30,000,000 x 60mo request
    "BEACON": {
        "period_end_date": "2025-12-31", "revenue_cents": 20_000_000,
        "ebitda_cents": 11_000_000, "addbacks_cents": 3_000_000,
        "distributions_cents": 800_000, "maintenance_capex_cents": 450_000,
        "existing_annual_debt_service_cents": 2_500_000,
        "total_assets_cents": 80_000_000, "total_liabilities_cents": 40_000_000,
    },
    # dscr_standard 2.1042 / dscr_stress 1.4730 on a 200,000,000 x 60mo request
    "MERIDIAN": {
        "period_end_date": "2025-12-31", "revenue_cents": 200_000_000,
        "ebitda_cents": 100_000_000, "addbacks_cents": 0,
        "distributions_cents": 0, "maintenance_capex_cents": 0,
        "existing_annual_debt_service_cents": 0,
        "total_assets_cents": 500_000_000, "total_liabilities_cents": 200_000_000,
    },
    # dscr_standard 4.2085 / dscr_stress 2.9459 on a 20,000,000 x 60mo request
    "WINDOW": {
        "period_end_date": "2025-12-31", "revenue_cents": 40_000_000,
        "ebitda_cents": 20_000_000, "addbacks_cents": 0,
        "distributions_cents": 0, "maintenance_capex_cents": 0,
        "existing_annual_debt_service_cents": 0,
        "total_assets_cents": 100_000_000, "total_liabilities_cents": 20_000_000,
    },
    # dscr_standard 2.8057 / dscr_stress 1.9640 on a 60,000,000 x 60mo request
    "HARBOR": {
        "period_end_date": "2025-12-31", "revenue_cents": 80_000_000,
        "ebitda_cents": 40_000_000, "addbacks_cents": 0,
        "distributions_cents": 0, "maintenance_capex_cents": 0,
        "existing_annual_debt_service_cents": 0,
        "total_assets_cents": 80_000_000, "total_liabilities_cents": 32_000_000,
    },
    # dscr_standard 2.6303 / dscr_stress 1.8412 on an 80,000,000 x 60mo request
    "COLD": {
        "period_end_date": "2025-12-31", "revenue_cents": 100_000_000,
        "ebitda_cents": 50_000_000, "addbacks_cents": 0,
        "distributions_cents": 0, "maintenance_capex_cents": 0,
        "existing_annual_debt_service_cents": 0,
        "total_assets_cents": 100_000_000, "total_liabilities_cents": 40_000_000,
    },
    # dscr_standard 0.6734 / dscr_stress 0.5724 on a 50,000,000 x 60mo request
    "THIN": {
        "period_end_date": "2025-12-31", "revenue_cents": 8_000_000,
        "ebitda_cents": 8_000_000, "addbacks_cents": 0,
        "distributions_cents": 0, "maintenance_capex_cents": 0,
        "existing_annual_debt_service_cents": 0,
        "total_assets_cents": 60_000_000, "total_liabilities_cents": 30_000_000,
    },
    # dscr_standard 2.1042 / dscr_stress 1.4730 on a 100,000,000 x 60mo request
    "TIER": {
        "period_end_date": "2025-12-31", "revenue_cents": 100_000_000,
        "ebitda_cents": 50_000_000, "addbacks_cents": 0,
        "distributions_cents": 0, "maintenance_capex_cents": 0,
        "existing_annual_debt_service_cents": 0,
        "total_assets_cents": 500_000_000, "total_liabilities_cents": 200_000_000,
    },
    # dscr_standard 1.4028 / dscr_stress 1.1924 on a 600,000,000 x 60mo request
    "TIER3": {
        "period_end_date": "2025-12-31", "revenue_cents": 200_000_000,
        "ebitda_cents": 200_000_000, "addbacks_cents": 0,
        "distributions_cents": 0, "maintenance_capex_cents": 0,
        "existing_annual_debt_service_cents": 0,
        "total_assets_cents": 1_000_000_000, "total_liabilities_cents": 400_000_000,
    },
    # dscr_standard 1.4028 / dscr_stress 1.1924 on a 1,200,000,000 x 60mo request
    "LARGE": {
        "period_end_date": "2025-12-31", "revenue_cents": 400_000_000,
        "ebitda_cents": 400_000_000, "addbacks_cents": 0,
        "distributions_cents": 0, "maintenance_capex_cents": 0,
        "existing_annual_debt_service_cents": 0,
        "total_assets_cents": 2_000_000_000, "total_liabilities_cents": 800_000_000,
    },
    # dscr_standard 1.4000 / dscr_stress 1.0884 on a 30,000,000 x 60mo request
    "TENURE": {
        "period_end_date": "2025-12-31", "revenue_cents": 20_000_000,
        "ebitda_cents": 13_479_805, "addbacks_cents": 0,
        "distributions_cents": 0, "maintenance_capex_cents": 0,
        "existing_annual_debt_service_cents": 2_500_000,
        "total_assets_cents": 80_000_000, "total_liabilities_cents": 60_000_000,
    },
    # dscr_standard 0.0584 / dscr_stress 0.0409 on a 30,000,000 x 60mo request
    "NOSIZE": {
        "period_end_date": "2025-12-31", "revenue_cents": 2_000_000,
        "ebitda_cents": 1_000_000, "addbacks_cents": 0,
        "distributions_cents": 0, "maintenance_capex_cents": 0,
        "existing_annual_debt_service_cents": 10_000_000,
        "total_assets_cents": 60_000_000, "total_liabilities_cents": 30_000_000,
    },
    # dscr_standard exactly 1.2500 / dscr_stress 1.0007 on a 30,000,000 x 60mo request
    "BOUNDARY_PASS": {
        "period_end_date": "2025-12-31", "revenue_cents": 16_000_000,
        "ebitda_cents": 12_035_540, "addbacks_cents": 0,
        "distributions_cents": 0, "maintenance_capex_cents": 0,
        "existing_annual_debt_service_cents": 2_500_000,
        "total_assets_cents": 80_000_000, "total_liabilities_cents": 40_000_000,
    },
    # dscr_standard 1.2499 / dscr_stress 1.0007 on a 30,000,000 x 60mo request
    "BOUNDARY_FAIL": {
        "period_end_date": "2025-12-31", "revenue_cents": 16_000_000,
        "ebitda_cents": 12_035_058, "addbacks_cents": 0,
        "distributions_cents": 0, "maintenance_capex_cents": 0,
        "existing_annual_debt_service_cents": 2_500_000,
        "total_assets_cents": 80_000_000, "total_liabilities_cents": 40_000_000,
    },
    # Restatement of BEACON: dscr_standard 1.5579 / dscr_stress 1.2463
    "BEACON_RESTATED": {
        "period_end_date": "2025-12-31", "revenue_cents": 20_000_000,
        "ebitda_cents": 15_000_000, "addbacks_cents": 0,
        "distributions_cents": 0, "maintenance_capex_cents": 0,
        "existing_annual_debt_service_cents": 2_500_000,
        "total_assets_cents": 80_000_000, "total_liabilities_cents": 40_000_000,
    },
}


def bank_officer_payload(**overrides) -> dict:
    defaults = {"full_name": "Rita RM"}
    defaults.update(overrides)
    return defaults


def borrower_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Beacon Holdings LLC",
        "naics_code": "332710",
        "relationship_since": "2018-01-01",
    }
    defaults.update(overrides)
    return defaults


def loan_application_payload(borrower_id, **overrides) -> dict:
    defaults = {
        "borrower_id": borrower_id,
        "product_type": "CRE_TERM",
        "requested_amount_cents": 30_000_000,
        "term_months": 60,
    }
    defaults.update(overrides)
    return defaults


def statement_payload(app_id, shape="BEACON", **overrides) -> dict:
    defaults = {"loan_application_id": app_id}
    defaults.update(STATEMENT_SHAPES[shape])
    defaults.update(overrides)
    return defaults


def appraiser_payload(**overrides) -> dict:
    defaults = {"name": "AppraisalCo", "license_number": "LIC-100"}
    defaults.update(overrides)
    return defaults


def appraisal_payload(app_id, appraiser_id, **overrides) -> dict:
    defaults = {
        "loan_application_id": app_id,
        "appraiser_id": appraiser_id,
        "collateral_class": "REAL_ESTATE",
        "engagement_start_date": "2026-08-03",
        "engagement_end_date": "2026-08-07",
    }
    defaults.update(overrides)
    return defaults


def receive_report_payload(**overrides) -> dict:
    defaults = {
        "appraised_value_cents": 400_000_000,
        "orderly_liquidation_value_cents": 380_000_000,
    }
    defaults.update(overrides)
    return defaults


def committee_session_payload(**overrides) -> dict:
    defaults = {
        "level": "STANDARD",
        "starts_at": "2026-08-10T14:00:00Z",
        "ends_at": "2026-08-10T15:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def committee_decision_payload(app_id, session_id, expected_version) -> dict:
    return {
        "loan_application_id": app_id,
        "committee_session_id": session_id,
        "expected_loan_application_version": expected_version,
    }


def term_sheet_payload(app_id, amount_cents, expected_version, **overrides) -> dict:
    defaults = {
        "loan_application_id": app_id,
        "amount_cents": amount_cents,
        "rate_bps": 650,
        "term_months": 60,
        "expires_at": "2026-08-20T00:00:00Z",
        "expected_loan_application_version": expected_version,
    }
    defaults.update(overrides)
    return defaults


def letter_issue_payload(**overrides) -> dict:
    defaults = {
        "expiry_date": "2026-09-01",
        "rate_lock_expires_at": "2026-08-31T23:59:59Z",
    }
    defaults.update(overrides)
    return defaults


def checklist_item_payload(app_id, **overrides) -> dict:
    defaults = {
        "loan_application_id": app_id,
        "category": "DOCUMENT",
        "label": "Executed promissory note",
    }
    defaults.update(overrides)
    return defaults


def funding_authorization_payload(app_id, **overrides) -> dict:
    defaults = {
        "loan_application_id": app_id,
        "amount_cents": 50_000_000,
        "disbursement_date": "2026-08-15",
    }
    defaults.update(overrides)
    return defaults


def covenant_payload(app_id, **overrides) -> dict:
    defaults = {
        "loan_application_id": app_id,
        "covenant_type": "DSCR_MIN",
        "threshold_value": 1.25,
        "frequency": "QUARTERLY",
    }
    defaults.update(overrides)
    return defaults


def participation_payload(app_id, **overrides) -> dict:
    defaults = {
        "loan_application_id": app_id,
        "participant_bank_name": "Bank North",
        "allocated_amount_cents": 10_000_000,
    }
    defaults.update(overrides)
    return defaults


def covenant_review_payload(**overrides) -> dict:
    defaults = {"measured_value": 1.3, "period_end_date": "2026-09-30"}
    defaults.update(overrides)
    return defaults
