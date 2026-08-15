"""Assembly order state machine and bench rules (PRD §3.3, §3.4): the rework
cycle, invalid transitions, the pressure-test floor, and tag uniqueness."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    build_assembly_order,
    create_assembly_order,
    create_customer,
    create_reel,
    confirm_assembly_order,
    get_reel,
    record_pressure_test,
    rework_assembly_order,
    tag_assembly_order,
    validate_error,
    validate_success,
)


def _draft_order(cust_id, reel_id, **overrides):
    base = dict(cut_length_mm=1000, required_working_pressure_psi=2000,
                crimp_diameter_spec_mm=25.0, estimated_labor_minutes=10)
    base.update(overrides)
    return create_assembly_order(cust_id, reel_id, **base)


class TestReworkCycle:
    def _setup(self):
        cust = create_customer(name="CycleTest")
        reel = create_reel(hose_sku="PARK-387-8C", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        order = create_assembly_order(cust["id"], reel["id"], cut_length_mm=2000,
                                      required_working_pressure_psi=2000,
                                      crimp_diameter_spec_mm=25.0,
                                      estimated_labor_minutes=10)
        confirm_assembly_order(order["id"])
        return cust, reel, order

    def test_rework_loop_returns_to_built_with_new_measurements(self, api):
        """PRD §3.4: "Sending the assembly to rework moves a `TEST_FAILED` order to `REWORK`, ready for another build attempt."
        PRD §3.4: "The same operation serves the rework loop: an order in `REWORK` returns to `BUILT` through the identical check, overwriting the previously recorded diameter and labor with the new measurements."

        BUILT -> TEST_FAILED -> REWORK -> BUILT; the second complete-build
        overwrites measured crimp 25.1 -> 25.0 and actual labor 10 -> 12.

        Design: Difficulty/non_linear_state_machine/assembly_order_rework_cycle
        """
        cust, reel, order = self._setup()
        built = build_assembly_order(order["id"], measured_crimp_diameter_mm=25.1,
                                     actual_labor_minutes=10)
        assert built["status"] == "BUILT"
        failed = record_pressure_test(order["id"], test_pressure_psi=4000,
                                      result="FAILED")
        assert failed["status"] == "TEST_FAILED"

        reworked = rework_assembly_order(order["id"])
        assert reworked["status"] == "REWORK"

        rebuilt = build_assembly_order(order["id"], measured_crimp_diameter_mm=25.0,
                                       actual_labor_minutes=12)
        assert rebuilt["status"] == "BUILT"
        assert rebuilt["measured_crimp_diameter_mm"] == pytest.approx(25.0)
        assert rebuilt["actual_labor_minutes"] == 12

    def test_rework_does_not_redebit_reel(self, api):
        """PRD §3.4: "Because the hose has already been cut and crimped, rework touches no inventory: reel lengths are not adjusted and coupling reservations stay exactly where they are."

        The 2000mm cut is committed at confirm (50000 -> 48000); the full
        TEST_FAILED -> REWORK -> BUILT loop leaves remaining_length_mm at 48000.

        Design: Difficulty/non_linear_state_machine/assembly_order_rework_cycle
        """
        cust, reel, order = self._setup()
        assert get_reel(reel["id"])["remaining_length_mm"] == 48000

        build_assembly_order(order["id"], measured_crimp_diameter_mm=25.1,
                             actual_labor_minutes=10)
        record_pressure_test(order["id"], test_pressure_psi=4000, result="FAILED")
        rework_assembly_order(order["id"])
        build_assembly_order(order["id"], measured_crimp_diameter_mm=25.0,
                             actual_labor_minutes=12)

        reel_after = get_reel(reel["id"])
        assert reel_after["remaining_length_mm"] == 48000, (
            "rework must not re-debit the committed cut")
        assert reel_after["scrap_length_mm"] == 0


class TestInvalidBenchTransitions:
    def test_record_pressure_test_from_draft_rejected(self, api):
        """PRD §3.4: "From `BUILT`, the technician records a test by supplying `test_pressure_psi` and a `result` of `PASSED` or `FAILED`."
        PRD §2.11: "Existence comes third, and then the state rungs: the assembly-order terminal lockdown (any action against a `COMPLETED` or `CANCELLED` order fails with `ERR_ORDER_TERMINAL`), general state-transition legality (`ERR_INVALID_STATE`), and the optimistic-concurrency check from §2.10 (`ERR_STALE_VERSION`)."

        record-pressure-test is only legal from BUILT; from DRAFT it fails with
        ERR_INVALID_STATE and stores nothing.

        Design: Corner/state_machines/record_pressure_test_from_draft_rejected
        """
        cust = create_customer(name="StateCo")
        reel = create_reel(hose_sku="PARK-387-8T", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        order = _draft_order(cust["id"], reel["id"])

        res = api.record_pressure_test(
            order["id"], {"test_pressure_psi": 4000, "result": "PASSED"},
            TEST_USERS["shop_technician_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        after = validate_success(
            api.get_assembly_order(order["id"],
                                   TEST_USERS["counter_sales_headers"]), 200)
        assert after["status"] == "DRAFT"
        assert after.get("test_result") is None
        assert after.get("test_pressure_psi") is None

    def test_rework_from_built_rejected(self, api):
        """PRD §3.4: "Sending the assembly to rework moves a `TEST_FAILED` order to `REWORK`, ready for another build attempt."
        PRD §2.11: "Existence comes third, and then the state rungs: the assembly-order terminal lockdown (any action against a `COMPLETED` or `CANCELLED` order fails with `ERR_ORDER_TERMINAL`), general state-transition legality (`ERR_INVALID_STATE`), and the optimistic-concurrency check from §2.10 (`ERR_STALE_VERSION`)."

        rework is only legal from TEST_FAILED; from BUILT it fails with ERR_INVALID_STATE.

        Design: Corner/state_machines/rework_from_built_rejected
        """
        cust = create_customer(name="ReworkCo")
        reel = create_reel(hose_sku="PARK-387-8RW", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        order = _draft_order(cust["id"], reel["id"])
        confirm_assembly_order(order["id"])
        build_assembly_order(order["id"], measured_crimp_diameter_mm=25.0,
                             actual_labor_minutes=10)

        res = api.rework_assembly_order(order["id"],
                                        TEST_USERS["shop_technician_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        after = validate_success(
            api.get_assembly_order(order["id"],
                                   TEST_USERS["counter_sales_headers"]), 200)
        assert after["status"] == "BUILT"

    def test_tag_from_built_rejected(self, api):
        """PRD §3.4: "Attaching the certification tag moves a `TEST_PASSED` order to `TAGGED`, storing the supplied `tag_serial` on the order."
        PRD §2.11: "Existence comes third, and then the state rungs: the assembly-order terminal lockdown (any action against a `COMPLETED` or `CANCELLED` order fails with `ERR_ORDER_TERMINAL`), general state-transition legality (`ERR_INVALID_STATE`), and the optimistic-concurrency check from §2.10 (`ERR_STALE_VERSION`)."

        tag requires TEST_PASSED; tagging a merely BUILT order fails with
        ERR_INVALID_STATE and stores no tag_serial.

        Design: Corner/state_machines/tag_from_built_rejected
        """
        cust = create_customer(name="TagCo")
        reel = create_reel(hose_sku="PARK-387-8TG", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        order = _draft_order(cust["id"], reel["id"])
        confirm_assembly_order(order["id"])
        build_assembly_order(order["id"], measured_crimp_diameter_mm=25.0,
                             actual_labor_minutes=10)

        res = api.tag_assembly_order(order["id"], {"tag_serial": "TAG-EARLY"},
                                     TEST_USERS["shop_technician_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        after = validate_success(
            api.get_assembly_order(order["id"],
                                   TEST_USERS["counter_sales_headers"]), 200)
        assert after["status"] == "BUILT"
        assert after.get("tag_serial") is None


class TestPressureTestFloor:
    def test_pressure_exactly_double_required_is_accepted(self, api):
        """PRD §2.8: "Every recorded pressure test must apply a pressure of at least twice the order's required working pressure; a test run below that multiple proves nothing and is refused outright, whether the result being recorded is a pass or a fail."
        PRD §3.4: "A recorded pass moves the order to `TEST_PASSED`; a recorded failure moves it to `TEST_FAILED`. Both values persist on the order as `test_pressure_psi` and `test_result`."

        4000 psi == 2.0 x 2000 psi meets the >= boundary; the pass is recorded and
        the order moves to TEST_PASSED.

        Design: Corner/calculations/test_pressure_exactly_double_passes
        """
        cust = create_customer(name="PressCo")
        reel = create_reel(hose_sku="PARK-387-8PR", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        order = _draft_order(cust["id"], reel["id"])
        confirm_assembly_order(order["id"])
        build_assembly_order(order["id"], measured_crimp_diameter_mm=25.0,
                             actual_labor_minutes=10)

        res = api.record_pressure_test(
            order["id"], {"test_pressure_psi": 4000, "result": "PASSED"},
            TEST_USERS["shop_technician_headers"])
        tested = validate_success(res, 200)
        assert tested["status"] == "TEST_PASSED"
        assert tested["test_pressure_psi"] == 4000
        assert tested["test_result"] == "PASSED"


class TestTagSerialUniqueness:
    def test_duplicate_tag_serial_rejected(self, api):
        """PRD §3.4: "The serial must be unique across every order that is not `CANCELLED`; a serial already present on another live order is rejected with `ERR_TAG_SERIAL_TAKEN`."

        O1 holds tag DUP-1; tagging O2 with the same serial fails and O2 keeps
        its TEST_PASSED status with no tag stored.

        Design: Corner/validations/duplicate_tag_serial_rejected
        """
        cust = create_customer(name="DupCo")
        reel = create_reel(hose_sku="PARK-387-8D", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)

        o1 = _draft_order(cust["id"], reel["id"])
        confirm_assembly_order(o1["id"])
        build_assembly_order(o1["id"], measured_crimp_diameter_mm=25.0,
                             actual_labor_minutes=10)
        record_pressure_test(o1["id"], test_pressure_psi=4000, result="PASSED")
        tag_assembly_order(o1["id"], "DUP-1")

        o2 = _draft_order(cust["id"], reel["id"])
        confirm_assembly_order(o2["id"])
        build_assembly_order(o2["id"], measured_crimp_diameter_mm=25.0,
                             actual_labor_minutes=10)
        record_pressure_test(o2["id"], test_pressure_psi=4000, result="PASSED")

        res = api.tag_assembly_order(o2["id"], {"tag_serial": "DUP-1"},
                                     TEST_USERS["shop_technician_headers"])
        validate_error(res, ApiErrorId.ERR_TAG_SERIAL_TAKEN, expected_status=409)

        after = validate_success(
            api.get_assembly_order(o2["id"], TEST_USERS["counter_sales_headers"]),
            200)
        assert after["status"] == "TEST_PASSED"
        assert after.get("tag_serial") is None


class TestOrderCreationValidation:
    def test_order_create_missing_cut_length_rejected(self, api):
        """PRD §2.11: "Dead last comes malformed-request validation — a missing required field, an invalid enum value, or an out-of-range numeric input — surfaced as `ERR_INVALID_REQUEST` (HTTP 400) only after every applicable business rule has passed."
        PRD §3.3: "The build specification carries the `cut_length_mm` requested (at least one millimeter), the application's `required_working_pressure_psi`, and the die-chart `crimp_diameter_spec_mm`, plus two overridable defaults: `crimp_tolerance_mm` at 0.2 millimeters and `crimp_count` at two crimped ends."

        POST /api/assembly-orders without required cut_length_mm -> ERR_INVALID_REQUEST.

        Design: Corner/entities/order_create_missing_required_field_returns_invalid_request
        """
        cust = create_customer(name="ReqCo")
        reel = create_reel(hose_sku="PARK-387-8", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)

        res = api.create_assembly_order({
            "customer_id": cust["id"],
            "reel_id": reel["id"],
            "required_working_pressure_psi": 2000,
            "crimp_diameter_spec_mm": 25.0,
            "estimated_labor_minutes": 10,
        }, TEST_USERS["counter_sales_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_order_create_with_unknown_coupling_rejected(self, api):
        """PRD §2.11: "Foreign keys supplied in a request body — a `customer_id`, `reel_id`, `equipment_asset_id`, a line-level `coupling_id`, or an `installed_assembly_order_id` — receive the same treatment once the path identifiers have resolved."
        PRD §2.11: "For a nested path, identifiers are validated left to right, and the first identifier that does not resolve produces the 404 specific to its resource kind: `ERR_CUSTOMER_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_REEL_NOT_FOUND`, `ERR_COUPLING_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, or `ERR_DISPATCH_NOT_FOUND`."

        A line referencing a non-existent coupling id -> ERR_COUPLING_NOT_FOUND (404)
        at order creation.

        Design: Corner/errors/order_create_with_unknown_coupling_returns_not_found
        """
        cust = create_customer(name="BadRefCo")
        reel = create_reel(hose_sku="PARK-387-8B", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)

        res = api.create_assembly_order({
            "customer_id": cust["id"],
            "reel_id": reel["id"],
            "cut_length_mm": 1000,
            "required_working_pressure_psi": 2000,
            "crimp_diameter_spec_mm": 25.0,
            "estimated_labor_minutes": 10,
            "lines": [{"coupling_id": NON_EXISTENT_UUID, "quantity": 1}],
        }, TEST_USERS["counter_sales_headers"])
        validate_error(res, ApiErrorId.ERR_COUPLING_NOT_FOUND,
                       expected_status=404)

    def test_order_get_unknown_id_not_found(self, api):
        """PRD §2.11: "For a nested path, identifiers are validated left to right, and the first identifier that does not resolve produces the 404 specific to its resource kind: `ERR_CUSTOMER_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_REEL_NOT_FOUND`, `ERR_COUPLING_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, or `ERR_DISPATCH_NOT_FOUND`."

        GET /api/assembly-orders/{unknown uuid} -> ERR_ORDER_NOT_FOUND (404).

        Design: Corner/errors/order_get_unknown_id_not_found
        """
        res = api.get_assembly_order(NON_EXISTENT_UUID,
                                     TEST_USERS["counter_sales_headers"])
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_FOUND, expected_status=404)
