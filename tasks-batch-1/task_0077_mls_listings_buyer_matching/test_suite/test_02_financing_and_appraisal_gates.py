"""Appraisal-gap and financing-DTI contingency gates (boundary precision)."""
from test_helpers import (
    validate_success,
    setup_accepted_offer,
    contingency_by_kind,
    make_buyer_agent_headers,
)


def _resolve(api, contingency_id, buyer_agent_id, payload=None):
    resp = api.resolve_contingency(
        contingency_id, payload, headers=make_buyer_agent_headers(buyer_agent_id))
    return validate_success(resp, 200)


def test_appraisal_and_financing_gates_diverge_on_same_offer(api):
    """PRD §3.7: "the gate satisfies the contingency only when the appraised value is
    at least the offer's `effective_price_cents`, and otherwise lands it in `FAILED`
    (a low appraisal)."
    PRD §3.7: "The contingency passes only when two conditions both hold: the back-end
    ratio is at most the maximum allowed ratio of 0.43 (a ratio of exactly 0.43
    passes; 0.4300001 fails), and the offer's `effective_price_cents` is at most the
    buyer's `prequalified_amount_cents`. If either condition is not met, the financing
    contingency lands in `FAILED`."

    Design: Difficulty/dual_variant_calc/appraisal_gap_vs_financing_dti_diverge_on_contingency
    """
    # Buyer: income=1000000, debt=180001, prequal=50000000; offer price 50000000.
    # monthly_pi = round_half_up(50000000*0.005)=250000; DTI=(180001+250000)/1000000
    # = 0.430001 > 0.43 -> FINANCING FAILS. APPRAISAL at exactly 50000000 SATISFIES.
    s = setup_accepted_offer(
        initial_price_cents=50_000_000,
        requested_contingencies=["APPRAISAL", "FINANCING"],
        buyer_overrides={
            "monthly_income_cents": 1_000_000,
            "monthly_debt_cents": 180_001,
            "prequalified_amount_cents": 50_000_000,
            "max_budget_cents": 60_000_000,
        })
    ba = s["buyer_agent"]["id"]
    appr = contingency_by_kind(s["contingencies"], "APPRAISAL")
    fin = contingency_by_kind(s["contingencies"], "FINANCING")

    appr_res = _resolve(api, appr["id"], ba, {"appraised_value_cents": 50_000_000})
    fin_res = _resolve(api, fin["id"], ba)

    assert appr_res["status"] == "SATISFIED", appr_res
    assert fin_res["status"] == "FAILED", fin_res


def test_appraisal_satisfies_while_financing_fails_divergent_outcomes(api):
    """PRD §3.7: "For an `APPRAISAL` contingency, the buyer's agent supplies an
    `appraised_value_cents`; the gate satisfies the contingency only when the appraised
    value is at least the offer's `effective_price_cents`, and otherwise lands it in
    `FAILED` (a low appraisal). For a `FINANCING` contingency, the gate is a
    debt-to-income test combined with a pre-qualification ceiling test, detailed below;
    it satisfies the contingency only when both tests pass and otherwise lands it in
    `FAILED`."

    Design: Difficulty/dual_variant_calc/appraisal_gap_vs_financing_dti_diverge_on_contingency
    """
    # Same accepted offer; the two gates reach opposite terminal statuses. After the
    # appraisal SATISFIES but financing FAILS, the financing failure unwinds the deal.
    s = setup_accepted_offer(
        initial_price_cents=50_000_000,
        requested_contingencies=["APPRAISAL", "FINANCING"],
        buyer_overrides={
            "monthly_income_cents": 1_000_000,
            "monthly_debt_cents": 180_001,
            "prequalified_amount_cents": 50_000_000,
            "max_budget_cents": 60_000_000,
        })
    ba = s["buyer_agent"]["id"]
    appr = contingency_by_kind(s["contingencies"], "APPRAISAL")
    fin = contingency_by_kind(s["contingencies"], "FINANCING")

    appr_res = _resolve(api, appr["id"], ba, {"appraised_value_cents": 50_000_000})
    assert appr_res["status"] == "SATISFIED", appr_res
    fin_res = _resolve(api, fin["id"], ba)
    assert fin_res["status"] == "FAILED", fin_res
    # Distinct terminal statuses on the same offer — the two gates diverged.
    assert appr_res["status"] != fin_res["status"]


