"""Graduation: credit audit buckets, final-portfolio gate, segregation of
duties, fiscal gate, testing gate, diploma issuance and terminal lockdown."""
from test_helpers import (
    ApiErrorId,
    assert_graduation_application,
    assert_transcript,
    create_graduation_application,
    create_open_coop_class,
    create_open_year,
    create_planned_credit,
    create_submitted_portfolio,
    evaluate_portfolio,
    get_ledger,
    get_success_data,
    make_director_headers,
    register_coop_ok,
    setup_active_enrollment,
    setup_graduation_candidate,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]       # dir-1
DIRECTOR2 = TEST_USERS["director2_headers"]     # dir-2
REGISTRAR = TEST_USERS["registrar_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]       # rev-1

# 22.0 total with MATH at 2.0 (below its 3.0 bucket minimum).
BUCKET_FAIL_BLOCKS = [
    ("ENGLISH", "English 9-12 block", 480, "A"),       # 4.0
    ("MATH", "Algebra+Geometry", 240, "A"),            # 2.0 (fails >= 3.0)
    ("SCIENCE", "Science block", 360, "A"),            # 3.0
    ("SOCIAL_STUDIES", "Social studies block", 360, "A"),  # 3.0
    ("ELECTIVE", "Elective block", 1200, "A"),         # 10.0
]


def test_graduation_bucket_minimum_interaction_rejects(api):
    """PRD §3.8: "the official credit audit must pass — at least 22.0 total
    posted credits, with at least 4.0 in `ENGLISH` and at least 3.0 each in
    `MATH`, `SCIENCE`, and `SOCIAL_STUDIES`, each credit counting only toward
    its own subject bucket and never cross-allocated — else
    `ERR_GRADUATION_REQUIREMENTS_UNMET`"

    Design: Difficulty/combinatorial_formula/graduation_bucket_minimum_interaction
    """
    year = create_open_year()
    ctx = setup_graduation_candidate(year["id"], credit_blocks=BUCKET_FAIL_BLOCKS,
                                     family_name="Family Buck", district_code="D-04",
                                     date_of_birth="2008-02-02")
    # Total is exactly 22.0 (total satisfies >= 22.0); only the MATH bucket fails.
    transcript = get_success_data(api.get_transcript(ctx["student"]["id"], REGISTRAR))
    assert transcript["official_credits_total"] == 22.0
    assert transcript["subject_credits_official"]["MATH"] == 2.0

    resp = api.evaluate_graduation_application(
        ctx["application"]["id"], {"decision": "APPROVE"}, DIRECTOR
    )
    validate_error(resp, ApiErrorId.ERR_GRADUATION_REQUIREMENTS_UNMET)


def test_graduation_bucket_failure_leaves_application_submitted(api):
    """PRD §3.8: "Success lands the application `APPROVED`; either decision
    records the director as `evaluated_by` and the notes as `decision_notes`."
    PRD §3.8: "the official credit audit must pass — at least 22.0 total posted
    credits, with at least 4.0 in `ENGLISH` and at least 3.0 each in `MATH`,
    `SCIENCE`, and `SOCIAL_STUDIES`, each credit counting only toward its own
    subject bucket and never cross-allocated — else
    `ERR_GRADUATION_REQUIREMENTS_UNMET`"

    Design: Difficulty/combinatorial_formula/graduation_bucket_minimum_interaction
    """
    year = create_open_year()
    ctx = setup_graduation_candidate(year["id"], credit_blocks=BUCKET_FAIL_BLOCKS,
                                     family_name="Family Buck", district_code="D-04",
                                     date_of_birth="2008-02-02")
    resp = api.evaluate_graduation_application(
        ctx["application"]["id"], {"decision": "APPROVE"}, DIRECTOR
    )
    validate_error(resp, ApiErrorId.ERR_GRADUATION_REQUIREMENTS_UNMET)
    current = get_success_data(
        api.get_graduation_application(ctx["application"]["id"], DIRECTOR)
    )
    assert current["status"] == "SUBMITTED", "no state change on failed evaluation"


def _setup_submitted_portfolio_grad_candidate(api):
    """All graduation criteria satisfied except the portfolio is merely
    SUBMITTED (no evaluation yet)."""
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 12, family_name="Fam Grad",
                                  district_code="D-21", student_name="Senior Grad",
                                  date_of_birth="2008-09-09")
    from test_helpers import create_posted_credit
    from test_helpers import GRADUATION_CREDIT_BLOCKS
    for subject, title, hours, grade in GRADUATION_CREDIT_BLOCKS:
        create_posted_credit(ctx["enrollment"], ctx["family"], subject, title, hours, grade)
    ctx["portfolio"] = create_submitted_portfolio(ctx["enrollment"], ctx["family"])
    ctx["application"] = create_graduation_application(
        ctx["student"], ctx["family"], year["id"]
    )
    return ctx


