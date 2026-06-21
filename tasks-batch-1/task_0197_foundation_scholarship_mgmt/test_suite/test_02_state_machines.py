"""State-machine tests: review/revision and award/renewal cycles, transition
preconditions, terminal-state lockdown, and initial-state behavior.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_applicant_headers,
    make_committee_member_headers,
    create_rubric_score_payload,
    create_criteria_payload,
    create_fund_payload,
    award_payload,
    create_renewal_review_payload,
    fixtures,
)

ADMIN = TEST_USERS["foundation_admin_headers"]
OFFICER = TEST_USERS["disbursement_officer_headers"]


# ===========================================================================
# Queue A — non_linear_state_machine
# ===========================================================================
def test_application_review_revision_cycle_loop(api):
    """PRD §3.5: "Two side effects accompany a revision request: the application's
    read-only `revision_round` counter is increased by one, and every rubric score on
    the application that is in `SUBMITTED` status is automatically transitioned to
    `RETRACTED` so that those scores leave the scoring pool. The application's
    `rubric_total` remains null through this step."
    PRD §3.5: "The same start-review action resumes a returned application, advancing
    it from `NEEDS_REVISION` back to `UNDER_REVIEW`."

    Design: Difficulty/non_linear_state_machine/application_review_revision_cycle_loop
    """
    ctx = fixtures.setup_under_review_application(
        endowment_cents=3_000_000, min_gpa=2.00, max_award_cents=500_000,
        requested_amount_cents=300_000, verified_gpa=3.00,
        scores=[(70, 70, 70), (70, 70, 70)],
    )
    app = ctx["application"]
    members = ctx["members"]
    score_ids = []
    for member in members:
        mh = make_committee_member_headers(member["id"])
        sp = create_rubric_score_payload(app["id"], member["id"], academic_score=70, need_score=70, essay_score=70)
        score = validate_success(api.create_rubric_score(sp, mh), 201)
        validate_success(api.submit_rubric_score(score["id"], mh))
        score_ids.append(score["id"])

    revised = validate_success(api.request_revision_application(app["id"], ADMIN))
    assert revised["status"] == "NEEDS_REVISION"
    assert revised["revision_round"] == 1
    assert revised["rubric_total"] is None
    retracted = validate_success(api.get_rubric_score(score_ids[0], ADMIN))
    assert retracted["status"] == "RETRACTED"

    resumed = validate_success(api.start_review_application(app["id"], ADMIN))
    assert resumed["status"] == "UNDER_REVIEW"
    assert resumed["revision_round"] == 1
    assert resumed["rubric_total"] is None


def test_award_renewal_pending_cycle_back_to_active(api):
    """PRD §3.8: "Approving a renewal review moves the award from `RENEWAL_PENDING`
    back to `ACTIVE` and re-commits a term."
    PRD §3.8: "On approval the review's status becomes `APPROVED`, the award's
    `term_index` is increased by one, and the fund's `committed_cents` is increased by
    the award's `provisional_award_cents` with `available_cents` recomputed"

    Design: Difficulty/non_linear_state_machine/award_renewal_pending_cycle_back_to_active
    """
    ctx = fixtures.setup_renewal_pending_award(
        reported_gpa=3.40,
        endowment_cents=9_000_000, min_gpa=3.00, max_award_cents=1_000_000,
        requested_amount_cents=1_000_000, verified_gpa=3.80,
        scores=[(95, 95, 95), (95, 95, 95)],
    )
    award_id = ctx["award"]["id"]
    review_id = ctx["renewal_review"]["id"]
    review = validate_success(api.approve_renewal_review(review_id, ADMIN))
    assert review["status"] == "APPROVED"
    award_after = validate_success(api.get_award(award_id, ADMIN))
    assert award_after["status"] == "ACTIVE"
    assert award_after["term_index"] == 2


# ===========================================================================
# Queue B — state_machines (precondition / terminal / initial)
# ===========================================================================
def test_open_fund_twice_rejected_invalid_state(api):
    """PRD §3.1: "Opening the fund moves it from `DRAFT` to `OPEN`; this requires the
    fund to currently be in `DRAFT` (otherwise `ERR_FUND_STATE_INVALID`)"

    Design: Corner/state_machines/open_fund_twice_rejected_invalid_state
    """
    fund = fixtures.create_open_fund(endowment_cents=500_000, max_award_cents=500_000)
    validate_error(api.open_fund(fund["id"], ADMIN), ApiErrorId.ERR_FUND_STATE_INVALID)
    after = validate_success(api.get_fund(fund["id"], ADMIN))
    assert after["status"] == "OPEN"


def test_open_fund_without_criteria_rejected(api):
    """PRD §3.1: "Opening the fund moves it from `DRAFT` to `OPEN`; this requires the
    fund to currently be in `DRAFT` (otherwise `ERR_FUND_STATE_INVALID`) and requires
    that exactly one eligibility criteria is attached (otherwise
    `ERR_CRITERIA_REQUIRED`)."

    Design: Corner/state_machines/open_fund_without_criteria_rejected
    """
    fund = fixtures.create_fund(endowment_cents=500_000)
    validate_error(api.open_fund(fund["id"], ADMIN), ApiErrorId.ERR_CRITERIA_REQUIRED)


def test_duplicate_eligibility_criteria_rejected(api):
    """PRD §3.1: "A fund may have at most one criteria record: an attempt to attach a
    second criteria to a fund that already has one is rejected with
    `ERR_DUPLICATE_CRITERIA`."

    Design: Corner/state_machines/duplicate_eligibility_criteria_rejected
    """
    fund = fixtures.create_fund(endowment_cents=500_000)
    fixtures.create_criteria(fund["id"], min_gpa=2.00, max_award_cents=500_000)
    payload = create_criteria_payload(
        fund["id"], min_gpa=3.00, required_residency_state="CA",
        required_field_of_study="ANY", max_award_cents=600_000,
    )
    validate_error(api.create_criteria(payload, ADMIN), ApiErrorId.ERR_DUPLICATE_CRITERIA)


def test_submit_without_recommendation_rejected(api):
    """PRD §3.3: "The application must carry at least one recommendation (otherwise
    `ERR_RECOMMENDATION_REQUIRED`) and must carry exactly one transcript (otherwise
    `ERR_TRANSCRIPT_REQUIRED`)."

    Design: Corner/state_machines/submit_without_recommendation_rejected
    """
    fund = fixtures.create_open_fund(endowment_cents=500_000, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_draft_application_with_docs(
        fund["id"], applicant["id"], requested_amount_cents=100_000,
        with_recommendation=False, with_transcript=True,
    )
    headers = make_applicant_headers(applicant["id"])
    validate_error(api.submit_application(app["id"], headers), ApiErrorId.ERR_RECOMMENDATION_REQUIRED)
    after = validate_success(api.get_application(app["id"], ADMIN))
    assert after["status"] == "DRAFT"


def test_submit_without_transcript_rejected(api):
    """PRD §3.3: "The application must carry at least one recommendation (otherwise
    `ERR_RECOMMENDATION_REQUIRED`) and must carry exactly one transcript (otherwise
    `ERR_TRANSCRIPT_REQUIRED`)."

    Design: Corner/state_machines/submit_without_transcript_rejected
    """
    fund = fixtures.create_open_fund(endowment_cents=500_000, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_draft_application_with_docs(
        fund["id"], applicant["id"], requested_amount_cents=100_000,
        with_recommendation=True, with_transcript=False,
    )
    headers = make_applicant_headers(applicant["id"])
    validate_error(api.submit_application(app["id"], headers), ApiErrorId.ERR_TRANSCRIPT_REQUIRED)


def test_start_review_not_eligible_rejected(api):
    """PRD §3.5: "that the application's `eligibility_matched` is true (otherwise
    `ERR_NOT_ELIGIBLE`)"

    Design: Corner/state_machines/start_review_not_eligible_rejected
    """
    fund = fixtures.create_open_fund(endowment_cents=500_000, min_gpa=3.50, max_award_cents=500_000)
    applicant = fixtures.create_applicant(self_reported_gpa=3.90, residency_state="CA")
    app = fixtures.create_draft_application_with_docs(
        fund["id"], applicant["id"], requested_amount_cents=100_000, verified_gpa=2.50,
    )
    member = fixtures.create_member()
    fixtures.assign_member(app["id"], member["id"])
    headers = make_applicant_headers(applicant["id"])
    submitted = validate_success(api.submit_application(app["id"], headers))
    assert submitted["eligibility_matched"] is False
    validate_success(api.begin_review_fund(fund["id"], ADMIN))
    validate_error(api.start_review_application(app["id"], ADMIN), ApiErrorId.ERR_NOT_ELIGIBLE)
    after = validate_success(api.get_application(app["id"], ADMIN))
    assert after["status"] == "SUBMITTED"


def test_start_review_without_committee_rejected(api):
    """PRD §3.5: "and that the application has at least one committee assignment in
    `ASSIGNED` status (otherwise `ERR_NO_COMMITTEE_ASSIGNED`)."

    Design: Corner/state_machines/start_review_without_committee_rejected
    """
    fund = fixtures.create_open_fund(endowment_cents=500_000, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_draft_application_with_docs(
        fund["id"], applicant["id"], requested_amount_cents=100_000, verified_gpa=3.00,
    )
    headers = make_applicant_headers(applicant["id"])
    validate_success(api.submit_application(app["id"], headers))
    validate_success(api.begin_review_fund(fund["id"], ADMIN))
    validate_error(api.start_review_application(app["id"], ADMIN), ApiErrorId.ERR_NO_COMMITTEE_ASSIGNED)


def test_award_score_below_floor_rejected(api):
    """PRD §3.6: "the application's `rubric_total` must clear the award score floor of
    60, meaning a `rubric_total` of at least 60 (otherwise `ERR_SCORE_BELOW_FLOOR`)"

    Design: Corner/state_machines/award_score_below_floor_rejected
    """
    ctx = fixtures.setup_awarding_scored_application(
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=500_000, verified_gpa=3.00,
        scores=[(50, 50, 50), (50, 50, 50)],
    )
    app = ctx["application"]
    assert app["rubric_total"] == 50.0
    validate_error(
        api.award_application(app["id"], award_payload(ctx["fund_version"]), ADMIN),
        ApiErrorId.ERR_SCORE_BELOW_FLOOR,
    )
    after = validate_success(api.get_application(app["id"], ADMIN))
    assert after["status"] == "SCORED"


def test_disburse_without_acknowledged_stewardship_rejected(api):
    """PRD §3.7: "the award must have exactly one stewardship record in `ACKNOWLEDGED`
    status (otherwise `ERR_STEWARDSHIP_REQUIRED`)."

    Design: Corner/state_machines/disburse_without_acknowledged_stewardship_rejected
    """
    ctx = fixtures.setup_committed_award_with_stewardship(
        acknowledge=False,
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=1_000_000, verified_gpa=3.50,
        scores=[(95, 90, 85), (95, 90, 85)],
    )
    award_id = ctx["award"]["id"]
    from test_helpers import disburse_payload
    validate_error(
        api.disburse_award(award_id, disburse_payload("I"), OFFICER),
        ApiErrorId.ERR_STEWARDSHIP_REQUIRED,
    )
    after = validate_success(api.get_award(award_id, ADMIN))
    assert after["status"] == "COMMITTED"


def test_renewal_approve_gpa_below_floor_rejected(api):
    """PRD §3.8: "Approval requires that the award is in `RENEWAL_PENDING` (otherwise
    `ERR_AWARD_STATE_INVALID`), that the review's `meets_floor` is true (otherwise
    `ERR_GPA_BELOW_FLOOR`)"

    Design: Corner/state_machines/renewal_approve_gpa_below_floor_rejected
    """
    ctx = fixtures.setup_renewal_pending_award(
        reported_gpa=2.90,
        endowment_cents=9_000_000, min_gpa=3.00, max_award_cents=1_000_000,
        requested_amount_cents=1_000_000, verified_gpa=3.50,
        scores=[(95, 95, 95), (95, 95, 95)],
    )
    award_id = ctx["award"]["id"]
    review_id = ctx["renewal_review"]["id"]
    review = validate_success(api.get_renewal_review(review_id, ADMIN))
    assert review["meets_floor"] is False
    validate_error(api.approve_renewal_review(review_id, ADMIN), ApiErrorId.ERR_GPA_BELOW_FLOOR)
    after = validate_success(api.get_award(award_id, ADMIN))
    assert after["status"] == "RENEWAL_PENDING"


def test_stewardship_initial_draft_then_acknowledged(api):
    """PRD §3.7: "A stewardship record is created for an award, referencing the
    `award_id` and carrying the recipient's `thank_you_text`; it opens in `DRAFT`. The
    owning applicant acknowledges it, moving it from `DRAFT` to the terminal
    `ACKNOWLEDGED` state"

    Design: Corner/state_machines/stewardship_acknowledge_initial_state_and_terminal
    """
    ctx = fixtures.setup_committed_award(
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=1_000_000, verified_gpa=3.50,
        scores=[(95, 90, 85), (95, 90, 85)],
    )
    award_id = ctx["award"]["id"]
    applicant = ctx["applicant"]
    from test_helpers import create_stewardship_record_payload
    headers = make_applicant_headers(applicant["id"])
    rec = validate_success(
        api.create_stewardship_record(create_stewardship_record_payload(award_id), headers), 201
    )
    assert rec["status"] == "DRAFT"
    acked = validate_success(api.acknowledge_stewardship_record(rec["id"], headers))
    assert acked["status"] == "ACKNOWLEDGED"
