"""Payload factories — one per entity, input fields only (PRD §3)."""

CANONICAL_CASE = {
    "case_number": "UR-2026-104",
    "utility_name": "Cascade Power & Light",
    "test_year_start": "2025-01-01T00:00:00Z",
    "test_year_end": "2025-12-31T00:00:00Z",
    "return_on_rate_base_bp": 750,
    "proposed_revenue_requirement_cents": 1897500000,
    "allocation_method": "COINCIDENT_PEAK",
}

RES_TIERS = [
    {"up_to_kwh": 300, "rate_mills": 700},
    {"up_to_kwh": 600, "rate_mills": 900},
    {"up_to_kwh": None, "rate_mills": 1100},
]
COM_TIERS = [
    {"up_to_kwh": 1000, "rate_mills": 800},
    {"up_to_kwh": None, "rate_mills": 1000},
]

RES_CLASS = {
    "class_code": "RESIDENTIAL",
    "customer_count": 20000,
    "monthly_kwh_per_customer": 500,
    "annual_kwh": 120000000,
    "coincident_peak_kw": 120000,
    "average_demand_kw": 80000,
    "present_customer_charge_cents": 800,
    "present_tiers": RES_TIERS,
}
COM_CLASS = {
    "class_code": "COMMERCIAL",
    "customer_count": 2000,
    "monthly_kwh_per_customer": 2500,
    "annual_kwh": 60000000,
    "coincident_peak_kw": 40000,
    "average_demand_kw": 20000,
    "present_customer_charge_cents": 2500,
    "present_tiers": COM_TIERS,
}

# Net rate base 2,400,000,000 (3.0e9 - 5.0e8 + 1.0e8 - 2.0e8).
RB1 = {
    "label": "Generation plant",
    "plant_in_service_cents": 3000000000,
    "accumulated_depreciation_cents": 500000000,
    "working_capital_cents": 100000000,
    "accumulated_deferred_taxes_cents": 200000000,
}
# Net rate base 900,000,000 (1.0e9 - 1.0e8).
RB2 = {
    "label": "Distribution plant",
    "plant_in_service_cents": 1000000000,
    "accumulated_depreciation_cents": 100000000,
    "working_capital_cents": 0,
    "accumulated_deferred_taxes_cents": 0,
}

# Storm deferral: principal 10,000,001 over 4 months (base 2,500,000, tail 2,500,001).
RA1 = {
    "asset_name": "Storm restoration deferral",
    "principal_cents": 10000001,
    "incurrence_start": "2024-06-01T00:00:00Z",
    "incurrence_end": "2024-12-31T00:00:00Z",
    "amortization_months": 4,
}

# RES 2027 tariff: annual revenue 12*20000*(900 + 2250 + 1900) = 1,212,000,000.
T_RES_2027 = {
    "label": "RES schedule 2027",
    "proposed_customer_charge_cents": 900,
    "proposed_tiers": [
        {"up_to_kwh": 300, "rate_mills": 750},
        {"up_to_kwh": 600, "rate_mills": 950},
        {"up_to_kwh": None, "rate_mills": 1200},
    ],
    "effective_start": "2027-01-01T00:00:00Z",
    "effective_end": "2028-01-01T00:00:00Z",
}
# COM 2027 tariff: annual revenue 12*2000*(1462 + 27500) = 695,088,000.
T_COM_2027 = {
    "label": "COM schedule 2027",
    "proposed_customer_charge_cents": 1462,
    "proposed_tiers": [{"up_to_kwh": None, "rate_mills": 1100}],
    "effective_start": "2027-01-01T00:00:00Z",
    "effective_end": "2028-01-01T00:00:00Z",
}


def create_rate_case_payload(**overrides) -> dict:
    payload = dict(CANONICAL_CASE)
    payload.update(overrides)
    return payload


def create_test_year_entry_payload(rate_case_id, **overrides) -> dict:
    payload = {
        "rate_case_id": rate_case_id,
        "account_code": "900",
        "category": "O_AND_M",
        "booked_amount_cents": 1000000000,
    }
    payload.update(overrides)
    return payload


def create_adjustment_payload(rate_case_id, test_year_entry_id, **overrides) -> dict:
    payload = {
        "rate_case_id": rate_case_id,
        "test_year_entry_id": test_year_entry_id,
        "amount_cents": 50000000,
        "reason": "Annualize pension cost",
    }
    payload.update(overrides)
    return payload


def create_rate_base_item_payload(rate_case_id, **overrides) -> dict:
    payload = {"rate_case_id": rate_case_id}
    payload.update(RB1)
    payload.update(overrides)
    return payload


def create_customer_class_payload(rate_case_id, **overrides) -> dict:
    payload = {"rate_case_id": rate_case_id}
    payload.update(RES_CLASS)
    payload["present_tiers"] = [dict(t) for t in RES_CLASS["present_tiers"]]
    payload.update(overrides)
    return payload


def create_intervenor_payload(rate_case_id, **overrides) -> dict:
    payload = {
        "rate_case_id": rate_case_id,
        "party_name": "AAA Industrial Group",
        "representative_name": "Rae Torres",
        "contact_email": "rae@aaa.example",
    }
    payload.update(overrides)
    return payload


def create_data_request_payload(rate_case_id, **overrides) -> dict:
    payload = {
        "rate_case_id": rate_case_id,
        "subject": "Pension normalization",
        "body": "Produce workpapers supporting adjustment A1",
    }
    payload.update(overrides)
    return payload


def create_settlement_proposal_payload(rate_case_id, expected_rate_case_version, **overrides) -> dict:
    payload = {
        "rate_case_id": rate_case_id,
        "proposed_revenue_requirement_cents": 1850000000,
        "terms": "Black-box settlement at 1.85B cents",
        "expected_rate_case_version": expected_rate_case_version,
    }
    payload.update(overrides)
    return payload


def create_regulatory_asset_payload(rate_case_id, **overrides) -> dict:
    payload = {"rate_case_id": rate_case_id}
    payload.update(RA1)
    payload.update(overrides)
    return payload


def create_tariff_rate_payload(rate_case_id, customer_class_id, **overrides) -> dict:
    payload = {"rate_case_id": rate_case_id, "customer_class_id": customer_class_id}
    payload.update(T_RES_2027)
    payload["proposed_tiers"] = [dict(t) for t in T_RES_2027["proposed_tiers"]]
    payload.update(overrides)
    return payload


def create_compliance_filing_payload(rate_case_id, expected_rate_case_version, **overrides) -> dict:
    payload = {
        "rate_case_id": rate_case_id,
        "period_label": "RATE_YEAR_1",
        "actual_revenue_by_class": [
            {"class_code": "RESIDENTIAL", "actual_revenue_cents": 1850000000},
        ],
        "expected_rate_case_version": expected_rate_case_version,
    }
    payload.update(overrides)
    return payload
