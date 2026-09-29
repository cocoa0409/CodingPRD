"""Entity-level guarantees: the fields a create returns, the row a read gives
back, the shape of a filtered page, and the four ways a write can be rejected
before any business rule is reached."""
import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_common_fields,
    assert_envelope_meta,
    assert_identity_only_fields,
)
from test_helpers.constants import FABRICATED_UUID, TEST_DEFAULTS, ZONE_A
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["cw_project_manager_headers"]
DETAILER = TEST_USERS["cw_detailer_headers"]
ARCHITECT = TEST_USERS["architect_of_record_headers"]
PROCUREMENT = TEST_USERS["glazing_procurement_headers"]
STRUCTURAL = TEST_USERS["structural_contractor_headers"]
SUPERINTENDENT = TEST_USERS["field_superintendent_headers"]
QC = TEST_USERS["qc_inspector_headers"]


class TestFacadePackageCreation:
    """The opening row of the whole project."""

    def test_create_returns_the_supplied_scope_and_every_declared_opening_value(self):
        """The eight payload fields come back verbatim, the system fork is forced
        to UNDECIDED even though the payload named UNITIZED, and all eleven
        derived counters open at their declared zero values.

        PRD: "A `system_type` value may appear in the payload, but it is not honoured at creation: the package always opens with `system_type` `UNDECIDED`, and the only thing that ever changes it is the system decision described below."

        Design: Corner/entities/create_facade_package_returns_every_declared_field
        """
        fx.set_clock("2026-08-03T08:00:00Z")
        response = api_client.create_facade_package(
            f.create_facade_package_payload(system_type="UNITIZED"), PM
        )
        package = validate_success(response, expected_status=201)
        assert_envelope_meta(response.json())

        assert package["name"] == TEST_DEFAULTS["PACKAGE_NAME"]
        assert package["floor_count"] == 20
        assert package["total_area_sqm"] == pytest.approx(9000.0, abs=0.01)
        assert package["contract_value_cents"] == 1_450_000_000
        assert package["unit_rate_cents_per_sqm"] == 148_733
        assert package["base_labor_rate_cents_per_hour"] == 9_800
        assert package["design_temp_delta_c"] == pytest.approx(60.0, abs=0.01)
        assert package["weather_tightness_deadline_date"] == "2026-12-15"

        assert package["system_type"] == "UNDECIDED"
        assert package["state"] == "DESIGN_ASSIST"
        assert package["engineering_posture"] == "OPEN"
        assert package["mockup_qualified"] is False
        assert package["blocking_submittal_count"] == 0
        assert package["open_critical_defect_count"] == 0
        assert package["planned_shop_hours"] == pytest.approx(0, abs=0.01)
        assert package["planned_field_crew_size"] == 0
        assert package["certified_area_sqm"] == pytest.approx(0, abs=0.01)
        assert package["earned_value_certified_cents"] == 0
        assert package["retention_held_cents"] == 0
        assert package["weather_tight_zone_count"] == 0

        assert_common_fields(package, "FacadePackage")
        assert package["version"] == 1


