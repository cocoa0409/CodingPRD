"""Request-payload builders.

Each builder returns the smallest payload the PRD declares as required for the
operation, with every optional input left out unless a caller supplies it via
``**overrides``.  That keeps "defaults applied when optional inputs are
omitted" tests honest.
"""

from typing import Any, Dict, List, Optional

from .constants import CLOCK_DEFAULT


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Clock
# ----------------------------------------------------------------------
def clock_payload(current_utc: str = CLOCK_DEFAULT, **overrides) -> Dict[str, Any]:
    return _merge({"current_utc": current_utc}, overrides)


# ----------------------------------------------------------------------
# Taxonomy
# ----------------------------------------------------------------------
def discipline_payload(
    code: str,
    name: str,
    required_terminal_degree_level: str = "MASTERS",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "code": code,
            "name": name,
            "required_terminal_degree_level": required_terminal_degree_level,
        },
        overrides,
    )


def program_payload(
    name: str,
    discipline_id: str,
    degree_level: str = "BACHELORS",
    qualification_policy: str = "DEGREE_FIELD",
    adequacy_basis: str = "HEADCOUNT",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "name": name,
            "discipline_id": discipline_id,
            "degree_level": degree_level,
            "qualification_policy": qualification_policy,
            "adequacy_basis": adequacy_basis,
        },
        overrides,
    )


def term_payload(
    code: str = "2026FA",
    start_date: str = "2026-09-15",
    end_date: str = "2026-12-20",
    census_date: str = "2026-10-01",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "code": code,
            "start_date": start_date,
            "end_date": end_date,
            "census_date": census_date,
        },
        overrides,
    )


def term_status_payload(to_status: str, **overrides) -> Dict[str, Any]:
    return _merge({"to_status": to_status}, overrides)


# ----------------------------------------------------------------------
# Faculty and credentials
# ----------------------------------------------------------------------
def faculty_payload(
    full_name: str,
    email: str,
    employment_class: str,
    home_program_id: str,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": full_name,
            "email": email,
            "employment_class": employment_class,
            "home_program_id": home_program_id,
        },
        overrides,
    )


def credential_record_payload(
    faculty_member_id: str,
    degree_level: str,
    discipline_id: str,
    conferring_institution: str,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "faculty_member_id": faculty_member_id,
            "degree_level": degree_level,
            "discipline_id": discipline_id,
            "conferring_institution": conferring_institution,
        },
        overrides,
    )


def transcript_payload(transcript_status: str, **overrides) -> Dict[str, Any]:
    return _merge({"transcript_status": transcript_status}, overrides)


def verification_payload(decision: str, **overrides) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def separation_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


# ----------------------------------------------------------------------
# Credential evaluations
# ----------------------------------------------------------------------
def evaluation_payload(
    credential_record_id: str,
    billed_program_id: str,
    evaluator_agency: str = "WES",
    page_count: int = 24,
    service_level: str = "STANDARD",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "credential_record_id": credential_record_id,
            "billed_program_id": billed_program_id,
            "evaluator_agency": evaluator_agency,
            "page_count": page_count,
            "service_level": service_level,
        },
        overrides,
    )


def evaluation_status_payload(to_status: str, **overrides) -> Dict[str, Any]:
    return _merge({"to_status": to_status}, overrides)


def evaluation_completion_payload(
    equivalency_degree_level: str,
    equivalency_discipline_id: str,
    equivalency_verdict: str,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "to_status": "COMPLETED",
            "equivalency_degree_level": equivalency_degree_level,
            "equivalency_discipline_id": equivalency_discipline_id,
            "equivalency_verdict": equivalency_verdict,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Sections and assignments
# ----------------------------------------------------------------------
def section_payload(
    program_id: str,
    term_id: str,
    discipline_id: str,
    course_code: str,
    title: str,
    credit_hours: int = 3,
    course_level: str = "LOWER_DIVISION",
    delivery_mode: str = "IN_PERSON",
    building_code: str = "HALL-A",
    meeting_days: Optional[List[str]] = None,
    meeting_start_minute: int = 540,
    meeting_end_minute: int = 620,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "term_id": term_id,
            "discipline_id": discipline_id,
            "course_code": course_code,
            "title": title,
            "credit_hours": credit_hours,
            "course_level": course_level,
            "delivery_mode": delivery_mode,
            "building_code": building_code,
            "meeting_days": ["MON"] if meeting_days is None else list(meeting_days),
            "meeting_start_minute": meeting_start_minute,
            "meeting_end_minute": meeting_end_minute,
        },
        overrides,
    )


