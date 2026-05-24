"""Serializers convert in-memory entity dicts into API JSON shapes.

Common fields (id, created_at, updated_at, version) are populated by
util.common_fields. Entity-specific fields follow the §1.1 entity tables.
"""

from util import common_fields, format_iso


def serialize_applicant(row):
    base = common_fields(row)
    base.update({
        "email": row["email"],
        "full_name": row["full_name"],
        "gpa": row["gpa"],
        "sat_total": row.get("sat_total"),
        "profile_status": row["profile_status"],
    })
    return base


def serialize_recommender(row):
    base = common_fields(row)
    base.update({
        "applicant_id": row["applicant_id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "relationship": row["relationship"],
        "invite_status": row["invite_status"],
    })
    return base


def serialize_school(row):
    base = common_fields(row)
    base.update({
        "name": row["name"],
        "target_class_size": row["target_class_size"],
        "ed_deadline_iso": format_iso(row["ed_deadline_iso"]),
        "ea_deadline_iso": format_iso(row["ea_deadline_iso"]),
        "rd_deadline_iso": format_iso(row["rd_deadline_iso"]),
        "rolling_open": row["rolling_open"],
        "requires_css_profile": row["requires_css_profile"],
        "confirmed_enrollment_count": row["confirmed_enrollment_count"],
        "posture": row["posture"],
    })
    return base


def serialize_application(row, *, admission_probability_score=None):
    base = common_fields(row)
    base.update({
        "applicant_id": row["applicant_id"],
        "school_id": row["school_id"],
        "plan": row["plan"],
        "status": row["status"],
        "submitted_at": format_iso(row.get("submitted_at")),
        "decision_at": format_iso(row.get("decision_at")),
        "waitlist_rank": row.get("waitlist_rank"),
        "waitlist_added_at": format_iso(row.get("waitlist_added_at")),
    })
    if admission_probability_score is not None:
        base["admission_probability_score"] = admission_probability_score
    return base


def serialize_essay(row):
    base = common_fields(row)
    base.update({
        "application_id": row["application_id"],
        "prompt_code": row["prompt_code"],
        "body": row["body"],
        "word_count": row["word_count"],
        "locked": row["locked"],
    })
    return base


def serialize_letter(row):
    base = common_fields(row)
    base.update({
        "application_id": row["application_id"],
        "recommender_id": row["recommender_id"],
        "status": row["status"],
        "body": row.get("body"),
        "submitted_at": format_iso(row.get("submitted_at")),
    })
    return base


def serialize_fa_profile(row):
    base = common_fields(row)
    base.update({
        "applicant_id": row["applicant_id"],
        "fafsa_efc_cents": row["fafsa_efc_cents"],
        "css_efc_cents": row.get("css_efc_cents"),
        "family_income_cents": row["family_income_cents"],
        "status": row["status"],
    })
    return base


def serialize_aid_offer(row):
    base = common_fields(row)
    base.update({
        "application_id": row["application_id"],
        "cost_of_attendance_cents": row["cost_of_attendance_cents"],
        "variant": row["variant"],
        "demonstrated_need_cents": row["demonstrated_need_cents"],
        "grant_cents": row["grant_cents"],
        "loan_cents": row["loan_cents"],
        "work_study_cents": row["work_study_cents"],
        "net_price_cents": row["net_price_cents"],
    })
    return base


def serialize_admission_cycle(row):
    base = common_fields(row)
    base.update({
        "school_id": row["school_id"],
        "clock_iso": format_iso(row.get("clock_iso")),
        "last_yield_run_at": format_iso(row.get("last_yield_run_at")),
        "yield_run_count": row["yield_run_count"],
        "cooldown_ms": row["cooldown_ms"],
    })
    return base
