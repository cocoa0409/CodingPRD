"""Creation, retrieval and rejection surface of the plant's fourteen resources.

Every test starts from an empty database and builds its own preconditions through
the documented endpoints, with the logical plant clock positioned first.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    PlantScenario,
    TEST_USERS,
    api_client,
    assert_certification_family,
    assert_component_lot,
    assert_engine_platform,
    assert_envelope_meta,
    assert_safety_certification,
    assert_service_part,
    build_assembly_line,
    build_certification_family,
    build_closed_machining_run,
    build_engine_platform,
    build_product_model,
    build_released_model,
    build_safety_certification,
    build_service_part,
    build_supplier,
    build_supply_base,
    certify_family,
    complete_durability_run,
    create_assembly_line_payload,
    create_build_order_payload,
    create_certification_family_payload,
    create_component_lot_payload,
    create_durability_test_payload,
    create_engine_platform_payload,
    create_engine_unit_payload,
    create_parts_request_payload,
    create_product_model_payload,
    create_service_part_payload,
    family_version,
    hot_test_unit,
    is_iso8601_timestamp,
    is_valid_uuid,
    plan_build_order,
    raise_parts_request,
    read_platform,
    read_service_part,
    receive_component_lot,
    record_line_audit_payload,
    record_torque,
    release_build_order,
    release_engine_unit,
    release_product_model,
    schedule_durability_run,
    schedule_line_audit,
    stage_engine_unit,
    submit_family,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANT_ADMIN = TEST_USERS["plant_admin_headers"]
CERTIFICATION_ENGINEER = TEST_USERS["certification_engineer_headers"]
COMPLIANCE_OFFICER = TEST_USERS["compliance_officer_headers"]
QUALITY_ENGINEER = TEST_USERS["quality_engineer_headers"]
PRODUCTION_PLANNER = TEST_USERS["production_planner_headers"]
CHANNEL_PARTNER = TEST_USERS["channel_partner_headers"]


# ---------------------------------------------------------------------------
# Callables used by the parametrised rejection families below. Each one drives
# exactly one documented endpoint against preconditions the test already built.
# ---------------------------------------------------------------------------


def _read_absent_certification_family(scenario):
    return api_client.get_certification_family(NON_EXISTENT_UUID, CERTIFICATION_ENGINEER)


def _read_absent_engine_platform(scenario):
    return api_client.get_engine_platform(NON_EXISTENT_UUID, PLANT_ADMIN)


def _read_absent_durability_test(scenario):
    return api_client.get_durability_test(NON_EXISTENT_UUID, CERTIFICATION_ENGINEER)


def _read_absent_product_model(scenario):
    return api_client.get_product_model(NON_EXISTENT_UUID, PLANT_ADMIN)


def _read_absent_supplier_scorecard(scenario):
    return api_client.get_supplier_scorecard(NON_EXISTENT_UUID, QUALITY_ENGINEER)


def _read_absent_component_lot(scenario):
    return api_client.get_component_lot(NON_EXISTENT_UUID, QUALITY_ENGINEER)


def _read_absent_machining_run(scenario):
    return api_client.get_machining_run(NON_EXISTENT_UUID, QUALITY_ENGINEER)


def _plan_order_against_absent_assembly_line(scenario):
    return api_client.create_build_order(
        create_build_order_payload(
            scenario.model_id,
            NON_EXISTENT_UUID,
            week_span=1,
            planned_quantity=4,
        ),
        PRODUCTION_PLANNER,
    )


def _read_absent_build_order(scenario):
    return api_client.get_build_order(NON_EXISTENT_UUID, PRODUCTION_PLANNER)


def _read_absent_engine_unit(scenario):
    return api_client.get_engine_unit(NON_EXISTENT_UUID, QUALITY_ENGINEER)


def _record_absent_line_audit(scenario):
    return api_client.record_line_audit(
        NON_EXISTENT_UUID, record_line_audit_payload(), COMPLIANCE_OFFICER
    )


def _read_absent_service_part(scenario):
    return api_client.get_service_part(NON_EXISTENT_UUID, CHANNEL_PARTNER)


def _declare_family_without_family_code(scenario):
    payload = create_certification_family_payload()
    payload.pop("family_code")
    return api_client.create_certification_family(payload, CERTIFICATION_ENGINEER)


def _receive_lot_without_lot_quantity(scenario):
    payload = create_component_lot_payload(
        scenario.suppliers["carburetor"]["id"], lot_code="CB-009"
    )
    payload.pop("lot_quantity")
    return api_client.create_component_lot(payload, QUALITY_ENGINEER)


def _schedule_durability_run_without_version_guard(scenario):
    payload = create_durability_test_payload(
        scenario.family_id, scenario.platform_id, family_version(scenario.family_id)
    )
    payload.pop("expected_certification_family_version")
    return api_client.create_durability_test(payload, CERTIFICATION_ENGINEER)


def _stage_unit_without_serial_number(scenario):
    payload = create_engine_unit_payload(
        NON_EXISTENT_UUID,
        NON_EXISTENT_UUID,
        NON_EXISTENT_UUID,
        NON_EXISTENT_UUID,
    )
    payload.pop("serial_number")
    return api_client.create_engine_unit(payload, QUALITY_ENGINEER)


def _create_model_with_unknown_product_line(scenario):
    return api_client.create_product_model(
        create_product_model_payload(
            scenario.platform_id, model_code="XX-BAD-LINE", product_line="TRACTOR"
        ),
        PLANT_ADMIN,
    )


def _declare_family_with_model_year_above_the_range(scenario):
    return api_client.create_certification_family(
        create_certification_family_payload(
            family_code="2040-EPA-BAD", model_year=2040
        ),
        CERTIFICATION_ENGINEER,
    )


def _create_line_with_changeover_gap_above_the_range(scenario):
    return api_client.create_assembly_line(
        create_assembly_line_payload(
            line_code="L-BAD-GAP",
            supported_product_lines=["WALK_MOWER"],
            changeover_gap_weeks=7,
        ),
        PLANT_ADMIN,
    )


def _list_component_lots_beyond_the_pagination_maximum(scenario):
    return api_client.list_component_lots(
        QUALITY_ENGINEER, params={"limit": 101, "offset": 0}
    )


def _create_platform_with_a_decreasing_speed_window(scenario):
    return api_client.create_engine_platform(
        create_engine_platform_payload(
            scenario.family_id,
            platform_code="208-REV",
            hot_test_min_rpm=3600,
            hot_test_max_rpm=3200,
        ),
        PLANT_ADMIN,
    )


class TestPlantWideCreationWalk:
    """One chain from an empty database through every created resource."""

    def test_creation_walk_from_an_empty_database_reaches_every_entity(
        self, canonical_clock
    ):
        """PRD §4: "Operations that mint a new resource — declaring a certification family, creating a platform or model, recording a safety certification, receiving a component lot, opening a machining run, creating an assembly line, planning a build order, scheduling a durability run or a line audit, staging an engine unit, creating a service part, raising a parts request — answer `201 Created`."

        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD §3.1: "A newly declared family opens in `status` `DRAFT` with `cumulative_audit_failures` at 0, and with `deterioration_factor`, `certified_emission_g_per_kwh`, `compliance_margin_pct`, `submitted_by_user_id`, `certified_by_user_id`, `certified_at` and `audit_hold_at` all empty."
        PRD §3.2: "On success the family moves `SUBMITTED → CERTIFIED`, `certified_by_user_id` records the certifying operator, `certified_at` is stamped from the clock, and every platform of the family has its posture recomputed to `OPEN`."
        PRD §3.3: "On success the model moves to `RELEASED` and `released_at` is stamped from the clock."
        PRD §3.4: "An acceptance sets `accepted_qty` to `lot_quantity` minus `defects_found`, sets `remaining_qty` equal to that `accepted_qty`, writes the lot's own `defect_ppm`, records the inspecting operator as `inspected_by_user_id`, adds 1 to the supplier's `inspected_lot_count`, adds 1 to the supplier's `consecutive_accepted_lots`, and recomputes the supplier's `rolling_defect_ppm`."
        PRD §3.5: "Clearing the gate moves the run to `CLOSED`, and only a `CLOSED` run may supply the critical component of an engine unit."
        PRD §3.6: "`total_committed_cents` is `build_value_cents` plus `carry_cost_cents`."
        PRD §3.7: "The unit reaches the terminal `RELEASED` build state with `released_at` stamped from the clock, the order's `built_quantity` rises by 1 while `staged_quantity` falls by 1, and the unit joins the order's allocation pool."
        PRD §3.8: "Its `required_sample_size` is the larger of 2 units and two percent of the order's `built_quantity` rounded **up** to a whole unit, and it is likewise frozen — later releases on the order do not enlarge it."
        PRD §3.9: "The server derives `commitment_expires_year` as `last_production_year` plus `committed_availability_years`, and the part opens in `status` `ACTIVE` with `superseded_by_part_id` empty, `filled_request_count`, `substituted_request_count` and `backordered_request_count` all 0, and `fill_rate_pct` empty."
        PRD §3.9: "A request that is `FILLED` or `SUBSTITUTED` gets `promised_ship_date` equal to the clock date plus the lead time its channel earns — `dealer_lead_time_days` for a `DEALER` request and `mass_retail_lead_time_days` for a `MASS_RETAIL` request, read from the part the pieces actually ship from."

        Design: Corner/entities/creation_walk_from_empty_db_covers_all_fourteen_entities
        """
        family_response = api_client.create_certification_family(
            create_certification_family_payload(), CERTIFICATION_ENGINEER
        )
        family = validate_success(family_response, 201)
        family_body = family_response.json()
        assert family_body["response_type"] == "object"
        assert_envelope_meta(family_body)
        assert_certification_family(family)
        assert family["status"] == "DRAFT"

        platform = build_engine_platform(family["id"])
        run = schedule_durability_run(family["id"], platform["id"])
        completed_run = complete_durability_run(run["id"])
        submit_family(family["id"])
        certified_family = certify_family(family["id"])

        model = build_product_model(platform["id"])
        certification = build_safety_certification(model["id"])
        released_model = release_product_model(model["id"])

        scenario = PlantScenario(
            family=certified_family,
            platform=read_platform(platform["id"]),
            model=released_model,
            line=build_assembly_line(),
        )
        build_supply_base(scenario)
        scenario.machining_run = build_closed_machining_run(
            scenario.platform_id, scenario.casting_lot_id
        )
        order = plan_build_order(scenario.model_id, scenario.line_id)
        scenario.build_order = release_build_order(order["id"])

        unit = stage_engine_unit(scenario, "SN-0001")
        record_torque(unit["id"])
        hot_test_unit(unit["id"])
        released_unit = release_engine_unit(unit["id"])

        audit = schedule_line_audit(scenario.build_order_id, audit_week="2026-09-14")
        part = build_service_part(scenario.platform_id)
        request = raise_parts_request(part["id"])

        assert certified_family["status"] == "CERTIFIED"
        assert certified_family["deterioration_factor"] == pytest.approx(1.2800, abs=0.0001)
        assert certified_family["certified_emission_g_per_kwh"] == pytest.approx(5.12, abs=0.01)
        assert certified_family["compliance_margin_pct"] == pytest.approx(36.00, abs=0.01)
        assert certified_family["cumulative_audit_failures"] == 0

        assert scenario.platform["certification_posture"] == "OPEN"

        assert completed_run["status"] == "COMPLETED"
        assert completed_run["computed_deterioration_factor"] == pytest.approx(1.2800, abs=0.0001)
        assert completed_run["extrapolated"] is False

        assert released_model["status"] == "RELEASED"
        assert certification["result"] == "PASSED"

        assert scenario.line["status"] == "RUNNING"
        scorecard = validate_success(
            api_client.get_supplier_scorecard(
                scenario.suppliers["carburetor"]["id"], PLANT_ADMIN
            )
        )
        assert scorecard["approval_status"] == "APPROVED"
        assert scorecard["incoming_inspection_level"] == "NORMAL"

        carburetor_lot = scenario.lots["carburetor"]
        assert carburetor_lot["status"] == "ACCEPTED"
        assert carburetor_lot["sample_size"] == 40
        assert carburetor_lot["acceptance_number"] == 4
        assert carburetor_lot["accepted_qty"] == 800
        assert scenario.lots["casting"]["acceptance_number"] == 0

        assert scenario.machining_run["status"] == "CLOSED"

        final_order = scenario.refresh_build_order()
        assert final_order["status"] == "IN_PRODUCTION"
        assert final_order["carry_weeks"] == 24
        assert final_order["carry_rate"] == pytest.approx(0.0040, abs=0.0001)
        assert final_order["carry_cost_cents"] == 12096
        assert final_order["total_committed_cents"] == 138096
        assert final_order["built_quantity"] == 1

        assert released_unit["build_state"] == "RELEASED"
        assert released_unit["conformance_state"] == "CONFORMING"
        assert is_iso8601_timestamp(released_unit["released_at"])
        assert released_unit["released_at"].startswith("2026-08-03")

        assert audit["status"] == "SCHEDULED"
        assert audit["required_sample_size"] == 2

        assert_service_part(part)
        assert part["status"] == "ACTIVE"
        assert part["commitment_expires_year"] == 2037
        assert read_service_part(part["id"])["on_hand_qty"] == 4

        assert request["status"] == "FILLED"
        assert request["promised_ship_date"] == "2026-08-05"
        assert request["requester_user_id"] == CHANNEL_PARTNER["X-User-ID"]


class TestSingleResourceRetrieval:
    """A read returns the stored row and changes nothing."""

    def test_reading_a_platform_and_its_family_echoes_every_stored_field(
        self, family_with_platform
    ):
        """PRD §2.5: "Every resource the API creates carries an `id`: a server-minted UUID with no type prefix."

        PRD §2.7: "An `EnginePlatform` does not hold an independent regulatory state of its own: its `certification_posture` is a pure projection of the owning family's `status`, recomputed inside the very same request that changes that status."
        PRD §3.1: "The new platform's `certification_posture` is initialised immediately by the projection in §2.7 from the owning family's current status — so a platform created under a `DRAFT` family opens at `PENDING`, and one created under a family already in `DURABILITY_TESTING` opens at `RESTRICTED`."
        PRD §3.1: "A newly declared family opens in `status` `DRAFT` with `cumulative_audit_failures` at 0, and with `deterioration_factor`, `certified_emission_g_per_kwh`, `compliance_margin_pct`, `submitted_by_user_id`, `certified_by_user_id`, `certified_at` and `audit_hold_at` all empty."

        Design: Corner/entities/retrieval_returns_the_stored_platform_and_family_rows
        """
        scenario = family_with_platform

        platform_response = api_client.get_engine_platform(
            scenario.platform_id, QUALITY_ENGINEER
        )
        platform = validate_success(platform_response, 200)
        platform_body = platform_response.json()
        assert platform_body["response_type"] == "object"
        assert_envelope_meta(platform_body)
        assert_engine_platform(platform)

        assert platform["platform_code"] == "208SS"
        assert platform["displacement_cc"] == 208
        assert platform["torque_spec_nm"] == pytest.approx(22.0, abs=0.01)
        assert platform["torque_tolerance_pct"] == pytest.approx(0.05, abs=0.01)
        assert platform["required_fastener_count"] == 4
        assert platform["hot_test_min_rpm"] == 3200
        assert platform["hot_test_max_rpm"] == 3600
        assert platform["certification_family_id"] == scenario.family_id
        assert platform["certification_posture"] == "PENDING"
        assert is_valid_uuid(platform["id"])

        family_response = api_client.get_certification_family(
            scenario.family_id, QUALITY_ENGINEER
        )
        family = validate_success(family_response, 200)
        family_body = family_response.json()
        assert family_body["response_type"] == "object"
        assert_envelope_meta(family_body)
        assert family["family_code"] == "2027-EPA-208SS"
        assert family["model_year"] == 2027
        assert family["emission_standard"] == "EPA_PHASE3"
        assert family["declared_baseline_emission_g_per_kwh"] == pytest.approx(4.00, abs=0.01)
        assert family["deterioration_factor"] is None
        assert family["certified_emission_g_per_kwh"] is None

        second_read = validate_success(
            api_client.get_engine_platform(scenario.platform_id, PRODUCTION_PLANNER), 200
        )
        assert second_read["version"] == platform["version"]
        assert second_read["updated_at"] == platform["updated_at"]


class TestCollectionPagination:
    """Windowed reads report the filtered population, not the page."""

    def test_component_lot_listing_windows_the_filtered_population(self, canonical_clock):
        """PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10, has a minimum of 1 and a maximum of 100."

        PRD §2.3: "`offset` is the number of rows to skip and defaults to 0, with a minimum of 0."
        PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope, where `total_count` is the number of rows matching the request's filters before pagination is applied and `has_more` indicates whether rows remain beyond the returned page."
        PRD §2.3: "Unless a particular endpoint states otherwise, list results are ordered by `created_at` ascending."
        PRD §3.4: "At `NORMAL` it is the larger of 8 pieces and five percent of `lot_quantity` rounded up."

        Design: Corner/entities/listing_pagination_reports_total_count_and_has_more
        """
        carburetor_supplier = build_supplier(
            supplier_code="SUP-CARB",
            name="Carburetion Partners",
            component_category="CARBURETOR",
        )
        ignition_supplier = build_supplier(
            supplier_code="SUP-IGN",
            name="Ignition Systems Co",
            component_category="IGNITION",
        )
        first_lot = receive_component_lot(
            carburetor_supplier["id"], lot_code="CB-001", lot_quantity=800
        )
        second_lot = receive_component_lot(
            carburetor_supplier["id"], lot_code="CB-003", lot_quantity=400
        )
        third_lot = receive_component_lot(
            carburetor_supplier["id"], lot_code="CB-004", lot_quantity=200
        )
        receive_component_lot(
            ignition_supplier["id"], lot_code="IG-001", lot_quantity=800
        )

        first_page_response = api_client.list_component_lots(
            QUALITY_ENGINEER,
            params={"supplier_id": carburetor_supplier["id"], "limit": 2, "offset": 0},
        )
        first_rows, first_meta = validate_paginated(first_page_response)
        assert first_page_response.json()["response_type"] == "array"
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert len(first_rows) == 2
        assert first_rows[0]["id"] == first_lot["id"]
        assert first_rows[1]["id"] == second_lot["id"]

        second_rows, second_meta = validate_paginated(
            api_client.list_component_lots(
                QUALITY_ENGINEER,
                params={
                    "supplier_id": carburetor_supplier["id"],
                    "limit": 2,
                    "offset": 2,
                },
            )
        )
        assert second_meta["limit"] == 2
        assert second_meta["offset"] == 2
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert len(second_rows) == 1
        assert second_rows[0]["id"] == third_lot["id"]

        all_rows, all_meta = validate_paginated(
            api_client.list_component_lots(QUALITY_ENGINEER)
        )
        assert all_meta["limit"] == 10
        assert all_meta["offset"] == 0
        assert all_meta["total_count"] == 4
        assert all_meta["has_more"] is False
        assert len(all_rows) == 4

        assert second_lot["sample_size"] == 20
        assert third_lot["sample_size"] == 10


class TestAbsentReferences:
    """Each existence rule answers with its own identifier."""

    @pytest.mark.parametrize(
        "submit_request, expected_error_id",
        [
            (_read_absent_certification_family, "ERR_CERTIFICATION_FAMILY_NOT_FOUND"),
            (_read_absent_engine_platform, "ERR_ENGINE_PLATFORM_NOT_FOUND"),
            (_read_absent_durability_test, "ERR_DURABILITY_TEST_NOT_FOUND"),
            (_read_absent_product_model, "ERR_PRODUCT_MODEL_NOT_FOUND"),
            (_read_absent_supplier_scorecard, "ERR_SUPPLIER_NOT_FOUND"),
            (_read_absent_component_lot, "ERR_COMPONENT_LOT_NOT_FOUND"),
            (_read_absent_machining_run, "ERR_MACHINING_RUN_NOT_FOUND"),
            (_plan_order_against_absent_assembly_line, "ERR_ASSEMBLY_LINE_NOT_FOUND"),
            (_read_absent_build_order, "ERR_BUILD_ORDER_NOT_FOUND"),
            (_read_absent_engine_unit, "ERR_ENGINE_UNIT_NOT_FOUND"),
            (_record_absent_line_audit, "ERR_LINE_AUDIT_NOT_FOUND"),
            (_read_absent_service_part, "ERR_SERVICE_PART_NOT_FOUND"),
        ],
        ids=[
            "certification_family",
            "engine_platform",
            "durability_test",
            "product_model",
            "supplier",
            "component_lot",
            "machining_run",
            "assembly_line_body_reference",
            "build_order",
            "engine_unit",
            "line_audit",
            "service_part",
        ],
    )
    def test_absent_identifier_answers_its_own_not_found(
        self, family_with_platform, submit_request, expected_error_id
    ):
        """PRD §2.8: "**Existence**, in this order of entity: certification family (`ERR_CERTIFICATION_FAMILY_NOT_FOUND`), engine platform (`ERR_ENGINE_PLATFORM_NOT_FOUND`), durability test run (`ERR_DURABILITY_TEST_NOT_FOUND`), product model (`ERR_PRODUCT_MODEL_NOT_FOUND`), supplier (`ERR_SUPPLIER_NOT_FOUND`), component lot (`ERR_COMPONENT_LOT_NOT_FOUND`), machining run (`ERR_MACHINING_RUN_NOT_FOUND`), assembly line (`ERR_ASSEMBLY_LINE_NOT_FOUND`), build order (`ERR_BUILD_ORDER_NOT_FOUND`), engine unit (`ERR_ENGINE_UNIT_NOT_FOUND`), production line audit (`ERR_LINE_AUDIT_NOT_FOUND`), service part (`ERR_SERVICE_PART_NOT_FOUND`)."

        PRD §2.8: "Each covers both the path identifier and the corresponding body reference where one exists."

        Design: Corner/entities/nonexistent_ids_return_not_found
        """
        scenario = build_released_model(family_with_platform)
        scenario.line = build_assembly_line()

        response = submit_request(scenario)
        body = validate_error(response, expected_error_id, 404)
        assert response.json()["response_type"] == "error"
        assert body["message"]

    def test_a_rejected_body_reference_creates_no_build_order(self, family_with_platform):
        """PRD §2.8: "**Existence**, in this order of entity: certification family (`ERR_CERTIFICATION_FAMILY_NOT_FOUND`), engine platform (`ERR_ENGINE_PLATFORM_NOT_FOUND`), durability test run (`ERR_DURABILITY_TEST_NOT_FOUND`), product model (`ERR_PRODUCT_MODEL_NOT_FOUND`), supplier (`ERR_SUPPLIER_NOT_FOUND`), component lot (`ERR_COMPONENT_LOT_NOT_FOUND`), machining run (`ERR_MACHINING_RUN_NOT_FOUND`), assembly line (`ERR_ASSEMBLY_LINE_NOT_FOUND`), build order (`ERR_BUILD_ORDER_NOT_FOUND`), engine unit (`ERR_ENGINE_UNIT_NOT_FOUND`), production line audit (`ERR_LINE_AUDIT_NOT_FOUND`), service part (`ERR_SERVICE_PART_NOT_FOUND`)."

        Design: Corner/entities/nonexistent_ids_return_not_found
        """
        scenario = build_released_model(family_with_platform)
        scenario.line = build_assembly_line()

        validate_error(
            _plan_order_against_absent_assembly_line(scenario),
            "ERR_ASSEMBLY_LINE_NOT_FOUND",
            404,
        )

        rows, meta = validate_paginated(api_client.list_build_orders(PRODUCTION_PLANNER))
        assert meta["total_count"] == 0
        assert rows == []


class TestRequiredBodyFields:
    """A body missing a required field never reaches a later rule."""

    @pytest.mark.parametrize(
        "submit_request",
        [
            _declare_family_without_family_code,
            _receive_lot_without_lot_quantity,
            _schedule_durability_run_without_version_guard,
            _stage_unit_without_serial_number,
        ],
        ids=[
            "family_without_family_code",
            "lot_without_lot_quantity",
            "durability_run_without_version_guard",
            "engine_unit_without_serial_number",
        ],
    )
    def test_omitting_a_required_field_answers_invalid_request(
        self, family_with_platform, submit_request
    ):
        """PRD §2.8: "**Request shape.** Required body and query fields present, types correct, enum members recognised, numbers inside their declared ranges, dates in ISO form."

        PRD §2.8: "All of these answer `ERR_INVALID_REQUEST`."
        PRD §2.8: "The rules are evaluated in a fixed order and **the first violated rule decides the response** — later rules are never reported."

        Design: Corner/entities/missing_required_body_fields_return_invalid_request
        """
        scenario = family_with_platform
        scenario.suppliers = {
            "carburetor": build_supplier(
                supplier_code="SUP-CARB",
                name="Carburetion Partners",
                component_category="CARBURETOR",
            )
        }

        validate_error(submit_request(scenario), "ERR_INVALID_REQUEST", 400)

    def test_a_malformed_lot_body_writes_no_component_lot_row(self, family_with_platform):
        """PRD §2.8: "**Request shape.** Required body and query fields present, types correct, enum members recognised, numbers inside their declared ranges, dates in ISO form."

        PRD §2.8: "All of these answer `ERR_INVALID_REQUEST`."

        Design: Corner/entities/missing_required_body_fields_return_invalid_request
        """
        scenario = family_with_platform
        scenario.suppliers = {
            "carburetor": build_supplier(
                supplier_code="SUP-CARB",
                name="Carburetion Partners",
                component_category="CARBURETOR",
            )
        }

        validate_error(
            _receive_lot_without_lot_quantity(scenario), "ERR_INVALID_REQUEST", 400
        )

        rows, meta = validate_paginated(api_client.list_component_lots(QUALITY_ENGINEER))
        assert meta["total_count"] == 0
        assert rows == []


class TestDeclaredDefaults:
    """Omitted optional inputs take the values the specification declares."""

    def test_assembly_line_defaults_its_changeover_gap_and_status(
        self, family_with_platform
    ):
        """PRD §3.6: "A `PlantAdmin` creates one with a `line_code` of 1 to 20 characters unique across lines, a non-empty `supported_product_lines` array drawn from `WALK_MOWER`, `RIDING_MOWER`, `SNOW_THROWER` and `GENERATOR`, a `weekly_capacity_units` between 1 and 100000 stating how many units the line can build in one production week, an optional `changeover_gap_weeks` between 0 and 4 that defaults to 1, and an optional `status` that defaults to `RUNNING` and may otherwise be `DOWN`."

        Design: Corner/entities/omitted_optional_fields_take_declared_defaults
        """
        payload = create_assembly_line_payload(
            line_code="L-DEFAULTS",
            supported_product_lines=["GENERATOR"],
            weekly_capacity_units=250,
        )
        payload.pop("changeover_gap_weeks")
        payload.pop("status")

        line = validate_success(
            api_client.create_assembly_line(payload, PLANT_ADMIN), 201
        )
        assert line["changeover_gap_weeks"] == 1
        assert line["status"] == "RUNNING"

    def test_service_part_defaults_its_channel_lead_times(self, family_with_platform):
        """PRD §3.9: "Stock and promises come with it: a non-negative `on_hand_qty` of pieces available to the network, a `committed_availability_years` of at least 7 years of availability owed after the part's last production, a `last_production_year` between 2020 and 2060, an optional `dealer_lead_time_days` between 1 and 30 defaulting to 2, and an optional `mass_retail_lead_time_days` between 1 and 60 defaulting to 5."

        PRD §3.9: "The server derives `commitment_expires_year` as `last_production_year` plus `committed_availability_years`, and the part opens in `status` `ACTIVE` with `superseded_by_part_id` empty, `filled_request_count`, `substituted_request_count` and `backordered_request_count` all 0, and `fill_rate_pct` empty."
        PRD §3.9: "A request that is `FILLED` or `SUBSTITUTED` gets `promised_ship_date` equal to the clock date plus the lead time its channel earns — `dealer_lead_time_days` for a `DEALER` request and `mass_retail_lead_time_days` for a `MASS_RETAIL` request, read from the part the pieces actually ship from."
        PRD §3.9: "Otherwise it is the served count divided by the total, multiplied by 100, rounded half up to 2 decimal places."

        Design: Corner/entities/omitted_optional_fields_take_declared_defaults
        """
        payload = create_service_part_payload(
            family_with_platform.platform_id,
            part_number="PN-FILTER-DEF",
            category="FILTER_KIT",
            on_hand_qty=4,
            committed_availability_years=7,
            last_production_year=2027,
        )
        payload.pop("dealer_lead_time_days")
        payload.pop("mass_retail_lead_time_days")

        part = validate_success(
            api_client.create_service_part(payload, PLANT_ADMIN), 201
        )
        assert part["dealer_lead_time_days"] == 2
        assert part["mass_retail_lead_time_days"] == 5
        assert part["commitment_expires_year"] == 2034
        assert part["status"] == "ACTIVE"

        request = validate_success(
            api_client.create_parts_request(
                create_parts_request_payload(part["id"], channel="MASS_RETAIL"),
                CHANNEL_PARTNER,
            ),
            201,
        )
        assert request["status"] == "FILLED"
        assert request["promised_ship_date"] == "2026-08-08"

        stocked = read_service_part(part["id"])
        assert stocked["on_hand_qty"] == 3
        assert stocked["fill_rate_pct"] == pytest.approx(100.00, abs=0.01)


class TestComputedAndSystemFields:
    """Derived and system-managed fields ignore whatever the client sends."""

    def test_smuggled_family_status_and_version_are_ignored(self, canonical_clock):
        """PRD §2.10: "No other endpoint takes a version field, and no other endpoint performs a version check."

        PRD §2.10: "Where an endpoint is not named in this subsection, submitting a version value is simply not part of its contract."
        PRD §2.5: "`version` is an integer that starts at 1 when the row is created and increments by 1 on every mutation of that row — including mutations the server performs on its own initiative, such as a derived counter being recomputed or a cascade imposing a hold."
        PRD §3.1: "A newly declared family opens in `status` `DRAFT` with `cumulative_audit_failures` at 0, and with `deterioration_factor`, `certified_emission_g_per_kwh`, `compliance_margin_pct`, `submitted_by_user_id`, `certified_by_user_id`, `certified_at` and `audit_hold_at` all empty."

        Design: Corner/entities/computed_and_system_fields_client_input_ignored
        """
        family = validate_success(
            api_client.create_certification_family(
                create_certification_family_payload(
                    family_code="2027-EPA-INPUT",
                    deterioration_factor=1.0000,
                    status="CERTIFIED",
                    version=99,
                ),
                CERTIFICATION_ENGINEER,
            ),
            201,
        )

        assert family["status"] == "DRAFT"
        assert family["deterioration_factor"] is None
        assert family["version"] == 1
        assert family["certified_emission_g_per_kwh"] is None
        assert family["compliance_margin_pct"] is None
        assert family["submitted_by_user_id"] is None

    def test_smuggled_lot_sampling_plan_and_status_are_recomputed(self, canonical_clock):
        """PRD §3.4: "Receipt is also where the lot's sampling plan is frozen."

        PRD §3.4: "The supplier's current `incoming_inspection_level` is snapshotted onto the lot as `inspection_level_at_receipt`, and both `sample_size` and `acceptance_number` are computed from that snapshot."
        PRD §3.4: "At `NORMAL` it is the larger of 8 pieces and five percent of `lot_quantity` rounded up."
        PRD §3.4: "The acceptance number — the maximum number of defective pieces in the sample that still permits acceptance — is 0 for a `CRITICAL` supplier, and for a `MAJOR` supplier it is ten percent of the resulting sample size rounded **down** to a whole number."
        PRD §3.4: "On receipt the lot opens in `status` `RECEIVED` with `component_category` copied from the supplier, `accepted_qty`, `consumed_qty` and `remaining_qty` at 0, `defects_found` and `defect_ppm` empty and `deviation_flag` false."
        PRD §2.5: "Every resource the API creates carries an `id`: a server-minted UUID with no type prefix."
        PRD §2.5: "Clients never supply an `id`."

        Design: Corner/entities/computed_and_system_fields_client_input_ignored
        """
        supplier = build_supplier(
            supplier_code="SUP-CARB",
            name="Carburetion Partners",
            component_category="CARBURETOR",
        )

        lot = validate_success(
            api_client.create_component_lot(
                create_component_lot_payload(
                    supplier["id"],
                    lot_code="CB-INPUT",
                    lot_quantity=800,
                    sample_size=1,
                    acceptance_number=99,
                    status="ACCEPTED",
                    accepted_qty=800,
                ),
                QUALITY_ENGINEER,
            ),
            201,
        )

        assert lot["status"] == "RECEIVED"
        assert lot["sample_size"] == 40
        assert lot["acceptance_number"] == 4
        assert lot["accepted_qty"] == 0
        assert lot["consumed_qty"] == 0
        assert lot["remaining_qty"] == 0
        assert lot["deviation_flag"] is False
        assert_component_lot(lot)
        assert is_valid_uuid(lot["id"])
        assert lot["id"] != supplier["id"]
        assert is_iso8601_timestamp(lot["created_at"])
        assert is_iso8601_timestamp(lot["updated_at"])
        assert lot["created_at"].startswith("2026-08-03")


class TestSafetyCertificationImmutability:
    """The bench-test record is appended to, never amended."""

    def test_bench_test_rows_carry_no_version_and_a_correction_is_appended(
        self, family_with_platform
    ):
        """PRD §2.5: "A `SafetyCertification` is an immutable bench-test record: once written it is never modified, and no update endpoint exists for it."

        PRD §2.5: "Such a record therefore carries only `id` and `created_at`; both `updated_at` and `version` are absent from its representation."
        PRD §3.3: "A measured blade stop time passes when it is absent altogether or when it is at most 3000 milliseconds; a measured operator-presence response — which for a generator is the carbon-monoxide shutoff response — passes when it is at most 1000 milliseconds."
        PRD §3.3: "The `result` is `PASSED` when both checks pass and `FAILED` otherwise."
        PRD §3.3: "The recording operator is retained as `tested_by_user_id`, and the row is immutable thereafter — as noted in §2.5 it therefore carries no `updated_at` and no `version`, and there is no way to amend it."
        PRD §3.3: "A model's certifications can be listed from the model, newest `tested_on` first."
        PRD §3.3: "The release looks for the model's **latest passing** safety certification — the rows whose `result` is `PASSED`, ordered by `tested_on` descending and, for ties on that date, by `created_at` descending, taking the first."

        Design: Corner/entities/safety_certification_is_immutable_and_versionless
        """
        model = build_product_model(family_with_platform.platform_id)
        failed_certification = build_safety_certification(
            model["id"],
            blade_stop_time_ms=3200,
            opc_stop_time_ms=900,
            tested_on="2026-06-01",
            expires_on="2027-06-01",
        )
        passed_certification = build_safety_certification(model["id"])

        rows, meta = validate_paginated(
            api_client.list_model_safety_certifications(
                model["id"], COMPLIANCE_OFFICER, params={"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 2
        for row in rows:
            assert "version" not in row
            assert "updated_at" not in row
        assert rows[0]["tested_on"] == "2026-07-15"
        assert rows[1]["tested_on"] == "2026-06-01"

        assert failed_certification["result"] == "FAILED"
        assert passed_certification["result"] == "PASSED"
        assert passed_certification["blade_stop_time_ms"] == 2600
        assert passed_certification["opc_stop_time_ms"] == 900
        assert_safety_certification(failed_certification)
        assert_safety_certification(passed_certification)

        appended_view = [row for row in rows if row["id"] == failed_certification["id"]]
        assert appended_view and appended_view[0] == failed_certification

        released = release_product_model(model["id"])
        assert released["status"] == "RELEASED"

        assert failed_certification["tested_by_user_id"] == COMPLIANCE_OFFICER["X-User-ID"]
        assert passed_certification["tested_by_user_id"] == COMPLIANCE_OFFICER["X-User-ID"]


class TestClosedEnumsAndDeclaredRanges:
    """Unknown members and out-of-range numbers never reach a state machine."""

    @pytest.mark.parametrize(
        "submit_request",
        [
            _create_model_with_unknown_product_line,
            _declare_family_with_model_year_above_the_range,
            _create_line_with_changeover_gap_above_the_range,
            _list_component_lots_beyond_the_pagination_maximum,
            _create_platform_with_a_decreasing_speed_window,
        ],
        ids=[
            "unknown_product_line_member",
            "model_year_above_the_range",
            "changeover_gap_above_the_range",
            "pagination_limit_above_the_maximum",
            "decreasing_hot_test_speed_window",
        ],
    )
    def test_out_of_contract_input_answers_invalid_request(
        self, family_with_platform, submit_request
    ):
        """PRD §2.8: "**Request shape.** Required body and query fields present, types correct, enum members recognised, numbers inside their declared ranges, dates in ISO form."

        PRD §2.8: "All of these answer `ERR_INVALID_REQUEST`."
        PRD §2.3: "A `limit` outside the range 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.3: "Its `product_line` is one of `WALK_MOWER`, `RIDING_MOWER`, `SNOW_THROWER` or `GENERATOR`, and that single choice determines the safety standard the model must be tested under, the operator-presence control it must carry, whether it may have a blade brake at all, and which calendar week counts as the start of its selling season."
        PRD §3.1: "The declaration carries a `family_code` of 1 to 40 characters drawn from uppercase letters, digits and hyphens and unique across all families; a `model_year` between 2026 and 2035; an `emission_standard` of either `EPA_PHASE3` or `CARB_2024`; a displacement band given as `displacement_min_cc` and `displacement_max_cc`, each between 50 and 1000 with the upper bound at least the lower; a `durability_hours` emission durability period that must be exactly one of 125, 250, 500 or 1000 hours; a `family_emission_limit_g_per_kwh` above zero at 2 decimal places, which is the regulatory ceiling the family will be held to; and a `declared_baseline_emission_g_per_kwh`, also above zero at 2 decimal places, which is the low-hour production baseline that deterioration will later be applied to."
        PRD §3.6: "A `PlantAdmin` creates one with a `line_code` of 1 to 20 characters unique across lines, a non-empty `supported_product_lines` array drawn from `WALK_MOWER`, `RIDING_MOWER`, `SNOW_THROWER` and `GENERATOR`, a `weekly_capacity_units` between 1 and 100000 stating how many units the line can build in one production week, an optional `changeover_gap_weeks` between 0 and 4 that defaults to 1, and an optional `status` that defaults to `RUNNING` and may otherwise be `DOWN`."

        Design: Corner/entities/unknown_enum_members_and_out_of_range_numbers_are_rejected
        """
        validate_error(
            submit_request(family_with_platform), "ERR_INVALID_REQUEST", 400
        )

    def test_rejected_platform_and_model_bodies_write_no_rows(self, family_with_platform):
        """PRD §2.8: "**Request shape.** Required body and query fields present, types correct, enum members recognised, numbers inside their declared ranges, dates in ISO form."

        PRD §2.8: "All of these answer `ERR_INVALID_REQUEST`."

        Design: Corner/entities/unknown_enum_members_and_out_of_range_numbers_are_rejected
        """
        scenario = family_with_platform

        validate_error(
            _create_model_with_unknown_product_line(scenario),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            _create_platform_with_a_decreasing_speed_window(scenario),
            "ERR_INVALID_REQUEST",
            400,
        )

        model_rows, model_meta = validate_paginated(
            api_client.list_platform_product_models(scenario.platform_id, PLANT_ADMIN)
        )
        assert model_meta["total_count"] == 0
        assert model_rows == []

        platform_rows, platform_meta = validate_paginated(
            api_client.list_family_engine_platforms(
                scenario.family_id, CERTIFICATION_ENGINEER
            )
        )
        assert platform_meta["total_count"] == 1
        assert platform_rows[0]["id"] == scenario.platform_id


class TestPlatformDisplacementWindow:
    """A platform must sit inside its family's declared displacement band."""

    def test_displacement_outside_the_family_band_is_refused_while_edges_are_accepted(
        self, draft_family
    ):
        """PRD §3.1: "A platform carries a `platform_code` of 1 to 30 characters, unique across all platforms; a `displacement_cc` between 50 and 1000 which must fall inside the owning family's declared band inclusively — a displacement below `displacement_min_cc` or above `displacement_max_cc` is refused with `ERR_DISPLACEMENT_OUT_OF_FAMILY`; a nominal fastener torque `torque_spec_nm` above zero at 1 decimal place; a fractional `torque_tolerance_pct` between 0.01 and 0.20 at 2 decimal places, so a value of 0.05 means a band of plus or minus five percent; a `required_fastener_count` between 1 and 12, being the number of torque readings each engine on that platform must report; and a governed-speed window for the hot test given as `hot_test_min_rpm` between 500 and 8000 and `hot_test_max_rpm` strictly above it and at most 8000, both bounds inclusive when the window is applied."

        PRD §3.1: "The new platform's `certification_posture` is initialised immediately by the projection in §2.7 from the owning family's current status — so a platform created under a `DRAFT` family opens at `PENDING`, and one created under a family already in `DURABILITY_TESTING` opens at `RESTRICTED`."

        Design: Corner/entities/platform_displacement_outside_the_family_window_rejected
        """
        family_id = draft_family["id"]

        validate_error(
            api_client.create_engine_platform(
                create_engine_platform_payload(
                    family_id, platform_code="250XX", displacement_cc=250
                ),
                PLANT_ADMIN,
            ),
            "ERR_DISPLACEMENT_OUT_OF_FAMILY",
            422,
        )

        lower_edge = build_engine_platform(
            family_id,
            platform_code="190LO",
            displacement_cc=190,
            torque_spec_nm=20.0,
        )
        upper_edge = build_engine_platform(
            family_id,
            platform_code="224HI",
            displacement_cc=224,
            torque_spec_nm=24.0,
        )

        assert lower_edge["displacement_cc"] == 190
        assert upper_edge["displacement_cc"] == 224
        assert lower_edge["certification_posture"] == "PENDING"
        assert upper_edge["certification_posture"] == "PENDING"

        rows, meta = validate_paginated(
            api_client.list_family_engine_platforms(family_id, CERTIFICATION_ENGINEER)
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {lower_edge["id"], upper_edge["id"]}


class TestCrossFamilyGraphScoping:
    """Scoped listings return only their own subtree, and pairings are checked by value."""

    def test_two_families_keep_their_platforms_models_and_runs_apart(
        self, family_with_platform
    ):
        """PRD §3.1: "Families and platforms are both readable individually, and the platforms of a family can be listed from the family, as can the finished-goods models of a platform."

        PRD §3.2: "The named platform must belong to the named family; if the platform's owning family is a different family, the request is refused with `ERR_PLATFORM_MISMATCH`."
        PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope, where `total_count` is the number of rows matching the request's filters before pagination is applied and `has_more` indicates whether rows remain beyond the returned page."

        Design: Corner/entities/graph_topology_cross_reference_scoping_across_two_families
        """
        scenario = family_with_platform
        model = build_product_model(scenario.platform_id)

        other_family = build_certification_family(
            family_code="2027-CARB-190",
            emission_standard="CARB_2024",
            displacement_min_cc=180,
            displacement_max_cc=200,
        )
        other_platform = build_engine_platform(
            other_family["id"],
            platform_code="190CB",
            displacement_cc=190,
            torque_spec_nm=20.0,
            hot_test_min_rpm=3100,
            hot_test_max_rpm=3500,
        )

        own_platforms, own_meta = validate_paginated(
            api_client.list_family_engine_platforms(
                scenario.family_id,
                CERTIFICATION_ENGINEER,
                params={"limit": 10, "offset": 0},
            )
        )
        assert own_meta["total_count"] == 1
        assert [row["id"] for row in own_platforms] == [scenario.platform_id]

        other_models, other_models_meta = validate_paginated(
            api_client.list_platform_product_models(
                other_platform["id"], PLANT_ADMIN, params={"limit": 10, "offset": 0}
            )
        )
        assert other_models_meta["total_count"] == 0
        assert other_models_meta["has_more"] is False
        assert other_models == []

        own_models, own_models_meta = validate_paginated(
            api_client.list_platform_product_models(scenario.platform_id, PLANT_ADMIN)
        )
        assert own_models_meta["total_count"] == 1
        assert own_models[0]["id"] == model["id"]

        observed_version = family_version(scenario.family_id)
        validate_error(
            api_client.create_durability_test(
                create_durability_test_payload(
                    scenario.family_id, other_platform["id"], observed_version
                ),
                CERTIFICATION_ENGINEER,
            ),
            "ERR_PLATFORM_MISMATCH",
            409,
        )

        family_after = validate_success(
            api_client.get_certification_family(
                scenario.family_id, CERTIFICATION_ENGINEER
            ),
            200,
        )
        assert family_after["status"] == "DRAFT"
        assert family_after["version"] == observed_version

        runs, runs_meta = validate_paginated(
            api_client.list_durability_tests(
                CERTIFICATION_ENGINEER,
                params={"engine_platform_id": other_platform["id"]},
            )
        )
        assert runs_meta["total_count"] == 0
        assert runs == []
