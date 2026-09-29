"""Corner behaviour of three state machines: the receipt's absorbing exits, the tank's two
independent dimensions, and the fuelling order's unreachable edges."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, fixtures as fx,
)

PIPELINE_PARCEL = dict(delivery_mode="PIPELINE", supplier_name="Refinery One",
                       meter_ticket_gross_liters=29800.0, tank_opening_gauge_liters=0.0,
                       tank_closing_gauge_liters=29700.0, temperature_c=15.0,
                       certificate_density_kg_per_m3=795.0, measured_water_liters=0.0)
PASSING_METRICS = {"particulate_mg_per_l": 0.4, "conductivity_ps_per_m": 150.0,
                   "flash_point_c": 41.0}


class TestFuelReceiptMachineCorners:
    def test_a_released_receipt_is_closed_to_every_further_request(self, api):
        """PRD §2.10: "The two optimistic-concurrency checks come next — `ERR_STALE_ORDER_VERSION` on
        uplift posting and `ERR_STALE_ACCOUNT_VERSION` on invoice creation — followed by the
        terminal-state guard (`ERR_ALREADY_TERMINAL`), which applies to every state-transition endpoint
        and fires when the target row already sits in a terminal state for its machine: a fuel receipt
        in `RELEASED` or `REJECTED`, a fuelling order in `COMPLETED`, `CANCELLED` or `ABORTED`, a fuel
        authorization in `REDEEMED`, `VOIDED` or `EXPIRED`, a spill incident in `CLOSED`, an invoice in
        `PAID` or `VOIDED`, or a reconciliation run in `POSTED`."
        PRD §3.2: "A `FarmOperator` records an inbound parcel the moment it lands, and the arithmetic
        performed at that instant is frozen forever: the volumes computed on creation are never
        recomputed, and they are exactly what a later release verdict adds to the tank ledger."

        Design: Corner/state_machines/terminal_released_rejects_every_further_action
        """
        env = fx.setup_fuel_farm(permit_overrides={"max_daily_throughput_liters": 400000.0})
        fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        tank = fx.make_released_tank(env["farm"]["id"], capacity_liters=5_000_000.0,
                                     safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                     opening_volume_liters=0.0)
        receipt = fx.make_released_receipt(tank["id"], metrics=dict(PASSING_METRICS),
                                           **PIPELINE_PARCEL)
        assert receipt["status"] == "RELEASED"
        assert fx.read_tank(tank["id"])["book_volume_liters"] == pytest.approx(29700.00,
                                                                              abs=0.005)

        validate_error(api.sign_receipt_verdict(receipt["id"], {"decision": "RELEASE"},
                                                fx.INSPECTOR_B),
                       ApiErrorId.ERR_ALREADY_TERMINAL, 409)
        validate_error(api.reject_fuel_receipt(receipt["id"], fx.OPERATOR,
                                               {"reason": "second thoughts"}),
                       ApiErrorId.ERR_ALREADY_TERMINAL, 409)
        validate_error(api.create_receipt_sample(receipt["id"], fx.INSPECTOR_A),
                       ApiErrorId.ERR_ALREADY_TERMINAL, 409)

        assert fx.read_tank(tank["id"])["book_volume_liters"] == pytest.approx(29700.00,
                                                                              abs=0.005), \
            "the parcel is credited exactly once"

    def test_a_verdict_cannot_jump_over_the_laboratory(self, api):
        """PRD §3.3: "The `UNDER_TEST → RELEASED` branch is the only path by which product enters the
        ledger, and it carries the heaviest set of preconditions."
        PRD §2.10: "Only then are the per-machine from-state guards evaluated:
        `ERR_INVALID_RECEIPT_STATE` on receipt sampling, verdict and rejection;
        `ERR_INVALID_ORDER_STATE` on order authorize, assign, unassign, start, uplift posting,
        complete, abort and cancel; `ERR_INVALID_TANK_STATE` on tank service-status changes, quality
        release, quarantine and tank sampling; `ERR_INVALID_ASSET_STATE` on asset status changes and
        filter changes; `ERR_INVALID_SPILL_STATE` on spill escalate, contain, remediate and close;
        `ERR_INVALID_INVOICE_STATE` on invoice issue, dispute, dispute resolution, void and payment;
        and `ERR_INVALID_RUN_STATE` on reconciliation measure and post."

        Design: Corner/state_machines/verdict_from_recorded_skips_the_test_phase
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=0.0)
        fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        receipt = fx.record_receipt(env["tank"]["id"], **PIPELINE_PARCEL)
        assert receipt["status"] == "RECORDED"

        validate_error(api.sign_receipt_verdict(receipt["id"], {"decision": "RELEASE"},
                                                fx.INSPECTOR_B),
                       ApiErrorId.ERR_INVALID_RECEIPT_STATE, 409)

        assert validate_success(
            api.get_fuel_receipt(receipt["id"], fx.OPERATOR))["status"] == "RECORDED"
        assert fx.read_tank(env["tank"]["id"])["book_volume_liters"] == \
            pytest.approx(0.00, abs=0.005), "no volume enters without a passing test"


