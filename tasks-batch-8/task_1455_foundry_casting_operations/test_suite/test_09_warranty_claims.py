"""Warranty claims: filing gates, review conversation cycles, appeal, the
dual-variant settlement credit, budget enforcement, and filing precedence."""
from test_helpers import (
    TEST_USERS,
    accept_casting,
    file_claim,
    get_claim,
    get_order,
    make_customer_headers,
    review,
    set_clock,
    setup_approved_claim,
    setup_casting_at_final_inspection,
    setup_fulfilled_order,
    validate_error,
    validate_success,
)

WM_1 = TEST_USERS["wm_1_headers"]
WM_2 = TEST_USERS["wm_2_headers"]


class TestClaimFilingGate:
    def test_claim_filing_rejected_while_order_in_production(self, api):
        """PRD §3.9: "A `Customer` files a claim against an order that is
        `FULFILLED` or `CLOSED` — filing against any other order state is
        `ERR_INVALID_STATE`"

        Design: Difficulty/cross_entity_state_dependency/claim_filing_requires_order_fulfilled
        """
        ctx = setup_casting_at_final_inspection()
        assert get_order(ctx["order"]["id"])["status"] == "IN_PRODUCTION"
        res = api.create_claim(
            {"order_id": ctx["order"]["id"], "claim_type": "DEFECT",
             "claim_qty": 1, "claimed_amount_cents": 50000},
            make_customer_headers(ctx["customer"]["id"]))
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_claim_filing_succeeds_once_order_fulfilled(self, api):
        """PRD §3.9: "A `Customer` files a claim against an order that is
        `FULFILLED` or `CLOSED`" and "The filer must own the order
        (`ERR_FORBIDDEN_OWNER`), and the claim's `customer_id` is copied from
        the order rather than supplied."

        Design: Difficulty/cross_entity_state_dependency/claim_filing_requires_order_fulfilled
        """
        ctx = setup_casting_at_final_inspection()
        accept_casting(ctx["castings"][0][0]["id"])
        assert get_order(ctx["order"]["id"])["status"] == "FULFILLED"
        claim = validate_success(api.create_claim(
            {"order_id": ctx["order"]["id"], "claim_type": "DEFECT",
             "claim_qty": 1, "claimed_amount_cents": 50000},
            make_customer_headers(ctx["customer"]["id"])), expected_status=201)
        assert claim["status"] == "FILED"
        assert claim["customer_id"] == ctx["customer"]["id"]


class TestWarrantyCreditVariants:
    def _settled_pair(self, api):
        """One FULFILLED order carrying two APPROVED claims, settled by wm_2:
        A DEFECT (STANDARD) and B MACHINING_SHORTFALL (MACHINING_ALLOWANCE)."""
        ctx = setup_fulfilled_order()
        claim_a = file_claim(ctx, claim_type="DEFECT", claim_qty=4,
                             claimed_amount_cents=250000)
        review(claim_a["id"], "START", WM_1)
        review(claim_a["id"], "APPROVE", WM_1)
        claim_b = file_claim(ctx, claim_type="MACHINING_SHORTFALL", claim_qty=4,
                             claimed_amount_cents=250000, freight_cents=5000)
        review(claim_b["id"], "START", WM_1)
        review(claim_b["id"], "APPROVE", WM_1)
        settled_a = validate_success(api.settle_claim(claim_a["id"], WM_2))
        settled_b = validate_success(api.settle_claim(claim_b["id"], WM_2))
        return ctx, claim_a, claim_b, settled_a, settled_b

    def test_standard_variant_settles_full_unit_price(self, api):
        """PRD §3.9: "Under the `STANDARD` variant — selected by `claim_type`
        `DEFECT` — the credit is the lesser of `claimed_amount_cents` and
        `unit_price_cents` multiplied by `claim_qty`; freight is ignored." and
        "A successful settlement records the credit as `settled_credit_cents`,
        records which `credit_variant_applied` (`STANDARD` or
        `MACHINING_ALLOWANCE`)".

        Design: Difficulty/dual_variant_calc/warranty_credit_standard_vs_machining_allowance
        """
        ctx, claim_a, claim_b, settled_a, settled_b = self._settled_pair(api)
        # min(250000, 100000 * 4) = 250000
        assert settled_a["settled_credit_cents"] == 250000
        assert settled_a["credit_variant_applied"] == "STANDARD"
        assert settled_a["status"] == "SETTLED"

    def test_machining_allowance_variant_settles_fraction_plus_freight(self, api):
        """PRD §3.9: "Under the `MACHINING_ALLOWANCE` variant — selected by
        `MACHINING_SHORTFALL` — the credit is the lesser of
        `claimed_amount_cents` and the sum of the per-unit allowance plus
        freight, where the allowance portion is `unit_price_cents` multiplied
        by `machining_allowance_pct` multiplied by `claim_qty`, rounded half-up
        to whole cents before `freight_cents` is added" and "adds the credit to
        the order's `settled_total_cents`".

        Design: Difficulty/dual_variant_calc/warranty_credit_standard_vs_machining_allowance
        """
        ctx, claim_a, claim_b, settled_a, settled_b = self._settled_pair(api)
        # min(250000, round(100000 * 0.15 * 4) + 5000) = min(250000, 65000)
        assert settled_b["settled_credit_cents"] == 65000
        assert settled_b["credit_variant_applied"] == "MACHINING_ALLOWANCE"
        # Same qty/claimed/price diverge across the two variants.
        assert settled_a["settled_credit_cents"] != settled_b["settled_credit_cents"]
        assert get_order(ctx["order"]["id"])["settled_total_cents"] == 315000


