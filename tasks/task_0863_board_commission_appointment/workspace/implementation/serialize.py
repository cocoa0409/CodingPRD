"""Entity serializers producing the exact output field shapes."""
from calc import attendance_counts, provisional_rate, final_rate

COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(rec, fields):
    return {f: rec.get(f) for f in fields}


def board_out(r):
    return _pick(r, COMMON + [
        "name", "jurisdiction", "board_type", "authorized_seat_count",
        "quorum_count", "term_length_months", "max_consecutive_terms",
        "max_cumulative_years", "attendance_threshold_pct", "sunshine_notice_days",
        "max_holdover_days", "is_sunshine_subject", "status",
    ])


def seat_out(r):
    return _pick(r, COMMON + [
        "board_id", "seat_number", "seat_category", "residency_requirement",
        "required_district", "occupancy_status",
    ])


def vacancy_out(r):
    return _pick(r, COMMON + ["seat_id", "reason", "application_deadline", "status"])


def applicant_out(r):
    return _pick(r, COMMON + [
        "full_name", "email", "residence_district", "resides_in_jurisdiction",
        "is_registered_voter", "employer", "status",
    ])


def application_out(r):
    return _pick(r, COMMON + [
        "applicant_id", "vacancy_id", "residency_attested", "statement",
        "return_count", "status",
    ])


def appointment_out(r):
    return _pick(r, COMMON + [
        "application_id", "seat_id", "applicant_id", "term_start_date",
        "term_end_date", "term_sequence_number", "nominated_by_user_id",
        "yes_votes", "no_votes", "confirmed_by_user_id", "status",
    ])


def term_out(store, r):
    present, absent, excused = attendance_counts(store, r["id"])
    out = _pick(r, COMMON + [
        "appointment_id", "seat_id", "applicant_id", "board_id",
        "term_start_date", "term_end_date", "term_sequence_number", "is_holdover",
    ])
    out["present_count"] = present
    out["absent_count"] = absent
    out["excused_count"] = excused
    out["provisional_attendance_rate"] = provisional_rate(present, absent)
    out["final_attendance_rate"] = final_rate(present, absent, excused)
    out["status"] = r["status"]
    return out


def meeting_out(r):
    return _pick(r, COMMON + [
        "board_id", "scheduled_date", "notice_posted_at", "notice_compliant", "status",
    ])


def attendance_out(r):
    return _pick(r, ["id", "created_at", "term_id", "meeting_id", "presence"])


def disclosure_out(r):
    return _pick(r, COMMON + [
        "term_id", "board_id", "filing_type", "due_date", "filed_at",
        "content", "status",
    ])


def removal_out(r):
    return _pick(r, COMMON + [
        "term_id", "reason", "effective_date", "initiated_by_user_id", "status",
    ])


def reappointment_out(r):
    return _pick(r, COMMON + [
        "term_id", "seat_id", "applicant_id", "requested_term_start",
        "consecutive_terms_at_request", "cumulative_years_at_request",
        "resulting_appointment_id", "status",
    ])
