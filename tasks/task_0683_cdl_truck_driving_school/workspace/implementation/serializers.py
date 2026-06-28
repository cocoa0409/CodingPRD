"""Public-shape serializers for each entity (SCAFFOLD Table 1.1).

Each serializer returns a dict with exactly the fields the PRD declares for
that resource, including common fields (id, created_at, updated_at, version).
Internal-only keys (prefixed with _) are never exposed.
"""

_COMMON = ("id", "created_at", "updated_at", "version")


def _base(record, fields):
    out = {}
    for f in _COMMON:
        out[f] = record.get(f)
    for f in fields:
        out[f] = record.get(f)
    return out


def program_out(r):
    return _base(r, [
        "name", "cdl_class", "classroom_required_hours", "range_required_hours",
        "road_required_hours", "tuition_cents", "skills_pass_threshold", "active",
    ])


def truck_out(r):
    return _base(r, [
        "unit_number", "cdl_class", "turnaround_buffer_minutes",
        "status", "reserved_minutes",
    ])


def instructor_out(r):
    return _base(r, [
        "full_name", "cdl_class", "examiner_certified",
        "status", "reserved_minutes",
    ])


def carrier_out(r):
    return _base(r, ["name", "commitment_months", "reimbursement_cents"])


def enrollment_out(r):
    return _base(r, [
        "program_id", "student_name", "dot_medical_verified", "permit_verified",
        "status", "logged_classroom_hours", "logged_range_hours",
        "logged_road_hours", "projected_road_hours", "sponsoring_carrier_id",
        "fmcsa_reported",
    ])


def prereq_document_out(r):
    return _base(r, [
        "enrollment_id", "kind", "reference_code", "expires_on", "status",
    ])


def clock_session_out(r):
    return _base(r, [
        "enrollment_id", "truck_id", "instructor_id", "phase",
        "starts_at", "duration_minutes", "status",
    ])


def skills_test_out(r):
    return _base(r, [
        "enrollment_id", "examiner_id", "supersedes_test_id",
        "pre_trip_score", "basic_control_score", "road_score",
        "weighted_score", "outcome", "status",
    ])


def sponsorship_offer_out(r):
    return _base(r, [
        "enrollment_id", "carrier_id", "months_served",
        "clawback_cents", "status",
    ])


def finance_plan_out(r):
    return _base(r, [
        "enrollment_id", "term_months", "tuition_cents", "down_payment_cents",
        "financed_cents", "total_interest_cents", "installment_cents",
        "final_installment_cents", "status",
    ])


def completion_report_out(r):
    return _base(r, [
        "enrollment_id", "reported_classroom_hours", "reported_range_hours",
        "reported_road_hours", "passing_test_id", "status",
    ])
