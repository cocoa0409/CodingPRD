"""Cleaning pipeline, dwell rules, segregation of duty, equipment serviceability."""
from test_helpers import (
    HK,
    SUP,
    ApiErrorId,
    accept_offer,
    add_equipment_asset,
    add_on_shift_transporter,
    advance_cleaning,
    advance_cleaning_ok,
    assert_cleaning_task,
    create_dispatch_offer,
    create_transport_request,
    find_cleaning_task,
    get_asset,
    list_cleaning_tasks,
    make_supervisor_headers,
    set_clock,
    setup_cleaning_in_progress,
    setup_completed_trip,
    setup_transport_site,
    setup_trip_in_transit,
    trip_event_ok,
    validate_error,
    validate_success,
)


class TestEquipmentCleaningFullCycle:
    def test_standard_trip_cycles_asset_back_to_available(self, api):
        """PRD §3.5: "the assigned asset, if any, moves to `AWAITING_CLEANING`,
        and when the trip ran under any isolation precaution its
        `isolation_contaminated` flag is set true. The asset's entry into
        `AWAITING_CLEANING` creates a `CleaningTask` in `PENDING` whose
        `task_type` is `DEEP` for isolation trips and `STANDARD` otherwise,
        linked to both the asset and the request."
        PRD §3.7: "Starting stamps `started_at` and moves the asset to
        `IN_CLEANING`."
        PRD §3.7: "A successful verification stamps `verified_at`, records
        `verified_by`, moves the task to `VERIFIED`, and cascades to the asset
        — back to `AVAILABLE`, `isolation_contaminated` cleared, and
        auto-dispatch evaluation run for the freed asset."

        Design: Difficulty/non_linear_state_machine/equipment_cleaning_full_cycle
        """
        world = setup_trip_in_transit(equipment="WHEELCHAIR", patient_ref="P1")
        t1, asset, r1 = (world["transporter"], world["asset"],
                         world["request"])
        assert get_asset(asset["id"])["status"] == "IN_USE", (
            "PICKUP moved the reserved asset to IN_USE")

        trip_event_ok(r1["id"], "COMPLETE", transporter_id=t1["id"])
        assert get_asset(asset["id"])["status"] == "AWAITING_CLEANING"
        task = find_cleaning_task(equipment_asset_id=asset["id"])
        assert_cleaning_task(task)
        assert task["task_type"] == "STANDARD"
        assert task["status"] == "PENDING"

        advance_cleaning_ok(task["id"], "IN_PROGRESS", HK)
        assert get_asset(asset["id"])["status"] == "IN_CLEANING"

        advance_cleaning_ok(task["id"], "AWAITING_VERIFICATION", HK)
        verified = advance_cleaning_ok(task["id"], "VERIFIED",
                                       make_supervisor_headers("sup-9"))
        assert verified["status"] == "VERIFIED"
        final = get_asset(asset["id"])
        assert final["status"] == "AVAILABLE", "the cycle closes"
        assert final["isolation_contaminated"] is False

    def test_isolation_trip_contaminates_then_clears_on_verify(self, api):
        """PRD §3.5: "when the trip ran under any isolation precaution its
        `isolation_contaminated` flag is set true. The asset's entry into
        `AWAITING_CLEANING` creates a `CleaningTask` in `PENDING` whose
        `task_type` is `DEEP` for isolation trips and `STANDARD` otherwise"
        PRD §3.7: "A successful verification stamps `verified_at`, records
        `verified_by`, moves the task to `VERIFIED`, and cascades to the asset
        — back to `AVAILABLE`, `isolation_contaminated` cleared, and
        auto-dispatch evaluation run for the freed asset."

        Design: Difficulty/non_linear_state_machine/equipment_cleaning_full_cycle
        """
        world = setup_completed_trip(
            equipment="WHEELCHAIR", isolation="CONTACT", patient_ref="P1",
            complete_at="2026-08-01T00:05:00Z")
        asset, task = world["asset"], world["cleaning_task"]
        dirty = get_asset(asset["id"])
        assert dirty["status"] == "AWAITING_CLEANING"
        assert dirty["isolation_contaminated"] is True
        assert task["task_type"] == "DEEP"

        advance_cleaning_ok(task["id"], "IN_PROGRESS", HK)
        assert get_asset(asset["id"])["status"] == "IN_CLEANING"
        set_clock("2026-08-01T00:20:00Z")
        advance_cleaning_ok(task["id"], "AWAITING_VERIFICATION", HK)
        advance_cleaning_ok(task["id"], "VERIFIED",
                            make_supervisor_headers("sup-9"))

        final = get_asset(asset["id"])
        assert final["status"] == "AVAILABLE"
        assert final["isolation_contaminated"] is False, (
            "verification clears the contamination flag")


