"""Quality claims: the chargeback waterfall (per-line rounding, penalty tiers),
the zero-sum ledger transfer, segregation of duties, the filing window, the
payable guard, and the suspension cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    accept_quotation,
    advance_to_production_complete,
    approve_claim,
    assert_chargeback_zero_sum,
    book_and_pass_psi,
    create_agent,
    create_buyer,
    create_inspector,
    create_quotation,
    create_quality_claim_payload,
    create_sourcing_request,
    file_claim,
    get_buyer,
    get_factory,
    get_purchase_order,
    get_quality_claim,
    get_quotation,
    make_buyer_manager_headers,
    make_grade_a_factory,
    make_sourcing_agent_headers,
    set_clock,
    setup_compliance_docs,
    setup_closed_po,
    ship_and_close,
    validate_error,
    validate_success,
)


class TestPerLineRounding:
    LINES = [
        {"description": "stitch", "qty_defective": 1, "unit_price_cents": 333},
        {"description": "dye", "qty_defective": 1, "unit_price_cents": 333},
        {"description": "zip", "qty_defective": 1, "unit_price_cents": 334},
    ]

    def _scenario(self):
        """CLOSED PO of 25 @ 400 (= 10,000) with the three-line claim filed."""
        ctx = setup_closed_po(unit_price_cents=400, ordered_qty=25)
        claim = file_claim(ctx["po"]["id"], ctx["buyer"]["id"], self.LINES)
        ctx["claim"] = claim
        return ctx

    def test_chargeback_per_line_rounding_penalty_51(self, api):
        """PRD: "Fourth — and the rounding order is pinned — each line's penalty is computed individually as `round_half_up(base_line * penalty_rate, 0 decimal places)`, and `penalty_cents` is the sum of those per-line penalties. Sum-then-round is explicitly not used."
        PRD: "a rate above 0.10 carries a 5% penalty"
        defect_rate 3/25 = 0.1200 -> 5%; per line 16.65/16.65/16.70 -> 17+17+17 = 51 (not round(1000*0.05)=50).

        Design: Difficulty/combinatorial_formula/chargeback_per_line_rounding_beats_sum_then_round
        """
        ctx = self._scenario()
        approved = approve_claim(ctx["claim"]["id"], ctx["agent2"]["id"])
        assert approved["defect_rate"] == pytest.approx(0.12)
        assert approved["penalty_cents"] == 51
        assert approved["total_chargeback_cents"] == 1051
        assert approved["base_amount_cents"] == 1000

    def test_chargeback_per_line_rounding_applies_to_ledgers(self, api):
        """PRD: "The factory's `debit_balance_cents` increases by `total_chargeback_cents`. The buyer's `credit_balance_cents` increases by the same amount — the zero-sum counterpart. The PO's `remaining_payable_cents` decreases by the total."
        The per-line-rounded total (1,051, not the sum-then-round 1,050) is what
        lands on both ledgers and the PO's payable balance.

        Design: Difficulty/combinatorial_formula/chargeback_per_line_rounding_beats_sum_then_round
        """
        ctx = self._scenario()
        approve_claim(ctx["claim"]["id"], ctx["agent2"]["id"])
        assert get_factory(ctx["factory"]["id"])["debit_balance_cents"] == 1051
        assert get_buyer(ctx["buyer"]["id"])["credit_balance_cents"] == 1051
        assert get_purchase_order(ctx["po"]["id"])["remaining_payable_cents"] == 8949


class TestZeroSumInvariant:
    def test_chargeback_adds_equal_debit_and_credit(self, api):
        """PRD: "The factory's `debit_balance_cents` increases by `total_chargeback_cents`. The buyer's `credit_balance_cents` increases by the same amount — the zero-sum counterpart."

        Design: Difficulty/compensating_invariant/chargeback_zero_sum_between_factory_and_buyer
        """
        ctx = setup_closed_po(unit_price_cents=400, ordered_qty=25)
        claim = file_claim(ctx["po"]["id"], ctx["buyer"]["id"],
                           TestPerLineRounding.LINES)
        approve_claim(claim["id"], ctx["agent2"]["id"])
        assert_chargeback_zero_sum(
            get_factory(ctx["factory"]["id"]),
            get_buyer(ctx["buyer"]["id"]),
            expected_total=1051,
        )

    def test_chargeback_reduces_remaining_payable(self, api):
        """PRD: "`remaining_payable_cents` is `total_cents` minus the sum of `total_chargeback_cents` over the PO's `APPROVED` quality claims."
        PRD: "The PO's `remaining_payable_cents` decreases by the total."

        Design: Difficulty/compensating_invariant/chargeback_zero_sum_between_factory_and_buyer
        """
        ctx = setup_closed_po(unit_price_cents=400, ordered_qty=25)
        claim = file_claim(ctx["po"]["id"], ctx["buyer"]["id"],
                           TestPerLineRounding.LINES)
        approve_claim(claim["id"], ctx["agent2"]["id"])
        po = get_purchase_order(ctx["po"]["id"])
        assert po["total_cents"] == 10000
        assert po["remaining_payable_cents"] == 10000 - 1051


class TestPenaltyTierBoundaries:
    def test_chargeback_penalty_tier_boundaries(self, api):
        """PRD: "Third, a penalty tier is selected on the defect rate with inclusive boundaries: a rate at most 0.05 carries no penalty; a rate above 0.05 and at most 0.10 carries a 2% penalty (a rate of exactly 0.1000 therefore sits in the 2% tier); a rate above 0.10 carries a 5% penalty."

        Design: Corner/calculations/chargeback_penalty_tier_boundaries
        """
        ctx = setup_closed_po(unit_price_cents=100, ordered_qty=1000)
        po_id = ctx["po"]["id"]
        buyer_id = ctx["buyer"]["id"]
        adjudicator = ctx["agent2"]["id"]

        cases = [
            ({"description": "edge50", "qty_defective": 50, "unit_price_cents": 100},
             0.05, 0, 5000),
            ({"description": "edge51", "qty_defective": 51, "unit_price_cents": 100},
             0.051, 102, 5202),
            ({"description": "edge100", "qty_defective": 100, "unit_price_cents": 10},
             0.10, 20, 1020),
            ({"description": "edge101", "qty_defective": 101, "unit_price_cents": 10},
             0.101, 51, 1061),
        ]
        for item, expected_rate, expected_penalty, expected_total in cases:
            claim = file_claim(po_id, buyer_id, [item])
            approved = approve_claim(claim["id"], adjudicator)
            assert approved["defect_rate"] == pytest.approx(expected_rate), item
            assert approved["penalty_cents"] == expected_penalty, item
            assert approved["total_chargeback_cents"] == expected_total, item


class TestPayableGuard:
    def test_error_claim_exceeds_payable_trigger(self, api):
        """PRD: "Sixth, the total must not exceed `po.remaining_payable_cents`; a chargeback that would is rejected with `ERR_CLAIM_EXCEEDS_PAYABLE` (HTTP 422)."

        Design: Corner/errors/error_claim_exceeds_payable_trigger
        """
        ctx = setup_closed_po(unit_price_cents=100, ordered_qty=10)
        po_id = ctx["po"]["id"]
        buyer_id = ctx["buyer"]["id"]
        adjudicator = ctx["agent2"]["id"]

        claim_a = file_claim(po_id, buyer_id,
                             [{"description": "A", "qty_defective": 6,
                               "unit_price_cents": 100}])
        approved_a = approve_claim(claim_a["id"], adjudicator)
        assert approved_a["total_chargeback_cents"] == 630  # 600 + 5% of 600
        assert get_purchase_order(po_id)["remaining_payable_cents"] == 370

        claim_b = file_claim(po_id, buyer_id,
                             [{"description": "B", "qty_defective": 5,
                               "unit_price_cents": 100}])
        # 500 base + 25 penalty (rate 0.5 -> 5%) = 525 > 370 remaining.
        validate_error(
            self._approve_raw(api, claim_b["id"], adjudicator),
            ApiErrorId.ERR_CLAIM_EXCEEDS_PAYABLE,
        )
        assert get_quality_claim(claim_b["id"])["status"] == "FILED"

    @staticmethod
    def _approve_raw(api, claim_id, agent_id):
        return api.approve_quality_claim(
            claim_id, make_sourcing_agent_headers(agent_id)
        )


class TestSegregationOfDuties:
    def test_error_segregation_of_duties_on_own_po_claim(self, api):
        """PRD: "Adjudication is reserved for a `SourcingAgent` other than the PO's assigned agent — if the caller's agent id equals `po.assigned_agent_id`, the call is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD: "`approved_by_agent_id` is set to the caller's id."

        Design: Corner/errors/error_segregation_of_duties_on_own_po_claim
        """
        ctx = setup_closed_po(unit_price_cents=100, ordered_qty=10)
        claim = file_claim(ctx["po"]["id"], ctx["buyer"]["id"],
                           [{"description": "tear", "qty_defective": 1,
                             "unit_price_cents": 100}])
        validate_error(
            api.approve_quality_claim(
                claim["id"], make_sourcing_agent_headers(ctx["agent"]["id"])
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )
        approved = approve_claim(claim["id"], ctx["agent2"]["id"])
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_agent_id"] == ctx["agent2"]["id"]


class TestClaimWindow:
    def test_claim_window_30_days_boundary(self, api):
        """PRD: "Filing is allowed only while the logical clock is at or before the PO's latest `delivered_at` plus 30 days; if no delivery has happened yet, or the window has closed, filing is rejected with `ERR_CLAIM_WINDOW_CLOSED`."
        delivered_at 2026-08-05T00:00:00Z: filing at 2026-09-04T00:00:00Z is
        exactly at the inclusive boundary; one second later is rejected.

        Design: Corner/validations/claim_window_30_days_boundary
        """
        set_clock("2026-08-05T00:00:00Z")
        ctx = setup_closed_po(unit_price_cents=100, ordered_qty=10,
                              inspection_date="2026-08-05")
        set_clock("2026-09-04T00:00:00Z")
        in_window = file_claim(
            ctx["po"]["id"], ctx["buyer"]["id"],
            [{"description": "in-window", "qty_defective": 1,
              "unit_price_cents": 50}],
        )
        assert in_window["status"] == "FILED"

        set_clock("2026-09-04T00:00:01Z")
        validate_error(
            api.create_quality_claim(
                ctx["po"]["id"],
                create_quality_claim_payload(
                    items=[{"description": "late", "qty_defective": 1,
                            "unit_price_cents": 50}]
                ),
                make_buyer_manager_headers(ctx["buyer"]["id"]),
            ),
            ApiErrorId.ERR_CLAIM_WINDOW_CLOSED,
        )


class TestSuspensionThreshold:
    def test_rate_threshold_suspension_boundary(self, api):
        """PRD: "if the factory's `debit_balance_cents` has reached or exceeded the suspension threshold of 1,000,000 cents, the factory transitions from `ACTIVE` to `SUSPENDED`"
        Claim c1 lands the debit at 999,810 (still ACTIVE); claim c2 (190)
        lands it on exactly 1,000,000 and the threshold is inclusive.

        Design: Corner/cross_cutting_layers/rate_threshold_suspension_boundary
        """
        ctx = setup_closed_po(category="FURNITURE", unit_price_cents=20000,
                              ordered_qty=500)
        po_id = ctx["po"]["id"]
        buyer_id = ctx["buyer"]["id"]
        adjudicator = ctx["agent2"]["id"]

        c1 = file_claim(po_id, buyer_id,
                        [{"description": "big", "qty_defective": 200,
                          "unit_price_cents": 4761}])
        approved1 = approve_claim(c1["id"], adjudicator)
        # 952,200 base; rate 0.4000 -> 5% -> 47,610 penalty.
        assert approved1["total_chargeback_cents"] == 999810
        factory = get_factory(ctx["factory"]["id"])
        assert factory["debit_balance_cents"] == 999810
        assert factory["status"] == "ACTIVE"

        c2 = file_claim(po_id, buyer_id,
                        [{"description": "small", "qty_defective": 1,
                          "unit_price_cents": 190}])
        approved2 = approve_claim(c2["id"], adjudicator)
        assert approved2["total_chargeback_cents"] == 190  # rate 0.0020 -> no penalty
        factory = get_factory(ctx["factory"]["id"])
        assert factory["debit_balance_cents"] == 1000000
        assert factory["status"] == "SUSPENDED"


class TestSuspensionCascade:
    def _suspension_cascade_scenario(self):
        """A big CLOSED PO with a filed 3,150,000 claim, plus a live OPEN
        quotation and a live unshipped ACTIVE PO at the same factory."""
        b1 = create_buyer("Buyer One")
        b2 = create_buyer("Buyer Two", "DE")
        a1 = create_agent("Agent One")
        a2 = create_agent("Agent Two")
        inspector = create_inspector("Inspector One")
        f1 = make_grade_a_factory(a1["id"])
        setup_compliance_docs(f1["id"], a1["id"], "FURNITURE")

        # p_big: 500 @ 30,000 = 15,000,000, fully closed.
        sr1 = create_sourcing_request(
            b1["id"], a1["id"], title="Big goods", product_category="FURNITURE",
            target_price_cents=30000, quantity=500,
        )
        q1 = create_quotation(sr1["id"], f1["id"], unit_price_cents=30000, moq=1)
        p_big = accept_quotation(b1["id"], q1, 500, delivery_month="2026-09")
        ctx_big = {"buyer": b1, "agent": a1, "factory": f1, "po": p_big,
                   "inspector": inspector}
        advance_to_production_complete(ctx_big)
        book_and_pass_psi(ctx_big, lot_size=500)
        ship_and_close(ctx_big)

        # An unrelated OPEN quotation from the same factory (another buyer).
        sr2 = create_sourcing_request(
            b2["id"], a1["id"], title="B2 goods", product_category="APPAREL",
            target_price_cents=500, quantity=10,
        )
        q_open = create_quotation(sr2["id"], f1["id"], unit_price_cents=500, moq=1)

        # A live, unshipped PO at the same factory.
        sr3 = create_sourcing_request(
            b1["id"], a1["id"], title="Victim goods", product_category="APPAREL",
            target_price_cents=1000, quantity=10,
        )
        q_v = create_quotation(sr3["id"], f1["id"], unit_price_cents=1000, moq=1)
        p_victim = accept_quotation(b1["id"], q_v, 10, delivery_month="2026-11")

        cl_big = file_claim(
            p_big["id"], b1["id"],
            [{"description": "cracked frames", "qty_defective": 100,
              "unit_price_cents": 30000}],
        )
        return {"b1": b1, "b2": b2, "a1": a1, "a2": a2, "f1": f1,
                "p_big": ctx_big["po"], "q_open": q_open,
                "p_victim": p_victim, "cl_big": cl_big}

    def test_claim_approval_crosses_threshold_suspends_factory(self, api):
        """PRD: "The factory's `debit_balance_cents` increases by `total_chargeback_cents`."
        PRD: "if the factory's `debit_balance_cents` has reached or exceeded the suspension threshold of 1,000,000 cents, the factory transitions from `ACTIVE` to `SUSPENDED`"
        100 defective of 500 at 30,000 -> rate 0.2000 -> 5% -> total 3,150,000.

        Design: Difficulty/transitive_cascade/claim_approval_suspends_factory_and_expires_quotations
        """
        sc = self._suspension_cascade_scenario()
        approved = approve_claim(sc["cl_big"]["id"], sc["a2"]["id"])
        assert approved["total_chargeback_cents"] == 3150000
        factory = get_factory(sc["f1"]["id"])
        assert factory["debit_balance_cents"] == 3150000
        assert factory["status"] == "SUSPENDED"

    def test_suspension_cascades_to_open_quotations_and_unshipped_pos(self, api):
        """PRD: "every quotation of that factory still in `OPEN` or `COUNTERED` flips to `EXPIRED`; and every PO of that factory with status `ACTIVE` and `shipped_qty` equal to 0 flips to `CANCELLED` (with `cancelled_qty` absorbing `open_qty` and `open_qty` zeroed)."

        Design: Difficulty/transitive_cascade/claim_approval_suspends_factory_and_expires_quotations
        """
        sc = self._suspension_cascade_scenario()
        approve_claim(sc["cl_big"]["id"], sc["a2"]["id"])

        assert get_quotation(sc["q_open"]["id"])["status"] == "EXPIRED"
        victim = get_purchase_order(sc["p_victim"]["id"])
        assert victim["status"] == "CANCELLED"
        assert victim["cancelled_qty"] == 10
        assert victim["open_qty"] == 0
        # The terminal CLOSED PO that originated the claim is untouched.
        assert get_purchase_order(sc["p_big"]["id"])["status"] == "CLOSED"
