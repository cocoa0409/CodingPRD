"""Resource serialisation: stored fields plus every derived field, always fresh."""
import calc
from store import db, iso


def school_json(school):
    out = {
        "id": school["id"],
        "name": school["name"],
        "building_code": school["building_code"],
        "cot_capacity": school["cot_capacity"],
        "emergency_protocol_enabled": school["emergency_protocol_enabled"],
    }
    out.update(calc.school_derived(school))
    out.update(_common(school))
    return out


def _common(record):
    return {
        "created_at": iso(record["created_at"]),
        "updated_at": iso(record["updated_at"]),
        "version": record["version"],
    }


def nurse_json(nurse):
    out = {
        "id": nurse["id"],
        "full_name": nurse["full_name"],
        "credential": nurse["credential"],
        "delegation_authorized": nurse["delegation_authorized"],
        "weekly_contracted_minutes": nurse["weekly_contracted_minutes"],
        "committed_weekly_minutes": nurse["committed_weekly_minutes"],
        "uncommitted_weekly_minutes": nurse["uncommitted_weekly_minutes"],
        "assigned_school_count": calc.assigned_school_count(nurse["id"]),
        "employment_status": nurse["employment_status"],
    }
    out.update(_common(nurse))
    return out


def coverage_json(block):
    out = {
        "id": block["id"],
        "nurse_id": block["nurse_id"],
        "school_id": block["school_id"],
        "weekday": block["weekday"],
        "start_minute": block["start_minute"],
        "end_minute": block["end_minute"],
        "effective_from": iso(block["effective_from"]),
        "effective_to": iso(block.get("effective_to")),
        "duration_minutes": calc.duration_minutes(block),
        "status": calc.coverage_status(block),
    }
    out.update(_common(block))
    return out


def student_json(student):
    effective = calc.effective_risk_score(student)
    plan = calc.active_action_plan(student["id"])
    out = {
        "id": student["id"],
        "school_id": student["school_id"],
        "full_name": student["full_name"],
        "grade_level": student["grade_level"],
        "date_of_birth": iso(student["date_of_birth"]),
        "allergy_severity": student["allergy_severity"],
        "chronic_condition_codes": list(student["chronic_condition_codes"]),
        "immunization_status": student["immunization_status"],
        "privacy_hold": student["privacy_hold"],
        "enrollment_status": student["enrollment_status"],
        "intake_risk_score": student["intake_risk_score"],
        "observed_risk_score": student["observed_risk_score"],
        "effective_risk_score": effective,
        "risk_tier": calc.risk_tier(effective),
        "alert_flags": calc.alert_flags(student),
        "self_carry_authorized": calc.self_carry_authorized(student["id"]),
        "active_action_plan_id": plan["id"] if plan else None,
    }
    out.update(_common(student))
    return out


def plan_json(plan):
    out = {
        "id": plan["id"],
        "student_id": plan["student_id"],
        "supersedes_action_plan_id": plan.get("supersedes_action_plan_id"),
        "condition_code": plan["condition_code"],
        "severity_score": plan["severity_score"],
        "requires_stock_epinephrine": plan["requires_stock_epinephrine"],
        "self_carry_requested": plan["self_carry_requested"],
        "effective_from": iso(plan["effective_from"]),
        "review_due_at": iso(plan.get("review_due_at")),
        "guardian_consent_at": iso(plan.get("guardian_consent_at")),
        "provider_signed_at": iso(plan.get("provider_signed_at")),
        "revision_round": plan["revision_round"],
        "status": plan["status"],
    }
    out.update(_common(plan))
    return out


def authorization_json(auth):
    last = calc.last_administered_at(auth)
    out = {
        "id": auth["id"],
        "student_id": auth["student_id"],
        "action_plan_id": auth.get("action_plan_id"),
        "medication_code": auth["medication_code"],
        "route": auth["route"],
        "dose_amount": auth["dose_amount"],
        "dose_unit": auth["dose_unit"],
        "schedule_type": auth["schedule_type"],
        "prn_min_interval_minutes": auth.get("prn_min_interval_minutes"),
        "max_doses_per_day": auth["max_doses_per_day"],
        "valid_from": iso(auth["valid_from"]),
        "valid_until": iso(auth["valid_until"]),
        "is_controlled": auth["is_controlled"],
        "consent_status": auth["consent_status"],
        "clinical_status": auth["clinical_status"],
        "dispensable": calc.dispensable(auth),
        "doses_administered_today": calc.doses_administered_today(auth),
        "last_administered_at": iso(last),
    }
    out.update(_common(auth))
    return out


