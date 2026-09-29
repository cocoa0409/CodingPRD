"""Entity shape: what a row looks like the moment it is created and read back.

These scenarios exercise the declared field set, the server-managed properties,
the documented defaults, list metadata, and the two identifier-resolution
families — a path identifier and a body foreign key.
"""

from test_helpers import (
    LotSpec,
    UNKNOWN_EQUIPMENT_ID,
    UNKNOWN_FLOW_ID,
    UNKNOWN_UUID,
    build_line,
    complete_step,
    equipment_engineer_headers,
    fab_planner_headers,
    open_run,
    process_engineer_headers,
    quality_manager_headers,
    two_recipe_line_spec,
    yield_engineer_headers,
)
from test_helpers.api_errors import (
    ERR_EQUIPMENT_NOT_FOUND,
    ERR_PROCESS_FLOW_NOT_FOUND,
    ERR_RECIPE_NOT_FOUND,
    ERR_VALIDATION,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_created_at_ascending,
    assert_envelope,
    assert_fields,
    assert_hours,
    assert_measurement_common_fields,
    assert_pagination_meta,
    assert_ratio,
    assert_timestamp_equals,
)
from test_helpers.factories import (
    chamber_payload,
    lot_payload,
    process_step_payload,
    recipe_payload,
)
from prd_bench_local_runner.testing.validators import validate_error, validate_success


# --------------------------------------------------------------------------
# The recipe row: creation, read-back, listing and the expiry default
# --------------------------------------------------------------------------


