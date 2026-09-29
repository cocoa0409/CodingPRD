"""State builders and pytest fixtures.

The harness restarts the server before every individual test, so each test
begins against an empty database.  Everything below therefore builds its state
from scratch through PRD-declared endpoints only; nothing is seeded out of
band.

The builders are layered:

* tier 1 - the logical clock and the discipline taxonomy;
* tier 2 - programs, whose two feature flags drive every downstream number;
* tier 3 - academic terms and their lifecycle;
* tier 4 - faculty members and their credential evidence chains;
* tier 5 - sections, assignments, rosters, contracts, professional
  development and accreditor reviews - the composite states the behavioural
  tests actually assert against.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import CLOCK_DEFAULT
from . import factories as f
from .test_users import (
    TEST_USERS,
    make_instructor_headers,
    make_program_dean_headers,
)

# ======================================================================
# Tier 1 - clock and taxonomy
# ======================================================================


def set_clock(current_utc: str = CLOCK_DEFAULT) -> Dict[str, Any]:
    """PRD 2.4: move the logical clock (SystemAdmin only)."""
    return get_success_data(
        api_client.set_clock(f.clock_payload(current_utc), TEST_USERS["admin"])
    )


def make_discipline(code: str, name: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_discipline(
            f.discipline_payload(code, name, **overrides), TEST_USERS["admin"]
        )
    )


def make_communication_taxonomy() -> Dict[str, Dict[str, Any]]:
    """Communication with two sibling children, Journalism and Public Relations.

    PRD 2.9 makes the sibling pair align at 0.6500 and each child align with
    its parent at 0.7100, which is the shape most qualification tests need.
    """
    comm = make_discipline("09.01", "Communication")
    journ = make_discipline(
        "09.04", "Journalism", parent_discipline_id=comm["id"], min_graduate_credit_hours=18
    )
    pr = make_discipline(
        "09.07",
        "Public Relations",
        parent_discipline_id=comm["id"],
        min_graduate_credit_hours=18,
    )
    return {"comm": comm, "journ": journ, "pr": pr}


# ======================================================================
# Tier 2 - programs
# ======================================================================


def make_program(name: str, discipline_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_program(
            f.program_payload(name, discipline_id, **overrides), TEST_USERS["admin"]
        )
    )


def make_degree_field_program(
    discipline_id: str,
    name: str = "BA Journalism (Degree-Field Policy)",
    **overrides,
) -> Dict[str, Any]:
    defaults = dict(
        degree_level="BACHELORS",
        qualification_policy="DEGREE_FIELD",
        adequacy_basis="HEADCOUNT",
        min_terminal_ratio=0.60,
        credential_budget_cents=500000,
    )
    defaults.update(overrides)
    return make_program(name, discipline_id, **defaults)


def make_coursework_program(
    discipline_id: str,
    name: str = "BA Journalism (Coursework Policy)",
    **overrides,
) -> Dict[str, Any]:
    defaults = dict(
        degree_level="BACHELORS",
        qualification_policy="COURSEWORK_18",
        adequacy_basis="CREDIT_HOUR_COVERAGE",
        min_terminal_ratio=0.60,
        credential_budget_cents=500000,
    )
    defaults.update(overrides)
    return make_program(name, discipline_id, **defaults)


def read_program(program_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(
        api_client.get_program(program_id, headers or TEST_USERS["admin"])
    )


# ======================================================================
# Tier 3 - terms
# ======================================================================


def make_term(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_term(f.term_payload(**overrides), TEST_USERS["registrar"])
    )


def move_term(term_id: str, to_status: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_term_status(
            term_id, f.term_status_payload(to_status), TEST_USERS["registrar"]
        )
    )


def make_open_term(**overrides) -> Dict[str, Any]:
    term = make_term(**overrides)
    return move_term(term["id"], "OPEN")


# ======================================================================
# Tier 4 - faculty members and credential evidence
# ======================================================================


def make_faculty(
    full_name: str, email: str, employment_class: str, home_program_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_faculty_member(
            f.faculty_payload(
                full_name, email, employment_class, home_program_id, **overrides
            ),
            TEST_USERS["registrar"],
        )
    )


def read_faculty(
    faculty_member_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_faculty_member(
            faculty_member_id, headers or TEST_USERS["registrar"]
        )
    )


def file_credential(
    faculty_member_id: str,
    degree_level: str,
    discipline_id: str,
    conferring_institution: str,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_credential_record(
            f.credential_record_payload(
                faculty_member_id,
                degree_level,
                discipline_id,
                conferring_institution,
                **overrides,
            ),
            TEST_USERS["registrar"],
        )
    )


def advance_transcript(record_id: str, transcript_status: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_transcript_status(
            record_id, f.transcript_payload(transcript_status), TEST_USERS["registrar"]
        )
    )


def decide_verification(
    record_id: str, decision: str = "VERIFY", headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.decide_verification(
            record_id,
            f.verification_payload(decision, **overrides),
            headers or TEST_USERS["analyst"],
        )
    )


def make_verified_credential(
    faculty_member_id: str,
    degree_level: str,
    discipline_id: str,
    conferring_institution: str,
    analyst_headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """File a record, receive the official transcript and verify it.

    This is the PRD 3.2 happy path that puts a record into the *official* and
    *eligible* sets used by the PRD 3.4 credential tests.
    """
    record = file_credential(
        faculty_member_id,
        degree_level,
        discipline_id,
        conferring_institution,
        **overrides,
    )
    advance_transcript(record["id"], "OFFICIAL_RECEIVED")
    return decide_verification(record["id"], "VERIFY", analyst_headers)


def make_credentialed_faculty(
    full_name: str,
    email: str,
    employment_class: str,
    home_program_id: str,
    degree_level: str,
    discipline_id: str,
    conferring_institution: str,
    graduate_credit_hours_in_discipline: int = 0,
) -> Dict[str, Any]:
    """A faculty member with one verified domestic degree on file.

    Returns ``{"faculty": ..., "record": ...}`` with the faculty member read
    back after the verification cascade, so the caller sees the settled
    ``dossier_status`` and ``appointment_status``.
    """
    faculty = make_faculty(full_name, email, employment_class, home_program_id)
    record = make_verified_credential(
        faculty["id"],
        degree_level,
        discipline_id,
        conferring_institution,
        graduate_credit_hours_in_discipline=graduate_credit_hours_in_discipline,
    )
    return {"faculty": read_faculty(faculty["id"]), "record": record}


def separate_faculty(faculty_member_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.separate_faculty_member(
            faculty_member_id,
            f.separation_payload(**overrides),
            TEST_USERS["registrar"],
        )
    )


# ======================================================================
# Tier 5 - sections, assignments, rosters, contracts, PD, reviews
# ======================================================================


def make_section(
    program_id: str,
    term_id: str,
    discipline_id: str,
    course_code: str,
    title: str,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_course_section(
            f.section_payload(
                program_id, term_id, discipline_id, course_code, title, **overrides
            ),
            make_program_dean_headers(program_id),
        )
    )


def read_section(section_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(
        api_client.get_course_section(section_id, headers or TEST_USERS["admin"])
    )


def section_version(section_id: str) -> int:
    """PRD 2.7: the section is the concurrency parent for assignment writes."""
    return read_section(section_id)["version"]


def make_assignment(
    section_id: str,
    faculty_member_id: str,
    dean_program_id: str,
    assignment_role: str = "INSTRUCTOR_OF_RECORD",
    expected_section_version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    version = (
        expected_section_version
        if expected_section_version is not None
        else section_version(section_id)
    )
    return get_success_data(
        api_client.create_course_assignment(
            f.assignment_payload(
                section_id,
                faculty_member_id,
                version,
                assignment_role=assignment_role,
                **overrides,
            ),
            make_program_dean_headers(dean_program_id),
        )
    )


def read_assignment(assignment_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(
        api_client.get_course_assignment(assignment_id, headers or TEST_USERS["admin"])
    )


def open_remediation(
    assignment_id: str, dean_program_id: str, remediation_action: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.open_remediation(
            assignment_id,
            f.remediation_payload(remediation_action, **overrides),
            make_program_dean_headers(dean_program_id),
        )
    )


def reverify_assignment(
    assignment_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.reverify_assignment(assignment_id, {}, headers or TEST_USERS["analyst"])
    )


def withdraw_assignment(
    assignment_id: str, dean_program_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.withdraw_assignment(
            assignment_id,
            f.withdrawal_payload(**overrides),
            make_program_dean_headers(dean_program_id),
        )
    )


def make_roster(
    program_id: str, term_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_roster(
            f.roster_payload(program_id, term_id), headers or TEST_USERS["liaison"]
        )
    )


def generate_roster(
    roster_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.generate_roster(roster_id, {}, headers or TEST_USERS["liaison"])
    )


def read_roster(roster_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(
        api_client.get_roster(roster_id, headers or TEST_USERS["liaison"])
    )


def make_generated_roster(
    program_id: str, term_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    roster = make_roster(program_id, term_id, headers)
    return generate_roster(roster["id"], headers)


def certify_roster(
    roster_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.certify_roster(
            roster_id, dict(overrides), headers or TEST_USERS["liaison"]
        )
    )


def make_justification(
    assignment_id: str,
    dean_program_id: str,
    documented_years_experience: int,
    industry_certification_level: str,
    alternative_credential_codes: Optional[List[str]] = None,
    supervisor_attestation_on_file: bool = True,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_justification(
            f.justification_payload(
                assignment_id,
                documented_years_experience,
                industry_certification_level,
                alternative_credential_codes,
                supervisor_attestation_on_file,
                **overrides,
            ),
            make_program_dean_headers(dean_program_id),
        )
    )


def submit_justification(justification_id: str, dean_program_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_justification_status(
            justification_id,
            f.justification_status_payload("SUBMITTED"),
            make_program_dean_headers(dean_program_id),
        )
    )


def review_justification(
    justification_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.review_justification(
            justification_id, {}, headers or TEST_USERS["analyst_2"]
        )
    )


def make_reviewed_justification(
    assignment_id: str,
    dean_program_id: str,
    documented_years_experience: int,
    industry_certification_level: str,
    alternative_credential_codes: Optional[List[str]] = None,
    supervisor_attestation_on_file: bool = True,
    reviewer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Drive a justification DRAFT -> SUBMITTED -> UNDER_REVIEW."""
    just = make_justification(
        assignment_id,
        dean_program_id,
        documented_years_experience,
        industry_certification_level,
        alternative_credential_codes,
        supervisor_attestation_on_file,
    )
    submit_justification(just["id"], dean_program_id)
    return review_justification(just["id"], reviewer_headers)


