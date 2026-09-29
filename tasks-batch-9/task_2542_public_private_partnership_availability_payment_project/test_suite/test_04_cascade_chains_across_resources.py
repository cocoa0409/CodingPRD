"""Cascades that cross resource boundaries inside the triggering request."""
from test_helpers import api_client, validate_success
from test_helpers.assertions import (
    assert_ledger_running_balance,
    assert_net_payment_identity,
    assert_reserve_transaction,
)
from test_helpers.factories import adjudicate_dispute_payload
from test_helpers.fixtures import (
    ALPHA,
    BETA,
    LENDER,
    approve_milestone,
    invoice_period,
    list_deduction_events_for_period,
    list_enforcement_rows,
    list_reserve_rows,
    pay_period,
    raise_dispute,
    raise_enforcement_action,
    refresh_concession,
    refresh_service_period,
    request_milestone,
    setup_concession_at_financial_close,
    setup_period_with_breaching_deduction,
)

UPHELD_GROUNDS = "category B failures were caused by an authority-side power outage"


def _paid_period_under_step_in_with_open_dispute():
    """A paid period whose only deduction is disputed, with a live step-in on top."""
    ctx = setup_period_with_breaching_deduction()
    invoice_period(ctx)
    pay_period(ctx, "BACS-2027-04-0001")
    raise_enforcement_action(ctx, "STEP_IN", "PERSISTENT_BREACH", "2027-04-02", LENDER)
    raise_dispute(ctx, ctx["deduction_events"][0]["id"], UPHELD_GROUNDS)
    return ctx


class TestUpheldDisputeCascade:
    def test_upholding_zeroes_the_dispute_and_overturns_the_deduction(self):
        """The first two links: the dispute is UPHELD and the event OVERTURNED.

        PRD: "The dispute lands in `UPHELD` and the deduction event lands in
        `OVERTURNED` — note that the two rows use different words for the same
        outcome — with `allowed_amount_cents` and `pro_rata_amount_cents` both set to
        zero, so the event leaves the allocation input set."

        Design: Difficulty/transitive_cascade/dispute_upheld_cascade_reaches_the_concessionaire_at_depth_five
        """
        ctx = _paid_period_under_step_in_with_open_dispute()
        event_id = ctx["deduction_events"][0]["id"]

        response = api_client.adjudicate_deduction_dispute(
            ctx["dispute"]["id"],
            adjudicate_dispute_payload(
                "UPHOLD", "authority-side outage accepted; deduction overturned in full"
            ),
            BETA,
        )

        dispute = validate_success(response)
        assert dispute["status"] == "UPHELD"
        assert dispute["adjudicated_by_user_id"] == "officer-beta"
        event = validate_success(api_client.get_deduction_event(event_id, ALPHA))
        assert event["status"] == "OVERTURNED"
        assert event["allowed_amount_cents"] == 0
        assert event["pro_rata_amount_cents"] == 0
        assert event["points"] == 600

    def test_the_re_priced_period_moves_from_paid_to_adjusted(self):
        """The third link re-prices the period and marks the payment already made.

        PRD: "The owning period then re-runs its allocation, its relief credit and
        its net payment in that pinned order, and a period that had already been paid
        moves `PAID → ADJUSTED` because the sum it was paid is no longer the sum the
        contract prescribes."

        Design: Difficulty/transitive_cascade/dispute_upheld_cascade_reaches_the_concessionaire_at_depth_five
        """
        ctx = _paid_period_under_step_in_with_open_dispute()
        net_before = refresh_service_period(ctx)["net_payment_cents"]

        api_client.adjudicate_deduction_dispute(
            ctx["dispute"]["id"],
            adjudicate_dispute_payload(
                "UPHOLD", "authority-side outage accepted; deduction overturned in full"
            ),
            BETA,
        )

        period = refresh_service_period(ctx)
        assert period["total_deduction_cents"] == 0
        assert period["relief_credit_cents"] == 0
        assert period["net_payment_cents"] == 8604167
        assert period["net_payment_cents"] - net_before == 750000
        assert period["payment_status"] == "ADJUSTED"
        assert period["reporting_status"] == "VERIFIED"
        assert_net_payment_identity(period)

    def test_clearing_the_breach_cures_the_step_in_and_reaches_the_sponsor_vehicle(self):
        """The fourth and fifth links: concession totals, then the automatic cure.

        PRD: "And if that recomputation flips `persistent_breach_flag` from true to
        false, an enforcement action of `trigger_reason` `PERSISTENT_BREACH` that is
        sitting in `STEP_IN_ACTIVE` is cured in the same request: it moves
        `STEP_IN_ACTIVE → CURED` with `cure_note` set to `PERSISTENT_BREACH_CLEARED`
        and `cured_at` stamped, the concession returns `STEP_IN → OPERATIONS`, and the
        sponsor vehicle returns `STEPPED_IN → ACTIVE`."

        Design: Difficulty/transitive_cascade/dispute_upheld_cascade_reaches_the_concessionaire_at_depth_five
        """
        ctx = _paid_period_under_step_in_with_open_dispute()
        assert refresh_concession(ctx)["persistent_breach_flag"] is True

        api_client.adjudicate_deduction_dispute(
            ctx["dispute"]["id"],
            adjudicate_dispute_payload(
                "UPHOLD", "authority-side outage accepted; deduction overturned in full"
            ),
            BETA,
        )

        concession = refresh_concession(ctx)
        assert concession["availability_deduction_ytd_cents"] == 0
        assert concession["deduction_points_ytd"] == 0
        assert concession["persistent_breach_flag"] is False
        assert concession["status"] == "OPERATIONS"
        actions, _ = list_enforcement_rows(ctx["concession_id"])
        assert actions[0]["status"] == "CURED"
        assert actions[0]["cure_note"] == "PERSISTENT_BREACH_CLEARED"
        sponsor = validate_success(
            api_client.get_concessionaire(ctx["concessionaire_id"], ALPHA)
        )
        assert sponsor["status"] == "ACTIVE"
        events, events_meta = list_deduction_events_for_period(ctx["service_period_id"])
        assert events_meta["total_count"] == 1
        _, reserve_meta = list_reserve_rows(ctx["concession_id"])
        assert reserve_meta["total_count"] == 1


