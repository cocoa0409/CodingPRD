"""Portfolio submission, evaluation outcomes, forced rejection, and visibility."""
from test_helpers import (
    ACCEPT_SCORES,
    REMEDIATION_SCORES,
    ApiErrorId,
    assert_enrollment,
    assert_evaluation,
    assert_portfolio,
    create_accepted_portfolio,
    create_open_year,
    create_submitted_portfolio,
    evaluate_portfolio,
    get_success_data,
    set_clock,
    setup_active_enrollment,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

REGISTRAR = TEST_USERS["registrar_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


def _setup_submitted_portfolio(api, grade_level=7, family_name="Fam Port",
                               district_code="D-06"):
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], grade_level, family_name=family_name,
                                  district_code=district_code)
    portfolio = create_submitted_portfolio(ctx["enrollment"], ctx["family"])
    return ctx, portfolio


def test_portfolio_cycle_forced_rejection_at_third_attempt(api):
    """PRD §3.5: "`REMEDIATION_REQUIRED` is available only while the portfolio
    has seen fewer than three attempts and returns it to `REMEDIATION_REQUIRED`
    for another cycle."
    PRD §3.5: "`REJECTED` lands the portfolio in `REJECTED` with `decided_at`
    stamped — and the same fate befalls a portfolio whose reviewer requests
    remediation on its third attempt: remediation at `attempt_count` 3 is a
    forced rejection."

    Design: Difficulty/non_linear_state_machine/portfolio_review_cycle_with_forced_rejection
    """
    ctx, portfolio = _setup_submitted_portfolio(api)
    pid, parent = portfolio["id"], ctx["parent_headers"]
    assert portfolio["attempt_count"] == 1, "first submit sets attempt_count to 1"

    get_success_data(evaluate_portfolio(pid, "REMEDIATION_REQUIRED"))
    resub2 = get_success_data(api.submit_portfolio(pid, parent))
    get_success_data(evaluate_portfolio(pid, "REMEDIATION_REQUIRED"))
    resub3 = get_success_data(api.submit_portfolio(pid, parent))
    assert resub3["attempt_count"] == 3, "the remediation cycle repeats"

    get_success_data(evaluate_portfolio(pid, "REMEDIATION_REQUIRED"))
    final = validate_success(api.get_portfolio(pid, REGISTRAR))
    assert_portfolio(final)
    assert final["status"] == "REJECTED", "remediation at attempt_count 3 is a forced rejection"
    assert final["decided_at"] is not None


def test_portfolio_rejection_drives_standing_noncompliant(api):
    """PRD §3.5: "A finally or forcibly rejected portfolio drives the
    enrollment's `compliance_standing` to `NONCOMPLIANT`, firing the standing
    cascade of §3.7 — confirmed co-op enrollments dropped with full
    `SCHOOL_STANDING` refunds, waitlisted ones cancelled, freed seats offered to
    the waitlist."

    Design: Difficulty/non_linear_state_machine/portfolio_review_cycle_with_forced_rejection
    """
    ctx, portfolio = _setup_submitted_portfolio(api)
    pid, parent = portfolio["id"], ctx["parent_headers"]
    for _ in range(2):
        get_success_data(evaluate_portfolio(pid, "REMEDIATION_REQUIRED"))
        get_success_data(api.submit_portfolio(pid, parent))
    get_success_data(evaluate_portfolio(pid, "REMEDIATION_REQUIRED"))

    enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], REGISTRAR))
    assert enrollment["compliance_standing"] == "NONCOMPLIANT", (
        "forced rejection escalates standing immediately, no sweep needed"
    )


