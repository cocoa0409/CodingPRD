"""Entity-level corners: creation, retrieval, listing, defaults and identity.

Each test here pins one row's declared field behaviour — what the server computes,
what it defaults, what it refuses and what it never lets the client dictate.
"""

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
    assert_fields_equal,
    assert_instant_shape,
    assert_only_id_and_created_at,
    ids_of,
    parse_instant,
)
from test_helpers.test_users import COORDINATOR, OFFICER, REGISTRAR, make_student_headers
from test_helpers.types import (
    Alignment,
    AssessmentStatus,
    CourseLevel,
    CreditStatus,
    EnrollmentStatus,
    FeeStatus,
    PortfolioStatus,
    PriorityTier,
    ProgramStatus,
    RuleStatus,
    SourceType,
)

_CS150_OUTCOMES = [
    {
        "outcome_code": "OC1",
        "description": "Design a program",
        "weight_bp": 8000,
        "mastery_threshold_bp": 7000,
    },
    {
        "outcome_code": "OC2",
        "description": "Test a program",
        "weight_bp": 2000,
        "mastery_threshold_bp": 7000,
    },
]


def test_program_creation_computes_the_cap_from_the_binding_arm(client):
    """The percentage arm binds at 30 even though the flat arm allows 45.

    PRD: "The programme's `effective_pla_cap_credits` is computed at registration and
    recomputed on every amendment." "Two further fields are optional at
    registration: `pla_pass_threshold_bp`, which defaults to null and when supplied
    must be from 1 through 10000, and `status`, which defaults to `ACTIVE`".

    Design: Corner/entities/program_creation_computes_effective_pla_cap_from_the_binding_arm
    """
    program = validate_success(
        client.create_program(
            f.program_payload(
                program_code="BSIT",
                total_credits_required=120,
                residency_min_credits=30,
                pla_max_credits=45,
                pla_max_pct_bp=2500,
                pla_upper_division_max_credits=6,
            ),
            headers=COORDINATOR,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        program,
        program_code="BSIT",
        total_credits_required=120,
        pla_max_credits=45,
        pla_max_pct_bp=2500,
        effective_pla_cap_credits=30,
        status=ProgramStatus.ACTIVE,
        version=1,
    )
    assert program["pla_pass_threshold_bp"] is None, "the pass threshold defaults to null"
    assert isinstance(program["id"], str) and program["id"], "id must be a server-minted string"
    # S2.4 fixes only the rendering of `created_at` — "ISO 8601 UTC timestamps with
    # three fractional digits" — and S2.5 scopes the logical clock to "deadline,
    # validity-window and service-level comparisons", so the stamp's source is open.
    assert_instant_shape(program["created_at"], "created_at")


def test_course_retrieval_returns_stored_data_and_the_derived_outcome_count(client):
    """`outcome_count` is derived from the inline outcome set, never supplied.

    PRD: "One learning outcome row is created per entry, and the course's
    `outcome_count` is set to the number created." "Each `weight_bp` is from 1 through
    10000, and **the `weight_bp` values of all outcomes belonging to one course must
    total exactly 10000**".

    Design: Corner/entities/course_retrieval_returns_stored_data_and_outcome_count
    """
    created = fx.new_course(
        client,
        course_code="CS150",
        department_code="CS",
        credits=6,
        level=CourseLevel.LOWER,
        learning_outcomes=_CS150_OUTCOMES,
    )
    course = validate_success(client.get_course(created["id"], headers=COORDINATOR))
    assert_fields_equal(
        course,
        course_code="CS150",
        credits=6,
        level=CourseLevel.LOWER,
        pla_eligible=True,
        outcome_count=2,
    )

    response = client.list_learning_outcomes({"course_id": course["id"]}, headers=COORDINATOR)
    rows, meta = validate_paginated(response)
    assert len(rows) == 2 and meta["total_count"] == 2, "one outcome row per inline entry"
    first = rows[0]
    assert_fields_equal(
        first,
        course_id=course["id"],
        outcome_code="OC1",
        weight_bp=8000,
        mastery_threshold_bp=7000,
    )
    assert sum(row["weight_bp"] for row in rows) == 10000


def test_claim_listing_paginates_in_created_at_then_claim_number_order(client):
    """Three claims page as 1,2 then 3, with `total_count` fixed at 3.

    PRD: "sorted by `created_at` ascending then `claim_number` ascending, which is
    exactly the total order the unblock waterfall of §3.8 walks." "`total_count`
    counts the records matching the filter before pagination is applied; `has_more`
    is true when records remain beyond the current window."

    Design: Corner/entities/pla_claims_listing_paginates_in_created_at_then_claim_number_order
    """
    program = fx.new_program(client, program_code="BSCS")
    student = fx.new_student(client, program["id"])
    claims = []
    for code in ("CS150", "CS160", "CS170"):
        course = fx.new_course(
            client,
            course_code=code,
            credits=3,
            level=CourseLevel.LOWER,
            learning_outcomes=[f.outcome_payload("OC1", 10000, mastery_threshold_bp=7000)],
        )
        claims.append(
            fx.new_claim(
                client,
                student["id"],
                course["id"],
                source_type=SourceType.PORTFOLIO,
                credits_requested=3,
            )
        )
    assert [claim["claim_number"] for claim in claims] == [1, 2, 3]

    first_page = client.list_claims(
        {"student_id": student["id"], "limit": 2, "offset": 0}, headers=COORDINATOR
    )
    rows, meta = validate_paginated(first_page)
    assert len(rows) == 2, "limit 2 returns two rows"
    assert meta["total_count"] == 3 and meta["has_more"] is True
    assert ids_of(rows) == [claims[0]["id"], claims[1]["id"]]

    second_page = client.list_claims(
        {"student_id": student["id"], "limit": 2, "offset": 2}, headers=COORDINATOR
    )
    rows, meta = validate_paginated(second_page)
    assert len(rows) == 1 and meta["total_count"] == 3 and meta["has_more"] is False
    assert rows[0]["id"] == claims[2]["id"]
    assert_fields_equal(rows[0], claim_number=3)


def test_an_unknown_student_id_in_the_path_is_a_404(client):
    """A well-formed identifier that resolves to nothing is the segment's own 404.

    PRD: "Identifiers in a request path are resolved strictly left to right, parent
    segment before child segment, and the first identifier that does not resolve ends
    the request with the 404 belonging to *that* segment."

    Design: Corner/entities/student_not_found_returns_404
    """
    response = client.get_student("00000000-0000-0000-0000-000000000000", headers=REGISTRAR)
    validate_error(response, ApiErrorId.ERR_STUDENT_NOT_FOUND, 404)

    listing = client.list_students({}, headers=REGISTRAR)
    rows, meta = validate_paginated(listing)
    assert rows == [] and meta["total_count"] == 0, "a failed read creates nothing"


def test_a_programme_without_residency_min_credits_is_refused(client):
    """A required field with no declared default is not silently zeroed.

    PRD: "Alongside those come the four ceiling numbers described in §2.11:
    `residency_min_credits`, at least 0 and at most `total_credits_required`".

    Design: Corner/entities/program_missing_required_residency_min_credits_returns_invalid_request
    """
    payload = f.program_payload(
        program_code="BSCS", allowed_source_types=[SourceType.PORTFOLIO]
    )
    payload.pop("residency_min_credits")
    response = client.create_program(payload, headers=COORDINATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    # Nothing was persisted, so the unique code is still free to claim.
    accepted = validate_success(
        client.create_program(
            f.program_payload(
                program_code="BSCS", allowed_source_types=[SourceType.PORTFOLIO]
            ),
            headers=COORDINATOR,
        ),
        expected_status=201,
    )
    assert_fields_equal(accepted, program_code="BSCS")


def test_a_bare_claim_body_takes_every_declared_default(client):
    """Four supplied fields, and everything else defaults or begins null.

    PRD: "the claim comes into being in `assessment_status` `DRAFT`, `fee_status`
    `UNBILLED` and `credit_status` `NOT_POSTED` with no reservation, no invoice and no
    assessor." "`rush_requested` defaults to false; setting it true both adds the rush
    surcharge line to the invoice and halves the assessment turnaround allowance, and
    it sets `priority_tier` to `EXPEDITED` rather than the default `STANDARD`."

    Design: Corner/entities/pla_claim_defaults_applied_when_optional_input_omitted
    """
    program = fx.new_program(client, program_code="BSCS")
    course = fx.new_course(
        client,
        course_code="CS150",
        credits=6,
        level=CourseLevel.LOWER,
        learning_outcomes=_CS150_OUTCOMES,
    )
    student = fx.new_student(client, program["id"])

    claim = validate_success(
        client.create_claim(
            {
                "student_id": student["id"],
                "course_id": course["id"],
                "source_type": SourceType.PORTFOLIO,
                "credits_requested": 6,
            },
            headers=make_student_headers(student["id"]),
        ),
        expected_status=201,
    )
    assert_fields_equal(
        claim,
        rush_requested=False,
        priority_tier=PriorityTier.STANDARD,
        assessment_status=AssessmentStatus.DRAFT,
        fee_status=FeeStatus.UNBILLED,
        credit_status=CreditStatus.NOT_POSTED,
        revision_round=0,
        sla_breach_count=0,
        appeal_count=0,
    )
    for field in ("credits_awarded", "attempt_date", "articulation_rule_id", "hold_reason"):
        assert claim[field] is None, "%s must begin null, got %r" % (field, claim[field])


def test_a_portfolio_ignores_smuggled_counters_and_status(client):
    """`artifact_count` tracks rows, not the body that claims to know it.

    PRD: "A new portfolio begins in `status` `DRAFT` with `artifact_count` at 0,
    `revision_round` at 0, `submitted_at` null and both `provisional_coverage_bp` and
    `verified_coverage_bp` null." "Attaching an artifact increments `artifact_count`
    by one and recomputes the portfolio's `provisional_coverage_bp`."

    Design: Corner/entities/portfolio_artifact_count_is_computed_and_client_input_ignored
    """
    program = fx.new_program(client, program_code="BSCS")
    course = fx.new_course(
        client,
        course_code="CS150",
        credits=6,
        level=CourseLevel.LOWER,
        learning_outcomes=_CS150_OUTCOMES,
    )
    outcomes = fx.outcomes_of(client, course["id"])
    student = fx.new_student(client, program["id"])
    student_headers = make_student_headers(student["id"])
    claim = fx.new_claim(
        client,
        student["id"],
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=6,
    )

    portfolio = validate_success(
        client.create_portfolio(
            {
                "claim_id": claim["id"],
                "narrative": "Eight years of production Python",
                "artifact_count": 7,
                "status": PortfolioStatus.SUBMITTED,
                "provisional_coverage_bp": 10000,
            },
            headers=student_headers,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        portfolio, artifact_count=0, status=PortfolioStatus.DRAFT, revision_round=0
    )
    assert portfolio["provisional_coverage_bp"] is None, "coverage begins null"
    assert portfolio["submitted_at"] is None, "submitted_at begins null"

    fx.attach_artifact(
        client, portfolio["id"], student["id"], [f.mapping(outcomes[0]["id"], Alignment.PRIMARY)]
    )
    reread = get_success_data(client.get_portfolio(portfolio["id"], headers=COORDINATOR))
    assert_fields_equal(reread, artifact_count=1)
    listing = client.list_artifacts({"portfolio_id": portfolio["id"]}, headers=COORDINATOR)
    rows, _meta = validate_paginated(listing)
    assert len(rows) == 1, "one Artifact row per attachment"


def test_student_system_fields_are_server_generated(client):
    """A body that dictates id, version and the ledger is ignored on all counts.

    PRD: "Every resource is addressed by an `id`: a server-minted UUID carrying no
    type prefix and never supplied by the client." "Four system-maintained counters
    make up the prior-learning ledger, and all four start at 0."

    Design: Corner/entities/student_system_fields_are_server_generated_and_input_ignored
    """
    program = fx.new_program(client, program_code="BSCS")
    student = validate_success(
        client.create_student(
            {
                "student_number": "S-1001",
                "full_name": "Ada Reyes",
                "program_id": program["id"],
                "id": "11111111-1111-1111-1111-111111111111",
                "created_at": "2001-01-01T00:00:00Z",
                "version": 42,
                "pla_credits_reserved": 12,
                "pla_credits_posted": 99,
                "fee_paid_net_cents": 5000,
            },
            headers=COORDINATOR,
        ),
        expected_status=201,
    )
    assert student["id"] != "11111111-1111-1111-1111-111111111111", "the id is server-minted"
    # The supplied `created_at` is not echoed. S2.4 fixes the rendering of the two
    # row-audit stamps but never their source, so the moment itself is not asserted.
    assert_instant_shape(student["created_at"], "created_at")
    assert_instant_shape(student["updated_at"], "updated_at")
    assert parse_instant(student["created_at"]) != parse_instant(
        "2001-01-01T00:00:00Z"
    ), "the client-supplied created_at was ignored"
    assert_fields_equal(
        student,
        version=1,
        pla_credits_reserved=0,
        pla_credits_awarded=0,
        pla_credits_posted=0,
        pla_upper_division_committed=0,
        fee_paid_net_cents=0,
        enrollment_status=EnrollmentStatus.MATRICULATED,
    )


def test_a_course_level_outside_the_domain_is_refused_before_the_weight_check(client):
    """`GRADUATE` is a request-shape failure, which outranks the weight-sum rung.

    PRD: "**Request shape.** Required input fields are present and every supplied
    field satisfies its declared type, enum domain and numeric range. Failure:
    `ERR_INVALID_REQUEST` (400)." "a set totalling 9999 or 10001 is rejected, as is a
    set containing two identical outcome codes, both under
    `ERR_OUTCOME_WEIGHTS_INVALID`."

    Design: Corner/entities/course_level_outside_enum_domain_rejected
    """
    response = client.create_course(
        {
            "course_code": "CS900",
            "title": "Graduate Seminar",
            "department_code": "CS",
            "credits": 3,
            "level": "GRADUATE",
            "pla_eligible": True,
            "learning_outcomes": [
                {
                    "outcome_code": "OC1",
                    "description": "Read papers",
                    "weight_bp": 9000,
                    "mastery_threshold_bp": 7000,
                }
            ],
        },
        headers=COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    outcomes = client.list_learning_outcomes({}, headers=COORDINATOR)
    rows, meta = validate_paginated(outcomes)
    assert rows == [] and meta["total_count"] == 0, (
        "a refused course leaves no learning outcomes behind"
    )


def test_a_learning_outcome_carries_no_version_and_no_updated_at(client):
    """The lean pair of entities is lean on read as well as in the model.

    PRD: "A `LearningOutcome` and an `Artifact` carry only `id` and `created_at`; both
    `updated_at` and `version` are absent from those two resources."

    Design: Corner/entities/learning_outcome_is_immutable_with_no_version_and_no_write_endpoint
    """
    course = fx.new_course(
        client,
        course_code="CS150",
        credits=6,
        level=CourseLevel.LOWER,
        learning_outcomes=_CS150_OUTCOMES,
    )
    outcomes = fx.outcomes_of(client, course["id"])
    outcome = validate_success(
        client.get_learning_outcome(outcomes[0]["id"], headers=COORDINATOR)
    )
    assert_fields_equal(
        outcome, outcome_code="OC1", weight_bp=8000, mastery_threshold_bp=7000
    )
    assert_only_id_and_created_at(outcome)


def test_a_portfolio_naming_an_unknown_claim_is_a_body_reference_404(client):
    """The body reference fails as the claim's own 404, and no orphan is left.

    PRD: "Only after every path segment resolves are identifiers carried in the
    request body resolved, and those are resolved in the order the endpoint declares
    its input fields."

    Design: Corner/entities/portfolio_parent_claim_not_found_returns_404
    """
    program = fx.new_program(client, program_code="BSCS")
    student = fx.new_student(client, program["id"])

    response = client.create_portfolio(
        {"claim_id": "00000000-0000-0000-0000-0000000000ff", "narrative": "Orphan portfolio"},
        headers=make_student_headers(student["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_NOT_FOUND, 404)

    listing = client.list_portfolios({}, headers=COORDINATOR)
    rows, meta = validate_paginated(listing)
    assert rows == [] and meta["total_count"] == 0, "no orphan portfolio was persisted"


def test_the_crosswalk_junction_is_navigable_from_both_ends(client):
    """One recommendation, two courses, two rules — and neither end counts as approved.

    PRD: "Crosswalk rules may be read individually — the response exposes
    `pinned_recommendation_version`, which is a `terms_version` pin and not a generic
    version — or listed with optional `recommendation_id`, `course_id` and `status`
    filters." "The rule begins in `DRAFT` with `pinned_recommendation_version`,
    `reviewed_by_user_id`, `approved_by_user_id` and `suspend_reason` all null."

    Design: Corner/entities/articulation_rule_junction_links_one_recommendation_to_two_courses
    """
    recommendation = fx.new_recommendation(
        client,
        credential_code="AWS-SAA",
        source_type=SourceType.INDUSTRY_CREDENTIAL,
        recommended_credits=3,
        recommended_level=CourseLevel.LOWER,
        effective_from="2026-01-01T00:00:00Z",
    )
    courses = [
        fx.new_course(
            client,
            course_code=code,
            credits=3,
            level=CourseLevel.LOWER,
            learning_outcomes=[f.outcome_payload("OC1", 10000, mastery_threshold_bp=7000)],
        )
        for code in ("CS150", "CS160")
    ]
    rules = [
        get_success_data(
            client.create_rule(
                f.rule_payload(
                    recommendation["id"],
                    course["id"],
                    awarded_credits=3,
                    effective_from="2026-01-01T00:00:00Z",
                ),
                headers=OFFICER,
            )
        )
        for course in courses
    ]

    by_recommendation = client.list_rules(
        {"recommendation_id": recommendation["id"]}, headers=OFFICER
    )
    rows, meta = validate_paginated(by_recommendation)
    assert meta["total_count"] == 2, "both rules hang off the one recommendation"
    assert sorted(ids_of(rows)) == sorted([rules[0]["id"], rules[1]["id"]])

    by_course = client.list_rules({"course_id": courses[0]["id"]}, headers=OFFICER)
    rows, meta = validate_paginated(by_course)
    assert meta["total_count"] == 1 and ids_of(rows) == [rules[0]["id"]]
    assert_fields_equal(
        rows[0],
        recommendation_id=recommendation["id"],
        course_id=courses[0]["id"],
        status=RuleStatus.DRAFT,
    )
    assert rows[0]["pinned_recommendation_version"] is None

    parent = get_success_data(
        client.get_recommendation(recommendation["id"], headers=OFFICER)
    )
    assert_fields_equal(parent, approved_rule_count=0)
