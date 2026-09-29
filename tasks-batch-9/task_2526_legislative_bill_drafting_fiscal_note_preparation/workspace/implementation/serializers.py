"""Response payload shaping.  Field lists come from SCAFFOLD S1.1 verbatim."""

from store import db

COMMON_TAIL = ("created_at", "updated_at", "version")

SESSION_FIELDS = (
    "id",
    "name",
    "introduction_deadline_utc",
    "committee_report_deadline_utc",
    "sine_die_utc",
    "fiscal_note_default_days",
    "constrained_threshold_cents",
    "fiscal_cap_cents",
    "required_fiscal_years",
    "status",
    "convened_utc",
    "adjourned_utc",
    "next_house_bill_number",
    "next_senate_bill_number",
    "certified_fiscal_total_cents",
    "fiscal_posture",
    "bills_introduced_count",
    "bills_enrolled_count",
) + COMMON_TAIL

MEMBER_FIELDS = (
    "id",
    "full_name",
    "chamber",
    "party",
    "priority_slots_total",
    "priority_slots_used",
    "clarification_pending_count",
    "intake_hold",
) + COMMON_TAIL

DRAFTER_FIELDS = (
    "id",
    "full_name",
    "is_senior",
    "max_concurrent_engagements",
    "active_engagement_count",
) + COMMON_TAIL

AGENCY_FIELDS = (
    "id",
    "name",
    "agency_code",
    "status",
    "max_open_requests",
    "open_request_count",
    "late_submission_count",
    "revision_count",
    "responsiveness_score",
) + COMMON_TAIL

COMMITTEE_FIELDS = (
    "id",
    "session_id",
    "chamber",
    "name",
    "is_fiscal_committee",
    "max_concurrent_referrals",
    "active_referral_count",
) + COMMON_TAIL

DRAFTING_REQUEST_FIELDS = (
    "id",
    "session_id",
    "member_id",
    "subject",
    "summary",
    "confidentiality",
    "priority_flag",
    "requested_sections_count",
    "target_code_chapter",
    "appropriation_requested_cents",
    "status",
    "assigned_drafter_id",
    "engagement_start_utc",
    "engagement_end_utc",
    "affected_sections_count",
    "research_completed_utc",
    "intake_complexity_estimate",
    "actual_complexity_score",
    "sla_due_utc",
    "revision_round",
    "blocking_conflict_count",
    "open_blocking_conflict_count",
    "advisory_conflict_count",
    "style_findings_count",
) + COMMON_TAIL

STATUTORY_CONFLICT_FIELDS = (
    "id",
    "drafting_request_id",
    "code_citation",
    "conflict_type",
    "severity",
    "resolution_status",
    "resolution_note",
    "resolved_utc",
) + COMMON_TAIL

BILL_FIELDS = (
    "id",
    "session_id",
    "drafting_request_id",
    "sponsor_member_id",
    "companion_bill_id",
    "chamber",
    "bill_number",
    "legislative_status",
    "fiscal_status",
    "appropriation_requested_cents",
    "priority_bill",
    "introduced_utc",
    "adopted_fiscal_delta_cents",
    "adopted_amendment_count",
    "referral_count",
) + COMMON_TAIL

COMMITTEE_REFERRAL_FIELDS = (
    "id",
    "bill_id",
    "committee_id",
    "referral_order",
    "hearing_window_start_utc",
    "hearing_window_end_utc",
    "report_deadline_utc",
    "status",
    "reported_utc",
) + COMMON_TAIL

FISCAL_NOTE_REQUEST_FIELDS = (
    "id",
    "bill_id",
    "agency_id",
    "reopened_by_amendment_id",
    "methodology",
    "routed_utc",
    "due_utc",
    "submitted_utc",
    "certified_utc",
    "status",
    "revision_round",
    "late_submission",
    "direct_cost_cents",
    "contingency_pct",
    "contingency_cents",
    "certified_total_cents",
    "projected_revenue_total_cents",
    "high_scenario_total_cents",
    "low_scenario_total_cents",
) + COMMON_TAIL

# A cost estimate line is append-only: only id and created_at (PRD S2.5).
COST_ESTIMATE_FIELDS = (
    "id",
    "fiscal_note_request_id",
    "fiscal_year",
    "scenario",
    "revision_round",
    "personnel_cost_cents",
    "operating_cost_cents",
    "one_time_cost_cents",
    "fte_count",
    "revenue_impact_cents",
    "assumption_note",
    "included_in_certification",
    "created_at",
)

AMENDMENT_FIELDS = (
    "id",
    "bill_id",
    "committee_referral_id",
    "requested_by_member_id",
    "drafted_by_drafter_id",
    "supersedes_amendment_id",
    "stage",
    "summary",
    "fiscal_impact_delta_cents",
    "drafting_start_utc",
    "drafting_due_utc",
    "requested_utc",
    "turnaround_deadline_utc",
    "status",
    "drafted_utc",
    "adopted_utc",
    "rescind_count",
) + COMMON_TAIL

ENROLLED_BILL_FIELDS = (
    "id",
    "bill_id",
    "adopted_amendment_count",
    "net_fiscal_delta_cents",
    "enrollment_sequence",
    "origin_signature_role",
    "expected_next_signature",
    "status",
    "corrections_applied_count",
    "open_corrections_count",
    "origin_signed_utc",
    "second_signed_utc",
    "transmitted_utc",
) + COMMON_TAIL

TECHNICAL_CORRECTION_FIELDS = (
    "id",
    "enrolled_bill_id",
    "proposed_by_drafter_id",
    "applied_by_drafter_id",
    "correction_type",
    "description",
    "is_substantive",
    "status",
    "applied_utc",
) + COMMON_TAIL


def _project(row, fields):
    out = {}
    for name in fields:
        value = row.get(name)
        if isinstance(value, list):
            value = list(value)
        out[name] = value
    return out


def session_out(row):
    return _project(row, SESSION_FIELDS)


def member_out(row):
    return _project(row, MEMBER_FIELDS)


def drafter_out(row):
    return _project(row, DRAFTER_FIELDS)


def agency_out(row):
    return _project(row, AGENCY_FIELDS)


def committee_out(row):
    return _project(row, COMMITTEE_FIELDS)


def drafting_request_out(row):
    return _project(row, DRAFTING_REQUEST_FIELDS)


def statutory_conflict_out(row):
    return _project(row, STATUTORY_CONFLICT_FIELDS)


def bill_out(row):
    return _project(row, BILL_FIELDS)


def committee_referral_out(row):
    return _project(row, COMMITTEE_REFERRAL_FIELDS)


def fiscal_note_request_out(row):
    return _project(row, FISCAL_NOTE_REQUEST_FIELDS)


def cost_estimate_out(row):
    out = _project(row, COST_ESTIMATE_FIELDS)
    note = db.fiscal_note_requests.get(row["fiscal_note_request_id"])
    out["included_in_certification"] = bool(
        note is not None and row["revision_round"] == note["revision_round"]
    )
    return out


def amendment_out(row):
    return _project(row, AMENDMENT_FIELDS)


def enrolled_bill_out(row):
    return _project(row, ENROLLED_BILL_FIELDS)


def technical_correction_out(row):
    return _project(row, TECHNICAL_CORRECTION_FIELDS)
