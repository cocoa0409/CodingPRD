"""Service ticket state machine: hold/resume cycles, capacity compensation,
invalid transitions, entry-permit gating."""
import pytest

from test_helpers import (
    ApiErrorId,
    make_plant_operator_headers,
    make_safety_officer_headers,
    make_technician_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    create_active_permit,
    create_approved_entry_ticket_with_permit,
    create_approved_ticket,
    create_draft_ticket,
    create_in_progress_ticket,
    create_quoted_ticket,
    create_scheduled_ticket,
    create_site,
    create_site_vessel_technician,
)
from test_helpers.test_users import TEST_USERS

SM = TEST_USERS["service_manager_headers"]
SO = TEST_USERS["safety_officer_headers"]


def _setup_in_progress_entry_ticket():
    """Site + vessel + tech + requires_entry CLEANOUT ticket SCHEDULED
    2026-08-10 08:00-12:00 + ACTIVE permit same window + ticket IN_PROGRESS."""
    from test_helpers import api_client

    site, vessel, tech = create_site_vessel_technician(
        site_overrides={"name": "Site Five", "state_code": "IL"},
        vessel_overrides={
            "name": "SILO-G",
            "capacity_tons": 100,
            "material_name": "grain",
            "reorder_point_pct": 30,
        },
        tech_overrides={"name": "Tech Two", "weekly_capacity_hours": 40},
    )
    ticket = create_scheduled_ticket(
        site["id"], vessel["id"], tech["id"],
        window_start="2026-08-10T08:00:00Z",
        window_end="2026-08-10T12:00:00Z",
        job_type="CLEANOUT", requires_entry=True, est_hours=4, crew_size=1,
    )
    permit = create_active_permit(
        vessel["id"], ticket["id"], tech["id"],
        window_start="2026-08-10T08:00:00Z",
        window_end="2026-08-10T12:00:00Z",
        oxygen_pct=20.9, combustible_pct=2.0,
    )
    started = validate_success(
        api_client.start_service_ticket(
            ticket["id"], make_technician_headers(tech["id"])
        ),
        200,
    )
    assert started["status"] == "IN_PROGRESS"
    return site, vessel, tech, ticket, permit


class TestTicketHoldResumeCycle:
    def test_failing_atmosphere_check_suspends_permit_and_holds_ticket(self, api):
        """PRD §3.8: "A failing reading transitions the permit from `ACTIVE` to
        `SUSPENDED`, sets `atmosphere_ok` to false, records the last readings, and
        cascades: the bound `ServiceTicket` (the one whose `id` equals the permit's
        `ticket_id`) whose status is `IN_PROGRESS` automatically transitions to
        `ON_HOLD`, releasing its `est_hours` from the technician's
        `remaining_capacity_hours` while the hold persists."

        Design: Difficulty/non_linear_state_machine/ticket_hold_resume_cycle_via_permit_suspension
        """
        from test_helpers import api_client

        site, vessel, tech, ticket, permit = _setup_in_progress_entry_ticket()
        checked = validate_success(
            api_client.atmosphere_check_entry_permit(
                permit["id"],
                {"oxygen_pct": 18.0, "combustible_pct": 2.0},
                make_technician_headers(tech["id"]),
            ),
            200,
        )
        assert checked["status"] == "SUSPENDED"
        assert checked["atmosphere_ok"] is False
        fetched_ticket = validate_success(
            api_client.get_service_ticket(ticket["id"], SM), 200
        )
        # cascade: IN_PROGRESS -> ON_HOLD
        assert fetched_ticket["status"] == "ON_HOLD"

    def test_resume_returns_permit_and_ticket_to_active_in_progress(self, api):
        """PRD §3.8: "On a pass the permit returns from `SUSPENDED` to `ACTIVE`,
        `atmosphere_ok` becomes true, the last readings are recorded, and the
        reverse cascade fires: the bound ticket whose status is `ON_HOLD`
        automatically returns to `IN_PROGRESS`, with its `est_hours` re-allocated
        against the technician's `remaining_capacity_hours`."

        Design: Difficulty/non_linear_state_machine/ticket_hold_resume_cycle_via_permit_suspension
        """
        from test_helpers import api_client

        site, vessel, tech, ticket, permit = _setup_in_progress_entry_ticket()
        validate_success(
            api_client.atmosphere_check_entry_permit(
                permit["id"],
                {"oxygen_pct": 18.0, "combustible_pct": 2.0},
                make_technician_headers(tech["id"]),
            ),
            200,
        )
        resumed = validate_success(
            api_client.resume_entry_permit(
                permit["id"],
                {"oxygen_pct": 20.9, "combustible_pct": 1.0},
                SO,
            ),
            200,
        )
        assert resumed["status"] == "ACTIVE"
        assert resumed["atmosphere_ok"] is True
        fetched_ticket = validate_success(
            api_client.get_service_ticket(ticket["id"], SM), 200
        )
        # reverse cascade: ON_HOLD -> IN_PROGRESS completes the cycle
        assert fetched_ticket["status"] == "IN_PROGRESS"


