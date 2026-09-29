"""Error corners: every refusal names the row and the rung that produced it.

Each probe is issued against a scenario whose only defect is the one under test,
so a blanket 404 or a generic conflict is as visible as a missing check.
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
from test_helpers.assertions import (
    assert_audit,
    assert_claim_dimensions,
    assert_fields_equal,
    assert_ledger,
    ids_of,
)
from test_helpers.test_users import (
    COORDINATOR,
    OFFICER_APPROVER,
    OFFICER_APPROVER_USER_ID,
    OFFICER_REVIEWER,
    OFFICER_REVIEWER_USER_ID,
    REGISTRAR,
    make_assessor_headers,
    make_student_headers,
)
from test_helpers.types import (
    Alignment,
    AssessmentStatus,
    AssessorStatus,
    AssignmentStatus,
    CourseLevel,
    CreditStatus,
    EnrollmentStatus,
    FeeStatus,
    PortfolioStatus,
    Recommendation,
    RecommendationStatus,
    RuleStatus,
    SelectionReason,
    SourceType,
)

# A syntactically valid UUID that no row can carry, because every `id` in this
# system is server-minted and never supplied by the client (PRD S2.4).
MISSING_ID = "00000000-0000-4000-8000-000000000000"

ALL_SOURCES = (
    SourceType.CREDIT_BY_EXAM,
    SourceType.PORTFOLIO,
    SourceType.MILITARY_TRAINING,
    SourceType.INDUSTRY_CREDENTIAL,
)


def _cs150_outcomes():
    """Two outcomes weighted 8000 and 2000, both at the default 7000 mastery."""
    return [
        f.outcome_payload("OC1", 8000, mastery_threshold_bp=7000),
        f.outcome_payload("OC2", 2000, mastery_threshold_bp=7000),
    ]


def _one_outcome(outcome_code):
    return [f.outcome_payload(outcome_code, 10000, mastery_threshold_bp=7000)]


def _program(client, program_code="BSCS", **overrides):
    fields = {
        "program_code": program_code,
        "total_credits_required": 120,
        "residency_min_credits": 30,
        "pla_max_credits": 30,
        "pla_max_pct_bp": 2500,
        "pla_upper_division_max_credits": 6,
        "allowed_source_types": list(ALL_SOURCES),
    }
    fields.update(overrides)
    return fx.new_program(client, **fields)


def _course(client, course_code, credits=6, learning_outcomes=None, **overrides):
    fields = {
        "course_code": course_code,
        "department_code": "CS",
        "credits": credits,
        "level": CourseLevel.LOWER,
        "learning_outcomes": (
            learning_outcomes if learning_outcomes is not None else _cs150_outcomes()
        ),
    }
    fields.update(overrides)
    return fx.new_course(client, **fields)


def _student(client, program_id, student_number="S-1001", **overrides):
    fields = {
        "student_number": student_number,
        "enrollment_status": EnrollmentStatus.MATRICULATED,
        "transfer_credits_accepted": 0,
        "institutional_credits_earned": 60,
    }
    fields.update(overrides)
    return fx.new_student(client, program_id, **fields)


def _portfolio_claim(client, student_id, course, credits_requested=6, alignments=None):
    """A DRAFT `PORTFOLIO` claim whose DRAFT portfolio holds one artifact per outcome."""
    claim = fx.new_claim(
        client,
        student_id,
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=credits_requested,
    )
    outcomes = fx.outcomes_of(client, course["id"])
    portfolio = fx.new_portfolio(client, claim["id"], student_id)
    chosen = alignments if alignments is not None else [Alignment.PRIMARY] * len(outcomes)
    for outcome, alignment in zip(outcomes, chosen):
        fx.attach_artifact(
            client, portfolio["id"], student_id, [f.mapping(outcome["id"], alignment)]
        )
    return {"claim": claim, "portfolio": portfolio, "outcomes": outcomes}


def _waive(client, invoice_id):
    return get_success_data(
        client.waive_invoice(
            invoice_id, {"waive_reason": "Institutional pilot cohort"}, headers=COORDINATOR
        )
    )


def _settled_portfolio_claim(
    client, student_id, course, credits_requested=6, alignments=None, settle="waive"
):
    """A `SUBMITTED` portfolio claim whose invoice is settled, so the fee gate is open."""
    parts = _portfolio_claim(
        client, student_id, course, credits_requested=credits_requested, alignments=alignments
    )
    fx.submit_portfolio(client, parts["portfolio"]["id"], student_id)
    fx.submit_claim(client, parts["claim"]["id"], student_id)
    invoice = fx.invoice_for_claim(client, parts["claim"]["id"])
    if settle == "waive":
        _waive(client, invoice["id"])
    else:
        fx.pay_invoice_in_full(client, parts["claim"]["id"], student_id)
    parts["invoice"] = invoice
    return parts


def test_every_by_id_lookup_of_a_missing_row_names_its_own_entity(client):
    """Fourteen read endpoints, fourteen distinct 404 codes, one probe identifier.

    PRD: "Identifiers in a request path are resolved strictly left to right, parent
    segment before child segment, and the first identifier that does not resolve ends
    the request with the 404 belonging to *that* segment." "The path-level 404 family
    is `ERR_PROGRAM_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`,
    `ERR_ASSESSOR_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PORTFOLIO_NOT_FOUND`,
    `ERR_ARTIFACT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_RUBRIC_SCORE_NOT_FOUND`,
    `ERR_APPEAL_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_RECOMMENDATION_NOT_FOUND` and
    `ERR_ARTICULATION_RULE_NOT_FOUND`." "The body-level family adds
    `ERR_OUTCOME_NOT_FOUND` for a `learning_outcome_id` or `outcome_id` that does not
    exist, and reuses the same claim, student, course, assessor, recommendation and
    rule codes." "The `meta` object for error responses contains only `api_request_id`
    and `api_request_timestamp`."

    Design: Corner/errors/every_by_id_lookup_of_a_missing_row_returns_its_own_not_found_code
    """
    # `GET /learning-outcomes/{outcome_id}` names its path parameter `outcome_id`, the
    # identifier the quoted clause attaches `ERR_OUTCOME_NOT_FOUND` to.
    probes = [
        ("programs", client.get_program, ApiErrorId.ERR_PROGRAM_NOT_FOUND),
        ("courses", client.get_course, ApiErrorId.ERR_COURSE_NOT_FOUND),
        ("learning-outcomes", client.get_learning_outcome, ApiErrorId.ERR_OUTCOME_NOT_FOUND),
        (
            "credential-recommendations",
            client.get_recommendation,
            ApiErrorId.ERR_RECOMMENDATION_NOT_FOUND,
        ),
        ("articulation-rules", client.get_rule, ApiErrorId.ERR_ARTICULATION_RULE_NOT_FOUND),
        ("students", client.get_student, ApiErrorId.ERR_STUDENT_NOT_FOUND),
        ("faculty-assessors", client.get_assessor, ApiErrorId.ERR_ASSESSOR_NOT_FOUND),
        ("pla-claims", client.get_claim, ApiErrorId.ERR_CLAIM_NOT_FOUND),
        ("portfolios", client.get_portfolio, ApiErrorId.ERR_PORTFOLIO_NOT_FOUND),
        ("artifacts", client.get_artifact, ApiErrorId.ERR_ARTIFACT_NOT_FOUND),
        ("assessor-assignments", client.get_assignment, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
        ("rubric-scores", client.get_rubric_score, ApiErrorId.ERR_RUBRIC_SCORE_NOT_FOUND),
        ("fee-invoices", client.get_invoice, ApiErrorId.ERR_INVOICE_NOT_FOUND),
        ("appeals", client.get_appeal, ApiErrorId.ERR_APPEAL_NOT_FOUND),
    ]
    assert len(probes) == 14, "one probe per by-id read endpoint of PRD S4"

    seen = []
    for label, read_one, error_id in probes:
        response = read_one(MISSING_ID, headers=COORDINATOR)
        validate_error(response, error_id, 404)
        body = response.json()
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "%s: the error envelope still carries a request identifier" % label
        )
        assert "limit" not in body["meta"], (
            "%s: an error envelope's meta carries only the two request fields" % label
        )
        seen.append(error_id)

    assert len(set(seen)) == 14, "each entity reports its own code, never a shared 404"


def test_a_body_reference_and_a_foreign_child_report_the_row_that_failed(client):
    """A body identifier resolves after the path, and a stranger's artifact is a 404.

    PRD: "Only after every path segment resolves are identifiers carried in the
    request body resolved, and those are resolved in the order the endpoint declares
    its input fields." "An artifact identifier that exists but belongs to a portfolio
    other than the one named in the path is also reported as `ERR_ARTIFACT_NOT_FOUND`."
    "`total_count` counts the records matching the filter before pagination is applied"

    Design: Corner/errors/every_by_id_lookup_of_a_missing_row_returns_its_own_not_found_code
    """
    program = _program(client)
    cs150 = _course(client, "CS150")
    cs160 = _course(client, "CS160", learning_outcomes=_one_outcome("OCY"))
    student = _student(client, program["id"])
    headers = make_student_headers(student["id"])

    first = _portfolio_claim(client, student["id"], cs150)
    second = _portfolio_claim(client, student["id"], cs160)
    stranger_artifacts, _meta = validate_paginated(
        client.list_artifacts({"portfolio_id": second["portfolio"]["id"]}, headers=COORDINATOR)
    )
    assert len(stranger_artifacts) == 1, "the second portfolio holds exactly one artifact"
    stranger = stranger_artifacts[0]

    missing_student = client.create_claim(
        f.claim_payload(MISSING_ID, cs150["id"], source_type=SourceType.PORTFOLIO),
        headers=COORDINATOR,
    )
    validate_error(missing_student, ApiErrorId.ERR_STUDENT_NOT_FOUND, 404)

    missing_course = client.create_claim(
        f.claim_payload(student["id"], MISSING_ID, source_type=SourceType.PORTFOLIO),
        headers=COORDINATOR,
    )
    validate_error(missing_course, ApiErrorId.ERR_COURSE_NOT_FOUND, 404)

    missing_child = client.delete_artifact(first["portfolio"]["id"], MISSING_ID, headers=headers)
    validate_error(missing_child, ApiErrorId.ERR_ARTIFACT_NOT_FOUND, 404)

    foreign_child = client.delete_artifact(
        first["portfolio"]["id"], stranger["id"], headers=headers
    )
    validate_error(foreign_child, ApiErrorId.ERR_ARTIFACT_NOT_FOUND, 404)

    survivors, _meta = validate_paginated(
        client.list_artifacts({"portfolio_id": second["portfolio"]["id"]}, headers=COORDINATOR)
    )
    assert ids_of(survivors) == [stranger["id"]], "the refused delete touched nothing"
    # `_portfolio_claim` attaches one artifact per outcome of its course, so CS150's
    # two-outcome portfolio holds two and CS160's single-outcome portfolio holds one.
    for scenario in (first, second):
        held = get_success_data(
            client.get_portfolio(scenario["portfolio"]["id"], headers=COORDINATOR)
        )
        assert_fields_equal(
            held,
            artifact_count=len(scenario["outcomes"]),
            status=PortfolioStatus.DRAFT,
        )

    empty, meta = validate_paginated(
        client.list_claims({"student_id": MISSING_ID}, headers=COORDINATOR)
    )
    assert empty == [], "a filter naming no row is an empty page, not a 404"
    assert meta["total_count"] == 0

    both, meta = validate_paginated(
        client.list_claims({"student_id": student["id"]}, headers=COORDINATOR)
    )
    assert ids_of(both) == [first["claim"]["id"], second["claim"]["id"]]
    assert meta["total_count"] == 2


@pytest.fixture
def an_accepted_assignment_and_a_foreign_outcome(client):
    """An `ACCEPTED` assignment on CS150, plus an outcome belonging to MATH100.

    MATH100 exists only to supply a real `learning_outcome_id` that does not belong
    to the claim's course, so the foreign-outcome rung can be reached with a
    resolvable identifier rather than a 404.
    """
    program = _program(client)
    cs150 = _course(client, "CS150")
    math100 = fx.new_course(
        client,
        course_code="MATH100",
        department_code="MATH",
        credits=3,
        level=CourseLevel.LOWER,
        learning_outcomes=_one_outcome("OCX"),
    )
    student = _student(client, program["id"])
    assessor = fx.new_assessor(
        client,
        employee_number="E-9001",
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=3,
    )
    parts = _settled_portfolio_claim(client, student["id"], cs150)
    assignment = fx.assign_assessor(client, parts["claim"]["id"], assessor["id"])
    fx.accept_assignment(client, assignment["id"], assessor["id"])
    return {
        "assessor": assessor,
        "assignment": assignment,
        "claim": parts["claim"],
        "portfolio": parts["portfolio"],
        "outcomes": parts["outcomes"],
        "foreign_outcome": fx.outcomes_of(client, math100["id"])[0],
        "student": student,
    }


def test_the_rubric_point_range_answers_before_the_foreign_outcome(
    client, an_accepted_assignment_and_a_foreign_outcome
):
    """Five points on a stranger's outcome reports the range, not the ownership.

    PRD: "a caller who violates two rules at once must receive the error belonging to
    the *lower-numbered* rung." "`points_awarded` must be an integer from 0 through 4
    inclusive; anything else is `ERR_RUBRIC_POINTS_OUT_OF_RANGE`. The named outcome
    must belong to the course of the assignment's claim, or the request is
    `ERR_OUTCOME_NOT_IN_COURSE`." "The pair of `assignment_id` and
    `learning_outcome_id` is unique: a second score for the same outcome on the same
    assignment is refused with `ERR_DUPLICATE_RUBRIC_SCORE` and is emphatically
    **not** an overwrite of the first."

    Design: Corner/errors/rubric_scoring_input_family_is_rejected_field_by_field
    """
    scenario = an_accepted_assignment_and_a_foreign_outcome
    assignment_id = scenario["assignment"]["id"]
    headers = make_assessor_headers(scenario["assessor"]["id"])
    outcomes = scenario["outcomes"]
    foreign = scenario["foreign_outcome"]

    # Rung 11 (point range) sits above rung 23 (outcome ownership), so the request
    # that breaks both reports the range.
    too_high = client.create_rubric_score(
        assignment_id, f.rubric_score_payload(foreign["id"], 5), headers=headers
    )
    validate_error(too_high, ApiErrorId.ERR_RUBRIC_POINTS_OUT_OF_RANGE, 422)

    negative = client.create_rubric_score(
        assignment_id, f.rubric_score_payload(outcomes[0]["id"], -1), headers=headers
    )
    validate_error(negative, ApiErrorId.ERR_RUBRIC_POINTS_OUT_OF_RANGE, 422)

    in_range_but_foreign = client.create_rubric_score(
        assignment_id, f.rubric_score_payload(foreign["id"], 3), headers=headers
    )
    validate_error(in_range_but_foreign, ApiErrorId.ERR_OUTCOME_NOT_IN_COURSE, 422)

    nothing_stored, meta = validate_paginated(
        client.list_rubric_scores({"assignment_id": assignment_id}, headers=COORDINATOR)
    )
    assert nothing_stored == [], "no refused score was persisted"
    assert meta["total_count"] == 0

    stored = validate_success(
        client.create_rubric_score(
            assignment_id, f.rubric_score_payload(outcomes[0]["id"], 3), headers=headers
        ),
        201,
    )
    assert_fields_equal(stored, points_possible=4, score_ratio_bp=7500, outcome_met=True)

    repeat = client.create_rubric_score(
        assignment_id, f.rubric_score_payload(outcomes[0]["id"], 4), headers=headers
    )
    validate_error(repeat, ApiErrorId.ERR_DUPLICATE_RUBRIC_SCORE, 409)

    rows, meta = validate_paginated(
        client.list_rubric_scores({"assignment_id": assignment_id}, headers=COORDINATOR)
    )
    assert ids_of(rows) == [stored["id"]], "the duplicate was refused, not merged"
    assert meta["total_count"] == 1
    assert_fields_equal(rows[0], points_awarded=3, score_ratio_bp=7500)


def test_completion_demands_every_outcome_and_an_agreeing_recommendation(
    client, an_accepted_assignment_and_a_foreign_outcome
):
    """One score short is incomplete; a PASS over 6500 basis points is inconsistent.

    PRD: "exactly one rubric score exists for **every** learning outcome of the
    claim's course, so a course with seven outcomes needs seven scores and six is
    `ERR_INCOMPLETE_RUBRIC`; and the submitted `recommendation` agrees with the
    recommendation the server computes for itself, or the request is
    `ERR_RECOMMENDATION_INCONSISTENT`." "`ASSIGNED` permits accept and decline;
    `ACCEPTED` permits rubric scoring and completion. Failures:
    `ERR_ASSIGNMENT_NOT_PENDING` and `ERR_ASSIGNMENT_NOT_ACCEPTED`, both 409."

    Design: Corner/errors/rubric_scoring_input_family_is_rejected_field_by_field
    """
    scenario = an_accepted_assignment_and_a_foreign_outcome
    assignment_id = scenario["assignment"]["id"]
    headers = make_assessor_headers(scenario["assessor"]["id"])
    outcomes = scenario["outcomes"]

    validate_success(
        client.create_rubric_score(
            assignment_id, f.rubric_score_payload(outcomes[0]["id"], 3), headers=headers
        ),
        201,
    )
    incomplete = client.complete_assignment(
        assignment_id, {"recommendation": Recommendation.FAIL}, headers=headers
    )
    validate_error(incomplete, ApiErrorId.ERR_INCOMPLETE_RUBRIC, 422)

    held = get_success_data(client.get_assignment(assignment_id, headers=COORDINATOR))
    assert_fields_equal(held, status=AssignmentStatus.ACCEPTED, verified_coverage_bp=None)
    open_claim = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(open_claim, assessment_status=AssessmentStatus.UNDER_ASSESSMENT)

    validate_success(
        client.create_rubric_score(
            assignment_id, f.rubric_score_payload(outcomes[1]["id"], 1), headers=headers
        ),
        201,
    )
    # (8000 * 7500 + 2000 * 2500) / 10000 == 6500, short of the 7000 threshold.
    inconsistent = client.complete_assignment(
        assignment_id, {"recommendation": Recommendation.PASS}, headers=headers
    )
    validate_error(inconsistent, ApiErrorId.ERR_RECOMMENDATION_INCONSISTENT, 422)

    completed = validate_success(
        client.complete_assignment(
            assignment_id, {"recommendation": Recommendation.FAIL}, headers=headers
        )
    )
    assert_fields_equal(
        completed,
        status=AssignmentStatus.SCORING_COMPLETE,
        verified_coverage_bp=6500,
        recommendation=Recommendation.FAIL,
    )

    scored = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(scored, assessment_status=AssessmentStatus.SCORED)
    assert_fields_equal(
        scored, verified_coverage_bp=6500, assessor_recommendation=Recommendation.FAIL
    )
    locked = get_success_data(
        client.get_portfolio(scenario["portfolio"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(locked, status=PortfolioStatus.LOCKED, verified_coverage_bp=6500)

    # Rung 17 (assignment state) outranks the duplicate-score rung, so a repeat score
    # on the finished assignment reports the state rather than the collision.
    late_score = client.create_rubric_score(
        assignment_id, f.rubric_score_payload(outcomes[0]["id"], 4), headers=headers
    )
    validate_error(late_score, ApiErrorId.ERR_ASSIGNMENT_NOT_ACCEPTED, 409)

    late_complete = client.complete_assignment(
        assignment_id, {"recommendation": Recommendation.FAIL}, headers=headers
    )
    validate_error(late_complete, ApiErrorId.ERR_ASSIGNMENT_NOT_ACCEPTED, 409)


@pytest.fixture
def two_programmes_and_four_students(client):
    """One programme that forbids portfolios, one that allows every source.

    S-1001 sits in the portfolio-less programme, S-1002 and S-1004 in the permissive
    one, and S-1003 is an `APPLICANT` who has not matriculated. S-1002 already holds
    a DRAFT portfolio claim on CS150, which is the row a `supersedes_claim_id` can
    point at while being anything but terminal.
    """
    no_portfolio = _program(
        client,
        program_code="BSCSNP",
        allowed_source_types=[
            SourceType.CREDIT_BY_EXAM,
            SourceType.MILITARY_TRAINING,
            SourceType.INDUSTRY_CREDENTIAL,
        ],
    )
    permissive = _program(client, program_code="BSITP")
    cs150 = _course(client, "CS150")
    cs999 = _course(
        client, "CS999", credits=3, learning_outcomes=_one_outcome("OCZ"), pla_eligible=False
    )
    s1001 = _student(client, no_portfolio["id"], student_number="S-1001")
    s1002 = _student(client, permissive["id"], student_number="S-1002")
    s1003 = _student(
        client,
        permissive["id"],
        student_number="S-1003",
        enrollment_status=EnrollmentStatus.APPLICANT,
    )
    s1004 = _student(client, permissive["id"], student_number="S-1004")
    draft = fx.new_claim(
        client,
        s1002["id"],
        cs150["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=6,
    )
    return {
        "no_portfolio": no_portfolio,
        "permissive": permissive,
        "cs150": cs150,
        "cs999": cs999,
        "s1001": s1001,
        "s1002": s1002,
        "s1003": s1003,
        "s1004": s1004,
        "draft": draft,
    }


def test_source_and_course_eligibility_answer_before_the_enrolment_gate(
    client, two_programmes_and_four_students
):
    """A forbidden source, an ineligible course and an applicant, each named exactly.

    PRD: "The claim's `source_type` is listed in the student's programme
    `allowed_source_types`, and the target course has `pla_eligible` true. Failures:
    `ERR_SOURCE_NOT_ALLOWED_BY_PROGRAM` and `ERR_COURSE_NOT_PLA_ELIGIBLE`, both 422.
    Applies to claim creation." "The student's `enrollment_status` is `MATRICULATED`
    and the programme's `status` is `ACTIVE`. Failures:
    `ERR_STUDENT_NOT_MATRICULATED` and `ERR_PROGRAM_INACTIVE`, both 409."

    Design: Corner/errors/claim_creation_eligibility_family_is_rejected_by_the_priority_ladder
    """
    scenario = two_programmes_and_four_students

    forbidden_source = client.create_claim(
        f.claim_payload(
            scenario["s1001"]["id"],
            scenario["cs150"]["id"],
            source_type=SourceType.PORTFOLIO,
            credits_requested=6,
        ),
        headers=make_student_headers(scenario["s1001"]["id"]),
    )
    validate_error(forbidden_source, ApiErrorId.ERR_SOURCE_NOT_ALLOWED_BY_PROGRAM, 422)

    ineligible_course = client.create_claim(
        f.claim_payload(
            scenario["s1004"]["id"],
            scenario["cs999"]["id"],
            source_type=SourceType.PORTFOLIO,
            credits_requested=3,
        ),
        headers=make_student_headers(scenario["s1004"]["id"]),
    )
    validate_error(ineligible_course, ApiErrorId.ERR_COURSE_NOT_PLA_ELIGIBLE, 422)

    # Rung 24 passes for this applicant — the programme allows portfolios and the
    # course is eligible — so the enrolment rung underneath is the one that answers.
    not_matriculated = client.create_claim(
        f.claim_payload(
            scenario["s1003"]["id"],
            scenario["cs150"]["id"],
            source_type=SourceType.PORTFOLIO,
            credits_requested=6,
        ),
        headers=make_student_headers(scenario["s1003"]["id"]),
    )
    validate_error(not_matriculated, ApiErrorId.ERR_STUDENT_NOT_MATRICULATED, 409)

    for student_key in ("s1001", "s1003", "s1004"):
        rows, meta = validate_paginated(
            client.list_claims(
                {"student_id": scenario[student_key]["id"]}, headers=COORDINATOR
            )
        )
        assert rows == [], "%s holds no claim after a refused creation" % student_key
        assert meta["total_count"] == 0

    everything, meta = validate_paginated(client.list_claims({}, headers=COORDINATOR))
    assert ids_of(everything) == [scenario["draft"]["id"]], "only the fixture's claim exists"
    assert meta["total_count"] == 1

    invoices, meta = validate_paginated(client.list_invoices({}, headers=COORDINATOR))
    assert invoices == [], "a refused creation never priced anything"
    assert meta["total_count"] == 0


def test_the_articulation_reference_family_is_checked_in_the_declared_order(
    client, two_programmes_and_four_students
):
    """A missing rule, a forbidden rule, an unresolvable rule and a live predecessor.

    PRD: "Every identifier referenced in the request body exists, resolved in the
    endpoint's declared field order." "On claim creation, `articulation_rule_id` is
    present for every `source_type` other than `PORTFOLIO` and absent for `PORTFOLIO`,
    and a supplied `supersedes_claim_id` names a claim of the same student and same
    course whose `assessment_status` is `DENIED_FINAL` or `WITHDRAWN`; failures are
    `ERR_ARTICULATION_RULE_REQUIRED`, `ERR_ARTICULATION_RULE_FORBIDDEN` and
    `ERR_SUPERSEDED_CLAIM_NOT_TERMINAL`, all 422."

    Design: Corner/errors/claim_creation_eligibility_family_is_rejected_by_the_priority_ladder
    """
    scenario = two_programmes_and_four_students
    recommendation = fx.published_recommendation(
        client,
        credential_code="ACE-MIL",
        source_type=SourceType.MILITARY_TRAINING,
        recommended_credits=6,
        recommended_level=CourseLevel.LOWER,
        effective_from="2026-01-01T00:00:00Z",
    )
    rule = fx.approved_rule(
        client,
        recommendation["id"],
        scenario["cs150"]["id"],
        awarded_credits=6,
        effective_from="2026-01-01T00:00:00Z",
    )
    student_id = scenario["s1002"]["id"]
    headers = make_student_headers(student_id)

    # Every non-`PORTFOLIO` payload here carries `attempt_date`, which S3.3 says "is
    # likewise required for every source other than `PORTFOLIO`": leaving it out would
    # break rung 8 as well and the ladder would answer with that lower rung instead.
    rule_missing = client.create_claim(
        f.claim_payload(
            student_id,
            scenario["cs150"]["id"],
            source_type=SourceType.MILITARY_TRAINING,
            credits_requested=6,
            attempt_date="2026-06-15T00:00:00Z",
        ),
        headers=headers,
    )
    validate_error(rule_missing, ApiErrorId.ERR_ARTICULATION_RULE_REQUIRED, 422)

    rule_forbidden = client.create_claim(
        f.claim_payload(
            student_id,
            scenario["cs150"]["id"],
            source_type=SourceType.PORTFOLIO,
            credits_requested=6,
            articulation_rule_id=rule["id"],
        ),
        headers=headers,
    )
    validate_error(rule_forbidden, ApiErrorId.ERR_ARTICULATION_RULE_FORBIDDEN, 422)

    # Rung 7 resolves the body reference before rung 9 judges its presence.
    rule_unresolvable = client.create_claim(
        f.claim_payload(
            student_id,
            scenario["cs150"]["id"],
            source_type=SourceType.MILITARY_TRAINING,
            credits_requested=6,
            articulation_rule_id=MISSING_ID,
            attempt_date="2026-06-15T00:00:00Z",
        ),
        headers=headers,
    )
    validate_error(rule_unresolvable, ApiErrorId.ERR_ARTICULATION_RULE_NOT_FOUND, 404)

    predecessor_alive = client.create_claim(
        f.claim_payload(
            student_id,
            scenario["cs150"]["id"],
            source_type=SourceType.PORTFOLIO,
            credits_requested=6,
            supersedes_claim_id=scenario["draft"]["id"],
        ),
        headers=headers,
    )
    validate_error(predecessor_alive, ApiErrorId.ERR_SUPERSEDED_CLAIM_NOT_TERMINAL, 422)

    mine, meta = validate_paginated(
        client.list_claims({"student_id": student_id}, headers=COORDINATOR)
    )
    assert ids_of(mine) == [scenario["draft"]["id"]], "four refusals created nothing"
    assert meta["total_count"] == 1

    accepted = validate_success(
        client.create_claim(
            f.claim_payload(
                scenario["s1004"]["id"],
                scenario["cs150"]["id"],
                source_type=SourceType.MILITARY_TRAINING,
                credits_requested=6,
                articulation_rule_id=rule["id"],
                attempt_date="2026-06-15T00:00:00Z",
            ),
            headers=make_student_headers(scenario["s1004"]["id"]),
        ),
        201,
    )
    assert_claim_dimensions(
        accepted,
        assessment_status=AssessmentStatus.DRAFT,
        fee_status=FeeStatus.UNBILLED,
        credit_status=CreditStatus.NOT_POSTED,
    )
    assert_fields_equal(accepted, articulation_rule_id=rule["id"], claim_number=1)


@pytest.fixture
def a_portfolio_claim_and_an_exam_claim(client):
    """One DRAFT portfolio claim carrying one artifact, plus an exam claim with none.

    MATH100 exists only to supply an outcome that belongs to no course under
    assessment here, which is what makes the mapping rung visible.
    """
    program = _program(client, program_code="BSITP", pla_max_credits=45)
    cs150 = _course(client, "CS150")
    cs160 = _course(client, "CS160", learning_outcomes=_one_outcome("OCY"))
    math100 = _course(
        client,
        "MATH100",
        credits=3,
        learning_outcomes=_one_outcome("OCX"),
        department_code="MATH",
    )
    student = _student(client, program["id"], student_number="S-1001")
    recommendation = fx.published_recommendation(
        client,
        credential_code="CLEP-CS",
        source_type=SourceType.CREDIT_BY_EXAM,
        recommended_credits=6,
        recommended_level=CourseLevel.LOWER,
        effective_from="2026-06-01T00:00:00Z",
    )
    rule = fx.approved_rule(
        client,
        recommendation["id"],
        cs160["id"],
        awarded_credits=6,
        effective_from="2026-06-01T00:00:00Z",
    )
    portfolio_claim = fx.new_claim(
        client,
        student["id"],
        cs150["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=6,
    )
    exam_claim = fx.new_claim(
        client,
        student["id"],
        cs160["id"],
        source_type=SourceType.CREDIT_BY_EXAM,
        credits_requested=6,
        articulation_rule_id=rule["id"],
        attempt_date="2026-06-15T00:00:00Z",
    )
    outcomes = fx.outcomes_of(client, cs150["id"])
    portfolio = fx.new_portfolio(client, portfolio_claim["id"], student["id"])
    artifact = fx.attach_artifact(
        client,
        portfolio["id"],
        student["id"],
        [f.mapping(outcomes[0]["id"], Alignment.PRIMARY)],
        title="Billing service",
    )
    return {
        "student": student,
        "cs150": cs150,
        "math_outcome": fx.outcomes_of(client, math100["id"])[0],
        "portfolio_claim": portfolio_claim,
        "exam_claim": exam_claim,
        "portfolio": portfolio,
        "artifact": artifact,
        "outcomes": outcomes,
    }


def test_a_portfolio_belongs_to_one_portfolio_claim_and_only_once(
    client, a_portfolio_claim_and_an_exam_claim
):
    """The wrong source, a duplicate, and a mapping that points outside the course.

    PRD: "(c) On portfolio creation, the target claim's `source_type` is `PORTFOLIO`
    and it has no portfolio yet; failures are `ERR_PORTFOLIO_NOT_ALLOWED_FOR_SOURCE`
    (422) and `ERR_PORTFOLIO_ALREADY_EXISTS` (409)." "Every `learning_outcome_id` must
    belong to the claim's course; one that does not is `ERR_OUTCOME_NOT_IN_COURSE`."

    Design: Corner/errors/portfolio_lifecycle_family_is_rejected_per_state
    """
    scenario = a_portfolio_claim_and_an_exam_claim
    headers = make_student_headers(scenario["student"]["id"])

    wrong_source = client.create_portfolio(
        f.portfolio_payload(
            scenario["exam_claim"]["id"], narrative="Exam score report attached"
        ),
        headers=headers,
    )
    validate_error(wrong_source, ApiErrorId.ERR_PORTFOLIO_NOT_ALLOWED_FOR_SOURCE, 422)
    rows, meta = validate_paginated(
        client.list_portfolios({"claim_id": scenario["exam_claim"]["id"]}, headers=COORDINATOR)
    )
    assert rows == [], "an exam claim never acquires a portfolio"
    assert meta["total_count"] == 0

    duplicate = client.create_portfolio(
        f.portfolio_payload(scenario["portfolio_claim"]["id"], narrative="Second attempt"),
        headers=headers,
    )
    validate_error(duplicate, ApiErrorId.ERR_PORTFOLIO_ALREADY_EXISTS, 409)
    rows, meta = validate_paginated(
        client.list_portfolios(
            {"claim_id": scenario["portfolio_claim"]["id"]}, headers=COORDINATOR
        )
    )
    assert ids_of(rows) == [scenario["portfolio"]["id"]], "still exactly one portfolio"
    assert meta["total_count"] == 1

    foreign_mapping = client.add_artifact(
        scenario["portfolio"]["id"],
        f.artifact_payload(
            [f.mapping(scenario["math_outcome"]["id"], Alignment.PRIMARY)],
            title="Algebra worksheet",
        ),
        headers=headers,
    )
    validate_error(foreign_mapping, ApiErrorId.ERR_OUTCOME_NOT_IN_COURSE, 422)

    portfolio = get_success_data(
        client.get_portfolio(scenario["portfolio"]["id"], headers=COORDINATOR)
    )
    # One PRIMARY mapping on the 8000-weight outcome, unmoved by three refusals.
    assert_fields_equal(
        portfolio,
        status=PortfolioStatus.DRAFT,
        artifact_count=1,
        provisional_coverage_bp=8000,
    )


def test_submission_flips_the_artifact_endpoints_and_then_submission_itself(
    client, a_portfolio_claim_and_an_exam_claim
):
    """After submit, add, delete and submit each refuse with their own code.

    PRD: "A portfolio in `DRAFT` or `REVISION_REQUESTED` may take artifact additions,
    artifact deletions and submission; `SUBMITTED`, `LOCKED` and `VOIDED` permit none
    of them." "Adding to or deleting from a portfolio in `SUBMITTED`, `LOCKED` or
    `VOIDED` is `ERR_PORTFOLIO_NOT_EDITABLE`." "submitting from `SUBMITTED`, `LOCKED`
    or `VOIDED` is `ERR_PORTFOLIO_NOT_SUBMITTABLE`."

    Design: Corner/errors/portfolio_lifecycle_family_is_rejected_per_state
    """
    scenario = a_portfolio_claim_and_an_exam_claim
    headers = make_student_headers(scenario["student"]["id"])
    portfolio_id = scenario["portfolio"]["id"]

    submitted = validate_success(client.submit_portfolio(portfolio_id, headers=headers))
    assert_fields_equal(
        submitted,
        status=PortfolioStatus.SUBMITTED,
        artifact_count=1,
        provisional_coverage_bp=8000,
    )
    assert submitted["submitted_at"] is not None, "submission stamps the logical clock"
    claim = get_success_data(
        client.get_claim(scenario["portfolio_claim"]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(claim, provisional_coverage_bp=8000)

    blocked_add = client.add_artifact(
        portfolio_id,
        f.artifact_payload(
            [f.mapping(scenario["outcomes"][1]["id"], Alignment.PRIMARY)],
            title="Late testing evidence",
        ),
        headers=headers,
    )
    validate_error(blocked_add, ApiErrorId.ERR_PORTFOLIO_NOT_EDITABLE, 409)

    blocked_delete = client.delete_artifact(
        portfolio_id, scenario["artifact"]["id"], headers=headers
    )
    validate_error(blocked_delete, ApiErrorId.ERR_PORTFOLIO_NOT_EDITABLE, 409)

    # The artifact floor is a lower rung, but state is judged first: a portfolio that
    # still holds its one artifact answers NOT_SUBMITTABLE rather than NO_ARTIFACTS.
    resubmit = client.submit_portfolio(portfolio_id, headers=headers)
    validate_error(resubmit, ApiErrorId.ERR_PORTFOLIO_NOT_SUBMITTABLE, 409)

    after = get_success_data(client.get_portfolio(portfolio_id, headers=COORDINATOR))
    assert_fields_equal(
        after,
        status=PortfolioStatus.SUBMITTED,
        artifact_count=1,
        provisional_coverage_bp=8000,
    )
    artifacts, meta = validate_paginated(
        client.list_artifacts({"portfolio_id": portfolio_id}, headers=COORDINATOR)
    )
    assert ids_of(artifacts) == [scenario["artifact"]["id"]], "the artifact survived"
    assert meta["total_count"] == 1


@pytest.fixture
def a_draft_recommendation_and_its_draft_rule(client):
    """A DRAFT recommendation and a DRAFT crosswalk rule pointing CS150's way."""
    course = _course(client, "CS150")
    recommendation = fx.new_recommendation(
        client,
        credential_code="CLEP-CS",
        source_type=SourceType.CREDIT_BY_EXAM,
        recommended_credits=6,
        recommended_level=CourseLevel.LOWER,
        effective_from="2026-06-01T00:00:00Z",
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
    return {"course": course, "recommendation": recommendation, "rule": rule}


def test_the_recommendation_gate_precedes_the_rules_whole_life(
    client, a_draft_recommendation_and_its_draft_rule
):
    """Review cannot start under a DRAFT recommendation, and publishing happens once.

    PRD: "Submitting a rule for review advances it `DRAFT → UNDER_REVIEW` and stamps
    the acting `X-User-ID` into `reviewed_by_user_id`; it requires the parent
    recommendation to be `PUBLISHED`". "It moves `status` from `DRAFT` to `PUBLISHED`
    and requires that `effective_to` is either null or strictly later than
    `effective_from`; publication increments the recommendation's `version` but
    deliberately leaves `terms_version` untouched."

    Design: Corner/errors/articulation_lifecycle_wrong_state_family_is_rejected
    """
    scenario = a_draft_recommendation_and_its_draft_rule
    assert_fields_equal(
        scenario["recommendation"],
        status=RecommendationStatus.DRAFT,
        version=1,
        terms_version=1,
        approved_rule_count=0,
    )
    assert_fields_equal(scenario["rule"], status=RuleStatus.DRAFT, version=1)
    for nulled in (
        "pinned_recommendation_version",
        "reviewed_by_user_id",
        "approved_by_user_id",
        "suspend_reason",
    ):
        assert scenario["rule"][nulled] is None, "%s starts null" % nulled

    # The design recipe expected this call to succeed while the recommendation was
    # still DRAFT; the PRD makes publication a precondition of review, so the rung
    # 15(b) recommendation arm answers instead.
    too_early = client.submit_rule_for_review(scenario["rule"]["id"], headers=OFFICER_REVIEWER)
    validate_error(too_early, ApiErrorId.ERR_RECOMMENDATION_NOT_PUBLISHED, 409)

    published = validate_success(
        client.publish_recommendation(
            scenario["recommendation"]["id"], headers=OFFICER_REVIEWER
        )
    )
    assert_fields_equal(
        published, status=RecommendationStatus.PUBLISHED, version=2, terms_version=1
    )

    again = client.publish_recommendation(
        scenario["recommendation"]["id"], headers=OFFICER_REVIEWER
    )
    validate_error(again, ApiErrorId.ERR_RECOMMENDATION_NOT_DRAFT, 409)

    rule = get_success_data(client.get_rule(scenario["rule"]["id"], headers=OFFICER_REVIEWER))
    assert_fields_equal(rule, status=RuleStatus.DRAFT, version=1)


def test_each_rule_transition_names_the_state_it_demands(
    client, a_draft_recommendation_and_its_draft_rule
):
    """Approve, suspend and reinstate refuse a DRAFT rule, each with its own code.

    PRD: "(b) The crosswalk rule's `status`, or the recommendation's `status`, is a
    declared from-state; failures are `ERR_RULE_NOT_DRAFT`,
    `ERR_RULE_NOT_UNDER_REVIEW`, `ERR_RULE_NOT_APPROVED`, `ERR_RULE_NOT_SUSPENDED`,
    `ERR_RECOMMENDATION_NOT_DRAFT` and `ERR_RECOMMENDATION_NOT_PUBLISHED`, all 409".
    "On success it pins `pinned_recommendation_version` to the recommendation's
    current `terms_version` — a counter this operation does not move, so a freshly
    approved rule is never stale".

    Design: Corner/errors/articulation_lifecycle_wrong_state_family_is_rejected
    """
    scenario = a_draft_recommendation_and_its_draft_rule
    rule_id = scenario["rule"]["id"]
    # Publishing first leaves the rule's own state as the only failing arm of rung
    # 15(b), so each refusal below is attributable to exactly one clause.
    published = validate_success(
        client.publish_recommendation(
            scenario["recommendation"]["id"], headers=OFFICER_REVIEWER
        )
    )
    assert published["version"] == 2

    not_under_review = client.approve_rule(
        rule_id, {"expected_recommendation_version": 2}, headers=OFFICER_APPROVER
    )
    validate_error(not_under_review, ApiErrorId.ERR_RULE_NOT_UNDER_REVIEW, 409)

    not_approved = client.suspend_rule(rule_id, headers=OFFICER_REVIEWER)
    validate_error(not_approved, ApiErrorId.ERR_RULE_NOT_APPROVED, 409)

    not_suspended = client.reinstate_rule(rule_id, headers=OFFICER_REVIEWER)
    validate_error(not_suspended, ApiErrorId.ERR_RULE_NOT_SUSPENDED, 409)

    parked = get_success_data(client.get_rule(rule_id, headers=OFFICER_REVIEWER))
    assert_fields_equal(parked, status=RuleStatus.DRAFT, version=1)

    reviewing = validate_success(
        client.submit_rule_for_review(rule_id, headers=OFFICER_REVIEWER)
    )
    assert_fields_equal(
        reviewing,
        status=RuleStatus.UNDER_REVIEW,
        reviewed_by_user_id=OFFICER_REVIEWER_USER_ID,
    )

    not_draft = client.submit_rule_for_review(rule_id, headers=OFFICER_REVIEWER)
    validate_error(not_draft, ApiErrorId.ERR_RULE_NOT_DRAFT, 409)

    approved = validate_success(
        client.approve_rule(
            rule_id, {"expected_recommendation_version": 2}, headers=OFFICER_APPROVER
        )
    )
    assert_fields_equal(
        approved,
        status=RuleStatus.APPROVED,
        approved_by_user_id=OFFICER_APPROVER_USER_ID,
        pinned_recommendation_version=1,
        suspend_reason=None,
    )

    recommendation = get_success_data(
        client.get_recommendation(scenario["recommendation"]["id"], headers=OFFICER_REVIEWER)
    )
    assert_fields_equal(recommendation, approved_rule_count=1, terms_version=1, version=3)


@pytest.fixture
def a_paid_claim_with_no_usable_assessor(client):
    """A paid, submitted CS claim facing an INACTIVE CS assessor and an active MATH one.

    The invoice is paid rather than waived so the fee gate stays satisfied through the
    revision cycle in the second test, where the recompute finds the same total and
    leaves `fee_status` on `PAID`.
    """
    program = _program(client, program_code="BSCS")
    course = _course(client, "CS150")
    student = _student(client, program["id"], student_number="S-1001")
    inactive_cs = fx.new_assessor(
        client,
        employee_number="E-9001",
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=3,
        status=AssessorStatus.INACTIVE,
    )
    active_math = fx.new_assessor(
        client,
        employee_number="E-9002",
        department_code="MATH",
        credential_rank=2,
        max_concurrent_assignments=3,
        status=AssessorStatus.ACTIVE,
    )
    parts = _settled_portfolio_claim(
        client,
        student["id"],
        course,
        credits_requested=6,
        alignments=[Alignment.PRIMARY, Alignment.SUPPORTING],
        settle="pay",
    )
    return {
        "student": student,
        "course": course,
        "inactive_cs": inactive_cs,
        "active_math": active_math,
        "claim": parts["claim"],
        "portfolio": parts["portfolio"],
        "invoice": parts["invoice"],
    }


def test_no_candidate_survives_the_filter_so_each_path_says_why(
    client, a_paid_claim_with_no_usable_assessor
):
    """Auto selection reports an empty pool; the two named candidates report themselves.

    PRD: "A candidate failing only the `status` predicate is `ERR_ASSESSOR_INACTIVE`
    (409)." "Any other failing predicate — a department mismatch, a `credential_rank`
    below the course-level floor, or for a reviewer a false `appeal_panel_member` — is
    `ERR_ASSESSOR_NOT_ELIGIBLE` (422)." "An empty pool on a directly requested
    assignment is `ERR_NO_ELIGIBLE_ASSESSOR` (409)."

    Design: Corner/errors/assessor_eligibility_family_is_rejected_before_any_assignment_exists
    """
    scenario = a_paid_claim_with_no_usable_assessor
    claim_id = scenario["claim"]["id"]
    settled = get_success_data(client.get_invoice(scenario["invoice"]["id"], headers=COORDINATOR))
    assert_fields_equal(settled, fee_status=FeeStatus.PAID, balance_due_cents=0)

    empty_pool = client.create_assignment(claim_id, headers=COORDINATOR)
    validate_error(empty_pool, ApiErrorId.ERR_NO_ELIGIBLE_ASSESSOR, 409)

    named_inactive = client.create_assignment(
        claim_id, {"assessor_id": scenario["inactive_cs"]["id"]}, headers=COORDINATOR
    )
    validate_error(named_inactive, ApiErrorId.ERR_ASSESSOR_INACTIVE, 409)

    wrong_department = client.create_assignment(
        claim_id, {"assessor_id": scenario["active_math"]["id"]}, headers=COORDINATOR
    )
    validate_error(wrong_department, ApiErrorId.ERR_ASSESSOR_NOT_ELIGIBLE, 422)

    # Rung 7 resolves the body reference ahead of every eligibility predicate.
    unresolvable = client.create_assignment(
        claim_id, {"assessor_id": MISSING_ID}, headers=COORDINATOR
    )
    validate_error(unresolvable, ApiErrorId.ERR_ASSESSOR_NOT_FOUND, 404)

    claim = get_success_data(client.get_claim(claim_id, headers=COORDINATOR))
    assert_claim_dimensions(claim, assessment_status=AssessmentStatus.SUBMITTED)
    assert claim["hold_reason"] is None, "a refused direct request parks nothing"

    rows, meta = validate_paginated(
        client.list_assignments({"claim_id": claim_id}, headers=COORDINATOR)
    )
    assert rows == [], "no shell assignment row is left behind"
    assert meta["total_count"] == 0
    for assessor_key in ("inactive_cs", "active_math"):
        assessor = get_success_data(
            client.get_assessor(scenario[assessor_key]["id"], headers=COORDINATOR)
        )
        assert_fields_equal(assessor, active_assignment_count=0)


def test_a_reactivated_assessor_is_selectable_once_and_then_excluded_forever(
    client, a_paid_claim_with_no_usable_assessor
):
    """One activation opens the pool; one revision cycle closes it permanently.

    PRD: "And they must not be the `assessor_id` of **any** assignment of this claim in
    any status whatsoever — per-claim exclusion is permanent, so an assessor who
    declined, was revoked, or already completed a scoring round on this claim can never
    be assigned to it again." "One who has ever held an assignment on this claim is
    `ERR_ASSESSOR_ALREADY_ASSIGNED` (409)."

    Design: Corner/errors/assessor_eligibility_family_is_rejected_before_any_assignment_exists
    """
    scenario = a_paid_claim_with_no_usable_assessor
    claim_id = scenario["claim"]["id"]
    assessor_id = scenario["inactive_cs"]["id"]

    reactivated = validate_success(
        client.patch_assessor(
            assessor_id, {"status": AssessorStatus.ACTIVE}, headers=COORDINATOR
        )
    )
    assert_fields_equal(reactivated, status=AssessorStatus.ACTIVE, active_assignment_count=0)

    assignment = validate_success(
        client.create_assignment(claim_id, headers=COORDINATOR), 201
    )
    assert_fields_equal(
        assignment,
        assessor_id=assessor_id,
        status=AssignmentStatus.ASSIGNED,
        selection_reason=SelectionReason.AUTO_SELECTED,
    )
    under_assessment = get_success_data(client.get_claim(claim_id, headers=COORDINATOR))
    assert_claim_dimensions(
        under_assessment, assessment_status=AssessmentStatus.UNDER_ASSESSMENT
    )

    validate_success(
        client.request_revision(
            claim_id, {"revision_note": "Attach the deployment evidence"}, headers=COORDINATOR
        )
    )
    revoked = get_success_data(client.get_assignment(assignment["id"], headers=COORDINATOR))
    assert_fields_equal(revoked, status=AssignmentStatus.REVOKED)

    student_headers = make_student_headers(scenario["student"]["id"])
    validate_success(client.submit_portfolio(scenario["portfolio"]["id"], headers=student_headers))
    resubmitted = validate_success(client.submit_claim(claim_id, headers=student_headers))
    assert_claim_dimensions(resubmitted, assessment_status=AssessmentStatus.SUBMITTED)
    # The recompute finds the same line set, so net paid cash still covers the total.
    assert_claim_dimensions(resubmitted, fee_status=FeeStatus.PAID)

    excluded = client.create_assignment(
        claim_id, {"assessor_id": assessor_id}, headers=COORDINATOR
    )
    validate_error(excluded, ApiErrorId.ERR_ASSESSOR_ALREADY_ASSIGNED, 409)

    pool_now_empty = client.create_assignment(claim_id, headers=COORDINATOR)
    validate_error(pool_now_empty, ApiErrorId.ERR_NO_ELIGIBLE_ASSESSOR, 409)

    rows, meta = validate_paginated(
        client.list_assignments({"claim_id": claim_id}, headers=COORDINATOR)
    )
    assert ids_of(rows) == [assignment["id"]], "the revoked row is the only assignment"
    assert meta["total_count"] == 1


@pytest.fixture
def an_awarded_claim_and_a_draft_one(client):
    """S-1001 holds an AWARDED, unposted claim; S-1002 holds a DRAFT one on the same course.

    Two states, two families of refusal: the terminal-claim rung answers for the first
    and the from-state rung answers for the second.
    """
    program = _program(client, program_code="BSCS")
    course = _course(client, "CS150")
    awarding_student = _student(client, program["id"], student_number="S-1001")
    drafting_student = _student(client, program["id"], student_number="S-1002")
    assessor = fx.new_assessor(
        client,
        employee_number="E-9001",
        department_code="CS",
        credential_rank=2,
        max_concurrent_assignments=3,
    )
    parts = _settled_portfolio_claim(client, awarding_student["id"], course, credits_requested=6)
    assignment = fx.assign_assessor(client, parts["claim"]["id"], assessor["id"])
    fx.accept_assignment(client, assignment["id"], assessor["id"])
    fx.score_all_outcomes(
        client, assignment["id"], assessor["id"], parts["outcomes"], [4, 4]
    )
    fx.complete_assignment(client, assignment["id"], assessor["id"], Recommendation.PASS)
    awarded = fx.award_claim(
        client, parts["claim"]["id"], awarding_student["id"], credits_awarded=6
    )
    draft = fx.new_claim(
        client,
        drafting_student["id"],
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=6,
    )
    return {
        "program": program,
        "course": course,
        "awarding_student": awarding_student,
        "drafting_student": drafting_student,
        "assessor": assessor,
        "assignment": assignment,
        "awarded": awarded,
        "draft": draft,
    }


def test_the_credit_dimension_posts_once_and_reverses_only_after(
    client, an_awarded_claim_and_a_draft_one
):
    """Reversal is refused before posting, posting is refused after it, and both name why.

    PRD: "the `credit_status` is `NOT_POSTED`, or `ERR_CREDIT_ALREADY_POSTED`". "A
    successful posting sets `credit_status` to `POSTED`, records `posted_term`, and sets
    `posted_credits` to `credits_awarded`." "It requires `credit_status` to be `POSTED`,
    or the request is `ERR_CREDIT_NOT_POSTED`. It sets `credit_status` to `REVERSED` and
    `posted_credits` to 0, subtracts the reversed credits from `pla_credits_posted` and
    returns them to `pla_credits_awarded`".

    Design: Corner/errors/claim_wrong_state_family_after_posting_is_rejected
    """
    scenario = an_awarded_claim_and_a_draft_one
    claim_id = scenario["awarded"]["id"]
    student_id = scenario["awarding_student"]["id"]
    assert_claim_dimensions(
        scenario["awarded"],
        assessment_status=AssessmentStatus.AWARDED,
        credit_status=CreditStatus.NOT_POSTED,
    )
    before = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    assert_ledger(before, reserved=0, awarded=6, posted=0)

    too_early = client.reverse_transcript(
        claim_id, {"reversal_reason": "Registrar keying error"}, headers=REGISTRAR
    )
    validate_error(too_early, ApiErrorId.ERR_CREDIT_NOT_POSTED, 409)

    posted = validate_success(
        client.post_transcript(claim_id, {"posted_term": "2026FA"}, headers=REGISTRAR)
    )
    assert_claim_dimensions(posted, credit_status=CreditStatus.POSTED)
    assert_fields_equal(posted, posted_term="2026FA", posted_credits=6, credits_awarded=6)
    moved = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    assert_ledger(moved, reserved=0, awarded=0, posted=6)

    repeat = client.post_transcript(claim_id, {"posted_term": "2027SP"}, headers=REGISTRAR)
    validate_error(repeat, ApiErrorId.ERR_CREDIT_ALREADY_POSTED, 409)
    unchanged = get_success_data(client.get_claim(claim_id, headers=COORDINATOR))
    assert_fields_equal(unchanged, posted_term="2026FA", posted_credits=6)

    reversed_now = validate_success(
        client.reverse_transcript(
            claim_id, {"reversal_reason": "Registrar keying error"}, headers=REGISTRAR
        )
    )
    assert_claim_dimensions(
        reversed_now,
        assessment_status=AssessmentStatus.AWARDED,
        credit_status=CreditStatus.REVERSED,
    )
    assert_fields_equal(reversed_now, posted_credits=0)
    after = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    assert_ledger(after, reserved=0, awarded=6, posted=0)

    audit = get_success_data(client.get_graduation_audit(student_id, headers=REGISTRAR))
    assert_audit(audit, pla_credits_posted=0, pla_credits_awarded=6, upper_division_pla_posted=0)


def test_an_awarded_claim_is_terminal_before_any_from_state_is_read(
    client, an_awarded_claim_and_a_draft_one
):
    """Five verbs meet the terminal rung; award and completion fall through to their own.

    PRD: "The claim's `assessment_status` is none of `AWARDED`, `DENIED_FINAL`,
    `WITHDRAWN`. Failure: `ERR_CLAIM_ALREADY_TERMINAL` (409). Applies to submitting a
    claim, withdrawing a claim, requesting a revision, denying a claim, creating an
    assessor assignment for a claim, and filing an appeal." "Scoring is permitted only
    while the assignment's `status` is `ACCEPTED`; from any other status the attempt is
    `ERR_ASSIGNMENT_NOT_ACCEPTED`."

    Design: Corner/errors/claim_wrong_state_family_after_posting_is_rejected
    """
    scenario = an_awarded_claim_and_a_draft_one
    claim_id = scenario["awarded"]["id"]
    student_headers = make_student_headers(scenario["awarding_student"]["id"])

    # The design recipe expected ERR_CLAIM_NOT_UNDER_ASSESSMENT, ERR_CLAIM_NOT_SCORED and
    # ERR_CLAIM_NOT_DENIED here, but rung 14 lists request-revision, denial and appeal
    # filing explicitly, so on a terminal claim it answers before rung 15 is consulted.
    terminal_probes = [
        ("submit", client.submit_claim(claim_id, headers=student_headers)),
        (
            "withdraw",
            client.withdraw_claim(
                claim_id, {"withdraw_reason": "Changed my mind"}, headers=student_headers
            ),
        ),
        (
            "request-revision",
            client.request_revision(
                claim_id, {"revision_note": "Reopen"}, headers=COORDINATOR
            ),
        ),
        (
            "deny",
            client.deny_claim(claim_id, {"denial_reason": "Reconsidered"}, headers=COORDINATOR),
        ),
        (
            "appeal",
            client.create_appeal(
                {"claim_id": claim_id, "grounds": "Wanted more credits"},
                headers=student_headers,
            ),
        ),
        (
            "assignment",
            client.create_assignment(
                claim_id, {"assessor_id": scenario["assessor"]["id"]}, headers=COORDINATOR
            ),
        ),
    ]
    for label, response in terminal_probes:
        body = validate_error(response, ApiErrorId.ERR_CLAIM_ALREADY_TERMINAL, 409)
        assert body["error_id"] == ApiErrorId.ERR_CLAIM_ALREADY_TERMINAL, (
            "%s on an AWARDED claim must report the terminal rung" % label
        )

    # Awarding is absent from rung 14's list, so it falls through to its own from-state.
    student = get_success_data(
        client.get_student(scenario["awarding_student"]["id"], headers=COORDINATOR)
    )
    not_scored = client.award_claim(
        claim_id,
        {"expected_student_version": student["version"], "credits_awarded": 6},
        headers=COORDINATOR,
    )
    validate_error(not_scored, ApiErrorId.ERR_CLAIM_NOT_SCORED, 409)

    finished = client.complete_assignment(
        scenario["assignment"]["id"],
        {"recommendation": Recommendation.PASS},
        headers=make_assessor_headers(scenario["assessor"]["id"]),
    )
    validate_error(finished, ApiErrorId.ERR_ASSIGNMENT_NOT_ACCEPTED, 409)

    claim = get_success_data(client.get_claim(claim_id, headers=COORDINATOR))
    assert_claim_dimensions(
        claim,
        assessment_status=AssessmentStatus.AWARDED,
        credit_status=CreditStatus.NOT_POSTED,
    )
    assert_fields_equal(claim, credits_awarded=6, appeal_count=0)
    appeals, meta = validate_paginated(
        client.list_appeals({"claim_id": claim_id}, headers=COORDINATOR)
    )
    assert appeals == [], "a refused filing creates no appeal"
    assert meta["total_count"] == 0


def test_a_draft_claim_names_the_state_each_verb_demanded(
    client, an_awarded_claim_and_a_draft_one
):
    """Four verbs on an untouched DRAFT claim, four distinct from-state codes.

    PRD: "(a) The claim's `assessment_status` is a declared from-state of the requested
    assessment transition; failures are `ERR_CLAIM_NOT_DRAFT`, `ERR_CLAIM_NOT_SUBMITTED`,
    `ERR_CLAIM_NOT_UNDER_ASSESSMENT`, `ERR_CLAIM_NOT_SCORED`, `ERR_CLAIM_NOT_DENIED` and
    `ERR_CLAIM_NOT_AWARDED`, all 409, and this applies to submitting, requesting a
    revision, creating an assessor assignment, awarding, denying, filing an appeal,
    posting to the transcript and reversing a posting."

    Design: Corner/errors/claim_wrong_state_family_after_posting_is_rejected
    """
    scenario = an_awarded_claim_and_a_draft_one
    claim_id = scenario["draft"]["id"]
    student_headers = make_student_headers(scenario["drafting_student"]["id"])
    assert_claim_dimensions(
        scenario["draft"],
        assessment_status=AssessmentStatus.DRAFT,
        fee_status=FeeStatus.UNBILLED,
        credit_status=CreditStatus.NOT_POSTED,
    )

    # The fee gate sits at rung 42, far below the from-state rung, so an unbilled DRAFT
    # claim still answers about its assessment state rather than about money.
    not_submitted = client.create_assignment(
        claim_id, {"assessor_id": scenario["assessor"]["id"]}, headers=COORDINATOR
    )
    validate_error(not_submitted, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED, 409)

    not_under_assessment = client.request_revision(
        claim_id, {"revision_note": "Reopen"}, headers=COORDINATOR
    )
    validate_error(not_under_assessment, ApiErrorId.ERR_CLAIM_NOT_UNDER_ASSESSMENT, 409)

    not_denied = client.create_appeal(
        {"claim_id": claim_id, "grounds": "Wanted more credits"}, headers=student_headers
    )
    validate_error(not_denied, ApiErrorId.ERR_CLAIM_NOT_DENIED, 409)

    not_awarded = client.post_transcript(
        claim_id, {"posted_term": "2026FA"}, headers=REGISTRAR
    )
    validate_error(not_awarded, ApiErrorId.ERR_CLAIM_NOT_AWARDED, 409)

    claim = get_success_data(client.get_claim(claim_id, headers=COORDINATOR))
    assert_claim_dimensions(
        claim,
        assessment_status=AssessmentStatus.DRAFT,
        fee_status=FeeStatus.UNBILLED,
        credit_status=CreditStatus.NOT_POSTED,
    )
    student = get_success_data(
        client.get_student(scenario["drafting_student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(student, reserved=0, awarded=0, posted=0, fee_paid_net_cents=0)
    rows, meta = validate_paginated(
        client.list_assignments({"claim_id": claim_id}, headers=COORDINATOR)
    )
    assert rows == [], "no assignment survives a from-state refusal"
    assert meta["total_count"] == 0


@pytest.fixture
def a_scored_upper_division_credential_claim(client):
    """A SCORED INDUSTRY_CREDENTIAL claim for 3 credits against an UPPER course.

    The rule grants exactly the 3 credits requested and the recommendation is `UPPER`,
    so rung 37 is satisfied on the way in and each test below breaks one clause of it.
    """
    program = _program(client, program_code="BSCSU", pla_upper_division_max_credits=3)
    course = _course(
        client,
        "CS350",
        credits=6,
        learning_outcomes=_one_outcome("OCU"),
        level=CourseLevel.UPPER,
    )
    student = _student(client, program["id"], student_number="S-1001")
    assessor = fx.new_assessor(
        client,
        employee_number="E-9001",
        department_code="CS",
        credential_rank=3,
        max_concurrent_assignments=3,
    )
    recommendation = fx.published_recommendation(
        client,
        credential_code="NCCRS-SEC",
        source_type=SourceType.INDUSTRY_CREDENTIAL,
        recommended_credits=3,
        recommended_level=CourseLevel.UPPER,
        effective_from="2026-06-01T00:00:00Z",
    )
    rule = fx.approved_rule(
        client,
        recommendation["id"],
        course["id"],
        awarded_credits=3,
        effective_from="2026-06-01T00:00:00Z",
    )
    claim = fx.new_claim(
        client,
        student["id"],
        course["id"],
        source_type=SourceType.INDUSTRY_CREDENTIAL,
        credits_requested=3,
        articulation_rule_id=rule["id"],
        attempt_date="2026-06-15T00:00:00Z",
    )
    fx.submit_claim(client, claim["id"], student["id"])
    invoice = fx.invoice_for_claim(client, claim["id"])
    _waive(client, invoice["id"])
    outcomes = fx.outcomes_of(client, course["id"])
    scored = fx.scored_claim(
        client, claim["id"], assessor["id"], outcomes, [4], Recommendation.PASS
    )
    return {
        "program": program,
        "course": course,
        "student": student,
        "assessor": assessor,
        "recommendation": recommendation,
        "rule": rule,
        "claim": scored,
    }


def test_an_amended_level_makes_the_pinned_crosswalk_refuse_the_award(
    client, a_scored_upper_division_credential_claim
):
    """A rule re-pinned to LOWER terms cannot buy an UPPER course.

    PRD: "`credits_awarded` is at most the pinned rule's `awarded_credits`, and the
    claim's course level matches the rule's recommended level. Failures:
    `ERR_AWARD_EXCEEDS_RECOMMENDATION` and `ERR_LEVEL_MISMATCH`, both 422." "It
    advances `SUSPENDED → APPROVED`, requires the parent recommendation to be
    `PUBLISHED`, re-runs the window-exclusivity check against sibling `APPROVED`
    rules, clears `suspend_reason` to null, and **re-pins
    `pinned_recommendation_version` to the recommendation's current `terms_version`**"

    Design: Corner/errors/award_limit_family_is_rejected_by_recommendation_then_level_then_cap
    """
    scenario = a_scored_upper_division_credential_claim
    assert_fields_equal(scenario["rule"], awarded_credits=3, pinned_recommendation_version=1)
    assert_fields_equal(scenario["course"], credits=6, level=CourseLevel.UPPER)
    assert_claim_dimensions(scenario["claim"], assessment_status=AssessmentStatus.SCORED)
    assert_fields_equal(
        scenario["claim"],
        credits_requested=3,
        verified_coverage_bp=10000,
        assessor_recommendation=Recommendation.PASS,
        credits_awarded=None,
    )

    # The level clause cannot be broken at setup time, because review demands an UPPER
    # recommendation for an UPPER course. Suspending, amending and reinstating is the
    # route that leaves an APPROVED rule with a current pin onto LOWER terms.
    validate_success(client.suspend_rule(scenario["rule"]["id"], headers=OFFICER_REVIEWER))
    amended = validate_success(
        client.patch_recommendation(
            scenario["recommendation"]["id"],
            {"recommended_level": CourseLevel.LOWER},
            headers=OFFICER_REVIEWER,
        )
    )
    assert_fields_equal(
        amended,
        recommended_level=CourseLevel.LOWER,
        status=RecommendationStatus.PUBLISHED,
        terms_version=2,
    )
    reinstated = validate_success(
        client.reinstate_rule(scenario["rule"]["id"], headers=OFFICER_REVIEWER)
    )
    assert_fields_equal(
        reinstated,
        status=RuleStatus.APPROVED,
        pinned_recommendation_version=2,
        suspend_reason=None,
    )

    student = get_success_data(client.get_student(scenario["student"]["id"], headers=COORDINATOR))
    mismatch = client.award_claim(
        scenario["claim"]["id"],
        {"expected_student_version": student["version"], "credits_awarded": 3},
        headers=COORDINATOR,
    )
    validate_error(mismatch, ApiErrorId.ERR_LEVEL_MISMATCH, 422)

    held = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(held, assessment_status=AssessmentStatus.SCORED)
    assert_fields_equal(held, credits_awarded=None)
    unchanged = get_success_data(
        client.get_student(scenario["student"]["id"], headers=COORDINATOR)
    )
    assert_ledger(unchanged, reserved=3, awarded=0, posted=0, upper_division_committed=3)


def test_the_upper_division_sub_cap_speaks_only_after_the_crosswalk_passes(
    client, a_scored_upper_division_credential_claim
):
    """A sub-cap of 1 refuses the whole 3 credits; restored to 3 it grants them.

    PRD: "For an `UPPER`-level course, `credits_awarded` is at most
    `pla_upper_division_max_credits` minus the student's `pla_upper_division_committed`.
    Failure: `ERR_UPPER_DIVISION_CAP_EXCEEDED` (409)." "And for an `UPPER`-level course,
    `credits_awarded` plus the student's `pla_upper_division_committed` reduced by this
    claim's own `credits_requested` must not exceed the programme's
    `pla_upper_division_max_credits`."

    Design: Corner/errors/award_limit_family_is_rejected_by_recommendation_then_level_then_cap
    """
    scenario = a_scored_upper_division_credential_claim
    claim_id = scenario["claim"]["id"]
    student_id = scenario["student"]["id"]

    tightened = validate_success(
        client.patch_program(
            scenario["program"]["id"],
            {"pla_upper_division_max_credits": 1},
            headers=COORDINATOR,
        )
    )
    assert_fields_equal(tightened, pla_upper_division_max_credits=1)

    student = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    # 3 awarded plus 3 committed less this claim's own 3 requested is 3, above the 1.
    over_sub_cap = client.award_claim(
        claim_id,
        {"expected_student_version": student["version"], "credits_awarded": 3},
        headers=COORDINATOR,
    )
    validate_error(over_sub_cap, ApiErrorId.ERR_UPPER_DIVISION_CAP_EXCEEDED, 409)

    refused = get_success_data(client.get_claim(claim_id, headers=COORDINATOR))
    assert_claim_dimensions(refused, assessment_status=AssessmentStatus.SCORED)
    assert_fields_equal(refused, credits_awarded=None)
    assert_ledger(
        get_success_data(client.get_student(student_id, headers=COORDINATOR)),
        reserved=3,
        awarded=0,
        upper_division_committed=3,
    )

    restored = validate_success(
        client.patch_program(
            scenario["program"]["id"],
            {"pla_upper_division_max_credits": 3},
            headers=COORDINATOR,
        )
    )
    assert_fields_equal(restored, pla_upper_division_max_credits=3)

    awarded = fx.award_claim(client, claim_id, student_id, credits_awarded=3)
    assert_claim_dimensions(awarded, assessment_status=AssessmentStatus.AWARDED)
    assert_fields_equal(awarded, credits_awarded=3)
    ledger = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    assert_ledger(ledger, reserved=0, awarded=3, posted=0, upper_division_committed=3)

    audit = get_success_data(client.get_graduation_audit(student_id, headers=REGISTRAR))
    assert_audit(
        audit,
        upper_division_remaining=0,
        upper_division_pla_posted=0,
        pla_credits_awarded=3,
        pla_credits_posted=0,
    )
