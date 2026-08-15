"""Surface cyclic machine, condition-code derivation, friction thresholds,
the report/assessment event-activity gate, and dispatch ordering."""
from test_helpers import (
    ApiErrorId,
    create_condition_report_payload,
    create_friction_assessment_payload,
    create_ready_equipment,
    create_snow_event,
    create_surface,
    file_condition_report,
    get_surface,
    get_surface_version,
    record_friction_assessment,
    setup_event_with_surface,
    surface_action,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSurfaceCyclicLoop:
    def test_surface_restrict_then_close(self, api, ops_controller_headers):
        """PRD §3.3: "`RESTRICT` moves `OPEN → RESTRICTED`; `CLOSE` moves
        `OPEN → CLOSED` or `RESTRICTED → CLOSED`; `REOPEN` moves `CLOSED →
        RESTRICTED`; `CLEAR` moves `RESTRICTED → OPEN`."

        Design: Difficulty/non_linear_state_machine/airfield_surface_cyclic_close_reopen_loop
        """
        ctx = setup_event_with_surface(event_code="SNOW-F")
        event_id = ctx["event"]["id"]
        surface_id = ctx["surface"]["id"]

        restricted = surface_action(surface_id, "RESTRICT", event_id)
        assert restricted["status"] == "RESTRICTED"
        closed = surface_action(surface_id, "CLOSE", event_id)
        assert closed["status"] == "CLOSED"

        assessment = record_friction_assessment(event_id, surface_id,
                                                mu_value=0.60)
        assert assessment["braking_action"] == "GOOD"

    def test_surface_full_close_reopen_clear_loop(
            self, api, ops_controller_headers):
        """PRD §3.3: "`REOPEN` moves `CLOSED → RESTRICTED`; `CLEAR` moves
        `RESTRICTED → OPEN`." and "`REOPEN` carries an additional safety gate:
        the latest `FrictionAssessment` on this surface with `status` =
        `REPORTED` must exist and have `braking_action` of `GOOD` or
        `MEDIUM`."

        Design: Difficulty/non_linear_state_machine/airfield_surface_cyclic_close_reopen_loop
        """
        ctx = setup_event_with_surface(event_code="SNOW-F")
        event_id = ctx["event"]["id"]
        surface_id = ctx["surface"]["id"]

        surface_action(surface_id, "RESTRICT", event_id)
        surface_action(surface_id, "CLOSE", event_id)
        record_friction_assessment(event_id, surface_id, mu_value=0.60)

        reopened = surface_action(surface_id, "REOPEN", event_id)
        assert reopened["status"] == "RESTRICTED", (
            "CLOSED -> RESTRICTED is guarded by GOOD friction; got "
            f"{reopened['status']}")
        cleared = surface_action(surface_id, "CLEAR", event_id)
        assert cleared["status"] == "OPEN", (
            f"the full loop must return to OPEN, got {cleared['status']}")

    def test_reopen_blocked_by_poor_friction_rejected(
            self, api, ops_controller_headers):
        """PRD §3.3: "If no such assessment exists, or the latest is
        `MEDIUM_POOR`, `POOR`, or `NIL`, the reopen is rejected with
        `ERR_REOPEN_FRICTION_TOO_LOW`."

        Design: Corner/state_machines/reopen_blocked_by_poor_friction_rejected
        """
        ctx = setup_event_with_surface(event_code="SNOW-C11")
        event_id = ctx["event"]["id"]
        surface_id = ctx["surface"]["id"]
        closed = surface_action(surface_id, "CLOSE", event_id)
        assessment = record_friction_assessment(
            event_id, surface_id, mu_value=0.20,
            expected_surface_version=closed["version"])
        assert assessment["braking_action"] == "POOR"

        resp = api.surface_action(
            surface_id, {"action": "REOPEN", "event_id": event_id},
            ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_REOPEN_FRICTION_TOO_LOW, 409)
        assert get_surface(surface_id)["status"] == "CLOSED"


class TestReportEventGate:
    def test_condition_report_requires_active_event_rejected(
            self, api, airfield_inspector_headers):
        """PRD §3.1: "filing condition reports, recording friction
        assessments, taking surface actions, proposing or authorizing chemical
        applications, and scheduling shifts all require the referenced event
        to be in `ACTIVATED` or `ESCALATED`, and reject with
        `ERR_EVENT_NOT_ACTIVE` otherwise."

        Design: Difficulty/cross_entity_state_dependency/condition_report_requires_active_event
        """
        surface = create_surface("RWY-09L")
        event = create_snow_event("SNOW-M")  # never activated: FORECAST
        resp = api.create_condition_report(
            create_condition_report_payload(
                event["id"], surface["id"], surface["version"],
                contaminant_type="DRY_SNOW", coverage_pct=40,
                depth_inches=0.2),
            airfield_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_ACTIVE, 409)

    def test_condition_report_rejection_persists_nothing(
            self, api, airfield_inspector_headers,
            ops_controller_headers):
        """PRD §3.1: "filing condition reports, recording friction
        assessments, taking surface actions, proposing or authorizing chemical
        applications, and scheduling shifts all require the referenced event
        to be in `ACTIVATED` or `ESCALATED`, and reject with
        `ERR_EVENT_NOT_ACTIVE` otherwise."

        Design: Difficulty/cross_entity_state_dependency/condition_report_requires_active_event
        """
        surface = create_surface("RWY-09L")
        event = create_snow_event("SNOW-M")  # never activated: FORECAST
        resp = api.create_condition_report(
            create_condition_report_payload(
                event["id"], surface["id"], surface["version"],
                contaminant_type="DRY_SNOW", coverage_pct=40,
                depth_inches=0.2),
            airfield_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_ACTIVE, 409)
        data, meta = validate_paginated(api.list_condition_reports(
            ops_controller_headers, params={"surface_id": surface["id"]}))
        assert meta["total_count"] == 0, (
            f"no report may be persisted for a non-active event, got "
            f"{meta['total_count']}")


class TestConditionCodeAndBrakingThresholds:
    def test_condition_code_ice_with_heavy_coverage_downgrades_to_zero(
            self, api):
        """PRD §3.4: "The base code by contaminant is: `DRY` → `6`, `WET` → `5`,
        `DRY_SNOW` → `4`, `WET_SNOW` → `3`, `COMPACTED_SNOW` → `2`,
        `SLUSH` → `2`, `STANDING_WATER` → `2`, `ICE` → `1`."
        PRD §3.4: "If `coverage_pct` is strictly greater than `50` **and**
        `depth_inches` is at least `0.25`, the base is reduced by `1`. The
        resulting code is floored at `0`, so `condition_code` is always an
        integer in `0..6`."

        Design: Corner/calculations/condition_code_ice_with_heavy_coverage_downgrades_to_zero
        """
        ctx = setup_event_with_surface(event_code="SNOW-K1")
        report = file_condition_report(
            ctx["event"]["id"], ctx["surface"]["id"],
            expected_surface_version=ctx["surface"]["version"],
            contaminant_type="ICE", coverage_pct=60, depth_inches=0.5)
        assert report["condition_code"] == 0, (
            "ICE base 1 minus 1 (coverage 60 > 50 and depth 0.5 >= 0.25) "
            f"floors at 0, got {report['condition_code']}")

    def test_braking_action_upper_boundary_good_vs_medium(self, api):
        """PRD §3.5: "If `mu_value` is at least `0.50`, `braking_action` is
        `GOOD`. Otherwise, if `mu_value` is at least `0.36`, it is `MEDIUM`."
        and "Because the lower bounds are inclusive, a `mu_value` of exactly
        `0.36` yields `MEDIUM`, not `MEDIUM_POOR`."

        Design: Corner/calculations/braking_action_upper_boundary_good_vs_medium
        """
        ctx = setup_event_with_surface(event_code="SNOW-K2")
        event_id = ctx["event"]["id"]
        surface_id = ctx["surface"]["id"]

        at = record_friction_assessment(
            event_id, surface_id, mu_value=0.50,
            expected_surface_version=ctx["surface"]["version"])
        assert at["braking_action"] == "GOOD", (
            f"mu 0.50 >= 0.50 inclusive must be GOOD, got "
            f"{at['braking_action']}")
        below = record_friction_assessment(event_id, surface_id,
                                           mu_value=0.49)
        assert below["braking_action"] == "MEDIUM", (
            f"mu 0.49 in [0.36, 0.50) must be MEDIUM, got "
            f"{below['braking_action']}")

    def test_friction_mu_at_medium_bound_is_medium(self, api):
        """PRD §3.5: "Because the lower bounds are inclusive, a `mu_value` of
        exactly `0.36` yields `MEDIUM`, not `MEDIUM_POOR`."

        Design: Difficulty/boundary_precision_check/friction_mu_threshold_equality_medium
        """
        ctx = setup_event_with_surface(event_code="SNOW-K")
        at = record_friction_assessment(
            ctx["event"]["id"], ctx["surface"]["id"], mu_value=0.36,
            expected_surface_version=ctx["surface"]["version"])
        assert at["braking_action"] == "MEDIUM", (
            f"mu exactly 0.36 hits the inclusive lower bound: got "
            f"{at['braking_action']}")

    def test_friction_mu_below_medium_bound_is_medium_poor(self, api):
        """PRD §3.5: "Otherwise, if `mu_value` is at least `0.26`, it is
        `MEDIUM_POOR`." and "Because the lower bounds are inclusive, a
        `mu_value` of exactly `0.36` yields `MEDIUM`, not `MEDIUM_POOR`."

        Design: Difficulty/boundary_precision_check/friction_mu_threshold_equality_medium
        """
        ctx = setup_event_with_surface(event_code="SNOW-K")
        below = record_friction_assessment(
            ctx["event"]["id"], ctx["surface"]["id"], mu_value=0.35,
            expected_surface_version=ctx["surface"]["version"])
        assert below["braking_action"] == "MEDIUM_POOR", (
            f"mu 0.35 falls below the 0.36 bound: got "
            f"{below['braking_action']}")


class TestDerivedConditionCodeReconciliation:
    def test_derived_current_condition_code_reconciled_on_supersede(
            self, api):
        """PRD §3.4: "The new report starts with `status` = `FILED` and
        `superseded_by_id` unset, and the surface's `current_condition_code`
        is updated to this newly derived code."
        PRD §3.4: "Filing a newer report for the same (`event_id`,
        `surface_id`) supersedes the prior `FILED` report".

        Design: Corner/cross_cutting_layers/derived_current_condition_code_reconciled_on_supersede
        """
        ctx = setup_event_with_surface(event_code="SNOW-L3")
        event_id = ctx["event"]["id"]
        surface_id = ctx["surface"]["id"]

        file_condition_report(
            event_id, surface_id,
            expected_surface_version=ctx["surface"]["version"],
            contaminant_type="DRY_SNOW", coverage_pct=40, depth_inches=0.2)
        first = get_surface(surface_id)
        assert first["current_condition_code"] == 4, (
            f"DRY_SNOW base with no downgrade is 4, got "
            f"{first['current_condition_code']}")

        file_condition_report(event_id, surface_id, contaminant_type="ICE",
                              coverage_pct=60, depth_inches=0.5)
        second = get_surface(surface_id)
        assert second["current_condition_code"] == 0, (
            "the denormalized code must reconcile to the latest report "
            f"(ICE downgraded to 0), got {second['current_condition_code']}")


class TestDispatchOrder:
    def test_dispatch_order_ranking_with_created_at_tiebreak(
            self, api, ops_controller_headers):
        """PRD §3.11: "The eligible set is every `AirfieldSurface` with
        `status` of `RESTRICTED` or `CLOSED`. The ordering is by
        `priority_rank` ascending; ties break by `created_at` ascending." and
        "The ordering is a deterministic total order; `id` is never used for
        ranking or tie-breaks."

        Design: Corner/calculations/dispatch_order_ranking_with_created_at_tiebreak
        """
        create_ready_equipment()
        s_a = create_surface("RWY-18L", priority_rank=2, length_ft=4000,
                             width_ft=100)
        s_b = create_surface("RWY-09L", priority_rank=1)
        s_c = create_surface("RWY-09R", priority_rank=1)
        event = create_snow_event("SNOW-K3")
        from test_helpers import activate_event
        activate_event(event["id"])
        for surface in (s_a, s_b, s_c):
            surface_action(surface["id"], "RESTRICT", event["id"])

        resp = api.get_dispatch_order(event["id"], ops_controller_headers)
        data = validate_success(resp, 200)
        codes = [row["surface_code"] for row in data]
        assert codes == ["RWY-09L", "RWY-09R", "RWY-18L"], (
            "rank 1 surfaces first (created_at ascending tie-break), then "
            f"rank 2; got {codes}")

    def test_dispatch_order_empty_when_all_surfaces_open(
            self, api, ops_controller_headers):
        """PRD §3.11: "If no surface is eligible, the result is an empty array
        — this is not an error."

        Design: Corner/calculations/dispatch_order_empty_when_all_surfaces_open
        """
        ctx = setup_event_with_surface(event_code="SNOW-K4")
        resp = api.get_dispatch_order(ctx["event"]["id"],
                                      ops_controller_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["response_type"] == "array"
        assert body["data"] == [], (
            f"all surfaces OPEN means an empty eligible set, got "
            f"{body['data']}")
