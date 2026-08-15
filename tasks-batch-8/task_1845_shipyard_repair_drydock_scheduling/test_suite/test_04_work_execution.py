"""Work execution: critical path, derived readiness, dependency discipline,
pricing-mode validation, hot-work gates, and terminal lockdown."""
from test_helpers import (
    PM,
    ApiErrorId,
    add_base_work_item,
    apply_permit,
    assert_timestamp_instant,
    award_project,
    book_reservation,
    complete_item,
    create_draft_project,
    get_project,
    get_success_data,
    grant_permit,
    setup_in_dock_project,
    start_item,
    submit_bid,
    validate_error,
    validate_success,
)


class TestCriticalPath:
    def test_critical_path_longest_chain_value(self, api):
        """PRD §3.4: "For each such item, its chain length is its own
        `duration_days` plus the greatest chain length among the prerequisites
        it names in `depends_on_ids` that are themselves still unfinished; an
        item with no unfinished prerequisites contributes only its own
        duration. The project's `critical_path_days` is the greatest chain
        length among all unfinished items, and zero when none remain."
        PRD §3.4: "The forecast redelivery instant, `forecast_delivery_utc`,
        is then `actual_dock_in_utc` plus `critical_path_days` whole days plus
        the sum of `schedule_delta_days` across the project's `APPROVED` change
        orders"

        Design: Corner/calculations/critical_path_longest_chain_value
        """
        project = create_draft_project(contract_delivery_date="2026-08-20")
        item_a = add_base_work_item(
            project["id"], description="A", trade_code="HULL_STEEL", duration_days=5
        )
        item_b = add_base_work_item(
            project["id"], description="B", trade_code="HULL_STEEL",
            duration_days=3, depends_on_ids=[item_a["id"]],
        )
        add_base_work_item(
            project["id"], description="C", trade_code="PIPING",
            duration_days=4, depends_on_ids=[item_a["id"]],
        )
        add_base_work_item(
            project["id"], description="D", trade_code="COATINGS",
            duration_days=2, depends_on_ids=[item_b["id"]],
        )
        submit_bid(project["id"])
        award_project(project["id"])
        reservation = book_reservation(
            project["id"],
            start_utc="2026-08-01T00:00:00Z",
            end_utc="2026-08-30T00:00:00Z",
        )
        get_success_data(api.activate_dock_reservation(reservation["id"], PM))

        docked = get_project(project["id"])
        assert docked["critical_path_days"] == 10, (
            f"Longest chain A->B->D = 5+3+2 = 10 beats A->C = 5+4 = 9, got "
            f"{docked['critical_path_days']}"
        )
        assert_timestamp_instant(
            docked["forecast_delivery_utc"], "2026-08-11T00:00:00"
        )


class TestDerivedReadiness:
    def test_work_item_ready_flag_derived_from_dependencies(self, api):
        """PRD §3.4: "An item's `ready` flag is derived, never stored as a
        state: it is true exactly when the item is `PLANNED` and every item
        named in its `depends_on_ids` is `COMPLETE`."

        Design: Corner/state_machines/work_item_ready_flag_derived_from_dependencies
        """
        project = create_draft_project()
        item_a = add_base_work_item(
            project["id"], description="Strip coating", trade_code="COATINGS",
            duration_days=2,
        )
        item_b = add_base_work_item(
            project["id"], description="Apply coating", trade_code="COATINGS",
            duration_days=2, depends_on_ids=[item_a["id"]],
        )
        submit_bid(project["id"])
        award_project(project["id"])
        reservation = book_reservation(project["id"])
        get_success_data(api.activate_dock_reservation(reservation["id"], PM))

        before = get_success_data(api.get_work_item(item_b["id"], PM))
        assert before["ready"] is False, (
            "Dependency A is not COMPLETE, so B is not ready"
        )

        start_item(item_a["id"])
        complete_item(item_a["id"])

        after = get_success_data(api.get_work_item(item_b["id"], PM))
        assert after["ready"] is True, (
            "Readiness flips exactly when the dependency completes"
        )
        assert after["status"] == "PLANNED", (
            "Readiness is derived — no state write to the dependent item"
        )


