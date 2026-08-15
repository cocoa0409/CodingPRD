"""Work package lifecycle: initial state, valid/invalid transitions, terminal
lockdown, and the two completion gates (open rework, open material issues)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_work_package,
    create_work_package_payload,
    fail_entry,
    get_success_data,
    issue_material,
    report_production,
    setup_active_contract,
    setup_field_scenario,
    setup_stock_item,
    validate_error,
    validate_success,
)

PM = TEST_USERS["contractor_pm_headers"]
FOREMAN = TEST_USERS["foreman_headers"]


class TestInitialState:
    def test_new_work_package_starts_planned(self, api):
        """PRD §3.2: "A new work package stands in `PLANNED`."

        Design: Corner/state_machines/new_work_package_initial_state_planned
        """
        contract, _ = setup_active_contract(
            contract_overrides={"contract_number": "CS-3"})
        wp = validate_success(api.create_work_package(
            contract["id"],
            create_work_package_payload(name="WP init", location="L3"),
            PM), 201)
        assert_work_package(wp)
        assert wp["status"] == "PLANNED", "A new work package stands in PLANNED"


class TestTransitionRules:
    def test_work_package_backward_transition_rejected(self, api):
        """PRD §3.2: "Its lifecycle proceeds by transition requests naming `to`:
        from `PLANNED` to `MOBILIZED`, which requires the contract to be `ACTIVE`
        and otherwise surfaces `ERR_CONTRACT_NOT_ACTIVE` or
        `ERR_CONTRACT_SUSPENDED`; from `MOBILIZED` to `IN_PROGRESS`, which
        requires at least one assignment of the package to stand in `PLANNED` or
        `ACTIVE` and otherwise fails with `ERR_INVALID_STATE`; from `IN_PROGRESS`
        to `PUNCH` without further preconditions"
        PRD §2.9: "7. Lifecycle and source-state gates — the entity must stand in
        a valid source state for the requested transition or child operation,
        otherwise `ERR_INVALID_STATE`; bid item creation outside `DRAFT` yields
        `ERR_BID_ITEMS_LOCKED`."
        `MOBILIZED` is not a valid target from `IN_PROGRESS`.

        Design: Corner/state_machines/work_package_backward_transition_rejected
        """
        scenario = setup_field_scenario(
            activate=False,
            contract_overrides={"contract_number": "CS-1"},
            wp_overrides={"name": "WP back", "location": "L1"})
        wp_id = scenario["work_package"]["id"]
        resp = api.transition_work_package(wp_id, {"to": "MOBILIZED"}, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        wp_after = validate_success(api.get_work_package(wp_id, PM))
        assert wp_after["status"] == "IN_PROGRESS", (
            "The rejected backward transition leaves the package IN_PROGRESS")

    def test_completed_work_package_is_terminal(self, api):
        """PRD §3.2: "A work package may instead be cancelled from `PLANNED`,
        `MOBILIZED`, or `IN_PROGRESS`; cancellation moves every assignment
        standing in `PLANNED` or `ACTIVE` to `CANCELLED` and voids every invoice
        in `DRAFT` or `REJECTED`, releasing their frozen unit pool."
        PRD §2.9: "7. Lifecycle and source-state gates — the entity must stand in
        a valid source state for the requested transition or child operation,
        otherwise `ERR_INVALID_STATE`; bid item creation outside `DRAFT` yields
        `ERR_BID_ITEMS_LOCKED`."
        `COMPLETED` is not among the cancellable source states.

        Design: Corner/state_machines/completed_work_package_is_terminal
        """
        scenario = setup_field_scenario(
            activate=False,
            contract_overrides={"contract_number": "CS-2"},
            wp_overrides={"name": "WP term", "location": "L2"})
        wp_id = scenario["work_package"]["id"]
        get_success_data(api.transition_work_package(wp_id, {"to": "PUNCH"}, PM))
        wp = get_success_data(api.transition_work_package(
            wp_id, {"to": "COMPLETED"}, PM))
        assert wp["status"] == "COMPLETED"

        resp = api.transition_work_package(wp_id, {"to": "CANCELLED"}, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        wp_after = validate_success(api.get_work_package(wp_id, PM))
        assert wp_after["status"] == "COMPLETED", (
            "A COMPLETED work package is terminal and stays COMPLETED")


class TestCompletionGates:
    def test_work_package_complete_blocked_by_open_rework(self, api):
        """PRD §3.2: "and from `PUNCH` to `COMPLETED`, which is gated twice — the
        package's `rework_open_count` must be zero or the transition fails with
        `ERR_OPEN_REWORK`, and its `open_material_issue_count` must be zero or it
        fails with `ERR_OPEN_MATERIAL_ISSUES`."

        Design: Corner/validations/work_package_complete_blocked_by_open_rework
        """
        scenario = setup_field_scenario(
            contract_overrides={"contract_number": "CV-15"},
            wp_overrides={"name": "WP rw", "location": "L21"})
        wp_id = scenario["work_package"]["id"]
        entry = report_production(scenario["assignment"]["id"],
                                  scenario["bid_item"]["id"], "2026-08-04", 5)
        fail_entry(wp_id, entry["id"])
        get_success_data(api.transition_work_package(wp_id, {"to": "PUNCH"}, PM))

        resp = api.transition_work_package(wp_id, {"to": "COMPLETED"}, PM)
        validate_error(resp, ApiErrorId.ERR_OPEN_REWORK)
        wp_after = validate_success(api.get_work_package(wp_id, PM))
        assert wp_after["status"] == "PUNCH", (
            "Open rework blocks completion; the package remains PUNCH")
        assert wp_after["rework_open_count"] == 1

    def test_completion_blocked_by_open_material_issues(self, api):
        """PRD §3.2: "and from `PUNCH` to `COMPLETED`, which is gated twice — the
        package's `rework_open_count` must be zero or the transition fails with
        `ERR_OPEN_REWORK`, and its `open_material_issue_count` must be zero or it
        fails with `ERR_OPEN_MATERIAL_ISSUES`."

        Design: Difficulty/cross_entity_state_dependency/completion_requires_material_reconciliation
        """
        scenario = setup_field_scenario(
            activate=False,
            contract_overrides={"contract_number": "C-801"},
            bid_item_overrides={"item_code": "OH-POLE-40",
                                "description": "40ft pole", "unit_price": 90.00,
                                "estimated_quantity": 30},
            wp_overrides={"name": "Pole repl P-8", "location": "Feeder F-8"},
            crew_overrides={"crew_code": "CR-W"},
            equipment_overrides={"equipment_code": "EQ-W",
                                 "kind": "DIGGER_DERRICK", "daily_rate": 200.00})
        wp_id = scenario["work_package"]["id"]
        stock = setup_stock_item(scenario["contract"]["id"], initial_on_hand=10,
                                 material_code="POLE-40",
                                 description="40ft wood pole")
        issue = issue_material(wp_id, stock["id"], 10)
        assert issue["status"] == "OPEN"
        get_success_data(api.transition_work_package(wp_id, {"to": "PUNCH"}, PM))

        resp = api.transition_work_package(wp_id, {"to": "COMPLETED"}, PM)
        validate_error(resp, ApiErrorId.ERR_OPEN_MATERIAL_ISSUES)
        wp_after = validate_success(api.get_work_package(wp_id, PM))
        assert wp_after["status"] == "PUNCH"
        assert wp_after["open_material_issue_count"] == 1, (
            "The OPEN issue still counts against completion")

    def test_completion_succeeds_after_material_reconciled(self, api):
        """PRD §3.4: "When installed plus returned exactly equals issued, a
        foreman reconciles directly: the issue moves to `RECONCILED`, its
        `variance` is recorded as zero, and the package's
        `open_material_issue_count` drops by one."
        PRD §3.2: "and from `PUNCH` to `COMPLETED`, which is gated twice — the
        package's `rework_open_count` must be zero or the transition fails with
        `ERR_OPEN_REWORK`, and its `open_material_issue_count` must be zero or it
        fails with `ERR_OPEN_MATERIAL_ISSUES`."

        Design: Difficulty/cross_entity_state_dependency/completion_requires_material_reconciliation
        """
        scenario = setup_field_scenario(
            activate=False,
            contract_overrides={"contract_number": "C-801"},
            bid_item_overrides={"item_code": "OH-POLE-40",
                                "description": "40ft pole", "unit_price": 90.00,
                                "estimated_quantity": 30},
            wp_overrides={"name": "Pole repl P-8", "location": "Feeder F-8"},
            crew_overrides={"crew_code": "CR-W"},
            equipment_overrides={"equipment_code": "EQ-W",
                                 "kind": "DIGGER_DERRICK", "daily_rate": 200.00})
        wp_id = scenario["work_package"]["id"]
        stock = setup_stock_item(scenario["contract"]["id"], initial_on_hand=10,
                                 material_code="POLE-40",
                                 description="40ft wood pole")
        issue = issue_material(wp_id, stock["id"], 10)
        get_success_data(api.transition_work_package(wp_id, {"to": "PUNCH"}, PM))

        # Return 4 and reconcile 6 installed: 6 + 4 == 10 issued, exact match.
        returned = get_success_data(api.return_material_issue(
            issue["id"], {"quantity": 4}, FOREMAN))
        assert returned["quantity_returned"] == 4
        reconciled = get_success_data(api.reconcile_material_issue(
            issue["id"], {"quantity_installed": 6}, FOREMAN))
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["variance"] == 0, "Exact match records variance zero"
        assert reconciled["quantity_installed"] == 6

        wp_mid = validate_success(api.get_work_package(wp_id, PM))
        assert wp_mid["open_material_issue_count"] == 0, (
            "Reconciliation drops the open-issue counter to zero")
        wp_done = validate_success(api.transition_work_package(
            wp_id, {"to": "COMPLETED"}, PM))
        assert wp_done["status"] == "COMPLETED", (
            "With both gates clear the PUNCH -> COMPLETED transition succeeds")