def assignment_payload(
    course_section_id: str,
    faculty_member_id: str,
    expected_section_version: int,
    assignment_role: str = "INSTRUCTOR_OF_RECORD",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "course_section_id": course_section_id,
            "faculty_member_id": faculty_member_id,
            "assignment_role": assignment_role,
            "expected_section_version": expected_section_version,
        },
        overrides,
    )


def remediation_payload(remediation_action: str, **overrides) -> Dict[str, Any]:
    return _merge({"remediation_action": remediation_action}, overrides)


def withdrawal_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


# ----------------------------------------------------------------------
# Tested-experience justifications
# ----------------------------------------------------------------------
def justification_payload(
    course_assignment_id: str,
    documented_years_experience: int,
    industry_certification_level: str,
    alternative_credential_codes: Optional[List[str]] = None,
    supervisor_attestation_on_file: bool = True,
    narrative: str = "Documented professional practice in the section's discipline",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "course_assignment_id": course_assignment_id,
            "narrative": narrative,
            "documented_years_experience": documented_years_experience,
            "industry_certification_level": industry_certification_level,
            "alternative_credential_codes": list(alternative_credential_codes or []),
            "supervisor_attestation_on_file": supervisor_attestation_on_file,
        },
        overrides,
    )


def justification_status_payload(to_status: str, **overrides) -> Dict[str, Any]:
    return _merge({"to_status": to_status}, overrides)


def justification_decision_payload(
    decision: str,
    decision_rationale: str = "Tested experience documented and attested",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {"decision": decision, "decision_rationale": decision_rationale}, overrides
    )


# ----------------------------------------------------------------------
# Rosters
# ----------------------------------------------------------------------
def roster_payload(program_id: str, term_id: str, **overrides) -> Dict[str, Any]:
    return _merge({"program_id": program_id, "term_id": term_id}, overrides)


# ----------------------------------------------------------------------
# Contracts
# ----------------------------------------------------------------------
def contract_payload(
    faculty_member_id: str,
    term_id: str,
    employment_class: str,
    contract_credit_hours: int,
    expected_faculty_version: int,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "faculty_member_id": faculty_member_id,
            "term_id": term_id,
            "employment_class": employment_class,
            "contract_credit_hours": contract_credit_hours,
            "expected_faculty_version": expected_faculty_version,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Professional development
# ----------------------------------------------------------------------
def pd_record_payload(
    faculty_member_id: str,
    discipline_id: str,
    activity_type: str,
    contact_hours: float,
    activity_date: str,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "faculty_member_id": faculty_member_id,
            "discipline_id": discipline_id,
            "activity_type": activity_type,
            "contact_hours": contact_hours,
            "activity_date": activity_date,
        },
        overrides,
    )


def pd_status_payload(to_status: str, **overrides) -> Dict[str, Any]:
    return _merge({"to_status": to_status}, overrides)


# ----------------------------------------------------------------------
# Accreditor reviews
# ----------------------------------------------------------------------
def review_payload(
    program_id: str,
    review_type: str,
    window_start_date: str,
    window_end_date: str,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "review_type": review_type,
            "window_start_date": window_start_date,
            "window_end_date": window_end_date,
        },
        overrides,
    )


def review_status_payload(to_status: str, **overrides) -> Dict[str, Any]:
    return _merge({"to_status": to_status}, overrides)


def findings_payload(finding_count: int, **overrides) -> Dict[str, Any]:
    return _merge({"finding_count": finding_count}, overrides)


def response_payload(response_narrative: str, **overrides) -> Dict[str, Any]:
    return _merge({"response_narrative": response_narrative}, overrides)


# ----------------------------------------------------------------------
# Launch gate
# ----------------------------------------------------------------------
def launch_review_payload(term_id: str, **overrides) -> Dict[str, Any]:
    return _merge({"term_id": term_id}, overrides)


def launch_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)
