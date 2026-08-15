"""Fields and planting plans: request shape, computed yield, season slots, lifecycle gates."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_planting_plan_payload,
    create_field, setup_field_with_plan, setup_harvesting_plan_with_kiln,
    create_in_kiln_lot, assert_planting_plan,
)


class TestFieldCreateShape:
    def test_field_create_missing_acreage_rejected(self, api, farm_manager_headers):
        """PRD §2.8: "4. Request shape — required body fields present; enum
        values valid; integer and number ranges respected (`acreage` above zero,
        `wet_lbs` above zero, prices above zero, `alpha_pct` greater than zero
        and at most 25, `term_end_year` no earlier than `term_start_year`,
        `coverage_pct` greater than zero and at most 1, `kiln_window_end`
        strictly after `kiln_window_start`, `source_lot_ids` carrying at least
        one entry); datetimes well-formed; and unknown body fields rejected —
        any failure yields `ERR_INVALID_REQUEST`."

        Design: Corner/entities/field_create_missing_required_returns_invalid_request
        """
        payload = {"name": "F1"}  # acreage omitted
        res = api.create_field(payload, farm_manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestPlanCreate:
    def test_plan_create_invalid_variety_rejected(self, api, farm_manager_headers):
        """PRD §3.1: "the `variety` — one of `CASCADE`, `CENTENNIAL`, `CTZ`,
        `CITRA`, or `MOSAIC`". PRD §2.8: "enum values valid ... any failure yields
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/plan_create_invalid_enum_returns_invalid_request
        """
        field = create_field()
        res = api.create_planting_plan(
            create_planting_plan_payload(field["id"], variety="GALAXY"),
            farm_manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_plan_projected_yield_computed_at_creation(self, api, farm_manager_headers):
        """PRD §3.1: "At creation the plan computes its `projected_yield_lbs`: the
        `planned_acreage` multiplied by the variety's base yield per acre — 1800
        lbs for `CASCADE`, 2000 for `CENTENNIAL`, 2200 for `CTZ`, 1900 for
        `CITRA`, and 1700 for `MOSAIC` — an exact integer product with no
        rounding."

        Design: Corner/entities/plan_projected_yield_computed
        """
        field = create_field()
        res = api.create_planting_plan(
            create_planting_plan_payload(field["id"], crop_year=2026,
                                         variety="CASCADE", planned_acreage=40),
            farm_manager_headers)
        plan = validate_success(res, 201)
        assert_planting_plan(plan)
        assert plan["projected_yield_lbs"] == 72000, (
            "40 acres x 1800 lbs/acre CASCADE base yield")
        assert plan["status"] == "DRAFT"

    def test_plan_acreage_above_field_acreage_rejected(self, api, farm_manager_headers):
        """PRD §3.1: "The planned acreage must be at least 1, and it may not exceed
        the field's total `acreage`; an overage is rejected with
        `ERR_ACREAGE_EXCEEDED`."

        Design: Corner/validations/plan_acreage_exceeded
        """
        field = create_field(acreage=100)
        res = api.create_planting_plan(
            create_planting_plan_payload(field["id"], planned_acreage=101),
            farm_manager_headers)
        validate_error(res, ApiErrorId.ERR_ACREAGE_EXCEEDED)


class TestFieldSeasonSlot:
    def test_second_plan_same_field_same_year_rejected(self, api, farm_manager_headers):
        """PRD §3.1: "A field accepts only one live plan per season: if a plan
        that is not `CANCELLED` already exists for the same `field_id` and
        `crop_year`, the new plan is rejected with `ERR_FIELD_SEASON_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/field_season_slot_conflict
        """
        field = create_field()
        validate_success(api.create_planting_plan(
            create_planting_plan_payload(field["id"], crop_year=2026,
                                         variety="CASCADE", planned_acreage=40),
            farm_manager_headers), 201)
        res = api.create_planting_plan(
            create_planting_plan_payload(field["id"], crop_year=2026,
                                         variety="CITRA", planned_acreage=10),
            farm_manager_headers)
        validate_error(res, ApiErrorId.ERR_FIELD_SEASON_CONFLICT)

    def test_plan_same_field_adjacent_year_allowed(self, api, farm_manager_headers):
        """PRD §3.1: "A field accepts only one live plan per season: if a plan
        that is not `CANCELLED` already exists for the same `field_id` and
        `crop_year`, the new plan is rejected with `ERR_FIELD_SEASON_CONFLICT`."
        The adjacent discrete season slot (2027 vs 2026) is free.

        Design: Difficulty/resource_temporal_overlap/field_season_slot_conflict
        """
        field = create_field()
        validate_success(api.create_planting_plan(
            create_planting_plan_payload(field["id"], crop_year=2026,
                                         variety="CASCADE", planned_acreage=40),
            farm_manager_headers), 201)
        plan_2027 = validate_success(api.create_planting_plan(
            create_planting_plan_payload(field["id"], crop_year=2027,
                                         variety="CITRA", planned_acreage=10),
            farm_manager_headers), 201)
        assert plan_2027["id"], "the 2027 season slot is independent of 2026"
        assert plan_2027["crop_year"] == 2027


class TestPlanLifecycleGates:
    def test_open_harvest_from_draft_rejected(self, api, farm_manager_headers):
        """PRD §3.1: "Opening the harvest moves `GROWING` to `HARVESTING`."
        PRD §2.8: "6. State-machine from-state — the target resource is in a
        state from which the requested transition exists, else
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/plan_open_harvest_from_draft_returns_invalid_state
        """
        field, plan = setup_field_with_plan(plan_state="DRAFT")
        res = api.open_harvest(plan["id"], farm_manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_complete_blocked_by_lot_in_kiln(self, api, farm_manager_headers):
        """PRD §3.1: "Completion moves a plan from `HARVESTING` to `COMPLETE`,
        and it is gated on an empty kiln pipeline: no linked harvest lot may
        remain in `HARVESTED`, `IN_KILN`, or `MOISTURE_CHECK` status, while lots
        already `DRIED` or `CONSUMED` are allowed."

        Design: Corner/state_machines/plan_complete_blocked_by_lots_in_kiln
        """
        ctx = setup_harvesting_plan_with_kiln()
        create_in_kiln_lot(ctx["plan"]["id"], ctx["kiln"]["id"], wet_lbs=1000)
        res = api.complete_plan(ctx["plan"]["id"], farm_manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