class TestTaskTypeDerivation:
    def test_task_type_derived_from_isolation(self, api):
        """PRD §3.5: "the assigned asset, if any, moves to `AWAITING_CLEANING`,
        and when the trip ran under any isolation precaution its
        `isolation_contaminated` flag is set true. The asset's entry into
        `AWAITING_CLEANING` creates a `CleaningTask` in `PENDING` whose
        `task_type` is `DEEP` for isolation trips and `STANDARD` otherwise,
        linked to both the asset and the request."

        Design: Corner/entities/task_type_derived_from_isolation
        """
        world = setup_completed_trip(equipment="WHEELCHAIR",
                                     isolation="CONTACT", patient_ref="P1")
        asset, r1 = world["asset"], world["request"]

        task = find_cleaning_task(transport_request_id=r1["id"])
        assert task["task_type"] == "DEEP"
        assert task["status"] == "PENDING"
        dirty = get_asset(asset["id"])
        assert dirty["isolation_contaminated"] is True
        assert dirty["status"] == "AWAITING_CLEANING"


class TestDeepCleaningDwell:
    def test_dwell_boundary_exact_15(self, api):
        """PRD §3.7: "for a `DEEP` task at least 15 minutes must have elapsed
        since `started_at` — exactly 15 minutes suffices — otherwise the
        advance is rejected with `ERR_DWELL_NOT_ELAPSED`, while `STANDARD`
        tasks carry no dwell requirement."

        Design: Difficulty/boundary_precision_check/dwell_boundary_exact_15
        """
        # Trip completes at the clock start; the task starts at 00:05.
        world = setup_cleaning_in_progress(
            isolation="CONTACT", start_at="2026-08-01T00:05:00Z")
        task = world["cleaning_task"]
        assert task["task_type"] == "DEEP"
        assert task["status"] == "IN_PROGRESS"

        # started_at + 14 minutes: the dwell has not elapsed.
        set_clock("2026-08-01T00:19:00Z")
        resp = advance_cleaning(task["id"], "AWAITING_VERIFICATION", HK)
        validate_error(resp, ApiErrorId.ERR_DWELL_NOT_ELAPSED)

        # started_at + 15 minutes exactly: the inclusive boundary passes.
        set_clock("2026-08-01T00:20:00Z")
        finished = advance_cleaning_ok(task["id"], "AWAITING_VERIFICATION", HK)
        assert finished["status"] == "AWAITING_VERIFICATION"

    def test_rework_restarts_the_dwell_clock(self, api):
        """PRD §3.7: "the supervisor instead sends the task from
        `AWAITING_VERIFICATION` back to `IN_PROGRESS` as rework: `rework_count`
        increments, `started_at` resets to the current instant, the asset stays
        `IN_CLEANING`, and the dwell requirement applies afresh to the next
        finish."

        Design: Difficulty/boundary_precision_check/dwell_boundary_exact_15
        """
        world = setup_cleaning_in_progress(
            isolation="CONTACT", start_at="2026-08-01T00:05:00Z")
        asset, task = world["asset"], world["cleaning_task"]
        set_clock("2026-08-01T00:20:00Z")
        advance_cleaning_ok(task["id"], "AWAITING_VERIFICATION", HK)

        reworked = advance_cleaning_ok(task["id"], "IN_PROGRESS",
                                       make_supervisor_headers("sup-1"))
        assert reworked["status"] == "IN_PROGRESS"
        assert reworked["rework_count"] == 1
        assert get_asset(asset["id"])["status"] == "IN_CLEANING"

        # 10 minutes after the rework's fresh started_at: dwell not elapsed.
        set_clock("2026-08-01T00:30:00Z")
        resp = advance_cleaning(task["id"], "AWAITING_VERIFICATION", HK)
        validate_error(resp, ApiErrorId.ERR_DWELL_NOT_ELAPSED)

        # 15 minutes after the rework: passes.
        set_clock("2026-08-01T00:35:00Z")
        finished = advance_cleaning_ok(task["id"], "AWAITING_VERIFICATION", HK)
        assert finished["status"] == "AWAITING_VERIFICATION"

    def test_standard_cleaning_finishes_without_dwell(self, api):
        """PRD §3.7: "for a `DEEP` task at least 15 minutes must have elapsed
        since `started_at` — exactly 15 minutes suffices — otherwise the
        advance is rejected with `ERR_DWELL_NOT_ELAPSED`, while `STANDARD`
        tasks carry no dwell requirement."

        Design: Corner/calculations/standard_cleaning_finishes_without_dwell
        """
        world = setup_cleaning_in_progress(isolation="NONE")
        task = world["cleaning_task"]
        assert task["task_type"] == "STANDARD"

        # Zero elapsed minutes since started_at: no dwell for STANDARD.
        finished = advance_cleaning_ok(task["id"], "AWAITING_VERIFICATION", HK)
        assert finished["status"] == "AWAITING_VERIFICATION"


