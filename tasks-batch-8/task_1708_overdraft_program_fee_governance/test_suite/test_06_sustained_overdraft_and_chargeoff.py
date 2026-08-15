"""Settle-driven cascades (PRD §3.5): sustained-overdraft day counting,
restriction with the one-time sustained fee, steering nudges, charge-off, and
the recovery invariant."""
from test_helpers import (
    assert_chargeoff_invariant,
    authorize,
    get_account,
    get_offer,
    get_waiver_request,
    list_fees,
    list_offers,
    make_account_holder_headers,
    make_charged_off_scenario,
    make_opted_in_account,
    make_program,
    open_batch,
    run_posting_day,
    seal_batch,
    set_clock,
    settle_batch,
    submit_waiver,
    validate_success,
)


class TestSettleCascadeRestrictToOffer:
    def _setup(self):
        """Threshold 3, grace 4. Mon: fund 1000 (settled). Tue: debit 5000
        (fee 3500 POSTED, ledger -7500, count 1). Wed: empty settle (count 2).
        Thu: empty batch SEALED, not settled."""
        program = make_program(name="OD-S", sustained_overdraft_days_threshold=3,
                               charge_off_grace_business_days=4)
        account, _ = make_opted_in_account(program["id"], holder_name="Holder S")
        run_posting_day(program["id"], "2026-08-03", account["id"],
                        [("CREDIT_DEPOSIT", 1000)], settle=True)
        run_posting_day(program["id"], "2026-08-04", account["id"],
                        [("DEBIT_ONE_TIME", 5000)], settle=True)
        run_posting_day(program["id"], "2026-08-05", account["id"], [],
                        settle=True)
        batch4 = open_batch(program["id"], "2026-08-06")
        seal_batch(batch4["id"])
        return program, account, batch4

    def test_threshold_crossing_restricts_and_assesses_sustained_fee(self, api):
        """PRD §3.5: "When an `ACTIVE` account's incremented count reaches or
        exceeds the program's `sustained_overdraft_days_threshold`, the account
        is restricted: its `status` becomes `RESTRICTED`,
        `restricted_business_days` resets to zero, and its `version`
        increments."
        PRD §3.5: "Unless the program is `SUSPENDED`, the same settle assesses
        the one-time sustained fee — an `OverdraftFee` of `fee_type`
        `SUSTAINED` for `sustained_overdraft_fee_cents`, born directly in
        `POSTED` status with `transaction_id` null, `posted_date` set to the
        batch's business date, exempt from both daily caps and the de minimis
        test, and debited from the ledger immediately — and adds the amount to
        `lifetime_fees_assessed_cents`."

        Design: Difficulty/transitive_cascade/settle_cascade_restrict_to_offer
        """
        _, account, batch4 = self._setup()
        settle_batch(batch4["id"])
        after = get_account(account["id"])
        assert after["status"] == "RESTRICTED"
        assert after["consecutive_negative_business_days"] == 3
        assert after["restricted_business_days"] == 0
        # -7500 - 3000 sustained fee, debited immediately.
        assert after["ledger_balance_cents"] == -10500
        # 3500 OVERDRAFT + 3000 SUSTAINED.
        assert after["lifetime_fees_assessed_cents"] == 6500

        sustained = list_fees(account_id=account["id"], fee_type="SUSTAINED")
        assert len(sustained) == 1
        assert sustained[0]["amount_cents"] == 3000
        assert sustained[0]["status"] == "POSTED"
        assert sustained[0]["posted_date"] == "2026-08-06"
        assert sustained[0]["transaction_id"] is None

    def test_restriction_auto_creates_sustained_od_offer(self, api):
        """PRD §3.5: "Restriction also triggers a steering nudge: an
        **EducationOffer** of type `OVERDRAFT_LINE_OF_CREDIT` with
        `trigger_reason` `SUSTAINED_OD` is auto-created, subject to the same
        steering caps described below."

        Design: Difficulty/transitive_cascade/settle_cascade_restrict_to_offer
        """
        _, account, batch4 = self._setup()
        settle_batch(batch4["id"])
        offers = list_offers(account["id"])
        assert len(offers) == 1
        assert offers[0]["offer_type"] == "OVERDRAFT_LINE_OF_CREDIT"
        assert offers[0]["trigger_reason"] == "SUSTAINED_OD"
        assert offers[0]["status"] == "OFFERED"


