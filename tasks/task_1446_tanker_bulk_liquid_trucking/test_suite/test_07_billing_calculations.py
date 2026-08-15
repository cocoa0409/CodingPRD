"""Meter-ticket temperature correction and billing-total calculation claims."""
import pytest

from test_helpers import (
    SO_1,
    TEST_USERS,
    close_delivery,
    close_meter,
    create_customer,
    create_product,
    create_rule,
    make_safety_officer_headers,
    plan_shipment,
    setup_delivering_shipment,
    setup_draft_shipment,
    setup_loading_shipment,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_meter_ticket_observed_vs_net60_divergence(api):
    """PRD 3.4: "The `observed_gallons` is simply the end reading minus the start
    reading." The net60 figure is "observed times (1 − coefficient × (observed
    temperature − 60)) — and the result is rounded half-up to 1 decimal place", and
    "At exactly 60 °F the two figures coincide; off 60 °F they diverge." PRD 3.6: "The provisional variant runs at close-meter. Its basis is
    the meter ticket's `observed_gallons` — raw rack gallons with no temperature
    correction". (5000 gal at 100F with coeff 0.0007: net60 = 4860.0; provisional =
    500000 + 20000 + 15000 = 535000.)

    Design: Difficulty/dual_variant_calc/meter_ticket_observed_vs_net60_divergence
    """
    scenario = setup_loading_shipment(
        ordered_gallons=5000, route_miles=100,
        product_overrides={"temp_coeff_per_degF": 0.0007})
    ticket = close_meter(scenario, meter_start_gal=0, meter_end_gal=5000, observed_temp_F=100)
    assert ticket["observed_gallons"] == pytest.approx(5000.0, abs=0.001)
    assert ticket["net60_gallons"] == pytest.approx(4860.0, abs=0.001)
    assert ticket["observed_gallons"] != ticket["net60_gallons"]

    ship = validate_success(api.get_shipment(scenario["ship"]["id"], DISP), 200)
    assert ship["provisional_total_cents"] == 535000


def test_meter_ticket_bases_coincide_at_reference_temp(api):
    """PRD 3.4: "At exactly 60 °F the two figures coincide; off 60 °F they diverge."
    PRD 2.6 fixes "the reference temperature for all volumetric corrections is 60 °F".

    Design: Difficulty/dual_variant_calc/meter_ticket_observed_vs_net60_divergence
    """
    scenario = setup_loading_shipment()
    ticket = close_meter(scenario, meter_start_gal=0, meter_end_gal=1000, observed_temp_F=60)
    assert ticket["observed_gallons"] == pytest.approx(1000.0, abs=0.001)
    assert ticket["net60_gallons"] == pytest.approx(1000.0, abs=0.001)


def test_net60_rounding_half_up_precision(api):
    """PRD 2.6: "Gallonage figures derived from meter readings (`observed_gallons`,
    `net60_gallons`, `delivered_net60_gal`, `allowed_loss_gal`, `variance_gallons`)
    are carried to exactly 1 decimal place using round-half-up." (333.0 gal at 85F,
    coeff 0.0007: 333*(1-0.0175) = 327.1725 -> 327.2, not 327.1 and not 2dp.)

    Design: Corner/calculations/net60_rounding_half_up_precision
    """
    scenario = setup_loading_shipment(ordered_gallons=333)
    ticket = close_meter(scenario, meter_start_gal=0, meter_end_gal=333, observed_temp_F=85)
    assert ticket["observed_gallons"] == pytest.approx(333.0, abs=0.001)
    assert ticket["net60_gallons"] == pytest.approx(327.2, abs=0.001)


def test_billing_provisional_vs_final_divergence(api):
    """PRD 3.6: "The provisional variant runs at close-meter. Its basis is the meter
    ticket's `observed_gallons` — raw rack gallons with no temperature correction —
    and its shortage credit is zero" and "The final variant runs at reconciliation.
    Its basis is the delivery ticket's `delivered_net60_gal`, and its shortage credit
    compensates the customer for proven loss beyond the allowed tolerance: take
    `loaded_net60_gal` minus `delivered_net60_gal` minus `allowed_loss_gal`, floor the
    result at zero, multiply by `rate_per_gal_cents`, and round half-up to integer
    cents." (5000 gal loaded at 100F, 4900 delivered at 80F over 500 miles:
    provisional 535000; final = 483140 + 19326 + 15000 - 1360 = 516106.)

    Design: Difficulty/dual_variant_calc/billing_provisional_vs_final_divergence
    """
    scenario = setup_delivering_shipment(
        ordered_gallons=5000, route_miles=500, meter_end_gal=5000, observed_temp_F=100)
    ticket = close_delivery(scenario, delivered_observed_gal=4900, delivered_temp_F=80)
    assert ticket["status"] == "CLOSED_VARIANCE"  # variance 28.6 > allowed 15.0

    resolved = validate_success(api.resolve_variance(
        scenario["ship"]["id"], {"resolution_note": "customer accepted shortage"},
        make_safety_officer_headers(SO_1)), 200)
    assert resolved["status"] == "DELIVERED"

    reconciled = validate_success(api.reconcile_shipment(scenario["ship"]["id"], ADMIN), 200)
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["provisional_total_cents"] == 535000
    assert reconciled["final_total_cents"] == 516106
    assert reconciled["final_total_cents"] != reconciled["provisional_total_cents"]


def test_billing_variants_agree_at_reference_temp(api):
    """PRD 3.6: "for identical route data the two figures differ whenever temperature
    correction or a shortage credit is non-zero" — with delivery at 60 °F in full, the
    final basis and shortage credit are unchanged from the provisional basis, so the
    two variants agree (1000 gal * 100c = 100000, + 4% = 4000, + 15000 rack fee).

    Design: Difficulty/dual_variant_calc/billing_provisional_vs_final_divergence
    """
    scenario = setup_delivering_shipment()
    close_delivery(scenario, delivered_observed_gal=1000, delivered_temp_F=60)
    reconciled = validate_success(api.reconcile_shipment(scenario["ship"]["id"], ADMIN), 200)
    assert reconciled["provisional_total_cents"] == 119000
    assert reconciled["final_total_cents"] == 119000


def test_billing_per_line_rounding_beats_sum_first(api):
    """PRD 3.6: "Billing is computed twice per shipment, on two different gallonage
    bases, but always through the same pinned assembly order. Each line is rounded
    half-up to integer cents before any summing — rounding the unrounded total instead
    is wrong." (100.1 net60 gal at 125 c/gal: round(12512.5)=12513 plus
    round(500.5)=501 plus 15000 = 28014; sum-first would give 28013.)

    Design: Difficulty/combinatorial_formula/billing_per_line_rounding_beats_sum_first
    """
    scenario = setup_delivering_shipment(
        ordered_gallons=100, route_miles=10, rate_per_gal_cents=125,
        meter_end_gal=100.1, observed_temp_F=60)
    close_delivery(scenario, delivered_observed_gal=100.1, delivered_temp_F=60)
    reconciled = validate_success(api.reconcile_shipment(scenario["ship"]["id"], ADMIN), 200)
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["final_total_cents"] == 28014


def test_provisional_per_line_rounding_matches_same_rule(api):
    """PRD 2.6: "Where a billing total is assembled from component lines, each line is
    individually rounded half-up to integer cents before the lines are summed;
    rounding the unrounded sum instead is incorrect and produces off-by-one-cent
    results." (Same 100.1 gal x 125 c/gal shipment: provisional at close-meter is
    also 28014 because the shortage credit is zero.)

    Design: Difficulty/combinatorial_formula/billing_per_line_rounding_beats_sum_first
    """
    scenario = setup_loading_shipment(
        ordered_gallons=100, route_miles=10, rate_per_gal_cents=125)
    close_meter(scenario, meter_start_gal=0, meter_end_gal=100.1, observed_temp_F=60)
    ship = validate_success(api.get_shipment(scenario["ship"]["id"], DISP), 200)
    assert ship["provisional_total_cents"] == 28014


def test_credit_exposure_filters_draft_and_cancelled(api):
    """PRD 3.6: "A customer's `exposure_cents` is the sum of `provisional_total_cents`
    across all of the customer's shipments in `PLANNED`, `LOADING`, `LOADED`,
    `IN_TRANSIT`, `DELIVERING`, `DELIVERED`, or `VARIANCE_REVIEW` — for `PLANNED`
    shipments, which have no meter ticket yet, the plan-time estimate of §3.3 stands
    in — plus the sum of `final_total_cents` across all `RECONCILED` shipments.
    `DRAFT` and `CANCELLED` shipments contribute zero." (100 gal at 100c: estimate
    10000 + 400 + 15000 = 25400 while PLANNED.)

    Design: Corner/calculations/credit_exposure_filters_draft_and_cancelled
    """
    scenario = setup_draft_shipment(ordered_gallons=100)

    cust0 = validate_success(api.get_customer(scenario["cust"]["id"], DISP), 200)
    assert cust0["exposure_cents"] == 0

    plan_shipment(scenario)
    cust1 = validate_success(api.get_customer(scenario["cust"]["id"], DISP), 200)
    assert cust1["exposure_cents"] == 25400

    validate_success(api.cancel_shipment(scenario["ship"]["id"], DISP), 200)
    cust2 = validate_success(api.get_customer(scenario["cust"]["id"], DISP), 200)
    assert cust2["exposure_cents"] == 0


def test_derived_exposure_reconciled_after_close_meter(api):
    """PRD 3.6: "The server recomputes exposure at five moments: when a plan is
    created (where it also gates, as in §3.3), when a meter ticket closes, when a
    shipment reconciles, when a shipment is unplanned, and when a planned shipment is
    cancelled." (Planned estimate 25400 for 100 gal; after close-meter measures 110.0
    gal the provisional recomputes to 11000 + 440 + 15000 = 26440.)

    Design: Corner/complexity_layers/derived_exposure_reconciled_after_close_meter
    """
    scenario = setup_loading_shipment(ordered_gallons=100)
    cust_planned = validate_success(api.get_customer(scenario["cust"]["id"], DISP), 200)
    assert cust_planned["exposure_cents"] == 25400

    close_meter(scenario, meter_start_gal=0, meter_end_gal=110, observed_temp_F=60)
    cust_loaded = validate_success(api.get_customer(scenario["cust"]["id"], DISP), 200)
    assert cust_loaded["exposure_cents"] == 26440
