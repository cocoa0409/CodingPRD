"""
Priority scoring: the same structure ranked by two different cycle policies.

PRD §3.8: "`priority_score` is a weighted score whose *variant is chosen by the
owning cycle's* `ranking_policy`, and the policy in force at scoring time is
frozen onto the candidate as `ranking_policy_applied`."
"""

from test_helpers import assertions as a
from test_helpers import fixtures as fx


def _two_cycles_and_a_low_risk_structure(client, roster, bridge):
    """
    Open a `CONDITION_BASED` cycle and a `RISK_BASED` cycle, accept the baseline
    report, and finalise a scour evaluation at code 5 so the structure reads
    `LOW_RISK`.

    Both cycles are opened *before* the report is accepted so that the
    acceptance cascade of PRD §3.3 files no automatic candidate: that hop fires
    only when "exactly one cycle is in `PLANNING`".
    """
    condition_cycle = fx.create_cycle(
        client, fiscal_year=2027, ranking_policy="CONDITION_BASED"
    )
    risk_cycle = fx.create_cycle(client, fiscal_year=2028, ranking_policy="RISK_BASED")
    report = fx.accepted_report(client, bridge["id"], roster)
    evaluation = fx.create_scour_evaluation(client, bridge["id"], roster, 5)
    fx.finalize_scour(client, evaluation["id"], roster)
    return {
        "condition_cycle": condition_cycle,
        "risk_cycle": risk_cycle,
        "report": report,
        "evaluation": evaluation,
    }


def test_condition_based_and_risk_based_scores_diverge_on_one_structure(
    client, roster, bridge
):
    """
    One structure, two cycles, two policies: the condition ranking scores it
    43.41 and the risk ranking scores it 36.21, a divergence of 7.20 points.

    PRD §3.8: "The `CONDITION_BASED` variant is the default statewide
    preservation ranking and uses condition inputs only: 0.50 times the condition
    gap, plus 0.30 times the rating gap, plus 0.20 times the structure's
    `deficiency_pct`. It ignores scour, traffic exposure and posting entirely."
    PRD §3.8: "The `RISK_BASED` variant is used in cycles that prioritise
    vulnerability and public exposure: it replaces the rating-gap and deficiency
    terms with 0.35 times the condition gap, plus 0.25 times the scour points,
    plus 0.25 times the exposure points, plus 0.15 times the posting points".
    PRD §3.8: "Under `CONDITION_BASED` the score is 17.265 plus 20.00 plus 6.146,
    which is 43.411, rounded to 43.41. Under `RISK_BASED` the exposure term is
    48.0 plus 8.5, which is 56.50 and below the cap, and the score is 12.0855
    plus 10.00 plus 14.125 plus 0, which is 36.2105, rounded to 36.21. Identical
    structure, identical cycle data, 7.20 points of divergence."

    Design: Difficulty/dual_variant_calc/candidate_priority_condition_vs_risk_policy_diverge
    """
    setup = _two_cycles_and_a_low_risk_structure(client, roster, bridge)

    condition_candidate = fx.identify_candidate(
        client, setup["condition_cycle"]["id"], bridge["id"], roster
    )
    risk_candidate = fx.identify_candidate(
        client, setup["risk_cycle"]["id"], bridge["id"], roster
    )

    assert condition_candidate["ranking_policy_applied"] == "CONDITION_BASED"
    assert risk_candidate["ranking_policy_applied"] == "RISK_BASED"
    assert condition_candidate["priority_score"] == 43.41
    assert risk_candidate["priority_score"] == 36.21
    assert round(
        condition_candidate["priority_score"] - risk_candidate["priority_score"], 2
    ) == 7.20
    a.assert_two_decimals(condition_candidate["priority_score"], "priority_score")
    a.assert_two_decimals(risk_candidate["priority_score"], "priority_score")


