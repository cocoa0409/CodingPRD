"""Record serialisers -- one per entity, field order taken from the scaffold."""

COMMON_TAIL = ("created_at", "updated_at", "version")

SCHOOL_FIELDS = (
    "name", "sis_school_id", "building_code", "grade_band", "status",
    "min_password_length", "password_requires_mixed_case",
    "password_max_age_days", "password_lockout_threshold",
    "temp_password_ttl_hours", "enrolled_student_count",
)

TERM_FIELDS = (
    "name", "school_year", "start_date", "end_date", "add_drop_cutoff_date",
    "instructional_days", "archive_retention_days", "state",
    "archived_access_expires_at",
)

TEACHER_FIELDS = (
    "school_id", "sis_staff_id", "full_name", "email", "employment_status",
    "separation_effective_date",
)

STUDENT_FIELDS = (
    "school_id", "sis_student_id", "first_name", "last_name", "grade_level",
    "date_of_birth", "state_student_id", "enrollment_state",
    "withdrawal_effective_date", "duplicate_of_student_id",
    "active_enrollment_count",
)

SECTION_FIELDS = (
    "school_id", "term_id", "primary_teacher_id", "sis_section_id",
    "course_code", "subject", "period_index", "meeting_days", "max_seats",
    "status", "roster_health", "active_enrollment_count",
)

ENROLLMENT_FIELDS = (
    "section_id", "student_id", "requested_effective_date", "effective_date",
    "drop_effective_date", "roster_status", "add_drop_class", "source",
)

VENDOR_APP_FIELDS = (
    "name", "vendor_code", "created_by_user_id", "activated_by_user_id",
    "term_id", "rostering_standard", "identifier_strategy", "username_domain",
    "name_format", "grade_band_scope", "seat_model", "allocation_policy",
    "block_seats", "overage_policy", "unmatched_teacher_policy", "total_seats",
    "price_per_seat_cents", "status", "unallocated_seats", "consumed_seats",
    "committed_charge_cents", "renewal_score", "renewal_recommendation",
    "sync_health",
)

BUILDING_ALLOCATION_FIELDS = (
    "vendor_app_id", "school_id", "allocated_seats", "consumed_seats",
    "borrowed_seats", "hard_cap", "eligible_headcount_snapshot",
)

APP_ACCOUNT_FIELDS = (
    "building_allocation_id", "student_id", "teacher_id", "subject_type",
    "username", "seat_status", "identity_status", "password_state",
    "failed_login_count", "last_password_set_at", "password_expires_at",
    "seat_charge_cents", "refunded_charge_cents", "active_minutes_total",
    "session_count", "last_activity_date", "deprovision_scheduled_date",
)

SYNC_RUN_FIELDS = (
    "vendor_app_id", "run_type", "state", "initiated_by_user_id",
    "published_by_user_id", "extracted_section_count",
    "extracted_enrollment_count", "transformed_record_count",
    "blocking_error_count", "advisory_error_count", "projected_seat_delta",
    "projected_charge_cents", "published_seat_delta", "published_charge_cents",
    "transform_count", "extracted_at", "transformed_at", "published_at",
)

ERROR_QUEUE_ITEM_FIELDS = (
    "sync_run_id", "category", "severity", "status", "source_ref",
    "subject_section_id", "subject_student_id",
    "duplicate_candidate_student_id", "resolved_by_user_id",
    "resolution_note", "resolved_at",
)


def _shape(record, fields):
    out = {"id": record["id"]}
    for field in fields:
        out[field] = record.get(field)
    for field in COMMON_TAIL:
        out[field] = record.get(field)
    return out


def school(record):
    return _shape(record, SCHOOL_FIELDS)


def term(record):
    return _shape(record, TERM_FIELDS)


def teacher(record):
    return _shape(record, TEACHER_FIELDS)


def student(record):
    return _shape(record, STUDENT_FIELDS)


def section(record):
    return _shape(record, SECTION_FIELDS)


def enrollment(record):
    return _shape(record, ENROLLMENT_FIELDS)


def vendor_app(record):
    return _shape(record, VENDOR_APP_FIELDS)


def building_allocation(record):
    return _shape(record, BUILDING_ALLOCATION_FIELDS)


def app_account(record):
    return _shape(record, APP_ACCOUNT_FIELDS)


def sync_run(record):
    return _shape(record, SYNC_RUN_FIELDS)


def error_queue_item(record):
    return _shape(record, ERROR_QUEUE_ITEM_FIELDS)
