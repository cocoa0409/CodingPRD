"""Resource representations. Immutable resources (NurseLicense, NurseShift,
ComplianceAuditRecord) deliberately expose no updated_at and no version, and the
clock-derived statuses of licences and shifts are computed here at read time.
"""
from calc import license_status, shift_status
from util import iso


def _common(record, versioned=True):
    out = {"id": record["id"], "created_at": iso(record["created_at"])}
    if versioned:
        out["updated_at"] = iso(record["updated_at"])
        out["version"] = record["version"]
    return out


def practice_json(p):
    out = _common(p)
    out.update({
        "name": p["name"],
        "office_open_utc_hhmm": p["office_open_utc_hhmm"],
        "office_close_utc_hhmm": p["office_close_utc_hhmm"],
        "weekend_is_after_hours": p["weekend_is_after_hours"],
        "per_minute_rate_millicents": p["per_minute_rate_millicents"],
        "consent_recording_required": p["consent_recording_required"],
        "variance_review_threshold": p["variance_review_threshold"],
        "audit_period_start_utc": iso(p["audit_period_start_utc"]),
        "status": p["status"],
        "compliance_posture": p["compliance_posture"],
        "open_callback_count": p["open_callback_count"],
        "open_variance_count": p["open_variance_count"],
        "escalated_callback_count": p["escalated_callback_count"],
        "billed_advice_minutes_total": p["billed_advice_minutes_total"],
        "advice_fee_accrued_cents": p["advice_fee_accrued_cents"],
    })
    return out


def patient_json(p):
    out = _common(p)
    out.update({
        "practice_id": p["practice_id"],
        "full_name": p["full_name"],
        "dob": p["dob"].isoformat(),
        "sex": p["sex"],
        "pregnancy_status": p["pregnancy_status"],
        "phone": p["phone"],
        "mrn": p["mrn"],
    })
    return out


def nurse_json(n):
    out = _common(n)
    out.update({
        "full_name": n["full_name"],
        "seniority_level": n["seniority_level"],
        "max_concurrent_calls": n["max_concurrent_calls"],
        "high_risk_cap": n["high_risk_cap"],
        "active_call_load": n["active_call_load"],
        "pending_high_risk_count": n["pending_high_risk_count"],
        "intake_eligibility": n["intake_eligibility"],
    })
    return out


def license_json(lic):
    out = _common(lic, versioned=False)
    out.update({
        "nurse_id": lic["nurse_id"],
        "state_code": lic["state_code"],
        "license_number": lic["license_number"],
        "expires_on": lic["expires_on"].isoformat(),
        "status": license_status(lic),
    })
    return out


def shift_json(shift):
    out = _common(shift, versioned=False)
    out.update({
        "nurse_id": shift["nurse_id"],
        "start_utc": iso(shift["start_utc"]),
        "end_utc": iso(shift["end_utc"]),
        "scheduled_minutes": shift["scheduled_minutes"],
        "status": shift_status(shift),
    })
    return out


def coverage_window_json(w):
    out = _common(w)
    out.update({
        "practice_id": w["practice_id"],
        "start_utc": iso(w["start_utc"]),
        "end_utc": iso(w["end_utc"]),
        "coverage_kind": w["coverage_kind"],
        "status": w["status"],
        "suspend_reason": w["suspend_reason"],
    })
    return out


def protocol_json(p):
    out = _common(p)
    out.update({
        "code": p["code"],
        "title": p["title"],
        "base_severity": p["base_severity"],
        "min_age_years": p["min_age_years"],
        "max_age_years": p["max_age_years"],
        "pregnancy_sensitive": p["pregnancy_sensitive"],
        "emergency_override": p["emergency_override"],
        "min_disposition_level": p["min_disposition_level"],
        "infant_modifier_points": p["infant_modifier_points"],
        "status": p["status"],
    })
    return out


