"""Remittance scheduling, day-count settlement split, pay/reverse ledger
conservation, period-overlap, and paid-off auto-transition (PRD §2.5, §3.5)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_pool_with_funded_cert, setup_day_count_pair, schedule_remittance,
    set_clock,
    make_originator_headers, make_buyer_headers,
)

ADMIN = TEST_USERS["network_admin_headers"]


class TestAccruedInterestDayCountVariants:
    def test_thirty_360_interest_and_fee(self, api):
        """PRD §2.5: "Under `THIRTY_360`, each full calendar month in the period counts as 30 days, and a partial month counts the smaller of the actual calendar days in the period and 30 — so the window 2026-08-01 through 2026-08-31 contributes 30 days."
        PRD §3.5: "Second, `servicing_fee_cents` is the beginning outstanding multiplied by the agreement's `servicing_fee_bps` divided by ten thousand, multiplied by the period's day count under the agreement's day-count convention, divided by 360, rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/accrued_interest_day_count_variants
        """
        ctx = setup_day_count_pair()
        originator = ctx["originator"]
        rem_t = schedule_remittance(ctx["cert_thirty"]["id"], originator["id"],
                                    period_start="2026-08-01T00:00:00Z",
                                    period_end="2026-08-31T00:00:00Z",
                                    collections_cents=100_000)
        # 30 days: interest = 10,000,000 x 0.06 x 30/360 = 50,000
        assert rem_t["interest_portion_cents"] == 50_000
        # fee = round_half_up(10,000,000 x 0.0025 x 30/360) = 2,083
        assert rem_t["servicing_fee_cents"] == 2_083

    def test_act_360_interest_and_fee_differ(self, api):
        """PRD §2.5: "Under `ACT_360`, the day count is the actual number of calendar days from the period start through the period end, inclusive — the same August window contributes 31 days."
        PRD §2.5: "Identical principal, rate, and window therefore produce different accruals under the two conventions, with `ACT_360` accruing more in 31-day months."

        Design: Difficulty/dual_variant_calc/accrued_interest_day_count_variants
        """
        ctx = setup_day_count_pair()
        originator = ctx["originator"]
        rem_t = schedule_remittance(ctx["cert_thirty"]["id"], originator["id"],
                                    period_start="2026-08-01T00:00:00Z",
                                    period_end="2026-08-31T00:00:00Z",
                                    collections_cents=100_000)
        rem_a = schedule_remittance(ctx["cert_act"]["id"], originator["id"],
                                    period_start="2026-08-01T00:00:00Z",
                                    period_end="2026-08-31T00:00:00Z",
                                    collections_cents=100_000)
        # 31 days: interest = round_half_up(10,000,000 x 0.06 x 31/360) = 51,667
        assert rem_a["interest_portion_cents"] == 51_667
        # fee = round_half_up(10,000,000 x 0.0025 x 31/360) = 2,153
        assert rem_a["servicing_fee_cents"] == 2_153
        assert rem_t["interest_portion_cents"] != rem_a["interest_portion_cents"]


class TestRemittanceSettlementEvaluationOrder:
    def test_split_computed_on_beginning_outstanding(self, api):
        """PRD §3.5: "The settlement split is computed in a pinned order. First, the beginning outstanding is the certificate's `outstanding_principal_cents` before this remittance applies."
        PRD §3.5: "Fourth, `principal_portion_cents` is the remainder — `collections_cents` minus the interest portion minus the servicing fee."

        Design: Difficulty/combinatorial_formula/remittance_settlement_evaluation_order
        """
        ctx = setup_pool_with_funded_cert(
            agreement_overrides={"grace_period_days": 5})
        rem = schedule_remittance(ctx["certificate"]["id"], ctx["originator"]["id"],
                                  collections_cents=5_052_083)
        # Fee is computed on the beginning outstanding 10,000,000, not on the
        # post-principal balance: interest 50,000, fee 2,083, principal 5,000,000.
        assert rem["interest_portion_cents"] == 50_000
        assert rem["servicing_fee_cents"] == 2_083
        assert rem["principal_portion_cents"] == 5_000_000

    def test_late_pay_penalty_on_interest_plus_principal(self, api):
        """PRD §3.5: "Paying after `due_at` moves it to `PAID_LATE` and stamps a penalty: the sum of the interest and principal portions, multiplied by 3 basis points per day and by the number of calendar days from `due_at` to the payment instant, divided by ten thousand, rounded half up to whole cents."
        PRD §3.5: "Either way the certificate's `outstanding_principal_cents` is reduced by `principal_portion_cents` and its `cumulative_interest_cents` grows by `interest_portion_cents`; if the outstanding principal thereby reaches zero, the certificate moves from `ACTIVE` to `PAID_OFF`."

        Design: Difficulty/combinatorial_formula/remittance_settlement_evaluation_order
        """
        ctx = setup_pool_with_funded_cert(
            agreement_overrides={"grace_period_days": 5})
        cert, originator = ctx["certificate"], ctx["originator"]
        rem = schedule_remittance(cert["id"], originator["id"],
                                  collections_cents=5_052_083)
        # due_at = 2026-09-15T00:00:00Z; pay at 2026-09-17 -> 2 days late.
        set_clock("2026-09-17T00:00:00Z")
        paid = validate_success(
            api.pay_remittance(rem["id"], make_originator_headers(originator["id"])), 200)
        assert paid["status"] == "PAID_LATE"
        # penalty = round_half_up((50,000 + 5,000,000) x 3bps x 2 / 10,000) = 3,030
        assert paid["penalty_cents"] == 3_030
        cert_after = validate_success(api.get_commitment(cert["id"], ADMIN), 200)
        assert cert_after["outstanding_principal_cents"] == 5_000_000


class TestPayReverseConservesCertificateLedger:
    def _pay_and_reverse(self, api):
        """Funded 10,000,000 certificate; remittance (interest 50,000, fee 2,083,
        principal 5,000,000) paid on time at the default clock, then reversed."""
        ctx = setup_pool_with_funded_cert()
        cert, originator = ctx["certificate"], ctx["originator"]
        rem = schedule_remittance(cert["id"], originator["id"],
                                  collections_cents=5_052_083)
        paid = validate_success(
            api.pay_remittance(rem["id"], make_originator_headers(originator["id"])), 200)
        reversed_res = api.reverse_remittance(rem["id"], ADMIN)
        return ctx, cert, paid, validate_success(reversed_res, 200)

    def test_pay_then_reverse_restores_outstanding_principal(self, api):
        """PRD §3.5: "A `NetworkAdmin` may reverse a `PAID` or `PAID_LATE` remittance as a compensating action, moving it to `REVERSED` (terminal): the certificate's `outstanding_principal_cents` is increased back by `principal_portion_cents`, `cumulative_interest_cents` is reduced by `interest_portion_cents`, and a certificate sitting in `PAID_OFF` returns to `ACTIVE`."
        PRD §3.5: "Paying a `SCHEDULED` remittance at or before `due_at` moves it to `PAID`, stamps `paid_at`, and leaves `penalty_cents` at zero."

        Design: Difficulty/compensating_invariant/pay_reverse_conserves_certificate_ledger
        """
        ctx, cert, paid, reversed_rem = self._pay_and_reverse(api)
        assert paid["status"] == "PAID"
        assert reversed_rem["status"] == "REVERSED"
        cert_after = validate_success(api.get_commitment(cert["id"], ADMIN), 200)
        assert cert_after["outstanding_principal_cents"] == 10_000_000

    def test_pay_then_reverse_restores_interest_and_status(self, api):
        """PRD §3.5: "A `NetworkAdmin` may reverse a `PAID` or `PAID_LATE` remittance as a compensating action, moving it to `REVERSED` (terminal): the certificate's `outstanding_principal_cents` is increased back by `principal_portion_cents`, `cumulative_interest_cents` is reduced by `interest_portion_cents`, and a certificate sitting in `PAID_OFF` returns to `ACTIVE`."

        Design: Difficulty/compensating_invariant/pay_reverse_conserves_certificate_ledger
        """
        ctx, cert, paid, reversed_rem = self._pay_and_reverse(api)
        cert_after = validate_success(api.get_commitment(cert["id"], ADMIN), 200)
        assert cert_after["cumulative_interest_cents"] == 0
        assert cert_after["status"] == "ACTIVE"


class TestRemittancePeriodClosedOverlap:
    def _setup_with_first_remittance(self, api):
        ctx = setup_pool_with_funded_cert()
        rem1 = schedule_remittance(ctx["certificate"]["id"], ctx["originator"]["id"],
                                   period_start="2026-08-01T00:00:00Z",
                                   period_end="2026-08-31T00:00:00Z",
                                   collections_cents=100_000)
        return ctx, rem1

    def test_shared_calendar_day_rejected(self, api):
        """PRD §3.5: "Remittance periods for a certificate are closed intervals, and a new period that shares even a single calendar day with another non-`REVERSED` remittance of the same certificate is rejected with `ERR_REMITTANCE_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/remittance_period_closed_overlap
        """
        ctx, _ = self._setup_with_first_remittance(api)
        res = api.create_remittance(
            {"certificate_id": ctx["certificate"]["id"],
             "period_start": "2026-08-31T00:00:00Z",
             "period_end": "2026-09-30T00:00:00Z",
             "collections_cents": 100_000},
            make_originator_headers(ctx["originator"]["id"]))
        validate_error(res, ApiErrorId.ERR_REMITTANCE_PERIOD_OVERLAP)

    def test_disjoint_next_day_period_accepted(self, api):
        """PRD §3.5: "Remittance periods for a certificate are closed intervals, and a new period that shares even a single calendar day with another non-`REVERSED` remittance of the same certificate is rejected with `ERR_REMITTANCE_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/remittance_period_closed_overlap
        """
        ctx, _ = self._setup_with_first_remittance(api)
        res = api.create_remittance(
            {"certificate_id": ctx["certificate"]["id"],
             "period_start": "2026-09-01T00:00:00Z",
             "period_end": "2026-09-30T00:00:00Z",
             "collections_cents": 100_000},
            make_originator_headers(ctx["originator"]["id"]))
        rem = validate_success(res, 201)
        assert rem["status"] == "SCHEDULED"


class TestRemittanceDerivationsAndFundsCheck:
    def test_due_at_derivation(self, api):
        """PRD §3.5: "`due_at` is the agreement's `remittance_due_day` in the month following `period_end`'s month, at 00:00:00Z."

        Design: Corner/calculations/remittance_due_at_derivation
        """
        ctx = setup_pool_with_funded_cert()
        rem = schedule_remittance(ctx["certificate"]["id"], ctx["originator"]["id"],
                                  period_start="2026-08-01T00:00:00Z",
                                  period_end="2026-08-31T00:00:00Z",
                                  collections_cents=100_000)
        # remittance_due_day 15, month following August -> 2026-09-15T00:00:00Z
        assert rem["due_at"].startswith("2026-09-15T00:00:00")

    def test_collections_insufficient_rejected(self, api):
        """PRD §3.5: "A remittance whose `collections_cents` falls short of the interest plus servicing fee is rejected at creation with `ERR_COLLECTIONS_INSUFFICIENT`."

        Design: Corner/validations/collections_insufficient_rejected
        """
        ctx = setup_pool_with_funded_cert()
        # interest 50,000 + fee 2,083 = 52,083 for the August period; 1,000 falls short.
        res = api.create_remittance(
            {"certificate_id": ctx["certificate"]["id"],
             "period_start": "2026-08-01T00:00:00Z",
             "period_end": "2026-08-31T00:00:00Z",
             "collections_cents": 1_000},
            make_originator_headers(ctx["originator"]["id"]))
        validate_error(res, ApiErrorId.ERR_COLLECTIONS_INSUFFICIENT)


class TestPayTransitions:
    def test_certificate_paid_off_auto_transition(self, api):
        """PRD §3.5: "Either way the certificate's `outstanding_principal_cents` is reduced by `principal_portion_cents` and its `cumulative_interest_cents` grows by `interest_portion_cents`; if the outstanding principal thereby reaches zero, the certificate moves from `ACTIVE` to `PAID_OFF`."
        PRD §3.5: "Paying a `SCHEDULED` remittance at or before `due_at` moves it to `PAID`, stamps `paid_at`, and leaves `penalty_cents` at zero."

        Design: Corner/state_machines/certificate_paid_off_auto_transition
        """
        ctx = setup_pool_with_funded_cert()
        cert, originator = ctx["certificate"], ctx["originator"]
        # collections 10,052,083 = interest 50,000 + fee 2,083 + principal 10,000,000
        rem = schedule_remittance(cert["id"], originator["id"],
                                  collections_cents=10_052_083)
        paid = validate_success(
            api.pay_remittance(rem["id"], make_originator_headers(originator["id"])), 200)
        assert paid["status"] == "PAID"
        cert_after = validate_success(api.get_commitment(cert["id"], ADMIN), 200)
        assert cert_after["outstanding_principal_cents"] == 0
        assert cert_after["status"] == "PAID_OFF"

    def test_pay_response_immediately_reflects_effects(self, api):
        """PRD §3.5: "Paying a `SCHEDULED` remittance at or before `due_at` moves it to `PAID`, stamps `paid_at`, and leaves `penalty_cents` at zero."
        PRD §2.4: "At startup, before any adjustment, the clock reads exactly 2026-08-01T00:00:00Z."
        PRD §3.5: "Either way the certificate's `outstanding_principal_cents` is reduced by `principal_portion_cents` and its `cumulative_interest_cents` grows by `interest_portion_cents`; if the outstanding principal thereby reaches zero, the certificate moves from `ACTIVE` to `PAID_OFF`."

        Design: Corner/consistency_model/pay_response_immediately_reflects_effects
        """
        ctx = setup_pool_with_funded_cert()
        cert, originator = ctx["certificate"], ctx["originator"]
        rem = schedule_remittance(cert["id"], originator["id"],
                                  collections_cents=5_052_083)
        paid = validate_success(
            api.pay_remittance(rem["id"], make_originator_headers(originator["id"])), 200)
        assert paid["status"] == "PAID"
        assert paid["penalty_cents"] == 0
        assert paid["paid_at"] is not None
        assert paid["paid_at"].startswith("2026-08-01T00:00:00")
        cert_after = validate_success(api.get_commitment(cert["id"], ADMIN), 200)
        assert cert_after["outstanding_principal_cents"] == 5_000_000
