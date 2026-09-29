"""Who may call, whose rows they may touch, and which rung answers first.

The four scenarios here walk the top of the validation ladder: authentication at
rung 1, authorization at rung 2, the two per-row scope rungs at 3 and 4, and the
segregation-of-duties rung at 20 that compares two operator identifiers inside a
single role.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_claim_dimensions, assert_fields_equal, ids_of
from test_helpers.test_users import (
    COORDINATOR,
    OFFICER_APPROVER,
    OFFICER_APPROVER_USER_ID,
    OFFICER_REVIEWER,
    OFFICER_REVIEWER_USER_ID,
    REGISTRAR,
    make_assessor_headers,
    make_headers,
    make_reviewer_headers,
    make_student_headers,
)
from test_helpers.types import (
    Alignment,
    AssessmentStatus,
    AssignmentStatus,
    CourseLevel,
    Recommendation,
    RecommendationStatus,
    Role,
    RuleStatus,
    SourceType,
)

MISSING_ID = "00000000-0000-4000-8000-000000000000"


def _cs150_outcomes():
    return [
        f.outcome_payload("OC1", 8000, mastery_threshold_bp=7000),
        f.outcome_payload("OC2", 2000, mastery_threshold_bp=7000),
    ]


def _program(client, program_code="BSCS"):
    return fx.new_program(
        client,
        program_code=program_code,
        total_credits_required=120,
        residency_min_credits=30,
        pla_max_credits=30,
        pla_max_pct_bp=2500,
        pla_upper_division_max_credits=6,
    )


def _cs150(client):
    return fx.new_course(
        client,
        course_code="CS150",
        department_code="CS",
        credits=6,
        level=CourseLevel.LOWER,
        learning_outcomes=_cs150_outcomes(),
    )


def _student(client, program_id, student_number):
    return fx.new_student(
        client,
        program_id,
        student_number=student_number,
        transfer_credits_accepted=0,
        institutional_credits_earned=60,
    )


def _assessor(client, employee_number, **overrides):
    return fx.new_assessor(
        client,
        employee_number=employee_number,
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=3,
        **overrides,
    )


@pytest.fixture
def one_programme_one_student_one_assessor(client):
    """The smallest world that has a row behind each of the three backed roles."""
    program = _program(client)
    student = _student(client, program["id"], "S-1001")
    assessor = _assessor(client, "E-9001", appeal_panel_member=True)
    return {"program": program, "student": student, "assessor": assessor}


def test_a_header_pair_that_does_not_resolve_is_refused_before_any_role_list(
    client, one_programme_one_student_one_assessor
):
    """Both headers must be present, and a backed role's id must name a real row.

    PRD: "Every request must carry two headers: `X-User-ID`, identifying the acting
    principal, and `X-User-Role`, declaring the capacity in which that principal is
    acting. A request missing either header is rejected with `ERR_UNAUTHENTICATED`
    (401). The same error is returned when the acting role is backed by a persisted
    entity and `X-User-ID` does not resolve to an existing row of that entity."
    "`X-User-Role` and `X-User-ID` are both present, and for `Student`,
    `FacultyAssessor` and `AppealReviewer` the supplied `X-User-ID` resolves to an
    existing row of its backing entity. Failure: `ERR_UNAUTHENTICATED` (401). Applies
    to every endpoint."

    Design: Corner/rbac/unauthenticated_and_unauthorized_calls_are_refused_ahead_of_every_business_rule
    """
    scenario = one_programme_one_student_one_assessor
    program_id = scenario["program"]["id"]
    student_id = scenario["student"]["id"]

    probes = {
        "no headers at all": {},
        "role without an id": {"X-User-Role": Role.STUDENT},
        "id without a role": {"X-User-ID": student_id},
        "a Student id that names no Student row": make_student_headers(MISSING_ID),
        "an assessor id that names no assessor row": make_assessor_headers(MISSING_ID),
        "a reviewer id that names no assessor row": make_reviewer_headers(MISSING_ID),
        # The claim row is the Student's, but the header still has to resolve first.
        "a Student id that names another entity's row": make_student_headers(program_id),
    }
    for label, headers in probes.items():
        refused = client.get_program(program_id, headers=headers)
        body = validate_error(refused, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        assert body["error_id"] == ApiErrorId.ERR_UNAUTHENTICATED, (
            "rung 1 must answer for %s" % label
        )

    # Rung 1 outranks rung 2: this endpoint is a PlaCoordinator exclusive, yet an
    # unresolvable Student id is still answered 401 rather than 403.
    unresolvable = client.create_program(
        f.program_payload(program_code="BSXX"), headers=make_student_headers(MISSING_ID)
    )
    validate_error(unresolvable, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    # No programme collection endpoint exists in S4, so the one readable programme
    # row stands in for the design's "still shows exactly 1 program" check.
    survivor = get_success_data(client.get_program(program_id, headers=COORDINATOR))
    assert_fields_equal(survivor, program_code="BSCS", version=1)


def test_the_opaque_roles_accept_any_identifier_and_the_backed_roles_a_real_row(
    client, one_programme_one_student_one_assessor
):
    """Three roles are never resolved against a table, and three always are.

    PRD: "When `X-User-Role` is `PlaCoordinator`, `X-User-ID` is an opaque operator
    identifier not tied to any persisted entity; the server does not compare it to any
    entity's `id`. The same holds for `Registrar`, sole authority over the transcript.
    When `X-User-Role` is `ArticulationOfficer`, `X-User-ID` is likewise an opaque
    operator identifier not tied to any persisted entity". "When `X-User-Role` is
    `AppealReviewer`, `X-User-ID` is likewise the `id` of a `FacultyAssessor` row — the
    two roles share one backing entity".

    Design: Corner/rbac/unauthenticated_and_unauthorized_calls_are_refused_ahead_of_every_business_rule
    """
    scenario = one_programme_one_student_one_assessor
    program_id = scenario["program"]["id"]

    opaque = {
        Role.PLA_COORDINATOR: "whoever-is-on-the-desk-today",
        Role.REGISTRAR: "registrar-42",
        Role.ARTICULATION_OFFICER: MISSING_ID,
    }
    for role, user_id in opaque.items():
        read = get_success_data(client.get_program(program_id, headers=make_headers(user_id, role)))
        assert read["id"] == program_id, "%s carries an unchecked identifier" % role

    backed = {
        Role.STUDENT: scenario["student"]["id"],
        Role.FACULTY_ASSESSOR: scenario["assessor"]["id"],
        # One FacultyAssessor row stands behind both faculty roles.
        Role.APPEAL_REVIEWER: scenario["assessor"]["id"],
    }
    for role, user_id in backed.items():
        read = get_success_data(client.get_program(program_id, headers=make_headers(user_id, role)))
        assert read["id"] == program_id, "%s resolved its own row" % role

    # A Student id offered as a FacultyAssessor is a row of the wrong entity.
    crossed = client.get_program(
        program_id, headers=make_headers(scenario["student"]["id"], Role.FACULTY_ASSESSOR)
    )
    validate_error(crossed, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    swapped = client.get_program(
        program_id, headers=make_headers(scenario["assessor"]["id"], Role.STUDENT)
    )
    validate_error(swapped, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_a_role_off_the_endpoint_list_is_refused_before_the_path_is_resolved(
    client, one_programme_one_student_one_assessor
):
    """Rung 2 answers 403 even when the path id names nothing at all.

    PRD: "Once the caller is identified, the endpoint's own authorization list is
    consulted; a role that does not appear on the called endpoint's list is rejected
    with `ERR_UNAUTHORIZED` (403)." "The acting role appears on the called endpoint's
    role list. Failure: `ERR_UNAUTHORIZED` (403). Applies to every endpoint." "Every
    identifier in the path exists, resolved left to right. Failure: the matching 404
    from the family in §2.8."

    Design: Corner/rbac/unauthenticated_and_unauthorized_calls_are_refused_ahead_of_every_business_rule
    """
    scenario = one_programme_one_student_one_assessor
    student_headers = make_student_headers(scenario["student"]["id"])
    assessor_headers = make_assessor_headers(scenario["assessor"]["id"])

    # Creating a programme is a PlaCoordinator exclusive; the Student is turned away.
    refused = client.create_program(
        f.program_payload(
            program_code="BSXX",
            allowed_source_types=[SourceType.PORTFOLIO],
        ),
        headers=student_headers,
    )
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED, 403)

    untouched = get_success_data(client.get_program(scenario["program"]["id"], headers=COORDINATOR))
    assert_fields_equal(untouched, program_code="BSCS", version=1)

    # Each of these paths names a row that does not exist; rung 2 answers first.
    off_list = {
        "a Student awarding a claim": client.award_claim(
            MISSING_ID, {"credits_awarded": 6}, headers=student_headers
        ),
        "a coordinator posting to the transcript": client.post_transcript(
            MISSING_ID, {"posted_term": "2026FA"}, headers=COORDINATOR
        ),
        "a coordinator reversing a posting": client.reverse_transcript(
            MISSING_ID, {"reversal_reason": "Keyed in error"}, headers=COORDINATOR
        ),
        "a registrar requesting a revision": client.request_revision(
            MISSING_ID, {"revision_note": "More evidence please"}, headers=REGISTRAR
        ),
        "an assessor waiving an invoice": client.waive_invoice(
            MISSING_ID, {"waive_reason": "Hardship"}, headers=assessor_headers
        ),
        "a student accepting an assignment": client.accept_assignment(
            MISSING_ID, headers=student_headers
        ),
        "a registrar filing an appeal": client.create_appeal(
            {"claim_id": MISSING_ID, "grounds": "Reconsider"}, headers=REGISTRAR
        ),
    }
    for label, response in off_list.items():
        body = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert body["error_id"] == ApiErrorId.ERR_UNAUTHORIZED, (
            "rung 2 must precede the 404 family for %s" % label
        )


@pytest.fixture
def two_peers_and_one_draft_portfolio_claim(client):
    """S-1001 owns a DRAFT portfolio claim; S-1002 is a peer in the same programme.

    One PRIMARY mapping on the 8000-weight outcome carries provisional coverage of
    8000 basis points, so the owner's own portfolio submission has a clear path once
    the peer's attempts have all been refused.
    """
    program = _program(client)
    course = _cs150(client)
    spare_course = fx.new_course(
        client,
        course_code="CS210",
        department_code="CS",
        credits=6,
        level=CourseLevel.LOWER,
        learning_outcomes=_cs150_outcomes(),
    )
    owner = _student(client, program["id"], "S-1001")
    peer = _student(client, program["id"], "S-1002")
    outcomes = fx.outcomes_of(client, course["id"])
    claim = fx.new_claim(
        client,
        owner["id"],
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=6,
    )
    portfolio = fx.new_portfolio(client, claim["id"], owner["id"])
    artifact = fx.attach_artifact(
        client,
        portfolio["id"],
        owner["id"],
        [f.mapping(outcomes[0]["id"], Alignment.PRIMARY)],
    )
    return {
        "program": program,
        "course": course,
        "spare_course": spare_course,
        "owner": owner,
        "peer": peer,
        "outcomes": outcomes,
        "claim": claim,
        "portfolio": portfolio,
        "artifact": artifact,
    }


def test_a_peer_student_is_refused_every_scoped_read_the_owner_is_granted(
    client, two_peers_and_one_draft_portfolio_claim
):
    """The Student role is on each endpoint's list, yet the rows are not the peer's.

    PRD: "A `Student` acts only on rows scoped to itself. Failure:
    `ERR_FORBIDDEN_STUDENT_SCOPE` (403). Applies to reading one claim, submitting a
    claim, withdrawing a claim, reading one portfolio, adding a portfolio artifact,
    deleting a portfolio artifact, submitting a portfolio, reading one invoice, paying
    an invoice, filing an appeal, and reading a graduation audit." "Concretely, a
    claim's `student_id`, a portfolio's parent claim's `student_id`, an artifact's
    grandparent claim's `student_id`, an invoice's `student_id`, an appeal's parent
    claim's `student_id`, and the `student_id` path segment of a graduation audit must
    all equal `X-User-ID`; otherwise the request fails with
    `ERR_FORBIDDEN_STUDENT_SCOPE` (403)."

    Design: Corner/rbac/student_cannot_read_or_act_on_another_students_claim
    """
    scenario = two_peers_and_one_draft_portfolio_claim
    owner_id = scenario["owner"]["id"]
    peer_headers = make_student_headers(scenario["peer"]["id"])

    reads = {
        "one claim": lambda headers: client.get_claim(scenario["claim"]["id"], headers=headers),
        "one portfolio": lambda headers: client.get_portfolio(
            scenario["portfolio"]["id"], headers=headers
        ),
        # S2.1 names "an artifact's grandparent claim's student_id" among the fields
        # that must equal X-User-ID, so the artifact read is scoped too.
        "one artifact": lambda headers: client.get_artifact(
            scenario["artifact"]["id"], headers=headers
        ),
        "a graduation audit": lambda headers: client.get_graduation_audit(
            owner_id, headers=headers
        ),
    }
    for label, call in reads.items():
        body = validate_error(call(peer_headers), ApiErrorId.ERR_FORBIDDEN_STUDENT_SCOPE, 403)
        assert body["error_id"] == ApiErrorId.ERR_FORBIDDEN_STUDENT_SCOPE, (
            "the peer must not read %s" % label
        )

    # Scope is per-row ownership, not per-role: the owner and the coordinator both read.
    for label, call in reads.items():
        for headers in (make_student_headers(owner_id), COORDINATOR):
            assert get_success_data(call(headers)), "%s is readable by its owner and the desk" % label


def test_a_peer_student_moves_nothing_and_the_owner_still_can(
    client, two_peers_and_one_draft_portfolio_claim
):
    """Six write attempts by the peer, then the owner walks the same claim forward.

    PRD: "ownership checks on any resource that references a `Student` compare the
    resource's student-bearing field to `X-User-ID`." "A `Student` acts only on rows
    scoped to itself. Failure: `ERR_FORBIDDEN_STUDENT_SCOPE` (403)."

    Design: Corner/rbac/student_cannot_read_or_act_on_another_students_claim
    """
    scenario = two_peers_and_one_draft_portfolio_claim
    owner_id = scenario["owner"]["id"]
    peer_headers = make_student_headers(scenario["peer"]["id"])
    claim_id = scenario["claim"]["id"]
    portfolio_id = scenario["portfolio"]["id"]

    writes = {
        "submitting the claim": client.submit_claim(claim_id, headers=peer_headers),
        "withdrawing the claim": client.withdraw_claim(
            claim_id, {"withdraw_reason": "Not mine to drop"}, headers=peer_headers
        ),
        "submitting the portfolio": client.submit_portfolio(portfolio_id, headers=peer_headers),
        "adding an artifact": client.add_artifact(
            portfolio_id,
            f.artifact_payload([f.mapping(scenario["outcomes"][1]["id"], Alignment.SUPPORTING)]),
            headers=peer_headers,
        ),
        "deleting an artifact": client.delete_artifact(
            portfolio_id, scenario["artifact"]["id"], headers=peer_headers
        ),
        # A fresh course keeps the duplicate-claim rule out of this probe, so the only
        # rule that can answer is the ownership check on the body's student_id.
        "opening a claim on the owner's behalf": client.create_claim(
            f.claim_payload(
                owner_id,
                scenario["spare_course"]["id"],
                source_type=SourceType.PORTFOLIO,
                credits_requested=6,
            ),
            headers=peer_headers,
        ),
    }
    for label, response in writes.items():
        body = validate_error(response, ApiErrorId.ERR_FORBIDDEN_STUDENT_SCOPE, 403)
        assert body["error_id"] == ApiErrorId.ERR_FORBIDDEN_STUDENT_SCOPE, (
            "the peer must be refused %s" % label
        )

    held = get_success_data(client.get_portfolio(portfolio_id, headers=COORDINATOR))
    assert_fields_equal(held, artifact_count=1)
    still_draft = get_success_data(client.get_claim(claim_id, headers=COORDINATOR))
    assert_claim_dimensions(still_draft, assessment_status=AssessmentStatus.DRAFT)

    owner_headers = make_student_headers(owner_id)
    submitted_portfolio = validate_success(
        client.submit_portfolio(portfolio_id, headers=owner_headers)
    )
    assert_fields_equal(submitted_portfolio, provisional_coverage_bp=8000)
    submitted_claim = validate_success(client.submit_claim(claim_id, headers=owner_headers))
    assert_claim_dimensions(submitted_claim, assessment_status=AssessmentStatus.SUBMITTED)


@pytest.fixture
def one_assignment_and_a_second_assessor(client):
    """An ASSIGNED assignment owned by E-9001, with idle E-9002 standing beside it.

    The invoice is waived rather than paid, because the assessment fee gate sits at
    the very bottom of the ladder and this scenario is about the top of it.
    """
    fx.set_clock(client, fx.CLOCK_EPOCH)
    program = _program(client)
    course = _cs150(client)
    student = _student(client, program["id"], "S-1001")
    owner = _assessor(client, "E-9001")
    other = _assessor(client, "E-9002")
    outcomes = fx.outcomes_of(client, course["id"])
    claim = fx.new_claim(
        client,
        student["id"],
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=6,
    )
    portfolio = fx.new_portfolio(client, claim["id"], student["id"])
    fx.attach_artifact(
        client, portfolio["id"], student["id"], [f.mapping(outcomes[0]["id"], Alignment.PRIMARY)]
    )
    fx.attach_artifact(
        client, portfolio["id"], student["id"], [f.mapping(outcomes[1]["id"], Alignment.SUPPORTING)]
    )
    fx.submit_portfolio(client, portfolio["id"], student["id"])
    fx.submit_claim(client, claim["id"], student["id"])
    invoice = fx.invoice_for_claim(client, claim["id"])
    get_success_data(
        client.waive_invoice(
            invoice["id"], {"waive_reason": "Pilot cohort waiver"}, headers=COORDINATOR
        )
    )
    assignment = fx.assign_assessor(client, claim["id"], owner["id"])
    return {
        "student": student,
        "owner": owner,
        "other": other,
        "outcomes": outcomes,
        "claim": claim,
        "assignment": assignment,
    }


def test_an_assignment_answers_only_to_the_assessor_it_names(
    client, one_assignment_and_a_second_assessor
):
    """E-9002 holds the role the endpoints list, but not this assignment.

    PRD: "an assignment-scoped operation is permitted only when the assignment's
    `assessor_id` equals `X-User-ID`, and a mismatch yields
    `ERR_FORBIDDEN_ASSESSOR_SCOPE` (403)." "A `FacultyAssessor` acts only on an
    assignment whose `assessor_id` equals `X-User-ID`. Failure:
    `ERR_FORBIDDEN_ASSESSOR_SCOPE` (403). Applies to accepting an assignment, declining
    an assignment, recording a rubric score, and completing an assignment."

    Design: Corner/rbac/assessor_cannot_score_or_complete_another_assessors_assignment
    """
    scenario = one_assignment_and_a_second_assessor
    assignment_id = scenario["assignment"]["id"]
    assert_fields_equal(
        scenario["assignment"],
        assessor_id=scenario["owner"]["id"],
        status=AssignmentStatus.ASSIGNED,
    )
    intruder = make_assessor_headers(scenario["other"]["id"])

    attempts = {
        "accepting": client.accept_assignment(assignment_id, headers=intruder),
        "declining": client.decline_assignment(
            assignment_id, {"decline_reason": "Too busy"}, headers=intruder
        ),
        # Rung 4 precedes rung 17, so this is not ERR_ASSIGNMENT_NOT_ACCEPTED even
        # though the assignment has never been accepted.
        "recording a rubric score": client.create_rubric_score(
            assignment_id,
            f.rubric_score_payload(scenario["outcomes"][0]["id"], 3),
            headers=intruder,
        ),
        "completing": client.complete_assignment(
            assignment_id, {"recommendation": Recommendation.PASS}, headers=intruder
        ),
    }
    for label, response in attempts.items():
        body = validate_error(response, ApiErrorId.ERR_FORBIDDEN_ASSESSOR_SCOPE, 403)
        assert body["error_id"] == ApiErrorId.ERR_FORBIDDEN_ASSESSOR_SCOPE, (
            "%s belongs to the named assessor alone" % label
        )

    untouched = get_success_data(client.get_assignment(assignment_id, headers=COORDINATOR))
    assert_fields_equal(untouched, status=AssignmentStatus.ASSIGNED, accepted_at=None)

    # Accepting is a FacultyAssessor exclusive, so the desk that created the
    # assignment cannot accept it on the assessor's behalf.
    validate_error(
        client.accept_assignment(assignment_id, headers=COORDINATOR),
        ApiErrorId.ERR_UNAUTHORIZED,
        403,
    )

    accepted = validate_success(
        client.accept_assignment(
            assignment_id, headers=make_assessor_headers(scenario["owner"]["id"])
        )
    )
    assert_fields_equal(accepted, status=AssignmentStatus.ACCEPTED)
    assert accepted["accepted_at"] is not None, "acceptance stamps the clock"


def test_the_other_assessor_may_read_the_work_it_may_not_touch(
    client, one_assignment_and_a_second_assessor
):
    """Rung 4 guards four verbs; the reads stay open to the whole faculty role.

    PRD: "Applies to accepting an assignment, declining an assignment, recording a
    rubric score, and completing an assignment." "Completion requires exactly one
    rubric score for every learning outcome of the claim's course, and the submitted
    `recommendation` must equal the recommendation the server computes from
    `verified_coverage_bp` against the effective pass threshold."

    Design: Corner/rbac/assessor_cannot_score_or_complete_another_assessors_assignment
    """
    scenario = one_assignment_and_a_second_assessor
    assignment_id = scenario["assignment"]["id"]
    owner_id = scenario["owner"]["id"]
    intruder = make_assessor_headers(scenario["other"]["id"])

    seen = get_success_data(client.get_assignment(assignment_id, headers=intruder))
    assert_fields_equal(seen, id=assignment_id, assessor_id=owner_id)
    rows, meta = validate_paginated(
        client.list_assignments({"assessor_id": owner_id}, headers=intruder)
    )
    assert ids_of(rows) == [assignment_id]
    assert meta["total_count"] == 1

    fx.accept_assignment(client, assignment_id, owner_id)
    scores = fx.score_all_outcomes(
        client, assignment_id, owner_id, scenario["outcomes"], [3, 3]
    )
    read_back = get_success_data(client.get_rubric_score(scores[0]["id"], headers=intruder))
    assert_fields_equal(read_back, id=scores[0]["id"], points_awarded=3)

    # The rubric is complete and the recommendation is the right one, and the scope
    # rung still answers first for the assessor who did not do the work.
    validate_error(
        client.complete_assignment(assignment_id, {"recommendation": Recommendation.PASS}, headers=intruder),
        ApiErrorId.ERR_FORBIDDEN_ASSESSOR_SCOPE,
        403,
    )

    completed = validate_success(
        client.complete_assignment(
            assignment_id, {"recommendation": Recommendation.PASS}, headers=make_assessor_headers(owner_id)
        )
    )
    assert_fields_equal(
        completed,
        status=AssignmentStatus.SCORING_COMPLETE,
        verified_coverage_bp=7500,
        recommendation=Recommendation.PASS,
    )
    scored = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(scored, assessment_status=AssessmentStatus.SCORED)


@pytest.fixture
def a_rule_under_review_by_the_officer_who_drafted_it(client):
    """CLEP-CS is PUBLISHED at version 2, and its CS150 rule waits at UNDER_REVIEW.

    Every setup call is made under one operator identifier — op-officer-reviewer-001 —
    so that identifier is the one stamped into ``reviewed_by_user_id``.
    """
    fx.set_clock(client, fx.CLOCK_EPOCH)
    course = _cs150(client)
    recommendation = get_success_data(
        client.create_recommendation(
            f.recommendation_payload(
                credential_code="CLEPCS",
                source_type=SourceType.CREDIT_BY_EXAM,
                recommended_credits=6,
                recommended_level=CourseLevel.LOWER,
                effective_from="2026-06-01T00:00:00Z",
            ),
            headers=OFFICER_REVIEWER,
        )
    )
    published = get_success_data(
        client.publish_recommendation(recommendation["id"], headers=OFFICER_REVIEWER)
    )
    rule = get_success_data(
        client.create_rule(
            f.rule_payload(
                recommendation["id"],
                course["id"],
                awarded_credits=6,
                effective_from="2026-06-01T00:00:00Z",
            ),
            headers=OFFICER_REVIEWER,
        )
    )
    under_review = get_success_data(
        client.submit_rule_for_review(rule["id"], headers=OFFICER_REVIEWER)
    )
    return {"course": course, "recommendation": published, "rule": under_review}


def test_the_officer_who_submitted_the_rule_may_not_approve_it(
    client, a_rule_under_review_by_the_officer_who_drafted_it
):
    """One identifier reviews, a different identifier approves, and only then.

    PRD: "Submitting a rule for review advances it `DRAFT → UNDER_REVIEW` and stamps
    the acting `X-User-ID` into `reviewed_by_user_id`". "Approval then advances
    `UNDER_REVIEW → APPROVED` and stamps the approver's `X-User-ID` into
    `approved_by_user_id`, which **must differ** from `reviewed_by_user_id`; a
    self-approval is `ERR_SEGREGATION_OF_DUTIES`." "On success it pins
    `pinned_recommendation_version` to the recommendation's current `terms_version` — a
    counter this operation does not move, so a freshly approved rule is never stale —
    increments `approved_rule_count` by one, increments the recommendation's `version`
    by one, and increments the rule's own `version` by one."

    Design: Corner/rbac/same_officer_must_not_review_and_then_approve_the_same_rule
    """
    scenario = a_rule_under_review_by_the_officer_who_drafted_it
    rule_id = scenario["rule"]["id"]
    assert_fields_equal(
        scenario["rule"],
        status=RuleStatus.UNDER_REVIEW,
        reviewed_by_user_id=OFFICER_REVIEWER_USER_ID,
        approved_by_user_id=None,
        pinned_recommendation_version=None,
    )
    assert_fields_equal(
        scenario["recommendation"],
        status=RecommendationStatus.PUBLISHED,
        version=2,
        terms_version=1,
    )

    self_approval = client.approve_rule(
        rule_id, {"expected_recommendation_version": 2}, headers=OFFICER_REVIEWER
    )
    validate_error(self_approval, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)

    held = get_success_data(client.get_rule(rule_id, headers=OFFICER_REVIEWER))
    assert_fields_equal(
        held,
        status=RuleStatus.UNDER_REVIEW,
        approved_by_user_id=None,
        pinned_recommendation_version=None,
        version=2,
    )

    # The identical payload from a different operator identifier is accepted.
    approved = validate_success(
        client.approve_rule(
            rule_id, {"expected_recommendation_version": 2}, headers=OFFICER_APPROVER
        )
    )
    assert_fields_equal(
        approved,
        status=RuleStatus.APPROVED,
        reviewed_by_user_id=OFFICER_REVIEWER_USER_ID,
        approved_by_user_id=OFFICER_APPROVER_USER_ID,
        pinned_recommendation_version=1,
    )

    recommendation = get_success_data(
        client.get_recommendation(scenario["recommendation"]["id"], headers=OFFICER_APPROVER)
    )
    assert_fields_equal(recommendation, approved_rule_count=1, version=3, terms_version=1)


def test_the_recommendation_version_gate_answers_before_the_duty_gate(
    client, a_rule_under_review_by_the_officer_who_drafted_it
):
    """A stale token from the barred officer is answered 412, not 409.

    PRD: "`expected_recommendation_version` equals the current
    `CredentialRecommendation` `version`. Failure: `ERR_STALE_RECOMMENDATION_VERSION`
    (412). Applies to approving a crosswalk rule." "The `X-User-ID` that submitted a
    crosswalk rule for review must not be the `X-User-ID` that approves it, and an
    appeal reviewer must not appear in the appeal's `prior_scorer_assessor_ids`.
    Failure: `ERR_SEGREGATION_OF_DUTIES` (409)." "publication increments the
    recommendation's `version` but deliberately leaves `terms_version` untouched."

    Design: Corner/rbac/same_officer_must_not_review_and_then_approve_the_same_rule
    """
    scenario = a_rule_under_review_by_the_officer_who_drafted_it
    rule_id = scenario["rule"]["id"]

    # Version 1 was the pre-publication value; both officers are told the same thing,
    # and the barred one is told it too — rung 13 sits above rung 20.
    for headers in (OFFICER_REVIEWER, OFFICER_APPROVER):
        stale = client.approve_rule(
            rule_id, {"expected_recommendation_version": 1}, headers=headers
        )
        validate_error(stale, ApiErrorId.ERR_STALE_RECOMMENDATION_VERSION, 412)

    untouched = get_success_data(client.get_rule(rule_id, headers=OFFICER_APPROVER))
    assert_fields_equal(
        untouched, status=RuleStatus.UNDER_REVIEW, approved_by_user_id=None, version=2
    )

    # With a current token the duty rung finally speaks for the reviewing officer.
    validate_error(
        client.approve_rule(
            rule_id, {"expected_recommendation_version": 2}, headers=OFFICER_REVIEWER
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        409,
    )
    approved = validate_success(
        client.approve_rule(
            rule_id, {"expected_recommendation_version": 2}, headers=OFFICER_APPROVER
        )
    )
    assert_fields_equal(
        approved, status=RuleStatus.APPROVED, approved_by_user_id=OFFICER_APPROVER_USER_ID
    )
