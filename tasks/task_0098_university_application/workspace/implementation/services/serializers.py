"""Outbound serializers: convert internal records (with Decimal values) to JSON-safe dicts."""
from __future__ import annotations
from decimal import Decimal


def _scalar(v):
    if isinstance(v, Decimal):
        # Keep two decimal places for score-like Decimals; Decimal preserves trailing zeros.
        return float(v)
    return v


def applicant_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "full_name": r["full_name"],
        "email": r["email"],
        "date_of_birth": r["date_of_birth"],
        "high_school_gpa": float(r["high_school_gpa"]) if isinstance(r["high_school_gpa"], Decimal) else r["high_school_gpa"],
        "household_income_cents": r["household_income_cents"],
        "fafsa_efc_cents": r.get("fafsa_efc_cents"),
        "css_profile_efc_cents": r.get("css_profile_efc_cents"),
        "ed_commitment_application_id": r.get("ed_commitment_application_id"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def university_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "yield_target_count": r["yield_target_count"],
        "regular_decision_deadline": r["regular_decision_deadline"],
        "early_decision_deadline": r["early_decision_deadline"],
        "rolling_admission_enabled": r.get("rolling_admission_enabled", False),
        "enrolled_count": r.get("enrolled_count", 0),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def program_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "university_id": r["university_id"],
        "name": r["name"],
        "capacity": r["capacity"],
        "admitted_count": r.get("admitted_count", 0),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def application_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "applicant_id": r["applicant_id"],
        "program_id": r["program_id"],
        "round": r["round"],
        "status": r["status"],
        "essay_id": r.get("essay_id"),
        "required_recommendation_count": r["required_recommendation_count"],
        "submitted_at": r.get("submitted_at"),
        "admission_decision_at": r.get("admission_decision_at"),
        "enrollment_deadline": r.get("enrollment_deadline"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def essay_out(r: dict) -> dict:
    score = r.get("customization_score")
    if isinstance(score, Decimal):
        score = float(score)
    return {
        "id": r["id"],
        "application_id": r["application_id"],
        "prompt_code": r["prompt_code"],
        "body": r["body"],
        "word_count": r.get("word_count", 0),
        "customization_score": score,
        "created_at": r["created_at"],
    }


def recommendation_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "application_id": r["application_id"],
        "recommender_email": r["recommender_email"],
        "status": r["status"],
        "invitation_expires_at": r.get("invitation_expires_at"),
        "letter_body": r.get("letter_body"),
        "letter_word_count": r.get("letter_word_count"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def aid_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "application_id": r["application_id"],
        "aid_method": r["aid_method"],
        "status": r["status"],
        "cost_of_attendance_cents": r["cost_of_attendance_cents"],
        "grant_cents": r.get("grant_cents", 0),
        "loan_cents": r.get("loan_cents", 0),
        "work_study_cents": r.get("work_study_cents", 0),
        "total_award_cents": r.get("total_award_cents", 0),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def waitlist_out(r: dict) -> dict:
    score = r.get("rank_score")
    if isinstance(score, Decimal):
        score = float(score)
    return {
        "id": r["id"],
        "application_id": r["application_id"],
        "program_id": r["program_id"],
        "status": r["status"],
        "rank_score": score,
        "offered_at": r.get("offered_at"),
        "offer_expires_at": r.get("offer_expires_at"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def sweep_out(r: dict) -> dict:
    return {
        "id": r["id"],
        "university_id": r["university_id"],
        "epoch": r["epoch"],
        "enrolled_count_at_start": r["enrolled_count_at_start"],
        "offers_extended": r["offers_extended"],
        "ran_at": r["ran_at"],
        "created_at": r["created_at"],
    }
