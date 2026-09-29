"""Rulings, credits and the forecast: two views of one safety class, half-up
rounding at the awkward midpoint, the two sequential credit roundings, and the
divergence between the two forecast variants.
"""
import pytest

from test_helpers import (
    ADMIN,
    COMPLIANCE,
    CUSTOMER,
    FAILURE_ENGINEER,
    api_client,
    factories,
    fixtures,
    get_success_data,
    validate_success,
)


def _read_case(case_id, headers=ADMIN):
    return get_success_data(api_client.get_defective_return(case_id, headers))


def _forecast(part_id, model_id, horizon_months, variant):
    response = api_client.get_demand_forecast(
        part_id,
        COMPLIANCE,
        params={
            "model_id": model_id,
            "horizon_months": horizon_months,
            "variant": variant,
        },
    )
    return validate_success(response, 200)


def test_a_pairing_override_frees_the_ruling_while_the_warranty_reads_the_stored_class():
    """PRD §3.5: "Branch four is not a decision but a substitution — the *effective*
    safety class is `UNRESTRICTED` when the part's `safety_class` is `PAIRED_SECURITY`
    and the region's `allows_pairing_restriction` is false, and is otherwise the part's
    own `safety_class`; a jurisdiction that outlaws parts pairing sees a paired-security
    part as if it were unrestricted, and every later branch reads the effective value."
    PRD §3.5: "The same request also classifies **warranty impact**, again by first
    matching branch, and this classification reads the part's stored `safety_class`
    rather than the pairing-override effective value."

    Design: Corner/calculations/pairing_override_frees_eligibility_while_warranty_reads_the_stored_safety_class
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "EU-DE", "allows_pairing_restriction": False},
        model_overrides={
            "model_code": "CRX-C206",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
        },
        part_overrides={
            "sku": "SKU-C206-SEC",
            "safety_class": "PAIRED_SECURITY",
            "list_price_cents": 4000,
        },
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "self_service_eligible": True,
            "install_minutes": 60,
        },
    )

    response = api_client.create_eligibility_assessment(
        factories.eligibility_assessment_payload(
            setup["model"]["id"],
            setup["part"]["id"],
            "EU-DE",
            requester_class="SELF_REPAIR_CONSUMER",
        ),
        CUSTOMER,
    )
    assessment = validate_success(response, 201)

    assert assessment["decision"] == "ELIGIBLE", (
        f"the region outlaws parts pairing, so the safety branch is skipped, got "
        f"{assessment['decision']}"
    )
    assert assessment["warranty_impact_class"] == "WARRANTY_VOID_AFFECTED_SUBSYSTEM", (
        f"the classifier ignores the override and reads the stored class, got "
        f"{assessment['warranty_impact_class']}"
    )
    assert assessment["self_repair_risk_index"] == 41, (
        "Expected the stored paired-security weight of 0.70 in the index, not the "
        f"overridden 0.10; got {assessment['self_repair_risk_index']}"
    )
    assert assessment["liability_warning_version"] == "LW-CRX-C206-R1", (
        assessment["liability_warning_version"]
    )
    assert assessment["pinned_manual_revision_id"] == setup["guide"]["id"], (
        f"Expected the published guide pinned, got "
        f"{assessment['pinned_manual_revision_id']}"
    )
    assert assessment["status"] == "VALID", assessment["status"]
    assert assessment["expires_at"].startswith("2026-09-30T00:00:00"), (
        f"Expected sixty days from the clock, got {assessment['expires_at']}"
    )


def test_the_risk_index_rounds_half_up_and_saturates_the_install_weight():
    """PRD §3.5: "The install weight is the compatibility row's `install_minutes`
    divided by 120 — two hours of bench time being the normalising figure — capped at
    1, and taken as 0 when no compatibility row was found."
    PRD §3.5: "The index is then 100 multiplied by the smaller of 1 and the sum of 0.40
    times the tier weight plus 0.35 times the safety weight plus 0.25 times the install
    weight, rounded half up to a whole number."

    Design: Corner/calculations/risk_index_rounds_half_up_to_ninety_seven_for_a_non_serviceable_high_voltage_part
    """
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-C207",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_D_NON_SERVICEABLE",
    )
    part = fixtures.create_part(
        sku="SKU-C207-HV",
        safety_class="SAFETY_RESTRICTED_HIGH_VOLTAGE",
        list_price_cents=7000,
    )
    fixtures.create_compatibility(
        part["id"],
        model["id"],
        effective_from="2024-02-01T00:00:00Z",
        self_service_eligible=False,
        install_minutes=200,
    )
    fixtures.publish_part(part["id"])

    response = api_client.create_eligibility_assessment(
        factories.eligibility_assessment_payload(
            model["id"], part["id"], "US-CA", requester_class="SELF_REPAIR_CONSUMER"
        ),
        CUSTOMER,
    )
    assessment = validate_success(response, 201)

    assert assessment["decision"] == "BLOCKED_TIER", (
        f"the non-serviceable tier branch wins before the safety branch, got "
        f"{assessment['decision']}"
    )
    assert assessment["self_repair_risk_index"] == 97, (
        "Expected the exact 96.5 midpoint rounded half up rather than truncated; got "
        f"{assessment['self_repair_risk_index']}"
    )
    assert assessment["warranty_impact_class"] == "WARRANTY_VOID_AFFECTED_SUBSYSTEM", (
        assessment["warranty_impact_class"]
    )
    assert assessment["liability_warning_version"] is None, (
        f"no guide is published, so there is no warning version, got "
        f"{assessment['liability_warning_version']}"
    )
    assert assessment["pinned_manual_revision_id"] is None, (
        assessment["pinned_manual_revision_id"]
    )
    assert assessment["status"] == "VALID", (
        f"a blocked ruling is still a valid row, got {assessment['status']}"
    )


def test_the_pro_rata_basis_is_rounded_before_the_goodwill_and_final_gradings():
    """PRD §3.9: "The pro-rata basis is the line's `line_total_cents` multiplied by the
    case's `quantity` and divided by the line's `quantity`, rounded half up to whole
    cents. That is the first of two sequential, pinned roundings."
    PRD §3.9: "When `defect_confirmed` is false, that factor is reduced to the smaller
    of itself and one quarter."

    Design: Corner/calculations/defective_credit_rounds_the_pro_rata_share_before_grading_it
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA", "max_documentation_fee_cents": 2000},
        model_overrides={
            "model_code": "CRX-C208",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_B_GUIDED",
        },
        part_overrides={"sku": "SKU-C208-BRD", "list_price_cents": 953},
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 30,
        },
        safety_warning_count=2,
    )
    bundle = fixtures.build_delivered_order(setup, 2, CUSTOMER)
    line = bundle["lines"][0]
    assert line["line_total_cents"] == 2001, (
        f"Expected 953 times 1.05 times two rounded once, got "
        f"{line['line_total_cents']}"
    )
    assert line["unit_price_cents"] == 1001, line["unit_price_cents"]

    case = fixtures.create_defective_return(line["id"], 1, CUSTOMER)
    received = fixtures.receive_defective_return(case["id"], ADMIN)
    assert received["provisional_credit_cents"] == 501, (
        "Expected the 1000.5 pro-rata basis rounded up to 1001 first and halved to "
        f"501, not a single combined rounding to 500; got "
        f"{received['provisional_credit_cents']}"
    )

    fixtures.record_analysis(
        case["id"],
        "MANUFACTURING_DEFECT",
        False,
        FAILURE_ENGINEER,
        analysis_note="no reproducible fault found",
    )
    decided = fixtures.decide_credit(case["id"], "ISSUE_CREDIT", ADMIN)

    assert decided["final_credit_cents"] == 250, (
        f"Expected the unconfirmed-defect cap of one quarter applied to 1001, got "
        f"{decided['final_credit_cents']}"
    )
    assert decided["status"] == "CREDIT_ISSUED", decided["status"]
    assert _read_case(case["id"])["provisional_credit_cents"] == 501, (
        "the goodwill offer stays on the record after the decision"
    )


