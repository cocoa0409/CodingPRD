"""Operator-suspension cascade and provisional-vs-final fallout radius
(PRD §3.1, §3.2, §3.6, §3.7)."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_inventory_movement,
    create_batch_payload,
    create_display_payload,
    create_magazine_payload,
    get_success_data,
    make_operator_headers,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_lead_crew,
    add_secured_post,
    add_site_plan,
    approve_permit,
    checkout_product,
    confirm_standby,
    create_magazine_with_batch,
    create_operator,
    go_decision,
    post_weather,
    set_clock,
    setup_event_ready,
    setup_event_standby_confirmed,
    setup_event_submitted,
)

ADMIN = TEST_USERS["admin_headers"]


class TestOperatorSuspendCascade:
    def _setup_operator_with_two_events(self, api):
        """E1: STANDBY_CONFIRMED with 20 units checked out and one SECURED
        post. E2: SUBMITTED with a pending application."""
        op, op_headers, e1, sp1, app1 = setup_event_standby_confirmed(
            display_overrides={"venue_id": "VEN-F1"},
        )
        mag, b1 = create_magazine_with_batch(op_headers)
        checkout_product(b1, e1, op_headers, 20)
        add_secured_post(e1, op_headers)
        # E2: second event, left in SUBMITTED with pending application.
        e2 = get_success_data(api.create_display(
            create_display_payload(
                venue_id="VEN-F2",
                scheduled_start_at="2026-09-05T20:00:00Z",
                scheduled_end_at="2026-09-05T23:00:00Z",
            ),
            op_headers,
        ))
        sp2 = add_site_plan(e2, op_headers)
        app2 = get_success_data(api.create_permit_application(
            e2["id"], {"site_plan_id": sp2["id"], "standby_engines": 1}, op_headers
        ))
        return op, op_headers, e1, e2, mag, b1, app1, app2

    def test_suspend_cancels_events_and_withdraws_applications(self, api):
        """PRD §3.1: "every one of that operator's `DisplayEvent` records
        still in `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, `APPROVED`,
        `STANDBY_CONFIRMED`, or `READY` is moved to `CANCELLED` with
        `cancellation_reason` set to `OPERATOR_SUSPENDED`"; §3.7: "Every
        non-terminal permit application of the event moves to `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/operator_suspend_cascade
        """
        op, op_headers, e1, e2, mag, b1, app1, app2 = \
            self._setup_operator_with_two_events(api)
        set_clock("2026-08-15T00:00:00Z")
        resp = api.suspend_operator(op["id"], {"reason": "ATF audit"}, ADMIN)
        op_after = validate_success(resp)
        assert op_after["status"] == "SUSPENDED"
        e1_after = get_success_data(api.get_display(e1["id"], ADMIN))
        assert e1_after["status"] == "CANCELLED"
        assert e1_after["cancellation_reason"] == "OPERATOR_SUSPENDED"
        e2_after = get_success_data(api.get_display(e2["id"], ADMIN))
        assert e2_after["status"] == "CANCELLED"
        apps, _ = validate_paginated(
            api.list_display_permit_applications(e2["id"], TEST_USERS["marshal_headers"])
        )
        assert apps[0]["status"] == "WITHDRAWN"

    def test_suspend_auto_returns_product_and_releases_posts(self, api):
        """PRD §3.7: "For every batch with `qty_at_show` above zero attributed
        to this event, the system writes a `RETURN` movement marked
        `auto_generated` true with `recorded_by_user_id` set to `system`",
        "Every security post of the event in `UNSTAFFED`, `STAFFED`, or
        `SECURED` moves to `RELEASED`", and "each affected magazine's
        `current_new_lbs` is recomputed per return."

        Design: Difficulty/transitive_cascade/operator_suspend_cascade
        """
        op, op_headers, e1, e2, mag, b1, app1, app2 = \
            self._setup_operator_with_two_events(api)
        set_clock("2026-08-15T00:00:00Z")
        validate_success(api.suspend_operator(op["id"], {"reason": "ATF audit"}, ADMIN))
        moves, meta = validate_paginated(api.list_batch_movements(b1["id"], op_headers))
        assert meta["total_count"] == 2
        auto_return = moves[1]  # created_at ASC: CHECK_OUT first, auto-RETURN second
        assert_inventory_movement(auto_return)
        assert auto_return["movement_type"] == "RETURN"
        assert auto_return["auto_generated"] is True
        assert auto_return["quantity"] == 20
        assert auto_return["recorded_by_user_id"] == "system"
        mag_after = get_success_data(api.get_magazine(mag["id"], op_headers))
        assert mag_after["current_new_lbs"] == 25.00  # all 50 units x 0.50 back home
        posts, _ = validate_paginated(
            api.list_security_posts(e1["id"], TEST_USERS["marshal_headers"])
        )
        assert posts[0]["status"] == "RELEASED"


class TestFalloutProvisionalVsFinal:
    def _setup_ready_5_declared_6_checked_out(self, api):
        """Event declared 5 in (boundary 500), site plan CURRENT; permit
        approved; standby confirmed; a 6 in batch checked out (gate passes:
        70×6 = 420 <= 500); SECURED post; LEAD crew; READY; fresh calm
        reading at show time."""
        op, op_headers = create_operator()
        ev = get_success_data(api.create_display(
            create_display_payload(
                venue_id="VEN-A", declared_max_shell_diameter_in=5,
            ),
            op_headers,
        ))
        sp = add_site_plan(ev, op_headers, spectator_boundary_ft=500,
                           nearest_structure_ft=600)
        app = get_success_data(api.create_permit_application(
            ev["id"], {"site_plan_id": sp["id"], "standby_engines": 1}, op_headers
        ))
        approve_permit(app)
        confirm_standby(ev, engines_on_site=1)
        mag = get_success_data(api.create_magazine(create_magazine_payload(), op_headers))
        b1 = get_success_data(api.create_batch(
            mag["id"],
            create_batch_payload(
                product_name="Shell 6in", shell_diameter_in=6, quantity_units=10,
                new_per_unit_lbs=0.50, lot_number="L6"),
            op_headers,
        ))
        checkout_product(b1, ev, op_headers, 10)
        crew, crew_headers = add_lead_crew(op, op_headers)
        add_secured_post(ev, op_headers, arc_degrees=30, radius_ft=500)
        validate_success(api.ready_display(ev["id"], op_headers))
        set_clock("2026-09-01T19:30:00Z")
        post_weather(ev, crew_headers, wind_speed_mph=5.0, gust_mph=12.0)
        ev = get_success_data(api.get_display(ev["id"], op_headers))
        return op, op_headers, ev, sp

    def test_provisional_radius_from_declared_diameter(self, api):
        """PRD §3.2: "the server computes the plan's
        `required_spectator_distance_ft` as 70 feet per inch of the parent
        event's `declared_max_shell_diameter_in`" — declared 5 in yields
        350 ft on the plan.

        Design: Difficulty/dual_variant_calc/fallout_radius_provisional_vs_final_site_plan
        """
        op, op_headers, ev, sp = self._setup_ready_5_declared_6_checked_out(api)
        assert sp["required_spectator_distance_ft"] == 350  # 70 x declared 5

    def test_final_radius_from_allocated_stock_diverges(self, api):
        """PRD §3.6: "The final base radius is 70 feet per inch of the
        greatest `shell_diameter_in` among batches with net `qty_at_show`
        above zero for the event at decision time — note this can differ from
        the declared diameter that drove the provisional site-plan figure
        whenever allocated stock differs from the declaration" and "When the
        sustained wind is below the 8-mph drift threshold, no adjustment
        applies."

        Design: Difficulty/dual_variant_calc/fallout_radius_provisional_vs_final_site_plan
        """
        op, op_headers, ev, sp = self._setup_ready_5_declared_6_checked_out(api)
        resp = go_decision(ev, op_headers, "GO")
        data = validate_success(resp)
        assert data["final_fallout_radius_ft"] == 420  # 70 x allocated 6; wind 5 < 8
        assert data["final_fallout_radius_ft"] != sp["required_spectator_distance_ft"]
        assert data["status"] == "IN_PROGRESS"
        assert data["weather_decision"] == "GO"
