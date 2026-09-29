"""The provisional and the final quote priced on one and the same order."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions, fixtures
from test_helpers.test_users import BENEFITS_A_HEADERS


def _committed_expedited_order(api):
    """An expedited progressive order committed to a surfacing route."""
    return fixtures.surfaced_queued_job(api)


def test_provisional_quote_prices_the_lens_without_the_surfacing_surcharge(api):
    """The provisional quote knows no route, so no surcharge and a 24-hour promise.

    PRD 3.3: "The lens component's charge is the design's `retail_price_cents`,
    plus a surfacing surcharge of 4500 cents that applies **only** in the final
    quote and **only** when the job's route turned out to require surfacing."

    Design: Difficulty/dual_variant_calc/order_quote_provisional_versus_final_diverges_on_rx_order_money
    """
    scenario = _committed_expedited_order(api)

    summary = validate_success(
        api.get_charge_summary(scenario["order_id"], BENEFITS_A_HEADERS)
    )

    assert summary["quote_variant"] == "PROVISIONAL"
    assert summary["gross_charge_cents"] == 81126
    assert summary["expedite_fee_cents"] == 13646


def test_provisional_projection_reports_the_uncapped_waterfall(api):
    """At intake the projection ignores the plan's annual cap entirely.

    PRD 3.3: "`estimated_benefit_cents` is the **uncapped** result of the benefit
    waterfall described in §3.9 — the annual cap is deliberately not applied,
    because at intake the store wants to show the patient what the plan is worth,
    not what is left of it."

    Design: Difficulty/dual_variant_calc/order_quote_provisional_versus_final_diverges_on_rx_order_money
    """
    scenario = _committed_expedited_order(api)

    summary = validate_success(
        api.get_charge_summary(scenario["order_id"], BENEFITS_A_HEADERS)
    )

    # 29000 of allowances plus 12697 of per-component coinsurance, uncapped even
    # though the plan's annual cap is only 40000.
    assert summary["estimated_benefit_cents"] == 41697
    assert summary["insurance_benefit_cents"] == 0


def test_final_quote_adds_the_surcharge_and_drops_the_expedite_fee(api):
    """The lens subtotal rises by 4500 while the fee falls from 13646 to 9997.

    PRD 3.3: "Because the surfacing penalty *lengthens* the promise, recomputing
    an expedited order with the actual route can push `promised_tat_hours` into a
    **cheaper** band — so the final expedite fee can be strictly lower than the
    provisional one even though the final lens subtotal is strictly higher."

    Design: Difficulty/dual_variant_calc/order_quote_provisional_versus_final_diverges_on_rx_order_money
    """
    scenario = _committed_expedited_order(api)
    provisional = validate_success(
        api.get_charge_summary(scenario["order_id"], BENEFITS_A_HEADERS)
    )

    validate_success(api.apply_benefit(scenario["order_id"], BENEFITS_A_HEADERS))

    final = validate_success(
        api.get_charge_summary(scenario["order_id"], BENEFITS_A_HEADERS)
    )
    assert final["quote_variant"] == "FINAL"
    assert final["gross_charge_cents"] == 81977
    assert final["expedite_fee_cents"] == 9997
    assert final["expedite_fee_cents"] < provisional["expedite_fee_cents"]
    assert final["gross_charge_cents"] > provisional["gross_charge_cents"]

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["promised_tat_hours"] == 36


def test_final_quote_caps_the_benefit_and_keeps_the_money_identity_exact(api):
    """The capped benefit lands on the 40000 cap and the identity still holds.

    PRD 3.9: "The patient portion for the final variant is the gross charge less
    `insurance_benefit_cents` less `lab_writeoff_cents`."

    Design: Difficulty/dual_variant_calc/order_quote_provisional_versus_final_diverges_on_rx_order_money
    """
    scenario = _committed_expedited_order(api)

    validate_success(api.apply_benefit(scenario["order_id"], BENEFITS_A_HEADERS))

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["insurance_benefit_cents"] == 40000
    assert order["patient_portion_cents"] == 41977
    assert order["lab_writeoff_cents"] == 0
    assertions.assert_money_identity(order)

    patient = fixtures.read_patient(api, scenario["patient_id"])
    assert patient["benefit_used_cents"] == 40000