class TestInstallationZoneRead:
    """A read gives back exactly what the create stored."""

    def test_read_by_id_reports_the_stored_geometry_and_both_derived_limits(self):
        """The zone read as the field superintendent carries the ten registered
        fields, both status axes at their initial values, the two limits derived
        from the unitized fork, and an untouched cost and hour ledger.

        PRD: "A new zone starts with `install_status` `PLANNED` and `weather_status` `NOT_TIGHT`, with `provisional_labor_cost_cents`, `final_labor_cost_cents`, `certified_line_cents`, `weather_tight_at` and `hang_completed_at` all null, `weather_tight_cycle_count` at 0, `consumed_crew_hours` at 0 and `remaining_crew_hours` equal to the budget."

        Design: Corner/entities/get_installation_zone_by_id_returns_the_stored_row
        """
        ctx = fx.new_project()
        created = fx.add_zone_a(ctx)

        zone = validate_success(
            api_client.get_installation_zone(created["id"], SUPERINTENDENT),
            expected_status=200,
        )
        assert zone["id"] == created["id"]
        assert zone["package_id"] == ctx["package_id"]
        assert zone["floor_number"] == 5
        assert zone["elevation_label"] == "NORTH"
        assert zone["area_sqm"] == pytest.approx(412.37, abs=0.01)
        assert zone["height_m"] == pytest.approx(24.0, abs=0.01)
        assert zone["span_mm"] == 3200
        assert zone["anchor_type"] == "SLOTTED"
        assert zone["designed_joint_mm"] == pytest.approx(22.0, abs=0.01)
        assert zone["planned_panel_count"] == 36
        assert zone["budget_crew_hours"] == pytest.approx(320.0, abs=0.1)

        assert zone["install_status"] == "PLANNED"
        assert zone["weather_status"] == "NOT_TIGHT"
        assert zone["weather_tight_cycle_count"] == 0
        assert zone["thermal_movement_allowance_mm"] == pytest.approx(7.34, abs=0.01)
        assert zone["deflection_limit_mm"] == pytest.approx(13.33, abs=0.01)

        assert zone["provisional_labor_cost_cents"] is None
        assert zone["final_labor_cost_cents"] is None
        assert zone["certified_line_cents"] is None
        assert zone["weather_tight_at"] is None
        assert zone["hang_completed_at"] is None
        assert zone["consumed_crew_hours"] == pytest.approx(0, abs=0.1)
        assert zone["remaining_crew_hours"] == pytest.approx(320.0, abs=0.1)
        assert_common_fields(zone, "InstallationZone")


class TestPanelLotListing:
    """The lot list narrows by zone and then pages inside that filtered set."""

    @staticmethod
    def _three_lots_across_two_zones():
        """Zone A owns a 36-panel and an 18-panel lot; zone B owns a 30-panel
        lot."""
        ctx = fx.setup_ready_for_release(zone_count=2)
        zone_a, zone_b = ctx["zone_ids"][0], ctx["zone_ids"][1]
        fx.create_release(ctx, zone_ids=[zone_a], panels_per_zone=36)
        fx.create_release(ctx, zone_ids=[zone_a], panels_per_zone=18)
        fx.create_release(ctx, zone_ids=[zone_b], panels_per_zone=30)
        return ctx, zone_a, zone_b

    def test_zone_filter_sets_total_count_and_the_page_window_walks_it(self):
        """A one-row page of zone A's two lots reports the filtered total of 2
        with more to come, a ten-row page returns both with nothing beyond, an
        offset past the end returns an empty page against the same total, and the
        unfiltered list reports all three.

        PRD: "The `meta` block of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the size of the filtered set before the page window is applied and `has_more` indicates whether rows remain beyond it."

        Design: Corner/entities/list_panel_lots_paginates_and_filters_by_zone
        """
        ctx, zone_a, zone_b = self._three_lots_across_two_zones()

        first_page, meta = validate_paginated(
            api_client.list_panel_lots(
                PM, params={"zone_id": zone_a, "limit": 1, "offset": 0}
            )
        )
        assert len(first_page) == 1
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert first_page[0]["zone_id"] == zone_a
        assert first_page[0]["lite_count"] == 72
        assert first_page[0]["fabrication_status"] == "BATCHED"

        whole_set, whole_meta = validate_paginated(
            api_client.list_panel_lots(
                PM, params={"zone_id": zone_a, "limit": 10, "offset": 0}
            )
        )
        assert len(whole_set) == 2
        assert whole_meta["total_count"] == 2
        assert whole_meta["has_more"] is False
        assert all(row["zone_id"] == zone_a for row in whole_set)
        assert all(row["fabrication_status"] == "BATCHED" for row in whole_set)
        assert sorted(row["panel_count"] for row in whole_set) == [18, 36]

        past_the_end, tail_meta = validate_paginated(
            api_client.list_panel_lots(
                PM, params={"zone_id": zone_a, "limit": 10, "offset": 2}
            )
        )
        assert past_the_end == []
        assert tail_meta["total_count"] == 2
        assert tail_meta["has_more"] is False

        everything, all_meta = validate_paginated(api_client.list_panel_lots(PM))
        assert all_meta["total_count"] == 3
        assert len(everything) == 3
        assert {row["zone_id"] for row in everything} == {zone_a, zone_b}


