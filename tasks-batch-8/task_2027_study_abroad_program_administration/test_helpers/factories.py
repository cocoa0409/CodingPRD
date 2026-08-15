"""Payload factories — one per entity, input fields only (PRD §3)."""

AGREEMENT_DEFAULTS = {
    "host_institution": "Universite Lyon",
    "country_code": "FR",
    "effective_from": "2026-01-01T00:00:00Z",
    "effective_to": "2028-12-31T23:59:59Z",
    "credit_conversion_factor": 0.75,
    "insurance_required": True,
}

PROGRAM_DEFAULTS = {
    "name": "Lyon Spring 2027",
    "country_code": "FR",
    "host_institution": "Universite Lyon",
    "term": "SPRING",
    "start_date": "2027-01-10T00:00:00Z",
    "end_date": "2027-05-10T00:00:00Z",
    "application_deadline": "2026-11-01T00:00:00Z",
    "capacity": 30,
    "billing_model": "PROGRAM_FEE",
    "program_fee_cents": 1800000,
    "min_gpa": 2.75,
}

STUDENT_DEFAULTS = {
    "full_name": "Test Student",
    "email": "student@uni.edu",
    "gpa": 3.00,
    "conduct_standing": "GOOD_STANDING",
    "aid_award_cents": 0,
}

ADVISORY_DEFAULTS = {
    "country_code": "FR",
    "level": "CAUTION",
    "effective_from": "2027-01-01T00:00:00Z",
    "effective_to": "2027-03-01T00:00:00Z",
}

ENROLLMENT_DEFAULTS = {
    "provider": "GlobalCare",
    "coverage_start_date": "2027-01-01T00:00:00Z",
    "coverage_end_date": "2027-05-31T00:00:00Z",
}

CPA_DEFAULTS = {
    "course_code": "HIST310",
    "course_title": "Modern French History",
    "host_credits": 3,
}

INCIDENT_DEFAULTS = {
    "severity": "HIGH",
    "description": "lost passport",
}


def create_partner_agreement_payload(**overrides) -> dict:
    defaults = dict(AGREEMENT_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_program_payload(partner_agreement_id: str, **overrides) -> dict:
    defaults = dict(PROGRAM_DEFAULTS)
    defaults["partner_agreement_id"] = partner_agreement_id
    defaults.update(overrides)
    # PRD §2.10 tier 4: a HOME_TUITION program must omit program_fee_cents or
    # set it to 0. When the caller flips billing_model to HOME_TUITION without
    # explicitly setting program_fee_cents, drop the inherited PROGRAM_FEE
    # default so the request stays PRD-consistent. An explicit
    # program_fee_cents override is preserved verbatim (validation tests).
    if defaults.get("billing_model") == "HOME_TUITION" and "program_fee_cents" not in overrides:
        defaults.pop("program_fee_cents", None)
    return defaults


def create_student_payload(**overrides) -> dict:
    defaults = dict(STUDENT_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_application_payload(student_id: str, program_id: str, **overrides) -> dict:
    defaults = {"student_id": student_id, "program_id": program_id}
    defaults.update(overrides)
    return defaults


def create_clearance_payload(decision: str, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_course_preapproval_payload(expected_application_version: int, **overrides) -> dict:
    defaults = dict(CPA_DEFAULTS)
    defaults["expected_application_version"] = expected_application_version
    defaults.update(overrides)
    return defaults


def create_review_payload(decision: str, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_revise_payload(host_credits: float, **overrides) -> dict:
    defaults = {"host_credits": host_credits}
    defaults.update(overrides)
    return defaults


def create_travel_advisory_payload(**overrides) -> dict:
    defaults = dict(ADVISORY_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_insurance_enrollment_payload(application_id: str, **overrides) -> dict:
    defaults = dict(ENROLLMENT_DEFAULTS)
    defaults["application_id"] = application_id
    defaults.update(overrides)
    return defaults


def create_lifecycle_payload(action: str, **overrides) -> dict:
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_incident_payload(application_id: str, **overrides) -> dict:
    defaults = dict(INCIDENT_DEFAULTS)
    defaults["application_id"] = application_id
    defaults.update(overrides)
    return defaults


def create_incident_transition_payload(to_state: str, **overrides) -> dict:
    defaults = {"to_state": to_state}
    defaults.update(overrides)
    return defaults


def create_credit_posting_payload(lines: list, **overrides) -> dict:
    defaults = {"lines": lines}
    defaults.update(overrides)
    return defaults


def create_clock_payload(to_iso8601: str, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