class TestRecipeEntity:
    def test_creating_a_recipe_returns_every_declared_field(self, fab):
        """A brand-new recipe is QUALIFIED at revision 1 with nothing restricted.

        PRD: "A new recipe opens with `status` `QUALIFIED`, `restricted_reason`
        `NONE` and `revision` 1."

        Design: Corner/entities/create_recipe_returns_201_with_all_declared_fields
        """
        response = fab.client.create_recipe(
            recipe_payload("LITHO-200", "LITHO", 50.0, 120),
            process_engineer_headers(),
        )

        recipe = validate_success(response, 201)
        assert_envelope(response.json(), "object")
        assert_fields(
            recipe,
            recipe_code="LITHO-200",
            tool_type="LITHO",
            qual_expiry_days=120,
            revision=1,
            status="QUALIFIED",
            restricted_reason="NONE",
        )
        assert_hours(recipe["target_value"], 50.00, "target_value")
        assert_common_fields(recipe, expected_version=1)
        assert_timestamp_equals(recipe["created_at"], "2026-08-01T00:00:00Z", "created_at")

    def test_reading_a_recipe_returns_the_stored_row(self, fab):
        """Every value supplied at creation survives the round trip unchanged.

        PRD: "A `ProcessEngineer` creates one with a `recipe_code` of 1 to 32
        globally unique characters, a `tool_type` from `LITHO`, `ETCH`,
        `DEPOSITION`, `IMPLANT` and `CMP`, a `target_value` greater than zero
        representing the current nominal process target such as an etch depth in
        nanometres, and optionally `qual_expiry_days`, the number of days a
        chamber qualification against this recipe stays valid, which must be at
        least 1 and defaults to 90."

        Design: Corner/entities/get_recipe_returns_the_stored_row
        """
        created = fab.recipe("LITHO-200", "LITHO", 50.0, 120)

        response = fab.client.get_recipe(created["id"], yield_engineer_headers())

        stored = validate_success(response, 200)
        assert_envelope(response.json(), "object")
        assert_fields(
            stored,
            id=created["id"],
            recipe_code="LITHO-200",
            tool_type="LITHO",
            qual_expiry_days=120,
            status="QUALIFIED",
        )
        assert_hours(stored["target_value"], 50.00, "target_value")

    def test_listing_recipes_reports_the_full_count_beyond_the_page(self, fab):
        """A two-row page out of three rows still reports three and flags more.

        PRD: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope."

        Design: Corner/entities/list_recipes_paginates_with_total_count_and_has_more
        """
        first = fab.recipe("LITHO-200", "LITHO", 50.0, 100)
        second = fab.recipe("ETCH-200", "ETCH", 100.0, 100)
        fab.recipe("CMP-200", "CMP", 30.0, 100)

        response = fab.client.list_recipes(
            fab_planner_headers(), {"limit": 2, "offset": 0}
        )

        page = validate_success(response, 200)
        body = response.json()
        assert_envelope(body, "array")
        assert_pagination_meta(body["meta"], 2, 0, 3, True)
        assert len(page) == 2, "a limit of 2 must return exactly 2 rows"
        # Default ordering is creation order, so the third recipe is off the page.
        assert [row["id"] for row in page] == [first["id"], second["id"]]
        assert_created_at_ascending(page)

    def test_omitting_the_expiry_window_applies_the_ninety_day_default(self, fab):
        """A recipe created without an expiry window qualifies a chamber for 90 days.

        PRD: "A `PASS` run drives the chamber `UNQUALIFIED → QUALIFIED` or
        `QUAL_EXPIRED → QUALIFIED`, setting `qualified_at` to the current logical
        instant and `qual_expires_at` to that instant plus the recipe's
        `qual_expiry_days` days."

        Design: Corner/entities/omitting_qual_expiry_days_applies_the_ninety_day_default
        """
        recipe = fab.recipe("LITHO-200", "LITHO", 50.0, qual_expiry_days=None)
        assert recipe["qual_expiry_days"] == 90
        tool = fab.equipment("LITHO-1", "LITHO")
        chamber = fab.chamber(tool["id"], recipe["id"], "CH_L1")

        qualified = fab.qualify_chamber(chamber["id"])

        assert qualified["qual_state"] == "QUALIFIED"
        assert_timestamp_equals(
            qualified["qualified_at"], "2026-08-01T00:00:00Z", "qualified_at"
        )
        # 2026-08-01 plus ninety days.
        assert_timestamp_equals(
            qualified["qual_expires_at"], "2026-10-30T00:00:00Z", "qual_expires_at"
        )

    def test_creating_a_recipe_without_a_tool_type_is_a_shape_failure(self, fab):
        """The missing required field is caught before any row is written.

        PRD: "Request shape: required fields present, correct types, enum members
        inside their constraint set, numeric ranges satisfied (including the
        per-element shape of `wafer_results` and the per-element membership of
        `certified_tool_types`), and pagination within bounds — `ERR_VALIDATION`."

        Design: Corner/entities/create_recipe_without_tool_type_returns_invalid_request
        """
        response = fab.client.create_recipe(
            recipe_payload("LITHO-200", target_value=50.0, drop=["tool_type", "qual_expiry_days"]),
            process_engineer_headers(),
        )

        body = validate_error(response, ERR_VALIDATION, 400)
        assert body["error_id"] == ERR_VALIDATION
        assert fab.count(fab.client.list_recipes(process_engineer_headers())) == 0

    def test_reading_an_unknown_recipe_reports_the_recipe_not_found_code(self, fab):
        """Each entity answers with its own not-found code, never a generic one.

        PRD: "Each entity has its own not-found code:
        `ERR_PROCESS_FLOW_NOT_FOUND`, `ERR_PROCESS_STEP_NOT_FOUND`,
        `ERR_RECIPE_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`,
        `ERR_EQUIPMENT_NOT_FOUND`, `ERR_CHAMBER_NOT_FOUND`,
        `ERR_OPERATOR_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
        `ERR_STEP_RUN_NOT_FOUND`, `ERR_SPC_CHART_NOT_FOUND`,
        `ERR_EXCURSION_NOT_FOUND` and `ERR_SORT_RUN_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/get_recipe_with_unknown_id_returns_recipe_not_found
        """
        response = fab.client.get_recipe(UNKNOWN_UUID, process_engineer_headers())

        body = validate_error(response, ERR_RECIPE_NOT_FOUND, 404)
        assert body["error_id"] == ERR_RECIPE_NOT_FOUND


# --------------------------------------------------------------------------
# Derived flow totals, recomputed on every append
# --------------------------------------------------------------------------


