"""Gate, threshold, window and ceiling rejections.

These tests isolate the guards that fire only once identity, shape, existence
and state have all been settled: the certification thresholds, the training
capacity and orientation preconditions, the defect gate on milestone closure,
the licensing gate on the soft opening, the fiscal and delivery-window guards on
procurement, the two reservation ceilings and the stabilization window.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_client import PreOpeningApiClient
from test_helpers.api_errors import (
    ERR_BUDGET_WOULD_EXCEED,
    ERR_CONTINGENCY_LIABILITY_EXCEEDED,
    ERR_CRITICAL_PUNCH_OPEN,
    ERR_DELIVERY_OUTSIDE_WINDOW,
    ERR_DEPARTMENT_NOT_READY,
    ERR_MANDATORY_PERMIT_NOT_ISSUED,
    ERR_ORIENTATION_NOT_COMPLETED,
    ERR_PREREQUISITE_SYSTEM_NOT_CERTIFIED,
    ERR_ROOM_NIGHT_CEILING_EXCEEDED,
    ERR_STABILIZATION_WINDOW_NOT_ELAPSED,
    ERR_SYSTEM_NOT_CERTIFIED,
    ERR_SYSTEM_PASS_RATE_BELOW_THRESHOLD,
    ERR_TRAINING_SESSION_FULL,
)
from test_helpers.assertions import (
    assert_budget_split,
    assert_cents,
    assert_page,
    assert_program_dimensions,
    assert_ratio,
)
from test_helpers.constants import (
    CODE_CONSTRUCTION_COMPLETE,
    DEFAULT_NOW,
    ROLE_PROGRAM_DIRECTOR,
)
from test_helpers.factories import (
    assign_orientation_payload,
    ose_order_payload,
    receive_payload,
    reservation_block_payload,
    soft_opening_payload,
)
from test_helpers.test_users import (
    CERTIFYING_INTEGRATOR,
    COMMERCIAL_DIRECTOR,
    CONSTRUCTION_MANAGER,
    PROCUREMENT_MANAGER,
    PROGRAM_DIRECTOR,
    QUALITY_INSPECTOR,
    SYSTEMS_INTEGRATOR,
    TALENT_MANAGER,
    headers_for,
)

# The second director, distinct from the one who baselines the schedule, is the
# only operator who may authorize a soft opening.
AUTHORIZING_DIRECTOR = headers_for(ROLE_PROGRAM_DIRECTOR, "pd-authorizer-2")

COMPLETION_INSTANT = "2026-10-01T00:00:00Z"

# A larger property with its own buffers, used where the scenario needs a
# thirty-day stabilization window and a sixty-day construction milestone.
AURORA_PROGRAM: Dict[str, Any] = {
    "property_name": "Aurora Summit Hotel",
    "brand_code": "ASH",
    "room_count": 150,
    "construction_start_date": "2026-09-01",
    "target_opening_date": "2027-06-01",
    "storage_capacity_pallets": 60,
    "relocation_rate_cents": 25000,
    "guarantee_penalty_cents": 150000,
    "room_night_ceiling": 300,
    "contingency_liability_cap_cents": 90000000,
    "licensing_buffer_days": 14,
    "slip_tolerance_days": 10,
    "stabilization_window_days": 30,
}


def _rooms_plan_with_session(
    api: PreOpeningApiClient, capacity: int
) -> Dict[str, Any]:
    """A rooms hiring plan for two people and one rooms orientation session."""
    fixtures.set_clock(api, DEFAULT_NOW)
    program = fixtures.make_program(api)
    plan = fixtures.make_hiring_plan(
        api,
        program["id"],
        department="ROOMS",
        headcount_target=2,
        wave_start_date="2026-09-10",
    )
    session = fixtures.make_training_session(
        api,
        program["id"],
        title="Rooms orientation",
        training_room_code="TR-1",
        starts_at="2026-09-14T09:00:00Z",
        ends_at="2026-09-14T12:00:00Z",
        capacity=capacity,
        department="ROOMS",
    )
    return {"program": program, "plan": plan, "session": session}


def _committed_order(
    api: PreOpeningApiClient,
    amount_cents: int,
    pallet_count: int,
    delivery_window_start: str,
    delivery_window_end: str,
    description: str = "Guest room linen",
) -> Dict[str, Any]:
    """A program with one SETUP line of 1000000 cents carrying one committed order."""
    fixtures.set_clock(api, DEFAULT_NOW)
    program = fixtures.make_program(api)
    line = fixtures.make_budget_line(
        api, program["id"], category="SETUP", authorized_cents=1000000
    )
    order = fixtures.make_ose_order(
        api,
        program["id"],
        line["id"],
        line["version"],
        description=description,
        amount_cents=amount_cents,
        pallet_count=pallet_count,
        delivery_window_start=delivery_window_start,
        delivery_window_end=delivery_window_end,
    )
    return {"program": program, "budget_line": line, "order": order}


def _booking_open_with_ceilings(
    api: PreOpeningApiClient,
    room_night_ceiling: int,
    contingency_liability_cap_cents: int,
) -> Dict[str, Any]:
    """A BOOKING_OPEN program whose two commercial ceilings are set explicitly."""
    fixtures.set_clock(api, DEFAULT_NOW)
    built = fixtures.construction_complete_program(
        api,
        finish_iso=COMPLETION_INSTANT,
        duration_days=30,
        program_overrides={
            "room_night_ceiling": room_night_ceiling,
            "contingency_liability_cap_cents": contingency_liability_cap_cents,
        },
    )
    built["program"] = fixtures.open_booking(api, built["program"]["id"])
    return built


class TestSystemCertificationThresholds:
    """Certification reads the latest run and the prerequisite system."""

    def test_certify_below_the_pass_rate_floor_is_refused(
        self, api: PreOpeningApiClient
    ) -> None:
        """A required revenue system has one run of thirty-seven cases out of forty
        with no blockers. That rate is well above the demotion line, so the system
        is in testing rather than failed, but it is under the certification floor
        and the sign-off is refused.

        The system's `latest_pass_rate` must be at least 0.95, else `ERR_SYSTEM_PASS_RATE_BELOW_THRESHOLD` — and this reads the **latest** rate, never the pooled one, so a system whose `cumulative_pass_rate` sits comfortably above the floor but whose most recent run fell below it must still be refused.

        Design: Corner/errors/certify_below_pass_rate_floor_returns_pass_rate_below_threshold
        """
        fixtures.set_clock(api, DEFAULT_NOW)
        program = fixtures.make_program(api)
        system = fixtures.make_system(
            api, program["id"], system_type="REVENUE", is_required=True
        )
        run = fixtures.add_test_run(
            api,
            system["id"],
            "2026-09-01T09:00:00Z",
            cases_total=40,
            cases_passed=37,
            blocker_count=0,
        )
        assert_ratio(run["pass_rate"], 0.925)
        assert run["result"] == "FAILED"
        in_testing = validate_success(
            api.get_system_implementation(system["id"], SYSTEMS_INTEGRATOR), 200
        )
        assert in_testing["state"] == "TESTING"

        response = api.certify_system(system["id"], CERTIFYING_INTEGRATOR)

        validate_error(response, ERR_SYSTEM_PASS_RATE_BELOW_THRESHOLD, 422)
        refreshed = fixtures.read_program(api, program["id"])
        assert refreshed["certified_system_count"] == 0
        assert refreshed["required_system_count"] == 1

    def test_certify_with_an_uncertified_prerequisite_is_refused(
        self, api: PreOpeningApiClient
    ) -> None:
        """The point-of-sale system passes all forty of its cases with no blockers,
        so every condition of its own is met. Its declared prerequisite, the
        property management system, has never been tested, and the sign-off is
        refused for that reason alone.

        If `prerequisite_system_id` is set, the system it names must itself be `CERTIFIED`, else `ERR_PREREQUISITE_SYSTEM_NOT_CERTIFIED`.

        Design: Corner/errors/certify_with_uncertified_prerequisite_returns_prerequisite_system_not_certified
        """
        fixtures.set_clock(api, DEFAULT_NOW)
        program = fixtures.make_program(api)
        pms = fixtures.make_system(
            api, program["id"], system_type="PMS", is_required=True
        )
        pos = fixtures.make_system(
            api,
            program["id"],
            system_type="POS",
            prerequisite_system_id=pms["id"],
            is_required=True,
        )
        fixtures.add_test_run(
            api,
            pos["id"],
            "2026-09-01T09:00:00Z",
            cases_total=40,
            cases_passed=40,
            blocker_count=0,
        )
        candidate = validate_success(
            api.get_system_implementation(pos["id"], SYSTEMS_INTEGRATOR), 200
        )
        assert candidate["state"] == "TESTING"
        assert_ratio(candidate["latest_pass_rate"], 1.0)
        assert candidate["open_blocker_count"] == 0

        response = api.certify_system(pos["id"], CERTIFYING_INTEGRATOR)

        validate_error(response, ERR_PREREQUISITE_SYSTEM_NOT_CERTIFIED, 422)
        prerequisite = validate_success(
            api.get_system_implementation(pms["id"], SYSTEMS_INTEGRATOR), 200
        )
        assert prerequisite["state"] == "PLANNED"
        refreshed = fixtures.read_program(api, program["id"])
        assert refreshed["required_system_count"] == 2
        assert refreshed["certified_system_count"] == 0


class TestTrainingCapacityAndOrientation:
    """Seats are finite and onboarding waits for the orientation to be delivered."""

    def test_a_full_session_refuses_a_further_enrolment(
        self, api: PreOpeningApiClient
    ) -> None:
        """A single-seat rooms orientation is already taken by the hire that named
        it at offer time. A second rooms hire, offered without a seat, cannot be
        enrolled, and the session's seat count does not move.

        Two eligibility rules apply: enrolling a hire that would push the session's `enrolled_count` above its `capacity` is refused with `ERR_TRAINING_SESSION_FULL`, and a session whose `department` is neither `ALL` nor the `department` of the hire's plan is refused with `ERR_TRAINING_DEPARTMENT_MISMATCH`.

        Design: Corner/errors/assign_orientation_to_full_session_returns_training_session_full
        """
        built = _rooms_plan_with_session(api, capacity=1)
        session_id = built["session"]["id"]
        fixtures.make_hire(
            api,
            built["plan"]["id"],
            session_id,
            full_name="A. Keeper",
            hourly_rate_cents=2500,
            scheduled_hours_per_day=8,
            start_date="2026-09-15",
        )
        second = fixtures.make_hire(
            api,
            built["plan"]["id"],
            full_name="B. Porter",
            hourly_rate_cents=2500,
            scheduled_hours_per_day=8,
            start_date="2026-09-15",
        )
        sessions, _ = validate_paginated(
            api.list_training_sessions(built["program"]["id"], TALENT_MANAGER)
        )
        full = next(row for row in sessions if row["id"] == session_id)
        assert full["capacity"] == 1
        assert full["enrolled_count"] == 1

        response = api.assign_orientation(
            second["id"], assign_orientation_payload(session_id), TALENT_MANAGER
        )

        validate_error(response, ERR_TRAINING_SESSION_FULL, 422)
        unchanged = validate_success(api.get_hire(second["id"], TALENT_MANAGER), 200)
        assert unchanged["orientation_session_id"] is None
        sessions, _ = validate_paginated(
            api.list_training_sessions(built["program"]["id"], TALENT_MANAGER)
        )
        still_full = next(row for row in sessions if row["id"] == session_id)
        assert still_full["enrolled_count"] == 1

    def test_onboarding_needs_the_orientation_delivered(
        self, api: PreOpeningApiClient
    ) -> None:
        """An accepted rooms hire is enrolled in an orientation that was never
        marked delivered. The clock has moved five days past the hire's start
        date, so the date condition is met and only the orientation is missing.

        It moves a hire `ACCEPTED → ONBOARDED` and requires two things: the hire must have a non-null `orientation_session_id` whose session is in state `COMPLETED`, else `ERR_ORIENTATION_NOT_COMPLETED`; and the logical clock date must have reached or passed the hire's `start_date`, else `ERR_INVALID_HIRE_STATE`.

        Design: Corner/errors/onboard_before_orientation_completed_returns_orientation_not_completed
        """
        built = _rooms_plan_with_session(api, capacity=5)
        hire = fixtures.make_hire(
            api,
            built["plan"]["id"],
            built["session"]["id"],
            full_name="A. Keeper",
            hourly_rate_cents=2500,
            scheduled_hours_per_day=8,
            start_date="2026-09-15",
        )
        fixtures.respond_to_offer(api, hire["id"], "ACCEPT")
        fixtures.set_clock(api, "2026-09-20T00:00:00Z")
        sessions, _ = validate_paginated(
            api.list_training_sessions(built["program"]["id"], TALENT_MANAGER)
        )
        orientation = next(
            row for row in sessions if row["id"] == built["session"]["id"]
        )
        assert orientation["state"] == "SCHEDULED"

        response = api.onboard_hire(hire["id"], TALENT_MANAGER)

        validate_error(response, ERR_ORIENTATION_NOT_COMPLETED, 422)
        unchanged = validate_success(api.get_hire(hire["id"], TALENT_MANAGER), 200)
        assert unchanged["state"] == "ACCEPTED"
        assert unchanged["onboarded_at"] is None
        plans, _ = validate_paginated(
            api.list_hiring_plans(built["program"]["id"], TALENT_MANAGER)
        )
        plan = next(row for row in plans if row["id"] == built["plan"]["id"])
        assert plan["onboarded_count"] == 0
        assert plan["readiness_flag"] == "NOT_READY"


class TestMilestoneClosureGate:
    """An unverified critical defect keeps its milestone open."""

    def test_open_critical_defect_blocks_milestone_completion(
        self, api: PreOpeningApiClient
    ) -> None:
        """A thirty-day construction milestone is under way and the clock has
        reached its planned finish, so nothing about the calendar prevents
        closure. One critical defect attributed to that milestone is still open,
        which both freezes the program and holds the milestone open.

        Completing a milestone moves it `IN_PROGRESS → COMPLETE`, but only if no punch-list item attributed to that milestone has `severity` `CRITICAL` and a state other than `VERIFIED`; such a defect blocks completion with `ERR_CRITICAL_PUNCH_OPEN`.

        Design: Corner/errors/milestone_complete_with_open_critical_punch_returns_critical_punch_open
        """
        fixtures.set_clock(api, DEFAULT_NOW)
        built = fixtures.baselined_program(
            api,
            milestones=[
                {
                    "code": CODE_CONSTRUCTION_COMPLETE,
                    "name": "Construction complete",
                    "duration_days": 30,
                    "planned_start_date": "2026-09-01",
                }
            ],
        )
        program_id = built["program"]["id"]
        milestone_id = built["milestones"][CODE_CONSTRUCTION_COMPLETE]["id"]
        fixtures.start_milestone(api, milestone_id)
        defect = fixtures.frozen_by_critical_punch(
            api, program_id, milestone_id=milestone_id
        )
        assert defect["blocks_certificate_of_occupancy"] is True
        fixtures.set_clock(api, COMPLETION_INSTANT)
        before = fixtures.read_program(api, program_id)
        assert before["open_critical_punch_count"] == 1

        response = api.complete_milestone(milestone_id, CONSTRUCTION_MANAGER)

        validate_error(response, ERR_CRITICAL_PUNCH_OPEN, 422)
        milestone = validate_success(
            api.get_milestone(milestone_id, CONSTRUCTION_MANAGER), 200
        )
        assert milestone["state"] == "IN_PROGRESS"
        assert milestone["actual_finish_date"] is None
        after = fixtures.read_program(api, program_id)
        assert_program_dimensions(
            after, schedule_state="BASELINED", readiness_posture="FROZEN"
        )


class TestSoftOpeningPermitGate:
    """The soft opening waits for all four mandatory permits."""

    def test_one_issued_permit_of_four_blocks_the_soft_opening(
        self, api: PreOpeningApiClient
    ) -> None:
        """A program in licensing has only its elevator approval in hand, while
        its single department is ready, no system is required and no defect is
        open. The proposed date sits inside the allowed window and the authorizing
        director is not the one who baselined, yet the call is refused.

        `issued_mandatory_permit_count` must equal 4 — all four opening-mandatory permit types issued — else `ERR_MANDATORY_PERMIT_NOT_ISSUED`.

        Design: Corner/errors/authorize_soft_opening_with_one_issued_permit_returns_mandatory_permit_not_issued
        """
        fixtures.set_clock(api, DEFAULT_NOW)
        built = fixtures.baselined_program(
            api,
            milestones=[
                {
                    "code": CODE_CONSTRUCTION_COMPLETE,
                    "name": "Construction complete",
                    "duration_days": 30,
                    "planned_start_date": "2026-09-01",
                }
            ],
        )
        program_id = built["program"]["id"]
        milestone_id = built["milestones"][CODE_CONSTRUCTION_COMPLETE]["id"]
        fixtures.start_milestone(api, milestone_id)

        # One rooms department taken all the way to READY, so the departmental
        # condition of the audit is satisfied and only the permits are missing.
        plan = fixtures.make_hiring_plan(
            api,
            program_id,
            department="ROOMS",
            headcount_target=1,
            wave_start_date="2026-09-10",
        )
        session = fixtures.make_training_session(
            api,
            program_id,
            title="Rooms orientation",
            training_room_code="TR-1",
            starts_at="2026-09-14T09:00:00Z",
            ends_at="2026-09-14T12:00:00Z",
            capacity=5,
            department="ROOMS",
        )
        hire = fixtures.make_hire(
            api,
            plan["id"],
            session["id"],
            full_name="R. Alvarez",
            hourly_rate_cents=2500,
            scheduled_hours_per_day=8,
            start_date="2026-09-15",
        )
        fixtures.respond_to_offer(api, hire["id"], "ACCEPT")
        fixtures.set_clock(api, "2026-09-20T00:00:00Z")
        fixtures.complete_session(api, session["id"])
        fixtures.onboard(api, hire["id"])

        fixtures.set_clock(api, COMPLETION_INSTANT)
        fixtures.complete_milestone(api, milestone_id)
        fixtures.issued_permit(
            api, program_id, milestone_id, permit_type="ELEVATOR", review_days=21
        )

        before = fixtures.read_program(api, program_id)
        assert before["schedule_state"] == "LICENSING"
        assert before["issued_mandatory_permit_count"] == 1
        assert before["departments_ready_count"] == before["hiring_plan_count"] == 1
        assert before["required_system_count"] == before["certified_system_count"] == 0
        assert before["open_critical_punch_count"] == 0
        assert before["projected_opening_date_committed"] == "2026-10-15"

        response = api.authorize_soft_opening(
            program_id, soft_opening_payload("2026-10-10"), AUTHORIZING_DIRECTOR
        )

        validate_error(response, ERR_MANDATORY_PERMIT_NOT_ISSUED, 422)
        after = fixtures.read_program(api, program_id)
        assert after["schedule_state"] == "LICENSING"
        assert after["soft_opening_date"] is None


class TestSoftOpeningGateOrder:
    """Two unmet soft-opening conditions surface in the declared order."""

    def test_the_system_gate_is_reported_before_the_department_gate(
        self, api: PreOpeningApiClient
    ) -> None:
        """A licensing program holds all four permits and no open defect, but one
        required system is still unimplemented and a second department has no
        onboarded hire. The audit refuses on the system condition first; once that
        system is certified the very same call refuses on the department condition.

        When several checks could reject the same request, they are evaluated in a fixed precedence so that the surfaced error is deterministic.

        **Licensing and closure gates** — permit sequencing prerequisites issued and the gating milestone complete before submission; and, for soft opening, all four mandatory permits issued, zero open critical punch items and every required system certified.

        The program must have at least one hiring plan and `departments_ready_count` must equal `hiring_plan_count` — every department at or above its eighty-percent onboarding threshold — else `ERR_DEPARTMENT_NOT_READY`.

        Design: Corner/errors/authorize_soft_opening_reports_the_system_gate_before_the_department_gate
        """
        fixtures.set_clock(api, DEFAULT_NOW)
        built = fixtures.soft_opening_ready_program(
            api, program_overrides=dict(AURORA_PROGRAM)
        )
        program_id = built["program"]["id"]

        # One required system that has never been tested, and a second department
        # whose wave has not started, so both conditions of the audit are unmet.
        system = fixtures.make_system(
            api, program_id, system_type="PMS", is_required=True
        )
        fixtures.make_hiring_plan(
            api,
            program_id,
            department="FOOD_BEVERAGE",
            headcount_target=2,
            wave_start_date="2026-09-10",
        )

        before = fixtures.read_program(api, program_id)
        assert before["schedule_state"] == "LICENSING"
        assert before["issued_mandatory_permit_count"] == 4
        assert before["open_critical_punch_count"] == 0
        assert before["required_system_count"] == 1
        assert before["certified_system_count"] == 0
        assert before["hiring_plan_count"] == 2
        assert before["departments_ready_count"] == 1
        assert before["projected_opening_date_committed"] == "2026-11-14"
        assert_program_dimensions(before, readiness_posture="MOBILIZING")

        first = api.authorize_soft_opening(
            program_id, soft_opening_payload("2026-11-10"), AUTHORIZING_DIRECTOR
        )
        validate_error(first, ERR_SYSTEM_NOT_CERTIFIED, 422)

        # Satisfy only the system condition, leaving the department one untouched.
        fixtures.add_test_run(
            api,
            system["id"],
            executed_at="2026-10-31T09:00:00Z",
            cases_total=40,
            cases_passed=40,
            blocker_count=0,
        )
        certified = fixtures.certify(api, system["id"])
        assert certified["state"] == "CERTIFIED"
        midway = fixtures.read_program(api, program_id)
        assert midway["certified_system_count"] == 1

        second = api.authorize_soft_opening(
            program_id, soft_opening_payload("2026-11-10"), AUTHORIZING_DIRECTOR
        )
        validate_error(second, ERR_DEPARTMENT_NOT_READY, 422)

        after = fixtures.read_program(api, program_id)
        assert after["schedule_state"] == "LICENSING"
        assert after["soft_opening_date"] is None


class TestProcurementGuards:
    """Commitment watches the running balance and receipt watches the window."""

    def test_second_order_beyond_the_running_available_balance_is_refused(
        self, api: PreOpeningApiClient
    ) -> None:
        """A setup line authorized at one million cents already carries a
        committed order of six hundred thousand, so four hundred thousand remain.
        A five hundred thousand cent order is individually inside the authorized
        total but outside what is left, and the line does not move.

        Fiscally, `amount_cents` may not exceed the line's `available_cents`; an amount strictly greater is refused with `ERR_BUDGET_WOULD_EXCEED`.

        Design: Corner/errors/order_beyond_available_returns_budget_would_exceed
        """
        built = _committed_order(
            api,
            amount_cents=600000,
            pallet_count=5,
            delivery_window_start="2026-09-05",
            delivery_window_end="2026-09-15",
        )
        program_id = built["program"]["id"]
        line_id = built["budget_line"]["id"]
        lines, _ = validate_paginated(
            api.list_budget_lines(program_id, PROCUREMENT_MANAGER, {"category": "SETUP"})
        )
        line = next(row for row in lines if row["id"] == line_id)
        assert_budget_split(line, 1000000, 600000, 0)

        response = api.create_ose_order(
            ose_order_payload(
                program_id,
                line_id,
                line["version"],
                description="Banquet chairs",
                amount_cents=500000,
                pallet_count=4,
                delivery_window_start="2026-09-05",
                delivery_window_end="2026-09-15",
            ),
            PROCUREMENT_MANAGER,
        )

        validate_error(response, ERR_BUDGET_WOULD_EXCEED, 422)
        lines, _ = validate_paginated(
            api.list_budget_lines(program_id, PROCUREMENT_MANAGER)
        )
        unchanged = next(row for row in lines if row["id"] == line_id)
        assert_budget_split(unchanged, 1000000, 600000, 0)
        _, meta = validate_paginated(
            api.list_ose_orders(PROCUREMENT_MANAGER, {"program_id": program_id})
        )
        assert_page(meta, total_count=1, has_more=False)

    def test_receiving_after_the_window_closes_is_refused(
        self, api: PreOpeningApiClient
    ) -> None:
        """A shipment was committed for the first ten days of October and the
        clock now reads the twentieth. The program is not frozen, so nothing else
        stands in the way, and the receipt is refused as outside the window with
        the money still sitting in commitment.

        The receipt date, taken from the logical clock, must fall inside the half-open delivery window — on or after `delivery_window_start` and strictly before `delivery_window_end`; outside that, the request is refused with `ERR_DELIVERY_OUTSIDE_WINDOW`.

        Design: Corner/errors/receive_outside_window_returns_delivery_outside_window
        """
        built = _committed_order(
            api,
            amount_cents=400000,
            pallet_count=5,
            delivery_window_start="2026-10-01",
            delivery_window_end="2026-10-10",
        )
        program_id = built["program"]["id"]
        order_id = built["order"]["id"]
        fixtures.set_clock(api, "2026-10-20T00:00:00Z")
        before = fixtures.read_program(api, program_id)
        assert before["readiness_posture"] == "MOBILIZING"

        response = api.receive_ose_order(
            order_id, receive_payload("BAY-07"), PROCUREMENT_MANAGER
        )

        validate_error(response, ERR_DELIVERY_OUTSIDE_WINDOW, 422)
        order = validate_success(api.get_ose_order(order_id, PROCUREMENT_MANAGER), 200)
        assert order["state"] == "COMMITTED"
        assert order["received_at"] is None
        assert order["stored_bay_code"] is None
        lines, _ = validate_paginated(
            api.list_budget_lines(program_id, PROCUREMENT_MANAGER)
        )
        line = next(row for row in lines if row["id"] == built["budget_line"]["id"])
        assert_budget_split(line, 1000000, 400000, 0)


class TestReservationCeilings:
    """The room-night ceiling and the contingency cap each refuse a block."""

    def test_block_beyond_the_room_night_ceiling_is_refused(
        self, api: PreOpeningApiClient
    ) -> None:
        """A block of nineteen rooms for four nights would hold seventy-six
        room-nights against a ceiling of fifty. Its contingency of 2052000 cents
        is far inside a fifty million cent cap, so the room-night ceiling is the
        only breach and nothing is booked.

        Three ceilings then apply: `committed_room_nights` plus the new block's `room_nights` may not be strictly greater than `room_night_ceiling`, else `ERR_ROOM_NIGHT_CEILING_EXCEEDED`; and the projected `contingency_liability_cents` after accepting the block — the existing liability plus this block's own `contingency_cents` — may not be strictly greater than `contingency_liability_cap_cents`, else `ERR_CONTINGENCY_LIABILITY_EXCEEDED`.

        Design: Corner/errors/block_beyond_room_night_ceiling_returns_room_night_ceiling_exceeded
        """
        built = _booking_open_with_ceilings(
            api, room_night_ceiling=50, contingency_liability_cap_cents=50000000
        )
        program_id = built["program"]["id"]
        before = fixtures.read_program(api, program_id)
        assert before["room_night_ceiling"] == 50
        assert before["committed_room_nights"] == 0

        response = api.create_reservation_block(
            reservation_block_payload(
                program_id,
                before["version"],
                account_name="Regatta Fleet",
                arrival_date="2026-10-05",
                night_count=4,
                room_count=19,
                rate_cents=20000,
            ),
            COMMERCIAL_DIRECTOR,
        )

        validate_error(response, ERR_ROOM_NIGHT_CEILING_EXCEEDED, 422)
        after = fixtures.read_program(api, program_id)
        assert after["committed_room_nights"] == 0
        assert_cents(after["contingency_liability_cents"], 0)

    def test_block_beyond_the_contingency_cap_is_refused(
        self, api: PreOpeningApiClient
    ) -> None:
        """The same seventy-six room-nights now fit under a ceiling of three
        hundred, so the acceptance reaches the money check. Seventy-six nights at
        the relocation rate give a base of 1900000 cents, an eight percent fee of
        152000 and a projection of 2052000 against a cap of one million.

        Three ceilings then apply: `committed_room_nights` plus the new block's `room_nights` may not be strictly greater than `room_night_ceiling`, else `ERR_ROOM_NIGHT_CEILING_EXCEEDED`; and the projected `contingency_liability_cents` after accepting the block — the existing liability plus this block's own `contingency_cents` — may not be strictly greater than `contingency_liability_cap_cents`, else `ERR_CONTINGENCY_LIABILITY_EXCEEDED`.

        Design: Corner/errors/block_beyond_liability_cap_returns_contingency_liability_exceeded
        """
        built = _booking_open_with_ceilings(
            api, room_night_ceiling=300, contingency_liability_cap_cents=1000000
        )
        program_id = built["program"]["id"]
        before = fixtures.read_program(api, program_id)
        assert before["room_night_ceiling"] == 300
        assert_cents(before["contingency_liability_cap_cents"], 1000000)
        assert_cents(before["contingency_liability_cents"], 0)

        response = api.create_reservation_block(
            reservation_block_payload(
                program_id,
                before["version"],
                account_name="Regatta Fleet",
                arrival_date="2026-10-05",
                night_count=4,
                room_count=19,
                rate_cents=20000,
            ),
            COMMERCIAL_DIRECTOR,
        )

        validate_error(response, ERR_CONTINGENCY_LIABILITY_EXCEEDED, 422)
        after = fixtures.read_program(api, program_id)
        assert_cents(after["contingency_liability_cents"], 0)
        assert after["committed_room_nights"] == 0


class TestStabilizationWindow:
    """Handover waits out the stabilization window after the soft opening."""

    def test_stabilizing_before_the_window_closes_is_refused(
        self, api: PreOpeningApiClient
    ) -> None:
        """A property has authorized a soft opening for the tenth of November with
        a thirty-day stabilization window, so handover cannot happen before the
        tenth of December. The clock still reads the end of October, and with no
        defect and no outstanding shipment the window is the only obstacle.

        Three conditions guard it: every punch-list item of the program must be `VERIFIED`, else `ERR_PUNCH_LIST_OPEN`; no OS&E order of the program may still be `COMMITTED` — every shipment either received or cancelled — else `ERR_OSE_ORDER_PENDING`; and the logical clock date must have reached or passed `soft_opening_date` plus the program's `stabilization_window_days`, else `ERR_STABILIZATION_WINDOW_NOT_ELAPSED`.

        Design: Corner/errors/stabilize_before_the_window_elapsed_returns_stabilization_window_not_elapsed
        """
        fixtures.set_clock(api, DEFAULT_NOW)
        built = fixtures.soft_opening_program(
            api,
            soft_opening_date="2026-11-10",
            authorized_by=AUTHORIZING_DIRECTOR,
            finish_iso="2026-10-31T00:00:00Z",
            duration_days=60,
            program_overrides=AURORA_PROGRAM,
        )
        program_id = built["program"]["id"]
        before = fixtures.read_program(api, program_id)
        assert before["schedule_state"] == "SOFT_OPENING"
        assert before["soft_opening_date"] == "2026-11-10"
        assert before["stabilization_window_days"] == 30
        _, punch_meta = validate_paginated(
            api.list_punch_items(QUALITY_INSPECTOR, {"program_id": program_id})
        )
        assert_page(punch_meta, total_count=0, has_more=False)
        _, order_meta = validate_paginated(
            api.list_ose_orders(PROCUREMENT_MANAGER, {"program_id": program_id})
        )
        assert_page(order_meta, total_count=0, has_more=False)

        response = api.transition_to_stabilized(program_id, PROGRAM_DIRECTOR)

        validate_error(response, ERR_STABILIZATION_WINDOW_NOT_ELAPSED, 422)
        after = fixtures.read_program(api, program_id)
        assert after["schedule_state"] == "SOFT_OPENING"
