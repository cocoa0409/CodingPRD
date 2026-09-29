"""Multi-step formulas whose step order changes the answer.

Two chains in this contract are order-sensitive. Nutrition attestation rounds per
component before summing, and the damages waterfall applies the monthly cap
before the cost-recovery credit. Both are exercised on fixtures where the
forbidden order produces a visibly different figure.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import ApiClient, assertions, factories, fixtures
from test_helpers import test_users as users


# ---------------------------------------------------------------------------
# Nutrition: per-item rounding before summation
# ---------------------------------------------------------------------------


def _draft_cycle_with_standard_day(api: ApiClient) -> dict:
    """An ACTIVE contract whose facility carries a complete one-day DRAFT cycle.

    The three components are chosen so that per-item rounding lands the energy
    total on exactly the contracted floor of 2800 kcal: 421.0 kcal over 50 g is
    210.5 rounded to 211, 306.0 over 225 g is 688.5 rounded to 689, and 380.0 over
    500 g is 1900.
    """
    ctx = fixtures.active_contract_with_facility(
        api,
        contract_overrides={"contract_code": "CFS-2515-CF1"},
        facility_overrides={
            "facility_code": "FAC-CF1",
            "sharps_authorized_count": 12,
            "satellite_site_count": 0,
        },
    )
    cycle = validate_success(
        api.create_menu_cycle(
            factories.menu_cycle_payload(
                ctx["facility"]["id"], cycle_code="CYC-CF1", cycle_length_days=1
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    items = fixtures.add_standard_day(api, cycle["id"])
    ctx["cycle"] = cycle
    ctx["items"] = items
    return ctx


def test_per_item_rounding_lands_the_energy_total_exactly_on_the_contract_floor(
    api: ApiClient,
) -> None:
    """Rounding each component before summing yields 2800 kcal and passes the
    inclusive adequacy gate; summing first would yield 2799 and be rejected.

    The PRD states: "The item's energy contribution is its `kcal_per_100g`
    multiplied by its `portion_grams`, divided by 100, then rounded half up to a
    whole number of kcal." It adds that "Summing the unrounded per-item values and
    rounding only once at the end is a different and forbidden computation" and
    that "All three comparisons are inclusive at the boundary: a cycle landing
    exactly on the contracted kcal minimum passes". The three components round to
    211, 689 and 1900 kcal, summing to exactly the contracted 2800.

    Design: Difficulty/combinatorial_formula/nutrition_per_item_rounding_before_summation_meets_contract_floor_exactly
    """
    ctx = _draft_cycle_with_standard_day(api)

    signed = validate_success(
        api.nutrition_sign_menu_cycle(ctx["cycle"]["id"], users.DIETITIAN)
    )

    assertions.assert_menu_cycle(signed)
    assert signed["status"] == "NUTRITION_APPROVED"
    assert signed["approved_kcal_per_meal_day"] == 2800
    assertions.assert_decimal_2dp(signed["approved_protein_grams_per_meal_day"], 58.50)
    assert signed["approved_sodium_mg_per_meal_day"] == 2000
    assert signed["item_count"] == 3


def test_signing_freezes_the_cost_figure_and_records_the_signing_dietitian(
    api: ApiClient,
) -> None:
    """The cost chain divides the raw total by the cycle length, applies the
    satellite tier and takes the ceiling exactly once at the end.

    The PRD states: "`approved_cost_cents_per_meal_day` is the unrounded base cost
    per meal-day multiplied by that multiplier, with the ceiling taken exactly once
    at the very end to reach whole cents." It adds: "On a successful sign, all four
    `approved_*` figures are written, `nutrition_signed_by_user_id` records the
    signing `X-User-ID`, and `version` is incremented by 1." A raw total of 315
    cents over a one-day cycle at a facility with no satellite sites takes the 1.00
    multiplier, so the frozen figure is 315 cents.

    Design: Difficulty/combinatorial_formula/nutrition_per_item_rounding_before_summation_meets_contract_floor_exactly
    """
    ctx = _draft_cycle_with_standard_day(api)
    before = validate_success(
        api.get_menu_cycle(ctx["cycle"]["id"], users.FOOD_SUPERVISOR)
    )

    signed = validate_success(
        api.nutrition_sign_menu_cycle(ctx["cycle"]["id"], users.DIETITIAN)
    )

    assert signed["approved_cost_cents_per_meal_day"] == 315
    assert signed["nutrition_signed_by_user_id"] == users.user_id_of(users.DIETITIAN)
    assertions.assert_version_bumped_by(before["version"], signed["version"])
    assert signed["activated_by_user_id"] is None
    assert signed["activated_at"] is None


# ---------------------------------------------------------------------------
# Damages waterfall: cap before credit
# ---------------------------------------------------------------------------


def _capped_reconciled_contract(api: ApiClient) -> dict:
    """A contract with a deliberately tiny monthly cap, one closed record worth 3
    weighted missed meals, reconciled under the incident-based variant.

    The pre-cap figure is 2250 cents against a cap of 1000, so the cap binds and
    everything downstream must be computed from the capped figure.
    """
    ctx = fixtures.facility_with_active_cycle(
        api,
        contract_overrides={
            "contract_code": "CFS-2515-CF2",
            "ld_monthly_cap_cents": 1000,
        },
        facility_overrides={
            "facility_code": "FAC-CF2",
            "sharps_authorized_count": 12,
        },
    )
    facility_id = ctx["facility"]["id"]
    count = fixtures.create_population_count(
        api,
        facility_id,
        general_population=130,
        segregation_population=20,
        satellite_population=12,
        medical_population=0,
    )
    forecast = validate_success(
        api.create_meal_forecast(
            factories.meal_forecast_payload(
                facility_id,
                count["id"],
                service_date="2026-08-02",
                meal_slot="BREAKFAST",
                forecast_variant="COUNT_DRIVEN",
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    locked = validate_success(
        api.lock_meal_forecast(forecast["id"], users.FOOD_SUPERVISOR)
    )
    record = validate_success(
        api.create_meal_service_record(
            factories.meal_service_record_payload(
                facility_id,
                locked["id"],
                service_date="2026-08-02",
                meal_slot="BREAKFAST",
                trays_served_general=130,
                trays_served_segregation=15,
                trays_served_satellite=5,
                special_diet_trays_served=0,
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    contract = fixtures.read_contract(api, ctx["contract"]["id"])
    validate_success(
        api.close_meal_service_record(
            record["id"],
            factories.close_service_record_payload(contract["version"]),
            users.FOOD_SUPERVISOR,
        )
    )
    reconciled = validate_success(
        api.reconcile_service_contract(
            ctx["contract"]["id"],
            {"ld_variant": "INCIDENT_BASED"},
            users.CONTRACT_ADMIN,
        )
    )
    ctx["contract"] = reconciled
    return ctx


def test_monthly_cap_binds_before_the_cost_recovery_credit_is_taken(
    api: ApiClient,
) -> None:
    """The credit is a fifth of the capped damages, not of the pre-cap figure.

    The PRD states: "`pre_cap_cents` is `raw_liquidated_damages_cents` plus
    `substitution_surcharge_cents`, and `liquidated_damages_cents` is the lesser of
    `pre_cap_cents` and the contract's `ld_monthly_cap_cents`", followed by
    "`cost_recovery_credit_cents` is the lesser of `liquidated_damages_cents` and
    `gross_food_cost_cents`, multiplied by the credit rate of 0.20, then truncated
    toward zero to a whole cent." With a raw figure of 2250 and a cap of 1000, the
    damages settle at 1000, the credit at 200 and the net at 800.

    Design: Difficulty/combinatorial_formula/liquidated_damages_monthly_cap_applied_before_cost_recovery_credit
    """
    contract = _capped_reconciled_contract(api)["contract"]

    assert contract["missed_meal_total"] == 3
    assert contract["meal_days_served"] == 50
    assert contract["gross_food_cost_cents"] == 15750
    assert contract["raw_liquidated_damages_cents"] == 2250
    assert contract["substitution_surcharge_cents"] == 0
    assert contract["liquidated_damages_cents"] == 1000
    assert contract["cost_recovery_credit_cents"] == 200
    assert contract["net_liquidated_damages_cents"] == 800
    assertions.assert_decimal_2dp(contract["cost_cents_per_meal_day_actual"], 315.00)
    assertions.assert_decimal_2dp(contract["performance_score"], 92.50)


def test_credit_computed_from_the_pre_cap_figure_is_rejected(api: ApiClient) -> None:
    """The forbidden step order is excluded explicitly, and the performance summary
    reports the same normative figures as the contract itself.

    The PRD states: "**The cap must be applied before the cost-recovery credit** —
    step 8 strictly before step 9." Taking the credit from the pre-cap 2250 would
    give a credit of 450 and leave a net of 1000 after capping; the normative order
    gives 200 and 800.

    Design: Difficulty/combinatorial_formula/liquidated_damages_monthly_cap_applied_before_cost_recovery_credit
    """
    ctx = _capped_reconciled_contract(api)
    contract = ctx["contract"]

    assert contract["cost_recovery_credit_cents"] != 450, (
        "the credit must be a fifth of the capped damages, not of the pre-cap figure"
    )
    assert contract["net_liquidated_damages_cents"] != 1000, (
        "capping the net after taking the credit is the forbidden step order"
    )

    summary = validate_success(
        api.get_performance_summary(contract["id"], users.CONTRACT_ADMIN)
    )
    assert summary["liquidated_damages_cents"] == 1000
    assert summary["cost_recovery_credit_cents"] == 200
    assert summary["net_liquidated_damages_cents"] == 800
    assert summary["raw_liquidated_damages_cents"] == 2250
    assert summary["ld_variant"] == "INCIDENT_BASED"
