"""Regulation CC expedited recredit: creation guards, provisional-credit
computation, finalization windows, and the late-provisioning sweep flag."""
import pytest

from test_helpers import (
    ApiErrorId,
    analyst,
    create_account,
    create_recredit_payload,
    make_customer_headers,
    set_clock,
    setup_paid_item,
    setup_presented_item,
    setup_recredit_provisioned,
    setup_recredit_submitted,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    SERVICE,
    list_ledger_entries,
)


class TestProvisionalCreditComputation:
    def _submitted_133333_at_wednesday(self):
        """Recredit for 133333 on a PAID 200000 item, requested at the
        default Friday clock; clock advanced 5 calendar days to Wednesday
        2026-05-06 before provisioning."""
        ctx = setup_recredit_submitted(
            claim_amount_cents=133333, item_amount_cents=200000,
            opening_balance_cents=0, risk_tier="STANDARD", reg_cc_eligible=True,
            bank_overrides={"name": "CB RC", "routing_number": "111000028"},
            item_reference="ITM-RC",
        )
        set_clock("2026-05-06T00:00:00Z")
        return ctx

    def test_recredit_interest_rounds_per_day_then_sums(self, api):
        """PRD §3.8: "for each such day, the day's interest is the principal
        multiplied by the daily rate of 0.0002, rounded half-up to whole
        cents, and `interest_cents` is the sum of those per-day amounts. The
        per-day rounding order is mandatory — rounding each day first and
        then summing is required, and multiplying-then-rounding-once is
        forbidden; concretely, a principal of 133333 cents held for 5 days
        earns 27 cents per day and 135 cents in total, not 133."

        Design: Difficulty/combinatorial_formula/recredit_provisional_daily_rounding
        """
        ctx = self._submitted_133333_at_wednesday()
        provisioned = validate_success(
            api.grant_provisional_credit(ctx["recredit"]["id"], SERVICE), 200
        )
        assert provisioned["principal_amount_cents"] == 133333
        assert provisioned["interest_cents"] == 135
        assert provisioned["provisional_amount_cents"] == 133468

    def test_recredit_provisioned_late_after_two_business_days(self, api):
        """PRD §3.8: "computes `provisioned_late`: true when the credit
        posted more than 2 business days after `submitted_at`." (Friday
        2026-05-01 -> Wednesday 2026-05-06 spans 3 business days under the
        §2.4 counting rule, so the credit is late.)

        Design: Difficulty/combinatorial_formula/recredit_provisional_daily_rounding
        """
        ctx = self._submitted_133333_at_wednesday()
        provisioned = validate_success(
            api.grant_provisional_credit(ctx["recredit"]["id"], SERVICE), 200
        )
        assert provisioned["provisioned_late"] is True


class TestRecreditClawback:
    def _provisioned_100000(self):
        """Recredit for 100000 provisioned at the same logical clock as
        submission (0 elapsed days -> interest 0 -> provisional 100000)."""
        return setup_recredit_provisioned(
            claim_amount_cents=100000, item_amount_cents=200000,
            opening_balance_cents=0, reg_cc_eligible=True,
            bank_overrides={"name": "CB RW", "routing_number": "111000041"},
            item_reference="ITM-RW",
        )

    def test_revoke_moves_request_to_revoked(self, api):
        """PRD §3.8: "An `outcome` of `REVOKED` is allowed only while the
        current time is no later than 45 calendar days after `submitted_at`"
        and "`CONFIRMED` and `REVOKED` are both terminal."
        PRD §3.8: "The `provisional_amount_cents` is the principal plus the
        interest." (0 elapsed days -> 100000 + 0 = 100000.)

        Design: Difficulty/compensating_invariant/recredit_clawback_nets_zero
        """
        ctx = self._provisioned_100000()
        assert ctx["recredit"]["provisional_amount_cents"] == 100000
        revoked = validate_success(
            api.finalize_recredit_request(
                ctx["recredit"]["id"], {"outcome": "REVOKED"}, analyst("analyst-9")
            ),
            200,
        )
        assert revoked["status"] == "REVOKED"

    def test_revoke_clawback_nets_recredit_ledger_zero(self, api):
        """PRD §3.8: "Revocation posts a `RECREDIT_CLAWBACK_DEBIT` ledger
        entry for the negative of `provisional_amount_cents`, marked
        provisional, which nets the recredit's ledger footprint for that
        request to zero"

        Design: Difficulty/compensating_invariant/recredit_clawback_nets_zero
        """
        ctx = self._provisioned_100000()
        validate_success(
            api.finalize_recredit_request(
                ctx["recredit"]["id"], {"outcome": "REVOKED"}, analyst("analyst-9")
            ),
            200,
        )
        entries = list_ledger_entries(recredit_request_id=ctx["recredit"]["id"])
        by_type = {e["entry_type"]: e["amount_cents"] for e in entries}
        assert by_type.get("RECREDIT_PROVISIONAL_CREDIT") == 100000
        assert by_type.get("RECREDIT_CLAWBACK_DEBIT") == -100000
        assert sum(e["amount_cents"] for e in entries) == 0


