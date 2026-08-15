"""Install scheduling: crew gates, overlap windows, labor cost, asset moves."""
from test_helpers import (
    ApiErrorId,
    create_asset_tag_payload,
    fixtures as fx,
    validate_error,
    validate_success,
    AE,
    ADMIN,
    CC,
    PM,
)


class TestEventCreationGates:
    def test_install_event_requires_order_acknowledged(self, api):
        """PRD section 3.6: "Event creation requires the order to be
        `ACKNOWLEDGED` or `DELIVERED`, else `ERR_ORDER_NOT_ACKNOWLEDGED`" — a
        merely `SUBMITTED` order cannot take an install event.

        Design: Difficulty/cross_entity_state_dependency/install_event_requires_order_acknowledged
        """
        ctx = fx.setup_submitted_order()
        fx.add_crew(ctx)
        resp = api.create_install_event(
            {
                "order_id": ctx.order["id"],
                "crew_id": ctx.crew["id"],
                "kind": "NEW_INSTALL",
                "scheduled_date": "2026-08-10",
                "start_minute": 540,
                "end_minute": 720,
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ACKNOWLEDGED)

    def test_install_event_requires_crew_active_create(self, api):
        """PRD section 3.6: "requires the crew to be `ACTIVE`, else
        `ERR_CREW_NOT_ACTIVE`" and PRD section 3.1: "Suspending a crew moves it
        to `SUSPENDED`; while suspended, any attempt to create or confirm an
        install event on that crew is rejected with `ERR_CREW_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/install_event_requires_crew_active
        """
        ctx = fx.setup_acknowledged_order()
        fx.add_crew(ctx)
        validate_success(api.suspend_crew(ctx.crew["id"], ADMIN))
        resp = api.create_install_event(
            {
                "order_id": ctx.order["id"],
                "crew_id": ctx.crew["id"],
                "kind": "NEW_INSTALL",
                "scheduled_date": "2026-08-10",
                "start_minute": 540,
                "end_minute": 720,
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_NOT_ACTIVE)

    def test_install_event_requires_crew_active_confirm(self, api):
        """PRD section 3.6: "Confirming a `TENTATIVE` event re-runs the same
        gates — crew `ACTIVE` and the overlap check including the turnover
        buffer against the crew's `CONFIRMED` and `IN_PROGRESS` events on that
        date" — confirming on a suspended crew fails.

        Design: Difficulty/cross_entity_state_dependency/install_event_requires_crew_active
        """
        ctx = fx.setup_acknowledged_order()
        event = fx.add_event(ctx)
        validate_success(api.suspend_crew(ctx.crew["id"], ADMIN))
        resp = api.confirm_event(event["id"], PM)
        validate_error(resp, ApiErrorId.ERR_CREW_NOT_ACTIVE)


class TestCrewOverlapBuffer:
    def _setup_with_confirmed_event(self):
        ctx = fx.setup_acknowledged_order()
        fx.add_confirmed_event(
            ctx, {"scheduled_date": "2026-08-10", "start_minute": 540,
                  "end_minute": 720}
        )
        return ctx

    def test_crew_buffer_exactly_30_ok(self, api):
        """PRD section 3.6: "the new event's window, widened on each side by
        the dealership's `turnover_buffer_minutes`, must not collide with any
        `CONFIRMED` or `IN_PROGRESS` event of the same crew on the same date,
        else `ERR_CREW_OVERLAP`" — with the default 30-minute buffer, a
        follow-up starting at 750 (exactly 720 + 30) widens to [720, 870) and
        does not collide with the confirmed [540, 720).

        Design: Difficulty/boundary_precision_check/crew_buffer_exactly_30_ok_29_conflict
        """
        ctx = self._setup_with_confirmed_event()
        resp = api.create_install_event(
            {
                "order_id": ctx.order["id"],
                "crew_id": ctx.crew["id"],
                "kind": "NEW_INSTALL",
                "scheduled_date": "2026-08-10",
                "start_minute": 750,
                "end_minute": 840,
            },
            PM,
        )
        assert validate_success(resp, 201)["status"] == "TENTATIVE"

    def test_crew_buffer_29_conflict(self, api):
        """PRD section 3.6: "the new event's window, widened on each side by
        the dealership's `turnover_buffer_minutes`, must not collide with any
        `CONFIRMED` or `IN_PROGRESS` event of the same crew on the same date,
        else `ERR_CREW_OVERLAP`" — a start at 749 widens to [719, 869) and
        collides with the confirmed [540, 720).

        Design: Difficulty/boundary_precision_check/crew_buffer_exactly_30_ok_29_conflict
        """
        ctx = self._setup_with_confirmed_event()
        resp = api.create_install_event(
            {
                "order_id": ctx.order["id"],
                "crew_id": ctx.crew["id"],
                "kind": "NEW_INSTALL",
                "scheduled_date": "2026-08-10",
                "start_minute": 749,
                "end_minute": 840,
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_OVERLAP)


class TestTentativeNonblocking:
    def test_crew_tentative_nonblocking_coexist(self, api):
        """PRD section 3.6: "the new event's window, widened on each side by
        the dealership's `turnover_buffer_minutes`, must not collide with any
        `CONFIRMED` or `IN_PROGRESS` event of the same crew on the same date,
        else `ERR_CREW_OVERLAP`" — two overlapping `TENTATIVE` events coexist
        because a tentative event holds no crew time. "A new event starts
        `TENTATIVE`".

        Design: Difficulty/resource_temporal_overlap/crew_tentative_nonblocking_exclusive_window
        """
        ctx = fx.setup_acknowledged_order()
        fx.add_crew(ctx)
        t1 = fx.add_event(ctx, {"start_minute": 540, "end_minute": 720})
        t2 = fx.add_event(ctx, {"start_minute": 660, "end_minute": 780})
        assert t1["status"] == "TENTATIVE"
        assert t2["status"] == "TENTATIVE"

    def test_crew_tentative_second_confirm_loses(self, api):
        """PRD section 3.6: "Confirming a `TENTATIVE` event re-runs the same
        gates — crew `ACTIVE` and the overlap check including the turnover
        buffer against the crew's `CONFIRMED` and `IN_PROGRESS` events on that
        date" — once the first event confirms [540, 720), the second
        overlapping event [660, 780) can no longer confirm: 660 < 720 + 30.

        Design: Difficulty/resource_temporal_overlap/crew_tentative_nonblocking_exclusive_window
        """
        ctx = fx.setup_acknowledged_order()
        fx.add_crew(ctx)
        t1 = fx.add_event(ctx, {"start_minute": 540, "end_minute": 720})
        t2 = fx.add_event(ctx, {"start_minute": 660, "end_minute": 780})
        confirmed = validate_success(api.confirm_event(t1["id"], PM))
        assert confirmed["status"] == "CONFIRMED"
        resp = api.confirm_event(t2["id"], PM)
        validate_error(resp, ApiErrorId.ERR_CREW_OVERLAP)


class TestEventWindowAndUnconfirm:
    def test_event_window_inverted_rejected(self, api):
        """PRD section 3.6: "a half-open time window from `start_minute`
        (0–1439) to `end_minute` (1–1440) — the window's end must be strictly
        greater than its start, else `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/event_window_inverted_rejected
        """
        ctx = fx.setup_acknowledged_order()
        fx.add_crew(ctx)
        resp = api.create_install_event(
            {
                "order_id": ctx.order["id"],
                "crew_id": ctx.crew["id"],
                "kind": "NEW_INSTALL",
                "scheduled_date": "2026-08-10",
                "start_minute": 720,
                "end_minute": 540,
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)

    def test_event_unconfirm_returns_to_tentative(self, api):
        """PRD section 3.6: "An event may be returned from `CONFIRMED` to
        `TENTATIVE` either explicitly by a `ProjectManager` or automatically by
        the promise-date cascade described in §3.7." and "when none of those
        hold, it is `NOT_SCHEDULED`" — with the only event back at TENTATIVE
        the posture drops to `NOT_SCHEDULED`.

        Design: Corner/state_machines/event_unconfirm_returns_to_tentative
        """
        ctx = fx.setup_acknowledged_order()
        event = fx.add_confirmed_event(ctx)
        unconfirmed = validate_success(api.unconfirm_event(event["id"], PM))
        assert unconfirmed["status"] == "TENTATIVE"
        order = validate_success(api.get_project_order(ctx.order["id"], PM))
        assert order["install_posture"] == "NOT_SCHEDULED"


class TestLaborCost:
    def test_labor_cost_after_hours_and_contract_override(self, api):
        """PRD section 3.6: "the hourly rate is the order's contract
        `labor_rate_cents_per_hour` when set, else the dealership's
        `standard_labor_rate_cents_per_hour`; the after-hours multiplier is the
        contract's `after_hours_multiplier_bp` when set, else the dealership's
        `after_hours_multiplier_bp`." and "The labor cost is then the standard
        minutes times the rate, plus the premium minutes times the rate times
        the multiplier in basis points divided by ten thousand, the whole
        divided by sixty, rounded half-up to whole cents."

        Design: Corner/calculations/labor_cost_after_hours_and_contract_override
        """
        dealership = fx.create_dealership()
        customer = fx.create_customer(dealership["id"])
        k1 = fx.create_active_contract(customer["id"])
        k2 = fx.create_active_contract(
            customer["id"],
            {"contract_type": "COOP", "after_hours_multiplier_bp": 20_000},
        )
        plan, _t = fx.create_approved_plan(customer["id"])
        series = fx.create_series(dealership["id"])
        crew_a = fx.create_crew(dealership["id"], {"name": "Crew Alpha"})
        crew_b = fx.create_crew(dealership["id"], {"name": "Crew Beta"})

        def ack_order(contract_id):
            order = fx.create_order(customer["id"], contract_id, plan["id"])
            fx.add_line(order["id"], series["id"], {"quantity": 1})
            validate_success(api.submit_order(order["id"], AE))
            return validate_success(api.acknowledge_order(order["id"], fx.REP))

        order_a = ack_order(k1["id"])
        order_b = ack_order(k2["id"])
        ev_a = validate_success(
            api.create_install_event(
                {"order_id": order_a["id"], "crew_id": crew_a["id"],
                 "kind": "NEW_INSTALL", "scheduled_date": "2026-08-10",
                 "start_minute": 540, "end_minute": 720},
                PM,
            ),
            201,
        )
        validate_success(api.confirm_event(ev_a["id"], PM))
        validate_success(api.start_event(ev_a["id"], PM))
        ev_b = validate_success(
            api.create_install_event(
                {"order_id": order_b["id"], "crew_id": crew_b["id"],
                 "kind": "NEW_INSTALL", "scheduled_date": "2026-08-10",
                 "start_minute": 960, "end_minute": 1200},
                PM,
            ),
            201,
        )
        validate_success(api.confirm_event(ev_b["id"], PM))
        validate_success(api.start_event(ev_b["id"], PM))
        done_a = validate_success(
            api.complete_event(ev_a["id"], {"labor_hours_actual": 3}, PM)
        )
        # 180 standard minutes at 10000 cents/hour -> 30000; no premium.
        assert done_a["labor_cost_cents"] == 30_000
        assert done_a["after_hours"] is False
        done_b = validate_success(
            api.complete_event(ev_b["id"], {"labor_hours_actual": 4}, PM)
        )
        # 120 standard + 120 premium minutes at contract 2.0x multiplier:
        # (120*10000 + 120*10000*20000/10000) / 60 = 60000.
        assert done_b["labor_cost_cents"] == 60_000
        assert done_b["after_hours"] is True


class TestAssetMovesAndBlockedOrder:
    def test_disposed_asset_move_rejected(self, api):
        """PRD section 3.6: "For a `RECONFIGURATION` event, completion
        additionally applies each `asset_moves` entry by setting the referenced
        asset tag's `current_location` to the entry's `to_location`; an entry
        referencing a `DISPOSED` asset is rejected with
        `ERR_ASSET_NOT_MOVABLE`."

        Design: Corner/validations/disposed_asset_move_rejected
        """
        ctx = fx.setup_acknowledged_order(line_overrides={"quantity": 1})
        crew_a = fx.create_crew(ctx.dealership["id"], {"name": "Crew Alpha"})
        crew_b = fx.create_crew(ctx.dealership["id"], {"name": "Crew Beta"})
        a1 = validate_success(
            api.create_asset_tag(
                create_asset_tag_payload(ctx.customer["id"],
                                         description="Chair 1",
                                         current_location="Floor 2"),
                AE,
            ),
            201,
        )
        a2 = validate_success(
            api.create_asset_tag(
                create_asset_tag_payload(ctx.customer["id"],
                                         description="Chair 2",
                                         current_location="Floor 2"),
                AE,
            ),
            201,
        )
        ev1 = validate_success(
            api.create_install_event(
                {"order_id": ctx.order["id"], "crew_id": crew_a["id"],
                 "kind": "RECONFIGURATION", "scheduled_date": "2026-08-10",
                 "start_minute": 540, "end_minute": 600,
                 "asset_moves": [{"asset_tag_id": a1["id"],
                                  "to_location": "Room 501"}]},
                PM,
            ),
            201,
        )
        validate_success(api.confirm_event(ev1["id"], PM))
        validate_success(api.start_event(ev1["id"], PM))
        validate_success(api.dispose_asset(a1["id"], AE))
        ev2 = validate_success(
            api.create_install_event(
                {"order_id": ctx.order["id"], "crew_id": crew_b["id"],
                 "kind": "RECONFIGURATION", "scheduled_date": "2026-08-10",
                 "start_minute": 540, "end_minute": 600,
                 "asset_moves": [{"asset_tag_id": a2["id"],
                                  "to_location": "Room 502"}]},
                PM,
            ),
            201,
        )
        validate_success(api.confirm_event(ev2["id"], PM))
        validate_success(api.start_event(ev2["id"], PM))
        resp = api.complete_event(ev1["id"], {"labor_hours_actual": 1}, PM)
        validate_error(resp, ApiErrorId.ERR_ASSET_NOT_MOVABLE)
        done2 = validate_success(
            api.complete_event(ev2["id"], {"labor_hours_actual": 1}, PM)
        )
        assert done2["status"] == "COMPLETED"
        a2_after = validate_success(api.get_asset_tag(a2["id"], AE))
        assert a2_after["current_location"] == "Room 502"

    def test_critical_punch_blocks_install_posture(self, api):
        """PRD section 3.6: "When any punch item of the order has `severity`
        `CRITICAL` and is in `OPEN` or `READY_FOR_VERIFY`, the posture is
        `BLOCKED`." and "Starting a `CONFIRMED` event moves it to
        `IN_PROGRESS`, but only when the order's `install_posture` is not
        `BLOCKED`; a start attempted against a blocked order is rejected with
        `ERR_ORDER_BLOCKED`."

        Design: Corner/complexity_layers/critical_punch_blocks_install_posture
        """
        ctx = fx.setup_acknowledged_order()
        event = fx.add_confirmed_event(ctx)
        punch = fx.add_punch(
            ctx,
            {"order_line_id": ctx.line["id"], "severity": "CRITICAL",
             "description": "Caster shear", "affected_units": 1},
        )
        blocked = validate_success(api.get_project_order(ctx.order["id"], PM))
        assert blocked["install_posture"] == "BLOCKED"
        resp = api.start_event(event["id"], PM)
        validate_error(resp, ApiErrorId.ERR_ORDER_BLOCKED)
        validate_success(api.ready_punch_for_verify(punch["id"], PM))
        verify = validate_success(api.verify_punch(punch["id"], {"passed": True}, CC))
        assert verify["status"] == "VERIFIED"
        unblocked = validate_success(api.get_project_order(ctx.order["id"], PM))
        assert unblocked["install_posture"] == "SCHEDULED"
        started = validate_success(api.start_event(event["id"], PM))
        assert started["status"] == "IN_PROGRESS"
