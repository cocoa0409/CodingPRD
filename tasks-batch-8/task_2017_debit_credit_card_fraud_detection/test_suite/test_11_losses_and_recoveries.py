"""Loss booking/finalization, recovery filings, rolling-loss window, tier
boundaries, INV-LOSS compensating pair, recovery cascade."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_card,
    create_active_ruleset,
    post_txn,
    set_clock,
    get_success_data,
    setup_confirmed_fraud_txn,
    create_booked_loss,
    create_finalized_loss,
    create_accepted_filing,
    create_manual_alert,
    claim_alert,
    create_and_complete_contact,
    resolve_alert,
    make_accountant_headers,
    make_recovery_headers,
    USER_ACCOUNTANT_1,
)

MANAGER = TEST_USERS["manager_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]
RECOVERY = TEST_USERS["recovery_headers"]


def test_loss_requires_confirmed_fraud_rejected(api):
    """PRD §3.8: "Every listed transaction must belong to the given account and
    carry `final_disposition` equal to `CONFIRMED_FRAUD`, else
    `ERR_LOSS_TXN_NOT_CONFIRMED` (HTTP 422)".

    Design: Corner/errors/loss_requires_confirmed_fraud_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    acct = create_account("ACCT-ER3", cardholder_name="Err Three")
    card = create_card(acct["id"], "PT-ER3")
    create_active_ruleset()
    txn = post_txn(card["id"], 10001, "M-ER3", channel="CNP", origin_country="US")
    assert txn["final_disposition"] == "UNDISPOSED"
    resp = api.create_loss_entry(
        {"account_id": acct["id"], "transaction_ids": [txn["id"]]}, ACCOUNTANT
    )
    validate_error(resp, ApiErrorId.ERR_LOSS_TXN_NOT_CONFIRMED, expected_status=422)


def test_txn_in_second_loss_rejected(api):
    """PRD §3.8: "each transaction may appear in at most one non-terminal loss
    entry, else `ERR_TXN_ALREADY_IN_LOSS`."

    Design: Corner/validations/txn_in_second_loss_rejected
    """
    setup = setup_confirmed_fraud_txn("ACCT-V12", "PT-V12", 10001, "M-V12")
    acct, txn = setup["account"], setup["txn"]
    get_success_data(
        api.create_loss_entry(
            {"account_id": acct["id"], "transaction_ids": [txn["id"]]}, ACCOUNTANT
        ),
        expected_status=201,
    )
    resp = api.create_loss_entry(
        {"account_id": acct["id"], "transaction_ids": [txn["id"]]}, ACCOUNTANT
    )
    validate_error(resp, ApiErrorId.ERR_TXN_ALREADY_IN_LOSS, expected_status=409)


