"""Entity-to-JSON serializers.

Each `serialize_*` function returns a dict matching the entity's exposed
shape per SCAFFOLD.yaml §1.1. Internal helper fields (like raw date objects)
are converted to ISO strings on the way out.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.util import date_to_iso, iso_utc


def _maybe_iso(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return iso_utc(value)
    if isinstance(value, date):
        return date_to_iso(value)
    return value


def serialize_claimant(c: dict) -> dict:
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "date_of_birth": _maybe_iso(c["date_of_birth"]),
        "filing_date": _maybe_iso(c["filing_date"]),
        "alleged_onset_date": _maybe_iso(c["alleged_onset_date"]),
        "established_onset_date": _maybe_iso(c.get("established_onset_date")),
        "total_qc_earned": c["total_qc_earned"],
        "qc_required": c["qc_required"],
        "qc_recent_window": c["qc_recent_window"],
        "qc_recent_required": c["qc_recent_required"],
        "insured_status": c["insured_status"],
        "ssn_last4": c["ssn_last4"],
        "created_at": _maybe_iso(c["created_at"]),
        "updated_at": _maybe_iso(c["updated_at"]),
        "version": c["version"],
    }


def serialize_quarter_credit(q: dict) -> dict:
    return {
        "id": q["id"],
        "claimant_id": q["claimant_id"],
        "year": q["year"],
        "quarter": q["quarter"],
        "earnings_cents": q["earnings_cents"],
        "qc_count": q["qc_count"],
        "credited": q["credited"],
        "created_at": _maybe_iso(q["created_at"]),
    }


def serialize_medical_evidence(m: dict) -> dict:
    return {
        "id": m["id"],
        "claimant_id": m["claimant_id"],
        "source_type": m["source_type"],
        "listing_code": m.get("listing_code"),
        "rfc_exertional_level": m.get("rfc_exertional_level"),
        "rfc_skill_level": m.get("rfc_skill_level"),
        "age_category_at_decision": m.get("age_category_at_decision"),
        "education_level": m.get("education_level"),
        "medical_findings": m["medical_findings"],
        "evidence_date": _maybe_iso(m["evidence_date"]),
        "status": m["status"],
        "created_at": _maybe_iso(m["created_at"]),
        "updated_at": _maybe_iso(m["updated_at"]),
        "version": m["version"],
    }


def serialize_application(a: dict) -> dict:
    return {
        "id": a["id"],
        "claimant_id": a["claimant_id"],
        "status": a["status"],
        "medical_decision": a.get("medical_decision"),
        "last_initial_examiner_id": a.get("last_initial_examiner_id"),
        "established_onset_date": _maybe_iso(a.get("established_onset_date")),
        "pia_cents": a.get("pia_cents"),
        "aime_cents": a.get("aime_cents"),
        "family_max_cents": a.get("family_max_cents"),
        "monthly_benefit_cents": a.get("monthly_benefit_cents"),
        "entitlement_date": _maybe_iso(a.get("entitlement_date")),
        "back_pay_cents": a.get("back_pay_cents"),
        "approval_date": _maybe_iso(a.get("approval_date")),
        "next_cdr_due_date": _maybe_iso(a.get("next_cdr_due_date")),
        "cdr_diary": a.get("cdr_diary"),
        "created_at": _maybe_iso(a["created_at"]),
        "updated_at": _maybe_iso(a["updated_at"]),
        "version": a["version"],
    }


def serialize_determination(d: dict) -> dict:
    return {
        "id": d["id"],
        "application_id": d["application_id"],
        "level": d["level"],
        "examiner_id": d["examiner_id"],
        "examiner_role": d["examiner_role"],
        "decision": d["decision"],
        "medical_basis": d.get("medical_basis"),
        "established_onset_date": _maybe_iso(d.get("established_onset_date")),
        "rationale": d["rationale"],
        "created_at": _maybe_iso(d["created_at"]),
    }


def serialize_hearing_slot(h: dict) -> dict:
    return {
        "id": h["id"],
        "alj_id": h["alj_id"],
        "hearing_office": h["hearing_office"],
        "start_at": _maybe_iso(h["start_at"]),
        "end_at": _maybe_iso(h["end_at"]),
        "application_id": h.get("application_id"),
        "status": h["status"],
        "created_at": _maybe_iso(h["created_at"]),
        "updated_at": _maybe_iso(h["updated_at"]),
        "version": h["version"],
    }


def serialize_child_auxiliary(c: dict) -> dict:
    return {
        "id": c["id"],
        "application_id": c["application_id"],
        "child_name": c["child_name"],
        "child_date_of_birth": _maybe_iso(c["child_date_of_birth"]),
        "child_relationship": c["child_relationship"],
        "is_full_time_student": c.get("is_full_time_student"),
        "is_disabled_before_22": c.get("is_disabled_before_22"),
        "status": c["status"],
        "termination_reason": c.get("termination_reason"),
        "monthly_benefit_cents": c.get("monthly_benefit_cents"),
        "created_at": _maybe_iso(c["created_at"]),
        "updated_at": _maybe_iso(c["updated_at"]),
        "version": c["version"],
    }


def serialize_ssi_supplement(s: dict) -> dict:
    return {
        "id": s["id"],
        "claimant_id": s["claimant_id"],
        "countable_income_cents": s["countable_income_cents"],
        "countable_resources_cents": s["countable_resources_cents"],
        "living_arrangement": s["living_arrangement"],
        "ssi_payment_cents": s.get("ssi_payment_cents"),
        "status": s["status"],
        "created_at": _maybe_iso(s["created_at"]),
        "updated_at": _maybe_iso(s["updated_at"]),
        "version": s["version"],
    }


def serialize_cdr_review(r: dict) -> dict:
    return {
        "id": r["id"],
        "application_id": r["application_id"],
        "review_due_date": _maybe_iso(r["review_due_date"]),
        "scheduled_at": _maybe_iso(r.get("scheduled_at")),
        "completed_at": _maybe_iso(r.get("completed_at")),
        "outcome": r.get("outcome"),
        "medical_improvement_found": r.get("medical_improvement_found"),
        "working_at_sga": r.get("working_at_sga"),
        "status": r["status"],
        "created_at": _maybe_iso(r["created_at"]),
        "updated_at": _maybe_iso(r["updated_at"]),
        "version": r["version"],
    }
