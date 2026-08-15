"""Drawings and BOM components: creation defaults, well-formedness and
existence rejections, catalogue pagination, find-number uniqueness, release
gating, supersession lockdown, and the drawing-state gate on program creation."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_drawing_component,
    assert_harness_drawing,
    is_valid_uuid,
    make_component,
    make_drawing,
    release_drawing,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ENG = TEST_USERS["harness_engineer_headers"]
PROC = TEST_USERS["process_engineer_headers"]
PLAN = TEST_USERS["production_planner_headers"]


class TestDrawingCreation:
    def test_drawing_create_ignores_readonly_status_input(self, api):
        """PRD §2.6: "Undeclared or read-only payload fields are ignored and are not an error."
        PRD §3.1: "A new drawing is born in `DRAFT` status, and both `released_at` and `superseded_at` remain null."
        PRD §2.4: "The `id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/c_drawing_create_readonly_status_input_ignored
        """
        resp = api.create_drawing(
            {
                "drawing_number": "DWG-E1",
                "customer_code": "ACME",
                "revision": "A",
                "workmanship_class": "IPC_CLASS_2",
                "status": "RELEASED",
            },
            ENG,
        )
        data = validate_success(resp, 201)
        assert_harness_drawing(data)
        assert data["status"] == "DRAFT", f"client-supplied status must be ignored, born DRAFT: {data}"
        assert data["released_at"] is None, f"released_at stays null until release: {data}"
        assert data["superseded_at"] is None, f"superseded_at stays null until supersession: {data}"
        assert is_valid_uuid(data["id"]) and "-" in data["id"], "id must be a bare UUID"

    def test_drawing_missing_workmanship_class_rejected(self, api):
        """PRD §3.1: "A `HarnessEngineer` authors a harness drawing by supplying a `drawing_number` (unique across the plant), the owning `customer_code`, a `revision` letter such as \"A\", and the `workmanship_class` (`IPC_CLASS_1`, `IPC_CLASS_2`, or `IPC_CLASS_3`)."
        PRD §2.6: "the body parses as JSON; declared input fields are present with correct types; enum values fall in their declared sets; conditional requirements hold (`opens_count` is required when `test_type` is `CONTINUITY`; `hipot_voltage_v`, `dwell_seconds`, `measured_leakage_ua`, and `leakage_limit_ua` are required when `test_type` is `HIPOT`); and field constraints hold (`qty_per_harness` at least 1, `qty_ordered` at least 1, `qty_received` at least 1, `planned_end_at` strictly after `planned_start_at`, `expires_at` strictly after `issued_at`, `wire_gauge_awg` an integer between 12 and 26 inclusive, cost-per-piece fields at least 0, cut and strip lengths strictly greater than 0, `opens_count` at least 0). Violations yield `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/c_drawing_missing_required_field_returns_invalid_request
        """
        resp = api.create_drawing(
            {"drawing_number": "DWG-E2", "customer_code": "ACME", "revision": "A"},
            ENG,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_drawing_not_found_returns_404(self, api):
        """PRD §2.4: "When a request references resources by identifier — whether in the path or in the body — each identifier must resolve to an existing resource; the first unresolvable identifier, validated left-to-right, yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/c_get_drawing_not_found_returns_404
        """
        resp = api.get_drawing(NON_EXISTENT_UUID, ENG)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestComponentCatalogue:
    def test_components_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "The `offset` parameter sets the number of items skipped and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`."
        PRD §3.1: "The component catalogue is listable with an optional `drawing_id` filter."

        Design: Corner/entities/c_components_list_pagination_envelope
        """
        drawing = make_drawing(api, drawing_number="DWG-E4")
        for i in range(11):
            make_component(
                api,
                drawing_id=drawing["id"],
                find_number=f"F{i:02d}",
                component_type="WIRE",
                mpn="WIRE-1",
                qty_per_harness=1,
                supply_type="FACTORY_STOCK",
                unit_cost_cents=10,
            )
        page1 = api.list_components(ENG, params={"drawing_id": drawing["id"]})
        data1, meta1 = validate_paginated(page1)
        assert meta1["limit"] == 10, f"default limit must be 10: {meta1}"
        assert meta1["offset"] == 0, f"default offset must be 0: {meta1}"
        assert meta1["total_count"] == 11, f"total_count must be 11: {meta1}"
        assert meta1["has_more"] is True, f"page 1 of 11 rows must have has_more: {meta1}"
        assert len(data1) == 10, f"page 1 carries the default page of 10: {len(data1)}"
        for row in data1:
            assert_drawing_component(row)
        page2 = api.list_components(ENG, params={"drawing_id": drawing["id"], "offset": 10})
        data2, meta2 = validate_paginated(page2)
        assert len(data2) == 1, f"offset 10 returns the 11th row only: {len(data2)}"
        assert meta2["has_more"] is False, f"last page must report has_more false: {meta2}"

    def test_component_invalid_enum_rejected(self, api):
        """PRD §3.1: "Each component line carries the `drawing_id` it belongs to, a `find_number` (unique within that drawing — adding a second line with the same `find_number` on the same drawing is rejected with `ERR_DUPLICATE_FIND_NUMBER`), a `component_type` of `CONNECTOR`, `TERMINAL`, `WIRE`, `SEAL`, or `SLEEVE`, the manufacturer part number `mpn`, a `qty_per_harness` of at least 1, a `supply_type` declaring the line `FACTORY_STOCK` or `CUSTOMER_CONSIGNED`, and a `unit_cost_cents` of at least 0."
        PRD §2.6: "the body parses as JSON; declared input fields are present with correct types; enum values fall in their declared sets; conditional requirements hold (`opens_count` is required when `test_type` is `CONTINUITY`; `hipot_voltage_v`, `dwell_seconds`, `measured_leakage_ua`, and `leakage_limit_ua` are required when `test_type` is `HIPOT`); and field constraints hold (`qty_per_harness` at least 1, `qty_ordered` at least 1, `qty_received` at least 1, `planned_end_at` strictly after `planned_start_at`, `expires_at` strictly after `issued_at`, `wire_gauge_awg` an integer between 12 and 26 inclusive, cost-per-piece fields at least 0, cut and strip lengths strictly greater than 0, `opens_count` at least 0). Violations yield `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/c_component_invalid_enum_rejected
        """
        drawing = make_drawing(api, drawing_number="DWG-E5")
        resp = api.create_component(
            {
                "drawing_id": drawing["id"],
                "find_number": "X1",
                "component_type": "PLASTIC",
                "mpn": "M-1",
                "qty_per_harness": 1,
                "supply_type": "FACTORY_STOCK",
                "unit_cost_cents": 10,
            },
            ENG,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_component_fk_drawing_not_found(self, api):
        """PRD §2.4: "When a request references resources by identifier — whether in the path or in the body — each identifier must resolve to an existing resource; the first unresolvable identifier, validated left-to-right, yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/c_component_fk_drawing_not_found
        """
        resp = api.create_component(
            {
                "drawing_id": NON_EXISTENT_UUID,
                "find_number": "X1",
                "component_type": "WIRE",
                "mpn": "W-1",
                "qty_per_harness": 1,
                "supply_type": "FACTORY_STOCK",
                "unit_cost_cents": 10,
            },
            ENG,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_duplicate_find_number_rejected_per_drawing(self, api):
        """PRD §3.1: "Each component line carries the `drawing_id` it belongs to, a `find_number` (unique within that drawing — adding a second line with the same `find_number` on the same drawing is rejected with `ERR_DUPLICATE_FIND_NUMBER`), a `component_type` of `CONNECTOR`, `TERMINAL`, `WIRE`, `SEAL`, or `SLEEVE`, the manufacturer part number `mpn`, a `qty_per_harness` of at least 1, a `supply_type` declaring the line `FACTORY_STOCK` or `CUSTOMER_CONSIGNED`, and a `unit_cost_cents` of at least 0."

        Design: Corner/validations/c_duplicate_find_number_rejected
        """
        drawing1 = make_drawing(api, drawing_number="DWG-V7A")
        drawing2 = make_drawing(api, drawing_number="DWG-V7B")
        make_component(api, drawing_id=drawing1["id"], find_number="F1",
                       component_type="WIRE", mpn="W-1", unit_cost_cents=10)
        resp = api.create_component(
            {
                "drawing_id": drawing1["id"],
                "find_number": "F1",
                "component_type": "WIRE",
                "mpn": "W-2",
                "qty_per_harness": 2,
                "supply_type": "FACTORY_STOCK",
                "unit_cost_cents": 20,
            },
            ENG,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_FIND_NUMBER)
        ok = api.create_component(
            {
                "drawing_id": drawing2["id"],
                "find_number": "F1",
                "component_type": "WIRE",
                "mpn": "W-2",
                "qty_per_harness": 2,
                "supply_type": "FACTORY_STOCK",
                "unit_cost_cents": 20,
            },
            ENG,
        )
        data = validate_success(ok, 201)
        assert_drawing_component(data)
        assert data["drawing_id"] == drawing2["id"], "uniqueness is scoped per drawing"


class TestDrawingReleaseAndSupersession:
    def test_drawing_release_gates(self, api):
        """PRD §3.1: "Release is refused with `ERR_DRAWING_EMPTY_BOM` when the drawing has no component lines, and with `ERR_DRAWING_NOT_DRAFT` when the drawing is not in `DRAFT`."
        PRD §3.1: "Component lines may only be added to a `DRAFT` drawing; the attempt on a drawing in any other status is rejected with `ERR_DRAWING_NOT_DRAFT`."
        PRD §3.1: "Releasing a drawing moves it `DRAFT → RELEASED`, stamps `released_at` from the logical clock, and increments its `version`."

        Design: Corner/state_machines/c_drawing_release_gates
        """
        drawing = make_drawing(api, drawing_number="DWG-S1")
        empty = api.release_drawing(drawing["id"], ENG)
        validate_error(empty, ApiErrorId.ERR_DRAWING_EMPTY_BOM)
        make_component(api, drawing_id=drawing["id"], find_number="T1",
                       component_type="TERMINAL", mpn="TERM-20", unit_cost_cents=100)
        released = api.release_drawing(drawing["id"], ENG)
        data = validate_success(released, 200)
        assert data["status"] == "RELEASED", f"drawing must be RELEASED after release: {data}"
        again = api.release_drawing(drawing["id"], ENG)
        validate_error(again, ApiErrorId.ERR_DRAWING_NOT_DRAFT)
        add_after_release = api.create_component(
            {
                "drawing_id": drawing["id"],
                "find_number": "T2",
                "component_type": "TERMINAL",
                "mpn": "TERM-21",
                "qty_per_harness": 1,
                "supply_type": "FACTORY_STOCK",
                "unit_cost_cents": 100,
            },
            ENG,
        )
        validate_error(add_after_release, ApiErrorId.ERR_DRAWING_NOT_DRAFT)

    def test_superseded_drawing_terminal_lockdown(self, api):
        """PRD §3.1: "A released drawing leaves `RELEASED` only by supersession through an applied engineering change notice (§3.8), which moves it to the terminal `SUPERSEDED` status and stamps `superseded_at`."
        PRD §3.1: "Only a `RELEASED` drawing may anchor downstream work: creating a machine program, a build order, or an engineering change notice against a drawing that is not `RELEASED` is rejected with `ERR_DRAWING_NOT_RELEASED`."
        PRD §3.1: "Release is refused with `ERR_DRAWING_EMPTY_BOM` when the drawing has no component lines, and with `ERR_DRAWING_NOT_DRAFT` when the drawing is not in `DRAFT`."
        PRD §3.8: "A new harness drawing is created at the `to_revision` — its `drawing_number`, `customer_code`, and `workmanship_class` copied from the old drawing, its status `DRAFT`, and every component row of the old drawing copied onto it — and the ECN's `new_drawing_id` points at it."

        Design: Corner/state_machines/c_superseded_drawing_terminal_lockdown
        """
        drawing = make_drawing(api, drawing_number="DWG-S2", revision="A")
        make_component(api, drawing_id=drawing["id"], find_number="T1",
                       component_type="TERMINAL", mpn="TERM-20", unit_cost_cents=100)
        release_drawing(api, drawing["id"])
        applicator = validate_success(
            api.create_applicator(
                {"applicator_code": "AP-S2", "compatible_terminal_mpn": "TERM-20"}, PROC
            ),
            201,
        )
        ecn = validate_success(
            api.create_ecn(
                {"ecn_code": "ECN-S2", "drawing_id": drawing["id"],
                 "to_revision": "B", "wip_disposition": "USE_AS_IS"},
                ENG,
            ),
            201,
        )
        applied = validate_success(api.apply_ecn(ecn["id"], ENG), 200)
        new_drawing_id = applied["new_drawing_id"]
        assert new_drawing_id, "applied ECN must point at the new revision row"

        re_release = api.release_drawing(drawing["id"], ENG)
        validate_error(re_release, ApiErrorId.ERR_DRAWING_NOT_DRAFT)
        program = api.create_machine_program(
            {
                "program_code": "PG-S2",
                "drawing_id": drawing["id"],
                "applicator_id": applicator["id"],
                "wire_gauge_awg": 20,
                "wire_type": "TXL",
                "cut_length_mm": 500.0,
                "strip_length_mm": 5.0,
                "terminal_mpn": "TERM-20",
                "terminal_type": "OPEN_BARREL",
            },
            PROC,
        )
        validate_error(program, ApiErrorId.ERR_DRAWING_NOT_RELEASED)
        order = api.create_build_order(
            {"order_code": "BO-S2", "drawing_id": drawing["id"], "qty_ordered": 1}, PLAN
        )
        validate_error(order, ApiErrorId.ERR_DRAWING_NOT_RELEASED)
        new_drawing = validate_success(api.get_drawing(new_drawing_id, ENG), 200)
        assert_harness_drawing(new_drawing)
        assert new_drawing["status"] == "DRAFT", f"new revision row is born DRAFT: {new_drawing}"
        assert new_drawing["revision"] == "B", f"new revision row carries to_revision: {new_drawing}"


class TestProgramCreationDrawingGate:
    def test_program_create_on_draft_drawing_rejected(self, api):
        """PRD §3.1: "Only a `RELEASED` drawing may anchor downstream work: creating a machine program, a build order, or an engineering change notice against a drawing that is not `RELEASED` is rejected with `ERR_DRAWING_NOT_RELEASED`."

        Design: Difficulty/cross_entity_state_dependency/program_creation_gated_by_drawing_release
        """
        drawing = make_drawing(api, drawing_number="DWG-CE2")
        make_component(api, drawing_id=drawing["id"], find_number="T1",
                       component_type="TERMINAL", mpn="TERM-20", unit_cost_cents=100)
        applicator = validate_success(
            api.create_applicator(
                {"applicator_code": "AP-CE2", "compatible_terminal_mpn": "TERM-20"}, PROC
            ),
            201,
        )
        resp = api.create_machine_program(
            {
                "program_code": "PG-CE2",
                "drawing_id": drawing["id"],
                "applicator_id": applicator["id"],
                "wire_gauge_awg": 20,
                "wire_type": "TXL",
                "cut_length_mm": 500.0,
                "strip_length_mm": 5.0,
                "terminal_mpn": "TERM-20",
                "terminal_type": "OPEN_BARREL",
            },
            PROC,
        )
        validate_error(resp, ApiErrorId.ERR_DRAWING_NOT_RELEASED)

    def test_program_create_succeeds_after_release(self, api):
        """PRD §3.1: "Only a `RELEASED` drawing may anchor downstream work: creating a machine program, a build order, or an engineering change notice against a drawing that is not `RELEASED` is rejected with `ERR_DRAWING_NOT_RELEASED`."
        PRD §3.2: "A program is born in `DRAFT`. Creation also computes the program's minimum crimp pull force, `min_pull_force_n`."
        PRD §3.2: "The computation starts from a base force looked up by wire gauge: 15.0 newtons for gauges 26, 25, and 24; 30.0 newtons for gauges 23, 22, 21, and 20; 50.0 newtons for gauges 19, 18, 17, and 16; and 80.0 newtons for gauges 15, 14, 13, and 12."

        Design: Difficulty/cross_entity_state_dependency/program_creation_gated_by_drawing_release
        """
        drawing = make_drawing(api, drawing_number="DWG-CE2", workmanship_class="IPC_CLASS_2")
        make_component(api, drawing_id=drawing["id"], find_number="T1",
                       component_type="TERMINAL", mpn="TERM-20", unit_cost_cents=100)
        applicator = validate_success(
            api.create_applicator(
                {"applicator_code": "AP-CE2", "compatible_terminal_mpn": "TERM-20"}, PROC
            ),
            201,
        )
        release_drawing(api, drawing["id"])
        resp = api.create_machine_program(
            {
                "program_code": "PG-CE2",
                "drawing_id": drawing["id"],
                "applicator_id": applicator["id"],
                "wire_gauge_awg": 20,
                "wire_type": "TXL",
                "cut_length_mm": 500.0,
                "strip_length_mm": 5.0,
                "terminal_mpn": "TERM-20",
                "terminal_type": "OPEN_BARREL",
            },
            PROC,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT", f"program is born DRAFT: {data}"
        # AWG 20 -> base 30.0; OPEN_BARREL derating 1.0; IPC_CLASS_2 multiplier 1.0 -> 30.0 N.
        assert data["min_pull_force_n"] == pytest.approx(30.0, abs=0.01), (
            f"class-2/AWG-20/OPEN_BARREL minimum must compute to 30.0 N: {data}"
        )