class TestLossProvisionEstimateVsFinalBooked:
    def _setup_two_network_loss(self, api):
        """One VISA txn of 10001 and one MASTERCARD txn of 10001, both confirmed
        FRAUD via manual alerts (contacts 60+ minutes apart)."""
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-LP1", cardholder_name="Lo Pro")
        card_v = create_card(acct["id"], "PT-LP1", product_type="CREDIT", network="VISA")
        card_m = create_card(acct["id"], "PT-LP2", product_type="DEBIT", network="MASTERCARD")
        create_active_ruleset()
        t1 = post_txn(card_v["id"], 10001, "M-LP", channel="CNP", origin_country="US")
        t2 = post_txn(card_m["id"], 10001, "M-LP", channel="CNP", origin_country="US")
        a1 = create_manual_alert(acct["id"], card_v["id"], auth_transaction_id=t1["id"])
        claim_alert(a1["id"])
        create_and_complete_contact(a1["id"], "CONFIRMED_FRAUD")
        resolve_alert(a1["id"], "FRAUD")
        set_clock("2026-08-01T01:01:00Z")
        a2 = create_manual_alert(acct["id"], card_m["id"], auth_transaction_id=t2["id"])
        claim_alert(a2["id"])
        create_and_complete_contact(a2["id"], "CONFIRMED_FRAUD", channel="SMS")
        resolve_alert(a2["id"], "FRAUD")
        return acct, t1, t2

    def test_provisional_estimate_uses_per_network_rates(self, api):
        """PRD §2.8: "a VISA line of 10001 cents contributes round-half-up of
        5500.55, i.e. 5501, and a MASTERCARD line of 10001 cents contributes
        round-half-up of 6000.60, i.e. 6001, totalling 11502"; §3.8: "The
        `tolerance_cents` is the provisional amount multiplied by ten percent,
        rounded half up."

        Design: Difficulty/dual_variant_calc/loss_provision_estimate_vs_final_booked
        """
        acct, t1, t2 = self._setup_two_network_loss(api)
        loss = get_success_data(
            api.create_loss_entry(
                {"account_id": acct["id"], "transaction_ids": [t1["id"], t2["id"]]}, ACCOUNTANT
            ),
            expected_status=201,
        )
        assert loss["provisional_amount_cents"] == 11502, (
            f"round(10001*0.55)=5501 + round(10001*0.60)=6001; got {loss['provisional_amount_cents']}"
        )
        assert loss["tolerance_cents"] == 1150, (
            f"round_half_up(11502*0.10) = 1150; got {loss['tolerance_cents']}"
        )

    def test_final_booked_differs_from_provisional_estimate(self, api):
        """PRD §3.8: "Finalization stamps `final_amount_cents` and `finalized_at`,
        sets `outstanding_cents` to the final amount"; the accountant-supplied
        final amount "must lie within the inclusive tolerance band centered on
        `provisional_amount_cents`".

        Design: Difficulty/dual_variant_calc/loss_provision_estimate_vs_final_booked
        """
        acct, t1, t2 = self._setup_two_network_loss(api)
        loss = get_success_data(
            api.create_loss_entry(
                {"account_id": acct["id"], "transaction_ids": [t1["id"], t2["id"]]}, ACCOUNTANT
            ),
            expected_status=201,
        )
        booked = get_success_data(api.book_loss_entry(loss["id"], make_accountant_headers(USER_ACCOUNTANT_1)))
        finalized = validate_success(
            api.finalize_loss_entry(
                loss["id"], {"final_amount_cents": 11000}, make_accountant_headers(USER_ACCOUNTANT_1)
            )
        )
        assert finalized["loss_status"] == "FINALIZED"
        assert finalized["final_amount_cents"] == 11000
        assert finalized["provisional_amount_cents"] == 11502
        assert finalized["final_amount_cents"] != finalized["provisional_amount_cents"]


class TestLossProvisionLineRoundingOrder:
    def test_per_line_rounding_then_sum(self, api):
        """PRD §2.8: "each transaction line is individually rounded **half up** to
        whole cents after applying the network recovery haircut, and only then are
        the per-line results summed. The alternative order (sum first, round once)
        is forbidden, because the two orders diverge by a cent on realistic
        inputs".

        Design: Difficulty/combinatorial_formula/loss_provision_line_rounding_order
        """
        loss = self._create_two_line_loss(api)
        assert loss["provisional_amount_cents"] == 23002, (
            f"per-line round(20001*0.55)=11001 + round(20001*0.60)=12001 -> 23002; "
            f"sum-then-round would give 23001; got {loss['provisional_amount_cents']}"
        )
        assert loss["provisional_amount_cents"] != 23001

    def test_tolerance_rounded_half_up_from_provisional(self, api):
        """PRD §3.8: "The `tolerance_cents` is the provisional amount multiplied by
        ten percent, rounded half up."; §2.8: "Where a percentage must produce a
        cent value (the finalize tolerance, and the false-positive rates in basis
        points), rounding is again half up to the nearest integer."

        Design: Difficulty/combinatorial_formula/loss_provision_line_rounding_order
        """
        loss = self._create_two_line_loss(api)
        assert loss["provisional_amount_cents"] == 23002
        assert loss["tolerance_cents"] == 2300, (
            f"round_half_up(23002*0.10) = round(2300.2) = 2300; got {loss['tolerance_cents']}"
        )

    def _create_two_line_loss(self, api):
        """Two confirmed-FRAUD txns (VISA 20001, MASTERCARD 20001) -> one loss."""
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-CF2", cardholder_name="Round Order")
        card_v = create_card(acct["id"], "PT-CF2V", product_type="CREDIT", network="VISA")
        card_m = create_card(acct["id"], "PT-CF2M", product_type="DEBIT", network="MASTERCARD")
        create_active_ruleset()
        u1 = post_txn(card_v["id"], 20001, "M-RO", channel="CNP", origin_country="US")
        u2 = post_txn(card_m["id"], 20001, "M-RO", channel="CNP", origin_country="US")
        a1 = create_manual_alert(acct["id"], card_v["id"], auth_transaction_id=u1["id"])
        claim_alert(a1["id"])
        create_and_complete_contact(a1["id"], "CONFIRMED_FRAUD")
        resolve_alert(a1["id"], "FRAUD")
        set_clock("2026-08-01T01:01:00Z")
        a2 = create_manual_alert(acct["id"], card_m["id"], auth_transaction_id=u2["id"])
        claim_alert(a2["id"])
        create_and_complete_contact(a2["id"], "CONFIRMED_FRAUD", channel="SMS")
        resolve_alert(a2["id"], "FRAUD")
        return get_success_data(
            api.create_loss_entry(
                {"account_id": acct["id"], "transaction_ids": [u1["id"], u2["id"]]}, ACCOUNTANT
            ),
            expected_status=201,
        )


