"""Operator shifts, equipment readiness, and the dual-variant event cost
model (provisional estimated vs final actual)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    authorize_application,
    create_operator_shift_payload,
    create_ready_equipment,
    create_snow_event,
    dispense_application,
    get_cost_summary,
    propose_application,
    schedule_shift,
    setup_activated_event,
    setup_event_with_surface,
    setup_proposed_application,
    shift_action,
    take_unit_out_of_service,
    validate_error,
    validate_success,
    activate_event,
    create_surface,
    create_chemical_product,
)


class TestDualVariantCostDivergence:
    def _setup_provisional(self):
        """One AUTHORIZED application (297000) + one SCHEDULED shift planned
        10h on PLOW-01 (labor 55000 + equipment 145000)."""
        ctx = setup_proposed_application(
            event_code="SNOW-A", product_code="NAAC-01", base_rate=30,
            unit_cost=12, seasonal_limit=100000, chemical_limit_lbs=100000,
            budget_cents=5000000, pavement_temp_f=20)
        authorize_application(ctx["application"]["id"])
        shift = schedule_shift(
            ctx["event"]["id"], operator_code="OP-01",
            base_rate_cents_per_hour=5000,
            start_utc="2026-08-10T08:00:00Z", end_utc="2026-08-10T18:00:00Z",
            equipment_unit_id=ctx["units"][0]["id"])
        ctx["shift"] = shift
        return ctx

    def test_event_cost_provisional_variant_before_completion(self, api):
        """PRD §3.10: "The **provisional variant**, `estimated_cost_cents`, is
        the sum of lines over shifts with `status` = `SCHEDULED` plus
        applications with `status` = `AUTHORIZED`. The **final variant**,
        `actual_cost_cents`, is the sum of lines over shifts with `status` =
        `COMPLETED` plus applications with `status` = `DISPENSED`."

        Design: Difficulty/dual_variant_calc/event_cost_provisional_vs_final_divergence
        """
        ctx = self._setup_provisional()
        summary = get_cost_summary(ctx["event"]["id"])
        assert summary["estimated_cost_cents"] == 497000, (
            "provisional: 55000 labor (8x5000 + 2x5000x1.5) + 145000 "
            f"equipment (10x14500) + 297000 chemical; got "
            f"{summary['estimated_cost_cents']}")
        assert summary["actual_cost_cents"] == 0, (
            "nothing COMPLETED or DISPENSED yet, the final variant is 0")

    def test_event_cost_final_variant_after_completion(self, api):
        """PRD §3.10: "Identical records yield a different total whenever
        planned hours differ from worked hours." and "The **final variant**,
        `actual_cost_cents`, is the sum of lines over shifts with `status` =
        `COMPLETED` plus applications with `status` = `DISPENSED`."

        Design: Difficulty/dual_variant_calc/event_cost_provisional_vs_final_divergence
        """
        ctx = self._setup_provisional()
        shift_action(ctx["shift"]["id"], "COMPLETE", worked_hours=9.5)
        dispense_application(ctx["application"]["id"])
        summary = get_cost_summary(ctx["event"]["id"])
        assert summary["estimated_cost_cents"] == 0, (
            "no SCHEDULED shifts or AUTHORIZED applications remain")
        assert summary["actual_cost_cents"] == 486000, (
            "final: 51250 labor at 9.5h (8x5000 + 1.5x5000x1.5) + 137750 "
            f"equipment (9.5x14500) + 297000 chemical; got "
            f"{summary['actual_cost_cents']}")
        assert summary["actual_cost_cents"] != 497000, (
            "identical underlying records diverge across variants by 11000 "
            "cents because planned (10h) differs from worked (9.5h)")


class TestPerLineRoundingOrder:
    def test_cost_per_line_rounding_order_pinned_two_shifts(self, api):
        """PRD §3.10: "The rounding order is pinned: each per-line cost is
        rounded half up to the cent **first**, and only then are the rounded
        lines summed. Sum-then-round is rejected."

        Design: Difficulty/combinatorial_formula/cost_per_line_rounding_order_pinned
        """
        ctx = setup_activated_event(event_code="SNOW-D",
                                    chemical_limit_lbs=1000,
                                    budget_cents=100000)
        for op in ("OP-A", "OP-B"):
            schedule_shift(ctx["event"]["id"], operator_code=op,
                           base_rate_cents_per_hour=1001,
                           start_utc="2026-08-10T08:00:00Z",
                           end_utc="2026-08-10T08:30:00Z")
        summary = get_cost_summary(ctx["event"]["id"])
        assert summary["estimated_cost_cents"] == 1002, (
            "per-line: round_half_up(0.5 x 1001) = 501 per shift; 501 + 501 "
            f"= 1002 (sum-then-round would give 1001); got "
            f"{summary['estimated_cost_cents']}")

    def test_cost_per_line_rounding_half_up_single_shift(self, api):
        """PRD §2.8: "**Money** (`line_cost_cents`, `estimated_cost_cents`,
        `actual_cost_cents`, `budget_cents`, `unit_cost_cents_per_lb`,
        `base_rate_cents_per_hour`, `hourly_rate_cents`) is integer cents,
        and every per-line cost is rounded half up to the cent **before**
        any summation; sum-then-round is not acceptable."

        Design: Difficulty/combinatorial_formula/cost_per_line_rounding_order_pinned
        """
        ctx = setup_activated_event(event_code="SNOW-D",
                                    chemical_limit_lbs=1000,
                                    budget_cents=100000)
        schedule_shift(ctx["event"]["id"], operator_code="OP-A",
                       base_rate_cents_per_hour=1001,
                       start_utc="2026-08-10T08:00:00Z",
                       end_utc="2026-08-10T08:30:00Z")
        summary = get_cost_summary(ctx["event"]["id"])
        assert summary["estimated_cost_cents"] == 501, (
            "round half up of 500.5 is 501 (round-half-even would give 500); "
            f"got {summary['estimated_cost_cents']}")

    def test_cost_estimate_excludes_cancelled_shift(
            self, api, ops_controller_headers):
        """PRD §3.10: "`CANCELLED` shifts and `REJECTED` or `VOIDED`
        applications are excluded from both variants."
        PRD §3.9: "Cancelling a shift (`SCHEDULED → CANCELLED`) recomputes
        `estimated_cost_cents` because the shift leaves the provisional input
        set and increments `version`."

        Design: Corner/calculations/cost_estimate_excludes_cancelled_shift
        """
        ctx = setup_activated_event(event_code="SNOW-K5")
        shift = schedule_shift(ctx["event"]["id"], operator_code="OP-C",
                               base_rate_cents_per_hour=5000,
                               start_utc="2026-08-10T08:00:00Z",
                               end_utc="2026-08-10T16:00:00Z")
        before = get_cost_summary(ctx["event"]["id"])
        assert before["estimated_cost_cents"] == 40000, (
            f"8 planned hours x 5000 = 40000, got "
            f"{before['estimated_cost_cents']}")
        shift_action(shift["id"], "CANCEL")
        after = get_cost_summary(ctx["event"]["id"])
        assert after["estimated_cost_cents"] == 0, (
            f"the CANCELLED shift leaves the provisional input set, got "
            f"{after['estimated_cost_cents']}")


class TestShiftOverlap:
    def test_operator_shift_half_open_adjacency_allowed(
            self, api, ops_controller_headers):
        """PRD §3.9: "The overlap check is scoped per `operator_code`: the new
        half-open window must overlap no other non-`CANCELLED` shift for the
        same operator, with touching endpoints (one shift's `end_utc` equal to
        another's `start_utc`) allowed; a conflict yields
        `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/operator_shift_half_open_adjacency
        """
        ctx = setup_activated_event(event_code="SNOW-O")
        first = schedule_shift(ctx["event"]["id"], operator_code="OP-07",
                               start_utc="2026-08-10T08:00:00Z",
                               end_utc="2026-08-10T12:00:00Z")
        second = schedule_shift(ctx["event"]["id"], operator_code="OP-07",
                                start_utc="2026-08-10T12:00:00Z",
                                end_utc="2026-08-10T16:00:00Z")
        assert first["status"] == "SCHEDULED"
        assert second["status"] == "SCHEDULED", (
            "a shift starting exactly when another ends touches but does not "
            "overlap under half-open semantics")

    def test_operator_shift_genuine_overlap_rejected(
            self, api, ops_controller_headers):
        """PRD §3.9: "the new half-open window must overlap no other
        non-`CANCELLED` shift for the same operator, with touching endpoints
        (one shift's `end_utc` equal to another's `start_utc`) allowed; a
        conflict yields `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/operator_shift_half_open_adjacency
        """
        ctx = setup_activated_event(event_code="SNOW-O")
        schedule_shift(ctx["event"]["id"], operator_code="OP-07",
                       start_utc="2026-08-10T08:00:00Z",
                       end_utc="2026-08-10T12:00:00Z")
        schedule_shift(ctx["event"]["id"], operator_code="OP-07",
                       start_utc="2026-08-10T12:00:00Z",
                       end_utc="2026-08-10T16:00:00Z")
        resp = api.create_operator_shift(
            create_operator_shift_payload(
                ctx["event"]["id"], operator_code="OP-07",
                start_utc="2026-08-10T11:00:00Z",
                end_utc="2026-08-10T13:00:00Z"),
            ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP, 409)


class TestShiftStateAndEquipment:
    def test_shift_complete_twice_rejected(self, api, ops_controller_headers):
        """PRD §3.9: "Attempting an action that does not match the current
        status — for example completing an already-`COMPLETED` shift — is
        rejected with `ERR_INVALID_SHIFT_STATE`."

        Design: Corner/state_machines/shift_complete_twice_rejected
        """
        ctx = setup_activated_event(event_code="SNOW-C9")
        shift = schedule_shift(ctx["event"]["id"], operator_code="OP-Z")
        completed = shift_action(shift["id"], "COMPLETE", worked_hours=8)
        assert completed["status"] == "COMPLETED"
        resp = api.shift_action(shift["id"],
                                {"action": "COMPLETE", "worked_hours": 8},
                                ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_SHIFT_STATE, 409)

    def test_shift_create_with_unknown_equipment_returns_not_found(
            self, api, ops_controller_headers):
        """PRD §2.7: ""Where a request body references foreign keys, body references are then
        resolved **left to right** in the order the fields appear in the
        input contract — `event_id` before `surface_id` before
        `product_id` before `equipment_unit_id`.""
        "Each missing reference yields the resource-specific 404 variant:
        `ERR_EVENT_NOT_FOUND`, `ERR_SURFACE_NOT_FOUND`,
        `ERR_PRODUCT_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
        `ERR_NOTAM_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, or
        `ERR_SHIFT_NOT_FOUND`.""

        Design: Corner/entities/shift_create_with_unknown_equipment_returns_not_found
        """
        ctx = setup_activated_event(event_code="SNOW-EQ")
        resp = api.create_operator_shift(
            create_operator_shift_payload(
                ctx["event"]["id"], operator_code="OP-X",
                equipment_unit_id=NON_EXISTENT_UUID,
                start_utc="2026-08-10T08:00:00Z",
                end_utc="2026-08-10T12:00:00Z"),
            ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_NOT_FOUND, 404)

    def test_shift_with_out_of_service_equipment_rejected(
            self, api, ops_controller_headers):
        """PRD §3.9: "When `equipment_unit_id` is supplied, the referenced
        unit must be `READY`; scheduling against an `OUT_OF_SERVICE` unit is
        rejected with `ERR_EQUIPMENT_NOT_READY`."

        Design: Corner/errors/shift_with_out_of_service_equipment_rejected
        """
        ctx = setup_activated_event(event_code="SNOW-X7")
        unit = ctx["units"][0]
        take_unit_out_of_service(unit["id"])
        resp = api.create_operator_shift(
            create_operator_shift_payload(
                ctx["event"]["id"], operator_code="OP-Y",
                equipment_unit_id=unit["id"]),
            ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_NOT_READY, 409)

    def test_equipment_readiness_cycle_round_trip(self, api,
                                                  maintenance_lead_headers):
        """PRD §3.9: "New units start with `readiness` = `READY`. A
        `MaintenanceLead` may take a unit out of service (`READY →
        OUT_OF_SERVICE`) and return it (`OUT_OF_SERVICE → READY`); each
        transition increments the unit's `version`."

        Design: Corner/state_machines/equipment_readiness_cycle_round_trip
        """
        units = create_ready_equipment([("PLOW-01", "PLOW", 14500)])
        unit = units[0]
        assert unit["readiness"] == "READY"
        resp = api.equipment_readiness_action(
            unit["id"], {"action": "TAKE_OUT_OF_SERVICE"},
            maintenance_lead_headers)
        assert validate_success(resp, 200)["readiness"] == "OUT_OF_SERVICE"
        resp = api.equipment_readiness_action(
            unit["id"], {"action": "RETURN_TO_SERVICE"},
            maintenance_lead_headers)
        assert validate_success(resp, 200)["readiness"] == "READY"
