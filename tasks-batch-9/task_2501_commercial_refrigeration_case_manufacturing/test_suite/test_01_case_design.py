"""Reference-data registration and case-design creation, reading and listing.

Covers the catalogue rows a design depends on (PRD §3.1) and the birth,
retrieval, listing and cross-field validation of a case model (PRD §3.2).
"""

import pytest

from test_helpers import *  # noqa: F401,F403


class TestRefrigerantCatalogue:
    """PRD §3.1 — the immutable refrigerant blend row."""

    def test_01_refrigerant_registration_returns_declared_reference_fields(self, api):
        """A registered blend echoes every declared field and no revision fields.

        PRD §3.1: "Refrigerant rows are pure reference data: they carry an `id`
        and a `created_at` and nothing else — no `updated_at`, no `version`."

        Design: Corner/entities/refrigerant_creation_returns_all_declared_fields
        """
        response = api.create_refrigerant(
            create_refrigerant_payload(
                refrigerant_code="R-448A",
                trade_name="Solstice N40",
                gwp_100yr=1387,
                safety_class="A1",
                max_charge_grams=4000,
                allowed_system_types=["REMOTE", "SELF_CONTAINED"],
            ),
            TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(response, expected_status=201)

        assert_refrigerant(data)
        assert data["refrigerant_code"] == "R-448A"
        assert data["trade_name"] == "Solstice N40"
        assert data["gwp_100yr"] == 1387
        assert data["safety_class"] == "A1"
        assert data["max_charge_grams"] == 4000
        assert data["allowed_system_types"] == ["REMOTE", "SELF_CONTAINED"], (
            "allowed_system_types must echo the declared subset in order"
        )
        assert "version" not in data, "a refrigerant blend must expose no version"
        assert "updated_at" not in data, "a refrigerant blend must expose no updated_at"

    def test_02_refrigerant_registration_without_gwp_is_rejected(self, api):
        """A blend registered with no `gwp_100yr` is a request-shape failure.

        PRD §2.5: "**Rank 4 — request shape.** Required fields present, enum
        members recognised, types correct, numeric fields inside their declared
        constraints, `limit` within 1 to 100 inclusive and `offset` at least 0,
        else `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/refrigerant_creation_missing_gwp_field_rejected
        """
        response = api.create_refrigerant(
            create_refrigerant_payload(
                refrigerant_code="R-NOGWP",
                trade_name="Blend Without GWP",
                gwp_100yr=None,
                safety_class="A1",
                max_charge_grams=4000,
                allowed_system_types=["REMOTE"],
            ),
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_03_duplicate_refrigerant_code_is_rejected(self, api):
        """A second blend re-using an existing `refrigerant_code` collides.

        PRD §3.1: "Refrigerant codes, standard codes, chamber codes, model
        codes, label codes and crew codes are each globally unique; a store
        plan's `store_number` is unique within its `banner_name`; and a depot
        row's `part_number` is unique within its `region_code`. Any collision is
        rejected with `ERR_DUPLICATE_CODE` (HTTP 409)."

        Design: Corner/validations/duplicate_refrigerant_code_rejected
        """
        first = seed_refrigerant()
        assert first["refrigerant_code"] == "R-448A"

        response = api.create_refrigerant(
            create_refrigerant_payload(
                refrigerant_code="R-448A",
                trade_name="Duplicate Blend",
                gwp_100yr=900,
                safety_class="A2L",
                max_charge_grams=4000,
                allowed_system_types=["SELF_CONTAINED"],
            ),
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_CODE.value)


class TestCaseModelCreation:
    """PRD §3.2 — a design is born in DRAFT with nothing computed yet."""

    def test_04_case_model_is_born_in_draft_at_design_revision_one(self, api):
        """A freshly opened design reads DRAFT at design_revision 1, version 1.

        PRD §3.2: "A `DesignEngineer` opens a new design, which is born in
        `DRAFT` with `design_revision` set to 1 and `submitted_by_user_id`
        absent."

        Design: Corner/state_machines/case_model_initial_state_is_draft_at_design_revision_one
        """
        ctx = setup_draft_case_model()

        fetched = validate_success(
            api.get_case_model(ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"])
        )
        assert fetched["status"] == "DRAFT"
        assert fetched["design_revision"] == 1
        assert fetched["version"] == 1
        assert fetched.get("submitted_by_user_id") is None

        rows, meta = validate_paginated(
            api.list_case_models(
                TEST_USERS["design_engineer_headers"], params={"status": "DRAFT"}
            )
        )
        assert meta["total_count"] == 1, "the only design in the store is the DRAFT one"
        assert rows[0]["id"] == fetched["id"]

    def test_05_case_model_system_fields_are_server_generated(self, api):
        """The caller supplies no identity, status, revision or attribution.

        PRD §2.4: "Every persisted resource carries an `id` that is a
        server-minted UUID with no type prefix, and a `created_at` timestamp in
        ISO 8601 UTC with three fractional digits."

        Design: Corner/entities/case_model_system_fields_generated_by_server
        """
        refrigerant = seed_refrigerant()
        response = api.create_case_model(
            create_case_model_payload(refrigerant["id"]),
            TEST_USERS["design_engineer_headers"],
        )
        data = validate_success(response, expected_status=201)

        assert_case_model(data)
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert data["status"] == "DRAFT"
        assert data["design_revision"] == 1
        assert data["version"] == 1
        assert data.get("submitted_by_user_id") is None

    def test_06_case_model_computed_load_fields_are_absent_before_the_airflow_model(
        self, api
    ):
        """All eleven computed airflow and charge fields read absent on a DRAFT.

        PRD §3.2: "All eight computed airflow fields and all three computed
        charge fields are absent on a freshly created design."

        Design: Corner/entities/case_model_computed_load_fields_null_until_airflow_model
        """
        ctx = setup_draft_case_model()
        assert_case_model_load_fields_absent(ctx["case_model"])

        fetched = validate_success(
            api.get_case_model(ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"])
        )
        assert_case_model_load_fields_absent(fetched)

    def test_07_case_model_omitted_glass_door_count_defaults_to_zero(self, api):
        """An OPEN design that omits `glass_door_count` reads back zero doors.

        PRD §3.2: "The front closure `door_type` is either `OPEN` or
        `GLASS_DOOR`, and `glass_door_count` (default 0, never negative) counts
        the glass doors carrying anti-sweat heat."

        Design: Corner/entities/case_model_omitted_glass_door_count_defaults_to_zero
        """
        refrigerant = seed_refrigerant()
        data = validate_success(
            api.create_case_model(
                create_case_model_payload(
                    refrigerant["id"], door_type="OPEN", glass_door_count=None
                ),
                TEST_USERS["design_engineer_headers"],
            ),
            expected_status=201,
        )
        assert data["door_type"] == "OPEN"
        assert data["glass_door_count"] == 0, (
            "an omitted glass_door_count must default to 0, not to absent"
        )

    def test_08_case_model_create_then_get_round_trip(self, api):
        """Every declared design input survives creation and re-reading unchanged.

        PRD §3.2: "Geometry follows: `nominal_length_ft` must be exactly 4, 6, 8
        or 12 feet, and `tda_sqft` is the total display area in square feet,
        strictly greater than zero, which every energy calculation divides by."

        Design: Corner/endpoints/case_model_create_then_get_round_trip
        """
        refrigerant = seed_refrigerant()
        created = validate_success(
            api.create_case_model(
                create_case_model_payload(refrigerant["id"]),
                TEST_USERS["design_engineer_headers"],
            ),
            expected_status=201,
        )
        assert created["model_code"] == "MDL-MT-8"
        assert created["status"] == "DRAFT"

        fetched = validate_success(
            api.get_case_model(created["id"], TEST_USERS["design_engineer_headers"])
        )
        assert fetched["id"] == created["id"]
        assert fetched["refrigerant_id"] == refrigerant["id"]
        assert fetched["tda_sqft"] == pytest.approx(26.4)
        assert fetched["charge_grams"] == 4200
        assert fetched["line_set_length_ft"] == 120
        assert fetched["curtain_layers"] == 2
        assert fetched["defrost_cycles_per_day"] == 4

    def test_09_case_model_retrieval_returns_the_stored_design_inputs(self, api):
        """A read by a non-owning role returns the full stored design.

        PRD §2.1: "Every role in the list may perform every read operation."

        Design: Corner/entities/case_model_retrieval_returns_stored_design_inputs
        """
        ctx = setup_draft_case_model()

        fetched = validate_success(
            api.get_case_model(ctx["case_model"]["id"], TEST_USERS["sales_engineer_headers"])
        )
        assert fetched["model_code"] == "MDL-MT-8"
        assert fetched["application"] == "DAIRY_MULTIDECK"
        assert fetched["temperature_class"] == "MT"
        assert fetched["system_type"] == "REMOTE"
        assert fetched["nominal_length_ft"] == 8
        assert fetched["tda_sqft"] == pytest.approx(26.4)
        assert fetched["door_type"] == "OPEN"
        assert fetched["discharge_velocity_mps"] == pytest.approx(0.55)
        assert fetched["lighting_w_per_ft"] == pytest.approx(12.0)
        assert fetched["fan_w_per_ft"] == pytest.approx(9.5)
        assert fetched.get("predecessor_model_id") is None


class TestCaseModelDiscovery:
    """PRD §2.3 and §3.2 — listing, paging and filtering designs."""

    def test_10_case_model_listing_paginates_with_total_count_and_has_more(self, api):
        """A two-row page over three designs reports the unpaged total.

        PRD §2.3: "List results are ordered by `created_at` ascending unless a
        specific endpoint description states otherwise, and no endpoint in this
        service overrides that default."

        Design: Corner/entities/case_model_listing_paginates_with_total_count_and_has_more
        """
        ctx = setup_draft_case_model()
        refrigerant_id = ctx["refrigerant"]["id"]
        for overrides in (
            {
                "model_code": "MDL-MT-6",
                "application": "DELI_SERVICE",
                "temperature_class": "MT",
                "system_type": "REMOTE",
                "nominal_length_ft": 6,
                "tda_sqft": 19.8,
                "charge_grams": 3000,
                "line_set_length_ft": 60,
                "door_type": "OPEN",
                "glass_door_count": 0,
                "curtain_layers": 2,
                "discharge_velocity_mps": 0.50,
                "case_air_temp_c": 3.0,
                "ambient_dew_point_c": 15.5,
                "lighting_w_per_ft": 11.0,
                "fan_w_per_ft": 9.0,
                "defrost_cycles_per_day": 4,
            },
            {
                "model_code": "MDL-HT-12",
                "application": "PRODUCE_ISLAND",
                "temperature_class": "HT",
                "system_type": "REMOTE",
                "nominal_length_ft": 12,
                "tda_sqft": 39.6,
                "charge_grams": 5200,
                "line_set_length_ft": 140,
                "door_type": "OPEN",
                "glass_door_count": 0,
                "curtain_layers": 1,
                "discharge_velocity_mps": 0.45,
                "case_air_temp_c": 6.0,
                "ambient_dew_point_c": 15.5,
                "lighting_w_per_ft": 10.0,
                "fan_w_per_ft": 8.0,
                "defrost_cycles_per_day": 2,
            },
        ):
            validate_success(
                api.create_case_model(
                    create_case_model_payload(refrigerant_id, **overrides),
                    TEST_USERS["design_engineer_headers"],
                ),
                expected_status=201,
            )

        first_page, first_meta = validate_paginated(
            api.list_case_models(
                TEST_USERS["design_engineer_headers"], params={"limit": 2, "offset": 0}
            )
        )
        assert first_meta["total_count"] == 3, "total_count counts rows before paging"
        assert first_meta["has_more"] is True
        assert len(first_page) == 2
        assert [row["model_code"] for row in first_page] == ["MDL-MT-8", "MDL-MT-6"], (
            "rows must arrive in created_at ascending order"
        )

        last_page, last_meta = validate_paginated(
            api.list_case_models(
                TEST_USERS["design_engineer_headers"], params={"limit": 2, "offset": 2}
            )
        )
        assert last_meta["total_count"] == 3
        assert last_meta["has_more"] is False
        assert len(last_page) == 1
        assert last_page[0]["model_code"] == "MDL-HT-12"

    def test_11_case_model_predecessor_link_is_traversable_by_filter(self, api):
        """`predecessor_model_id` filtering walks a transition chain one hop.

        PRD §3.2: "A design listing can be filtered by `refrigerant_id`, by
        `predecessor_model_id` to walk a transition chain, or by `status`."

        Design: Corner/entities/case_model_predecessor_self_reference_is_traversable
        """
        ctx = setup_draft_case_model()
        predecessor_id = ctx["case_model"]["id"]

        successor = validate_success(
            api.create_case_model(
                create_case_model_payload(
                    ctx["refrigerant"]["id"],
                    model_code="MDL-MT-8B",
                    predecessor_model_id=predecessor_id,
                    charge_grams=3600,
                ),
                TEST_USERS["design_engineer_headers"],
            ),
            expected_status=201,
        )
        assert successor["predecessor_model_id"] == predecessor_id

        rows, meta = validate_paginated(
            api.list_case_models(
                TEST_USERS["design_engineer_headers"],
                params={"predecessor_model_id": predecessor_id},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["model_code"] == "MDL-MT-8B"

        empty, empty_meta = validate_paginated(
            api.list_case_models(
                TEST_USERS["design_engineer_headers"],
                params={"predecessor_model_id": successor["id"]},
            )
        )
        assert empty_meta["total_count"] == 0, "nothing supersedes the successor yet"
        assert empty == []

    def test_12_case_model_get_with_unknown_id_returns_not_found(self, api):
        """An unresolvable path id is the case-model-specific 404.

        PRD §2.5: "**Rank 5 — path existence.** Every identifier appearing in
        the URL path resolves to an existing row, validated left to right, else
        the entity-specific not-found error at HTTP 404"

        Design: Corner/entities/case_model_get_with_unknown_id_returns_not_found
        """
        response = api.get_case_model(
            NON_EXISTENT_UUID, TEST_USERS["design_engineer_headers"]
        )
        validate_error(response, ApiErrorId.ERR_CASE_MODEL_NOT_FOUND.value)


class TestCaseModelCrossFieldRules:
    """PRD §3.2 — closure and circuit configuration are cross-checked at create."""

    def test_13_case_model_unknown_temperature_class_is_rejected(self, api):
        """An unrecognised `temperature_class` member fails request shape.

        PRD §2.5: "**Rank 4 — request shape.** Required fields present, enum
        members recognised, types correct, numeric fields inside their declared
        constraints, `limit` within 1 to 100 inclusive and `offset` at least 0,
        else `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/case_model_unknown_temperature_class_enum_rejected
        """
        refrigerant = seed_refrigerant()
        response = api.create_case_model(
            create_case_model_payload(
                refrigerant["id"], model_code="MDL-BAD-CLASS", temperature_class="FROZEN"
            ),
            TEST_USERS["design_engineer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_14_open_case_declaring_glass_doors_is_rejected(self, api):
        """An OPEN closure carrying three glass doors is a door-config failure.

        PRD §3.2: "An `OPEN` case must carry exactly zero glass doors and a
        `GLASS_DOOR` case must carry at least one; either violation is rejected
        with `ERR_DOOR_CONFIG_INVALID` (HTTP 422) at global rank 17"

        Design: Corner/validations/open_case_declaring_glass_doors_rejected
        """
        refrigerant = seed_refrigerant()
        response = api.create_case_model(
            create_case_model_payload(
                refrigerant["id"],
                model_code="MDL-BAD-DOOR",
                door_type="OPEN",
                glass_door_count=3,
            ),
            TEST_USERS["design_engineer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_DOOR_CONFIG_INVALID.value)

        _rows, meta = validate_paginated(
            api.list_case_models(TEST_USERS["design_engineer_headers"])
        )
        assert meta["total_count"] == 0, "the rejected design must not have persisted"

    def test_15_self_contained_case_declaring_a_line_set_is_rejected(self, api):
        """A SELF_CONTAINED circuit must declare exactly zero line-set feet.

        PRD §3.2: "a `SELF_CONTAINED` case must declare exactly 0 feet of line
        set, while a `REMOTE` case must declare at least 1 foot, and a violation
        of either half is rejected with `ERR_LINE_SET_NOT_PERMITTED` (HTTP 422)
        at global rank 18"

        Design: Corner/validations/self_contained_case_with_line_set_rejected
        """
        refrigerant = seed_refrigerant(
            refrigerant_code="R-290",
            trade_name="Propane",
            gwp_100yr=3,
            safety_class="A3",
            max_charge_grams=300,
            allowed_system_types=["SELF_CONTAINED"],
        )
        response = api.create_case_model(
            create_case_model_payload(
                refrigerant["id"],
                model_code="MDL-SC-6",
                application="GRAB_AND_GO",
                temperature_class="MT",
                system_type="SELF_CONTAINED",
                nominal_length_ft=6,
                tda_sqft=19.8,
                charge_grams=280,
                line_set_length_ft=40,
                door_type="OPEN",
                glass_door_count=0,
                curtain_layers=2,
                discharge_velocity_mps=0.50,
                case_air_temp_c=3.0,
                ambient_dew_point_c=15.5,
                lighting_w_per_ft=11.0,
                fan_w_per_ft=9.0,
                defrost_cycles_per_day=4,
            ),
            TEST_USERS["design_engineer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_LINE_SET_NOT_PERMITTED.value)

    def test_16_submit_for_test_before_the_airflow_model_is_rejected(self, api):
        """Submission is admissible only from MODELED, never straight from DRAFT.

        PRD §3.2: "Submitting a `MODELED` design to the lab moves it `MODELED →
        SUBMITTED_FOR_TEST`, takes no request body, and records the acting
        engineer's `X-User-ID` as `submitted_by_user_id`"

        Design: Corner/state_machines/case_model_submit_for_test_before_airflow_model_rejected
        """
        ctx = setup_draft_case_model()

        response = api.submit_case_model_for_test(
            ctx["case_model"]["id"], TEST_USERS["design_engineer_headers"]
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

        fetched = refresh_case_model(ctx)
        assert fetched["status"] == "DRAFT"
        assert fetched.get("submitted_by_user_id") is None
        assert_version_is(fetched, 1, "case model")
