"""Wire serializers: strip internal keys, keep declared field sets."""


def _pub(rec, fields):
    return {f: rec.get(f) for f in fields}


COMMON = ["id", "created_at", "updated_at", "version"]


def member(r):
    return _pub(r, COMMON + [
        "full_name", "npdb_subject_id", "primary_specialty_code",
        "membership_status", "privilege_posture",
        "current_term_start", "current_term_end",
        "active_privilege_line_count", "credential_expiry_risk_score",
        "sod_exclusion_tags",
    ])


def criterion(r):
    return _pub(r, COMMON + [
        "specialty_code", "privilege_line", "min_training_months",
        "min_case_volume_24mo", "required_board_cert", "fppe_case_count",
        "volume_tier_table",
    ])


def application(r):
    return _pub(r, COMMON + [
        "member_id", "application_kind", "application_status", "submitted_at",
        "verification_complete_count", "verification_required_count",
        "supersedes_application_id", "decision_reason",
    ])


def verification_item(r):
    return _pub(r, COMMON + [
        "application_id", "item_kind", "item_status", "requested_at",
        "verified_at", "discrepancy_note", "waiver_justification",
        "is_primary_source",
    ])


def delineation(r):
    return _pub(r, COMMON + [
        "application_id", "privilege_line", "documented_training_months",
        "documented_cases_24mo", "delineation_status", "satisfaction_tier",
        "satisfaction_score",
    ])


def grant(r):
    return _pub(r, COMMON + [
        "member_id", "delineation_id", "privilege_line", "grant_status",
        "effective_from", "effective_until", "fppe_cases_completed",
        "suspension_reason",
    ])


def review(r):
    return _pub(r, COMMON + [
        "member_id", "privilege_grant_id", "review_kind", "review_status",
        "period_start", "period_end", "provisional_composite_score",
        "final_composite_score", "metric_count", "retracted_metric_count",
        "outcome",
    ])


def metric(r):
    return _pub(r, COMMON + [
        "review_id", "metric_domain", "raw_value", "normalized_value",
        "domain_weight", "collected_at", "metric_status", "passed_fppe_case",
    ])


def credential(r):
    return _pub(r, COMMON + [
        "member_id", "credential_kind", "credential_number", "issued_on",
        "expires_on", "credential_status", "supersedes_credential_id",
    ])


def temp(r):
    return _pub(r, COMMON + [
        "member_id", "sponsor_member_id", "temp_kind", "privilege_line",
        "window_start", "window_end", "temp_status", "disaster_declaration_ref",
    ])


def case(r):
    return _pub(r, COMMON + [
        "subject_member_id", "proposed_by_member_id", "case_kind",
        "case_status", "proposed_at", "hearing_request_deadline",
        "hearing_requested_at", "npdb_reportable", "restriction_days",
        "linked_review_id",
    ])


def panel(r):
    return _pub(r, COMMON + [
        "case_id", "panel_member_id", "panel_role", "panel_status",
        "seated_at",
    ])


def npdb_report(r):
    # NPDB reports are immutable filings: only id + created_at, no
    # updated_at / version (PRD §2.4).
    return _pub(r, [
        "id", "created_at", "member_id", "case_id", "report_kind",
        "submitted_at", "submission_deadline", "report_status", "is_late",
    ])


def agenda_item(r):
    return _pub(r, COMMON + [
        "item_kind", "ref_application_id", "ref_delineation_id",
        "ref_case_id", "committee_status", "committee_votes_for",
        "committee_votes_against", "quorum_required", "mec_voter_ids",
        "board_voter_id",
    ])
