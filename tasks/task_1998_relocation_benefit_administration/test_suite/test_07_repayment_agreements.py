"""Repayment agreements: proration, installment rounding, payments, default/cure."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    assert_repayment_agreement,
    setup_repayment_case,
    set_clock,
    DATES,
)

MC = TEST_USERS["coordinator_headers"]
FIN = TEST_USERS["finance_headers"]


class TestInstallmentSchedule:
    def test_repayment_installment_floor_remainder(self):
        """PRD §3.8: "The schedule divides that obligation into
        `installments_count` equal to `repayment_window_months`: the regular
        `installment_cents` is the total owed divided by the installment count,
        rounded down to a whole cent, and `final_installment_cents` is whatever
        remains after all but one regular installment are accounted for. The
        rounding-down happens first and the final installment absorbs the
        remainder — that order is pinned, since summing rounded installments
        first would yield a different tail."

        Design: Difficulty/combinatorial_formula/repayment_installment_floor_remainder
        """
        ctx = setup_repayment_case(paid_amount=61000, sign=False)
        agreement = ctx["agreement"]
        assert_repayment_agreement(agreement)
        # authorized 2026-08-01 + 24 months = 2028-08-01; terminated 2027-02-01
        # -> 18 months remaining; owed = round_half_up(61000 x 18/24) = 45750.
        assert agreement["total_owed_cents"] == 45750
        assert agreement["installments_count"] == 24
        # floor(45750 / 24) = 1906; the final installment absorbs the remainder.
        assert agreement["installment_cents"] == 1906
        assert agreement["final_installment_cents"] == 1912
        assert 23 * 1906 + 1912 == 45750, "floor-then-remainder conserves the total"
        assert agreement["status"] == "DRAFT"
        assert agreement["balance_cents"] == 45750

    def test_repayment_total_rounds_half_up_before_installments(self):
        """PRD §3.8: "a `total_owed_cents` equal to the case's
        `total_paid_cents` at closure multiplied by the months remaining and
        divided by `repayment_window_months`, rounded half up to a whole cent."
        PRD §3.8: "the regular `installment_cents` is the total owed divided by
        the installment count, rounded down to a whole cent, and
        `final_installment_cents` is whatever remains after all but one regular
        installment are accounted for."

        Design: Difficulty/combinatorial_formula/repayment_installment_floor_remainder
        """
        ctx = setup_repayment_case(paid_amount=61001, sign=False)
        agreement = ctx["agreement"]
        # round_half_up(61001 x 18/24) = round_half_up(45750.75) = 45751.
        assert agreement["total_owed_cents"] == 45751
        assert agreement["installments_count"] == 24
        assert agreement["installment_cents"] == 1906  # floor(45751 / 24)
        assert agreement["final_installment_cents"] == 1913  # 45751 - 23 x 1906
        assert 23 * 1906 + 1913 == 45751


class TestPaymentBoundary:
    def test_payment_exactly_at_balance_settles(self):
        """PRD §3.8: "A payment larger than the outstanding `balance_cents` is
        rejected with `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422), while a payment
        exactly equal to the balance is accepted and settles the agreement."

        Design: Difficulty/boundary_precision_check/payment_exactly_at_balance_settles
        """
        ctx1 = setup_repayment_case(paid_amount=61000, sign=True)
        ra1 = ctx1["agreement"]
        assert ra1["balance_cents"] == 45750

        # Payment == balance: accepted and settles.
        settled = get_success_data(api_client.record_payment(
            ra1["id"], {"amount_cents": 45750}, FIN))
        assert settled["balance_cents"] == 0
        assert settled["status"] == "SETTLED"
        assert settled["paid_to_date_cents"] == 45750

        # A second agreement at the same balance: payment == balance + 1 fails.
        ctx2 = setup_repayment_case(paid_amount=61000, sign=True,
                                    create_new_policy=False,
                                    policy=ctx1["policy"])
        ra2 = ctx2["agreement"]
        resp = api_client.record_payment(ra2["id"], {"amount_cents": 45751}, FIN)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)

        after = validate_success(api_client.get_repayment_agreement(ra2["id"], MC))
        assert after["balance_cents"] == 45750
        assert after["status"] == "ACTIVE"
        assert after["paid_to_date_cents"] == 0

    def test_payment_reaches_balance_across_installments(self):
        """PRD §3.8: "Each recorded payment raises `paid_to_date_cents` and
        recomputes `balance_cents` as `total_owed_cents` minus
        `paid_to_date_cents`. When a payment brings the balance to zero the
        agreement settles itself"

        Design: Difficulty/boundary_precision_check/payment_exactly_at_balance_settles
        """
        ctx = setup_repayment_case(paid_amount=61000, sign=True)
        ra = ctx["agreement"]

        first = get_success_data(api_client.record_payment(
            ra["id"], {"amount_cents": 43844}, FIN))
        assert first["paid_to_date_cents"] == 43844
        assert first["balance_cents"] == 1906
        assert first["status"] == "ACTIVE"

        # The final payment equals the remaining balance exactly.
        second = get_success_data(api_client.record_payment(
            ra["id"], {"amount_cents": 1906}, FIN))
        assert second["balance_cents"] == 0
        assert second["status"] == "SETTLED"


class TestReversalConservation:
    def test_repayment_payment_reversal_conservation(self):
        """PRD §3.8: "Payments can also be reversed as a compensating action:
        `paid_to_date_cents` falls by the reversed amount — a reversal that
        would drive it below zero is rejected with `ERR_INVALID_REQUEST` — the
        balance is recomputed"
        PRD §3.8: "Each recorded payment raises `paid_to_date_cents` and
        recomputes `balance_cents` as `total_owed_cents` minus
        `paid_to_date_cents`."

        Design: Difficulty/compensating_invariant/repayment_payment_reversal_conservation
        """
        ctx = setup_repayment_case(paid_amount=61000, sign=True)
        ra = ctx["agreement"]

        paid = get_success_data(api_client.record_payment(
            ra["id"], {"amount_cents": 1906}, FIN))
        assert paid["paid_to_date_cents"] == 1906
        assert paid["balance_cents"] == 43844  # 45750 - 1906
        assert paid["status"] == "ACTIVE"

        reversed_ra = get_success_data(api_client.reverse_payment(
            ra["id"], {"amount_cents": 1906}, FIN))
        assert reversed_ra["paid_to_date_cents"] == 0
        assert reversed_ra["balance_cents"] == 45750
        assert reversed_ra["status"] == "ACTIVE"

        # The obligation is conserved at every step.
        final = validate_success(api_client.get_repayment_agreement(ra["id"], MC))
        assert final["paid_to_date_cents"] + final["balance_cents"] == 45750
        assert final["total_owed_cents"] == 45750

    def test_reversal_reopens_settled_agreement(self):
        """PRD §3.8: "a `SETTLED` agreement whose balance reopens returns
        automatically to `ACTIVE`."
        PRD §3.8: "When a payment brings the balance to zero the agreement
        settles itself"

        Design: Difficulty/compensating_invariant/repayment_payment_reversal_conservation
        """
        ctx = setup_repayment_case(paid_amount=61000, sign=True)
        ra = ctx["agreement"]

        settled = get_success_data(api_client.record_payment(
            ra["id"], {"amount_cents": 45750}, FIN))
        assert settled["status"] == "SETTLED"

        reopened = get_success_data(api_client.reverse_payment(
            ra["id"], {"amount_cents": 1906}, FIN))
        assert reopened["status"] == "ACTIVE"
        assert reopened["paid_to_date_cents"] == 43844
        assert reopened["balance_cents"] == 1906
        assert reopened["paid_to_date_cents"] + reopened["balance_cents"] == 45750


class TestDefaultAndCure:
    def test_mark_default_before_due_date_rejected(self):
        """PRD §3.8: "A `FinanceSpecialist` may mark an `ACTIVE` agreement
        `DEFAULTED` only when the logical clock has passed `next_due_date` and
        `paid_to_date_cents` stands below that threshold."
        PRD §3.8: "The agreement activates when the owning employee signs it
        (`DRAFT` → `ACTIVE`): `signed_at` is stamped from the logical clock and
        `next_due_date` falls exactly one calendar month later."

        Design: Corner/state_machines/mark_default_before_due_date_rejected
        """
        ctx = setup_repayment_case(paid_amount=61000, sign=True,
                                   sign_at=DATES["SIGN_AT"])  # signed 2027-02-15
        ra = ctx["agreement"]
        assert ra["status"] == "ACTIVE"
        # Clock is still 2027-02-15; next_due_date is 2027-03-15.
        assert ra["next_due_date"].startswith("2027-03-15")

        resp = api_client.mark_default(ra["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api_client.get_repayment_agreement(ra["id"], MC))
        assert after["status"] == "ACTIVE"

    def test_repayment_default_then_cure_cycle(self):
        """PRD §3.8: "The arrears threshold compares cumulative payments against
        the installments that should have landed by now: the whole calendar
        months elapsed from `signed_at` to the logical clock, capped at one less
        than `installments_count`, multiplied by `installment_cents`."
        PRD §3.8: "when a payment against a `DEFAULTED` agreement raises
        `paid_to_date_cents` to at least the arrears threshold without zeroing
        the balance, the agreement cures itself back to `ACTIVE`."

        Design: Corner/state_machines/repayment_default_then_cure_cycle
        """
        ctx = setup_repayment_case(paid_amount=61000, sign=True,
                                   sign_at=DATES["SIGN_AT"])  # signed 2027-02-15
        ra = ctx["agreement"]

        # Advance past next_due_date 2027-03-15: at 2027-04-01 one whole
        # calendar month has elapsed from signed_at, so 1 x 1906 is due.
        set_clock(DATES["PAST_DUE_AT"])
        defaulted = get_success_data(api_client.mark_default(ra["id"], FIN))
        assert defaulted["status"] == "DEFAULTED"

        # A covering payment (1906 >= 1 x 1906 due) cures the default.
        cured = get_success_data(api_client.record_payment(
            ra["id"], {"amount_cents": 1906}, FIN))
        assert cured["status"] == "ACTIVE"
        assert cured["paid_to_date_cents"] == 1906
        assert cured["balance_cents"] == 43844
