"""Entity -> JSON projection.

Field order and field membership come straight from the scaffold entity table.
The three association records declared `common_fields: false` (OwnershipPeriod,
ContaminantSample, WorkWindow) are immutable: they carry `id` and `created_at`
only, never `updated_at` and never `version`.
"""

from logical_clock import iso, iso_day
from numeric import as_json_number

INT = "int"
NUM = "num"
STR = "str"
DT = "dt"
DAY = "day"
BOOL = "bool"
ARR = "arr"


def _value(kind, raw):
    if raw is None:
        return None
    if kind == INT:
        return int(raw)
    if kind == NUM:
        return as_json_number(raw)
    if kind == DT:
        return iso(raw)
    if kind == DAY:
        return iso_day(raw)
    if kind == BOOL:
        return bool(raw)
    if kind == ARR:
        return list(raw)
    return raw


def _project(record, spec, mutable):
    out = {"id": record["id"]}
    for name, kind in spec:
        out[name] = _value(kind, record.get(name))
    out["created_at"] = iso(record["created_at"])
    if mutable:
        out["updated_at"] = iso(record["updated_at"])
        out["version"] = record["version"]
    return out


SITE = (
    ("name", STR),
    ("epa_region", INT),
    ("hrs_score", NUM),
    ("listing_status", STR),
    ("listing_reference", STR),
    ("cost_posture", STR),
    ("oversight_direct_cents", INT),
    ("oversight_indirect_rate_bp", INT),
    ("oversight_indirect_cents", INT),
    ("oversight_billed_cents", INT),
    ("oversight_cap_utilization_pct", NUM),
    ("total_response_cost_cents", INT),
    ("recovered_cost_cents", INT),
    ("orphan_write_off_cents", INT),
    ("unrecovered_cost_cents", INT),
    ("adopted_round_id", STR),
    ("verified_waste_volume_tons", NUM),
    ("construction_complete_at", DT),
    ("five_year_review_due_at", DT),
    ("last_five_year_review_at", DT),
    ("last_protectiveness_determination", STR),
)

PRP = (
    ("site_id", STR),
    ("legal_name", STR),
    ("party_type", STR),
    ("viability_score", INT),
    ("status", STR),
    ("notice_reference", STR),
    ("submitted_volume_tons", NUM),
    ("verified_volume_tons", NUM),
    ("max_toxicity_class", STR),
    ("volumetric_share_pct", NUM),
    ("ownership_days_total", INT),
    ("de_minimis_eligible", BOOL),
    ("contribution_protection", BOOL),
)

OWNERSHIP_PERIOD = (
    ("site_id", STR),
    ("prp_id", STR),
    ("start_date", DAY),
    ("end_date", DAY),
    ("acquisition_type", STR),
    ("ownership_days", INT),
)

WASTE_IN_RECORD = (
    ("site_id", STR),
    ("prp_id", STR),
    ("volume_tons", NUM),
    ("toxicity_class", STR),
    ("evidence_grade", STR),
    ("disposal_year", INT),
    ("transporter_name", STR),
    ("status", STR),
    ("verified_volume_tons", NUM),
    ("effective_volume_tons", NUM),
    ("verified_by_user_id", STR),
)

REMEDIAL_INVESTIGATION = (
    ("site_id", STR),
    ("scope_summary", STR),
    ("exposure_medium", STR),
    ("status", STR),
    ("authored_by_user_id", STR),
    ("approved_by_user_id", STR),
    ("revision_round_count", INT),
    ("valid_sample_count", INT),
    ("central_tendency_epc_ug_per_l", NUM),
    ("rme_epc_ug_per_l", NUM),
    ("central_tendency_risk", NUM),
    ("rme_risk", NUM),
    ("hazard_index", NUM),
    ("action_level_exceeded", BOOL),
)

CONTAMINANT_SAMPLE = (
    ("remedial_investigation_id", STR),
    ("medium", STR),
    ("contaminant", STR),
    ("concentration_ug_per_l", NUM),
    ("qa_status", STR),
    ("collected_at", DT),
    ("lab_reference", STR),
)

REMEDY_ALTERNATIVE = (
    ("remedial_investigation_id", STR),
    ("selected_by_rod_id", STR),
    ("label", STR),
    ("capital_cost_cents", INT),
    ("annual_om_cost_cents", INT),
    ("om_years", INT),
    ("discount_rate_bp", INT),
    ("effectiveness_score", INT),
    ("implementability_score", INT),
    ("npv_cents", INT),
    ("cost_score", NUM),
    ("remedy_score", NUM),
)

