"""Coil disposition lifecycle, list behavior, and the conserved weight ledger
(PRD §2.3, §2.6, §2.9, §3.4, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_kg,
    approve_coil,
    create_coil,
    get_coil,
    get_order,
    get_press,
    get_run,
    schedule_run,
    setup_completed_run,
    setup_runnable,
    start_run,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCoilDisposition:
    def test_rejected_coil_accepts_no_further_transitions(self, api, quality_engineer_headers):
        """PRD §3.4: "`REJECTED` and `DEPLETED` are terminal."
        PRD §2.5: "The target resource's current state permits the requested action — a run must be `RUNNING` to complete, a coil must be `APPROVED` to feed a run start, and so on through every state machine in §3. Failure: `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/coil_terminal_rejected_accepts_no_transitions
        """
        coil = create_coil(coil_number="C-TERM", heat_lot_number="HL-TERM",
                           material_spec="DC04", thickness_mm=0.8, received_weight_kg=100)
        validate_success(api.reject_steel_coil(coil["id"], quality_engineer_headers))
        resp = api.hold_steel_coil(coil["id"], quality_engineer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        coil_after = validate_success(api.get_steel_coil(coil["id"], quality_engineer_headers))
        assert coil_after["status"] == "REJECTED"


class TestCoilListing:
    def test_coil_list_paginates_with_default_limit(self, api, shipping_clerk_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100."
        PRD §2.3: "The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/pagination_envelope_shape
        """
        for i in range(1, 13):
            create_coil(coil_number=f"C-PG{i:02d}", heat_lot_number="HL-PG",
                        material_spec="DC04", thickness_mm=0.8, received_weight_kg=10)
        resp = api.list_steel_coils(shipping_clerk_headers)
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert len(data) == 10, f"default limit is 10, got {len(data)} items"
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True

    def test_coil_list_filters_by_status(self, api, shipping_clerk_headers, quality_engineer_headers):
        """PRD §2.6: "Customers can be listed filtered by `active`; parts by `customer_id`; dies by `status`; presses by `status`; part–die assignments by `part_id` or `die_id`; die changeovers by `press_id`, `from_die_id`, `to_die_id`, or `status`; production runs by `production_order_id`, `press_id`, `die_id`, `coil_id`, or `status`; layered audits by `press_id`, `escalated_from_id`, `result`, or `audit_tier`; steel coils by `status` or `heat_lot_number`; strip layouts of a part by `status`; production orders by `part_id` or `status`; runs of an order by `status`; outside-processing orders of an order by `status`; and index publications by `index_code`."

        Design: Corner/endpoints/filtered_list_by_status
        """
        create_coil(coil_number="C-F1", heat_lot_number="HL-F", material_spec="DC04",
                    thickness_mm=0.8, received_weight_kg=10)
        c2 = create_coil(coil_number="C-F2", heat_lot_number="HL-F", material_spec="DC04",
                         thickness_mm=0.8, received_weight_kg=10)
        validate_success(api.reject_steel_coil(c2["id"], quality_engineer_headers))
        data, meta = validate_paginated(
            api.list_steel_coils(shipping_clerk_headers, params={"status": "RECEIVED"})
        )
        assert len(data) == 1, f"expected exactly the RECEIVED coil, got {len(data)}"
        assert data[0]["coil_number"] == "C-F1"


