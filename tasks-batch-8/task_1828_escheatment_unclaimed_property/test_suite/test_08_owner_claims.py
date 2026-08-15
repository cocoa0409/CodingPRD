"""Owner claims: creation gates, review loop, payout computation, and
reunification (PRD §3.7)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    make_claimant_headers,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)
from test_helpers.fixtures import (
    CE,
    READER,
    TO,
    create_claim,
    get_property,
    set_clock,
    setup_accepted_single_line_report,
    setup_remitted_cash_property,
    setup_remitted_securities_property,
    setup_under_review_claim,
    start_claim_review,
)

CE_H = TEST_USERS["claims_examiner_headers"]
AP_H = TEST_USERS["claims_approver_headers"]
TO_H = TEST_USERS["treasury_ops_headers"]


class TestClaimCreationGate:
    def test_claim_on_reported_but_not_remitted_rejected(self, api):
        """PRD §3.7: "The property must stand `REMITTED` or `ESCHEATED`, else
        `ERR_PROPERTY_NOT_CLAIMABLE`."

        Design: Difficulty/cross_entity_state_dependency/claim_create_requires_remitted_property
        """
        chain = setup_accepted_single_line_report(value=100000)
        # The property is REPORTED (in an ACCEPTED report) but not REMITTED.
        assert get_property(chain["property"]["id"])["status"] == "REPORTED"
        resp = api.create_claim(
            {"property_id": chain["property"]["id"]},
            make_claimant_headers(chain["owner"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_CLAIMABLE, 422)

    def test_rejected_claim_leaves_no_row(self, api):
        """PRD §3.7: "A `Claimant` files through a payload naming the
        `property_id` and, optionally, an `evidence_ref`. The claim's
        `claimant_owner_id` is set to the filer's `X-User-ID` and must equal
        the property's owner"

        Design: Difficulty/cross_entity_state_dependency/claim_create_requires_remitted_property
        """
        chain = setup_accepted_single_line_report(value=100000)
        prop = get_property(chain["property"]["id"])
        validate_error(
            api.create_claim(
                {"property_id": prop["id"]},
                make_claimant_headers(prop["owner_id"]),
            ),
            ApiErrorId.ERR_PROPERTY_NOT_CLAIMABLE,
            422,
        )
        claims, meta = validate_paginated(
            api.list_property_claims(prop["id"], READER)
        )
        assert meta["total_count"] == 0


class TestClaimPayoutVariants:
    def test_cash_claim_accrues_interest(self, api):
        """PRD §3.7: "Second, interest: for `CASH`, the base multiplied by the
        applicable rule's `annual_interest_rate_bp` and by the days held,
        divided by 3,650,000, and rounded half-up to whole cents, where the
        days held run from the confirming remittance's `confirmed_date` to the
        approval date and never below zero"

        Design: Difficulty/dual_variant_calc/claim_payout_cash_interest_vs_securities_proceeds
        """
        chain = setup_remitted_cash_property(original_value_cents=200000)
        claim = create_claim(chain["property"]["id"], chain["owner"]["id"])
        start_claim_review(claim["id"])
        set_clock("2026-12-10T00:00:00Z")  # 100 days after the 2026-09-01 confirm
        approved = get_success_data(api.approve_claim(claim["id"], AP_H), 200)
        assert approved["claim_type"] == "CASH"
        assert approved["approved_base_cents"] == 200000
        # round_half_up(200000 * 1200 * 100 / 3650000) = 6575
        assert approved["approved_interest_cents"] == 6575
        # gross 206575 > 100000 -> round_half_up(206575 * 150 / 10000) = 3099
        assert approved["processing_fee_cents"] == 3099
        assert approved["approved_payout_cents"] == 203476

    def test_securities_claim_pays_proceeds_without_interest(self, api):
        """PRD §3.7: "for `SECURITIES`, always zero — states return liquidation
        proceeds without interest, so identical bases still yield different
        payouts across the two variants whenever the days held are positive."

        Design: Difficulty/dual_variant_calc/claim_payout_cash_interest_vs_securities_proceeds
        """
        chain = setup_remitted_securities_property()
        claim = create_claim(chain["property"]["id"], chain["owner"]["id"])
        start_claim_review(claim["id"])
        set_clock("2026-12-10T00:00:00Z")  # days_held 100, same as the cash case
        approved = get_success_data(api.approve_claim(claim["id"], AP_H), 200)
        assert approved["claim_type"] == "SECURITIES"
        assert approved["approved_base_cents"] == 480000  # settled net proceeds
        assert approved["approved_interest_cents"] == 0
        # gross 480000 > 100000 -> round_half_up(480000 * 150 / 10000) = 7200
        assert approved["processing_fee_cents"] == 7200
        assert approved["approved_payout_cents"] == 472800


class TestClaimFeeTierBoundary:
    def test_gross_at_cap_pays_no_fee(self, api):
        """PRD §3.7: "Fourth, the fee tier is selected by that gross: the
        processing fee applies only when the gross exceeds 100000 cents — one
        thousand dollars — and a gross at or below that cap pays no fee."

        Design: Difficulty/combinatorial_formula/claim_payout_fee_tier_pinned_evaluation_order
        """
        chain = setup_remitted_cash_property(original_value_cents=100000)
        claim = create_claim(chain["property"]["id"], chain["owner"]["id"])
        start_claim_review(claim["id"])
        # Approve on the confirmation date itself: days_held 0, interest 0.
        approved = get_success_data(api.approve_claim(claim["id"], AP_H), 200)
        assert approved["approved_interest_cents"] == 0
        assert approved["approved_base_cents"] == 100000
        # gross 100000 is not strictly above the 100000 cap.
        assert approved["processing_fee_cents"] == 0
        assert approved["approved_payout_cents"] == 100000

    def test_one_day_of_interest_crosses_into_fee_tier(self, api):
        """PRD §3.7: "The payout is computed in a pinned order — this ordering
        is what resolves the apparent circularity between the fee and the gross
        it is levied on."
        PRD §3.7: "Fifth, the `processing_fee_cents` is the gross multiplied by
        150 basis points — one and a half percent — rounded half-up to whole
        cents when the tier applies, and zero otherwise."

        Design: Difficulty/combinatorial_formula/claim_payout_fee_tier_pinned_evaluation_order
        """
        chain = setup_remitted_cash_property(original_value_cents=100000)
        claim = create_claim(chain["property"]["id"], chain["owner"]["id"])
        start_claim_review(claim["id"])
        set_clock("2026-09-02T00:00:00Z")  # one day after the confirm
        approved = get_success_data(api.approve_claim(claim["id"], AP_H), 200)
        # round_half_up(100000 * 1200 * 1 / 3650000) = 33
        assert approved["approved_interest_cents"] == 33
        # gross 100033 > 100000 -> tier applies: round_half_up(100033 * 150 / 10000) = 1500
        assert approved["processing_fee_cents"] == 1500
        assert approved["approved_payout_cents"] == 98533


class TestClaimReviewLoop:
    def _loop_twice(self, claim_id, owner_id):
        ce = CE_H
        claimant = make_claimant_headers(owner_id)
        s1 = get_success_data(
            api_client.request_claim_info(
                claim_id, {"info_request_note": "need id document"}, ce
            ),
            200,
        )
        s2 = get_success_data(
            api_client.submit_claim_info(
                claim_id, {"info_response_ref": "doc-9"}, claimant
            ),
            200,
        )
        s3 = get_success_data(
            api_client.request_claim_info(
                claim_id, {"info_request_note": "need proof of address"}, ce
            ),
            200,
        )
        s4 = get_success_data(
            api_client.submit_claim_info(
                claim_id, {"info_response_ref": "doc-10"}, claimant
            ),
            200,
        )
        return [s1, s2, s3, s4]

    def test_under_review_more_info_loop_twice(self, api):
        """PRD §3.7: "The examiner may request more information, supplying an
        `info_request_note`, which moves an `UNDER_REVIEW` claim (else
        `ERR_CLAIM_NOT_UNDER_REVIEW`) to `MORE_INFO_REQUESTED`. The claimant
        answers by submitting information with an `info_response_ref`; this is
        allowed only from `MORE_INFO_REQUESTED` (else
        `ERR_CLAIM_NOT_AWAITING_INFO`) and only by the owning claimant (else
        `ERR_OWNERSHIP_SCOPE_VIOLATION`), and returns the claim to
        `UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/claim_more_info_request_cycle
        """
        chain = setup_under_review_claim(original_value_cents=150000)
        states = self._loop_twice(chain["claim"]["id"], chain["owner"]["id"])
        assert [s["status"] for s in states] == [
            "MORE_INFO_REQUESTED", "UNDER_REVIEW",
            "MORE_INFO_REQUESTED", "UNDER_REVIEW",
        ]
        for s in states:
            assert s["reviewed_by_user_id"] == "ce-1", (
                "the review anchor stays pinned across info loops"
            )

    def test_approve_after_loops_computes_payout(self, api):
        """PRD §3.7: "Approval additionally requires the property to still
        stand `REMITTED` or `ESCHEATED` (else `ERR_PROPERTY_NOT_CLAIMABLE`); it
        computes the payout, recording `approved_base_cents`,
        `approved_interest_cents`, `processing_fee_cents`, and
        `approved_payout_cents`, and captures the approver as
        `decided_by_user_id`."

        Design: Difficulty/non_linear_state_machine/claim_more_info_request_cycle
        """
        chain = setup_under_review_claim(original_value_cents=150000)
        self._loop_twice(chain["claim"]["id"], chain["owner"]["id"])
        approved = get_success_data(
            api.approve_claim(chain["claim"]["id"], AP_H), 200
        )
        assert approved["status"] == "APPROVED"
        # days_held 0 -> interest 0; gross 150000 > 100000 -> fee 2250
        assert approved["approved_base_cents"] == 150000
        assert approved["approved_interest_cents"] == 0
        assert approved["processing_fee_cents"] == 2250
        assert approved["approved_payout_cents"] == 147750
        assert approved["reviewed_by_user_id"] == "ce-1"
        assert approved["decided_by_user_id"] == "ap-1"


class TestClaimTransitions:
    def test_withdraw_from_submitted_then_review_rejected(self, api):
        """PRD §3.7: "A claimant who thinks better of it may withdraw, but only
        from `SUBMITTED` or `MORE_INFO_REQUESTED` (else
        `ERR_CLAIM_NOT_WITHDRAWABLE`) and only their own claim (else
        `ERR_OWNERSHIP_SCOPE_VIOLATION`), moving it to the terminal
        `WITHDRAWN`."
        PRD §3.7: "A `ClaimsExaminer` opens review on a `SUBMITTED` claim —
        any other state is `ERR_CLAIM_NOT_SUBMITTED`"

        Design: Corner/state_machines/claim_withdraw_from_submitted
        """
        chain = setup_remitted_cash_property(original_value_cents=90000)
        claim = create_claim(chain["property"]["id"], chain["owner"]["id"])
        withdrawn = get_success_data(
            api.withdraw_claim(
                claim["id"], make_claimant_headers(chain["owner"]["id"])
            ),
            200,
        )
        assert withdrawn["status"] == "WITHDRAWN"
        resp = api.start_claim_review(claim["id"], CE_H)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED, 409)

    def test_pay_reunites_property(self, api):
        """PRD §3.7: "A `TreasuryOps` operator pays an `APPROVED` claim — any
        other state is `ERR_CLAIM_NOT_APPROVED` — stamping `paid_date` with the
        clock date, moving the claim to its terminal `PAID` state, and
        cascading to the property: `REMITTED → REUNITED` or `ESCHEATED →
        REUNITED`, with `reunited_date` set to the clock date."

        Design: Corner/state_machines/claim_pay_reunites_property
        """
        chain = setup_under_review_claim(original_value_cents=150000)
        get_success_data(api.approve_claim(chain["claim"]["id"], AP_H), 200)
        paid = get_success_data(api.pay_claim(chain["claim"]["id"], TO_H), 200)
        assert paid["status"] == "PAID"
        assert paid["paid_date"] == "2026-09-01"
        prop = get_property(chain["property"]["id"])
        assert prop["status"] == "REUNITED"
        assert prop["reunited_date"] == "2026-09-01"

    def test_off_transition_actions_from_under_review(self, api):
        """PRD §3.7: "this is allowed only from `MORE_INFO_REQUESTED` (else
        `ERR_CLAIM_NOT_AWAITING_INFO`)"
        PRD §3.7: "A `TreasuryOps` operator pays an `APPROVED` claim — any
        other state is `ERR_CLAIM_NOT_APPROVED`"
        PRD §3.7: "A claimant who thinks better of it may withdraw, but only
        from `SUBMITTED` or `MORE_INFO_REQUESTED` (else
        `ERR_CLAIM_NOT_WITHDRAWABLE`)"

        Design: Corner/errors/claim_actions_from_under_review_rejected
        """
        chain = setup_under_review_claim(original_value_cents=90000)
        claim = chain["claim"]
        owner_headers = make_claimant_headers(chain["owner"]["id"])
        e1 = api.submit_claim_info(claim["id"], {"info_response_ref": "doc-x"}, owner_headers)
        validate_error(e1, ApiErrorId.ERR_CLAIM_NOT_AWAITING_INFO, 409)
        e2 = api.pay_claim(claim["id"], TO_H)
        validate_error(e2, ApiErrorId.ERR_CLAIM_NOT_APPROVED, 409)
        e3 = api.withdraw_claim(claim["id"], owner_headers)
        validate_error(e3, ApiErrorId.ERR_CLAIM_NOT_WITHDRAWABLE, 409)
        still = get_success_data(api.get_claim(claim["id"], READER), 200)
        assert still["status"] == "UNDER_REVIEW"

    def test_start_review_twice_rejected(self, api):
        """PRD §3.7: "A `ClaimsExaminer` opens review on a `SUBMITTED` claim —
        any other state is `ERR_CLAIM_NOT_SUBMITTED` — moving it to
        `UNDER_REVIEW` and recording their identity as `reviewed_by_user_id`."

        Design: Corner/errors/start_review_twice_rejected
        """
        chain = setup_remitted_cash_property(original_value_cents=90000)
        claim = create_claim(chain["property"]["id"], chain["owner"]["id"])
        start_claim_review(claim["id"])
        resp = api.start_claim_review(claim["id"], CE_H)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED, 409)

    def test_duplicate_active_claim_rejected(self, api):
        """PRD §3.7: "At most one non-terminal claim — one in `SUBMITTED`,
        `UNDER_REVIEW`, `MORE_INFO_REQUESTED`, or `APPROVED` — may exist per
        property, else `ERR_DUPLICATE_ACTIVE_CLAIM`."

        Design: Corner/errors/duplicate_active_claim_rejected
        """
        chain = setup_remitted_cash_property(original_value_cents=90000)
        first = create_claim(chain["property"]["id"], chain["owner"]["id"])
        resp = api.create_claim(
            {"property_id": chain["property"]["id"]},
            make_claimant_headers(chain["owner"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_CLAIM, 409)
        still = get_success_data(api.get_claim(first["id"], READER), 200)
        assert still["status"] == "SUBMITTED"
