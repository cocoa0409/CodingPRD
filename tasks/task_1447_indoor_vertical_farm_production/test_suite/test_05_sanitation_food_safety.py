"""Sanitation cycles, water-loop posture, quarantine cascades, pack gates, and
segregation of duties (PRD §3.2, §3.4, §2.10)."""
import pytest

from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_instant_equal,
    create_crop_with_active_recipe, create_loop_rack, create_growing_batch,
    mark_harvest_ready, harvest_batch, safety_release,
    set_clock, schedule_cycle, start_cycle, record_cycle_result,
    setup_packed_batch, setup_reserved_shipment, confirm_pack,
    make_quality_assurance_headers, make_sanitation_lead_headers,
    SEED_CLOCK, HARVESTER_USER_ID, QA_USER_ID,
    SANITATION_USER_1, SANITATION_USER_2,
)

FM = TEST_USERS["farm_manager_headers"]
GR = TEST_USERS["grower_headers"]
SL = TEST_USERS["sanitation_lead_headers"]


class TestWaterLoopPostureCycle:
    def _loop_with_failed_cycle(self, api):
        loop, rack, _ = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=2)
        set_clock("2026-08-08T00:00:00Z")
        cy1 = schedule_cycle(loop["id"], "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z")
        return loop, rack, cy1

    def test_loop_enters_in_progress_then_hold_on_failed_result(self, api):
        """PRD §3.4: "On start, `started_at` is stamped, the loop flips to
        `SANITATION_IN_PROGRESS`" and "A `FAILED` result holds everything: the loop
        enters `SANITATION_HOLD`, the racks stay in `SANITATION_HOLD`".

        Design: Difficulty/non_linear_state_machine/water_loop_posture_cycle_with_retest
        """
        loop, rack, cy1 = self._loop_with_failed_cycle(api)
        started = start_cycle(cy1["id"], "2026-08-10T08:00:00Z")
        assert started["cycle_status"] == "IN_PROGRESS"
        loop_mid = validate_success(api.get_water_loop(loop["id"], FM))
        assert loop_mid["posture"] == "SANITATION_IN_PROGRESS"

        record_cycle_result(cy1["id"], "FAILED", 240, "2026-08-10T10:30:00Z",
                            recorded_by=SANITATION_USER_1)
        loop_hold = validate_success(api.get_water_loop(loop["id"], FM))
        assert loop_hold["posture"] == "SANITATION_HOLD"

    def test_retest_pass_closes_loop_and_resets_schedule(self, api):
        """PRD §3.4: "A `PASSED` result returns the loop to `IN_SERVICE`, sets
        `last_passed_at` to `completed_at`, recomputes `next_sanitation_due_at` 168
        hours out, restores the held racks to `OPERATING`". PRD §3.2: the due date "is
        set 168 hours — one full week — later".

        Design: Difficulty/non_linear_state_machine/water_loop_posture_cycle_with_retest
        """
        loop, rack, cy1 = self._loop_with_failed_cycle(api)
        start_cycle(cy1["id"], "2026-08-10T08:00:00Z")
        record_cycle_result(cy1["id"], "FAILED", 240, "2026-08-10T10:30:00Z",
                            recorded_by=SANITATION_USER_1)

        cy2 = schedule_cycle(loop["id"], "2026-08-10T14:30:00Z", "2026-08-10T16:30:00Z",
                             parent_cycle_id=cy1["id"])
        start_cycle(cy2["id"], "2026-08-10T14:30:00Z")
        record_cycle_result(cy2["id"], "PASSED", 0, "2026-08-10T16:45:00Z",
                            recorded_by=SANITATION_USER_2)

        loop_final = validate_success(api.get_water_loop(loop["id"], FM))
        assert loop_final["posture"] == "IN_SERVICE"
        validate_instant_equal(loop_final["last_passed_at"], "2026-08-10T16:45:00Z")
        validate_instant_equal(loop_final["next_sanitation_due_at"], "2026-08-17T16:45:00Z")  # last pass + 168h
        rack_final = validate_success(api.get_rack(rack["id"], FM))
        assert rack_final["rack_posture"] == "OPERATING"


