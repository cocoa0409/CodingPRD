"""Payload factories — one per entity, carrying only client-supplied fields."""

DEFAULTS = {
    "LEGAL_NAME": "Northside Manufacturing LLC",
    "NAICS_CODE": "332999",
    "INDUSTRY_SECTOR": "MANUFACTURING",
    "WORKERS_COMP_CARRIER": "Statewide Mutual",
    "WORKERS_COMP_POLICY_NO": "WC-2026-88120",
    "WORKERS_COMP_EXPIRES_ON": "2027-06-30",
    "SITE_NAME": "Northside Plant Floor 2",
    "ADDRESS_LINE": "1420 Industrial Parkway",
    "SUPERVISOR_NAME": "Dana Whitfield",
    "SUPERVISOR_EMAIL": "dana.whitfield@northside.example",
    "TRAINING_COMPLETED_ON": "2026-05-01",
    "STUDENT_NAME": "Jordan Alvarez",
    "COURSE_CODE": "MFG-210",
    "COMPETENCY_CODE": "MFG-C1",
    "OBJECTIVE_DESCRIPTION": "Demonstrate safe machine set-up to district rubric level 3.",
}


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


def create_employer_partner_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "naics_code": DEFAULTS["NAICS_CODE"],
        "industry_sector": DEFAULTS["INDUSTRY_SECTOR"],
        "workers_comp_carrier": DEFAULTS["WORKERS_COMP_CARRIER"],
        "workers_comp_policy_no": DEFAULTS["WORKERS_COMP_POLICY_NO"],
        "workers_comp_expires_on": DEFAULTS["WORKERS_COMP_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def update_employer_insurance_payload(**overrides) -> dict:
    payload = {
        "workers_comp_carrier": DEFAULTS["WORKERS_COMP_CARRIER"],
        "workers_comp_policy_no": DEFAULTS["WORKERS_COMP_POLICY_NO"],
        "workers_comp_expires_on": DEFAULTS["WORKERS_COMP_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def create_worksite_payload(employer_partner_id: str, **overrides) -> dict:
    payload = {
        "employer_partner_id": employer_partner_id,
        "site_name": DEFAULTS["SITE_NAME"],
        "address_line": DEFAULTS["ADDRESS_LINE"],
        "hazard_class": "NON_HAZARDOUS",
        "has_power_machinery": False,
        "displaces_paid_employee": False,
        "max_concurrent_students": 3,
    }
    payload.update(overrides)
    return payload


def create_safety_review_payload(worksite_id: str, expected_worksite_version: int, **overrides) -> dict:
    payload = {
        "worksite_id": worksite_id,
        "machinery_guarding_ok": True,
        "hazard_findings_count": 0,
        "orientation_documented": True,
        "emergency_plan_on_file": True,
        "expected_worksite_version": expected_worksite_version,
    }
    payload.update(overrides)
    return payload


def decide_safety_review_payload(decision: str = "APPROVED", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_supervisor_payload(worksite_id: str, **overrides) -> dict:
    payload = {
        "worksite_id": worksite_id,
        "full_name": DEFAULTS["SUPERVISOR_NAME"],
        "email": DEFAULTS["SUPERVISOR_EMAIL"],
        "training_completed_on": DEFAULTS["TRAINING_COMPLETED_ON"],
        "max_student_load": 3,
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(
    employer_partner_id: str,
    worksite_id: str,
    employer_signer_supervisor_id: str,
    **overrides,
) -> dict:
    payload = {
        "employer_partner_id": employer_partner_id,
        "worksite_id": worksite_id,
        "employer_signer_supervisor_id": employer_signer_supervisor_id,
        "effective_on": "2026-09-01",
        "expires_on": "2027-06-30",
        "insurance_rider": True,
    }
    payload.update(overrides)
    return payload


def create_student_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["STUDENT_NAME"],
        "birth_date": "2009-03-15",
        "grade_level": 11,
        "gpa": 3.20,
        "attendance_rate": 0.96,
        "student_learner_certificate": False,
        "guardian_consent_on_file": True,
    }
    payload.update(overrides)
    return payload


def update_student_academics_payload(
    grade_level: int, gpa: float, attendance_rate: float, **overrides
) -> dict:
    payload = {
        "grade_level": grade_level,
        "gpa": gpa,
        "attendance_rate": attendance_rate,
    }
    payload.update(overrides)
    return payload


def create_work_permit_payload(student_id: str, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "permit_class": "MINOR_16_17",
        "hazardous_endorsement": False,
    }
    payload.update(overrides)
    return payload


def issue_work_permit_payload(expires_on: str = "2027-06-30", **overrides) -> dict:
    payload = {"expires_on": expires_on}
    payload.update(overrides)
    return payload


def revoke_work_permit_payload(revoked_reason: str = "Guardian withdrew consent", **overrides) -> dict:
    payload = {"revoked_reason": revoked_reason}
    payload.update(overrides)
    return payload


def create_placement_payload(
    student_id: str,
    worksite_id: str,
    agreement_id: str,
    supervisor_id: str,
    expected_worksite_version: int,
    **overrides,
) -> dict:
    payload = {
        "student_id": student_id,
        "worksite_id": worksite_id,
        "agreement_id": agreement_id,
        "supervisor_id": supervisor_id,
        "scheduled_weekly_hours": 12.00,
        "start_on": "2026-09-07",
        "end_on": "2026-12-18",
        "pay_classification": "PAID",
        "hourly_wage_cents": 1500,
        "stipend_total_cents": 0,
        "credit_target_credits": 1.00,
        "credit_award_mode": "HOURS_BASED",
        "required_evaluation_cycles": 2,
        "transportation_mode": "DISTRICT_BUS",
        "commute_round_trip_miles": 0.00,
        "expected_worksite_version": expected_worksite_version,
    }
    payload.update(overrides)
    return payload


def terminate_placement_payload(termination_reason: str = "Student withdrew", **overrides) -> dict:
    payload = {"termination_reason": termination_reason}
    payload.update(overrides)
    return payload


def compliance_decision_payload(decision: str, note: str, **overrides) -> dict:
    payload = {"decision": decision, "note": note}
    payload.update(overrides)
    return payload


def settle_wages_payload(mode: str = "FINAL", **overrides) -> dict:
    payload = {"mode": mode}
    payload.update(overrides)
    return payload


def create_training_plan_payload(
    placement_id: str, expected_placement_version: int, **overrides
) -> dict:
    payload = {
        "placement_id": placement_id,
        "course_code": DEFAULTS["COURSE_CODE"],
        "credit_hours_target": 90.00,
        "expected_placement_version": expected_placement_version,
    }
    payload.update(overrides)
    return payload


def request_changes_payload(change_request_note: str, **overrides) -> dict:
    payload = {"change_request_note": change_request_note}
    payload.update(overrides)
    return payload


def create_learning_objective_payload(
    training_plan_id: str, aligned_course_code: str, **overrides
) -> dict:
    payload = {
        "training_plan_id": training_plan_id,
        "competency_code": DEFAULTS["COMPETENCY_CODE"],
        "description": DEFAULTS["OBJECTIVE_DESCRIPTION"],
        "aligned_course_code": aligned_course_code,
        "assessment_method": "SUPERVISOR_RATING",
    }
    payload.update(overrides)
    return payload


def create_timesheet_entry_payload(
    placement_id: str,
    work_date: str,
    start_time: str,
    end_time: str,
    **overrides,
) -> dict:
    payload = {
        "placement_id": placement_id,
        "work_date": work_date,
        "start_time": start_time,
        "end_time": end_time,
        "break_minutes": 0,
        "is_school_day": True,
    }
    payload.update(overrides)
    return payload


def void_timesheet_entry_payload(voided_reason: str = "Logged against the wrong shift", **overrides) -> dict:
    payload = {"voided_reason": voided_reason}
    payload.update(overrides)
    return payload


def submit_evaluation_payload(
    rating_technical: int = 4,
    rating_communication: int = 4,
    rating_reliability: int = 4,
    rating_safety: int = 4,
    rating_initiative: int = 4,
    **overrides,
) -> dict:
    payload = {
        "rating_technical": rating_technical,
        "rating_communication": rating_communication,
        "rating_reliability": rating_reliability,
        "rating_safety": rating_safety,
        "rating_initiative": rating_initiative,
    }
    payload.update(overrides)
    return payload


def submit_reflection_payload(
    reflection_text: str = "This cycle I learned to follow the lockout checklist end to end.",
    **overrides,
) -> dict:
    payload = {"reflection_text": reflection_text}
    payload.update(overrides)
    return payload


def reflection_decision_payload(
    decision: str = "ACCEPT", feedback_note: str = "Thorough and specific.", **overrides
) -> dict:
    payload = {"decision": decision, "feedback_note": feedback_note}
    payload.update(overrides)
    return payload


def create_incident_report_payload(
    placement_id: str,
    worksite_id: str,
    occurred_at: str,
    severity: str = "MINOR",
    injury_type: str = "LACERATION",
    **overrides,
) -> dict:
    payload = {
        "placement_id": placement_id,
        "worksite_id": worksite_id,
        "occurred_at": occurred_at,
        "severity": severity,
        "description": "Student reported an injury while working on the line.",
        "injury_type": injury_type,
    }
    payload.update(overrides)
    return payload


def incident_finding_payload(finding: str = "SUBSTANTIATED", **overrides) -> dict:
    payload = {"finding": finding}
    payload.update(overrides)
    return payload


def create_placement_outcome_payload(
    placement_id: str, outcome_type: str = "EMPLOYED_PART_TIME", **overrides
) -> dict:
    payload = {
        "placement_id": placement_id,
        "outcome_type": outcome_type,
        "verification_source": "EMPLOYER_LETTER",
    }
    if outcome_type in ("EMPLOYED_FULL_TIME", "EMPLOYED_PART_TIME", "APPRENTICESHIP"):
        payload["employer_name"] = DEFAULTS["LEGAL_NAME"]
    if outcome_type == "POSTSECONDARY_ENROLLED":
        payload["institution_name"] = "Riverbend Community College"
    payload.update(overrides)
    return payload
