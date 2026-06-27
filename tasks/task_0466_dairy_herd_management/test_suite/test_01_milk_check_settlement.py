"""Milk-check settlement: advance vs final, multi-component gross, pooling.

Difficulty instances:
  dual_variant_calc / milk_check_advance_vs_final_settlement_diverge
  combinatorial_formula / milk_check_multi_component_nonlinear_settlement
Corner instances:
  calculations / milk_check_two_record_pool_aggregation
"""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    setup_provisional_milk_check_single_record,
    setup_open_lactation, add_test_day, create_price_sheet,
    api_client, TEST_USERS,
)

COOP = TEST_USERS["coop_agent_headers"]
HM = TEST_USERS["herd_manager_headers"]
VET = TEST_USERS["veterinarian_headers"]
PT = TEST_USERS["parlor_tech_headers"]


def test_advance_paid_is_milk_weight_only_at_provisional():
    """PRD §3.7: "The `advance_paid` is computed using only that pooled milk weight: take the announced `advance_rate_per_cwt`, multiply it by the pooled milk in hundredweight (the pooled pounds divided by 100), and round to 2 decimal places."
    PRD §3.7: "The advance deliberately ignores components, somatic-cell
    adjustments, and the PPD — those enter only at final settlement."

    Design: Difficulty/dual_variant_calc/milk_check_advance_vs_final_settlement_diverge
    """
    _h, _a, _l, milk_check, _ps, _tdr = setup_provisional_milk_check_single_record(
        scc_thousands=180, milk_weight_lbs=1000, fat_pct=3.8, protein_pct=3.1,
        herd_name="Dual Variant Dairy",
    )
    # advance is set at PROVISIONAL, before finalize.
    assert milk_check["advance_paid"] == 160.00, (
        f"advance_paid should be milk-weight-only 160.00, got {milk_check['advance_paid']}"
    )


def test_final_settlement_diverges_from_advance_on_finalize():
    """PRD §3.8: "Each of these five lines is rounded to 2 decimal places individually, and `gross_settlement` is their sum."
    PRD §3.8: "The `net_payable` is the `gross_settlement` minus the `advance_paid` recorded at creation minus this hauling deduction — an exact subtraction of the already-rounded values, no further rounding."

    Design: Difficulty/dual_variant_calc/milk_check_advance_vs_final_settlement_diverge
    """
    _h, _a, _l, milk_check, _ps, _tdr = setup_provisional_milk_check_single_record(
        scc_thousands=180, milk_weight_lbs=1000, fat_pct=3.8, protein_pct=3.1,
        herd_name="Dual Variant Dairy 2",
    )
    data = validate_success(
        api_client.finalize_milk_check(milk_check["id"], milk_check["version"], COOP)
    )
    assert data["gross_settlement"] == 251.55, data["gross_settlement"]
    assert data["net_payable"] == 83.05, data["net_payable"]
    assert data["advance_paid"] == 160.00, data["advance_paid"]
    assert data["advance_paid"] != data["gross_settlement"], (
        "advance variant and final variant must diverge"
    )


def test_gross_settlement_sums_five_component_lines():
    """PRD §3.8: "The **gross settlement** is the sum of five dollar lines, each rounded to the cent before they are added together."
    PRD §3.8: "For each pooled record the system derives three component pounds, each rounded to 2 decimal places: the fat pounds are `milk_weight_lbs` times `fat_pct` divided by 100; the protein pounds are `milk_weight_lbs` times `protein_pct` divided by 100; and the other-solids pounds are `milk_weight_lbs` times a fixed other-solids percentage of 5.7 divided by 100."

    Design: Difficulty/combinatorial_formula/milk_check_multi_component_nonlinear_settlement
    """
    _h, _a, _l, milk_check, _ps, _tdr = setup_provisional_milk_check_single_record(
        scc_thousands=180, milk_weight_lbs=1000, fat_pct=3.8, protein_pct=3.1,
        herd_name="Combo Dairy",
    )
    data = validate_success(
        api_client.finalize_milk_check(milk_check["id"], milk_check["version"], COOP)
    )
    assert data["pooled_fat_lbs"] == 38.00, data["pooled_fat_lbs"]
    assert data["pooled_protein_lbs"] == 31.00, data["pooled_protein_lbs"]
    assert data["pooled_other_solids_lbs"] == 57.00, data["pooled_other_solids_lbs"]
    assert data["gross_settlement"] == 251.55, data["gross_settlement"]


