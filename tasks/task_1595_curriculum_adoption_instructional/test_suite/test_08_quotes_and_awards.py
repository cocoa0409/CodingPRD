"""Publisher quotes: bundled-pricing rounding, the clarification loop, the
award's bid/winner rules under both award methods, and the OCC guard."""
import pytest

from test_helpers import (
    ApiErrorId,
    SECRETARY,
    TEST_USERS,
    award_quote,
    award_quote_fresh,
    create_quote,
    evaluate_quote,
    get_cycle,
    get_cycle_version,
    get_quote,
    setup_cycle_adopted,
    setup_cycle_in_pilot_open,
    setup_two_candidate_cycle,
    transition_quote,
    validate_error,
    validate_success,
)

PROCUREMENT = TEST_USERS["procurement_officer_headers"]

# The standard three-quote pool used by the dual award-method tests.
CHEAP = {"publisher_name": "PubCheap", "print_unit_price": 80.00,
         "print_quantity": 500, "digital_seat_rate": 25.00,
         "digital_seat_count": 480, "bundle_discount_pct": 0.10,
         "training_sessions": 1, "license_years": 1}      # evaluated 50800.00
RICH = {"publisher_name": "PubRich", "print_unit_price": 95.00,
        "print_quantity": 500, "digital_seat_rate": 10.00,
        "digital_seat_count": 480, "bundle_discount_pct": 0,
        "training_sessions": 6, "license_years": 5}       # evaluated 52300.00
MID = {"publisher_name": "PubMid", "print_unit_price": 88.50,
       "print_quantity": 500, "digital_seat_rate": 18.75,
       "digital_seat_count": 480, "bundle_discount_pct": 0.05,
       "training_sessions": 4, "license_years": 4}        # evaluated 52800.00


def _evaluated_pool(cycle_id, material_id, specs):
    quotes = [create_quote(cycle_id, material_id, **spec) for spec in specs]
    return [evaluate_quote(q["id"]) for q in quotes]


class TestBundledPricingRounding:
    def test_per_line_rounding_before_sum(self, api):
        """PRD §3.5: "first the print line is computed as `print_unit_price`
        times `print_quantity` and rounded half-up to cents; likewise the
        digital line is computed as `digital_seat_rate` times
        `digital_seat_count` and rounded half-up to cents."
        PRD §3.5: "Last, the total is the sum of the two rounded lines.
        Summing the unrounded lines and rounding once at the end yields
        different cents and is not the specification."

        Design: Difficulty/combinatorial_formula/quote_line_rounding_order
        """
        ctx = setup_cycle_in_pilot_open()
        quote = create_quote(ctx["cycle"]["id"], ctx["material"]["id"],
                             publisher_name="PubR", print_unit_price=10.125,
                             print_quantity=1, digital_seat_rate=10.125,
                             digital_seat_count=1, bundle_discount_pct=0,
                             training_sessions=0, license_years=0)
        evaluated = evaluate_quote(quote["id"])
        # Per-line rounding: 10.125 -> 10.13 twice -> 20.26. Sum-then-round
        # of the unrounded 20.25 would give 20.25, which is NOT the spec.
        assert evaluated["evaluated_total"] == pytest.approx(20.26, abs=0.01)

    def test_bundle_discount_applied_after_line_rounding(self, api):
        """PRD §3.5: "when a positive `bundle_discount_pct` is present and
        both the print and digital quantities are greater than zero, the
        bundle discount applies to the digital line only — the already-rounded
        digital line is multiplied by one minus the discount and the result
        is rounded half-up to cents again."

        Design: Difficulty/combinatorial_formula/quote_line_rounding_order
        """
        ctx = setup_cycle_in_pilot_open()
        quote = create_quote(ctx["cycle"]["id"], ctx["material"]["id"],
                             **CHEAP)
        evaluated = evaluate_quote(quote["id"])
        # print 40000.00 + round(12000.00 * 0.90) = 10800.00 -> 50800.00.
        assert evaluated["evaluated_total"] == pytest.approx(50800.00, abs=0.01)


