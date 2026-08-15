"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "PORTFOLIO_NAME": "P1",
    "FIRM_NAME": "PM Co",
    "CONTACT_EMAIL": "pm@x.com",
    "ASSET_NAME": "A1",
    "ASSET_ADDRESS": "1 Main St",
    "ASSET_CLASS": "OFFICE",
    "SQFT": 100000,
    "ACQ_PRICE": 800000000,
    "ACQ_DATE": "2024-06-15",
    "HOLD_YEARS": 5,
    "LENDER_NAME": "Bank",
    "PRINCIPAL": 300000000,
    "RATE_BPS": 1000,
    "ORIGINATION": "2026-01-01",
    "MATURITY": "2028-06-30",
}


def create_portfolio_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["PORTFOLIO_NAME"]}
    defaults.update(overrides)
    return defaults


def create_property_manager_payload(**overrides) -> dict:
    defaults = {
        "firm_name": DEFAULTS["FIRM_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(portfolio_id, property_manager_id, **overrides) -> dict:
    defaults = {
        "portfolio_id": portfolio_id,
        "property_manager_id": property_manager_id,
        "name": DEFAULTS["ASSET_NAME"],
        "address": DEFAULTS["ASSET_ADDRESS"],
        "asset_class": DEFAULTS["ASSET_CLASS"],
        "net_rentable_sqft": DEFAULTS["SQFT"],
        "acquisition_price_cents": DEFAULTS["ACQ_PRICE"],
        "acquisition_date": DEFAULTS["ACQ_DATE"],
        "hold_period_years": DEFAULTS["HOLD_YEARS"],
    }
    defaults.update(overrides)
    return defaults


def create_business_plan_payload(asset_id, fiscal_year, expected_asset_version,
                                 **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "fiscal_year": fiscal_year,
        "expected_asset_version": expected_asset_version,
    }
    defaults.update(overrides)
    return defaults


def budget_line_entry(category, month_index, budget_amount_cents) -> dict:
    return {
        "category": category,
        "month_index": month_index,
        "budget_amount_cents": budget_amount_cents,
    }


def create_budget_lines_payload(plan_id, lines, **overrides) -> dict:
    defaults = {"plan_id": plan_id, "lines": lines}
    defaults.update(overrides)
    return defaults


def actuals_line_entry(budget_line_id, actual_amount_cents) -> dict:
    return {"budget_line_id": budget_line_id, "actual_amount_cents": actual_amount_cents}


def create_actuals_report_payload(plan_id, month_index, lines, **overrides) -> dict:
    defaults = {"plan_id": plan_id, "month_index": month_index, "lines": lines}
    defaults.update(overrides)
    return defaults


def create_capital_project_payload(asset_id, plan_id, name, requested_amount_cents,
                                   sched_start_month, sched_end_month,
                                   **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "plan_id": plan_id,
        "name": name,
        "requested_amount_cents": requested_amount_cents,
        "sched_start_month": sched_start_month,
        "sched_end_month": sched_end_month,
    }
    defaults.update(overrides)
    return defaults


def create_funding_draw_payload(project_id, amount_cents, **overrides) -> dict:
    defaults = {"project_id": project_id, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_lease_strategy_payload(asset_id, space_type, current_occupancy_pct,
                                  proposed_asking_rate_psf_cents,
                                  market_comp_rate_psf_cents, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "space_type": space_type,
        "current_occupancy_pct": current_occupancy_pct,
        "proposed_asking_rate_psf_cents": proposed_asking_rate_psf_cents,
        "market_comp_rate_psf_cents": market_comp_rate_psf_cents,
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(asset_id, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "lender_name": DEFAULTS["LENDER_NAME"],
        "principal_balance_cents": DEFAULTS["PRINCIPAL"],
        "annual_interest_rate_bps": DEFAULTS["RATE_BPS"],
        "origination_date": DEFAULTS["ORIGINATION"],
        "maturity_date": DEFAULTS["MATURITY"],
    }
    defaults.update(overrides)
    return defaults


def create_covenant_payload(loan_id, covenant_type="MIN_DSCR", threshold_bps=12500,
                            test_frequency="QUARTERLY", **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "covenant_type": covenant_type,
        "threshold_bps": threshold_bps,
        "test_frequency": test_frequency,
    }
    defaults.update(overrides)
    return defaults


def create_covenant_test_payload(covenant_id, period_label, **overrides) -> dict:
    defaults = {"covenant_id": covenant_id, "period_label": period_label}
    defaults.update(overrides)
    return defaults


def create_valuation_payload(asset_id, effective_date, method, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "effective_date": effective_date,
        "method": method,
    }
    defaults.update(overrides)
    return defaults


def create_scorecard_payload(asset_id, period_label, occupancy_pct, collections_pct,
                             renewal_rate_pct, expense_variance_bps, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "period_label": period_label,
        "occupancy_pct": occupancy_pct,
        "collections_pct": collections_pct,
        "renewal_rate_pct": renewal_rate_pct,
        "expense_variance_bps": expense_variance_bps,
    }
    defaults.update(overrides)
    return defaults


def reforecast_line_entry(category, revised_annual_amount_cents) -> dict:
    return {"category": category,
            "revised_annual_amount_cents": revised_annual_amount_cents}


def create_reforecast_payload(plan_id, lines, **overrides) -> dict:
    defaults = {"plan_id": plan_id, "lines": lines}
    defaults.update(overrides)
    return defaults


def create_disposition_decision_payload(asset_id, trigger_type, **overrides) -> dict:
    defaults = {"asset_id": asset_id, "trigger_type": trigger_type}
    defaults.update(overrides)
    return defaults


def create_lender_report_payload(loan_id, period_label, **overrides) -> dict:
    defaults = {"loan_id": loan_id, "period_label": period_label}
    defaults.update(overrides)
    return defaults
