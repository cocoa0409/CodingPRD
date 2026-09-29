"""Explicit per-entity serializers. Datetimes render as ISO 8601 UTC with three
fractional digits; calendar dates render as the stored YYYY-MM-DD string."""

from calc import is_eligible_student
from common import iso


def _common(row, versioned=True):
    out = {"id": row["id"], "created_at": iso(row["created_at"])}
    if versioned:
        out["updated_at"] = iso(row["updated_at"])
        out["version"] = row["version"]
    return out


def state_rule(row):
    out = _common(row, versioned=False)
    for name in ("state_code", "transfer_response_days", "discipline_inclusion_mode",
                 "discipline_min_days_removed", "include_pending_investigations",
                 "sped_requires_consent", "amendment_hearing_days",
                 "destruction_min_age_years", "directory_optout_grace_days",
                 "notification_wait_days"):
        out[name] = row[name]
    return out


def district(row):
    out = _common(row)
    for name in ("name", "district_code", "state_code", "open_request_count"):
        out[name] = row[name]
    return out


def student(row):
    # Rights transfer is a pure function of the clock, recomputed on every read.
    row["is_eligible_student"] = is_eligible_student(row)
    out = _common(row)
    for name in ("district_id", "first_name", "last_name", "dob", "grade_level",
                 "has_iep", "guardian_user_id", "student_user_id", "enrollment_status",
                 "is_eligible_student", "directory_optout_categories",
                 "directory_optout_effective", "exit_effective_date"):
        out[name] = row[name]
    out["directory_optout_deadline_at"] = iso(row["directory_optout_deadline_at"])
    out["directory_optout_received_at"] = iso(row["directory_optout_received_at"])
    out["records_disposition_date"] = iso(row["records_disposition_date"])
    return out


def withdrawal(row):
    out = _common(row)
    for name in ("student_id", "effective_date", "destination_district_code",
                 "withdrawal_reason", "status", "hold_count", "active_hold_types"):
        out[name] = row[name]
    out["completed_at"] = iso(row["completed_at"])
    return out


def cumulative_file(row):
    out = _common(row)
    for name in ("student_id", "assembly_status", "required_component_types",
                 "certified_component_count", "completeness_pct", "total_page_count",
                 "included_page_count", "excluded_page_count", "disclosable_page_count"):
        out[name] = row[name]
    out["last_packet_snapshot_at"] = iso(row["last_packet_snapshot_at"])
    return out


def file_component(row):
    out = _common(row)
    for name in ("cumulative_file_id", "component_type", "status", "page_count",
                 "redacted_page_count", "disclosable_page_count", "exclusion_reason",
                 "certified_by_user_id", "amendment_count",
                 "statement_of_disagreement_present", "is_required"):
        out[name] = row[name]
    out["certified_at"] = iso(row["certified_at"])
    return out


def discipline_incident(row):
    out = _common(row)
    for name in ("student_id", "incident_date", "action_type", "days_removed",
                 "incident_status", "adjudicated_by_court", "description",
                 "transfer_inclusion_state"):
        out[name] = row[name]
    return out


def records_request(row):
    out = _common(row)
    for name in ("student_id", "requesting_district_id", "responding_district_id",
                 "request_priority", "includes_special_education", "sped_consent_on_file",
                 "authorization_reference", "authorization_verified", "status",
                 "statutory_days_allowed", "is_overdue", "packet_status",
                 "packet_page_count", "included_incident_count", "withheld_incident_count",
                 "receiving_state_inclusion_count", "reopen_count", "denial_reason",
                 "transmission_method"):
        out[name] = row[name]
    out["received_at"] = iso(row["received_at"])
    out["statutory_due_at"] = iso(row["statutory_due_at"])
    out["released_at"] = iso(row["released_at"])
    return out


def inspection_room(row):
    out = _common(row)
    for name in ("room_code", "site_name", "seats", "status"):
        out[name] = row[name]
    return out


def inspection_request(row):
    out = _common(row)
    for name in ("student_id", "requester_user_id", "requester_role", "requested_categories",
                 "copies_requested", "status", "base_copy_fee_cents",
                 "certification_fee_cents", "fee_assessed_cents", "fee_collected_cents",
                 "fee_waived_cents", "fee_outstanding_cents"):
        out[name] = row[name]
    out["statutory_inspection_due_at"] = iso(row["statutory_inspection_due_at"])
    out["inspection_completed_at"] = iso(row["inspection_completed_at"])
    return out


def review_appointment(row):
    out = _common(row)
    for name in ("inspection_request_id", "room_id", "duration_minutes", "status"):
        out[name] = row[name]
    out["start_at"] = iso(row["start_at"])
    out["end_at"] = iso(row["end_at"])
    out["attended_at"] = iso(row["attended_at"])
    return out


def hearing_officer(row):
    out = _common(row)
    for name in ("full_name", "credential", "status"):
        out[name] = row[name]
    return out


def amendment_request(row):
    out = _common(row)
    for name in ("student_id", "contested_component_id", "hearing_officer_id",
                 "requester_user_id", "contested_field", "requested_change", "rationale",
                 "status", "initial_decided_by_user_id", "hearing_decided_by_user_id",
                 "hearing_duration_minutes", "statement_text", "decision_note"):
        out[name] = row.get(name)
    out["denied_at"] = iso(row["denied_at"])
    out["hearing_due_at"] = iso(row["hearing_due_at"])
    out["hearing_start_at"] = iso(row["hearing_start_at"])
    out["hearing_end_at"] = iso(row["hearing_end_at"])
    out["statement_filed_at"] = iso(row["statement_filed_at"])
    return out


def legal_demand(row):
    out = _common(row)
    for name in ("student_id", "demand_type", "issuing_authority", "case_reference",
                 "production_scope", "notification_waived", "waiver_basis", "status",
                 "notified_party", "produced_page_count"):
        out[name] = row[name]
    out["received_at"] = iso(row["received_at"])
    out["notification_sent_at"] = iso(row["notification_sent_at"])
    out["production_allowed_at"] = iso(row["production_allowed_at"])
    out["produced_at"] = iso(row["produced_at"])
    return out


def disclosure_entry(row):
    out = _common(row, versioned=False)
    for name in ("student_id", "disclosure_type", "source_type", "source_id",
                 "recipient_name", "disclosed_categories", "page_count",
                 "logged_by_user_id", "legitimate_interest_note"):
        out[name] = row[name]
    out["disclosed_at"] = iso(row["disclosed_at"])
    return out


def retention_schedule(row):
    out = _common(row)
    for name in ("cumulative_file_id", "destruction_min_age_years", "status",
                 "destruction_method", "certification_note"):
        out[name] = row[name]
    out["exit_anchor_at"] = iso(row["exit_anchor_at"])
    out["last_activity_at"] = iso(row["last_activity_at"])
    out["destruction_eligible_at"] = iso(row["destruction_eligible_at"])
    out["exit_anchored_eligible_at"] = iso(row["exit_anchored_eligible_at"])
    out["destroyed_at"] = iso(row["destroyed_at"])
    return out
