"""Mix-batch lifecycle, run state machine, tunnel bookings (PRD §3.3, §3.5)."""
from test_helpers import (
    ApiErrorId,
    complete_run,
    create_booking,
    create_mix_batch,
    create_product,
    create_released_batch,
    create_run,
    get_success_data,
    make_qa_manager_headers,
    pasteurize_batch,
    set_clock,
    setup_mix_assigned_run,
    setup_plant,
    start_run,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import PM, PLANNER


class TestMixAssignment:
    def test_assign_mix_requires_released_state(self, api):
        """PRD §3.5: "the planner assigns a RELEASED MixBatch ... A batch
        not yet RELEASED rejects with ERR_MIX_NOT_RELEASED"."

        The batch here is PASTEURIZED (pasteurized but never QA-released).

        Design: Difficulty/cross_entity_state_dependency/assign_mix_requires_released_state
        """
        product, line, _, _ = setup_plant()
        set_clock("2026-08-10T08:00:00Z")
        batch = create_mix_batch(product["id"], batch_code="MB-G")
        pasteurize_batch(batch["id"], "op_1")
        run = create_run(product["id"], line["id"], run_code="R-G",
                         scheduled_start="2026-08-10T14:00:00Z")
        resp = api.assign_mix(run["id"], {"mix_batch_id": batch["id"]}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_MIX_NOT_RELEASED)
        run_after = get_success_data(api.get_production_run(run["id"], PM))
        assert run_after["status"] == "SCHEDULED"
        assert run_after["mix_batch_id"] is None

    def test_assign_mix_rejects_planned_batch(self, api):
        """PRD §3.5: "A batch not yet RELEASED rejects with
        ERR_MIX_NOT_RELEASED"; §3.3: "A ProductionPlanner creates a
        MixBatch in PLANNED status". A batch still in PLANNED (never
        pasteurized) is also not RELEASED.

        Design: Difficulty/cross_entity_state_dependency/assign_mix_requires_released_state
        """
        product, line, _, _ = setup_plant()
        batch = create_mix_batch(product["id"], batch_code="MB-P")
        run = create_run(product["id"], line["id"], run_code="R-G2",
                         scheduled_start="2026-08-10T14:00:00Z")
        resp = api.assign_mix(run["id"], {"mix_batch_id": batch["id"]}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_MIX_NOT_RELEASED)
        run_after = get_success_data(api.get_production_run(run["id"], PM))
        assert run_after["status"] == "SCHEDULED"


class TestMixBatchTerminal:
    def test_mix_release_after_reject_rejected(self, api):
        """PRD §3.3: "Rejection is permitted from either PASTEURIZED or
        RELEASED" — REJECTED is terminal, so releasing a rejected batch is
        rejected with ERR_INVALID_STATE (§5: "Target resource's state does
        not allow the requested transition")."

        Design: Corner/state_machines/mix_release_after_reject_rejected
        """
        product = create_product()
        set_clock("2026-08-10T08:00:00Z")
        batch = create_mix_batch(product["id"], batch_code="MB-X")
        pasteurize_batch(batch["id"], "op_1")
        get_success_data(api.reject_mix_batch(
            batch["id"], make_qa_manager_headers("qa_1")))
        resp = api.release_mix_batch(batch["id"],
                                     make_qa_manager_headers("qa_2"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        batch_after = get_success_data(api.get_mix_batch(batch["id"], PM))
        assert batch_after["status"] == "REJECTED"


class TestRunInvalidTransitions:
    def test_run_complete_from_scheduled_rejected(self, api):
        """PRD §3.5: completion is defined as a transition a LineOperator
        performs on a running production run ("A LineOperator completes the
        run by supplying actual_units ..."); §5 ERR_INVALID_STATE covers
        "Target resource's state does not allow the requested transition".
        A SCHEDULED run (never mix-assigned, never started) cannot complete.

        Design: Corner/state_machines/run_complete_from_scheduled_rejected
        """
        product, line, _, zone = setup_plant()
        run = create_run(product["id"], line["id"], run_code="R-I",
                         planned_units=100)
        resp = complete_run(run["id"], 100, 10.0, zone["id"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        run_after = get_success_data(api.get_production_run(run["id"], PM))
        assert run_after["status"] == "SCHEDULED"

    def test_run_cancel_cancels_booking(self, api):
        """PRD §3.5: "Cancellation flips this run's BOOKED tunnel bookings
        to CANCELED"." And §3.5 conflict check: "every existing
        non-cancelled booking on the same tunnel (status BOOKED or
        COMPLETED; CANCELED and EXPIRED are excluded)" — so rebooking the
        same window for another run succeeds after the cancellation.

        Design: Corner/state_machines/run_cancel_cancels_booking
        """
        product, line, tunnel, _ = setup_plant()
        run1 = create_run(product["id"], line["id"], run_code="R-CN",
                          planned_units=1000,
                          scheduled_start="2026-08-10T10:00:00Z")
        booking = create_booking(tunnel["id"], run1["id"],
                                 start_at="2026-08-10T10:00:00Z",
                                 end_at="2026-08-10T11:00:00Z")
        run2 = create_run(product["id"], line["id"], run_code="R-CN2",
                          planned_units=1000,
                          scheduled_start="2026-08-10T10:00:00Z")
        cancelled = validate_success(api.cancel_run(run1["id"], PLANNER))
        assert cancelled["status"] == "CANCELED"
        booking_after = get_success_data(
            api.get_tunnel_booking(booking["id"], PLANNER))
        assert booking_after["status"] == "CANCELED"
        # The cancelled booking no longer blocks the window.
        rebooked = create_booking(tunnel["id"], run2["id"],
                                  start_at="2026-08-10T10:00:00Z",
                                  end_at="2026-08-10T11:00:00Z")
        assert rebooked["status"] == "BOOKED"


class TestMixExpiry:
    def test_mix_expired_at_assign_rejected(self, api):
        """PRD §3.5: "an expiry at or before scheduled_start rejects with
        ERR_MIX_EXPIRED". Batch pasteurized 2026-08-10T08:00 expires
        2026-08-13T08:00 (produced_at plus 72 hours, §3.3); the run is
        scheduled 2026-08-14T09:00, strictly after expiry.

        Design: Corner/validations/mix_expired_at_assign_rejected
        """
        product, line, _, _ = setup_plant()
        batch = create_released_batch(product["id"], batch_code="MB-EX",
                                      clock="2026-08-10T08:00:00Z")
        run = create_run(product["id"], line["id"], run_code="R-EX",
                         scheduled_start="2026-08-14T09:00:00Z")
        resp = api.assign_mix(run["id"], {"mix_batch_id": batch["id"]}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_MIX_EXPIRED)

    def test_mix_product_mismatch_rejected(self, api):
        """PRD §3.5: "a product mismatch rejects with
        ERR_MIX_PRODUCT_MISMATCH"."

        Design: Corner/validations/mix_product_mismatch_rejected
        """
        product, line, _, _ = setup_plant()
        choc = create_product(sku_code="BAR-CHOC-70", product_name="Choc Bar",
                              flavor_family="CHOCOLATE",
                              allergens=["MILK", "SOY"])
        batch = create_released_batch(product["id"], batch_code="MB-MM")
        run = create_run(choc["id"], line["id"], run_code="R-MM",
                         scheduled_start="2026-08-10T14:00:00Z")
        resp = api.assign_mix(run["id"], {"mix_batch_id": batch["id"]}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_MIX_PRODUCT_MISMATCH)


class TestInsufficientMix:
    def test_insufficient_mix_at_complete_rejected(self, api):
        """PRD §3.5: "mix_metered_litres (positive, and no greater than the
        batch's litres_remaining — else ERR_INSUFFICIENT_MIX)". Metering
        600.0 litres against a 500-litre batch must fail and leave the run
        IN_PRODUCTION with no lot created.

        Design: Corner/validations/insufficient_mix_at_complete_rejected
        """
        ctx = setup_mix_assigned_run(run_code="R-IM")
        start_run(ctx["run"]["id"])
        resp = complete_run(ctx["run"]["id"], 2000, 600.0, ctx["zone"]["id"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MIX)
        run_after = get_success_data(
            api.get_production_run(ctx["run"]["id"], PM))
        assert run_after["status"] == "IN_PRODUCTION"
        lots, meta = validate_paginated(
            api.list_inventory_lots(PM, params={"run_id": ctx["run"]["id"]}))
        assert meta["total_count"] == 0
