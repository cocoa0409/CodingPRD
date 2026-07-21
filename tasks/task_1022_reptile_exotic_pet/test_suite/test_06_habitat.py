"""Habitat builds: change-order cycle, install-buffer scheduling, OCC version guard."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    ApiErrorId, TEST_USERS,
    make_customer_headers,
    setup_habitat_build_in_progress,
)

_SALES = TEST_USERS["sales_associate_headers"]


class TestHabitatChangeOrderCycle:
    def test_two_change_rounds_accumulate_total(self, api):
        """PRD §3.8: "the owning `Customer` files a change order (moving it from `IN_PROGRESS` to `CHANGE_REQUESTED`) by supplying a `delta_cents` amount and the `expected_habitat_build_version` guard described in §2.10; the change order adds its `delta_cents` to the running `change_orders_total_cents` and increments the build's `version` by one."

        Design: Difficulty/non_linear_state_machine/habitat_build_change_request_cycle
        """
        ctx = setup_habitat_build_in_progress(api, quote_cents=100000)
        build = ctx["build"]
        cust = make_customer_headers(ctx["customer"]["id"])
        co1 = get_success_data(api.create_change_order(
            build["id"], {"delta_cents": 5000, "expected_habitat_build_version": build["version"]},
            headers=cust))
        assert co1["status"] == "CHANGE_REQUESTED"
        approved = get_success_data(api.approve_change(build["id"], headers=_SALES))
        co2 = validate_success(api.create_change_order(
            build["id"], {"delta_cents": 5000, "expected_habitat_build_version": approved["version"]},
            headers=cust))
        assert co2["status"] == "CHANGE_REQUESTED"
        assert co2["change_orders_total_cents"] == 10000

    def test_approve_change_returns_build_to_in_progress(self, api):
        """PRD §3.8: "A `SalesAssociate` approves the change to resume work, moving the build from `CHANGE_REQUESTED` back to `IN_PROGRESS`; this cycle may repeat."

        Design: Difficulty/non_linear_state_machine/habitat_build_change_request_cycle
        """
        ctx = setup_habitat_build_in_progress(api, quote_cents=100000)
        build = ctx["build"]
        cust = make_customer_headers(ctx["customer"]["id"])
        get_success_data(api.create_change_order(
            build["id"], {"delta_cents": 5000, "expected_habitat_build_version": build["version"]},
            headers=cust))
        resumed = validate_success(api.approve_change(build["id"], headers=_SALES))
        assert resumed["status"] == "IN_PROGRESS"
        assert resumed["change_orders_total_cents"] == 5000


class TestHabitatInstallBuffer:
    def _scheduled_first_build(self, api, email):
        ctx1 = setup_habitat_build_in_progress(
            api, customer=None, quote_cents=50000, spec_summary="build one")
        get_success_data(api.schedule_install(
            ctx1["build"]["id"],
            {"installer_id": "INST-X", "install_start_at": "2026-07-10T09:00:00Z",
             "install_end_at": "2026-07-10T11:00:00Z"},
            headers=_SALES))
        ctx2 = setup_habitat_build_in_progress(
            api, customer=ctx1["customer"], quote_cents=60000, spec_summary="build two")
        return ctx2["build"]

    def test_schedule_within_buffer_returns_conflict(self, api):
        """PRD §3.8: "on the same `installer_id`, the gap between the requested window and any other build's install window must be at least 60 minutes, and a request that leaves less than a 60-minute gap is rejected with `ERR_INSTALL_BUFFER_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/habitat_install_buffer_conflict
        """
        build2 = self._scheduled_first_build(api, "buffer1@x.com")
        # first ends 11:00; requesting 11:30 start leaves only a 30-minute gap (< 60)
        resp = api.schedule_install(
            build2["id"],
            {"installer_id": "INST-X", "install_start_at": "2026-07-10T11:30:00Z",
             "install_end_at": "2026-07-10T13:00:00Z"},
            headers=_SALES)
        validate_error(resp, ApiErrorId.ERR_INSTALL_BUFFER_CONFLICT.value)

    def test_schedule_with_exactly_sixty_minute_gap_succeeds(self, api):
        """PRD §3.8: "on the same `installer_id`, the gap between the requested window and any other build's install window must be at least 60 minutes, and a request that leaves less than a 60-minute gap is rejected with `ERR_INSTALL_BUFFER_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/habitat_install_buffer_conflict
        """
        build2 = self._scheduled_first_build(api, "buffer2@x.com")
        # first ends 11:00; requesting 12:00 start leaves exactly a 60-minute gap (>= 60)
        scheduled = validate_success(api.schedule_install(
            build2["id"],
            {"installer_id": "INST-X", "install_start_at": "2026-07-10T12:00:00Z",
             "install_end_at": "2026-07-10T14:00:00Z"},
            headers=_SALES))
        assert scheduled["install_start_at"] is not None


class TestHabitatOptimisticConcurrency:
    def test_stale_change_order_version_is_rejected(self, api):
        """PRD §2.10: "If `expected_habitat_build_version` does not equal the build's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/change_order_stale_version_returns_412
        """
        ctx = setup_habitat_build_in_progress(api, quote_cents=80000)
        build = ctx["build"]
        cust = make_customer_headers(ctx["customer"]["id"])
        v_start = build["version"]
        get_success_data(api.create_change_order(
            build["id"], {"delta_cents": 3000, "expected_habitat_build_version": v_start},
            headers=cust))
        # second change order still carries the pre-first (now stale) version
        resp = api.create_change_order(
            build["id"], {"delta_cents": 4000, "expected_habitat_build_version": v_start},
            headers=cust)
        # PRD §2.10 names ERR_STALE_VERSION; PRD §2.8 orders state legality before
        # business rules and the build is now CHANGE_REQUESTED, so a faithful reader may
        # surface ERR_INVALID_STATE instead — accept either (error-precedence).
        validate_error_is_one_of(resp, [ApiErrorId.ERR_STALE_VERSION.value,
                                        ApiErrorId.ERR_INVALID_STATE.value])
