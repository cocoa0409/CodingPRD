"""Confirm-time validation ladder and terminal lockdown (PRD §2.11, §3.3, §3.5):
which check fires when several rules are simultaneously violated."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_assembly_order,
    create_completed_order,
    create_customer,
    create_reel,
    confirm_assembly_order,
    get_reel,
    validate_error,
    validate_success,
)


class TestTerminalLockdown:
    def test_terminal_lockdown_beats_credit_hold(self, api):
        """PRD §2.11: "Existence comes third, and then the state rungs: the assembly-order terminal lockdown (any action against a `COMPLETED` or `CANCELLED` order fails with `ERR_ORDER_TERMINAL`), general state-transition legality (`ERR_INVALID_STATE`), and the optimistic-concurrency check from §2.10 (`ERR_STALE_VERSION`)."
        PRD §2.11: "Business rules occupy the lower rungs, evaluated in this relative order: the safety rules first (pressure rating, waiver presence, crimp tolerance, and test pressure — `ERR_PRESSURE_RATING_MISMATCH`, `ERR_WAIVER_REQUIRED`, `ERR_CRIMP_OUT_OF_TOLERANCE`, `ERR_TEST_PRESSURE_TOO_LOW`); then the temporal and uniqueness rules (`ERR_INVALID_WINDOW`, `ERR_VAN_WINDOW_CONFLICT`, `ERR_INSPECTION_WINDOW_CONFLICT`, `ERR_TAG_SERIAL_TAKEN`); then the referential rules (`ERR_REEL_NOT_USABLE`, `ERR_ASSET_NOT_ACTIVE`); then the fiscal rules (`ERR_CREDIT_HOLD`, `ERR_INSUFFICIENT_REEL_LENGTH`, `ERR_INSUFFICIENT_COUPLING_STOCK`)."

        Confirming a COMPLETED order whose customer is now on credit hold violates
        both rungs; the state rung wins -> ERR_ORDER_TERMINAL (409), not
        ERR_CREDIT_HOLD.

        Design: Difficulty/priority_pair_validation_conflict/terminal_state_beats_credit_hold
        """
        cust = create_customer(name="PrioCo")
        reel = create_reel(hose_sku="PARK-387-8P", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        order = create_completed_order(
            cust["id"], reel["id"], tag_serial="TAG-PRIO1",
            cut_length_mm=1000, required_working_pressure_psi=2000,
            crimp_diameter_spec_mm=25.0, estimated_labor_minutes=10)
        assert order["status"] == "COMPLETED"

        res = api.update_customer(cust["id"], {"credit_hold": True},
                                  TEST_USERS["shop_manager_headers"])
        validate_success(res, 200)

        res = api.confirm_assembly_order(order["id"], {},
                                         TEST_USERS["counter_sales_headers"])
        validate_error(res, ApiErrorId.ERR_ORDER_TERMINAL, expected_status=409)

    def test_cancel_completed_order_returns_terminal(self, api):
        """PRD §2.11: "Existence comes third, and then the state rungs: the assembly-order terminal lockdown (any action against a `COMPLETED` or `CANCELLED` order fails with `ERR_ORDER_TERMINAL`), general state-transition legality (`ERR_INVALID_STATE`), and the optimistic-concurrency check from §2.10 (`ERR_STALE_VERSION`)."
        PRD §3.5: "In every case the order lands in `CANCELLED` and locks terminally, joining `COMPLETED` orders under the `ERR_ORDER_TERMINAL` lockdown described in §2.11."

        Cancel is an action against a COMPLETED order -> ERR_ORDER_TERMINAL (409).

        Design: Difficulty/priority_pair_validation_conflict/terminal_state_beats_credit_hold
        """
        cust = create_customer(name="PrioCo")
        reel = create_reel(hose_sku="PARK-387-8P", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        order = create_completed_order(
            cust["id"], reel["id"], tag_serial="TAG-PRIO1",
            cut_length_mm=1000, required_working_pressure_psi=2000,
            crimp_diameter_spec_mm=25.0, estimated_labor_minutes=10)

        res = api.cancel_assembly_order(order["id"],
                                        TEST_USERS["counter_sales_headers"])
        validate_error(res, ApiErrorId.ERR_ORDER_TERMINAL, expected_status=409)


class TestSafetyBeatsReferential:
    def test_pressure_mismatch_beats_retired_reel(self, api):
        """PRD §3.3: "The application-pressure check runs first, so an over-pressure request surfaces `ERR_PRESSURE_RATING_MISMATCH` rather than being masked by a later failure: the order's `required_working_pressure_psi` must not exceed the reel's rated `working_pressure_psi`."
        PRD §3.3: "Third, the reel must be usable — `AVAILABLE` or `LOW`, never `DEPLETED` or `RETIRED` — or the confirm is rejected with `ERR_REEL_NOT_USABLE`."

        The order requires 3000 psi on a reel rated 2000 psi AND the reel has been
        RETIRED; the earlier pressure check fires -> ERR_PRESSURE_RATING_MISMATCH
        (422), not ERR_REEL_NOT_USABLE.

        Design: Difficulty/priority_pair_validation_conflict/safety_pressure_beats_retired_reel
        """
        cust = create_customer(name="SafeCo")
        reel = create_reel(hose_sku="PARK-201-8", hose_diameter_in=0.5,
                           working_pressure_psi=2000, price_per_meter_cents=600,
                           initial_length_mm=50000)
        order = create_assembly_order(
            cust["id"], reel["id"], cut_length_mm=1000,
            required_working_pressure_psi=3000, crimp_diameter_spec_mm=25.0,
            estimated_labor_minutes=10)
        validate_success(
            api.retire_reel(reel["id"], TEST_USERS["shop_manager_headers"]), 200)

        res = api.confirm_assembly_order(order["id"], {},
                                         TEST_USERS["counter_sales_headers"])
        validate_error(res, ApiErrorId.ERR_PRESSURE_RATING_MISMATCH,
                       expected_status=422)

    def test_pressure_equal_to_rating_confirms(self, api):
        """PRD §3.3: "The application-pressure check runs first, so an over-pressure request surfaces `ERR_PRESSURE_RATING_MISMATCH` rather than being masked by a later failure: the order's `required_working_pressure_psi` must not exceed the reel's rated `working_pressure_psi`."

        A required pressure exactly equal to the reel's rating does not exceed it;
        the confirm succeeds.

        Design: Difficulty/priority_pair_validation_conflict/safety_pressure_beats_retired_reel
        """
        cust = create_customer(name="SafeCo")
        reel = create_reel(hose_sku="PARK-201-8", hose_diameter_in=0.5,
                           working_pressure_psi=2000, price_per_meter_cents=600,
                           initial_length_mm=50000)
        order = create_assembly_order(
            cust["id"], reel["id"], cut_length_mm=1000,
            required_working_pressure_psi=2000, crimp_diameter_spec_mm=25.0,
            estimated_labor_minutes=10)

        confirmed = confirm_assembly_order(order["id"])
        assert confirmed["status"] == "CONFIRMED"


class TestCreditHold:
    def test_credit_hold_blocks_confirm(self, api):
        """PRD §3.3: "Fourth, the customer's `credit_hold` must be false, with violations rejected as `ERR_CREDIT_HOLD` (HTTP 402)."
        PRD §3.1: "`credit_hold`, which defaults to false and, while true, blocks both order confirmation and dispatch booking"

        A credit-hold customer's confirm is rejected even though every safety and
        referential check passes; the order stays DRAFT and the reel is untouched.

        Design: Corner/validations/credit_hold_blocks_confirm
        """
        cust = create_customer(name="HoldCo", credit_hold=True)
        reel = create_reel(hose_sku="PARK-387-8H", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        order = create_assembly_order(
            cust["id"], reel["id"], cut_length_mm=1000,
            required_working_pressure_psi=2000, crimp_diameter_spec_mm=25.0,
            estimated_labor_minutes=10)

        res = api.confirm_assembly_order(order["id"], {},
                                         TEST_USERS["counter_sales_headers"])
        validate_error(res, ApiErrorId.ERR_CREDIT_HOLD, expected_status=402)

        after = validate_success(
            api.get_assembly_order(order["id"],
                                   TEST_USERS["counter_sales_headers"]), 200)
        assert after["status"] == "DRAFT"
        assert get_reel(reel["id"])["remaining_length_mm"] == 50000


class TestWaiverRequirement:
    def test_waiver_required_then_satisfied(self, api):
        """PRD §3.3: "Second comes the waiver rule: when the order was drafted with `application_error_suspected` set, the confirmation payload must supply both `waiver_signed_by` and `waiver_liability_cents`, and the request fails with `ERR_WAIVER_REQUIRED` if either is missing."
        PRD §3.3: "And whenever the confirmation payload carries the waiver fields, `waiver_signed` flips to true with both `waiver_signed_by` and `waiver_liability_cents` stored on the order."

        First confirm without waiver fields -> ERR_WAIVER_REQUIRED (422); second
        confirm with both fields succeeds and stores them.

        Design: Corner/validations/waiver_required_then_satisfied
        """
        cust = create_customer(name="WaiveCo")
        reel = create_reel(hose_sku="PARK-387-8W", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        order = create_assembly_order(
            cust["id"], reel["id"], cut_length_mm=1000,
            required_working_pressure_psi=2000, crimp_diameter_spec_mm=25.0,
            estimated_labor_minutes=10, application_error_suspected=True)

        res = api.confirm_assembly_order(order["id"], {},
                                         TEST_USERS["counter_sales_headers"])
        validate_error(res, ApiErrorId.ERR_WAIVER_REQUIRED, expected_status=422)

        res = api.confirm_assembly_order(
            order["id"],
            {"waiver_signed_by": "Pat Customer", "waiver_liability_cents": 50000},
            TEST_USERS["counter_sales_headers"])
        confirmed = validate_success(res, 200)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["waiver_signed"] is True
        assert confirmed["waiver_signed_by"] == "Pat Customer"
        assert confirmed["waiver_liability_cents"] == 50000