class TestClaimReviewCycles:
    def test_info_request_loop_closes_via_customer_respond(self, api):
        """PRD §3.9: "the manager may `START` review (`FILED → UNDER_REVIEW`),
        `APPROVE` (`UNDER_REVIEW → APPROVED`), `DENY` (`UNDER_REVIEW →
        DENIED`), or `REQUEST_INFO` (`UNDER_REVIEW → INFO_REQUESTED`); the
        owning customer may `RESPOND` to an information request
        (`INFO_REQUESTED → UNDER_REVIEW`) or `APPEAL` a denial (`DENIED →
        UNDER_REVIEW`), with either customer action rejected as
        `ERR_FORBIDDEN_OWNER` when the caller's `X-User-ID` differs from the
        claim's `customer_id`."

        Design: Difficulty/non_linear_state_machine/warranty_claim_info_and_appeal_cycles
        """
        ctx = setup_fulfilled_order()
        claim = file_claim(ctx, claim_type="DEFECT", claim_qty=1,
                           claimed_amount_cents=50000)
        customer = make_customer_headers(ctx["customer"]["id"])
        assert review(claim["id"], "START", WM_1)["status"] == "UNDER_REVIEW"
        assert review(claim["id"], "REQUEST_INFO", WM_1)["status"] == "INFO_REQUESTED"
        assert review(claim["id"], "RESPOND", customer)["status"] == "UNDER_REVIEW"

    def test_appeal_loop_reopens_denied_claim_once(self, api):
        """PRD §3.9: "the owning customer may `RESPOND` to an information request
        (`INFO_REQUESTED → UNDER_REVIEW`) or `APPEAL` a denial (`DENIED →
        UNDER_REVIEW`), with either customer action rejected as
        `ERR_FORBIDDEN_OWNER` when the caller's `X-User-ID` differs from the
        claim's `customer_id`." and "A claim carries exactly one appeal:
        `APPEAL` requires `appeal_used` still false and sets it true; a second
        appeal is `ERR_APPEAL_ALREADY_USED`." and "Approval and denial both
        stamp `reviewed_by_user_id` with the deciding manager."

        Design: Difficulty/non_linear_state_machine/warranty_claim_info_and_appeal_cycles
        """
        ctx = setup_fulfilled_order()
        claim = file_claim(ctx, claim_type="DEFECT", claim_qty=1,
                           claimed_amount_cents=50000)
        customer = make_customer_headers(ctx["customer"]["id"])
        review(claim["id"], "START", WM_1)
        assert review(claim["id"], "DENY", WM_1)["status"] == "DENIED"
        appealed = review(claim["id"], "APPEAL", customer)
        assert appealed["status"] == "UNDER_REVIEW"
        assert appealed["appeal_used"] is True
        approved = review(claim["id"], "APPROVE", WM_1)
        assert approved["status"] == "APPROVED"
        assert approved["reviewed_by_user_id"] == "wm_1"


