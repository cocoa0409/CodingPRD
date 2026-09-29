"""Requests that break two rules at once, and which rule the service reports."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
)

from test_helpers.factories import (
    build_hazard_area_payload,
    build_submittal_payload,
    build_water_supply_evaluation_payload,
)
from test_helpers.fixtures import (
    create_auxiliary_system,
    create_calculation,
    create_flow_test,
    create_hazard_area,
    read_project,
    build_project_stage,
)
from test_helpers.test_users import make_design_engineer_headers


def _draft_with_a_stale_pin(client):
    """A DRAFT calculation, then an auxiliary system that leaves the captured project
    version behind."""
    ctx = build_project_stage(client)
    ctx["stale_version"] = ctx["project"]["version"]
    area = create_hazard_area(client, ctx["project_id"], ctx["lead_id"])
    ctx["calculation"] = create_calculation(
        client, ctx["project_id"], area["id"], ctx["lead_id"]
    )
    create_auxiliary_system(client, ctx["project_id"], ctx["lead_id"])
    assert read_project(client, ctx["project_id"])["version"] > ctx["stale_version"]
    return ctx


def _lodge(client, ctx, calculation_ids, version):
    payload = build_submittal_payload(
        project_id=ctx["project_id"],
        included_calculation_ids=calculation_ids,
        expected_project_version=version,
    )
    return client.create_submittal(payload, make_design_engineer_headers(ctx["lead_id"]))


class TestBodyForeignKeyOutranksTheVersionPin:
    def test_01_an_unknown_calculation_in_the_body_answers_before_the_stale_pin(
        self, client
    ):
        """Every foreign key supplied in the request body resolves to an existing row of its
        declared parent type, validated in the order the fields are listed for that
        endpoint.

        Design: Difficulty/priority_pair_validation_conflict/body_fk_existence_outranks_stale_project_version_on_submittal_create
        """
        ctx = _draft_with_a_stale_pin(client)
        refused = _lodge(client, ctx, [NON_EXISTENT_UUID], ctx["stale_version"])
        validate_error(refused, "ERR_CALCULATION_NOT_FOUND", expected_status=404)

        rows, meta = validate_paginated(
            client.list_submittals(
                make_design_engineer_headers(ctx["lead_id"]),
                params={"project_id": ctx["project_id"]},
            )
        )
        assert meta["total_count"] == 0 and rows == []
        project = read_project(client, ctx["project_id"])
        assert project["submittal_cycle_count"] == 0
        assert project["status"] == "DESIGN"

    def test_02_a_real_calculation_with_the_same_pin_reaches_the_version_check(self, client):
        """When `expected_project_version` does not equal the project's current `version`,
        the request is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412).

        Design: Difficulty/priority_pair_validation_conflict/body_fk_existence_outranks_stale_project_version_on_submittal_create
        """
        ctx = _draft_with_a_stale_pin(client)
        # The calculation is only DRAFT, so the pin at priority 11 has to answer before
        # the seal-state rule further down the order.
        refused = _lodge(
            client, ctx, [ctx["calculation"]["id"]], ctx["stale_version"]
        )
        validate_error(refused, "ERR_STALE_PROJECT_VERSION", expected_status=412)

        _, meta = validate_paginated(
            client.list_submittals(
                make_design_engineer_headers(ctx["lead_id"]),
                params={"project_id": ctx["project_id"]},
            )
        )
        assert meta["total_count"] == 0
        assert read_project(client, ctx["project_id"])["submittal_cycle_count"] == 0


# 426 days before the 2026-08-01T00:00:00Z clock, so outside the 365-day window.
STALE_TESTED_AT = "2025-06-01T00:00:00.000Z"
FRESH_TESTED_AT = "2026-05-14T15:00:00.000Z"


def _two_hydrant_tests_and_an_empty_chain(client):
    ctx = build_project_stage(client)
    area = create_hazard_area(client, ctx["project_id"], ctx["lead_id"])
    ctx["calculation"] = create_calculation(
        client, ctx["project_id"], area["id"], ctx["lead_id"]
    )
    assert ctx["calculation"]["iteration_count"] == 0
    ctx["old_test"] = create_flow_test(
        client,
        ctx["project_id"],
        ctx["lead_id"],
        hydrant_tag="H-OLD",
        tested_at=STALE_TESTED_AT,
    )
    ctx["fresh_test"] = create_flow_test(
        client,
        ctx["project_id"],
        ctx["lead_id"],
        hydrant_tag="H-14",
        tested_at=FRESH_TESTED_AT,
    )
    return ctx


def _evaluate(client, ctx, flow_test_id):
    payload = build_water_supply_evaluation_payload(
        project_id=ctx["project_id"],
        flow_test_id=flow_test_id,
        governing_hydraulic_calculation_id=ctx["calculation"]["id"],
    )
    return client.create_water_supply_evaluation(
        payload, make_design_engineer_headers(ctx["lead_id"])
    )


class TestStaleHydrantTestOutranksTheEmptyChain:
    def test_03_the_out_of_date_hydrant_test_answers_before_the_empty_chain(self, client):
        """A flow test is accepted as evidence while its `tested_at` is no earlier than 365
        days before the current clock reading; a test older than that is refused when an
        evaluation tries to use it, with `ERR_FLOW_TEST_STALE`.

        Design: Difficulty/priority_pair_validation_conflict/stale_flow_test_outranks_empty_iteration_chain_on_supply_evaluation
        """
        ctx = _two_hydrant_tests_and_an_empty_chain(client)
        refused = _evaluate(client, ctx, ctx["old_test"]["id"])
        validate_error(refused, "ERR_FLOW_TEST_STALE", expected_status=422)

        _, meta = validate_paginated(
            client.list_water_supply_evaluations(
                make_design_engineer_headers(ctx["lead_id"]),
                params={"project_id": ctx["project_id"]},
            )
        )
        assert meta["total_count"] == 0
        assert read_project(client, ctx["project_id"])[
            "governing_hydraulic_calculation_id"
        ] is None

    def test_04_the_same_request_on_a_fresh_test_reaches_the_chain_check(self, client):
        """The calculation referenced by an evaluation has at least one iteration —
        `ERR_NO_ITERATIONS_IN_CHAIN` (409).

        Design: Difficulty/priority_pair_validation_conflict/stale_flow_test_outranks_empty_iteration_chain_on_supply_evaluation
        """
        ctx = _two_hydrant_tests_and_an_empty_chain(client)
        refused = _evaluate(client, ctx, ctx["fresh_test"]["id"])
        validate_error(refused, "ERR_NO_ITERATIONS_IN_CHAIN", expected_status=409)

        _, meta = validate_paginated(
            client.list_water_supply_evaluations(
                make_design_engineer_headers(ctx["lead_id"]),
                params={"project_id": ctx["project_id"]},
            )
        )
        assert meta["total_count"] == 0


UNPARSEABLE_HAZARD_CLASS = "EXTRA_HAZARD_3"


def _malformed_area(project_id):
    return build_hazard_area_payload(
        project_id=project_id,
        label="Rack Storage Bay A",
        hazard_class=UNPARSEABLE_HAZARD_CLASS,
        commodity_class="CLASS_IV",
        storage_height_ft=18.0,
        ceiling_height_ft=36.0,
        area_sqft=24000.0,
        sprinkler_system_type="WET",
        ceiling_slope_pct=None,
        room_area_sqft=None,
        enclosure_rating_hours=None,
        room_has_unprotected_opening=None,
    )


class TestProjectEngineerAuthorizationOutranksTheSchema:
    def test_05_an_engineer_who_is_not_the_lead_learns_nothing_about_his_payload(
        self, client
    ):
        """The acting `DesignEngineer` is the project's `lead_engineer_id` —
        `ERR_NOT_PROJECT_ENGINEER` (403).

        Design: Difficulty/priority_pair_validation_conflict/project_engineer_authorization_outranks_invalid_enum_on_hazard_area_create
        """
        ctx = build_project_stage(client)
        refused = client.create_hazard_area(
            _malformed_area(ctx["project_id"]),
            make_design_engineer_headers(ctx["second_id"]),
        )
        validate_error(refused, "ERR_NOT_PROJECT_ENGINEER", expected_status=403)

        _, meta = validate_paginated(
            client.list_hazard_areas(
                ctx["lead_headers"], params={"project_id": ctx["project_id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_06_the_identical_body_from_the_lead_engineer_fails_on_the_enum(self, client):
        """The body conforms to the endpoint's input schema: required fields present, types
        correct, enum members recognised, numeric ranges satisfied.

        Design: Difficulty/priority_pair_validation_conflict/project_engineer_authorization_outranks_invalid_enum_on_hazard_area_create
        """
        ctx = build_project_stage(client)
        body = _malformed_area(ctx["project_id"])
        validate_error(
            client.create_hazard_area(
                body, make_design_engineer_headers(ctx["second_id"])
            ),
            "ERR_NOT_PROJECT_ENGINEER",
        )
        refused = client.create_hazard_area(body, ctx["lead_headers"])
        validate_error(refused, "ERR_INVALID_REQUEST", expected_status=422)

        _, meta = validate_paginated(
            client.list_hazard_areas(
                ctx["lead_headers"], params={"project_id": ctx["project_id"]}
            )
        )
        assert meta["total_count"] == 0