def lot_json(lot):
    out = {
        "id": lot["id"],
        "school_id": lot["school_id"],
        "medication_code": lot["medication_code"],
        "lot_number": lot["lot_number"],
        "is_stock_protocol": lot["is_stock_protocol"],
        "expiration_date": iso(lot["expiration_date"]),
        "received_total": lot["received_total"],
        "quantity_on_hand": lot["quantity_on_hand"],
        "quantity_reserved": lot["quantity_reserved"],
        "quantity_administered": lot["quantity_administered"],
        "quantity_wasted": lot["quantity_wasted"],
        "quantity_available": lot["quantity_on_hand"],
        "days_of_supply": calc.as_float(calc.lot_days_of_supply(lot)),
        "status": lot["status"],
    }
    out.update(_common(lot))
    return out


def visit_json(visit):
    out = {
        "id": visit["id"],
        "student_id": visit["student_id"],
        "school_id": visit["school_id"],
        "nurse_id": visit["nurse_id"],
        "complaint_code": visit["complaint_code"],
        "acuity": visit["acuity"],
        "assessment_note": visit.get("assessment_note"),
        "arrival_at": iso(visit["arrival_at"]),
        "closed_at": iso(visit.get("closed_at")),
        "triage_score": visit["triage_score"],
        "requires_ems_review": visit["requires_ems_review"],
        "disposition": visit.get("disposition"),
        "guardian_notified": visit["guardian_notified"],
        "reopen_count": visit["reopen_count"],
        "pending_administration_count": calc.pending_administration_count(visit["id"]),
        "minutes_in_office": visit.get("minutes_in_office"),
        "status": visit["status"],
    }
    out.update(_common(visit))
    return out


def record_json(record):
    out = {
        "id": record["id"],
        "visit_id": record["visit_id"],
        "authorization_id": record.get("authorization_id"),
        "lot_id": record["lot_id"],
        "administering_nurse_id": record["administering_nurse_id"],
        "witness_nurse_id": record.get("witness_nurse_id"),
        "medication_code": record["medication_code"],
        "units": record["units"],
        "dose_amount": record["dose_amount"],
        "protocol_mode": record["protocol_mode"],
        "reason_code": record.get("reason_code"),
        "prepared_at": iso(record["prepared_at"]),
        "administered_at": iso(record.get("administered_at")),
        "voided_at": iso(record.get("voided_at")),
        "status": record["status"],
    }
    out.update(_common(record))
    return out


def screening_json(screening):
    out = {
        "id": screening["id"],
        "student_id": screening["student_id"],
        "school_id": screening["school_id"],
        "screened_by_nurse_id": screening.get("screened_by_nurse_id"),
        "screening_type": screening["screening_type"],
        "scheduled_for": iso(screening["scheduled_for"]),
        "cycle_number": screening["cycle_number"],
        "result_value": screening.get("result_value"),
        "outcome": screening.get("outcome"),
        "rescreen_due_at": iso(screening.get("rescreen_due_at")),
        "referral_due_at": iso(screening.get("referral_due_at")),
        "referral_completed_at": iso(screening.get("referral_completed_at")),
        "referral_outcome": screening.get("referral_outcome"),
        "status": screening["status"],
    }
    out.update(_common(screening))
    return out


def disclosure_json(row):
    out = {
        "id": row["id"],
        "student_id": row["student_id"],
        "requester_type": row["requester_type"],
        "requester_reference": row["requester_reference"],
        "scope": list(row["scope"]),
        "purpose_code": row["purpose_code"],
        "consent_granted_at": iso(row.get("consent_granted_at")),
        "expires_at": iso(row.get("expires_at")),
        "released_at": iso(row.get("released_at")),
        "decided_by_user_id": row.get("decided_by_user_id"),
        "released_by_user_id": row.get("released_by_user_id"),
        "redaction_level": row["redaction_level"],
        "release_package_item_count": row["release_package_item_count"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out
