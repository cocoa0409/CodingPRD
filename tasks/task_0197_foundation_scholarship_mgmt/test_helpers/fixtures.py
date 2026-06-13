"""Composite setup helpers for the Foundation Scholarship Management API.

Each helper builds preconditions from scratch using only PRD-declared endpoints,
because the server database is empty at the start of every test. Setup calls use
get_success_data() (lenient) so a setup failure surfaces as a clear "Setup failed"
rather than an obscure assertion error.

Identity threading: Applicant and CommitteeMember are entity-backed roles, so any
ownership-gated call uses make_applicant_headers(applicant_id) /
make_committee_member_headers(member_id) with the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_committee_member_headers,
)
from . import factories as F

ADMIN = TEST_USERS["foundation_admin_headers"]
OFFICER = TEST_USERS["disbursement_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: Primitive creators
# ---------------------------------------------------------------------------
def create_fund(endowment_cents=5_000_000, **overrides):
    """Create a DRAFT fund. Returns the fund object."""
    payload = F.create_fund_payload(endowment_cents=endowment_cents, **overrides)
    return get_success_data(api_client.create_fund(payload, ADMIN))


def create_criteria(fund_id, min_gpa=2.00, max_award_cents=1_000_000,
                    required_residency_state="ANY", required_field_of_study="ANY", **overrides):
    payload = F.create_criteria_payload(
        fund_id,
        min_gpa=min_gpa,
        max_award_cents=max_award_cents,
        required_residency_state=required_residency_state,
        required_field_of_study=required_field_of_study,
        **overrides,
    )
    return get_success_data(api_client.create_criteria(payload, ADMIN))


def create_open_fund(endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
                     required_residency_state="ANY", required_field_of_study="ANY", **fund_overrides):
    """Create fund + criteria, then OPEN it. Returns the OPEN fund object."""
    fund = create_fund(endowment_cents=endowment_cents, **fund_overrides)
    create_criteria(
        fund["id"], min_gpa=min_gpa, max_award_cents=max_award_cents,
        required_residency_state=required_residency_state,
        required_field_of_study=required_field_of_study,
    )
    get_success_data(api_client.open_fund(fund["id"], ADMIN))
    return get_success_data(api_client.get_fund(fund["id"], ADMIN))


def create_applicant(self_reported_gpa=3.50, residency_state="CA", field_of_study="CS", **overrides):
    payload = F.create_applicant_payload(
        self_reported_gpa=self_reported_gpa,
        residency_state=residency_state,
        field_of_study=field_of_study,
        **overrides,
    )
    return get_success_data(api_client.create_applicant(payload, ADMIN))


def create_member(expertise_field="CS", **overrides):
    payload = F.create_committee_member_payload(expertise_field=expertise_field, **overrides)
    return get_success_data(api_client.create_committee_member(payload, ADMIN))


def create_application(fund_id, applicant_id, requested_amount_cents=500_000, **overrides):
    payload = F.create_application_payload(
        fund_id, applicant_id, requested_amount_cents=requested_amount_cents, **overrides
    )
    headers = make_applicant_headers(applicant_id)
    return get_success_data(api_client.create_application(payload, headers))


def add_recommendation(application_id, applicant_id, **overrides):
    payload = F.create_recommendation_payload(application_id, **overrides)
    headers = make_applicant_headers(applicant_id)
    return get_success_data(api_client.create_recommendation(payload, headers))


def add_transcript(application_id, applicant_id, verified_gpa=3.50, **overrides):
    payload = F.create_transcript_payload(application_id, verified_gpa=verified_gpa, **overrides)
    headers = make_applicant_headers(applicant_id)
    return get_success_data(api_client.create_transcript(payload, headers))


def assign_member(application_id, member_id):
    payload = F.create_committee_assignment_payload(application_id, member_id)
    return get_success_data(api_client.create_committee_assignment(payload, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: Application lifecycle building blocks
# ---------------------------------------------------------------------------
def create_draft_application_with_docs(fund_id, applicant_id, requested_amount_cents=500_000,
                                       verified_gpa=3.50, with_recommendation=True,
                                       with_transcript=True):
    """DRAFT application with optional recommendation + transcript attached.
    Returns the application object."""
    app = create_application(fund_id, applicant_id, requested_amount_cents=requested_amount_cents)
    if with_recommendation:
        add_recommendation(app["id"], applicant_id)
    if with_transcript:
        add_transcript(app["id"], applicant_id, verified_gpa=verified_gpa)
    return app


def setup_submitted_application(endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
                                requested_amount_cents=500_000, verified_gpa=3.50,
                                residency_state="CA", field_of_study="CS",
                                required_residency_state="ANY", required_field_of_study="ANY",
                                num_members=2):
    """Build an OPEN fund, applicant, application with docs, num_members assigned,
    then SUBMIT the application. Returns dict with fund, applicant, application,
    members (list of member objects).
    """
    fund = create_open_fund(
        endowment_cents=endowment_cents, min_gpa=min_gpa, max_award_cents=max_award_cents,
        required_residency_state=required_residency_state,
        required_field_of_study=required_field_of_study,
    )
    applicant = create_applicant(residency_state=residency_state, field_of_study=field_of_study)
    app = create_draft_application_with_docs(
        fund["id"], applicant["id"],
        requested_amount_cents=requested_amount_cents, verified_gpa=verified_gpa,
    )
    members = []
    for i in range(num_members):
        m = create_member(email=f"rev{i}@example.edu")
        assign_member(app["id"], m["id"])
        members.append(m)
    headers = make_applicant_headers(applicant["id"])
    application = get_success_data(api_client.submit_application(app["id"], headers))
    return {
        "fund": fund,
        "applicant": applicant,
        "application": application,
        "members": members,
    }


def setup_under_review_application(scores=None, **kwargs):
    """Submitted application advanced to UNDER_REVIEW.
    `scores` is an optional list of (academic, need, essay) tuples — one DRAFT score
    is created (and submitted) per tuple by the corresponding assigned member.
    Returns dict with fund, applicant, application, members, score_ids (list).
    """
    if scores is None:
        scores = [(90, 90, 90), (90, 90, 90)]
    num_members = max(len(scores), kwargs.pop("num_members", len(scores)))
    ctx = setup_submitted_application(num_members=num_members, **kwargs)
    fund, applicant, app = ctx["fund"], ctx["applicant"], ctx["application"]
    # Fund: OPEN -> REVIEW
    get_success_data(api_client.begin_review_fund(fund["id"], ADMIN))
    # Application: SUBMITTED -> UNDER_REVIEW
    application = get_success_data(api_client.start_review_application(app["id"], ADMIN))
    ctx["application"] = application
    return ctx


def setup_scored_application(scores=None, **kwargs):
    """UNDER_REVIEW application with submitted scores, then finalize-scoring -> SCORED.
    Returns dict with fund, applicant, application, members, score_ids.
    """
    if scores is None:
        scores = [(90, 90, 90), (90, 90, 90)]
    ctx = setup_under_review_application(scores=scores, **kwargs)
    app = ctx["application"]
    members = ctx["members"]
    score_ids = []
    for (academic, need, essay), member in zip(scores, members):
        member_headers = make_committee_member_headers(member["id"])
        payload = F.create_rubric_score_payload(
            app["id"], member["id"],
            academic_score=academic, need_score=need, essay_score=essay,
        )
        score = get_success_data(api_client.create_rubric_score(payload, member_headers))
        get_success_data(api_client.submit_rubric_score(score["id"], member_headers))
        score_ids.append(score["id"])
    ctx["score_ids"] = score_ids
    application = get_success_data(api_client.finalize_scoring_application(app["id"], ADMIN))
    ctx["application"] = application
    return ctx


def setup_awarding_scored_application(scores=None, **kwargs):
    """SCORED application whose fund has been advanced REVIEW -> AWARDING.
    Returns dict with fund (refreshed, AWARDING), applicant, application (SCORED),
    members, score_ids, fund_version (the current fund version, for the OCC field).
    """
    ctx = setup_scored_application(scores=scores, **kwargs)
    fund = ctx["fund"]
    get_success_data(api_client.begin_awarding_fund(fund["id"], ADMIN))
    refreshed = get_success_data(api_client.get_fund(fund["id"], ADMIN))
    ctx["fund"] = refreshed
    ctx["fund_version"] = refreshed["version"]
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: Award lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_committed_award(scores=None, **kwargs):
    """Full pipeline through an awarded application -> Award in COMMITTED status.
    Returns dict with fund, applicant, application, members, score_ids, award.
    """
    if scores is None:
        scores = [(95, 90, 85), (95, 90, 85)]
    ctx = setup_awarding_scored_application(scores=scores, **kwargs)
    app = ctx["application"]
    fund_version = ctx["fund_version"]
    award = get_success_data(
        api_client.award_application(app["id"], F.award_payload(fund_version), ADMIN)
    )
    ctx["award"] = award
    return ctx


def create_stewardship(award_id, applicant_id, acknowledge=True):
    """Create a stewardship record for the award; optionally acknowledge it.
    Returns the stewardship record (post-acknowledge if acknowledge=True)."""
    payload = F.create_stewardship_record_payload(award_id)
    headers = make_applicant_headers(applicant_id)
    rec = get_success_data(api_client.create_stewardship_record(payload, headers))
    if acknowledge:
        rec = get_success_data(api_client.acknowledge_stewardship_record(rec["id"], headers))
    return rec


def setup_committed_award_with_stewardship(acknowledge=True, scores=None, **kwargs):
    """COMMITTED award with a stewardship record (acknowledged by default).
    Returns dict with all of setup_committed_award plus stewardship.
    """
    ctx = setup_committed_award(scores=scores, **kwargs)
    rec = create_stewardship(ctx["award"]["id"], ctx["applicant"]["id"], acknowledge=acknowledge)
    ctx["stewardship"] = rec
    return ctx


def setup_active_award(scores=None, institution_id="INST-TEST", **kwargs):
    """ACTIVE award with a PENDING disbursement (disbursed after stewardship ack).
    Returns dict with fund, applicant, application, members, award (ACTIVE),
    disbursement (PENDING).
    """
    ctx = setup_committed_award_with_stewardship(acknowledge=True, scores=scores, **kwargs)
    award_id = ctx["award"]["id"]
    disb = get_success_data(
        api_client.disburse_award(award_id, F.disburse_payload(institution_id), OFFICER)
    )
    ctx["disbursement"] = disb
    ctx["award"] = get_success_data(api_client.get_award(award_id, ADMIN))
    return ctx


def setup_settled_disbursement(scores=None, institution_id="INST-TEST", **kwargs):
    """ACTIVE award with a SETTLED disbursement.
    Returns dict with award (ACTIVE), disbursement (SETTLED), plus the fund refreshed.
    """
    ctx = setup_active_award(scores=scores, institution_id=institution_id, **kwargs)
    disb_id = ctx["disbursement"]["id"]
    get_success_data(api_client.settle_disbursement(disb_id, OFFICER))
    ctx["disbursement"] = get_success_data(api_client.get_disbursement(disb_id, ADMIN))
    ctx["fund"] = get_success_data(api_client.get_fund(ctx["fund"]["id"], ADMIN))
    return ctx


def setup_renewal_pending_award(reported_gpa=3.40, scores=None, **kwargs):
    """ACTIVE award advanced to RENEWAL_PENDING via a created renewal review.
    Returns dict with award (RENEWAL_PENDING), renewal_review, plus active-award context.
    """
    ctx = setup_active_award(scores=scores, **kwargs)
    award_id = ctx["award"]["id"]
    review = get_success_data(
        api_client.create_renewal_review(
            F.create_renewal_review_payload(award_id, reported_gpa=reported_gpa), ADMIN
        )
    )
    ctx["renewal_review"] = review
    ctx["award"] = get_success_data(api_client.get_award(award_id, ADMIN))
    return ctx