class TestFinalizeToleranceInclusiveBoundary:
    def _setup_booked_loss(self, api):
        setup = setup_confirmed_fraud_txn("ACCT-V10", "PT-V10", 10001, "M-V10")
        acct, txn = setup["account"], setup["txn"]
        loss = create_booked_loss(acct["id"], [txn["id"]])
        assert loss["provisional_amount_cents"] == 5501
        assert loss["tolerance_cents"] == 550
        return acct, txn, loss

    def test_exactly_tolerance_passes(self, api):
        """PRD §3.8: "the accountant-supplied `final_amount_cents` must lie within
        the inclusive tolerance band centered on `provisional_amount_cents` — the
        absolute difference must not exceed `tolerance_cents`, and a difference of
        exactly `tolerance_cents` passes".

        Design: Corner/validations/finalize_tolerance_inclusive_boundary
        """
        _acct, _txn, loss = self._setup_booked_loss(api)
        finalized = validate_success(
            api.finalize_loss_entry(
                loss["id"], {"final_amount_cents": 4951}, make_accountant_headers(USER_ACCOUNTANT_1)
            )
        )
        assert finalized["loss_status"] == "FINALIZED"
        assert finalized["outstanding_cents"] == 4951

    def test_one_cent_beyond_tolerance_fails_and_remains_booked(self, api):
        """PRD §3.8: "the absolute difference must not exceed `tolerance_cents`,
        and a difference of exactly `tolerance_cents` passes — else
        `ERR_FINAL_AMOUNT_TOLERANCE` (HTTP 422)."

        Design: Corner/validations/finalize_tolerance_inclusive_boundary
        """
        _acct, _txn, loss = self._setup_booked_loss(api)
        resp = api.finalize_loss_entry(
            loss["id"], {"final_amount_cents": 4950}, make_accountant_headers(USER_ACCOUNTANT_1)
        )
        validate_error(resp, ApiErrorId.ERR_FINAL_AMOUNT_TOLERANCE, expected_status=422)
        current = validate_success(api.get_loss_entry(loss["id"], ACCOUNTANT))
        assert current["loss_status"] == "BOOKED"


class TestTemporalBeatsFiscalOnFinalize:
    def _setup_expired_window(self, api):
        setup = setup_confirmed_fraud_txn("ACCT-PP3", "PT-PP3", 10001, "M-PP3")
        acct, txn = setup["account"], setup["txn"]
        loss = create_booked_loss(acct["id"], [txn["id"]])
        assert loss["provisional_amount_cents"] == 5501
        assert loss["tolerance_cents"] == 550
        set_clock("2026-09-05T00:00:00Z")
        return acct, loss

    def test_temporal_error_reported_not_fiscal(self, api):
        """PRD §3.8: "the logical clock must not have passed `booked_at` plus 30
        days — the temporal check, evaluated before the fiscal one, failing with
        `ERR_FINALIZE_WINDOW_EXPIRED`".

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_finalize
        """
        _acct, loss = self._setup_expired_window(api)
        resp = api.finalize_loss_entry(
            loss["id"], {"final_amount_cents": 99999}, make_accountant_headers(USER_ACCOUNTANT_1)
        )
        validate_error(resp, ApiErrorId.ERR_FINALIZE_WINDOW_EXPIRED, expected_status=409)

    def test_failed_finalize_leaves_loss_booked(self, api):
        """PRD §3.8: "Finalization moves it from `BOOKED` to `FINALIZED`" — a
        rejected finalize performs no transition, so the entry stays `BOOKED`.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_finalize
        """
        _acct, loss = self._setup_expired_window(api)
        api.finalize_loss_entry(
            loss["id"], {"final_amount_cents": 99999}, make_accountant_headers(USER_ACCOUNTANT_1)
        )
        current = validate_success(api.get_loss_entry(loss["id"], ACCOUNTANT))
        assert current["loss_status"] == "BOOKED"