class TestSettleGuards:
    def test_settle_denied_claim_state_beats_budget(self, api):
        """PRD §2.10: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order and surfaces the first
        failure." and "Fourth, state feasibility: the target resource must be in
        a state from which the requested transition exists, with terminal
        resources rejected as `ERR_ALREADY_TERMINAL` and other mismatches as
        `ERR_INVALID_STATE`." and "Ninth, fiscal and capacity accounting
        (`ERR_FURNACE_CAPACITY_EXCEEDED`, `ERR_LINE_MINUTES_EXCEEDED`,
        `ERR_ORDER_QUANTITY_EXCEEDED`, `ERR_RETURN_LOT_INSUFFICIENT`,
        `ERR_METAL_INSUFFICIENT`, `ERR_SAND_INSUFFICIENT`,
        `ERR_WARRANTY_BUDGET_EXCEEDED`, `ERR_SAND_MASS_MISMATCH`)."

        Design: Difficulty/priority_pair_validation_conflict/settle_denied_claim_state_beats_budget
        """
        # Budget 1000 < would-be credit 250000, but the claim is DENIED.
        ctx = setup_fulfilled_order(warranty_budget_cents=1000)
        claim = file_claim(ctx, claim_type="DEFECT", claim_qty=4,
                           claimed_amount_cents=250000)
        review(claim["id"], "START", WM_1)
        review(claim["id"], "DENY", WM_1)
        res = api.settle_claim(claim["id"], WM_2)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_settle_denied_claim_leaves_no_side_effects(self, api):
        """PRD §3.9: "A successful settlement records the credit as
        `settled_credit_cents`, records which `credit_variant_applied`
        (`STANDARD` or `MACHINING_ALLOWANCE`), adds the credit to the order's
        `settled_total_cents`, and moves the claim to `SETTLED`, which is
        terminal." — a rejected settlement records nothing: "A new claim is
        `FILED` with `appeal_used` false and `settled_credit_cents` null."

        Design: Difficulty/priority_pair_validation_conflict/settle_denied_claim_state_beats_budget
        """
        ctx = setup_fulfilled_order(warranty_budget_cents=1000)
        claim = file_claim(ctx, claim_type="DEFECT", claim_qty=4,
                           claimed_amount_cents=250000)
        review(claim["id"], "START", WM_1)
        review(claim["id"], "DENY", WM_1)
        validate_error(api.settle_claim(claim["id"], WM_2),
                       "ERR_INVALID_STATE", expected_status=409)
        after = get_claim(claim["id"])
        assert after["status"] == "DENIED"
        assert after["settled_credit_cents"] is None
        assert get_order(ctx["order"]["id"])["settled_total_cents"] == 0

    def test_settle_over_budget_rejected(self, api):
        """PRD §3.9: "The computed credit must fit the order's remaining
        warranty budget — it may not exceed `warranty_budget_cents` minus
        `settled_total_cents`, or settlement is rejected with
        `ERR_WARRANTY_BUDGET_EXCEEDED` (HTTP 422)."

        Design: Corner/errors/settle_over_budget_rejected
        """
        ctx = setup_approved_claim(claim_type="DEFECT", claim_qty=1,
                                   claimed_amount_cents=100000,
                                   warranty_budget_cents=60000)
        # STANDARD credit min(100000, 100000 * 1) = 100000 > 60000 remaining.
        res = api.settle_claim(ctx["claim"]["id"], WM_2)
        validate_error(res, "ERR_WARRANTY_BUDGET_EXCEEDED", expected_status=422)
        after = get_claim(ctx["claim"]["id"])
        assert after["status"] == "APPROVED"
        assert get_order(ctx["order"]["id"])["settled_total_cents"] == 0


class TestWarrantyWindow:
    def test_claim_after_warranty_window_expired(self, api):
        """PRD §3.9: "and within `warranty_months` of the order's `fulfilled_at`
        as measured by the logical clock; a claim filed after the window closes
        is `ERR_CLAIM_WINDOW_EXPIRED`."

        Design: Corner/validations/claim_after_warranty_window_expired
        """
        # warranty_months 1: fulfilled 2026-08-10 -> window closes 2026-09-10.
        ctx = setup_fulfilled_order(warranty_months=1)
        set_clock("2026-09-11T00:00:00Z")
        res = api.create_claim(
            {"order_id": ctx["order"]["id"], "claim_type": "DEFECT",
             "claim_qty": 1, "claimed_amount_cents": 1000},
            make_customer_headers(ctx["customer"]["id"]))
        validate_error(res, "ERR_CLAIM_WINDOW_EXPIRED", expected_status=409)


class TestAppealBudget:
    def test_second_appeal_rejected(self, api):
        """PRD §3.9: "A claim carries exactly one appeal: `APPEAL` requires
        `appeal_used` still false and sets it true; a second appeal is
        `ERR_APPEAL_ALREADY_USED`."

        Design: Corner/errors/second_appeal_rejected
        """
        ctx = setup_fulfilled_order()
        claim = file_claim(ctx, claim_type="DEFECT", claim_qty=1,
                           claimed_amount_cents=5000)
        customer = make_customer_headers(ctx["customer"]["id"])
        review(claim["id"], "START", WM_1)
        review(claim["id"], "DENY", WM_1)
        review(claim["id"], "APPEAL", customer)
        review(claim["id"], "DENY", WM_1)
        res = api.review_claim(claim["id"], {"action": "APPEAL"}, customer)
        validate_error(res, "ERR_APPEAL_ALREADY_USED", expected_status=409)
        assert get_claim(claim["id"])["status"] == "DENIED"