class TestHeldCoilGatesRunStart:
    def test_held_coil_blocks_run_start_with_quality_hold(self, api, quality_engineer_headers, press_operator_headers):
        """PRD §3.4: "Holding a coil deliberately does not abort the `SCHEDULED` runs that already reference it; instead the block is enforced at start time, when attempting to start a run against a held coil is rejected `ERR_QUALITY_HOLD`."
        PRD §3.4: "Starting a run against a coil that is `QUARANTINED`, `ON_HOLD`, or `REJECTED` draws `ERR_QUALITY_HOLD` (422); a coil in any other non-approved disposition (for example still `RECEIVED`) fails the state precondition with `ERR_INVALID_STATE` (409)."

        Design: Difficulty/cross_entity_state_dependency/run_start_depends_on_coil_and_die_states
        """
        ctx = setup_runnable(quantity_ordered=10, coil_weight_kg=500)
        run = schedule_run(ctx)
        validate_success(api.hold_steel_coil(ctx["coil"]["id"], quality_engineer_headers))
        resp = api.start_production_run(run["id"], press_operator_headers)
        validate_error(resp, ApiErrorId.ERR_QUALITY_HOLD)
        run_after = get_run(run["id"])
        assert run_after["status"] == "SCHEDULED", (
            "the run's own state was valid; the rejection must leave it SCHEDULED"
        )

    def test_released_hold_lets_same_run_start(self, api, quality_engineer_headers):
        """PRD §3.4: "An approved coil can be put on hold — `APPROVED` to `ON_HOLD` — and later released back, `ON_HOLD` to `APPROVED`."
        PRD §3.7: "When the start succeeds, the press moves to `RUNNING`, and an order that was `RELEASED` advances to `IN_PROGRESS` with its `version` incremented and `updated_at` refreshed."

        Design: Difficulty/cross_entity_state_dependency/run_start_depends_on_coil_and_die_states
        """
        ctx = setup_runnable(quantity_ordered=10, coil_weight_kg=500)
        run = schedule_run(ctx)
        validate_success(api.hold_steel_coil(ctx["coil"]["id"], quality_engineer_headers))
        validate_success(api.release_hold_steel_coil(ctx["coil"]["id"], quality_engineer_headers))
        started = start_run(run["id"])
        assert started["status"] == "RUNNING"
        assert get_press(ctx["press"]["id"])["status"] == "RUNNING"
        assert get_order(ctx["order"]["id"])["status"] == "IN_PROGRESS"


class TestCoilLedgerConservation:
    def test_hold_release_pair_leaves_ledger_unchanged(self, api, quality_engineer_headers):
        """PRD §2.9: "A steel coil's weight is a conserved ledger quantity. At receipt, `remaining_weight_kg` is initialized exactly equal to `received_weight_kg`; thereafter the only write that ever decrements it is the successful completion of a production run, which subtracts that run's `steel_consumed_kg` (§3.7)."
        PRD §3.7: "The coil's `remaining_weight_kg` is decremented by exactly that amount at the same precision, the coil's `version` increments, and if the remainder is exactly zero the coil moves `APPROVED` to `DEPLETED`."

        Design: Difficulty/compensating_invariant/coil_weight_conservation_under_hold_release_cycle
        """
        ctx = setup_completed_run(shots_recorded=100, quantity_ordered=500,
                                  coil_weight_kg=500)
        coil_before = get_coil(ctx["coil"]["id"])
        assert_kg(coil_before["remaining_weight_kg"], 415.0, "remaining after 85 kg consumption")

        validate_success(api.hold_steel_coil(ctx["coil"]["id"], quality_engineer_headers))
        validate_success(api.release_hold_steel_coil(ctx["coil"]["id"], quality_engineer_headers))
        coil_after = get_coil(ctx["coil"]["id"])
        assert coil_after["status"] == "APPROVED"
        assert_kg(coil_after["remaining_weight_kg"], 415.0,
                  "the hold/release pair must leave the conserved ledger unchanged")

    def test_ledger_invariant_remaining_plus_consumed_equals_received(self, api):
        """PRD §2.9: "A steel coil's weight is a conserved ledger quantity. At receipt, `remaining_weight_kg` is initialized exactly equal to `received_weight_kg`; thereafter the only write that ever decrements it is the successful completion of a production run, which subtracts that run's `steel_consumed_kg` (§3.7)."
        PRD §3.7: "Its `steel_consumed_kg` is the `good_count` multiplied by the part's `steel_content_kg`, rounded to 3 decimal places half up."

        Design: Difficulty/compensating_invariant/coil_weight_conservation_under_hold_release_cycle
        """
        ctx = setup_completed_run(shots_recorded=100, quantity_ordered=500,
                                  coil_weight_kg=500)
        run_after = get_run(ctx["run"]["id"])
        assert_kg(run_after["steel_consumed_kg"], 85.0, "steel_consumed_kg")
        coil_after = get_coil(ctx["coil"]["id"])
        conserved = coil_after["remaining_weight_kg"] + run_after["steel_consumed_kg"]
        assert conserved == pytest.approx(coil_after["received_weight_kg"], abs=1e-6), (
            "conservation violated: remaining + consumed must equal received"
        )
        assert_kg(coil_after["received_weight_kg"], 500.0, "received_weight_kg")
