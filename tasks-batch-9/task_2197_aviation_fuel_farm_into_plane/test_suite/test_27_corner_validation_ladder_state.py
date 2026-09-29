"""Corner behaviour of the middle of the validation ladder: optimistic concurrency, the shared terminal
guard, the seven per-machine state errors, and segregation of duties."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    fixtures as fx, factories as F,
)

BIG_CREDIT = 100_000_000_000


def _ticket(version, start, end):
    return F.create_uplift_record_payload(version, meter_start_liters=start,
                                          meter_end_liters=end, temperature_c=15.0)


class TestOptimisticConcurrencyCorners:
    def test_an_unassign_and_reassign_stales_a_version_captured_before_them(self, api):
        """PRD §2.9: "Posting an uplift ticket onto a fuelling order requires the non-optional field
        `expected_fueling_order_version`, carrying the client's last observed `version` of that order."
        PRD §2.9: "If `expected_fueling_order_version` does not equal the order's current `version`, the
        post is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), which is what prevents a ticket from
        being written against an out-of-date view of the order's posted volume and the tank reservation
        behind it."
        PRD §3.6: "Unassigning, `ASSIGNED → AUTHORIZED`, clears both the `fueling_asset_id` and the
        `hydrant_pit_id` to null, raises `unassign_count` by one, and ends the order's pit occupancy for its
        window — but it deliberately leaves the tank's `reserved_volume_liters` untouched, because the
        volume reservation belongs to the authorised state, not to the assignment."

        Design: Corner/validations/version_from_before_an_unrelated_mutation_is_stale
        """
        env = fx.setup_truck_order(target_state="ASSIGNED", requested_uplift_liters=20_000.0,
                                   max_authorized_liters=20_000.0,
                                   account_overrides={"credit_limit_cents": BIG_CREDIT})
        order_id = env["order"]["id"]
        captured = fx.current_order_version(order_id)

        validate_success(api.unassign_order(order_id, fx.AGENT))
        fx.assign_order(order_id, env["truck"]["id"])
        fx.start_order(order_id)

        validate_error(api.create_uplift_record(order_id, _ticket(captured, 0.0, 10_000.0),
                                                fx.AGENT),
                       ApiErrorId.ERR_STALE_ORDER_VERSION, 412)
        assert fx.current_order_version(order_id) > captured, \
            "an unassign moves no fuel at all and still invalidates the client's view"

    def test_the_concurrency_check_speaks_before_the_window_and_the_asset_do(self, api):
        """PRD §2.10: "**Concurrency and state.** The two optimistic-concurrency checks come next —
        `ERR_STALE_ORDER_VERSION` on uplift posting and `ERR_STALE_ACCOUNT_VERSION` on invoice creation —
        followed by the terminal-state guard (`ERR_ALREADY_TERMINAL`), which applies to every
        state-transition endpoint and fires when the target row already sits in a terminal state for its
        machine: a fuel receipt in `RELEASED` or `REJECTED`, a fuelling order in `COMPLETED`, `CANCELLED`
        or `ABORTED`, a fuel authorization in `REDEEMED`, `VOIDED` or `EXPIRED`, a spill incident in
        `CLOSED`, an invoice in `PAID` or `VOIDED`, or a reconciliation run in `POSTED`."
        PRD §3.6: "Posting is gated on the fuelling window, on the source tank still being `RELEASED`, on
        the asset still being serviceable, on the farm not being `FROZEN` and having an active permit, on
        the tank's `book_volume_liters` less the farm's `unpumpable_bottom_liters` being at least the
        ticket's `net_liters` (`ERR_INSUFFICIENT_TANK_VOLUME`), on the farm's permit-day throughput
        including this volume staying within `max_daily_throughput_liters`
        (`ERR_PERMIT_THROUGHPUT_EXCEEDED`), and on the order's `posted_net_liters` after this ticket not
        exceeding **105 percent** of the authorization's `max_authorized_liters` — a deliberate five
        percent posting tolerance, breach of which is `ERR_UPLIFT_EXCEEDS_AUTHORIZATION`."
        PRD §2.10: "The practical reading is that structural problems always beat business problems,
        business-state problems beat safety problems, and safety problems beat money problems."

        Design: Corner/validations/occ_check_precedes_every_business_guard
        """
        env = fx.setup_truck_order(target_state="FUELING", requested_uplift_liters=20_000.0,
                                   max_authorized_liters=20_000.0,
                                   account_overrides={"credit_limit_cents": BIG_CREDIT})
        order_id = env["order"]["id"]
        stale = fx.current_order_version(order_id)
        fx.post_uplift(order_id, meter_start_liters=0.0, meter_end_liters=5_000.0,
                       temperature_c=15.0)

        fx.set_clock("2026-08-10T09:00:00Z")
        validate_success(api.change_asset_status(env["truck"]["id"],
                                                {"to_status": "DOWN_MAINTENANCE"}, fx.OPERATOR))

        validate_error(api.create_uplift_record(order_id, _ticket(stale, 5_000.0, 6_000.0),
                                                fx.AGENT),
                       ApiErrorId.ERR_STALE_ORDER_VERSION, 412)
        assert fx.read_order(order_id)["posted_net_liters"] == pytest.approx(5000.00,
                                                                            abs=0.005), \
            "a closed window and an unserviceable truck are both diagnosed later than a stale read"

    def test_a_re_read_is_all_the_client_needs_to_retry(self, api):
        """PRD §2.9: "If `expected_fueling_order_version` does not equal the order's current `version`, the
        post is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), which is what prevents a ticket from
        being written against an out-of-date view of the order's posted volume and the tank reservation
        behind it."
        PRD §2.9: "A second ticket on the same order is legitimate product behaviour — a top-up after a
        first partial ticket, each with its own `ticket_number` — so the request cannot be refused on state
        grounds."
        PRD §3.6: "Posting debits the tank's book volume, raises the asset's
        `liters_since_filter_change` and recomputes its `element_life_pct`, recomputes the farm's
        permit-day throughput and posture, recomputes the account's accrual exposure, and raises the
        order's `version` by one."

        Design: Corner/validations/correct_version_is_accepted_after_a_re_read
        """
        env = fx.setup_truck_order(target_state="FUELING", requested_uplift_liters=20_000.0,
                                   max_authorized_liters=20_000.0,
                                   account_overrides={"credit_limit_cents": BIG_CREDIT})
        order_id = env["order"]["id"]
        stale = fx.current_order_version(order_id)
        fx.post_uplift(order_id, meter_start_liters=0.0, meter_end_liters=5_000.0,
                       temperature_c=15.0)

        validate_error(api.create_uplift_record(order_id, _ticket(stale, 5_000.0, 6_000.0),
                                                fx.AGENT),
                       ApiErrorId.ERR_STALE_ORDER_VERSION, 412)

        fresh = fx.current_order_version(order_id)
        second = validate_success(api.create_uplift_record(
            order_id, _ticket(fresh, 5_000.0, 6_000.0), fx.AGENT), 201)

        assert second["status"] == "POSTED", "there is no retry counter and no lockout"
        assert fx.current_order_version(order_id) == fresh + 1, \
            "the accepted post moves the version on by exactly one"


class TestTerminalGuardCorners:
    def test_a_cancelled_order_reports_terminality_rather_than_its_from_state(self, api):
        """PRD §2.10: "The two optimistic-concurrency checks come next — `ERR_STALE_ORDER_VERSION` on
        uplift posting and `ERR_STALE_ACCOUNT_VERSION` on invoice creation — followed by the terminal-state
        guard (`ERR_ALREADY_TERMINAL`), which applies to every state-transition endpoint and fires when the
        target row already sits in a terminal state for its machine: a fuel receipt in `RELEASED` or
        `REJECTED`, a fuelling order in `COMPLETED`, `CANCELLED` or `ABORTED`, a fuel authorization in
        `REDEEMED`, `VOIDED` or `EXPIRED`, a spill incident in `CLOSED`, an invoice in `PAID` or `VOIDED`,
        or a reconciliation run in `POSTED`."
        PRD §3.6: "All three of `COMPLETED`, `CANCELLED` and `ABORTED` are terminal."
        PRD §3.6: "Starting fuelling, `ASSIGNED → FUELING`, is gated on time and fitness."

        Design: Corner/validations/terminal_check_precedes_the_entity_specific_state_error
        """
        env = fx.setup_truck_order(target_state="REQUESTED",
                                   account_overrides={"credit_limit_cents": BIG_CREDIT})
        order_id = env["order"]["id"]

        validate_error(api.start_order(order_id, fx.AGENT),
                       ApiErrorId.ERR_INVALID_ORDER_STATE, 409)

        cancelled = validate_success(api.cancel_order(order_id, fx.AGENT))
        assert cancelled["status"] == "CANCELLED"

        validate_error(api.start_order(order_id, fx.AGENT),
                       ApiErrorId.ERR_ALREADY_TERMINAL, 409)
        assert fx.read_order(order_id)["status"] == "CANCELLED", \
            "the very same call changes its diagnosis once the row is terminal"

    def test_immutable_audit_children_carry_no_state_to_guard(self, api):
        """PRD §2.10: "Only then are the per-machine from-state guards evaluated:
        `ERR_INVALID_RECEIPT_STATE` on receipt sampling, verdict and rejection; `ERR_INVALID_ORDER_STATE`
        on order authorize, assign, unassign, start, uplift posting, complete, abort and cancel;
        `ERR_INVALID_TANK_STATE` on tank service-status changes, quality release, quarantine and tank
        sampling; `ERR_INVALID_ASSET_STATE` on asset status changes and filter changes;
        `ERR_INVALID_SPILL_STATE` on spill escalate, contain, remediate and close;
        `ERR_INVALID_INVOICE_STATE` on invoice issue, dispute, dispute resolution, void and payment; and
        `ERR_INVALID_RUN_STATE` on reconciliation measure and post."
        PRD §3.7: "As an immutable audit document a filter change record carries no `updated_at` and no
        `version`."
        PRD §3.4: "Manual gauging is how physical reality enters the tank record."

        Design: Corner/validations/terminal_check_does_not_apply_to_stateless_children
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=400.0)
        truck = fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        fx.isolate_tank(env["tank"]["id"], "2026-08-10T06:00:00Z", "2026-08-10T10:00:00Z")

        gauge = fx.gauge_tank(env["tank"]["id"], 400.0)
        assert "status" not in gauge, "a gauge reading is a fact, not a machine"
        assert fx.read_tank(env["tank"]["id"])["last_gauge_volume_liters"] == \
            pytest.approx(400.00, abs=0.005)

        validate_success(api.change_asset_status(truck["id"], {"to_status": "DOWN_FOR_FILTER"},
                                                 fx.OPERATOR))
        change = get_success_data(api.create_filter_change(
            truck["id"], {"element_lot_number": "LOT-STATELESS", "element_count": 2,
                          "post_change_differential_pressure_kpa": 6.0}, fx.INSPECTOR_A))

        assert "status" not in change
        assert "version" not in change, \
            "no terminal check can apply to a row that has no terminal state to be in"