class TestClarificationLoop:
    def test_clarification_resubmit_recomputes_evaluated_total(self, api):
        """PRD §3.5: "the resubmission may carry updated values for any of
        the pricing or service fields (`print_unit_price`, `print_quantity`,
        `digital_seat_rate`, `digital_seat_count`, `bundle_discount_pct`,
        `training_sessions`, `license_years`), and the `evaluated_total` is
        recomputed on each resubmit."

        Design: Difficulty/non_linear_state_machine/quote_clarification_resubmit_cycle
        """
        ctx = setup_cycle_in_pilot_open()
        quote = create_quote(ctx["cycle"]["id"], ctx["material"]["id"], **CHEAP)

        evaluated = evaluate_quote(quote["id"])
        assert evaluated["status"] == "UNDER_EVALUATION"
        assert evaluated["evaluated_total"] == pytest.approx(50800.00, abs=0.01)

        clarified = transition_quote(quote["id"], "CLARIFICATION_REQUESTED")
        assert clarified["status"] == "CLARIFICATION_REQUESTED"

        # Resubmit with a revised print price: 70.00 x 500 = 35000.00 print
        # plus the unchanged discounted digital line 10800.00 -> 45800.00.
        resubmitted = transition_quote(quote["id"], "UNDER_EVALUATION",
                                       print_unit_price=70.00)
        assert resubmitted["status"] == "UNDER_EVALUATION"
        assert resubmitted["evaluated_total"] == pytest.approx(45800.00,
                                                               abs=0.01)

    def test_clarification_loop_bumps_version_each_pass(self, api):
        """PRD §3.5: "The loop may iterate, and each pass bumps the quote's
        `version` — which is exactly what makes the cycle's quote pin
        meaningful."
        PRD §2.9: "Every state transition on every entity — whether driven by
        an explicit operator request or fired automatically by the system as
        a cascade — increments the affected entity's `version` by exactly one
        and refreshes its `updated_at`."

        Design: Difficulty/non_linear_state_machine/quote_clarification_resubmit_cycle
        """
        ctx = setup_cycle_in_pilot_open()
        quote = create_quote(ctx["cycle"]["id"], ctx["material"]["id"], **CHEAP)
        v_created = quote["version"]

        v2 = evaluate_quote(quote["id"])["version"]
        assert v2 == v_created + 1, "evaluate bumps the version by exactly one"
        v3 = transition_quote(quote["id"], "CLARIFICATION_REQUESTED")["version"]
        assert v3 == v2 + 1, "clarification bumps the version by exactly one"
        v4 = transition_quote(quote["id"], "UNDER_EVALUATION",
                              print_unit_price=70.00)["version"]
        assert v4 == v3 + 1, "resubmit bumps the version by exactly one"

        # The loop may iterate a second time.
        v5 = transition_quote(quote["id"], "CLARIFICATION_REQUESTED")["version"]
        assert v5 == v4 + 1
        v6 = transition_quote(quote["id"], "UNDER_EVALUATION")["version"]
        assert v6 == v5 + 1
        assert get_quote(quote["id"])["evaluated_total"] == pytest.approx(
            45800.00, abs=0.01), "no field updates -> the recomputation is stable"


class TestQuoteWithdrawal:
    def test_quote_withdrawn_terminal_lockdown(self, api):
        """PRD §3.5: "A quote may also be withdrawn from `SUBMITTED`,
        `UNDER_EVALUATION`, or `CLARIFICATION_REQUESTED`, moving to
        `WITHDRAWN`, terminal alongside `REJECTED` and `SUPERSEDED`."
        PRD §3.5: "Evaluation begins when the `ProcurementOfficer` moves a
        `SUBMITTED` quote to `UNDER_EVALUATION`"

        Design: Corner/state_machines/quote_withdrawn_terminal_lockdown
        """
        ctx = setup_cycle_in_pilot_open()
        quote = create_quote(ctx["cycle"]["id"], ctx["material"]["id"],
                             publisher_name="PubA", print_unit_price=10.00,
                             print_quantity=5)
        withdrawn = transition_quote(quote["id"], "WITHDRAWN")
        assert withdrawn["status"] == "WITHDRAWN"

        validate_error(api.transition_quote(quote["id"],
                                            {"to_state": "UNDER_EVALUATION"},
                                            PROCUREMENT),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.transition_quote(quote["id"],
                                            {"to_state": "WITHDRAWN"},
                                            PROCUREMENT),
                       ApiErrorId.ERR_INVALID_STATE)


