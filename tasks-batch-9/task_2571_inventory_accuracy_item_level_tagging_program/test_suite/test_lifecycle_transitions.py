"""
Declared transitions, refused transitions and terminal states across the tag
batch, the count task, the investigation revision loop, the shrink period and
the physical inventory.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_COUNT_SCHEDULE_NOT_ACTIVE,
    ERR_COUNT_TASK_INVALID_STATE,
    ERR_PHYSICAL_INVENTORY_INVALID_STATE,
    ERR_SHRINK_PERIOD_INVALID_STATE,
    ERR_TAG_BATCH_INVALID_STATE,
)
from test_helpers.assertions import assert_pct, assert_tag_batch_counters_cleared
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    ANALYST_2,
    CONTROLLER,
    SUPERVISOR,
    USER_ANALYST_1,
    USER_ANALYST_2,
    make_store_ops_headers,
    make_vendor_rep_headers,
)


class TestTagBatchBirthAndFreeze:
    def test_a_new_batch_is_born_in_draft_with_nothing_frozen(self, api):
        """
        The draft state holds no sample and no outcome.

        "A batch is born in `DRAFT` with `rework_round` at 0, with `sampled_units`,
        `readable_units`, `duplicate_epc_count`, `unencoded_units` and
        `read_rate_bps` all 0, and with `verification_outcome` null. Nothing is
        frozen yet."

        Design: Corner/state_machines/tag_batch_created_starts_in_draft
        """
        world = fx.apparel_reference_world(api, baseline=100)
        vendor_headers = make_vendor_rep_headers(world["vendor_id"])

        created = validate_success(
            api.create_tag_batch(
                f.tag_batch_payload(
                    world["vendor_id"],
                    world["item_id"],
                    world["store_id"],
                    quantity_encoded=1000,
                ),
                vendor_headers,
            ),
            201,
        )
        assert created["status"] == "DRAFT"
        assert created["rework_round"] == 0
        assert created["verification_outcome"] is None
        assert_tag_batch_counters_cleared(created)

        rows, meta = validate_paginated(
            api.list_tag_batches(ADMIN, {"vendor_id": world["vendor_id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "DRAFT"

    def test_encoding_freezes_the_sample_obligation_from_the_current_band(self, api):
        """
        Encoding is the moment the obligation is frozen.

        "Encoding is also the moment the receiving store's obligation is frozen.
        `required_sample_units` is set to the batch's `quantity_encoded` multiplied
        by the vendor's `required_verification_sample_pct` as that percentage stands
        at this instant, divided by 100, and rounded **up** to a whole number."

        Design: Corner/state_machines/tag_batch_encode_from_draft_freezes_sample_units
        """
        world = fx.apparel_reference_world(api, baseline=100)
        vendor_headers = make_vendor_rep_headers(world["vendor_id"])
        batch = validate_success(
            api.create_tag_batch(
                f.tag_batch_payload(
                    world["vendor_id"],
                    world["item_id"],
                    world["store_id"],
                    quantity_encoded=1000,
                ),
                vendor_headers,
            ),
            201,
        )
        assert batch["version"] == 1

        encoded = validate_success(
            api.encode_tag_batch(batch["id"], f.encode_payload(), vendor_headers)
        )
        assert encoded["status"] == "ENCODED"
        assert encoded["required_sample_units"] == 50
        assert encoded["encoding_scheme"] == "SGTIN_96"
        assert encoded["epc_prefix"] == "0614141"
        assert encoded["version"] == 2


class TestTagBatchRefusedTransitions:
    def test_verifying_a_draft_batch_reports_the_state_not_the_sample_size(self, api):
        """
        The state gate is the first of the three verification gates.

        "Three gates apply in order. The batch must be in `RECEIVED`.
        `sampled_units` must be at least the `required_sample_units` frozen at
        encoding, otherwise the submission is rejected with
        `ERR_SAMPLE_BELOW_REQUIRED` (HTTP 422)."

        Design: Corner/state_machines/tag_batch_verify_from_draft_rejected_before_sample_checks
        """
        world = fx.apparel_reference_world(api, baseline=100)
        vendor_headers = make_vendor_rep_headers(world["vendor_id"])
        store_headers = make_store_ops_headers(world["store_id"])
        batch = validate_success(
            api.create_tag_batch(
                f.tag_batch_payload(
                    world["vendor_id"],
                    world["item_id"],
                    world["store_id"],
                    quantity_encoded=1000,
                ),
                vendor_headers,
            ),
            201,
        )

        validate_error(
            api.verify_tag_batch(batch["id"], f.verify_payload(), store_headers),
            ERR_TAG_BATCH_INVALID_STATE,
            409,
        )

        stalled = fx.read_tag_batch(api, batch["id"])
        assert stalled["status"] == "DRAFT"
        assert stalled["sampled_units"] == 0
        assert stalled["read_rate_bps"] == 0
        assert stalled["verification_outcome"] is None

        vendor = fx.read_vendor(api, world["vendor_id"])
        assert vendor["tag_compliance_score_bps"] == 10000

    def test_a_passed_batch_is_terminal_and_refuses_both_futures(self, api):
        """
        No transition leaves a terminal state.

        "Attempting to encode a batch that is not in `DRAFT` — or, on the rework
        path described below, not in `VERIFICATION_FAILED` — is rejected with
        `ERR_TAG_BATCH_INVALID_STATE`, as is any transition attempted out of the two
        terminal states `VERIFIED_PASS` and `SCRAPPED`."

        Design: Corner/state_machines/tag_batch_verified_pass_is_terminal_and_rejects_rework
        """
        world = fx.encoded_tag_batch_world(api, quantity=1000, baseline=100)

        passed = validate_success(
            api.verify_tag_batch(
                world["batch_id"],
                f.verify_payload(sampled_units=50, readable_units=50),
                world["store_headers"],
            )
        )
        assert passed["status"] == "VERIFIED_PASS"
        assert passed["read_rate_bps"] == 10000
        assert passed["verification_outcome"] == "PASS"
        assert fx.read_vendor(api, world["vendor_id"])["tag_compliance_score_bps"] == 10000

        validate_error(
            api.rework_tag_batch(world["batch_id"], SUPERVISOR),
            ERR_TAG_BATCH_INVALID_STATE,
            409,
        )
        after_rework = fx.read_tag_batch(api, world["batch_id"])
        assert after_rework["status"] == "VERIFIED_PASS"
        assert after_rework["rework_round"] == 0

        validate_error(
            api.scrap_tag_batch(world["batch_id"], SUPERVISOR),
            ERR_TAG_BATCH_INVALID_STATE,
            409,
        )
        assert fx.read_tag_batch(api, world["batch_id"])["status"] == "VERIFIED_PASS"

    def test_a_repeated_receive_is_refused_and_writes_nothing(self, api):
        """
        Receipt is a single declared step out of `ENCODED`.

        "Receipt is a separate step from verification. `StoreOps` at the destination
        store — or an `InventorySupervisor` — acknowledges physical arrival, moving
        the batch from `ENCODED` to `RECEIVED`."

        Design: Corner/state_machines/tag_batch_second_receive_rejected_as_repeat_trigger
        """
        world = fx.encoded_tag_batch_world(api, quantity=1000, baseline=100)
        assert world["received_batch"]["status"] == "RECEIVED"
        assert world["received_batch"]["version"] == 3

        validate_error(
            api.receive_tag_batch(world["batch_id"], world["store_headers"]),
            ERR_TAG_BATCH_INVALID_STATE,
            409,
        )

        unchanged = fx.read_tag_batch(api, world["batch_id"])
        assert unchanged["status"] == "RECEIVED"
        assert unchanged["version"] == 3


class TestCountTaskStartSnapshot:
    def test_the_start_freezes_a_category_scoped_denominator(self, api):
        """
        The coverage denominator is captured once, at the start.

        "The start is also the only moment the coverage denominator is captured:
        `in_scope_position_count` is snapshotted as the number of stock positions at
        the task's store whose SKU belongs to the task's category. That snapshot is
        **not** refreshed if positions appear later inside the window."

        Design: Corner/state_machines/count_task_start_snapshots_in_scope_position_count
        """
        world = fx.apparel_two_item_world(api, baseline_a=100, baseline_b=50)
        home = fx.create_category(api, f.home_category_payload())
        pan = fx.create_item(api, f.pan_item_payload(home["id"], world["vendor_id"]))
        fx.create_position(api, world["store_id"], pan["id"], baseline=40)

        schedule = fx.create_schedule(
            api, world["store_id"], world["category_id"], first_due_date="2026-08-01"
        )
        task = fx.create_task(api, schedule["id"])
        assert task["in_scope_position_count"] == 0

        started = validate_success(api.start_count_task(task["id"], ANALYST))
        assert started["status"] == "IN_PROGRESS"
        assert started["in_scope_position_count"] == 2

        third = fx.create_item(
            api,
            f.item_payload(
                world["category_id"], world["vendor_id"], sku="TEE-003", description="Tank"
            ),
        )
        fx.create_position(api, world["store_id"], third["id"], baseline=25)

        assert fx.read_task(api, task["id"])["in_scope_position_count"] == 2

        rows, meta = validate_paginated(
            api.list_stock_positions(ANALYST, {"store_id": world["store_id"]})
        )
        assert meta["total_count"] == 4


class TestCountTaskRefusedTransitions:
    def test_voiding_a_counted_task_is_refused_and_keeps_its_lines(self, api):
        """
        Void is declared only from the two pre-count states.

        "An `InventorySupervisor` or `ShrinkController` may abandon a task that will
        never be completed, optionally with a `note`, from either `SCHEDULED` or
        `IN_PROGRESS`, landing it in the terminal `VOIDED`. Every counted line on the
        task is deleted and `counted_line_count` resets to 0."

        Design: Corner/state_machines/count_task_void_from_counted_rejected
        """
        world = fx.apparel_reference_world(api, baseline=100)
        fx.with_started_task(api, world)
        fx.add_line(api, world["task_id"], world["item_id"], 100)
        submitted = fx.submit_task(api, world["task_id"])
        assert submitted["status"] == "COUNTED"
        assert_pct(submitted["coverage_pct"], 100.00)
        assert submitted["counted_line_count"] == 1
        assert submitted["variance_line_count"] == 0
        assert submitted["total_variance_value_cents"] == 0

        validate_error(
            api.void_count_task(world["task_id"], SUPERVISOR),
            ERR_COUNT_TASK_INVALID_STATE,
            409,
        )

        rows, meta = validate_paginated(
            api.list_count_lines(ANALYST, {"count_task_id": world["task_id"]})
        )
        assert meta["total_count"] == 1
        assert fx.read_task(api, world["task_id"])["status"] == "COUNTED"

    def test_a_paused_schedule_refuses_to_authorise_a_new_task(self, api):
        """
        The backing schedule's activity is a precondition of task creation.

        "Creating a task runs a specific sequence of checks. The backing schedule
        must be `ACTIVE`, otherwise `ERR_COUNT_SCHEDULE_NOT_ACTIVE`."

        Design: Corner/state_machines/count_task_create_on_paused_schedule_rejected
        """
        category = fx.create_category(api, f.apparel_category_payload())
        store = fx.create_store(api, f.store_payload())
        schedule = fx.create_schedule(
            api, store["id"], category["id"], first_due_date="2026-08-01"
        )
        paused = validate_success(api.pause_count_schedule(schedule["id"], SUPERVISOR))
        assert paused["status"] == "PAUSED"

        validate_error(
            api.create_count_task(f.count_task_payload(schedule["id"]), ANALYST),
            ERR_COUNT_SCHEDULE_NOT_ACTIVE,
            409,
        )

        rows, meta = validate_paginated(
            api.list_count_tasks(ANALYST, {"count_schedule_id": schedule["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

        resumed = validate_success(api.resume_count_schedule(schedule["id"], SUPERVISOR))
        assert resumed["status"] == "ACTIVE"

        accepted = validate_success(
            api.create_count_task(f.count_task_payload(schedule["id"]), ANALYST), 201
        )
        assert accepted["status"] == "SCHEDULED"
        assert accepted["store_id"] == store["id"]
        assert accepted["category_id"] == category["id"]


class TestInvestigationRevisionLoop:
    def test_a_second_proposal_supersedes_the_first_and_advances_the_round(self, api):
        """
        A self-loop on `CAUSE_PROPOSED` overwrites the standing proposal.

        "A proposal is accepted from `IN_REVIEW`, moving the investigation to
        `CAUSE_PROPOSED`, and is also accepted from `CAUSE_PROPOSED` itself, in which
        case the investigation stays in `CAUSE_PROPOSED` and the earlier proposal is
        superseded. Both branches behave identically in every other respect:
        `proposed_root_cause` and `evidence_note` are overwritten by the new
        submission, `proposed_by_user_id` is set to the acting `X-User-ID`, and
        `proposal_round` is incremented by 1."

        Design: Corner/state_machines/investigation_propose_cause_supersede_increments_proposal_round
        """
        world = fx.counted_variance_world(api, counted_units=105)
        first = fx.drive_to_cause_proposed(
            api, world["investigation_id"], "PROCESS_ERROR"
        )
        assert first["status"] == "CAUSE_PROPOSED"
        assert first["proposal_round"] == 1
        assert first["proposed_root_cause"] == "PROCESS_ERROR"
        assert first["proposed_by_user_id"] == USER_ANALYST_1

        second = validate_success(
            api.propose_cause(
                world["investigation_id"],
                f.propose_cause_payload(
                    "THEFT",
                    first["version"],
                    evidence_note="CCTV review contradicts the receiving theory",
                ),
                ANALYST_2,
            )
        )
        assert second["status"] == "CAUSE_PROPOSED"
        assert second["proposal_round"] == 2
        assert second["proposed_root_cause"] == "THEFT"
        assert (
            second["evidence_note"] == "CCTV review contradicts the receiving theory"
        )
        assert second["proposed_by_user_id"] == USER_ANALYST_2
        assert second["approved_root_cause"] is None
        assert second["approved_by_user_id"] is None
        assert second["version"] == first["version"] + 1

        attribution = fx.read_attribution(api, world["shrink_period_id"])
        assert attribution["unresolved_cents"] == 6633
        assert attribution["theft_cents"] == 0
        assert attribution["process_error_cents"] == 0

    def test_a_return_clears_the_proposal_but_not_the_counter(self, api):
        """
        The round counter records proposals made, not proposals standing.

        "On success `proposed_root_cause` is reset to null and `proposed_by_user_id`
        is reset to null, but `proposal_round` is **not** decremented — the counter
        records how many proposals have been made, not how many currently stand.
        This edge closes the revision loop from `IN_REVIEW` through `CAUSE_PROPOSED`
        back to `IN_REVIEW`."

        Design: Corner/state_machines/investigation_return_clears_proposal_and_keeps_proposal_round
        """
        world = fx.counted_variance_world(api, counted_units=105)
        proposed = fx.drive_to_cause_proposed(api, world["investigation_id"], "THEFT")
        assert proposed["proposal_round"] == 1

        returned = validate_success(
            api.return_investigation(world["investigation_id"], SUPERVISOR)
        )
        assert returned["status"] == "IN_REVIEW"
        assert returned["proposed_root_cause"] is None
        assert returned["proposed_by_user_id"] is None
        assert returned["proposal_round"] == 1
        assert returned["assigned_investigator_id"] == USER_ANALYST_1

        attribution = fx.read_attribution(api, world["shrink_period_id"])
        assert attribution["unresolved_cents"] == 6633
        assert attribution["theft_cents"] == 0

        again = validate_success(
            api.propose_cause(
                world["investigation_id"],
                f.propose_cause_payload("DAMAGE", returned["version"]),
                ANALYST,
            )
        )
        assert again["status"] == "CAUSE_PROPOSED"
        assert again["proposal_round"] == 2
        assert again["proposed_root_cause"] == "DAMAGE"


class TestShrinkPeriodClosureOrder:
    def test_a_final_close_may_not_skip_the_provisional_one(self, api):
        """
        The closure ladder is walked one rung at a time.

        "A period runs `OPEN` to `PROVISIONAL_CLOSED` to `FINAL_CLOSED`, with a
        reopen loop back from `PROVISIONAL_CLOSED` to `OPEN`. Every one of these
        steps belongs to the `ShrinkController` alone, and any of them attempted from
        the wrong status is rejected with `ERR_SHRINK_PERIOD_INVALID_STATE`."

        Design: Corner/state_machines/shrink_period_final_close_from_open_rejected
        """
        store = fx.create_store(api, f.store_payload())
        period = fx.create_shrink_period(api, store["id"])
        assert period["status"] == "OPEN"

        validate_error(
            api.final_close_shrink_period(period["id"], CONTROLLER),
            ERR_SHRINK_PERIOD_INVALID_STATE,
            409,
        )

        stalled = validate_success(api.get_shrink_period(period["id"], CONTROLLER))
        assert stalled["status"] == "OPEN"
        assert stalled["final_total_shrink_cents"] == 0
        assert stalled["shrink_rate_bps"] == 0

        provisional = validate_success(
            api.provisional_close_shrink_period(period["id"], CONTROLLER)
        )
        assert provisional["status"] == "PROVISIONAL_CLOSED"

        final = validate_success(
            api.final_close_shrink_period(period["id"], CONTROLLER)
        )
        assert final["status"] == "FINAL_CLOSED"
        assert final["unresolved_cents"] == 0


class TestPhysicalInventoryAbandon:
    def test_abandoning_a_started_inventory_is_refused(self, api):
        """
        Abandonment is declared only out of `PLANNED`.

        "Separately, a `ShrinkController` or `SystemAdmin` may abandon a `PLANNED`
        inventory, optionally with a `note`, moving it to the terminal `ABANDONED`;
        that releases the store's blackout interval so a new inventory may be
        scheduled over the same dates."

        Design: Corner/state_machines/physical_inventory_abandon_from_counting_rejected
        """
        world = fx.physical_inventory_world(api, with_period=False)
        started = validate_success(
            api.start_physical_inventory(world["physical_inventory_id"], CONTROLLER)
        )
        assert started["status"] == "COUNTING"

        validate_error(
            api.abandon_physical_inventory(world["physical_inventory_id"], CONTROLLER),
            ERR_PHYSICAL_INVENTORY_INVALID_STATE,
            409,
        )

        unchanged = fx.read_physical_inventory(api, world["physical_inventory_id"])
        assert unchanged["status"] == "COUNTING"
        assert unchanged["certified_at"] is None
