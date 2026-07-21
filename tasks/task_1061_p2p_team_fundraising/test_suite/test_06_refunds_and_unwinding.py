"""Refunds: reversing the match, unwinding credit and revoking incentives."""

from test_helpers import (
    ApiErrorId,
    assert_pool_cents_conserved,
    make_platform_admin_headers,
    refund_gift,
    set_clock,
    setup_campaign_with_balance,
    setup_exhausted_pool_with_settled_gift,
    setup_two_tier_participant_with_awards,
    request_payout,
    validate_error,
    validate_success,
)

ADMIN = make_platform_admin_headers()


def test_refunding_a_matched_gift_reverses_its_match_dimension(api, anonymous_headers):
    """PRD §3.7: "Step 1: when the gift's match dimension reads `MATCHED`, it
    transitions `MATCHED → REVERSED`. Step 2: that reversal returns the reversed
    `matched_amount_cents` to the pool's `remaining_cents` and sets the gift's
    `matched_amount_cents` to 0."

    Design: Difficulty/transitive_cascade/refund_reverses_match_restores_pool_and_reactivates_exhausted_pool
    """
    ctx = setup_exhausted_pool_with_settled_gift(api=api)

    refunded = validate_success(
        api.refund_donation(ctx["donation_id"], {"reason": "donor requested"}, ADMIN)
    )

    assert refunded["payment_status"] == "REFUNDED"
    assert refunded["match_status"] == "REVERSED"
    assert refunded["matched_amount_cents"] == 0


def test_the_restored_cents_reactivate_the_exhausted_pool(api, anonymous_headers):
    """PRD §3.7: "Step 3: a pool that had been driven to `EXHAUSTED` and now holds a
    positive `remaining_cents` transitions `EXHAUSTED → ACTIVE` and re-enters the
    candidate set for future settlements."
    PRD §3.7: "Step 1: the credited totals are recomputed downward — the designated
    fundraiser's `credited_cents` and `projected_cents`, the relevant team's
    `credited_cents`, and the campaign's `raised_credited_cents`, `lifetime_net_cents`,
    `available_balance_cents` and `donor_count`."

    Design: Difficulty/transitive_cascade/refund_reverses_match_restores_pool_and_reactivates_exhausted_pool
    """
    ctx = setup_exhausted_pool_with_settled_gift(api=api)
    exhausted = validate_success(api.get_match_pool(ctx["pool_id"], ctx["cm_headers"]))
    assert exhausted["status"] == "EXHAUSTED" and exhausted["remaining_cents"] == 0

    refund_gift(ctx["donation_id"], api=api)

    pool = validate_success(api.get_match_pool(ctx["pool_id"], ctx["cm_headers"]))
    assert pool["remaining_cents"] == 5000
    assert pool["status"] == "ACTIVE"
    page = validate_success(api.get_participant(ctx["participant_id"], anonymous_headers))
    assert page["credited_cents"] == 0, "Credit is recomputed downward"


def test_pool_cents_are_conserved_after_the_compensating_refund(api):
    """PRD §2.11: "A sponsor pool's `remaining_cents` is its `pool_amount_cents` less
    its `allocated_cents`, and never goes below zero."
    PRD §3.7: "Step 2: that reversal returns the reversed `matched_amount_cents` to the
    pool's `remaining_cents` and sets the gift's `matched_amount_cents` to 0."

    Design: Difficulty/compensating_invariant/sponsor_pool_cents_conserved_across_match_and_refund_reversal
    """
    ctx = setup_exhausted_pool_with_settled_gift(api=api)

    refund_gift(ctx["donation_id"], api=api, reason="card dispute")

    pool = validate_success(api.get_match_pool(ctx["pool_id"], ctx["cm_headers"]))
    assert pool["allocated_cents"] == 0
    assert pool["remaining_cents"] == 5000
    assert pool["status"] == "ACTIVE"


def test_allocated_and_remaining_always_add_back_to_the_pool_amount(api):
    """PRD §2.11: "A sponsor pool's `remaining_cents` is its `pool_amount_cents` less
    its `allocated_cents`, and never goes below zero."
    PRD §3.5: "the pool's `allocated_cents` rises by the matched amount and its
    `remaining_cents` becomes `pool_amount_cents` less `allocated_cents`"

    Design: Difficulty/compensating_invariant/sponsor_pool_cents_conserved_across_match_and_refund_reversal
    """
    ctx = setup_exhausted_pool_with_settled_gift(api=api)
    after_match = validate_success(api.get_match_pool(ctx["pool_id"], ctx["cm_headers"]))
    assert_pool_cents_conserved(after_match)
    assert after_match["allocated_cents"] == 5000

    refund_gift(ctx["donation_id"], api=api)

    after_refund = validate_success(api.get_match_pool(ctx["pool_id"], ctx["cm_headers"]))
    assert_pool_cents_conserved(after_refund)
    assert after_refund["pool_amount_cents"] == 5000


