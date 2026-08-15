"""Pricing dual-variant and multifactor formula tests.

Covers the provisional/final invoice divergence on the WorkOrder domain and the
pinned multi-factor pricing formula (tier rate, run count, rework surcharge,
discount tier keyed on the pre-discount subtotal, hazmat fee after discount).
"""
import pytest

from test_helpers import (
    CHEM,
    MGR,
    OP,
    QC,
    complete_load_run,
    create_compat_rule,
    create_customer,
    create_fixture,
    create_titrated_bath,
    get_bath_version,
    get_success_data,
    get_work_order,
    inspect_work_order,
    make_customer_headers,
    prepare_work_order,
    route_work_order,
    start_load_run,
    strip_and_replate,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_work_order_payload


def _build_shipped_rack_order_with_one_rework():
    """WO1 scenario: RACK order, masking 30 min, one STAIN rework lap, then shipped."""
    customer = create_customer(company_name="Acme Aerospace")
    create_compat_rule(alloy_code="AL6061", process_type="ANODIZE",
                       chemistry_family="SULFURIC", compatibility="COMPATIBLE")
    fixture = create_fixture(fixture_code="RACK-01", routing_mode="RACK", capacity_dm2=500,
                             purchase_cost_cents=120000, rated_uses=50)
    bath = create_titrated_bath(
        bath_code="ANO-1", process_type="ANODIZE", chemistry_family="SULFURIC",
        routing_modes_supported=["RACK", "BARREL"], volume_liters=800,
        target_concentration_g_l=5.0, low_concentration_g_l=4.0,
        high_concentration_g_l=6.0, amp_hour_capacity=600,
        titration_overrides={"titrant_volume_ml": 10.0, "titrant_normality": 0.1,
                             "sample_volume_ml": 10.0},
    )
    payload = create_work_order_payload(
        customer_id=customer["id"], part_number="PN-100", alloy_code="AL6061",
        process_type="ANODIZE", routing_mode="RACK", part_count=10,
        surface_area_dm2_per_part=2.5, thickness_spec_min_um=12.0,
        thickness_spec_max_um=18.0, requires_masking=True,
    )
    resp = api_client.create_work_order(payload, make_customer_headers(customer["id"]))
    wo = get_success_data(resp)
    quote_at_create = wo["provisional_quote_cents"]
    prepared = prepare_work_order(wo["id"], masking_minutes=30)
    quote_after_prepare = prepared["provisional_quote_cents"]
    route_work_order(wo["id"], bath["id"], fixture_id=fixture["id"])
    # First pass: STAIN reject, strip-and-replate lap
    lr1 = start_load_run(wo["id"], bath_id=bath["id"])
    complete_load_run(lr1["id"])
    inspect_work_order(wo["id"], thickness_readings_um=[12.5, 13.0, 14.0], defect_type="STAIN")
    strip_and_replate(wo["id"])
    route_work_order(wo["id"], bath["id"], fixture_id=fixture["id"])
    lr2 = start_load_run(wo["id"], bath_id=bath["id"])
    complete_load_run(lr2["id"])
    inspect_work_order(wo["id"], thickness_readings_um=[12.5, 13.0, 14.0], defect_type="NONE")
    return wo, quote_at_create, quote_after_prepare


def test_provisional_quote_at_create_and_after_prepare():
    """PRD §3.4: "The provisional variant always plans exactly one run. A rack order
    with no fixture yet assigned — always the case at creation — instead uses an
    unassigned-fixture fee of 2000 cents for the planned run."
    PRD §3.5: "The minutes are recorded as `masking_minutes_actual` (zero when masking
    is not required) and `provisional_quote_cents` is recomputed with the real masking figure."

    Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_divergence
    """
    wo, quote_at_create, quote_after_prepare = _build_shipped_rack_order_with_one_rework()
    # At create: masking 0 (not yet recorded) + unassigned rack fee 2000
    # + processing round_half_up(25 x 15.0 x 15) = 5625 -> 7625
    assert quote_at_create == 7625, (
        f"Provisional quote at creation: expected 7625, got {quote_at_create}"
    )
    # After prepare: masking 30 x 85 = 2550 + fixture still unassigned 2000 + 5625 = 10175
    assert quote_after_prepare == 10175, (
        f"Provisional quote after prepare: expected 10175, got {quote_after_prepare}"
    )


def test_final_invoice_diverges_from_provisional_after_ship():
    """PRD §3.7: "The final variant follows the identical nine-line structure and
    pinned evaluation order of §3.4 with three substitutions: the number of planned
    runs becomes the actual `completed_load_count`, the rework surcharge uses the
    actual `rework_count`, and the hazmat fee of 2500 cents applies when the
    `routed_chemistry_family` snapshot is `CHROMIC` or `CYANIDE`."

    Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_divergence
    """
    wo, _q_create, _q_prepare = _build_shipped_rack_order_with_one_rework()
    shipped = get_success_data(api_client.ship_work_order(wo["id"], OP))
    assert shipped["status"] == "SHIPPED"
    # Final: masking 2550 + fixture 2400 x 2 runs + processing 5625
    # + rework surcharge round(5625 x 0.20) x 1 = 1125 -> subtotal 14100, no discount/hazmat
    assert shipped["final_invoice_cents"] == 14100, (
        f"Final invoice: expected 14100, got {shipped['final_invoice_cents']}"
    )
    assert shipped["final_invoice_cents"] - 10175 == 3925, (
        "Delta equals the fixture uplift (2400 x 2 - 2000 = 2800) plus one rework surcharge (1125)"
    )


def test_barrel_order_final_invoice_with_rework_surcharge():
    """PRD §3.4: "For a `RACK` order, the assigned fixture's `amortization_cents_per_use`
    multiplied by the number of planned runs; for a `BARREL` order, a flat 1200 cents
    per planned run."
    PRD §3.7: "the rework surcharge uses the actual `rework_count`"

    Design: Difficulty/combinatorial_formula/pricing_multifactor_tier_surcharge_mode_a
    """
    customer = create_customer(company_name="Gamma Wheels")
    create_compat_rule()
    bath = create_titrated_bath(
        bath_code="ANO-3", routing_modes_supported=["RACK", "BARREL"],
        titration_overrides={"titrant_volume_ml": 10.0, "titrant_normality": 0.1,
                             "sample_volume_ml": 10.0},
    )
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(
            customer_id=customer["id"], part_number="PN-300", routing_mode="BARREL",
            thickness_spec_min_um=4.0, thickness_spec_max_um=6.0,
        ),
        make_customer_headers(customer["id"]),
    ))
    prepare_work_order(wo["id"])
    route_work_order(wo["id"], bath["id"])
    lr1 = start_load_run(wo["id"], bath_id=bath["id"])
    complete_load_run(lr1["id"])
    inspect_work_order(wo["id"], thickness_readings_um=[4.5, 5.0, 5.5], defect_type="STAIN")
    strip_and_replate(wo["id"])
    route_work_order(wo["id"], bath["id"])
    lr2 = start_load_run(wo["id"], bath_id=bath["id"])
    complete_load_run(lr2["id"])
    inspect_work_order(wo["id"], thickness_readings_um=[4.5, 5.0, 5.5], defect_type="NONE")
    shipped = get_success_data(api_client.ship_work_order(wo["id"], OP))
    # masking 0 + barrel 1200 x 2 runs + processing round(25 x 5.0 x 12) = 1500
    # + surcharge round(1500 x 0.20) x 1 = 300 -> 2400 + 1500 + 300 = 4200
    assert shipped["final_invoice_cents"] == 4200, (
        f"Final invoice: expected 4200, got {shipped['final_invoice_cents']}"
    )


