"""Validation, precedence-conflict, cross-entity dependency, resource-overlap, and
optimistic-concurrency tests.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_applicant_headers,
    make_committee_member_headers,
    create_committee_assignment_payload,
    create_rubric_score_payload,
    create_transcript_payload,
    create_application_payload,
    award_payload,
    fixtures,
)

ADMIN = TEST_USERS["foundation_admin_headers"]


# ===========================================================================
# Queue A — priority_pair_validation_conflict
# ===========================================================================
def test_state_beats_fiscal_on_award_wrong_state(api):
    """PRD §2.5: "Seventh, the target resource's own state is checked. Only after all
    of these structural gates do the domain-specific business constraints, fiscal
    checks, the optimistic-concurrency check, and finally field-level input validation
    apply"
    PRD §3.6: "The application must be `SCORED` (otherwise
    `ERR_APPLICATION_STATE_INVALID`)"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_award_wrong_state
    """
    # Fund AWARDING with tiny endowment; application still SUBMITTED (never SCORED).
    fund = fixtures.create_open_fund(endowment_cents=100, min_gpa=2.00, max_award_cents=1_000_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_draft_application_with_docs(
        fund["id"], applicant["id"], requested_amount_cents=1_000_000, verified_gpa=3.20,
    )
    headers = make_applicant_headers(applicant["id"])
    validate_success(api.submit_application(app["id"], headers))
    validate_success(api.begin_review_fund(fund["id"], ADMIN))
    validate_success(api.begin_awarding_fund(fund["id"], ADMIN))
    fund_v = validate_success(api.get_fund(fund["id"], ADMIN))["version"]
    validate_error(
        api.award_application(app["id"], award_payload(fund_v), ADMIN),
        ApiErrorId.ERR_APPLICATION_STATE_INVALID,
    )


def test_existence_beats_state_on_decline_missing_assignment(api):
    """PRD §2.5: "Third, path resource existence is checked left to right, yielding
    the relevant not-found code."
    PRD §2.4: "A path resource that does not exist yields a not-found error specific to
    its type: `ERR_FUND_NOT_FOUND`, `ERR_CRITERIA_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_COMMITTEE_MEMBER_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SCORE_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`,
    `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_RENEWAL_NOT_FOUND`, or
    `ERR_STEWARDSHIP_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_decline_missing_assignment
    """
    member = fixtures.create_member()
    headers = make_committee_member_headers(member["id"])
    validate_error(
        api.decline_committee_assignment(NON_EXISTENT_UUID, headers),
        ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
    )


# ===========================================================================
# Queue A — cross_entity_state_dependency
# ===========================================================================
def test_application_award_requires_fund_awarding(api):
    """PRD §3.6: "the owning fund must be in `AWARDING` (otherwise
    `ERR_FUND_NOT_AWARDING`)"

    Design: Difficulty/cross_entity_state_dependency/application_award_requires_fund_awarding
    """
    # Build a SCORED application but leave the fund in REVIEW (no begin-awarding).
    ctx = fixtures.setup_scored_application(
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=800_000, verified_gpa=3.50,
        scores=[(90, 90, 90), (90, 90, 90)],
    )
    app = ctx["application"]
    fund_v = validate_success(api.get_fund(ctx["fund"]["id"], ADMIN))["version"]
    validate_error(
        api.award_application(app["id"], award_payload(fund_v), ADMIN),
        ApiErrorId.ERR_FUND_NOT_AWARDING,
    )
    after = validate_success(api.get_application(app["id"], ADMIN))
    assert after["status"] == "SCORED"


def test_rubric_submit_requires_application_under_review(api):
    """PRD §3.4: "Submitting a rubric score moves it from `DRAFT` to `SUBMITTED`."
    PRD §3.4: "and that the parent application is in `UNDER_REVIEW` (otherwise
    `ERR_APPLICATION_NOT_UNDER_REVIEW`)."

    Design: Difficulty/cross_entity_state_dependency/rubric_submit_requires_application_under_review
    """
    # Application SUBMITTED (fund REVIEW) but start-review NOT called; score drafted
    # while application is still SUBMITTED.
    fund = fixtures.create_open_fund(endowment_cents=2_000_000, min_gpa=2.00, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_draft_application_with_docs(
        fund["id"], applicant["id"], requested_amount_cents=300_000, verified_gpa=3.00,
    )
    member = fixtures.create_member()
    fixtures.assign_member(app["id"], member["id"])
    mh = make_committee_member_headers(member["id"])
    sp = create_rubric_score_payload(app["id"], member["id"], academic_score=88, need_score=88, essay_score=88)
    score = validate_success(api.create_rubric_score(sp, mh), 201)
    ah = make_applicant_headers(applicant["id"])
    validate_success(api.submit_application(app["id"], ah))
    validate_success(api.begin_review_fund(fund["id"], ADMIN))
    validate_error(
        api.submit_rubric_score(score["id"], mh),
        ApiErrorId.ERR_APPLICATION_NOT_UNDER_REVIEW,
    )
    after = validate_success(api.get_rubric_score(score["id"], ADMIN))
    assert after["status"] == "DRAFT"


# ===========================================================================
# Queue A — resource_temporal_overlap
# ===========================================================================
def test_duplicate_committee_assignment_same_member_same_application(api):
    """PRD §3.4: "a member who already holds an `ASSIGNED` assignment on the same
    application cannot be assigned again, which is rejected with
    `ERR_DUPLICATE_ASSIGNMENT`"

    Design: Difficulty/resource_temporal_overlap/duplicate_committee_assignment_same_member_same_application
    """
    fund = fixtures.create_open_fund(endowment_cents=2_000_000, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_application(fund["id"], applicant["id"], requested_amount_cents=300_000)
    member = fixtures.create_member()
    fixtures.assign_member(app["id"], member["id"])
    payload = create_committee_assignment_payload(app["id"], member["id"])
    validate_error(api.create_committee_assignment(payload, ADMIN), ApiErrorId.ERR_DUPLICATE_ASSIGNMENT)


def test_duplicate_transcript_upload_same_application(api):
    """PRD §3.2: "An application may hold many recommendations but at most one
    transcript — uploading a second transcript for the same application is rejected
    with `ERR_DUPLICATE_TRANSCRIPT`."

    Design: Difficulty/resource_temporal_overlap/duplicate_transcript_upload_same_application
    """
    fund = fixtures.create_open_fund(endowment_cents=2_000_000, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_application(fund["id"], applicant["id"], requested_amount_cents=300_000)
    fixtures.add_transcript(app["id"], applicant["id"], verified_gpa=3.00)
    headers = make_applicant_headers(applicant["id"])
    payload = create_transcript_payload(app["id"], document_uri="s3://t2", verified_gpa=3.50)
    validate_error(api.create_transcript(payload, headers), ApiErrorId.ERR_DUPLICATE_TRANSCRIPT)


# ===========================================================================
# Queue B — validations
# ===========================================================================
def test_create_score_without_assignment_rejected(api):
    """PRD §3.4: "Creating a rubric score requires that the acting member holds an
    `ASSIGNED` committee assignment on the same application; without one the create is
    rejected with `ERR_NO_ASSIGNMENT_FOR_SCORE`."

    Design: Corner/validations/self_conflict_no_assignment_for_score_when_member_not_assigned
    """
    fund = fixtures.create_open_fund(endowment_cents=500_000, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_application(fund["id"], applicant["id"], requested_amount_cents=100_000)
    member = fixtures.create_member()
    mh = make_committee_member_headers(member["id"])
    sp = create_rubric_score_payload(app["id"], member["id"], academic_score=80, need_score=80, essay_score=80)
    validate_error(api.create_rubric_score(sp, mh), ApiErrorId.ERR_NO_ASSIGNMENT_FOR_SCORE)


def test_member_overloaded_when_max_concurrent_assignments_reached(api):
    """PRD §3.4: "a member who already holds the maximum number of concurrent
    `ASSIGNED` assignments across all applications — a cap of three concurrent
    assignments — cannot take on another, which is rejected with
    `ERR_MEMBER_OVERLOADED`"

    Design: Corner/validations/member_overloaded_when_max_concurrent_assignments_reached
    """
    fund = fixtures.create_open_fund(endowment_cents=9_000_000, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    member = fixtures.create_member()
    apps = []
    for _ in range(4):
        app = fixtures.create_application(fund["id"], applicant["id"], requested_amount_cents=100_000)
        apps.append(app)
    for app in apps[:3]:
        fixtures.assign_member(app["id"], member["id"])
    payload = create_committee_assignment_payload(apps[3]["id"], member["id"])
    validate_error(api.create_committee_assignment(payload, ADMIN), ApiErrorId.ERR_MEMBER_OVERLOADED)


def test_close_fund_with_open_applications_rejected(api):
    """PRD §3.1: "closing is additionally blocked while any application on the fund
    remains in `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_REVISION`, or `SCORED`, in which
    case the request fails with `ERR_OPEN_APPLICATIONS_EXIST`."

    Design: Corner/validations/close_fund_with_open_applications_rejected
    """
    fund = fixtures.create_open_fund(endowment_cents=2_000_000, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_draft_application_with_docs(
        fund["id"], applicant["id"], requested_amount_cents=100_000, verified_gpa=3.00,
    )
    headers = make_applicant_headers(applicant["id"])
    validate_success(api.submit_application(app["id"], headers))
    validate_success(api.begin_review_fund(fund["id"], ADMIN))
    validate_success(api.begin_awarding_fund(fund["id"], ADMIN))
    validate_error(api.close_fund(fund["id"], ADMIN), ApiErrorId.ERR_OPEN_APPLICATIONS_EXIST)
    after = validate_success(api.get_fund(fund["id"], ADMIN))
    assert after["status"] == "AWARDING"


# ===========================================================================
# Queue B — errors / OCC
# ===========================================================================
def test_stale_fund_version_on_award_rejected(api):
    """PRD §2.9: "If `expected_fund_version` does not equal the fund's current
    `version`, the award is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412)."

    Design: Corner/errors/error_stale_fund_version
    """
    # Two SCORED applications on the same AWARDING fund; capture version before any
    # award, award app1 (bumps version), then reuse the stale version on app2.
    fund = fixtures.create_open_fund(
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
    )
    member_a = fixtures.create_member(email="ra@x.edu")
    member_b = fixtures.create_member(email="rb@x.edu")

    def build_scored_app(seed):
        applicant = fixtures.create_applicant(email=f"occ{seed}@x.edu", self_reported_gpa=3.50)
        app = fixtures.create_draft_application_with_docs(
            fund["id"], applicant["id"], requested_amount_cents=500_000, verified_gpa=3.50,
        )
        fixtures.assign_member(app["id"], member_a["id"])
        fixtures.assign_member(app["id"], member_b["id"])
        ah = make_applicant_headers(applicant["id"])
        validate_success(api.submit_application(app["id"], ah))
        return app

    app1 = build_scored_app(1)
    app2 = build_scored_app(2)
    validate_success(api.begin_review_fund(fund["id"], ADMIN))
    for app in (app1, app2):
        validate_success(api.start_review_application(app["id"], ADMIN))
        for member in (member_a, member_b):
            mh = make_committee_member_headers(member["id"])
            sp = create_rubric_score_payload(app["id"], member["id"], academic_score=95, need_score=90, essay_score=85)
            score = validate_success(api.create_rubric_score(sp, mh), 201)
            validate_success(api.submit_rubric_score(score["id"], mh))
        validate_success(api.finalize_scoring_application(app["id"], ADMIN))
    validate_success(api.begin_awarding_fund(fund["id"], ADMIN))

    fund_v_stale = validate_success(api.get_fund(fund["id"], ADMIN))["version"]
    validate_success(api.award_application(app1["id"], award_payload(fund_v_stale), ADMIN), 201)
    # app2 reuses the now-stale version.
    validate_error(
        api.award_application(app2["id"], award_payload(fund_v_stale), ADMIN),
        ApiErrorId.ERR_STALE_FUND_VERSION,
    )
    after = validate_success(api.get_application(app2["id"], ADMIN))
    assert after["status"] == "SCORED"