class TestMissingIdentifiers:
    """Each entity family reports its own not-found code."""

    def test_each_family_reports_its_own_not_found_code_before_any_other_rule(self):
        """Ten reads and writes aimed at a syntactically valid but never-minted
        identifier each return that family's declared 404, including the hoist
        code on a hang against a real but unready zone and the generic code for a
        crew-day log.

        PRD: "Existence checks, in this internal order: the addressed facade package does not exist — `ERR_PACKAGE_NOT_FOUND` (404), on every endpoint carrying an `{id}` path parameter or a `*_id` body field; then the addressed submittal — `ERR_SUBMITTAL_NOT_FOUND` (404), on submittal endpoints and release creation; then the addressed glass order — `ERR_GLASS_ORDER_NOT_FOUND` (404), on glass-order endpoints, release creation and breakage draws; then the addressed zone — `ERR_ZONE_NOT_FOUND` (404), on zone endpoints, release creation, embed-survey opening, field-test scheduling and reservation creation, and also when the zone belongs to another package than the one named in the request; then the addressed panel lot or fabrication release — `ERR_LOT_NOT_FOUND` (404), on panel-lot and fabrication-release endpoints; then the addressed embed survey — `ERR_SURVEY_NOT_FOUND` (404), on embed-survey endpoints; then the addressed mockup test or field test — `ERR_TEST_NOT_FOUND` (404), on mockup-test and field-test endpoints; then the addressed defect item — `ERR_DEFECT_NOT_FOUND` (404), on defect-item endpoints; then the addressed hoist rig or reservation — `ERR_HOIST_NOT_FOUND` (404), on hoist endpoints and on panel hanging; then a referenced laboratory, crew-day log or breakage draw — `ERR_RESOURCE_NOT_FOUND` (404), on mockup booking, crew-day voiding and breakage-draw cancellation."

        Design: Corner/entities/missing_ids_across_entity_families_return_not_found
        """
        ctx = fx.new_project()
        zone = fx.add_zone_a(ctx)
        ghost = FABRICATED_UUID

        probes = [
            (
                api_client.get_facade_package(ghost, PM),
                ApiErrorId.ERR_PACKAGE_NOT_FOUND.value,
            ),
            (
                api_client.get_installation_zone(ghost, PM),
                ApiErrorId.ERR_ZONE_NOT_FOUND.value,
            ),
            (
                api_client.get_glass_order(ghost, PROCUREMENT),
                ApiErrorId.ERR_GLASS_ORDER_NOT_FOUND.value,
            ),
            (
                api_client.get_submittal(ghost, DETAILER),
                ApiErrorId.ERR_SUBMITTAL_NOT_FOUND.value,
            ),
            (
                api_client.advance_fabrication(
                    ghost, f.advance_fabrication_payload("GLAZED"), SUPERINTENDENT
                ),
                ApiErrorId.ERR_LOT_NOT_FOUND.value,
            ),
            (
                api_client.confirm_pour(ghost, f.confirm_pour_payload(), STRUCTURAL),
                ApiErrorId.ERR_SURVEY_NOT_FOUND.value,
            ),
            (
                api_client.record_field_test_result(
                    ghost, f.water_result_payload(False), QC
                ),
                ApiErrorId.ERR_TEST_NOT_FOUND.value,
            ),
            (
                api_client.waive_defect(ghost, f.waive_payload("WV-2026-01"), ARCHITECT),
                ApiErrorId.ERR_DEFECT_NOT_FOUND.value,
            ),
            (
                api_client.hang_panels(
                    zone["id"], f.hang_panels_payload(ghost), SUPERINTENDENT
                ),
                ApiErrorId.ERR_HOIST_NOT_FOUND.value,
            ),
            (
                api_client.void_crew_day(
                    zone["id"], ghost, f.void_crew_day_payload("wrong zone"), SUPERINTENDENT
                ),
                ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
            ),
        ]

        for response, expected in probes:
            error = validate_error(response, expected, expected_status=404)
            assert error["message"]
            body = response.json()
            assert body["response_type"] == "error"
            assert body["data"]["error_id"] == expected

        zeroed = api_client.hang_panels(
            zone["id"], f.hang_panels_payload(NON_EXISTENT_UUID), SUPERINTENDENT
        )
        error = validate_error(
            zeroed, ApiErrorId.ERR_HOIST_NOT_FOUND.value, expected_status=404
        )
        assert error["error_id"] != ApiErrorId.ERR_ZONE_SEQUENCE_VIOLATION.value


