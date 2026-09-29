"""Two calculations that exist in two variants each, and diverge on identical rows.

The fraud score is computed once at origination and again at review decision time
with a different velocity weight, a different free allowance, a different window
and a re-evaluated new-beneficiary term, so the stored transfer keeps its frozen
origination figure while the review records a different final figure.

Reconciliation is the accounting counterpart: a `PROVISIONAL` run and a `FINAL`
run read the same stored rows but admit different clearing and exception states
and treat the access fee differently, so one identical `core_deposit_total_cents`
can be balanced under one variant and out of balance under the other.
"""

from test_helpers import (
    accept_transfer,
    alpha_and_beta_scenario,
    alpha_scenario,
    assert_reconciliation_figures,
    assert_transfer_dimensions,
    assign_review,
    cutoff_cycle,
    decide_review,
    honor_return_request,
    lodge_return_request,
    read_account,
    read_cycle,
    read_transfer,
    send_from_alpha,
    set_clock,
    settle_transfer,
    sole_fraud_review,
    submit_reconciliation_run,
)


def test_review_final_score_diverges_from_frozen_origination_score(api):
    """The review-time recomputation drops the new-beneficiary bonus and lands on 50.

    PRD 3.5: "And the new-beneficiary term is re-evaluated as of decision time, so a
    beneficiary that has since received a `SETTLED` transfer from the same customer
    account drops that 12-point bonus to zero."

    Design: Difficulty/dual_variant_calc/fraud_score_origination_vs_review_final_diverge
    """
    scenario = alpha_scenario(api, fraud_risk_baseline=25)

    held = send_from_alpha(api, scenario, 250_000_000)
    assert held["fraud_score"] == 63
    assert_transfer_dimensions(held, "FRAUD_HOLD", "NONE")

    set_clock(api, "2026-08-03T13:10:00Z")
    sibling = send_from_alpha(api, scenario, 200_000)
    assert sibling["fraud_score"] == 45
    accept_transfer(api, sibling["id"])
    settled_sibling = settle_transfer(api, sibling["id"])
    assert_transfer_dimensions(settled_sibling, "SETTLED", "NONE")

    review = sole_fraud_review(api, held["id"])
    assert review["score_at_origination"] == 63
    assign_review(api, review["id"])

    set_clock(api, "2026-08-03T13:20:00Z")
    decided = decide_review(
        api, review["id"], "RELEASE", "Beneficiary confirmed by treasury callback."
    )

    assert decided["final_fraud_score"] == 50
    assert decided["score_at_origination"] == 63
    assert decided["final_fraud_score"] != decided["score_at_origination"]
    assert decided["status"] == "RELEASED"

    released = read_transfer(api, held["id"])
    assert released["fraud_score"] == 63, "the origination score is frozen, not recomputed"
    assert_transfer_dimensions(released, "INITIATED", "NONE")


def test_review_final_score_matches_origination_when_beneficiary_stays_new(api):
    """With no settled sibling the bonus survives, so both variants land on 63.

    PRD 3.5: "The base and the amount term are unchanged, and the multiplier is the
    same — yet the final score is generally a different number from the origination
    score on identical stored data."

    Design: Difficulty/dual_variant_calc/fraud_score_origination_vs_review_final_diverge
    """
    scenario = alpha_scenario(api, fraud_risk_baseline=25)

    held = send_from_alpha(api, scenario, 250_000_000)
    assert held["fraud_score"] == 63

    set_clock(api, "2026-08-03T13:10:00Z")
    sibling = send_from_alpha(api, scenario, 200_000)
    assert_transfer_dimensions(sibling, "INITIATED", "NONE")

    review = sole_fraud_review(api, held["id"])
    assign_review(api, review["id"])

    set_clock(api, "2026-08-03T13:20:00Z")
    decided = decide_review(api, review["id"], "RELEASE")

    assert decided["final_fraud_score"] == 63
    assert decided["score_at_origination"] == 63
    assert decided["status"] == "RELEASED"
    assert_transfer_dimensions(read_transfer(api, held["id"]), "INITIATED", "NONE")


