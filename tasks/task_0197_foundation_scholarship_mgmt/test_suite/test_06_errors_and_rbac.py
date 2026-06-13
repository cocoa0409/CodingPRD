"""Error-catalogue and RBAC tests: not-found probes, FK existence, fund/resource
state errors, ownership violations, and role-based access control.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_applicant_headers,
    make_committee_member_headers,
    make_headers,
    create_committee_assignment_payload,
    create_application_payload,
    create_rubric_score_payload,
    create_fund_payload,
    disburse_payload,
    fixtures,
)

ADMIN = TEST_USERS["foundation_admin_headers"]
OFFICER = TEST_USERS["disbursement_officer_headers"]


_NOT_FOUND_GET = (
    'PRD §2.4: "A path resource that does not exist yields a not-found error specific '
    'to its type"'
)


# ===========================================================================
# Queue B — errors: not-found GET probes (one test per resource type)
# ===========================================================================
def test_get_award_nonexistent_returns_not_found(api):
    """PRD §2.4: "an unresolved `award_id` raises `ERR_AWARD_NOT_FOUND`"

    Design: Corner/errors/error_award_not_found_on_get
    """
    validate_error(api.get_award(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_AWARD_NOT_FOUND)


def test_get_criteria_nonexistent_returns_not_found(api):
    """PRD §2.4: "A path resource that does not exist yields a not-found error specific
    to its type: `ERR_FUND_NOT_FOUND`, `ERR_CRITERIA_NOT_FOUND`"

    Design: Corner/errors/error_criteria_not_found_on_get
    """
    validate_error(api.get_criteria(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_CRITERIA_NOT_FOUND)


def test_get_rubric_score_nonexistent_returns_not_found(api):
    """PRD §2.4: "A path resource that does not exist yields a not-found error specific
    to its type: `ERR_FUND_NOT_FOUND`, `ERR_CRITERIA_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_COMMITTEE_MEMBER_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SCORE_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`,
    `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_RENEWAL_NOT_FOUND`, or
    `ERR_STEWARDSHIP_NOT_FOUND`."

    Design: Corner/errors/error_score_not_found_on_get
    """
    validate_error(api.get_rubric_score(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_SCORE_NOT_FOUND)


def test_get_disbursement_nonexistent_returns_not_found(api):
    """PRD §2.4: "A path resource that does not exist yields a not-found error specific
    to its type: `ERR_FUND_NOT_FOUND`, `ERR_CRITERIA_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_COMMITTEE_MEMBER_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SCORE_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`,
    `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_RENEWAL_NOT_FOUND`, or
    `ERR_STEWARDSHIP_NOT_FOUND`."

    Design: Corner/errors/error_disbursement_not_found_on_get
    """
    validate_error(api.get_disbursement(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_DISBURSEMENT_NOT_FOUND)


def test_get_renewal_review_nonexistent_returns_not_found(api):
    """PRD §2.4: "A path resource that does not exist yields a not-found error specific
    to its type: `ERR_FUND_NOT_FOUND`, `ERR_CRITERIA_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_COMMITTEE_MEMBER_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SCORE_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`,
    `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_RENEWAL_NOT_FOUND`, or
    `ERR_STEWARDSHIP_NOT_FOUND`."

    Design: Corner/errors/error_renewal_not_found_on_get
    """
    validate_error(api.get_renewal_review(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_RENEWAL_NOT_FOUND)


def test_get_stewardship_record_nonexistent_returns_not_found(api):
    """PRD §2.4: "A path resource that does not exist yields a not-found error specific
    to its type: `ERR_FUND_NOT_FOUND`, `ERR_CRITERIA_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_COMMITTEE_MEMBER_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SCORE_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`,
    `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_RENEWAL_NOT_FOUND`, or
    `ERR_STEWARDSHIP_NOT_FOUND`."

    Design: Corner/errors/error_stewardship_not_found_on_get
    """
    validate_error(api.get_stewardship_record(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_STEWARDSHIP_NOT_FOUND)


# ===========================================================================
# Queue B — errors: FK existence on committee-assignment create
# ===========================================================================
def test_committee_assignment_unknown_application_returns_not_found(api):
    """PRD §2.4: "Body foreign keys on create endpoints are subject to the same
    existence check: an unresolved `fund_id` raises `ERR_FUND_NOT_FOUND`, an unresolved
    `applicant_id` raises `ERR_APPLICANT_NOT_FOUND`, an unresolved `application_id`
    raises `ERR_APPLICATION_NOT_FOUND`, an unresolved `award_id` raises
    `ERR_AWARD_NOT_FOUND`, and an unresolved `committee_member_id` raises
    `ERR_COMMITTEE_MEMBER_NOT_FOUND`."

    Design: Corner/errors/error_application_not_found_on_committee_assignment
    """
    member = fixtures.create_member()
    payload = create_committee_assignment_payload(NON_EXISTENT_UUID, member["id"])
    validate_error(api.create_committee_assignment(payload, ADMIN), ApiErrorId.ERR_APPLICATION_NOT_FOUND)


def test_committee_assignment_unknown_member_returns_not_found(api):
    """PRD §2.4: "Body foreign keys on create endpoints are subject to the same
    existence check: an unresolved `fund_id` raises `ERR_FUND_NOT_FOUND`, an unresolved
    `applicant_id` raises `ERR_APPLICANT_NOT_FOUND`, an unresolved `application_id`
    raises `ERR_APPLICATION_NOT_FOUND`, an unresolved `award_id` raises
    `ERR_AWARD_NOT_FOUND`, and an unresolved `committee_member_id` raises
    `ERR_COMMITTEE_MEMBER_NOT_FOUND`."

    Design: Corner/errors/error_committee_member_not_found_on_committee_assignment
    """
    fund = fixtures.create_open_fund(endowment_cents=500_000, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_application(fund["id"], applicant["id"], requested_amount_cents=100_000)
    payload = create_committee_assignment_payload(app["id"], NON_EXISTENT_UUID)
    validate_error(api.create_committee_assignment(payload, ADMIN), ApiErrorId.ERR_COMMITTEE_MEMBER_NOT_FOUND)


# ===========================================================================
# Queue B — errors: fund / resource state
# ===========================================================================
def test_application_create_against_draft_fund_rejected(api):
    """PRD §3.2: "An application is created against a fund that must currently be
    `OPEN`."

    Design: Corner/errors/error_fund_not_open_on_application_create
    """
    fund = fixtures.create_fund(endowment_cents=500_000)
    applicant = fixtures.create_applicant()
    payload = create_application_payload(fund["id"], applicant["id"], requested_amount_cents=100_000)
    headers = make_applicant_headers(applicant["id"])
    validate_error(api.create_application(payload, headers), ApiErrorId.ERR_FUND_NOT_OPEN)


def test_start_review_when_fund_not_in_review_rejected(api):
    """PRD §3.5: "This requires that the application is currently in `SUBMITTED`
    (otherwise `ERR_APPLICATION_STATE_INVALID`), that the owning fund is in `REVIEW`
    (otherwise `ERR_FUND_NOT_IN_REVIEW`)"

    Design: Corner/errors/error_fund_not_in_review_on_start_review
    """
    fund = fixtures.create_open_fund(endowment_cents=500_000, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_draft_application_with_docs(
        fund["id"], applicant["id"], requested_amount_cents=100_000, verified_gpa=3.00,
    )
    member = fixtures.create_member()
    fixtures.assign_member(app["id"], member["id"])
    headers = make_applicant_headers(applicant["id"])
    validate_success(api.submit_application(app["id"], headers))
    # Fund left OPEN (begin-review not called).
    validate_error(api.start_review_application(app["id"], ADMIN), ApiErrorId.ERR_FUND_NOT_IN_REVIEW)


def test_double_submit_rubric_score_rejected(api):
    """PRD §3.4: "Submitting a rubric score moves it from `DRAFT` to `SUBMITTED`. The
    submit requires that the score is in `DRAFT` (otherwise `ERR_SCORE_STATE_INVALID`)"

    Design: Corner/errors/error_score_state_invalid_on_double_submit
    """
    ctx = fixtures.setup_under_review_application(
        endowment_cents=500_000, min_gpa=2.00, max_award_cents=500_000,
        requested_amount_cents=100_000, verified_gpa=3.00,
        scores=[(80, 80, 80)], num_members=1,
    )
    app = ctx["application"]
    member = ctx["members"][0]
    mh = make_committee_member_headers(member["id"])
    sp = create_rubric_score_payload(app["id"], member["id"], academic_score=80, need_score=80, essay_score=80)
    score = validate_success(api.create_rubric_score(sp, mh), 201)
    validate_success(api.submit_rubric_score(score["id"], mh))
    validate_error(api.submit_rubric_score(score["id"], mh), ApiErrorId.ERR_SCORE_STATE_INVALID)


def test_double_settle_disbursement_rejected(api):
    """PRD §3.7: "Settling a disbursement moves it from `PENDING` to the terminal
    `SETTLED` state and requires the disbursement to be `PENDING` (otherwise
    `ERR_DISBURSEMENT_STATE_INVALID`)"

    Design: Corner/errors/error_disbursement_state_invalid_on_double_settle
    """
    ctx = fixtures.setup_settled_disbursement(
        institution_id="I",
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=1_000_000, verified_gpa=3.50,
        scores=[(95, 90, 85), (95, 90, 85)],
    )
    disb_id = ctx["disbursement"]["id"]
    validate_error(api.settle_disbursement(disb_id, OFFICER), ApiErrorId.ERR_DISBURSEMENT_STATE_INVALID)


def test_double_acknowledge_stewardship_rejected(api):
    """PRD §3.7: "acknowledgement requires that the record is in `DRAFT` (otherwise
    `ERR_STEWARDSHIP_STATE_INVALID`)"

    Design: Corner/errors/error_stewardship_state_invalid_on_double_acknowledge
    """
    ctx = fixtures.setup_committed_award_with_stewardship(
        acknowledge=True,
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=1_000_000, verified_gpa=3.50,
        scores=[(95, 90, 85), (95, 90, 85)],
    )
    rec_id = ctx["stewardship"]["id"]
    headers = make_applicant_headers(ctx["applicant"]["id"])
    validate_error(
        api.acknowledge_stewardship_record(rec_id, headers),
        ApiErrorId.ERR_STEWARDSHIP_STATE_INVALID,
    )


def test_decline_completed_assignment_rejected(api):
    """PRD §3.4: "A committee member may decline their own assignment while it is
    `ASSIGNED`, moving it to the terminal `DECLINED` state; this requires that the
    assignment is `ASSIGNED` (otherwise `ERR_ASSIGNMENT_STATE_INVALID`)"

    Design: Corner/errors/error_assignment_state_invalid_on_decline_completed
    """
    # finalize-scoring cascades the assignment to COMPLETED.
    ctx = fixtures.setup_scored_application(
        endowment_cents=2_000_000, min_gpa=2.00, max_award_cents=500_000,
        requested_amount_cents=100_000, verified_gpa=3.00,
        scores=[(90, 90, 90), (90, 90, 90)],
    )
    app = ctx["application"]
    member = ctx["members"][0]
    # Find member's assignment (now COMPLETED).
    data, _ = validate_paginated(
        api.list_committee_assignments(ADMIN, params={"application_id": app["id"], "committee_member_id": member["id"]})
    )
    assert len(data) >= 1
    assignment_id = data[0]["id"]
    mh = make_committee_member_headers(member["id"])
    validate_error(api.decline_committee_assignment(assignment_id, mh), ApiErrorId.ERR_ASSIGNMENT_STATE_INVALID)


def test_revision_limit_reached_on_resume_rejected(api):
    """PRD §3.5: "the `revision_round` count has not gone past the permitted ceiling
    of two revision rounds — resumption is allowed only while `revision_round` is at
    most two, and once it exceeds that ceiling the resume is blocked with
    `ERR_REVISION_LIMIT_REACHED`."

    Design: Corner/errors/error_revision_limit_reached_on_resume
    """
    ctx = fixtures.setup_under_review_application(
        endowment_cents=2_000_000, min_gpa=2.00, max_award_cents=500_000,
        requested_amount_cents=100_000, verified_gpa=3.00,
        scores=[(70, 70, 70)], num_members=1,
    )
    app = ctx["application"]
    # Three request-revision cycles drive revision_round to 3 (> ceiling 2).
    validate_success(api.request_revision_application(app["id"], ADMIN))
    validate_success(api.start_review_application(app["id"], ADMIN))
    validate_success(api.request_revision_application(app["id"], ADMIN))
    validate_success(api.start_review_application(app["id"], ADMIN))
    validate_success(api.request_revision_application(app["id"], ADMIN))
    validate_error(api.start_review_application(app["id"], ADMIN), ApiErrorId.ERR_REVISION_LIMIT_REACHED)
    after = validate_success(api.get_application(app["id"], ADMIN))
    assert after["status"] == "NEEDS_REVISION"


def test_not_score_owner_on_submit_rejected(api):
    """PRD §2.1: "A committee member acting on a rubric score they do not own is
    rejected with `ERR_NOT_SCORE_OWNER`"

    Design: Corner/errors/error_not_score_owner_on_submit
    """
    ctx = fixtures.setup_under_review_application(
        endowment_cents=500_000, min_gpa=2.00, max_award_cents=500_000,
        requested_amount_cents=100_000, verified_gpa=3.00,
        scores=[(80, 80, 80), (80, 80, 80)],
    )
    app = ctx["application"]
    member_a, member_b = ctx["members"][0], ctx["members"][1]
    mh_a = make_committee_member_headers(member_a["id"])
    sp = create_rubric_score_payload(app["id"], member_a["id"], academic_score=80, need_score=80, essay_score=80)
    score = validate_success(api.create_rubric_score(sp, mh_a), 201)
    # member_b attempts to submit member_a's score.
    mh_b = make_committee_member_headers(member_b["id"])
    validate_error(api.submit_rubric_score(score["id"], mh_b), ApiErrorId.ERR_NOT_SCORE_OWNER)


def test_not_assignment_owner_on_decline_rejected(api):
    """PRD §2.1: "and on a committee assignment they do not own with
    `ERR_NOT_ASSIGNMENT_OWNER`."

    Design: Corner/errors/error_not_assignment_owner_on_decline
    """
    fund = fixtures.create_open_fund(endowment_cents=500_000, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_application(fund["id"], applicant["id"], requested_amount_cents=100_000)
    member_a = fixtures.create_member(email="ra@x.edu")
    member_b = fixtures.create_member(email="rb@x.edu")
    assignment = fixtures.assign_member(app["id"], member_a["id"])
    mh_b = make_committee_member_headers(member_b["id"])
    validate_error(api.decline_committee_assignment(assignment["id"], mh_b), ApiErrorId.ERR_NOT_ASSIGNMENT_OWNER)


def test_renewal_on_committed_award_rejected_not_active(api):
    """PRD §3.8: "A `FoundationAdmin` opens a renewal review, which moves the award
    from `ACTIVE` to `RENEWAL_PENDING`; this requires the award to be `ACTIVE`
    (otherwise `ERR_AWARD_NOT_ACTIVE`)."

    Design: Corner/errors/error_award_not_active_on_renewal_for_committed_award
    """
    ctx = fixtures.setup_committed_award(
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=1_000_000, verified_gpa=3.50,
        scores=[(95, 90, 85), (95, 90, 85)],
    )
    award_id = ctx["award"]["id"]
    from test_helpers import create_renewal_review_payload
    validate_error(
        api.create_renewal_review(create_renewal_review_payload(award_id, reported_gpa=3.40), ADMIN),
        ApiErrorId.ERR_AWARD_NOT_ACTIVE,
    )


# ===========================================================================
# Queue B — rbac
# ===========================================================================
def test_applicant_cannot_create_fund(api):
    """PRD §2.1: "When a syntactically valid request is made by a role that is not
    permitted to perform the operation, the system responds with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/applicant_cannot_create_fund
    """
    applicant = fixtures.create_applicant()
    headers = make_applicant_headers(applicant["id"])
    payload = create_fund_payload(fund_name="Sneaky", endowment_cents=100_000)
    validate_error(api.create_fund(payload, headers), ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_committee_member_cannot_disburse(api):
    """PRD §2.5: "Role authorization is second: a role not permitted for the operation
    (`ERR_FORBIDDEN_ROLE`) is rejected before any resource is loaded."

    Design: Corner/rbac/committee_member_cannot_disburse
    """
    member = fixtures.create_member()
    headers = make_committee_member_headers(member["id"])
    validate_error(
        api.disburse_award(NON_EXISTENT_UUID, disburse_payload("I"), headers),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
    )


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "If either header is missing or invalid, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    bad_headers = make_headers("NotARole", "someone")
    validate_error(api.list_funds(bad_headers), ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT)


def test_applicant_cannot_submit_other_applicants_application(api):
    """PRD §3.3: "and that the acting applicant owns it — that is, `X-User-ID` equals
    the application's `applicant_id` (otherwise `ERR_NOT_APPLICATION_OWNER`)."

    Design: Corner/rbac/applicant_cannot_submit_other_applicants_application
    """
    fund = fixtures.create_open_fund(endowment_cents=500_000, max_award_cents=500_000)
    applicant_a = fixtures.create_applicant(email="a@x.edu")
    applicant_b = fixtures.create_applicant(email="b@x.edu")
    app = fixtures.create_draft_application_with_docs(
        fund["id"], applicant_a["id"], requested_amount_cents=100_000, verified_gpa=3.00,
    )
    headers_b = make_applicant_headers(applicant_b["id"])
    validate_error(api.submit_application(app["id"], headers_b), ApiErrorId.ERR_NOT_APPLICATION_OWNER)
    after = validate_success(api.get_application(app["id"], ADMIN))
    assert after["status"] == "DRAFT"
