"""Ward registration, patient admission and the reference catalogues."""
import pytest
from test_helpers import (
    ApiErrorId,
    assert_diet_rule,
    assert_menu_item,
    assert_patient,
    assert_ward,
    create_diet_order_payload,
    create_diet_rule_payload,
    create_meal_period_payload,
    create_menu_item_payload,
    create_patient_payload,
    create_ward_payload,
    is_valid_uuid,
    new_diet_rule,
    new_menu_item,
    new_patient,
    new_ward,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["nutrition_manager_headers"]
CLERK = TEST_USERS["diet_clerk_headers"]
DIETITIAN = TEST_USERS["dietitian_headers"]
PHYSICIAN = TEST_USERS["physician_headers"]

UNKNOWN_UUID = "11111111-2222-3333-4444-555555555555"


class TestWardRegistration:
    def test_ward_creation_applies_declared_defaults(self, api):
        """PRD §3.1: "A boolean `temperature_probe_required` completes the profile
        and defaults to true when omitted, meaning a temperature check is mandatory
        before delivery for every tray on that ward."
        PRD §3.1: "A newly registered ward begins `ACTIVE` with an
        `active_patient_census` of 0."
        PRD §2.4: "`version` is an integer that starts at 1 when the row is created
        and increments by exactly 1 on every mutation of that row, including
        mutations that a cascade performs on the operator's behalf rather than
        mutations the operator requested directly."
        PRD §2.4: "Identifiers never carry a type prefix — an entity's `id` is the
        bare UUID string and nothing more."

        Design: Corner/entities/ward_creation_applies_declared_defaults_and_common_fields
        """
        response = api.create_ward(create_ward_payload(), MANAGER)
        ward = validate_success(response, 201)
        assert_ward(ward)

        assert ward["temperature_probe_required"] is True
        assert ward["status"] == "ACTIVE"
        assert ward["active_patient_census"] == 0
        assert ward["version"] == 1
        assert is_valid_uuid(ward["id"]), f"id must be a bare UUID, got {ward['id']!r}"

        body = response.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)

    def test_ward_retrieval_by_id_returns_the_stored_row(self, api):
        """PRD §3.1: "`tray_line_capacity_per_window` is how many trays the ward's
        tray line can plate in a single service window and must be at least 1; it is
        used in exactly one place, as the fallback tray count when a rolling-average
        forecast finds no closed history to average, and nowhere else."
        PRD §3.1: "`delivery_lead_minutes` is the expected gap in minutes between
        plating and bedside arrival and must be zero or greater."

        Design: Corner/entities/ward_retrieval_by_id_returns_the_stored_row
        """
        ward = new_ward()

        response = api.get_ward(ward["id"], CLERK)
        fetched = validate_success(response, 200)

        assert response.json()["response_type"] == "object"
        assert fetched["code"] == "W5E"
        assert fetched["tray_line_capacity_per_window"] == 20
        assert fetched["delivery_lead_minutes"] == 20

    def test_wards_listing_honours_limit_offset_and_reports_has_more(self, api):
        """PRD §2.3: "The `meta` object of a list response carries four pagination
        fields — `limit` and `offset` echo the effective values in force for the
        request, `total_count` reports how many rows match the filters before
        pagination is applied, and `has_more` is true when rows remain beyond the
        current page."

        Design: Corner/entities/wards_listing_honours_limit_offset_and_reports_has_more
        """
        new_ward()
        new_ward(name="Ward 6 North", code="W6N", tray_line_capacity_per_window=16,
                 delivery_lead_minutes=25)

        first_page = api.list_wards(MANAGER, params={"limit": 1, "offset": 0})
        rows, meta = validate_paginated(first_page)
        assert first_page.json()["response_type"] == "array"
        assert len(rows) == 1, f"limit=1 must return one row, got {len(rows)}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is True

        second_page = api.list_wards(MANAGER, params={"limit": 1, "offset": 1})
        rows2, meta2 = validate_paginated(second_page)
        assert len(rows2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False

    def test_ward_get_with_unknown_uuid_returns_not_found(self, api):
        """PRD §2.5: "3. **Path existence** — every identifier embedded in the URL
        resolves to a stored row, checked strictly left to right, else the
        type-specific not-found error described in §2.8."
        PRD §2.8: "Each entity type has its own not-found error so that a client can
        tell which reference failed: `ERR_WARD_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`,
        `ERR_DIET_RULE_NOT_FOUND`, `ERR_DIET_ORDER_NOT_FOUND`,
        `ERR_MEAL_PERIOD_NOT_FOUND`, `ERR_MENU_ITEM_NOT_FOUND`,
        `ERR_MEAL_ORDER_NOT_FOUND`, `ERR_MEAL_ORDER_LINE_NOT_FOUND`,
        `ERR_PROCEDURE_HOLD_NOT_FOUND`, `ERR_CONSULT_NOT_FOUND`,
        `ERR_SUPPLEMENT_ORDER_NOT_FOUND` and `ERR_SURVEY_NOT_FOUND`."

        Design: Corner/entities/ward_get_with_unknown_uuid_returns_not_found
        """
        response = api.get_ward(UNKNOWN_UUID, MANAGER)
        validate_error(response, ApiErrorId.ERR_WARD_NOT_FOUND, 404)

    def test_ward_creation_with_duplicate_code_returns_conflict(self, api):
        """PRD §3.1: "A `NutritionManager` registers a ward with a human-readable
        `name` and a short `code` of between 2 and 8 characters that must be unique
        across all wards — a second ward submitted with a `code` already in use is
        rejected with `ERR_DUPLICATE_WARD_CODE`."

        Design: Corner/entities/ward_creation_with_duplicate_code_returns_conflict
        """
        new_ward()

        response = api.create_ward(
            create_ward_payload(
                name="Ward 5 East Annex",
                code="W5E",
                tray_line_capacity_per_window=8,
                delivery_lead_minutes=15,
            ),
            MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_WARD_CODE, 409)

        _, meta = validate_paginated(api.list_wards(MANAGER))
        assert meta["total_count"] == 1, "the rejected ward must not be stored"

    def test_suspended_ward_blocks_meal_period_creation(self, api):
        """PRD §3.1: "Suspension is not cosmetic: while a ward is `SUSPENDED`, no
        meal period may be created for it, no meal period of that ward may have its
        forecast locked, and no meal period of that ward may be opened for service —
        all three are rejected with `ERR_WARD_SUSPENDED`."
        PRD §3.1: "The manager may later suspend it, moving `status` from `ACTIVE` to
        `SUSPENDED`, and may reinstate it, moving `SUSPENDED` back to `ACTIVE`; each
        move requires the ward to be in the corresponding from-state and bumps the
        ward's `version` by 1, and the same update capability may re-capacity a ward
        by revising `tray_line_capacity_per_window`, `delivery_lead_minutes` or
        `temperature_probe_required`."

        Design: Corner/endpoints/suspended_ward_blocks_meal_period_creation
        """
        ward = new_ward()
        suspended = validate_success(
            api.update_ward(ward["id"], {"status": "SUSPENDED"}, MANAGER), 200
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["version"] == 2, "the suspension is a mutation and bumps version"

        response = api.create_meal_period(create_meal_period_payload(ward["id"]), MANAGER)
        validate_error(response, ApiErrorId.ERR_WARD_SUSPENDED, 409)

        _, meta = validate_paginated(
            api.list_meal_periods(MANAGER, params={"ward_id": ward["id"]})
        )
        assert meta["total_count"] == 0


class TestPatientAdmission:
    def test_patient_creation_missing_required_mrn_returns_invalid_request(self, api):
        """PRD §2.5: "4. **Request shape** — required body fields present, types
        correct, enum members recognised, numeric ranges respected, and the
        pagination parameters within their bounds, else `ERR_INVALID_REQUEST`."
        PRD §3.1: "The admission payload names the ward through `ward_id` and carries
        the patient's `mrn` — a medical record number that must be unique across all
        patients, with a collision rejected as `ERR_DUPLICATE_MRN` — together with
        `full_name` and `age_years`, which must fall between 0 and 120 inclusive."

        Design: Corner/entities/patient_creation_missing_required_mrn_returns_invalid_request
        """
        ward = new_ward()

        response = api.create_patient(
            {"ward_id": ward["id"], "full_name": "Ada Kern", "age_years": 71}, CLERK
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

        _, meta = validate_paginated(
            api.list_patients(CLERK, params={"ward_id": ward["id"]})
        )
        assert meta["total_count"] == 0, "the rejected admission must not be stored"

    def test_patient_creation_applies_texture_and_liquid_defaults(self, api):
        """PRD §3.1: "Three clinical fields are optional at admission and default
        when omitted: `allergen_codes` defaults to an empty list and holds
        upper-snake-case allergen strings such as `PEANUT` or `MILK`; `texture_level`
        defaults to `REGULAR` and records the coarsest texture the patient can safely
        manage, drawn from `REGULAR`, `MINCED_MOIST`, `PUREED` and `LIQUIDISED`; and
        `liquid_level` defaults to `THIN` and records the minimum thickness the
        patient's fluids require, drawn from `THIN`, `MILDLY_THICK`,
        `MODERATELY_THICK` and `EXTREMELY_THICK`."
        PRD §3.1: "An admitted patient starts with `status` of `ADMITTED` and
        `npo_status` of `NONE`, and the ward's `active_patient_census` is recomputed
        immediately."
        PRD §3.1: "A patient row accumulates a running clinical and financial picture
        that no client writes directly, and every one of its numeric rollups starts at
        zero on admission."
        PRD §3.1: "`survey_count` counts the satisfaction surveys recorded for the
        patient and `satisfaction_score_avg` averages them to 2 decimal places,
        reading null while `survey_count` is 0."

        Design: Corner/entities/patient_creation_applies_texture_and_liquid_defaults
        """
        ward = new_ward()

        response = api.create_patient(
            create_patient_payload(ward["id"], mrn="MRN-L001", full_name="Lena Ruiz",
                                   age_years=45),
            CLERK,
        )
        patient = validate_success(response, 201)
        assert_patient(patient)

        assert patient["texture_level"] == "REGULAR"
        assert patient["liquid_level"] == "THIN"
        assert patient["allergen_codes"] == []
        assert patient["status"] == "ADMITTED"
        assert patient["npo_status"] == "NONE"
        assert patient["missed_meal_count"] == 0
        assert patient["protein_deficit_g"] == 0
        assert patient["daily_supplement_cost_cents"] == 0
        assert patient["survey_count"] == 0
        assert patient["satisfaction_score_avg"] is None

        ward_after = validate_success(api.get_ward(ward["id"], MANAGER), 200)
        assert ward_after["active_patient_census"] == 1

    def test_patient_creation_with_duplicate_mrn_returns_conflict(self, api):
        """PRD §3.1: "The admission payload names the ward through `ward_id` and
        carries the patient's `mrn` — a medical record number that must be unique
        across all patients, with a collision rejected as `ERR_DUPLICATE_MRN` —
        together with `full_name` and `age_years`, which must fall between 0 and 120
        inclusive."

        Design: Corner/entities/patient_creation_with_duplicate_mrn_returns_conflict
        """
        ward_one = new_ward()
        ward_two = new_ward(name="Ward 6 North", code="W6N",
                            tray_line_capacity_per_window=16, delivery_lead_minutes=25)
        new_patient(ward_one["id"], mrn="MRN-M001", full_name="Mo Ali", age_years=50)

        response = api.create_patient(
            create_patient_payload(ward_two["id"], mrn="MRN-M001",
                                   full_name="Mo Ali Duplicate", age_years=50),
            CLERK,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_MRN, 409)

        _, meta = validate_paginated(
            api.list_patients(CLERK, params={"ward_id": ward_two["id"]})
        )
        assert meta["total_count"] == 0, "uniqueness is global, not ward-scoped"

    def test_patient_creation_with_unknown_ward_returns_ward_not_found(self, api):
        """PRD §2.5: "5. **Body existence** — every identifier supplied in the
        request body resolves to a stored row, checked in the order the endpoint's
        input list declares those fields, else the type-specific not-found error."
        PRD §2.8: "The same catalogue governs identifiers supplied in a request body,
        with one difference: body identifiers are resolved in the order the endpoint
        declares its input fields, so when two body references are both unresolvable
        the earlier-declared field decides the error."

        Design: Corner/entities/patient_creation_with_unknown_ward_returns_ward_not_found
        """
        response = api.create_patient(
            create_patient_payload(UNKNOWN_UUID, mrn="MRN-N001",
                                   full_name="Nia Blum", age_years=33),
            CLERK,
        )
        validate_error(response, ApiErrorId.ERR_WARD_NOT_FOUND, 404)

    def test_patients_list_filtered_by_ward_id_excludes_other_wards(self, api):
        """PRD §2.3: "Filter query parameters are documented alongside the endpoints
        they belong to; they narrow `total_count` as well as the returned page."
        PRD §2.7: "A ward's `active_patient_census` counts the patients on that ward
        who are `ADMITTED` and whose `npo_status` is `NONE`, and is recomputed
        whenever a patient is admitted, discharged, placed under a hold, or released
        from one."

        Design: Corner/entities/patients_list_filtered_by_ward_id_excludes_other_wards
        """
        ward_one = new_ward()
        ward_two = new_ward(name="Ward 6 North", code="W6N",
                            tray_line_capacity_per_window=16, delivery_lead_minutes=25)
        new_patient(ward_one["id"], mrn="MRN-O001", full_name="Ola Berg", age_years=61)
        patient_two = new_patient(ward_two["id"], mrn="MRN-O002",
                                  full_name="Pia Nord", age_years=39)

        rows, meta = validate_paginated(
            api.list_patients(CLERK, params={"ward_id": ward_two["id"]})
        )
        assert meta["total_count"] == 1, "the filter must narrow total_count"
        assert len(rows) == 1
        assert rows[0]["id"] == patient_two["id"]

        assert validate_success(api.get_ward(ward_one["id"], MANAGER))["active_patient_census"] == 1
        assert validate_success(api.get_ward(ward_two["id"], MANAGER))["active_patient_census"] == 1

    def test_patient_patch_updates_allergens_and_bumps_version(self, api):
        """PRD §3.1: "Those same three clinical fields may be revised later by a
        `DietClerk` or a `Dietitian`; such a revision bumps the patient's `version`,
        and because the therapeutic envelope reads the patient's texture and liquid
        floors, the patient's `ACTIVE` diet order reflects the change the next time
        its envelope is read or a tray is validated against it."

        Design: Corner/endpoints/patient_patch_updates_allergens_and_bumps_version
        """
        ward = new_ward()
        patient = new_patient(ward["id"], mrn="MRN-AQ01", full_name="Sal Munoz",
                              age_years=56)
        assert patient["version"] == 1

        updated = validate_success(
            api.update_patient(
                patient["id"],
                {"allergen_codes": ["PEANUT", "MILK"], "texture_level": "PUREED"},
                DIETITIAN,
            ),
            200,
        )
        assert updated["allergen_codes"] == ["PEANUT", "MILK"]
        assert updated["texture_level"] == "PUREED"
        assert updated["liquid_level"] == "THIN", "an unmentioned field is untouched"
        assert updated["version"] == 2
        assert updated["mrn"] == "MRN-AQ01"

    def test_diet_order_creation_for_a_discharged_patient_returns_patient_discharged(self, api):
        """PRD §3.1: "Once `DISCHARGED`, the patient is closed to further clinical or
        ordering work: drafting or submitting or cosigning a diet order, creating or
        validating a tray, booking or activating a procedure hold, raising a consult,
        and activating a supplement regimen all reject with `ERR_PATIENT_DISCHARGED`."

        Design: Corner/errors/diet_order_creation_for_a_discharged_patient_returns_patient_discharged
        """
        ward = new_ward()
        rule = new_diet_rule("REGULAR_STD")
        patient = new_patient(ward["id"], mrn="MRN-AU01", full_name="Wren Diaz",
                              age_years=81)
        discharged = validate_success(api.discharge_patient(patient["id"], CLERK), 200)
        assert discharged["status"] == "DISCHARGED"

        response = api.create_diet_order(
            create_diet_order_payload(patient["id"], rule["id"]), PHYSICIAN
        )
        validate_error(response, ApiErrorId.ERR_PATIENT_DISCHARGED, 409)

        assert validate_success(api.get_ward(ward["id"], MANAGER))["active_patient_census"] == 0
        _, meta = validate_paginated(
            api.list_diet_orders(PHYSICIAN, params={"patient_id": patient["id"]})
        )
        assert meta["total_count"] == 0


class TestCatalogues:
    def test_menu_item_creation_with_invalid_enum_returns_invalid_request(self, api):
        """PRD §3.2: "`service_temp_class` is one of `HOT`, `COLD` or `AMBIENT` and
        decides which probe reading a tray's temperature check will demand."
        PRD §2.5: "4. **Request shape** — required body fields present, types
        correct, enum members recognised, numeric ranges respected, and the
        pagination parameters within their bounds, else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/menu_item_creation_with_invalid_enum_returns_invalid_request
        """
        response = api.create_menu_item(
            {
                "item_code": "BAD-ONE",
                "display_name": "Mystery Item",
                "sodium_mg": 10,
                "potassium_mg": 10,
                "carb_g": 1.0,
                "protein_g": 1.0,
                "unit_cost_cents": 100,
                "texture_level": "REGULAR",
                "service_temp_class": "LUKEWARM",
            },
            MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

        _, meta = validate_paginated(api.list_menu_items(MANAGER))
        assert meta["total_count"] == 0

    def test_duplicate_menu_item_code_returns_conflict(self, api):
        """PRD §3.2: "Each item carries an `item_code` unique across all items — a
        duplicate is `ERR_DUPLICATE_MENU_ITEM_CODE` — a `display_name`, and a
        nutrition profile of `sodium_mg` and `potassium_mg` in whole milligrams
        together with `carb_g` and `protein_g` in grams to 1 decimal place, each of
        which must be zero or greater."

        Design: Corner/errors/duplicate_menu_item_code_returns_conflict
        """
        item = new_menu_item("SOU-BRO")
        assert_menu_item(item)

        response = api.create_menu_item(
            {
                "item_code": "SOU-BRO",
                "display_name": "Broth Duplicate",
                "sodium_mg": 100,
                "potassium_mg": 100,
                "carb_g": 1.0,
                "protein_g": 1.0,
                "unit_cost_cents": 100,
                "texture_level": "LIQUIDISED",
                "service_temp_class": "HOT",
            },
            MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_MENU_ITEM_CODE, 409)

        _, meta = validate_paginated(api.list_menu_items(MANAGER))
        assert meta["total_count"] == 1

    def test_duplicate_diet_rule_code_returns_conflict(self, api):
        """PRD §3.2: "Each rule carries a `diet_code` that must be unique across all
        rules — a duplicate is rejected with `ERR_DUPLICATE_DIET_RULE_CODE` — a
        human-readable `display_name`, and a `precedence_rank` between 1 and 999
        where a lower number means clinically stronger."

        Design: Corner/errors/duplicate_diet_rule_code_returns_conflict
        """
        rule = new_diet_rule("REGULAR_STD")
        assert_diet_rule(rule)

        response = api.create_diet_rule(
            create_diet_rule_payload(
                "REGULAR_STD", display_name="Regular Duplicate", precedence_rank=91
            ),
            MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_DIET_RULE_CODE, 409)

        _, meta = validate_paginated(api.list_diet_rules(MANAGER))
        assert meta["total_count"] == 1

    def test_retired_diet_rule_rejected_at_diet_order_creation(self, api):
        """PRD §3.2: "A `RETIRED` rule can no longer back a new diet order or a
        resubmitted one; both attempts are rejected with `ERR_DIET_RULE_RETIRED`."

        Design: Corner/validations/retired_diet_rule_rejected_at_diet_order_creation
        """
        ward = new_ward()
        rule = new_diet_rule("REGULAR_STD")
        patient = new_patient(ward["id"], mrn="MRN-AL01", full_name="Nils Haugen",
                              age_years=64)
        retired = validate_success(
            api.update_diet_rule(rule["id"], {"status": "RETIRED"}, DIETITIAN), 200
        )
        assert retired["status"] == "RETIRED"

        response = api.create_diet_order(
            create_diet_order_payload(patient["id"], rule["id"]), PHYSICIAN
        )
        validate_error(response, ApiErrorId.ERR_DIET_RULE_RETIRED, 422)

        _, meta = validate_paginated(
            api.list_diet_orders(PHYSICIAN, params={"patient_id": patient["id"]})
        )
        assert meta["total_count"] == 0

    def test_meal_period_with_cutoff_after_window_start_returns_invalid_window(self, api):
        """PRD §3.5: "The geometry must be sane — the cutoff strictly before the
        window start, and the window start strictly before the window end — and a
        violation is `ERR_INVALID_WINDOW`."

        Design: Corner/validations/meal_period_with_cutoff_after_window_start_returns_invalid_window
        """
        ward = new_ward()

        response = api.create_meal_period(
            create_meal_period_payload(
                ward["id"], order_cutoff_at="2026-08-02T12:00:00Z"
            ),
            MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_WINDOW, 400)

        _, meta = validate_paginated(
            api.list_meal_periods(MANAGER, params={"ward_id": ward["id"]})
        )
        assert meta["total_count"] == 0
