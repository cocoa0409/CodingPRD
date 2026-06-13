"""Second test per difficulty instance (Queue A requires >= 2 tests per instance).

Each test below targets the same design instance as its counterpart in the earlier
files but asserts a complementary, PRD-derivable aspect (a boundary neighbor, a
freed-slot, a side effect, a different parent/branch state).
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
    create_rubric_score_payload,
    create_committee_assignment_payload,
    create_transcript_payload,
    create_recommendation_payload,
    award_payload,
    disburse_payload,
    create_renewal_review_payload,
    fixtures,
)

ADMIN = TEST_USERS["foundation_admin_headers"]
OFFICER = TEST_USERS["disbursement_officer_headers"]


# ===========================================================================
# dual_variant_calc
# ===========================================================================
def test_final_equals_provisional_when_verified_gpa_high(api):
    """PRD §3.7: "a `verified_gpa` of at least 3.50 selects the high factor of 1.00"
    PRD §3.7: "A disbursement record is created in `PENDING` status, referencing the
    `award_id`, the paying `fund_id`, and the `institution_id`, with its read-only
    `amount_cents` equal to the award's `final_award_cents` at this moment."

    Design: Difficulty/dual_variant_calc/award_provisional_vs_final_diverge_on_same_applicant
    """
    ctx = fixtures.setup_committed_award_with_stewardship(
        acknowledge=True,
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=1_000_000, verified_gpa=3.80,
        scores=[(95, 90, 85), (95, 90, 85)],
    )
    award = ctx["award"]
    assert award["provisional_award_cents"] == 1_000_000
    disb = validate_success(api.disburse_award(award["id"], disburse_payload("INST1"), OFFICER), 201)
    award_after = validate_success(api.get_award(award["id"], ADMIN))
    # factor 1.00 -> final == provisional, and disbursement mirrors final.
    assert award_after["final_award_cents"] == 1_000_000
    assert disb["amount_cents"] == 1_000_000


def test_eligibility_passes_on_verified_gpa_despite_low_self_report(api):
    """PRD §3.3: "Critically, the GPA test uses the registrar-verified GPA from the
    transcript (`verified_gpa`), never the applicant's `self_reported_gpa`."
    PRD §3.3: "The read-only `eligibility_matched` flag is set to true exactly when
    `eligibility_failures` is empty, and false otherwise."

    Design: Difficulty/dual_variant_calc/eligibility_uses_verified_gpa_not_self_reported
    """
    # self_reported below floor, verified above floor -> matched true (uses verified).
    fund = fixtures.create_open_fund(endowment_cents=2_000_000, min_gpa=3.00, max_award_cents=500_000)
    applicant = fixtures.create_applicant(self_reported_gpa=2.00, residency_state="CA")
    app = fixtures.create_draft_application_with_docs(
        fund["id"], applicant["id"], requested_amount_cents=400_000, verified_gpa=3.40,
    )
    headers = make_applicant_headers(applicant["id"])
    submitted = validate_success(api.submit_application(app["id"], headers))
    assert submitted["eligibility_matched"] is True
    assert submitted["eligibility_failures"] == []


# ===========================================================================
# combinatorial_formula
# ===========================================================================
def test_provisional_award_uncapped_when_raw_below_ceiling(api):
    """PRD §3.6: "a `rubric_total` of at least 60 but below 75 selects the low
    multiplier of 0.60"
    PRD §3.6: "The applicant's `requested_amount_cents` is multiplied by the selected
    multiplier and the product is rounded half up to whole cents; that rounded raw
    amount is then capped at the fund criteria's `max_award_cents`, taking the smaller
    of the two."

    Design: Difficulty/combinatorial_formula/provisional_award_nonlinear_tier_times_request_capped
    """
    # rubric_total 70 (two reviewers 70/70/70) -> low tier 0.60; requested 500000;
    # raw 300000 < cap 1000000, so the cap does NOT bind: provisional == 300000.
    ctx = fixtures.setup_awarding_scored_application(
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=500_000, verified_gpa=3.00,
        scores=[(70, 70, 70), (70, 70, 70)],
    )
    app = ctx["application"]
    assert app["rubric_total"] == 70.0
    award = validate_success(
        api.award_application(app["id"], award_payload(ctx["fund_version"]), ADMIN), 201
    )
    assert award["provisional_award_cents"] == 300_000


def test_rubric_total_three_scores_single_final_round(api):
    """PRD §3.5: "the submitted weighted values are summed, that sum is divided by the
    count of submitted scores, and the quotient is rounded half up to two decimal
    places — a single rounding applied only at the very end, after the division."

    Design: Difficulty/combinatorial_formula/rubric_total_sum_then_divide_then_round_once
    """
    # weighted_values: (90,80,70)->83.00, (90,80,70)->83.00, (90,90,90)->90.00.
    # sum 256.00 / 3 = 85.3333 -> single round 85.33.
    ctx = fixtures.setup_under_review_application(
        endowment_cents=9_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=500_000, verified_gpa=3.20,
        scores=[(90, 80, 70), (90, 80, 70), (90, 90, 90)],
    )
    app = ctx["application"]
    members = ctx["members"]
    specs = [(90, 80, 70), (90, 80, 70), (90, 90, 90)]
    for (academic, need, essay), member in zip(specs, members):
        mh = make_committee_member_headers(member["id"])
        sp = create_rubric_score_payload(app["id"], member["id"], academic_score=academic, need_score=need, essay_score=essay)
        score = validate_success(api.create_rubric_score(sp, mh), 201)
        validate_success(api.submit_rubric_score(score["id"], mh))
    scored = validate_success(api.finalize_scoring_application(app["id"], ADMIN))
    assert scored["rubric_total"] == 85.33


# ===========================================================================
# non_linear_state_machine
# ===========================================================================
def test_resume_allowed_at_revision_round_two_boundary(api):
    """PRD §3.5: "resumption is allowed only while `revision_round` is at most two,
    and once it exceeds that ceiling the resume is blocked with
    `ERR_REVISION_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/application_review_revision_cycle_loop
    """
    ctx = fixtures.setup_under_review_application(
        endowment_cents=2_000_000, min_gpa=2.00, max_award_cents=500_000,
        requested_amount_cents=100_000, verified_gpa=3.00,
        scores=[(70, 70, 70)], num_members=1,
    )
    app = ctx["application"]
    # Two revision cycles bring revision_round to 2; the resume at the ceiling is allowed.
    validate_success(api.request_revision_application(app["id"], ADMIN))
    validate_success(api.start_review_application(app["id"], ADMIN))
    revised = validate_success(api.request_revision_application(app["id"], ADMIN))
    assert revised["revision_round"] == 2
    resumed = validate_success(api.start_review_application(app["id"], ADMIN))
    assert resumed["status"] == "UNDER_REVIEW"
    assert resumed["revision_round"] == 2


def test_renewal_approval_recommits_fund_committed_cents(api):
    """PRD §3.8: "On approval the review's status becomes `APPROVED`, the award's
    `term_index` is increased by one, and the fund's `committed_cents` is increased by
    the award's `provisional_award_cents` with `available_cents` recomputed — the
    renewal re-commitment."

    Design: Difficulty/non_linear_state_machine/award_renewal_pending_cycle_back_to_active
    """
    ctx = fixtures.setup_renewal_pending_award(
        reported_gpa=3.40,
        endowment_cents=9_000_000, min_gpa=3.00, max_award_cents=1_000_000,
        requested_amount_cents=1_000_000, verified_gpa=3.80,
        scores=[(95, 95, 95), (95, 95, 95)],
    )
    award = ctx["award"]
    fund_id = ctx["fund"]["id"]
    provisional = award["provisional_award_cents"]
    review_id = ctx["renewal_review"]["id"]
    validate_success(api.approve_renewal_review(review_id, ADMIN))
    fund_after = validate_success(api.get_fund(fund_id, ADMIN))
    # committed reflects the re-commitment of one term's provisional amount.
    assert fund_after["committed_cents"] == provisional
    assert fund_after["available_cents"] == fund_after["endowment_cents"] - provisional


# ===========================================================================
# transitive_cascade
# ===========================================================================
def test_settled_return_cascade_releases_committed_with_different_amount(api):
    """PRD §3.7: "Returning a `SETTLED` disbursement is a deeper compensation: the
    fund's `disbursed_cents` is decreased by the disbursement's `amount_cents`, the
    fund's `committed_cents` is decreased by the award's `provisional_award_cents`,
    `available_cents` is recomputed, and the parent award cascades to the terminal
    `REVOKED` state."

    Design: Difficulty/transitive_cascade/settled_disbursement_return_cascade_depth3
    """
    ctx = fixtures.setup_settled_disbursement(
        institution_id="IX",
        endowment_cents=8_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=800_000, verified_gpa=3.50,
        scores=[(95, 90, 85), (95, 90, 85)],
    )
    award_id = ctx["award"]["id"]
    disb_id = ctx["disbursement"]["id"]
    validate_success(api.return_disbursement(disb_id, OFFICER))
    fund_after = validate_success(api.get_fund(ctx["fund"]["id"], ADMIN))
    assert fund_after["committed_cents"] == 0
    assert fund_after["disbursed_cents"] == 0
    assert fund_after["available_cents"] == 8_000_000
    award_after = validate_success(api.get_award(award_id, ADMIN))
    assert award_after["status"] == "REVOKED"


def test_finalize_scoring_completes_each_assignment(api):
    """PRD §3.5: "Finalize-scoring also cascades to the committee: every committee
    assignment on the application that is in `ASSIGNED` status is transitioned to
    `COMPLETED`, and each affected member's `active_assignment_count` is recomputed
    downward."

    Design: Difficulty/transitive_cascade/finalize_scoring_completes_assignments_decrements_count_depth2
    """
    ctx = fixtures.setup_scored_application(
        endowment_cents=3_000_000, min_gpa=2.00, max_award_cents=500_000,
        requested_amount_cents=300_000, verified_gpa=3.20,
        scores=[(90, 90, 90), (90, 90, 90)],
    )
    app = ctx["application"]
    data, _ = validate_paginated(api.list_committee_assignments(ADMIN, params={"application_id": app["id"]}))
    assert len(data) == 2
    for assignment in data:
        assert assignment["status"] == "COMPLETED"
    for member in ctx["members"]:
        m = validate_success(api.get_committee_member(member["id"], ADMIN))
        assert m["active_assignment_count"] == 0


# ===========================================================================
# priority_pair_validation_conflict
# ===========================================================================
def test_state_beats_fiscal_on_award_draft_state(api):
    """PRD §2.5: "Seventh, the target resource's own state is checked. Only after all
    of these structural gates do the domain-specific business constraints, fiscal
    checks, the optimistic-concurrency check, and finally field-level input validation
    apply"
    PRD §3.6: "The application must be `SCORED` (otherwise
    `ERR_APPLICATION_STATE_INVALID`)"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_award_wrong_state
    """
    # Application still in DRAFT (a different wrong state) on an AWARDING fund whose
    # endowment is too small; the state check pre-empts the fiscal check.
    fund = fixtures.create_open_fund(endowment_cents=100, min_gpa=2.00, max_award_cents=1_000_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_draft_application_with_docs(
        fund["id"], applicant["id"], requested_amount_cents=1_000_000, verified_gpa=3.20,
    )
    # Drive fund to AWARDING without involving the DRAFT application.
    validate_success(api.begin_review_fund(fund["id"], ADMIN))
    validate_success(api.begin_awarding_fund(fund["id"], ADMIN))
    fund_v = validate_success(api.get_fund(fund["id"], ADMIN))["version"]
    validate_error(
        api.award_application(app["id"], award_payload(fund_v), ADMIN),
        ApiErrorId.ERR_APPLICATION_STATE_INVALID,
    )


def test_existence_beats_state_on_decline_missing_assignment_with_valid_member(api):
    """PRD §2.5: "Third, path resource existence is checked left to right, yielding the
    relevant not-found code."
    PRD §2.4: "A path resource that does not exist yields a not-found error specific to
    its type: `ERR_FUND_NOT_FOUND`, `ERR_CRITERIA_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_COMMITTEE_MEMBER_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SCORE_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`,
    `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_RENEWAL_NOT_FOUND`, or
    `ERR_STEWARDSHIP_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_decline_missing_assignment
    """
    # Existence is checked before any state guard: a missing assignment id on decline
    # yields the not-found code rather than a state-invalid code, even with a valid
    # acting member present.
    member = fixtures.create_member()
    headers = make_committee_member_headers(member["id"])
    validate_error(
        api.decline_committee_assignment(NON_EXISTENT_UUID, headers),
        ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
    )


# ===========================================================================
# cross_entity_state_dependency
# ===========================================================================
def test_award_rejected_leaves_fund_in_review_unchanged(api):
    """PRD §3.6: "the owning fund must be in `AWARDING` (otherwise
    `ERR_FUND_NOT_AWARDING`)"

    Design: Difficulty/cross_entity_state_dependency/application_award_requires_fund_awarding
    """
    ctx = fixtures.setup_scored_application(
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=600_000, verified_gpa=3.50,
        scores=[(95, 90, 85), (95, 90, 85)],
    )
    app = ctx["application"]
    fund_id = ctx["fund"]["id"]
    fund_v = validate_success(api.get_fund(fund_id, ADMIN))["version"]
    validate_error(
        api.award_application(app["id"], award_payload(fund_v), ADMIN),
        ApiErrorId.ERR_FUND_NOT_AWARDING,
    )
    fund_after = validate_success(api.get_fund(fund_id, ADMIN))
    assert fund_after["status"] == "REVIEW"
    assert fund_after["committed_cents"] == 0


def test_rubric_submit_blocked_when_application_needs_revision(api):
    """PRD §3.4: "and that the parent application is in `UNDER_REVIEW` (otherwise
    `ERR_APPLICATION_NOT_UNDER_REVIEW`)."

    Design: Difficulty/cross_entity_state_dependency/rubric_submit_requires_application_under_review
    """
    # Create a DRAFT score while UNDER_REVIEW, then push the application to
    # NEEDS_REVISION (DRAFT scores are not retracted), then attempt the submit.
    ctx = fixtures.setup_under_review_application(
        endowment_cents=2_000_000, min_gpa=2.00, max_award_cents=500_000,
        requested_amount_cents=300_000, verified_gpa=3.00,
        scores=[(88, 88, 88)], num_members=1,
    )
    app = ctx["application"]
    member = ctx["members"][0]
    mh = make_committee_member_headers(member["id"])
    sp = create_rubric_score_payload(app["id"], member["id"], academic_score=88, need_score=88, essay_score=88)
    score = validate_success(api.create_rubric_score(sp, mh), 201)
    validate_success(api.request_revision_application(app["id"], ADMIN))  # UNDER_REVIEW -> NEEDS_REVISION
    validate_error(
        api.submit_rubric_score(score["id"], mh),
        ApiErrorId.ERR_APPLICATION_NOT_UNDER_REVIEW,
    )


# ===========================================================================
# boundary_precision_check
# ===========================================================================
def test_eligibility_gpa_just_below_min_fails(api):
    """PRD §3.3: "The GPA criterion passes when the transcript's `verified_gpa` is at
    least the criteria's `min_gpa` (an inclusive comparison at the boundary)."
    PRD §3.3: "a GPA failure is listed before a residency failure, which is listed
    before a field failure."

    Design: Difficulty/boundary_precision_check/eligibility_gpa_at_exact_min_is_inclusive
    """
    # min_gpa 3.00, verified 2.99 (one boundary step below) -> GPA criterion fails.
    fund = fixtures.create_open_fund(endowment_cents=1_000_000, min_gpa=3.00, max_award_cents=500_000)
    applicant = fixtures.create_applicant(self_reported_gpa=3.00, residency_state="CA")
    app = fixtures.create_draft_application_with_docs(
        fund["id"], applicant["id"], requested_amount_cents=300_000, verified_gpa=2.99,
    )
    headers = make_applicant_headers(applicant["id"])
    submitted = validate_success(api.submit_application(app["id"], headers))
    assert submitted["eligibility_matched"] is False
    assert submitted["eligibility_failures"] == ["GPA"]


def test_finalize_scoring_succeeds_at_exact_quorum(api):
    """PRD §3.5: "the count of rubric scores in `SUBMITTED` status meets the scoring
    quorum of at least two submitted scores (otherwise `ERR_QUORUM_NOT_MET`)."

    Design: Difficulty/boundary_precision_check/finalize_scoring_blocked_when_quorum_count_below_two
    """
    # Exactly two SUBMITTED scores (the boundary) -> finalize succeeds.
    ctx = fixtures.setup_scored_application(
        endowment_cents=2_000_000, min_gpa=2.00, max_award_cents=500_000,
        requested_amount_cents=300_000, verified_gpa=3.00,
        scores=[(90, 90, 90), (90, 90, 90)],
    )
    assert ctx["application"]["status"] == "SCORED"
    assert ctx["application"]["rubric_total"] == 90.0


# ===========================================================================
# resource_temporal_overlap
# ===========================================================================
def test_reassignment_allowed_after_decline_frees_slot(api):
    """PRD §3.4: "a member who already holds an `ASSIGNED` assignment on the same
    application cannot be assigned again, which is rejected with
    `ERR_DUPLICATE_ASSIGNMENT`"
    PRD §3.4: "A committee member may decline their own assignment while it is
    `ASSIGNED`, moving it to the terminal `DECLINED` state"

    Design: Difficulty/resource_temporal_overlap/duplicate_committee_assignment_same_member_same_application
    """
    fund = fixtures.create_open_fund(endowment_cents=2_000_000, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_application(fund["id"], applicant["id"], requested_amount_cents=300_000)
    member = fixtures.create_member()
    assignment = fixtures.assign_member(app["id"], member["id"])
    mh = make_committee_member_headers(member["id"])
    validate_success(api.decline_committee_assignment(assignment["id"], mh))
    # Slot freed by DECLINED -> re-assignment of the same member succeeds.
    payload = create_committee_assignment_payload(app["id"], member["id"])
    reassigned = validate_success(api.create_committee_assignment(payload, ADMIN), 201)
    assert reassigned["status"] == "ASSIGNED"


def test_multiple_recommendations_allowed_unlike_singleton_transcript(api):
    """PRD §3.2: "An application may hold many recommendations but at most one
    transcript — uploading a second transcript for the same application is rejected
    with `ERR_DUPLICATE_TRANSCRIPT`."

    Design: Difficulty/resource_temporal_overlap/duplicate_transcript_upload_same_application
    """
    fund = fixtures.create_open_fund(endowment_cents=2_000_000, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_application(fund["id"], applicant["id"], requested_amount_cents=300_000)
    headers = make_applicant_headers(applicant["id"])
    # First transcript accepted.
    validate_success(api.create_transcript(create_transcript_payload(app["id"], document_uri="s3://t1", verified_gpa=3.00), headers), 201)
    # Second transcript on the same application rejected (singleton slot).
    validate_error(
        api.create_transcript(create_transcript_payload(app["id"], document_uri="s3://t2", verified_gpa=3.50), headers),
        ApiErrorId.ERR_DUPLICATE_TRANSCRIPT,
    )
    # A second recommendation, by contrast, is accepted (many allowed).
    validate_success(api.create_recommendation(create_recommendation_payload(app["id"], document_uri="s3://r2"), headers), 201)


# ===========================================================================
# compensating_invariant
# ===========================================================================
def test_award_commits_then_revoke_restores_committed(api):
    """PRD §3.6: "As a cascade, the fund's `committed_cents` is increased by the award's
    `provisional_award_cents`, `available_cents` is recomputed"
    PRD §2.7: "a forward award followed by its revoke leaves `committed_cents` exactly
    as it was before"

    Design: Difficulty/compensating_invariant/award_then_revoke_leaves_committed_cents_unchanged
    """
    ctx = fixtures.setup_committed_award(
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=1_000_000, verified_gpa=3.50,
        scores=[(95, 90, 85), (95, 90, 85)],
    )
    award = ctx["award"]
    fund_id = ctx["fund"]["id"]
    provisional = award["provisional_award_cents"]
    fund_mid = validate_success(api.get_fund(fund_id, ADMIN))
    assert fund_mid["committed_cents"] == provisional
    validate_success(api.revoke_award(award["id"], ADMIN))
    fund_after = validate_success(api.get_fund(fund_id, ADMIN))
    assert fund_after["committed_cents"] == 0
    assert fund_after["available_cents"] == 5_000_000


def test_settle_then_return_leaves_committed_cents_unchanged(api):
    """PRD §2.7: "a settle followed by its return leaves both `disbursed_cents` and
    `committed_cents` exactly as they were before."
    PRD §3.7: "Returning a `SETTLED` disbursement is a deeper compensation: the fund's
    `disbursed_cents` is decreased by the disbursement's `amount_cents`, the fund's
    `committed_cents` is decreased by the award's `provisional_award_cents`"

    Design: Difficulty/compensating_invariant/settle_then_return_leaves_disbursed_cents_unchanged
    """
    ctx = fixtures.setup_settled_disbursement(
        institution_id="I17b",
        endowment_cents=5_000_000, min_gpa=2.00, max_award_cents=1_000_000,
        requested_amount_cents=1_000_000, verified_gpa=3.20,
        scores=[(95, 90, 85), (95, 90, 85)],
    )
    disb_id = ctx["disbursement"]["id"]
    award_id = ctx["award"]["id"]
    validate_success(api.return_disbursement(disb_id, OFFICER))
    fund_after = validate_success(api.get_fund(ctx["fund"]["id"], ADMIN))
    # Both conserved quantities return to their pre-settle baseline of 0.
    assert fund_after["disbursed_cents"] == 0
    assert fund_after["committed_cents"] == 0
    award_after = validate_success(api.get_award(award_id, ADMIN))
    assert award_after["status"] == "REVOKED"
