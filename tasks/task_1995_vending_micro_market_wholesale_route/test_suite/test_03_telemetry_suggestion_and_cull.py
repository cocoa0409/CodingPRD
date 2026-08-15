"""DEX telemetry ingestion, suggested replenishment, and slow-mover culling."""
from test_helpers import (
    ApiErrorId,
    find_projection_entry,
    find_slot,
    get_location,
    get_order,
    get_success_data,
    ingest_telemetry,
    setup_selling_location,
    validate_error,
    validate_success,
)


class TestSuggestedReplenishment:
    def test_suggestion_ceil_and_exclusion_rules(self, api):
        """PRD §3.4: "A slot with no such event item is excluded from the
        suggestion entirely. Otherwise the raw need is the slot's
        `par_level_units` minus the item's `on_hand_units`; a raw need of zero
        or less excludes the slot. The suggested quantity for a surviving slot
        is its raw need divided by the product's `case_pack_qty`, rounded up to
        the next whole case"

        Design: Corner/calculations/suggestion_ceil_and_exclusion_rules
        """
        world = setup_selling_location(
            products_spec=[
                {"sku": "PS-1", "name": "Sug 1", "category": "BEVERAGE"},
                {"sku": "PS-2", "name": "Sug 2", "base_price_cents": 800,
                 "cost_cents": 500},
                {"sku": "PS-3", "name": "Sug 3", "category": "CANDY",
                 "base_price_cents": 700, "cost_cents": 400},
            ],
            slots_spec=[
                {"slot_code": "S1", "product_index": 0, "par_level_units": 25,
                 "vend_price_cents": 150},
                {"slot_code": "S2", "product_index": 1, "par_level_units": 10,
                 "vend_price_cents": 120},
                {"slot_code": "S3", "product_index": 2, "par_level_units": 10,
                 "vend_price_cents": 110},
            ],
            route_code="R-SUG",
        )
        p1, p2, p3 = (p["id"] for p in world["products"])
        # PS-1: on_hand 3 (need 22 -> ceil(22/10) = 3); PS-2: no telemetry
        # item; PS-3: on_hand 12 >= par 10.
        ingest_telemetry(
            world["location"]["id"], "2026-08-01T06:00:00Z",
            [
                {"product_id": p1, "units_vended": 4, "on_hand_units": 3},
                {"product_id": p3, "units_vended": 0, "on_hand_units": 12},
            ],
        )

        resp = api.generate_order_from_telemetry(
            {"location_id": world["location"]["id"],
             "requested_delivery_date": "2026-08-03"},
            world["om_headers"],
        )
        order = validate_success(resp, 201)
        assert order["source"] == "TELEMETRY_SUGGESTED"
        assert order["fulfillment_status"] == "DRAFT"
        assert len(order["lines"]) == 1, (
            "only PS-1 survives; PS-2 lacks telemetry and PS-3 is at/above par"
        )
        line = order["lines"][0]
        assert line["product_id"] == p1
        assert line["quantity_cases"] == 3, "ceil((25-3)/10) == 3"
        assert order["total_cases"] == 3

    def test_generate_requires_active_planogram(self, api):
        """PRD §3.4: "The location must have an `ACTIVE` planogram, else
        `ERR_NO_ACTIVE_PLANOGRAM`"

        Design: Corner/endpoints/generate_requires_active_planogram
        """
        world = setup_selling_location(
            products_spec=[{"sku": "NPG-1", "name": "NoPG item"}],
            planogram_name="PG-DraftOnly",
            activate=False,
        )
        err = api.generate_order_from_telemetry(
            {"location_id": world["location"]["id"],
             "requested_delivery_date": "2026-08-03"},
            world["om_headers"],
        )
        validate_error(err, ApiErrorId.ERR_NO_ACTIVE_PLANOGRAM)

    def test_generate_empty_suggestion_rejected(self, api):
        """PRD §3.4: "if it yields nothing — every slot at or above par,
        culled, or lacking telemetry — the request fails with
        `ERR_EMPTY_SUGGESTION`."

        Design: Corner/endpoints/generate_empty_suggestion_rejected
        """
        world = setup_selling_location(
            products_spec=[{"sku": "EMS-1", "name": "EmS item"}],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 10, "vend_price_cents": 150}],
            route_code="R-EMS",
        )
        # on_hand 14 >= par 10 -> raw need <= 0 -> slot excluded -> empty.
        ingest_telemetry(
            world["location"]["id"], "2026-08-01T06:00:00Z",
            [{"product_id": world["products"][0]["id"], "units_vended": 0,
              "on_hand_units": 14}],
        )
        err = api.generate_order_from_telemetry(
            {"location_id": world["location"]["id"],
             "requested_delivery_date": "2026-08-03"},
            world["om_headers"],
        )
        validate_error(err, ApiErrorId.ERR_EMPTY_SUGGESTION)


