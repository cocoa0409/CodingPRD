"""Interim expense claims: FX rounding, eligibility window, per-day vs pooled caps,
adjudication and payment (PRD §2.8, §3.6)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_expense_claim_payload,
    setup_bag_and_report, setup_declared_lost_report, create_expense_claim,
    make_receipt,
    TEST_USERS, make_passenger_headers,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]


class TestExpenseReimbursementVariants:

    def _claim(self, api, report_id, passenger_id, receipts):
        resp = api.create_expense_claim(
            create_expense_claim_payload(report_id, receipts),
            make_passenger_headers(passenger_id))
        return validate_success(resp, 201)

    def test_domestic_per_day_cap_vs_montreal_pool(self, api):
        """PRD §3.6: "For a `DOMESTIC` report, eligible receipts are grouped by their
        `incurred_on` day, each day's converted total is clipped at the passenger's
        tier daily cap — 7500 cents for `STANDARD`, 10000 cents for `PREMIUM`, 15000
        cents for `ELITE` — and the reimbursable total is the sum of the clipped
        daily amounts; a single 20000-cent day therefore yields 7500 cents for a
        standard passenger. For a `MONTREAL` report, all eligible receipts pool into
        one converted sum clipped only at the 150000-cent pool cap"

        Design: Difficulty/dual_variant_calc/expense_reimbursement_perday_vs_pooled
        """
        ctx_dom = setup_bag_and_report(is_international=False, report_type="DELAYED")
        ctx_intl = setup_bag_and_report(is_international=True, report_type="DELAYED")
        receipts = [
            make_receipt("2026-08-02", 20000, "USD", "toiletries"),
            make_receipt("2026-08-03", 3000, "USD", "shirt"),
        ]
        clm_dom = self._claim(api, ctx_dom["report"]["id"],
                              ctx_dom["passenger"]["id"], receipts)
        clm_intl = self._claim(api, ctx_intl["report"]["id"],
                               ctx_intl["passenger"]["id"], receipts)

        dom = validate_success(
            api.adjudicate_expense_claim(clm_dom["id"], {"decision": "APPROVE"},
                                         ADJUSTER), 200)
        intl = validate_success(
            api.adjudicate_expense_claim(clm_intl["id"], {"decision": "APPROVE"},
                                         ADJUSTER), 200)
        # Domestic: 7500 (capped day 1) + 3000 = 10500; Montreal: pooled 23000.
        assert dom["reimbursable_total_cents"] == 10500
        assert intl["reimbursable_total_cents"] == 23000
        assert dom["status"] == "APPROVED"
        assert intl["status"] == "APPROVED"

    def test_tier_daily_caps_differ(self, api):
        """PRD §3.6: "each day's converted total is clipped at the passenger's tier
        daily cap — 7500 cents for `STANDARD`, 10000 cents for `PREMIUM`, 15000
        cents for `ELITE` — and the reimbursable total is the sum of the clipped
        daily amounts"

        Design: Difficulty/dual_variant_calc/expense_reimbursement_perday_vs_pooled
        """
        ctx_elite = setup_bag_and_report(is_international=False, report_type="DELAYED",
                                         tier="ELITE")
        receipts = [make_receipt("2026-08-02", 20000, "USD", "toiletries"),
                    make_receipt("2026-08-03", 3000, "USD", "shirt")]
        clm = self._claim(api, ctx_elite["report"]["id"],
                          ctx_elite["passenger"]["id"], receipts)
        approved = validate_success(
            api.adjudicate_expense_claim(clm["id"], {"decision": "APPROVE"},
                                         ADJUSTER), 200)
        # ELITE daily cap 15000: day1 clipped to 15000, day2 3000 -> 18000.
        assert approved["reimbursable_total_cents"] == 18000


class TestFxRoundingOrder:

    def test_round_per_receipt_then_sum(self, api):
        """PRD §2.8: "each receipt is converted individually and rounded half up to
        whole cents before any summation, and summing first and rounding afterward
        is expressly forbidden."
        PRD §3.6: "a receipt in `USD` converts at a rate of 1.0, a receipt in `EUR`
        at 1.10, and a receipt in `JPY` at 0.0067"

        Design: Difficulty/combinatorial_formula/expense_fx_round_per_receipt_then_sum
        """
        ctx = setup_bag_and_report(is_international=True, report_type="DELAYED")
        receipts = [
            make_receipt("2026-08-02", 95, "EUR", "adapter"),
            make_receipt("2026-08-03", 95, "EUR", "snacks"),
        ]
        resp = api.create_expense_claim(
            create_expense_claim_payload(ctx["report"]["id"], receipts),
            make_passenger_headers(ctx["passenger"]["id"]))
        claim = validate_success(resp, 201)
        # 95 EUR minor -> round_half_up(95 * 1.10) = round_half_up(104.5) = 105 each.
        assert claim["claimed_total_cents"] == 210
        assert claim["eligible_receipt_count"] == 2

        approved = validate_success(
            api.adjudicate_expense_claim(claim["id"], {"decision": "APPROVE"},
                                         ADJUSTER), 200)
        # Per-receipt rounding pins 105 + 105 = 210 (sum-then-round would give 209).
        assert approved["reimbursable_total_cents"] == 210

    def test_rounding_half_up_boundary(self, api):
        """PRD §2.8: "each receipt is converted individually and rounded half up to
        whole cents before any summation, and summing first and rounding afterward
        is expressly forbidden."
        PRD §3.6: "a receipt in `EUR` at 1.10"

        Design: Difficulty/combinatorial_formula/expense_fx_round_per_receipt_then_sum
        """
        ctx = setup_bag_and_report(is_international=True, report_type="DELAYED")
        # Each 5 EUR minor converts to round_half_up(5.5) = 6; per-receipt order
        # yields 6 + 6 = 12, while the forbidden sum-then-round order yields
        # round_half_up(11.0) = 11.
        receipts = [
            make_receipt("2026-08-02", 5, "EUR", "a"),
            make_receipt("2026-08-02", 5, "EUR", "b"),
        ]
        claim = create_expense_claim(ctx["report"]["id"], ctx["passenger"]["id"],
                                     receipts)
        assert claim["claimed_total_cents"] == 12
        approved = validate_success(
            api.adjudicate_expense_claim(claim["id"], {"decision": "APPROVE"},
                                         ADJUSTER), 200)
        assert approved["reimbursable_total_cents"] == 12


class TestEligibilityWindow:

    def test_out_of_window_receipts_excluded(self, api):
        """PRD §3.6: "The `eligible_receipt_count` records how many of the receipts
        fall inside the eligibility window — from the report's `opened_on` through
        the earlier of the bag's `delivered_on` and the date five days after
        `opened_on`, both bounds inclusive; while `delivered_on` is still null, only
        the five-day bound applies. Receipts outside the window are excluded from
        reimbursement without error."

        Design: Corner/calculations/expense_window_excludes_out_of_window_receipts
        """
        ctx = setup_bag_and_report(is_international=False, report_type="DELAYED")
        receipts = [
            make_receipt("2026-08-02", 4000, "USD", "meals"),
            make_receipt("2026-08-10", 9000, "USD", "late coat"),
        ]
        claim = create_expense_claim(ctx["report"]["id"], ctx["passenger"]["id"],
                                     receipts)
        assert claim["claimed_total_cents"] == 13000
        assert claim["eligible_receipt_count"] == 1
        approved = validate_success(
            api.adjudicate_expense_claim(claim["id"], {"decision": "APPROVE"},
                                         ADJUSTER), 200)
        assert approved["reimbursable_total_cents"] == 4000

    def test_daily_cap_exact_boundary(self, api):
        """PRD §3.6: "each day's converted total is clipped at the passenger's tier
        daily cap — 7500 cents for `STANDARD`, 10000 cents for `PREMIUM`, 15000
        cents for `ELITE`"

        Design: Difficulty/boundary_precision_check/expense_daily_cap_exact_boundary
        """
        ctx = setup_bag_and_report(is_international=False, report_type="DELAYED",
                                   tier="STANDARD")
        clm_a = create_expense_claim(ctx["report"]["id"], ctx["passenger"]["id"],
                                     [make_receipt("2026-08-02", 7500, "USD",
                                                   "at cap")])
        clm_b = create_expense_claim(ctx["report"]["id"], ctx["passenger"]["id"],
                                     [make_receipt("2026-08-03", 7501, "USD",
                                                   "one over")])
        approved_a = validate_success(
            api.adjudicate_expense_claim(clm_a["id"], {"decision": "APPROVE"},
                                         ADJUSTER), 200)
        approved_b = validate_success(
            api.adjudicate_expense_claim(clm_b["id"], {"decision": "APPROVE"},
                                         ADJUSTER), 200)
        # Exactly 7500 is reimbursed in full; 7501 is clipped to 7500.
        assert approved_a["reimbursable_total_cents"] == 7500
        assert approved_b["reimbursable_total_cents"] == 7500

    def test_daily_cap_one_below(self, api):
        """PRD §3.6: "each day's converted total is clipped at the passenger's tier
        daily cap — 7500 cents for `STANDARD`, 10000 cents for `PREMIUM`, 15000
        cents for `ELITE`"

        Design: Difficulty/boundary_precision_check/expense_daily_cap_exact_boundary
        """
        ctx = setup_bag_and_report(is_international=False, report_type="DELAYED",
                                   tier="STANDARD")
        clm = create_expense_claim(ctx["report"]["id"], ctx["passenger"]["id"],
                                   [make_receipt("2026-08-02", 7499, "USD",
                                                 "one below")])
        approved = validate_success(
            api.adjudicate_expense_claim(clm["id"], {"decision": "APPROVE"},
                                         ADJUSTER), 200)
        assert approved["reimbursable_total_cents"] == 7499


class TestExpenseClaimRules:

    def test_state_error_beats_fiscal_cap(self, api):
        """PRD §2.10: "Every request is screened against an ordered validation
        cascade, and the first failing check determines the rejection."
        PRD §2.10 item 6 assigns state checks and item 10 assigns fiscal caps.
        PRD §3.6: "A claim against a damaged or pilfered report, or against a
        delayed report in any other status, is rejected with
        `ERR_REPORT_NOT_ACCEPTING_EXPENSES`."

        Design: Difficulty/priority_pair_validation_conflict/expense_state_beats_fiscal_cap
        """
        ctx = setup_bag_and_report(report_type="DAMAGED")
        resp = api.create_expense_claim(
            create_expense_claim_payload(
                ctx["report"]["id"],
                [make_receipt("2026-08-02", 300001, "USD", "splurge")]),
            make_passenger_headers(ctx["passenger"]["id"]))
        err = validate_error(resp, ApiErrorId.ERR_REPORT_NOT_ACCEPTING_EXPENSES, 409)
        assert err["error_id"] == "ERR_REPORT_NOT_ACCEPTING_EXPENSES"
        assert err["error_id"] != "ERR_EXPENSE_CLAIM_OVER_MAX"

    def test_state_error_also_wins_on_valid_amount_damaged_report(self, api):
        """PRD §3.6: "only `DELAYED` reports in an expense-accepting status qualify:
        `TRACING`, `FOUND_PENDING_DELIVERY`, `DELIVERY_IN_PROGRESS`, `DELIVERED`, or
        `DECLARED_LOST`. A claim against a damaged or pilfered report, or against a
        delayed report in any other status, is rejected with
        `ERR_REPORT_NOT_ACCEPTING_EXPENSES`."

        Design: Difficulty/priority_pair_validation_conflict/expense_state_beats_fiscal_cap
        """
        ctx = setup_bag_and_report(report_type="PILFERED")
        resp = api.create_expense_claim(
            create_expense_claim_payload(
                ctx["report"]["id"],
                [make_receipt("2026-08-02", 4000, "USD", "meals")]),
            make_passenger_headers(ctx["passenger"]["id"]))
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_ACCEPTING_EXPENSES, 409)

    def test_claim_over_max_in_valid_state(self, api):
        """PRD §3.6: "This pre-cap total is validated at creation: a claim whose
        converted total exceeds 300000 cents is rejected with
        `ERR_EXPENSE_CLAIM_OVER_MAX` (HTTP 422)."

        Design: Corner/validations/expense_claim_over_max_in_valid_state
        """
        ctx = setup_bag_and_report(is_international=False, report_type="DELAYED")
        resp = api.create_expense_claim(
            create_expense_claim_payload(
                ctx["report"]["id"],
                [make_receipt("2026-08-02", 300001, "USD", "huge")]),
            make_passenger_headers(ctx["passenger"]["id"]))
        validate_error(resp, ApiErrorId.ERR_EXPENSE_CLAIM_OVER_MAX, 422)

    def test_ownership_other_passenger_forbidden(self, api):
        """PRD §3.6: "Only the report's owning passenger may file — a caller whose
        `X-User-ID` differs from the report's `passenger_id` is rejected with
        `ERR_NOT_RESOURCE_OWNER`"

        Design: Corner/validations/ownership_other_passenger_claim_forbidden
        """
        ctx = setup_bag_and_report(is_international=False, report_type="DELAYED")
        other = get_success_data(api.create_passenger(
            {"full_name": "Sam Other", "email": "sam@x.com", "tier": "STANDARD"},
            AGENT))
        resp = api.create_expense_claim(
            create_expense_claim_payload(
                ctx["report"]["id"],
                [make_receipt("2026-08-02", 4000, "USD", "meals")]),
            make_passenger_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)


class TestAdjudicationAndPayment:

    def test_adjudicate_twice_not_idempotent(self, api):
        """PRD §3.6: "Adjudication belongs to the `ClaimsAdjuster`, who supplies a
        `decision` of `APPROVE` or `REJECT` for a claim in `SUBMITTED` — acting on a
        claim in any other status is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/adjudicate_twice_not_idempotent
        """
        ctx = setup_bag_and_report(is_international=False, report_type="DELAYED")
        claim = create_expense_claim(ctx["report"]["id"], ctx["passenger"]["id"],
                                     [make_receipt("2026-08-02", 4000, "USD",
                                                   "meals")])
        first = validate_success(
            api.adjudicate_expense_claim(claim["id"], {"decision": "APPROVE"},
                                         ADJUSTER), 200)
        assert first["status"] == "APPROVED"
        assert first["reimbursable_total_cents"] == 4000

        resp = api.adjudicate_expense_claim(claim["id"], {"decision": "APPROVE"},
                                            ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        current = get_success_data(api.get_expense_claim(claim["id"], ADJUSTER))
        assert current["status"] == "APPROVED"
        assert current["reimbursable_total_cents"] == 4000

    def test_pay_submitted_claim_rejected(self, api):
        """PRD §3.6: "the claim must be `APPROVED` (otherwise
        `ERR_CLAIM_NOT_PAYABLE`)"

        Design: Corner/errors/pay_submitted_claim_rejected
        """
        ctx = setup_bag_and_report(is_international=False, report_type="DELAYED")
        claim = create_expense_claim(ctx["report"]["id"], ctx["passenger"]["id"],
                                     [make_receipt("2026-08-02", 4000, "USD",
                                                   "meals")])
        resp = api.pay_expense_claim(claim["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_PAYABLE, 409)
        current = get_success_data(api.get_expense_claim(claim["id"], ADJUSTER))
        assert current["status"] == "SUBMITTED"
        report_now = get_success_data(api.get_report(ctx["report"]["id"], ADJUSTER))
        assert report_now["expenses_paid_cents"] == 0
