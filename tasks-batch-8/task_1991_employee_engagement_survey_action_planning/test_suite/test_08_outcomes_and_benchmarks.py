"""Outcome linkage, the attrition risk index variants, and benchmark floors."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_cycle,
    get_direct_snapshot,
    get_success_data,
    api_client,
    setup_cycle_with_field_results,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.factories import create_benchmark_set_payload, create_outcome_linkage_payload

PEOPLE_ANALYST = TEST_USERS["people_analyst_headers"]

RISK_ANSWERS = [[3, 3, 3]] * 10


def _low_scoring_census(api, unit_name, manager_id):
    """10 submitters answering a uniform 3 -> overall 50.00, below the 60.00
    low-engagement floor; cycle driven CLOSED -> SCORING."""
    return setup_cycle_with_field_results(
        bank_name=f"{unit_name}Bank",
        item_specs=[
            {"item_code": "R-01", "dimension": "WORKLOAD", "weight": 1.0},
            {"item_code": "R-02", "dimension": "WORKLOAD", "weight": 1.0},
            {"item_code": "R-03", "dimension": "WORKLOAD", "weight": 1.0},
        ],
        unit_name=unit_name,
        manager_user_id=manager_id,
        min_n_threshold=3,
        num_employees=10,
        target_state="SCORING",
        submitters=10,
        submit_scores=RISK_ANSWERS,
    )


def test_provisional_attrition_risk_uses_prior_base_rate(api):
    """PRD §3.8: "The provisional variant is computed at the `CLOSED → SCORING`
    transition, before any outcome linkage rows exist: it uses a prior base
    rate of 0.08 as a forward-looking estimate."
    PRD §3.8: "Either variant then applies the engagement modifier identically:
    when the snapshot's `overall_score` is below the low-engagement floor of
    60.00, the base rate is multiplied by the sum of 1 and the risk coefficient
    1.75; otherwise it is multiplied by 1 alone."

    Design: Difficulty/dual_variant_calc/attrition_risk_provisional_vs_final
    """
    sc = _low_scoring_census(api, "RiskProv", "mgr-rp")
    snap = get_direct_snapshot(sc["cycle"]["id"], sc["unit"]["id"])
    assert snap["overall_score"] == pytest.approx(50.00, abs=0.005), (
        "uniform 3s -> scaled 50.00, below the 60.00 low-engagement floor"
    )

    cycle = get_cycle(sc["cycle"]["id"])
    assert cycle["attrition_risk"] == pytest.approx(0.22, abs=1e-9), (
        "provisional variant at SCORING: 0.08 * (1 + 1.75) = 0.2200"
    )


def test_final_attrition_risk_supersedes_provisional(api):
    """PRD §3.8: "The final variant is computed once attrition linkage rows
    exist for the cycle and supersedes the provisional value: the base rate is
    the observed ratio of attrition linkage rows whose `outcome_value` is
    `VOLUNTARY` or `INVOLUNTARY` to the cycle's count of `SUBMITTED`
    invitations, and the risk is null when that denominator is zero."
    PRD §3.8: "Either variant then applies the engagement modifier identically:
    when the snapshot's `overall_score` is below the low-engagement floor of
    60.00, the base rate is multiplied by the sum of 1 and the risk coefficient
    1.75; otherwise it is multiplied by 1 alone."

    Design: Difficulty/dual_variant_calc/attrition_risk_provisional_vs_final
    """
    sc = _low_scoring_census(api, "RiskFinal", "mgr-rf")
    cycle_id = sc["cycle"]["id"]
    provisional = get_cycle(cycle_id)["attrition_risk"]
    assert provisional == pytest.approx(0.22, abs=1e-9)

    for employee in sc["employees"][:2]:
        resp = api.create_outcome_linkage(
            employee["id"],
            create_outcome_linkage_payload(
                cycle_id=cycle_id, outcome_kind="ATTRITION", outcome_value="VOLUNTARY"
            ),
            PEOPLE_ANALYST,
        )
        validate_success(resp, 201)

    final = get_cycle(cycle_id)["attrition_risk"]
    assert final == pytest.approx(0.55, abs=1e-9), (
        "final variant: observed base 2/10 = 0.20 * (1 + 1.75) = 0.5500"
    )
    assert final != pytest.approx(provisional, abs=1e-9), (
        "the final variant supersedes the provisional 0.2200 estimate"
    )


def test_benchmark_set_requires_at_least_five_entries(api):
    """PRD §3.6: "A `PeopleAnalyst` registers a **benchmark set** — a reference
    distribution such as "Tech Industry 2026" — with a `name` and a
    `dimension_scores` array holding at least five reference overall scores,
    each between 0 and 100 inclusive at 2 decimal places; a thinner
    distribution is rejected with `ERR_BENCHMARK_TOO_SMALL` (HTTP 422)."

    Design: Corner/errors/error_benchmark_too_small
    """
    resp_small = api.create_benchmark_set(
        create_benchmark_set_payload(name="Tiny", dimension_scores=[50, 60, 70, 80]),
        PEOPLE_ANALYST,
    )
    validate_error(resp_small, ApiErrorId.ERR_BENCHMARK_TOO_SMALL)

    resp_ok = api.create_benchmark_set(
        create_benchmark_set_payload(name="OK", dimension_scores=[50, 60, 70, 80, 90]),
        PEOPLE_ANALYST,
    )
    bench = validate_success(resp_ok, 201)
    assert bench["status"] == "ACTIVE", "exactly five entries accepted at the inclusive floor"