def test_duplicate_portfolio_create_rejected(api):
    """PRD §3.5: "Each enrollment accumulates exactly one portfolio — creating
    a second is refused with `ERR_PORTFOLIO_ALREADY_EXISTS` — opened as `DRAFT`
    with `attempt_count` at zero."

    Design: Corner/state_machines/duplicate_portfolio_create_rejected
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 4, family_name="Fam P",
                                  district_code="D-37")
    first = validate_success(
        api.create_portfolio(ctx["enrollment"]["id"], ctx["parent_headers"]), 201
    )
    assert_portfolio(first)
    assert first["status"] == "DRAFT"
    assert first["attempt_count"] == 0
    resp = api.create_portfolio(ctx["enrollment"]["id"], ctx["parent_headers"])
    validate_error(resp, ApiErrorId.ERR_PORTFOLIO_ALREADY_EXISTS)


def test_evaluation_accepted_requires_min_scores(api):
    """PRD §3.5: "`ACCEPTED` is lawful only when every subject score is at
    least 2 — a mismatch is rejected with
    `ERR_EVALUATION_SCORE_OUTCOME_MISMATCH` — and lands the portfolio in
    `ACCEPTED` with `decided_at` stamped."

    Design: Corner/state_machines/evaluation_accepted_requires_min_scores
    """
    ctx, portfolio = _setup_submitted_portfolio(api, grade_level=4,
                                                family_name="Fam E",
                                                district_code="D-38")
    bad_scores = [
        {"subject": "READING", "score": 3},
        {"subject": "WRITING", "score": 3},
        {"subject": "MATH", "score": 1},
        {"subject": "SCIENCE", "score": 3},
        {"subject": "SOCIAL_STUDIES", "score": 3},
    ]
    resp = evaluate_portfolio(portfolio["id"], "ACCEPTED", subject_scores=bad_scores)
    validate_error(resp, ApiErrorId.ERR_EVALUATION_SCORE_OUTCOME_MISMATCH)
    current = get_success_data(api.get_portfolio(portfolio["id"], REGISTRAR))
    assert current["status"] == "SUBMITTED", "no evaluation outcome persisted"


def test_portfolio_submit_after_year_window_closed(api):
    """PRD §3.5: "Submission is a parent action with two guards: the enrollment
    must be `ACTIVE` (else `ERR_ENROLLMENT_NOT_ACTIVE`), and the logical clock
    must read no later than the end of the year's final instructional day —
    submission after that date is refused with `ERR_PORTFOLIO_WINDOW_CLOSED`."

    Design: Corner/errors/portfolio_submit_after_year_window_closed
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 4, family_name="Fam Pw",
                                  district_code="D-73")
    portfolio = get_success_data(
        api.create_portfolio(ctx["enrollment"]["id"], ctx["parent_headers"])
    )
    set_clock("2027-06-01T00:00:00Z")  # past end_date 2027-05-31
    resp = api.submit_portfolio(portfolio["id"], ctx["parent_headers"])
    validate_error(resp, ApiErrorId.ERR_PORTFOLIO_WINDOW_CLOSED)
    current = get_success_data(api.get_portfolio(portfolio["id"], REGISTRAR))
    assert current["status"] == "DRAFT"
    assert current["attempt_count"] == 0


def test_reviewer_conflict_of_interest_forbidden(api):
    """PRD §3.5: "The conflict-of-interest rule applies here as to plans: a
    reviewer who is the student's own parent is rejected with
    `ERR_REVIEWER_CONFLICT_OF_INTEREST`."

    Design: Corner/errors/reviewer_conflict_of_interest_forbidden
    """
    from test_helpers import make_reviewer_headers

    ctx, portfolio = _setup_submitted_portfolio(api, grade_level=4,
                                                family_name="Fam Ci",
                                                district_code="D-67")
    # Reviewer whose X-User-ID equals the student's family id.
    resp = evaluate_portfolio(
        portfolio["id"], "ACCEPTED",
        reviewer_headers=make_reviewer_headers(ctx["family"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REVIEWER_CONFLICT_OF_INTEREST)
    current = get_success_data(api.get_portfolio(portfolio["id"], REGISTRAR))
    assert current["status"] == "SUBMITTED"


def test_immediate_visibility_after_mutation(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.5: "Every evaluation is written as an immutable row tied to the
    portfolio via `portfolio_id`, capturing the acting `reviewer_id` and an
    `attempt_number` equal to the portfolio's `attempt_count` at the moment of
    evaluation; evaluation rows carry only `id` and `created_at`, with no
    `updated_at` or `version`."

    Design: Corner/consistency_model/immediate_visibility_after_mutation
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 4, family_name="Fam Im",
                                  district_code="D-85")
    # The activate response body itself carries the new state.
    enrollment = validate_success(api.get_enrollment(ctx["enrollment"]["id"], REGISTRAR))
    assert enrollment["enrollment_status"] == "ACTIVE"
    assert enrollment["activated_at"] is not None

    portfolio = get_success_data(
        api.create_portfolio(ctx["enrollment"]["id"], ctx["parent_headers"])
    )
    get_success_data(api.submit_portfolio(portfolio["id"], ctx["parent_headers"]))
    evaluation = validate_success(
        evaluate_portfolio(portfolio["id"], "ACCEPTED",
                           subject_scores=[
                               {"subject": "READING", "score": 4},
                               {"subject": "WRITING", "score": 4},
                               {"subject": "MATH", "score": 4},
                               {"subject": "SCIENCE", "score": 4},
                               {"subject": "SOCIAL_STUDIES", "score": 4},
                           ]),
        201,
    )
    assert_evaluation(evaluation)
    assert evaluation["overall_outcome"] == "ACCEPTED"
    assert evaluation["attempt_number"] == 1
    assert evaluation["reviewer_id"] == "rev-1"

    current = validate_success(api.get_portfolio(portfolio["id"], REGISTRAR))
    assert current["status"] == "ACCEPTED"
    assert current["decided_at"] is not None
