"""Entity -> response payload projections (PRD Section 2.5 common fields)."""

from services import derive

COMMON = ("created_at", "updated_at", "version")

PROJECT_FIELDS = (
    "id",
    "name",
    "operator_name",
    "basin_code",
    "total_project_acreage",
    "requested_annual_injection_rate_tpy",
    "annual_monitoring_cost_usd",
    "required_consent_pct",
    "ca_rig_slots",
    "status",
    "operational_posture",
    "governing_geologic_model_id",
    "aor_radius_km",
    "secured_acreage",
    "outstanding_acreage",
    "pore_space_consent_pct",
    "pore_space_bonus_total_usd",
    "unitization_status",
    "unitization_consent_pct_at_filing",
    "statutory_bonus_per_acre_usd",
    "corrective_action_completion_pct",
    "cumulative_stored_tonnes",
    "pending_credit_usd",
    "required_financial_assurance_usd",
    "allocated_assurance_usd",
    "assurance_coverage_status",
    "effective_annual_monitoring_cost_usd",
    "pisc_duration_years",
    "alternative_timeframe_years",
    "pisc_start_at",
    "pisc_elapsed_years",
    "non_endangerment_demonstrated",
    "closure_status",
    "closure_certified_by_user_id",
    "closure_certified_at",
    "open_remediation_count",
) + COMMON

MODEL_FIELDS = (
    "id",
    "project_id",
    "supersedes_model_id",
    "model_label",
    "injection_zone_top_depth_m",
    "injection_zone_thickness_m",
    "seal_thickness_m",
    "capillary_entry_pressure_psi",
    "p10_seal_thickness_m",
    "p10_capillary_entry_pressure_psi",
    "reservoir_pressure_psi",
    "fracture_pressure_psi",
    "permeability_md",
    "porosity_fraction",
    "assessment_variant",
    "seal_integrity_index",
    "seal_integrity_index_p10",
    "seal_classification",
    "max_injection_rate_tpy",
    "effective_injection_rate_tpy",
    "injection_years",
    "plume_radius_km",
    "pressure_front_radius_km",
    "aor_radius_km",
    "plume_status",
    "status",
    "reviewer_user_id",
    "revision_round_count",
) + COMMON

WELLBORE_FIELDS = (
    "id",
    "project_id",
    "api_number",
    "distance_from_injector_km",
    "total_depth_m",
    "penetrates_seal",
    "plug_condition",
    "plug_record_available",
    "risk_score",
    "ca_cost_estimate_usd",
    "corrective_action_status",
    "ca_window_start",
    "ca_window_end",
    "waiver_reviewer_user_id",
) + COMMON

TRACT_FIELDS = (
    "id",
    "project_id",
    "tract_label",
    "acreage",
    "ownership_pct",
    "landowner_user_id",
    "lease_status",
    "current_offer_bonus_per_acre_usd",
    "current_offer_royalty_rate_pct",
    "counter_bonus_per_acre_usd",
    "executed_bonus_per_acre_usd",
    "executed_royalty_rate_pct",
    "lease_term_start",
    "lease_term_end",
    "negotiation_round_count",
    "bonus_settlement_usd",
    "net_acreage",
) + COMMON

PERMIT_FIELDS = (
    "id",
    "project_id",
    "geologic_model_id",
    "well_name",
    "casing_program",
    "corrosion_resistant_material",
    "tubing_packer_installed",
    "requested_injection_pressure_psi",
    "max_injection_pressure_psi",
    "authorized_injection_rate_tpy",
    "permit_status",
    "construction_status",
    "last_mit_type",
    "last_mit_result",
    "last_mit_at",
    "mit_pass_count",
    "technical_reviewer_user_id",
    "revision_round_count",
    "activated_at",
) + COMMON

PLAN_FIELDS = (
    "id",
    "project_id",
    "plan_label",
    "status",
    "technical_review_complete",
    "public_comment_complete",
    "subsurface_subscore",
    "surface_subscore",
    "atmospheric_subscore",
    "coverage_score",
    "condition_count",
    "approved_by_user_id",
    "revision_round_count",
) + COMMON

METHOD_FIELDS = (
    "id",
    "monitoring_plan_id",
    "domain",
    "technique",
    "detection_threshold_tpy",
    "frequency_per_year",
    "spatial_coverage_pct",
    "method_score",
    "status",
) + COMMON

INSTRUMENT_FIELDS = (
    "id",
    "project_id",
    "instrument_type",
    "face_amount_usd",
    "allocated_ca_usd",
    "allocated_plugging_usd",
    "allocated_pisc_usd",
    "allocated_emergency_usd",
    "unallocated_usd",
    "drawn_usd",
    "status",
    "released_at",
) + COMMON

PERIOD_FIELDS = (
    "id",
    "permit_id",
    "period_start",
    "period_end",
    "mass_injected_tonnes",
    "measured_leakage_tonnes",
    "net_stored_tonnes",
    "status",
    "voided_at",
    "created_at",
)

CLAIM_FIELDS = (
    "id",
    "project_id",
    "monitoring_plan_id",
    "tax_year",
    "claim_variant",
    "lca_upstream_emissions_factor",
    "reported_tonnes",
    "verified_tonnes",
    "credit_rate_usd_per_tonne",
    "credit_amount_usd",
    "status",
    "submitted_by_user_id",
    "verifier_user_id",
) + COMMON

ORDER_FIELDS = (
    "id",
    "project_id",
    "trigger_type",
    "severity",
    "narrative",
    "reserve_draw_usd",
    "status",
    "opened_at",
    "resolved_at",
) + COMMON


def _project(row, fields):
    return {name: row.get(name) for name in fields}


def project(row):
    # PRD 3.9: pisc_elapsed_years is recomputed on every read of the project
    # rather than being written by any mutation.
    derive.refresh_pisc_elapsed(row)
    return _project(row, PROJECT_FIELDS)


def model(row):
    return _project(row, MODEL_FIELDS)


def wellbore(row):
    return _project(row, WELLBORE_FIELDS)


def tract(row):
    return _project(row, TRACT_FIELDS)


def permit(row):
    return _project(row, PERMIT_FIELDS)


def plan(row):
    return _project(row, PLAN_FIELDS)


def method(row):
    return _project(row, METHOD_FIELDS)


def instrument(row):
    return _project(row, INSTRUMENT_FIELDS)


def period(row):
    return _project(row, PERIOD_FIELDS)


def claim(row):
    return _project(row, CLAIM_FIELDS)


def order(row):
    return _project(row, ORDER_FIELDS)