def test_weighted_scc_drives_nonlinear_scc_adjustment():
    """PRD §3.8: "The milk-weighted somatic-cell count `weighted_scc_thousands` is the sum over pooled records of each record's `scc_thousands` times its `milk_weight_lbs`, divided by the total pooled milk pounds, rounded to 2 decimal places."
    PRD §3.8: "The somatic-cell adjustment is the somatic-cell baseline of 350 (in thousands) minus the pool's `weighted_scc_thousands`, multiplied by a per-thousand-per-hundredweight rate of 0.0005, multiplied by the pool's hundredweight — a credit when the pool's weighted SCC is below the baseline and a debit when it is above."

    Design: Difficulty/combinatorial_formula/milk_check_multi_component_nonlinear_settlement
    """
    _h, _a, _l, milk_check, _ps, _tdr = setup_provisional_milk_check_single_record(
        scc_thousands=180, milk_weight_lbs=1000, fat_pct=3.8, protein_pct=3.1,
        herd_name="Combo Dairy 2",
    )
    data = validate_success(
        api_client.finalize_milk_check(milk_check["id"], milk_check["version"], COOP)
    )
    assert data["weighted_scc_thousands"] == 180.00, data["weighted_scc_thousands"]
    assert data["gross_settlement"] == 251.55, data["gross_settlement"]


def test_two_record_pool_aggregates_milk_and_weights_scc():
    """PRD §3.8: "The pooled totals are then the sums of these per-record figures: `pooled_milk_lbs` is the sum of the milk weights, `pooled_fat_lbs` the sum of the fat-pound lines, `pooled_protein_lbs` the sum of the protein-pound lines, and `pooled_other_solids_lbs` the sum of the other-solids lines."
    PRD §3.8: "The milk-weighted somatic-cell count `weighted_scc_thousands` is the sum over pooled records of each record's `scc_thousands` times its `milk_weight_lbs`, divided by the total pooled milk pounds, rounded to 2 decimal places."

    Design: Corner/calculations/milk_check_two_record_pool_aggregation
    """
    # Two milk_eligible cows in one herd, one 2026-06 test each.
    herd, _a1, lact1, _c1 = setup_open_lactation(
        herd_name="Two Record Dairy", ear_tag="TR-001",
        service_date="2026-01-10", calving_date="2026-02-01",
        calving_clock="2026-02-01T00:00:00Z",
    )
    # Second cow in the SAME herd via direct helpers.
    a2 = get_success_data(api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "TR-002", "birth_date": "2023-01-01"}, HM))
    be2 = get_success_data(api_client.create_breeding_event(
        {"animal_id": a2["id"], "service_date": "2026-01-10", "sire_code": "S-2"}, VET))
    get_success_data(api_client.confirm_breeding_event(be2["id"], VET))
    ce2 = get_success_data(api_client.create_calving_event(
        {"animal_id": a2["id"], "breeding_event_id": be2["id"], "calving_date": "2026-02-01"}, HM))
    lact2_id = ce2["opened_lactation_id"]

    add_test_day(lact1["id"], "2026-06-10", milk_weight_lbs=1000, fat_pct=3.8,
                 protein_pct=3.1, scc_thousands=180, clock="2026-06-10T00:00:00Z")
    add_test_day(lact2_id, "2026-06-10", milk_weight_lbs=1200, fat_pct=4.0,
                 protein_pct=3.2, scc_thousands=420)

    price_sheet = create_price_sheet(herd["id"], settlement_month="2026-06")
    milk_check = get_success_data(api_client.create_milk_check(
        {"herd_id": herd["id"], "price_sheet_id": price_sheet["id"]}, COOP))

    data = validate_success(
        api_client.finalize_milk_check(milk_check["id"], milk_check["version"], COOP)
    )
    assert data["pooled_milk_lbs"] == 2200, data["pooled_milk_lbs"]
    assert data["weighted_scc_thousands"] == 310.91, data["weighted_scc_thousands"]
    assert data["gross_settlement"] == 562.90, data["gross_settlement"]
