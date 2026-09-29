"""One not-found identifier per collection, on the path and again in the request body."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
)

from test_helpers.factories import (
    build_auxiliary_system_payload,
    build_fire_pump_payload,
    build_hazard_area_payload,
    build_project_payload,
    build_record_clearance_payload,
    build_water_supply_evaluation_payload,
)
from test_helpers.fixtures import (
    ADMIN_HEADERS,
    build_evaluated_stage,
    build_project_stage,
    read_project,
)
from test_helpers.test_users import make_design_engineer_headers

GHOST = NON_EXISTENT_UUID


class TestPathParameterNotFound:
    def test_01_each_single_row_read_names_its_own_collection(self, client):
        """Every `{id}` path parameter resolves to an existing row, validated left to right
        along the path — the matching one of `ERR_PROJECT_NOT_FOUND`,
        `ERR_HAZARD_AREA_NOT_FOUND`, `ERR_CALCULATION_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`,
        `ERR_FIRE_PUMP_NOT_FOUND`, `ERR_AUXILIARY_SYSTEM_NOT_FOUND`,
        `ERR_SHOP_DRAWING_NOT_FOUND`, `ERR_TRADE_CLEARANCE_NOT_FOUND`,
        `ERR_SUBMITTAL_NOT_FOUND`, `ERR_REVIEW_COMMENT_NOT_FOUND`,
        `ERR_ACCEPTANCE_TEST_NOT_FOUND` (404).

        Design: Corner/errors/every_path_parameter_collection_has_its_own_not_found_error
        """
        build_project_stage(client)
        reads = [
            (client.get_project, "ERR_PROJECT_NOT_FOUND"),
            (client.get_hazard_area, "ERR_HAZARD_AREA_NOT_FOUND"),
            (client.get_hydraulic_calculation, "ERR_CALCULATION_NOT_FOUND"),
            (client.get_water_supply_evaluation, "ERR_EVALUATION_NOT_FOUND"),
            (client.get_fire_pump, "ERR_FIRE_PUMP_NOT_FOUND"),
            (client.get_auxiliary_system, "ERR_AUXILIARY_SYSTEM_NOT_FOUND"),
            (client.get_shop_drawing, "ERR_SHOP_DRAWING_NOT_FOUND"),
            (client.get_submittal, "ERR_SUBMITTAL_NOT_FOUND"),
            (client.get_review_comment, "ERR_REVIEW_COMMENT_NOT_FOUND"),
            (client.get_acceptance_test, "ERR_ACCEPTANCE_TEST_NOT_FOUND"),
        ]
        seen = set()
        for read, error_id in reads:
            # validate_error also proves the envelope carries a non-blank message.
            validate_error(read(GHOST, ADMIN_HEADERS), error_id, expected_status=404)
            seen.add(error_id)
        assert len(seen) == 10, "one shared ERR_NOT_FOUND would collapse these ten ids"

    def test_02_a_nested_list_validates_its_owner_before_listing(self, client):
        """Every `{id}` path parameter resolves to an existing row, validated left to right
        along the path ...

        Design: Corner/errors/every_path_parameter_collection_has_its_own_not_found_error
        """
        build_project_stage(client)
        validate_error(
            client.list_project_flow_tests(GHOST, ADMIN_HEADERS),
            "ERR_PROJECT_NOT_FOUND",
            expected_status=404,
        )
        # Not an empty page: the sheet that owns the collection has to exist first.
        validate_error(
            client.list_trade_clearances(GHOST, ADMIN_HEADERS),
            "ERR_SHOP_DRAWING_NOT_FOUND",
            expected_status=404,
        )

    def test_03_the_clearance_404_is_visible_only_through_its_action(self, client):
        """Every `{id}` path parameter resolves to an existing row, validated left to right
        along the path — the matching one of ... `ERR_TRADE_CLEARANCE_NOT_FOUND` ... (404).

        Design: Corner/errors/every_path_parameter_collection_has_its_own_not_found_error
        """
        ctx = build_project_stage(client)
        refused = client.record_trade_clearance(
            GHOST,
            build_record_clearance_payload(outcome="CLEARED", note="No such row"),
            make_design_engineer_headers(ctx["lead_id"]),
        )
        validate_error(refused, "ERR_TRADE_CLEARANCE_NOT_FOUND", expected_status=404)


GHOST_PROJECT = dict(
    project_number="FP-2699", building_name="Ghost Reference Tower",
    building_height_ft=30.0, underground_lead_in_loss_psi=4.0,
)


class TestBodyForeignKeyNotFound:
    def test_04_the_first_unknown_reference_in_declaration_order_answers(self, client):
        """Every foreign key supplied in the request body resolves to an existing row of its
        declared parent type, validated in the order the fields are listed for that endpoint —
        the matching one of `ERR_ENGINEER_NOT_FOUND`, `ERR_REVIEWER_NOT_FOUND` ...

        Design: Corner/errors/every_body_foreign_key_has_its_own_not_found_error
        """
        ctx = build_project_stage(client)
        both_unknown = client.create_project(
            build_project_payload(
                lead_engineer_id=GHOST, ahj_reviewer_id=GHOST, **GHOST_PROJECT
            ),
            ADMIN_HEADERS,
        )
        # lead_engineer_id is declared first, so the reviewer is never reached.
        validate_error(both_unknown, "ERR_ENGINEER_NOT_FOUND", expected_status=404)

        reviewer_only = client.create_project(
            build_project_payload(
                lead_engineer_id=ctx["lead_id"], ahj_reviewer_id=GHOST, **GHOST_PROJECT
            ),
            ADMIN_HEADERS,
        )
        validate_error(reviewer_only, "ERR_REVIEWER_NOT_FOUND", expected_status=404)

        rows, meta = validate_paginated(client.list_projects(ADMIN_HEADERS))
        assert meta["total_count"] == 1, "no ghost project was minted"
        assert [row["project_number"] for row in rows] == ["FP-2601"]

    def test_05_an_unknown_owner_or_parent_area_answers_before_any_domain_rule(self, client):
        """... `ERR_PROJECT_NOT_FOUND`, `ERR_HAZARD_AREA_NOT_FOUND` ... This applies to project
        creation, hazard area creation, flow test creation, water supply evaluation creation,
        hydraulic calculation creation, fire pump creation, auxiliary system creation ...

        Design: Corner/errors/every_body_foreign_key_has_its_own_not_found_error
        """
        ctx = build_evaluated_stage(client)
        engineer = make_design_engineer_headers(ctx["lead_id"])

        orphan_area = client.create_hazard_area(
            build_hazard_area_payload(
                project_id=GHOST, label="Orphan bay", hazard_class="ORDINARY_1",
                commodity_class="CLASS_III", storage_height_ft=8.0,
                ceiling_height_ft=12.0, area_sqft=1800.0, sprinkler_system_type="WET",
                ceiling_slope_pct=None, room_area_sqft=None,
                enclosure_rating_hours=None, room_has_unprotected_opening=None,
            ),
            engineer,
        )
        validate_error(orphan_area, "ERR_PROJECT_NOT_FOUND", expected_status=404)

        # Existence at priority 5 outranks the in-rack commodity check at priority 29.
        orphan_rack = client.create_auxiliary_system(
            build_auxiliary_system_payload(
                project_id=ctx["project_id"], system_type="IN_RACK",
                label="Orphan rack tier", hazard_area_id=GHOST, in_rack_head_count=10,
            ),
            engineer,
        )
        validate_error(orphan_rack, "ERR_HAZARD_AREA_NOT_FOUND", expected_status=404)

        rows, meta = validate_paginated(
            client.list_hazard_areas(ADMIN_HEADERS, params={"project_id": ctx["project_id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == ctx["hazard_area_id"]
        listed, aux_meta = validate_paginated(
            client.list_auxiliary_systems(
                ADMIN_HEADERS, params={"project_id": ctx["project_id"]}
            )
        )
        assert aux_meta["total_count"] == 1
        assert listed[0]["system_type"] == "STANDPIPE_CLASS_I"

    def test_06_the_supply_evaluation_body_separates_its_two_references(self, client):
        """... `ERR_FLOW_TEST_NOT_FOUND`, `ERR_CALCULATION_NOT_FOUND`,
        `ERR_EVALUATION_NOT_FOUND` ... This applies to project creation, hazard area
        creation, flow test creation, water supply evaluation creation ...

        Design: Corner/errors/every_body_foreign_key_has_its_own_not_found_error
        """
        ctx = build_evaluated_stage(client)
        engineer = make_design_engineer_headers(ctx["lead_id"])

        unknown_test = client.create_water_supply_evaluation(
            build_water_supply_evaluation_payload(
                project_id=ctx["project_id"],
                flow_test_id=GHOST,
                governing_hydraulic_calculation_id=ctx["calculation_id"],
            ),
            engineer,
        )
        validate_error(unknown_test, "ERR_FLOW_TEST_NOT_FOUND", expected_status=404)

        unknown_calculation = client.create_water_supply_evaluation(
            build_water_supply_evaluation_payload(
                project_id=ctx["project_id"],
                flow_test_id=ctx["flow_test_id"],
                governing_hydraulic_calculation_id=GHOST,
            ),
            engineer,
        )
        validate_error(unknown_calculation, "ERR_CALCULATION_NOT_FOUND", expected_status=404)

        rows, meta = validate_paginated(
            client.list_water_supply_evaluations(
                ADMIN_HEADERS, params={"project_id": ctx["project_id"]}
            )
        )
        assert meta["total_count"] == 2, "the preliminary and final evaluations, and no third"
        assert ctx["evaluation_id"] in {row["id"] for row in rows}

    def test_07_the_pump_reference_answers_before_its_own_version_pin(self, client):
        """Every foreign key supplied in the request body resolves to an existing row of its
        declared parent type ... `ERR_EVALUATION_NOT_FOUND` ... This applies to ... fire pump
        creation ...

        Design: Corner/errors/every_body_foreign_key_has_its_own_not_found_error
        """
        ctx = build_evaluated_stage(client)
        version_before = read_project(client, ctx["project_id"])["version"]

        # A live version pin: only the unknown evaluation can be at fault.
        refused = client.create_fire_pump(
            build_fire_pump_payload(
                project_id=ctx["project_id"],
                water_supply_evaluation_id=GHOST,
                expected_water_supply_evaluation_version=ctx["evaluation"]["version"],
                model_tag="PUMP-Z",
            ),
            make_design_engineer_headers(ctx["lead_id"]),
        )
        validate_error(refused, "ERR_EVALUATION_NOT_FOUND", expected_status=404)

        _, meta = validate_paginated(
            client.list_fire_pumps(ADMIN_HEADERS, params={"project_id": ctx["project_id"]})
        )
        assert meta["total_count"] == 0, "no pump row was minted by the refusal"
        assert read_project(client, ctx["project_id"])["version"] == version_before
