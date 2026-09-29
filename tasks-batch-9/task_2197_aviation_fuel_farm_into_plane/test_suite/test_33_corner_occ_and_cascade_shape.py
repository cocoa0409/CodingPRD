"""Corner behaviour of the two concurrency guards and of the cascade machinery: both version rules are
reachable, no other endpoint has one, and a cascade is atomic, terminal-safe and idempotent."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, fixtures as fx, factories as F,
)

BIG_CREDIT = 100_000_000_000
FAIL_METRICS = {"water_reaction_rating": 3, "particulate_mg_per_l": 2.5,
                "conductivity_ps_per_m": 40.0, "flash_point_c": 41.0}
FAILING_PARCEL = dict(delivery_mode="TRUCK", supplier_name="Refinery One",
                      meter_ticket_gross_liters=30120.0, tank_opening_gauge_liters=100.0,
                      tank_closing_gauge_liters=30100.0, temperature_c=25.0,
                      certificate_density_kg_per_m3=795.0, measured_water_liters=200.0)


class TestOptimisticConcurrencyCorners:
    def test_the_order_guard_and_the_account_guard_are_separate_rules(self, api):
        """PRD §2.9: "If `expected_fueling_order_version` does not equal the order's current `version`, the
        post is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), which is what prevents a ticket from
        being written against an out-of-date view of the order's posted volume and the tank reservation
        behind it."
        PRD §2.9: "If `expected_airline_account_version` does not equal the account's current `version`, the
        create is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412), catching the case where the account's
        exposure figures moved — a completed order, an issued invoice, a voided invoice — after the clerk
        computed the sweep."

        Design: Corner/complexity_layers/both_occ_rules_are_independently_reachable
        """
        ramp = fx.setup_truck_order(target_state="FUELING",
                                    account_overrides={"credit_limit_cents": BIG_CREDIT})
        validate_error(api.create_uplift_record(
            ramp["order"]["id"], F.create_uplift_record_payload(
                1, meter_start_liters=0.0, meter_end_liters=20_000.0, temperature_c=15.0),
            fx.AGENT), ApiErrorId.ERR_STALE_ORDER_VERSION, 412)

        billed = fx.setup_completed_order(meter_end_liters=20_000.0,
                                         account_overrides={"credit_limit_cents": BIG_CREDIT})
        account_id = billed["account"]["id"]
        validate_error(api.create_invoice(F.create_invoice_payload(
            account_id, 1, period_start_utc="2026-08-10T00:00:00Z",
            period_end_utc="2026-08-10T08:00:00Z"), fx.BILLING),
                       ApiErrorId.ERR_STALE_ACCOUNT_VERSION, 412)

        live_version = fx.read_account(account_id)["version"]
        draft = validate_success(api.create_invoice(F.create_invoice_payload(
            account_id, live_version, period_start_utc="2026-08-10T00:00:00Z",
            period_end_utc="2026-08-10T08:00:00Z"), fx.BILLING), 201)
        assert draft["status"] == "DRAFT", \
            "the two guards name different parents and are never interchanged"

    def test_no_other_endpoint_has_a_version_guard(self, api):
        """PRD §2.9: "No other endpoint in this system accepts a version field. Requests to endpoints outside
        these two must not be expected to supply one, and supplying one has no effect."
        PRD §2.10: "The two optimistic-concurrency checks come next — `ERR_STALE_ORDER_VERSION` on uplift
        posting and `ERR_STALE_ACCOUNT_VERSION` on invoice creation — followed by the terminal-state guard
        (`ERR_ALREADY_TERMINAL`), which applies to every state-transition endpoint and fires when the target
        row already sits in a terminal state for its machine: a fuel receipt in `RELEASED` or `REJECTED`, a
        fuelling order in `COMPLETED`, `CANCELLED` or `ABORTED`, a fuel authorization in `REDEEMED`, `VOIDED`
        or `EXPIRED`, a spill incident in `CLOSED`, an invoice in `PAID` or `VOIDED`, or a reconciliation run
        in `POSTED`."

        Design: Corner/complexity_layers/occ_is_the_only_concurrency_mechanism
        """
        env = fx.setup_fueling_order_with_uplift(
            meter_end_liters=20_000.0, requested_uplift_liters=20_000.0,
            max_authorized_liters=20_000.0,
            account_overrides={"credit_limit_cents": BIG_CREDIT})
        order_id = env["order"]["id"]

        completed = validate_success(api.complete_order(
            order_id, fx.AGENT, {"expected_fueling_order_version": 999}), 200)
        assert completed["status"] == "COMPLETED", \
            "a version field outside the two guarded endpoints has no effect at all"

        # a conflict on any other endpoint is expressed as a state error, never as a 412
        validate_error(api.complete_order(order_id, fx.AGENT),
                       ApiErrorId.ERR_ALREADY_TERMINAL, 409)


class TestCascadeShapeCorners:
    def test_the_quarantine_response_and_the_next_reads_agree_immediately(self, api):
        """PRD §2.11: "Cascades run to completion within the request that triggered them; there is no
        deferred or eventual settlement."
        PRD §3.3: "**Hop one** sets the destination tank's `quality_status` to `QUARANTINED`, which is the
        tank's own quality-dimension move from either `RELEASED` or `ON_TEST` into `QUARANTINED`."
        PRD §3.3: "**Hop two**, caused by hop one, reaches every fuelling order drawing on that tank: each
        order in `ASSIGNED` is driven `ASSIGNED → AUTHORIZED`, releasing its `fueling_asset_id` and
        `hydrant_pit_id` and raising its `unassign_count` by one, and each order in `FUELING` is driven
        `FUELING → ABORTED` with `abort_reason` set to `QUALITY_HOLD`."

        Design: Corner/complexity_layers/cascade_is_atomic_with_its_trigger
        """
        env = fx.setup_fueling_order_with_uplift(
            meter_end_liters=20_000.0, requested_uplift_liters=20_000.0,
            max_authorized_liters=20_000.0,
            account_overrides={"credit_limit_cents": BIG_CREDIT})
        receipt, _sample = fx.make_tested_receipt(env["tank"]["id"],
                                                  metrics=dict(FAIL_METRICS),
                                                  **FAILING_PARCEL)

        signed = fx.sign_verdict(receipt["id"], "QUARANTINE", fx.INSPECTOR_B)

        assert signed["status"] == "QUARANTINED", \
            "the triggering response already carries the quarantine"
        assert fx.read_tank(env["tank"]["id"])["quality_status"] == "QUARANTINED"
        order = fx.read_order(env["order"]["id"])
        assert order["status"] == "ABORTED"
        assert order["abort_reason"] == "QUALITY_HOLD"
        assert fx.read_uplift(env["uplift"]["id"])["status"] == "VOIDED"
        assert fx.read_authorization(env["auth"]["id"])["status"] == "VOIDED"
        assert fx.read_tank(env["tank"]["id"])["book_volume_liters"] == \
            pytest.approx(1000000.00, abs=0.005), \
            "no background job was needed for the credit back to the ledger"

    def test_a_freeze_leaves_finished_work_alone(self, api):
        """PRD §3.8: "**Hop two**, caused by hop one, sweeps the farm: every fuelling order at the farm in
        `AUTHORIZED` is driven `AUTHORIZED → CANCELLED`, every order in `FUELING` is driven `FUELING →
        ABORTED` with `abort_reason` `SPILL`, and every fuelling asset at the farm whose `status` is
        `IN_SERVICE` or `FILTER_DUE` is driven to `DOWN_MAINTENANCE`."
        PRD §3.8: "**Hop three**, caused by hop two, settles each affected order: its authorization is
        driven `ISSUED → VOIDED` with `voided_reason` `FARM_FROZEN`, its tank reservation is released, and
        the owning account's `accrual_exposure_cents` is recomputed; aborted orders additionally void their
        `POSTED` uplift tickets and credit those tickets' `net_liters` back to the source tank's
        `book_volume_liters`."
        PRD §3.6: "**Completion**, `FUELING → COMPLETED`, requires at least one `POSTED` ticket on the order
        (otherwise `ERR_NO_UPLIFT_RECORDED`) and requires the order's `posted_net_liters` to be at most the
        authorization's `max_authorized_liters` — with **no tolerance at all** at this gate, in contrast to
        the five percent allowed when posting."

        Design: Corner/complexity_layers/cascade_does_not_touch_terminal_children
        """
        env = fx.setup_completed_order(meter_end_liters=20_000.0,
                                      account_overrides={"credit_limit_cents": BIG_CREDIT})
        assert fx.read_authorization(env["auth"]["id"])["status"] == "REDEEMED"
        spill = fx.report_spill(env["farm"]["id"], spilled_volume_liters=25.0,
                                surface="APRON", fueling_asset_id=env["truck"]["id"])

        fx.escalate_spill(spill["id"])

        assert fx.read_farm(env["farm"]["id"])["posture"] == "FROZEN"
        assert fx.read_asset(env["truck"]["id"])["status"] == "DOWN_MAINTENANCE", \
            "the sweep did run — it simply skipped the finished rows"
        assert fx.read_order(env["order"]["id"])["status"] == "COMPLETED"
        assert fx.read_authorization(env["auth"]["id"])["status"] == "REDEEMED"
        ticket = fx.read_uplift(env["uplift"]["id"])
        assert ticket["status"] == "POSTED"
        assert fx.read_tank(env["tank"]["id"])["book_volume_liters"] == \
            pytest.approx(980000.00, abs=0.005), \
            "a completed order's ticket is not credited back"

    def test_a_second_escalation_changes_nothing_and_one_containment_is_not_enough(self, api):
        """PRD §3.8: "**Hop one** recomputes the farm's posture, which becomes `FROZEN` because an escalated
        incident now exists at the farm."
        PRD §3.8: "That recomputation is how a farm thaws: the farm leaves `FROZEN` once no escalated
        incident remains at it and its permit is `ACTIVE` and unexpired, landing on `RESTRICTED` while any
        incident is still merely `REPORTED`."
        PRD §3.8: "An escalated incident reaches containment by the same action from a different origin:
        `ESCALATED → CONTAINED` requires only a `contained_volume_liters` no greater than the spilled volume,
        applies the same reliability penalty, and recomputes the open spill count and posture."

        Design: Corner/complexity_layers/cascade_is_idempotent_under_repetition
        """
        env = fx.setup_truck_order(target_state="AUTHORIZED",
                                   account_overrides={"credit_limit_cents": BIG_CREDIT})
        first = fx.report_spill(env["farm"]["id"], spilled_volume_liters=25.0,
                                surface="APRON")
        fx.escalate_spill(first["id"])
        after_first = fx.read_order(env["order"]["id"])
        assert after_first["status"] == "CANCELLED"
        assert fx.read_authorization(env["auth"]["id"])["status"] == "VOIDED"

        second = fx.report_spill(env["farm"]["id"], spilled_volume_liters=25.0,
                                 surface="APRON")
        fx.escalate_spill(second["id"], regulator_reference="REG-2026-0002")

        assert fx.read_farm(env["farm"]["id"])["posture"] == "FROZEN"
        repeated = fx.read_order(env["order"]["id"])
        assert repeated["status"] == "CANCELLED"
        assert repeated["version"] == after_first["version"], \
            "the second sweep found nothing left to move, so nothing moved twice"

        fx.contain_spill(second["id"], 25.0)
        assert fx.read_farm(env["farm"]["id"])["posture"] == "FROZEN", \
            "the first incident is still escalated, so the farm has not thawed"
