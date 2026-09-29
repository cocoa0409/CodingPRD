"""Per-component coinsurance rounding against rounding the summed remainder."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions, fixtures
from test_helpers.test_users import BENEFITS_A_HEADERS


def _uncapped_plan_order(api):
    """An expedited surfaced order on a plan whose cap can never bind."""
    scenario = fixtures.surfaced_registry(
        api, plan_code="VSP-UNCAPPED", annual_benefit_cap_cents=100000
    )
    scenario = fixtures.surfaced_verified_prescription(api, scenario)
    scenario = fixtures.surfaced_draft_order(api, scenario)
    scenario = fixtures.surfaced_layout_ready_order(api, scenario)
    return fixtures.surfaced_queued_job(api, scenario)


def test_benefit_sums_four_separately_rounded_coinsurance_contributions(api):
    """29000 of allowances plus 14182 of per-component coinsurance, never 14183.

    PRD 3.9: "Rounding once on the summed uncovered amount is not equivalent and is
    not permitted: whenever the per-component fractional parts add to more than a
    cent, the two approaches differ."

    Design: Difficulty/combinatorial_formula/benefit_coinsurance_rounds_per_component_never_on_the_summed_remainder
    """
    scenario = _uncapped_plan_order(api)

    order = validate_success(api.apply_benefit(scenario["order_id"], BENEFITS_A_HEADERS))

    assert order["gross_charge_cents"] == 81977
    # 6995, 30495, 2995 and 2495 uncovered, each rounded on its own at 0.33.
    assert order["insurance_benefit_cents"] == 43182
    assert order["insurance_benefit_cents"] != 43183


def test_patient_portion_and_rolling_usage_follow_the_per_component_benefit(api):
    """The one-cent choice propagates into the patient portion and the ledger.

    PRD 3.9: "The uncapped benefit is the sum of all component allowances plus the
    sum of all per-component coinsurance contributions, plus `expedite_fee_cents`
    in full when the plan's `expedite_covered` is true."

    Design: Difficulty/combinatorial_formula/benefit_coinsurance_rounds_per_component_never_on_the_summed_remainder
    """
    scenario = _uncapped_plan_order(api)

    validate_success(api.apply_benefit(scenario["order_id"], BENEFITS_A_HEADERS))

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["patient_portion_cents"] == 38795
    assert order["lab_writeoff_cents"] == 0
    assertions.assert_money_identity(order)

    patient = fixtures.read_patient(api, scenario["patient_id"])
    assert patient["benefit_used_cents"] == 43182
