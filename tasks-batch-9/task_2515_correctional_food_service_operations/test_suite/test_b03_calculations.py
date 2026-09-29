"""Calculations: deadlines, tray arithmetic, nutrition rounding and the ledger.

Every figure in this domain is derived by a formula whose step order the
specification pins. These cases exercise the pinned orders — per-item rounding
before summation, the ceiling per population segment, the tiered waste
allowance, inclusive equivalence bands, the closed chiller interval, and the
nine-step damages waterfall including the divergence between its two variants.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import ApiClient, assertions, factories, fixtures
from test_helpers import test_users as users


def _lunch_item(ctx: dict) -> dict:
    """The LUNCH component of the fixture's one-day cycle."""
    for item in ctx["items"]:
        if item["meal_slot"] == "LUNCH":
            return item
    raise AssertionError("the fixture cycle has no LUNCH component")


# ---------------------------------------------------------------------------
# Deadlines
# ---------------------------------------------------------------------------


def test_a_religious_denial_grievance_is_due_five_days_later_to_the_minute(
    api: ApiClient,
) -> None:
    """The expedited window is five 24-hour days measured from `filed_at`, so the
    deadline keeps the filing time of day rather than dropping to midnight.

    The PRD states: "The window is 5 days when the `category` is
    `RELIGIOUS_DIET_DENIAL` or `DIET_NOT_HONORED` — a denied religious or therapeutic
    diet is an ongoing harm and gets the expedited window — and 10 days for every other
    category. `response_due_at` is `filed_at` plus that many days, each day being
    exactly 24 hours."

    Design: Corner/calculations/corner_expedited_grievance_due_date_is_five_days_from_filing
    """
    fixtures.set_clock(api, "2026-08-03T09:00:00Z")
    contract = fixtures.create_contract(api, contract_code="CFS-2515-C01")
    facility = fixtures.create_facility(
        api, contract["id"], facility_code="FAC-C01", sharps_authorized_count=12
    )
    inmate = fixtures.create_inmate(
        api, facility["id"], booking_number="BK-C01", religious_affiliation="MUSLIM"
    )

    grievance = fixtures.filed_grievance(
        api,
        inmate["id"],
        facility["id"],
        category="RELIGIOUS_DIET_DENIAL",
        narrative="Halal tray refused at the serving line.",
    )

    assertions.assert_grievance(grievance)
    assertions.assert_instant(grievance["filed_at"], "2026-08-03T09:00:00Z")
    assertions.assert_instant(grievance["response_due_at"], "2026-08-08T09:00:00Z")
    assert grievance["status"] == "FILED"
    assert grievance["sla_breached"] is False


# ---------------------------------------------------------------------------
# Forecast tray arithmetic
# ---------------------------------------------------------------------------