class TestDisbursementCascadeSeedsTheReserve:
    def test_disbursement_moves_both_drawn_totals_on_the_concession(self):
        """The first link of the funding cascade credits equity and debt separately.

        PRD: "The concession's `equity_drawn_cents` then rises by this milestone's
        equity portion and its `senior_debt_drawn_cents` by its debt portion."

        Design: Difficulty/transitive_cascade/milestone_disbursement_cascade_seeds_the_reserve_at_depth_four
        """
        ctx = setup_concession_at_financial_close()
        milestone = request_milestone(ctx, "M1 Design Complete", 120000000)
        approve_milestone(ctx, milestone["id"], 120000000)

        response = api_client.disburse_drawdown_milestone(milestone["id"], LENDER)

        disbursed = validate_success(response)
        assert disbursed["status"] == "DISBURSED"
        assert disbursed["disbursed_at"].startswith("2026-09-01T00:00:00")
        concession = refresh_concession(ctx)
        assert concession["equity_drawn_cents"] == 100000000
        assert concession["senior_debt_drawn_cents"] == 20000000
        assert (
            concession["equity_drawn_cents"] + concession["senior_debt_drawn_cents"]
            == 120000000
        )

    def test_crossing_the_threshold_starts_construction_and_appends_the_seed_entry(self):
        """The remaining links: the ratio, the auto-transition and the seeded ledger.

        PRD: "Firing it seeds the lifecycle reserve: one ledger entry is appended
        with `txn_type` of `CONTRIBUTION`, `created_by_role` of `SYSTEM`, a `reason`
        of `CONSTRUCTION_SEED` and an `amount_cents` equal to two per cent of the
        certified total project cost rounded half up to a whole cent; the concession's
        `lifecycle_reserve_balance_cents` is then set to that new entry's
        `resulting_balance_cents`."

        Design: Difficulty/transitive_cascade/milestone_disbursement_cascade_seeds_the_reserve_at_depth_four
        """
        ctx = setup_concession_at_financial_close()
        milestone = request_milestone(ctx, "M1 Design Complete", 120000000)
        approve_milestone(ctx, milestone["id"], 120000000)

        api_client.disburse_drawdown_milestone(milestone["id"], LENDER)

        concession = refresh_concession(ctx)
        assert concession["cumulative_drawn_pct"] == 0.3
        assert concession["status"] == "CONSTRUCTION"
        rows, meta = list_reserve_rows(ctx["concession_id"])
        assert meta["total_count"] == 1
        seed = rows[0]
        assert_reserve_transaction(seed)
        assert seed["sequence_no"] == 1
        assert seed["txn_type"] == "CONTRIBUTION"
        assert seed["reason"] == "CONSTRUCTION_SEED"
        assert seed["created_by_role"] == "SYSTEM"
        assert seed["amount_cents"] == 8000000
        assert seed["signed_amount_cents"] == 8000000
        assert seed["resulting_balance_cents"] == 8000000
        assert_ledger_running_balance(rows)
        assert concession["lifecycle_reserve_balance_cents"] == 8000000
