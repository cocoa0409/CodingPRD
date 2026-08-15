"""Study submission gates, peer review (segregation of duties, range-width
gate, revision loop), the quarter-close checkpoint, roll-forward anchoring,
and the transaction/pattern staleness cascades (PRD §2.7, §2.8, §2.10, §3.4,
§3.7, §3.9).
"""
from test_helpers import (
    ApiErrorId,
    create_study,
    make_actuarial_analyst_headers,
    make_peer_reviewer_headers,
    post_payment,
    setup_main_book_study,
    setup_main_book_with_run,
    setup_minimal_book,
    setup_minimal_book_study,
    setup_minimal_book_with_run,
    validate_error,
    validate_success,
)


class TestSubmissionGates:
    def test_submit_without_matching_method_run_rejected(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.7: "Second, a run matching the study's segment, valuation
        quarter, selected method, and selected basis must exist at all —
        otherwise `ERR_NO_SELECTED_RUN`."

        Design: Corner/validations/submit_without_matching_method_run_rejected
        """
        ctx = setup_minimal_book_with_run()  # CHAIN_LADDER / PAID run at 2025-Q1
        study = create_study(
            ctx["segment"]["id"],
            "2025-Q1",
            selected_method="BORNHUETTER_FERGUSON",
            selected_basis="PAID",
        )
        resp = api.submit_study(study["id"], actuarial_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_NO_SELECTED_RUN)

    def test_submit_with_stale_data_flag_rejected(self, api, actuarial_analyst_headers):
        """PRD §3.7: "First, the `stale_data_flag` must be false — an
        unacknowledged cascade surfaces as `ERR_STUDY_STALE_DATA` rather than
        being masked by the later checks."
        PRD §2.7: "Whenever the matched run of an `IN_REVIEW` reserving study
        turns stale, the study is reverted by the system from `IN_REVIEW` back
        to `DRAFT`, its `stale_data_flag` is set to true, and its `updated_at`
        is refreshed and `version` incremented."

        Design: Corner/validations/submit_with_stale_data_flag_rejected
        """
        ctx = setup_minimal_book_study(status="IN_REVIEW")
        # A payment inside the triangle's valuation quarter fires the cascade.
        post_payment(ctx["claim"]["id"], "2025-02-20T00:00:00Z", 2000)

        resp = api.submit_study(ctx["study"]["id"], actuarial_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_STUDY_STALE_DATA)

        data = validate_success(
            api.get_study(ctx["study"]["id"], actuarial_analyst_headers)
        )
        assert data["status"] == "DRAFT"
        assert data["stale_data_flag"] is True

    def test_study_submit_gated_on_run_freshness(self, api, actuarial_analyst_headers):
        """PRD §3.7: "Third, the matched run must be fresh — when every match
        is stale, the submission fails with `ERR_RUN_STALE`."

        Design: Difficulty/cross_entity_state_dependency/study_submit_gated_on_run_freshness
        """
        ctx = setup_main_book_with_run(include_claim_d=False)
        study = create_study(ctx["segment"]["id"], "2025-Q3", "CHAIN_LADDER", "PAID")
        # The payment's effective quarter (2025-Q3) is on the triangle's
        # valuation quarter, so the triangle — and the run — turn stale.
        post_payment(ctx["claims"]["C-B"]["id"], "2025-09-20T00:00:00Z", 5000)

        resp = api.submit_study(study["id"], actuarial_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_RUN_STALE)

    def test_study_submit_gated_on_run_freshness_state_unchanged(
        self, api, actuarial_analyst_headers
    ):
        """PRD §2.7: "Stale runs are immutable: they are never recomputed in
        place, and a fresh estimate is produced only by creating a new run."
        PRD §3.7: "Submission moves the study from `DRAFT` to `IN_REVIEW` and
        applies its three checks in a fixed order."

        Design: Difficulty/cross_entity_state_dependency/study_submit_gated_on_run_freshness
        """
        ctx = setup_main_book_with_run(include_claim_d=False)
        study = create_study(ctx["segment"]["id"], "2025-Q3", "CHAIN_LADDER", "PAID")
        post_payment(ctx["claims"]["C-B"]["id"], "2025-09-20T00:00:00Z", 5000)

        resp = api.submit_study(study["id"], actuarial_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_RUN_STALE)

        run = validate_success(
            api.get_reserve_run(ctx["run"]["id"], actuarial_analyst_headers)
        )
        assert run["is_stale"] is True
        data = validate_success(api.get_study(study["id"], actuarial_analyst_headers))
        assert data["status"] == "DRAFT", "the rejected submission leaves the study DRAFT"
        assert data["stale_data_flag"] is False, (
            "the study never reached IN_REVIEW, so no cascade acknowledgement is pending"
        )


class TestReviewAndQuarterClose:
    def test_study_draft_in_review_revision_loop(self, api):
        """PRD §3.7: "Rejection returns the study to `DRAFT`, likewise records
        `reviewed_by_user_id`, and the study may be revised and re-submitted —
        the revision loop."
        PRD §3.7: "The review carries a `decision` of `APPROVE` or `REJECT`."

        Design: Difficulty/non_linear_state_machine/study_draft_in_review_revision_loop
        """
        ctx = setup_main_book_study(status="DRAFT")
        study_id = ctx["study"]["id"]
        analyst = make_actuarial_analyst_headers("analyst-1")
        reviewer = make_peer_reviewer_headers("reviewer-1")

        data = validate_success(api.submit_study(study_id, analyst), 200)
        assert data["status"] == "IN_REVIEW"

        resp = api.review_study(study_id, {"decision": "REJECT"}, reviewer)
        data = validate_success(resp, 200)
        assert data["status"] == "DRAFT", "the reject edge loops back to DRAFT"
        assert data["reviewed_by_user_id"] == "reviewer-1"

        data = validate_success(api.submit_study(study_id, analyst), 200)
        assert data["status"] == "IN_REVIEW", "re-submission after rejection is legal"

        resp = api.review_study(
            study_id,
            {"decision": "APPROVE", "chief_actuary_override": True},
            reviewer,
        )
        data = validate_success(resp, 200)
        assert data["status"] == "APPROVED"
        assert data["reviewed_by_user_id"] == "reviewer-1"

    def test_study_approval_fires_quarter_close_checkpoint(self, api):
        """PRD §3.7: "Approval records the reviewer in `reviewed_by_user_id`
        and fires the quarter-close checkpoint: the segment's
        `last_closed_quarter` advances to the later of its current value and
        the study's valuation quarter, with a null checkpoint treated as
        earlier than any quarter label."

        Design: Difficulty/non_linear_state_machine/study_draft_in_review_revision_loop
        """
        ctx = setup_main_book_study(status="APPROVED")
        segment = validate_success(
            api.get_segment(ctx["segment"]["id"], make_actuarial_analyst_headers("analyst-1"))
        )
        assert segment["last_closed_quarter"] == "2025-Q3", (
            "approving the 2025-Q3 study advances the checkpoint from null to 2025-Q3"
        )

    def test_review_state_precedes_range_fiscal(self, api):
        """PRD §2.8: "Beyond existence, every request is evaluated against
        eleven ordered validation tiers, and the first failing tier determines
        the error returned"
        PRD §3.7: "Acting on a `LOCKED` or `WITHDRAWN` study — or submitting,
        reviewing, revising, or withdrawing from a status the transition does
        not start from — is refused with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/review_state_precedes_range_fiscal
        """
        ctx = setup_main_book_study(status="DRAFT")  # never submitted
        resp = api.review_study(
            ctx["study"]["id"],
            {"decision": "APPROVE"},
            make_peer_reviewer_headers("reviewer-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_review_of_draft_study_leaves_no_side_effects(self, api):
        """PRD §2.8: "Because the tiers are ordered, an earlier failure masks a
        later one: a payload that is both malformed and aimed at a closed
        quarter is answered with `ERR_INVALID_REQUEST`, and a request against a
        missing segment is answered with `ERR_NOT_FOUND` regardless of what
        business rules the payload would also violate."
        PRD §3.1: "Every segment carries a computed `last_closed_quarter`: the
        maximum valuation quarter across the segment's `APPROVED` studies, or
        null when no study has been approved yet."

        Design: Difficulty/priority_pair_validation_conflict/review_state_precedes_range_fiscal
        """
        ctx = setup_main_book_study(status="DRAFT")
        resp = api.review_study(
            ctx["study"]["id"],
            {"decision": "APPROVE"},
            make_peer_reviewer_headers("reviewer-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        study = validate_success(
            api.get_study(ctx["study"]["id"], make_actuarial_analyst_headers("analyst-1"))
        )
        assert study["status"] == "DRAFT", "a rejected review changes nothing"
        segment = validate_success(
            api.get_segment(ctx["segment"]["id"], make_actuarial_analyst_headers("analyst-1"))
        )
        assert segment["last_closed_quarter"] is None, (
            "the quarter-close checkpoint fires only on a successful approval"
        )

    def test_range_width_exceeded_requires_chief_override(self, api):
        """PRD §3.7: "Approval additionally passes the range-width gate: the
        width of the indicated range — `selected_range_high_cents` minus
        `selected_range_low_cents` — divided by `selected_ibnr_cents` must not
        exceed the segment's `max_range_width_pct`; when the selected IBNR is
        zero, the width ratio is taken as zero. A chief-actuary override exists
        for exceptional quarters: when the review carries
        `chief_actuary_override` as true, the gate is waived; without it, an
        over-wide range is refused with `ERR_RANGE_WIDTH_EXCEEDED`."

        Design: Corner/validations/range_width_exceeded_requires_chief_override
        """
        ctx = setup_main_book_study(status="IN_REVIEW")
        reviewer = make_peer_reviewer_headers("reviewer-1")

        # The range band is pinned at 0.75x / 1.50x of IBNR, so the width ratio
        # is 0.75 against a segment cap of 0.5.
        resp = api.review_study(ctx["study"]["id"], {"decision": "APPROVE"}, reviewer)
        validate_error(resp, ApiErrorId.ERR_RANGE_WIDTH_EXCEEDED)

        resp = api.review_study(
            ctx["study"]["id"],
            {"decision": "APPROVE", "chief_actuary_override": True},
            reviewer,
        )
        data = validate_success(resp, 200)
        assert data["status"] == "APPROVED"

    def test_reviewer_who_prepared_study_rejected(self, api):
        """PRD §2.10: "First, the preparer of a reserving study may not review
        it: a peer-review decision is rejected with
        `ERR_SOD_REVIEWER_IS_PREPARER` (403) whenever the reviewer's
        `X-User-ID` equals the study's `created_by_user_id`, and this holds for
        approval and rejection alike."

        Design: Corner/validations/reviewer_who_prepared_study_rejected
        """
        ctx = setup_minimal_book_study(status="IN_REVIEW")
        # The same operator id that created the study, wearing the reviewer role.
        resp = api.review_study(
            ctx["study"]["id"],
            {"decision": "APPROVE"},
            make_peer_reviewer_headers("analyst-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_REVIEWER_IS_PREPARER)

        study = validate_success(
            api.get_study(ctx["study"]["id"], make_actuarial_analyst_headers("analyst-1"))
        )
        assert study["status"] == "IN_REVIEW"

    def test_quarter_closed_back_dated_transaction_rejected(
        self, api, claims_examiner_headers
    ):
        """PRD §3.7: "From then on, any transaction whose effective quarter is
        on or before the checkpoint is refused with `ERR_QUARTER_CLOSED`."

        Design: Corner/validations/quarter_closed_back_dated_transaction_rejected
        """
        ctx = setup_minimal_book_study(status="APPROVED")  # closes 2025-Q1

        resp = api.post_claim_transaction(
            ctx["claim"]["id"],
            {
                "type": "PAYMENT",
                "transaction_date": "2025-02-20T00:00:00Z",
                "amount_cents": 1000,
            },
            claims_examiner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_QUARTER_CLOSED)

        resp = api.post_claim_transaction(
            ctx["claim"]["id"],
            {
                "type": "PAYMENT",
                "transaction_date": "2025-04-05T00:00:00Z",
                "amount_cents": 1000,
            },
            claims_examiner_headers,
        )
        data = validate_success(resp, 201)
        assert data["effective_quarter"] == "2025-Q2", (
            "2025-Q2 is strictly later than the closed quarter 2025-Q1"
        )


class TestStalenessCascades:
    def test_transaction_posting_staleness_cascade(self, api, actuarial_analyst_headers):
        """PRD §2.7: "Posting a claim transaction sets `is_stale` to true on
        every triangle of the segment whose valuation quarter is on or after
        the transaction's effective quarter."
        PRD §3.2: "A `PAYMENT` requires a positive `amount_cents` and adds that
        amount to paid-to-date."

        Design: Difficulty/transitive_cascade/transaction_posting_staleness_cascade
        """
        ctx = setup_main_book_study(status="IN_REVIEW")
        post_payment(ctx["claims"]["C-A"]["id"], "2025-09-15T00:00:00Z", 60000)

        claim = validate_success(
            api.get_claim(ctx["claims"]["C-A"]["id"], actuarial_analyst_headers)
        )
        assert claim["paid_to_date_cents"] == 310000, (
            "100000 + 100000 + 50000 + the new 60000 payment"
        )
        triangle = validate_success(
            api.get_triangle(ctx["triangle"]["id"], actuarial_analyst_headers)
        )
        assert triangle["is_stale"] is True, (
            "the transaction's effective quarter 2025-Q3 is on the valuation quarter"
        )

    def test_transaction_posting_staleness_cascade_reverts_study(
        self, api, actuarial_analyst_headers
    ):
        """PRD §2.7: "A triangle turning stale in turn sets `is_stale` on every
        reserve run computed from it"
        PRD §2.7: "Whenever the matched run of an `IN_REVIEW` reserving study
        turns stale, the study is reverted by the system from `IN_REVIEW` back
        to `DRAFT`, its `stale_data_flag` is set to true, and its `updated_at`
        is refreshed and `version` incremented."

        Design: Difficulty/transitive_cascade/transaction_posting_staleness_cascade
        """
        ctx = setup_main_book_study(status="IN_REVIEW")
        post_payment(ctx["claims"]["C-A"]["id"], "2025-09-15T00:00:00Z", 60000)

        run = validate_success(
            api.get_reserve_run(ctx["run"]["id"], actuarial_analyst_headers)
        )
        assert run["is_stale"] is True
        study = validate_success(
            api.get_study(ctx["study"]["id"], actuarial_analyst_headers)
        )
        assert study["status"] == "DRAFT", "the cascade reverts IN_REVIEW to DRAFT"
        assert study["stale_data_flag"] is True

    def test_pattern_withdrawal_staleness_cascade(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.4: "Withdrawal fires the pattern-side staleness cascade:
        every reserve run built on this pattern with a valuation quarter inside
        the window becomes stale, and every `IN_REVIEW` study of the segment
        whose matched run turned stale reverts to `DRAFT` with its
        `stale_data_flag` set (§2.7)."

        Design: Difficulty/transitive_cascade/pattern_withdrawal_staleness_cascade
        """
        ctx = setup_main_book_study(status="IN_REVIEW")
        resp = api.withdraw_development_pattern(
            ctx["pattern"]["id"], actuarial_analyst_headers
        )
        data = validate_success(resp, 200)
        assert data["status"] == "WITHDRAWN"

        run = validate_success(
            api.get_reserve_run(ctx["run"]["id"], actuarial_analyst_headers)
        )
        assert run["is_stale"] is True, (
            "the run's valuation quarter 2025-Q3 lies inside the withdrawn window"
        )

    def test_pattern_withdrawal_staleness_cascade_reverts_study(
        self, api, actuarial_analyst_headers
    ):
        """PRD §2.7: "a run's `is_stale` likewise becomes true when its
        triangle was re-aggregated after the run was computed or when the
        development pattern it used is later withdrawn."
        PRD §2.7: "Whenever the matched run of an `IN_REVIEW` reserving study
        turns stale, the study is reverted by the system from `IN_REVIEW` back
        to `DRAFT`, its `stale_data_flag` is set to true, and its `updated_at`
        is refreshed and `version` incremented."

        Design: Difficulty/transitive_cascade/pattern_withdrawal_staleness_cascade
        """
        ctx = setup_main_book_study(status="IN_REVIEW")
        resp = api.withdraw_development_pattern(
            ctx["pattern"]["id"], actuarial_analyst_headers
        )
        validate_success(resp, 200)

        study = validate_success(
            api.get_study(ctx["study"]["id"], actuarial_analyst_headers)
        )
        assert study["status"] == "DRAFT"
        assert study["stale_data_flag"] is True


class TestRollForwardAnchoring:
    def test_rollforward_without_prior_approved_study_rejected(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.9: "That prior study must be `APPROVED`; if no such study
        exists, or it exists in any other status, the request fails with
        `ERR_NO_APPROVED_PRIOR_STUDY`."

        Design: Corner/endpoints/rollforward_without_prior_approved_study_rejected
        """
        ctx = setup_minimal_book()  # claims and transactions, but no study at all
        resp = api.create_roll_forward(
            {"segment_id": ctx["segment"]["id"], "valuation_quarter": "2025-Q2"},
            actuarial_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_APPROVED_PRIOR_STUDY)