def make_contract(
    faculty_member_id: str,
    term_id: str,
    employment_class: str,
    contract_credit_hours: int,
    dean_program_id: str,
    expected_faculty_version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    version = (
        expected_faculty_version
        if expected_faculty_version is not None
        else read_faculty(faculty_member_id)["version"]
    )
    return get_success_data(
        api_client.create_contract(
            f.contract_payload(
                faculty_member_id,
                term_id,
                employment_class,
                contract_credit_hours,
                version,
                **overrides,
            ),
            make_program_dean_headers(dean_program_id),
        )
    )


def countersign_contract(contract_id: str, faculty_member_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.countersign_contract(
            contract_id, {}, make_instructor_headers(faculty_member_id)
        )
    )


def make_pd_record(
    faculty_member_id: str,
    discipline_id: str,
    activity_type: str,
    contact_hours: float,
    activity_date: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_pd_record(
            f.pd_record_payload(
                faculty_member_id,
                discipline_id,
                activity_type,
                contact_hours,
                activity_date,
            ),
            headers or TEST_USERS["registrar"],
        )
    )


def set_pd_status(pd_record_id: str, to_status: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_pd_record_status(
            pd_record_id, f.pd_status_payload(to_status), TEST_USERS["analyst"]
        )
    )


def make_verified_pd_record(
    faculty_member_id: str,
    discipline_id: str,
    activity_type: str,
    contact_hours: float,
    activity_date: str,
) -> Dict[str, Any]:
    record = make_pd_record(
        faculty_member_id, discipline_id, activity_type, contact_hours, activity_date
    )
    return set_pd_status(record["id"], "VERIFIED")


def make_review(
    program_id: str, review_type: str, window_start_date: str, window_end_date: str
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_review(
            f.review_payload(
                program_id, review_type, window_start_date, window_end_date
            ),
            TEST_USERS["reviewer"],
        )
    )


def move_review(review_id: str, to_status: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_review_status(
            review_id, f.review_status_payload(to_status, **overrides), TEST_USERS["reviewer"]
        )
    )


def make_started_review(
    program_id: str,
    review_type: str,
    window_start_date: str = "2026-07-25",
    window_end_date: str = "2026-08-10",
) -> Dict[str, Any]:
    review = make_review(program_id, review_type, window_start_date, window_end_date)
    return move_review(review["id"], "IN_PROGRESS")


def issue_findings(review_id: str, finding_count: int, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.issue_findings(
            review_id,
            f.findings_payload(finding_count, **overrides),
            TEST_USERS["reviewer"],
        )
    )


def submit_response(review_id: str, response_narrative: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_response(
            review_id, f.response_payload(response_narrative), TEST_USERS["liaison"]
        )
    )


def submit_launch_review(program_id: str, term_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_launch_review(
            program_id,
            f.launch_review_payload(term_id),
            make_program_dean_headers(program_id),
        )
    )


def decide_launch(program_id: str, decision: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.decide_launch(
            program_id,
            f.launch_decision_payload(decision, **overrides),
            TEST_USERS["liaison"],
        )
    )


def total_count(response) -> int:
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


# ======================================================================
# Composite pytest fixtures
# ======================================================================


class Env:
    """The reference data almost every behavioural test needs.

    Two sibling programs over the same Journalism discipline, one under each
    ``qualification_policy`` / ``adequacy_basis`` pairing, so the divergence of
    the two calculation variants is always reachable.
    """

    def __init__(self, taxonomy: Dict[str, Any], programs: Dict[str, Any], term: Dict[str, Any]):
        self.comm = taxonomy["comm"]
        self.journ = taxonomy["journ"]
        self.pr = taxonomy["pr"]
        self.comm_id = self.comm["id"]
        self.journ_id = self.journ["id"]
        self.pr_id = self.pr["id"]
        self.prog_df = programs["degree_field"]
        self.prog_cw = programs["coursework"]
        self.prog_df_id = self.prog_df["id"]
        self.prog_cw_id = self.prog_cw["id"]
        self.term = term
        self.term_id = term["id"]

    @property
    def dean_df(self) -> Dict[str, str]:
        return make_program_dean_headers(self.prog_df_id)

    @property
    def dean_cw(self) -> Dict[str, str]:
        return make_program_dean_headers(self.prog_cw_id)


def build_env(open_term: bool = True) -> Env:
    set_clock()
    taxonomy = make_communication_taxonomy()
    programs = {
        "degree_field": make_degree_field_program(taxonomy["journ"]["id"]),
        "coursework": make_coursework_program(taxonomy["journ"]["id"]),
    }
    term = make_open_term() if open_term else make_term()
    return Env(taxonomy, programs, term)


@pytest.fixture
def planning_env() -> Env:
    """Clock, taxonomy, both programs, and a term still in ``PLANNING``."""
    return build_env(open_term=False)


@pytest.fixture
def env() -> Env:
    """Clock, taxonomy, both programs, and an ``OPEN`` term."""
    return build_env(open_term=True)