def test_the_two_policies_agree_on_work_type_and_cost_while_disagreeing_on_rank(
    client, roster, bridge
):
    """
    Only the score is policy-dependent. Work type comes from the structure's
    minimum component rating and the estimate comes from the source report's
    deficient quantities, so both candidates carry the same values.

    PRD §3.8: "`work_type` is a first-match threshold on the structure's
    `min_nbi_rating` at the moment of creation: a rating of 3 or below yields
    `REPLACEMENT`".
    PRD §3.8: "a subtotal of 23,120,000, which multiplied by 1.15 gives
    26,588,000 cents."
    PRD §3.8: "A candidate created through this route records `origin` `MANUAL`".

    Design: Difficulty/dual_variant_calc/candidate_priority_condition_vs_risk_policy_diverge
    """
    setup = _two_cycles_and_a_low_risk_structure(client, roster, bridge)

    condition_candidate = fx.identify_candidate(
        client, setup["condition_cycle"]["id"], bridge["id"], roster
    )
    risk_candidate = fx.identify_candidate(
        client, setup["risk_cycle"]["id"], bridge["id"], roster
    )

    for candidate, label in (
        (condition_candidate, "condition-ranked candidate"),
        (risk_candidate, "risk-ranked candidate"),
    ):
        assert candidate["work_type"] == "REPLACEMENT", label
        assert candidate["estimated_cost_cents"] == 26588000, label
        a.assert_whole_cents(candidate["estimated_cost_cents"], f"{label} estimate")
        assert candidate["origin"] == "MANUAL", label
        assert candidate["status"] == "IDENTIFIED", label
        assert candidate["bridge_id"] == bridge["id"], label

    assert condition_candidate["program_cycle_id"] == setup["condition_cycle"]["id"]
    assert risk_candidate["program_cycle_id"] == setup["risk_cycle"]["id"]


def test_one_structure_holds_live_candidates_in_two_cycles_at_once(
    client, roster, bridge
):
    """
    The supersede rule is scoped to a structure-and-cycle pair, so filing in the
    second cycle does not withdraw the candidate filed in the first.

    PRD §3.8: "Note the supersede is scoped to the pair of structure and cycle:
    the same structure may hold live candidates in two different cycles
    simultaneously, and superseding never touches a candidate that has already
    been programmed or deferred."

    Design: Difficulty/dual_variant_calc/candidate_priority_condition_vs_risk_policy_diverge
    """
    setup = _two_cycles_and_a_low_risk_structure(client, roster, bridge)

    condition_candidate = fx.identify_candidate(
        client, setup["condition_cycle"]["id"], bridge["id"], roster
    )
    fx.identify_candidate(client, setup["risk_cycle"]["id"], bridge["id"], roster)

    still_live = fx.read_candidate(client, condition_candidate["id"])
    assert still_live["status"] == "IDENTIFIED", (
        "a candidate in another cycle must not be superseded"
    )
    assert still_live["withdrawn_at"] is None

    condition_rows = fx.candidates_in_cycle(client, setup["condition_cycle"]["id"])
    risk_rows = fx.candidates_in_cycle(client, setup["risk_cycle"]["id"])
    assert len(condition_rows) == 1
    assert len(risk_rows) == 1


def test_a_low_risk_scour_finding_leaves_the_structure_plan_compliant(
    client, roster, bridge
):
    """
    A finalised evaluation at code 5 lands in the middle band, and a structure
    that is not scour critical needs no plan of action to be compliant.

    PRD §3.6: "a code of 3 or below is `SCOUR_CRITICAL`, a code from 4 through 6
    is `LOW_RISK`, and a code of 7 or above is `STABILIZED`."
    PRD §3.6: "That flag is false exactly when `scour_status` is
    `SCOUR_CRITICAL` and no plan of action for the structure is `APPROVED`, and
    true in every other case — including on structures that are `LOW_RISK`,
    `STABILIZED` or `NOT_EVALUATED`."

    Design: Difficulty/dual_variant_calc/candidate_priority_condition_vs_risk_policy_diverge
    """
    setup = _two_cycles_and_a_low_risk_structure(client, roster, bridge)

    evaluation = fx.read_scour(client, setup["evaluation"]["id"])
    assert evaluation["status"] == "FINAL"
    assert evaluation["derived_scour_status"] == "LOW_RISK"

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["scour_status"] == "LOW_RISK"
    assert structure["poa_compliant"] is True
    assert structure["service_posture"] == "OPEN"

    plans = fx.plans_for_bridge(client, bridge["id"])
    assert plans == [], (
        "no plan of action is created for a structure that is not scour critical"
    )