class TestStorageTankMachineCorners:
    def test_the_quality_cycle_completes_while_the_tank_stays_isolated(self, api):
        """PRD §3.4: "A storage tank carries two status dimensions that evolve on the same row without
        constraining each other's shape. The mechanical dimension, `service_status`, moves among
        `IN_SERVICE`, `ISOLATED` and `OUT_OF_SERVICE`. The product dimension, `quality_status`, moves
        among `ON_TEST`, `RELEASED` and `QUARANTINED`. A tank may perfectly well be `RELEASED` on
        quality while `ISOLATED` on service, and the two dimensions must be tracked and reported
        separately."
        PRD §3.4: "Recovery runs the other way: drawing a fresh periodic tank QA sample moves
        `QUARANTINED → ON_TEST`, which is permitted only when no receipt targeting the tank is still
        `QUARANTINED`."

        Design: Corner/state_machines/two_orthogonal_dimensions_advance_independently
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=1_000_000.0)
        fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        tank_id = env["tank"]["id"]

        quarantined = validate_success(api.quarantine_tank(
            tank_id, fx.INSPECTOR_A, {"reason": "suspect membrane"}))
        assert quarantined["quality_status"] == "QUARANTINED"

        isolated = fx.isolate_tank(tank_id, "2026-08-10T06:00:00Z", "2026-08-10T10:00:00Z")
        assert isolated["service_status"] == "ISOLATED"
        assert isolated["quality_status"] == "QUARANTINED"

        sample = fx.draw_tank_sample(tank_id, fx.INSPECTOR_A)
        on_test = fx.read_tank(tank_id)
        assert on_test["quality_status"] == "ON_TEST"
        assert on_test["service_status"] == "ISOLATED"

        fx.post_results(sample["id"], fx.INSPECTOR_A, observed_density_kg_per_m3=795.0)
        released = fx.release_tank_quality(tank_id, fx.INSPECTOR_B)

        assert released["quality_status"] == "RELEASED"
        assert released["service_status"] == "ISOLATED", \
            "two quality hops later the mechanical dimension has not moved"

    def test_a_second_quality_release_has_no_source_state_to_leave(self, api):
        """PRD §3.4: "On the quality dimension, a fresh tank starts `ON_TEST` and cannot yet source an
        order. Signing a tank's quality release, `ON_TEST → RELEASED`, is a `QualityInspector` action
        requiring three things: a periodic tank QA sample exists for this tank whose `sample_purpose`
        is `PERIODIC_TANK_QA`, whose `status` is `TESTED`, whose `verdict` is `PASS`, and whose
        `created_at` is the latest of any sample for this tank; the acting identifier differs from that
        sample's `drawn_by_user_id`, since an inspector may not release a tank on the strength of a
        sample they drew themselves; and the tank's `water_bottom_mm` is strictly below 25.0."
        PRD §2.10: "`ERR_INVALID_TANK_STATE` on tank service-status changes, quality release,
        quarantine and tank sampling"

        Design: Corner/state_machines/quality_release_from_released_is_a_no_op_error
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=1_000_000.0)
        tank_id = env["tank"]["id"]
        assert fx.read_tank(tank_id)["quality_status"] == "RELEASED"
        version_before = fx.read_tank(tank_id)["version"]

        validate_error(api.release_tank_quality(tank_id, fx.INSPECTOR_C),
                       ApiErrorId.ERR_INVALID_TANK_STATE, 409)

        after = fx.read_tank(tank_id)
        assert after["quality_status"] == "RELEASED"
        assert after["version"] == version_before, "a refused hop writes nothing"


