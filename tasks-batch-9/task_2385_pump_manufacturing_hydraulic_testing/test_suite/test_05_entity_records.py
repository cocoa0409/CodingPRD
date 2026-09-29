"""Entity records: declared fields, defaults, immutability and reachability.

This file reads the stored records themselves rather than any workflow verdict.
It pins the field set each entity promises on creation, the values the contract
declares as defaults, the two entities that carry no `updated_at` and no
`version` because they are immutable after creation, the paging counters a
collection response must expose, the two distinct not-found paths for a path
segment and for a body foreign key, and the three parent filters through which
the selection junction row is reachable.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_build_order,
    assert_common_fields,
    assert_error_envelope,
    assert_foundry,
    assert_material_seal_config,
    assert_pattern_asset,
    assert_pump_model,
    assert_test_point,
    assert_wear_index,
    constants as K,
    expected_allowable_unbalance,
    factories as F,
    fixtures as X,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─────────────────────────────────────────────────────────────────────────────
# Foundries
# ─────────────────────────────────────────────────────────────────────────────
class TestFoundryRecords:
    """The one entity whose whole field set is either supplied or defaulted."""

    def test_registering_a_foundry_echoes_every_declared_field(
        self, api, admin_headers
    ):
        """A new foundry carries its four inputs, its two defaults and the four common fields.

        A foundry is registered with a `foundry_code`, the partner's legal
        `name`, an `approved_alloys` array and a `concurrent_pour_capacity`, and
        is created `ACTIVE` with a `suspension_reason` of null.  Nothing else on
        the record is derived, so a create response that drops a field has
        nowhere to hide: all six declared fields plus the server-minted `id` and
        `created_at`, the refreshed `updated_at` and a `version` of 1 must all be
        present in the 201 envelope.

        Design: Corner/entities/create_foundry_returns_all_declared_fields
        """
        response = api.create_foundry(
            F.foundry_payload(
                foundry_code="FDY-NORTH",
                name="North Iron Works",
                approved_alloys=["CI_GG25", "DUPLEX_S31803"],
                concurrent_pour_capacity=2,
            ),
            admin_headers,
        )
        foundry = validate_success(response, 201)
        assert response.json()["response_type"] == "object"

        assert_foundry(foundry)
        assert foundry["foundry_code"] == "FDY-NORTH"
        assert foundry["name"] == "North Iron Works"
        assert foundry["approved_alloys"] == ["CI_GG25", "DUPLEX_S31803"]
        assert foundry["concurrent_pour_capacity"] == 2
        assert foundry["status"] == "ACTIVE"
        assert foundry["suspension_reason"] is None
        assert foundry["version"] == 1

    def test_foundry_pages_report_the_whole_filtered_count_not_the_page_size(
        self, api, planner_headers
    ):
        """`total_count` counts every matching row; `has_more` looks past the window.

        Three foundries exist and the window is two rows wide.  The first window
        returns two rows and must still report a `total_count` of 3 with
        `has_more` true, because rows matching the filters remain beyond it.  The
        second window returns the remaining row, keeps the same `total_count` and
        flips `has_more` to false.  Narrowing by a `status` no foundry holds
        matches nothing at all, which drives `total_count` itself to 0.

        Design: Corner/entities/list_foundries_paginates_with_total_count_and_has_more
        """
        north = X.create_foundry(
            api,
            foundry_code="FDY-NORTH",
            name="North Iron Works",
            approved_alloys=["CI_GG25", "DUPLEX_S31803"],
            concurrent_pour_capacity=2,
        )
        south = X.create_foundry(
            api,
            foundry_code="FDY-SOUTH",
            name="Southern Castings",
            approved_alloys=["CI_GG25"],
            concurrent_pour_capacity=1,
        )
        east = X.create_foundry(
            api,
            foundry_code="FDY-EAST",
            name="Eastern Foundry",
            approved_alloys=["CN7M"],
            concurrent_pour_capacity=3,
        )
        all_ids = {north["id"], south["id"], east["id"]}

        first_page, first_meta = validate_paginated(
            api.list_foundries(planner_headers, limit=2, offset=0)
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0

        second_page, second_meta = validate_paginated(
            api.list_foundries(planner_headers, limit=2, offset=2)
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_meta["limit"] == 2
        assert second_meta["offset"] == 2

        paged_ids = {row["id"] for row in first_page} | {
            row["id"] for row in second_page
        }
        assert paged_ids == all_ids
        assert len(first_page) + len(second_page) == 3

        suspended, suspended_meta = validate_paginated(
            api.list_foundries(planner_headers, status="SUSPENDED")
        )
        assert suspended == []
        assert suspended_meta["total_count"] == 0
        assert suspended_meta["has_more"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Hydraulic models
# ─────────────────────────────────────────────────────────────────────────────
class TestPumpModelRecords:
    """The catalogue entry reads back exactly as it was registered."""

    def test_reading_a_model_returns_the_registered_curve_and_zeroed_counters(
        self, api, test_engineer_headers
    ):
        """Every registered hydraulic parameter survives the round trip untouched.

        A hydraulic model is registered with its codes, its impeller diameter
        pair, its shutoff head, its best-efficiency-point triple, its catalogue
        suction requirement, its nameplate speed, its flow envelope, its rotor
        mass and its ISO 1940 balance grade.  None of those are derived, so the
        read must return them unchanged.  A new model is created `ORDERABLE`,
        with `superseded_by_model_id` null and all three warranty counters at 0.
        Reading is open to every role, so the test engineer may fetch it.

        Design: Corner/entities/get_pump_model_returns_stored_hydraulic_definition
        """
        model = X.create_pump_model(api, model_code="HSC-14")

        response = api.get_pump_model(model["id"], test_engineer_headers)
        stored = validate_success(response, 200)

        assert_pump_model(stored)
        assert stored["model_code"] == "HSC-14"
        assert stored["generation"] == 2
        assert stored["interchange_group"] == "IG-HSC-14"
        assert stored["max_impeller_diameter_mm"] == pytest.approx(355.0, abs=0.01)
        assert stored["min_impeller_diameter_mm"] == pytest.approx(300.0, abs=0.01)
        assert stored["shutoff_head_m"] == pytest.approx(92.0, abs=0.01)
        assert stored["bep_flow_m3h"] == pytest.approx(300.0, abs=0.01)
        assert stored["bep_head_m"] == pytest.approx(72.0, abs=0.01)
        assert stored["bep_efficiency_pct"] == pytest.approx(82.0, abs=0.01)
        assert stored["npshr_at_bep_m"] == pytest.approx(4.20, abs=0.01)
        assert stored["rated_speed_rpm"] == 2950
        assert stored["max_flow_m3h"] == pytest.approx(380.0, abs=0.01)
        assert stored["rotor_mass_kg"] == pytest.approx(68.0, abs=0.01)
        assert stored["balance_grade"] == "G6_3"

        assert stored["status"] == "ORDERABLE"
        assert stored["superseded_by_model_id"] is None
        assert stored["warranty_defect_count"] == 0
        assert stored["application_error_count"] == 0
        assert stored["no_defect_count"] == 0

    def test_a_model_registered_without_its_bep_flow_is_refused_and_not_stored(
        self, api, admin_headers
    ):
        """A missing required input field is a malformed request, not a null column.

        `bep_flow_m3h` is part of the best-efficiency-point triple every
        hydraulic model must declare; it is neither optional nor defaulted.  A
        body that omits it fails the request-shape rung with
        `ERR_INVALID_REQUEST`, and because a rejected request writes nothing the
        catalogue must still be empty afterwards.

        Design: Corner/entities/create_pump_model_missing_required_bep_flow_returns_invalid_request
        """
        payload = F.pump_model_payload(model_code="HSC-14")
        del payload["bep_flow_m3h"]

        response = api.create_pump_model(payload, admin_headers)
        validate_error(response, ApiErrorId.INVALID_REQUEST)

        rows, meta = validate_paginated(api.list_pump_models(admin_headers))
        assert meta["total_count"] == 0
        assert rows == []


# ─────────────────────────────────────────────────────────────────────────────
# Casting tooling
# ─────────────────────────────────────────────────────────────────────────────
class TestPatternAssetRecords:
    """Tooling starts qualified with an unworn wear curve."""

    def test_new_tooling_starts_qualified_with_every_wear_counter_at_zero(
        self, api, admin_headers
    ):
        """The four counters and the initial state are defaults, not inputs.

        A casting pattern is registered against the model it produces and the
        foundry that physically holds it, with a unique `pattern_code` and a
        `wear_threshold` of at least 1.  A new pattern is `QUALIFIED`, with
        `pours_since_refurb`, `defect_pours_since_refurb`, `wear_index` and
        `refurb_cycles` all at 0.  Nothing has been poured, so the wear score -
        pours plus twice the defect pours - is 0 as well.

        Design: Corner/entities/create_pattern_asset_defaults_counters_and_status_to_qualified
        """
        world = X.setup_master_data(api, with_pattern=False, with_config=False)

        response = api.create_pattern_asset(
            F.pattern_asset_payload(
                world["model"]["id"],
                world["foundry"]["id"],
                pattern_code="PAT-HSC14-A",
                wear_threshold=20,
            ),
            admin_headers,
        )
        pattern = validate_success(response, 201)

        assert_pattern_asset(pattern)
        assert pattern["pump_model_id"] == world["model"]["id"]
        assert pattern["foundry_id"] == world["foundry"]["id"]
        assert pattern["pattern_code"] == "PAT-HSC14-A"
        assert pattern["wear_threshold"] == 20
        assert pattern["status"] == "QUALIFIED"
        assert pattern["pours_since_refurb"] == 0
        assert pattern["defect_pours_since_refurb"] == 0
        assert pattern["wear_index"] == 0
        assert pattern["refurb_cycles"] == 0
        assert pattern["version"] == 1
        assert_wear_index(pattern)

    def test_tooling_naming_an_unknown_model_reports_the_missing_body_reference(
        self, api, admin_headers
    ):
        """A body foreign key that resolves to nothing is not a path-level miss.

        `pump_model_id` is supplied in the request body rather than in the path,
        so it is checked at the body-reference rung and yields
        `ERR_REFERENCED_RESOURCE_NOT_FOUND` - deliberately a different identifier
        from the `ERR_NOT_FOUND` that an unresolvable path segment produces, even
        though both answer with the same HTTP status.  The foundry named
        alongside it does exist, so nothing else can account for the rejection,
        and no tooling row may be created.

        Design: Corner/entities/create_pattern_asset_with_unknown_pump_model_returns_referenced_resource_not_found
        """
        foundry = X.create_foundry(api, foundry_code="FDY-NORTH")

        response = api.create_pattern_asset(
            F.pattern_asset_payload(
                NON_EXISTENT_UUID, foundry["id"], pattern_code="PAT-ORPHAN"
            ),
            admin_headers,
        )
        error = validate_error(response, ApiErrorId.REFERENCED_RESOURCE_NOT_FOUND)
        assert error["error_id"] != ApiErrorId.NOT_FOUND

        rows, meta = validate_paginated(api.list_pattern_assets(admin_headers))
        assert meta["total_count"] == 0
        assert rows == []


# ─────────────────────────────────────────────────────────────────────────────
# Material and seal configurations
# ─────────────────────────────────────────────────────────────────────────────
class TestMaterialSealConfigRecords:
    """A released configuration is enum-constrained and immutable once created."""

    def test_only_an_api_682_flush_plan_is_accepted_and_the_stored_row_is_immutable(
        self, api, admin_headers
    ):
        """`API_PLAN_99` is outside the declared set; `API_PLAN_11` is inside it.

        The API 682 `flush_plan` of a material and seal configuration is one of
        `API_PLAN_02`, `API_PLAN_11`, `API_PLAN_23`, `API_PLAN_32` or
        `API_PLAN_53B`, so a value outside that set fails the request-shape rung
        with `ERR_INVALID_REQUEST`.  The otherwise identical body naming
        `API_PLAN_11` is accepted, and because a configuration is immutable once
        created it carries only `id` and `created_at`: neither `updated_at` nor
        `version` appears on the record at all.  The rejected attempt left no
        row, so exactly one configuration exists at the end.

        Design: Corner/entities/create_material_seal_config_invalid_enum_flush_plan_rejected
        """
        model = X.create_pump_model(api, model_code="HSC-14")

        rejected = api.create_material_seal_config(
            F.material_seal_config_payload(
                model["id"], config_code="MSC-BAD", flush_plan="API_PLAN_99"
            ),
            admin_headers,
        )
        validate_error(rejected, ApiErrorId.INVALID_REQUEST)

        accepted = api.create_material_seal_config(
            F.material_seal_config_payload(
                model["id"], config_code="MSC-CI-P11", flush_plan="API_PLAN_11"
            ),
            admin_headers,
        )
        config = validate_success(accepted, 201)

        assert_material_seal_config(config)
        assert_common_fields(config, versioned=False)
        assert config["flush_plan"] == "API_PLAN_11"
        assert config["config_code"] == "MSC-CI-P11"
        assert config["pump_model_id"] == model["id"]
        assert "updated_at" not in config
        assert "version" not in config

        rows, meta = validate_paginated(api.list_material_seal_configs(admin_headers))
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == config["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Measured test points
# ─────────────────────────────────────────────────────────────────────────────
class TestTestPointRecords:
    """A recorded measurement is append-only and can never be edited."""

    def test_a_measured_point_reads_back_with_no_version_and_no_updated_at(
        self, api, test_engineer_headers
    ):
        """The immutable point exposes `id` and `created_at` and nothing more.

        Measured points are immutable and append-only, and a measured test point
        is one of the two entity types that therefore carry only `id` and
        `created_at`: the `updated_at` and `version` fields are absent from
        their representations rather than present and null.  The read must return
        the recorded flow, the three-percent-head-drop suction measurement and
        the suction-point flag exactly as they were appended, and the collection
        narrowed to the point's own run must return that single row.

        Design: Corner/entities/test_point_is_immutable_with_no_version_field
        """
        ctx = X.setup_assembled_build_order(api)
        run = get_success_data(
            api.create_test_run(
                F.test_run_payload(ctx["build_order"]["id"]), test_engineer_headers
            )
        )
        point = get_success_data(
            api.add_test_point(
                run["id"],
                F.test_point_payload(
                    265.0, 74.0, 67.21, measured_npsh3_m=3.40, is_npsh_point=True
                ),
                test_engineer_headers,
            )
        )

        response = api.get_test_point(point["id"], test_engineer_headers)
        stored = validate_success(response, 200)

        assert_test_point(stored)
        assert_common_fields(stored, versioned=False)
        assert "updated_at" not in stored
        assert "version" not in stored
        assert stored["test_run_id"] == run["id"]
        assert stored["measured_flow_m3h"] == pytest.approx(265.0, abs=0.01)
        assert stored["measured_head_m"] == pytest.approx(74.0, abs=0.01)
        assert stored["measured_power_kw"] == pytest.approx(67.21, abs=0.01)
        assert stored["measured_npsh3_m"] == pytest.approx(3.40, abs=0.01)
        assert stored["is_npsh_point"] is True

        rows, meta = validate_paginated(
            api.list_test_points(test_engineer_headers, test_run_id=run["id"])
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == point["id"]
        assert "version" not in rows[0]


# ─────────────────────────────────────────────────────────────────────────────
# Build orders
# ─────────────────────────────────────────────────────────────────────────────
class TestBuildOrderRecords:
    """The balance allowance appears only when assembly is recorded."""

    def test_allowable_unbalance_is_null_until_assembly_then_derived_from_the_model(
        self, api, planner_headers
    ):
        """The allowance comes from the model's balance grade, never from the body.

        A new build order is `PLANNED` with `running_clearance_mm`,
        `residual_unbalance_g_mm`, `seal_flush_plan_installed` and
        `allowable_unbalance_g_mm` all null.  Recording assembly stores the three
        measurements and computes the allowance alongside them: the balance
        quality number of `G6_3` is 6.3, multiplied by the ISO 1940 coefficient
        9549 and by the rotor mass of 68.0 kilograms, divided by the rated speed
        of 2950 revolutions per minute, which rounds to 1386.71 gramme
        millimetres.  The assembly request carries no such field, so the value
        can only have come from the model.  The measured 900.00 sits below the
        allowance, the measured clearance of 0.35 sits inside the band anchored
        on the configuration's 0.30 minimum, and the installed plan matches, so
        the order lands on `ASSEMBLED` with no rework loops behind it.

        Design: Corner/entities/build_order_allowable_unbalance_computed_at_assembly_from_model_grade
        """
        ctx = X.setup_planned_build_order(api)
        planned = ctx["build_order"]
        assert planned["status"] == "PLANNED"
        assert planned["allowable_unbalance_g_mm"] is None
        assert planned["running_clearance_mm"] is None
        assert planned["residual_unbalance_g_mm"] is None
        assert planned["seal_flush_plan_installed"] is None

        response = api.record_assembly(
            planned["id"],
            F.assembly_payload(
                running_clearance_mm=0.35,
                residual_unbalance_g_mm=900.00,
                seal_flush_plan_installed="API_PLAN_11",
            ),
            planner_headers,
        )
        assembled = validate_success(response, 200)

        assert_build_order(assembled)
        assert assembled["allowable_unbalance_g_mm"] == pytest.approx(
            K.BUILD_ALLOWABLE_UNBALANCE_G_MM, abs=0.01
        )
        assert assembled["allowable_unbalance_g_mm"] == pytest.approx(
            expected_allowable_unbalance("G6_3", 68.0, 2950), abs=0.01
        )
        assert assembled["status"] == "ASSEMBLED"
        assert assembled["rework_cycles"] == 0
        assert assembled["running_clearance_mm"] == pytest.approx(0.35, abs=0.01)
        assert assembled["residual_unbalance_g_mm"] == pytest.approx(900.00, abs=0.01)
        assert assembled["seal_flush_plan_installed"] == "API_PLAN_11"


# ─────────────────────────────────────────────────────────────────────────────
# Enquiries
# ─────────────────────────────────────────────────────────────────────────────
class TestDutyApplicationRecords:
    """System-sourced audit fields are not accepted from the client."""

    def test_an_enquiry_body_carrying_its_own_id_is_refused_and_writes_nothing(
        self, api, engineer_headers
    ):
        """`id` is server-minted, so supplying it is an unknown input field.

        Every resource carries a server-minted `id`, and the enquiry endpoint's
        declared inputs are the application code, the customer name, the duty
        point, the installation and fluid description and the commercial terms -
        `id` is not among them.  A body that carries one is neither honoured nor
        quietly ignored: it fails the request-shape rung, which forbids unknown
        fields, with `ERR_INVALID_REQUEST`, and no enquiry exists afterwards.

        Design: Corner/entities/duty_application_create_with_client_supplied_id_extra_field_rejected
        """
        payload = F.duty_application_payload(application_code="APP-1001")
        payload["id"] = "11111111-1111-1111-1111-111111111111"

        response = api.create_duty_application(payload, engineer_headers)
        validate_error(response, ApiErrorId.INVALID_REQUEST)

        rows, meta = validate_paginated(api.list_duty_applications(engineer_headers))
        assert meta["total_count"] == 0
        assert rows == []


# ─────────────────────────────────────────────────────────────────────────────
# Selections
# ─────────────────────────────────────────────────────────────────────────────
class TestSelectionRecords:
    """An unresolvable path segment is a not-found, never an empty success."""

    def test_reading_a_selection_that_does_not_exist_returns_not_found(
        self, api, engineer_headers
    ):
        """A well-formed identifier addressing no row fails at the path rung.

        Path existence is checked for every resource addressed by a path segment,
        and a segment that resolves to nothing yields `ERR_NOT_FOUND`.  The
        identifier here is a syntactically valid UUID, so the request never
        reaches the request-shape rung and cannot be reported as malformed, and
        the answer is an error envelope carrying a human-readable message rather
        than an empty success body.

        Design: Corner/entities/get_selection_with_unknown_id_returns_not_found
        """
        response = api.get_selection(NON_EXISTENT_UUID, engineer_headers)
        error = validate_error(response, ApiErrorId.NOT_FOUND)

        assert_error_envelope(response.json(), ApiErrorId.NOT_FOUND)
        assert error["message"].strip()
        assert response.json()["meta"]["api_request_id"].startswith("req_")


class TestSelectionGraphTopology:
    """The junction row is reachable in reverse from each of its three parents."""

    def test_a_selection_is_listed_under_each_of_its_three_parent_filters(
        self, api, approver_headers
    ):
        """Enquiry, model and configuration filters all return the same row.

        A selection names a `duty_application_id`, a `pump_model_id` and a
        `material_seal_config_id`, and selections may be filtered by any of the
        three.  Each of the three narrowings must therefore return exactly the
        one row that joins them, which proves the graph is traversable in reverse
        from every parent rather than only from the enquiry that owns the
        sizing.  All three filters are exact-match, so a filter naming a
        different enquiry or a different model returns nothing at all.  Creating
        the selection leaves it in `DRAFT`.

        Design: Corner/entities/graph_topology_selection_reachable_from_all_three_parent_filters
        """
        ctx = X.setup_draft_selection(api)
        selection_id = ctx["selection"]["id"]

        other_duty = X.create_duty_application(api, application_code="APP-9999")
        other_model = X.create_pump_model(api, **K.MODEL_VTP_08)

        for filters in (
            {"duty_application_id": ctx["duty"]["id"]},
            {"pump_model_id": ctx["model"]["id"]},
            {"material_seal_config_id": ctx["config"]["id"]},
        ):
            rows, meta = validate_paginated(
                api.list_selections(approver_headers, **filters)
            )
            assert meta["total_count"] == 1, f"filter {filters} lost the row"
            assert len(rows) == 1
            assert rows[0]["id"] == selection_id
            assert rows[0]["status"] == "DRAFT"

        for filters in (
            {"duty_application_id": other_duty["id"]},
            {"pump_model_id": other_model["id"]},
        ):
            rows, meta = validate_paginated(
                api.list_selections(approver_headers, **filters)
            )
            assert meta["total_count"] == 0, f"filter {filters} matched too much"
            assert rows == []
