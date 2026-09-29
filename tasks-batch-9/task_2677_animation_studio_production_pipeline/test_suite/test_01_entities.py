"""Entity-level contract tests: defaults, retrieval, listing and input handling."""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_POOL_NOT_FOUND,
    ERR_PRODUCTION_NOT_FOUND,
    ERR_VALIDATION,
)
from test_helpers.assertions import (
    assert_cents,
    assert_common_fields,
    assert_two_decimal,
)
from test_helpers.constants import (
    CLOCK_START,
    COLOR_ACESCG,
    GATE_DRAFT,
    GATE_TYPES_CANONICAL,
    PHASE_PRE_PRODUCTION,
    SHOT_BLOCKED_PREPROD,
)
from test_helpers.test_users import (
    ARTIST_HEADERS,
    PRODUCTION_MANAGER_HEADERS,
    SUPERVISOR_HEADERS,
)

NON_EXISTENT_ID = "00000000-0000-0000-0000-000000000000"


class TestProductionCreation:
    def test_create_applies_optional_defaults_and_materializes_the_gate_set(self, client):
        """A create carrying only the required inputs defaults the contingency, the
        approved color spaces and the gate set, and materializes four DRAFT gates.

        PRD: "`contingency_pct` is the fraction of the budget released as a contingency
        reserve; it defaults to 0.10, carries two decimal places, and must be between 0
        and 0.50 inclusive."
        PRD: "Each gate is stamped with the owning `production_id`, its `gate_type`, and
        a `sequence_index` assigned by walking the canonical order and numbering
        consecutively from 1 — so for the default full set `SCRIPT` is 1, `STORYBOARD` is
        2, `ANIMATIC` is 3 and `DESIGN` is 4."

        Design: Corner/entities/production_create_applies_defaults_and_materializes_four_gates
        """
        response = client.create_production(
            {
                "title": "Aurora Drift",
                "production_code": "AD01",
                "format": "FEATURE",
                "budget_cents": 100000000,
                "render_allowance_cents": 5000000,
                "master_color_space": COLOR_ACESCG,
            },
            PRODUCTION_MANAGER_HEADERS,
        )
        production = validate_success(response, 201)
        assert response.json()["response_type"] == "object"

        assert_two_decimal(production["contingency_pct"], 0.10, "contingency_pct")
        assert production["approved_color_spaces"] == [COLOR_ACESCG]
        assert production["gate_types"] == GATE_TYPES_CANONICAL
        assert production["phase"] == PHASE_PRE_PRODUCTION
        assert_cents(production["available_cents"], 110000000, "available_cents")
        assert_common_fields(production, expected_version=1)

        gate_response = client.list_gates(
            PRODUCTION_MANAGER_HEADERS, {"production_id": production["id"]}
        )
        gates, meta = validate_paginated(gate_response)
        assert meta["total_count"] == 4
        assert meta["has_more"] is False
        assert len(gates) == 4
        assert gates[0]["gate_type"] == "SCRIPT"
        assert gates[0]["sequence_index"] == 1
        assert gates[0]["status"] == GATE_DRAFT
        assert gates[3]["gate_type"] == "DESIGN"
        assert gates[3]["sequence_index"] == 4

    def test_create_without_master_color_space_persists_nothing(self, client):
        """Omitting the mandatory master color space is a schema violation and leaves
        neither a production nor a partially materialized gate set behind.

        PRD: "Required fields are present, types are correct, enum members are legal, and
        numeric ranges are respected."

        Design: Corner/entities/production_create_missing_master_color_space_rejects
        """
        response = client.create_production(
            {
                "title": "Aurora Drift",
                "production_code": "AD01",
                "format": "FEATURE",
                "budget_cents": 100000000,
                "render_allowance_cents": 5000000,
            },
            PRODUCTION_MANAGER_HEADERS,
        )
        validate_error(response, ERR_VALIDATION, 422)

        _, production_meta = validate_paginated(
            client.list_productions(PRODUCTION_MANAGER_HEADERS)
        )
        assert production_meta["total_count"] == 0
        _, gate_meta = validate_paginated(client.list_gates(PRODUCTION_MANAGER_HEADERS))
        assert gate_meta["total_count"] == 0


