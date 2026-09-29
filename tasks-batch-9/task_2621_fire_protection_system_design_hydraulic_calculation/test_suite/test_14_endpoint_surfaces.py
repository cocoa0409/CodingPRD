"""Endpoint surfaces: the read channels, the path-owned association and the ledger read."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import (
    assert_demand_ledger,
    assert_flow,
    assert_money,
    assert_posture,
    assert_pressure,
    assert_sheet_counters,
)
from test_helpers.factories import (
    build_hydraulic_calculation_payload,
    build_trade_clearance_payload,
)
from test_helpers.fixtures import (
    ADMIN_HEADERS,
    CONTRACTOR_HEADERS,
    STANDPIPE_DEMAND_GPM,
    build_project_stage,
    build_sealed_stage,
    create_auxiliary_system,
    create_flow_test,
    create_hazard_area,
    create_project,
    create_shop_drawing,
    read_project,
    read_shop_drawing,
    read_trade_clearance,
    record_clearance,
)
from test_helpers.test_users import make_design_engineer_headers

H14 = dict(
    hydrant_tag="H-14", static_psi=80.0, residual_psi=64.0, flow_gpm=2250.0,
    tested_at="2026-05-14T15:00:00.000Z",
)
H15 = dict(
    hydrant_tag="H-15", static_psi=78.0, residual_psi=60.0, flow_gpm=2100.0,
    tested_at="2026-05-15T15:00:00.000Z",
)
H16 = dict(
    hydrant_tag="H-16", static_psi=76.0, residual_psi=58.0, flow_gpm=2050.0,
    tested_at="2026-05-16T15:00:00.000Z",
)
H90 = dict(
    hydrant_tag="H-90", static_psi=60.0, residual_psi=44.0, flow_gpm=1800.0,
    tested_at="2026-05-17T15:00:00.000Z",
)
SECOND_PROJECT = dict(
    project_number="FP-2602", building_name="Second Street Warehouse"
)


def _two_projects_four_hydrants(client):
    """Three tests on FP-2601 and one on a sibling project sharing the same engineer."""
    ctx = build_project_stage(client)
    ctx["second_project_id"] = create_project(
        client, ctx["lead_id"], ctx["reviewer_id"], **SECOND_PROJECT
    )["id"]
    ctx["tests"] = [
        create_flow_test(client, ctx["project_id"], ctx["lead_id"], **hydrant)
        for hydrant in (H14, H15, H16)
    ]
    ctx["other_test"] = create_flow_test(
        client, ctx["second_project_id"], ctx["lead_id"], **H90
    )
    return ctx


class TestFlowTestReadChannel:
    def test_01_the_project_scoped_list_returns_the_three_hydrants_as_recorded(self, client):
        """A flow test is immutable once recorded, and every test taken for a project can be
        listed from the project.

        Design: Corner/endpoints/flow_test_crud_surface_is_create_read_and_a_filtered_project_scoped_list
        """
        ctx = _two_projects_four_hydrants(client)
        rows, meta = validate_paginated(
            client.list_project_flow_tests(ctx["project_id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert [row["id"] for row in rows] == [row["id"] for row in ctx["tests"]]

        recorded = rows[0]
        assert recorded["hydrant_tag"] == "H-14"
        assert_pressure(recorded["static_psi"], 80.0)
        assert_pressure(recorded["residual_psi"], 64.0)
        assert_flow(recorded["flow_gpm"], 2250.0)
        assert str(recorded["tested_at"]).startswith("2026-05-14T15:00:00")

    def test_02_a_flow_test_row_carries_no_version_and_no_update_route(self, client):
        """Four record types are deliberately append-only or reference-only and therefore carry
        **only** `id` and `created_at`, with both `updated_at` and `version` absent from their
        representations ... the `FlowTest` field record.

        Design: Corner/endpoints/flow_test_crud_surface_is_create_read_and_a_filtered_project_scoped_list
        """
        ctx = _two_projects_four_hydrants(client)
        rows, _ = validate_paginated(
            client.list_project_flow_tests(ctx["project_id"], ADMIN_HEADERS)
        )
        for row in rows:
            assert "version" not in row
            assert "updated_at" not in row
            assert "created_at" in row
            assert "id" in row

    def test_03_the_tail_page_reports_the_full_count_with_nothing_beyond_it(self, client):
        """List responses carry `limit`, `offset`, `total_count` and `has_more` in the `meta`
        object, where `total_count` counts every row matching the filters before pagination is
        applied and `has_more` is true when rows remain beyond the current page.

        Design: Corner/endpoints/flow_test_crud_surface_is_create_read_and_a_filtered_project_scoped_list
        """
        ctx = _two_projects_four_hydrants(client)
        rows, meta = validate_paginated(
            client.list_project_flow_tests(
                ctx["project_id"], ADMIN_HEADERS, params={"limit": 2, "offset": 2}
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 3
        assert meta["limit"] == 2
        assert meta["offset"] == 2
        assert meta["has_more"] is False
        assert rows[0]["id"] == ctx["tests"][2]["id"]

    def test_04_the_list_is_scoped_by_the_project_in_the_path(self, client):
        """Each list endpoint accepts filters for the foreign keys of the resource it lists, so
        no relationship in the model is write-only: flow tests are reachable by project.

        Design: Corner/endpoints/flow_test_crud_surface_is_create_read_and_a_filtered_project_scoped_list
        """
        ctx = _two_projects_four_hydrants(client)
        rows, meta = validate_paginated(
            client.list_project_flow_tests(ctx["second_project_id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [ctx["other_test"]["id"]]
        assert rows[0]["hydrant_tag"] == "H-90"


class TestTradeClearanceLinkIsPathOwned:
    def test_05_an_unknown_sheet_in_the_path_is_a_not_found_before_any_write(self, client):
        """Every `{id}` path parameter resolves to an existing row, validated left to right
        along the path — the matching one of ... `ERR_SHOP_DRAWING_NOT_FOUND` ... (404).

        Design: Corner/endpoints/trade_clearance_link_requires_the_sheet_and_shows_up_on_both_sides
        """
        ctx = build_sealed_stage(client)
        sheet = create_shop_drawing(client, ctx["project_id"], ctx["calculation_id"])

        refused = client.create_trade_clearance(
            NON_EXISTENT_UUID,
            build_trade_clearance_payload(
                trade="STRUCTURAL", elevation_low_in=96.0, elevation_high_in=120.0
            ),
            CONTRACTOR_HEADERS,
        )
        validate_error(refused, "ERR_SHOP_DRAWING_NOT_FOUND", expected_status=404)

        items, meta = validate_paginated(
            client.list_trade_clearances(sheet["id"], CONTRACTOR_HEADERS)
        )
        assert meta["total_count"] == 0
        assert items == []

    def test_06_the_new_item_is_visible_from_the_row_and_from_the_sheet(self, client):
        """A coordination item is opened per trade, and each item carries the
        `shop_drawing_id` of the sheet it belongs to.

        Design: Corner/endpoints/trade_clearance_link_requires_the_sheet_and_shows_up_on_both_sides
        """
        ctx = build_sealed_stage(client)
        sheet = create_shop_drawing(client, ctx["project_id"], ctx["calculation_id"])

        item = validate_success(
            client.create_trade_clearance(
                sheet["id"],
                build_trade_clearance_payload(
                    trade="STRUCTURAL", elevation_low_in=96.0, elevation_high_in=120.0
                ),
                CONTRACTOR_HEADERS,
            ),
            expected_status=201,
        )
        assert item["shop_drawing_id"] == sheet["id"]
        assert item["trade"] == "STRUCTURAL"
        assert item["state"] == "PENDING"

        listed, meta = validate_paginated(
            client.list_trade_clearances(sheet["id"], CONTRACTOR_HEADERS)
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in listed] == [item["id"]]

        # Opening an item does not clear a trade.
        assert_sheet_counters(read_shop_drawing(client, sheet["id"]), "IN_COORDINATION", 0)

    def test_07_only_recording_the_outcome_moves_the_sheet_counter(self, client):
        """A clearance that leaves `cleared_trade_count` short of `required_trade_count` moves
        the sheet to `IN_COORDINATION`.

        Design: Corner/endpoints/trade_clearance_link_requires_the_sheet_and_shows_up_on_both_sides
        """
        ctx = build_sealed_stage(client)
        sheet = create_shop_drawing(client, ctx["project_id"], ctx["calculation_id"])
        item = validate_success(
            client.create_trade_clearance(
                sheet["id"],
                build_trade_clearance_payload(
                    trade="STRUCTURAL", elevation_low_in=96.0, elevation_high_in=120.0
                ),
                CONTRACTOR_HEADERS,
            ),
            expected_status=201,
        )
        assert_sheet_counters(read_shop_drawing(client, sheet["id"]), "IN_COORDINATION", 0)

        recorded = record_clearance(
            client, item["id"], ctx["lead_id"],
            outcome="CLEARED", note="Coordinated in the field",
        )
        assert recorded["state"] == "CLEARED"
        assert read_trade_clearance(client, sheet["id"], item["id"])["state"] == "CLEARED"
        # One trade of three: the sheet counts it but is not coordinated yet.
        assert_sheet_counters(read_shop_drawing(client, sheet["id"]), "IN_COORDINATION", 1)


OFFICE_ROOM = dict(
    label="Compliant office room", hazard_class="ORDINARY_1", commodity_class="CLASS_III",
    storage_height_ft=8.0, ceiling_height_ft=12.0, area_sqft=1800.0,
    sprinkler_system_type="WET", ceiling_slope_pct=4.0, room_area_sqft=1200.0,
    enclosure_rating_hours=2.0, room_has_unprotected_opening=False,
)
KITCHEN_HOOD = dict(
    system_type="COOKING", label="Kitchen hood line", appliance_count=4,
    water_wash_enabled=True, agent_type="WET_CHEMICAL",
)


def _sealed_plus_a_draft_office_calculation(client):
    """HC-1 sealed, a second calculation left in DRAFT, and a second auxiliary system."""
    ctx = build_sealed_stage(client)
    office = create_hazard_area(client, ctx["project_id"], ctx["lead_id"], **OFFICE_ROOM)
    ctx["office_calculation"] = validate_success(
        client.create_hydraulic_calculation(
            build_hydraulic_calculation_payload(
                project_id=ctx["project_id"], hazard_area_id=office["id"],
                method="ROOM_DESIGN", k_factor=25.2,
            ),
            make_design_engineer_headers(ctx["lead_id"]),
        ),
        expected_status=201,
    )
    ctx["hood"] = create_auxiliary_system(
        client, ctx["project_id"], ctx["lead_id"], **KITCHEN_HOOD
    )
    return ctx


class TestProjectReadReturnsTheWholeLedger:
    def test_08_the_governing_selection_ignores_the_draft_calculation(self, client):
        """First, the eligible set is pinned by state: only calculations of this project in
        `CONVERGED`, `QC_PASSED` or `SEALED` are eligible. Calculations in `DRAFT`, `ITERATING`,
        `PRESSURE_DEFICIENT`, `REOPENED` or `ARCHIVED` are excluded.

        Design: Corner/endpoints/project_read_returns_every_derived_ledger_field_in_one_shot
        """
        ctx = _sealed_plus_a_draft_office_calculation(client)
        office = ctx["office_calculation"]
        assert office["state"] == "DRAFT"
        assert_flow(office["hazard_total_demand_gpm"], 448.0)

        project = read_project(client, ctx["project_id"])
        assert project["governing_hydraulic_calculation_id"] == ctx["calculation_id"]
        assert_flow(project["governing_demand_gpm"], 1380.0)

    def test_09_the_auxiliary_roll_up_and_the_total_agree_in_one_read(self, client):
        """Finally `total_system_demand_gpm` is `governing_demand_gpm` plus
        `auxiliary_demand_gpm`, rounded to 1 decimal place.

        Design: Corner/endpoints/project_read_returns_every_derived_ledger_field_in_one_shot
        """
        ctx = _sealed_plus_a_draft_office_calculation(client)
        assert_flow(ctx["hood"]["demand_gpm"], 160.0)

        project = read_project(client, ctx["project_id"])
        assert_demand_ledger(project, ctx["calculation_id"], 1380.0, 910.0, 2290.0)
        assert_flow(ctx["standpipe"]["demand_gpm"], STANDPIPE_DEMAND_GPM)

    def test_10_the_same_read_carries_the_counters_the_posture_derives_from(self, client):
        """... otherwise, when `open_major_comment_count` is greater than zero the posture is
        `GATED`; otherwise the posture is `OPEN`.

        Design: Corner/endpoints/project_read_returns_every_derived_ledger_field_in_one_shot
        """
        ctx = _sealed_plus_a_draft_office_calculation(client)
        project = read_project(client, ctx["project_id"])
        assert project["sealed_calculation_count"] == 1
        assert project["open_major_comment_count"] == 0
        assert_posture(project, "OPEN")
        assert_money(project["review_fee_balance_usd"], 0.00)
        assert project["submittal_cycle_count"] == 0
        assert project["pump_required_flag"] is False
