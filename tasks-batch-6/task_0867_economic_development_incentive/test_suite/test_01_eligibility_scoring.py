"""Eligibility scoring, the inclusive PASS/FAIL boundary, the four-eyes approval guard,
and the immutable eligibility-review record."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_program, create_application, submit_application, start_review,
    create_application_payload,
    make_applicant_headers, make_analyst_headers, make_director_headers,
)

APPLICANT1 = make_applicant_headers("applicant-1")
ANALYST1 = make_analyst_headers("analyst-1")


def test_eligibility_score_applies_min_caps(api):
    """PRD §3.2: "The jobs component is thirty times the ratio of `proposed_jobs` to the
    program's `min_jobs_required`, capped at 30." Jobs 100/50 -> 60 clamps to 30 and
    investment 150M/100M -> 45 clamps to 30, plus a but-for bonus of 25 gives 85.00.

    Design: Difficulty/combinatorial_formula/eligibility_score_mincap_nonlinear
    """
    prog = create_program()
    app = create_application(prog["id"], but_for_attested=True)
    data = validate_success(api.submit_application(app["id"], APPLICANT1))
    assert data["but_for_eligibility_score"] == 85.0, data["but_for_eligibility_score"]
    assert data["status"] == "SUBMITTED"


def test_eligibility_score_summed_and_rounded_on_submit(api):
    """PRD §3.2: "The four terms are summed and the total is rounded half up to two
    decimal places to give `but_for_eligibility_score`." The stored score survives a
    subsequent read of the application.

    Design: Difficulty/combinatorial_formula/eligibility_score_mincap_nonlinear
    """
    prog = create_program()
    app = create_application(prog["id"], but_for_attested=True)
    submit_application(app["id"], "applicant-1")
    got = validate_success(api.get_application(app["id"], APPLICANT1))
    assert got["but_for_eligibility_score"] == 85.0, got["but_for_eligibility_score"]


def test_eligibility_finding_pass_at_exact_threshold(api):
    """PRD §3.2: "The review's `finding` is set to `PASS` when the snapshot score is greater
    than or equal to the program's `but_for_pass_threshold`, and to `FAIL` otherwise — the
    boundary is inclusive." A score of exactly 60.00 == the default threshold passes.

    Design: Difficulty/boundary_precision_check/eligibility_score_at_threshold_passes
    """
    prog = create_program()
    app = create_application(prog["id"], proposed_jobs=50, proposed_investment_cents=100_000_000)
    submit_application(app["id"], "applicant-1")
    review = validate_success(api.start_review(app["id"], ANALYST1), expected_status=201)
    assert review["eligibility_score"] == 60.0, review["eligibility_score"]
    assert review["finding"] == "PASS"


def test_eligibility_finding_fail_below_threshold(api):
    """PRD §3.2: "The review's `finding` is set to `PASS` when the snapshot score is greater
    than or equal to the program's `but_for_pass_threshold`, and to `FAIL` otherwise — the
    boundary is inclusive." A score of 58.80 (< 60) falls to FAIL.

    Design: Difficulty/boundary_precision_check/eligibility_score_at_threshold_passes
    """
    prog = create_program()
    app = create_application(prog["id"], proposed_jobs=48, proposed_investment_cents=100_000_000)
    submit_application(app["id"], "applicant-1")
    review = validate_success(api.start_review(app["id"], ANALYST1), expected_status=201)
    assert review["eligibility_score"] == 58.8, review["eligibility_score"]
    assert review["finding"] == "FAIL"


def test_approve_blocked_when_review_failed(api):
    """PRD §3.2: "the application's latest eligibility review must carry a `finding` of
    `PASS`, otherwise the request is rejected with `ERR_ELIGIBILITY_NOT_PASSED` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/approve_requires_pass_eligibility_review
    """
    prog = create_program()
    app = create_application(prog["id"], proposed_jobs=10, proposed_investment_cents=10_000_000)
    submit_application(app["id"], "applicant-1")
    start_review(app["id"], "analyst-1")
    validate_error(api.approve_application(app["id"], make_director_headers("director-1")),
                   ApiErrorId.ERR_ELIGIBILITY_NOT_PASSED)


def test_failed_review_records_fail_finding(api):
    """PRD §3.2: "The review's `finding` is set to `PASS` when the snapshot score is greater
    than or equal to the program's `but_for_pass_threshold`, and to `FAIL` otherwise — the
    boundary is inclusive." A sub-threshold application yields a FAIL review.

    Design: Difficulty/cross_entity_state_dependency/approve_requires_pass_eligibility_review
    """
    prog = create_program()
    app = create_application(prog["id"], proposed_jobs=10, proposed_investment_cents=10_000_000)
    submit_application(app["id"], "applicant-1")
    review = validate_success(api.start_review(app["id"], ANALYST1), expected_status=201)
    assert review["eligibility_score"] == 9.0, review["eligibility_score"]
    assert review["finding"] == "FAIL"


def test_application_optional_flags_default_false(api):
    """PRD §3.2: "Two optional booleans capture the policy hooks: `but_for_attested` (the
    applicant's attestation that the project would not proceed but for the incentive,
    defaulting to false) and `distress_zone` (whether the site sits in a designated
    economically-distressed zone, defaulting to false)."

    Design: Corner/entities/application_default_flags_applied
    """
    prog = create_program()
    data = validate_success(
        api.create_application(create_application_payload(prog["id"]), APPLICANT1),
        expected_status=201)
    assert data["but_for_attested"] is False
    assert data["distress_zone"] is False
    assert data["status"] == "DRAFT"


def test_eligibility_review_is_immutable_record(api):
    """PRD §2.4: "One entity is an exception: an eligibility review is an append-only,
    immutable determination record — it carries only `id` and `created_at`, and has neither
    `updated_at` nor `version`."

    Design: Corner/entities/eligibility_review_is_immutable_record
    """
    prog = create_program()
    app = create_application(prog["id"], but_for_attested=True)
    submit_application(app["id"], "applicant-1")
    review = start_review(app["id"], "analyst-1", notes="ok")
    got = validate_success(api.get_eligibility_review(review["id"], ANALYST1))
    assert got["finding"] == "PASS"
    assert "version" not in got, "eligibility review must not carry version"
    assert "updated_at" not in got, "eligibility review must not carry updated_at"


def test_self_approval_rejected_segregation_of_duties(api):
    """PRD §3.2: "the approving director's identifier must differ from that review's
    `reviewer_user_id`, enforcing four-eyes segregation of duties — a self-approval is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/approve_by_review_author_returns_forbidden_sod
    """
    prog = create_program()
    app = create_application(prog["id"], but_for_attested=True)
    submit_application(app["id"], "applicant-1")
    start_review(app["id"], "shared-1")
    validate_error(api.approve_application(app["id"], make_director_headers("shared-1")),
                   ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