class TestRecreditValidationOrder:
    def _two_accounts_one_paid_item(self):
        """Account A (requesting) and account B (owns the PAID 50000 item)."""
        ctx_b = setup_paid_item(
            amount_cents=50000, reg_cc_eligible=True,
            bank_overrides={"name": "CB RF", "routing_number": "111000034"},
            item_reference="ITM-B",
        )
        acct_a = create_account(
            customer_name="Judy", account_number="A-1000", reg_cc_eligible=True,
            opening_balance_cents=0,
        )
        return acct_a, ctx_b

    def test_item_mismatch_masks_over_claim_amount(self, api):
        """PRD §2.11: "tenth, cross-reference coherence
        (`ERR_RECREDIT_ITEM_MISMATCH`); and eleventh, amount sanity and
        request shape (`ERR_INVALID_AMOUNT`, `ERR_INVALID_REQUEST`). A
        failure at any step masks every later step." (Item belongs to another
        account AND claimed 999999 exceeds the item amount -> the referential
        error surfaces.)

        Design: Difficulty/priority_pair_validation_conflict/recredit_referential_vs_fiscal
        """
        acct_a, ctx_b = self._two_accounts_one_paid_item()
        res = api.create_recredit_request(
            create_recredit_payload(
                acct_a["id"], ctx_b["item"]["id"],
                claimed_amount_cents=999999, reason="mismatch and over-claim",
            ),
            SERVICE,
        )
        validate_error(res, ApiErrorId.ERR_RECREDIT_ITEM_MISMATCH)

    def test_item_mismatch_masks_zero_claim_amount(self, api):
        """PRD §2.11: "tenth, cross-reference coherence
        (`ERR_RECREDIT_ITEM_MISMATCH`); and eleventh, amount sanity and
        request shape (`ERR_INVALID_AMOUNT`, `ERR_INVALID_REQUEST`). A
        failure at any step masks every later step." (Item belongs to
        another account AND claimed 0 violates the fiscal floor -> the
        referential error surfaces.)

        Design: Difficulty/priority_pair_validation_conflict/recredit_referential_vs_fiscal
        """
        acct_a, ctx_b = self._two_accounts_one_paid_item()
        res = api.create_recredit_request(
            create_recredit_payload(
                acct_a["id"], ctx_b["item"]["id"],
                claimed_amount_cents=0, reason="mismatch and zero claim",
            ),
            SERVICE,
        )
        validate_error(res, ApiErrorId.ERR_RECREDIT_ITEM_MISMATCH)


