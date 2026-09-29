"""Output shapes for the twelve entities (PRD 2.4)."""

COMMON = ("id", "created_at", "updated_at", "version")

AGENCY_FIELDS = (
    "legal_name", "home_country_code", "ownership_disclosed", "beneficial_owner_count",
    "sanctions_screen_passed", "reference_check_count", "vetting_state", "compliance_posture",
    "rolling_risk_score", "lifetime_risk_score", "confirmed_incident_count",
    "reviewed_document_count", "confirmed_fraud_document_count",
    "net_earned_commission_cents", "clawback_liability_cents", "current_tier",
    "last_posture_reason",
)

PROGRAM_FIELDS = (
    "code", "name", "level", "annual_tuition_cents", "term_start_date", "census_date",
    "persistence_check_date", "commission_eligible", "max_commission_bps",
)

CONTRACT_FIELDS = (
    "agency_id", "contract_ref", "status", "exclusivity_model", "term_start_date",
    "term_end_date", "annual_commission_cap_cents", "disclosure_template_version",
    "amendment_round", "created_by_user_id", "agency_signed_by_user_id",
    "compliance_approved_by_user_id", "terminated_on", "termination_reason_code",
    "suspension_reason",
)

ASSIGNMENT_FIELDS = (
    "contract_id", "country_code", "exclusivity", "start_date", "end_date", "status",
    "released_on",
)

SCHEDULE_FIELDS = (
    "contract_id", "version_no", "effective_from", "effective_to", "deposit_rate_bps",
    "enrollment_rate_bps", "census_rate_bps", "persistence_rate_bps", "rate_cap_bps",
    "per_milestone_cap_cents", "clawback_window_days",
)

CERTIFICATION_FIELDS = (
    "agency_id", "module_code", "score", "issued_on", "expires_on", "status",
    "revoked_reason",
)

APPLICATION_FIELDS = (
    "agency_id", "custody_agency_id", "program_id", "pinned_contract_id",
    "pinned_schedule_id", "student_ref", "student_residence_country", "student_us_person",
    "recruitment_origin", "status", "disclosure_state", "disclosure_template_version",
    "disclosure_ack_token", "disclosure_acknowledged_at", "submitted_on",
    "tier_snapshot_at_submission", "projected_commission_cents", "net_commission_cents",
    "integrity_hold", "deposit_paid_on", "enrolled_on", "census_confirmed_on",
    "persisted_on", "withdrawn_on", "withdrawal_reason",
)

DOCUMENT_FIELDS = (
    "application_id", "doc_type", "content_hash", "issuer_name", "declared_signals",
    "fraud_signals", "fraud_index", "verification_state", "verified_by_user_id",
)

INCIDENT_FIELDS = (
    "agency_id", "application_id", "document_id", "category", "severity", "occurred_on",
    "source", "status", "resolved_by_user_id",
)

ENTRY_FIELDS = (
    "contract_id", "application_id", "schedule_id", "parent_entry_id", "kind", "milestone",
    "milestone_event_date", "tier_snapshot", "effective_bps", "amount_cents", "state",
    "incentive_comp_prohibited", "approved_by_user_id", "paid_by_user_id", "void_reason",
)

SCORECARD_FIELDS = (
    "agency_id", "period_start_date", "period_end_date", "submitted_count",
    "enrolled_count", "persisted_count", "reviewed_document_count",
    "flagged_document_count", "yield_rate", "persistence_rate", "quality_index",
    "composite_score", "tier", "posture_action_applied",
)

TRANSITION_FIELDS = (
    "application_id", "from_agency_id", "to_agency_id", "trigger_contract_id",
    "reason_code", "application_status_at_transition", "disclosure_reset",
)


def _shape(record, fields, common=COMMON):
    out = {}
    for key in common:
        out[key] = record.get(key)
    for key in fields:
        value = record.get(key)
        if isinstance(value, list):
            value = list(value)
        out[key] = value
    return out


def agency(record):
    return _shape(record, AGENCY_FIELDS)


def program(record):
    return _shape(record, PROGRAM_FIELDS)


def contract(record):
    return _shape(record, CONTRACT_FIELDS)


def assignment(record):
    return _shape(record, ASSIGNMENT_FIELDS)


def schedule(record):
    return _shape(record, SCHEDULE_FIELDS)


def certification(record):
    return _shape(record, CERTIFICATION_FIELDS)


def application(record):
    return _shape(record, APPLICATION_FIELDS)


def document(record):
    return _shape(record, DOCUMENT_FIELDS)


def incident(record):
    return _shape(record, INCIDENT_FIELDS)


def entry(record):
    return _shape(record, ENTRY_FIELDS)


def scorecard(record):
    return _shape(record, SCORECARD_FIELDS)


def transition(record):
    return _shape(record, TRANSITION_FIELDS, common=("id", "created_at"))
