"""Placing a room-service tray: pricing, nutrient totals and creation-time gates."""
import pytest
from test_helpers import (
    ApiErrorId,
    PHYSICIAN_1,
    TEST_USERS,
    approx1,
    assert_meal_order,
    close_period,
    assert_meal_order_line,
    create_active_diet_order,
    create_meal_order_payload,
    diet_order_version,
    line,
    lines_of,
    lock_forecast,
    new_diet_rule,
    new_meal_period,
    new_menu_item,
    new_menu_items,
    new_patient,
    new_ward,
    open_service,
    place_tray,
    read_diet_order,
    read_meal_order,
    set_clock,
    setup_tray_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["nutrition_manager_headers"]
CLERK = TEST_USERS["diet_clerk_headers"]


def _three_line_pureed_tray():
    """A pureed patient's tray of pudding, supplement and broth, one unit each."""
    return setup_tray_scenario(
        menu_keys=("DES-PUD", "SUP-ORS", "SOU-BRO"),
        patient_overrides={"mrn": "MRN-4001", "texture_level": "PUREED"},
        tray_lines=(("DES-PUD", 1), ("SUP-ORS", 1), ("SOU-BRO", 1)),
    )


def _closed_period_past_cutoff():
    ward = new_ward()
    rule = new_diet_rule("REGULAR_STD")
    rice = new_menu_item("SID-RIC")
    patient = new_patient(ward["id"], mrn="MRN-C001", full_name="Cara Lind",
                          age_years=58)
    diet_order = create_active_diet_order(patient["id"], rule["id"])
    period = new_meal_period(ward["id"])
    lock_forecast(period["id"], "CENSUS_BASED")
    open_service(period["id"])
    close_period(period["id"])
    set_clock("2026-08-02T14:00:00Z")
    return {
        "ward": ward,
        "rule": rule,
        "menu_item": rice,
        "patient": patient,
        "diet_order": diet_order,
        "period": period,
    }


class TestTrayCostRounding:
    def test_food_cost_sums_the_already_rounded_line_costs(self, api):
        """PRD §3.6: "**Tray cost** is computed at the same three moments and is
        deliberately rounded at the line rather than at the tray. First the per-unit
        texture surcharge is read from the tray's `effective_texture_level`: nothing at
        all for `REGULAR`, 25 cents per unit for `MINCED_MOIST`, 60 cents per unit for
        `PUREED`, and 90 cents per unit for `LIQUIDISED`."
        PRD §3.6: "Then, for each line in ascending `created_at` order, the base amount
        is the effective menu item's `unit_cost_cents` multiplied by the line's
        `quantity`, the preparation amount is the surcharge per unit multiplied by that
        same `quantity`, and `line_cost_cents` is the sum of those two amounts
        multiplied by a waste factor of 1.08, rounded half up to whole cents."
        PRD §3.6: "Finally `food_cost_cents` is the plain sum of the already-rounded
        `line_cost_cents` values. **The evaluation order is pinned:** round at the line
        first, then add the rounded integers. The alternative reading — summing the
        unrounded line amounts and rounding once at the end — is rejected, and returns
        a different integer whenever the discarded fractions accumulate past a cent."

        Design: Difficulty/combinatorial_formula/tray_cost_rounds_per_line_before_summing
        """
        scenario = _three_line_pureed_tray()
        tray = scenario["meal_order"]
        assert_meal_order(tray)

        assert tray["food_cost_cents"] == 741
        assert tray["food_cost_cents"] != 740, (
            "summing the unrounded line amounts and rounding once would give 740"
        )

        rows = lines_of(tray["id"])
        assert len(rows) == 3
        for row in rows:
            assert_meal_order_line(row)
        assert sorted(row["line_cost_cents"] for row in rows) == [184, 211, 346]

    def test_nutrient_totals_and_probe_flags_span_every_line(self, api):
        """PRD §3.6: "`total_sodium_mg` is the sum, across lines, of the effective menu
        item's `sodium_mg` multiplied by that line's `quantity`, in whole milligrams,
        and `total_potassium_mg` is the same sum over `potassium_mg`. `total_carb_g` is
        the sum of the effective item's `carb_g` multiplied by `quantity`, with
        round-half-up to 1 decimal place applied **once to the completed sum**, and
        `total_protein_g` is the same over `protein_g`."
        PRD §3.6: "Two booleans fall out of the same pass: `requires_hot_probe` is true
        when at least one line resolves to a menu item whose `service_temp_class` is
        `HOT`, and `requires_cold_probe` is true when at least one line resolves to an
        item whose `service_temp_class` is `COLD`. An `AMBIENT` item demands neither
        probe."

        Design: Difficulty/combinatorial_formula/tray_cost_rounds_per_line_before_summing
        """
        scenario = _three_line_pureed_tray()
        tray = scenario["meal_order"]

        assert tray["total_sodium_mg"] == 1110
        assert tray["total_potassium_mg"] == 690
        assert tray["total_carb_g"] == approx1(55.0)
        assert tray["total_protein_g"] == approx1(23.0)
        assert tray["requires_hot_probe"] is True
        assert tray["requires_cold_probe"] is True


class TestClosedPeriodOutranksCutoff:
    def test_closed_period_wins_over_the_passed_ordering_cutoff(self, api):
        """PRD §2.5: "Requests are checked in a fixed, globally consistent order, and
        **the first check that fails determines the response**. Later checks are not
        evaluated, which means a request with two independent defects always reports
        the defect that sits higher on the ladder."
        PRD §2.5: "9. **Meal period openness** — the meal period the operation touches
        is not `CLOSED`, else `ERR_MEAL_PERIOD_CLOSED`."
        PRD §3.5: "Once `CLOSED`, the period admits no tray creation and no tray
        validation; both report `ERR_MEAL_PERIOD_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/meal_period_closed_state_outranks_order_cutoff_temporal_on_create
        """
        scenario = _closed_period_past_cutoff()

        response = api.create_meal_order(
            create_meal_order_payload(
                scenario["patient"]["id"],
                scenario["period"]["id"],
                scenario["diet_order"]["id"],
                diet_order_version(scenario["diet_order"]["id"]),
                [line(scenario["menu_item"]["id"], 1)],
            ),
            CLERK,
        )
        error = validate_error(response, ApiErrorId.ERR_MEAL_PERIOD_CLOSED, 409)
        assert error["error_id"] != "ERR_ORDER_CUTOFF_PASSED"

    def test_cutoff_defect_is_never_reported_and_nothing_is_persisted(self, api):
        """PRD §2.5: "30. **Ordering cutoff** — else `ERR_ORDER_CUTOFF_PASSED`."
        PRD §3.6: "Ordering closes when the logical clock reaches the period's
        `order_cutoff_at`: the clock must be **strictly before** the cutoff, so an
        attempt at exactly the cutoff instant is already too late and reports
        `ERR_ORDER_CUTOFF_PASSED`."
        PRD §2.5: "Requests are checked in a fixed, globally consistent order, and
        **the first check that fails determines the response**. Later checks are not
        evaluated, which means a request with two independent defects always reports
        the defect that sits higher on the ladder."

        Design: Difficulty/priority_pair_validation_conflict/meal_period_closed_state_outranks_order_cutoff_temporal_on_create
        """
        scenario = _closed_period_past_cutoff()

        response = api.create_meal_order(
            create_meal_order_payload(
                scenario["patient"]["id"],
                scenario["period"]["id"],
                scenario["diet_order"]["id"],
                diet_order_version(scenario["diet_order"]["id"]),
                [line(scenario["menu_item"]["id"], 1)],
            ),
            CLERK,
        )
        assert response.status_code == 409
        assert response.json()["data"]["error_id"] == "ERR_MEAL_PERIOD_CLOSED"

        _, meta = validate_paginated(
            api.list_meal_orders(
                CLERK, params={"meal_period_id": scenario["period"]["id"]}
            )
        )
        assert meta["total_count"] == 0, "the rejected tray must not be stored"


class TestEmptyTray:
    def test_empty_lines_array_is_rejected_as_an_empty_meal_order(self, api):
        """PRD §3.6: "The tray's contents arrive as `lines`, an array in which each
        entry names a `menu_item_id` and a `quantity` of between 1 and 10 units. The
        array must contain at least one entry; an empty `lines` array is rejected with
        `ERR_EMPTY_MEAL_ORDER`."
        PRD §2.5: "31. **Non-empty tray** — else `ERR_EMPTY_MEAL_ORDER`."

        Design: Difficulty/boundary_precision_check/empty_lines_array_rejected_at_tray_creation
        """
        ward = new_ward()
        rule = new_diet_rule("REGULAR_STD")
        patient = new_patient(ward["id"], mrn="MRN-E001", full_name="Eve Marsh",
                              age_years=66)
        diet_order = create_active_diet_order(patient["id"], rule["id"])
        period = new_meal_period(ward["id"])
        set_clock("2026-08-02T09:00:00Z")

        response = api.create_meal_order(
            create_meal_order_payload(
                patient["id"], period["id"], diet_order["id"],
                diet_order["version"], []
            ),
            CLERK,
        )
        error = validate_error(response, ApiErrorId.ERR_EMPTY_MEAL_ORDER, 422)
        assert error["error_id"] != "ERR_INVALID_REQUEST", (
            "an empty array is type-valid, so the request-shape check does not fire"
        )

    def test_empty_tray_rejection_leaves_the_diet_order_untouched(self, api):
        """PRD §3.6: "The array must contain at least one entry; an empty `lines`
        array is rejected with `ERR_EMPTY_MEAL_ORDER`."
        PRD §3.6: "Creation also increments the pinned diet order's
        `linked_meal_order_count` by 1 and therefore that diet order's `version` by 1 —
        which is exactly why the next tray placed against the same prescription needs a
        freshly-read `expected_diet_order_version`."

        Design: Difficulty/boundary_precision_check/empty_lines_array_rejected_at_tray_creation
        """
        ward = new_ward()
        rule = new_diet_rule("REGULAR_STD")
        patient = new_patient(ward["id"], mrn="MRN-E001", full_name="Eve Marsh",
                              age_years=66)
        diet_order = create_active_diet_order(patient["id"], rule["id"])
        period = new_meal_period(ward["id"])
        set_clock("2026-08-02T09:00:00Z")
        version_before = diet_order["version"]

        response = api.create_meal_order(
            create_meal_order_payload(
                patient["id"], period["id"], diet_order["id"], version_before, []
            ),
            CLERK,
        )
        assert response.status_code == 422

        _, meta = validate_paginated(
            api.list_meal_orders(CLERK, params={"meal_period_id": period["id"]})
        )
        assert meta["total_count"] == 0

        after = read_diet_order(diet_order["id"])
        assert after["linked_meal_order_count"] == 0
        assert after["version"] == version_before


class TestTrayCreationGates:
    def test_tray_creation_after_cutoff_on_a_planned_period_returns_cutoff_passed(self, api):
        """PRD §3.6: "Ordering closes when the logical clock reaches the period's
        `order_cutoff_at`: the clock must be **strictly before** the cutoff, so an
        attempt at exactly the cutoff instant is already too late and reports
        `ERR_ORDER_CUTOFF_PASSED`."

        Design: Corner/validations/tray_creation_after_cutoff_on_a_planned_period_returns_cutoff_passed
        """
        ward = new_ward()
        rule = new_diet_rule("REGULAR_STD")
        rice = new_menu_item("SID-RIC")
        patient = new_patient(ward["id"], mrn="MRN-AP01", full_name="Rui Costa",
                              age_years=38)
        diet_order = create_active_diet_order(patient["id"], rule["id"])
        period = new_meal_period(ward["id"])
        set_clock("2026-08-02T11:00:00Z")

        response = api.create_meal_order(
            create_meal_order_payload(
                patient["id"], period["id"], diet_order["id"],
                diet_order["version"], [line(rice["id"], 1)]
            ),
            CLERK,
        )
        validate_error(response, ApiErrorId.ERR_ORDER_CUTOFF_PASSED, 422)

        assert validate_success(
            api.get_meal_period(period["id"], MANAGER)
        )["status"] == "PLANNED", "the state gate passed, isolating the temporal gate"
        _, meta = validate_paginated(
            api.list_meal_orders(CLERK, params={"meal_period_id": period["id"]})
        )
        assert meta["total_count"] == 0

    def test_second_open_tray_for_the_same_patient_and_period_returns_duplicate(self, api):
        """PRD §3.6: "A patient may hold only one live tray per period — if another
        meal order already exists for the same `patient_id` and `meal_period_id` whose
        fulfillment dimension is anything other than `CANCELLED` or `MISSED`, the new
        one is rejected with `ERR_DUPLICATE_MEAL_ORDER`."

        Design: Corner/validations/second_open_tray_for_the_same_patient_and_period_returns_duplicate
        """
        scenario = setup_tray_scenario(
            menu_keys=("SID-RIC",),
            patient_overrides={"mrn": "MRN-AO01", "full_name": "Quen Tao",
                               "age_years": 42},
        )
        fresh_version = diet_order_version(scenario["diet_order"]["id"])

        response = api.create_meal_order(
            create_meal_order_payload(
                scenario["patient"]["id"],
                scenario["period"]["id"],
                scenario["diet_order"]["id"],
                fresh_version,
                [line(scenario["menu"]["SID-RIC"]["id"], 2)],
            ),
            CLERK,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_MEAL_ORDER, 409)

        _, meta = validate_paginated(
            api.list_meal_orders(
                CLERK, params={"meal_period_id": scenario["period"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert read_diet_order(
            scenario["diet_order"]["id"]
        )["linked_meal_order_count"] == 1

    def test_discontinued_menu_item_rejected_at_tray_creation(self, api):
        """PRD §3.2: "A `DISCONTINUED` item may not be placed on a new tray, may not be
        substituted onto an existing line, may not survive a tray validation, and may
        not back a supplement order; all four reject with
        `ERR_MENU_ITEM_DISCONTINUED`."
        PRD §3.2: "Menu items are published `ACTIVE` and the manager may later
        discontinue, reinstate or re-price one, moving `status` between `ACTIVE` and
        `DISCONTINUED` or revising `unit_cost_cents`, with the item's `version` bumping
        on each change."

        Design: Corner/validations/discontinued_menu_item_rejected_at_tray_creation
        """
        ward = new_ward()
        rule = new_diet_rule("REGULAR_STD")
        broth = new_menu_item("SOU-BRO")
        patient = new_patient(ward["id"], mrn="MRN-AK01", full_name="Mira Foss",
                              age_years=47)
        diet_order = create_active_diet_order(patient["id"], rule["id"])
        period = new_meal_period(ward["id"])
        set_clock("2026-08-02T09:00:00Z")
        discontinued = validate_success(
            api.update_menu_item(broth["id"], {"status": "DISCONTINUED"}, MANAGER), 200
        )
        assert discontinued["status"] == "DISCONTINUED"

        response = api.create_meal_order(
            create_meal_order_payload(
                patient["id"], period["id"], diet_order["id"],
                diet_order["version"], [line(broth["id"], 1)]
            ),
            CLERK,
        )
        validate_error(response, ApiErrorId.ERR_MENU_ITEM_DISCONTINUED, 422)

        _, meta = validate_paginated(
            api.list_meal_orders(CLERK, params={"meal_period_id": period["id"]})
        )
        assert meta["total_count"] == 0
        assert read_diet_order(diet_order["id"])["linked_meal_order_count"] == 0


class TestTrayLines:
    def test_totals_and_cost_follow_the_substituted_menu_item(self, api):
        """PRD §3.6: "On success the line's `menu_item_id` becomes the replacement,
        `substituted_from_menu_item_id` records the item the line previously carried,
        `line_status` becomes `SUBSTITUTED`, the reason is stored, and the tray's
        nutrient totals, the line's own `line_cost_cents` and the tray's
        `food_cost_cents` are all recomputed; the line's `version` and the tray's
        `version` each increment by 1."
        PRD §3.6: "Every line of the tray participates, whether its `line_status` is
        `REQUESTED` or `SUBSTITUTED`, processed in ascending `created_at` order; a
        substituted line contributes its **new** menu item, never the item it
        originally carried."

        Design: Corner/calculations/nutrient_totals_and_cost_follow_the_substituted_menu_item
        """
        scenario = setup_tray_scenario(
            menu_keys=("SID-RIC", "ENT-CHK"),
            patient_overrides={"mrn": "MRN-AB01", "full_name": "Bo Lang",
                               "age_years": 50},
            tray_lines=(("SID-RIC", 1),),
        )
        tray_id = scenario["meal_order"]["id"]
        rice = scenario["menu"]["SID-RIC"]
        chicken = scenario["menu"]["ENT-CHK"]
        line_id = lines_of(tray_id)[0]["id"]

        substituted = validate_success(
            api.substitute_line(
                tray_id,
                line_id,
                {"substitute_menu_item_id": chicken["id"],
                 "substitution_reason": "Patient preference"},
                CLERK,
            ),
            200,
        )
        assert substituted["line_status"] == "SUBSTITUTED"
        assert substituted["menu_item_id"] == chicken["id"]
        assert substituted["substituted_from_menu_item_id"] == rice["id"]
        assert substituted["line_cost_cents"] == 367

        tray = read_meal_order(tray_id)
        assert tray["food_cost_cents"] == 367
        assert tray["total_sodium_mg"] == 480
        assert tray["total_potassium_mg"] == 320
        assert tray["total_carb_g"] == approx1(12.0)
        assert tray["total_protein_g"] == approx1(28.0)

        _, meta = validate_paginated(
            api.list_meal_order_lines(
                CLERK, params={"substituted_from_menu_item_id": rice["id"]}
            )
        )
        assert meta["total_count"] == 1

    def test_line_from_another_tray_returns_line_not_found(self, api):
        """PRD §2.8: "If the meal order exists but the line identifier resolves to
        nothing — **or resolves to a line that belongs to some other meal order** — the
        response is `ERR_MEAL_ORDER_LINE_NOT_FOUND`. A line addressed through the wrong
        parent is treated as not found, never as a cross-parent operation."

        Design: Corner/entities/meal_order_line_from_another_tray_returns_line_not_found
        """
        ward = new_ward()
        rule = new_diet_rule("REGULAR_STD")
        menu = new_menu_items(("SID-RIC", "ENT-CHK"))
        patient_one = new_patient(ward["id"], mrn="MRN-Q001", full_name="Quin Roe",
                                  age_years=52)
        patient_two = new_patient(ward["id"], mrn="MRN-Q002", full_name="Rae Lund",
                                  age_years=48)
        order_one = create_active_diet_order(patient_one["id"], rule["id"])
        order_two = create_active_diet_order(patient_two["id"], rule["id"])
        period = new_meal_period(ward["id"])
        set_clock("2026-08-02T09:00:00Z")
        tray_one = place_tray(patient_one["id"], period["id"], order_one["id"],
                              [line(menu["SID-RIC"]["id"], 1)], order_one["version"])
        tray_two = place_tray(patient_two["id"], period["id"], order_two["id"],
                              [line(menu["SID-RIC"]["id"], 1)], order_two["version"])
        foreign_line_id = lines_of(tray_two["id"])[0]["id"]

        response = api.substitute_line(
            tray_one["id"],
            foreign_line_id,
            {"substitute_menu_item_id": menu["ENT-CHK"]["id"]},
            CLERK,
        )
        validate_error(response, ApiErrorId.ERR_MEAL_ORDER_LINE_NOT_FOUND, 404)

        untouched = lines_of(tray_two["id"])[0]
        assert untouched["line_status"] == "REQUESTED"
        assert untouched["menu_item_id"] == menu["SID-RIC"]["id"]
        assert read_meal_order(tray_one["id"])["food_cost_cents"] == 70

    def test_lines_are_discoverable_through_both_foreign_keys(self, api):
        """PRD §3.6: "Lines can be surveyed independently, filtered by
        `meal_order_id`, by the current `menu_item_id`, by the pre-substitution
        `substituted_from_menu_item_id`, or by `line_status`."
        PRD §3.6: "One meal order line is created per `lines` entry, each carrying
        `meal_order_id` back to the owning tray, a `line_status` of `REQUESTED`, and a
        null `substituted_from_menu_item_id` and `substitution_reason`."

        Design: Corner/endpoints/meal_order_lines_filtered_list_finds_children_from_both_foreign_keys
        """
        scenario = setup_tray_scenario(
            menu_keys=("SOU-BRO", "SUP-ORS"),
            patient_overrides={"mrn": "MRN-AR01", "full_name": "Tess Byrne",
                               "age_years": 49},
            tray_lines=(("SOU-BRO", 1), ("SUP-ORS", 2)),
            forecast_variant="CENSUS_BASED",
            open_for_service=True,
        )
        tray = scenario["meal_order"]

        by_tray = api.list_meal_order_lines(
            CLERK, params={"meal_order_id": tray["id"]}
        )
        rows, meta = validate_paginated(by_tray)
        assert by_tray.json()["response_type"] == "array"
        assert meta["total_count"] == 2

        by_item = api.list_meal_order_lines(
            CLERK, params={"menu_item_id": scenario["menu"]["SOU-BRO"]["id"]}
        )
        broth_rows, broth_meta = validate_paginated(by_item)
        assert broth_meta["total_count"] == 1
        assert broth_rows[0]["line_cost_cents"] == 146

        assert tray["food_cost_cents"] == 708
        assert tray["total_protein_g"] == approx1(36.0)
        assert tray["requires_hot_probe"] is True
        assert tray["requires_cold_probe"] is True
