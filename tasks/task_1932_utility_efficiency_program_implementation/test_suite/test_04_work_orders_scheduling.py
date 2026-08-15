"""Work orders: start-date gating, half-open calendar overlap, and
entity-backed ownership enforcement."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_approved_project,
    create_contractor_payload,
    create_proposed_project,
    create_work_order,
    get_program,
    make_contractor_headers,
    set_clock,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]


class TestWorkOrderStartDateGating:
    def test_work_order_start_too_early_rejected(self, api, pm_headers):
        """PRD 3.5: "the logical clock's calendar date must equal the
        `scheduled_on` date — an attempt to start before the scheduled day is
        refused with `ERR_START_TOO_EARLY`."

        Design: Corner/state_machines/work_order_start_too_early_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = create_approved_project()
        wo = create_work_order(ctx["project"]["id"], ctx["contractor"]["id"],
                               scheduled_on="2026-08-05T09:00:00Z")
        assert wo["status"] == "SCHEDULED"
        resp = api.start_work_order(
            wo["id"], make_contractor_headers(ctx["contractor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_START_TOO_EARLY)


class TestContractorCalendarHalfOpenOverlap:
    def _program_with_two_approved_projects(self, api):
        """One ACTIVE program, one APPROVED contractor, and two APPROVED
        projects for that contractor (each from its own accepted lead)."""
        set_clock("2026-08-01T00:00:00Z")
        ctx1 = create_approved_project()
        ctx2 = create_proposed_project(
            program_id=ctx1["program"]["id"],
            contractor_id=ctx1["contractor"]["id"],
            customer_id=ctx1["customer"]["id"],
        )
        version = get_program(ctx1["program"]["id"])["version"]
        resp = api.approve_project(ctx2["project"]["id"], version, PM)
        ctx2["project"] = validate_success(resp, expected_status=200)
        return ctx1, ctx2

    def test_adjacent_work_orders_do_not_conflict(self, api, pm_headers):
        """PRD 3.5: "the platform refuses with `ERR_SCHEDULE_CONFLICT` any
        order whose working window — the half-open interval that begins at
        `scheduled_on` and runs for `duration_hours`, with the end instant
        itself excluded — would overlap another `SCHEDULED` or `IN_PROGRESS`
        work order for the same contractor on the same calendar date.
        Back-to-back bookings, where one window ends exactly as another
        begins, do not conflict."
        WO1 occupies [09:00, 13:00); WO2 begins at 13:00 — adjacent, allowed.

        Design: Difficulty/resource_temporal_overlap/contractor_calendar_half_open_overlap
        """
        ctx1, ctx2 = self._program_with_two_approved_projects(api)
        ctr_id = ctx1["contractor"]["id"]
        wo1 = create_work_order(ctx1["project"]["id"], ctr_id,
                                scheduled_on="2026-08-05T09:00:00Z", duration_hours=4)
        assert wo1["status"] == "SCHEDULED"
        wo2 = create_work_order(ctx2["project"]["id"], ctr_id,
                                scheduled_on="2026-08-05T13:00:00Z", duration_hours=2)
        assert wo2["status"] == "SCHEDULED"

    def test_overlapping_work_order_rejected(self, api, pm_headers):
        """PRD 3.5: "the platform refuses with `ERR_SCHEDULE_CONFLICT` any
        order whose working window — the half-open interval that begins at
        `scheduled_on` and runs for `duration_hours`, with the end instant
        itself excluded — would overlap another `SCHEDULED` or `IN_PROGRESS`
        work order for the same contractor on the same calendar date."
        WO1 occupies [09:00, 13:00); WO2's [12:00, 13:00) lies inside it.

        Design: Difficulty/resource_temporal_overlap/contractor_calendar_half_open_overlap
        """
        ctx1, ctx2 = self._program_with_two_approved_projects(api)
        ctr_id = ctx1["contractor"]["id"]
        create_work_order(ctx1["project"]["id"], ctr_id,
                          scheduled_on="2026-08-05T09:00:00Z", duration_hours=4)
        resp = api.create_work_order(
            ctx2["project"]["id"],
            {"contractor_id": ctr_id, "scheduled_on": "2026-08-05T12:00:00Z",
             "duration_hours": 1},
            make_contractor_headers(ctr_id),
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT)


class TestWorkOrderOwnership:
    def test_contractor_cannot_complete_other_contractors_work_order(self, api, pm_headers):
        """PRD 3.5: "The caller must own the order (`ERR_NOT_RESOURCE_OWNER`)"
        — and PRD 2.1: "When `X-User-Role` is `Contractor`, `X-User-ID` is the
        `id` of the acting Contractor, and ownership checks on any resource
        that references a contractor — an assigned lead, a work order —
        compare the resource's contractor foreign-key field to `X-User-ID`."

        Design: Corner/roles/contractor_cannot_complete_other_contractors_work_order
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = create_approved_project()
        wo = create_work_order(ctx["project"]["id"], ctx["contractor"]["id"],
                               scheduled_on="2026-08-02T00:00:00Z", duration_hours=4)
        # Another contractor identity attempts to start the order on its date.
        set_clock("2026-08-02T09:00:00Z")
        other = validate_success(
            api.create_contractor(create_contractor_payload(), PM), expected_status=201)
        resp = api.start_work_order(wo["id"], make_contractor_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