class TestSustainedDayCountExactThresholdBoundary:
    def _setup(self):
        """Threshold 3, grace 4. Mon: debit 2000 from 0 (fee POSTED, ledger
        -5500, count 1). Tue: empty settle (count 2). Wed: empty batch SEALED
        only."""
        program = make_program(name="OD-T", sustained_overdraft_days_threshold=3,
                               charge_off_grace_business_days=4)
        account, _ = make_opted_in_account(program["id"], holder_name="Holder T")
        run_posting_day(program["id"], "2026-08-03", account["id"],
                        [("DEBIT_ONE_TIME", 2000)], settle=True)
        run_posting_day(program["id"], "2026-08-04", account["id"], [],
                        settle=True)
        batch3 = open_batch(program["id"], "2026-08-05")
        seal_batch(batch3["id"])
        return program, account, batch3

    def test_count_below_threshold_stays_active(self, api):
        """PRD §3.5: "When an `ACTIVE` account's incremented count reaches or
        exceeds the program's `sustained_overdraft_days_threshold`, the account
        is restricted".
        PRD §3.5: "An account whose post-fee ledger is negative has its
        `consecutive_negative_business_days` incremented".

        Design: Difficulty/boundary_precision_check/sustained_day_count_exact_threshold_boundary
        """
        _, account, _ = self._setup()
        mid = get_account(account["id"])
        # Count 2 < threshold 3: no restriction yet.
        assert mid["status"] == "ACTIVE"
        assert mid["consecutive_negative_business_days"] == 2

    def test_count_reaching_threshold_restricts_with_sustained_fee(self, api):
        """PRD §3.5: "When an `ACTIVE` account's incremented count reaches or
        exceeds the program's `sustained_overdraft_days_threshold`, the account
        is restricted: its `status` becomes `RESTRICTED`,
        `restricted_business_days` resets to zero, and its `version`
        increments."

        Design: Difficulty/boundary_precision_check/sustained_day_count_exact_threshold_boundary
        """
        _, account, batch3 = self._setup()
        settle_batch(batch3["id"])
        after = get_account(account["id"])
        # Count 3 >= 3: exact crossing restricts.
        assert after["status"] == "RESTRICTED"
        assert after["consecutive_negative_business_days"] == 3
        # -5500 - 3000 sustained fee.
        assert after["ledger_balance_cents"] == -8500
        sustained = list_fees(account_id=account["id"], fee_type="SUSTAINED")
        assert len(sustained) == 1
        assert sustained[0]["amount_cents"] == 3000
        assert sustained[0]["posted_date"] == "2026-08-05"


class TestChargeoffRecoveryConservesPrincipal:
    def test_chargeoff_freezes_principal_and_zeroes_ledger(self, api):
        """PRD §3.5: "Charge-off moves the account to `CLOSED_CHARGEOFF`, sets
        `charged_off_cents` and `charge_off_original_cents` to the magnitude of
        the negative ledger, sets `recovered_cents` to zero, zeroes
        `ledger_balance_cents`, and increments `version`."
        PRD §3.2: "`charge_off_original_cents` records the principal at
        closure, `charged_off_cents` tracks the still-unrecovered remainder,
        and `recovered_cents` accumulates recovery credits — with the invariant
        that `charged_off_cents` plus `recovered_cents` always equals
        `charge_off_original_cents`."

        Design: Difficulty/compensating_invariant/chargeoff_recovery_conserves_principal
        """
        ctx = make_charged_off_scenario()
        account = ctx["account"]
        # 5000 debit + 3500 OVERDRAFT + 3000 SUSTAINED = 11500 principal.
        assert account["status"] == "CLOSED_CHARGEOFF"
        assert account["charged_off_cents"] == 11500
        assert account["charge_off_original_cents"] == 11500
        assert account["recovered_cents"] == 0
        assert account["ledger_balance_cents"] == 0
        assert_chargeoff_invariant(account)
        # The charge-off cascade retired the OFFERED steering offer.
        offers = list_offers(account["id"])
        assert len(offers) == 1
        assert offers[0]["status"] == "EXPIRED"

    def test_recovery_credits_post_immediately_and_conserve_principal(self, api):
        """PRD §3.3: "A recovery credit never enters a batch — it posts
        immediately, born `POSTED` with `batch_id` and `posting_sequence` left
        null and `posted_date` set to the creation date".
        PRD §3.3: "Each posted recovery increases `recovered_cents` and
        decreases `charged_off_cents` by the same amount, preserving the
        charge-off invariant; the account's `ledger_balance_cents`, zeroed at
        charge-off, is not altered by recovery postings."

        Design: Difficulty/compensating_invariant/chargeoff_recovery_conserves_principal
        """
        ctx = make_charged_off_scenario()
        account = ctx["account"]
        holder = make_account_holder_headers(account["id"])

        rec1 = validate_success(api.create_transaction(
            {"account_id": account["id"], "type": "CREDIT_DEPOSIT",
             "amount_cents": 4000}, holder), 201)
        assert rec1["status"] == "POSTED"
        assert rec1["batch_id"] is None
        # Clock never advanced in this scenario: still the startup default.
        assert rec1["posted_date"] == "2026-08-01"

        mid = get_account(account["id"])
        assert mid["charged_off_cents"] == 7500
        assert mid["recovered_cents"] == 4000
        assert_chargeoff_invariant(mid)

        rec2 = validate_success(api.create_transaction(
            {"account_id": account["id"], "type": "CREDIT_DEPOSIT",
             "amount_cents": 7500}, holder), 201)
        assert rec2["status"] == "POSTED"
        final = get_account(account["id"])
        assert final["charged_off_cents"] == 0
        assert final["recovered_cents"] == 11500
        assert final["charge_off_original_cents"] == 11500
        assert_chargeoff_invariant(final)