class TestCleaningStateBeforeSafety:
    def test_pending_deep_task_finish_reports_state_not_dwell(self, api):
        """PRD §2.6: "6. **Entity state** — the target resource is in a status
        that permits the operation; requests already in a terminal state answer
        `ERR_ALREADY_TERMINAL`, other state violations answer the appropriate
        `ERR_INVALID_*_STATE` error."
        PRD §2.6: "7. **Business safety** — isolation capability, cleaning
        dwell, and segregation-of-duty rules."
        PRD §2.6: "Because the tiers are ordered, a request that would fail
        several checks always reports the earliest failure: a stale offer
        attempt surfaces `ERR_STALE_VERSION` rather than a state error, and an
        unknown path id surfaces `ERR_NOT_FOUND` before any business rule is
        consulted."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_cleaning_finish
        """
        # A DEEP task that was never started: advancing it to
        # AWAITING_VERIFICATION violates both the state precondition and the
        # 15-minute dwell rule; the state tier must win.
        world = setup_completed_trip(
            equipment="WHEELCHAIR", isolation="CONTACT", patient_ref="P1",
            complete_at="2026-08-01T00:05:00Z")
        task = world["cleaning_task"]
        assert task["task_type"] == "DEEP"
        assert task["status"] == "PENDING"

        resp = advance_cleaning(task["id"], "AWAITING_VERIFICATION", HK)
        validate_error(resp, ApiErrorId.ERR_INVALID_CLEANING_STATE)

    def test_pending_standard_task_finish_is_a_state_violation(self, api):
        """PRD §3.7: "Finishing moves the task from `IN_PROGRESS` to
        `AWAITING_VERIFICATION`"
        PRD §2.6: "the target resource is in a status that permits the
        operation; requests already in a terminal state answer
        `ERR_ALREADY_TERMINAL`, other state violations answer the appropriate
        `ERR_INVALID_*_STATE` error."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_cleaning_finish
        """
        # STANDARD tasks carry no dwell, so only the state tier can fail here.
        world = setup_completed_trip(equipment="WHEELCHAIR", isolation="NONE",
                                     patient_ref="P1")
        task = world["cleaning_task"]
        assert task["task_type"] == "STANDARD"
        assert task["status"] == "PENDING"

        resp = advance_cleaning(task["id"], "AWAITING_VERIFICATION", HK)
        validate_error(resp, ApiErrorId.ERR_INVALID_CLEANING_STATE)


