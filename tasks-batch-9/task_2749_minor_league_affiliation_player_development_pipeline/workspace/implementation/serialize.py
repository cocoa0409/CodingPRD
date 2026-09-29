"""Response projections: explicit field lists per entity (SCAFFOLD entities)."""

AUDIT = ("created_at", "updated_at", "version")

AFFILIATE_FIELDS = (
    "id", "name", "level", "market_city", "roster_limit", "reserve_slots",
    "housing_beds", "meal_stipend_cents_per_day", "travel_standard_tier",
    "active_roster_count", "rehab_assignment_count", "reserve_list_count",
    "facility_score", "open_major_deficiency_count", "facility_status",
) + AUDIT

AGREEMENT_FIELDS = (
    "id", "affiliate_id", "term_start_date", "term_end_date",
    "facility_standard_tier", "minimum_active_players", "required_staff_roles",
    "club_reimbursement_cap_cents", "housing_expense_cents", "meal_expense_cents",
    "travel_expense_cents", "upkeep_expense_cents",
    "audited_housing_expense_cents", "audited_meal_expense_cents",
    "audited_travel_expense_cents", "audited_upkeep_expense_cents",
    "status", "posture", "provisional_club_obligation_cents",
    "final_club_obligation_cents", "affiliate_overflow_cents",
    "settlement_status", "submitted_by_user_id",
) + AUDIT

REVIEW_FIELDS = (
    "id", "affiliate_id", "category", "review_date", "score", "deficiency_level",
    "status", "remediation_due_date", "remediation_note",
    "remediation_submitted_at", "reopen_count", "waiver_granted_by_user_id",
    "is_overdue",
) + AUDIT

STAFF_MEMBER_FIELDS = (
    "id", "full_name", "discipline", "curriculum_version_certified",
    "certification_expires_on", "total_committed_fte_pct", "status",
) + AUDIT

ALLOCATION_FIELDS = (
    "id", "staff_member_id", "affiliate_id", "staff_role", "fte_pct",
    "effective_start", "effective_end", "curriculum_version", "status",
) + AUDIT

PLAYER_FIELDS = (
    "id", "full_name", "origin", "signed_date", "service_days_accrued",
    "roster_status", "medical_status", "is_on_domestic_reserve_list",
    "current_affiliate_id", "option_years_used", "option_years_remaining",
    "workload_index", "workload_index_projected", "promotion_readiness",
) + AUDIT

ASSIGNMENT_FIELDS = (
    "id", "player_id", "affiliate_id", "superseded_assignment_id",
    "assignment_type", "movement_reason", "effective_date", "end_date",
    "workload_ceiling_index", "status", "initiated_by_user_id",
    "level_at_assignment", "projected_optional_days", "option_year_charged",
) + AUDIT

PLAN_FIELDS = (
    "id", "assignment_id", "target_level", "curriculum_version",
    "curriculum_modules", "workload_limit_weekly_index",
    "completed_module_count", "completion_pct", "status", "review_cycle_count",
    "revision_note",
) + AUDIT

WORKLOAD_LOG_FIELDS = (
    "id", "assignment_id", "log_date", "pitches_thrown", "innings_pitched",
    "high_intensity_minutes", "is_rehab_outing", "created_at",
)

CLEARANCE_FIELDS = (
    "id", "player_id", "clearance_type", "status", "requested_by_user_id",
    "issued_by_user_id", "cleared_workload_ceiling_index", "expires_on",
    "restriction_note", "is_expired",
) + AUDIT

OPTION_YEAR_FIELDS = (
    "id", "triggering_assignment_id", "season_year", "optional_days", "status",
    "charged_at",
) + AUDIT

POOL_FIELDS = (
    "id", "season_year", "base_pool_cents", "trade_adjustment_cents",
    "forfeited_cents", "effective_pool_cents", "allocated_cents",
    "remaining_cents", "overage_tax_accrued_cents", "status",
) + AUDIT

SIGNING_FIELDS = (
    "id", "pool_id", "player_id", "academy_affiliate_id", "bonus_cents",
    "status", "rejection_reason", "pool_charge_cents", "overage_tax_cents",
    "tier3_breach", "approved_by_user_id",
) + AUDIT

REPORT_FIELDS = (
    "id", "assignment_id", "transaction_type", "status", "initiated_by_user_id",
    "certified_by_user_id", "filing_deadline", "filed_at", "is_late",
    "late_fee_cents", "refile_count", "league_note",
) + AUDIT


def _project(rec, fields):
    return {f: rec.get(f) for f in fields}


def affiliate(rec):
    return _project(rec, AFFILIATE_FIELDS)


def agreement(rec):
    return _project(rec, AGREEMENT_FIELDS)


def review(rec):
    return _project(rec, REVIEW_FIELDS)


def staff_member(rec):
    return _project(rec, STAFF_MEMBER_FIELDS)


def allocation(rec):
    return _project(rec, ALLOCATION_FIELDS)


def player(rec):
    return _project(rec, PLAYER_FIELDS)


def assignment(rec):
    return _project(rec, ASSIGNMENT_FIELDS)


def plan(rec):
    return _project(rec, PLAN_FIELDS)


def workload_log(rec):
    return _project(rec, WORKLOAD_LOG_FIELDS)


def clearance(rec):
    return _project(rec, CLEARANCE_FIELDS)


def option_year(rec):
    return _project(rec, OPTION_YEAR_FIELDS)


def pool(rec):
    return _project(rec, POOL_FIELDS)


def signing(rec):
    return _project(rec, SIGNING_FIELDS)


def report(rec):
    return _project(rec, REPORT_FIELDS)
