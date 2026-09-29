"""The discrepancy-claim window: the review cycle, its ceiling and the two decisions."""

from test_helpers import (
    ApiErrorId,
    MANAGER_1,
    approve_claim_payload,
    assert_bag_settlement_identity,
    assert_discrepancy_claim,
    create_discrepancy_claim_payload,
    make_customer_account_holder_headers,
    make_manager_headers,
    read_bag,
    read_claim,
    read_ticket,
    resubmit_claim_payload,
    setup_claim_under_review,
    setup_counted_bag,
    setup_verified_ticket,
    settle_ticket,
    validate_error,
    validate_paginated,
    validate_success,
)

SHORT_BAG = {
    "declared_amount_cents": 102_500,
    "declared_note_count": 100,
    "counted_amount_cents": 100_000,
    "counted_note_count": 100,
}


class TestClaimReviewCycle:
    def test_each_resubmit_increments_the_review_round(self, api):
        """PRD §3.6: "A filed claim is created in `SUBMITTED` with `review_round` at 1,
        `filed_at` stamped from the logical clock, `resolution_amount_cents` at 0, and
        `decided_by_user_id`, `info_request_note` and `denial_reason` all null."
        PRD §3.6: "The customer answers by resubmitting with a revised
        `claimed_amount_cents`, which moves the claim `INFO_REQUESTED → SUBMITTED`, replaces
        the stored amount with the revised one, and increments `review_round` by 1."

        Design: Difficulty/non_linear_state_machine/discrepancy_claim_cycles_until_review_round_limit
        """
        scenario = setup_claim_under_review(**SHORT_BAG, claimed_amount_cents=2_500, rounds=3)

        assert scenario["review_rounds"] == [1, 2, 3], (
            f"The claim must pass through rounds 1, 2 and 3, got {scenario['review_rounds']}"
        )
        claim = read_claim(scenario["claim"]["id"])
        assert_discrepancy_claim(claim)
        assert claim["status"] == "SUBMITTED", (
            f"After the second resubmit the claim is back at SUBMITTED, got {claim['status']}"
        )
        assert claim["review_round"] == 3, (
            f"Expected review_round 3, got {claim['review_round']}"
        )
        assert claim["customer_account_id"] == scenario["account"]["id"], (
            "customer_account_id is copied from the disputed bag's deposit ticket"
        )

    def test_a_fourth_submission_is_refused_at_the_review_round_ceiling(self, api):
        """PRD §3.6: "And the cycle is capped at three review rounds: a resubmit is accepted
        only while `review_round` is strictly less than 3, so a claim already on its third
        round cannot go around again and the attempt is rejected with
        `ERR_CLAIM_ROUND_LIMIT`."
        PRD §3.6: "A `VaultManager` who needs more evidence supplies an `info_request_note`
        and moves the claim `SUBMITTED → INFO_REQUESTED`, recording the note."

        Design: Difficulty/non_linear_state_machine/discrepancy_claim_cycles_until_review_round_limit
        """
        scenario = setup_claim_under_review(
            **SHORT_BAG, claimed_amount_cents=2_500, rounds=3, leave_in_info_requested=True
        )
        claim_id = scenario["claim"]["id"]
        assert scenario["claim"]["status"] == "INFO_REQUESTED"
        assert scenario["claim"]["review_round"] == 3

        response = api.resubmit_discrepancy_claim(
            claim_id,
            resubmit_claim_payload(2_500),
            make_customer_account_holder_headers(scenario["account"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_CLAIM_ROUND_LIMIT.value)
        assert response.status_code == 409, (
            f"ERR_CLAIM_ROUND_LIMIT must be HTTP 409, got {response.status_code}"
        )

        claim = read_claim(claim_id)
        assert claim["review_round"] == 3, (
            f"The refused resubmit must not advance the round, got {claim['review_round']}"
        )
        assert claim["status"] == "INFO_REQUESTED", (
            f"The claim stays in INFO_REQUESTED, got {claim['status']}"
        )


class TestFilingGuards:
    def test_a_claim_against_an_uncounted_bag_is_refused(self, api):
        """PRD §3.6: "The bag must actually have been counted — its counting axis must read
        `COUNTED` or `ADJUSTED`, and a bag still `PENDING` or `COUNTING` yields
        `ERR_BAG_NOT_COUNTED`."

        Design: Corner/validations/claim_on_uncounted_bag_returns_bag_not_counted
        """
        scenario = setup_verified_ticket(
            bag_specs=[
                {
                    "bag_type": "CURRENCY",
                    "declared_amount_cents": 102_500,
                    "declared_note_count": 100,
                    "declared_coin_weight_grams": 0,
                }
            ]
        )
        bag = scenario["bag"]
        assert read_bag(bag["id"])["count_status"] == "PENDING"

        response = api.create_discrepancy_claim(
            create_discrepancy_claim_payload(bag["id"], 2_500),
            make_customer_account_holder_headers(scenario["account"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_BAG_NOT_COUNTED.value)
        assert response.status_code == 409

        _, meta = validate_paginated(
            api.list_discrepancy_claims(
                make_manager_headers(MANAGER_1), params={"sealed_bag_id": bag["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"No claim may be created against an uncounted bag, got {meta['total_count']}"
        )

    def test_a_claim_above_the_bags_declared_amount_is_refused(self, api):
        """PRD §3.6: "And the amount asserted must not exceed the bag's own
        `declared_amount_cents`; a customer cannot claim more than they said was in the bag,
        and an over-claim is `ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED`."

        Design: Corner/validations/claim_amount_exceeding_bag_declared_amount_rejected
        """
        scenario = setup_counted_bag(**SHORT_BAG)

        response = api.create_discrepancy_claim(
            create_discrepancy_claim_payload(scenario["bag"]["id"], 200_000),
            make_customer_account_holder_headers(scenario["account"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED.value)
        assert response.status_code == 422

        _, meta = validate_paginated(
            api.list_discrepancy_claims(
                make_manager_headers(MANAGER_1),
                params={"sealed_bag_id": scenario["bag"]["id"]},
            )
        )
        assert meta["total_count"] == 0, (
            f"No claim may be created by an over-claim, got {meta['total_count']}"
        )


class TestClaimDecisions:
    def test_a_resolution_above_the_claimed_amount_is_refused(self, api):
        """PRD §3.6: "**Approving** the claim moves it `SUBMITTED → APPROVED` and requires a
        `resolution_amount_cents` that does not exceed the claim's current
        `claimed_amount_cents` — a manager may grant less than was asked but never more, and
        an over-grant is `ERR_RESOLUTION_EXCEEDS_CLAIM`."

        Design: Corner/validations/resolution_amount_exceeding_claimed_amount_rejected
        """
        scenario = setup_claim_under_review(**SHORT_BAG, claimed_amount_cents=2_500)

        response = api.approve_discrepancy_claim(
            scenario["claim"]["id"],
            approve_claim_payload(3_000),
            make_manager_headers(MANAGER_1),
        )
        validate_error(response, ApiErrorId.ERR_RESOLUTION_EXCEEDS_CLAIM.value)
        assert response.status_code == 422

        claim = read_claim(scenario["claim"]["id"])
        assert claim["status"] == "SUBMITTED", (
            f"The refused approval leaves the claim SUBMITTED, got {claim['status']}"
        )
        assert claim["resolution_amount_cents"] == 0
        bag = read_bag(scenario["bag"]["id"])
        assert bag["count_status"] == "COUNTED", "The bag is untouched by a refused approval"
        assert bag["claim_adjustment_cents"] == 0

    def test_the_count_verifier_may_not_decide_the_claim_about_that_count(self, api):
        """PRD §2.9: "When a discrepancy claim is approved or denied, the deciding
        `VaultManager`'s `X-User-ID` must differ from the `verifier_user_id` of the
        `COMPLETED` counting session whose `sealed_bag_id` matches the claim's disputed bag."
        PRD §3.6: "Both terminal decisions are made by a `VaultManager`, and both are blocked
        for one particular manager: whoever holds the `verifier_user_id` on the `COMPLETED`
        counting session for the disputed bag may not decide the claim, and an attempt yields
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/count_verifier_cannot_decide_the_claim_about_that_count
        """
        scenario = setup_claim_under_review(
            **SHORT_BAG, claimed_amount_cents=2_500, verifier_user_id=MANAGER_1
        )
        assert scenario["session"]["verifier_user_id"] == MANAGER_1, (
            "The count was completed by the user who now tries to decide the claim"
        )

        response = api.approve_discrepancy_claim(
            scenario["claim"]["id"],
            approve_claim_payload(2_500),
            make_manager_headers(MANAGER_1),
        )
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        assert response.status_code == 409

        claim = read_claim(scenario["claim"]["id"])
        assert claim["status"] == "SUBMITTED"
        assert read_bag(scenario["bag"]["id"])["count_status"] == "COUNTED"

    def test_approving_the_claim_adjusts_the_bag_and_clears_the_settlement_block(self, api):
        """PRD §3.6: "Three cascade hops follow. First, the bag's `claim_adjustment_cents` is
        set to the granted `resolution_amount_cents` and the bag's counting axis moves
        `COUNTED → ADJUSTED`, incrementing the bag's `version` by 1. Second, because the bag
        was adjusted, its `settlement_amount_cents` is recomputed as `counted_amount_cents`
        plus `claim_adjustment_cents` minus `seized_amount_cents`, and the deposit ticket's
        `counted_total_cents` is recomputed from the bags. Note that the bag's
        `variance_cents` is deliberately left alone — it remains the frozen record of what the
        machine found. Third, if the bag carried `materiality_flag` true, the ticket's
        `material_variance_open_count` is decremented by 1, because that flagged bag has now
        left `COUNTED`."
        PRD §3.7: "Step four: the ticket's `final_settlement_cents` is the gross counted
        figure minus that final fee."

        Design: Corner/state_machines/claim_approval_adjusts_the_bag_and_releases_the_settlement_block
        """
        scenario = setup_claim_under_review(**SHORT_BAG, claimed_amount_cents=2_500)
        assert read_ticket(scenario["ticket"]["id"])["material_variance_open_count"] == 1

        response = api.approve_discrepancy_claim(
            scenario["claim"]["id"],
            approve_claim_payload(2_500),
            make_manager_headers(MANAGER_1),
        )
        claim = validate_success(response, 200)
        assert claim["status"] == "APPROVED", f"Expected APPROVED, got {claim['status']}"
        assert claim["resolution_amount_cents"] == 2_500
        assert claim["decided_by_user_id"] == MANAGER_1

        bag = read_bag(scenario["bag"]["id"])
        assert bag["count_status"] == "ADJUSTED", (
            f"The bag's counting axis moves to ADJUSTED, got {bag['count_status']}"
        )
        assert bag["claim_adjustment_cents"] == 2_500
        assert bag["variance_cents"] == -2500, (
            "variance_cents stays frozen at the machine's finding"
        )
        assert bag["settlement_amount_cents"] == 102_500, (
            f"100000 + 2500 - 0 = 102500, got {bag['settlement_amount_cents']}"
        )
        assert_bag_settlement_identity(bag)

        ticket = read_ticket(scenario["ticket"]["id"])
        assert ticket["counted_total_cents"] == 102_500
        assert ticket["material_variance_open_count"] == 0, (
            "The flagged bag has left COUNTED, so the counter drops to 0"
        )

        settled = settle_ticket(ticket["id"])
        assert settled["final_settlement_cents"] == 102_246, (
            f"102500 gross minus the 254 fee = 102246, got {settled['final_settlement_cents']}"
        )