class TestRequiredFieldsOnZoneCreation:
    """Every declared zone input is required."""

    def test_omitting_any_declared_zone_input_is_an_invalid_request(self):
        """Dropping `span_mm` is rejected as an invalid request and creates
        nothing, each of the six other declared inputs is rejected the same way,
        the parent package is never versioned by a rejected write, and supplying
        the field completes the create.

        PRD: "A required input field absent, null, or of the wrong JSON type — `ERR_INVALID_REQUEST` (400). Applies to every write endpoint."

        Design: Corner/entities/zone_create_missing_required_field_returns_invalid_request
        """
        ctx = fx.new_project()
        package_id = ctx["package_id"]
        opening_version = fx.refresh_package(ctx)["version"]

        without_span = f.create_installation_zone_payload(package_id)
        without_span.pop("span_mm")
        refused = api_client.create_installation_zone(without_span, PM)
        error = validate_error(
            refused, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
        )
        assert "span_mm" in error["message"]

        _, meta = validate_paginated(
            api_client.list_installation_zones(PM, params={"package_id": package_id})
        )
        assert meta["total_count"] == 0

        for field in (
            "designed_joint_mm",
            "area_sqm",
            "height_m",
            "anchor_type",
            "planned_panel_count",
            "budget_crew_hours",
        ):
            payload = f.create_installation_zone_payload(package_id)
            payload.pop(field)
            validate_error(
                api_client.create_installation_zone(payload, PM),
                ApiErrorId.ERR_INVALID_REQUEST.value,
                expected_status=400,
            )

        assert fx.refresh_package(ctx)["version"] == opening_version

        complete = validate_success(
            api_client.create_installation_zone(
                f.create_installation_zone_payload(package_id), PM
            ),
            expected_status=201,
        )
        assert complete["span_mm"] == 3200
        assert complete["install_status"] == "PLANNED"


