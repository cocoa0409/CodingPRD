"""Bath-life dual variant, titration rounding, dose math, and dose gating."""
from test_helpers import (
    ApiErrorId,
    CHEM,
    MGR,
    OP,
    create_bath,
    create_compat_rule,
    create_customer,
    create_titrated_bath,
    dose_bath,
    get_bath,
    get_bath_version,
    get_success_data,
    prepare_work_order,
    route_work_order,
    setup_routed_order,
    start_load_run,
    titrate_bath,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_work_order_payload
from test_helpers.test_users import make_customer_headers


def _setup_bath_titrated_to_4_9():
    """Bath at concentration 4.9 (efficiency 0.98), capacity 600 Ah."""
    customer = create_customer(company_name="Beta Defense")
    create_compat_rule(alloy_code="AL7075", process_type="ANODIZE",
                       chemistry_family="SULFURIC", compatibility="COMPATIBLE")
    bath = create_bath(
        bath_code="ANO-2", process_type="ANODIZE", chemistry_family="SULFURIC",
        routing_modes_supported=["BARREL"], volume_liters=800,
        target_concentration_g_l=5.0, low_concentration_g_l=4.0,
        high_concentration_g_l=6.0, amp_hour_capacity=600,
    )
    tit = titrate_bath(bath["id"], titrant_volume_ml=10.0, titrant_normality=0.1,
                       sample_volume_ml=10.0)
    return customer, bath, tit


def test_bath_life_variants_exposed_on_detail_read():
    """PRD §3.3: "The optimistic `nameplate_remaining_ah` is simply the bath's amp-hour
    capacity minus its amp-hours used, carried to two decimal places. The pessimistic
    `effective_remaining_ah` first derives a chemistry efficiency: 1.0 when the current
    concentration is at or above target, otherwise the ratio of current to target
    concentration, but never below 0.5. The effective figure is then the capacity minus
    the used, multiplied by that efficiency, floored to a whole number."

    Design: Difficulty/dual_variant_calc/bath_life_nameplate_vs_chemistry_adjusted
    """
    _customer, bath, tit = _setup_bath_titrated_to_4_9()
    assert tit["measured_concentration_g_l"] == 4.9, (
        f"Titration: expected 4.9, got {tit['measured_concentration_g_l']}"
    )
    detail = get_bath(bath["id"])
    assert detail["nameplate_remaining_ah"] == 600.0, (
        f"Nameplate variant: expected 600.0, got {detail['nameplate_remaining_ah']}"
    )
    assert detail["effective_remaining_ah"] == 588, (
        f"Effective variant: expected 588 (floor(600 x 0.98)), got {detail['effective_remaining_ah']}"
    )


def test_route_rejected_by_pessimistic_variant_when_optimistic_would_pass():
    """PRD §3.3: "Routing decisions consult only the pessimistic variant: a route is
    accepted only when `effective_remaining_ah` is at least the planned load's
    estimated amp-hours, else `ERR_BATH_LIFE_INSUFFICIENT`."

    Design: Difficulty/dual_variant_calc/bath_life_nameplate_vs_chemistry_adjusted
    """
    customer, bath, _tit = _setup_bath_titrated_to_4_9()
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(
            customer_id=customer["id"], part_number="PN-200", alloy_code="AL7075",
            routing_mode="BARREL", part_count=10, surface_area_dm2_per_part=2.5,
            thickness_spec_min_um=12.0, thickness_spec_max_um=18.0,
        ),
        make_customer_headers(customer["id"]),
    ))
    prepare_work_order(wo["id"])
    # planned estimate: 25 dm2 x 1.5 A/dm2 x 944 min / 60 = 590.0 Ah > 588 effective
    resp = api_client.route_work_order(
        wo["id"],
        {"bath_id": bath["id"], "planned_duration_minutes": 944,
         "planned_current_density_a_dm2": 1.5},
        OP,
    )
    validate_error(resp, ApiErrorId.ERR_BATH_LIFE_INSUFFICIENT)


def test_titration_half_up_rounding():
    """PRD §3.2: "The `measured_concentration_g_l` is the titrant volume multiplied by
    the titrant normality multiplied by the equivalent weight of the bath's chemistry
    family, divided by the sample volume, rounded half-up to three decimal places."
    PRD §2.5: "**Chemistry concentrations** (grams per liter): titration results, dose
    results, dragout adjustments, and stored bath concentrations are rounded half-up to
    exactly three decimal places."

    Design: Corner/calculations/titration_half_up_rounding
    """
    bath = create_bath(
        bath_code="ANO-RT", process_type="ANODIZE", chemistry_family="SULFURIC",
        routing_modes_supported=["BARREL"], volume_liters=800,
        target_concentration_g_l=5.0, low_concentration_g_l=0.1,
        high_concentration_g_l=6.0, amp_hour_capacity=600,
    )
    # 1.0 x 0.1 x 49.0 / 8.0 = 0.6125 -> half-up 3 dp = 0.613 (banker's would give 0.612)
    tit = titrate_bath(bath["id"], titrant_volume_ml=1.0, titrant_normality=0.1,
                       sample_volume_ml=8.0)
    assert tit["measured_concentration_g_l"] == 0.613, (
        f"Expected 0.613 (half-up of 0.6125), got {tit['measured_concentration_g_l']}"
    )
    detail = get_bath(bath["id"])
    assert detail["current_concentration_g_l"] == 0.613