class TestDependencyDiscipline:
    def test_dependency_cycle_rejected_on_patch(self, api):
        """PRD §3.4: "The edit is cycle-checked — the revised `depends_on_ids`
        must keep the project's work-item graph acyclic and must not reference
        the item itself, or it is rejected with `ERR_DEPENDENCY_CYCLE`"

        Design: Corner/validations/dependency_cycle_rejected_on_patch
        """
        project = create_draft_project()
        item_a = add_base_work_item(
            project["id"], description="A", trade_code="HULL_STEEL", duration_days=2
        )
        item_b = add_base_work_item(
            project["id"], description="B", trade_code="HULL_STEEL",
            duration_days=2, depends_on_ids=[item_a["id"]],
        )
        resp = api.patch_work_item(
            item_a["id"], {"depends_on_ids": [item_b["id"]]}, PM
        )
        validate_error(resp, ApiErrorId.ERR_DEPENDENCY_CYCLE)

    def test_start_with_unmet_dependency_returns_dependency_not_met(self, api):
        """PRD §3.4: "every item named in `depends_on_ids` must already be
        `COMPLETE`, or the start is rejected with `ERR_DEPENDENCY_NOT_MET`"

        Design: Corner/errors/start_with_unmet_dependency_returns_dependency_not_met
        """
        project = create_draft_project()
        item_a = add_base_work_item(
            project["id"], description="A", trade_code="COATINGS", duration_days=2
        )
        item_b = add_base_work_item(
            project["id"], description="B", trade_code="COATINGS",
            duration_days=2, depends_on_ids=[item_a["id"]],
        )
        submit_bid(project["id"])
        award_project(project["id"])
        reservation = book_reservation(project["id"])
        get_success_data(api.activate_dock_reservation(reservation["id"], PM))

        resp = api.start_work_item(item_b["id"], PM)
        validate_error(resp, ApiErrorId.ERR_DEPENDENCY_NOT_MET)


