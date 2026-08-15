"""Service purchase pricing, installment schedules, overlap rules, plan money."""
import pytest

from test_helpers import (
    ApiErrorId,
    accept_purchase,
    assert_purchase_money_conserved,
    assert_purchase_payment,
    assert_service_purchase,
    create_member,
    create_purchase,
    get_purchase,
    list_payments_sorted,
    make_member_headers,
    pay_installment,
    quote_purchase,
    reconcile_member_history,
    record_death,
    set_clock,
    setup_fund_and_employer,
    setup_plan_active_purchase,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST


def _setup_priced_pair(api):
    """Two members with identical salary (6,000,000) and identical 2.0-year
    MILITARY purchases; member A hired 2024-06-01 (inside the five-year flat
    window at clock 2026-08-01), member B hired 2010-01-01 (outside it)."""
    fund, employer = setup_fund_and_employer()
    member_a = create_member(employer["id"], full_name="Flat Winifred",
                             date_of_birth="1980-01-01", hire_date="2024-06-01")
    reconcile_member_history(employer["id"], [{
        "member_id": member_a["id"], "fiscal_year": 2023,
        "salary_cents": 6_000_000}])
    member_b = create_member(employer["id"], full_name="Actuarial Alice",
                             date_of_birth="1980-01-01", hire_date="2010-01-01")
    reconcile_member_history(employer["id"], [{
        "member_id": member_b["id"], "fiscal_year": 2024,
        "salary_cents": 6_000_000}])
    purchase_a = quote_purchase(create_purchase(member_a["id"])["id"])
    purchase_b = quote_purchase(create_purchase(member_b["id"])["id"])
    return member_a, member_b, purchase_a, purchase_b


class TestDualVariantPurchasePricing:
    def test_flat_window_member_gets_flat_variant(self, api):
        """PRD §3.4: "`flat_cost_cents` is the product of 0.10, the current
        annual salary, and `years_purchased`, rounded half-up to whole cents."
        PRD §3.4: "if the quote date falls within five years of the member's
        `hire_date` — that is, `hire_date` plus five years is on or after the
        quote date — the member is entitled to the flat rate and
        `cost_variant` is `FLAT`; after that window closes, `cost_variant` is
        `ACTUARIAL`."

        Design: Difficulty/dual_variant_calc/purchase_cost_flat_vs_actuarial_same_inputs
        """
        _ma, _mb, purchase_a, _pb = _setup_priced_pair(api)
        assert_service_purchase(purchase_a)
        assert purchase_a["flat_cost_cents"] == 1_200_000, (
            f"0.10 * 6,000,000 * 2.0 must be 1,200,000, "
            f"got {purchase_a['flat_cost_cents']}")
        assert purchase_a["actuarial_cost_cents"] == 4_200_000, (
            f"age 46 -> 14 years to 60 -> factor 0.35: 6,000,000 * 2.0 * 0.35 "
            f"must be 4,200,000, got {purchase_a['actuarial_cost_cents']}")
        assert purchase_a["cost_variant"] == "FLAT"
        assert purchase_a["quoted_cost_cents"] == 1_200_000
        assert purchase_a["status"] == "QUOTED"

    def test_post_window_member_gets_actuarial_variant(self, api):
        """PRD §3.4: "The age factor is 0.35 when `years_to_60` is at least
        10, else 0.28 when it is at least 5, else 0.22."
        PRD §3.4: "The system always computes both cost variants and stores
        both; the variant selector then decides which one the member actually
        pays."

        Design: Difficulty/dual_variant_calc/purchase_cost_flat_vs_actuarial_same_inputs
        """
        _ma, _mb, purchase_a, purchase_b = _setup_priced_pair(api)
        assert purchase_b["cost_variant"] == "ACTUARIAL"
        assert purchase_b["quoted_cost_cents"] == 4_200_000
        assert purchase_b["flat_cost_cents"] == 1_200_000, (
            "both variants are stored even when ACTUARIAL is selected")
        assert purchase_a["quoted_cost_cents"] != purchase_b["quoted_cost_cents"], (
            "identical salary/years must price differently across the window")


def _setup_odd_salary_member(api, full_name="Remainder Rita"):
    """Member hired 2024-06-01 (FLAT window), DOB 1980-01-01, one ACCEPTED
    FY2023 line at salary 5,000,005 (contribution 400,000)."""
    fund, employer = setup_fund_and_employer()
    member = create_member(employer["id"], full_name=full_name,
                           date_of_birth="1980-01-01", hire_date="2024-06-01")
    reconcile_member_history(employer["id"], [{
        "member_id": member["id"], "fiscal_year": 2023,
        "salary_cents": 5_000_005, "contribution_cents": 400_000}])
    return fund, employer, member


class TestInstallmentSchedule:
    def test_remainder_lands_on_last_payment(self, api):
        """PRD §3.4: "The schedule divides the quoted cost into equal monthly
        payments with a pinned rounding order: the per-installment amount is
        `quoted_cost_cents` divided by `installment_count`, rounded half-up to
        whole cents; that rounded per-installment amount is assigned to each
        of the first `installment_count` − 1 payments; and the final payment
        receives the remainder — the quoted cost minus the per-installment
        amount times `installment_count` − 1 — which may be larger than the
        per-installment amount."

        Design: Difficulty/combinatorial_formula/installment_rounding_remainder_on_last_payment
        """
        _f, _e, member = _setup_odd_salary_member(api)
        purchase = quote_purchase(create_purchase(member["id"])["id"])
        assert purchase["quoted_cost_cents"] == 1_000_001
        purchase = accept_purchase(purchase["id"], member["id"], 12)
        assert purchase["status"] == "PLAN_ACTIVE"
        payments = list_payments_sorted(purchase["id"])
        assert len(payments) == 12
        for payment in payments[:11]:
            assert_purchase_payment(payment)
            assert payment["amount_cents"] == 83_333, (
                f"seq {payment['sequence_number']} must be the rounded "
                f"per-installment 83,333, got {payment['amount_cents']}")
        assert_purchase_payment(payments[11])
        assert payments[11]["amount_cents"] == 83_338, (
            f"final payment takes the remainder 1,000,001 - 11*83,333 = "
            f"83,338, got {payments[11]['amount_cents']}")

    def test_schedule_sums_to_quoted_cost_and_due_dates_roll_monthly(self, api):
        """PRD §3.4: "Each payment's `due_date` is the first day of the month
        that is its `sequence_number` months after the month of acceptance —
        sequence 1 falls on the first of the month following acceptance — and
        every generated payment begins in `PENDING` with `applied_at` null."
        PRD §3.4: "On acceptance the purchase moves `QUOTED → PLAN_ACTIVE`,
        `balance_due_cents` is set equal to `quoted_cost_cents`, and the
        installment schedule is generated."

        Design: Difficulty/combinatorial_formula/installment_rounding_remainder_on_last_payment
        """
        _f, _e, member = _setup_odd_salary_member(api)
        purchase = quote_purchase(create_purchase(member["id"])["id"])
        purchase = accept_purchase(purchase["id"], member["id"], 12)
        assert purchase["balance_due_cents"] == 1_000_001
        payments = list_payments_sorted(purchase["id"])
        total = sum(p["amount_cents"] for p in payments)
        assert total == 1_000_001 == purchase["quoted_cost_cents"]
        # accepted at clock 2026-08-01 -> seq 1 due 2026-09-01, seq 12 due 2027-08-01
        assert payments[0]["due_date"] == "2026-09-01"
        assert payments[11]["due_date"] == "2027-08-01"
        assert all(p["status"] == "PENDING" for p in payments)


class TestPurchasePeriodOverlap:
    def _member_with_fy2023_credit(self, api):
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Overlap Owen")
        reconcile_member_history(employer["id"], [{
            "member_id": member["id"], "fiscal_year": 2023,
            "salary_cents": 6_000_000}])
        return member

    def test_non_overlapping_period_accepted(self, api):
        """PRD §3.4: "The service period is a closed interval: it includes
        both its start and its end day, and any shared day with a fiscal year
        already credited to the member — meaning any fiscal year in which the
        member holds an `ACCEPTED` contribution line — is an overlap, rejected
        with `ERR_PURCHASE_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/purchase_period_closed_interval_touching_credit_rejected
        """
        member = self._member_with_fy2023_credit(api)
        purchase = create_purchase(member["id"], "PRIOR_SERVICE",
                                   "2024-01-01", "2025-12-31", 2.0)
        assert purchase["status"] == "REQUESTED", (
            "period 2024-01-01..2025-12-31 shares no day with credited FY2023")

    def test_shared_boundary_day_is_an_overlap(self, api):
        """PRD §3.4: "The service period is a closed interval: it includes
        both its start and its end day, and any shared day with a fiscal year
        already credited to the member — meaning any fiscal year in which the
        member holds an `ACCEPTED` contribution line — is an overlap, rejected
        with `ERR_PURCHASE_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/purchase_period_closed_interval_touching_credit_rejected
        """
        member = self._member_with_fy2023_credit(api)
        ok = create_purchase(member["id"], "PRIOR_SERVICE",
                             "2024-01-01", "2025-12-31", 2.0)
        res = api.create_service_purchase(
            member["id"],
            {"purchase_type": "PRIOR_SERVICE",
             "service_period_start": "2023-12-31",
             "service_period_end": "2024-12-30",
             "years_purchased": 1.0},
            make_member_headers(member["id"]))
        validate_error(res, ApiErrorId.ERR_PURCHASE_PERIOD_OVERLAP)
        purchases, meta = validate_paginated(
            api.list_member_service_purchases(member["id"], ANALYST))
        assert meta["total_count"] == 1
        assert purchases[0]["id"] == ok["id"]


class TestExpiredQuoteAcceptance:
    def _setup_expired_quote_with_late_overlap(self, api):
        """Purchase quoted at clock 2026-01-01 while only FY2022 is credited;
        FY2023 (overlapping the purchase period) is credited afterwards; the
        clock then advances past quote_expires_at (2026-04-01)."""
        set_clock("2026-01-01T00:00:00Z")
        fund, employer = setup_fund_and_employer(set_clock_to=None)
        member = create_member(employer["id"], full_name="Temporal Tessa")
        reconcile_member_history(employer["id"], [{
            "member_id": member["id"], "fiscal_year": 2022,
            "salary_cents": 5_500_000}])
        purchase = create_purchase(member["id"], "PRIOR_SERVICE",
                                   "2023-06-01", "2024-05-31", 1.0)
        quoted = quote_purchase(purchase["id"])
        reconcile_member_history(employer["id"], [{
            "member_id": member["id"], "fiscal_year": 2023,
            "salary_cents": 6_000_000}])
        set_clock("2026-04-02T00:00:00Z")
        return member, quoted

    def test_accept_after_expiry_returns_quote_expired_not_overlap(self, api):
        """PRD §2.8: "9. **Clock-relative windows** — quote expiry, appeal
        window, claim deadline (`ERR_QUOTE_EXPIRED`,
        `ERR_APPEAL_WINDOW_CLOSED`, `ERR_CLAIM_DEADLINE_PASSED`). 10.
        **Interval and uniqueness constraints** — report period overlap,
        purchase period overlap, duplicate line period, installment bounds
        (`ERR_REPORT_PERIOD_OVERLAP`, `ERR_PURCHASE_PERIOD_OVERLAP`,
        `ERR_DUPLICATE_LINE_PERIOD`, `ERR_INVALID_REQUEST`)."
        PRD §3.4: "An acceptance attempted after expiry is rejected with
        `ERR_QUOTE_EXPIRED` (HTTP 422), and the purchase itself moves
        `QUOTED → EXPIRED` in the same stroke — expiry is lazy, discovered at
        the moment of acceptance, and it is permanent."

        Design: Difficulty/priority_pair_validation_conflict/accept_expired_quote_with_overlapping_period_temporal_wins
        """
        member, quoted = self._setup_expired_quote_with_late_overlap(api)
        res = api.accept_service_purchase(
            quoted["id"], {"installment_count": 6},
            make_member_headers(member["id"]))
        validate_error(res, ApiErrorId.ERR_QUOTE_EXPIRED)

    def test_expired_accept_moves_purchase_to_expired(self, api):
        """PRD §3.4: "An acceptance attempted after expiry is rejected with
        `ERR_QUOTE_EXPIRED` (HTTP 422), and the purchase itself moves
        `QUOTED → EXPIRED` in the same stroke — expiry is lazy, discovered at
        the moment of acceptance, and it is permanent."
        PRD §3.4: "Every quote carries a shelf life: `quote_expires_at` is the
        quote datetime plus 90 days, after which the offer lapses."

        Design: Difficulty/priority_pair_validation_conflict/accept_expired_quote_with_overlapping_period_temporal_wins
        """
        member, quoted = self._setup_expired_quote_with_late_overlap(api)
        assert quoted["quote_expires_at"] == "2026-04-01T00:00:00Z"
        validate_error(
            api.accept_service_purchase(
                quoted["id"], {"installment_count": 6},
                make_member_headers(member["id"])),
            ApiErrorId.ERR_QUOTE_EXPIRED)
        after = get_purchase(quoted["id"])
        assert after["status"] == "EXPIRED"
        payments, meta = validate_paginated(
            api.list_purchase_payments(quoted["id"], ANALYST))
        assert meta["total_count"] == 0


class TestPlanMoneyConservation:
    def test_balance_invariant_holds_across_payments(self, api):
        """PRD §3.4: "On success the payment moves `PENDING → APPLIED`, its
        `applied_at` is set to the logical clock, the purchase's
        `balance_due_cents` is reduced by the payment's `amount_cents`, and
        the purchase's `version` increments by 1 — which is precisely what
        serializes consecutive installments."

        Design: Difficulty/compensating_invariant/purchase_plan_money_conservation_through_payment_and_cancel
        """
        _f, _e, member = _setup_odd_salary_member(api, "Conserve Connie")
        ctx = setup_plan_active_purchase(member["id"])
        purchase, payments = ctx["purchase"], ctx["payments"]
        assert purchase["balance_due_cents"] == 1_000_001
        assert_purchase_money_conserved(purchase, payments)

        purchase = pay_installment(purchase["id"], payments[0]["id"],
                                   purchase["version"], member["id"])
        assert purchase["balance_due_cents"] == 916_668, (
            f"1,000,001 - 83,333 = 916,668, got {purchase['balance_due_cents']}")
        after1 = list_payments_sorted(purchase["id"])
        assert_purchase_money_conserved(purchase, after1)

        purchase = pay_installment(purchase["id"], payments[1]["id"],
                                   purchase["version"], member["id"])
        assert purchase["balance_due_cents"] == 833_335
        after2 = list_payments_sorted(purchase["id"])
        assert_purchase_money_conserved(purchase, after2)
        assert after2[0]["status"] == "APPLIED"
        assert after2[1]["status"] == "APPLIED"

    def test_cancel_refunds_applied_payments_and_zeroes_balance(self, api):
        """PRD §3.4: "Cancelling a `PLAN_ACTIVE` purchase refunds it: every
        payment in `APPLIED` moves to `REFUNDED`, the purchase's
        `refunded_total_cents` becomes the sum of those applied amounts, and
        `balance_due_cents` is zeroed."

        Design: Difficulty/compensating_invariant/purchase_plan_money_conservation_through_payment_and_cancel
        """
        _f, _e, member = _setup_odd_salary_member(api, "Conserve Connie")
        ctx = setup_plan_active_purchase(member["id"])
        purchase, payments = ctx["purchase"], ctx["payments"]
        purchase = pay_installment(purchase["id"], payments[0]["id"],
                                   purchase["version"], member["id"])
        purchase = pay_installment(purchase["id"], payments[1]["id"],
                                   purchase["version"], member["id"])
        cancelled = validate_success(api.cancel_service_purchase(
            purchase["id"], make_member_headers(member["id"])), 200)
        assert_service_purchase(cancelled)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["balance_due_cents"] == 0
        assert cancelled["refunded_total_cents"] == 166_666, (
            f"two applied installments (2 x 83,333) must be refunded, "
            f"got {cancelled['refunded_total_cents']}")
        after = list_payments_sorted(purchase["id"])
        assert after[0]["status"] == "REFUNDED"
        assert after[1]["status"] == "REFUNDED"
        assert all(p["status"] == "PENDING" for p in after[2:])


class TestPurchaseCompletion:
    def test_final_payment_completes_and_posts_service_credit(self, api):
        """PRD §3.4: "When a payment application brings `balance_due_cents` to
        zero, the purchase moves `PLAN_ACTIVE → COMPLETED` automatically and
        the member's `total_service_years` is recomputed to include the
        purchased `years_purchased` — the service credit posts at completion,
        not before."

        Design: Corner/endpoints/purchase_completion_posts_service_credit_to_member
        """
        _f, _e, member = _setup_odd_salary_member(api, "Complete Carla")
        ctx = setup_plan_active_purchase(member["id"])
        purchase, payments = ctx["purchase"], ctx["payments"]
        version = purchase["version"]
        for payment in payments:
            purchase = pay_installment(purchase["id"], payment["id"],
                                       version, member["id"])
            version = purchase["version"]
        assert purchase["status"] == "COMPLETED"
        assert purchase["balance_due_cents"] == 0
        member_after = validate_success(api.get_member(member["id"], ANALYST),
                                        200)
        assert member_after["total_service_years"] == pytest.approx(3.0), (
            f"1.0 credited year + 2.0 purchased years = 3.0, "
            f"got {member_after['total_service_years']}")
        assert member_after["current_annual_salary_cents"] == 5_000_005, (
            "purchases add service, not salary")


class TestPaymentStateGates:
    def test_payment_on_cancelled_plan_returns_plan_not_active(self, api):
        """PRD §3.4: "Payment is only possible while the purchase is in
        `PLAN_ACTIVE`; paying against a purchase in any other state is
        `ERR_PLAN_NOT_ACTIVE` (HTTP 409), and paying a payment that is not
        itself `PENDING` is a generic `ERR_INVALID_STATE`."

        Design: Corner/validations/payment_before_plan_active_returns_plan_not_active
        """
        _f, _e, member = _setup_odd_salary_member(api, "Plan Paige")
        ctx = setup_plan_active_purchase(member["id"])
        purchase, payments = ctx["purchase"], ctx["payments"]
        purchase = pay_installment(purchase["id"], payments[0]["id"],
                                   purchase["version"], member["id"])
        validate_success(api.cancel_service_purchase(
            purchase["id"], make_member_headers(member["id"])), 200)
        current_version = get_purchase(purchase["id"])["version"]
        res = api.apply_payment(
            purchase["id"],
            {"payment_id": payments[1]["id"],
             "expected_purchase_version": current_version},
            make_member_headers(member["id"]))
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_ACTIVE)
        after = list_payments_sorted(purchase["id"])
        assert after[1]["status"] == "PENDING"
        assert after[0]["status"] == "REFUNDED"


class TestDeceasedMemberLockout:
    def test_purchase_on_deceased_member_returns_error(self, api):
        """PRD §3.5: "Operations on a `DECEASED` member's account — new
        purchases, new applications — are blocked with
        `ERR_MEMBER_DECEASED`."

        Design: Corner/validations/purchase_on_deceased_member_returns_error
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Deceased Drew")
        reconcile_member_history(employer["id"], [{
            "member_id": member["id"], "fiscal_year": 2023,
            "salary_cents": 6_000_000}])
        record_death(member["id"], "2026-08-01")
        res = api.create_service_purchase(
            member["id"],
            {"purchase_type": "MILITARY",
             "service_period_start": "2005-01-01",
             "service_period_end": "2006-12-31",
             "years_purchased": 2.0},
            ANALYST)
        validate_error(res, ApiErrorId.ERR_MEMBER_DECEASED)
        _purchases, meta = validate_paginated(
            api.list_member_service_purchases(member["id"], ANALYST))
        assert meta["total_count"] == 0