def test_provisional_zeroes_the_fee_while_final_nets_it(api):
    """One core figure, two variants: the fee component alone flips the outcome.

    PRD 3.10: "The `PROVISIONAL` variant's debit side admits the participant's
    outbound transfers in either `ACCEPTED` or `SETTLED`, matching an
    accepted-but-unsettled transfer to the cycle by the UTC date of its `accepted_at`
    because its `settlement_business_date` is still null; it ignores `exception_status`
    entirely, so an already honoured return is still counted as a debit; its
    `fee_component_cents` is always 0; and it never changes the cycle's status."

    Design: Difficulty/dual_variant_calc/reconciliation_variance_provisional_vs_final_diverge
    """
    scenario = alpha_scenario(api)
    transfer = send_from_alpha(api, scenario, 250_000_000)
    accept_transfer(api, transfer["id"])
    set_clock(api, "2026-08-03T13:10:00Z")
    settle_transfer(api, transfer["id"])

    set_clock(api, "2026-08-03T13:20:00Z")
    cycle = cutoff_cycle(api, scenario.cycle_id)
    assert cycle["assessed_fee_total_cents"] == 250_000
    assert cycle["settled_transfer_count"] == 1

    core_total = -250_250_000
    provisional = submit_reconciliation_run(
        api, scenario.cycle_id, scenario.alpha.id, core_total, "PROVISIONAL"
    )
    assert_reconciliation_figures(
        provisional,
        rail_net_position_cents=-250_000_000,
        variance_cents=-250_000,
        outcome="OUT_OF_BALANCE",
        included_transfer_count=1,
        fee_component_cents=0,
        revision=1,
    )
    assert read_cycle(api, scenario.cycle_id)["status"] == "CUTOFF"

    final = submit_reconciliation_run(
        api, scenario.cycle_id, scenario.alpha.id, core_total, "FINAL"
    )
    assert_reconciliation_figures(
        final,
        rail_net_position_cents=-250_250_000,
        variance_cents=0,
        outcome="BALANCED",
        included_transfer_count=1,
        fee_component_cents=-250_000,
        revision=1,
    )
    assert read_cycle(api, scenario.cycle_id)["status"] == "RECONCILING"


def test_final_excludes_the_honoured_outbound_that_provisional_still_counts(api):
    """The exception dimension is admitted by one variant and excluded by the other.

    PRD 3.10: "The `FINAL` variant's debit side admits outbound transfers in
    `SETTLED` only and excludes any whose `exception_status` is `RETURN_HONORED`,
    since returned money is netted out rather than counted; its `fee_component_cents`
    is the summed `amount_cents` of the account's ledger entries with `entry_type`
    `FEE_DEBIT` whose `business_date` equals the cycle's business date, a figure that
    is negative or zero; and it drives the cycle's status."

    Design: Difficulty/dual_variant_calc/reconciliation_variance_provisional_vs_final_diverge
    """
    scenario = alpha_and_beta_scenario(api)
    kept = send_from_alpha(api, scenario, 250_000_000)
    returned = send_from_alpha(api, scenario, 30_000_000)
    accept_transfer(api, kept["id"])
    accept_transfer(api, returned["id"])

    set_clock(api, "2026-08-03T13:10:00Z")
    settle_transfer(api, kept["id"])
    settle_transfer(api, returned["id"])

    set_clock(api, "2026-08-03T13:20:00Z")
    request = lodge_return_request(
        api, returned["id"], scenario.beta.id, reason_code="TECHNICAL_ERROR"
    )
    set_clock(api, "2026-08-03T13:25:00Z")
    honor_return_request(api, request["id"])
    assert_transfer_dimensions(read_transfer(api, returned["id"]), "SETTLED", "RETURN_HONORED")

    set_clock(api, "2026-08-03T13:30:00Z")
    cycle = cutoff_cycle(api, scenario.cycle_id)
    assert cycle["assessed_fee_total_cents"] == 280_000
    assert cycle["settled_transfer_count"] == 2

    core_total = -220_280_000
    provisional = submit_reconciliation_run(
        api, scenario.cycle_id, scenario.alpha.id, core_total, "PROVISIONAL"
    )
    assert_reconciliation_figures(
        provisional,
        rail_net_position_cents=-250_000_000,
        variance_cents=29_720_000,
        outcome="OUT_OF_BALANCE",
        included_transfer_count=3,
        fee_component_cents=0,
        revision=1,
    )

    final = submit_reconciliation_run(
        api, scenario.cycle_id, scenario.alpha.id, core_total, "FINAL"
    )
    assert_reconciliation_figures(
        final,
        rail_net_position_cents=-220_280_000,
        variance_cents=0,
        outcome="BALANCED",
        included_transfer_count=2,
        fee_component_cents=-280_000,
        revision=1,
    )
    assert read_cycle(api, scenario.cycle_id)["status"] == "RECONCILING"
    assert read_account(api, scenario.alpha.account_id)["current_balance_cents"] == 949_720_000
