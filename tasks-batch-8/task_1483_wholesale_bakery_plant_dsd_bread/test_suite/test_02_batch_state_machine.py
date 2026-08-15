"""Batch lifecycle state machine (PRD §3.4) and order terminal lockdown (PRD §3.2)."""
from test_helpers import (
    TEST_USERS,
    assert_batch,
    create_batch,
    create_line,
    create_plan,
    create_plant,
    create_product,
    lock_plan,
    make_operator_headers,
    release_plan,
    set_clock,
    validate_error,
    validate_success,
)


class TestBatchInitialState:
    def test_batch_initial_state_scheduled(self, api):
        """PRD §3.4: "A newly created batch starts in `SCHEDULED`, and its
        creation increments the parent plan's `version` by 1."
        PRD §3.4: "until it is baked a batch has no `fresh_until`."

        Design: Corner/state_machines/batch_initial_state_scheduled
        """
        plant = create_plant()
        product_a = create_product(plant["id"])
        line = create_line(plant["id"])
        set_clock("2026-08-06T00:00:00Z")
        plan = create_plan(plant["id"], expected_plant_version=plant["version"])
        locked_plan = lock_plan(plan["id"])
        resp = api.create_batch(
            {
                "production_plan_id": plan["id"],
                "line_id": line["id"],
                "product_id": product_a["id"],
                "qty_units": 100,
                "scheduled_start_at": "2026-08-09T07:00:00Z",
                "scheduled_end_at": "2026-08-09T09:00:00Z",
                "expected_production_plan_version": locked_plan["version"],
            },
            TEST_USERS["planner_headers"],
        )
        batch = validate_success(resp, expected_status=201)
        assert_batch(batch)
        assert batch["status"] == "SCHEDULED"
        assert batch.get("bake_completed_at") is None, (
            f"unbaked batch must have no bake_completed_at, got {batch.get('bake_completed_at')!r}"
        )


class TestBatchInvalidTransition:
    def test_batch_start_proof_from_scheduled_rejected(self, api):
        """PRD §3.4: "Starting the proof moves `MIXING` to `PROOFING` and
        stamps `proof_started_at`." — the transition is defined only from
        MIXING.
        PRD §2.9 step 6: "State preconditions — the target resource is in a
        valid from-state for the requested transition, including: the plan
        is released before a batch may start mixing, the pickup stop is
        delivered before a stale return enters the credit chain, and batches
        are released before delivery; failure yields `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/batch_start_proof_from_scheduled_rejected
        """
        plant = create_plant()
        product_a = create_product(plant["id"])
        line = create_line(plant["id"])
        set_clock("2026-08-06T00:00:00Z")
        plan = create_plan(plant["id"], expected_plant_version=plant["version"])
        locked_plan = lock_plan(plan["id"])
        batch = create_batch(
            plan["id"], line["id"], product_a["id"], plan_version=locked_plan["version"]
        )
        resp = api.start_proof(batch["id"], make_operator_headers("op-1"))
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)
        after = validate_success(api.get_batch(batch["id"], TEST_USERS["planner_headers"]))
        assert after["status"] == "SCHEDULED"

    def test_batch_terminal_lockdown_after_abort_rejected(self, api):
        """PRD §2.6: "Resources in a terminal state are locked down: any
        action that names a terminal resource as its target is rejected with
        `ERR_INVALID_STATE` (HTTP 409) rather than partially applied."
        PRD §3.4: "aborting lands in the terminal `ABORTED` state."

        Design: Corner/state_machines/batch_terminal_lockdown_after_abort_rejected
        """
        plant = create_plant()
        product_a = create_product(plant["id"])
        line = create_line(plant["id"])
        set_clock("2026-08-06T00:00:00Z")
        plan = create_plan(plant["id"], expected_plant_version=plant["version"])
        locked_plan = lock_plan(plan["id"])
        batch = create_batch(
            plan["id"], line["id"], product_a["id"], plan_version=locked_plan["version"]
        )
        aborted = validate_success(
            api.abort_batch(batch["id"], TEST_USERS["planner_headers"])
        )
        assert aborted["status"] == "ABORTED"

        # The plan has not been RELEASED, but the terminal-state lockdown
        # applies regardless of plan state.
        resp = api.start_mix(batch["id"], make_operator_headers("op-1"))
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)
        after = validate_success(api.get_batch(batch["id"], TEST_USERS["planner_headers"]))
        assert after["status"] == "ABORTED"


