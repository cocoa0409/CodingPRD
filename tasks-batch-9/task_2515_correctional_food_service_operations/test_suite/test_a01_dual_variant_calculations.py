"""Dual-variant calculations: the same fixture must diverge when the variant flips.

Two variant switches exist in this contract. A meal forecast is either
`COUNT_DRIVEN` or `ROSTER_DRIVEN`, and a contract reconciliation is either
`INCIDENT_BASED` or `POPULATION_WEIGHTED`. Each pair is exercised over one
identical fixture so that only the variant explains the difference.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import ApiClient, assertions, factories, fixtures
from test_helpers import test_users as users


# ---------------------------------------------------------------------------
# Forecast variant fixture
# ---------------------------------------------------------------------------


def _forecast_variant_context(api: ApiClient) -> dict:
    """An ACTIVE contract and facility whose roster of record disagrees with the
    stored population count: three heads booked against a count feed of 13."""
    ctx = fixtures.facility_with_active_cycle(
        api,
        contract_overrides={"contract_code": "CFS-2515-DV1"},
        facility_overrides={
            "facility_code": "FAC-DV1",
            "sharps_authorized_count": 12,
            "satellite_site_count": 0,
            "blast_chiller_capacity": 2,
        },
    )
    facility_id = ctx["facility"]["id"]
    fixtures.create_inmate(
        api, facility_id, booking_number="BK-DV1-001", housing_unit="GENERAL"
    )
    fixtures.create_inmate(
        api, facility_id, booking_number="BK-DV1-002", housing_unit="GENERAL"
    )
    fixtures.create_inmate(
        api, facility_id, booking_number="BK-DV1-003", housing_unit="SEGREGATION"
    )
    count = fixtures.create_population_count(
        api,
        facility_id,
        general_population=10,
        segregation_population=2,
        satellite_population=1,
        medical_population=0,
        source="FORMAL_COUNT",
    )
    ctx["population_count"] = count
    return ctx


def _forecast(api: ApiClient, ctx: dict, meal_slot: str, variant: str) -> dict:
    return validate_success(
        api.create_meal_forecast(
            factories.meal_forecast_payload(
                ctx["facility"]["id"],
                ctx["population_count"]["id"],
                service_date="2026-08-02",
                meal_slot=meal_slot,
                forecast_variant=variant,
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )


def test_count_driven_forecast_reads_the_stored_population_count(api: ApiClient) -> None:
    """A count-driven forecast takes its four segment populations off the
    referenced count row and never from the roster.

    The PRD states: "A `COUNT_DRIVEN` forecast — the standard path — reads the
    four population fields off the referenced population count row." The segment
    ladder then applies: the serving line is general plus medical at 94 percent
    rounded up (10 heads gives 10 trays), segregation is served head for head
    (2 trays) and satellite carries a 3 percent transport loss rounded up (1 head
    gives 2 trays), so `line_trays` is 14. A line demand of 500 trays or fewer
    takes the flat allowance of 8 trays, so `total_forecast_trays` is 22.

    Design: Difficulty/dual_variant_calc/forecast_count_driven_vs_roster_driven_diverge_on_stale_count_feed
    """
    ctx = _forecast_variant_context(api)

    assert ctx["population_count"]["total_population"] == 13
    assertions.assert_population_count(ctx["population_count"])

    forecast = _forecast(api, ctx, "BREAKFAST", "COUNT_DRIVEN")

    assertions.assert_meal_forecast(forecast)
    assert forecast["forecast_variant"] == "COUNT_DRIVEN"
    assert forecast["line_trays"] == 14
    assert forecast["waste_allowance_trays"] == 8
    assert forecast["total_forecast_trays"] == 22
    assert forecast["forecast_special_diet_trays"] == 0
    assert forecast["status"] == "DRAFT"


def test_roster_driven_forecast_recounts_the_roster_and_diverges(api: ApiClient) -> None:
    """A roster-driven forecast ignores the stored numbers and recounts custody,
    so the identical fixture produces a materially smaller tray demand.

    The PRD states: "A `ROSTER_DRIVEN` forecast is used when the count feed has
    gone stale and the roster of record governs: it ignores the stored numbers
    entirely and recounts inmates at calculation time, taking every inmate at the
    facility whose `status` is `IN_CUSTODY` and bucketing them by `housing_unit`."
    Two general heads give a serving line of 2 trays after the 94 percent rate is
    rounded up, one segregation head gives 1 mandatory in-cell tray and there are
    no satellite heads, so `line_trays` is 3 against the count-driven 14.

    Design: Difficulty/dual_variant_calc/forecast_count_driven_vs_roster_driven_diverge_on_stale_count_feed
    """
    ctx = _forecast_variant_context(api)

    count_driven = _forecast(api, ctx, "BREAKFAST", "COUNT_DRIVEN")
    roster_driven = _forecast(api, ctx, "LUNCH", "ROSTER_DRIVEN")

    assertions.assert_meal_forecast(roster_driven)
    assert roster_driven["forecast_variant"] == "ROSTER_DRIVEN"
    assert roster_driven["line_trays"] == 3
    assert roster_driven["waste_allowance_trays"] == 8
    assert roster_driven["total_forecast_trays"] == 11
    assert roster_driven["forecast_special_diet_trays"] == 0

    assert count_driven["line_trays"] - roster_driven["line_trays"] == 11
    assert (
        count_driven["total_forecast_trays"] - roster_driven["total_forecast_trays"] == 11
    )
    assert roster_driven["population_count_id"] == ctx["population_count"]["id"]


# ---------------------------------------------------------------------------
# Liquidated damages variant fixture
# ---------------------------------------------------------------------------


def _reconciled_contract(api: ApiClient, suffix: str, ld_variant: str) -> dict:
    """A contract carrying exactly one closed service record with 3 weighted
    missed meals, reconciled under the named variant.

    The forecast is built from a count of 130 general, 20 segregation and 12
    satellite heads, giving a line of 156 trays and an expected service of 156.
    150 trays are served, so the shortfall of 6 less the tolerance of 3 leaves 3
    weighted missed meals over 50 meal-days.
    """
    ctx = fixtures.facility_with_active_cycle(
        api,
        contract_overrides={"contract_code": f"CFS-2515-DV2{suffix}"},
        facility_overrides={
            "facility_code": f"FAC-DV2{suffix}",
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
    assert locked["line_trays"] == 156
    assert locked["waste_allowance_trays"] == 8
    assert locked["total_forecast_trays"] == 164

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
    assert record["expected_service_trays"] == 156

    contract = fixtures.read_contract(api, ctx["contract"]["id"])
    closed = validate_success(
        api.close_meal_service_record(
            record["id"],
            factories.close_service_record_payload(contract["version"]),
            users.FOOD_SUPERVISOR,
        )
    )
    assert closed["missed_meal_count"] == 3

    reconciled = validate_success(
        api.reconcile_service_contract(
            ctx["contract"]["id"], {"ld_variant": ld_variant}, users.CONTRACT_ADMIN
        )
    )
    return {"contract": reconciled, "facility": ctx["facility"], "record": closed}


def test_incident_based_variant_charges_a_flat_rate_per_missed_meal(
    api: ApiClient,
) -> None:
    """Under the incident-based variant the damages term is nothing more than the
    weighted missed-meal count times the contractual rate.

    The PRD states: "Under `INCIDENT_BASED`, the variant term is
    `missed_meal_total` multiplied by `ld_cents_per_missed_meal`." With 3 weighted
    missed meals at 750 cents each the term is 2250 cents; there are no
    substitutions and no grievance breaches, so the raw figure stands, the cap of
    5000000 cents does not bite, the credit is a truncated fifth of it at 450 and
    the net settles at 1800.

    Design: Difficulty/dual_variant_calc/liquidated_damages_incident_based_vs_population_weighted_diverge_on_severity_multiplier
    """
    result = _reconciled_contract(api, "A", "INCIDENT_BASED")
    contract = result["contract"]

    assert contract["status"] == "RECONCILING"
    assert contract["ld_variant"] == "INCIDENT_BASED"
    assert contract["total_trays_served"] == 150
    assert contract["meal_days_served"] == 50
    assert contract["missed_meal_total"] == 3
    assert contract["grievance_sla_breach_count"] == 0
    assert contract["gross_food_cost_cents"] == 15750
    assert contract["raw_liquidated_damages_cents"] == 2250
    assert contract["substitution_surcharge_cents"] == 0
    assert contract["liquidated_damages_cents"] == 2250
    assert contract["cost_recovery_credit_cents"] == 450
    assert contract["net_liquidated_damages_cents"] == 1800
    assertions.assert_decimal_2dp(contract["performance_score"], 92.50)


def test_population_weighted_variant_adds_the_severity_multiplier(
    api: ApiClient,
) -> None:
    """Under the population-weighted variant the same three missed meals cost more,
    because failures concentrated into few meal-days are surcharged.

    The PRD states: "Under `POPULATION_WEIGHTED`, the variant term is
    `missed_meal_total` multiplied by `ld_cents_per_missed_meal` multiplied by a
    severity multiplier, the whole product rounded **up** to the next whole cent.
    The severity multiplier is 1 plus the quotient of `missed_meal_total` divided
    by the greater of 1 and `meal_days_served`, that quotient rounded to 2 decimal
    places with half-up rounding before the multiplication." Three missed meals
    over 50 meal-days give a quotient of 0.06 and a multiplier of 1.06, so the term
    is 3 times 750 times 1.06 rounded up, namely 2385 cents.

    Design: Difficulty/dual_variant_calc/liquidated_damages_incident_based_vs_population_weighted_diverge_on_severity_multiplier
    """
    result = _reconciled_contract(api, "B", "POPULATION_WEIGHTED")
    contract = result["contract"]

    assert contract["status"] == "RECONCILING"
    assert contract["ld_variant"] == "POPULATION_WEIGHTED"
    assert contract["total_trays_served"] == 150
    assert contract["meal_days_served"] == 50
    assert contract["missed_meal_total"] == 3
    assert contract["gross_food_cost_cents"] == 15750
    assert contract["raw_liquidated_damages_cents"] == 2385
    assert contract["substitution_surcharge_cents"] == 0
    assert contract["liquidated_damages_cents"] == 2385
    assert contract["cost_recovery_credit_cents"] == 477
    assert contract["net_liquidated_damages_cents"] == 1908
    assertions.assert_decimal_2dp(contract["performance_score"], 92.50)


def test_the_two_damages_variants_share_every_other_ledger_figure(
    api: ApiClient,
) -> None:
    """Reconciling two structurally identical contracts under the two variants
    isolates the divergence to the damages terms alone.

    The PRD states: "`raw_liquidated_damages_cents` is the sum of a variant term
    and a grievance term." Only the variant term differs, so the tray, meal-day,
    missed-meal, gross cost and performance figures must be identical while the
    net damages differ by exactly 108 cents.

    Design: Difficulty/dual_variant_calc/liquidated_damages_incident_based_vs_population_weighted_diverge_on_severity_multiplier
    """
    incident = _reconciled_contract(api, "A", "INCIDENT_BASED")["contract"]
    weighted = _reconciled_contract(api, "B", "POPULATION_WEIGHTED")["contract"]

    assertions.assert_fields_equal(
        incident,
        weighted,
        (
            "total_trays_served",
            "meal_days_served",
            "missed_meal_total",
            "grievance_sla_breach_count",
            "gross_food_cost_cents",
            "substitution_surcharge_cents",
            "substitution_total",
            "status",
        ),
    )
    assertions.assert_decimal_2dp(incident["cost_cents_per_meal_day_actual"], 315.00)
    assertions.assert_decimal_2dp(weighted["cost_cents_per_meal_day_actual"], 315.00)
    assertions.assert_decimal_2dp(
        float(incident["performance_score"]), float(weighted["performance_score"])
    )

    assert (
        weighted["raw_liquidated_damages_cents"]
        - incident["raw_liquidated_damages_cents"]
        == 135
    )
    assert (
        weighted["net_liquidated_damages_cents"]
        - incident["net_liquidated_damages_cents"]
        == 108
    )