class TestDeclaredDefaults:
    """Five optional inputs, five declared fallbacks."""

    def test_every_optional_input_falls_back_to_its_declared_value(self):
        """A submittal without the delegated-design flag, a rig without a
        changeover buffer, a survey without a tolerance, a first-attempt mockup
        and an order without an expedite authorisation each open on the value the
        contract declares rather than on null.

        PRD: "The optional `delegated_design_scope` flag — false unless supplied — marks the submittal as carrying delegated design responsibility, which means it needs a professional seal before anyone may review it."

        Design: Corner/entities/declared_defaults_applied_when_optional_inputs_omitted
        """
        ctx = fx.new_project()
        zone = fx.add_zone_a(ctx)

        submittal_payload = f.create_submittal_payload(
            ctx["package_id"], submittal_type="COATING_SPEC"
        )
        submittal_payload.pop("delegated_design_scope")
        submittal = validate_success(
            api_client.create_submittal(submittal_payload, DETAILER), expected_status=201
        )
        assert submittal["submittal_type"] == "COATING_SPEC"
        assert submittal["delegated_design_scope"] is False
        assert submittal["state"] == "SUBMITTED"
        assert submittal["revision_cycle"] == 1
        assert submittal["open_notes_count"] == 0

        rig_payload = f.create_hoist_rig_payload(ctx["package_id"])
        rig_payload.pop("changeover_buffer_minutes")
        rig = validate_success(
            api_client.create_hoist_rig(rig_payload, SUPERINTENDENT), expected_status=201
        )
        assert rig["changeover_buffer_minutes"] == 45
        assert rig["status"] == "ACTIVE"

        survey_payload = f.create_embed_survey_payload()
        assert "tolerance_mm" not in survey_payload
        survey = validate_success(
            api_client.create_embed_survey(zone["id"], survey_payload, STRUCTURAL),
            expected_status=201,
        )
        assert survey["tolerance_mm"] == pytest.approx(25.0, abs=0.01)
        assert survey["state"] == "PENDING_SURVEY"
        assert survey["survey_attempt_count"] == 0
        assert survey["poured_at"] is None

        lab = fx.create_lab(ctx)
        mockup_payload = f.create_mockup_test_payload(ctx["package_id"], lab["id"])
        assert "attempt_no" not in mockup_payload
        mockup = validate_success(
            api_client.create_mockup_test(mockup_payload, PM), expected_status=201
        )
        assert mockup["attempt_no"] == 1
        assert mockup["retest_of_test_id"] is None
        assert mockup["surcharge_cents"] == 0

        order_payload = f.create_glass_order_payload(ctx["package_id"])
        assert "expedite_authorized" not in order_payload
        order = validate_success(
            api_client.create_glass_order(order_payload, PROCUREMENT), expected_status=201
        )
        assert order["expedite_authorized"] is False
        assert order["expedite_tier"] == 0
        assert order["coating_revision_count"] == 0
        assert order["re_fire_required"] is False
        assert order["received_lites"] == 0


class TestSystemOwnedFieldsOnCreate:
    """A client cannot pre-load a derived field, a status or a counter."""

    def test_derived_geometry_status_and_counters_ignore_the_payload(self):
        """A zone create that also names a thermal allowance, a hung install
        status, a certified line and a version of 7 stores the derived allowance,
        the declared opening statuses, a null line and a version of 1.

        PRD: "Every resource is identified by `id`, a server-minted UUID carrying no type prefix and no embedded semantics; clients never supply it."

        Design: Corner/entities/computed_and_system_fields_input_ignored_on_create
        """
        ctx = fx.new_project()
        payload = f.create_installation_zone_payload(
            ctx["package_id"],
            thermal_movement_allowance_mm=99.99,
            install_status="PANELS_HUNG",
            certified_line_cents=500,
            version=7,
        )
        zone = validate_success(
            api_client.create_installation_zone(payload, PM), expected_status=201
        )

        assert zone["thermal_movement_allowance_mm"] == pytest.approx(7.34, abs=0.01)
        assert zone["thermal_movement_allowance_mm"] != pytest.approx(99.99, abs=0.01)
        assert zone["install_status"] == "PLANNED"
        assert zone["weather_status"] == "NOT_TIGHT"
        assert zone["certified_line_cents"] is None
        assert zone["provisional_labor_cost_cents"] is None
        assert zone["hang_completed_at"] is None
        assert zone["version"] == 1
        assert_common_fields(zone, "InstallationZone")

        stored = get_success_data(api_client.get_installation_zone(zone["id"], PM))
        assert stored["install_status"] == "PLANNED"
        assert stored["certified_line_cents"] is None
        assert stored["version"] == 1