def test_dose_gate_blocks_load_start_until_retitration():
    """PRD §3.2: "Every dose sets `dose_verification_pending` to true and increments the
    bath's `version`; only the next recorded titration clears the flag."
    PRD §3.2: "While `dose_verification_pending` is true, two operations refuse to run:
    starting a load on the bath (`ERR_DOSE_VERIFICATION_PENDING`, §3.5) and releasing
    the bath from quarantine (§3.3)."

    Design: Corner/calculations/dose_gate_requires_retitration
    """
    customer = create_customer(company_name="Gate Co")
    create_compat_rule()
    bath = create_titrated_bath(
        bath_code="ANO-G", routing_modes_supported=["BARREL"],
        titration_overrides={"titrant_volume_ml": 10.0, "titrant_normality": 0.1,
                             "sample_volume_ml": 10.0},
    )
    wo = setup_routed_order(customer["id"], bath["id"], part_number="PN-G")
    v1 = get_bath_version(bath["id"])
    dose = dose_bath(bath["id"], v1, chemical_code="H2SO4", quantity_g=80.0)
    # 4.9 + 80 g / 800 L = 5.000
    assert dose["resulting_concentration_g_l"] == 5.0, (
        f"Dose result: expected 5.0, got {dose['resulting_concentration_g_l']}"
    )
    detail = get_bath(bath["id"])
    assert detail["dose_verification_pending"] is True
    resp = api_client.start_load_run(
        wo["id"],
        {"duration_minutes": 40, "current_density_a_dm2": 1.5,
         "expected_bath_version": detail["version"]},
        OP,
    )
    validate_error(resp, ApiErrorId.ERR_DOSE_VERIFICATION_PENDING)
    # Fresh titration clears the flag; the same load start then succeeds.
    titrate_bath(bath["id"])
    detail2 = get_bath(bath["id"])
    assert detail2["dose_verification_pending"] is False
    lr = start_load_run(wo["id"], bath_version=detail2["version"])
    assert lr["status"] == "RUNNING"


def test_dose_not_needed_at_target():
    """PRD §3.2: "A dose recorded while the current concentration is already at or above
    the target is rejected with `ERR_DOSE_NOT_NEEDED`."

    Design: Corner/calculations/dose_not_needed_at_target
    """
    bath = create_titrated_bath(bath_code="ANO-H", routing_modes_supported=["BARREL"])
    assert bath["current_concentration_g_l"] == 5.0  # target is 5.0
    resp = api_client.create_dose(
        bath["id"],
        {"chemical_code": "H2SO4", "quantity_g": 10.0,
         "expected_bath_version": bath["version"]},
        CHEM,
    )
    validate_error(resp, ApiErrorId.ERR_DOSE_NOT_NEEDED)


def test_dose_stale_version_rejected():
    """PRD §2.7: "Recording a dose (`POST /baths/{id}/doses`) requires
    `expected_bath_version` matching the target PlatingBath's current `version`. A dose
    written against a fresh view and a dose written against a stale view would each
    legitimately succeed if issued sequentially — the bath is dosable and its
    concentration is below target in both cases — so the stale request is rejected
    purely because its view of the bath is stale."

    Design: Corner/validations/dose_stale_version_rejected
    """
    bath = create_bath(
        bath_code="ANO-DO", process_type="ANODIZE", chemistry_family="SULFURIC",
        routing_modes_supported=["BARREL"], volume_liters=800,
        target_concentration_g_l=5.0, low_concentration_g_l=3.5,
        high_concentration_g_l=6.0, amp_hour_capacity=600,
    )
    # 40.0 x 0.1 x 49.0 / 49.0 = 4.0 g/L exactly
    tit = titrate_bath(bath["id"], titrant_volume_ml=40.0, titrant_normality=0.1,
                       sample_volume_ml=49.0)
    assert tit["measured_concentration_g_l"] == 4.0
    v = get_bath_version(bath["id"])
    dose1 = dose_bath(bath["id"], v, chemical_code="H2SO4", quantity_g=80.0)
    # 4.0 + 80/800 = 4.1
    assert dose1["resulting_concentration_g_l"] == 4.1
    # Second dose with the now-stale version must be rejected.
    resp = api_client.create_dose(
        bath["id"],
        {"chemical_code": "H2SO4", "quantity_g": 80.0, "expected_bath_version": v},
        CHEM,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
