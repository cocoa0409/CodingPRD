"""Liquidation credit: valuation variants, OCC appraisal, ledger conservation."""
from test_helpers import (
    ApiErrorId,
    assert_order_totals_invariants,
    fixtures as fx,
    make_finance_manager_headers,
    validate_error,
    validate_success,
    AE,
    FINANCE,
    USER_LIQUIDATION_APPRAISER,
)


class TestLiquidationValuationVariants:
    def test_liquidation_estimate_variant_at_offer(self, api):
        """PRD section 3.9: "The lot starts `OFFERED` and the system computes a
        provisional `estimated_credit_cents` that always assumes condition
        grade B: it is the `item_count` times the per-item catalog estimate of
        75,000 cents, reduced by a twenty percent estimation haircut — that is,
        multiplied by eighty percent — rounded half-up to whole cents." Ten
        items give 10 x 75000 x 0.8 = 600000.

        Design: Difficulty/dual_variant_calc/liquidation_estimate_vs_final_credit
        """
        ctx = fx.setup_catalog(activate=False, approve_plan=False)
        lot = fx.create_lot(ctx.customer["id"], {"item_count": 10})
        assert lot["status"] == "OFFERED"
        assert lot["estimated_credit_cents"] == 600_000

    def test_liquidation_final_credit_differs_from_estimate(self, api):
        """PRD section 3.9: "the `appraised_value_cents` is first reduced by a
        fifteen percent liquidation fee — multiplied by eighty-five percent and
        rounded half-up to whole cents — and then the per-item refurbishment
        deduction for the lot's actual `condition_grade` is subtracted once per
        item. The refurbishment deduction is 5,000 cents per item for grade A"
        and "The lot moves to `CREDIT_ISSUED`, the customer's
        `liquidation_credit_balance_cents` increases by the
        `final_credit_cents`". Grade A appraised at 1000000 with 10 items:
        round(1000000 x 0.85) - 5000 x 10 = 800000, different from the
        600000 estimate for the same lot.

        Design: Difficulty/dual_variant_calc/liquidation_estimate_vs_final_credit
        """
        ctx = fx.setup_catalog(activate=False, approve_plan=False)
        lot = fx.create_lot(ctx.customer["id"], {"item_count": 10})
        estimate = lot["estimated_credit_cents"]
        lot = fx.appraise_lot(lot, "A", 1_000_000)
        lot = fx.issue_credit(lot["id"])
        assert lot["status"] == "CREDIT_ISSUED"
        assert lot["final_credit_cents"] == 800_000
        assert lot["final_credit_cents"] != estimate
        customer = validate_success(api.get_customer(ctx.customer["id"], FINANCE))
        assert customer["liquidation_credit_balance_cents"] == 800_000