class TestPermitSuspendResumeRepeatableCycle:
    def _setup_active_permit_unscheduled_ticket(self):
        site, vessel, tech = create_site_vessel_technician(
            site_overrides={"name": "Site Six", "state_code": "IL"},
            vessel_overrides={
                "name": "BIN-H",
                "vessel_kind": "BIN",
                "capacity_tons": 80,
                "material_name": "sand",
                "reorder_point_pct": 30,
            },
            tech_overrides={"name": "Tech Three", "weekly_capacity_hours": 40},
        )
        ticket = create_approved_ticket(
            site["id"], vessel["id"],
            job_type="DIAGNOSIS", requires_entry=True, est_hours=4, crew_size=1,
        )
        permit = create_active_permit(
            vessel["id"], ticket["id"], tech["id"],
            window_start="2026-08-10T08:00:00Z",
            window_end="2026-08-10T10:00:00Z",
            oxygen_pct=20.9, combustible_pct=0.0,
        )
        return site, vessel, tech, ticket, permit

    def test_permit_suspend_resume_cycle_repeats_then_closes(self, api):
        """PRD §3.8: "A `SafetyOfficer` resumes a `SUSPENDED` permit by supplying
        fresh `oxygen_pct` and `combustible_pct`. The same pass band as activation
        applies; a failure is rejected with `ERR_ATMOSPHERE_UNSAFE`."
        PRD §3.8: "A `SafetyOfficer` closes an `ACTIVE` permit by supplying
        `findings`."
        PRD §3.8: "A failing reading transitions the permit from `ACTIVE` to
        `SUSPENDED`, sets `atmosphere_ok` to false, records the last readings, and
        cascades: the bound `ServiceTicket` (the one whose `id` equals the permit's
        `ticket_id`) whose status is `IN_PROGRESS` automatically transitions to
        `ON_HOLD`, releasing its `est_hours` from the technician's
        `remaining_capacity_hours` while the hold persists."

        Design: Difficulty/non_linear_state_machine/permit_suspend_resume_repeatable_cycle_then_close
        """
        from test_helpers import api_client, validate_paginated

        site, vessel, tech, ticket, permit = (
            self._setup_active_permit_unscheduled_ticket()
        )
        # cycle 1: oxygen 24.0 > 23.5 fails -> SUSPENDED; resume -> ACTIVE
        first = validate_success(
            api_client.atmosphere_check_entry_permit(
                permit["id"], {"oxygen_pct": 24.0, "combustible_pct": 0.0}, SO
            ),
            200,
        )
        assert first["status"] == "SUSPENDED"
        resumed1 = validate_success(
            api_client.resume_entry_permit(
                permit["id"], {"oxygen_pct": 20.5, "combustible_pct": 0.0}, SO
            ),
            200,
        )
        assert resumed1["status"] == "ACTIVE"

        # cycle 2: combustible 15.0 > 10.0 fails -> SUSPENDED; resume -> ACTIVE
        second = validate_success(
            api_client.atmosphere_check_entry_permit(
                permit["id"], {"oxygen_pct": 20.9, "combustible_pct": 15.0}, SO
            ),
            200,
        )
        assert second["status"] == "SUSPENDED"
        resumed2 = validate_success(
            api_client.resume_entry_permit(
                permit["id"], {"oxygen_pct": 20.9, "combustible_pct": 5.0}, SO
            ),
            200,
        )
        assert resumed2["status"] == "ACTIVE"

        closed = validate_success(
            api_client.close_entry_permit(permit["id"], {"findings": "NONE"}, SO),
            200,
        )
        assert closed["status"] == "CLOSED"

        # no findings -> no auto DIAGNOSIS ticket
        data, meta = validate_paginated(
            api_client.list_service_tickets(
                SM, params={"source_permit_id": permit["id"]}
            )
        )
        assert meta["total_count"] == 0

        # cascade only touches IN_PROGRESS/ON_HOLD tickets; APPROVED is untouched
        fetched_ticket = validate_success(
            api_client.get_service_ticket(ticket["id"], SM), 200
        )
        assert fetched_ticket["status"] == "APPROVED"

    def test_permit_cycle_keeps_unstarted_ticket_approved(self, api):
        """PRD §3.8: "A passing reading leaves the permit `ACTIVE` and only updates
        `last_oxygen_pct` and `last_combustible_pct`. A failing reading transitions
        the permit from `ACTIVE` to `SUSPENDED`, sets `atmosphere_ok` to false,
        records the last readings, and cascades: the bound `ServiceTicket` (the one
        whose `id` equals the permit's `ticket_id`) whose status is `IN_PROGRESS`
        automatically transitions to `ON_HOLD`, releasing its `est_hours` from the
        technician's `remaining_capacity_hours` while the hold persists."

        Design: Difficulty/non_linear_state_machine/permit_suspend_resume_repeatable_cycle_then_close
        """
        from test_helpers import api_client

        site, vessel, tech, ticket, permit = (
            self._setup_active_permit_unscheduled_ticket()
        )
        validate_success(
            api_client.atmosphere_check_entry_permit(
                permit["id"], {"oxygen_pct": 24.0, "combustible_pct": 0.0}, SO
            ),
            200,
        )
        # ticket never started -> cascade does not touch APPROVED tickets
        fetched_ticket = validate_success(
            api_client.get_service_ticket(ticket["id"], SM), 200
        )
        assert fetched_ticket["status"] == "APPROVED"
        validate_success(
            api_client.resume_entry_permit(
                permit["id"], {"oxygen_pct": 20.5, "combustible_pct": 0.0}, SO
            ),
            200,
        )
        fetched_ticket = validate_success(
            api_client.get_service_ticket(ticket["id"], SM), 200
        )
        assert fetched_ticket["status"] == "APPROVED"