class TestBestValueZeroMinPool:
    def _zero_min_pool(self, api):
        """BEST_VALUE cycle with three evaluated quotes: FREE1 (total 0.00,
        10 sessions / 5 years), FREE2 (total 0.00, 0/0), PAID (total 100.00,
        3 sessions / 2 years)."""
        ctx = setup_cycle_adopted(award_method="BEST_VALUE")
        free1 = create_quote(ctx["cycle"]["id"], ctx["material"]["id"],
                             publisher_name="PubFree1", print_unit_price=0,
                             print_quantity=100, digital_seat_rate=0,
                             digital_seat_count=0, training_sessions=10,
                             license_years=5)
        free2 = create_quote(ctx["cycle"]["id"], ctx["material"]["id"],
                             publisher_name="PubFree2", print_unit_price=0,
                             print_quantity=100, digital_seat_rate=0,
                             digital_seat_count=0, training_sessions=0,
                             license_years=0)
        paid = create_quote(ctx["cycle"]["id"], ctx["material"]["id"],
                            publisher_name="PubPaid", print_unit_price=100.00,
                            print_quantity=1, digital_seat_rate=0,
                            digital_seat_count=0, training_sessions=3,
                            license_years=2)
        for q in (free1, free2, paid):
            evaluate_quote(q["id"])
        return ctx, free1, free2, paid

    def test_priced_quote_loses_when_min_total_is_zero(self, api):
        """PRD §3.5: "the price score is one hundred when the pool's minimum
        `evaluated_total` is zero"
        PRD §3.5: "Third, the target must be the rule winner, or the award
        fails with `ERR_QUOTE_NOT_AWARD_WINNER`."

        Design: Difficulty/combinatorial_formula/best_value_zero_min_pool
        """
        ctx, free1, free2, paid = self._zero_min_pool(api)
        # Every price score is flattened to 100 (min_total == 0), so service
        # terms decide: PAID's 67.50 loses to FREE1's 100.00.
        validate_error(award_quote(ctx["cycle"]["id"], paid["id"]),
                       ApiErrorId.ERR_QUOTE_NOT_AWARD_WINNER)

    def test_zero_priced_quote_wins_on_service_terms(self, api):
        """PRD §3.5: "the price score is one hundred when the pool's minimum
        `evaluated_total` is zero, and otherwise the larger of zero and one
        hundred times two-minus-the-ratio of the quote's `evaluated_total` to
        that minimum; the training score is ten points per included
        `training_sessions`, capped at one hundred; the license score is
        twenty points per `license_years`, capped at one hundred; the final
        score is half the price score plus a quarter of the training score
        plus a quarter of the license score, combined at full precision and
        rounded half-up to two decimal places only at the end"

        Design: Difficulty/combinatorial_formula/best_value_zero_min_pool
        """
        ctx, free1, free2, paid = self._zero_min_pool(api)
        award_quote_fresh(ctx["cycle"]["id"], free1["id"])

        # min_total == 0 -> all price scores 100. FREE1: 50 + 25 + 25 =
        # 100.00; PAID: 50 + 7.50 + 10.00 = 67.50; FREE2: 50 + 0 + 0 = 50.00.
        assert get_quote(free1["id"])["best_value_score"] == pytest.approx(
            100.00, abs=0.01)
        assert get_quote(paid["id"])["best_value_score"] == pytest.approx(
            67.50, abs=0.01)
        assert get_quote(free2["id"])["best_value_score"] == pytest.approx(
            50.00, abs=0.01)

        assert get_quote(free1["id"])["status"] == "SELECTED"
        assert get_quote(free2["id"])["status"] == "REJECTED"
        assert get_quote(paid["id"])["status"] == "REJECTED"