class TestEnumRangeAndWindowGates:
    """Three ordered gates ahead of every business rule."""

    def test_bad_enums_out_of_range_numbers_and_bad_windows_each_report_their_own_code(self):
        """An unlisted elevation label and an unlisted anchor type report the
        enum code, a zero area reports the range code, and a mockup window that
        ends before or exactly at its start reports the window code — with no
        zone and no mockup surviving any of them.

        PRD: "An enum field carrying a value outside its declared set, or a date or timestamp field that is not ISO 8601 — `ERR_INVALID_ENUM` (400). Applies to every write endpoint carrying an enum, date or timestamp field."

        Design: Corner/entities/enum_and_range_constraints_rejected_on_write
        """
        ctx = fx.new_project()
        package_id = ctx["package_id"]
        lab = fx.create_lab(ctx)

        validate_error(
            api_client.create_installation_zone(
                f.create_installation_zone_payload(
                    package_id, elevation_label="NORTHEAST"
                ),
                PM,
            ),
            ApiErrorId.ERR_INVALID_ENUM.value,
            expected_status=400,
        )
        validate_error(
            api_client.create_installation_zone(
                f.create_installation_zone_payload(package_id, anchor_type="CANTILEVERED"),
                PM,
            ),
            ApiErrorId.ERR_INVALID_ENUM.value,
            expected_status=400,
        )
        validate_error(
            api_client.create_installation_zone(
                f.create_installation_zone_payload(package_id, area_sqm=0), PM
            ),
            ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value,
            expected_status=400,
        )

        validate_error(
            api_client.create_mockup_test(
                f.create_mockup_test_payload(
                    package_id,
                    lab["id"],
                    window_start="2026-08-05T20:00:00Z",
                    window_end="2026-08-05T06:00:00Z",
                ),
                PM,
            ),
            ApiErrorId.ERR_INVALID_WINDOW.value,
            expected_status=400,
        )
        validate_error(
            api_client.create_mockup_test(
                f.create_mockup_test_payload(
                    package_id,
                    lab["id"],
                    window_start="2026-08-05T06:00:00Z",
                    window_end="2026-08-05T06:00:00Z",
                ),
                PM,
            ),
            ApiErrorId.ERR_INVALID_WINDOW.value,
            expected_status=400,
        )

        _, zone_meta = validate_paginated(
            api_client.list_installation_zones(PM, params={"package_id": package_id})
        )
        assert zone_meta["total_count"] == 0
        _, mockup_meta = validate_paginated(
            api_client.list_mockup_tests(PM, params={"package_id": package_id})
        )
        assert mockup_meta["total_count"] == 0

    def test_an_unlisted_shop_target_status_is_refused_as_an_invalid_enum(self):
        """The shop advance accepts only GLAZED and SHIPPED, so a CRATED target
        is refused as an invalid enum and the lot keeps its batched status.

        PRD: "Lots move through the shop under the `FieldSuperintendent`, who supplies a `to_status` of `GLAZED` or `SHIPPED`; any other value is refused as an invalid enum."

        Design: Corner/entities/enum_and_range_constraints_rejected_on_write
        """
        ctx = fx.setup_released_zone()
        lot = ctx["lots"][ctx["zone_ids"][0]][0]

        validate_error(
            api_client.advance_fabrication(
                lot["id"], f.advance_fabrication_payload("CRATED"), SUPERINTENDENT
            ),
            ApiErrorId.ERR_INVALID_ENUM.value,
            expected_status=400,
        )
        assert (
            get_success_data(api_client.get_panel_lot(lot["id"], PM))["fabrication_status"]
            == "BATCHED"
        )


