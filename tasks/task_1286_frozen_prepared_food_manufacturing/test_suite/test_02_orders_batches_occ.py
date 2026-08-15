"""Order intake, batch lifecycle, holds/rework, OCC guards (PRD §2.8, §3.2, §3.3)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_component,
    book_cycle,
    complete_batch,
    complete_run,
    cook_batch,
    create_approved_recipe,
    create_batch,
    create_film_lot,
    create_freezer_cell,
    create_order,
    create_packaging_line,
    create_recipe,
    get_batch,
    kit_batch,
    pin_clock,
    record_ccp,
    schedule_run,
    setup_cooked_batch,
    setup_frozen_batch,
    setup_kitted_batch,
    start_and_verify_cycle,
    start_run,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["line_operator_headers"]
QA_TECH = TEST_USERS["qa_technician_headers"]
QA_MGR = TEST_USERS["qa_manager_headers"]


class TestOrderIntake:
    def test_order_create_with_draft_recipe_rejected(self, api):
        """PRD §3.2: "The referenced recipe must be `APPROVED` at creation;
        referencing a draft or retired recipe is rejected with
        `ERR_RECIPE_NOT_APPROVED`."

        Design: Corner/validations/order_create_with_draft_recipe_rejected
        """
        recipe = create_recipe(name="R-Draft")
        add_component(recipe["id"])
        resp = api.create_production_order(
            {"recipe_id": recipe["id"], "pack_format": "RETAIL", "units_planned": 6000},
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_RECIPE_NOT_APPROVED, expected_status=409)

    def test_batch_create_on_cancelled_order_rejected(self, api):
        """PRD §3.2: "The order must be open — `PLANNED` or `IN_PROGRESS`;
        attempting to add a batch to a `CANCELLED` or `COMPLETED` order is rejected
        with `ERR_ORDER_NOT_OPEN`."
        PRD §3.2: "a `ProductionPlanner` may cancel an order from either `PLANNED`
        or `IN_PROGRESS`, but only while every batch of the order sits in `CREATED`
        or `CANCELLED`"

        Design: Corner/validations/batch_create_on_cancelled_order_rejected
        """
        recipe = create_approved_recipe(name="R-Ord")
        order = create_order(recipe["id"], units_planned=6000)
        cancelled = validate_success(
            api.cancel_production_order(order["id"], PLANNER), expected_status=200
        )
        assert cancelled["status"] == "CANCELLED"
        # The OCC guard passes (version read from the cancel response is current);
        # the state gate must fire instead.
        resp = api.create_batch(
            order["id"],
            {"units_planned": 6000, "expected_order_version": cancelled["version"]},
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_OPEN, expected_status=409)


class TestOrderAutoProgression:
    def test_order_auto_progression_on_batch_lifecycle(self, api):
        """PRD §3.2: "On success the batch begins in `CREATED` status, stamped with
        its `order_id`, the order's `version` increments by one, and the very first
        batch created under a `PLANNED` order automatically moves that order to
        `IN_PROGRESS` with its own version increment."
        PRD §3.2: "When every batch of an `IN_PROGRESS` order has resolved into
        `COMPLETED` or `CANCELLED` and at least one of them is `COMPLETED`, the
        order automatically transitions from `IN_PROGRESS` to `COMPLETED`"
        PRD §3.7: "House-brand orders, whose `copack_customer_id` is null, keep
        `billed_amount_cents` null."

        Design: Corner/state_machines/order_auto_progression_on_batch_lifecycle
        """
        pin_clock()
        recipe = create_approved_recipe(name="R-Auto")
        order = create_order(recipe["id"], units_planned=6000)
        assert order["status"] == "PLANNED", f"new order must be PLANNED, got {order['status']}"

        # Drive the batch through the full production chain under this order.
        batch = create_batch(order["id"], units_planned=6000)
        mid = validate_success(api.get_production_order(order["id"], PLANNER))
        assert mid["status"] == "IN_PROGRESS", (
            f"first batch must auto-advance the order to IN_PROGRESS, got {mid['status']}"
        )

        kit_batch(batch["id"])
        cook_batch(batch["id"], cooked_mass_kg=1550)
        cell = create_freezer_cell()
        cycle = book_cycle(batch["id"], cell_id=cell["id"])
        start_and_verify_cycle(cycle["id"])
        line = create_packaging_line()
        film = create_film_lot()
        run = schedule_run(line["id"], batch["id"], film["id"], units_planned=6000)
        start_run(run["id"])
        complete_run(run["id"], units_packed=6000, film_meters_consumed=2671)
        complete_batch(batch["id"])

        done = validate_success(api.get_production_order(order["id"], PLANNER))
        assert done["status"] == "COMPLETED", (
            f"order must auto-complete when its only batch completes, got {done['status']}"
        )
        assert done["billed_amount_cents"] is None, (
            "house-brand order keeps billed_amount_cents null"
        )


class TestBatchTransitions:
    def test_batch_kit_twice_rejected(self, api):
        """PRD §3.3: "Any batch transition attempted from a state where that
        transition is not defined — cooking a batch that is still `CREATED`, for
        example — is rejected with `ERR_BATCH_STATE`."
        PRD §3.3: "A `LineOperator` kits a `CREATED` batch, moving it to `KITTED`"

        Design: Corner/state_machines/batch_kit_twice_rejected
        """
        env = setup_kitted_batch()
        resp = api.kit_batch(env["batch"]["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_BATCH_STATE, expected_status=409)
        after = get_batch(env["batch"]["id"])
        assert after["status"] == "KITTED", "rejected re-kit must leave the batch KITTED"

    def test_hold_resume_restores_origin_state(self, api):
        """PRD §3.3: "the batch moves to `ON_HOLD`, the state it just occupied is
        recorded in `hold_origin_state`, the supplied text is recorded in
        `hold_reason`, and the batch's `version` increments."
        PRD §3.3: "a `QATechnician` resumes a held batch, and the batch returns to
        exactly the state recorded in `hold_origin_state`" / "A successful resume
        clears both `hold_origin_state` and `hold_reason` to null and increments
        the batch's `version`."

        Design: Corner/state_machines/hold_resume_restores_origin_state
        """
        env = setup_cooked_batch()
        held = validate_success(
            api.hold_batch(env["batch"]["id"], {"reason": "thermometer drift"}, QA_TECH),
            expected_status=200,
        )
        assert held["status"] == "ON_HOLD"
        assert held["hold_origin_state"] == "COOKED", (
            f"hold_origin_state must record COOKED, got {held['hold_origin_state']}"
        )
        assert held["hold_reason"] == "thermometer drift"

        resumed = validate_success(
            api.resume_batch(env["batch"]["id"], QA_TECH), expected_status=200
        )
        assert resumed["status"] == "COOKED", (
            f"resume must return to hold_origin_state COOKED, got {resumed['status']}"
        )
        assert resumed["hold_origin_state"] is None, "resume clears hold_origin_state"
        assert resumed["hold_reason"] is None, "resume clears hold_reason"

    def test_ccp_fail_hold_blocks_resume_until_pass(self, api):
        """PRD §3.3: "When the `hold_reason` carries the critical-control failure
        marker described in §3.6, an additional gate applies: the latest recorded
        check of the named type on this batch must be `PASS`, otherwise the resume
        is rejected with `ERR_BATCH_STATE`."
        PRD §3.6: "The batch must be in `FROZEN`, `PACKED`, `COMPLETED`, or
        `ON_HOLD` — the `ON_HOLD` admission exists so investigative re-checks can
        be recorded while a batch is held"

        Design: Corner/state_machines/ccp_fail_hold_blocks_resume_until_pass
        """
        env = setup_frozen_batch()
        record_ccp(env["batch"]["id"], "METAL_DETECTOR", False, "qa-tech-1")
        held = get_batch(env["batch"]["id"])
        assert held["status"] == "ON_HOLD"

        resp = api.resume_batch(env["batch"]["id"], QA_TECH)
        validate_error(resp, ApiErrorId.ERR_BATCH_STATE, expected_status=409)

        # Investigative re-check is recordable while ON_HOLD; a newer PASS opens the gate.
        record_ccp(env["batch"]["id"], "METAL_DETECTOR", True, "qa-tech-1")
        resumed = validate_success(
            api.resume_batch(env["batch"]["id"], QA_TECH), expected_status=200
        )
        assert resumed["status"] == "FROZEN", (
            f"resume returns to hold_origin_state FROZEN, got {resumed['status']}"
        )


class TestBatchReworkLoop:
    def test_rework_loop_hold_and_rework_phases(self, api):
        """PRD §3.3: "A `QATechnician` may place a batch on hold from `KITTED`,
        `COOKED`, `FROZEN`, or `PACKED`, supplying a `reason`"
        PRD §3.3: "A `QAManager` may send an `ON_HOLD` batch to `REWORK` —
        supplying a `reason` — which clears the hold fields and increments the
        version"

        Design: Difficulty/non_linear_state_machine/batch_rework_loop_cycle
        """
        env = setup_kitted_batch()
        held = validate_success(
            api.hold_batch(env["batch"]["id"], {"reason": "under-fill suspicion"}, QA_TECH),
            expected_status=200,
        )
        assert held["status"] == "ON_HOLD"
        assert held["hold_origin_state"] == "KITTED"

        rework = validate_success(
            api.rework_batch(env["batch"]["id"], {"reason": "re-kit with corrected sauce"}, QA_MGR),
            expected_status=200,
        )
        assert rework["status"] == "REWORK", f"expected REWORK, got {rework['status']}"
        assert rework["hold_origin_state"] is None
        assert rework["hold_reason"] is None

    def test_rework_loop_closes_back_through_kit_and_cook(self, api):
        """PRD §3.3: "the rework loop then runs through kitting again, where a
        `LineOperator` may kit a `REWORK` batch back to `KITTED` provided the
        owning order is `IN_PROGRESS` (otherwise `ERR_ORDER_NOT_OPEN`)"
        PRD §3.3: "Cooking follows: from `KITTED`, the operator records the actual
        `cooked_mass_kg` — a value that stays null until this step and must be
        positive once present — and the batch moves to `COOKED`."

        Design: Difficulty/non_linear_state_machine/batch_rework_loop_cycle
        """
        env = setup_kitted_batch()
        validate_success(
            api.hold_batch(env["batch"]["id"], {"reason": "under-fill suspicion"}, QA_TECH),
            expected_status=200,
        )
        validate_success(
            api.rework_batch(env["batch"]["id"], {"reason": "re-kit"}, QA_MGR),
            expected_status=200,
        )
        rekitted = validate_success(api.kit_batch(env["batch"]["id"], OPERATOR), expected_status=200)
        assert rekitted["status"] == "KITTED", (
            f"rework loop must close back to KITTED, got {rekitted['status']}"
        )
        cooked = validate_success(
            api.cook_batch(env["batch"]["id"], {"cooked_mass_kg": 1550}, OPERATOR),
            expected_status=200,
        )
        assert cooked["status"] == "COOKED"
        assert cooked["cooked_mass_kg"] == 1550


class TestOptimisticConcurrency:
    def test_occ_stale_version_on_batch_create(self, api):
        """PRD §2.8: "When creating a production batch under an order, the request
        must carry `expected_order_version` holding the client last-observed
        `version` of the target order. If the order's current `version` has advanced
        beyond what the client observed — another writer may legitimately have added
        a batch to the same order in the meantime — the creation is rejected with
        `ERR_STALE_VERSION` (HTTP 412)"
        PRD §3.2: "On success the batch begins in `CREATED` status, stamped with its
        `order_id`, the order's `version` increments by one"

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_batch_create
        """
        recipe = create_approved_recipe(name="R-OCC1")
        order = create_order(recipe["id"], units_planned=12000)
        observed_version = order["version"]

        first = validate_success(
            api.create_batch(
                order["id"],
                {"units_planned": 6000, "expected_order_version": observed_version},
                PLANNER,
            ),
            expected_status=201,
        )
        assert first["status"] == "CREATED"

        # The version captured before batch 1 is now stale.
        resp = api.create_batch(
            order["id"],
            {"units_planned": 6000, "expected_order_version": observed_version},
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        fresh = validate_success(api.get_production_order(order["id"], PLANNER))
        assert fresh["version"] > observed_version, (
            "the first batch creation must have advanced the order version"
        )
        second = validate_success(
            api.create_batch(
                order["id"],
                {"units_planned": 6000, "expected_order_version": fresh["version"]},
                PLANNER,
            ),
            expected_status=201,
        )
        assert second["status"] == "CREATED"
        after = validate_success(api.get_production_order(order["id"], PLANNER))
        assert after["version"] == fresh["version"] + 1, (
            "an order already IN_PROGRESS gains exactly one version increment per "
            f"added batch: {fresh['version']} -> {after['version']}"
        )

    def test_immediate_consistency_read_after_write(self, api):
        """PRD §2.11: "All such side effects apply immediately within the
        triggering request — there is no deferred or asynchronous reconciliation"
        PRD §2.5: "`version` (integer): a system-managed integer that increments
        by one with every modification to the resource"
        PRD §3.3: "Cooking follows: from `KITTED`, the operator records the actual
        `cooked_mass_kg` — a value that stays null until this step and must be
        positive once present — and the batch moves to `COOKED`."

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        recipe = create_approved_recipe(name="R-Cons")
        order = create_order(recipe["id"], units_planned=6000)
        batch = create_batch(order["id"], units_planned=6000)
        created_version = batch["version"]

        kitted = validate_success(api.kit_batch(batch["id"], OPERATOR), expected_status=200)
        assert kitted["version"] == created_version + 1, (
            "kit increments the batch version by exactly one"
        )
        cooked = validate_success(
            api.cook_batch(batch["id"], {"cooked_mass_kg": 1550}, OPERATOR),
            expected_status=200,
        )
        assert cooked["status"] == "COOKED"
        assert cooked["cooked_mass_kg"] == 1550
        assert cooked["version"] == created_version + 2, (
            "cook increments the batch version by exactly one over kit"
        )

        reread = validate_success(api.get_batch(batch["id"], PLANNER))
        assert reread["status"] == cooked["status"], "read-after-write shows the same state"
        assert reread["version"] == cooked["version"], (
            "read-after-write shows the same version (no reconciliation lag)"
        )
        assert reread["cooked_mass_kg"] == 1550