def test_graduation_approval_rejected_while_portfolio_submitted(api):
    """PRD §3.8: "the final-year portfolio must stand `ACCEPTED`, else
    `ERR_FINAL_PORTFOLIO_NOT_ACCEPTED`"

    Design: Difficulty/cross_entity_state_dependency/graduation_approval_requires_final_portfolio_accepted
    """
    ctx = _setup_submitted_portfolio_grad_candidate(api)
    resp = api.evaluate_graduation_application(
        ctx["application"]["id"], {"decision": "APPROVE"}, DIRECTOR
    )
    validate_error(resp, ApiErrorId.ERR_FINAL_PORTFOLIO_NOT_ACCEPTED)


def test_graduation_approval_succeeds_after_portfolio_accepted(api):
    """PRD §3.8: "the final-year portfolio must stand `ACCEPTED`, else
    `ERR_FINAL_PORTFOLIO_NOT_ACCEPTED`; the testing requirement must be either
    absent or satisfied, else `ERR_TESTING_REQUIREMENT_UNMET`; and the family's
    `fee_balance_cents` must be exactly zero, else `ERR_FEES_UNSETTLED`."
    PRD §3.8: "Success lands the application `APPROVED`; either decision records
    the director as `evaluated_by` and the notes as `decision_notes`."

    Design: Difficulty/cross_entity_state_dependency/graduation_approval_requires_final_portfolio_accepted
    """
    ctx = _setup_submitted_portfolio_grad_candidate(api)
    resp = api.evaluate_graduation_application(
        ctx["application"]["id"], {"decision": "APPROVE"}, DIRECTOR
    )
    validate_error(resp, ApiErrorId.ERR_FINAL_PORTFOLIO_NOT_ACCEPTED)

    # Accept the portfolio, then the identical evaluation succeeds (grade 12 is
    # not in the default testing_grades, so testing is absent; fees are zero).
    get_success_data(evaluate_portfolio(ctx["portfolio"]["id"], "ACCEPTED"))
    approved = validate_success(
        api.evaluate_graduation_application(
            ctx["application"]["id"], {"decision": "APPROVE"}, DIRECTOR
        )
    )
    assert_graduation_application(approved)
    assert approved["status"] == "APPROVED"
    assert approved["evaluated_by"] == "dir-1"