class TestScreeningRoomRetrieval:
    def test_read_echoes_stored_inputs_and_derives_calibration_status(self, client):
        """A read of a freshly registered room echoes its stored inputs, applies both
        optional defaults, and derives the calibration status from a null calibration.

        PRD: "A freshly registered room has a null `last_calibrated_at` and therefore a
        `calibration_status` of `UNCALIBRATED`, and it cannot host anything until it is
        calibrated."
        PRD: "Two optional fields tune the room's behaviour: `turnover_buffer_minutes`,
        the mandatory idle time between two sessions in the room, which defaults to 30
        minutes and may not be negative; and `calibration_valid_days`, the number of days
        a projector calibration stays good for, which defaults to 30 and must be at least
        1."

        Design: Corner/entities/screening_room_get_returns_stored_row_with_derived_calibration_status
        """
        room = fx.create_room(
            client, name="STAGE-1", seat_capacity=12, room_color_space=COLOR_ACESCG
        )

        stored = validate_success(
            client.get_screening_room(room["id"], PRODUCTION_MANAGER_HEADERS)
        )
        assert stored["name"] == "STAGE-1"
        assert stored["seat_capacity"] == 12
        assert stored["room_color_space"] == COLOR_ACESCG
        assert stored["turnover_buffer_minutes"] == 30
        assert stored["calibration_valid_days"] == 30
        assert stored["calibration_status"] == "UNCALIBRATED"
        assert stored["last_calibrated_at"] is None


