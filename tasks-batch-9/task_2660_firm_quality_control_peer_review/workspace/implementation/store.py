"""In-memory data store.

Every collection is a plain dict keyed by the row's UUID ``id``.  Nothing is persisted to
disk and nothing is seeded: the store starts completely empty on every boot and tests
build every entity through the declared endpoints.
"""

import itertools
import uuid

import clock

FIRMS = "firms"
PARTNERS = "partners"
ENGAGEMENTS = "engagements"
QUALITY_RISKS = "quality_risks"
RISK_RESPONSES = "risk_responses"
QUALITY_REVIEWS = "quality_reviews"
INSPECTIONS = "inspections"
INSPECTION_SELECTIONS = "inspection_selections"
FINDINGS = "findings"
RCAS = "rcas"
PLANS = "plans"
PEER_REVIEWERS = "peer_reviewers"
PEER_REVIEWS = "peer_reviews"
PR_SELECTIONS = "pr_selections"
CAPS = "caps"

COLLECTIONS = (
    FIRMS, PARTNERS, ENGAGEMENTS, QUALITY_RISKS, RISK_RESPONSES, QUALITY_REVIEWS,
    INSPECTIONS, INSPECTION_SELECTIONS, FINDINGS, RCAS, PLANS, PEER_REVIEWERS,
    PEER_REVIEWS, PR_SELECTIONS, CAPS,
)

DB = {name: {} for name in COLLECTIONS}

_seq = itertools.count(1)


def reset():
    global _seq
    for name in COLLECTIONS:
        DB[name].clear()
    _seq = itertools.count(1)
    clock.reset()


def table(name):
    return DB[name]


def get(name, row_id):
    if not isinstance(row_id, str) or not row_id:
        return None
    return DB[name].get(row_id)


def rows(name):
    """All rows of a collection in stable creation order."""
    return sorted(DB[name].values(), key=lambda r: r["_seq"])


def insert(name, fields):
    stamp = clock.now_iso()
    row = dict(fields)
    row["id"] = str(uuid.uuid4())
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = next(_seq)
    DB[name][row["id"]] = row
    return row


def mutate(row, updates=None, force=False):
    """Apply ``updates``; bump version + updated_at when something actually changed.

    ``force=True`` is used for the direct target of an operation (and for the handful of
    places the PRD explicitly says a related row's version increments by one even though
    no visible field of it changes).
    """
    changed = False
    if updates:
        for key, value in updates.items():
            if row.get(key) != value:
                row[key] = value
                changed = True
    if changed or force:
        row["version"] = row["version"] + 1
        row["updated_at"] = clock.now_iso()
    return changed or force


def order_key(row):
    """Every ordering in the PRD ends in created_at ascending; because the logical clock
    can be frozen, the stable insertion sequence resolves identical stamps."""
    return (row["created_at"], row["_seq"])