class TestCreditIssuanceGates:
    def test_sod_credit_issue_by_appraiser_rejected(self, api):
        """PRD section 3.9: "Credit issuance belongs to the `FinanceManager`
        and is segregation-of-duties gated: the issuer's `X-User-ID` must
        differ from the recorded `appraised_by_user_id`, else
        `ERR_SOD_VIOLATION`."

        Design: Corner/validations/sod_credit_issue_by_appraiser_rejected
        """
        ctx = fx.setup_catalog(activate=False, approve_plan=False)
        lot = fx.create_lot(ctx.customer["id"], {"item_count": 10})
        lot = fx.appraise_lot(lot, "B", 500_000)
        resp = api.issue_credit(
            lot["id"], make_finance_manager_headers(USER_LIQUIDATION_APPRAISER)
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        issued = validate_success(api.issue_credit(lot["id"], FINANCE))
        assert issued["status"] == "CREDIT_ISSUED"
        # round(500000 x 0.85) - 15000 x 10 = 425000 - 150000 = 275000
        assert issued["final_credit_cents"] == 275_000

    def test_occ_lot_appraisal_stale_rejected(self, api):
        """PRD section 2.6: "A request to record (or re-record) an appraisal
        against a `LiquidationLot` must carry `expected_lot_version` equal to
        the lot's current `version`. If the lot's `version` has advanced since
        the client last observed it, the appraisal is rejected with
        `ERR_STALE_VERSION` (HTTP 412)". PRD section 3.9: "A lot already
        `APPRAISED` may be re-appraised — the transition is `APPRAISED` →
        `APPRAISED` — with the same OCC guard; the prior appraisal values are
        overwritten".

        Design: Corner/complexity_layers/occ_lot_appraisal_stale_rejected
        """
        ctx = fx.setup_catalog(activate=False, approve_plan=False)
        lot = fx.create_lot(ctx.customer["id"], {"item_count": 10})
        create_version = lot["version"]
        appraised = fx.appraise_lot(lot, "B", 500_000)
        resp = api.appraise_lot(
            lot["id"],
            {"condition_grade": "C", "appraised_value_cents": 400_000,
             "expected_lot_version": create_version},
            fx.APPRAISER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        reappraised = validate_success(
            api.appraise_lot(
                lot["id"],
                {"condition_grade": "C", "appraised_value_cents": 400_000,
                 "expected_lot_version": appraised["version"]},
                fx.APPRAISER,
            )
        )
        assert reappraised["status"] == "APPRAISED"
        assert reappraised["condition_grade"] == "C"

    def test_appraisal_validity_sweep_boundary(self, api):
        """PRD section 2.7: "any `LiquidationLot` in `APPRAISED` whose latest
        `appraised_at` date is more than thirty days before the new current UTC
        date transitions to `EXPIRED`, reflecting the thirty-day validity of an
        appraisal." Appraised at the startup clock 2026-08-01, the lot is still
        valid on 2026-08-31 (exactly thirty days) and expired on 2026-09-01;
        credit issuance then targets a state from which the transition does not
        exist (PRD section 2.8 rule 4).

        Design: Corner/endpoints/appraisal_validity_sweep_boundary
        """
        ctx = fx.setup_catalog(activate=False, approve_plan=False)
        lot = fx.create_lot(ctx.customer["id"], {"item_count": 10})
        fx.appraise_lot(lot, "B", 500_000)  # appraised_at = 2026-08-01
        fx.set_clock("2026-08-31T00:00:00Z")
        still_valid = validate_success(api.get_liquidation_lot(lot["id"], FINANCE))
        assert still_valid["status"] == "APPRAISED"
        fx.set_clock("2026-09-01T00:00:00Z")
        expired = validate_success(api.get_liquidation_lot(lot["id"], FINANCE))
        assert expired["status"] == "EXPIRED"
        resp = api.issue_credit(lot["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCreditApplyCancelRoundtrip:
    def _setup_credited_order(self):
        """800000 issued credit; submitted order 10 x 100000 list at 40%."""
        ctx = fx.setup_submitted_order(line_overrides={"quantity": 10})
        fx.setup_customer_credit(
            ctx.customer["id"], appraised_value_cents=1_000_000,
            condition_grade="A", item_count=10,
        )
        return ctx

    def test_credit_apply_cancel_roundtrip_apply(self, api):
        """PRD section 3.8: "A successful application increases the order's
        `credit_applied_cents` by the amount, recomputes the
        `grand_total_cents`, debits the customer's ledger" — net 600000 + fee
        72000 (12-percent band: list 1000000 is under fifty thousand dollars)
        - credit 100000 = 572000; the ledger drops from 800000 to 700000.

        Design: Difficulty/compensating_invariant/credit_apply_cancel_roundtrip
        """
        ctx = self._setup_credited_order()
        before = validate_success(api.get_customer(ctx.customer["id"], FINANCE))
        assert before["liquidation_credit_balance_cents"] == 800_000
        order = validate_success(
            api.apply_credit(ctx.order["id"], {"amount_cents": 100_000}, FINANCE)
        )
        assert order["credit_applied_cents"] == 100_000
        assert order["install_fee_cents"] == 72_000
        assert order["grand_total_cents"] == 572_000
        assert_order_totals_invariants(order)
        after = validate_success(api.get_customer(ctx.customer["id"], FINANCE))
        assert after["liquidation_credit_balance_cents"] == 700_000

    def test_credit_apply_cancel_roundtrip_cancel_restores(self, api):
        """PRD section 2.10: "The conservation property is exact: applying
        credit to an order and then cancelling that order restores the
        customer's prior balance exactly." PRD section 3.6: "From `SUBMITTED`
        the fee is also zero" and "In every case the order's
        `credit_applied_cents` is returned to the customer's credit ledger".

        Design: Difficulty/compensating_invariant/credit_apply_cancel_roundtrip
        """
        ctx = self._setup_credited_order()
        validate_success(
            api.apply_credit(ctx.order["id"], {"amount_cents": 100_000}, FINANCE)
        )
        cancelled = validate_success(api.cancel_order(ctx.order["id"], AE))
        assert cancelled["cancel_fee_cents"] == 0
        restored = validate_success(api.get_customer(ctx.customer["id"], FINANCE))
        assert restored["liquidation_credit_balance_cents"] == 800_000


class TestCreditFiscalGates:
    def test_apply_credit_exceeds_balance_rejected(self, api):
        """PRD section 3.8: "the amount must not exceed the customer's
        available `liquidation_credit_balance_cents`, else
        `ERR_INSUFFICIENT_CREDIT`" — 100000 against a 90000 balance fails even
        though the order's credit cap (168000) would allow the amount.

        Design: Corner/validations/apply_credit_exceeds_balance_rejected
        """
        ctx = fx.setup_submitted_order(line_overrides={"quantity": 10})
        fx.setup_customer_credit(
            ctx.customer["id"], appraised_value_cents=400_000,
            condition_grade="C", item_count=10,
        )  # 340000 - 250000 = 90000
        resp = api.apply_credit(ctx.order["id"], {"amount_cents": 100_000}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT)

    def test_state_beats_fiscal_on_apply_credit_cancelled(self, api):
        """PRD section 3.8: "A `FinanceManager` applies customer credit to an
        order in `SUBMITTED` or `ACKNOWLEDGED`" — a `CANCELLED` order is in a
        state from which the transition does not exist.
        PRD section 2.8: "Auth, existence, and state failures surface before
        any business rule; fiscal failures surface last." With an empty ledger
        the amount would also fail the balance rule, yet the state error wins.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_apply_credit
        """
        ctx = fx.setup_submitted_order()
        validate_success(api.cancel_order(ctx.order["id"], AE))
        resp = api.apply_credit(ctx.order["id"], {"amount_cents": 100}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_state_beats_fiscal_on_apply_credit_draft(self, api):
        """PRD section 3.8: "A `FinanceManager` applies customer credit to an
        order in `SUBMITTED` or `ACKNOWLEDGED`" — a `DRAFT` order is likewise a
        state from which the transition does not exist, and per PRD section
        2.8 "state failures surface before any business rule; fiscal failures
        surface last", ERR_INVALID_STATE beats the balance check on an empty
        ledger.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_apply_credit
        """
        ctx = fx.setup_draft_order()
        resp = api.apply_credit(ctx.order["id"], {"amount_cents": 100}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestRedeemAndCustomerClose:
    def test_lot_manual_redeem_forfeits_remainder(self, api):
        """PRD section 3.9: "A `FinanceManager` may also redeem a
        `CREDIT_ISSUED` lot manually, which forfeits any unredeemed remainder:
        the lot moves to `REDEEMED` and the forfeited remainder — the
        `final_credit_cents` minus the `redeemed_cents` — is debited from the
        customer's credit ledger." 800000 issued, 100000 applied, 700000
        forfeited: the ledger goes to zero.

        Design: Corner/state_machines/lot_manual_redeem_forfeits_remainder
        """
        ctx = fx.setup_submitted_order(line_overrides={"quantity": 10})
        lot = fx.setup_customer_credit(
            ctx.customer["id"], appraised_value_cents=1_000_000,
            condition_grade="A", item_count=10,
        )
        validate_success(
            api.apply_credit(ctx.order["id"], {"amount_cents": 100_000}, FINANCE)
        )
        redeemed = validate_success(api.redeem_lot(lot["id"], FINANCE))
        assert redeemed["status"] == "REDEEMED"
        customer = validate_success(api.get_customer(ctx.customer["id"], FINANCE))
        assert customer["liquidation_credit_balance_cents"] == 0

    def test_customer_close_blocked_when_not_settled(self, api):
        """PRD section 3.2: "Closing a customer is permitted only when the
        account is fully settled: the `liquidation_credit_balance_cents` must
        be zero and the customer must have no project order in `DRAFT`,
        `SUBMITTED`, `ACKNOWLEDGED`, `DELIVERED`, or `INSTALLED` status. A
        close attempt that violates either condition is rejected with
        `ERR_CUSTOMER_NOT_SETTLED`".

        Design: Corner/validations/customer_close_blocked_when_not_settled
        """
        ctx = fx.setup_catalog(activate=False, approve_plan=False)
        fx.setup_customer_credit(
            ctx.customer["id"], appraised_value_cents=1_000_000,
            condition_grade="A", item_count=10,
        )
        resp = api.close_customer(ctx.customer["id"], AE)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_SETTLED)