class TestShotListing:
    def test_production_filter_is_applied_before_the_page_window(self, client):
        """A filtered shot listing reports the matching row count and pages through it in
        shot-code order without leaking a shot of another production.

        PRD: "Paginated responses carry four additional keys inside `meta`: the effective
        `limit`, the effective `offset`, `total_count` (the number of rows matching the
        filters before the page window is applied) and `has_more` (true when rows remain
        beyond the current page)."

        Design: Corner/entities/shot_list_filters_by_production_and_paginates
        """
        production_a = fx.open_production(
            client, title="Aurora Drift", production_code="AD01"
        )
        production_b = fx.open_production(
            client,
            title="Copper Skies",
            production_code="AD02",
            format="SERIES_EPISODE",
            budget_cents=60000000,
            render_allowance_cents=4000000,
        )
        for code, sequence, frames, budget in (
            ("AD01_010_0010", "010", 120, 1000000),
            ("AD01_010_0020", "010", 120, 1000000),
            ("AD01_020_0010", "020", 60, 500000),
        ):
            fx.create_shot(
                client,
                production_a["id"],
                shot_code=code,
                sequence_code=sequence,
                frame_count=frames,
                budget_cents=budget,
                planned_start_at=CLOCK_START,
                planned_finish_at="2026-09-30T00:00:00Z",
            )
        fx.create_shot(
            client,
            production_b["id"],
            shot_code="AD02_010_0010",
            sequence_code="010",
            frame_count=96,
            budget_cents=800000,
            planned_start_at=CLOCK_START,
            planned_finish_at="2026-09-30T00:00:00Z",
        )

        first_page, first_meta = validate_paginated(
            client.list_shots(
                SUPERVISOR_HEADERS,
                {"production_id": production_a["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True
        assert first_page[0]["shot_code"] == "AD01_010_0010"
        assert first_page[1]["shot_code"] == "AD01_010_0020"

        second_page, second_meta = validate_paginated(
            client.list_shots(
                SUPERVISOR_HEADERS,
                {"production_id": production_a["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(second_page) == 1
        assert second_page[0]["shot_code"] == "AD01_020_0010"
        assert second_meta["total_count"] == 3
        assert second_meta["offset"] == 2
        assert second_meta["has_more"] is False

        listed_codes = [row["shot_code"] for row in first_page + second_page]
        assert "AD02_010_0010" not in listed_codes


class TestRenderPoolRetrieval:
    def test_unknown_pool_id_reports_a_typed_not_found(self, client):
        """A syntactically valid but unknown pool id on the scalar read reports the
        pool-specific not-found error and leaves the collection untouched.

        PRD: "Every identifier in the request path resolves to a stored row, validated
        **left to right** so that the leftmost unresolvable identifier is the one
        reported."

        Design: Corner/entities/render_pool_get_unknown_id_returns_not_found
        """
        fx.create_pool(client, name="FARM-A", total_cores=100, cost_per_core_hour_cents=175)

        response = client.get_render_pool(NON_EXISTENT_ID, PRODUCTION_MANAGER_HEADERS)
        error = validate_error(response, ERR_POOL_NOT_FOUND, 404)
        assert isinstance(error["message"], str) and error["message"]
        assert response.json()["response_type"] == "error"

        _, meta = validate_paginated(client.list_render_pools(PRODUCTION_MANAGER_HEADERS))
        assert meta["total_count"] == 1


class TestShotCreationInputHandling:
    def test_client_supplied_system_fields_are_ignored(self, client):
        """Identity, version, status and the earned-value figures are server-owned, so
        supplying them in the create body changes nothing and raises no error.

        PRD: "`id` is a server-minted UUID with no type prefix; clients never supply it."
        PRD: "Unknown fields are ignored rather than rejected."

        Design: Corner/entities/shot_create_system_fields_input_ignored
        """
        production = fx.open_production(client, title="Aurora Drift", production_code="AD01")

        response = client.create_shot(
            {
                "production_id": production["id"],
                "shot_code": "AD01_010_0010",
                "sequence_code": "010",
                "frame_count": 120,
                "budget_cents": 1000000,
                "planned_start_at": CLOCK_START,
                "planned_finish_at": "2026-09-30T00:00:00Z",
                "id": "shot-i-picked",
                "status": "COMPLETE",
                "bcwp_cents": 999999,
                "retake_count": 7,
                "version": 42,
            },
            PRODUCTION_MANAGER_HEADERS,
        )
        shot = validate_success(response, 201)
        assert shot["id"] != "shot-i-picked"
        assert shot["status"] == SHOT_BLOCKED_PREPROD
        assert_cents(shot["bcwp_cents"], 0, "bcwp_cents")
        assert shot["retake_count"] == 0
        assert_common_fields(shot, expected_version=1)

    def test_unknown_production_id_is_a_not_found_while_a_valid_one_seeds_five_stages(
        self, client
    ):
        """A body foreign key that does not resolve reports a typed not-found, and a
        resolving one materializes the five stage tasks in stage order.

        PRD: "Every foreign key in the request body resolves to a stored row, validated
        in the order the fields are declared in that endpoint's input list; an array of
        foreign keys such as `stage_task_ids` is validated element by element in array
        order, so the first unresolvable element is the one reported."
        PRD: "Each task is stamped with the owning `shot_id`, its `stage` — which occurs
        exactly once per `shot_id` — a `stage_order` of 1 through 5 following that same
        order, and its `stage_weight_pct` — 0.10 for `LAYOUT`, 0.40 for `ANIMATION`, 0.15
        for `EFFECTS`, 0.15 for `LIGHTING` and 0.20 for `COMP`, which together sum to
        exactly 1.00."

        Design: Corner/entities/shot_create_with_unknown_production_id_returns_not_found
        """
        production = fx.open_production(client, title="Aurora Drift", production_code="AD01")
        shot_body = {
            "shot_code": "AD01_010_0010",
            "sequence_code": "010",
            "frame_count": 120,
            "budget_cents": 1000000,
            "planned_start_at": CLOCK_START,
            "planned_finish_at": "2026-09-30T00:00:00Z",
        }

        rejected = client.create_shot(
            dict(shot_body, production_id=NON_EXISTENT_ID), PRODUCTION_MANAGER_HEADERS
        )
        validate_error(rejected, ERR_PRODUCTION_NOT_FOUND, 404)

        shot = validate_success(
            client.create_shot(
                dict(shot_body, production_id=production["id"]), PRODUCTION_MANAGER_HEADERS
            ),
            201,
        )

        tasks, meta = validate_paginated(
            client.list_stage_tasks(PRODUCTION_MANAGER_HEADERS, {"shot_id": shot["id"]})
        )
        assert meta["total_count"] == 5
        assert len(tasks) == 5
        assert tasks[0]["stage"] == "LAYOUT"
        assert tasks[0]["stage_order"] == 1
        assert_two_decimal(tasks[0]["stage_weight_pct"], 0.10, "stage_weight_pct")
        assert tasks[0]["shot_id"] == shot["id"]
        assert tasks[4]["stage"] == "COMP"
        assert tasks[4]["stage_order"] == 5
        assert_two_decimal(tasks[4]["stage_weight_pct"], 0.20, "stage_weight_pct")


class TestAssetCreationConstraints:
    def test_illegal_asset_type_and_zero_complexity_are_both_rejected(self, client):
        """The asset type enumeration is closed and the complexity estimate must be
        strictly positive, so neither request creates a row.

        PRD: "An asset is briefed with the owning `production_id`, an `asset_code` unique
        within that production, an `asset_type` chosen from `CHARACTER_MODEL`, `PROP`,
        `ENVIRONMENT`, `RIG` and `SURFACING_PACKAGE`, and a `base_complexity_points`
        estimate that must be strictly greater than zero and carries two decimal places."

        Design: Corner/entities/asset_create_invalid_asset_type_rejects
        """
        production = fx.open_production(client, title="Aurora Drift", production_code="AD01")

        bad_type = client.create_asset(
            {
                "production_id": production["id"],
                "asset_code": "AD01_MATTE_01",
                "asset_type": "MATTE_PAINTING",
                "base_complexity_points": 100.00,
            },
            ARTIST_HEADERS,
        )
        validate_error(bad_type, ERR_VALIDATION, 422)

        bad_points = client.create_asset(
            {
                "production_id": production["id"],
                "asset_code": "AD01_PROP_01",
                "asset_type": "PROP",
                "base_complexity_points": 0,
            },
            ARTIST_HEADERS,
        )
        validate_error(bad_points, ERR_VALIDATION, 422)

        _, meta = validate_paginated(
            client.list_assets(
                PRODUCTION_MANAGER_HEADERS, {"production_id": production["id"]}
            )
        )
        assert meta["total_count"] == 0
