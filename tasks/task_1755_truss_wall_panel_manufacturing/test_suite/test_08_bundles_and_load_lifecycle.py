"""Bundle map constraints and the load return/reschedule/re-dispatch loop."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_load,
    make_bundle,
    book_slot,
    set_clock,
    create_bundle_payload,
    setup_load_with_light_crane,
    setup_load_dispatched,
    setup_production_preamble,
    load_fresh,
    bundle_fresh,
    batch_fresh,
    job_fresh,
)

PM = TEST_USERS["plant_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
SC = TEST_USERS["shipping_coordinator_headers"]


class TestBundleWeightExactCapacity:
    def test_weight_equal_to_capacity_accepted(self, api):
        """PRD §3.7: "`weight_lbs` must not exceed the `capacity_lbs` of the crane on
        the load's earliest-start `BOOKED` or `COMPLETED` `LOAD_PICK` slot — equality
        is permitted, strictly greater is rejected with `ERR_BUNDLE_OVERWEIGHT`
        (HTTP 422)" and "Each accepted bundle is born `PACKED`, and the load's
        `actual_total_weight_lbs` is recomputed."

        Design: Difficulty/boundary_precision_check/bundle_weight_exact_capacity
        """
        ns = setup_load_with_light_crane()
        bundle = make_bundle(ns.load["id"], ns.bat1["id"], 1, 4000)
        assert bundle["status"] == "PACKED", "weight == capacity_lbs (4000) is permitted"
        assert load_fresh(ns.load["id"])["actual_total_weight_lbs"] == pytest.approx(4000)

    def test_weight_one_over_capacity_rejected(self, api):
        """PRD §3.7: "`weight_lbs` must not exceed the `capacity_lbs` of the crane on
        the load's earliest-start `BOOKED` or `COMPLETED` `LOAD_PICK` slot — equality
        is permitted, strictly greater is rejected with `ERR_BUNDLE_OVERWEIGHT`
        (HTTP 422)".

        Design: Difficulty/boundary_precision_check/bundle_weight_exact_capacity
        """
        ns = setup_load_with_light_crane()
        resp = api.create_bundle(ns.load["id"],
                                 create_bundle_payload(ns.bat1["id"], 1, 4001), SC)
        validate_error(resp, ApiErrorId.ERR_BUNDLE_OVERWEIGHT)
        data, meta = validate_paginated(
            api.list_bundles(PM, params={"delivery_load_id": ns.load["id"]}))
        assert meta["total_count"] == 0, "the rejected bundle persists nothing"


class TestLoadReturnRescheduleCycle:
    def test_return_reverts_then_reschedule_updates_date(self, api):
        """PRD §3.7: "A return — `DISPATCHED` to `RETURNED` — moves every `LOADED`
        bundle to `RETURNED`, returns every referenced `LOADED` batch to `STAGED`,
        and recomputes the job's posture to `AT_RISK`." and "A returned load is
        rescheduled by moving `RETURNED` to `RESCHEDULED` with a `rescheduled_date`
        in the request" and "the load's `scheduled_date` is updated and posture
        recomputed."

        Design: Difficulty/non_linear_state_machine/load_return_reschedule_cycle
        """
        ns = setup_load_dispatched(job_name="Return Job")
        returned = validate_success(api.transition_load(ns.load["id"], {"to_state": "RETURNED"}, SC))
        assert returned["status"] == "RETURNED"
        assert bundle_fresh(ns.bundle["id"])["status"] == "RETURNED"
        assert batch_fresh(ns.bat1["id"])["status"] == "STAGED", "batch reverts from LOADED"
        assert job_fresh(ns.job["id"])["posture"] == "AT_RISK"

        rescheduled = validate_success(api.transition_load(
            ns.load["id"], {"to_state": "RESCHEDULED",
                            "rescheduled_date": "2026-08-22T00:00:00Z"}, SC))
        assert rescheduled["status"] == "RESCHEDULED"
        assert rescheduled["scheduled_date"].startswith("2026-08-22")
        assert job_fresh(ns.job["id"])["posture"] == "GREEN", \
            "no RETURNED load remains after rescheduling"

    def test_redispatch_stamps_latest_dispatch_and_readvances(self, api):
        """PRD §3.7: "Re-dispatch from `RESCHEDULED` re-runs the same temporal and
        fiscal guards as a first dispatch, stamps `last_dispatched_at` anew —
        extending the storage window, since it always reflects the latest dispatch —
        moves bundles in `RETURNED` back to `LOADED`, and moves referenced batches
        currently `STAGED` back to `LOADED`." PRD §3.2: "the moment its first delivery
        load reaches `DISPATCHED`, it moves `IN_PRODUCTION` to `SHIPPING`".

        Design: Difficulty/non_linear_state_machine/load_return_reschedule_cycle
        """
        ns = setup_load_dispatched(job_name="Return Job")
        validate_success(api.transition_load(ns.load["id"], {"to_state": "RETURNED"}, SC))
        validate_success(api.transition_load(
            ns.load["id"], {"to_state": "RESCHEDULED",
                            "rescheduled_date": "2026-08-22T00:00:00Z"}, SC))
        set_clock("2026-08-22T00:00:00Z")
        redispatched = validate_success(api.transition_load(ns.load["id"], {"to_state": "DISPATCHED"}, SC))
        assert redispatched["status"] == "DISPATCHED"
        assert redispatched["last_dispatched_at"].startswith("2026-08-22"), \
            "last_dispatched_at always reflects the latest dispatch"
        assert bundle_fresh(ns.bundle["id"])["status"] == "LOADED"
        assert batch_fresh(ns.bat1["id"])["status"] == "LOADED"
        assert job_fresh(ns.job["id"])["status"] == "SHIPPING"


class TestBundleReferentialGuards:
    def test_bundle_without_load_pick_slot_rejected(self, api):
        """PRD §3.7: "The load must be in `PLANNED`, `STAGED`, or `LOADING`; the
        referenced batch must be `STAGED` and belong to the same job as the load; and
        at least one `LOAD_PICK` slot in `BOOKED` or `COMPLETED` must exist for the
        load, since it anchors the weight check — a violation of any of these three
        referential conditions is rejected with `ERR_BUNDLE_JOB_MISMATCH` (HTTP 422)."

        Design: Corner/errors/bundle_without_load_pick_slot_rejected
        """
        ns = setup_production_preamble(job_name="NoSlot Job")
        load = make_load(ns.job["id"], planned_weight_est_lbs=5000)  # no LOAD_PICK slot
        resp = api.create_bundle(load["id"], create_bundle_payload(ns.bat1["id"], 1, 5000), SC)
        validate_error(resp, ApiErrorId.ERR_BUNDLE_JOB_MISMATCH)
        data, meta = validate_paginated(
            api.list_bundles(PM, params={"delivery_load_id": load["id"]}))
        assert meta["total_count"] == 0

    def test_stack_position_conflict_within_load(self, api):
        """PRD §3.7: "`stack_position`, the load-order position where 1 is the floor,
        must be unique among the load's non-`SUPERSEDED` bundles, else
        `ERR_STACK_POSITION_CONFLICT` (HTTP 409)."

        Design: Corner/errors/stack_position_conflict_within_load
        """
        ns = setup_production_preamble(job_name="Stack Job")
        load = make_load(ns.job["id"], planned_weight_est_lbs=5000)
        book_slot(ns.crane["id"], "LOAD_PICK", "2026-08-20T09:00:00Z", "2026-08-20T10:00:00Z",
                  delivery_load_id=load["id"])
        make_bundle(load["id"], ns.bat1["id"], 1, 5000)
        resp = api.create_bundle(load["id"], create_bundle_payload(ns.bat1["id"], 1, 4000), SC)
        validate_error(resp, ApiErrorId.ERR_STACK_POSITION_CONFLICT)
        b2 = make_bundle(load["id"], ns.bat1["id"], 2, 4000)
        assert b2["status"] == "PACKED"
        assert load_fresh(load["id"])["actual_total_weight_lbs"] == pytest.approx(9000)