def test_barrel_order_provisional_quote_uses_flat_fee_and_one_run():
    """PRD §3.4: "for a `BARREL` order, a flat 1200 cents per planned run. The
    provisional variant always plans exactly one run."
    PRD §3.4: "The tier rate is 12 when the billing thickness is below 10 micrometers"

    Design: Difficulty/combinatorial_formula/pricing_multifactor_tier_surcharge_mode_a
    """
    customer = create_customer(company_name="Gamma Wheels Prov")
    create_compat_rule()
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(
            customer_id=customer["id"], part_number="PN-300P", routing_mode="BARREL",
            thickness_spec_min_um=4.0, thickness_spec_max_um=6.0,
        ),
        make_customer_headers(customer["id"]),
    ))
    # provisional: barrel 1200 x 1 + processing round(25 x 5.0 x 12) = 1500 -> 2700
    assert wo["provisional_quote_cents"] == 2700, (
        f"Provisional quote: expected 2700, got {wo['provisional_quote_cents']}"
    )


def _build_cyanide_cyanide_discount_scenario():
    """WO4 scenario: CYANIDE PLATE BARREL, 1000 dm2, spec [28,32], one clean pass."""
    customer = create_customer(company_name="Delta Brassworks")
    create_compat_rule(alloy_code="C360", process_type="PLATE",
                       chemistry_family="CYANIDE", compatibility="COMPATIBLE")
    bath = create_titrated_bath(
        bath_code="PLT-4", process_type="PLATE", chemistry_family="CYANIDE",
        routing_modes_supported=["BARREL"], volume_liters=1000,
        target_concentration_g_l=5.0, low_concentration_g_l=4.0,
        high_concentration_g_l=6.0, amp_hour_capacity=1000,
        titration_overrides={"titrant_volume_ml": 10.0, "titrant_normality": 0.1,
                             "sample_volume_ml": 10.0},
    )
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(
            customer_id=customer["id"], part_number="PN-400", alloy_code="C360",
            process_type="PLATE", routing_mode="BARREL", part_count=1000,
            surface_area_dm2_per_part=1.0, thickness_spec_min_um=28.0,
            thickness_spec_max_um=32.0,
        ),
        make_customer_headers(customer["id"]),
    ))
    prepare_work_order(wo["id"])
    route_work_order(wo["id"], bath["id"], planned_duration_minutes=10,
                     planned_current_density_a_dm2=1.5)
    lr = start_load_run(wo["id"], bath_id=bath["id"], duration_minutes=10,
                        current_density_a_dm2=1.5)
    complete_load_run(lr["id"])
    inspect_work_order(wo["id"], thickness_readings_um=[29.0, 30.0, 31.0], defect_type="NONE")
    return wo