class TestCleaningRbac:
    def test_housekeeping_cannot_verify_returns_403(self, api):
        """PRD §2.1: "`HousekeepingStaff` may advance cleaning only to
        `IN_PROGRESS` or `AWAITING_VERIFICATION`; verification and rework
        belong to the supervisor"
        PRD §3.7: "Verification belongs to the supervisor and enforces
        segregation of duty"

        Design: Corner/rbac/housekeeping_cannot_verify_returns_403
        """
        world = setup_completed_trip(equipment="WHEELCHAIR", isolation="NONE",
                                     patient_ref="P1")
        task = world["cleaning_task"]

        resp = advance_cleaning(task["id"], "VERIFIED", HK)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_segregation_of_duty_verify_rejected(self, api):
        """PRD §3.7: "a verifier whose `X-User-ID` equals the task's
        `performed_by` is rejected with `ERR_SEGREGATION_OF_DUTY` (HTTP 403). A
        successful verification stamps `verified_at`, records `verified_by`,
        moves the task to `VERIFIED`, and cascades to the asset — back to
        `AVAILABLE`, `isolation_contaminated` cleared, and auto-dispatch
        evaluation run for the freed asset."

        Design: Corner/rbac/segregation_of_duty_verify_rejected
        """
        world = setup_cleaning_in_progress(isolation="NONE")
        task = world["cleaning_task"]
        finished = advance_cleaning_ok(task["id"], "AWAITING_VERIFICATION", HK)
        assert finished["performed_by"] == "hk-1"

        # The same operator id may not verify, even with the supervisor role.
        resp = advance_cleaning(task["id"], "VERIFIED",
                                make_supervisor_headers("hk-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTY)

        verified = advance_cleaning_ok(task["id"], "VERIFIED",
                                       make_supervisor_headers("sup-9"))
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by"] == "sup-9"


class TestCleaningTaskListing:
    def test_cleaning_tasks_list_filter_by_status(self, api):
        """PRD §3.7: "Housekeeping, dispatchers, and supervisors can list
        tasks and filter by `status`, `equipment_asset_id`, or
        `transport_request_id`."

        Design: Corner/endpoints/cleaning_tasks_list_filter_by_status
        """
        setup_completed_trip(equipment="WHEELCHAIR", isolation="NONE",
                             patient_ref="P1")

        pending, meta_pending = list_cleaning_tasks(params={"status": "PENDING"})
        assert meta_pending["total_count"] == 1
        assert pending[0]["status"] == "PENDING"

        verified, meta_verified = list_cleaning_tasks(
            params={"status": "VERIFIED"})
        assert meta_verified["total_count"] == 0
        assert verified == []


class TestAssetServiceStatus:
    def test_asset_out_of_service_cycle_and_guard(self, api):
        """PRD §3.7: "Pulling an asset `OUT_OF_SERVICE` is permitted from
        `AVAILABLE` or `RESERVED`; attempting it from `IN_USE`,
        `AWAITING_CLEANING`, or `IN_CLEANING` is rejected with
        `ERR_INVALID_ASSET_STATE`."
        PRD §3.7: "Returning an asset to `AVAILABLE` is permitted only from
        `OUT_OF_SERVICE` (anything else again answers
        `ERR_INVALID_ASSET_STATE`), and the return runs auto-dispatch
        evaluation."

        Design: Corner/endpoints/asset_out_of_service_cycle_and_guard
        """
        site = setup_transport_site()
        t1 = add_on_shift_transporter("T One", site["hub"]["id"],
                                      certified_equipment=["WHEELCHAIR"])
        asset = add_equipment_asset("WC-001", "WHEELCHAIR", site["ward"]["id"])

        pulled = api.set_equipment_service_status(
            asset["id"], {"service_status": "OUT_OF_SERVICE"}, SUP)
        pulled_data = validate_success(pulled, 200)
        assert pulled_data["status"] == "OUT_OF_SERVICE"

        returned = api.set_equipment_service_status(
            asset["id"], {"service_status": "AVAILABLE"}, SUP)
        returned_data = validate_success(returned, 200)
        assert returned_data["status"] == "AVAILABLE"

        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")
        offer = create_dispatch_offer(r1, transporter_id=t1["id"])
        accept_offer(offer["id"], t1["id"])
        trip_event_ok(r1["id"], "ARRIVE_PICKUP", transporter_id=t1["id"])
        trip_event_ok(r1["id"], "PICKUP", transporter_id=t1["id"])
        assert get_asset(asset["id"])["status"] == "IN_USE"

        resp = api.set_equipment_service_status(
            asset["id"], {"service_status": "OUT_OF_SERVICE"}, SUP)
        validate_error(resp, ApiErrorId.ERR_INVALID_ASSET_STATE)
