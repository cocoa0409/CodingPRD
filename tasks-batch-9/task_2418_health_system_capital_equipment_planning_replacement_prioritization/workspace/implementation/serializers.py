"""Explicit field projections for every entity."""


def _pick(row, names):
    return {name: row.get(name) for name in names}


FACILITY_FIELDS = [
    "id", "name", "code", "region", "max_concurrent_construction",
    "active_asset_count", "created_at", "updated_at", "version",
]

DEPARTMENT_FIELDS = [
    "id", "facility_id", "name", "modality_scope",
    "utilization_penalty_points", "underperformance_flag",
    "created_at", "updated_at", "version",
]

CYCLE_FIELDS = [
    "id", "plan_year", "plan_year_start", "total_capital_cents",
    "contingency_pct", "facility_contingency_pct", "allocation_method",
    "status", "system_contingency_cents", "distributable_cents",
    "unallocated_cents", "contingency_drawn_cents", "allocation_count",
    "exhausted_allocation_count", "scored_count", "expedited_count",
    "allocated_by_user_id", "created_at", "updated_at", "version",
]

ALLOCATION_FIELDS = [
    "id", "cycle_id", "facility_id", "demand_cents", "weighted_score",
    "allocated_cents", "contingency_reserve_cents", "contingency_status",
    "released_contingency_cents", "committed_cents", "available_cents",
    "posture", "created_at", "updated_at", "version",
]

ASSET_FIELDS = [
    "id", "facility_id", "department_id", "modality", "model_name",
    "install_date", "expected_life_years", "acquisition_cost_cents",
    "oem_support_end_date", "status", "disposition_status",
    "trade_in_credit_applied_cents", "age_years", "nominal_ruls_score",
    "adjusted_ruls_score", "service_penalty_points", "corrective_count_24m",
    "downtime_hours_24m", "unresolved_recall", "ruls_as_of",
    "created_at", "updated_at", "version",
]

SERVICE_EVENT_FIELDS = [
    "id", "asset_id", "event_date", "category", "downtime_hours", "cost_cents",
    "recall_resolved", "notes", "created_at",
]

REQUEST_FIELDS = [
    "id", "cycle_id", "department_id", "asset_id", "sponsor_member_id",
    "clinical_justification", "current_annual_volume",
    "projected_annual_volume", "estimated_capital_cents",
    "facility_modification_cents", "annual_service_contract_cents",
    "disposable_unit_cents", "regulatory_mandate_flag", "mandate_deadline",
    "status", "revision_count", "return_count", "safety_driver",
    "growth_driver", "regulatory_driver", "eos_driver", "composite_score",
    "expedited", "budgetary_operating_5y_cents", "budgetary_tco_cents",
    "negotiated_operating_5y_cents", "negotiated_tco_cents",
    "baseline_year1_opex_cents", "funded_amount_cents",
    "created_at", "updated_at", "version",
]

SCORE_FIELDS = [
    "id", "request_id", "sequence", "reason", "asset_adjusted_ruls_snapshot",
    "corrective_count_snapshot", "safety_driver", "growth_driver",
    "regulatory_driver", "eos_driver", "department_penalty_points",
    "composite_score", "expedited", "created_at",
]

MEMBER_FIELDS = [
    "id", "full_name", "seat", "facility_id", "department_id", "voting_weight",
    "active", "created_at", "updated_at", "version",
]

VOTE_FIELDS = [
    "id", "request_id", "member_id", "vote", "rationale", "counted_weight",
    "superseded", "created_at",
]

CONTRACT_FIELDS = [
    "id", "contract_code", "vendor_name", "small_tier_pct", "mid_tier_pct",
    "large_tier_pct", "tier_mid_floor_cents", "tier_large_floor_cents",
    "multi_unit_addendum_pct", "trade_in_cap_pct", "expires_on",
    "created_at", "updated_at", "version",
]

QUOTE_FIELDS = [
    "id", "request_id", "gpo_contract_id", "trade_in_asset_id", "vendor_name",
    "list_price_cents", "trade_in_offer_cents", "multi_unit_count",
    "warranty_months", "service_escalation_pct", "valid_until", "status",
    "negotiation_round", "gpo_tier", "gpo_discount_cents",
    "multi_unit_addendum_cents", "subtotal_cents", "trade_in_credit_cents",
    "net_capital_cents", "created_at", "updated_at", "version",
]

PROJECT_FIELDS = [
    "id", "request_id", "facility_id", "department_id",
    "predecessor_project_id", "construction_required", "construction_start",
    "construction_end", "downtime_start", "downtime_end",
    "construction_status", "equipment_status", "record_status", "go_live_at",
    "created_at", "updated_at", "version",
]

AUDIT_FIELDS = [
    "id", "request_id", "installation_project_id", "audit_window_start",
    "audit_window_end", "projected_annual_volume_snapshot",
    "baseline_year1_opex_snapshot", "actual_annual_volume",
    "actual_annual_opex_cents", "volume_attainment_pct", "opex_variance_pct",
    "status", "created_at", "updated_at", "version",
]


def facility(row):
    return _pick(row, FACILITY_FIELDS)


def department(row):
    return _pick(row, DEPARTMENT_FIELDS)


def cycle(row):
    return _pick(row, CYCLE_FIELDS)


def allocation(row):
    return _pick(row, ALLOCATION_FIELDS)


def asset(row):
    return _pick(row, ASSET_FIELDS)


def service_event(row):
    return _pick(row, SERVICE_EVENT_FIELDS)


def request_row(row):
    return _pick(row, REQUEST_FIELDS)


def score(row):
    return _pick(row, SCORE_FIELDS)


def member(row):
    return _pick(row, MEMBER_FIELDS)


def vote(row):
    return _pick(row, VOTE_FIELDS)


def contract(row):
    return _pick(row, CONTRACT_FIELDS)


def quote(row):
    return _pick(row, QUOTE_FIELDS)


def project(row):
    return _pick(row, PROJECT_FIELDS)


def audit(row):
    return _pick(row, AUDIT_FIELDS)
