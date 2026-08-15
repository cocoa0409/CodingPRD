"""Write-side guards: role authorization, resource ownership, segregation of
duties, and optimistic concurrency control on the two OCC-guarded endpoints.
"""
from test_helpers import (
    ApiErrorId,
    SECOND_PROPOSER_ID,
    advance_through_committee,
    create_department,
    create_new_course_proposal,
    create_submitted_new_course_proposal,
    create_term,
    get_proposal,
    get_term,
    make_chair_headers,
    make_committee_headers,
    make_proposer_headers,
    make_registrar_headers,
    validate_error,
    validate_success,
)


def test_proposer_cannot_post_decisions(api):
    """PRD §2.1: "A request whose role is not listed in the target endpoint's
    authorized role set is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: the decisions endpoint authorizes `DepartmentChair,
    CurriculumCommittee, FacultySenate, Registrar` — no FacultyProposer.

    Design: Corner/rbac/proposer_cannot_post_decisions
    """
    dept = create_department()
    term = create_term()
    proposal = create_submitted_new_course_proposal(dept["id"], term["id"],
                                                    "450")

    resp = api.post_decision(proposal["id"], {"action": "APPROVE"},
                             make_proposer_headers("fac-001"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_proposal(proposal["id"])["status"] == "DEPT_REVIEW"


def test_proposer_cannot_edit_others_proposal(api):
    """PRD §3.3: "While a proposal sits in `DRAFT` or `RETURNED`, its author
    may revise the proposed payload — the subject code, number, title, credit
    and workload hours, outcomes, justification, requisites, declared cohorts,
    requested term, and even the sponsoring department."
    PRD §2.8: "fifth, resource-level ownership (`ERR_NOT_RESOURCE_OWNER`)".

    Design: Corner/rbac/proposer_cannot_edit_others_proposal
    """
    dept = create_department()
    term = create_term()
    proposal = create_new_course_proposal(dept["id"], term["id"], "450",
                                          proposer_id="fac-001")

    resp = api.update_proposal(
        proposal["id"],
        {"expected_proposal_version": proposal["version"],
         "proposed_title": "Hijacked"},
        make_proposer_headers(SECOND_PROPOSER_ID))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert get_proposal(proposal["id"])["proposed_title"] == "Compilers"


def test_chair_cannot_decide_other_department(api):
    """PRD §3.5: "Approval at the department stage requires an additional
    ownership check: the acting chair's `X-User-ID` must equal the proposal's
    `proposer_department_id`, otherwise `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/chair_cannot_decide_other_department
    """
    dept_cs = create_department()
    dept_math = create_department(dept_name="Mathematics",
                                  subject_codes=["MATH"], college="Sciences")
    term = create_term()
    proposal = create_submitted_new_course_proposal(dept_cs["id"], term["id"],
                                                    "450")

    resp = api.post_decision(proposal["id"], {"action": "APPROVE"},
                             make_chair_headers(dept_math["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert get_proposal(proposal["id"])["status"] == "DEPT_REVIEW"


def test_committee_cannot_approve_at_dept_stage(api):
    """PRD §3.5: "From `DEPT_REVIEW` onward, a proposal advances through a
    fixed approval chain, each stage gated to its own role class:
    `DepartmentChair` decides at `DEPT_REVIEW`, `CurriculumCommittee` at
    `COMMITTEE_REVIEW`, `FacultySenate` at `SENATE_REVIEW`, and `Registrar` at
    `REGISTRAR_REVIEW`. A role listed on the decisions endpoint but mismatched
    to the proposal's current stage is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/committee_cannot_approve_at_dept_stage
    """
    dept = create_department()
    term = create_term()
    proposal = create_submitted_new_course_proposal(dept["id"], term["id"],
                                                    "450")

    resp = api.post_decision(proposal["id"], {"action": "APPROVE"},
                             make_committee_headers())
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_proposal(proposal["id"])["status"] == "DEPT_REVIEW"


def test_proposer_self_approval_rejected(api):
    """PRD §3.5: "**Segregation of duties** applies to every approve, return,
    and reject decision at every stage: the acting user's `X-User-ID` must not
    equal the proposal's `proposer_id` under raw string equality, and a
    violation is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`."

    Design: Corner/rbac/proposer_self_approval_rejected
    """
    dept = create_department()
    term = create_term()
    proposal = create_submitted_new_course_proposal(dept["id"], term["id"],
                                                    "450", proposer_id="fac-001")
    advance_through_committee(proposal["id"], dept["id"])

    # A registrar operator whose X-User-ID happens to equal the proposer_id.
    resp = api.post_decision(
        proposal["id"],
        {"action": "APPROVE", "effective_term_id": term["id"]},
        make_registrar_headers("fac-001"))
    validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)
    assert get_proposal(proposal["id"])["status"] == "REGISTRAR_REVIEW"


def test_proposal_update_stale_version_rejected(api):
    """PRD §2.6: "Editing a draft or returned proposal requires the request to
    carry `expected_proposal_version`, holding the value of the proposal's
    `version` the client last observed. If the proposal's current `version` has
    advanced beyond the supplied value, the edit is rejected with
    `ERR_STALE_VERSION` (HTTP 412), preventing the client from silently
    overwriting a document it has not observed."

    Design: Corner/cross_cutting_complexity_layers/proposal_update_stale_version_rejected
    """
    dept = create_department()
    term = create_term()
    proposal = create_new_course_proposal(dept["id"], term["id"], "450",
                                          proposer_id="fac-001")
    observed_version = proposal["version"]

    first = api.update_proposal(
        proposal["id"],
        {"expected_proposal_version": observed_version,
         "proposed_title": "Compilers (revised)"},
        make_proposer_headers("fac-001"))
    data = validate_success(first)
    assert data["version"] == observed_version + 1, (
        "the first writer advances the version")

    replay = api.update_proposal(
        proposal["id"],
        {"expected_proposal_version": observed_version,
         "proposed_title": "Hijacked"},
        make_proposer_headers("fac-001"))
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    assert get_proposal(proposal["id"])["proposed_title"] == \
        "Compilers (revised)"


def test_term_update_stale_version_rejected(api):
    """PRD §2.6: "Editing a term's dates requires the request to carry
    `expected_term_version`, holding the term's last-observed `version`. A
    mismatch against the term's current `version` is likewise rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/term_update_stale_version_rejected
    """
    term = create_term()
    observed_version = term["version"]

    first = api.patch_term(
        term["id"],
        {"expected_term_version": observed_version,
         "proposal_freeze_at": "2026-10-05T00:00:00Z"},
        make_registrar_headers())
    data = validate_success(first)
    assert data["version"] == observed_version + 1

    replay = api.patch_term(
        term["id"],
        {"expected_term_version": observed_version,
         "catalog_freeze_at": "2027-01-12T00:00:00Z"},
        make_registrar_headers())
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    assert get_term(term["id"])["catalog_freeze_at"] == "2027-01-10T00:00:00Z"
