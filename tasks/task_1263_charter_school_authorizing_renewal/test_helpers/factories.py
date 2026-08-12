"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "SCHOOL_NAME": "Test Charter Academy",
    "FOUNDING_GROUP": "FG Test",
    "CYCLE_YEAR": 2027,
    "PROPOSED_GRADES": "K-8",
    "INTERVIEW_START": "2026-05-10T10:00:00Z",
    "INTERVIEW_END": "2026-05-10T11:00:00Z",
    "FRAMEWORK_VERSION": "FW-1",
    "TERM_START": "2027-07-01T00:00:00Z",
    "TERM_END": "2032-06-30T00:00:00Z",
    "FISCAL_YEAR": 2028,
    "ACADEMIC_YEAR": 2028,
    "CAPACITY": 10,
    "GRADE_LEVEL": "K",
    "PLAN_TEXT": "Hire a coach; weekly tutoring",
    "CLOSURE_DATE": "2027-06-30T00:00:00Z",
    "GROUNDS": "Procedural defect in the decision",
}


def create_application_payload(**overrides) -> dict:
    defaults = {
        "school_name": DEFAULTS["SCHOOL_NAME"],
        "founding_group": DEFAULTS["FOUNDING_GROUP"],
        "cycle_year": DEFAULTS["CYCLE_YEAR"],
        "proposed_grades": DEFAULTS["PROPOSED_GRADES"],
    }
    defaults.update(overrides)
    return defaults


def create_score_payload(criterion="ACADEMIC_PLAN", score=90, **overrides) -> dict:
    defaults = {"criterion": criterion, "score": score}
    defaults.update(overrides)
    return defaults


def create_interview_payload(scheduled_start=None, scheduled_end=None,
                             panelist_user_ids=None, **overrides) -> dict:
    defaults = {
        "scheduled_start": scheduled_start or DEFAULTS["INTERVIEW_START"],
        "scheduled_end": scheduled_end or DEFAULTS["INTERVIEW_END"],
        "panelist_user_ids": panelist_user_ids if panelist_user_ids is not None else ["rev_panel_fx"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(expected_school_version, framework_version=None,
                            term_start=None, term_end=None, prior_contract_id=None,
                            **overrides) -> dict:
    defaults = {
        "framework_version": framework_version or DEFAULTS["FRAMEWORK_VERSION"],
        "term_start": term_start or DEFAULTS["TERM_START"],
        "term_end": term_end or DEFAULTS["TERM_END"],
        "expected_school_version": expected_school_version,
    }
    if prior_contract_id is not None:
        defaults["prior_contract_id"] = prior_contract_id
    defaults.update(overrides)
    return defaults


def create_target_payload(domain="ACADEMIC", metric_code="MATH_PROF", target_value=80,
                          floor_value=60, weight=0.5, **overrides) -> dict:
    defaults = {
        "domain": domain,
        "metric_code": metric_code,
        "target_value": target_value,
        "floor_value": floor_value,
        "weight": weight,
    }
    defaults.update(overrides)
    return defaults


def create_monitoring_report_payload(fiscal_year=None, academic_score=90,
                                     financial_score=90, operational_score=90,
                                     **overrides) -> dict:
    defaults = {
        "fiscal_year": fiscal_year if fiscal_year is not None else DEFAULTS["FISCAL_YEAR"],
        "academic_score": academic_score,
        "financial_score": financial_score,
        "operational_score": operational_score,
    }
    defaults.update(overrides)
    return defaults


def create_lottery_payload(academic_year=None, capacity=None, **overrides) -> dict:
    defaults = {
        "academic_year": academic_year if academic_year is not None else DEFAULTS["ACADEMIC_YEAR"],
        "capacity": capacity if capacity is not None else DEFAULTS["CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_lottery_entry_payload(student_ref="stu_1", grade_level=None,
                                 preference_codes=None, **overrides) -> dict:
    defaults = {
        "student_ref": student_ref,
        "grade_level": grade_level or DEFAULTS["GRADE_LEVEL"],
        "preference_codes": preference_codes if preference_codes is not None else [],
    }
    defaults.update(overrides)
    return defaults


def create_intervention_payload(level="NOTICE", domain="COMPLIANCE",
                                reason="Intervention reason", **overrides) -> dict:
    defaults = {"level": level, "domain": domain, "reason": reason}
    defaults.update(overrides)
    return defaults


def create_corrective_plan_payload(expected_intervention_version, plan_text=None,
                                   **overrides) -> dict:
    defaults = {
        "plan_text": plan_text or DEFAULTS["PLAN_TEXT"],
        "expected_intervention_version": expected_intervention_version,
    }
    defaults.update(overrides)
    return defaults


def create_renewal_decision_payload(contract_id, **overrides) -> dict:
    defaults = {"contract_id": contract_id}
    defaults.update(overrides)
    return defaults


def create_closure_plan_payload(reason="VOLUNTARY", closure_date=None, **overrides) -> dict:
    defaults = {
        "reason": reason,
        "closure_date": closure_date or DEFAULTS["CLOSURE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_student_transition_payload(student_ref="stu_close_1", **overrides) -> dict:
    defaults = {"student_ref": student_ref}
    defaults.update(overrides)
    return defaults


def create_fee_invoice_payload(fiscal_year=2026, estimated_enrollment=400,
                               base_per_pupil_cents=800000,
                               qualifying_supplemental_pupils=100, **overrides) -> dict:
    defaults = {
        "fiscal_year": fiscal_year,
        "estimated_enrollment": estimated_enrollment,
        "base_per_pupil_cents": base_per_pupil_cents,
        "qualifying_supplemental_pupils": qualifying_supplemental_pupils,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(target_type, target_id, grounds=None, school_id=None,
                          **overrides) -> dict:
    defaults = {
        "target_type": target_type,
        "target_id": target_id,
        "grounds": grounds or DEFAULTS["GROUNDS"],
    }
    if school_id is not None:
        defaults["school_id"] = school_id
    defaults.update(overrides)
    return defaults