class TestTelemetryCascade:
    def test_projection_follows_latest_event(self, api):
        """PRD §3.4: "First, the location's `on_hand_projection` is rebuilt:
        for each product appearing in the event's items, the projected
        `on_hand_units` is taken from the event for that location with the
        maximum `recorded_at`, breaking ties toward the later `created_at`, and
        each projection entry carries the `product_id`, the `on_hand_units`,
        and the `as_of_event_id` it was derived from."

        Design: Difficulty/transitive_cascade/telemetry_projection_suggestion_cascade_depth2
        """
        world = setup_selling_location(
            products_spec=[{"sku": "TEL-1", "name": "Tele item",
                            "category": "BEVERAGE"}],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 30, "vend_price_cents": 150}],
            route_code="R-TEL",
        )
        pr = world["products"][0]["id"]
        loc_id = world["location"]["id"]

        # E1 (on_hand 5) -> suggested DRAFT order with ceil((30-5)/10) = 3.
        ingest_telemetry(
            loc_id, "2026-08-01T06:00:00Z",
            [{"product_id": pr, "units_vended": 0, "on_hand_units": 5}],
        )
        gen = api.generate_order_from_telemetry(
            {"location_id": loc_id, "requested_delivery_date": "2026-08-03"},
            world["om_headers"],
        )
        suggested = validate_success(gen, 201)
        assert suggested["lines"][0]["quantity_cases"] == 3

        # E2 (later recorded_at, on_hand 25) — link 1 under test.
        event2 = ingest_telemetry(
            loc_id, "2026-08-01T07:00:00Z",
            [{"product_id": pr, "units_vended": 0, "on_hand_units": 25}],
        )
        loc = get_location(loc_id)
        entry = find_projection_entry(loc, pr)
        assert entry["on_hand_units"] == 25
        assert entry["as_of_event_id"] == event2["id"]

    def test_suggested_draft_refreshed_on_ingest(self, api):
        """PRD §3.4: "Second — triggered by that projection change — the
        location's `DRAFT` order whose `source` is `TELEMETRY_SUGGESTED` (the
        one with the latest `created_at`, if several) has its lines recomputed
        by the suggestion rule below; lines whose suggestion has dropped to
        zero are removed, and that order's `version` increments."

        Design: Difficulty/transitive_cascade/telemetry_projection_suggestion_cascade_depth2
        """
        world = setup_selling_location(
            products_spec=[{"sku": "TEL-1", "name": "Tele item",
                            "category": "BEVERAGE"}],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 30, "vend_price_cents": 150}],
            route_code="R-TEL",
        )
        pr = world["products"][0]["id"]
        loc_id = world["location"]["id"]

        ingest_telemetry(
            loc_id, "2026-08-01T06:00:00Z",
            [{"product_id": pr, "units_vended": 0, "on_hand_units": 5}],
        )
        suggested = validate_success(
            api.generate_order_from_telemetry(
                {"location_id": loc_id, "requested_delivery_date": "2026-08-03"},
                world["om_headers"],
            ),
            201,
        )
        assert suggested["total_cases"] == 3

        # Link 2: on_hand 25 -> raw need 5 -> ceil(5/10) = 1 case.
        ingest_telemetry(
            loc_id, "2026-08-01T07:00:00Z",
            [{"product_id": pr, "units_vended": 0, "on_hand_units": 25}],
        )
        order = get_order(suggested["id"])
        assert order["fulfillment_status"] == "DRAFT"
        assert order["source"] == "TELEMETRY_SUGGESTED"
        assert len(order["lines"]) == 1
        assert order["lines"][0]["quantity_cases"] == 1, (
            "suggestion refresh recomputes ceil((30-25)/10) == 1"
        )
        assert order["total_cases"] == 1


