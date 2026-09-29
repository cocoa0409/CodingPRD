"""Request-payload builders for the Timberland Investment Management API.

Each builder returns a complete, valid body with the canonical values the suite
reuses, and accepts `**overrides` so a single field can be varied. Passing the
sentinel `...` for a field drops it from the payload entirely, which is how the
suite exercises missing required inputs.
"""

from typing import Any, Dict

# --- Canonical fund ------------------------------------------------------
CANONICAL_FUND_NAME = "Longleaf Timber Fund I"
CANONICAL_COMMITTED_CAPITAL_USD = 500000.00
CANONICAL_OPENING_CASH_USD = 400000.00

# --- Canonical tract -----------------------------------------------------
CANONICAL_PROPERTY_NAME = "Piney Creek Tract"
CANONICAL_TOTAL_ACRES = 1200.00
CANONICAL_HAUL_DISTANCE_MILES = 62
CANONICAL_INSURED_VALUE_USD = 4200000.00

# --- Canonical stand -----------------------------------------------------
CANONICAL_STAND_CODE = "PC-01"
CANONICAL_STAND_ACRES = 120.00
CANONICAL_SPECIES_CODE = "LOBLOLLY_PINE"

# --- Canonical five-plot cruise -----------------------------------------
# Rounded per-plot net tons per acre: 38.681, 37.285, 39.764, 38.127, 39.771.
# Mean 38.726 on 120.00 acres expands to 4647.12 tons at NORMAL confidence.
CANONICAL_CRUISE_PLOTS = (
    {"plot_number": 1, "tons_per_acre": 41.37, "defect_pct": 6.5},
    {"plot_number": 2, "tons_per_acre": 38.94, "defect_pct": 4.25},
    {"plot_number": 3, "tons_per_acre": 44.06, "defect_pct": 9.75},
    {"plot_number": 4, "tons_per_acre": 39.51, "defect_pct": 3.5},
    {"plot_number": 5, "tons_per_acre": 42.88, "defect_pct": 7.25},
)
CANONICAL_MEASURED_AT = "2026-07-15T00:00:00Z"
CANONICAL_NET_MERCH_TONS = 4647.12
CANONICAL_MEAN_NET_TONS_PER_ACRE = 38.726


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    merged.update(overrides)
    return {k: v for k, v in merged.items() if v is not ...}


def fund_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": CANONICAL_FUND_NAME,
            "vintage_year": 2025,
            "committed_capital_usd": CANONICAL_COMMITTED_CAPITAL_USD,
            "target_cash_yield_bps": 0,
            "opening_cash_usd": CANONICAL_OPENING_CASH_USD,
        },
        overrides,
    )


def property_payload(fund_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "fund_id": fund_id,
            "name": CANONICAL_PROPERTY_NAME,
            "region_code": "SOUTH",
            "total_acres": CANONICAL_TOTAL_ACRES,
            "haul_distance_miles": CANONICAL_HAUL_DISTANCE_MILES,
            "insured_value_usd": CANONICAL_INSURED_VALUE_USD,
            "hbu_acres": 0.00,
            "hbu_price_per_acre_usd": 0.00,
            "annual_rec_income_usd": 0.00,
            "certification_scheme": "SFI",
        },
        overrides,
    )


def stand_payload(property_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "property_id": property_id,
            "stand_code": CANONICAL_STAND_CODE,
            "acres": CANONICAL_STAND_ACRES,
            "species_code": CANONICAL_SPECIES_CODE,
            "age_years": 22,
            "site_index": 78,
        },
        overrides,
    )


def cruise_plot_payload(stand_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "stand_id": stand_id,
            "plot_number": 1,
            "tons_per_acre": 41.37,
            "defect_pct": 6.5,
            "measured_at": CANONICAL_MEASURED_AT,
        },
        overrides,
    )


def underwriting_case_payload(
    property_id: str, expected_property_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "property_id": property_id,
            "growth_variant": "YIELD_TABLE",
            "discount_rate_bps": 800,
            "stumpage_price_usd_per_ton": 60.50,
            "bid_price_usd": 100000.00,
            "expected_property_version": expected_property_version,
        },
        overrides,
    )


def harvest_block_payload(
    stand_id: str, expected_stand_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "stand_id": stand_id,
            "planned_start_date": "2027-06-01",
            "planned_end_date": "2027-09-30",
            "planned_tons": 1000.00,
            "product_mix": "MIXED",
            "expected_stumpage_price_usd_per_ton": 58.00,
            "price_index_factor": 1.05,
            "expected_haul_distance_miles": 140,
            "growth_variant": "YIELD_TABLE",
            "expected_stand_version": expected_stand_version,
        },
        overrides,
    )


def carbon_project_payload(property_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "property_id": property_id,
            "registry": "ACR",
            "crediting_period_years": 20,
            "permanence_term_years": 30,
            "baseline_tons_per_acre": 28.50,
        },
        overrides,
    )


def carbon_dedication_payload(
    carbon_project_id: str, stand_id: str, expected_stand_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "carbon_project_id": carbon_project_id,
            "stand_id": stand_id,
            "dedicated_tons": 500.00,
            "expected_stand_version": expected_stand_version,
        },
        overrides,
    )


def hbu_parcel_payload(stand_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "stand_id": stand_id,
            "parcel_code": "PC-01-HBU",
            "acres": 110.00,
            "ask_price_usd": 300000.00,
        },
        overrides,
    )


def recreational_lease_payload(property_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "property_id": property_id,
            "lessee_name": "Piney Creek Hunt Club",
            "leased_acres": 600.00,
            "rent_per_acre_usd": 22.50,
            "term_start_date": "2027-01-01",
            "term_end_date": "2028-01-01",
            "blackout_start_date": "2027-06-01",
            "blackout_end_date": "2027-12-01",
        },
        overrides,
    )


def certification_audit_payload(property_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "property_id": property_id,
            "audit_type": "SURVEILLANCE",
            "scheduled_date": "2026-09-01",
        },
        overrides,
    )


def audit_finding_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "finding_code": "SFI-2.1",
            "severity": "MINOR",
            "indicator_ref": "2.1.3",
            "due_date": "2026-12-01",
        },
        overrides,
    )


def hazard_event_payload(stand_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "stand_id": stand_id,
            "event_type": "WILDFIRE",
            "occurred_at": "2026-07-01T00:00:00Z",
            "damaged_tons": 1000.00,
        },
        overrides,
    )


def risk_review_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "insurance_rating_basis": "ACTUARIAL",
            "wildfire_hazard_index": 72.00,
            "insect_hazard_index": 64.00,
            "weather_hazard_index": 48.00,
        },
        overrides,
    )


def market_appraisal_submit_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "action": "SUBMIT",
            "appraisal_methodology": "MARKET",
            "comparable_price_per_acre_usd": 3250.00,
        },
        overrides,
    )


def income_appraisal_submit_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "action": "SUBMIT",
            "appraisal_methodology": "INCOME",
            "stabilized_noi_usd": 210000.00,
            "cap_rate_bps": 575,
        },
        overrides,
    )


def cost_appraisal_submit_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "action": "SUBMIT",
            "appraisal_methodology": "COST",
            "bare_land_value_per_acre_usd": 1150.00,
            "timber_unit_value_usd_per_ton": 26.50,
        },
        overrides,
    )