def call_json(c):
    out = _common(c)
    out.update({
        "practice_id": c["practice_id"],
        "patient_id": c["patient_id"],
        "caller_name": c["caller_name"],
        "caller_phone": c["caller_phone"],
        "caller_relationship": c["caller_relationship"],
        "caller_state_code": c["caller_state_code"],
        "reason_text": c["reason_text"],
        "status": c["status"],
        "is_after_hours": c["is_after_hours"],
        "match_method": c["match_method"],
        "match_confidence_pct": c["match_confidence_pct"],
        "consent_type": c["consent_type"],
        "consent_given_by": c["consent_given_by"],
        "consent_recorded_at": iso(c["consent_recorded_at"]),
        "recording_reference": c["recording_reference"],
        "assigned_nurse_id": c["assigned_nurse_id"],
        "assigned_at": iso(c["assigned_at"]),
        "deferred_assignment_count": c["deferred_assignment_count"],
        "requires_warm_transfer": c["requires_warm_transfer"],
        "warm_transfer_completed_at": iso(c["warm_transfer_completed_at"]),
        "handle_minutes": c["handle_minutes"],
        "billable_minutes": c["billable_minutes"],
        "advice_fee_cents": c["advice_fee_cents"],
        "closed_at": iso(c["closed_at"]),
        "reopen_count": c["reopen_count"],
        "abandon_reason": c["abandon_reason"],
    })
    return out


def assessment_json(a):
    out = _common(a)
    out.update({
        "call_id": a["call_id"],
        "protocol_id": a["protocol_id"],
        "confirmation_mode": a["confirmation_mode"],
        "stated_age_years": a["stated_age_years"],
        "confirmed_pregnancy_status": a["confirmed_pregnancy_status"],
        "red_flag_count": a["red_flag_count"],
        "age_years_used": a["age_years_used"],
        "pregnancy_status_used": a["pregnancy_status_used"],
        "age_modifier_points": a["age_modifier_points"],
        "pregnancy_modifier_points": a["pregnancy_modifier_points"],
        "red_flag_points": a["red_flag_points"],
        "acuity_score": a["acuity_score"],
        "status": a["status"],
    })
    return out


def disposition_json(d):
    out = _common(d)
    out.update({
        "call_id": d["call_id"],
        "assessment_id": d["assessment_id"],
        "determined_by_nurse_id": d["determined_by_nurse_id"],
        "overridden_by_nurse_id": d["overridden_by_nurse_id"],
        "recommended_level": d["recommended_level"],
        "final_level": d["final_level"],
        "is_override": d["is_override"],
        "override_reason_code": d["override_reason_code"],
        "override_narrative": d["override_narrative"],
        "requires_callback": d["requires_callback"],
        "advice_status": d["advice_status"],
        "audit_status": d["audit_status"],
        "callback_verified_at": iso(d["callback_verified_at"]),
    })
    return out


def warm_transfer_json(t):
    out = _common(t)
    out.update({
        "call_id": t["call_id"],
        "psap_center_code": t["psap_center_code"],
        "location_source": t["location_source"],
        "location_address_line": t["location_address_line"],
        "location_state_code": t["location_state_code"],
        "location_lat": t["location_lat"],
        "location_lng": t["location_lng"],
        "callback_number": t["callback_number"],
        "location_verified_by": t["location_verified_by"],
        "location_confidence_pct": t["location_confidence_pct"],
        "psap_incident_number": t["psap_incident_number"],
        "status": t["status"],
    })
    return out


def callback_task_json(t):
    out = _common(t)
    out.update({
        "disposition_id": t["disposition_id"],
        "practice_id": t["practice_id"],
        "assigned_nurse_id": t["assigned_nurse_id"],
        "risk_class": t["risk_class"],
        "due_by_utc": iso(t["due_by_utc"]),
        "attempt_count": t["attempt_count"],
        "max_attempts": t["max_attempts"],
        "last_attempt_outcome": t["last_attempt_outcome"],
        "patient_condition": t["patient_condition"],
        "advice_followed": t["advice_followed"],
        "verifier_attestation": t["verifier_attestation"],
        "verified_by_nurse_id": t["verified_by_nurse_id"],
        "verified_at": iso(t["verified_at"]),
        "status": t["status"],
    })
    return out


def audit_record_json(r):
    out = _common(r, versioned=False)
    out.update({
        "disposition_id": r["disposition_id"],
        "auditor_user_id": r["auditor_user_id"],
        "reported_outcome": r["reported_outcome"],
        "outcome_source": r["outcome_source"],
        "outcome_observed_at": iso(r["outcome_observed_at"]),
        "outcome_ordinal": r["outcome_ordinal"],
        "disposition_level_ordinal": r["disposition_level_ordinal"],
        "variance_class": r["variance_class"],
        "variance_severity_points": r["variance_severity_points"],
    })
    return out