def test_a_fulfilled_award_survives_the_revocation_cascade(api):
    """PRD §3.7: "Step 2: every incentive award of that fundraiser sitting in `EARNED`
    whose tier's `threshold_cents` now exceeds the recomputed `credited_cents`
    transitions `EARNED → REVOKED` and has `revoked_at` stamped. Awards already in
    `FULFILLED` are left untouched, and awards already `REVOKED` stay revoked."
    PRD §3.6: "Fulfilment stamps `fulfilled_at` and, importantly, makes the award
    permanently immune to the revocation cascade described next."

    Design: Corner/state_machines/incentive_award_fulfilled_survives_refund_revocation_cascade
    """
    ctx = setup_two_tier_participant_with_awards(api=api)
    validate_success(
        api.fulfill_incentive_award(ctx["award_bronze_id"], ctx["cm_headers"])
    )

    refunded = refund_gift(ctx["donation_big_id"], api=api)

    assert refunded["payment_status"] == "REFUNDED"
    gold = validate_success(
        api.get_incentive_award(ctx["award_gold_id"], ctx["cm_headers"])
    )
    assert gold["status"] == "REVOKED", "The 15000-cent tier is no longer met"
    bronze = validate_success(
        api.get_incentive_award(ctx["award_bronze_id"], ctx["cm_headers"])
    )
    assert bronze["status"] == "FULFILLED", "A fulfilled award is immune"
    page = validate_success(api.get_participant(ctx["participant_id"], ctx["cm_headers"]))
    assert page["credited_cents"] == 5000


def test_a_refund_past_the_sixty_day_window_is_rejected(api):
    """PRD §3.7: "The current logical-clock instant must be at or before the gift's
    `settled_at` plus a refund window of 60 days; the boundary instant itself is still
    refundable, and anything later is rejected with `ERR_REFUND_WINDOW_EXPIRED`."

    Design: Corner/validations/refund_after_sixty_day_window_rejected
    """
    ctx = setup_campaign_with_balance(api=api, amount_cents=10000)
    set_clock("2026-08-31T00:00:00Z", api=api)

    response = api.refund_donation(
        ctx["donation_id"], {"reason": "late request"}, ADMIN
    )

    validate_error(
        response, ApiErrorId.ERR_REFUND_WINDOW_EXPIRED.value, expected_status=422
    )
    gift = validate_success(api.get_donation(ctx["donation_id"], ctx["cm_headers"]))
    assert gift["payment_status"] == "SETTLED"
    campaign = validate_success(api.get_campaign(ctx["campaign_id"], ctx["cm_headers"]))
    assert campaign["available_balance_cents"] == 9180


def test_a_refund_that_would_overdraw_the_campaign_is_rejected(api):
    """PRD §3.7: "Finally, the campaign's `available_balance_cents` must be greater
    than or equal to the gift's `net_cents` added to its `matched_amount_cents` — a
    campaign that has already reserved or disbursed the money cannot give it back, and
    the attempt is rejected with `ERR_INSUFFICIENT_CAMPAIGN_BALANCE`."

    Design: Corner/validations/refund_that_would_overdraw_campaign_balance_rejected
    """
    ctx = setup_campaign_with_balance(api=api, amount_cents=100000)
    request_payout(ctx["campaign_id"], ctx["cm_headers"], 92070, api=api)

    response = api.refund_donation(
        ctx["donation_id"], {"reason": "donor requested"}, ADMIN
    )

    validate_error(
        response, ApiErrorId.ERR_INSUFFICIENT_CAMPAIGN_BALANCE.value, expected_status=422
    )
    gift = validate_success(api.get_donation(ctx["donation_id"], ctx["cm_headers"]))
    assert gift["payment_status"] == "SETTLED"
    campaign = validate_success(api.get_campaign(ctx["campaign_id"], ctx["cm_headers"]))
    assert campaign["available_balance_cents"] == 0
    assert campaign["reserved_payout_cents"] == 92070


def test_an_already_refunded_gift_reports_the_state_problem_not_the_window(api):
    """PRD §2.8: "A refund request against a gift that was never settled surfaces as
    `ERR_DONATION_NOT_REFUNDABLE` rather than as a window or balance complaint, because
    state admissibility runs before any window arithmetic."
    PRD §3.7: "The gift's payment dimension must read `SETTLED`; a gift that is
    `PENDING`, `FAILED` or already `REFUNDED` is rejected with
    `ERR_DONATION_NOT_REFUNDABLE` before any window arithmetic runs at all."

    Design: Difficulty/priority_pair_validation_conflict/refund_state_beats_expired_window_priority_conflict
    """
    ctx = setup_campaign_with_balance(api=api, amount_cents=10000)
    refund_gift(ctx["donation_id"], api=api, reason="first refund")
    set_clock("2026-10-01T00:00:00Z", api=api)

    response = api.refund_donation(
        ctx["donation_id"], {"reason": "second refund attempt"}, ADMIN
    )

    validate_error(
        response, ApiErrorId.ERR_DONATION_NOT_REFUNDABLE.value, expected_status=409
    )


def test_the_doubly_invalid_refund_leaves_the_gift_refunded(api):
    """PRD §3.7: "Both `REFUNDED` and `FAILED` are terminal for the payment dimension:
    a refunded gift can never be settled again."
    PRD §2.8: "6. **State admissibility** — the target is in a state that admits the
    requested transition, otherwise `ERR_INVALID_STATE` (HTTP 409), except on the
    refund path where the dedicated code `ERR_DONATION_NOT_REFUNDABLE` (HTTP 409) is
    returned instead."

    Design: Difficulty/priority_pair_validation_conflict/refund_state_beats_expired_window_priority_conflict
    """
    ctx = setup_campaign_with_balance(api=api, amount_cents=10000)
    refund_gift(ctx["donation_id"], api=api, reason="first refund")
    set_clock("2026-10-01T00:00:00Z", api=api)

    rejected = api.refund_donation(
        ctx["donation_id"], {"reason": "second refund attempt"}, ADMIN
    )
    validate_error(
        rejected, ApiErrorId.ERR_DONATION_NOT_REFUNDABLE.value, expected_status=409
    )

    gift = validate_success(api.get_donation(ctx["donation_id"], ctx["cm_headers"]))
    assert gift["payment_status"] == "REFUNDED", "The rejected retry changes nothing"