class TestPerMachineStateErrorCorners:
    def test_seven_machines_report_seven_different_state_errors(self, api):
        """PRD §2.10: "Only then are the per-machine from-state guards evaluated:
        `ERR_INVALID_RECEIPT_STATE` on receipt sampling, verdict and rejection; `ERR_INVALID_ORDER_STATE`
        on order authorize, assign, unassign, start, uplift posting, complete, abort and cancel;
        `ERR_INVALID_TANK_STATE` on tank service-status changes, quality release, quarantine and tank
        sampling; `ERR_INVALID_ASSET_STATE` on asset status changes and filter changes;
        `ERR_INVALID_SPILL_STATE` on spill escalate, contain, remediate and close;
        `ERR_INVALID_INVOICE_STATE` on invoice issue, dispute, dispute resolution, void and payment; and
        `ERR_INVALID_RUN_STATE` on reconciliation measure and post."
        PRD §3.7: "Recording a filter change is a `QualityInspector` action, permitted when the asset's
        `status` is either `DOWN_FOR_FILTER` or `FILTER_DUE` and the farm is not `FROZEN`, and it is what
        returns the asset to `IN_SERVICE`."
        PRD §3.8: "`CONTAINED → REMEDIATED` requires only that the incident is `CONTAINED` and raises the
        incident's `version` by one; it touches nothing else."

        Design: Corner/validations/each_entity_has_its_own_state_error_id
        """
        env = fx.setup_issued_invoice(
            meter_end_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": BIG_CREDIT})
        farm_id, tank_id = env["farm"]["id"], env["tank"]["id"]

        receipt = fx.record_receipt(tank_id)
        validate_error(api.sign_receipt_verdict(receipt["id"], {"decision": "RELEASE"},
                                                fx.INSPECTOR_B),
                       ApiErrorId.ERR_INVALID_RECEIPT_STATE, 409)

        flight = fx.register_flight(env["account"]["id"], stand_code="E01",
                                    scheduled_departure_utc="2026-08-10T10:00:00Z")
        auth = fx.issue_authorization(env["account"]["id"], flight["id"],
                                      max_authorized_liters=5_000.0)
        order = fx.create_order(flight["id"], auth["id"], tank_id,
                                auth["authorization_code"], delivery_mode="TRUCK",
                                requested_uplift_liters=5_000.0,
                                window_start_utc="2026-08-10T06:00:00Z",
                                window_end_utc="2026-08-10T09:00:00Z")
        validate_error(api.start_order(order["id"], fx.AGENT),
                       ApiErrorId.ERR_INVALID_ORDER_STATE, 409)

        validate_error(api.release_tank_quality(tank_id, fx.INSPECTOR_C),
                       ApiErrorId.ERR_INVALID_TANK_STATE, 409)

        validate_error(api.create_filter_change(
            env["truck"]["id"], {"element_lot_number": "LOT-STATE", "element_count": 2,
                                 "post_change_differential_pressure_kpa": 6.0},
            fx.INSPECTOR_A), ApiErrorId.ERR_INVALID_ASSET_STATE, 409)

        spill = fx.report_spill(farm_id, spilled_volume_liters=5.0, surface="APRON")
        validate_error(api.remediate_spill(spill["id"], fx.ENVIRO),
                       ApiErrorId.ERR_INVALID_SPILL_STATE, 409)

        validate_error(api.issue_invoice(env["invoice"]["id"], fx.BILLING),
                       ApiErrorId.ERR_INVALID_INVOICE_STATE, 409)

        run = fx.open_reconciliation_run(farm_id)
        validate_error(api.post_reconciliation_run(run["id"], fx.ADMIN),
                       ApiErrorId.ERR_INVALID_RUN_STATE, 409)

    def test_the_order_in_the_path_is_diagnosed_before_its_tank(self, api):
        """PRD §2.10: "Only then are the per-machine from-state guards evaluated:
        `ERR_INVALID_RECEIPT_STATE` on receipt sampling, verdict and rejection; `ERR_INVALID_ORDER_STATE`
        on order authorize, assign, unassign, start, uplift posting, complete, abort and cancel;
        `ERR_INVALID_TANK_STATE` on tank service-status changes, quality release, quarantine and tank
        sampling; `ERR_INVALID_ASSET_STATE` on asset status changes and filter changes;
        `ERR_INVALID_SPILL_STATE` on spill escalate, contain, remediate and close;
        `ERR_INVALID_INVOICE_STATE` on invoice issue, dispute, dispute resolution, void and payment; and
        `ERR_INVALID_RUN_STATE` on reconciliation measure and post."
        PRD §2.10: "Then the source-tank quality guard (`ERR_TANK_QUARANTINED`) on order authorization,
        fuelling start and uplift posting; then the sample-verdict guard (`ERR_SAMPLE_VERDICT_FAIL`) on
        receipt verdicts; then the water-bottom guard (`ERR_WATER_BOTTOM_EXCEEDED`) on tank quality release
        and tank service-status changes; then the re-test ceiling (`ERR_RETEST_LIMIT_REACHED`) on receipt
        sampling; then asset serviceability (`ERR_ASSET_NOT_SERVICEABLE`) on order assignment, fuelling
        start and uplift posting; then spill reportability (`ERR_SPILL_NOT_REPORTABLE`) on spill escalation;
        then the empty-result guard (`ERR_EMPTY_TEST_RESULT_SET`) on posting laboratory results."
        PRD §2.10: "The practical reading is that structural problems always beat business problems,
        business-state problems beat safety problems, and safety problems beat money problems."

        Design: Corner/validations/state_error_of_the_acted_on_entity_wins_over_a_related_entity
        """
        env = fx.setup_truck_order(target_state="AUTHORIZED", requested_uplift_liters=20_000.0,
                                   max_authorized_liters=20_000.0,
                                   account_overrides={"credit_limit_cents": BIG_CREDIT})
        order_id, tank_id = env["order"]["id"], env["tank"]["id"]

        quarantined = validate_success(api.quarantine_tank(tank_id, fx.INSPECTOR_A,
                                                           {"reason": "water carry-over"}))
        assert quarantined["quality_status"] == "QUARANTINED"
        assert fx.read_order(order_id)["status"] == "AUTHORIZED", \
            "the cascade only touches assigned and fuelling orders"

        validate_error(api.start_order(order_id, fx.AGENT),
                       ApiErrorId.ERR_INVALID_ORDER_STATE, 409)


class TestSegregationOfDutiesCorners:
    def test_the_inspector_who_drew_the_sample_cannot_sign_its_verdict(self, api):
        """PRD §3.3: "Both branches are `QualityInspector` actions and both refuse a signer whose
        identifier equals the receipt's `sampled_by_user_id` — the inspector who drew the sample may not
        sign its verdict, and an attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.1: "**Segregation of duties.** Three workflow steps compare the acting `X-User-ID` against
        the identifier recorded at the preceding step of the same workflow, and reject a match with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403): an inspector may not sign a receipt verdict when the acting
        identifier equals the receipt's `sampled_by_user_id`; an inspector may not release a tank on the
        quality dimension when the acting identifier equals the `drawn_by_user_id` of the governing periodic
        tank sample; and a billing clerk may not resolve a dispute on an invoice whose `issued_by_user_id`
        equals the acting identifier."
        PRD §3.3: "On success the receipt's `released_at_utc` is stamped from the logical clock and its
        `released_by_user_id` from the acting identifier; the receipt's net volume enters the tank ledger,
        which recomputes the tank's `book_volume_liters`, `reserved_volume_liters` and
        `available_volume_liters`; the farm's permit-day throughput counter is recomputed; and the farm's
        posture is recomputed, which may land on `RESTRICTED` the moment permit utilisation reaches the 90
        percent boundary."

        Design: Corner/validations/sampler_cannot_release_their_own_sample
        """
        env = fx.setup_farm_with_released_tank()
        receipt, _sample = fx.make_tested_receipt(env["tank"]["id"], drawer=fx.INSPECTOR_A)
        assert receipt["sampled_by_user_id"] == "qi-alice"

        validate_error(api.sign_receipt_verdict(receipt["id"], {"decision": "RELEASE"},
                                                fx.INSPECTOR_A),
                       ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        released = fx.sign_verdict(receipt["id"], "RELEASE", fx.INSPECTOR_B)
        assert released["status"] == "RELEASED"
        assert released["released_by_user_id"] == "qi-bob"
        assert released["released_by_user_id"] != released["sampled_by_user_id"], \
            "a second pair of eyes is exactly what the rule buys"

    def test_the_same_inspector_may_still_post_the_laboratory_results(self, api):
        """PRD §2.1: "**Segregation of duties.** Three workflow steps compare the acting `X-User-ID`
        against the identifier recorded at the preceding step of the same workflow, and reject a match with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403): an inspector may not sign a receipt verdict when the acting
        identifier equals the receipt's `sampled_by_user_id`; an inspector may not release a tank on the
        quality dimension when the acting identifier equals the `drawn_by_user_id` of the governing periodic
        tank sample; and a billing clerk may not resolve a dispute on an invoice whose `issued_by_user_id`
        equals the acting identifier."
        PRD §3.2: "It creates a quality sample whose `sample_purpose` is `RECEIPT_QC`, whose `status` is
        `DRAWN`, and whose `fuel_receipt_id` points back at this receipt, stamps the receipt's
        `sampled_by_user_id` with the acting identifier, and raises the receipt's `version` by one."
        PRD §3.2: "Posting results sets the sample's `status` to `TESTED`, records `tested_by_user_id` from
        the acting identifier, and raises the receipt's `version` by one."

        Design: Corner/validations/segregation_is_not_rbac
        """
        env = fx.setup_farm_with_released_tank()
        receipt = fx.record_receipt(env["tank"]["id"])
        sample = fx.draw_receipt_sample(receipt["id"], fx.INSPECTOR_A)
        assert fx.read_receipt(receipt["id"])["sampled_by_user_id"] == "qi-alice"

        tested = validate_success(api.post_test_results(
            sample["id"], F.create_test_results_payload(), fx.INSPECTOR_A))

        assert tested["status"] == "TESTED"
        assert tested["verdict"] == "PASS", \
            "only the release decision is segregated, so testing one's own sample is ordinary work"
        assert fx.read_receipt(receipt["id"])["status"] == "UNDER_TEST"

    def test_a_receipt_that_is_not_yet_tested_reports_its_state_not_the_signer(self, api):
        """PRD §2.10: "Only then are the per-machine from-state guards evaluated:
        `ERR_INVALID_RECEIPT_STATE` on receipt sampling, verdict and rejection; `ERR_INVALID_ORDER_STATE`
        on order authorize, assign, unassign, start, uplift posting, complete, abort and cancel;
        `ERR_INVALID_TANK_STATE` on tank service-status changes, quality release, quarantine and tank
        sampling; `ERR_INVALID_ASSET_STATE` on asset status changes and filter changes;
        `ERR_INVALID_SPILL_STATE` on spill escalate, contain, remediate and close;
        `ERR_INVALID_INVOICE_STATE` on invoice issue, dispute, dispute resolution, void and payment; and
        `ERR_INVALID_RUN_STATE` on reconciliation measure and post."
        PRD §2.10: "Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`) comes next on its three operations
        — receipt verdict, tank quality release and invoice dispute resolution."
        PRD §3.3: "Both branches are `QualityInspector` actions and both refuse a signer whose identifier
        equals the receipt's `sampled_by_user_id` — the inspector who drew the sample may not sign its
        verdict, and an attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/segregation_check_follows_the_state_checks
        """
        env = fx.setup_farm_with_released_tank()
        receipt = fx.record_receipt(env["tank"]["id"])
        fx.draw_receipt_sample(receipt["id"], fx.INSPECTOR_A)
        sampled = fx.read_receipt(receipt["id"])
        assert sampled["status"] == "SAMPLED"
        assert sampled["sampled_by_user_id"] == "qi-alice"

        validate_error(api.sign_receipt_verdict(receipt["id"], {"decision": "RELEASE"},
                                                fx.INSPECTOR_A),
                       ApiErrorId.ERR_INVALID_RECEIPT_STATE, 409)
        assert fx.read_receipt(receipt["id"])["status"] == "SAMPLED", \
            "the state band runs first even when the signer is the sampler themselves"
