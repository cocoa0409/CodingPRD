"""Cross-entity state dependencies (PRD §3.3, §3.6, §3.8): one entity's
transition is gated on the aggregate state of a related entity."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_switching_step,
    api_client,
    approve_outage_window,
    begin_switching,
    create_outage_window,
    create_verified_relay_setting,
    create_work_order,
    execute_step,
    set_clock,
    setup_asset,
    setup_defect_with_work_order,
    setup_relay_domain,
    validate_error,
    validate_success,
    verify_step,
)

OPS = TEST_USERS["ops_manager_headers"]
SUP1 = TEST_USERS["supervisor_headers"]
SUP2 = TEST_USERS["supervisor_alt_headers"]


class TestClearRequiresAllStepsVerified:
    def _setup_partially_verified_window(self) -> dict:
        """SWITCHING window with step1 VERIFIED and step2 merely EXECUTED."""
        base = setup_asset("POWER_TRANSFORMER", install_date="2020-01-01T00:00:00Z")
        window = create_outage_window(
            base["substation"]["id"], base["asset"]["id"],
            "2026-08-15T08:00:00Z", "2026-08-15T16:00:00Z", purpose="Testing",
        )
        step1 = add_switching_step(window["id"], 1, "Open breaker 1")
        step2 = add_switching_step(window["id"], 2, "Apply grounds")
        approve_outage_window(window["id"], "ops-mgr-1")
        set_clock("2026-08-15T09:00:00Z")
        begin_switching(window["id"], "sup-1")
        execute_step(step1["id"], "sup-1")
        verify_step(step1["id"], "sup-2")
        execute_step(step2["id"], "sup-1")
        return {**base, "window": window, "step1": step1, "step2": step2}

    def test_clear_rejected_while_a_step_is_not_verified(self):
        """PRD §3.3: "Clearing the window requires every switching step of the
        window to be `VERIFIED`; any shortfall is rejected with
        `ERR_STEPS_NOT_VERIFIED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/clear_requires_all_steps_verified
        """
        ctx = self._setup_partially_verified_window()
        resp = api_client.clear_outage_window(ctx["window"]["id"], SUP1)
        validate_error(resp, ApiErrorId.ERR_STEPS_NOT_VERIFIED)

    def test_clear_succeeds_once_all_steps_are_verified(self):
        """PRD §3.3: "Clearing the window requires every switching step of the
        window to be `VERIFIED`; any shortfall is rejected with
        `ERR_STEPS_NOT_VERIFIED` (HTTP 409). A successful clear transitions
        `SWITCHING → CLEARED`."

        Design: Difficulty/cross_entity_state_dependency/clear_requires_all_steps_verified
        """
        ctx = self._setup_partially_verified_window()
        resp = api_client.clear_outage_window(ctx["window"]["id"], SUP1)
        validate_error(resp, ApiErrorId.ERR_STEPS_NOT_VERIFIED)
        # Verify the outstanding step (by a different supervisor than its
        # executor), then the identical clear succeeds.
        verify_step(ctx["step2"]["id"], "sup-2")
        cleared = validate_success(api_client.clear_outage_window(ctx["window"]["id"], SUP1))
        assert cleared["status"] == "CLEARED"


class TestWorkOrderCreateRequiresOpenDefect:
    def test_second_work_order_on_same_defect_rejected(self):
        """PRD §3.6: "Creating a `WorkOrder` against an `OPEN` defect is an
        `OperationsManager` action supplying `defect_id`,
        `assigned_technician_id`, `title`, and `estimated_hours` (strictly
        greater than 0)."
        PRD §2.8: "then the state-machine permission check
        (`ERR_STATE_TRANSITION`, HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/workorder_create_requires_open_defect_rejected
        """
        ctx = setup_defect_with_work_order(severity="C2", estimated_hours=2)
        # The first work order moved the defect OPEN -> WORK_ORDERED, so a
        # second creation against the same defect is a state violation.
        resp = api_client.create_work_order(
            {
                "defect_id": ctx["defect"]["id"],
                "assigned_technician_id": ctx["technician"]["id"],
                "title": "Duplicate order",
                "estimated_hours": 1,
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_STATE_TRANSITION)

    def test_defect_remains_work_ordered_after_rejected_create(self):
        """PRD §3.6: "Creation transitions the defect `OPEN → WORK_ORDERED` and
        leaves the work order in `DRAFT` with `outage_window_id` null and
        `labor_lines` and `parts_lines` both empty arrays."
        PRD §2.8: "then the state-machine permission check
        (`ERR_STATE_TRANSITION`, HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/workorder_create_requires_open_defect_rejected
        """
        ctx = setup_defect_with_work_order(severity="C2", estimated_hours=2)
        resp = api_client.create_work_order(
            {
                "defect_id": ctx["defect"]["id"],
                "assigned_technician_id": ctx["technician"]["id"],
                "title": "Duplicate order",
                "estimated_hours": 1,
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_STATE_TRANSITION)
        defect = validate_success(api_client.get_defect(ctx["defect"]["id"], OPS))
        assert defect["status"] == "WORK_ORDERED"


class TestRelayActivateRequiresAssetInService:
    def _setup_out_of_service_relay_with_verified_setting(self) -> dict:
        domain = setup_relay_domain()
        setting = create_verified_relay_setting(
            domain["asset"]["id"], domain["author_headers"], domain["verifier_headers"],
            pickup_a=80,
        )
        # Take the relay asset OUT_OF_SERVICE via a switching outage.
        window = create_outage_window(
            domain["substation"]["id"], domain["asset"]["id"],
            "2026-08-20T08:00:00Z", "2026-08-20T16:00:00Z", purpose="Relay work",
        )
        add_switching_step(window["id"], 1, "Isolate relay panel")
        approve_outage_window(window["id"], "ops-mgr-1")
        set_clock("2026-08-20T09:00:00Z")
        begin_switching(window["id"], "sup-1")
        return {**domain, "setting": setting, "window": window}

    def test_activate_rejected_when_asset_out_of_service(self):
        """PRD §3.8: "The asset must be `IN_SERVICE` — activation against an
        asset in any other state is rejected with `ERR_ASSET_NOT_IN_SERVICE`
        (HTTP 409)."
        PRD §3.3: "Success transitions the window `APPROVED → SWITCHING` and
        drives the asset `IN_SERVICE → OUT_OF_SERVICE`, incrementing both
        entities' versions."

        Design: Difficulty/cross_entity_state_dependency/relay_activate_requires_asset_in_service_rejected
        """
        ctx = self._setup_out_of_service_relay_with_verified_setting()
        asset = validate_success(api_client.get_asset(ctx["asset"]["id"], OPS))
        assert asset["status"] == "OUT_OF_SERVICE"
        resp = api_client.activate_relay_setting(
            ctx["setting"]["id"],
            {"expected_asset_version": asset["version"]},
            ctx["verifier_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ASSET_NOT_IN_SERVICE)

    def test_setting_remains_verified_after_rejected_activation(self):
        """PRD §3.8: "The asset must be `IN_SERVICE` — activation against an
        asset in any other state is rejected with `ERR_ASSET_NOT_IN_SERVICE`
        (HTTP 409)."
        PRD §3.8: "Verification transitions `SUBMITTED → VERIFIED` and stamps
        `verified_by_technician_id`."

        Design: Difficulty/cross_entity_state_dependency/relay_activate_requires_asset_in_service_rejected
        """
        ctx = self._setup_out_of_service_relay_with_verified_setting()
        asset = validate_success(api_client.get_asset(ctx["asset"]["id"], OPS))
        resp = api_client.activate_relay_setting(
            ctx["setting"]["id"],
            {"expected_asset_version": asset["version"]},
            ctx["verifier_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ASSET_NOT_IN_SERVICE)
        setting = validate_success(api_client.get_relay_setting(ctx["setting"]["id"], OPS))
        assert setting["status"] == "VERIFIED"