class TestFuelingOrderMachineCorners:
    def test_the_three_terminal_doors_shut_on_each_other(self, api):
        """PRD §3.6: "All three of `COMPLETED`, `CANCELLED` and `ABORTED` are terminal."
        PRD §2.10: "the terminal-state guard (`ERR_ALREADY_TERMINAL`), which applies to every
        state-transition endpoint and fires when the target row already sits in a terminal state for
        its machine: a fuel receipt in `RELEASED` or `REJECTED`, a fuelling order in `COMPLETED`,
        `CANCELLED` or `ABORTED`, a fuel authorization in `REDEEMED`, `VOIDED` or `EXPIRED`, a spill
        incident in `CLOSED`, an invoice in `PAID` or `VOIDED`, or a reconciliation run in `POSTED`."
        PRD §3.6: "From `REQUESTED → CANCELLED` only the authorization is voided with reason
        `ORDER_CANCELLED`, and the order's and authorization's versions rise."

        Design: Corner/state_machines/three_terminal_states_are_mutually_exclusive
        """
        env = fx.setup_truck_order(target_state="FUELING", requested_uplift_liters=20_000.0,
                                   max_authorized_liters=20_000.0,
                                   account_overrides={"base_price_cents_per_liter": 62.00,
                                                      "credit_limit_cents": 100_000_000})
        aborted = fx.abort_order(env["order"]["id"], abort_reason="EQUIPMENT_FAILURE")
        assert aborted["status"] == "ABORTED"

        validate_error(api.cancel_order(env["order"]["id"], fx.AGENT),
                       ApiErrorId.ERR_ALREADY_TERMINAL, 409)

        second_flight = fx.register_flight(env["account"]["id"], stand_code="B02",
                                           scheduled_departure_utc="2026-08-10T09:00:00Z")
        second_auth = fx.issue_authorization(env["account"]["id"], second_flight["id"],
                                             max_authorized_liters=10_000.0)
        second = fx.create_order(second_flight["id"], second_auth["id"], env["tank"]["id"],
                                 second_auth["authorization_code"], delivery_mode="TRUCK",
                                 requested_uplift_liters=10_000.0)
        cancelled = validate_success(api.cancel_order(second["id"], fx.AGENT))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["abort_reason"] is None

        validate_error(api.abort_order(second["id"], {"abort_reason": "SPILL"}, fx.AGENT),
                       ApiErrorId.ERR_ALREADY_TERMINAL, 409)
        assert fx.read_order(second["id"])["abort_reason"] is None

    def test_fuelling_cannot_start_before_an_asset_has_been_named(self, api):
        """PRD §3.6: "Starting fuelling, `ASSIGNED → FUELING`, is gated on time and fitness."
        PRD §3.6: "Assignment stores the `fueling_asset_id` and, for hydrant work, the
        `hydrant_pit_id`, and records the order's pit occupancy for its window — note that the pit's
        own `status` is *not* changed to `LOCKED_OUT` by an assignment, because lockout means
        administrative unavailability, not momentary use."
        PRD §2.10: "`ERR_INVALID_ORDER_STATE` on order authorize, assign, unassign, start, uplift
        posting, complete, abort and cancel"

        Design: Corner/state_machines/start_from_authorized_without_an_assignment
        """
        env = fx.setup_truck_order(target_state="AUTHORIZED", requested_uplift_liters=20_000.0,
                                   max_authorized_liters=20_000.0,
                                   account_overrides={"base_price_cents_per_liter": 62.00,
                                                      "credit_limit_cents": 100_000_000})
        order_id = env["order"]["id"]
        assert fx.read_order(order_id)["fueling_asset_id"] is None

        validate_error(api.start_order(order_id, fx.AGENT),
                       ApiErrorId.ERR_INVALID_ORDER_STATE, 409)

        order = fx.read_order(order_id)
        assert order["status"] == "AUTHORIZED"
        assert order["fueling_asset_id"] is None
        tickets, _meta = validate_paginated(api.list_uplift_records(
            fx.AGENT, {"fueling_order_id": order_id}))
        assert tickets == []

    def test_the_asset_cannot_be_detached_once_fuel_is_moving(self, api):
        """PRD §3.6: "Assignment is reversible. Unassigning, `ASSIGNED → AUTHORIZED`, clears both the
        `fueling_asset_id` and the `hydrant_pit_id` to null, raises `unassign_count` by one, and ends
        the order's pit occupancy for its window — but it deliberately leaves the tank's
        `reserved_volume_liters` untouched, because the volume reservation belongs to the authorised
        state, not to the assignment."
        PRD §3.7: "The `onboard_volume_liters` of an asset is the sum of `net_liters` over the uplift
        tickets whose `status` is `POSTED`, whose parent order is currently `FUELING`, whose parent
        order's `delivery_mode` is `TRUCK`, and whose parent order names this asset."

        Design: Corner/state_machines/unassign_from_fueling_is_refused
        """
        env = fx.setup_fueling_order_with_uplift(
            meter_end_liters=20_000.0, temperature_c=15.0,
            requested_uplift_liters=20_000.0, max_authorized_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000},
            permit_overrides={"max_daily_throughput_liters": 400000.0})
        order_id, truck_id = env["order"]["id"], env["truck"]["id"]

        validate_error(api.unassign_order(order_id, fx.AGENT),
                       ApiErrorId.ERR_INVALID_ORDER_STATE, 409)

        order = fx.read_order(order_id)
        assert order["status"] == "FUELING"
        assert order["fueling_asset_id"] == truck_id
        assert order["unassign_count"] == 0
        assert fx.read_asset(truck_id)["onboard_volume_liters"] == \
            pytest.approx(20000.00, abs=0.005), "the on-board figure can never be orphaned"
