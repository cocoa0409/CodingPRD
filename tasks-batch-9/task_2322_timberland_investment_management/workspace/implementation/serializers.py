"""Resource serialization: the declared field set of each entity, in order.

Only these keys ever reach a client, so the internal bookkeeping keys the store
carries (parsed dates, insertion sequence) are stripped by construction.
"""

import services

FUND_FIELDS = (
    "id", "name", "vintage_year", "committed_capital_usd", "target_cash_yield_bps",
    "opening_cash_usd", "cash_balance_usd", "net_operating_cash_usd",
    "cash_yield_bps", "harvest_acceleration_required", "nav_usd",
    "replan_property_count", "valuation_basis_stale_count",
    "created_at", "updated_at", "version",
)

PROPERTY_FIELDS = (
    "id", "fund_id", "name", "region_code", "total_acres", "haul_distance_miles",
    "insured_value_usd", "hbu_acres", "hbu_price_per_acre_usd",
    "annual_rec_income_usd", "certification_scheme", "status", "appraisal_status",
    "appraisal_methodology", "appraised_value_usd", "appraisal_submitted_by_user_id",
    "appraisal_signed_by_user_id", "appraisal_signed_at", "certification_posture",
    "harvest_plan_status", "market_access_tier", "market_access_discount_pct",
    "insurance_rating_basis", "wildfire_hazard_index", "insect_hazard_index",
    "weather_hazard_index", "composite_risk_score", "insurance_premium_usd",
    "acquisition_price_usd", "created_at", "updated_at", "version",
)

STAND_FIELDS = (
    "id", "property_id", "split_from_stand_id", "stand_code", "acres",
    "species_code", "age_years", "site_index", "status", "plot_count",
    "mean_net_tons_per_acre", "cruise_confidence", "gross_merch_tons",
    "net_merch_tons", "reserved_tons", "committed_tons", "dedicated_tons",
    "hbu_withdrawn_tons", "available_tons", "created_at", "updated_at", "version",
)

CRUISE_PLOT_FIELDS = (
    "id", "stand_id", "plot_number", "tons_per_acre", "defect_pct", "measured_at",
    "net_tons_per_acre", "measured_by_user_id", "created_at",
)

UNDERWRITING_CASE_FIELDS = (
    "id", "property_id", "growth_variant", "discount_rate_bps",
    "stumpage_price_usd_per_ton", "bid_price_usd", "status", "revision_count",
    "timber_pv_usd", "hbu_premium_usd", "rec_income_pv_usd", "pre_fee_value_usd",
    "acquisition_fee_pct", "acquisition_fee_usd", "underwritten_value_usd",
    "authored_by_user_id", "decided_by_user_id", "decision_note",
    "created_at", "updated_at", "version",
)

HARVEST_BLOCK_FIELDS = (
    "id", "stand_id", "planned_start_date", "planned_end_date", "planned_tons",
    "actual_tons", "product_mix", "expected_stumpage_price_usd_per_ton",
    "price_index_factor", "realized_price_index_factor",
    "expected_haul_distance_miles", "growth_variant", "years_to_start",
    "projected_available_tons", "status", "provisional_net_revenue_usd",
    "final_net_revenue_usd", "severance_tax_usd", "voided_reason",
    "created_at", "updated_at", "version",
)

CARBON_PROJECT_FIELDS = (
    "id", "property_id", "registry", "crediting_period_years",
    "permanence_term_years", "baseline_tons_per_acre", "status",
    "dedicated_tons_total", "buffer_pool_tons", "buffer_deficit_tons",
    "created_at", "updated_at", "version",
)

CARBON_DEDICATION_FIELDS = (
    "id", "carbon_project_id", "stand_id", "dedicated_tons", "reduced_tons",
    "status", "permanence_end_date", "release_reason",
    "created_at", "updated_at", "version",
)

HBU_PARCEL_FIELDS = (
    "id", "stand_id", "parcel_code", "acres", "ask_price_usd",
    "contract_price_usd", "closing_costs_usd", "status", "withdrawn_tons",
    "commission_usd", "net_proceeds_usd", "derived_stand_id",
    "created_at", "updated_at", "version",
)

RECREATIONAL_LEASE_FIELDS = (
    "id", "property_id", "lessee_name", "leased_acres", "rent_per_acre_usd",
    "term_start_date", "term_end_date", "blackout_start_date", "blackout_end_date",
    "status", "annual_rent_usd", "term_days", "first_year_prorated_rent_usd",
    "earned_rent_usd", "refunded_rent_usd", "termination_effective_date",
    "created_at", "updated_at", "version",
)

CERTIFICATION_AUDIT_FIELDS = (
    "id", "property_id", "audit_type", "scheduled_date", "status",
    "major_finding_count", "open_major_count", "open_minor_count",
    "created_at", "updated_at", "version",
)

AUDIT_FINDING_FIELDS = (
    "id", "certification_audit_id", "finding_code", "severity", "indicator_ref",
    "due_date", "status", "car_text", "car_submitted_by_user_id",
    "closed_by_user_id", "rejection_count", "created_at", "updated_at", "version",
)

HAZARD_EVENT_FIELDS = (
    "id", "stand_id", "event_type", "occurred_at", "damaged_tons",
    "salvageable_tons", "insurance_claim_usd", "settled_claim_usd",
    "salvage_sold_tons", "inventory_shortfall_tons", "reallocation_log", "status",
    "created_at", "updated_at", "version",
)


def _project(rec, fields, extra=None):
    out = {}
    for field in fields:
        if extra is not None and field in extra:
            out[field] = extra[field]
        else:
            out[field] = rec.get(field)
    return out


def fund(rec):
    services.recompute_fund(rec)
    return _project(rec, FUND_FIELDS)


def prop(rec):
    return _project(rec, PROPERTY_FIELDS)


def stand(rec):
    return _project(rec, STAND_FIELDS, services.stand_buckets(rec))


def cruise_plot(rec):
    return _project(rec, CRUISE_PLOT_FIELDS)


def underwriting_case(rec):
    return _project(rec, UNDERWRITING_CASE_FIELDS)


def harvest_block(rec):
    return _project(rec, HARVEST_BLOCK_FIELDS)


def carbon_project(rec):
    return _project(
        rec, CARBON_PROJECT_FIELDS,
        {"dedicated_tons_total": services.dedicated_tons_total(rec["id"])})


def carbon_dedication(rec):
    return _project(rec, CARBON_DEDICATION_FIELDS)


def hbu_parcel(rec):
    return _project(rec, HBU_PARCEL_FIELDS)


def recreational_lease(rec):
    return _project(rec, RECREATIONAL_LEASE_FIELDS)


def certification_audit(rec):
    return _project(rec, CERTIFICATION_AUDIT_FIELDS, services.audit_counts(rec))


def audit_finding(rec):
    return _project(rec, AUDIT_FINDING_FIELDS)


def hazard_event(rec):
    return _project(rec, HAZARD_EVENT_FIELDS)


def many(serializer, records):
    return [serializer(rec) for rec in records]