class TestPricingModeValidation:
    def test_tm_item_missing_hours_returns_pricing_invalid(self, api):
        """PRD §3.2: "A `TIME_AND_MATERIALS` line must supply `estimated_hours`
        greater than zero and an `hourly_rate_cents` of zero or more"
        PRD §3.2: "Any missing or non-positive mode-conditional input is
        rejected with `ERR_PRICING_INPUT_INVALID`."

        Design: Corner/validations/tm_item_missing_hours_returns_pricing_invalid
        """
        project = create_draft_project()
        resp = api.create_work_item(
            {
                "project_id": project["id"],
                "description": "T&M line",
                "trade_code": "MACHINERY",
                "pricing_mode": "TIME_AND_MATERIALS",
                "duration_days": 2,
                "hourly_rate_cents": 9500,
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_PRICING_INPUT_INVALID)


class TestHotWorkGate:
    def test_hot_work_without_permit_and_unmet_dependency_returns_safety_error(self, api):
        """PRD §2.9: "Every request is validated against an ordered ladder of
        rungs; a request failing any rung is rejected without evaluating later
        rungs, while checks sharing a rung carry no relative order among
        themselves." (Business safety — the hot-work permit gate
        `ERR_HOT_WORK_PERMIT_REQUIRED` — is rung 7; referential business
        checks — dependency completion `ERR_DEPENDENCY_NOT_MET` — are rung 10.)

        Design: Difficulty/priority_pair_validation_conflict/start_hot_work_without_permit_and_unmet_dependency_returns_safety_error
        """
        # Both lines join the base specification while the project is in DRAFT
        # (PRD §3.2); the dependency is then declared while the line is still
        # PLANNED (PRD §3.4), after the project has docked in.
        ctx = setup_in_dock_project(item_specs=[
            {"description": "Strip old coating", "trade_code": "COATINGS",
             "duration_days": 2, "quantity": 1, "unit_price_cents": 10000},
            {"description": "Weld doubler plate", "trade_code": "HULL_STEEL",
             "duration_days": 2, "quantity": 1, "unit_price_cents": 10000,
             "requires_hot_work": True},
        ])
        item_a, item_b = ctx["items"]
        get_success_data(
            api.patch_work_item(item_b["id"], {"depends_on_ids": [item_a["id"]]}, PM)
        )
        resp = api.start_work_item(item_b["id"], PM)
        validate_error(resp, ApiErrorId.ERR_HOT_WORK_PERMIT_REQUIRED)

    def test_hot_work_without_permit_alone_returns_safety_error(self, api):
        """PRD §3.4: "when `requires_hot_work` is true, the project must hold a
        `HOT_WORK` permit in `GRANTED` status whose window covers the current
        logical time — the time must fall on or after `valid_from` and on or
        before `valid_to` — or the start is rejected with
        `ERR_HOT_WORK_PERMIT_REQUIRED`; `SUSPENDED` and `EXPIRED` permits do
        not satisfy this gate."

        Design: Difficulty/priority_pair_validation_conflict/start_hot_work_without_permit_and_unmet_dependency_returns_safety_error
        """
        ctx = setup_in_dock_project(item_specs=[
            {"description": "Weld doubler plate", "trade_code": "HULL_STEEL",
             "duration_days": 2, "quantity": 1, "unit_price_cents": 10000,
             "requires_hot_work": True},
        ])
        item = ctx["items"][0]
        resp = api.start_work_item(item["id"], PM)
        validate_error(resp, ApiErrorId.ERR_HOT_WORK_PERMIT_REQUIRED)

    def test_hot_work_start_blocked_while_permit_only_applied(self, api):
        """PRD §3.4: "when `requires_hot_work` is true, the project must hold a
        `HOT_WORK` permit in `GRANTED` status whose window covers the current
        logical time — the time must fall on or after `valid_from` and on or
        before `valid_to` — or the start is rejected with
        `ERR_HOT_WORK_PERMIT_REQUIRED`; `SUSPENDED` and `EXPIRED` permits do
        not satisfy this gate."

        Design: Difficulty/cross_entity_state_dependency/hot_work_item_start_requires_granted_permit
        """
        ctx = setup_in_dock_project(item_specs=[
            {"description": "Weld doubler plate", "trade_code": "HULL_STEEL",
             "duration_days": 2, "quantity": 1, "unit_price_cents": 10000,
             "requires_hot_work": True},
        ])
        item = ctx["items"][0]
        apply_permit(ctx["project"]["id"], permit_type="HOT_WORK")

        resp = api.start_work_item(item["id"], PM)
        validate_error(resp, ApiErrorId.ERR_HOT_WORK_PERMIT_REQUIRED)

    def test_hot_work_start_succeeds_once_permit_granted(self, api):
        """PRD §3.4: "when `requires_hot_work` is true, the project must hold a
        `HOT_WORK` permit in `GRANTED` status whose window covers the current
        logical time — the time must fall on or after `valid_from` and on or
        before `valid_to` — or the start is rejected with
        `ERR_HOT_WORK_PERMIT_REQUIRED`"

        Design: Difficulty/cross_entity_state_dependency/hot_work_item_start_requires_granted_permit
        """
        ctx = setup_in_dock_project(item_specs=[
            {"description": "Weld doubler plate", "trade_code": "HULL_STEEL",
             "duration_days": 2, "quantity": 1, "unit_price_cents": 10000,
             "requires_hot_work": True},
        ])
        item = ctx["items"][0]
        permit = apply_permit(ctx["project"]["id"], permit_type="HOT_WORK")
        grant_permit(permit["id"])

        started = start_item(item["id"])
        assert started["status"] == "IN_PROGRESS", (
            "A GRANTED HOT_WORK permit covering the current logical time "
            "satisfies the start gate"
        )


class TestTerminalLockdown:
    def test_cancel_complete_work_item_returns_invalid_state(self, api):
        """PRD §3.4: "a cancel attempted against a line that is not `PLANNED`,
        or against a growth or rework line, is rejected with
        `ERR_INVALID_STATE`"

        Design: Corner/state_machines/cancel_complete_work_item_returns_invalid_state
        """
        ctx = setup_in_dock_project()
        item = ctx["items"][0]
        start_item(item["id"])
        complete_item(item["id"])
        resp = api.cancel_work_item(item["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
