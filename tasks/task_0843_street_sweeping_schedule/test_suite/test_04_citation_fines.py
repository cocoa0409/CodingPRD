"""Citation fine calculations: provisional vs. final, tiered late fees, repeat multiplier.

Translates queue A (Difficulty) dual_variant_calc and combinatorial_formula
citation instances, plus the queue B uphold-then-pay instance.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    setup_issued_citation, setup_prior_upheld_then_issue, setup_upheld_citation,
    set_clock, pay_citation,
)

OFFICER = TEST_USERS["enforcement_officer_headers"]


def test_provisional_amount_pins_days_late_zero(api):
    """PRD §3.7: "The **provisional** fine is computed at issuance and stored in `amount_due_cents`: because a freshly issued citation has a `days_late` pinned to 0, its `late_fee_cents` is 0 and only the base and repeat multiplier apply."

    Design: Difficulty/dual_variant_calc/citation_fine_provisional_vs_final
    """
    route, block, cit = setup_issued_citation(plate="ABC123", scan_iso="2026-03-10T08:30:00Z")
    assert cit["amount_due_cents"] == 6000
    assert cit["status"] == "ISSUED"


def test_final_amount_folds_late_fee_tier(api):
    """PRD §3.7: "The **final** fine is computed at payment and stored in `paid_amount_cents`: at that point `days_late` is set to the number of whole days from `issued_at` to the payment-time logical clock, the applicable late-fee tier is folded in, and the multiplier and cap are applied as above."
    PRD §3.7: "3,000 cents ($30.00) when between 16 and 30 days late"

    Design: Difficulty/dual_variant_calc/citation_fine_provisional_vs_final
    """
    route, block, cit = setup_issued_citation(plate="ABC123", scan_iso="2026-03-10T08:30:00Z")
    set_clock("2026-03-30T08:30:00Z", OFFICER)
    paid = pay_citation(cit["id"], officer_id="officer-1")
    assert paid["days_late"] == 20
    assert paid["paid_amount_cents"] == 9000
    assert paid["status"] == "PAID"


def test_repeat_multiplier_applies_to_provisional(api):
    """PRD §3.7: "the multiplier is 1.0 when there are no prior upheld/paid citations, 1.5 when there are 1 or 2, and 2.0 when there are 3 or more."
    PRD §3.7: "The system computes the derived `prior_upheld_count` — the number of earlier citations for the same `plate` whose status is `UPHELD` or `PAID`, counting only citations created before this one and excluding the citation itself — and pins the provisional fine into `amount_due_cents`."

    Design: Difficulty/combinatorial_formula/citation_fine_nonlinear_repeat_multiplier
    """
    route, block, cit2 = setup_prior_upheld_then_issue(plate="REP999")
    assert cit2["prior_upheld_count"] == 1
    # provisional: (6000 + 0) * 1.5 = 9000
    assert cit2["amount_due_cents"] == 9000


def test_final_combines_late_tier_and_repeat_multiplier(api):
    """PRD §3.7: "The sum of base and late fee is then multiplied by a repeat-offender multiplier driven by `prior_upheld_count`"
    PRD §3.7: "1,500 cents ($15.00) when the citation is between 1 and 15 whole days late"

    Design: Difficulty/combinatorial_formula/citation_fine_nonlinear_repeat_multiplier
    """
    route, block, cit2 = setup_prior_upheld_then_issue(plate="REP999",
                                                       second_scan="2026-03-12T08:30:00Z")
    set_clock("2026-03-17T08:30:00Z", OFFICER)
    paid = pay_citation(cit2["id"], officer_id="officer-1")
    # final: (6000 + 1500) * 1.5 = 11250, days_late = 5
    assert paid["days_late"] == 5
    assert paid["paid_amount_cents"] == 11250


def test_upheld_citation_can_be_paid_same_day(api):
    """PRD §3.7: "Payment can be made from two starting states: `ISSUED → PAID` for a citation that was never contested, and `UPHELD → PAID` for one whose contest was upheld. In both cases the server sets `days_late`, computes `paid_amount_cents` via the final fine variant, and moves the citation to `PAID`."

    Design: Corner/state_machines/uphold_then_pay_final_amount
    """
    route, block, upheld = setup_upheld_citation(plate="UPH001", scan_iso="2026-03-10T08:30:00Z")
    assert upheld["status"] == "UPHELD"
    paid = pay_citation(upheld["id"], officer_id="officer-2")
    assert paid["status"] == "PAID"
    assert paid["days_late"] == 0
    assert paid["paid_amount_cents"] == 6000