def test_financing_gate_passes_at_exact_dti_boundary(api):
    """PRD §3.7: "The contingency passes only when two conditions both hold: the
    back-end ratio is at most the maximum allowed ratio of 0.43 (a ratio of exactly
    0.43 passes; 0.4300001 fails), and the offer's `effective_price_cents` is at most
    the buyer's `prequalified_amount_cents`."

    Design: Difficulty/combinatorial_formula/financing_dti_three_input_nonlinear_gate
    """
    # income=1000000, debt=180000, price 50000000 -> monthly_pi=250000;
    # DTI=(180000+250000)/1000000 = 0.43 exactly -> passes; prequal 50000000 == price.
    s = setup_accepted_offer(
        initial_price_cents=50_000_000,
        requested_contingencies=["FINANCING"],
        buyer_overrides={
            "monthly_income_cents": 1_000_000,
            "monthly_debt_cents": 180_000,
            "prequalified_amount_cents": 50_000_000,
            "max_budget_cents": 60_000_000,
        })
    ba = s["buyer_agent"]["id"]
    fin = contingency_by_kind(s["contingencies"], "FINANCING")
    res = _resolve(api, fin["id"], ba)
    assert res["status"] == "SATISFIED", res


def test_financing_gate_fails_one_past_dti_boundary(api):
    """PRD §3.7: "The contingency passes only when two conditions both hold: the
    back-end ratio is at most the maximum allowed ratio of 0.43 (a ratio of exactly 0.43
    passes; 0.4300001 fails), and the offer's `effective_price_cents` is at most the
    buyer's `prequalified_amount_cents`. If either condition is not met, the financing
    contingency lands in `FAILED`."

    Design: Difficulty/combinatorial_formula/financing_dti_three_input_nonlinear_gate
    """
    # debt=180001 pushes DTI to 0.430001 > 0.43 -> FAILED, all else passing.
    s = setup_accepted_offer(
        initial_price_cents=50_000_000,
        requested_contingencies=["FINANCING"],
        buyer_overrides={
            "monthly_income_cents": 1_000_000,
            "monthly_debt_cents": 180_001,
            "prequalified_amount_cents": 50_000_000,
            "max_budget_cents": 60_000_000,
        })
    ba = s["buyer_agent"]["id"]
    fin = contingency_by_kind(s["contingencies"], "FINANCING")
    res = _resolve(api, fin["id"], ba)
    assert res["status"] == "FAILED", res


def test_appraisal_gate_satisfies_at_exact_equality(api):
    """PRD §3.7: "the gate satisfies the contingency only when the appraised value is
    at least the offer's `effective_price_cents`, and otherwise lands it in `FAILED`
    (a low appraisal)."

    Design: Difficulty/boundary_precision_check/appraisal_gap_exact_equality_satisfies
    """
    s = setup_accepted_offer(
        initial_price_cents=50_000_000,
        requested_contingencies=["APPRAISAL"],
        buyer_overrides={"max_budget_cents": 60_000_000})
    ba = s["buyer_agent"]["id"]
    appr = contingency_by_kind(s["contingencies"], "APPRAISAL")
    res = _resolve(api, appr["id"], ba, {"appraised_value_cents": 50_000_000})
    assert res["status"] == "SATISFIED", res


def test_appraisal_gate_fails_one_cent_below(api):
    """PRD §3.7: "the gate satisfies the contingency only when the appraised value is
    at least the offer's `effective_price_cents`, and otherwise lands it in `FAILED`
    (a low appraisal)."

    Design: Difficulty/boundary_precision_check/appraisal_gap_exact_equality_satisfies
    """
    s = setup_accepted_offer(
        initial_price_cents=50_000_000,
        requested_contingencies=["APPRAISAL"],
        buyer_overrides={"max_budget_cents": 60_000_000})
    ba = s["buyer_agent"]["id"]
    appr = contingency_by_kind(s["contingencies"], "APPRAISAL")
    res = _resolve(api, appr["id"], ba, {"appraised_value_cents": 49_999_999})
    assert res["status"] == "FAILED", res