class TestSustainedFeeExemptFromDailyCaps:
    def test_sustained_fee_posts_despite_saturated_daily_caps(self, api):
        """PRD §3.5: "Unless the program is `SUSPENDED`, the same settle
        assesses the one-time sustained fee — an `OverdraftFee` of `fee_type`
        `SUSTAINED` for `sustained_overdraft_fee_cents`, born directly in
        `POSTED` status with `transaction_id` null, `posted_date` set to the
        batch's business date, exempt from both daily caps and the de minimis
        test, and debited from the ledger immediately — and adds the amount to
        `lifetime_fees_assessed_cents`."

        Design: Corner/calculations/sustained_fee_exempt_from_daily_caps
        """
        program = make_program(name="OD-CAL3",
                               sustained_overdraft_days_threshold=1,
                               steering_fee_count_threshold=99)
        account, _ = make_opted_in_account(program["id"], holder_name="H CAL3")
        batch = open_batch(program["id"], "2026-08-03")
        for clock in ("2026-08-03T09:00:00Z", "2026-08-03T09:01:00Z",
                      "2026-08-03T09:02:00Z"):
            set_clock(clock)
            authorize(account["id"], "DEBIT_ONE_TIME", 2000)
        seal = seal_batch(batch["id"])
        # Daily caps saturated by OVERDRAFT fees alone (3 x 3500 = 10500).
        assert seal["fees_assessed_count"] == 3
        assert seal["fees_assessed_cents"] == 10500

        settle_batch(batch["id"])
        sustained = list_fees(account_id=account["id"], fee_type="SUSTAINED")
        assert len(sustained) == 1
        assert sustained[0]["amount_cents"] == 3000
        assert sustained[0]["transaction_id"] is None
        assert sustained[0]["status"] == "POSTED"

        after = get_account(account["id"])
        # 3 x 3500 OVERDRAFT + 3000 SUSTAINED.
        assert after["lifetime_fees_assessed_cents"] == 13500
        # -6000 items, -10500 OVERDRAFT fees at settle, -3000 sustained fee.
        assert after["ledger_balance_cents"] == -19500
        assert after["status"] == "RESTRICTED"


class TestChargeoffCascadeResolvesOpenItems:
    def test_pending_waiver_denied_final_and_offer_expired(self, api):
        """PRD §3.5: "The cascade resolves the account's open items in the same
        motion: every waiver request still in `PENDING_SUPERVISOR`,
        `PENDING_MANAGER`, or `PENDING_COMPLIANCE` is moved to `DENIED_FINAL`,
        and every education offer still `OFFERED` is moved to `EXPIRED`."
        PRD §3.6: "An `AccountHolder`-created request never auto-approves; even
        a one-dollar holder request routes to `PENDING_SUPERVISOR` at minimum."

        Design: Corner/cross_cutting_complexity_layers/chargeoff_cascade_denies_pending_waiver_and_expires_offer
        """
        program = make_program(name="OD-CAS1",
                               sustained_overdraft_days_threshold=1,
                               charge_off_grace_business_days=2,
                               steering_fee_count_threshold=99)
        account, _ = make_opted_in_account(program["id"], holder_name="H CAS1")
        run_posting_day(program["id"], "2026-08-03", account["id"],
                        [("DEBIT_ONE_TIME", 5000)], settle=True)
        fee_ids = [f["id"] for f in list_fees(account_id=account["id"])]
        assert len(fee_ids) == 2  # OVERDRAFT 3500 + SUSTAINED 3000

        waiver = submit_waiver(account["id"], fee_ids, kind="FULL",
                               reason_code="HARDSHIP", as_holder=True)
        assert waiver["status"] == "PENDING_SUPERVISOR"
        offers = list_offers(account["id"])
        assert len(offers) == 1 and offers[0]["status"] == "OFFERED"

        run_posting_day(program["id"], "2026-08-04", account["id"], [],
                        settle=True)
        run_posting_day(program["id"], "2026-08-05", account["id"], [],
                        settle=True)

        after = get_account(account["id"])
        assert after["status"] == "CLOSED_CHARGEOFF"
        assert after["charged_off_cents"] == 11500
        assert get_waiver_request(waiver["id"])["status"] == "DENIED_FINAL"
        assert get_offer(offers[0]["id"])["status"] == "EXPIRED"
