"""Resource serialisers.

Every instant-valued field passes through `render_instant` and every
date-valued field through `render_date`, so no code path can emit a
differently shaped instant.
"""

import calc
from timefmt import render_date, render_instant


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = render_instant(row["created_at"])
    out["updated_at"] = render_instant(row["updated_at"])
    out["version"] = row["version"]
    return out


def program_period(row):
    return _common(row, {
        "name": row["name"],
        "starts_on": render_date(row["starts_on"]),
        "ends_on": render_date(row["ends_on"]),
        "status": row["status"],
        "frozen_at": render_instant(row["frozen_at"]),
        "state_submission_ref": row["state_submission_ref"],
    })


def site(row):
    active_holds = sum(
        1 for h in _rows("site_holds") if h["site_id"] == row["id"] and h["hold_status"] == "ACTIVE"
    )
    return _common(row, {
        "name": row["name"],
        "site_type": row["site_type"],
        "state_code": row["state_code"],
        "status": row["status"],
        "roster_disclosure_level": row["roster_disclosure_level"],
        "facility_contact_name": row["facility_contact_name"],
        "active_hold_count": active_holds,
    })


def site_hold(row):
    return _common(row, {
        "site_id": row["site_id"],
        "hold_type": row["hold_type"],
        "starts_at": render_instant(row["starts_at"]),
        "ends_at": render_instant(row["ends_at"]),
        "hold_status": row["hold_status"],
        "reason": row["reason"],
        "released_at": render_instant(row["released_at"]),
        "blocked_visit_count": row["blocked_visit_count"],
    })


