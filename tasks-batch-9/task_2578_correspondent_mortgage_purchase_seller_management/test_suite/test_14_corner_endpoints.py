"""Operational endpoints: sweeps, pair-offs, closes, settlements and transfers."""

from test_helpers import (
    ADMIN,
    ANALYST,
    REVIEWER,
    TRADER,
    ApiErrorId,
    api_client,
    assert_commitment,
    assert_commitment_amounts_conserved,
    assert_defect,
    assert_escrow_transfer,
    assert_loan,
    assert_purchase_advice,
    assert_seller_scorecard,
    assert_suspense_condition,
    factories,
    fixtures,
    make_seller_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDeadlineBoundariesAndTheLoanSweep:
    """The actor's deadline is inclusive; the sweep's is strict."""

    @staticmethod
    def _file_with_two_deadlines_in_each_family() -> dict:
        staged = fixtures.setup_loan_in_review(with_adjustment=False)
        staged["defect_ontime"] = fixtures.record_defect(
            staged["loan_id"], "CRED-DTI-2305", "CREDIT", "MEDIUM"
        )
        staged["defect_late"] = fixtures.record_defect(
            staged["loan_id"], "CRED-RESERVES-2311", "CREDIT", "MEDIUM"
        )
        staged["condition_ontime"] = fixtures.add_suspense_condition(
            staged["loan_id"], "COND-HOI-01", description="hazard policy missing"
        )
        staged["condition_late"] = fixtures.add_suspense_condition(
            staged["loan_id"], "COND-FLOOD-02"
        )
        return staged

    def test_resolutions_landing_exactly_on_the_deadline_are_on_time(self):
        """A cure on the tenth day and a clearance on the seventh both stand.

        A medium finding gets ten days and a condition gets seven, counted from
        the instant each was raised. Acting precisely at the deadline instant is
        still acting inside the window, so both resolutions are accepted, while
        the same two operations one day later are refused and leave their items
        open for the sweep to find.

        PRD: "the logical clock must be at or before the defect's
        `cure_deadline_at`, with a cure landing exactly **on** the deadline
        instant counting as on time and anything strictly later refused with
        `ERR_CURE_WINDOW_EXPIRED`"

        PRD: "The condition must be `OPEN`, else `ERR_CONDITION_NOT_OPEN`, and
        the logical clock must be at or before its `due_at`, with a clearance
        strictly after that instant refused with `ERR_SUSPENSE_WINDOW_EXPIRED`."

        Design: Corner/endpoints/late_cure_and_late_clearance_are_refused_then_the_loan_sweep_expires_both_items
        """
        staged = self._file_with_two_deadlines_in_each_family()

        assert_defect(staged["defect_ontime"])
        assert staged["defect_ontime"]["cure_deadline_at"] == "2026-08-11T00:00:00.000Z"
        assert_suspense_condition(staged["condition_ontime"])
        assert staged["condition_ontime"]["due_at"] == "2026-08-08T00:00:00.000Z"

        fixtures.setup_clock("2026-08-08T00:00:00Z")
        cleared = fixtures.clear_suspense_condition(
            staged["condition_ontime"]["id"], "HOI-2026-0001"
        )
        assert cleared["status"] == "CLEARED"
        assert cleared["cleared_at"] == "2026-08-08T00:00:00.000Z"

        fixtures.setup_clock("2026-08-11T00:00:00Z")
        cured = fixtures.cure_defect(
            staged["defect_ontime"]["id"], staged["seller_id"], "CURE-DTI-0001"
        )
        assert cured["status"] == "CURED"
        assert cured["cured_at"] == "2026-08-11T00:00:00.000Z"

        fixtures.setup_clock("2026-08-12T00:00:00Z")
        late_cure = validate_error(
            api_client.cure_defect(
                staged["defect_late"]["id"],
                factories.cure_payload("CURE-RES-0002"),
                make_seller_user_headers(staged["seller_id"]),
            ),
            ApiErrorId.ERR_CURE_WINDOW_EXPIRED,
            409,
        )
        assert late_cure["error_id"] != ApiErrorId.ERR_DEFECT_NOT_CURABLE

        validate_error(
            api_client.clear_suspense_condition(
                staged["condition_late"]["id"],
                factories.condition_clear_payload("FLOOD-2026-0002"),
                REVIEWER,
            ),
            ApiErrorId.ERR_SUSPENSE_WINDOW_EXPIRED,
            409,
        )

        defects = {d["defect_code"]: d for d in fixtures.read_loan_defects(staged["loan_id"])}
        assert defects["CRED-RESERVES-2311"]["status"] == "OPEN"
        conditions = {
            c["condition_code"]: c
            for c in fixtures.read_loan_conditions(staged["loan_id"])
        }
        assert conditions["COND-FLOOD-02"]["status"] == "OPEN"

    def test_the_sweep_expires_only_the_strictly_overdue_items_and_then_idles(self):
        """One defect and one condition expire; a second sweep changes nothing.

        The sweep is the mirror image of the actor's window: it takes exactly the
        items whose deadline the clock has passed strictly, reports a count per
        family and where the file stands, and because that leaves no open items
        at all the file climbs back out of suspense and books one review cycle.
        Run again it finds nothing and touches nothing.

        PRD: "The sweep answers with `expired_defect_count`,
        `expired_condition_count`, and `loan_purchase_status` reporting where the
        file stands once the sweep is done."

        PRD: "When the resolving mutation leaves the loan with `open_defect_count`
        at zero **and** `open_suspense_count` at zero, and the loan was in
        `SUSPENDED`, the loan moves `SUSPENDED → IN_REVIEW` and its
        `review_cycle_count` rises by one."

        Design: Corner/endpoints/late_cure_and_late_clearance_are_refused_then_the_loan_sweep_expires_both_items
        """
        staged = self._file_with_two_deadlines_in_each_family()

        fixtures.setup_clock("2026-08-08T00:00:00Z")
        fixtures.clear_suspense_condition(
            staged["condition_ontime"]["id"], "HOI-2026-0001"
        )
        fixtures.setup_clock("2026-08-11T00:00:00Z")
        fixtures.cure_defect(
            staged["defect_ontime"]["id"], staged["seller_id"], "CURE-DTI-0001"
        )
        fixtures.setup_clock("2026-08-12T00:00:00Z")

        first = fixtures.sweep_loan_conditions(staged["loan_id"])
        assert first["expired_defect_count"] == 1
        assert first["expired_condition_count"] == 1
        assert first["loan_purchase_status"] == "IN_REVIEW"

        loan = fixtures.read_loan(staged["loan_id"])
        assert_loan(loan)
        assert loan["purchase_status"] == "IN_REVIEW"
        assert loan["open_defect_count"] == 0
        assert loan["open_suspense_count"] == 0
        assert loan["review_cycle_count"] == 1

        defects = {d["defect_code"]: d for d in fixtures.read_loan_defects(staged["loan_id"])}
        assert defects["CRED-RESERVES-2311"]["status"] == "EXPIRED"
        assert defects["CRED-DTI-2305"]["status"] == "CURED"
        conditions = {
            c["condition_code"]: c
            for c in fixtures.read_loan_conditions(staged["loan_id"])
        }
        assert conditions["COND-FLOOD-02"]["status"] == "EXPIRED"
        assert conditions["COND-HOI-01"]["status"] == "CLEARED"

        second = fixtures.sweep_loan_conditions(staged["loan_id"])
        assert second["expired_defect_count"] == 0
        assert second["expired_condition_count"] == 0

        unchanged = fixtures.read_loan(staged["loan_id"])
        assert unchanged["purchase_status"] == "IN_REVIEW"
        assert unchanged["review_cycle_count"] == 1


class TestPairOffNeedsAnEmptyPipeline:
    """A line with a delivery in flight cannot be closed out."""

    @staticmethod
    def _line_with_one_file_in_the_pipeline() -> dict:
        return fixtures.setup_loan_in_review()

    def test_an_outstanding_allocation_blocks_the_pair_off_and_rejection_needs_grounds(
        self,
    ):
        """Neither the desk nor the reviewer can act while the file is merely open.

        The pair-off gate looks at the allocation rather than the residual, so a
        line with 60,000,000 still available is refused outright while its one
        delivered loan is in review; and the reviewer cannot dispose of that loan
        either, because rejection is reserved for files carrying an open
        non-curable finding and this one carries no finding at all.

        PRD: "The commitment must be `LOCKED` or `PARTIALLY_FULFILLED`, else
        `ERR_COMMITMENT_NOT_OPEN`, and its `allocated_amount_cents` must be
        exactly zero, else `ERR_ALLOCATION_OUTSTANDING` — loans already delivered
        and still moving through the purchase pipeline must be purchased or
        rejected before the line can be closed out."

        PRD: "**Rejection** is the other door, and it is only available when the
        file is genuinely unbuyable: a `PurchaseReviewer` rejects a loan in
        `IN_REVIEW` or `SUSPENDED` with an optional `note`, and the loan must
        carry at least one open non-curable defect, else
        `ERR_NO_NON_CURABLE_DEFECT`."

        Design: Corner/endpoints/pair_off_refuses_a_line_with_an_outstanding_allocation_and_rejection_frees_it
        """
        staged = self._line_with_one_file_in_the_pipeline()
        assert staged["commitment"]["commitment_price_pct"] == 100.880
        assert staged["commitment"]["tolerance_cents"] == 2000000

        validate_error(
            api_client.pair_off_commitment(
                staged["commitment_id"], factories.pair_off_payload(100.500), TRADER
            ),
            ApiErrorId.ERR_ALLOCATION_OUTSTANDING,
            409,
        )

        held = fixtures.read_commitment(staged["commitment_id"])
        assert held["status"] == "LOCKED"
        assert held["allocated_amount_cents"] == 40000000
        assert held["available_amount_cents"] == 60000000

        validate_error(
            api_client.reject_loan(
                staged["loan_id"], REVIEWER, {"note": "no justification on file yet"}
            ),
            ApiErrorId.ERR_NO_NON_CURABLE_DEFECT,
            409,
        )
        assert fixtures.read_loan(staged["loan_id"])["purchase_status"] == "IN_REVIEW"

    def test_rejection_frees_the_line_and_the_pair_off_then_prices_the_market_loss(self):
        """A compliance finding empties the pipeline and the desk pays 397,400.

        Once the non-curable finding justifies a rejection the allocation goes
        back to the line, which the identical pair-off call now accepts: the full
        100,000,000 residual is paired off, the shortfall is netted against the
        2,000,000 tolerance and marked from 100.880 down to 100.500, and the
        372,400 market loss plus the 25,000 administrative component lands on the
        seller's fee receivable with its mandatory exposure released.

        PRD: "The market loss is the billable amount multiplied by the excess of
        the locked `commitment_price_pct` over the observed
        `pair_off_market_price_pct`, that excess floored at zero, the product
        divided by 100, and the result rounded half up to whole cents."

        PRD: "the parent commitment's `allocated_amount_cents` falls by the loan's
        `note_amount_cents` and its `available_amount_cents` rises by the same
        amount, restoring the conserved notional identity of §2.7 exactly as it
        stood before delivery."

        Design: Corner/endpoints/pair_off_refuses_a_line_with_an_outstanding_allocation_and_rejection_frees_it
        """
        staged = self._line_with_one_file_in_the_pipeline()

        defect = fixtures.record_defect(
            staged["loan_id"], "COMP-TRID-4001", "COMPLIANCE", "HIGH"
        )
        assert defect["classification"] == "NON_CURABLE"
        assert defect["cure_deadline_at"] is None

        rejected = validate_success(
            api_client.reject_loan(
                staged["loan_id"], REVIEWER, {"note": "non-curable TRID violation"}
            ),
            200,
        )
        assert rejected["purchase_status"] == "REJECTED"

        freed = fixtures.read_commitment(staged["commitment_id"])
        assert freed["allocated_amount_cents"] == 0
        assert freed["available_amount_cents"] == 100000000
        assert freed["status"] == "LOCKED"

        paired = fixtures.pair_off_commitment(staged["commitment_id"], 100.500)
        assert_commitment(paired)
        assert paired["status"] == "PAIRED_OFF"
        assert paired["pair_off_method"] == "MANDATORY_MARK_TO_MARKET"
        assert paired["paired_off_amount_cents"] == 100000000
        assert paired["pair_off_fee_cents"] == 397400
        assert paired["available_amount_cents"] == 0
        assert paired["pair_off_market_price_pct"] == 100.500
        assert_commitment_amounts_conserved(paired)

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["fee_receivable_cents"] == 397400
        assert seller["open_mandatory_exposure_cents"] == 0


class TestScorecardCloseTiming:
    """A period cannot be graded while it is still running, or graded twice."""

    @staticmethod
    def _two_clean_purchases_and_an_open_period() -> dict:
        staged = fixtures.setup_purchased_loan(funding_reference="WIRE-A-0001")
        staged["twin"] = fixtures.purchase_additional_loan(
            staged["commitment_id"],
            staged["seller_id"],
            "HP-0002",
            funding_reference="WIRE-B-0001",
        )
        staged["scorecard"] = fixtures.open_scorecard(
            staged["seller_id"], "2026-08-01", "2026-08-31"
        )
        staged["scorecard_id"] = staged["scorecard"]["id"]
        return staged

    def test_a_close_one_second_before_midnight_is_still_inside_the_period(self):
        """2026-08-31T23:59:59Z has not passed the period's final millisecond.

        The period is a closed interval whose last instant is the end date at
        23:59:59.999Z, so a close attempted a second earlier is refused and the
        scorecard keeps the zeroed, ungraded shape it was opened with, even though
        two loans have already been funded inside the window.

        PRD: "the logical clock must be strictly past the **end** of the period —
        that is, past `period_end` at 23:59:59.999Z — else
        `ERR_SCORECARD_PERIOD_NOT_ENDED`."

        PRD: "The new scorecard is created in `OPEN` status with every metric
        zeroed — `purchased_loan_count`, `purchased_upb_cents`,
        `defective_loan_count`, `defective_upb_cents`, `defect_rate_bps` and
        `upb_weighted_defect_rate_bps` — its `grade` at `UNRATED`, its `breach`
        flag false, its `standing_action_applied` at `NONE`, and `closed_at` null."

        Design: Corner/endpoints/scorecard_close_needs_the_period_ended_and_cannot_be_repeated
        """
        staged = self._two_clean_purchases_and_an_open_period()

        opened = staged["scorecard"]
        assert_seller_scorecard(opened)
        assert opened["status"] == "OPEN"
        assert opened["grade"] == "UNRATED"
        assert opened["purchased_loan_count"] == 0
        assert opened["purchased_upb_cents"] == 0
        assert opened["defective_loan_count"] == 0
        assert opened["defective_upb_cents"] == 0
        assert opened["defect_rate_bps"] == 0
        assert opened["upb_weighted_defect_rate_bps"] == 0
        assert opened["breach"] is False
        assert opened["standing_action_applied"] == "NONE"
        assert opened["closed_at"] is None

        assert fixtures.read_seller(staged["seller_id"])["net_funded_cents"] == 80754778

        fixtures.setup_clock("2026-08-31T23:59:59Z")
        validate_error(
            api_client.close_scorecard(staged["scorecard_id"], ANALYST),
            ApiErrorId.ERR_SCORECARD_PERIOD_NOT_ENDED,
            409,
        )

        still_open, _ = validate_paginated(
            api_client.list_scorecards(staged["seller_id"], ADMIN)
        )
        assert still_open[0]["status"] == "OPEN"
        assert still_open[0]["grade"] == "UNRATED"

    def test_the_close_grades_the_period_and_cannot_be_repeated(self):
        """Two clean loans grade A, take no action, and close the door behind them.

        The day after the period ends the close scores both purchases, finds no
        defective loan in a population large enough to grade, records both rates
        at zero and a grade of A with no breach, selects no standing action
        against a seller already in good standing, and publishes the figures onto
        the seller row. A second close finds the scorecard no longer open.

        PRD: "Otherwise the grade is `A` at 1000 basis points or less, `B` at 2500
        or less, `C` at 5000 or less, and `D` above 5000."

        PRD: "Finally, the scorecard moves `OPEN → CLOSED` with `closed_at`
        stamped from the logical clock, and the seller adopts the closed figures:
        `current_defect_rate_bps` takes the governing `defect_rate_bps` and
        `current_scorecard_grade` takes the `grade`, so the seller record always
        reflects its most recently closed period."

        Design: Corner/endpoints/scorecard_close_needs_the_period_ended_and_cannot_be_repeated
        """
        staged = self._two_clean_purchases_and_an_open_period()

        fixtures.setup_clock("2026-09-01T00:00:00Z")
        closed = fixtures.close_scorecard(staged["scorecard_id"])
        assert_seller_scorecard(closed)
        assert closed["status"] == "CLOSED"
        assert closed["purchased_loan_count"] == 2
        assert closed["purchased_upb_cents"] == 80000000
        assert closed["defective_loan_count"] == 0
        assert closed["defective_upb_cents"] == 0
        assert closed["defect_rate_bps"] == 0
        assert closed["upb_weighted_defect_rate_bps"] == 0
        assert closed["grade"] == "A"
        assert closed["breach"] is False
        assert closed["standing_action_applied"] == "NONE"
        assert closed["closed_at"] == "2026-09-01T00:00:00.000Z"

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["current_defect_rate_bps"] == 0
        assert seller["current_scorecard_grade"] == "A"
        assert seller["delivery_standing"] == "GOOD_STANDING"

        validate_error(
            api_client.close_scorecard(staged["scorecard_id"], ANALYST),
            ApiErrorId.ERR_SCORECARD_NOT_OPEN,
            409,
        )


class TestLockTimeProductScreening:
    """At lock time only the product's own availability and type list are read."""

    @staticmethod
    def _a_retired_product_an_active_one_and_an_approved_seller() -> dict:
        fixtures.setup_clock()
        retired = fixtures.setup_product(
            product_code="CONFLEGACY",
            base_price_pct=100.750,
            min_fico=660,
            max_ltv_pct=97.0,
            max_loan_amount_cents=76650000,
            allowed_commitment_types=["MANDATORY"],
            allowed_occupancies=["PRIMARY"],
            srp_pct=1.000,
            status="RETIRED",
            description="withdrawn legacy conforming product",
        )
        jumbo = fixtures.setup_product(
            product_code="JUMBO30F",
            base_price_pct=100.500,
            min_fico=700,
            max_ltv_pct=80.0,
            max_loan_amount_cents=200000000,
            allowed_commitment_types=["MANDATORY"],
            allowed_occupancies=["PRIMARY"],
            srp_pct=0.750,
        )
        staged = fixtures.setup_approved_seller()
        staged["retired"] = retired
        staged["jumbo"] = jumbo
        return staged

    def test_a_retired_product_answers_before_the_commitment_type_is_examined(self):
        """The withdrawn product refuses both a permitted and a forbidden type.

        A product created directly in the withdrawn state is unavailable for new
        business, and that answer comes first: asking for the mandatory type the
        product does list and the best-efforts type it does not both return the
        same product refusal, because the availability gate outranks the type
        gate.

        PRD: "The named product must be `ACTIVE`, and a lock against a `RETIRED`
        product is refused with `ERR_PRODUCT_NOT_ELIGIBLE` — note that at lock
        time only the product's availability is examined, because no borrower
        characteristics exist yet to test against the credit box; the full matrix
        is applied later, at delivery."

        PRD: "**Product-matrix referential gates**, in this relative order:
        `ERR_PRODUCT_NOT_ELIGIBLE`, `ERR_COMMITMENT_TYPE_NOT_ALLOWED`,
        `ERR_SERVICING_RETAINED_NOT_ELIGIBLE`. All three are HTTP 422."

        Design: Corner/endpoints/commitment_creation_screens_the_product_status_before_the_allowed_type_list
        """
        staged = self._a_retired_product_an_active_one_and_an_approved_seller()
        assert staged["retired"]["status"] == "RETIRED"

        for commitment_type in ("MANDATORY", "BEST_EFFORTS"):
            validate_error(
                api_client.create_commitment(
                    factories.commitment_payload(
                        staged["seller_id"],
                        staged["retired"]["id"],
                        commitment_type=commitment_type,
                        reference_fico=740,
                        reference_ltv_pct=70.0,
                    ),
                    TRADER,
                ),
                ApiErrorId.ERR_PRODUCT_NOT_ELIGIBLE,
                422,
            )

        listed, meta = validate_paginated(api_client.list_commitments(TRADER))
        assert listed == []
        assert meta["total_count"] == 0

    def test_an_active_product_refuses_the_unlisted_type_and_prices_the_listed_one(self):
        """Best efforts is outside the jumbo list; the mandatory lock prices 100.630.

        The available product carries only one commitment type, so the
        best-efforts request is refused on the type list itself, while the
        mandatory request goes through and prices from the product's own base with
        the mandatory spread and the thirty-day term adjustment and no grid rows to
        match. Only the accepted lock moves the seller's mandatory exposure.

        PRD: "The requested `commitment_type` must appear in the product's
        `allowed_commitment_types`, else `ERR_COMMITMENT_TYPE_NOT_ALLOWED`."

        Design: Corner/endpoints/commitment_creation_screens_the_product_status_before_the_allowed_type_list
        """
        staged = self._a_retired_product_an_active_one_and_an_approved_seller()

        validate_error(
            api_client.create_commitment(
                factories.commitment_payload(
                    staged["seller_id"],
                    staged["jumbo"]["id"],
                    commitment_type="BEST_EFFORTS",
                    reference_fico=740,
                    reference_ltv_pct=70.0,
                ),
                TRADER,
            ),
            ApiErrorId.ERR_COMMITMENT_TYPE_NOT_ALLOWED,
            422,
        )

        accepted = fixtures.setup_commitment(
            staged["seller_id"],
            staged["jumbo"]["id"],
            commitment_type="MANDATORY",
            reference_fico=740,
            reference_ltv_pct=70.0,
        )
        assert_commitment(accepted)
        assert accepted["commitment_price_pct"] == 100.630
        assert accepted["llpa_bps_applied"] == 0
        assert accepted["lock_term_days"] == 30

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["open_mandatory_exposure_cents"] == 100000000


class TestSettlementIsSingleShot:
    """The wire fires once per advice, and a voided advice never fires at all."""

    @staticmethod
    def _one_settled_and_one_outstanding_advice() -> dict:
        staged = fixtures.setup_purchased_loan(
            settle_actor=ADMIN, funding_reference="WIRE-A-0001"
        )
        twin = fixtures.deliver_loan(
            staged["commitment_id"], staged["seller_id"], seller_loan_number="HP-0002"
        )
        fixtures.open_loan_review(twin["id"])
        fixtures.clear_loan_for_purchase(twin["id"])
        twin_advice = fixtures.issue_purchase_advice(twin["id"])
        staged["twin_loan_id"] = twin["id"]
        staged["twin_advice"] = twin_advice
        staged["twin_advice_id"] = twin_advice["id"]
        return staged

    def test_an_already_settled_advice_refuses_a_second_wire(self):
        """The second funding reference is rejected and the money is not doubled.

        Settlement is the only place the funded total moves, and the status gate
        stands guard over it: once the advice has reached its terminal settled
        state the same call with a fresh reference is refused, and the seller's
        funded total still shows exactly one wire.

        PRD: "The advice must be in `ISSUED` status, else
        `ERR_ADVICE_NOT_SETTLEABLE` — a superseded, voided, already-settled or
        reversed advice cannot be wired."

        Design: Corner/endpoints/advice_settlement_is_single_shot_and_a_voided_advice_can_never_settle
        """
        staged = self._one_settled_and_one_outstanding_advice()

        settled = staged["advice"]
        assert_purchase_advice(settled)
        assert settled["status"] == "SETTLED"
        assert settled["settled_at"] == "2026-08-01T00:00:00.000Z"
        assert settled["funding_reference"] == "WIRE-A-0001"
        assert staged["twin_advice"]["status"] == "ISSUED"

        validate_error(
            api_client.settle_purchase_advice(
                staged["advice_id"],
                factories.settlement_payload("WIRE-A-0002"),
                ADMIN,
            ),
            ApiErrorId.ERR_ADVICE_NOT_SETTLEABLE,
            409,
        )

        assert fixtures.read_seller(staged["seller_id"])["net_funded_cents"] == 40377389

    def test_a_post_clear_defect_voids_the_outstanding_advice_for_good(self):
        """The late documentation finding kills the wire on the twin file.

        A finding recorded after the file was cleared drags the loan back into
        suspense and voids its outstanding advice on the way, so the settlement
        that was ready to run is refused for the same status reason as a replay,
        and the line keeps the twin's allocation because that file is still in the
        pipeline.

        PRD: "A loan in `CLEARED_FOR_PURCHASE` moves `CLEARED_FOR_PURCHASE →
        SUSPENDED`, and that transition additionally moves **every** purchase
        advice of that loan still in `ISSUED` status `ISSUED → VOIDED` — a late
        finding cannot leave a priced advice standing."

        Design: Corner/endpoints/advice_settlement_is_single_shot_and_a_voided_advice_can_never_settle
        """
        staged = self._one_settled_and_one_outstanding_advice()

        fixtures.record_defect(
            staged["twin_loan_id"], "DOC-MISSING-1008", "DOCUMENTATION", "LOW"
        )

        advices = fixtures.read_loan_advices(staged["twin_loan_id"])
        assert [advice["status"] for advice in advices] == ["VOIDED"]
        twin_loan = fixtures.read_loan(staged["twin_loan_id"])
        assert twin_loan["purchase_status"] == "SUSPENDED"

        validate_error(
            api_client.settle_purchase_advice(
                staged["twin_advice_id"],
                factories.settlement_payload("WIRE-B-0001"),
                ADMIN,
            ),
            ApiErrorId.ERR_ADVICE_NOT_SETTLEABLE,
            409,
        )

        commitment = fixtures.read_commitment(staged["commitment_id"])
        assert commitment["status"] == "PARTIALLY_FULFILLED"
        assert commitment["fulfilled_amount_cents"] == 40000000
        assert commitment["allocated_amount_cents"] == 40000000
        assert_commitment_amounts_conserved(commitment)
        assert fixtures.read_seller(staged["seller_id"])["net_funded_cents"] == 40377389


class TestEscrowTransferCompletionWindow:
    """Fifteen days to hand over the escrow, and one attempt to do it."""

    @staticmethod
    def _twin_released_purchases_with_their_transfers() -> dict:
        staged = fixtures.setup_purchased_loan(
            settle_actor=ADMIN,
            funding_reference="WIRE-A-0001",
            loan_overrides={
                "servicing_election": "RELEASED",
                "escrow_balance_cents": 250000,
            },
        )
        staged["twin"] = fixtures.purchase_additional_loan(
            staged["commitment_id"],
            staged["seller_id"],
            "HP-0002",
            funding_reference="WIRE-B-0001",
            settle_actor=ADMIN,
            servicing_election="RELEASED",
            escrow_balance_cents=180000,
        )
        staged["transfer"] = fixtures.read_pending_escrow_transfer(staged["loan_id"])
        staged["twin_transfer"] = fixtures.read_pending_escrow_transfer(
            staged["twin"]["loan_id"]
        )
        return staged

    def test_each_transfer_freezes_its_own_escrow_and_completes_on_the_due_instant(self):
        """250,000 and 180,000 travel separately, and the fifteenth day still counts.

        Settlement synthesises one transfer per released file, each frozen at that
        loan's own escrow balance and due fifteen days after its purchase, and the
        transfers are only discoverable through the loan's listing. Completing
        exactly at the due instant is on time, and the same transfer cannot be
        completed twice — the duplicate leaves the original goodbye letter in
        place.

        PRD: "When the loan's `servicing_election` is `RELEASED`, an
        **EscrowTransfer** is created in `PENDING` status with
        `transfer_amount_cents` frozen at the loan's `escrow_balance_cents` and
        `transfer_due_at` set to `purchased_at` advanced by 15 days."

        PRD: "The transfer must be in `PENDING` status, else
        `ERR_TRANSFER_NOT_PENDING`."

        Design: Corner/endpoints/escrow_completion_is_on_time_at_the_due_instant_single_shot_and_barred_one_second_late
        """
        staged = self._twin_released_purchases_with_their_transfers()

        transfer = staged["transfer"]
        assert_escrow_transfer(transfer)
        assert transfer["transfer_amount_cents"] == 250000
        assert transfer["transfer_due_at"] == "2026-08-16T00:00:00.000Z"
        assert transfer["status"] == "PENDING"
        assert staged["twin_transfer"]["transfer_amount_cents"] == 180000

        fixtures.setup_clock("2026-08-16T00:00:00Z")
        completed = fixtures.complete_escrow_transfer(
            transfer["id"], "GBL-2026-0001"
        )
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"] == "2026-08-16T00:00:00.000Z"
        assert completed["goodbye_letter_reference"] == "GBL-2026-0001"

        validate_error(
            api_client.complete_escrow_transfer(
                transfer["id"],
                factories.escrow_completion_payload("GBL-2026-0001-DUP"),
                REVIEWER,
            ),
            ApiErrorId.ERR_TRANSFER_NOT_PENDING,
            409,
        )

        unchanged = [
            item
            for item in fixtures.read_escrow_transfers(staged["loan_id"])
            if item["id"] == transfer["id"]
        ][0]
        assert unchanged["goodbye_letter_reference"] == "GBL-2026-0001"
        assert unchanged["status"] == "COMPLETED"

    def test_a_transfer_one_second_late_is_barred_and_left_pending(self):
        """At 2026-08-16T00:00:01Z the twin's handover must go off-platform.

        The window closes the instant after the due instant, so the twin transfer
        is refused a single second later and stays exactly as settlement left it:
        pending, uncompleted and unreversed, with nothing recorded against it.

        PRD: "And the logical clock must be at or before `transfer_due_at`, else
        `ERR_ESCROW_TRANSFER_OVERDUE` — a late transfer must be escalated
        off-platform rather than booked on time."

        Design: Corner/endpoints/escrow_completion_is_on_time_at_the_due_instant_single_shot_and_barred_one_second_late
        """
        staged = self._twin_released_purchases_with_their_transfers()

        fixtures.setup_clock("2026-08-16T00:00:01Z")
        validate_error(
            api_client.complete_escrow_transfer(
                staged["twin_transfer"]["id"],
                factories.escrow_completion_payload("GBL-2026-0002"),
                REVIEWER,
            ),
            ApiErrorId.ERR_ESCROW_TRANSFER_OVERDUE,
            409,
        )

        twin_transfers, meta = validate_paginated(
            api_client.list_escrow_transfers(staged["twin"]["loan_id"], REVIEWER)
        )
        assert meta["total_count"] == 1
        still_pending = twin_transfers[0]
        assert_escrow_transfer(still_pending)
        assert still_pending["status"] == "PENDING"
        assert still_pending["completed_at"] is None
        assert still_pending["reversal_reason"] is None
        assert still_pending["goodbye_letter_reference"] is None
        assert fixtures.read_loan(staged["twin"]["loan_id"])["purchase_status"] == "PURCHASED"