def test_a_counterfeit_line_zeroes_the_credit_despite_a_confirmed_defect():
    """PRD §3.9: "The analysis-final figure is zero outright when the source line's
    `authentication_status` is `COUNTERFEIT_SUSPECT`."
    PRD §3.9: "A `COUNTERFEIT_SUSPECT` line is deliberately absent from that list: it
    is decided rather than incomplete, so it clears the guard and the final calculation
    zeroes its credit instead."

    Design: Corner/calculations/counterfeit_line_zeroes_the_final_credit_despite_a_confirmed_manufacturing_defect
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA", "max_documentation_fee_cents": 2000},
        model_overrides={
            "model_code": "CRX-C209",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
        },
        part_overrides={
            "sku": "SKU-C209-CAM",
            "list_price_cents": 1000,
            "requires_authentication": True,
        },
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 30,
        },
        safety_warning_count=2,
    )
    bundle = fixtures.build_delivered_order(setup, 1, CUSTOMER)
    line = bundle["lines"][0]

    counterfeit = fixtures.authenticate_line(
        bundle["order"]["id"], line["id"], "WRONG-TOKEN-VALUE", CUSTOMER
    )
    assert counterfeit["authentication_status"] == "COUNTERFEIT_SUSPECT", (
        counterfeit["authentication_status"]
    )

    case = fixtures.create_defective_return(line["id"], 1, CUSTOMER)
    received = fixtures.receive_defective_return(case["id"], ADMIN)
    assert received["provisional_credit_cents"] == 500, (
        f"the goodwill offer was computed before the analysis, got "
        f"{received['provisional_credit_cents']}"
    )

    fixtures.record_analysis(
        case["id"],
        "MANUFACTURING_DEFECT",
        True,
        FAILURE_ENGINEER,
        analysis_note="bench reproduced the reported fault",
    )

    response = api_client.decide_defective_credit(
        case["id"], factories.credit_decision_payload("ISSUE_CREDIT"), ADMIN
    )
    decided = validate_success(response, 200)
    assert decided["status"] == "CREDIT_ISSUED", (
        f"a decided counterfeit line clears the service-step guard, got "
        f"{decided['status']}"
    )
    assert decided["final_credit_cents"] == 0, (
        f"the counterfeit branch wins over the confirmed defect factor, got "
        f"{decided['final_credit_cents']}"
    )
    assert _read_case(case["id"])["provisional_credit_cents"] == 500, (
        "the goodwill offer survives as the audit trail"
    )


def test_the_two_forecast_variants_diverge_on_identical_data():
    """PRD §3.9: "Fifth, the monthly demand figure depends on the variant: under
    `TRAILING_ONLY` it is simply `base_monthly_units`, so open orders never lift the
    forecast, while under `PIPELINE_WEIGHTED` it is six tenths of `base_monthly_units`
    plus four tenths of `pipeline_units` divided by `horizon_months`."
    PRD §3.9: "Ninth, `recommended_stock_units` is `projected_units` multiplied by one
    plus `safety_stock_pct`, rounded up to a whole unit, plus `mandated_buffer_units`."

    Design: Corner/calculations/pipeline_weighted_forecast_diverges_from_the_trailing_only_forecast
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA", "max_documentation_fee_cents": 2000},
        model_overrides={
            "model_code": "CRX-C214",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
        },
        part_overrides={"sku": "SKU-C214-FAN", "list_price_cents": 1200},
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 20,
        },
        safety_warning_count=2,
    )
    delivered = fixtures.build_delivered_order(setup, 12, CUSTOMER)
    assert delivered["order"]["confirmed_at"].startswith("2026-08-01T00:00:00"), (
        delivered["order"]["confirmed_at"]
    )

    pipeline = fixtures.build_pending_disclosure_order(setup, 60, CUSTOMER)
    assert pipeline["order"]["fulfillment_status"] == "PENDING_DISCLOSURE", (
        pipeline["order"]["fulfillment_status"]
    )

    fixtures.move_clock("2026-09-01T00:00:00Z")

    trailing = _forecast(
        setup["part"]["id"], setup["model"]["id"], 12, "TRAILING_ONLY"
    )
    blended = _forecast(
        setup["part"]["id"], setup["model"]["id"], 12, "PIPELINE_WEIGHTED"
    )

    for name, forecast in (("trailing", trailing), ("blended", blended)):
        assert forecast["trailing_units"] == 12, (
            f"{name}: the delivered order sits inside the trailing window, got "
            f"{forecast['trailing_units']}"
        )
        assert forecast["pipeline_units"] == 60, (
            f"{name}: the open order is counted with no date filter, got "
            f"{forecast['pipeline_units']}"
        )
        assert forecast["base_monthly_units"] == pytest.approx(2.0, abs=0.01), (
            f"{name}: {forecast['base_monthly_units']}"
        )
        assert forecast["obsolescence_band"] == "CURRENT", (
            f"{name}: the model is still in production, got "
            f"{forecast['obsolescence_band']}"
        )
        assert forecast["band_multiplier"] == pytest.approx(1.00, abs=0.01), (
            f"{name}: {forecast['band_multiplier']}"
        )
        assert forecast["mandated_buffer_units"] == 0, (
            f"{name}: no obligation exists, got {forecast['mandated_buffer_units']}"
        )
        assert forecast["safety_stock_pct"] == pytest.approx(0.30, abs=0.01), (
            f"{name}: both projections stay under fifty units, got "
            f"{forecast['safety_stock_pct']}"
        )

    assert trailing["recommended_stock_units"] == 32, (
        f"Expected 24.0 projected padded by thirty percent and rounded up, got "
        f"{trailing['recommended_stock_units']}"
    )
    assert blended["recommended_stock_units"] == 50, (
        f"Expected the blended 38.4 projection padded and rounded up, got "
        f"{blended['recommended_stock_units']}"
    )
    assert blended["recommended_stock_units"] - trailing["recommended_stock_units"] == 18, (
        "the open pipeline lifts the recommendation by eighteen units"
    )