class TestAwardMethodDualVariant:
    def test_lowest_responsive_rejects_pricier_quote(self, api):
        """PRD §3.5: "Under `LOWEST_RESPONSIVE`, the winner is the pool quote
        with the lowest `evaluated_total`, ties broken in favor of the
        earliest `created_at`."
        PRD §3.5: "Third, the target must be the rule winner, or the award
        fails with `ERR_QUOTE_NOT_AWARD_WINNER`."
        PRD §3.5: "A quote's `best_value_score` remains null unless its cycle
        awards under `BEST_VALUE`."

        Design: Difficulty/dual_variant_calc/award_lowest_responsive_vs_best_value
        """
        ctx = setup_cycle_adopted(award_method="LOWEST_RESPONSIVE")
        cheap, rich, mid = _evaluated_pool(
            ctx["cycle"]["id"], ctx["material"]["id"], [CHEAP, RICH, MID])
        assert cheap["evaluated_total"] == pytest.approx(50800.00, abs=0.01)
        assert rich["evaluated_total"] == pytest.approx(52300.00, abs=0.01)
        assert mid["evaluated_total"] == pytest.approx(52800.00, abs=0.01)

        # The 52300.00 quote is not the cheapest: rejected under this method.
        validate_error(award_quote(ctx["cycle"]["id"], rich["id"]),
                       ApiErrorId.ERR_QUOTE_NOT_AWARD_WINNER)

        # The cheapest quote is the winner; the rest of the pool is rejected.
        award_quote_fresh(ctx["cycle"]["id"], cheap["id"])
        assert get_quote(cheap["id"])["status"] == "SELECTED"
        assert get_quote(rich["id"])["status"] == "REJECTED"
        assert get_quote(mid["id"])["status"] == "REJECTED"
        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["status"] == "PROCURING"
        assert cycle["pinned_quote_id"] == cheap["id"]
        # No best-value scoring under LOWEST_RESPONSIVE.
        assert get_quote(cheap["id"])["best_value_score"] is None

    def test_best_value_accepts_high_service_quote(self, api):
        """PRD §3.5: "Under `BEST_VALUE`, the system first computes and
        persists a `best_value_score` for every quote in the pool"
        PRD §3.5: "the winner is the highest score, ties again broken by the
        earliest `created_at`."
        PRD §3.5: "`pinned_quote_id` records the quote and
        `quote_version_pin` captures the quote's `version` at that instant."

        Design: Difficulty/dual_variant_calc/award_lowest_responsive_vs_best_value
        """
        ctx = setup_cycle_adopted(award_method="BEST_VALUE",
                                  subject_area="SCIENCE",
                                  framework_code="FW-SCI-K5",
                                  close_clock="2026-10-02T00:00:00Z")
        cheap, rich, mid = _evaluated_pool(
            ctx["cycle"]["id"], ctx["material"]["id"], [CHEAP, RICH, MID])

        # The identical 52300.00 quote WINS under BEST_VALUE (highest score).
        resp = award_quote(ctx["cycle"]["id"], rich["id"])
        validate_success(resp)
        assert get_cycle(ctx["cycle"]["id"])["status"] == "PROCURING"

        assert get_quote(rich["id"])["best_value_score"] == pytest.approx(
            88.52, abs=0.01)
        assert get_quote(cheap["id"])["best_value_score"] == pytest.approx(
            57.50, abs=0.01)
        assert get_quote(mid["id"])["best_value_score"] == pytest.approx(
            78.03, abs=0.01)

        assert get_quote(rich["id"])["status"] == "SELECTED"
        assert get_quote(cheap["id"])["status"] == "REJECTED"
        assert get_quote(mid["id"])["status"] == "REJECTED"

        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["pinned_quote_id"] == rich["id"]
        assert cycle["quote_version_pin"] == get_quote(rich["id"])["version"]


class TestBidRule:
    def test_bid_rule_formal_threshold_inclusive(self, api):
        """PRD §3.5: "the responsive pool — all quotes of this cycle in
        `UNDER_EVALUATION` whose material is the adopted material, the award
        target included — must satisfy the bid rule: at least three
        responsive quotes when the target's `evaluated_total` is at least
        250,000.00 dollars (a target priced at exactly 250,000.00 is held to
        this formal-bid rule), and at least two otherwise; a short pool fails
        with `ERR_BID_RULE_NOT_SATISFIED`."

        Design: Corner/calculations/bid_rule_formal_threshold_inclusive
        """
        ctx = setup_cycle_adopted()
        q1 = create_quote(ctx["cycle"]["id"], ctx["material"]["id"],
                          publisher_name="PubA", print_unit_price=250.00,
                          print_quantity=1000)
        q2 = create_quote(ctx["cycle"]["id"], ctx["material"]["id"],
                          publisher_name="PubB", print_unit_price=260.00,
                          print_quantity=1000)
        q1 = evaluate_quote(q1["id"])
        evaluate_quote(q2["id"])
        # Exactly the formal threshold: the informal 2-quote rule does NOT
        # apply to this target.
        assert q1["evaluated_total"] == pytest.approx(250000.00, abs=0.01)

        validate_error(award_quote(ctx["cycle"]["id"], q1["id"]),
                       ApiErrorId.ERR_BID_RULE_NOT_SATISFIED)

        # A third responsive quote satisfies the formal rule; the minimum
        # evaluated_total wins under LOWEST_RESPONSIVE.
        q3 = create_quote(ctx["cycle"]["id"], ctx["material"]["id"],
                          publisher_name="PubC", print_unit_price=255.00,
                          print_quantity=1000)
        evaluate_quote(q3["id"])
        award_quote_fresh(ctx["cycle"]["id"], q1["id"])
        assert get_cycle(ctx["cycle"]["id"])["status"] == "PROCURING"