class TestProcessFlowDerivedTotals:
    def test_each_appended_step_recomputes_the_flow_totals(self, fab):
        """Two appends take the flow from 0 steps and 0.0 hours to 2 steps and 5.0.

        PRD: "Appending a step recomputes the parent flow's `step_count` as the
        number of steps belonging to it and its `total_standard_hours` as the sum
        of `standard_hours` over those steps rounded to 2 decimal places, and
        increments the flow's `version` by 1."

        Design: Corner/entities/flow_step_count_and_total_standard_hours_are_recomputed_per_step
        """
        litho = fab.recipe("LITHO-200", "LITHO", 50.0, 100)
        etch = fab.recipe("ETCH-200", "ETCH", 100.0, 100)
        flow = fab.flow("FLOW-C", "LOGIC_N7")

        assert flow["step_count"] == 0
        assert_hours(flow["total_standard_hours"], 0.0, "total_standard_hours")

        fab.step(flow["id"], litho["id"], 10, "LITHO-1", 2.0)
        response = fab.client.add_process_step(
            flow["id"],
            process_step_payload(
                etch["id"],
                step_seq=20,
                step_name="ETCH-1",
                standard_hours=3.0,
                metrology_required=True,
            ),
            process_engineer_headers(),
        )

        second_step = validate_success(response, 201)
        assert second_step["metrology_required"] is True

        reread = fab.read_flow(flow["id"])
        assert reread["step_count"] == 2
        assert_hours(reread["total_standard_hours"], 5.0, "total_standard_hours")
        assert_fields(reread, status="DRAFT", revision=1)
        # One increment per append on top of the creation version.
        assert_common_fields(reread, expected_version=3)


# --------------------------------------------------------------------------
# The lot row: server-minted fields and enum constraints
# --------------------------------------------------------------------------


def _released_flow_with_a_draft_plan(fab):
    """A released flow and a plan that has never been priced, with no lots."""
    return build_line(fab, two_recipe_line_spec(commit_plan=False, lots=[]))


class TestLotEntity:
    def test_client_supplied_system_fields_are_ignored_on_lot_creation(self, fab):
        """The client's id, created_at and version are all overwritten by the server.

        PRD: "A created lot opens with `flow_state` `PLANNED`, `hold_state`
        `NONE`, `lot_type` `PRODUCTION`, `current_step_seq` 0, `rework_count` 0,
        `origin_wafer_count` equal to the supplied `wafer_count`, and
        `parent_lot_id`, `hold_excursion_id`, `released_at`, `completed_at` and
        `actual_cycle_time_days` all null."

        Design: Corner/entities/lot_system_fields_are_server_minted_and_client_supplied_ones_are_input_ignored
        """
        env = _released_flow_with_a_draft_plan(fab)
        forged_id = "11111111-1111-1111-1111-111111111111"

        response = fab.client.create_lot(
            lot_payload(
                env.plan["id"],
                env.flow["id"],
                "LOT-777",
                5,
                id=forged_id,
                created_at="2000-01-01T00:00:00Z",
                version=99,
            ),
            fab_planner_headers(),
        )

        lot = validate_success(response, 201)
        assert lot["id"] != forged_id, "the id must be server-minted"
        assert_common_fields(lot, expected_version=1)
        assert_timestamp_equals(lot["created_at"], "2026-08-01T00:00:00Z", "created_at")
        assert_fields(
            lot,
            flow_state="PLANNED",
            hold_state="NONE",
            current_step_seq=0,
            lot_type="PRODUCTION",
            priority_class="STANDARD",
            wafer_count=5,
            origin_wafer_count=5,
        )

    def test_a_priority_class_outside_the_enum_is_a_shape_failure(self, fab):
        """URGENT is not one of the three priority classes, so nothing is created.

        PRD: "A `FabPlanner` creates a production lot naming the `plan_id` whose
        wafer starts it will consume and the `flow_id` it will run, which must
        equal the plan's `flow_id` or the request is rejected with
        `ERR_PRODUCT_FAMILY_MISMATCH`; a globally unique `lot_number` of 1 to 32
        characters, duplicates rejected with `ERR_DUPLICATE_CODE`; a
        `wafer_count` of at least 1; and optionally a `priority_class` of
        `STANDARD`, `HOT` or `SUPER_HOT`, defaulting to `STANDARD`."

        Design: Corner/entities/create_lot_with_priority_class_outside_the_enum_returns_invalid_request
        """
        env = _released_flow_with_a_draft_plan(fab)

        response = fab.client.create_lot(
            lot_payload(
                env.plan["id"], env.flow["id"], "LOT-778", 5, priority_class="URGENT"
            ),
            fab_planner_headers(),
        )

        body = validate_error(response, ERR_VALIDATION, 400)
        assert body["error_id"] == ERR_VALIDATION
        assert fab.count(
            fab.client.list_lots(fab_planner_headers(), {"plan_id": env.plan["id"]})
        ) == 0


