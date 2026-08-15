"""Composite setup helpers for the tenure & promotion review domain.

The test runner restarts the API server before every individual test, so every
fixture builds its preconditions from scratch through the public API only.

Versioning note (PRD §2.6, §2.11): dossier-item and invitation creation carry
`expected_case_version`, and the case version advances on many lifecycle
events. Helpers that create those child resources always re-read the case
version immediately before the write, so fixtures never depend on absolute
version arithmetic.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories
from .api_client import api_client
from .constants import (
    CLOCK_STARTUP_DEFAULT,
    REVIEW_WINDOW_END,
    REVIEW_WINDOW_START,
    SERVICE_END,
    SERVICE_START,
    TERM_END,
    TERM_START,
)
from .test_users import (
    TEST_USERS,
    make_candidate_headers,
    make_committee_chair_headers,
    make_committee_voter_headers,
    make_external_reviewer_headers,
)

READER = TEST_USERS["reader_headers"]
PO_CREATOR = TEST_USERS["provost_creator_headers"]
PO_DECIDER = TEST_USERS["provost_decider_headers"]
APPEAL_OFFICER = TEST_USERS["appeal_officer_headers"]
RECORDS_OFFICER = TEST_USERS["records_officer_headers"]
SYSTEM_ADMIN = TEST_USERS["system_admin_headers"]


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601: str = CLOCK_STARTUP_DEFAULT) -> dict:
    return get_success_data(
        api_client.set_clock(factories.set_clock_payload(to_iso8601=to_iso8601), SYSTEM_ADMIN)
    )


# ---------------------------------------------------------------------------
# Candidates and cases (PRD §3.1)
# ---------------------------------------------------------------------------

def register_candidate(
    employee_id: str,
    full_name: str = "Test Candidate",
    department: str = "CS",
    college: str = "ENG",
    tenure_clock_start: str = "2020-08-01",
) -> dict:
    payload = factories.create_candidate_payload(
        full_name=full_name,
        employee_id=employee_id,
        department=department,
        college=college,
        tenure_clock_start=tenure_clock_start,
    )
    return get_success_data(api_client.create_candidate(payload, PO_CREATOR), 201)


def open_case(
    candidate_id: str,
    clock_policy: str = "ANNIVERSARY",
    waiver_signed=None,
    review_cycle: str = "2026-2027",
    target_rank: str = "ASSOCIATE_PROFESSOR",
    seeking_tenure: bool = True,
    creator_headers=None,
) -> dict:
    payload = factories.create_case_payload(
        candidate_id=candidate_id,
        review_cycle=review_cycle,
        target_rank=target_rank,
        seeking_tenure=seeking_tenure,
        clock_policy=clock_policy,
    )
    if waiver_signed is not None:
        payload["waiver_signed"] = waiver_signed
    return get_success_data(
        api_client.create_case(payload, creator_headers or PO_CREATOR), 201
    )


def read_case(case_id: str) -> dict:
    return get_success_data(api_client.get_case(case_id, READER))


def read_case_version(case_id: str) -> int:
    return read_case(case_id)["version"]


def read_candidate(candidate_id: str) -> dict:
    return get_success_data(api_client.get_candidate(candidate_id, READER))


# ---------------------------------------------------------------------------
# Dossier items (PRD §3.2)
# ---------------------------------------------------------------------------

def add_dossier_item(
    case_id: str,
    candidate_id: str,
    category: str,
    title: str,
    page_count: int = 10,
    is_peer_reviewed=None,
    supersedes_item_id=None,
) -> dict:
    """Create a DRAFT dossier item; reads the current case version first (OCC)."""
    payload = factories.create_dossier_item_payload(
        case_id=case_id,
        category=category,
        title=title,
        page_count=page_count,
        expected_case_version=read_case_version(case_id),
    )
    if is_peer_reviewed is not None:
        payload["is_peer_reviewed"] = is_peer_reviewed
    if supersedes_item_id is not None:
        payload["supersedes_item_id"] = supersedes_item_id
    return get_success_data(
        api_client.create_dossier_item(payload, make_candidate_headers(candidate_id)), 201
    )


def submit_dossier_item(item_id: str, candidate_id: str) -> dict:
    return get_success_data(
        api_client.submit_dossier_item(item_id, make_candidate_headers(candidate_id))
    )


def build_dossier(case_id: str, candidate_id: str, spec: list) -> list:
    """Create dossier items from a spec list of dicts and submit those whose
    `submit` key is not False. Spec keys: category, title, page_count,
    is_peer_reviewed, supersedes_item_id, submit."""
    items = []
    for entry in spec:
        item = add_dossier_item(
            case_id,
            candidate_id,
            category=entry["category"],
            title=entry["title"],
            page_count=entry.get("page_count", 10),
            is_peer_reviewed=entry.get("is_peer_reviewed"),
        )
        if entry.get("submit", True):
            item = submit_dossier_item(item["id"], candidate_id)
        items.append(item)
    return items


def build_standard_dossier(case_id: str, candidate_id: str) -> list:
    """The minimal complete dossier: 2 TEACHING + 3 RESEARCH (one peer-reviewed)
    + 1 SERVICE, all SUBMITTED (PRD §3.2 completeness minima met exactly)."""
    return build_dossier(
        case_id,
        candidate_id,
        [
            {"category": "TEACHING", "title": "T1", "page_count": 10},
            {"category": "TEACHING", "title": "T2", "page_count": 10},
            {"category": "RESEARCH", "title": "R1", "page_count": 12, "is_peer_reviewed": True},
            {"category": "RESEARCH", "title": "R2", "page_count": 12},
            {"category": "RESEARCH", "title": "R3", "page_count": 12},
            {"category": "SERVICE", "title": "S1", "page_count": 5},
        ],
    )


def submit_dossier(case_id: str, candidate_id: str) -> dict:
    return get_success_data(
        api_client.submit_dossier(case_id, make_candidate_headers(candidate_id))
    )


# ---------------------------------------------------------------------------
# Composite: case in EXTERNAL_REVIEW (PRD §3.2)
# ---------------------------------------------------------------------------

def setup_external_review_case(
    employee_id: str,
    full_name: str = "Test Candidate",
    department: str = "CS",
    college: str = "ENG",
    clock_policy: str = "ANNIVERSARY",
    waiver_signed=True,
    dossier_spec=None,
    reset_clock: bool = True,
) -> dict:
    """Candidate + case + complete dossier + submit-dossier.

    Returns {"candidate", "case", "items"} with the case read after submission.
    """
    if reset_clock:
        set_logical_clock()
    candidate = register_candidate(
        employee_id, full_name=full_name, department=department, college=college
    )
    case = open_case(
        candidate["id"], clock_policy=clock_policy, waiver_signed=waiver_signed
    )
    items = build_dossier(
        case["id"], candidate["id"], dossier_spec or []
    ) if dossier_spec is not None else build_standard_dossier(case["id"], candidate["id"])
    submit_dossier(case["id"], candidate["id"])
    return {
        "candidate": candidate,
        "case": read_case(case["id"]),
        "items": items,
    }


# ---------------------------------------------------------------------------
# External reviewers and invitations (PRD §3.4)
# ---------------------------------------------------------------------------

def register_reviewer(
    full_name: str,
    email: str,
    institution: str = "MIT",
    expertise_area: str = "CS",
) -> dict:
    payload = factories.create_reviewer_payload(
        full_name=full_name,
        institution=institution,
        email=email,
        expertise_area=expertise_area,
    )
    return get_success_data(api_client.create_reviewer(payload, PO_CREATOR), 201)


def invite_reviewer(
    case_id: str,
    reviewer_id: str,
    review_window_start: str = REVIEW_WINDOW_START,
    review_window_end: str = REVIEW_WINDOW_END,
) -> dict:
    """Solicit a reviewer; reads the current case version first (OCC, PRD §2.11)."""
    payload = factories.create_invitation_payload(
        case_id=case_id,
        reviewer_id=reviewer_id,
        review_window_start=review_window_start,
        review_window_end=review_window_end,
        expected_case_version=read_case_version(case_id),
    )
    return get_success_data(api_client.create_invitation(payload, PO_CREATOR), 201)


def accept_invitation(invitation_id: str, reviewer_id: str) -> dict:
    return get_success_data(
        api_client.accept_invitation(
            invitation_id, make_external_reviewer_headers(reviewer_id)
        )
    )


def decline_invitation(invitation_id: str, reviewer_id: str) -> dict:
    return get_success_data(
        api_client.decline_invitation(
            invitation_id, make_external_reviewer_headers(reviewer_id)
        )
    )


def submit_letter(invitation_id: str, reviewer_id: str, letter_text: str = "External letter.") -> dict:
    return get_success_data(
        api_client.submit_letter(
            invitation_id,
            factories.submit_letter_payload(letter_text=letter_text),
            make_external_reviewer_headers(reviewer_id),
        )
    )


def invite_and_collect_letter(
    case_id: str,
    full_name: str,
    email: str,
    institution: str = "MIT",
    letter_text: str = "External letter.",
) -> dict:
    """Register a reviewer, solicit, accept, and submit the letter."""
    reviewer = register_reviewer(full_name, email, institution=institution)
    invitation = invite_reviewer(case_id, reviewer["id"])
    accept_invitation(invitation["id"], reviewer["id"])
    invitation = submit_letter(invitation["id"], reviewer["id"], letter_text=letter_text)
    return {"reviewer": reviewer, "invitation": invitation}


def read_invitation(invitation_id: str) -> dict:
    return get_success_data(api_client.get_invitation(invitation_id, READER))


# ---------------------------------------------------------------------------
# Mid-tenure reviews (PRD §3.3)
# ---------------------------------------------------------------------------

def create_midterm(case_id: str, review_year: int = 3) -> dict:
    payload = factories.create_midterm_review_payload(case_id=case_id, review_year=review_year)
    return get_success_data(api_client.create_midterm_review(payload, PO_CREATOR), 201)


def complete_midterm(case_id: str, outcome: str = "SATISFACTORY", review_year: int = 3) -> dict:
    review = create_midterm(case_id, review_year=review_year)
    return get_success_data(
        api_client.complete_midterm_review(
            review["id"], factories.complete_midterm_payload(outcome=outcome), PO_CREATOR
        )
    )


# ---------------------------------------------------------------------------
# Committees and members (PRD §3.5)
# ---------------------------------------------------------------------------

def create_committee(
    level: str,
    academic_unit: str,
    pass_rule: str = "STRICT_MAJORITY_OF_CAST",
    term_start: str = TERM_START,
    term_end: str = TERM_END,
    quorum_fraction=None,
) -> dict:
    payload = factories.create_committee_payload(
        level=level,
        academic_unit=academic_unit,
        term_start=term_start,
        term_end=term_end,
        pass_rule=pass_rule,
    )
    if quorum_fraction is not None:
        payload["quorum_fraction"] = quorum_fraction
    return get_success_data(api_client.create_committee(payload, PO_CREATOR), 201)


def add_member(
    committee_id: str,
    full_name: str,
    email: str,
    role_in_committee=None,
    service_start: str = SERVICE_START,
    service_end: str = SERVICE_END,
) -> dict:
    payload = factories.create_member_payload(
        committee_id=committee_id,
        full_name=full_name,
        email=email,
        service_start=service_start,
        service_end=service_end,
    )
    if role_in_committee is not None:
        payload["role_in_committee"] = role_in_committee
    return get_success_data(api_client.create_member(payload, PO_CREATOR), 201)


def build_committee(
    level: str,
    academic_unit: str,
    member_count: int,
    pass_rule: str = "STRICT_MAJORITY_OF_CAST",
    email_prefix: str = "m",
    term_start: str = TERM_START,
    term_end: str = TERM_END,
    quorum_fraction=None,
) -> dict:
    """Committee with one active CHAIR plus `member_count` plain members.

    Returns {"committee", "chair", "members"}.
    """
    committee = create_committee(
        level,
        academic_unit,
        pass_rule=pass_rule,
        term_start=term_start,
        term_end=term_end,
        quorum_fraction=quorum_fraction,
    )
    chair = add_member(
        committee["id"],
        f"Chair {email_prefix}",
        f"chair_{email_prefix}@u.edu",
        role_in_committee="CHAIR",
    )
    members = [
        add_member(committee["id"], f"Member {email_prefix}{i}", f"{email_prefix}{i}@u.edu")
        for i in range(1, member_count + 1)
    ]
    return {"committee": committee, "chair": chair, "members": members}


# ---------------------------------------------------------------------------
# Review rounds and ballots (PRD §3.5, §3.6)
# ---------------------------------------------------------------------------

def list_case_rounds(case_id: str, level=None) -> list:
    params = {"case_id": case_id}
    if level is not None:
        params["level"] = level
    data, _meta = validate_paginated(api_client.list_rounds(READER, params))
    return data


def latest_round(case_id: str, level=None) -> dict:
    """Rounds list is created_at-ascending (PRD §2.3); the latest is last."""
    rounds = list_case_rounds(case_id, level=level)
    assert rounds, f"No rounds found for case {case_id} (level={level})"
    return rounds[-1]


def read_round(round_id: str) -> dict:
    return get_success_data(api_client.get_round(round_id, READER))


def open_round(round_id: str, chair_id: str) -> dict:
    return get_success_data(
        api_client.open_round(round_id, make_committee_chair_headers(chair_id))
    )


def cast_ballot(round_id: str, member_id: str, ballot: str) -> dict:
    payload = factories.create_vote_payload(round_id=round_id, ballot=ballot)
    return get_success_data(
        api_client.create_vote(payload, make_committee_voter_headers(member_id)), 201
    )


def close_voting(round_id: str, chair_id: str) -> dict:
    return get_success_data(
        api_client.close_voting(round_id, make_committee_chair_headers(chair_id))
    )


def certify_round(
    round_id: str,
    chair_id: str,
    recommendation: str = "SUPPORT",
    letter_text: str = "Committee letter.",
) -> dict:
    return get_success_data(
        api_client.certify_round(
            round_id,
            factories.certify_round_payload(
                recommendation=recommendation, letter_text=letter_text
            ),
            make_committee_chair_headers(chair_id),
        )
    )


def run_round_to_certified(
    case_id: str,
    level: str,
    chair_id: str,
    ballots: list,
    recommendation: str = "SUPPORT",
) -> dict:
    """Open the case's latest round at `level`, cast [(member_id, ballot), ...],
    close voting, and certify. Returns the certified round."""
    round_id = latest_round(case_id, level=level)["id"]
    open_round(round_id, chair_id)
    for member_id, ballot in ballots:
        cast_ballot(round_id, member_id, ballot)
    close_voting(round_id, chair_id)
    return certify_round(round_id, chair_id, recommendation=recommendation)


def advance_case(case_id: str) -> dict:
    return get_success_data(api_client.advance_stage(case_id, PO_CREATOR))


def close_solicitation(case_id: str) -> dict:
    return get_success_data(api_client.close_solicitation(case_id, PO_CREATOR))


# ---------------------------------------------------------------------------
# Composite: case at DEPT_COMMITTEE with an open round ready (PRD §3.4/§3.5)
# ---------------------------------------------------------------------------

def setup_solicited_case(
    employee_id: str,
    letter_count: int = 3,
    midterm_outcome="SATISFACTORY",
    with_midterm: bool = True,
    department: str = "CS",
    college: str = "ENG",
    waiver_signed=True,
    email_prefix: str = "rev",
) -> dict:
    """Case in EXTERNAL_REVIEW with `letter_count` letters received and
    (optionally) a completed mid-tenure review."""
    ctx = setup_external_review_case(
        employee_id, department=department, college=college, waiver_signed=waiver_signed
    )
    case_id = ctx["case"]["id"]
    invitations = [
        invite_and_collect_letter(
            case_id, f"Rev {email_prefix}{i}", f"{email_prefix}{i}@ext{i}.edu"
        )["invitation"]
        for i in range(1, letter_count + 1)
    ]
    ctx["invitations"] = invitations
    if with_midterm:
        ctx["midterm"] = complete_midterm(case_id, outcome=midterm_outcome)
    ctx["case"] = read_case(case_id)
    return ctx


def setup_department_stage_case(
    employee_id: str,
    member_count: int = 3,
    pass_rule: str = "STRICT_MAJORITY_OF_CAST",
    department: str = "CS",
    college: str = "ENG",
    letter_count: int = 3,
    midterm_outcome="SATISFACTORY",
    waiver_signed=True,
    email_prefix: str = "d",
    quorum_fraction=None,
) -> dict:
    """Case driven to DEPT_COMMITTEE: letters + midterm + committee + close.

    Returns the solicited-case ctx plus {"committee_ctx", "round"} where the
    round is the freshly created SCHEDULED department round.
    """
    ctx = setup_solicited_case(
        employee_id,
        letter_count=letter_count,
        midterm_outcome=midterm_outcome,
        department=department,
        college=college,
        waiver_signed=waiver_signed,
        email_prefix=f"r{email_prefix}",
    )
    case_id = ctx["case"]["id"]
    committee_ctx = build_committee(
        "DEPARTMENT",
        department,
        member_count,
        pass_rule=pass_rule,
        email_prefix=f"c{email_prefix}",
        quorum_fraction=quorum_fraction,
    )
    close_solicitation(case_id)
    ctx["committee_ctx"] = committee_ctx
    ctx["round"] = latest_round(case_id, level="DEPARTMENT")
    ctx["case"] = read_case(case_id)
    return ctx


# ---------------------------------------------------------------------------
# Composite: full three-level committee ladder (PRD §3.6)
# ---------------------------------------------------------------------------

def setup_committee_ladder(
    employee_id: str,
    level_specs: dict,
    department: str = "CS",
    college: str = "ENG",
    waiver_signed=True,
    email_prefix: str = "l",
) -> dict:
    """Drive a case through DEPARTMENT -> COLLEGE -> UNIVERSITY and certify
    every level, stopping right after the university certification (the case
    is still UNIVERSITY_COMMITTEE; the final advance is left to the caller).

    level_specs maps each of "DEPARTMENT", "COLLEGE", "UNIVERSITY" to
    {"member_count": int, "ballots": [ballot, ...], "pass_rule": str}.
    Ballots are cast by the plain members in order; the chair stays silent.
    """
    ctx = setup_solicited_case(
        employee_id,
        letter_count=3,
        department=department,
        college=college,
        waiver_signed=waiver_signed,
        email_prefix=f"r{email_prefix}",
    )
    case_id = ctx["case"]["id"]
    committees = {}
    for level, unit in (
        ("DEPARTMENT", department),
        ("COLLEGE", college),
        ("UNIVERSITY", "UNIVERSITY"),
    ):
        spec = level_specs[level]
        committees[level] = build_committee(
            level,
            unit,
            spec["member_count"],
            pass_rule=spec.get("pass_rule", "STRICT_MAJORITY_OF_CAST"),
            email_prefix=f"{level[0]}{email_prefix}",
        )
    close_solicitation(case_id)
    rounds = {}
    for level in ("DEPARTMENT", "COLLEGE"):
        spec = level_specs[level]
        members = committees[level]["members"]
        ballots = [(members[i]["id"], b) for i, b in enumerate(spec["ballots"])]
        rounds[level] = run_round_to_certified(
            case_id,
            level,
            committees[level]["chair"]["id"],
            ballots,
            recommendation=spec.get("recommendation", "SUPPORT"),
        )
        advance_case(case_id)
    spec = level_specs["UNIVERSITY"]
    members = committees["UNIVERSITY"]["members"]
    ballots = [(members[i]["id"], b) for i, b in enumerate(spec["ballots"])]
    rounds["UNIVERSITY"] = run_round_to_certified(
        case_id,
        "UNIVERSITY",
        committees["UNIVERSITY"]["chair"]["id"],
        ballots,
        recommendation=spec.get("recommendation", "SUPPORT"),
    )
    ctx["committees"] = committees
    ctx["rounds"] = rounds
    ctx["case"] = read_case(case_id)
    return ctx


def single_yes_ladder_specs() -> dict:
    """Minimal electorate at every level: 1 member + chair, single YES ballot."""
    return {
        level: {"member_count": 1, "ballots": ["YES"]}
        for level in ("DEPARTMENT", "COLLEGE", "UNIVERSITY")
    }


# ---------------------------------------------------------------------------
# Decisions, notification, appeals (PRD §3.7, §3.8)
# ---------------------------------------------------------------------------

def record_decision(
    case_id: str,
    decision: str,
    rationale_text: str = "Decision rationale.",
    override_rationale=None,
    recorder_headers=None,
) -> dict:
    payload = factories.create_decision_payload(
        case_id=case_id, decision=decision, rationale_text=rationale_text
    )
    if override_rationale is not None:
        payload["override_rationale"] = override_rationale
    return get_success_data(
        api_client.create_decision(payload, recorder_headers or PO_DECIDER), 201
    )


def setup_provost_review_case(
    employee_id: str,
    level_specs=None,
    department: str = "CS",
    college: str = "ENG",
    email_prefix: str = "p",
) -> dict:
    """Full committee ladder plus the final advance into PROVOST_REVIEW."""
    ctx = setup_committee_ladder(
        employee_id,
        level_specs or single_yes_ladder_specs(),
        department=department,
        college=college,
        email_prefix=email_prefix,
    )
    ctx["case"] = advance_case(ctx["case"]["id"])
    return ctx


def setup_decided_case(
    employee_id: str,
    decision: str = "GRANT_TENURE",
    level_specs=None,
    department: str = "CS",
    college: str = "ENG",
    email_prefix: str = "p",
) -> dict:
    """Case through PROVOST_REVIEW with a RECORDED decision (independent
    recording officer, per the decision SoD rule)."""
    ctx = setup_provost_review_case(
        employee_id,
        level_specs=level_specs,
        department=department,
        college=college,
        email_prefix=email_prefix,
    )
    ctx["decision"] = record_decision(ctx["case"]["id"], decision)
    ctx["case"] = read_case(ctx["case"]["id"])
    return ctx


def setup_notified_case(
    employee_id: str,
    decision: str = "DENY",
    level_specs=None,
    department: str = "CS",
    college: str = "ENG",
    email_prefix: str = "p",
) -> dict:
    """Case through DECIDED and notified the same clock day."""
    ctx = setup_decided_case(
        employee_id,
        decision=decision,
        level_specs=level_specs,
        department=department,
        college=college,
        email_prefix=email_prefix,
    )
    get_success_data(api_client.notify_case(ctx["case"]["id"], PO_CREATOR))
    ctx["decision"] = get_success_data(
        api_client.get_decision(ctx["decision"]["id"], READER)
    )
    ctx["case"] = read_case(ctx["case"]["id"])
    return ctx


def file_appeal(case_id: str, candidate_id: str, grounds: str = "PROCEDURAL_ERROR") -> dict:
    payload = factories.create_appeal_payload(case_id=case_id, grounds=grounds)
    return get_success_data(
        api_client.create_appeal(payload, make_candidate_headers(candidate_id)), 201
    )


# ---------------------------------------------------------------------------
# Clock extensions (PRD §3.3)
# ---------------------------------------------------------------------------

def file_clock_extension(
    case_id: str,
    candidate_id: str,
    interval_start: str,
    interval_end: str,
    reason: str = "MEDICAL_LEAVE",
) -> dict:
    payload = factories.create_clock_extension_payload(
        case_id=case_id,
        reason=reason,
        interval_start=interval_start,
        interval_end=interval_end,
    )
    return get_success_data(
        api_client.create_clock_extension(payload, make_candidate_headers(candidate_id)),
        201,
    )


def approve_clock_extension(extension_id: str) -> dict:
    return get_success_data(api_client.approve_clock_extension(extension_id, PO_CREATOR))


def read_clock_extension(extension_id: str) -> dict:
    return get_success_data(api_client.get_clock_extension(extension_id, READER))