class TestOrderCancelIdempotency:
    def test_order_second_cancel_rejected(self, api):
        """PRD §3.2: "A planner may also cancel an order, but only from
        `PLACED` or `CONFIRMED`; cancellation moves it to the terminal
        `CANCELLED` state."
        PRD §2.6: "Resources in a terminal state are locked down: any action
        that names a terminal resource as its target is rejected with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/order_second_cancel_rejected
        """
        plant = create_plant()
        product_a = create_product(plant["id"])
        store_resp = api.create_store(
            {
                "plant_id": plant["id"],
                "name": "S",
                "lead_time_hours": 48,
                "min_remaining_life_hours_on_delivery": 12,
                "shelf_capacity_units": 100,
            },
            TEST_USERS["admin_headers"],
        )
        store = validate_success(store_resp, expected_status=201)
        set_clock("2026-08-06T00:00:00Z")
        order_resp = api.create_store_order(
            {
                "store_id": store["id"],
                "delivery_date": "2026-08-10",
                "lines": [{"product_id": product_a["id"], "qty": 10}],
            },
            TEST_USERS["planner_headers"],
        )
        order = validate_success(order_resp, expected_status=201)
        cancelled = validate_success(
            api.cancel_store_order(order["id"], TEST_USERS["planner_headers"])
        )
        assert cancelled["status"] == "CANCELLED"

        resp = api.cancel_store_order(order["id"], TEST_USERS["planner_headers"])
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)
        after = validate_success(
            api.get_store_order(order["id"], TEST_USERS["planner_headers"])
        )
        assert after["status"] == "CANCELLED"


class TestProofWindowTooEarly:
    def test_proof_window_too_early_rejected(self, api):
        """PRD §3.4: "Starting the bake is gated on the proof window: at
        least 60 minutes and at most 120 minutes must have elapsed since
        `proof_started_at` — both bounds inclusive — or the transition is
        rejected with `ERR_PROOF_WINDOW_VIOLATION`."

        Design: Corner/errors/proof_window_too_early_rejected
        """
        plant = create_plant(name="Plant P ProofEarly")
        product_a = create_product(plant["id"])
        line = create_line(plant["id"])
        set_clock("2026-08-09T07:50:00Z")
        plan = create_plan(plant["id"], expected_plant_version=plant["version"])
        locked_plan = lock_plan(plan["id"])
        batch = create_batch(
            plan["id"], line["id"], product_a["id"],
            plan_version=locked_plan["version"], qty_units=100,
        )
        release_plan(plan["id"])
        op = make_operator_headers("op-1")
        validate_success(api.start_mix(batch["id"], op))
        validate_success(api.start_proof(batch["id"], op))
        # 30 minutes elapsed — below the 60-minute floor.
        set_clock("2026-08-09T08:20:00Z")
        resp = api.start_bake(batch["id"], op)
        validate_error(resp, "ERR_PROOF_WINDOW_VIOLATION", expected_status=409)
        after = validate_success(api.get_batch(batch["id"], TEST_USERS["planner_headers"]))
        assert after["status"] == "PROOFING"


class TestBatchOverproofAutoTransition:
    def test_batch_overproof_auto_then_start_bake_rejected(self, api):
        """PRD §2.4: "every batch still in `PROOFING` whose proof has run
        longer than 120 minutes transitions to `OVERPROOFED`."
        PRD §3.4: "Starting the bake is gated on the proof window: at least
        60 minutes and at most 120 minutes must have elapsed since
        `proof_started_at` — both bounds inclusive — or the transition is
        rejected with `ERR_PROOF_WINDOW_VIOLATION`."

        Design: Corner/state_machines/batch_overproof_auto_then_start_bake_rejected
        """
        plant = create_plant()
        product_a = create_product(plant["id"])
        line = create_line(plant["id"])
        set_clock("2026-08-09T07:50:00Z")
        plan = create_plan(plant["id"], expected_plant_version=plant["version"])
        locked_plan = lock_plan(plan["id"])
        batch = create_batch(
            plan["id"], line["id"], product_a["id"], plan_version=locked_plan["version"]
        )
        release_plan(plan["id"])
        op = make_operator_headers("op-1")
        validate_success(api.start_mix(batch["id"], op))
        validate_success(api.start_proof(batch["id"], op))
        # 121 minutes past proof_started_at — beyond the 120-minute window.
        set_clock("2026-08-09T09:51:00Z")

        plant_after = validate_success(
            api.close_day(plant["id"], TEST_USERS["admin_headers"])
        )
        assert plant_after["day_index"] == 1, (
            f"close_day must advance day_index by 1, got {plant_after['day_index']}"
        )

        batch_after = validate_success(api.get_batch(batch["id"], TEST_USERS["planner_headers"]))
        assert batch_after["status"] == "OVERPROOFED", (
            f"close_day sweep must flip long-proofing batch to OVERPROOFED, got {batch_after['status']}"
        )

        # From OVERPROOFED the start-bake transition is not defined; the from-
        # state check rejects with ERR_INVALID_STATE (PRD §2.9 step 6).
        resp = api.start_bake(batch["id"], op)
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)