class TestSanitationFailureCascade:
    def _quarantined_scenario(self, api):
        """PACKED batch + PACKED shipment, then a FAILED sanitation result on the loop."""
        ctx = setup_packed_batch(packed_lb=46.0, grade_a_lb=40.0, grade_b_lb=6.0, cull_lb=3.0)
        ship_ctx = setup_reserved_shipment(ctx["batch"], ctx["crop"]["id"], reserve_lb=10.0)
        confirm_pack(ship_ctx["shipment"]["id"])
        cy2 = schedule_cycle(ctx["loop"]["id"], "2026-08-24T13:00:00Z", "2026-08-24T15:00:00Z")
        start_cycle(cy2["id"], "2026-08-24T13:00:00Z")
        record_cycle_result(cy2["id"], "FAILED", 400, "2026-08-24T15:30:00Z",
                            recorded_by=SANITATION_USER_1)
        return ctx, ship_ctx

    def test_failed_result_holds_loop_and_racks(self, api):
        """PRD §3.4: "A `FAILED` result holds everything: the loop enters
        `SANITATION_HOLD`, the racks stay in `SANITATION_HOLD`".

        Design: Difficulty/transitive_cascade/sanitation_failure_four_link_cascade
        """
        ctx, _ = self._quarantined_scenario(api)
        loop = validate_success(api.get_water_loop(ctx["loop"]["id"], FM))
        assert loop["posture"] == "SANITATION_HOLD"
        rack = validate_success(api.get_rack(ctx["rack"]["id"], FM))
        assert rack["rack_posture"] == "SANITATION_HOLD"

    def test_failed_result_quarantines_batch_and_flags_shipment(self, api):
        """PRD §3.4: "every batch occupying a tower on those racks with
        `production_status` in `SEEDED`, `GROWING`, `AT_RISK`, `HARVEST_READY`,
        `HARVESTED`, or `PACKED` has its `safety_status` driven to `QUARANTINED`
        (whether it was `PENDING` or `RELEASED`), and every shipment with a non-terminal
        line on such a batch recomputes `has_safety_block` to true."

        Design: Difficulty/transitive_cascade/sanitation_failure_four_link_cascade
        """
        ctx, ship_ctx = self._quarantined_scenario(api)
        batch = validate_success(api.get_batch(ctx["batch"]["id"], FM))
        assert batch["safety_status"] == "QUARANTINED"
        assert batch["production_status"] == "PACKED", "quarantine does not move production state"
        shipment = validate_success(api.get_shipment(ship_ctx["shipment"]["id"],
                                                     TEST_USERS["contracts_manager_headers"]))
        assert shipment["has_safety_block"] is True
        assert shipment["shipment_status"] == "PACKED", "pounds are blocked, not auto-released"


class TestPackRecencyGate:
    def test_pack_rejected_when_last_pass_over_72h_old(self, api):
        """PRD §3.4: "if no such cycle exists, or the most recent pass is strictly more
        than 72 hours old, the pack is refused with `ERR_SANITATION_RECENCY_MISSING`".

        Design: Difficulty/cross_entity_state_dependency/pack_requires_recent_passed_sanitation
        """
        crop, _ = create_crop_with_active_recipe()
        loop, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=4)
        cy1 = schedule_cycle(loop["id"], "2026-08-21T01:00:00Z", "2026-08-21T03:00:00Z")
        batch = create_growing_batch(crop["id"], [t["id"] for t in towers], seed_clock=SEED_CLOCK)
        start_cycle(cy1["id"], "2026-08-21T01:00:00Z")
        record_cycle_result(cy1["id"], "PASSED", 0, "2026-08-21T03:30:00Z",
                            recorded_by=SANITATION_USER_1)
        mark_harvest_ready(batch["id"])
        batch = harvest_batch(batch["id"], 46.0)  # harvested 2026-08-24T06:30:00Z
        safety_release(batch["id"])

        resp = api.pack_batch(batch["id"], {"packed_lb": 46.0}, GR)
        validate_error(resp, ApiErrorId.ERR_SANITATION_RECENCY_MISSING)
        # 2026-08-21T03:30 -> 2026-08-24T06:30 is 75h00m: strictly over the 72h limit.

    def test_pack_allowed_when_last_pass_exactly_72h_old(self, api):
        """PRD §3.4: "a pass exactly 72 hours old still counts."

        Design: Difficulty/cross_entity_state_dependency/pack_requires_recent_passed_sanitation
        """
        crop, _ = create_crop_with_active_recipe()
        loop, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=4)
        cy1 = schedule_cycle(loop["id"], "2026-08-21T01:00:00Z", "2026-08-21T03:00:00Z")
        batch = create_growing_batch(crop["id"], [t["id"] for t in towers], seed_clock=SEED_CLOCK)
        start_cycle(cy1["id"], "2026-08-21T01:00:00Z")
        record_cycle_result(cy1["id"], "PASSED", 0, "2026-08-21T03:30:00Z",
                            recorded_by=SANITATION_USER_1)
        mark_harvest_ready(batch["id"])
        batch = harvest_batch(batch["id"], 46.0, at_clock="2026-08-24T03:00:00Z")
        safety_release(batch["id"])

        set_clock("2026-08-24T03:30:00Z")  # exactly 72h00m after the pass
        packed = validate_success(api.pack_batch(batch["id"], {"packed_lb": 46.0}, GR))
        assert packed["production_status"] == "PACKED"


