"""Meter sizing, meter set lifecycle, purge & leak tests, and witness segregation."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_inspector_payload,
    create_meter_set_payload,
    get_success_data,
    make_inspector_headers,
    record_purge_leak_test,
    refresh_application,
    refresh_meter_set,
    refresh_purge_leak_test,
    setup_load_confirmed_app,
    setup_meter_installed_app,
    setup_testing_app,
    validate_error,
    validate_paginated,
)


class TestMeterSizing:
    def test_exact_capacity_boundary_selects_model(self, api, engineer_headers,
                                                   technician_headers):
        """PRD §3.6: "The selected `meter_model` is the model with the smallest pressure-adjusted capacity that still covers the diversity-adjusted load, and a capacity exactly equal to the load selects that model rather than the next size up."
        PRD §3.6: "Sizing compares the application's `diversity_adjusted_load_cfph` against five meter models whose base capacities are 425, 800, 1,400, 2,300, and 5,000 cubic feet per hour — the models `AL_425`, `AL_800`, `AL_1400`, `AL_2300`, and `AL_5000` respectively."
        PRD §3.6: "Each meter pairs with exactly one regulator, recorded as `regulator_model`: `AL_425` with `R_325`, `AL_800` with `R_750`, `AL_1400` with `R_1200`, `AL_2300` with `R_2100`, and `AL_5000` with `R_4500`."

        Design: Corner/calculations/meter_sizing_exact_capacity_boundary
        """
        two_rows = [
            {"appliance_type": "FURNACE", "quantity": 1, "btuh_input_rating": 250000},
            {"appliance_type": "POOL_HEATER", "quantity": 1, "btuh_input_rating": 250000},
        ]
        ctx_x = setup_load_confirmed_app(
            loads=two_rows, service_address="100 Boundary Rd"
        )
        assert ctx_x["app"]["diversity_adjusted_load_cfph"] == pytest.approx(425.0)
        ms_x = get_success_data(
            api.create_meter_set(
                create_meter_set_payload(ctx_x["app"]["id"]), technician_headers
            )
        )
        sized_x = get_success_data(api.size_meter_set(ms_x["id"], engineer_headers))
        assert sized_x["status"] == "SIZED"
        assert sized_x["meter_model"] == "AL_425", (
            f"425.0 == AL_425 capacity selects AL_425, got {sized_x['meter_model']}"
        )
        assert sized_x["regulator_model"] == "R_325"

        three_rows = two_rows + [
            {"appliance_type": "STANDBY_GENERATOR", "quantity": 1,
             "btuh_input_rating": 250000},
        ]
        ctx_y = setup_load_confirmed_app(
            loads=three_rows, service_address="200 Boundary Rd"
        )
        assert ctx_y["app"]["diversity_adjusted_load_cfph"] == pytest.approx(637.5)
        ms_y = get_success_data(
            api.create_meter_set(
                create_meter_set_payload(ctx_y["app"]["id"]), technician_headers
            )
        )
        sized_y = get_success_data(api.size_meter_set(ms_y["id"], engineer_headers))
        assert sized_y["status"] == "SIZED"
        assert sized_y["meter_model"] == "AL_800", (
            f"637.5 exceeds AL_425, next size up covers it, got {sized_y['meter_model']}"
        )
        assert sized_y["regulator_model"] == "R_750"

    def test_load_beyond_largest_model_rejected(self, api, engineer_headers,
                                                technician_headers):
        """PRD §3.6: "When even the largest model's adjusted capacity falls short, sizing is rejected with `ERR_METER_SIZE_UNAVAILABLE` (HTTP 422)."
        PRD §3.1: "`appliance_count` is the number of load rows (not the sum of their quantities)."

        Design: Corner/calculations/meter_size_unavailable_rejected
        """
        ctx = setup_load_confirmed_app(
            loads=[{"appliance_type": "OTHER", "quantity": 90,
                    "btuh_input_rating": 100000}],
            service_address="300 Industrial Pkwy",
        )
        assert ctx["app"]["appliance_count"] == 1, (
            "one row with quantity 90: the row count drives the diversity tier"
        )
        assert ctx["app"]["diversity_adjusted_load_cfph"] == pytest.approx(9000.0)

        ms = get_success_data(
            api.create_meter_set(
                create_meter_set_payload(ctx["app"]["id"]), technician_headers
            )
        )
        resp = api.size_meter_set(ms["id"], engineer_headers)
        validate_error(resp, ApiErrorId.ERR_METER_SIZE_UNAVAILABLE, expected_status=422)

        after = refresh_meter_set(ms["id"])
        assert after["status"] == "PLANNED"
        assert not after.get("meter_model"), "a rejected sizing must not set a model"


class TestMeterSetLifecycle:
    def test_duplicate_meter_set_rejected(self, api, technician_headers):
        """PRD §3.6: "it starts in `PLANNED`, and an application may have at most one non-`CANCELLED` meter set (`ERR_DUPLICATE_METER_SET`, HTTP 409)."

        Design: Corner/errors/duplicate_meter_set_rejected
        """
        ctx = setup_load_confirmed_app()
        first = get_success_data(
            api.create_meter_set(
                create_meter_set_payload(ctx["app"]["id"]), technician_headers
            )
        )
        assert first["status"] == "PLANNED"

        resp = api.create_meter_set(
            create_meter_set_payload(ctx["app"]["id"]), technician_headers
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_METER_SET, expected_status=409)

        resp = api.list_meter_sets(
            technician_headers, params={"service_application_id": ctx["app"]["id"]}
        )
        _, meta = validate_paginated(resp)
        assert meta["total_count"] == 1

    def test_install_before_service_line_rejected(self, api, engineer_headers,
                                                  technician_headers):
        """PRD §3.6: "Installation requires the application to be exactly at `SERVICE_INSTALLED`, else `ERR_SERVICE_LINE_NOT_INSTALLED` (HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/meter_install_needs_service_line_complete
        """
        from test_helpers import setup_ciac_pending_app
        ctx = setup_ciac_pending_app(design_footage_ft=100, crossings=[])
        assert ctx["app"]["status"] == "APPROVED_FOR_CONSTRUCTION"

        ms = get_success_data(
            api.create_meter_set(
                create_meter_set_payload(ctx["app"]["id"]), technician_headers
            )
        )
        get_success_data(api.size_meter_set(ms["id"], engineer_headers))
        get_success_data(
            api.mark_meter_ordered(ms["id"], {"serial_number": "M-9001"},
                                   technician_headers)
        )

        resp = api.install_meter_set(ms["id"], technician_headers)
        validate_error(resp, ApiErrorId.ERR_SERVICE_LINE_NOT_INSTALLED,
                       expected_status=409)

    def test_rejected_install_leaves_no_trace(self, api, engineer_headers,
                                              technician_headers):
        """PRD §3.6: "a successful install stamps `installed_by_user_id` and `installed_at`, moves the set from `ORDERED` to `INSTALLED`, and pushes the application from `SERVICE_INSTALLED` into `METER_WORK`."

        Design: Difficulty/cross_entity_state_dependency/meter_install_needs_service_line_complete
        """
        from test_helpers import setup_ciac_pending_app
        ctx = setup_ciac_pending_app(design_footage_ft=100, crossings=[])
        ms = get_success_data(
            api.create_meter_set(
                create_meter_set_payload(ctx["app"]["id"]), technician_headers
            )
        )
        get_success_data(api.size_meter_set(ms["id"], engineer_headers))
        get_success_data(
            api.mark_meter_ordered(ms["id"], {"serial_number": "M-9001"},
                                   technician_headers)
        )

        resp = api.install_meter_set(ms["id"], technician_headers)
        validate_error(resp, ApiErrorId.ERR_SERVICE_LINE_NOT_INSTALLED,
                       expected_status=409)

        after = refresh_meter_set(ms["id"])
        assert after["status"] == "ORDERED"
        assert not after.get("installed_by_user_id")
        assert not after.get("installed_at")
        assert refresh_application(ctx["app"]["id"])["status"] == "APPROVED_FOR_CONSTRUCTION"


class TestLeakTestAcceptance:
    def test_drop_equal_to_allowance_passes(self, api):
        """PRD §3.6: "At record time the system computes the acceptance criterion: the `max_allowed_drop_psi` is the reference allowance of 0.300 psi over a reference duration of sixty minutes, scaled by the actual hold — 0.300 multiplied by 60, divided by the test's duration in minutes — rounded half up to three decimal places. The computed `result` is `PASS` when the observed drop is less than or equal to that allowance — a drop exactly equal to the allowed maximum passes — and `FAIL` when it is greater."

        Design: Difficulty/boundary_precision_check/leak_test_drop_equals_allowance_passes
        """
        ctx = setup_meter_installed_app()
        plt = record_purge_leak_test(
            ctx["meter_set"]["id"], observed_pressure_drop_psi=0.300
        )
        assert plt["max_allowed_drop_psi"] == pytest.approx(0.300), (
            f"0.300 x 60 / 60 = 0.300, got {plt['max_allowed_drop_psi']}"
        )
        assert plt["result"] == "PASS", "a drop exactly equal to the allowance passes"

    def test_recording_moves_meter_and_application_to_testing(self, api):
        """PRD §3.6: "Recording the test moves the meter set from `INSTALLED` (or from `REPAIR`, after a repair loop) to `TESTING` and the application from `METER_WORK` to `TESTING`, and stamps the technician's identity as `installer_user_id`."

        Design: Difficulty/boundary_precision_check/leak_test_drop_equals_allowance_passes
        """
        ctx = setup_testing_app(observed_drop=0.300)
        assert ctx["plt"]["status"] == "RECORDED"
        assert ctx["plt"]["installer_user_id"] == "tech-1"
        assert ctx["meter_set"]["status"] == "TESTING"
        assert ctx["app"]["status"] == "TESTING"


class TestFailRepairRetestCycle:
    def _setup_fail_then_repair(self, api, admin_headers):
        ctx = setup_meter_installed_app()
        failing = record_purge_leak_test(
            ctx["meter_set"]["id"], observed_pressure_drop_psi=0.301
        )
        assert failing["result"] == "FAIL", "0.301 > 0.300 allowance"
        ctx["plt_fail"] = failing
        ctx["inspector"] = get_success_data(
            api.create_inspector(create_inspector_payload(), admin_headers)
        )
        return ctx

    def test_certified_fail_loops_meter_through_repair(self, api, admin_headers,
                                                       technician_headers):
        """PRD §3.6: "when the result is `FAIL`, the meter set drops to `REPAIR`, from which the technician's mark-repaired returns it to `INSTALLED` for another attempt."

        Design: Difficulty/non_linear_state_machine/meter_set_fail_repair_retest_cycle
        """
        ctx = self._setup_fail_then_repair(api, admin_headers)
        get_success_data(
            api.certify_purge_leak_test(
                ctx["plt_fail"]["id"], make_inspector_headers(ctx["inspector"]["id"])
            )
        )
        assert refresh_meter_set(ctx["meter_set"]["id"])["status"] == "REPAIR"

        repaired = get_success_data(
            api.mark_meter_repaired(ctx["meter_set"]["id"], technician_headers)
        )
        assert repaired["status"] == "INSTALLED", (
            "the repair loop closes back to INSTALLED for another attempt"
        )

    def test_passing_retest_advances_to_turn_on(self, api, admin_headers,
                                                technician_headers):
        """PRD §3.6: "Certifying stamps `witness_inspector_id` and moves the test from `RECORDED` to `CERTIFIED`, with a two-link consequence: when the result is `PASS`, the meter set moves from `TESTING` to `READY_FOR_TURN_ON` and the application bubbles from `TESTING` to `TURN_ON`; when the result is `FAIL`, the meter set drops to `REPAIR`, from which the technician's mark-repaired returns it to `INSTALLED` for another attempt."

        Design: Difficulty/non_linear_state_machine/meter_set_fail_repair_retest_cycle
        """
        ctx = self._setup_fail_then_repair(api, admin_headers)
        get_success_data(
            api.certify_purge_leak_test(
                ctx["plt_fail"]["id"], make_inspector_headers(ctx["inspector"]["id"])
            )
        )
        get_success_data(api.mark_meter_repaired(ctx["meter_set"]["id"], technician_headers))

        passing = record_purge_leak_test(
            ctx["meter_set"]["id"], observed_pressure_drop_psi=0.300
        )
        assert passing["result"] == "PASS", "equality passes on the second attempt"
        get_success_data(
            api.certify_purge_leak_test(
                passing["id"], make_inspector_headers(ctx["inspector"]["id"])
            )
        )

        assert refresh_meter_set(ctx["meter_set"]["id"])["status"] == "READY_FOR_TURN_ON"
        assert refresh_application(ctx["app"]["id"])["status"] == "TURN_ON", (
            "the spine advances only on the passing loop iteration"
        )
        history = refresh_purge_leak_test(ctx["plt_fail"]["id"])
        assert history["status"] == "CERTIFIED"
        assert history["result"] == "FAIL", "the failed attempt stays on record"


class TestCertifyCascade:
    def test_certify_pass_moves_test_and_meter(self, api, admin_headers):
        """PRD §3.6: "Certifying stamps `witness_inspector_id` and moves the test from `RECORDED` to `CERTIFIED`, with a two-link consequence: when the result is `PASS`, the meter set moves from `TESTING` to `READY_FOR_TURN_ON` and the application bubbles from `TESTING` to `TURN_ON`"

        Design: Difficulty/transitive_cascade/certify_pass_three_link_cascade
        """
        ctx = setup_testing_app(observed_drop=0.300)
        inspector = get_success_data(
            api.create_inspector(create_inspector_payload(), admin_headers)
        )
        certified = get_success_data(
            api.certify_purge_leak_test(
                ctx["plt"]["id"], make_inspector_headers(inspector["id"])
            )
        )
        assert certified["status"] == "CERTIFIED"
        assert certified["witness_inspector_id"] == inspector["id"]
        assert refresh_meter_set(ctx["meter_set"]["id"])["status"] == "READY_FOR_TURN_ON", (
            "link 1: the meter set reacts to the certification"
        )

    def test_certify_pass_bubbles_application_and_versions(self, api, admin_headers):
        """PRD §3.6: "when the result is `PASS`, the meter set moves from `TESTING` to `READY_FOR_TURN_ON` and the application bubbles from `TESTING` to `TURN_ON`"
        PRD §2.4: "`version` (integer): starts as a small integer and increments by one on every mutation of the resource — including system-driven mutations caused by cascades from other resources, not just direct client writes."

        Design: Difficulty/transitive_cascade/certify_pass_three_link_cascade
        """
        ctx = setup_testing_app(observed_drop=0.300)
        inspector = get_success_data(
            api.create_inspector(create_inspector_payload(), admin_headers)
        )
        before = {
            "plt": refresh_purge_leak_test(ctx["plt"]["id"])["version"],
            "ms": refresh_meter_set(ctx["meter_set"]["id"])["version"],
            "app": refresh_application(ctx["app"]["id"])["version"],
        }
        get_success_data(
            api.certify_purge_leak_test(
                ctx["plt"]["id"], make_inspector_headers(inspector["id"])
            )
        )
        plt_after = refresh_purge_leak_test(ctx["plt"]["id"])
        ms_after = refresh_meter_set(ctx["meter_set"]["id"])
        app_after = refresh_application(ctx["app"]["id"])
        assert app_after["status"] == "TURN_ON", (
            "link 2: the meter set transition bubbles the spine to TURN_ON"
        )
        assert plt_after["version"] == before["plt"] + 1
        assert ms_after["version"] == before["ms"] + 1
        assert app_after["version"] == before["app"] + 1


class TestPurgeLeakSafety:
    def test_unsafe_purge_duration_rejected(self, api, technician_headers):
        """PRD §3.6: "Safety minima are hard: at least five minutes of purge, at least 10.0 psi of test pressure, and at least fifteen minutes of pressure hold — any shortfall is rejected with `ERR_TEST_PARAMS_UNSAFE` (HTTP 422)."

        Design: Corner/errors/unsafe_test_params_rejected
        """
        ctx = setup_meter_installed_app()
        resp = api.create_purge_leak_test(
            {
                "meter_set_id": ctx["meter_set"]["id"],
                "purge_duration_min": 3,
                "test_pressure_psi": 15.0,
                "test_duration_min": 60,
                "observed_pressure_drop_psi": 0.100,
            },
            technician_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TEST_PARAMS_UNSAFE, expected_status=422)

        assert refresh_meter_set(ctx["meter_set"]["id"])["status"] == "INSTALLED"
        resp = api.list_purge_leak_tests(
            technician_headers, params={"meter_set_id": ctx["meter_set"]["id"]}
        )
        _, meta = validate_paginated(resp)
        assert meta["total_count"] == 0, "an unsafe record attempt persists no row"

    def test_second_active_test_rejected(self, api, technician_headers):
        """PRD §3.6: "Only one test per meter set may sit in `RECORDED` at a time (`ERR_TEST_ALREADY_ACTIVE`, HTTP 409)."

        Design: Corner/errors/second_active_test_rejected
        """
        ctx = setup_testing_app(observed_drop=0.200)
        resp = api.create_purge_leak_test(
            {
                "meter_set_id": ctx["meter_set"]["id"],
                "purge_duration_min": 12,
                "test_pressure_psi": 15.0,
                "test_duration_min": 30,
                "observed_pressure_drop_psi": 0.100,
            },
            technician_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TEST_ALREADY_ACTIVE, expected_status=409)

        resp = api.list_purge_leak_tests(
            technician_headers, params={"meter_set_id": ctx["meter_set"]["id"]}
        )
        _, meta = validate_paginated(resp)
        assert meta["total_count"] == 1

    def test_witness_cannot_be_installer(self, api, admin_headers, technician_headers):
        """PRD §3.6: "An `Inspector` acting as witness must hold the `PRESSURE_TEST` certification (`ERR_INSPECTOR_NOT_CERTIFIED`) and must not be the technician who recorded the test — a witness identity equal to the test's `installer_user_id` is rejected with `ERR_SOD_WITNESS_IS_INSTALLER` (HTTP 422)."

        Design: Corner/errors/sod_witness_is_installer_rejected
        """
        inspector = get_success_data(
            api.create_inspector(create_inspector_payload(), admin_headers)
        )
        # The same human identity runs the meter work (opaque technician user id)
        # and then tries to witness their own test.
        ctx = setup_testing_app(observed_drop=0.200, technician_id=inspector["id"])
        assert ctx["plt"]["installer_user_id"] == inspector["id"]

        resp = api.certify_purge_leak_test(
            ctx["plt"]["id"], make_inspector_headers(inspector["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SOD_WITNESS_IS_INSTALLER, expected_status=422)

        assert refresh_purge_leak_test(ctx["plt"]["id"])["status"] == "RECORDED"
        assert refresh_meter_set(ctx["meter_set"]["id"])["status"] == "TESTING"

    def test_technician_cannot_certify(self, api, technician_headers):
        """PRD §2.1: "A request whose role is not on the target endpoint's authorized-role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: certify is listed for Inspector.

        Design: Corner/rbac/technician_cannot_certify_test
        """
        ctx = setup_testing_app(observed_drop=0.200)
        resp = api.certify_purge_leak_test(ctx["plt"]["id"], technician_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
        assert refresh_purge_leak_test(ctx["plt"]["id"])["status"] == "RECORDED"