# --------------------------------------------------------------------------
# The one entity that carries neither version nor updated_at
# --------------------------------------------------------------------------


class TestMeasurementImmutability:
    def test_a_metrology_reading_carries_no_version_and_no_updated_at(self, fab):
        """The reading is an observation, so only id and created_at accompany it.

        PRD: "A metrology reading is an immutable observation, so a measurement
        row carries only `id` and `created_at`; it has **no** `updated_at` and
        **no** `version`, and no endpoint modifies one after it is recorded."

        Design: Corner/entities/metrology_measurement_row_is_immutable_with_no_version_or_updated_at
        """
        env = build_line(
            fab, two_recipe_line_spec(lots=[LotSpec("LOT-001", 3, "STANDARD")])
        )
        complete_step(fab, env, step_ix=0, lot_ix=0)
        run = open_run(fab, env, step_ix=1, lot_ix=0)
        recorded = fab.measure(
            run["id"], env.charts[0]["id"], 100.0, env.operators[0]["id"]
        )

        response = fab.client.get_measurement(
            recorded["id"], quality_manager_headers()
        )

        measurement = validate_success(response, 200)
        assert measurement["id"] == recorded["id"]
        assert_measurement_common_fields(measurement)
        assert_timestamp_equals(
            measurement["created_at"], "2026-08-01T00:00:00Z", "created_at"
        )
        assert measurement["classification"] == "IN_CONTROL"
        assert_ratio(measurement["deviation_sigma"], 0.0000, "deviation_sigma")


# --------------------------------------------------------------------------
# Identifier resolution: one in the path, one in the body
# --------------------------------------------------------------------------


class TestIdentifierResolution:
    def test_appending_a_step_under_an_unknown_flow_reports_the_flow_code(self, fab):
        """The path identifier is resolved before the body is even considered.

        PRD: "When a path carries an identifier, the server resolves it before it
        evaluates any business rule."

        Design: Corner/entities/append_step_under_unknown_flow_returns_process_flow_not_found
        """
        recipe = fab.recipe("LITHO-200", "LITHO", 50.0, 100)
        assert fab.count(fab.client.list_process_flows(process_engineer_headers())) == 0

        response = fab.client.add_process_step(
            UNKNOWN_FLOW_ID,
            process_step_payload(recipe["id"], 10, "LITHO-1", 2.0),
            process_engineer_headers(),
        )

        body = validate_error(response, ERR_PROCESS_FLOW_NOT_FOUND, 404)
        assert body["error_id"] == ERR_PROCESS_FLOW_NOT_FOUND

    def test_an_unresolvable_body_foreign_key_reports_its_own_entity_code(self, fab):
        """The same catalogue serves body foreign keys, so equipment_id answers for itself.

        PRD: "The same catalogue serves foreign keys supplied in a request body:
        an unresolvable `plan_id` yields `ERR_PLAN_NOT_FOUND`, an unresolvable
        `qualified_recipe_id` yields `ERR_RECIPE_NOT_FOUND`, and so on."

        Design: Corner/entities/create_chamber_with_unknown_equipment_id_returns_equipment_not_found
        """
        recipe = fab.recipe("LITHO-200", "LITHO", 50.0, 100)
        assert fab.count(fab.client.list_equipment(equipment_engineer_headers())) == 0

        response = fab.client.create_chamber(
            chamber_payload(UNKNOWN_EQUIPMENT_ID, recipe["id"], "CH_X1", 50.0),
            equipment_engineer_headers(),
        )

        body = validate_error(response, ERR_EQUIPMENT_NOT_FOUND, 404)
        assert body["error_id"] == ERR_EQUIPMENT_NOT_FOUND