RECORD_OF_DECISION = (
    ("site_id", STR),
    ("remedial_investigation_id", STR),
    ("proposed_plan_summary", STR),
    ("comment_period_days", INT),
    ("status", STR),
    ("comment_period_start", DT),
    ("comment_period_end", DT),
    ("public_comments_count", INT),
    ("responsiveness_summary", STR),
    ("selected_alternative_id", STR),
    ("signed_by_user_id", STR),
    ("signed_at", DT),
)

ALLOCATION_ROUND = (
    ("site_id", STR),
    ("round_number", INT),
    ("weight_volume_bp", INT),
    ("weight_toxicity_bp", INT),
    ("weight_ownership_bp", INT),
    ("status", STR),
    ("facilitator_user_id", STR),
    ("allocated_share_total_pct", NUM),
    ("orphan_share_pct", NUM),
    ("settled_share_pct", NUM),
    ("accept_share_pct", NUM),
    ("share_count", INT),
    ("balloted_count", INT),
    ("adopted_at", DT),
    ("revision_note", STR),
)

ALLOCATION_SHARE = (
    ("allocation_round_id", STR),
    ("prp_id", STR),
    ("provisional_pct", NUM),
    ("final_pct", NUM),
    ("pre_settlement_final_pct", NUM),
    ("disposition", STR),
    ("ballot", STR),
    ("ballot_rationale", STR),
    ("ballot_cast_at", DT),
)

CONSENT_DECREE = (
    ("site_id", STR),
    ("scope_type", STR),
    ("scope_summary", STR),
    ("party_prp_ids", ARR),
    ("oversight_cost_cap_cents", INT),
    ("stipulated_penalty_per_day_cents", INT),
    ("performance_deadline", DAY),
    ("legal_status", STR),
    ("compliance_status", STR),
    ("violation_type", STR),
    ("first_noncompliance_date", DAY),
    ("days_in_violation", INT),
    ("penalty_cap_cents", INT),
    ("accrued_penalty_cents", INT),
    ("court_docket_number", STR),
    ("entered_at", DT),
    ("lodged_at", DT),
    ("public_comment_close_at", DT),
    ("paid_penalty_cents", INT),
    ("penalty_capped", BOOL),
    ("last_assessment_at", DT),
    ("open_violation_count", INT),
    ("terminated_at", DT),
)

REMEDIATION_CONTRACT = (
    ("site_id", STR),
    ("record_of_decision_id", STR),
    ("solicitation_reference", STR),
    ("engineer_estimate_cents", INT),
    ("status", STR),
    ("contractor_name", STR),
    ("awarded_amount_cents", INT),
    ("max_concurrent_windows", INT),
    ("awarded_at", DT),
    ("completion_date", DAY),
    ("punch_list_items", INT),
    ("work_window_count", INT),
)

WORK_WINDOW = (
    ("remediation_contract_id", STR),
    ("activity_type", STR),
    ("start_at", DT),
    ("end_at", DT),
    ("crew_size", INT),
    ("description", STR),
    ("buffered_start_at", DT),
    ("buffered_end_at", DT),
)

COST_RECOVERY_ACTION = (
    ("site_id", STR),
    ("respondent_prp_id", STR),
    ("claimant_prp_id", STR),
    ("action_type", STR),
    ("demanded_cents", INT),
    ("premium_floor_cents", INT),
    ("respondent_share_pct_at_offer", NUM),
    ("status", STR),
    ("received_cents", INT),
    ("received_at", DT),
    ("void_reason", STR),
)


def site(record):
    return _project(record, SITE, True)


def prp(record):
    return _project(record, PRP, True)


def ownership_period(record):
    return _project(record, OWNERSHIP_PERIOD, False)


def waste_in_record(record):
    return _project(record, WASTE_IN_RECORD, True)


def remedial_investigation(record):
    return _project(record, REMEDIAL_INVESTIGATION, True)


def contaminant_sample(record):
    return _project(record, CONTAMINANT_SAMPLE, False)


def remedy_alternative(record):
    return _project(record, REMEDY_ALTERNATIVE, True)


def record_of_decision(record):
    return _project(record, RECORD_OF_DECISION, True)


def allocation_round(record):
    return _project(record, ALLOCATION_ROUND, True)


def allocation_share(record):
    return _project(record, ALLOCATION_SHARE, True)


def consent_decree(record):
    return _project(record, CONSENT_DECREE, True)


def remediation_contract(record):
    return _project(record, REMEDIATION_CONTRACT, True)


def work_window(record):
    return _project(record, WORK_WINDOW, False)


def cost_recovery_action(record):
    return _project(record, COST_RECOVERY_ACTION, True)
