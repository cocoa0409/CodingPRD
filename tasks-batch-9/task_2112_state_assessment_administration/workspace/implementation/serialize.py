"""Resource representations. Datetimes render as ISO 8601 UTC with three
fractional digits; custody entries carry id and created_at but neither
updated_at nor version (PRD 2.4)."""

from datetime import datetime

from derive import certification_status
from timeutil import fmt_iso

COMMON_TAIL = ("created_at", "updated_at", "version")

DISTRICT_FIELDS = (
    "id",
    "name",
    "district_code",
    "state_code",
    "replacement_charge_total_cents",
    "security_assessment_cents",
    "open_discrepancy_count",
) + COMMON_TAIL

SCHOOL_FIELDS = (
    "id",
    "district_id",
    "name",
    "school_code",
    "max_concurrent_seats",
) + COMMON_TAIL

WINDOW_FIELDS = (
    "id",
    "name",
    "subject",
    "grade_band",
    "window_start",
    "window_end",
    "makeup_start",
    "makeup_end",
    "appeal_window_days",
    "min_participation_pct",
    "status",
    "released_at",
    "appeal_window_closes_at",
    "participation_rate_provisional_pct",
    "participation_rate_final_pct",
    "registered_distinct_count",
    "present_distinct_count",
    "open_breach_count",
    "security_hold",
) + COMMON_TAIL

PROCTOR_FIELDS = (
    "id",
    "school_id",
    "full_name",
    "email",
    "training_status",
    "quiz_score_pct",
    "training_completed_at",
    "revoked_at",
    "certification_status",
    "strike_count",
    "latest_affidavit_id",
) + COMMON_TAIL

AFFIDAVIT_FIELDS = (
    "id",
    "proctor_id",
    "window_id",
    "affidavit_version",
    "signed_at",
    "signer_user_id",
    "status",
    "revoked_reason",
) + COMMON_TAIL

SESSION_FIELDS = (
    "id",
    "window_id",
    "school_id",
    "proctor_id",
    "room_code",
    "scheduled_start",
    "scheduled_end",
    "seat_capacity",
    "session_type",
    "status",
    "seats_consumed",
    "effective_seat_capacity",
    "separate_setting_count",
    "materials_checked_out",
    "materials_checked_in",
    "opened_at",
    "closed_at",
) + COMMON_TAIL

REGISTRATION_FIELDS = (
    "id",
    "session_id",
    "makeup_of_registration_id",
    "student_state_id",
    "grade",
    "guardian_email",
    "accommodation_codes",
    "accommodation_status",
    "accommodation_decision_note",
    "attendance_status",
    "raw_score",
    "score_status",
    "report_delivery_status",
    "report_suppressed_reason",
    "report_delivered_at",
    "seats_required",
) + COMMON_TAIL

LOT_FIELDS = (
    "id",
    "window_id",
    "district_id",
    "lot_code",
    "quantity_shipped",
    "seal_range_start",
    "seal_range_end",
    "status",
    "quantity_at_district",
    "quantity_at_school",
    "quantity_in_sessions",
    "quantity_destroyed",
    "chain_accounted_count",
    "declared_accounted_count",
    "chain_vs_declared_delta",
    "missing_count",
    "seal_broken_count",
    "replacement_charge_cents",
    "charge_reversed",
    "reconciled_at",
) + COMMON_TAIL

CUSTODY_EVENT_FIELDS = (
    "id",
    "material_lot_id",
    "previous_event_id",
    "session_id",
    "sequence_no",
    "event_type",
    "quantity",
    "sealed_count",
    "from_holder_type",
    "to_holder_type",
    "actor_user_id",
    "actor_role",
    "occurred_at",
    "chain_balance_after",
    "note",
    "created_at",
)

REPORT_FIELDS = (
    "id",
    "session_id",
    "registration_id",
    "reporter_proctor_id",
    "material_lot_id",
    "category",
    "severity",
    "narrative",
    "status",
    "disposition",
    "return_count",
    "adjudicated_at",
    "system_generated",
) + COMMON_TAIL

APPEAL_FIELDS = (
    "id",
    "registration_id",
    "reason_code",
    "narrative",
    "filed_by_role",
    "filed_by_user_id",
    "filed_at",
    "status",
    "corrected_raw_score",
    "decided_at",
) + COMMON_TAIL


def _project(entity, fields, overrides=None):
    payload = {}
    for field in fields:
        if overrides and field in overrides:
            value = overrides[field]
        else:
            value = entity.get(field)
        if isinstance(value, datetime):
            value = fmt_iso(value)
        elif isinstance(value, list):
            value = list(value)
        payload[field] = value
    return payload


def district(entity):
    return _project(entity, DISTRICT_FIELDS)


def school(entity):
    return _project(entity, SCHOOL_FIELDS)


def window(entity):
    return _project(entity, WINDOW_FIELDS)


def proctor(entity):
    return _project(entity, PROCTOR_FIELDS, {"certification_status": certification_status(entity)})


def affidavit(entity):
    return _project(entity, AFFIDAVIT_FIELDS)


def session(entity):
    return _project(entity, SESSION_FIELDS)


def registration(entity):
    return _project(entity, REGISTRATION_FIELDS)


def lot(entity):
    return _project(entity, LOT_FIELDS)


def custody_event(entity):
    return _project(entity, CUSTODY_EVENT_FIELDS)


def report(entity):
    return _project(entity, REPORT_FIELDS)


def appeal(entity):
    return _project(entity, APPEAL_FIELDS)