class TestSlowMoverCull:
    def _setup_cull_world(self, api):
        world = setup_selling_location(
            products_spec=[
                {"sku": "CV-1", "name": "Cull keep", "base_price_cents": 800,
                 "cost_cents": 500},
                {"sku": "CV-2", "name": "Cull slow", "category": "CANDY",
                 "base_price_cents": 700, "cost_cents": 400,
                 "shelf_life_days": 120},
            ],
            slots_spec=[
                {"slot_code": "A1", "product_index": 0, "par_level_units": 20,
                 "vend_price_cents": 120},
                {"slot_code": "A2", "product_index": 1, "par_level_units": 20,
                 "vend_price_cents": 110},
            ],
            route_code="R-CUL",
        )
        p1, p2 = (p["id"] for p in world["products"])
        # In-window (clock default 2026-08-01, window [2026-07-04, 2026-08-01]):
        # p1 vends 1+1 = 2 units; p2 vends 1+0 = 1 unit.
        ingest_telemetry(
            world["location"]["id"], "2026-07-20T10:00:00Z",
            [
                {"product_id": p1, "units_vended": 1, "on_hand_units": 10},
                {"product_id": p2, "units_vended": 1, "on_hand_units": 12},
            ],
        )
        ingest_telemetry(
            world["location"]["id"], "2026-07-25T10:00:00Z",
            [
                {"product_id": p1, "units_vended": 1, "on_hand_units": 9},
                {"product_id": p2, "units_vended": 0, "on_hand_units": 12},
            ],
        )
        return world, p1, p2

    def test_velocity_at_threshold_not_culled(self, api):
        """PRD §3.3: "Otherwise the slot's `cull_flag` is set to true when its
        four-week velocity is strictly fewer than 2 units; a velocity of
        exactly 2 units is not culled."

        Design: Difficulty/boundary_precision_check/cull_velocity_exact_boundary
        """
        world, p1, _ = self._setup_cull_world(api)
        resp = api.cull_evaluate_planogram(world["planogram"]["id"],
                                           world["om_headers"])
        evaluated = validate_success(resp, 200)
        assert find_slot(evaluated, p1)["cull_flag"] is False, (
            "velocity exactly 2 is NOT culled (strict fewer-than)"
        )

    def test_velocity_below_threshold_culled(self, api):
        """PRD §3.3: "Otherwise the slot's `cull_flag` is set to true when its
        four-week velocity is strictly fewer than 2 units; a velocity of
        exactly 2 units is not culled."

        Design: Difficulty/boundary_precision_check/cull_velocity_exact_boundary
        """
        world, p1, p2 = self._setup_cull_world(api)
        evaluated = validate_success(
            api.cull_evaluate_planogram(world["planogram"]["id"],
                                        world["om_headers"]),
            200,
        )
        assert find_slot(evaluated, p2)["cull_flag"] is True, (
            "velocity 1 < 2 is culled"
        )
        # Sibling stays intact in the same evaluation.
        assert find_slot(evaluated, p1)["cull_flag"] is False

    def test_cull_velocity_window_filtering(self, api):
        """PRD §3.3: "For each slot, the system sums `units_vended` across the
        location's telemetry events whose `recorded_at` falls inside the
        twenty-eight-day window ending at the current logical instant,
        inclusive of both endpoints."
        PRD §3.3: "A slot product with no event items anywhere in that window
        is treated as having insufficient data and is not culled."

        Design: Corner/calculations/cull_velocity_window_filtering
        """
        world = setup_selling_location(
            products_spec=[
                {"sku": "CW-1", "name": "CullW 1", "base_price_cents": 800,
                 "cost_cents": 500},
                {"sku": "CW-2", "name": "CullW 2", "category": "CANDY",
                 "base_price_cents": 700, "cost_cents": 400,
                 "shelf_life_days": 120},
            ],
            slots_spec=[
                {"slot_code": "A1", "product_index": 0, "par_level_units": 20,
                 "vend_price_cents": 120},
                {"slot_code": "A2", "product_index": 1, "par_level_units": 20,
                 "vend_price_cents": 110},
            ],
            route_code="R-CLW",
        )
        p1, p2 = (p["id"] for p in world["products"])
        # 2026-06-15 is outside the 28-day window ending 2026-08-01.
        ingest_telemetry(
            world["location"]["id"], "2026-06-15T10:00:00Z",
            [
                {"product_id": p1, "units_vended": 100, "on_hand_units": 0},
                {"product_id": p2, "units_vended": 50, "on_hand_units": 0},
            ],
        )
        # In-window: only p1 appears, with 1 unit.
        ingest_telemetry(
            world["location"]["id"], "2026-07-20T10:00:00Z",
            [{"product_id": p1, "units_vended": 1, "on_hand_units": 5}],
        )

        evaluated = validate_success(
            api.cull_evaluate_planogram(world["planogram"]["id"],
                                        world["om_headers"]),
            200,
        )
        assert find_slot(evaluated, p1)["cull_flag"] is True, (
            "in-window velocity 1 < 2; the 100 pre-window units are excluded"
        )
        assert find_slot(evaluated, p2)["cull_flag"] is False, (
            "zero in-window items is insufficient data, not a cull"
        )