class TestTicketInvalidTransitions:
    def test_ticket_complete_from_scheduled_invalid_state(self, api):
        """PRD §3.9: "Completion is performed by the same assigned technician
        (again, `X-User-ID` must equal `technician_id`)."
        PRD §3.9: "Any attempt to invoke a ticket action from a wrong from-state is
        rejected with `ERR_INVALID_TICKET_STATE` (HTTP 409)."

        Design: Corner/state_machines/ticket_complete_from_scheduled_invalid_state
        """
        site, vessel, tech = create_site_vessel_technician(
            site_overrides={"name": "TC Site", "state_code": "IA"},
            vessel_overrides={
                "name": "BIN-TC", "vessel_kind": "BIN", "capacity_tons": 50,
                "material_name": "salt", "reorder_point_pct": 30,
            },
            tech_overrides={"name": "Tech C", "weekly_capacity_hours": 40},
        )
        ticket = create_scheduled_ticket(
            site["id"], vessel["id"], tech["id"],
            window_start="2026-08-10T08:00:00Z",
            window_end="2026-08-10T10:00:00Z",
            job_type="INSPECTION", requires_entry=False, est_hours=2, crew_size=1,
        )
        res = api.complete_service_ticket(
            ticket["id"],
            {"actual_hours": 2, "mileage_miles": 0, "disposal_tons": 0},
            make_technician_headers(tech["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_TICKET_STATE, expected_status=409)
        fetched = validate_success(api.get_service_ticket(ticket["id"], SM), 200)
        assert fetched["status"] == "SCHEDULED"
        assert fetched.get("invoice_total_cents") is None

    def test_ticket_approve_after_decline_terminal_lockdown(self, api):
        """PRD §3.6: "A `PlantOperator` may instead decline a `QUOTED` ticket,
        moving it to the terminal `DECLINED` state."
        PRD §3.9: "Any attempt to invoke a ticket action from a wrong from-state is
        rejected with `ERR_INVALID_TICKET_STATE` (HTTP 409)."

        Design: Corner/state_machines/ticket_approve_after_decline_terminal_lockdown
        """
        site, vessel, tech = create_site_vessel_technician(
            site_overrides={"name": "TD Site", "state_code": "IA"},
            vessel_overrides={
                "name": "BIN-TD", "vessel_kind": "BIN", "capacity_tons": 50,
                "material_name": "salt", "reorder_point_pct": 30,
            },
        )
        ticket = create_quoted_ticket(
            site["id"], vessel["id"],
            job_type="DIAGNOSIS", requires_entry=False, est_hours=2, crew_size=1,
        )
        declined = validate_success(
            api.decline_service_ticket(
                ticket["id"], make_plant_operator_headers(site["id"])
            ),
            200,
        )
        assert declined["status"] == "DECLINED"
        res = api.approve_service_ticket(
            ticket["id"], make_plant_operator_headers(site["id"])
        )
        validate_error(res, ApiErrorId.ERR_INVALID_TICKET_STATE, expected_status=409)
        fetched = validate_success(api.get_service_ticket(ticket["id"], SM), 200)
        assert fetched["status"] == "DECLINED"


class TestStartEntryPermitRequired:
    def test_start_entry_ticket_requires_active_permit(self, api):
        """PRD §3.9: "When the ticket's `requires_entry` is true, there must exist
        an `EntryPermit` whose `ticket_id` equals the ticket's `id` and whose
        status is `ACTIVE`; otherwise the start is rejected with
        `ERR_ENTRY_PERMIT_REQUIRED`."

        Design: Corner/state_machines/start_entry_ticket_requires_active_permit
        """
        site, vessel, tech = create_site_vessel_technician(
            site_overrides={"name": "EP Site", "state_code": "IA"},
            vessel_overrides={
                "name": "BIN-EP", "vessel_kind": "BIN", "capacity_tons": 50,
                "material_name": "salt", "reorder_point_pct": 30,
            },
            tech_overrides={"name": "Tech E", "weekly_capacity_hours": 40},
        )
        ticket = create_scheduled_ticket(
            site["id"], vessel["id"], tech["id"],
            window_start="2026-08-10T08:00:00Z",
            window_end="2026-08-10T12:00:00Z",
            job_type="CLEANOUT", requires_entry=True, est_hours=4, crew_size=1,
        )
        res = api.start_service_ticket(
            ticket["id"], make_technician_headers(tech["id"])
        )
        validate_error(
            res, ApiErrorId.ERR_ENTRY_PERMIT_REQUIRED, expected_status=409
        )
        fetched = validate_success(api.get_service_ticket(ticket["id"], SM), 200)
        assert fetched["status"] == "SCHEDULED"


class TestTechnicianHoursCompensation:
    def _setup_approved_inspection(self):
        site, vessel, tech = create_site_vessel_technician(
            site_overrides={"name": "Site Seventeen", "state_code": "TX"},
            vessel_overrides={
                "name": "BIN-W", "vessel_kind": "BIN", "capacity_tons": 50,
                "material_name": "salt", "reorder_point_pct": 30,
            },
            tech_overrides={"name": "Tech Eleven", "weekly_capacity_hours": 40},
        )
        ticket = create_approved_ticket(
            site["id"], vessel["id"],
            job_type="INSPECTION", requires_entry=False, est_hours=8, crew_size=1,
        )
        return site, vessel, tech, ticket

    def test_schedule_allocates_est_hours(self, api):
        """PRD §3.7: "That field equals `weekly_capacity_hours` minus the sum of
        `est_hours` across the technician's tickets whose status is `SCHEDULED` or
        `IN_PROGRESS`, expressed at 2 decimal places, rounded half up."

        Design: Difficulty/compensating_invariant/schedule_then_complete_restores_technician_hours
        """
        site, vessel, tech, ticket = self._setup_approved_inspection()
        before = validate_success(api.get_technician(tech["id"], SM), 200)
        assert before["remaining_capacity_hours"] == pytest.approx(40.0, abs=1e-9)

        scheduled = validate_success(
            api.schedule_service_ticket(
                ticket["id"],
                {
                    "technician_id": tech["id"],
                    "window_start": "2026-08-10T08:00:00Z",
                    "window_end": "2026-08-10T16:00:00Z",
                },
                SM,
            ),
            200,
        )
        assert scheduled["status"] == "SCHEDULED"
        after = validate_success(api.get_technician(tech["id"], SM), 200)
        # 40 - 8
        assert after["remaining_capacity_hours"] == pytest.approx(32.0, abs=1e-9)

    def test_schedule_then_complete_restores_technician_hours(self, api):
        """PRD §3.7: "Tickets in `ON_HOLD` no longer count (the crew is released to
        standby by the safety hold), and tickets in `COMPLETED` or `DECLINED` never
        count; consequently schedule-then-complete restores the pre-schedule value
        exactly."

        Design: Difficulty/compensating_invariant/schedule_then_complete_restores_technician_hours
        """
        site, vessel, tech, ticket = self._setup_approved_inspection()
        validate_success(
            api.schedule_service_ticket(
                ticket["id"],
                {
                    "technician_id": tech["id"],
                    "window_start": "2026-08-10T08:00:00Z",
                    "window_end": "2026-08-10T16:00:00Z",
                },
                SM,
            ),
            200,
        )
        started = validate_success(
            api.start_service_ticket(
                ticket["id"], make_technician_headers(tech["id"])
            ),
            200,
        )
        assert started["status"] == "IN_PROGRESS"
        # still allocated while IN_PROGRESS
        mid = validate_success(api.get_technician(tech["id"], SM), 200)
        assert mid["remaining_capacity_hours"] == pytest.approx(32.0, abs=1e-9)

        completed = validate_success(
            api.complete_service_ticket(
                ticket["id"],
                {"actual_hours": 8, "mileage_miles": 0, "disposal_tons": 0},
                make_technician_headers(tech["id"]),
            ),
            200,
        )
        assert completed["status"] == "COMPLETED"
        after = validate_success(api.get_technician(tech["id"], SM), 200)
        # est_hours released: pre-schedule value restored exactly
        assert after["remaining_capacity_hours"] == pytest.approx(40.0, abs=1e-9)