def test_only_active_orders_covering_the_service_date_count_as_special_diets(
    api: ApiClient,
) -> None:
    """Three orders exist; only the one that is ACTIVE and whose half-open window
    contains the service date is counted, and it does not disturb the line arithmetic.

    The PRD states: "`forecast_special_diet_trays` is counted separately and is not part
    of the line arithmetic. It is the number of diet orders whose `status` is `ACTIVE`,
    whose inmate is `IN_CUSTODY` at this forecast's facility, and whose coverage window
    contains the service date treated as midnight UTC on that date: the order's
    `effective_from` must be at or before that instant and its `effective_to` must be
    strictly after it."

    Design: Corner/calculations/corner_forecast_special_diet_count_includes_only_active_in_window_orders
    """
    ctx = fixtures.active_contract_with_facility(
        api,
        contract_overrides={"contract_code": "CFS-2515-C02"},
        facility_overrides={
            "facility_code": "FAC-C02",
            "sharps_authorized_count": 12,
        },
    )
    facility_id = ctx["facility"]["id"]

    covering = fixtures.create_inmate(
        api, facility_id, booking_number="BK-C02A", religious_affiliation="JEWISH"
    )
    unverified = fixtures.create_inmate(
        api, facility_id, booking_number="BK-C02B", religious_affiliation="MUSLIM"
    )
    later = fixtures.create_inmate(
        api, facility_id, booking_number="BK-C02C", religious_affiliation="JEWISH"
    )

    order_a = validate_success(
        api.create_diet_order(
            factories.religious_diet_order_payload(
                covering["id"],
                covering["version"],
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2026-10-01T00:00:00Z",
            ),
            users.DIETITIAN,
        ),
        201,
    )
    assert (
        validate_success(api.verify_diet_order(order_a["id"], users.CHAPLAIN))["status"]
        == "ACTIVE"
    )
    order_b = validate_success(
        api.create_diet_order(
            factories.religious_diet_order_payload(
                unverified["id"],
                unverified["version"],
                diet_code="HALAL",
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2026-10-01T00:00:00Z",
            ),
            users.DIETITIAN,
        ),
        201,
    )
    assert order_b["status"] == "PENDING_VERIFICATION"
    order_c = validate_success(
        api.create_diet_order(
            factories.religious_diet_order_payload(
                later["id"],
                later["version"],
                effective_from="2026-08-05T00:00:00Z",
                effective_to="2026-10-05T00:00:00Z",
            ),
            users.DIETITIAN,
        ),
        201,
    )
    assert (
        validate_success(api.verify_diet_order(order_c["id"], users.CHAPLAIN))["status"]
        == "ACTIVE"
    )

    count = fixtures.create_population_count(api, facility_id)
    forecast = validate_success(
        api.create_meal_forecast(
            factories.meal_forecast_payload(
                facility_id,
                count["id"],
                service_date="2026-08-01",
                meal_slot="LUNCH",
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )

    assertions.assert_meal_forecast(forecast)
    assert forecast["forecast_special_diet_trays"] == 1
    assert forecast["line_trays"] == 14
    assert forecast["waste_allowance_trays"] == 8
    assert forecast["total_forecast_trays"] == 22
    assert forecast["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Substitution arithmetic
# ---------------------------------------------------------------------------


def test_equivalence_bands_are_inclusive_at_their_edges_to_two_decimals(
    api: ApiClient,
) -> None:
    """A substitute landing exactly on all three limits is equivalent; one two decimals
    beyond the energy band is not.

    The PRD states: "each of the six nutrition figures is portion-scaled and rounded to
    2 decimal places with half-up rounding **before** any delta is taken", that
    "`kcal_delta_pct` is the substitute kilocalories minus the planned kilocalories,
    multiplied by 100, divided by the planned kilocalories, rounded to 2 decimal
    places", and that "`nutrition_equivalent` is true if and only if all three of these
    hold, and every band is inclusive at its limit: the absolute value of
    `kcal_delta_pct` is at or below 10.00, `protein_delta_pct` is at or above negative
    5.00, and `sodium_delta_mg` is at or below 200.00." It also states that on the
    approved branch alone "the service record's `substitution_count` rises by 1".

    Design: Corner/calculations/corner_substitution_deltas_round_to_two_decimals_on_the_band_edges
    """
    ctx = fixtures.open_service_record(
        api,
        fixtures.locked_forecast(
            api,
            contract_overrides={"contract_code": "CFS-2515-C03"},
            facility_overrides={
                "facility_code": "FAC-C03",
                "sharps_authorized_count": 12,
            },
        ),
    )
    lunch = _lunch_item(ctx)
    record_id = ctx["record"]["id"]

    on_the_edge = validate_success(
        api.create_menu_substitution(
            factories.menu_substitution_payload(
                lunch["id"],
                record_id,
                substitute_component_name="Chicken Rice Bake",
                substitute_kcal_per_100g=275.4,
                substitute_protein_grams_per_100g=7.6,
                substitute_sodium_mg_per_100g=400.0,
                substitute_portion_grams=225,
                substitute_cost_cents=105,
                reason="SUPPLY_OUTAGE",
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )

    assertions.assert_menu_substitution(on_the_edge)
    assertions.assert_decimal_2dp(on_the_edge["kcal_delta_pct"], -10.00)
    assertions.assert_decimal_2dp(on_the_edge["protein_delta_pct"], -5.00)
    assertions.assert_decimal_2dp(on_the_edge["sodium_delta_mg"], 0.00)
    assert on_the_edge["cost_variance_cents"] == -5
    assert on_the_edge["nutrition_equivalent"] is True
    assert on_the_edge["approval_status"] == "PENDING"

    too_thin = validate_success(
        api.create_menu_substitution(
            factories.menu_substitution_payload(
                lunch["id"],
                record_id,
                substitute_component_name="Thin Vegetable Broth",
                substitute_kcal_per_100g=261.0,
                substitute_protein_grams_per_100g=7.6,
                substitute_sodium_mg_per_100g=400.0,
                substitute_portion_grams=225,
                substitute_cost_cents=90,
                reason="SUPPLY_OUTAGE",
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )

    assertions.assert_decimal_2dp(too_thin["kcal_delta_pct"], -14.71)
    assert too_thin["nutrition_equivalent"] is False
    assert too_thin["approval_status"] == "PENDING"
    assert too_thin["cost_variance_cents"] == -20

    record = fixtures.read_service_record(api, record_id)
    assert record["substitution_count"] == 0, "the counter only moves on approval"


def test_approving_a_substitution_mid_reconcile_voids_the_money_but_not_the_tallies(
    api: ApiClient,
) -> None:
    """The reconciliation is thrown away — variant, stamp and every cents figure reset —
    while the trays, meal days, missed meals and substitution count survive.

    The PRD states: "When a substitution is approved while the contract sits in
    `RECONCILING` ... the contract cycles back from `RECONCILING` to `ACTIVE`.
    `ld_variant` is cleared to null and `reconciled_at` is cleared to null;
    `raw_liquidated_damages_cents`, `substitution_surcharge_cents`,
    `liquidated_damages_cents`, `cost_recovery_credit_cents`,
    `net_liquidated_damages_cents` and `gross_food_cost_cents` are all reset to 0;
    `cost_cents_per_meal_day_actual`, `substitution_rate_pct` and `performance_score` are
    all reset to 0.00 ... Crucially, `total_trays_served`, `meal_days_served`,
    `missed_meal_total` and `grievance_sla_breach_count` are **not** zeroed." Approval is
    permitted here because "a substitution may only be approved when
    `nutrition_equivalent` is true, **or** when its `reason` is `QA_CONDEMNATION`."

    Design: Corner/calculations/corner_substitution_decision_during_reconcile_invalidates_the_ledger
    """
    ctx = fixtures.closed_service_record(
        api,
        fixtures.locked_forecast(
            api,
            contract_overrides={"contract_code": "CFS-2515-C04"},
            facility_overrides={
                "facility_code": "FAC-C04",
                "sharps_authorized_count": 12,
            },
        ),
    )
    contract_id = ctx["contract"]["id"]
    record_id = ctx["record"]["id"]
    assert ctx["record"]["status"] == "CLOSED"
    assert ctx["record"]["expected_service_trays"] == 14
    assert ctx["record"]["total_trays_served"] == 13
    assert ctx["record"]["missed_meal_count"] == 1

    substitution = validate_success(
        api.create_menu_substitution(
            factories.menu_substitution_payload(
                _lunch_item(ctx)["id"],
                record_id,
                substitute_component_name="Emergency Bean Bake",
                substitute_kcal_per_100g=200.0,
                substitute_protein_grams_per_100g=4.0,
                substitute_sodium_mg_per_100g=500.0,
                substitute_portion_grams=225,
                substitute_cost_cents=120,
                reason="QA_CONDEMNATION",
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    assert substitution["nutrition_equivalent"] is False

    reconciled = validate_success(
        api.reconcile_service_contract(
            contract_id, {"ld_variant": "INCIDENT_BASED"}, users.CONTRACT_ADMIN
        )
    )
    assert reconciled["status"] == "RECONCILING"
    assert reconciled["ld_variant"] == "INCIDENT_BASED"
    assertions.assert_instant(reconciled["reconciled_at"], "2026-08-01T00:00:00Z")
    assert reconciled["gross_food_cost_cents"] == 1260
    assert reconciled["raw_liquidated_damages_cents"] == 750
    assert reconciled["liquidated_damages_cents"] == 750
    assert reconciled["cost_recovery_credit_cents"] == 150
    assert reconciled["net_liquidated_damages_cents"] == 600
    assertions.assert_decimal_2dp(reconciled["performance_score"], 97.50)

    approved = validate_success(
        api.decide_menu_substitution(
            substitution["id"],
            factories.substitution_decision_payload(
                "APPROVED", decision_note="Condemned batch, substitution stands."
            ),
            users.DIETITIAN_2,
        )
    )
    assert approved["approval_status"] == "APPROVED"

    contract = fixtures.read_contract(api, contract_id)
    assert contract["status"] == "ACTIVE"
    assert contract["ld_variant"] is None
    assert contract["reconciled_at"] is None
    for field in (
        "raw_liquidated_damages_cents",
        "substitution_surcharge_cents",
        "liquidated_damages_cents",
        "cost_recovery_credit_cents",
        "net_liquidated_damages_cents",
        "gross_food_cost_cents",
    ):
        assert contract[field] == 0, field
    assertions.assert_decimal_2dp(contract["cost_cents_per_meal_day_actual"], 0.00)
    assertions.assert_decimal_2dp(contract["substitution_rate_pct"], 0.00)
    assertions.assert_decimal_2dp(contract["performance_score"], 0.00)
    assert contract["total_trays_served"] == 13
    assert contract["meal_days_served"] == 4
    assert contract["missed_meal_total"] == 1
    assert contract["substitution_total"] == 1
    assert fixtures.read_service_record(api, record_id)["substitution_count"] == 1


# ---------------------------------------------------------------------------
# Nutrition rounding order and the HACCP thresholds
# ---------------------------------------------------------------------------
