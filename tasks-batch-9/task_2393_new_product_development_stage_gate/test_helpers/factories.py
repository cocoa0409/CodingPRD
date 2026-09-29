"""Payload factories — one per write operation, client-supplied fields only."""

DEFAULTS = {
    "PROJECT_NAME": "Sparkling Yuzu",
    "BRAND": "AquaVida",
    "PLANT_NAME": "Akron Pilot",
    "RETAILER_NAME": "SnackMart",
    "SPEC_SUMMARY": "Yuzu base A",
    "LABEL_VERSION": "LV-v1",
    "CLAIM": "Sparkling yuzu, no added sugar",
}


def stage_gate_payload(**overrides) -> dict:
    payload = {
        "gate_number": 2,
        "category": "BEVERAGE",
        "stage_from": "SCREENED",
        "stage_to": "PILOT_QUALIFIED",
        "required_deliverable_types": [],
        "quorum_size": 1,
        "veto_functions": [],
        "npv_hurdle_usd": 0.00,
        "payback_months_max": 999,
        "gross_margin_floor_pct": 0.00,
        "readiness_floor_index": 0.00,
    }
    payload.update(overrides)
    return payload


def retailer_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["RETAILER_NAME"],
        "channel": "GROCERY",
        "acv_contribution_pct": 28.00,
        "presentation_lead_days": 21,
    }
    payload.update(overrides)
    return payload


def shelf_reset_window_payload(**overrides) -> dict:
    payload = {
        "category": "BEVERAGE",
        "window_start": "2026-10-12T00:00:00Z",
        "window_end": "2026-11-06T23:59:59Z",
        "max_presentations": 2,
    }
    payload.update(overrides)
    return payload


def pilot_line_payload(**overrides) -> dict:
    payload = {
        "plant_name": DEFAULTS["PLANT_NAME"],
        "line_code": "AKR-1",
        "changeover_buffer_minutes": 240,
        "allergen_regime": "NONE",
        "hourly_cost_usd": 800.00,
    }
    payload.update(overrides)
    return payload


def project_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PROJECT_NAME"],
        "brand": DEFAULTS["BRAND"],
        "category": "BEVERAGE",
        "project_type": "NEW_BRAND",
        "strategic_fit_score": 8,
        "consumer_need_score": 7,
        "target_gross_margin_pct": 36,
        "category_attractiveness_score": 7,
        "development_budget_cap_usd": 100000.00,
    }
    payload.update(overrides)
    return payload


def concept_test_payload(**overrides) -> dict:
    payload = {
        "test_type": "MONADIC",
        "sample_size": 300,
        "purchase_intent_top2_pct": 42.00,
        "uniqueness_pct": 38.00,
        "fielded_at": "2026-08-02T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def business_case_payload(expected_project_version, **overrides) -> dict:
    payload = {
        "expected_project_version": expected_project_version,
        "variant_mode": "BOTTOM_UP",
        "category_size_units_year": 0,
        "target_share_pct": 0.00,
        "cogs_per_unit_usd": 1.2000,
        "slotting_fees_usd": 50000.00,
        "capex_usd": 300000.00,
        "discount_rate_pct": 9.00,
    }
    payload.update(overrides)
    return payload


def forecast_line_payload(**overrides) -> dict:
    payload = {
        "channel": "GROCERY",
        "store_count": 2400,
        "base_velocity_units_per_store_week": 1.20,
        "promo_weeks": 4,
        "promo_lift_pct": 30.00,
        "list_price_usd": 5.7500,
    }
    payload.update(overrides)
    return payload


def deliverable_payload(gate_id, **overrides) -> dict:
    payload = {
        "gate_id": gate_id,
        "deliverable_type": "MANUFACTURING_READINESS",
        "owner_function": "OPERATIONS",
    }
    payload.update(overrides)
    return payload


def gate_review_payload(gate_id, **overrides) -> dict:
    payload = {"gate_id": gate_id, "scheduled_at": "2026-08-05T09:00:00Z"}
    payload.update(overrides)
    return payload


def gate_vote_payload(**overrides) -> dict:
    payload = {"function": "OPERATIONS", "vote": "APPROVE"}
    payload.update(overrides)
    return payload


def formulation_payload(expected_project_version, **overrides) -> dict:
    payload = {
        "expected_project_version": expected_project_version,
        "spec_summary": DEFAULTS["SPEC_SUMMARY"],
        "allergen_regime": "NONE",
        "target_shelf_life_days": 180,
        "unit_cost_usd": 1.0500,
    }
    payload.update(overrides)
    return payload


def pilot_run_payload(pilot_line_id, **overrides) -> dict:
    payload = {
        "pilot_line_id": pilot_line_id,
        "window_start": "2026-08-06T08:00:00Z",
        "window_end": "2026-08-06T16:00:00Z",
        "planned_units": 10000,
        "committed_cost_usd": 20000.00,
    }
    payload.update(overrides)
    return payload


def shelf_life_study_payload(expected_formulation_version, **overrides) -> dict:
    payload = {
        "expected_formulation_version": expected_formulation_version,
        "duration_days": 30,
        "committed_cost_usd": 30000.00,
        "start_at": "2026-08-06T17:00:00Z",
    }
    payload.update(overrides)
    return payload


def timepoint_payload(**overrides) -> dict:
    payload = {"day_index": 30, "quality_score": 88.00}
    payload.update(overrides)
    return payload


def label_approval_payload(formulation_id, **overrides) -> dict:
    payload = {
        "formulation_id": formulation_id,
        "label_version": DEFAULTS["LABEL_VERSION"],
        "claims": [DEFAULTS["CLAIM"]],
    }
    payload.update(overrides)
    return payload


def sell_in_presentation_payload(retailer_id, shelf_reset_window_id, **overrides) -> dict:
    payload = {
        "retailer_id": retailer_id,
        "shelf_reset_window_id": shelf_reset_window_id,
        "scheduled_at": "2026-09-14T10:00:00Z",
        "proposed_sku_count": 3,
    }
    payload.update(overrides)
    return payload


def launch_lock_payload(launch_date, shelf_reset_window_id, **overrides) -> dict:
    payload = {
        "launch_date": launch_date,
        "shelf_reset_window_id": shelf_reset_window_id,
    }
    payload.update(overrides)
    return payload


def post_launch_period_payload(period_index, **overrides) -> dict:
    payload = {
        "period_index": period_index,
        "actual_units": 34000,
        "actual_net_revenue_usd": 190000.00,
        "actual_gross_margin_usd": 60000.00,
        "attainment_basis": "CUMULATIVE",
    }
    payload.update(overrides)
    return payload