class TestRecreditCreationGuards:
    def test_recredit_window_expired_after_40_days(self, api):
        """PRD §3.8: "the request must be created no more than 40 calendar
        days after the item's `paid_at` (else `ERR_RECREDIT_WINDOW_EXPIRED`)"
        (Paid Friday 2026-05-01 -> day 40 is 2026-06-10; 2026-06-11 is late.)

        Design: Corner/validations/recredit_window_expired_after_40_days
        """
        ctx = setup_paid_item(
            amount_cents=200000, reg_cc_eligible=True,
            bank_overrides={"name": "CB RW2", "routing_number": "222000028"},
            item_reference="ITM-RW2",
        )
        set_clock("2026-06-11T00:00:00Z")
        res = api.create_recredit_request(
            create_recredit_payload(
                ctx["account"]["id"], ctx["item"]["id"],
                claimed_amount_cents=50000, reason="late claim",
            ),
            SERVICE,
        )
        validate_error(res, ApiErrorId.ERR_RECREDIT_WINDOW_EXPIRED)

    def test_finalize_revoke_after_45_days_rejected_but_confirm_ok(self, api):
        """PRD §3.8: "An `outcome` of `CONFIRMED` is allowed at any time: the
        provisional credit simply stands, `finalized_at` is recorded, and the
        request lands in the terminal `CONFIRMED` state. An `outcome` of
        `REVOKED` is allowed only while the current time is no later than 45
        calendar days after `submitted_at` — later attempts are rejected with
        `ERR_FINALIZE_WINDOW_EXPIRED`."
        (Submitted Friday 2026-05-01 -> day 45 is 2026-06-15; 2026-06-16 is
        past the window.)

        Design: Corner/validations/finalize_revoke_after_45_days_rejected_but_confirm_ok
        """
        ctx = setup_recredit_provisioned(
            claim_amount_cents=50000, item_amount_cents=200000,
            reg_cc_eligible=True,
            bank_overrides={"name": "CB FZ", "routing_number": "222000029"},
            item_reference="ITM-FZ",
        )
        set_clock("2026-06-16T00:00:00Z")
        revoked = api.finalize_recredit_request(
            ctx["recredit"]["id"], {"outcome": "REVOKED"}, analyst("analyst-1")
        )
        validate_error(revoked, ApiErrorId.ERR_FINALIZE_WINDOW_EXPIRED)

        confirmed = validate_success(
            api.finalize_recredit_request(
                ctx["recredit"]["id"], {"outcome": "CONFIRMED"}, analyst("analyst-1")
            ),
            200,
        )
        assert confirmed["status"] == "CONFIRMED"

    def test_recredit_already_open_rejected(self, api):
        """PRD §3.8: "no other recredit request for the same item may be
        sitting in `SUBMITTED` or `PROVISIONALLY_CREDITED` (else
        `ERR_RECREDIT_ALREADY_OPEN`)"

        Design: Corner/validations/recredit_already_open_rejected
        """
        ctx = setup_recredit_submitted(
            claim_amount_cents=1000, item_amount_cents=200000,
            reg_cc_eligible=True,
            bank_overrides={"name": "CB AO", "routing_number": "222000030"},
            item_reference="ITM-AO",
        )
        res = api.create_recredit_request(
            create_recredit_payload(
                ctx["account"]["id"], ctx["item"]["id"],
                claimed_amount_cents=2000, reason="second",
            ),
            SERVICE,
        )
        validate_error(res, ApiErrorId.ERR_RECREDIT_ALREADY_OPEN)

    def test_recredit_not_eligible_account(self, api):
        """PRD §3.8: "the account's `reg_cc_eligible` must be true (else
        `ERR_RECREDIT_NOT_ELIGIBLE`)"

        Design: Corner/validations/recredit_not_eligible_account
        """
        ctx = setup_paid_item(
            amount_cents=200000, reg_cc_eligible=False,
            bank_overrides={"name": "CB NE", "routing_number": "222000031"},
            item_reference="ITM-NE",
        )
        res = api.create_recredit_request(
            create_recredit_payload(
                ctx["account"]["id"], ctx["item"]["id"],
                claimed_amount_cents=1000, reason="ineligible account",
            ),
            SERVICE,
        )
        validate_error(res, ApiErrorId.ERR_RECREDIT_NOT_ELIGIBLE)

    def test_recredit_requires_paid_item(self, api):
        """PRD §3.8: "the referenced check item must belong to the named
        account (else `ERR_RECREDIT_ITEM_MISMATCH`); the item must be `PAID`
        (else `ERR_INVALID_STATE`)"
        (Item is PRESENTED but never paid.)

        Design: Corner/validations/recredit_requires_paid_item
        """
        ctx = setup_presented_item(
            amount_cents=200000, reg_cc_eligible=True,
            bank_overrides={"name": "CB NP", "routing_number": "222000032"},
            item_reference="ITM-NP",
        )
        res = api.create_recredit_request(
            create_recredit_payload(
                ctx["account"]["id"], ctx["item"]["id"],
                claimed_amount_cents=1000, reason="item not paid",
            ),
            SERVICE,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_recredit_zero_claim_rejected(self, api):
        """PRD §3.8: "the claimed amount must be greater than zero and no
        more than the item's `amount_cents` (else `ERR_INVALID_AMOUNT`)"

        Design: Corner/validations/recredit_zero_claim_rejected
        """
        ctx = setup_paid_item(
            amount_cents=200000, reg_cc_eligible=True,
            bank_overrides={"name": "CB ZA", "routing_number": "222000033"},
            item_reference="ITM-ZA",
        )
        res = api.create_recredit_request(
            create_recredit_payload(
                ctx["account"]["id"], ctx["item"]["id"],
                claimed_amount_cents=0, reason="zero claim",
            ),
            SERVICE,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_AMOUNT)

    def test_customer_creates_own_recredit_request(self, api):
        """PRD §3.8: "A `Customer` files a recredit request only against
        their own account (per the §2.1 ownership rule); a `CustomerService`
        agent may file on any account's behalf. The request names the
        `depositor_account_id`, the `check_item_id`, a `claimed_amount_cents`,
        and a `reason`, and it is born `SUBMITTED` with `submitted_at` set
        from the logical clock."

        Design: Corner/rbac/customer_creates_own_recredit_request
        """
        ctx = setup_paid_item(
            amount_cents=200000, reg_cc_eligible=True,
            bank_overrides={"name": "CB CU", "routing_number": "222000041"},
            item_reference="ITM-CU",
        )
        customer_headers = make_customer_headers(ctx["account"]["id"])
        created = validate_success(
            api.create_recredit_request(
                create_recredit_payload(
                    ctx["account"]["id"], ctx["item"]["id"],
                    claimed_amount_cents=75000, reason="customer-initiated",
                ),
                customer_headers,
            ),
            201,
        )
        assert created["status"] == "SUBMITTED"


class TestRecreditBreachSweep:
    def test_recredit_late_breach_flagged_by_sweep(self, api):
        """PRD §3.8: "Should a request sit in `SUBMITTED` for more than 2
        business days without provisional credit, the daily sweep sets its
        `breach_flagged` boolean (initially false) to true, surfacing the
        missed regulatory clock." (Submitted Friday 2026-05-01, swept at
        Wednesday 2026-05-06 — 3 business days later.)

        Design: Corner/cross_cutting_layers/recredit_late_breach_flagged_by_sweep
        """
        ctx = setup_recredit_submitted(
            claim_amount_cents=10000, item_amount_cents=200000,
            reg_cc_eligible=True,
            bank_overrides={"name": "CB BF", "routing_number": "222000046"},
            item_reference="ITM-BF",
        )
        set_clock("2026-05-06T00:00:00Z")
        report = validate_success(api.run_daily_ops(ADMIN), 200)
        assert report["recredits_flagged"] == 1

        refreshed = validate_success(
            api.get_recredit_request(ctx["recredit"]["id"], ADMIN), 200
        )
        assert refreshed["breach_flagged"] is True