class TestLossFinalizeBlockedByOpenChargeback:
    def _setup(self, api):
        """Confirmed-FRAUD txn 50000; chargeback posted 10000; loss created (27500)
        and booked."""
        set_clock("2026-08-01T00:00:00Z")
        setup = setup_confirmed_fraud_txn("ACCT-CE3", "PT-CE3", 50000, "M-CE3", clock="2026-08-01T00:00:00Z")
        acct, txn = setup["account"], setup["txn"]
        cb = get_success_data(
            api.create_chargeback_case(
                {"auth_transaction_id": txn["id"], "reason_code": "4855", "provisional_credit_cents": 10000},
                RECOVERY,
            ),
            expected_status=201,
        )
        get_success_data(api.post_provisional_credit(cb["id"], RECOVERY))
        loss = create_booked_loss(acct["id"], [txn["id"]])
        assert loss["provisional_amount_cents"] == 27500
        assert loss["tolerance_cents"] == 2750
        return acct, txn, cb, loss

    def test_finalize_rejected_while_chargeback_open(self, api):
        """PRD §3.8: "no covered transaction may have a chargeback in `FILED`,
        `PROVISIONAL_CREDIT_POSTED`, or `REPRESENTMENT_FILED`, else
        `ERR_CHARGEBACK_PENDING`".

        Design: Difficulty/cross_entity_state_dependency/loss_finalize_blocked_by_open_chargeback
        """
        _acct, _txn, _cb, loss = self._setup(api)
        resp = api.finalize_loss_entry(
            loss["id"], {"final_amount_cents": 27500}, make_accountant_headers(USER_ACCOUNTANT_1)
        )
        validate_error(resp, ApiErrorId.ERR_CHARGEBACK_PENDING, expected_status=409)

    def test_finalize_succeeds_after_chargeback_terminal(self, api):
        """PRD §3.8: "no covered transaction may have a chargeback in `FILED`,
        `PROVISIONAL_CREDIT_POSTED`, or `REPRESENTMENT_FILED`"; `RESOLVED_LOST` is
        terminal (§3.7), so it lifts the block. "Finalization stamps
        `final_amount_cents` and `finalized_at`, sets `outstanding_cents` to the
        final amount".

        Design: Difficulty/cross_entity_state_dependency/loss_finalize_blocked_by_open_chargeback
        """
        _acct, _txn, cb, loss = self._setup(api)
        api.finalize_loss_entry(
            loss["id"], {"final_amount_cents": 27500}, make_accountant_headers(USER_ACCOUNTANT_1)
        )
        validate_success(api.resolve_chargeback_case(cb["id"], {"outcome": "LOST"}, RECOVERY))
        finalized = validate_success(
            api.finalize_loss_entry(
                loss["id"], {"final_amount_cents": 27500}, make_accountant_headers(USER_ACCOUNTANT_1)
            )
        )
        assert finalized["loss_status"] == "FINALIZED"
        assert finalized["final_amount_cents"] == 27500
        assert finalized["outstanding_cents"] == 27500