FIELDS = {
    FIRMS: [
        "id", "legal_name", "state_code", "aa_hours_last_year", "enrolled_program",
        "peer_review_year_end", "risk_posture", "open_deficiency_count",
        "open_material_failure_count", "critical_risk_count", "last_peer_review_rating",
        "prior_reviewer_ids", "unassigned_review_flag",
        "created_at", "updated_at", "version",
    ],
    PARTNERS: [
        "id", "firm_id", "full_name", "cpa_license_state", "designations",
        "industry_specializations", "cpe_hours_last_3y", "prior_engagement_team_clients",
        "independence_conflict_client_names", "status", "open_eqr_count",
        "open_engagement_count", "last_inspected_year", "eqr_eligible",
        "created_at", "updated_at", "version",
    ],
    ENGAGEMENTS: [
        "id", "firm_id", "client_name", "engagement_type", "period_end",
        "is_public_interest", "is_first_year_client", "prior_finding_count_3y",
        "engagement_partner_id", "risk_score", "eqr_required", "workflow_state",
        "file_state", "eqr_concurred_at", "report_release_date", "reopened_count",
        "created_at", "updated_at", "version",
    ],
    QUALITY_RISKS: [
        "id", "firm_id", "component", "quality_objective_code", "risk_statement",
        "likelihood", "impact", "inherent_risk_score", "evaluation_basis",
        "residual_risk_score", "severity_band", "state", "response_count",
        "reopen_count", "created_at", "updated_at", "version",
    ],
    RISK_RESPONSES: [
        "id", "quality_risk_id", "response_type", "description", "design_effectiveness",
        "operating_effectiveness", "tested_on", "status",
        "created_at", "updated_at", "version",
    ],
    QUALITY_REVIEWS: [
        "id", "engagement_id", "reviewer_partner_id", "assigned_at", "concluded_at",
        "objectivity_attested", "cooling_off_days_at_assignment", "concern_round_count",
        "last_concern_summary", "state", "created_at", "updated_at", "version",
    ],
    INSPECTIONS: [
        "id", "firm_id", "inspection_year", "target_engagement_count",
        "engagements_selected_count", "must_select_eligible_count",
        "must_select_selected_count", "must_select_coverage_pct", "severity_index_basis",
        "deficiency_severity_index", "concluded_at", "state",
        "created_at", "updated_at", "version",
    ],
    INSPECTION_SELECTIONS: [
        "id", "inspection_id", "engagement_id", "selection_reason", "is_must_select",
        "selected_rank", "finding_count", "weighted_points",
        "created_at", "updated_at", "version",
    ],
    FINDINGS: [
        "id", "selection_id", "title", "sqm_component", "prior_cycle_recurrence",
        "classification", "pervasiveness", "affects_report_conclusion", "class_points",
        "verified_at", "reopen_count", "state", "created_at", "updated_at", "version",
    ],
    RCAS: [
        "id", "finding_id", "method", "root_cause_category", "contributing_factor_count",
        "narrative", "recurrence_flag", "depth_score", "validated_at", "state",
        "created_at", "updated_at", "version",
    ],
    PLANS: [
        "id", "finding_id", "root_cause_analysis_id", "owner_partner_id",
        "target_completion_date", "action_count", "action_specificity_score",
        "completed_action_count", "raw_completeness", "completeness_tier",
        "acceptance_score", "return_count", "accepted_at", "state",
        "created_at", "updated_at", "version",
    ],
    PEER_REVIEWERS: [
        "id", "reviewer_firm_name", "license_state", "accepts_out_of_state",
        "qualified_categories", "independence_conflict_firm_names",
        "max_concurrent_reviews", "experience_hours", "status", "active_review_count",
        "committed_hours_balance", "created_at", "updated_at", "version",
    ],
    PEER_REVIEWS: [
        "id", "firm_id", "prior_peer_review_id", "assigned_reviewer_id", "review_type",
        "year_end", "scheduled_window_start", "scheduled_window_end",
        "must_select_categories", "total_scope_hours", "unallocated_hours", "rating",
        "is_follow_up", "scope_limitation_count", "report_issued_at", "state",
        "created_at", "updated_at", "version",
    ],
    PR_SELECTIONS: [
        "id", "peer_review_id", "engagement_id", "must_select_category",
        "hours_committed", "is_scope_limitation", "disposition", "non_conforming",
        "status", "created_at", "updated_at", "version",
    ],
    CAPS: [
        "id", "peer_review_id", "action_code", "due_date", "evidence_summary",
        "evidence_submitted_at", "rejection_count", "status",
        "created_at", "updated_at", "version",
    ],
}


def serialize(name, row):
    out = {}
    for key in FIELDS[name]:
        value = row.get(key)
        if isinstance(value, list):
            value = [dict(item) if isinstance(item, dict) else item for item in value]
        out[key] = value
    return out


def serialize_many(name, row_list):
    return [serialize(name, row) for row in row_list]