class TestLaboratoryImmutability:
    """The one row in the system that carries no revision counter."""

    def test_a_laboratory_carries_only_an_identity_and_never_gains_a_version(self):
        """The registered laboratory emits `id` and `created_at` and neither
        `version` nor `updated_at`, its filtered listing finds exactly the one
        row, and booking a mockup against it leaves the row byte-identical.

        PRD: "Test laboratories are the single exception. A laboratory is an immutable accreditation reference: it carries only `id` and `created_at`. It has no `updated_at`, no `version` and no update capability of any kind."

        Design: Corner/entities/test_lab_row_is_immutable_and_carries_no_version
        """
        ctx = fx.new_project()
        lab = validate_success(
            api_client.create_test_lab(f.create_test_lab_payload(), PM),
            expected_status=201,
        )
        assert lab["name"] == TEST_DEFAULTS["LAB_NAME"]
        assert lab["chamber_capacity"] == 2
        assert lab["accreditation_ref"] == TEST_DEFAULTS["LAB_ACCREDITATION_REF"]
        assert_identity_only_fields(lab, "TestLab")
        assert "version" not in lab

        ctx["lab"] = lab
        ctx["lab_id"] = lab["id"]
        fx.book_mockup(ctx)

        after = validate_success(
            api_client.get_test_lab(lab["id"], PM), expected_status=200
        )
        assert after == lab

        rows, meta = validate_paginated(
            api_client.list_test_labs(PM, params={"name": TEST_DEFAULTS["LAB_NAME"]})
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == lab["id"]
        assert "version" not in rows[0]
        assert "updated_at" not in rows[0]


class TestForeignKeyScoping:
    """A zone of another package is reported as a zone that does not exist."""

    @staticmethod
    def _two_packages_each_with_one_zone():
        first = fx.new_project()
        zone_a = fx.add_zone_a(first)
        second = fx.new_project()
        zone_b = fx.add_zone_b(second)
        return first, zone_a, second, zone_b

    def test_a_cross_package_zone_reference_is_reported_as_a_missing_zone(self):
        """A defect naming package A but zone B is refused with the zone
        not-found code and leaves package A's punch list empty, the same payload
        with A's own zone is accepted, and a release naming A while covering B is
        refused the same way.

        PRD: "When a payload names both a package and a zone, the package is resolved first; a zone that exists but belongs to a different package than the one named in the request is treated exactly like a zone that does not exist, and reported as `ERR_ZONE_NOT_FOUND`."

        Design: Corner/entities/foreign_keys_must_resolve_within_the_same_package
        """
        first, zone_a, second, zone_b = self._two_packages_each_with_one_zone()
        assert zone_a["package_id"] == first["package_id"]
        assert zone_b["package_id"] == second["package_id"]
        assert zone_a["floor_number"] == ZONE_A["floor_number"]

        crossed = api_client.create_defect_item(
            f.create_defect_item_payload(
                first["package_id"],
                origin="PUNCH_LIST",
                severity="MINOR",
                description="sealant tooling at grid 4",
                zone_id=zone_b["id"],
            ),
            QC,
        )
        validate_error(
            crossed, ApiErrorId.ERR_ZONE_NOT_FOUND.value, expected_status=404
        )

        _, meta = validate_paginated(
            api_client.list_defect_items(
                QC, params={"package_id": first["package_id"]}
            )
        )
        assert meta["total_count"] == 0

        accepted = validate_success(
            api_client.create_defect_item(
                f.create_defect_item_payload(
                    first["package_id"],
                    origin="PUNCH_LIST",
                    severity="MINOR",
                    description="sealant tooling at grid 4",
                    zone_id=zone_a["id"],
                ),
                QC,
            ),
            expected_status=201,
        )
        assert accepted["status"] == "OPEN"
        assert accepted["zone_id"] == zone_a["id"]
        assert accepted["package_id"] == first["package_id"]

    def test_a_release_covering_a_zone_of_another_package_is_refused(self):
        """The `zone_ids` array is resolved against the release's own package, so
        a release opened on package A that names package B's zone reports the
        zone not-found code and creates neither a release nor a lot.

        PRD: "Arrays of references are validated in the order they appear: the `zone_ids` array on a fabrication release is walked front to back, and the first element that either does not resolve or resolves to a zone whose `package_id` differs from the release's `package_id` produces `ERR_ZONE_NOT_FOUND`, with no later element examined."

        Design: Corner/entities/foreign_keys_must_resolve_within_the_same_package
        """
        first = fx.setup_ready_for_release()
        second = fx.new_project()
        foreign_zone = fx.add_zone_b(second)

        refused = api_client.create_fabrication_release(
            f.create_fabrication_release_payload(
                first["package_id"],
                first["submittal_id"],
                first["glass_order_id"],
                [foreign_zone["id"]],
                fx.package_version(first),
            ),
            PM,
        )
        validate_error(refused, ApiErrorId.ERR_ZONE_NOT_FOUND.value, expected_status=404)

        assert get_success_data(api_client.list_fabrication_releases(PM)) == []
        assert get_success_data(api_client.list_panel_lots(PM)) == []