def patient(row):
    return _common(row, {
        "site_id": row["site_id"],
        "patient_type": row["patient_type"],
        "external_ref": row["external_ref"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "date_of_birth": render_date(row["date_of_birth"]),
        "grade_level": row["grade_level"],
        "room_number": row["room_number"],
        "household_size": row["household_size"],
        "annual_household_income_cents": row["annual_household_income_cents"],
        "capacity_determination": row["capacity_determination"],
        "capacity_determined_at": render_instant(row["capacity_determined_at"]),
        "varnish_applications_in_period": row["varnish_applications_in_period"],
        "last_varnish_date": render_date(row["last_varnish_date"]),
    })


def consent(row):
    return _common(row, {
        "patient_id": row["patient_id"],
        "site_id": row["site_id"],
        "program_period_id": row["program_period_id"],
        "regime": row["regime"],
        "scope_tier": row["scope_tier"],
        "status": row["status"],
        "guardian_name": row["guardian_name"],
        "guardian_relationship": row["guardian_relationship"],
        "responsible_party_name": row["responsible_party_name"],
        "responsible_party_authority": row["responsible_party_authority"],
        "poa_document_ref": row["poa_document_ref"],
        "signed_at": render_instant(row["signed_at"]),
        "expires_at": render_instant(row["expires_at"]),
        "reaffirmation_due_at": render_instant(row["reaffirmation_due_at"]),
        "superseded_by_consent_id": row["superseded_by_consent_id"],
        "revoked_at": render_instant(row["revoked_at"]),
        "revoke_reason": row["revoke_reason"],
        "expired_at": render_instant(row["expired_at"]),
        "invalidated_procedure_count": row["invalidated_procedure_count"],
    })


def portable_unit(row):
    due_on, status = calc.calibration_projection(row)
    return _common(row, {
        "unit_code": row["unit_code"],
        "status": row["status"],
        "last_calibrated_on": render_date(row["last_calibrated_on"]),
        "calibration_due_on": render_date(due_on),
        "calibration_status": status,
        "last_passed_load_at": render_instant(row["last_passed_load_at"]),
        "quarantined_at": render_instant(row["quarantined_at"]),
    })


def sterilization_load(row):
    return _common(row, {
        "portable_unit_id": row["portable_unit_id"],
        "site_visit_id": row["site_visit_id"],
        "loaded_by_staff_id": row["loaded_by_staff_id"],
        "result_recorded_by_staff_id": row["result_recorded_by_staff_id"],
        "load_number": row["load_number"],
        "cycle_completed_at": render_instant(row["cycle_completed_at"]),
        "incubation_ends_at": render_instant(row["incubation_ends_at"]),
        "spore_result": row["spore_result"],
        "result_recorded_at": render_instant(row["result_recorded_at"]),
        "auto_failed": row["auto_failed"],
        "tainted_procedure_count": row["tainted_procedure_count"],
    })


def staff_member(row):
    return _common(row, {
        "full_name": row["full_name"],
        "staff_role": row["staff_role"],
        "license_number": row["license_number"],
        "license_state": row["license_state"],
        "supervision_level": row["supervision_level"],
        "credential_status": row["credential_status"],
        "credential_expires_on": render_date(row["credential_expires_on"]),
    })


def site_visit(row):
    return _common(row, {
        "site_id": row["site_id"],
        "program_period_id": row["program_period_id"],
        "portable_unit_id": row["portable_unit_id"],
        "lead_staff_id": row["lead_staff_id"],
        "onsite_dentist_staff_id": row["onsite_dentist_staff_id"],
        "remote_dentist_staff_id": row["remote_dentist_staff_id"],
        "scheduled_start_at": render_instant(row["scheduled_start_at"]),
        "scheduled_end_at": render_instant(row["scheduled_end_at"]),
        "chair_count": row["chair_count"],
        "capacity_chair_minutes": row["capacity_chair_minutes"],
        "booked_chair_minutes": calc.booked_chair_minutes(row["id"]),
        "status": row["status"],
        "reschedule_count": row["reschedule_count"],
        "started_at": render_instant(row["started_at"]),
        "completed_at": render_instant(row["completed_at"]),
        "cancelled_at": render_instant(row["cancelled_at"]),
    })


def coverage(row):
    percent = row["fpl_percent"]
    return _common(row, {
        "patient_id": row["patient_id"],
        "payer_type": row["payer_type"],
        "payer_name": row["payer_name"],
        "member_id": row["member_id"],
        "verification_status": row["verification_status"],
        "verified_through_date": render_date(row["verified_through_date"]),
        "verified_at": render_instant(row["verified_at"]),
        "fpl_percent": float(percent) if percent is not None else None,
        "sliding_fee_band": row["sliding_fee_band"],
        "determination_date": render_date(row["determination_date"]),
    })


def encounter(row):
    tainted = sum(
        1 for p in calc.encounter_procedures(row["id"]) if p["status"] == "TAINTED"
    )
    return _common(row, {
        "site_visit_id": row["site_visit_id"],
        "patient_id": row["patient_id"],
        "consent_id": row["consent_id"],
        "coverage_id": row["coverage_id"],
        "clinical_status": row["clinical_status"],
        "billing_status": row["billing_status"],
        "triage_band": row["triage_band"],
        "cavitated_lesion_count": row["cavitated_lesion_count"],
        "pain_reported": row["pain_reported"],
        "abscess_or_swelling": row["abscess_or_swelling"],
        "untreated_decay_present": row["untreated_decay_present"],
        "denture_problem": row["denture_problem"],
        "oral_hygiene_score": row["oral_hygiene_score"],
        "medical_complexity_count": row["medical_complexity_count"],
        "exam_modality": row["exam_modality"],
        "teledentistry_reviewed_at": render_instant(row["teledentistry_reviewed_at"]),
        "subtotal_cents": row["subtotal_cents"],
        "supply_surcharge_cents": row["supply_surcharge_cents"],
        "total_charge_cents": row["total_charge_cents"],
        "allowed_amount_cents": row["allowed_amount_cents"],
        "patient_responsibility_cents": row["patient_responsibility_cents"],
        "plan_paid_cents": row["plan_paid_cents"],
        "write_off_cents": row["write_off_cents"],
        "pricing_regime": row["pricing_regime"],
        "tainted_procedure_count": tainted,
        "deferred_reason": row["deferred_reason"],
        "denial_reason": row["denial_reason"],
    })


def procedure(row):
    return _common(row, {
        "encounter_id": row["encounter_id"],
        "treatment_plan_id": row["treatment_plan_id"],
        "sterilization_load_id": row["sterilization_load_id"],
        "performing_staff_id": row["performing_staff_id"],
        "procedure_code": row["procedure_code"],
        "tooth_number": row["tooth_number"],
        "surface": row["surface"],
        "required_tier": row["required_tier"],
        "chair_minutes": row["chair_minutes"],
        "charge_cents": row["charge_cents"],
        "status": row["status"],
        "performed_at": render_instant(row["performed_at"]),
        "taint_reason": row["taint_reason"],
        "void_reason": row["void_reason"],
    })


def treatment_plan(row):
    # follow_up_status is a read-derived projection (PRD 2.4); a plan the
    # referral loop drove to COMPLETED keeps the CONTACTED value pinned on it.
    if row["plan_status"] == "COMPLETED":
        status = row.get("follow_up_status") or "CONTACTED"
    else:
        status = calc.follow_up_status(row)
    return _common(row, {
        "encounter_id": row["encounter_id"],
        "patient_id": row["patient_id"],
        "authoring_staff_id": row["authoring_staff_id"],
        "plan_status": row["plan_status"],
        "urgency_band": row["urgency_band"],
        "planned_procedure_codes": list(row["planned_procedure_codes"]),
        "activated_on": render_date(row["activated_on"]),
        "follow_up_due_date": render_date(row["follow_up_due_date"]),
        "follow_up_status": status,
        "last_contact_at": render_instant(row["last_contact_at"]),
        "contact_attempt_count": row["contact_attempt_count"],
        "superseded_reason": row["superseded_reason"],
    })


def referral(row):
    return _common(row, {
        "treatment_plan_id": row["treatment_plan_id"],
        "patient_id": row["patient_id"],
        "dental_home_name": row["dental_home_name"],
        "status": row["status"],
        "attempt_count": row["attempt_count"],
        "due_at": render_instant(row["due_at"]),
        "last_sent_at": render_instant(row["last_sent_at"]),
        "next_eligible_send_at": render_instant(row["next_eligible_send_at"]),
        "abandoned_at": render_instant(row["abandoned_at"]),
        "abandon_reason": row["abandon_reason"],
        "case_management_opened_at": render_instant(row["case_management_opened_at"]),
    })


def report(row):
    return _common(row, {
        "program_period_id": row["program_period_id"],
        "site_id": row["site_id"],
        "patient_id": row["patient_id"],
        "report_type": row["report_type"],
        "recipient_user_id": row["recipient_user_id"],
        "status": row["status"],
        "payload": row["payload"],
        "generated_at": render_instant(row["generated_at"]),
        "submitted_at": render_instant(row["submitted_at"]),
        "stale_reason": row["stale_reason"],
    })


def _rows(collection):
    import store
    return store.all_rows(collection)


def many(serializer, rows):
    return [serializer(r) for r in rows]