def test_provisional_quote_discount_keyed_on_prediscount_subtotal():
    """PRD §3.4: "The pre-discount subtotal determines the rate: 0.08 when the subtotal
    is at least 1000000 cents, 0.05 when it is at least 500000 cents but below 1000000,
    and zero below 500000."
    PRD §3.4: "The provisional variant is computed before any bath is routed, so its
    hazmat fee is always zero."

    Design: Difficulty/combinatorial_formula/invoice_discount_tier_prediscount_subtotal_mode_c
    """
    customer = create_customer(company_name="Delta Brassworks Prov")
    create_compat_rule(alloy_code="C360", process_type="PLATE",
                       chemistry_family="CYANIDE", compatibility="COMPATIBLE")
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(
            customer_id=customer["id"], part_number="PN-400P", alloy_code="C360",
            process_type="PLATE", routing_mode="BARREL", part_count=1000,
            surface_area_dm2_per_part=1.0, thickness_spec_min_um=28.0,
            thickness_spec_max_um=32.0,
        ),
        make_customer_headers(customer["id"]),
    ))
    # subtotal 571200 = barrel 1200 + processing 570000; discount 5% = 28560; hazmat 0
    # provisional total = 571200 - 28560 = 542640
    assert wo["provisional_quote_cents"] == 542640, (
        f"Provisional quote: expected 542640, got {wo['provisional_quote_cents']}"
    )


def test_final_invoice_hazmat_fee_added_after_discount():
    """PRD §3.4: "**Hazmat fee.** A flat 2500 cents when the routed chemistry family
    snapshot is `CHROMIC` or `CYANIDE`, otherwise zero."
    PRD §3.4: "**Total.** The subtotal minus the discount plus the hazmat fee."
    PRD §3.7: "the hazmat fee of 2500 cents applies when the `routed_chemistry_family`
    snapshot is `CHROMIC` or `CYANIDE`."

    Design: Difficulty/combinatorial_formula/invoice_discount_tier_prediscount_subtotal_mode_c
    """
    wo = _build_cyanide_cyanide_discount_scenario()
    shipped = get_success_data(api_client.ship_work_order(wo["id"], OP))
    # final: 571200 - 28560 + 2500 hazmat = 545140
    assert shipped["final_invoice_cents"] == 545140, (
        f"Final invoice: expected 545140, got {shipped['final_invoice_cents']}"
    )
    assert shipped["final_invoice_cents"] - 542640 == 2500, (
        "Final minus provisional equals exactly the hazmat fee"
    )
