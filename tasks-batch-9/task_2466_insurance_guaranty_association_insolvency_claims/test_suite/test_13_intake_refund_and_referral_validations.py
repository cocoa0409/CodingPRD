"""Refusals around the order, claim intake, the single refund and the referral desk."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_covered_claim,
    assert_instant_equals,
    assert_referral,
    assert_unearned_premium_refund,
    claim_payload,
    create_policy,
    get_success_data,
    move_clock,
    premium_refund_payload,
    raise_referral,
    read_claim,
    read_insolvency,
    read_policy,
    referral_payload,
    referral_response_payload,
    respond_to_referral,
    setup_claim_under_adjustment,
    setup_claim_with_open_referral,
    setup_declared_insolvency,
    setup_policy_with_premium_refund,
    setup_triggered_insolvency,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["association_admin_headers"]
ANALYST = TEST_USERS["coverage_analyst_headers"]

LIVE_TERM = {
    "policy_number": "PA-1001",
    "policyholder_name": "Ada Renner",
    "effective_date": "2025-10-01",
    "expiration_date": "2026-10-01",
    "annual_premium_cents": 1_200_000,
}
SIBLING_TERM = {
    "policy_number": "PA-1002",
    "policyholder_name": "Boris Ilic",
    "effective_date": "2025-10-01",
    "expiration_date": "2026-10-01",
    "annual_premium_cents": 1_200_000,
}
HOMEOWNERS_TERM = {
    "policy_number": "HO-1",
    "line_of_business": "HOMEOWNERS",
    "policyholder_name": "Ada Renner",
    "effective_date": "2025-10-01",
    "expiration_date": "2026-10-01",
    "annual_premium_cents": 1_200_000,
}

MICHIGAN_CLAIM = {
    "claim_number": "C-1",
    "claimant_name": "Ben Ortiz",
    "gross_loss_cents": 900_000,
}
OHIO_CLAIM = {
    "claim_number": "C-1",
    "claimant_name": "Ben Ortiz",
    "claimant_state_code": "OH",
    "gross_loss_cents": 900_000,
}
KESTREL_ADJUSTER = {
    "vendor_name": "Kestrel Claims Services",
    "settlement_authority_cents": 900_000,
    "hourly_rate_cents": 18_000,
    "engagement_start": "2026-08-01",
    "engagement_end": "2026-08-31",
}


class TestTheOrderMustBeAbleToPriceTheBook:
    """The triggering event needs a configuration row for every imported line."""

    def test_an_imported_line_with_no_configuration_row_blocks_the_order(self):
        """Nothing statutory happens until the **triggering event** is recorded, and that recording is
        a one-way door. Before an `AssociationAdmin` may record it, three conditions must hold: the
        file must still be in `DECLARED`; at least one transferred policy of the file must exist in
        `IMPORTED`; and a statutory coverage configuration row must exist for every distinct line of
        business appearing among the file's transferred policies, without which the operation fails
        with `ERR_COVERAGE_PROFILE_MISSING` because the association would be unable to price the book
        it is about to inherit.

        Design: Corner/validations/triggering_without_a_profile_for_an_imported_line_is_refused
        """
        env = setup_declared_insolvency(policy_overrides=dict(HOMEOWNERS_TERM))
        assert env["profile"]["line_of_business"] == "PERSONAL_AUTO", (
            env["profile"]["line_of_business"]
        )
        assert env["policy"]["line_of_business"] == "HOMEOWNERS", (
            env["policy"]["line_of_business"]
        )

        validate_error(
            api_client.trigger_insolvency(env["insolvency"]["id"], ADMIN),
            "ERR_COVERAGE_PROFILE_MISSING",
            422,
        )

        after = read_insolvency(env["insolvency"]["id"])
        assert after["status"] == "DECLARED", (
            f"the order cannot be recorded on an unpriceable book, got {after['status']}"
        )
        assert after["triggered_at_utc"] is None
        assert after["coverage_termination_date"] is None, (
            f"no statutory date is derived, got {after['coverage_termination_date']}"
        )
        assert after["proof_of_claim_deadline_utc"] is None

        policy = read_policy(env["policy"]["id"])
        assert policy["status"] == "IMPORTED", (
            f"the refused cascade leaves the policy untouched, got {policy['status']}"
        )
        assert policy["cancellation_date"] is None


class TestClaimIntakeUniquenessAndTheDeadline:
    """The claim number is scoped to one policy, and the deadline instant is inclusive."""

    def test_the_same_claim_number_is_free_on_a_sibling_policy(self):
        """`claim_number` must be unique within the one policy, a collision being refused with
        `ERR_DUPLICATE_CLAIM`; `claimant_state_code` must be exactly two uppercase letters;
        `loss_date` must be an ISO 8601 calendar date; and `gross_loss_cents` must be greater than 0.

        Design: Corner/validations/reusing_a_claim_number_on_the_same_policy_is_refused
        """
        env = setup_declared_insolvency(policy_overrides=dict(LIVE_TERM))
        sibling = create_policy(env["insolvency"]["id"], **SIBLING_TERM)
        env["insolvency"] = get_success_data(
            api_client.trigger_insolvency(env["insolvency"]["id"], ADMIN)
        )
        insolvency_id = env["insolvency"]["id"]

        first = get_success_data(
            api_client.create_claim(
                claim_payload(insolvency_id, env["policy"]["id"], **MICHIGAN_CLAIM), ANALYST
            ),
            201,
        )
        assert_covered_claim(first)
        assert first["claim_number"] == "C-1", first["claim_number"]

        validate_error(
            api_client.create_claim(
                claim_payload(
                    insolvency_id,
                    env["policy"]["id"],
                    claim_number="C-1",
                    claimant_name="Cora Diaz",
                    loss_date="2026-02-01",
                    gross_loss_cents=400_000,
                ),
                ANALYST,
            ),
            "ERR_DUPLICATE_CLAIM",
            409,
        )

        elsewhere = get_success_data(
            api_client.create_claim(
                claim_payload(
                    insolvency_id,
                    sibling["id"],
                    claim_number="C-1",
                    claimant_name="Cora Diaz",
                    loss_date="2026-02-01",
                    gross_loss_cents=400_000,
                ),
                ANALYST,
            ),
            201,
        )
        assert elsewhere["policy_id"] == sibling["id"], (
            "the same number is free on another policy of the same file"
        )

        rows, _ = validate_paginated(
            api_client.list_claims(ANALYST, {"policy_id": env["policy"]["id"], "limit": 50})
        )
        assert len(rows) == 1, f"the refused collision stored nothing, got {len(rows)} claims"
        assert rows[0]["id"] == first["id"]

    def test_a_claim_filed_on_the_deadline_instant_itself_is_accepted(self):
        """It computes `proof_of_claim_deadline_utc` as the `liquidation_order_date` advanced by 365
        calendar days, at the instant `00:00:00Z` on that date; filings at exactly that instant are
        still accepted, and only filings strictly after it are late.

        A covered claim may be presented by a `ReceiverLiaison` or a `CoverageAnalyst`, but only
        against a triggered insolvency file and only at or before the file's
        `proof_of_claim_deadline_utc`; a filing whose logical-clock instant falls strictly after that
        boundary is refused with `ERR_FILING_DEADLINE_PASSED`.

        Design: Corner/validations/a_claim_filed_exactly_at_the_deadline_instant_is_accepted
        """
        env = setup_triggered_insolvency(policy_overrides=dict(LIVE_TERM))
        assert_instant_equals(
            env["insolvency"]["proof_of_claim_deadline_utc"], "2027-03-01T00:00:00Z"
        )

        move_clock("2027-03-01T00:00:00Z")
        claim = get_success_data(
            api_client.create_claim(
                claim_payload(
                    env["insolvency"]["id"],
                    env["policy"]["id"],
                    claim_number="C-LATE",
                    claimant_name="Ben Ortiz",
                    gross_loss_cents=900_000,
                ),
                ANALYST,
            ),
            201,
        )

        assert_covered_claim(claim)
        assert_instant_equals(
            claim["filed_at_utc"],
            "2027-03-01T00:00:00Z",
            f"the boundary instant itself is allowed, got {claim['filed_at_utc']}",
        )
        assert claim["status"] == "RECEIVED", claim["status"]

        insolvency = read_insolvency(env["insolvency"]["id"])
        assert_instant_equals(
            insolvency["proof_of_claim_deadline_utc"], "2027-03-01T00:00:00Z"
        )


class TestOneRefundPerPolicy:
    """The refund latch does not reopen for the other statutory variant."""

    def test_the_second_filing_is_refused_even_under_the_other_variant(self):
        """Exactly one refund may exist per policy: a `CoverageAnalyst` files it, and the operation is
        admissible only on a policy whose `status` is `CANCELLED_BY_ORDER` — a policy still in
        `IMPORTED`, or one that expired before the order and sits in `EXPIRED_BEFORE_ORDER`, is
        refused with `ERR_POLICY_NOT_CANCELLED` — and only while that policy's `up_refund_filed` is
        still false, a second attempt being refused with `ERR_UP_REFUND_ALREADY_FILED`.

        On the policy, `up_refund_filed` is set to true and the policy's `version` is incremented by
        one — which is exactly why a second, concurrent filer holding the earlier version is turned
        away.

        Design: Corner/validations/filing_a_second_unearned_premium_refund_on_one_policy_is_refused
        """
        env = setup_policy_with_premium_refund(
            refund_method="PRO_RATA", policy_overrides=dict(LIVE_TERM)
        )
        refund = env["refund"]
        assert_unearned_premium_refund(refund)
        assert refund["computed_refund_cents"] == 604_932, (
            f"1200000 over 365 days for 184 unexpired days, got "
            f"{refund['computed_refund_cents']}"
        )

        latched = read_policy(env["policy"]["id"])
        assert latched["up_refund_filed"] is True, "the first filing sets the latch"

        validate_error(
            api_client.create_premium_refund(
                latched["id"],
                premium_refund_payload("SHORT_RATE", latched["version"]),
                ANALYST,
            ),
            "ERR_UP_REFUND_ALREADY_FILED",
            409,
        )

        after = read_policy(latched["id"])
        assert after["up_refund_filed"] is True, after["up_refund_filed"]
        rows, _ = validate_paginated(
            api_client.list_premium_refunds(latched["id"], ANALYST)
        )
        assert len(rows) == 1, f"the list holds either zero rows or one, got {len(rows)}"
        assert rows[0]["computed_refund_cents"] == 604_932, rows[0]["computed_refund_cents"]
        assert rows[0]["refund_method"] == "PRO_RATA", (
            f"the refused election must not replace the filed one, got {rows[0]['refund_method']}"
        )

        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["pending_up_liability_cents"] == 604_932, (
            "the refund exposure is booked exactly once, got "
            f"{insolvency['pending_up_liability_cents']}"
        )


class TestReferralOfferAndAnswerGuards:
    """The asserted basis must point at the target, and an answer is recorded once."""

    def test_a_basis_that_resolves_to_this_state_cannot_export_the_claim(self):
        """`basis` is one of `POLICYHOLDER_RESIDENCE`, `CLAIMANT_RESIDENCE` or `PROPERTY_LOCATION`,
        and the server resolves it into `basis_state_code`: `POLICYHOLDER_RESIDENCE` resolves to the
        parent policy's `policyholder_state_code`, while both `CLAIMANT_RESIDENCE` and
        `PROPERTY_LOCATION` resolve to the claim's `claimant_state_code`. The resolved
        `basis_state_code` must equal `target_state_code`, else the offer is refused with
        `ERR_REFERRAL_BASIS_MISMATCH` — the association will not export a claim to a state that the
        asserted facts do not actually point at.

        Design: Corner/validations/referral_basis_that_resolves_to_another_state_is_refused
        """
        env = setup_claim_under_adjustment(
            claim_overrides=dict(MICHIGAN_CLAIM),
            assignment_overrides=dict(KESTREL_ADJUSTER),
            policy_overrides=dict(LIVE_TERM),
        )
        assert env["claim"]["claimant_state_code"] == "MI", (
            env["claim"]["claimant_state_code"]
        )
        assert env["policy"]["policyholder_state_code"] == "MI", (
            env["policy"]["policyholder_state_code"]
        )

        validate_error(
            api_client.create_referral(
                env["claim"]["id"], referral_payload("OH", "CLAIMANT_RESIDENCE"), ADMIN
            ),
            "ERR_REFERRAL_BASIS_MISMATCH",
            422,
        )

        claim = read_claim(env["claim"]["id"])
        assert claim["status"] == "ADJUSTING", (
            f"the refused offer does not park the claim, got {claim['status']}"
        )
        assert claim["pre_referral_status"] is None
        rows, _ = validate_paginated(
            api_client.list_referrals(env["claim"]["id"], ADMIN)
        )
        assert rows == [], "no referral row may be stored on a mismatched basis"
        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["referral_pending_count"] == 0, (
            insolvency["referral_pending_count"]
        )

    def test_a_declined_referral_cannot_be_answered_again(self):
        """The sister association's answer is recorded by an `AssociationAdmin` as a `disposition` of
        either `ACCEPTED` or `DECLINED`, with an optional `response_note`; the target referral must
        still be `OPEN`, else `ERR_REFERRAL_ALREADY_ANSWERED`.

        On `DECLINED` the claim is restored to whatever `pre_referral_status` holds and
        `pre_referral_status` is then cleared to null: a claim that was parked from adjustment moves
        `REFERRAL_PENDING → ADJUSTING`, and a claim that was parked from screening moves
        `REFERRAL_PENDING → SCREENED_ELIGIBLE`.

        Design: Corner/validations/answering_a_referral_twice_is_refused
        """
        env = setup_claim_under_adjustment(
            claim_overrides=dict(OHIO_CLAIM),
            assignment_overrides=dict(KESTREL_ADJUSTER),
            policy_overrides=dict(LIVE_TERM),
        )
        raise_referral(env, "OH", "CLAIMANT_RESIDENCE")
        declined = respond_to_referral(env, "DECLINED", "no Ohio connecting factor accepted")
        assert_referral(declined)
        assert declined["status"] == "DECLINED", declined["status"]

        validate_error(
            api_client.respond_referral(
                env["claim"]["id"],
                declined["id"],
                referral_response_payload("ACCEPTED"),
                ADMIN,
            ),
            "ERR_REFERRAL_ALREADY_ANSWERED",
            409,
        )

        rows, _ = validate_paginated(
            api_client.list_referrals(env["claim"]["id"], ADMIN)
        )
        assert len(rows) == 1, len(rows)
        assert rows[0]["status"] == "DECLINED", rows[0]["status"]
        assert rows[0]["response_note"] == "no Ohio connecting factor accepted", (
            rows[0]["response_note"]
        )

        claim = read_claim(env["claim"]["id"])
        assert claim["status"] == "ADJUSTING", (
            f"the claim resumed where it left off and stays there, got {claim['status']}"
        )
        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["referral_pending_count"] == 0, (
            "the refused answer must not drive the pending count negative, got "
            f"{insolvency['referral_pending_count']}"
        )

    def test_the_open_referral_is_reported_ahead_of_the_parked_status(self):
        """No sister-association referral on the claim is still `OPEN` →
        `ERR_REFERRAL_ALREADY_OPEN` (HTTP 409), on `POST /claims/{id}/referrals`. This check
        deliberately outranks the claim-state check that follows, so that a claim already parked with
        a sister association reports the open referral rather than its parked status.

        Design: Corner/validations/open_referral_check_outranks_the_claim_state_check
        """
        env = setup_claim_with_open_referral(
            target_state_code="OH",
            basis="CLAIMANT_RESIDENCE",
            claim_overrides=dict(OHIO_CLAIM),
            policy_overrides=dict(LIVE_TERM),
        )
        parked = read_claim(env["claim"]["id"])
        assert parked["status"] == "REFERRAL_PENDING", parked["status"]
        assert env["referral"]["status"] == "OPEN", env["referral"]["status"]
        assert read_insolvency(env["insolvency"]["id"])["referral_pending_count"] == 1

        validate_error(
            api_client.create_referral(
                env["claim"]["id"], referral_payload("OH", "CLAIMANT_RESIDENCE"), ADMIN
            ),
            "ERR_REFERRAL_ALREADY_OPEN",
            409,
        )

        rows, _ = validate_paginated(
            api_client.list_referrals(env["claim"]["id"], ADMIN)
        )
        assert len(rows) == 1, f"the second offer is not stored, got {len(rows)} referrals"
        assert rows[0]["status"] == "OPEN", rows[0]["status"]
        after = read_claim(env["claim"]["id"])
        assert after["status"] == "REFERRAL_PENDING", after["status"]
        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["referral_pending_count"] == 1, (
            f"still exactly one referral in flight, got {insolvency['referral_pending_count']}"
        )