def test_second_active_graduation_application_rejected(api):
    """PRD §3.8: "the application is born `SUBMITTED`, and a student may hold
    only one active application — a second attempt while one stands `SUBMITTED`
    or `APPROVED` fails with `ERR_ACTIVE_GRADUATION_APPLICATION_EXISTS`."

    Design: Corner/errors/second_active_graduation_application_rejected
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 12, family_name="Fam Ga",
                                  district_code="D-64", date_of_birth="2008-01-01")
    create_graduation_application(ctx["student"], ctx["family"], year["id"])
    resp = api.create_graduation_application(
        ctx["student"]["id"], {"academic_year_id": year["id"]}, ctx["parent_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_ACTIVE_GRADUATION_APPLICATION_EXISTS)


def test_graduation_evaluator_equals_portfolio_reviewer_forbidden(api):
    """PRD §3.8: "Approval runs the full criteria chain, in the pipeline order
    of §2.8 — duty gates first, fiscal gates last: the evaluating director must
    not be the reviewer who accepted the final-year portfolio — the
    `reviewer_id` of the latest `ACCEPTED` evaluation on that portfolio — else
    `ERR_SEGREGATION_OF_DUTIES_VIOLATION`"

    Design: Corner/errors/graduation_evaluator_equals_portfolio_reviewer_forbidden
    """
    year = create_open_year()
    # No course credits at all: the credit audit would fail if it were reached.
    ctx = setup_graduation_candidate(year["id"], credit_blocks=[],
                                     family_name="Fam Sd", district_code="D-66",
                                     date_of_birth="2008-01-01")
    # Same person as the accepting reviewer (rev-1) acting as director.
    resp = api.evaluate_graduation_application(
        ctx["application"]["id"], {"decision": "APPROVE"},
        make_director_headers("rev-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

    # A different director passes segregation and hits the empty-transcript audit.
    resp2 = api.evaluate_graduation_application(
        ctx["application"]["id"], {"decision": "APPROVE"}, DIRECTOR
    )
    validate_error(resp2, ApiErrorId.ERR_GRADUATION_REQUIREMENTS_UNMET)


def test_graduation_approval_requires_settled_fees(api):
    """PRD §3.8: "Approval runs the full criteria chain, in the pipeline order
    of §2.8 — duty gates first, fiscal gates last: the evaluating director must
    not be the reviewer who accepted the final-year portfolio — the
    `reviewer_id` of the latest `ACCEPTED` evaluation on that portfolio — else
    `ERR_SEGREGATION_OF_DUTIES_VIOLATION`; the final-year enrollment's standing
    must not be `NONCOMPLIANT`, else `ERR_ENROLLMENT_NONCOMPLIANT`; the official
    credit audit must pass — at least 22.0 total posted credits, with at least
    4.0 in `ENGLISH` and at least 3.0 each in `MATH`, `SCIENCE`, and
    `SOCIAL_STUDIES`, each credit counting only toward its own subject bucket
    and never cross-allocated — else `ERR_GRADUATION_REQUIREMENTS_UNMET`; the
    final-year portfolio must stand `ACCEPTED`, else
    `ERR_FINAL_PORTFOLIO_NOT_ACCEPTED`; the testing requirement must be either
    absent or satisfied, else `ERR_TESTING_REQUIREMENT_UNMET`; and the family's
    `fee_balance_cents` must be exactly zero, else `ERR_FEES_UNSETTLED`."

    Design: Corner/errors/graduation_approval_requires_settled_fees
    """
    year = create_open_year()
    ctx = setup_graduation_candidate(year["id"], family_name="Fam Fee",
                                     district_code="D-68", date_of_birth="2008-01-01")
    # Register into a co-op class starting 2026-08-25 (inside 30 days of the
    # 2026-08-01 default clock): no early-bird, so the charge is 11000 unpaid.
    coop_class = create_open_coop_class(year["id"], title="Feeclass", meeting_day="THU")
    register_coop_ok(coop_class["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    assert get_ledger(ctx["family"]["id"])["fee_balance_cents"] == 11000

    resp = api.evaluate_graduation_application(
        ctx["application"]["id"], {"decision": "APPROVE"}, DIRECTOR
    )
    validate_error(resp, ApiErrorId.ERR_FEES_UNSETTLED)

    get_success_data(
        api.create_ledger_payment(ctx["family"]["id"], {"amount_cents": 11000},
                                  ctx["parent_headers"])
    )
    approved = validate_success(
        api.evaluate_graduation_application(
            ctx["application"]["id"], {"decision": "APPROVE"}, DIRECTOR
        )
    )
    assert approved["status"] == "APPROVED"


def test_graduation_testing_requirement_gate(api):
    """PRD §3.8: "the testing requirement must be either absent or satisfied,
    else `ERR_TESTING_REQUIREMENT_UNMET`"
    PRD §3.6: "Whether a given enrollment must test is settled at enrollment
    creation (§3.2): `testing_required` holds when the grade is a member of the
    year's `testing_grades`."

    Design: Corner/errors/graduation_testing_requirement_gate
    """
    year = create_open_year()
    # Grade 11 is in the default testing_grades; no passing/EXCUSED registration.
    ctx = setup_graduation_candidate(year["id"], grade_level=11,
                                     family_name="Fam Tg", district_code="D-77",
                                     date_of_birth="2009-01-01")
    assert ctx["enrollment"]["testing_required"] is True
    resp = api.evaluate_graduation_application(
        ctx["application"]["id"], {"decision": "APPROVE"}, DIRECTOR
    )
    validate_error(resp, ApiErrorId.ERR_TESTING_REQUIREMENT_UNMET)
    current = get_success_data(
        api.get_graduation_application(ctx["application"]["id"], DIRECTOR)
    )
    assert current["status"] == "SUBMITTED"


def test_graduation_happy_path_and_terminal_lockdown(api):
    """PRD §3.8: "Issuance moves the application to the terminal state
    `DIPLOMA_ISSUED` with `diploma_issued_at` stamped; assigns the student a
    `diploma_number` composed of the literal prefix `DIP-`, the start year of
    the graduating academic year, and a zero-padded three-digit sequence
    beginning at 001 in issuance order within that year; seals the transcript —
    `transcript_sealed` true, `sealed_at` stamped — which blocks any further
    credit posting or revocation; and moves the final-year enrollment, the one
    whose year matches the application's `academic_year_id`, from `ACTIVE` or
    `COMPLETED` to `GRADUATED`."
    PRD §3.8: "a director issues the diploma for an `APPROVED` application, but
    the issuer must differ from the application's `evaluated_by`, else
    `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

    Design: Corner/errors/graduation_happy_path_and_terminal_lockdown
    """
    year = create_open_year()
    ctx = setup_graduation_candidate(year["id"], family_name="Fam Hp",
                                     district_code="D-79", date_of_birth="2008-01-01")
    # A sixth credit left VERIFIED (60h C): excluded from the official audit.
    c6 = create_planned_credit(ctx["enrollment"], ctx["family"], subject="ELECTIVE",
                               course_title="Late elective", planned_hours=60)
    from test_helpers import complete_credit
    get_success_data(complete_credit(c6, ctx["family"], 60, "C"))
    get_success_data(api.verify_course_credit(c6["id"], {"decision": "APPROVE"}, REGISTRAR))

    approved = validate_success(
        api.evaluate_graduation_application(
            ctx["application"]["id"], {"decision": "APPROVE", "notes": "all criteria met"},
            DIRECTOR,
        )
    )
    assert approved["status"] == "APPROVED"

    issued = validate_success(
        api.issue_diploma(ctx["application"]["id"], DIRECTOR2)
    )
    assert issued["status"] == "DIPLOMA_ISSUED"
    assert issued["diploma_issued_at"] is not None

    student = get_success_data(api.get_student(ctx["student"]["id"], REGISTRAR))
    assert student["transcript_sealed"] is True
    assert student["diploma_number"] == "DIP-2026-001", (
        "start year 2026, first diploma issued in the year"
    )

    enrollment = get_success_data(api.get_enrollment(ctx["enrollment"]["id"], REGISTRAR))
    assert enrollment["enrollment_status"] == "GRADUATED"

    transcript = get_success_data(api.get_transcript(ctx["student"]["id"], REGISTRAR))
    assert_transcript(transcript)
    assert transcript["official_credits_total"] == 22.0
    assert transcript["gpa_official"] == 4.0

    # Terminal lockdown: re-evaluate, post, and revoke all fail.
    resp_eval = api.evaluate_graduation_application(
        ctx["application"]["id"], {"decision": "DENY"}, DIRECTOR
    )
    validate_error(resp_eval, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    resp_post = api.post_course_credit(c6["id"], REGISTRAR)
    validate_error(resp_post, ApiErrorId.ERR_TRANSCRIPT_SEALED)

    resp_revoke = api.revoke_course_credit(
        ctx["credits"][0]["id"], {"reason": "late audit"}, REGISTRAR
    )
    validate_error(resp_revoke, ApiErrorId.ERR_TRANSCRIPT_SEALED)