class TestPackValidationPriority:
    def test_pack_state_violation_beats_safety_pending(self, api):
        """PRD §2.10: "the server evaluates them in a fixed tier order and reports the
        first failure encountered" — tier 5 is "Lifecycle state ...
        (`ERR_INVALID_STATE_TRANSITION` ...)" and tier 7 is "Food-safety gates ...
        (`ERR_BATCH_SAFETY_PENDING` ...)".

        Design: Difficulty/priority_pair_validation_conflict/pack_state_violation_beats_safety_pending
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=4)
        batch = create_growing_batch(crop["id"], [t["id"] for t in towers], seed_clock=SEED_CLOCK)
        batch = mark_harvest_ready(batch["id"])  # HARVEST_READY (not HARVESTED) AND safety PENDING

        resp = api.pack_batch(batch["id"], {"packed_lb": 10.0}, GR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_pack_safety_pending_when_state_valid(self, api):
        """PRD §3.4: "The batch must be `HARVESTED` and safety-`RELEASED` — a `PENDING`
        batch is refused with `ERR_BATCH_SAFETY_PENDING`".

        Design: Difficulty/priority_pair_validation_conflict/pack_state_violation_beats_safety_pending
        """
        crop, _ = create_crop_with_active_recipe()
        loop, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=4)
        cy1 = schedule_cycle(loop["id"], "2026-08-22T01:00:00Z", "2026-08-22T03:00:00Z")
        batch = create_growing_batch(crop["id"], [t["id"] for t in towers], seed_clock=SEED_CLOCK)
        start_cycle(cy1["id"], "2026-08-22T01:00:00Z")
        record_cycle_result(cy1["id"], "PASSED", 0, "2026-08-22T03:30:00Z",
                            recorded_by=SANITATION_USER_1)
        mark_harvest_ready(batch["id"])
        batch = harvest_batch(batch["id"], 46.0)  # HARVESTED, safety never released

        resp = api.pack_batch(batch["id"], {"packed_lb": 46.0}, GR)
        validate_error(resp, ApiErrorId.ERR_BATCH_SAFETY_PENDING)


class TestSanitationWindowRules:
    def _loop_with_first_cycle(self, api):
        loop, _, _ = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        set_clock("2026-08-08T00:00:00Z")
        cy1 = schedule_cycle(loop["id"], "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z")
        return loop, cy1

    def test_sanitation_touch_and_buffer_violation_rejected(self, api):
        """PRD §3.4: "Windows on the same loop are compared as closed intervals and must
        not overlap any other `SCHEDULED` or `IN_PROGRESS` cycle, and they must
        additionally respect a 4-hour buffer against neighboring cycles — violations
        raise `ERR_SANITATION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/sanitation_closed_interval_with_buffer
        """
        loop, _ = self._loop_with_first_cycle(api)
        # Closed intervals share the 10:00 endpoint -> overlap.
        resp_touch = api.create_sanitation_cycle(
            {"water_loop_id": loop["id"], "scheduled_start_at": "2026-08-10T10:00:00Z",
             "scheduled_end_at": "2026-08-10T12:00:00Z"}, SL)
        validate_error(resp_touch, ApiErrorId.ERR_SANITATION_OVERLAP)
        # Only 3h59m after the prior end -> inside the 4-hour buffer.
        resp_buffer = api.create_sanitation_cycle(
            {"water_loop_id": loop["id"], "scheduled_start_at": "2026-08-10T13:59:00Z",
             "scheduled_end_at": "2026-08-10T15:59:00Z"}, SL)
        validate_error(resp_buffer, ApiErrorId.ERR_SANITATION_OVERLAP)

    def test_sanitation_exactly_four_hour_buffer_accepted(self, api):
        """PRD §3.4: cycles "must additionally respect a 4-hour buffer against
        neighboring cycles" — a start exactly 4 hours after the prior window's end
        satisfies the buffer.

        Design: Difficulty/resource_temporal_overlap/sanitation_closed_interval_with_buffer
        """
        loop, _ = self._loop_with_first_cycle(api)
        resp = api.create_sanitation_cycle(
            {"water_loop_id": loop["id"], "scheduled_start_at": "2026-08-10T14:00:00Z",
             "scheduled_end_at": "2026-08-10T16:00:00Z"}, SL)
        data = validate_success(resp, expected_status=201)
        assert data["cycle_status"] == "SCHEDULED"


class TestSanitationCycleBasics:
    def test_record_result_before_start_rejected(self, api):
        """PRD §3.4: recording a result is defined on a started cycle; a `SCHEDULED`
        cycle admits only start/cancel, so record-result is rejected as an invalid
        lifecycle transition (PRD §2.10 tier 5, `ERR_INVALID_STATE_TRANSITION`).

        Design: Corner/state_machines/sanitation_record_result_before_start_rejected
        """
        loop, _, _ = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        set_clock("2026-08-08T00:00:00Z")
        cy1 = schedule_cycle(loop["id"], "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z")

        resp = api.record_sanitation_result(cy1["id"], {"result": "PASSED", "coliform_cfu": 0},
                                            make_sanitation_lead_headers(SANITATION_USER_1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        cycle = validate_success(api.get_sanitation_cycle(cy1["id"], SL))
        assert cycle["cycle_status"] == "SCHEDULED"
        loop_after = validate_success(api.get_water_loop(loop["id"], FM))
        assert loop_after["posture"] == "IN_SERVICE"

    def test_cycle_duration_bounds_rejected(self, api):
        """PRD §3.4: "The window's duration must fall between 2 and 12 hours inclusive;
        anything shorter or longer is `ERR_CYCLE_DURATION_INVALID`."

        Design: Corner/errors/cycle_duration_bounds_rejected
        """
        loop, _, _ = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        set_clock("2026-08-08T00:00:00Z")
        resp_short = api.create_sanitation_cycle(
            {"water_loop_id": loop["id"], "scheduled_start_at": "2026-08-10T08:00:00Z",
             "scheduled_end_at": "2026-08-10T09:00:00Z"}, SL)
        validate_error(resp_short, ApiErrorId.ERR_CYCLE_DURATION_INVALID)
        resp_long = api.create_sanitation_cycle(
            {"water_loop_id": loop["id"], "scheduled_start_at": "2026-08-10T08:00:00Z",
             "scheduled_end_at": "2026-08-10T21:00:00Z"}, SL)
        validate_error(resp_long, ApiErrorId.ERR_CYCLE_DURATION_INVALID)
        resp_ok = api.create_sanitation_cycle(
            {"water_loop_id": loop["id"], "scheduled_start_at": "2026-08-10T08:00:00Z",
             "scheduled_end_at": "2026-08-10T10:00:00Z"}, SL)
        validate_success(resp_ok, expected_status=201)

    def test_cycle_start_too_early_boundary(self, api):
        """PRD §3.4: "the clock must be no more than 30 minutes before
        `scheduled_start_at` — earlier starts are `ERR_CYCLE_NOT_DUE`."

        Design: Corner/errors/cycle_start_too_early_boundary
        """
        loop, _, _ = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        set_clock("2026-08-08T00:00:00Z")
        cy1 = schedule_cycle(loop["id"], "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z")

        set_clock("2026-08-10T07:29:00Z")  # 31 minutes early
        resp = api.start_sanitation_cycle(cy1["id"], SL)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_DUE)

        set_clock("2026-08-10T07:30:00Z")  # exactly 30 minutes early
        started = validate_success(api.start_sanitation_cycle(cy1["id"], SL))
        assert started["cycle_status"] == "IN_PROGRESS"


class TestSanitationDueBoundary:
    def test_sanitation_due_only_strictly_after_due_instant(self, api):
        """PRD §3.2: "it reports `SANITATION_DUE` when `next_sanitation_due_at` is set
        and the clock has passed it" — at the exact due instant the clock has not passed
        it yet.

        Design: Corner/calculations/sanitation_due_boundary_strictly_greater
        """
        loop, _, _ = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        cy1 = schedule_cycle(loop["id"], "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z")
        start_cycle(cy1["id"], "2026-08-10T08:00:00Z")
        record_cycle_result(cy1["id"], "PASSED", 0, "2026-08-10T10:30:00Z",
                            recorded_by=SANITATION_USER_1)

        set_clock("2026-08-17T10:30:00Z")  # exactly last_passed + 168h
        loop_exact = validate_success(api.get_water_loop(loop["id"], FM))
        assert loop_exact["posture"] == "IN_SERVICE"

        set_clock("2026-08-17T10:31:00Z")  # one minute past
        loop_after = validate_success(api.get_water_loop(loop["id"], FM))
        assert loop_after["posture"] == "SANITATION_DUE"
        validate_instant_equal(loop_after["next_sanitation_due_at"], "2026-08-17T10:30:00Z")


class TestHarvestInFlightGate:
    def test_harvest_in_flight_blocks_sanitation_start(self, api):
        """PRD §3.4: "no batch on the loop's racks may be `HARVEST_READY` or
        `HARVESTED`, since starting sanitation mid-harvest would strand produce
        (`ERR_HARVEST_IN_FLIGHT`)".

        Design: Corner/errors/harvest_in_flight_blocks_sanitation_start
        """
        crop, _ = create_crop_with_active_recipe()
        loop, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        batch = create_growing_batch(crop["id"], [towers[0]["id"]], seed_clock=SEED_CLOCK)
        batch = mark_harvest_ready(batch["id"])
        assert batch["production_status"] == "HARVEST_READY"

        cy1 = schedule_cycle(loop["id"], "2026-08-22T07:00:00Z", "2026-08-22T09:00:00Z")
        set_clock("2026-08-22T07:00:00Z")
        resp = api.start_sanitation_cycle(cy1["id"], SL)
        validate_error(resp, ApiErrorId.ERR_HARVEST_IN_FLIGHT)
        cycle = validate_success(api.get_sanitation_cycle(cy1["id"], SL))
        assert cycle["cycle_status"] == "SCHEDULED"

        # The same batch harvests fine once no cycle is in progress.
        harvested = harvest_batch(batch["id"], 10.0)
        assert harvested["production_status"] == "HARVESTED"


class TestPackSafetyGates:
    def test_same_day_pack_violation_rejected(self, api):
        """PRD §3.4: "Packing must happen on the same UTC calendar date as
        `harvested_at`; crossing midnight UTC is `ERR_SAME_DAY_PACK_VIOLATION`."

        Design: Corner/errors/same_day_pack_violation_rejected
        """
        crop, _ = create_crop_with_active_recipe()
        loop, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        cy1 = schedule_cycle(loop["id"], "2026-08-24T01:00:00Z", "2026-08-24T03:00:00Z")
        batch = create_growing_batch(crop["id"], [towers[0]["id"]], seed_clock=SEED_CLOCK)
        start_cycle(cy1["id"], "2026-08-24T01:00:00Z")
        record_cycle_result(cy1["id"], "PASSED", 0, "2026-08-24T03:30:00Z",
                            recorded_by=SANITATION_USER_1)
        mark_harvest_ready(batch["id"], at_clock="2026-08-24T06:00:00Z")
        batch = harvest_batch(batch["id"], 46.0)  # harvested 2026-08-24T06:30:00Z
        safety_release(batch["id"])

        set_clock("2026-08-25T06:00:00Z")  # next UTC date; recency (26.5h) still passes
        resp = api.pack_batch(batch["id"], {"packed_lb": 46.0}, GR)
        validate_error(resp, ApiErrorId.ERR_SAME_DAY_PACK_VIOLATION)
        after = validate_success(api.get_batch(batch["id"], GR))
        assert after["production_status"] == "HARVESTED"

    def test_condemned_batch_pack_rejected(self, api):
        """PRD §3.4: "The batch must be `HARVESTED` and safety-`RELEASED`" and the
        food-safety tier covers "Batch safety release, quarantine and condemnation
        checks, the same-day pack rule, and sanitation recency" (PRD §2.10 tier 7).

        Design: Corner/errors/condemned_batch_pack_rejected
        """
        # A fresh PASSED cycle keeps the recency gate satisfied so only the
        # condemnation gate can fail.
        crop, _ = create_crop_with_active_recipe()
        loop, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        cy1 = schedule_cycle(loop["id"], "2026-08-22T01:00:00Z", "2026-08-22T03:00:00Z")
        batch = create_growing_batch(crop["id"], [towers[0]["id"]], seed_clock=SEED_CLOCK)
        start_cycle(cy1["id"], "2026-08-22T01:00:00Z")
        record_cycle_result(cy1["id"], "PASSED", 0, "2026-08-22T03:30:00Z",
                            recorded_by=SANITATION_USER_1)
        mark_harvest_ready(batch["id"])
        batch = harvest_batch(batch["id"], 46.0)
        condemned = safety_release(batch["id"], decision="CONDEMNED", lab_ref="LAB-E8")
        assert condemned["safety_status"] == "CONDEMNED"

        resp = api.pack_batch(batch["id"], {"packed_lb": 46.0}, GR)
        validate_error(resp, ApiErrorId.ERR_BATCH_CONDEMNED)
        after = validate_success(api.get_batch(batch["id"], GR))
        assert after["production_status"] == "HARVESTED"
        assert after["packed_lb"] == pytest.approx(0.0)


class TestSegregationOfDuties:
    def test_sod_harvester_cannot_release_own_batch(self, api):
        """PRD §3.4: "Segregation of duties forbids the harvesting user from releasing
        their own harvest: when `harvested_by_user_id` is set, a matching `X-User-ID` is
        rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/errors/sod_harvester_cannot_release_own_batch
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        batch = create_growing_batch(crop["id"], [towers[0]["id"]], seed_clock=SEED_CLOCK)
        mark_harvest_ready(batch["id"])
        batch = harvest_batch(batch["id"], 46.0, harvester=HARVESTER_USER_ID)

        resp = api.safety_release_batch(
            batch["id"], {"decision": "RELEASED", "lab_ref": "LAB-S1"},
            make_quality_assurance_headers(HARVESTER_USER_ID))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        released = safety_release(batch["id"], lab_ref="LAB-S1", qa_user=QA_USER_ID)
        assert released["safety_status"] == "RELEASED"

    def test_sod_sanitation_retest_same_user_rejected(self, api):
        """PRD §3.4: "When the cycle is a retest — `parent_cycle_id` set — segregation
        of duties forbids the same user who recorded the parent cycle's result from
        recording this one, on pain of `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/errors/sod_sanitation_retest_same_user_rejected
        """
        loop, _, _ = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        cy1 = schedule_cycle(loop["id"], "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z")
        start_cycle(cy1["id"], "2026-08-10T08:00:00Z")
        record_cycle_result(cy1["id"], "FAILED", 400, "2026-08-10T10:30:00Z",
                            recorded_by=SANITATION_USER_1)

        cy2 = schedule_cycle(loop["id"], "2026-08-10T14:30:00Z", "2026-08-10T16:30:00Z",
                             parent_cycle_id=cy1["id"])
        start_cycle(cy2["id"], "2026-08-10T14:30:00Z")

        set_clock("2026-08-10T16:45:00Z")
        resp = api.record_sanitation_result(
            cy2["id"], {"result": "PASSED", "coliform_cfu": 0},
            make_sanitation_lead_headers(SANITATION_USER_1))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        cycle_mid = validate_success(api.get_sanitation_cycle(cy2["id"], SL))
        assert cycle_mid["cycle_status"] == "IN_PROGRESS"

        passed = record_cycle_result(cy2["id"], "PASSED", 0, "2026-08-10T16:45:00Z",
                                     recorded_by=SANITATION_USER_2)
        assert passed["cycle_status"] == "PASSED"


class TestRackReturnToService:
    def test_rack_return_blocked_during_sanitation(self, api):
        """PRD §3.2: "Returning a rack to service is gated on its water loop: the loop's
        posture must be `IN_SERVICE` or `SANITATION_DUE`, and a loop caught in sanitation
        work answers with `ERR_WATER_LOOP_SANITATION_HOLD`."

        Design: Corner/errors/rack_return_to_service_blocked_during_sanitation
        """
        loop, rack, _ = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        validate_success(api.set_rack_out_of_service(rack["id"], FM))
        set_clock("2026-08-08T00:00:00Z")
        cy1 = schedule_cycle(loop["id"], "2026-08-08T01:00:00Z", "2026-08-08T03:00:00Z")
        start_cycle(cy1["id"], "2026-08-08T01:00:00Z")

        resp = api.return_rack_to_service(rack["id"], FM)
        validate_error(resp, ApiErrorId.ERR_WATER_LOOP_SANITATION_HOLD)
        rack_after = validate_success(api.get_rack(rack["id"], FM))
        assert rack_after["rack_posture"] == "OUT_OF_SERVICE"


class TestQuarantineRecoveryPath:
    def test_pending_after_retest_pass_blocks_ship_until_rerelease(self, api):
        """PRD §3.4: a PASSED retest "moves every quarantined batch on those racks back
        from `QUARANTINED` to `PENDING` — a fresh release decision is required before any
        pack or ship." PRD §3.5: ship requires "every line's batch is safety-`RELEASED`
        (otherwise `ERR_BATCH_SAFETY_PENDING`, `ERR_BATCH_QUARANTINED`, or
        `ERR_BATCH_CONDEMNED` according to the batch's state)".

        Design: Corner/errors/sanitation_pending_after_retest_pass_blocks_ship
        """
        ctx = setup_packed_batch(packed_lb=46.0, tower_count=1)
        ship_ctx = setup_reserved_shipment(ctx["batch"], ctx["crop"]["id"], reserve_lb=10.0)
        confirm_pack(ship_ctx["shipment"]["id"])

        cy2 = schedule_cycle(ctx["loop"]["id"], "2026-08-24T09:00:00Z", "2026-08-24T11:00:00Z")
        start_cycle(cy2["id"], "2026-08-24T09:00:00Z")
        record_cycle_result(cy2["id"], "FAILED", 900, "2026-08-24T11:30:00Z",
                            recorded_by=SANITATION_USER_1)
        cy3 = schedule_cycle(ctx["loop"]["id"], "2026-08-24T15:00:00Z", "2026-08-24T17:00:00Z",
                             parent_cycle_id=cy2["id"])
        start_cycle(cy3["id"], "2026-08-24T15:00:00Z")
        record_cycle_result(cy3["id"], "PASSED", 0, "2026-08-24T17:30:00Z",
                            recorded_by=SANITATION_USER_2)

        set_clock("2026-08-24T18:00:00Z")  # inside the 08:00-20:00 dock window
        CM = TEST_USERS["contracts_manager_headers"]
        resp = api.ship_shipment(ship_ctx["shipment"]["id"], CM)
        validate_error(resp, ApiErrorId.ERR_BATCH_SAFETY_PENDING)

        batch = validate_success(api.get_batch(ctx["batch"]["id"], GR))
        assert batch["safety_status"] == "PENDING", "retest pass lifts quarantine only to PENDING"
        shipment_mid = validate_success(api.get_shipment(ship_ctx["shipment"]["id"], CM))
        assert shipment_mid["has_safety_block"] is True

        safety_release(ctx["batch"]["id"], lab_ref="LAB-E12", qa_user=QA_USER_ID)
        shipped = validate_success(api.ship_shipment(ship_ctx["shipment"]["id"], CM))
        assert shipped["shipment_status"] == "SHIPPED"