class TestAwardGuards:
    def test_award_quote_material_mismatch_rejected(self, api):
        """PRD §3.5: "First, the named quote's `material_id` must equal the
        cycle's `adopted_material_id`, or the award fails with
        `ERR_QUOTE_MATERIAL_MISMATCH`."

        Design: Corner/validations/award_quote_material_mismatch_rejected
        """
        ctx = setup_two_candidate_cycle()
        # Quote evaluated against M2 while M2 is still a pilot candidate.
        quote_m2 = create_quote(ctx["cycle"]["id"], ctx["m2"]["id"],
                                publisher_name="PubB", print_unit_price=10.00,
                                print_quantity=10)
        evaluate_quote(quote_m2["id"])

        # The board adopts M1 (M2 is rejected by the cascade).
        resp = api.board_decision(ctx["cycle"]["id"],
                                  {"material_id": ctx["m1"]["id"],
                                   "decision": "ADOPT"}, SECRETARY)
        assert resp.status_code == 200

        validate_error(award_quote(ctx["cycle"]["id"], quote_m2["id"]),
                       ApiErrorId.ERR_QUOTE_MATERIAL_MISMATCH)
        assert get_cycle(ctx["cycle"]["id"])["status"] == "ADOPTED"

    def test_occ_award_stale_version_rejected(self, api):
        """PRD §2.8: "If `expected_cycle_version` does not equal the cycle's
        current `version`, the request is rejected with
        `ERR_STALE_CYCLE_VERSION` (HTTP 412)."
        PRD §3.5: "On a re-award while `PROCURING`, the previously `SELECTED`
        quote moves to `SUPERSEDED` — a legitimate, intended write, which is
        precisely what the OCC rule guards — and the pin moves to the new
        winner."

        Design: Corner/cross_cutting_complexity_layers/occ_award_stale_version_rejected
        """
        ctx = setup_cycle_adopted()
        qa, qb = _evaluated_pool(ctx["cycle"]["id"], ctx["material"]["id"], [
            {"publisher_name": "PubA", "print_unit_price": 10.00,
             "print_quantity": 10, "digital_seat_rate": 0,
             "digital_seat_count": 0, "training_sessions": 0,
             "license_years": 0},
            {"publisher_name": "PubB", "print_unit_price": 20.00,
             "print_quantity": 10, "digital_seat_rate": 0,
             "digital_seat_count": 0, "training_sessions": 0,
             "license_years": 0}])
        stale_version = get_cycle_version(ctx["cycle"]["id"])
        award_quote_fresh(ctx["cycle"]["id"], qa["id"])  # advances the version

        # A second pool arrives (a legitimate re-award target exists).
        qc, qd = _evaluated_pool(ctx["cycle"]["id"], ctx["material"]["id"], [
            {"publisher_name": "PubC", "print_unit_price": 10.00,
             "print_quantity": 10, "digital_seat_rate": 0,
             "digital_seat_count": 0, "training_sessions": 0,
             "license_years": 0},
            {"publisher_name": "PubD", "print_unit_price": 20.00,
             "print_quantity": 10, "digital_seat_rate": 0,
             "digital_seat_count": 0, "training_sessions": 0,
             "license_years": 0}])

        # The client still holds the pre-award version: stale write rejected.
        validate_error(
            award_quote(ctx["cycle"]["id"], qc["id"],
                        expected_cycle_version=stale_version),
            ApiErrorId.ERR_STALE_CYCLE_VERSION)
        assert get_quote(qa["id"])["status"] == "SELECTED"
        assert get_quote(qc["id"])["status"] == "UNDER_EVALUATION"

        # Retrying with the fresh version succeeds and supersedes QA.
        award_quote_fresh(ctx["cycle"]["id"], qc["id"])
        assert get_quote(qc["id"])["status"] == "SELECTED"
        assert get_quote(qa["id"])["status"] == "SUPERSEDED"
        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["status"] == "PROCURING"
        assert cycle["pinned_quote_id"] == qc["id"]