def test_recovery_filing_by_loss_booker_rejected(api):
    """PRD §2.10: "the `RecoverySpecialist` who files a network recovery against a
    loss must not be the `LossAccountant` who booked that loss — the filer's
    `X-User-ID` (stamped as `filed_by_user_id`) must differ from the loss's
    `booked_by_user_id`, and a match is again rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/recovery_filing_by_loss_booker_rejected
    """
    setup = setup_confirmed_fraud_txn("ACCT-V7", "PT-V7", 10001, "M-V7")
    acct, txn = setup["account"], setup["txn"]
    loss = create_finalized_loss(acct["id"], [txn["id"]], 5500)

    bad = api.create_recovery_filing(
        {"loss_entry_id": loss["id"], "network_reference": "NR-V7A", "claimed_cents": 5500},
        make_recovery_headers("acct-1"),
    )
    validate_error(bad, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    good = validate_success(
        api.create_recovery_filing(
            {"loss_entry_id": loss["id"], "network_reference": "NR-V7B", "claimed_cents": 5500},
            make_recovery_headers("rec-1"),
        ),
        expected_status=201,
    )
    assert good["filing_status"] == "FILED"


def test_recovery_paid_before_accepted_rejected(api):
    """PRD §3.8: "marking `PAID` directly from `FILED` is `ERR_INVALID_STATE`".

    Design: Corner/state_machines/recovery_paid_before_accepted_rejected
    """
    setup = setup_confirmed_fraud_txn("ACCT-SM7", "PT-SM7", 200000, "M-SM7")
    acct, txn = setup["account"], setup["txn"]
    loss = create_finalized_loss(acct["id"], [txn["id"]], 110000)
    filing = get_success_data(
        api.create_recovery_filing(
            {"loss_entry_id": loss["id"], "network_reference": "NR-SM7", "claimed_cents": 110000},
            make_recovery_headers("rec-1"),
        ),
        expected_status=201,
    )
    resp = api.mark_filing_outcome(filing["id"], {"outcome": "PAID", "paid_cents": 110000}, RECOVERY)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    current = validate_success(api.get_recovery_filing(filing["id"], RECOVERY))
    assert current["filing_status"] == "FILED"
    loss_after = validate_success(api.get_loss_entry(loss["id"], ACCOUNTANT))
    assert loss_after["outstanding_cents"] == 110000


def test_recovery_paid_exceeds_outstanding_rejected(api):
    """PRD §3.8: "from `ACCEPTED` to `PAID`, which requires `paid_cents` present and
    at least 1, no more than `claimed_cents`, and no more than the loss's current
    `outstanding_cents` (violations of either bound are
    `ERR_RECOVERY_EXCEEDS_OUTSTANDING` ...)".

    Design: Corner/validations/recovery_paid_exceeds_outstanding_rejected
    """
    setup = setup_confirmed_fraud_txn("ACCT-V13", "PT-V13", 200000, "M-V13")
    acct, txn = setup["account"], setup["txn"]
    loss = create_finalized_loss(acct["id"], [txn["id"]], 110000)
    filing = create_accepted_filing(loss["id"], 110000, "NR-V13")
    resp = api.mark_filing_outcome(filing["id"], {"outcome": "PAID", "paid_cents": 110001}, RECOVERY)
    validate_error(resp, ApiErrorId.ERR_RECOVERY_EXCEEDS_OUTSTANDING, expected_status=422)
    current = validate_success(api.get_recovery_filing(filing["id"], RECOVERY))
    assert current["filing_status"] == "ACCEPTED"
    loss_after = validate_success(api.get_loss_entry(loss["id"], ACCOUNTANT))
    assert loss_after["outstanding_cents"] == 110000


class TestRecoveryPaidToAccountTierCascade:
    def _setup(self, api):
        """Loss finalized at 110000 (rolling -> HIGH tier); filing claimed 110000,
        ACCEPTED."""
        setup = setup_confirmed_fraud_txn("ACCT-TC4", "PT-TC4", 200000, "M-TC4")
        acct, txn = setup["account"], setup["txn"]
        loss = create_finalized_loss(acct["id"], [txn["id"]], 110000)
        filing = create_accepted_filing(loss["id"], 110000, "NR-TC4")
        return acct, txn, loss, filing

    def test_tier_is_high_before_payment(self, api):
        """PRD §3.1: "the tier is `HIGH` when ... the rolling 90-day confirmed loss
        is at least 100000 cents".

        Design: Difficulty/transitive_cascade/recovery_paid_to_account_tier_cascade
        """
        acct, _txn, _loss, _filing = self._setup(api)
        account = validate_success(api.get_account(acct["id"], MANAGER))
        assert account["risk_tier"] == "HIGH", f"rolling 110000 >= 100000 must force HIGH, got {account['risk_tier']}"

    def test_full_payment_cascades_to_fully_recovered_and_low_tier(self, api):
        """PRD §3.8: "a payment that leaves outstanding at zero moves the loss to
        `FULLY_RECOVERED` (which also drops it from the account's rolling-loss set
        and recomputes the tier)"; §2.11: "`FULLY_RECOVERED` losses are excluded
        from the set."

        Design: Difficulty/transitive_cascade/recovery_paid_to_account_tier_cascade
        """
        acct, _txn, loss, filing = self._setup(api)
        validate_success(api.mark_filing_outcome(filing["id"], {"outcome": "PAID", "paid_cents": 110000}, RECOVERY))
        loss_after = validate_success(api.get_loss_entry(loss["id"], ACCOUNTANT))
        assert loss_after["outstanding_cents"] == 0
        assert loss_after["loss_status"] == "FULLY_RECOVERED"
        account = validate_success(api.get_account(acct["id"], MANAGER))
        assert account["rolling_90d_loss_cents"] == 0
        assert account["risk_tier"] == "LOW"


class TestRecoveryPaidAndReversedConserveOutstanding:
    def _setup(self, api):
        setup = setup_confirmed_fraud_txn("ACCT-CI2", "PT-CI2", 200000, "M-CI2")
        acct, txn = setup["account"], setup["txn"]
        loss = create_finalized_loss(acct["id"], [txn["id"]], 110000)
        filing = create_accepted_filing(loss["id"], 110000, "NR-CI2")
        return acct, loss, filing

    def test_partial_payment_moves_to_partially_recovered(self, api):
        """PRD §3.8: "a partial payment moves a `FINALIZED` loss to
        `PARTIALLY_RECOVERED`"; §2.11: "`outstanding_cents` is the
        `final_amount_cents` minus the sum of `paid_cents` over its recovery
        filings in `PAID` minus `written_off_cents`".

        Design: Difficulty/compensating_invariant/recovery_paid_and_reversed_conserve_outstanding
        """
        _acct, loss, filing = self._setup(api)
        validate_success(api.mark_filing_outcome(filing["id"], {"outcome": "PAID", "paid_cents": 40000}, RECOVERY))
        mid = validate_success(api.get_loss_entry(loss["id"], ACCOUNTANT))
        assert mid["outstanding_cents"] == 70000
        assert mid["loss_status"] == "PARTIALLY_RECOVERED"

    def test_reversal_restores_outstanding_inv_loss(self, api):
        """PRD §2.11: "invariant INV-LOSS states that a filing marked `PAID` and
        later `REVERSED` (a network clawback) leaves `outstanding_cents` unchanged,
        because reversed filings drop out of the paid sum and thereby restore the
        outstanding amount."; §3.8: "outstanding back to the full
        `final_amount_cents` returns the loss to `FINALIZED`".

        Design: Difficulty/compensating_invariant/recovery_paid_and_reversed_conserve_outstanding
        """
        _acct, loss, filing = self._setup(api)
        validate_success(api.mark_filing_outcome(filing["id"], {"outcome": "PAID", "paid_cents": 40000}, RECOVERY))
        reversed_filing = validate_success(
            api.mark_filing_outcome(filing["id"], {"outcome": "REVERSED"}, RECOVERY)
        )
        assert reversed_filing["filing_status"] == "REVERSED"
        end = validate_success(api.get_loss_entry(loss["id"], ACCOUNTANT))
        assert end["outstanding_cents"] == 110000, "INV-LOSS: PAID+REVERSED must conserve outstanding"
        assert end["loss_status"] == "FINALIZED"


class TestRollingLossNinetyDayWindow:
    def _setup_finalized(self, api):
        """Loss finalized at 2026-08-01T00:00:00Z with final 5500."""
        setup = setup_confirmed_fraud_txn("ACCT-CA5", "PT-CA5", 10001, "M-CA5")
        acct, txn = setup["account"], setup["txn"]
        loss = create_finalized_loss(acct["id"], [txn["id"]], 5500)
        return acct, loss

    def test_loss_counts_at_exactly_90_days(self, api):
        """PRD §2.11: "the sum of `final_amount_cents` across the account's losses in
        `FINALIZED`, `PARTIALLY_RECOVERED`, or `WRITTEN_OFF` whose `finalized_at`
        falls within the inclusive 90-day window ending at the current logical
        time".

        Design: Corner/calculations/rolling_loss_ninety_day_window
        """
        acct, _loss = self._setup_finalized(api)
        set_clock("2026-10-30T00:00:00Z")
        account = validate_success(api.get_account(acct["id"], MANAGER))
        assert account["rolling_90d_loss_cents"] == 5500, (
            f"at exactly finalized_at + 90d the loss still counts (inclusive bound); got {account['rolling_90d_loss_cents']}"
        )

    def test_loss_drops_out_at_91_days(self, api):
        """PRD §2.11: "whose `finalized_at` falls within the inclusive 90-day window
        ending at the current logical time"; §3.1: "otherwise the tier is `LOW`".

        Design: Corner/calculations/rolling_loss_ninety_day_window
        """
        acct, _loss = self._setup_finalized(api)
        set_clock("2026-10-31T00:00:00Z")
        account = validate_success(api.get_account(acct["id"], MANAGER))
        assert account["rolling_90d_loss_cents"] == 0
        assert account["risk_tier"] == "LOW"


class TestRiskTierThresholdBoundaries:
    def test_two_open_alerts_force_high(self, api):
        """PRD §3.1: "the tier is `HIGH` when at least two alerts are open (statuses
        `OPEN`, `IN_REVIEW`, or `CONTACT_PENDING`)"; "failing that, the tier is
        `MEDIUM` when exactly one alert is open". "All boundaries are inclusive
        exactly as written."

        Design: Corner/calculations/risk_tier_threshold_boundaries
        """
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-CA6A", cardholder_name="Tier A")
        card = create_card(acct["id"], "PT-CA6A")
        create_manual_alert(acct["id"], card["id"])
        mid = validate_success(api.get_account(acct["id"], MANAGER))
        assert mid["risk_tier"] == "MEDIUM", f"exactly 1 open alert -> MEDIUM, got {mid['risk_tier']}"
        create_manual_alert(acct["id"], card["id"])
        high = validate_success(api.get_account(acct["id"], MANAGER))
        assert high["risk_tier"] == "HIGH", f"exactly 2 open alerts (>= 2) -> HIGH, got {high['risk_tier']}"

    def test_rolling_loss_exact_boundaries(self, api):
        """PRD §3.1: "the tier is `MEDIUM` when ... the rolling loss is at least
        25000 cents"; "the tier is `HIGH` when ... the rolling 90-day confirmed
        loss is at least 100000 cents". "All boundaries are inclusive exactly as
        written."

        Design: Corner/calculations/risk_tier_threshold_boundaries
        """
        create_active_ruleset()
        # Account B: rolling exactly 25000 -> MEDIUM
        setup_b = setup_confirmed_fraud_txn("ACCT-CA6B", "PT-CA6B", 50000, "M-CA6", clock="2026-08-01T00:00:00Z")
        create_finalized_loss(setup_b["account"]["id"], [setup_b["txn"]["id"]], 25000)
        acct_b = validate_success(api.get_account(setup_b["account"]["id"], MANAGER))
        assert acct_b["risk_tier"] == "MEDIUM", (
            f"rolling exactly 25000 (>= 25000, < 100000) -> MEDIUM, got {acct_b['risk_tier']}"
        )
        # Account C: rolling exactly 100000 -> HIGH
        setup_c = setup_confirmed_fraud_txn("ACCT-CA6C", "PT-CA6C", 200000, "M-CA6", clock="2026-08-01T00:00:00Z")
        create_finalized_loss(setup_c["account"]["id"], [setup_c["txn"]["id"]], 100000)
        acct_c = validate_success(api.get_account(setup_c["account"]["id"], MANAGER))
        assert acct_c["risk_tier"] == "HIGH", (
            f"rolling exactly 100000 (>= 100000) -> HIGH, got {acct_c['risk_tier']}"
        )
