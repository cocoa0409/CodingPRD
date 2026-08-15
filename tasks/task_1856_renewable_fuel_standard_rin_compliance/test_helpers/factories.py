"""Payload factories — one per entity, input fields only (PRD §3)."""

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_account_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "company_name": f"Acme Refining {n}",
        "epa_registration_id": f"EPA-ACME-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_obligation_year_payload(**overrides) -> dict:
    defaults = {
        "year": 2026,
        "projected_volume_gal": 1000,
        "std_cellulosic_pct": 10.0,
        "std_biomass_diesel_pct": 20.0,
        "std_advanced_pct": 30.0,
        "std_total_pct": 40.0,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "vendor_name": f"GreenRIN LLC {n}",
        "qap_audited": True,
    }
    defaults.update(overrides)
    return defaults


def create_rin_lot_payload(**overrides) -> dict:
    defaults = {
        "d_code": "D6",
        "vintage_year": 2026,
        "gallon_qty": 100,
        "equivalence_value": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_separation_payload(**overrides) -> dict:
    defaults = {"blended_gallons": 10}
    defaults.update(overrides)
    return defaults


def create_rin_trade_payload(**overrides) -> dict:
    defaults = {
        "d_code": "D6",
        "vintage_year": 2026,
        "rin_qty": 10,
        "price_per_rin_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def create_retirement_batch_payload(**overrides) -> dict:
    defaults = {
        "category": "TOTAL_RENEWABLE",
        "d_code": "D6",
        "rin_qty": 10,
    }
    defaults.update(overrides)
    return defaults


def create_compliance_report_payload(**overrides) -> dict:
    defaults = {
        "report_type": "QUARTERLY",
        "quarter_end_date": "2026-06-30T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_attest_engagement_payload(**overrides) -> dict:
    defaults = {
        "auditor_user_id": "aud-1",
        "fieldwork_start": "2026-09-01T00:00:00Z",
        "fieldwork_end": "2026-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_state_program_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "program_type": "LCFS",
        "ci_standard_gco2e_mj": 90.0,
        "default_ci_gco2e_mj": 80.0,
    }
    defaults.update(overrides)
    return defaults


def create_state_credit_report_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "period_label": f"2026-Q{(n % 4) + 1}-{n}",
        "fuel_gallons": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_price_quote_payload(**overrides) -> dict:
    defaults = {
        "d_code": "D6",
        "vintage_year": 2026,
        "price_cents": 150,
        "effective_start": "2026-08-01T00:00:00Z",
        "effective_end": "2026-08-31T23:59:59Z",
    }
    defaults.update(overrides)
    return defaults
