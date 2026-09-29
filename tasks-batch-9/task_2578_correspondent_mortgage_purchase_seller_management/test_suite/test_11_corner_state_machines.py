"""Onboarding hops, terminal lockdowns and the one-shot nature of each act."""

from test_helpers import (
    ADMIN,
    ANALYST,
    ANALYST_ALT,
    QC,
    REVIEWER,
    TRADER,
    ApiErrorId,
    api_client,
    assert_commitment,
    assert_commitment_amounts_conserved,
    assert_financial_statement,
    assert_qc_review,
    assert_seller,
    factories,
    fixtures,
    make_seller_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStatementAdjudication:
    """Accepting a statement is a statement hop, not a seller hop."""

    def test_accepting_a_statement_records_the_reviewer_and_moves_no_seller_field(self):
        """The seller is a bystander to its own statement being accepted.

        The statement goes terminal, remembers which analyst decided it, keeps the
        note it was decided with and advances one version — while the seller it
        belongs to is left exactly where the registration put it, with no net worth
        frozen and no tier granted.

        PRD: "Both are terminal, both record the acting `X-User-ID` as
        `reviewed_by_user_id`, and both increment the statement's `version` by 1."

        Design: Corner/state_machines/financial_statement_accept_records_reviewer_and_leaves_the_seller_untouched
        """
        fixtures.setup_clock("2026-08-01T00:00:00Z")
        seller = fixtures.setup_seller()
        statement = fixtures.setup_financial_statement(
            seller["id"], actor=make_seller_user_headers(seller["id"])
        )

        reviewed = validate_success(
            api_client.review_financial_statement(
                statement["id"],
                {"decision": "ACCEPT", "review_note": "audited, tie-out complete"},
                ANALYST_ALT,
            ),
            200,
        )

        assert_financial_statement(reviewed)
        assert reviewed["status"] == "ACCEPTED"
        assert reviewed["reviewed_by_user_id"] == "u-ca-2"
        assert reviewed["review_note"] == "audited, tie-out complete"
        assert reviewed["version"] == 2

        untouched = fixtures.read_seller(seller["id"])
        assert untouched["approval_status"] == "APPLIED"
        assert untouched["delivery_standing"] == "NOT_ELIGIBLE"
        assert untouched["approved_tangible_net_worth_cents"] == 0
        assert untouched["approval_tier"] is None


class TestApprovalPreconditionOrder:
    """The approval gates announce themselves one at a time, in order."""

    def test_the_same_seller_is_refused_three_different_ways_before_it_is_approved(self):
        """Each attempt fixes one gate and immediately meets the next one.

        The first decision arrives while the applicant has never been reviewed at
        all, so it is refused on the seller's own state. Opening the review fixes
        that and exposes the missing accepted statement, accepting the statement
        exposes the still-open review, and only completing the review lets the
        fourth attempt through.

        PRD: "Either way the seller must currently be `UNDER_REVIEW` on the
        approval dimension, else `ERR_INVALID_SELLER_STATE`."

        PRD: "If that set is empty — no accepted statement, or only
        accepted-but-unaudited ones — approval fails with
        `ERR_NO_ACCEPTED_STATEMENT`."

        PRD: "The **governing quality-control review** is drawn from the seller's
        reviews whose `status` is `COMPLETED`, ordered by `completed_at` from latest
        to earliest and, among ties, by `created_at` from latest to earliest; again
        the first row governs, and an empty set fails with
        `ERR_QC_REVIEW_NOT_COMPLETED`."

        Design: Corner/state_machines/approval_requires_an_accepted_statement_then_a_completed_qc_review_in_that_order
        """
        fixtures.setup_clock("2026-08-01T00:00:00Z")
        seller = fixtures.setup_seller()
        statement = fixtures.setup_financial_statement(seller["id"])

        def approve():
            return api_client.decide_seller_approval(
                seller["id"], {"decision": "APPROVE"}, ANALYST
            )

        validate_error(approve(), ApiErrorId.ERR_INVALID_SELLER_STATE, 409)
        assert fixtures.read_seller(seller["id"])["approval_status"] == "APPLIED"

        qc_review = fixtures.setup_qc_review(seller["id"], "PRE_APPROVAL")
        assert fixtures.read_seller(seller["id"])["approval_status"] == "UNDER_REVIEW"

        validate_error(approve(), ApiErrorId.ERR_NO_ACCEPTED_STATEMENT, 409)

        fixtures.review_financial_statement(statement["id"], "ACCEPT")

        validate_error(approve(), ApiErrorId.ERR_QC_REVIEW_NOT_COMPLETED, 409)

        fixtures.complete_qc_review(qc_review["id"], 2, 0)

        approved = validate_success(approve(), 200)

        assert_seller(approved)
        assert approved["approval_status"] == "APPROVED"
        assert approved["delivery_standing"] == "GOOD_STANDING"
        assert approved["approval_tier"] == "STANDARD"
        assert approved["mandatory_exposure_limit_cents"] == 3000000000


class TestApprovalQuantitativeGates:
    """Three sellers, each failing exactly one measurable gate."""

    @staticmethod
    def _seller_awaiting_a_decision(
        legal_name: str,
        tin: str,
        seller_type: str,
        statement_overrides: dict,
        findings_count: int,
        critical_findings_count: int,
    ) -> dict:
        fixtures.setup_clock("2026-08-01T00:00:00Z")
        staged = fixtures.setup_seller_under_review(
            seller_overrides={
                "legal_name": legal_name,
                "tin": tin,
                "seller_type": seller_type,
            },
            statement_overrides=statement_overrides,
        )
        staged["qc_review"] = fixtures.complete_qc_review(
            staged["qc_review"]["id"], findings_count, critical_findings_count
        )
        return staged

    @staticmethod
    def _assert_left_under_review(seller_id: str) -> None:
        seller = fixtures.read_seller(seller_id)
        assert seller["approval_status"] == "UNDER_REVIEW"
        assert seller["delivery_standing"] == "NOT_ELIGIBLE"
        assert seller["mandatory_exposure_limit_cents"] == 0
        assert seller["servicing_retained_eligible"] is False

    def test_a_statement_more_than_455_days_old_blocks_the_approval(self):
        """A 2025-01-01 period expired on 2026-04-01, four months before the clock.

        The books governing this applicant close 455 days before 2026-04-01, and
        the clock reads 2026-08-01, so the statement is out of date even though its
        net worth and liquidity are ample and its review passed.

        PRD: "The governing statement must not be stale: its `fiscal_year_end`
        advanced by 455 days must fall on or after the current logical clock date,
        and a statement older than that fails with `ERR_FINANCIAL_STATEMENT_STALE`."

        Design: Corner/state_machines/approval_blocked_by_stale_statement_thin_liquidity_or_failed_qc_outcome
        """
        staged = self._seller_awaiting_a_decision(
            "Stonebridge Home Loans",
            "551204118",
            "NON_BANK_IMB",
            {
                "fiscal_year_end": "2025-01-01",
                "tangible_net_worth_cents": 300000000,
                "liquid_assets_cents": 80000000,
            },
            1,
            0,
        )
        assert staged["qc_review"]["outcome"] == "PASS"

        validate_error(
            api_client.decide_seller_approval(
                staged["seller_id"], {"decision": "APPROVE"}, ANALYST
            ),
            ApiErrorId.ERR_FINANCIAL_STATEMENT_STALE,
            409,
        )

        self._assert_left_under_review(staged["seller_id"])

    def test_liquidity_one_cent_under_the_floor_blocks_the_approval(self):
        """49,999,999 cents of liquid assets misses the floor by a single cent.

        Net worth is triple what is required and the review came back clean, but
        the liquidity line is one cent short of half a million dollars, which is
        the one gate this applicant fails.

        PRD: "Its `liquid_assets_cents` must likewise be at least 50,000,000 cents
        — half a million dollars — with exactly the floor passing and anything below
        failing with `ERR_LIQUIDITY_BELOW_MINIMUM`."

        Design: Corner/state_machines/approval_blocked_by_stale_statement_thin_liquidity_or_failed_qc_outcome
        """
        staged = self._seller_awaiting_a_decision(
            "Willow Creek Mortgage Co",
            "662317249",
            "BANK",
            {
                "tangible_net_worth_cents": 300000000,
                "liquid_assets_cents": 49999999,
            },
            0,
            0,
        )
        assert staged["qc_review"]["outcome"] == "PASS"

        validate_error(
            api_client.decide_seller_approval(
                staged["seller_id"], {"decision": "APPROVE"}, ANALYST
            ),
            ApiErrorId.ERR_LIQUIDITY_BELOW_MINIMUM,
            409,
        )

        self._assert_left_under_review(staged["seller_id"])

    def test_a_single_critical_finding_fails_the_review_and_blocks_approval(self):
        """One critical finding out of three drives the outcome to a failure.

        The financial file is beyond reproach — 400,000,000 of net worth and
        90,000,000 of liquidity on a current period — but the review that governs
        the decision came back failed, and a failed review is fatal on its own.

        PRD: "And the governing review's `outcome` must be either `PASS` or
        `CONDITIONAL_PASS`; a `FAIL` outcome blocks approval outright with
        `ERR_QC_REVIEW_FAILED`."

        Design: Corner/state_machines/approval_blocked_by_stale_statement_thin_liquidity_or_failed_qc_outcome
        """
        staged = self._seller_awaiting_a_decision(
            "Redstone Residential Funding",
            "773428350",
            "CREDIT_UNION",
            {
                "tangible_net_worth_cents": 400000000,
                "liquid_assets_cents": 90000000,
            },
            3,
            1,
        )
        assert_qc_review(staged["qc_review"])
        assert staged["qc_review"]["outcome"] == "FAIL"

        validate_error(
            api_client.decide_seller_approval(
                staged["seller_id"], {"decision": "APPROVE"}, ANALYST
            ),
            ApiErrorId.ERR_QC_REVIEW_FAILED,
            409,
        )

        self._assert_left_under_review(staged["seller_id"])


class TestDeliveredLoanHasOnlyOneExit:
    """A delivered file accepts review and nothing else at all."""

    def test_findings_conditions_and_clearance_all_wait_for_review_to_open(self):
        """Three endpoints and then a fourth all answer on the loan's state.

        Nothing may be recorded against a file that has only been delivered, and it
        cannot jump straight to cleared either. Opening review changes that for the
        review operations, but pricing still waits: an advice may only be issued
        once the file has actually been cleared, so it is refused on the same
        grounds even though the version travelling with it is correct.

        PRD: "Defects may be recorded while the loan is `IN_REVIEW` or `SUSPENDED`
        — a file may carry several at once — and also on a `PURCHASED` loan, where
        the finding is booked as a post-purchase quality-control observation without
        disturbing the completed purchase."

        PRD: "Conditions may be added while the loan is `IN_REVIEW` or `SUSPENDED`
        only; anything else is `ERR_INVALID_LOAN_STATE`."

        PRD: "The state gate admits a loan in `IN_REVIEW` or `SUSPENDED` — anything
        else is `ERR_INVALID_LOAN_STATE` — but a `SUSPENDED` file always then fails
        one of the three open-item gates, so in practice only an `IN_REVIEW` file
        with a clean slate is ever cleared."

        PRD: "Once a loan is `CLEARED_FOR_PURCHASE`, a `PurchaseReviewer` issues a
        **PurchaseAdvice** — the settlement statement that prices the purchase to the
        cent."

        Design: Corner/state_machines/defect_and_clear_before_review_is_opened_are_refused_as_invalid_loan_state
        """
        staged = fixtures.setup_delivered_loan()
        loan_id = staged["loan_id"]

        validate_error(
            api_client.create_defect(
                loan_id,
                factories.defect_payload("DOC-MISSING-1008", "DOCUMENTATION", "LOW"),
                REVIEWER,
            ),
            ApiErrorId.ERR_INVALID_LOAN_STATE,
            409,
        )
        validate_error(
            api_client.create_suspense_condition(
                loan_id,
                factories.suspense_condition_payload(
                    "COND-HOI-01", description="hazard policy missing"
                ),
                REVIEWER,
            ),
            ApiErrorId.ERR_INVALID_LOAN_STATE,
            409,
        )
        validate_error(
            api_client.clear_loan(loan_id, REVIEWER, {"note": "premature clear"}),
            ApiErrorId.ERR_INVALID_LOAN_STATE,
            409,
        )

        in_review = fixtures.open_loan_review(loan_id)
        assert in_review["purchase_status"] == "IN_REVIEW"

        validate_error(
            api_client.create_purchase_advice(
                loan_id, factories.advice_payload(in_review["version"]), REVIEWER
            ),
            ApiErrorId.ERR_INVALID_LOAN_STATE,
            409,
        )

        loan = fixtures.read_loan(loan_id)
        assert loan["open_defect_count"] == 0
        assert loan["open_suspense_count"] == 0
        assert loan["advice_count"] == 0
        assert loan["review_cycle_count"] == 0


class TestCommitmentInitialState:
    """A lock is born with its price frozen and its buckets empty."""

    def test_a_new_lock_holds_the_whole_notional_available_and_nothing_else(self):
        """Every bucket but the residual starts at zero, and the price never moves.

        The line opens with all 100,000,000 available, a tolerance of two percent
        truncated to the cent, no pair-off history at all, and a price of 100.880
        settled once and for all: 25 basis points on for the mandatory obligation,
        12 off for the thirty-day term and 50 off for the matching grid row.

        PRD: "Its conserved amounts are initialised so that `available_amount_cents`
        equals the full `notional_amount_cents` while `allocated_amount_cents`,
        `fulfilled_amount_cents`, `paired_off_amount_cents` and
        `cancelled_amount_cents` are all zero."

        PRD: "Its `tolerance_cents` is fixed at this moment as 2.00 percent of the
        notional with any fraction of a cent truncated away — two cents of tolerance
        per dollar of notional, floored."

        Design: Corner/state_machines/commitment_starts_locked_with_conserved_amounts_zeroed_and_price_frozen
        """
        staged = fixtures.setup_lock_ready_seller()

        commitment = validate_success(
            api_client.create_commitment(
                factories.commitment_payload(staged["seller_id"], staged["product_id"]),
                TRADER,
            ),
            201,
        )

        assert_commitment(commitment)
        assert commitment["status"] == "LOCKED"
        assert commitment["allocated_amount_cents"] == 0
        assert commitment["fulfilled_amount_cents"] == 0
        assert commitment["paired_off_amount_cents"] == 0
        assert commitment["cancelled_amount_cents"] == 0
        assert commitment["available_amount_cents"] == 100000000
        assert commitment["tolerance_cents"] == 2000000
        assert commitment["lock_term_days"] == 30
        assert commitment["llpa_bps_applied"] == -50
        assert commitment["commitment_price_pct"] == 100.880
        assert commitment["pair_off_fee_cents"] == 0
        assert commitment["pair_off_method"] is None
        assert commitment["pair_off_market_price_pct"] is None
        assert commitment["locked_by_user_id"] == "u-ld-1"
        assert commitment["version"] == 1
        assert_commitment_amounts_conserved(commitment)

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["open_mandatory_exposure_cents"] == 100000000


class TestDeclinedSellerLockdown:
    """Declined is terminal, and nothing may be filed against the row again."""

    @staticmethod
    def _declined_seller() -> dict:
        fixtures.setup_clock("2026-08-01T00:00:00Z")
        product = fixtures.setup_product()
        seller = fixtures.setup_seller(
            legal_name="Fallbrook Lending Group",
            tin="914455207",
            seller_type="NON_BANK_IMB",
        )
        fixtures.setup_qc_review(seller["id"], "PRE_APPROVAL")
        declined = fixtures.decide_approval(seller["id"], "DECLINE")
        return {
            "seller": declined,
            "seller_id": seller["id"],
            "product_id": product["id"],
        }

    def test_no_further_statement_review_or_decision_may_be_filed(self):
        """The onboarding endpoints all refuse the row on its own state.

        The decline is terminal and it left the delivery dimension untouched, so a
        fresh set of books, a recertification review and a change of heart on the
        decision are each refused, and the analyst who declined stays on record.

        PRD: "There is **no** cross-dimension effect: `delivery_standing` stays
        exactly where it was at `NOT_ELIGIBLE`."

        PRD: "Statements may only be filed while the seller's `approval_status` is
        `APPLIED` or `UNDER_REVIEW`; filing against an `APPROVED` or `DECLINED`
        seller is refused with `ERR_INVALID_SELLER_STATE`."

        PRD: "As with statements, reviews may only be opened while the seller's
        `approval_status` is `APPLIED` or `UNDER_REVIEW`, else
        `ERR_INVALID_SELLER_STATE`."

        Design: Corner/state_machines/declined_seller_refuses_onboarding_standing_actions_and_locks
        """
        staged = self._declined_seller()
        assert staged["seller"]["approval_status"] == "DECLINED"
        assert staged["seller"]["delivery_standing"] == "NOT_ELIGIBLE"
        assert staged["seller"]["approval_decided_by_user_id"] == "u-ca-1"

        validate_error(
            api_client.create_financial_statement(
                staged["seller_id"],
                factories.financial_statement_payload(
                    tangible_net_worth_cents=900000000,
                    liquid_assets_cents=200000000,
                ),
                ANALYST,
            ),
            ApiErrorId.ERR_INVALID_SELLER_STATE,
            409,
        )
        validate_error(
            api_client.create_qc_review(
                staged["seller_id"], {"review_type": "ANNUAL_RECERT"}, QC
            ),
            ApiErrorId.ERR_INVALID_SELLER_STATE,
            409,
        )
        validate_error(
            api_client.decide_seller_approval(
                staged["seller_id"], {"decision": "APPROVE"}, ANALYST
            ),
            ApiErrorId.ERR_INVALID_SELLER_STATE,
            409,
        )

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["approval_status"] == "DECLINED"
        assert seller["mandatory_exposure_limit_cents"] == 0

    def test_neither_a_standing_action_nor_a_lock_can_resurrect_the_row(self):
        """The two dimensions refuse the row for two different reasons.

        A reinstatement is refused because standing actions are only available to an
        approved counterparty, while the lock desk is refused one gate earlier on
        the approval dimension itself — and no line is created.

        PRD: "Manual standing actions require the seller to be `APPROVED` on the
        approval dimension, else `ERR_INVALID_SELLER_STATE`; an action that is
        unavailable from the seller's current `delivery_standing` — a
        `PLACE_ON_WATCH` on a seller that is not in `GOOD_STANDING`, a `REINSTATE` on
        a seller already in `GOOD_STANDING`, a `SUSPEND` on a seller already
        `SUSPENDED`, or any action at all on a `TERMINATED` seller — is likewise
        refused with `ERR_INVALID_SELLER_STATE`."

        PRD: "The seller's `approval_status` must be `APPROVED`, else
        `ERR_SELLER_NOT_APPROVED`."

        Design: Corner/state_machines/declined_seller_refuses_onboarding_standing_actions_and_locks
        """
        staged = self._declined_seller()

        validate_error(
            api_client.apply_standing_action(
                staged["seller_id"],
                {"action": "REINSTATE", "note": "resurrection attempt"},
                ANALYST,
            ),
            ApiErrorId.ERR_INVALID_SELLER_STATE,
            409,
        )

        validate_error(
            api_client.create_commitment(
                factories.commitment_payload(
                    staged["seller_id"],
                    staged["product_id"],
                    commitment_type="BEST_EFFORTS",
                    notional_amount_cents=50000000,
                ),
                TRADER,
            ),
            ApiErrorId.ERR_SELLER_NOT_APPROVED,
            409,
        )

        _, meta = validate_paginated(
            api_client.list_commitments(TRADER, {"seller_id": staged["seller_id"]})
        )
        assert meta["total_count"] == 0


class TestOneShotOnboardingActs:
    """Neither adjudication nor completion may be replayed."""

    def test_a_second_review_and_a_second_completion_preserve_the_first_result(self):
        """The retries are refused and, more importantly, change nothing.

        A different analyst tries to reverse the acceptance and the original
        reviewer tries to restate the finding counts as catastrophic; both are
        refused, and the statement keeps its first decider while the review keeps
        its passing outcome and its original counts.

        PRD: "Only a statement still in `SUBMITTED` may be adjudicated; a second
        attempt on an already-decided statement is refused with
        `ERR_STATEMENT_NOT_REVIEWABLE`."

        PRD: "Only an `OPEN` review may be completed, else `ERR_QC_REVIEW_NOT_OPEN`."

        Design: Corner/state_machines/statement_review_and_qc_completion_are_not_repeatable
        """
        fixtures.setup_clock("2026-08-01T00:00:00Z")
        staged = fixtures.setup_seller_under_review()
        completed = fixtures.complete_qc_review(staged["qc_review"]["id"], 2, 0)

        validate_error(
            api_client.review_financial_statement(
                staged["statement"]["id"],
                {"decision": "REJECT", "review_note": "second thoughts"},
                ANALYST_ALT,
            ),
            ApiErrorId.ERR_STATEMENT_NOT_REVIEWABLE,
            409,
        )
        validate_error(
            api_client.complete_qc_review(
                completed["id"],
                {"findings_count": 9, "critical_findings_count": 4},
                QC,
            ),
            ApiErrorId.ERR_QC_REVIEW_NOT_OPEN,
            409,
        )

        statements = validate_paginated(
            api_client.list_financial_statements(staged["seller_id"], ANALYST)
        )[0]
        assert len(statements) == 1
        assert statements[0]["status"] == "ACCEPTED"
        assert statements[0]["reviewed_by_user_id"] == "u-ca-1"
        assert statements[0]["version"] == 2

        reviews = validate_paginated(
            api_client.list_qc_reviews(staged["seller_id"], QC)
        )[0]
        assert len(reviews) == 1
        assert reviews[0]["status"] == "COMPLETED"
        assert reviews[0]["outcome"] == "PASS"
        assert reviews[0]["findings_count"] == 2
        assert reviews[0]["critical_findings_count"] == 0
        assert reviews[0]["completed_at"] == "2026-08-01T00:00:00.000Z"
        assert reviews[0]["version"] == 2


class TestOneShotItemResolutions:
    """A resolved open item cannot be resolved a second time.

    A replay must not be allowed to decrement the loan's roll-ups twice, so the
    counters are read again after the refusals.
    """

    @staticmethod
    def _loan_with_both_items_resolved() -> dict:
        staged = fixtures.setup_loan_in_review()
        defect = fixtures.record_defect(
            staged["loan_id"], "DOC-MISSING-1008", "DOCUMENTATION", "LOW"
        )
        condition = fixtures.add_suspense_condition(
            staged["loan_id"], "COND-HOI-01", description="hazard policy missing"
        )
        fixtures.cure_defect(defect["id"], staged["seller_id"], "DOC-1008-A")
        fixtures.clear_suspense_condition(condition["id"], "HOI-2026-0001")
        staged["defect_id"] = defect["id"]
        staged["condition_id"] = condition["id"]
        return staged

    def test_a_cured_defect_refuses_both_a_second_cure_and_a_waiver(self):
        """The openness gate answers before the curability gate is even reached.

        The defect was curable and was cured, so a replayed cure and an attempted
        waiver both fail on openness rather than on curability, and the loan's
        counters do not move a second time.

        PRD: "The defect must be `OPEN` and `CURABLE`, on pain of
        `ERR_DEFECT_NOT_OPEN` and `ERR_DEFECT_NOT_CURABLE` respectively."

        Design: Corner/state_machines/defect_cure_and_suspense_clearance_are_each_single_shot
        """
        staged = self._loan_with_both_items_resolved()

        second_cure = validate_error(
            api_client.cure_defect(
                staged["defect_id"],
                {"cure_document_reference": "DOC-1008-B"},
                staged["seller_headers"],
            ),
            ApiErrorId.ERR_DEFECT_NOT_OPEN,
            409,
        )
        assert second_cure["error_id"] != ApiErrorId.ERR_DEFECT_NOT_CURABLE.value

        waive_attempt = validate_error(
            api_client.waive_defect(
                staged["defect_id"], {"price_adjustment_bps": -25}, REVIEWER
            ),
            ApiErrorId.ERR_DEFECT_NOT_OPEN,
            409,
        )
        assert waive_attempt["error_id"] != ApiErrorId.ERR_DEFECT_NOT_CURABLE.value

        defect = fixtures.read_loan_defects(staged["loan_id"])[0]
        assert defect["status"] == "CURED"
        assert defect["cured_at"] == "2026-08-01T00:00:00.000Z"
        assert defect["cure_document_reference"] == "DOC-1008-A"
        assert defect["price_adjustment_bps"] == 0

        loan = fixtures.read_loan(staged["loan_id"])
        assert loan["open_defect_count"] == 0
        assert loan["purchase_status"] == "IN_REVIEW"
        assert loan["review_cycle_count"] == 1

    def test_a_cleared_condition_refuses_a_second_clearance(self):
        """A second document against the same condition changes nothing.

        The condition is already cleared with its first document reference, so the
        replay is refused and the reference is not overwritten, leaving the
        paperwork count at zero rather than driving it negative.

        PRD: "The condition must be `OPEN`, else `ERR_CONDITION_NOT_OPEN`, and the
        logical clock must be at or before its `due_at`, with a clearance strictly
        after that instant refused with `ERR_SUSPENSE_WINDOW_EXPIRED`."

        Design: Corner/state_machines/defect_cure_and_suspense_clearance_are_each_single_shot
        """
        staged = self._loan_with_both_items_resolved()

        validate_error(
            api_client.clear_suspense_condition(
                staged["condition_id"], {"document_reference": "HOI-2026-0002"}, REVIEWER
            ),
            ApiErrorId.ERR_CONDITION_NOT_OPEN,
            409,
        )

        condition = fixtures.read_loan_conditions(staged["loan_id"])[0]
        assert condition["status"] == "CLEARED"
        assert condition["document_reference"] == "HOI-2026-0001"

        loan = fixtures.read_loan(staged["loan_id"])
        assert loan["open_suspense_count"] == 0
        assert loan["purchase_status"] == "IN_REVIEW"
        assert loan["review_cycle_count"] == 1


class TestStandingActionSideEffects:
    """Suspension leaves the book alone; termination prunes only idle lines."""

    @staticmethod
    def _seller_with_one_used_and_one_idle_line() -> dict:
        staged = fixtures.setup_lock_ready_seller()
        used = fixtures.setup_commitment(staged["seller_id"], staged["product_id"])
        idle = fixtures.setup_commitment(
            staged["seller_id"],
            staged["product_id"],
            delivery_window_start="2026-08-31",
            delivery_expiry_date="2026-09-30",
        )
        loan = fixtures.deliver_loan(used["id"], staged["seller_id"])
        staged["used_id"] = used["id"]
        staged["idle_id"] = idle["id"]
        staged["loan_id"] = loan["id"]
        return staged

    def test_a_manual_suspension_cancels_nothing_and_charges_nothing(self):
        """Both lines survive the suspension untouched, fees and exposure included.

        The seller is put on the naughty step by hand, which records the manual
        reason and stops new business, but the two live lines keep their status and
        the whole 200,000,000 of mandatory exposure stays booked with no fee raised.

        PRD: "`SUSPEND` moves either `GOOD_STANDING → SUSPENDED` or `WATCH →
        SUSPENDED` and sets `suspension_reason` to `MANUAL_COUNTERPARTY_ACTION`;
        crucially, a manual suspension **cancels nothing** — existing locks survive
        it untouched."

        Design: Corner/state_machines/manual_suspension_preserves_locks_while_termination_cancels_only_unallocated_lines
        """
        staged = self._seller_with_one_used_and_one_idle_line()

        suspended = fixtures.apply_standing_action(staged["seller_id"], "SUSPEND")
        assert suspended["delivery_standing"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "MANUAL_COUNTERPARTY_ACTION"
        assert suspended["fee_receivable_cents"] == 0
        assert suspended["open_mandatory_exposure_cents"] == 200000000

        assert fixtures.read_commitment(staged["used_id"])["status"] == "LOCKED"
        assert fixtures.read_commitment(staged["idle_id"])["status"] == "LOCKED"

        reinstated = fixtures.apply_standing_action(staged["seller_id"], "REINSTATE")
        assert reinstated["delivery_standing"] == "GOOD_STANDING"
        assert reinstated["suspension_reason"] is None
        assert fixtures.read_loan(staged["loan_id"])["purchase_status"] == "DELIVERED"

    def test_termination_cancels_only_the_line_with_no_allocation_outstanding(self):
        """The idle line is pruned at the flat fee; the working line is skipped.

        Termination sweeps the seller's book but takes only the line nothing has
        been delivered against: it is cancelled for its full notional at the flat
        administrative charge, which lands on the seller's receivable, while the
        line carrying the delivered file keeps its allocation and its locked status.

        PRD: "`TERMINATE` moves `GOOD_STANDING → TERMINATED`, `WATCH → TERMINATED`
        or `SUSPENDED → TERMINATED`, and does cancel: every commitment of that seller
        whose `status` is `LOCKED` or `PARTIALLY_FULFILLED` **and** whose
        `allocated_amount_cents` is zero is cancelled, each one picking up the
        administrative flat pair-off fee described in §3.5, with each fee accruing to
        the seller's `fee_receivable_cents`."

        PRD: "Commitments that still carry an outstanding allocation are left alone."

        Design: Corner/state_machines/manual_suspension_preserves_locks_while_termination_cancels_only_unallocated_lines
        """
        staged = self._seller_with_one_used_and_one_idle_line()

        terminated = fixtures.apply_standing_action(
            staged["seller_id"], "TERMINATE", actor=ADMIN
        )
        assert terminated["delivery_standing"] == "TERMINATED"
        assert terminated["fee_receivable_cents"] == 25000
        assert terminated["open_mandatory_exposure_cents"] == 100000000

        cancelled = fixtures.read_commitment(staged["idle_id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancelled_amount_cents"] == 100000000
        assert cancelled["available_amount_cents"] == 0
        assert cancelled["pair_off_method"] == "ADMINISTRATIVE_FLAT"
        assert cancelled["pair_off_fee_cents"] == 25000
        assert_commitment_amounts_conserved(cancelled)

        survivor = fixtures.read_commitment(staged["used_id"])
        assert survivor["status"] == "LOCKED"
        assert survivor["allocated_amount_cents"] == 40000000
        assert survivor["cancelled_amount_cents"] == 0
        assert fixtures.read_loan(staged["loan_id"])["purchase_status"] == "DELIVERED"
