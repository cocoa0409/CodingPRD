"""
Per-entity surface: what creation returns, what a read returns, how lists paginate,
what the server mints itself, and how the graph is navigated.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INVALID_REQUEST, ERR_PLANT_NOT_FOUND
from test_helpers.assertions import (
    PLANT_FIELDS,
    assert_audit_columns,
    assert_has_fields,
    same_instant,
)
from test_helpers.test_users import (
    BLEND_TECHNICIAN,
    BODY_ENGINEER,
    PLANT_ADMIN,
    SALES_REP,
)


class TestPlantEntitySurface:
    """Section 3.1 and section 4 fix what a plant row carries and who may read it."""

    def test_creation_returns_every_declared_field(self, api, clock):
        """
        POST /plants echoes the payload and mints the server-side columns.

        Section 3.1: a plant is created "ACTIVE with fired_scrap_units at 0 and
        idled_at null", carrying its grid position, market radius, freight rate,
        daily capacity and the unloading equipment list. Section 2.2 makes every id
        "a bare UUID" and starts `version` at 1.

        Design: Corner/entities/plant_creation_returns_all_declared_fields
        """
        payload = F.plant_payload()
        plant = validate_success(api.create_plant(payload, PLANT_ADMIN), 201)

        assert_has_fields(plant, PLANT_FIELDS, "Plant")
        assert plant["plant_code"] == payload["plant_code"]
        assert plant["name"] == payload["name"]
        assert plant["grid_x"] == 0
        assert plant["grid_y"] == 0
        assert plant["market_radius_miles"] == 300
        assert plant["freight_rate_cents_per_ton_mile"] == 42
        assert plant["base_capacity_green_units_per_day"] == 40000
        assert plant["unloading_equipment_available"] == [
            "CUSTOMER_FORKLIFT",
            "TRUCK_MOUNTED_FORKLIFT",
            "CRANE",
        ]
        assert plant["status"] == "ACTIVE"
        assert plant["fired_scrap_units"] == 0
        assert plant["idled_at"] is None
        assert is_valid_uuid(plant["id"])
        assert plant["version"] == 1
        assert_audit_columns(plant)

    def test_a_single_resource_read_returns_the_stored_row_to_any_role(self, api, clock):
        """
        GET /plants/{id} is readable by a role that cannot create plants.

        Section 4 lists every role on the plant read endpoint, and section 2.2 makes
        `created_at` a write-once column, so a read after creation returns the same
        instant.

        Design: Corner/entities/plant_single_resource_get_returns_stored_row
        """
        created = fx.create_plant(api)
        read = validate_success(api.get_plant(created["id"], SALES_REP))
        assert read["id"] == created["id"]
        assert read["plant_code"] == created["plant_code"]
        assert read["market_radius_miles"] == 300
        assert read["created_at"] == created["created_at"]
        assert read["version"] == created["version"]

    def test_the_plant_list_paginates_on_created_at_ascending(self, api, clock):
        """
        Two pages of a three-plant registry, ordered oldest first.

        Section 2.4: "List results are returned sorted by created_at ascending", the
        four meta fields are "limit, offset, total_count and has_more", and
        "has_more is true exactly when there is at least one further matching row
        beyond the returned page."

        Design: Corner/entities/plants_list_honors_limit_and_offset
        """
        first = fx.create_plant(api)
        second = fx.create_plant(api)
        third = fx.create_plant(api)

        page_one, meta_one = validate_paginated(
            api.list_plants(PLANT_ADMIN, params={"limit": 2, "offset": 0})
        )
        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0
        assert page_one[0]["plant_code"] == first["plant_code"]
        assert page_one[1]["plant_code"] == second["plant_code"]

        page_two, meta_two = validate_paginated(
            api.list_plants(PLANT_ADMIN, params={"limit": 2, "offset": 2})
        )
        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert meta_two["offset"] == 2
        assert page_two[0]["plant_code"] == third["plant_code"]

        assert {p["id"] for p in page_one + page_two} == {
            first["id"],
            second["id"],
            third["id"],
        }

    def test_an_unknown_plant_id_is_a_not_found_in_the_error_envelope(self, api, clock):
        """
        A well-formed but unused UUID reads as ERR_PLANT_NOT_FOUND.

        Section 2.3 fixes the error envelope as "response_type error" with "data
        carrying error_id" and a message, and section 5 maps ERR_PLANT_NOT_FOUND to
        HTTP 404.

        Design: Corner/entities/plant_get_with_unknown_id_returns_not_found
        """
        alive = fx.create_plant(api)
        error = validate_error(
            api.get_plant(NON_EXISTENT_UUID, PLANT_ADMIN), ERR_PLANT_NOT_FOUND, 404
        )
        assert isinstance(error["message"], str) and error["message"]

        still_there = validate_success(api.get_plant(alive["id"], PLANT_ADMIN))
        assert still_there["id"] == alive["id"]

    def test_a_missing_required_field_is_rejected_and_persists_nothing(self, api, clock):
        """
        A plant payload without market_radius_miles is a malformed request.

        Section 2.3 maps a malformed payload to ERR_INVALID_REQUEST (HTTP 400), and
        section 3.1 lists `market_radius_miles` among the required intake fields, so
        no row may be written.

        Design: Corner/entities/plant_creation_missing_required_market_radius_returns_invalid_request
        """
        payload = F.plant_payload(market_radius_miles=None)
        assert "market_radius_miles" not in payload

        validate_error(api.create_plant(payload, PLANT_ADMIN), ERR_INVALID_REQUEST, 400)

        rows, meta = validate_paginated(api.list_plants(PLANT_ADMIN))
        assert meta["total_count"] == 0
        assert rows == []

    def test_system_fields_are_server_minted_and_version_counts_mutations(
        self, api, clock
    ):
        """
        One idle call takes version from 1 to 2 and refreshes updated_at only.

        Section 2.2: ids are bare UUIDs, `created_at` "is never rewritten", and every
        mutation increments `version` by 1. Section 3.9 stamps `idled_at` "from the
        logical clock", which is the same instant `updated_at` moves to.

        Design: Corner/entities/plant_system_fields_are_server_minted_and_version_starts_at_one
        """
        plant = fx.create_plant(api)
        assert plant["version"] == 1
        assert plant["updated_at"] == plant["created_at"]
        assert is_iso8601_timestamp(plant["created_at"])
        assert is_valid_uuid(plant["id"])
        assert "plant_" not in plant["id"]

        idled = validate_success(api.idle_plant(plant["id"], PLANT_ADMIN))
        assert idled["version"] == 2
        assert idled["created_at"] == plant["created_at"]
        assert idled["updated_at"] == "2026-08-01T00:00:00.000Z"
        assert same_instant(idled["idled_at"], idled["updated_at"])


class TestDefaultsAndComputedFieldsAtCreation:
    """
    Optional booleans default rather than arriving null, and derived figures are
    written by the server at the moment of creation.
    """

    def test_omitted_order_flags_default_to_false_and_shape_the_promise(
        self, api, clock
    ):
        """
        An order created without either flag promises 15 days out.

        Section 3.5: "both default to false when omitted", and the promise is "a base
        of 14 days" plus "requested_units divided by the winning plant's
        base_capacity_green_units_per_day, rounded up to a whole day" - with neither
        the 28-day special-order adder nor the 7-day panel adder. "With the clock at
        its startup default, a 12000-unit standard order at a plant rated 40000 green
        units per day promises 15 days out, at 2026-08-16T00:00:00Z."

        Design: Corner/entities/order_omitted_optional_flags_default_to_false
        """
        fx.build_plant_with_assets(api, clock=None)
        payload = F.order_payload(requested_units=12000)
        assert "is_special_order" not in payload
        assert "requires_panel_approval" not in payload

        order = validate_success(api.create_order(payload, SALES_REP), 201)
        assert order["is_special_order"] is False
        assert order["requires_panel_approval"] is False
        assert order["fulfillment_status"] == "DRAFT"
        assert order["freight_status"] == "UNQUOTED"

        assigned = validate_success(api.assign_plant(order["id"], SALES_REP))
        assert assigned["lead_time_days"] == 15
        assert assigned["promised_ship_date"] == "2026-08-16T00:00:00Z"

    def test_the_projection_and_the_clay_commitment_are_written_at_creation(
        self, api, clock
    ):
        """
        A fresh run already carries its projection and its committed tonnage.

        Section 3.3: the projection is "350 basis points ... of green_units_set,
        rounded up to a whole unit, plus a flat allowance of 12 units", the
        commitment is "green_units_set divided by 1000, multiplied by the
        formulation's clay_tons_per_thousand_units, and rounded half up to two
        decimal places", and the actual-variant columns are "all null" until green
        handling is closed.

        Design: Corner/entities/production_run_projected_units_and_clay_commitment_are_computed_at_creation
        """
        env = fx.build_plant_with_assets(api, clock=None)
        run = validate_success(
            api.create_production_run(
                F.production_run_payload(
                    env["plant"]["id"], env["formulation"]["id"], env["kiln_car"]["id"]
                ),
                env["operator"],
            ),
            201,
        )
        assert run["projected_net_green_units"] == 9638
        assert run["clay_tons_committed"] == 32.00
        assert run["net_green_units"] is None
        assert run["green_loss_pct"] is None
        assert run["green_loss_units"] is None
        assert run["green_loss_variance_units"] is None
        assert run["scrap_units"] == 0
        assert run["status"] == "SETTING"


class TestTypeConstraintsAndParentResolution:
    """
    Malformed payloads are refused before any domain rule runs, and a child cannot
    be attached to a parent that does not exist.
    """

    def test_an_unknown_texture_is_a_malformed_request(self, api, clock):
        """
        A texture outside the declared vocabulary is ERR_INVALID_REQUEST.

        Section 2.11 fixes the texture vocabulary as WIRE_CUT, SMOOTH, SAND_FACED and
        TUMBLED, and section 2.3 rejects a value outside a declared enumeration with
        ERR_INVALID_REQUEST (HTTP 400) before any state or ledger is touched.

        Design: Corner/entities/production_run_with_unknown_texture_returns_invalid_request
        """
        env = fx.build_plant_with_assets(api, clock=None)
        validate_error(
            api.create_production_run(
                F.production_run_payload(
                    env["plant"]["id"],
                    env["formulation"]["id"],
                    env["kiln_car"]["id"],
                    texture="HAND_CARVED_DELUXE",
                ),
                env["operator"],
            ),
            ERR_INVALID_REQUEST,
            400,
        )

        runs, meta = validate_paginated(
            api.list_production_runs(PLANT_ADMIN, params={"plant_id": env["plant"]["id"]})
        )
        assert meta["total_count"] == 0
        pits = validate_success(api.list_clay_pits(env["plant"]["id"], PLANT_ADMIN))
        assert [p["committed_tons"] for p in pits] == [0.00, 0.00]

    def test_a_window_that_ends_before_it_starts_is_malformed_not_a_conflict(
        self, api, clock
    ):
        """
        end_at earlier than start_at is ERR_INVALID_REQUEST, never a window conflict.

        Section 3.4 requires "end_at strictly later than start_at", and section 2.5
        ranks the payload check above the temporal collision check - which here has
        nothing to collide with, since the kiln holds no other runs.

        Design: Corner/entities/kiln_run_with_end_at_before_start_at_returns_invalid_request
        """
        env = fx.build_plant_with_assets(api, clock=None)
        validate_error(
            api.create_kiln_run(
                F.kiln_run_payload(
                    env["kiln"]["id"],
                    env["formulation"]["id"],
                    start_at="2026-08-07T00:00:00Z",
                    end_at="2026-08-05T00:00:00Z",
                ),
                env["operator"],
            ),
            ERR_INVALID_REQUEST,
            400,
        )
        runs, meta = validate_paginated(
            api.list_kiln_runs(PLANT_ADMIN, params={"kiln_id": env["kiln"]["id"]})
        )
        assert meta["total_count"] == 0

    def test_a_pit_cannot_be_opened_under_a_plant_that_does_not_exist(self, api, clock):
        """
        POST under an unknown plant id is a 404 and attaches nothing.

        Section 3.2 opens pits "under a plant", so the parent must resolve first;
        section 5 maps the unresolved parent to ERR_PLANT_NOT_FOUND (HTTP 404).

        Design: Corner/entities/clay_pit_creation_under_unknown_plant_returns_not_found
        """
        real = fx.create_plant(api)
        validate_error(
            api.create_clay_pit(NON_EXISTENT_UUID, F.clay_pit_payload(), PLANT_ADMIN),
            ERR_PLANT_NOT_FOUND,
            404,
        )
        pits, meta = validate_paginated(api.list_clay_pits(real["id"], PLANT_ADMIN))
        assert meta["total_count"] == 0
        assert pits == []


class TestGraphNavigation:
    """
    The blend component junction is navigable from either parent, and formulation
    supersession is a self-referential edge with its own filter.
    """

    def test_one_lot_serves_two_blends_through_the_component_junction(self, api, clock):
        """
        Two 4000-unit draws on one lot are visible from the blend side and the lot side.

        Section 3.7 pins two audit figures on the junction row: "color_index_at_allocation
        snapshots the lot's color_index as it stands now, and contribution_index is
        color_index_at_allocation multiplied by units, rounded half up to two decimal
        places", with `source` MANUAL on a hand-picked draw. Section 2.9 keeps the
        lot's three columns summing to fired_units across both blends.

        Design: Corner/entities/blend_component_junction_is_navigable_from_both_parents
        """
        env = fx.build_fired_lot(api, clock=None)
        lot_id = env["fired_lot"]["id"]
        order_a = fx.build_assigned_order(api, requested_units=4000)
        order_b = fx.build_assigned_order(api, requested_units=4000)
        blend_a = fx.build_draft_blend_with_allocation(api, order_a, [(lot_id, 4000)])
        blend_b = fx.build_draft_blend_with_allocation(api, order_b, [(lot_id, 4000)])

        blend_side = validate_success(
            api.list_blend_components(blend_a["id"], BLEND_TECHNICIAN)
        )
        assert len(blend_side) == 1
        assert blend_side[0]["fired_lot_id"] == lot_id
        assert blend_side[0]["blend_id"] == blend_a["id"]
        assert blend_side[0]["units"] == 4000
        assert blend_side[0]["source"] == "MANUAL"
        assert blend_side[0]["status"] == "ALLOCATED"
        assert blend_side[0]["color_index_at_allocation"] == 52.18
        assert blend_side[0]["contribution_index"] == 208720.00

        lot_side = validate_success(
            api.list_fired_lot_blend_components(lot_id, BLEND_TECHNICIAN)
        )
        assert len(lot_side) == 2
        assert [c["blend_id"] for c in lot_side] == [blend_a["id"], blend_b["id"]]

        lot = validate_success(api.get_fired_lot(lot_id, BLEND_TECHNICIAN))
        assert lot["reserved_units"] == 8000
        assert lot["available_units"] == 1600
        assert lot["consumed_units"] == 0

    def test_supersession_is_a_filterable_self_referential_edge(self, api, clock):
        """
        A two-edge chain F1 <- F2 <- F3 is walkable through the list filter.

        Section 3.6 walks "upward through each formulation's
        supersedes_formulation_id", and section 3.2 notes a body created over a
        QUALIFIED predecessor moves that predecessor to RETIRED. The chain root
        supersedes nothing and the leaf is superseded by nothing.

        Design: Corner/entities/formulation_supersession_is_self_referential_and_filterable
        """
        env = fx.build_plant_with_assets(api, clock=None)
        first = env["formulation"]
        assert first["supersedes_formulation_id"] is None

        second = fx.create_draft_formulation(
            api, env["plant"]["id"], supersedes_formulation_id=first["id"]
        )
        third = fx.create_draft_formulation(
            api, env["plant"]["id"], supersedes_formulation_id=second["id"]
        )
        assert second["supersedes_formulation_id"] == first["id"]
        assert third["supersedes_formulation_id"] == second["id"]

        children_of_first, meta_first = validate_paginated(
            api.list_formulations(
                BODY_ENGINEER, params={"supersedes_formulation_id": first["id"]}
            )
        )
        assert meta_first["total_count"] == 1
        assert children_of_first[0]["id"] == second["id"]

        children_of_second, meta_second = validate_paginated(
            api.list_formulations(
                BODY_ENGINEER, params={"supersedes_formulation_id": second["id"]}
            )
        )
        assert meta_second["total_count"] == 1
        assert children_of_second[0]["id"] == third["id"]

        leaves, meta_leaf = validate_paginated(
            api.list_formulations(
                BODY_ENGINEER, params={"supersedes_formulation_id": third["id"]}
            )
        )
        assert meta_leaf["total_count"] == 0
        assert leaves == []

        retired = validate_success(api.get_formulation(first["id"], BODY_ENGINEER))
        assert retired["status"] == "RETIRED"
