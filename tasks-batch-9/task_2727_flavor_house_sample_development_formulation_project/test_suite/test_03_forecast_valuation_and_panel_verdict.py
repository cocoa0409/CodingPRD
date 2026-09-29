"""Forecast valuation variants and the panel-score pass boundary."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.factories import close_brief_payload
from test_helpers.fixtures import (
    CITRUS_LINE_WEIGHTS,
    approve_formula,
    build_formula_with_lines,
    citrus_accepted_brief,
    citrus_approved_formula,
    citrus_materials,
    citrus_released_lot,
    cost_formula,
    create_rig,
    publish_forecast,
    read_brief,
    read_forecast,
    read_formula,
    record_application_test_result,
    schedule_application_test,
    start_application_test,
    submit_formula,
)
from test_helpers.test_users import ACCOUNT_MANAGER

PANEL_WINDOW_START = "2026-08-10T08:00:00Z"
PANEL_WINDOW_END = "2026-08-10T10:00:00Z"


def _forecast_for(api, brief_id):
    brief = read_brief(api, brief_id)
    return publish_forecast(api, brief_id, brief["version"],
                            annual_volume_kg=1200, unit_price_cents_per_kg=4200)


def _approve_citrus_formula_on(api, brief_id, materials):
    """Take the three citrus lines from DRAFT to APPROVED on an existing brief."""
    built = build_formula_with_lines(
        api, brief_id,
        [(materials["m1"]["id"], CITRUS_LINE_WEIGHTS[0]),
         (materials["m2"]["id"], CITRUS_LINE_WEIGHTS[1]),
         (materials["m3"]["id"], CITRUS_LINE_WEIGHTS[2])],
        name="Citrus Top Note F1")
    cost_formula(api, built["formula"]["id"])
    submit_formula(api, built["formula"]["id"])
    return approve_formula(api, built["formula"]["id"])


def test_risk_weighted_forecast_climbs_when_a_formula_reaches_approved(api):
    """The same volume and price value at 1247400 then at 1814400.

    The PRD sets `technical_factor` to "0.80 when there is an approved formula
    but no passed test, and 0.55 when there is not even an approved formula",
    with `stage_probability` "0.45 when the brief is `ACCEPTED`".  The gross
    figure 1200 x 4200 is 5040000, so the two risk-weighted values are
    5040000 x 0.45 x 0.55 = 1247400 and 5040000 x 0.45 x 0.80 = 1814400.

    Design: Difficulty/dual_variant_calc/forecast_risk_weighted_vs_committed_variant_divergence
    """
    materials = citrus_materials(api)
    brief = citrus_accepted_brief(api)

    early = _forecast_for(api, brief["id"])
    assert early["weighted_annual_value_cents"] == 1247400
    assert early["variant_applied"] == "RISK_WEIGHTED"
    assert float(early["technical_factor"]) == 0.55

    _approve_citrus_formula_on(api, brief["id"], materials)
    later = _forecast_for(api, brief["id"])

    assert later["weighted_annual_value_cents"] == 1814400
    assert later["variant_applied"] == "RISK_WEIGHTED"
    assert float(later["stage_probability"]) == 0.45
    assert float(later["technical_factor"]) == 0.80


def test_publishing_a_second_forecast_freezes_the_first_at_its_last_value(api):
    """The superseded forecast keeps 1247400 rather than re-valuing.

    The PRD says "the brief's existing forecasts in `ACTIVE` or `AT_RISK` are
    moved to `SUPERSEDED`, where their computed values stay frozen at whatever
    they last held".

    Design: Difficulty/dual_variant_calc/forecast_risk_weighted_vs_committed_variant_divergence
    """
    scenario = citrus_approved_formula(api)
    brief_id = scenario["brief"]["id"]

    early = publish_forecast(api, brief_id, read_brief(api, brief_id)["version"],
                             annual_volume_kg=1200, unit_price_cents_per_kg=4200)
    second = _forecast_for(api, brief_id)

    frozen = read_forecast(api, early["id"])
    assert frozen["status"] == "SUPERSEDED"
    assert frozen["weighted_annual_value_cents"] == early["weighted_annual_value_cents"]
    assert second["status"] == "ACTIVE"
    assert second["id"] != early["id"]


def test_closing_the_brief_as_won_switches_the_forecast_to_the_committed_variant(api):
    """One CLOSED_WON transition takes 1814400 to the full 5040000.

    The PRD says "when the brief has reached `CLOSED_WON` the committed
    variant applies instead: `variant_applied` records `COMMITTED`, both
    `stage_probability` and `technical_factor` are pinned at 1.00, and
    `weighted_annual_value_cents` is the gross figure itself", and that a win
    "moves the brief's forecasts in `ACTIVE` or `AT_RISK` to `REALIZED`".

    Design: Difficulty/dual_variant_calc/forecast_risk_weighted_vs_committed_variant_divergence
    """
    scenario = citrus_approved_formula(api)
    brief_id = scenario["brief"]["id"]
    forecast = _forecast_for(api, brief_id)
    assert forecast["weighted_annual_value_cents"] == 1814400

    get_success_data(
        api.close_customer_brief(brief_id, close_brief_payload("WON"), ACCOUNT_MANAGER),
        200)

    realized = read_forecast(api, forecast["id"])
    assert realized["variant_applied"] == "COMMITTED"
    assert realized["weighted_annual_value_cents"] == 5040000
    assert float(realized["stage_probability"]) == 1.00
    assert float(realized["technical_factor"]) == 1.00
    assert realized["status"] == "REALIZED"

    closed = read_brief(api, brief_id)
    assert closed["status"] == "CLOSED_WON"
    assert closed["outcome"] == "WON"


def test_a_panel_score_of_exactly_seventy_passes_the_test(api):
    """70 / 70 / 70 weights to exactly 70.00 and the verdict is PASSED.

    The PRD weights the composite as "the aroma score multiplied by 0.40, plus
    the taste score multiplied by 0.35, plus the stability score multiplied by
    0.25, with a single round-half-up to two decimal places", then says "a
    `panel_score` of at least 70.00 drives `IN_PROGRESS → PASSED` ... A score
    of exactly 70.00 passes."

    Design: Difficulty/boundary_precision_check/panel_score_exactly_at_pass_threshold_passes
    """
    scenario = citrus_released_lot(api, batch_size_g=500)
    rig = create_rig(api, rig_code="RIG-BEV-01", matrix_type="BEVERAGE_STILL",
                     cleanout_buffer_minutes=30)
    test = schedule_application_test(api, scenario["lot"]["id"], rig["id"],
                                     dosage_pct=2.5, consumed_g=100,
                                     window_start=PANEL_WINDOW_START,
                                     window_end=PANEL_WINDOW_END)
    start_application_test(api, test["id"])

    recorded = record_application_test_result(api, test["id"], 70, 70, 70)

    assert float(recorded["panel_score"]) == 70.00
    assert recorded["status"] == "PASSED"
    assert recorded["status"] != "FAILED"


def test_a_pass_at_the_threshold_leaves_the_formula_approved(api):
    """A passing verdict is not a rework trigger.

    The PRD reserves the rework chain for failures — "because the test failed,
    the lot's formula — if it was `APPROVED` — is pushed to `REWORK_REQUIRED`
    with `rework_reason` `APPLICATION_TEST_FAILURE`" — so a pass must leave the
    formula alone.

    Design: Difficulty/boundary_precision_check/panel_score_exactly_at_pass_threshold_passes
    """
    scenario = citrus_released_lot(api, batch_size_g=500)
    rig = create_rig(api, rig_code="RIG-BEV-01", matrix_type="BEVERAGE_STILL",
                     cleanout_buffer_minutes=30)
    test = schedule_application_test(api, scenario["lot"]["id"], rig["id"],
                                     dosage_pct=2.5, consumed_g=100,
                                     window_start=PANEL_WINDOW_START,
                                     window_end=PANEL_WINDOW_END)
    start_application_test(api, test["id"])
    record_application_test_result(api, test["id"], 70, 70, 70)

    formula = read_formula(api, scenario["formula"]["id"])
    assert formula["status"] == "APPROVED"
    assert formula["rework_reason"] is None


def test_a_threshold_pass_reweights_the_forecast_with_proven_technical_factor(api):
    """The forecast moves from 1814400 to 2268000 on the passing verdict.

    The PRD says `technical_factor` is "1.00 when the brief has at least one
    formula in `APPROVED` *and* at least one application test in `PASSED`",
    and that on a pass "a commercialization forecast of the brief in `ACTIVE`
    or `AT_RISK` has its `technical_factor` recomputed to 1.00 and its
    `weighted_annual_value_cents` recomputed accordingly": 5040000 x 0.45 x
    1.00 is 2268000.

    Design: Difficulty/boundary_precision_check/panel_score_exactly_at_pass_threshold_passes
    """
    scenario = citrus_released_lot(api, batch_size_g=500)
    forecast = _forecast_for(api, scenario["brief"]["id"])
    assert forecast["weighted_annual_value_cents"] == 1814400

    rig = create_rig(api, rig_code="RIG-BEV-01", matrix_type="BEVERAGE_STILL",
                     cleanout_buffer_minutes=30)
    test = schedule_application_test(api, scenario["lot"]["id"], rig["id"],
                                     dosage_pct=2.5, consumed_g=100,
                                     window_start=PANEL_WINDOW_START,
                                     window_end=PANEL_WINDOW_END)
    start_application_test(api, test["id"])
    record_application_test_result(api, test["id"], 70, 70, 70)

    reweighted = read_forecast(api, forecast["id"])
    assert float(reweighted["technical_factor"]) == 1.00
    assert reweighted["weighted_annual_value_cents"] == 2268000
    assert reweighted["status"] == "ACTIVE"
