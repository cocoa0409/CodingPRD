"""Entity state machines: initial states, illegal hops, guards and cascades.

The Hotel Pre-Opening Program Management PRD fixes both the legal source state
of every transition and the side effects each one must apply. This module walks
the milestone, hire, OS&E order, system, training-session and programme
lifecycles, including the two-dimensional programme record whose delivery and
commercial dimensions move independently.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_INVALID_MILESTONE_STATE,
    ERR_INVALID_OSE_ORDER_STATE,
    ERR_INVALID_PROGRAM_STATE,
    ERR_OPEN_BLOCKERS_PRESENT,
    ERR_SOFT_OPENING_DATE_INVALID,
    ERR_TRAINING_SESSION_HAS_ENROLLMENTS,
)
from test_helpers.assertions import (
    assert_budget_split,
    assert_cents,
    assert_committed_is_authority,
    assert_program_dimensions,
    assert_ratio,
)
from test_helpers.constants import (
    CODE_CONSTRUCTION_COMPLETE,
    ROLE_PROGRAM_DIRECTOR,
)
from test_helpers.fixtures import (
    add_test_run,
    cancel_order,
    construction_complete_program,
    make_budget_line,
    make_hiring_plan,
    make_milestone,
    make_ose_order,
    make_system,
    make_training_session,
    open_booking,
    read_budget_lines,
    read_program,
)
from test_helpers.test_users import (
    CERTIFYING_INTEGRATOR,
    COMMERCIAL_DIRECTOR,
    CONSTRUCTION_MANAGER,
    PROCUREMENT_MANAGER,
    PROGRAM_DIRECTOR,
    SYSTEMS_INTEGRATOR,
    TALENT_MANAGER,
    TEST_RUNNER_INTEGRATOR,
    headers_for,
)

# The operator who authorizes the soft opening, distinct from the baselining
# director so that the duty-separation rule is satisfied.
SOFT_OPENING_AUTHORIZER = headers_for(ROLE_PROGRAM_DIRECTOR, "pd-authorizer-2")


def _thirty_day_construction_program(api):
    """A programme driven to CONSTRUCTION_COMPLETE on a single 30-day milestone.

    The milestone is started while the logical clock reads 2026-09-01 and
    completed after the clock has moved to 2026-10-01, so the actual duration is
    thirty whole days and the committed projection adds the fourteen-day
    licensing buffer to give 2026-10-15.
    """
    return construction_complete_program(
        api, finish_iso="2026-10-01T00:00:00Z", duration_days=30
    )


class TestMilestoneLifecycle:
    """Milestone execution: the legal source states and the completion cascade."""

    def test_milestone_complete_from_not_started_returns_invalid_milestone_state(
        self, api, program
    ):
        """A construction manager tries to sign off a milestone that has never
        been started. Completion is only reachable from work in progress, so the
        call is refused and no actual finish date is stamped.

        Completing a milestone moves it `IN_PROGRESS → COMPLETE`, but only if no punch-list item attributed to that milestone has `severity` `CRITICAL` and a state other than `VERIFIED`; such a defect blocks completion with `ERR_CRITICAL_PUNCH_OPEN`.

        Design: Corner/state_machines/milestone_complete_from_not_started_returns_invalid_milestone_state
        """
        milestone = make_milestone(
            api,
            program["id"],
            code="STRUCTURE_TOPPED_OUT",
            name="Structure topped out",
            duration_days=30,
            planned_start_date="2026-09-01",
        )
        assert milestone["state"] == "NOT_STARTED"

        validate_error(
            api.complete_milestone(milestone["id"], CONSTRUCTION_MANAGER),
            ERR_INVALID_MILESTONE_STATE,
            expected_status=409,
        )

        unchanged = validate_success(
            api.get_milestone(milestone["id"], CONSTRUCTION_MANAGER)
        )
        assert unchanged["state"] == "NOT_STARTED"
        assert unchanged["actual_finish_date"] is None
        assert unchanged["actual_duration_days"] is None

    def test_milestone_complete_writes_actual_duration_and_advances_program(
        self, api, clock_at_default
    ):
        """The construction-complete milestone runs from 1 September to 1 October
        and is signed off. One call must stamp the actual dates, recompute the
        critical path and bubble the delivery dimension forward.

        Completion then cascades: the program's critical path is recomputed; if the milestone's `code` is `CONSTRUCTION_COMPLETE` the delivery dimension advances `BASELINED → CONSTRUCTION_COMPLETE`; the readiness posture is recomputed; and because the projected opening date has moved, the cost-at-completion figures are recomputed as well — the payroll accrual horizon travels with the schedule.

        Design: Corner/state_machines/milestone_complete_writes_actual_duration_and_advances_program_to_construction_complete
        """
        built = _thirty_day_construction_program(api)

        completed = built["milestones"][CODE_CONSTRUCTION_COMPLETE]
        assert completed["state"] == "COMPLETE"
        assert completed["actual_start_date"] == "2026-09-01"
        assert completed["actual_finish_date"] == "2026-10-01"
        assert completed["actual_duration_days"] == 30

        data = validate_success(api.get_program(built["program"]["id"], PROGRAM_DIRECTOR))
        assert_program_dimensions(data, schedule_state="CONSTRUCTION_COMPLETE")
        assert data["projected_opening_date_committed"] == "2026-10-15"
        assert_committed_is_authority(data)
        assert data["schedule_slip_days"] == 0
        assert data["critical_path_milestone_count"] == 1


class TestHireInitialState:
    """A new offer enters the hire lifecycle at its declared initial state."""

    def test_hire_created_starts_in_offered(self, api, program):
        """A rooms plan approved for four people receives its first offer. The
        hire starts as an outstanding offer with no accrual and no onboarding
        instant, and only the offered counter on the plan moves.

        A hire begins in `OFFERED` with `accrual_cents` at 0 and `onboarded_at` null, and the plan's `offered_count` rises by one.

        Design: Corner/state_machines/hire_created_starts_in_offered
        """
        plan = make_hiring_plan(
            api,
            program["id"],
            department="ROOMS",
            headcount_target=4,
            wave_start_date="2026-09-10",
        )
        assert plan["offered_count"] == 0

        hire = validate_success(
            api.create_hire(
                factories.hire_payload(
                    plan["id"],
                    full_name="R. Alvarez",
                    hourly_rate_cents=2500,
                    scheduled_hours_per_day=8,
                    start_date="2026-09-15",
                ),
                TALENT_MANAGER,
            ),
            201,
        )
        assert hire["state"] == "OFFERED"
        assert_cents(hire["accrual_cents"], 0)
        assert hire["onboarded_at"] is None
        assert hire["orientation_session_id"] is None

        plans, _ = validate_paginated(
            api.list_hiring_plans(program["id"], TALENT_MANAGER)
        )
        refreshed = next(row for row in plans if row["id"] == plan["id"])
        assert refreshed["offered_count"] == 1
        assert refreshed["accepted_count"] == 0
        assert refreshed["onboarded_count"] == 0
        assert_ratio(refreshed["staffing_ratio"], 0.0)
        assert refreshed["readiness_flag"] == "NOT_READY"


class TestOseOrderTerminalStates:
    """A cancelled shipment has left the order lifecycle for good."""

    def test_cancelled_ose_order_cannot_be_received(self, api, program):
        """Linen worth 400,000 cents is committed against the setup line and then
        cancelled when the vendor withdraws. Receiving the same shipment
        afterwards must fail, leaving the released budget untouched.

        An order that is not `COMMITTED` can be neither received nor cancelled, and either attempt is refused with `ERR_INVALID_OSE_ORDER_STATE`.

        Design: Corner/state_machines/cancelled_ose_order_cannot_be_received
        """
        line = make_budget_line(
            api, program["id"], category="SETUP", authorized_cents=1000000
        )
        order = make_ose_order(
            api,
            program["id"],
            line["id"],
            line["version"],
            description="Guest room linen",
            amount_cents=400000,
            pallet_count=5,
            delivery_window_start="2026-09-05",
            delivery_window_end="2026-09-15",
        )
        cancelled = cancel_order(api, order["id"])
        assert cancelled["state"] == "CANCELLED"

        validate_error(
            api.receive_ose_order(
                order["id"], factories.receive_payload("BAY-01"), PROCUREMENT_MANAGER
            ),
            ERR_INVALID_OSE_ORDER_STATE,
            expected_status=409,
        )

        after = next(
            row
            for row in read_budget_lines(api, program["id"])
            if row["id"] == line["id"]
        )
        assert_budget_split(
            after, authorized_cents=1000000, committed_cents=0, spent_cents=0
        )
        assert validate_success(
            api.get_ose_order(order["id"], PROCUREMENT_MANAGER)
        )["state"] == "CANCELLED"


class TestSystemCertificationGuards:
    """Certification reads the latest run's blocker count, not just its pass rate."""

    def test_certify_with_open_blocker_returns_open_blockers_present(
        self, api, program
    ):
        """The property-management system passes all forty cases but the run still
        closes with one blocking defect open. A perfect pass rate does not buy a
        certificate while a blocker stands.

        Its `open_blocker_count` must be zero, else `ERR_OPEN_BLOCKERS_PRESENT`. If `prerequisite_system_id` is set, the system it names must itself be `CERTIFIED`, else `ERR_PREREQUISITE_SYSTEM_NOT_CERTIFIED`.

        Design: Corner/state_machines/certify_with_open_blocker_returns_open_blockers_present
        """
        system = make_system(api, program["id"], system_type="PMS", is_required=True)
        run = add_test_run(
            api,
            system["id"],
            "2026-09-01T10:00:00Z",
            40,
            40,
            headers=TEST_RUNNER_INTEGRATOR,
            blocker_count=1,
        )
        assert_ratio(run["pass_rate"], 1.0)
        assert run["result"] == "FAILED"

        after_run = validate_success(
            api.get_system_implementation(system["id"], SYSTEMS_INTEGRATOR)
        )
        assert after_run["state"] == "TESTING"
        assert after_run["open_blocker_count"] == 1
        assert_ratio(after_run["latest_pass_rate"], 1.0)

        validate_error(
            api.certify_system(system["id"], CERTIFYING_INTEGRATOR),
            ERR_OPEN_BLOCKERS_PRESENT,
            expected_status=422,
        )

        still_testing = validate_success(
            api.get_system_implementation(system["id"], SYSTEMS_INTEGRATOR)
        )
        assert still_testing["state"] == "TESTING"
        assert still_testing["certified_by_user_id"] is None
        assert still_testing["certified_at"] is None


class TestTrainingSessionCancellationGuard:
    """A session holding an enrolment cannot be cancelled."""

    def test_training_session_cancel_with_enrollment_returns_has_enrollments(
        self, api, program
    ):
        """One rooms orientation in room TR-1 already holds a single enrolled
        candidate when the trainer falls through. The cancellation is refused
        because the seat is taken, whatever the session's dates say.

        A session may instead be cancelled, moving it `SCHEDULED → CANCELLED` with an optional `reason`, but only while it is empty: a session whose `enrolled_count` is above zero is refused with `ERR_TRAINING_SESSION_HAS_ENROLLMENTS`.

        Design: Corner/state_machines/training_session_cancel_with_enrollment_returns_has_enrollments
        """
        plan = make_hiring_plan(
            api,
            program["id"],
            department="ROOMS",
            headcount_target=4,
            wave_start_date="2026-09-10",
        )
        session = make_training_session(
            api,
            program["id"],
            title="Rooms orientation",
            training_room_code="TR-1",
            starts_at="2026-09-14T09:00:00Z",
            ends_at="2026-09-14T12:00:00Z",
            capacity=5,
            department="ROOMS",
        )
        assert session["enrolled_count"] == 0

        validate_success(
            api.create_hire(
                factories.hire_payload(
                    plan["id"],
                    session["id"],
                    full_name="R. Alvarez",
                    hourly_rate_cents=2500,
                    scheduled_hours_per_day=8,
                    start_date="2026-09-15",
                ),
                TALENT_MANAGER,
            ),
            201,
        )

        sessions, _ = validate_paginated(
            api.list_training_sessions(program["id"], TALENT_MANAGER)
        )
        enrolled = next(row for row in sessions if row["id"] == session["id"])
        assert enrolled["enrolled_count"] == 1

        validate_error(
            api.cancel_training_session(
                session["id"], TALENT_MANAGER, {"reason": "Trainer unavailable"}
            ),
            ERR_TRAINING_SESSION_HAS_ENROLLMENTS,
            expected_status=409,
        )

        after, _ = validate_paginated(
            api.list_training_sessions(program["id"], TALENT_MANAGER)
        )
        assert next(row for row in after if row["id"] == session["id"])["state"] == (
            "SCHEDULED"
        )


class TestCommercialDimensionCycle:
    """The commercial dimension may be suspended and reopened without limit."""

    def test_second_open_booking_on_open_program_returns_invalid_program_state(
        self, api, clock_at_default
    ):
        """Booking acceptance is opened once and the call is then replayed. There
        is no legal source state for opening a book that is already open, so the
        replay is rejected and the commercial dimension stands still.

        A `CommercialDirector` opens booking acceptance, moving the commercial dimension `BOOKING_CLOSED → BOOKING_OPEN`.

        Design: Corner/state_machines/second_open_booking_on_open_program_returns_invalid_program_state
        """
        built = _thirty_day_construction_program(api)
        program_id = built["program"]["id"]

        opened = open_booking(api, program_id)
        assert_program_dimensions(opened, commercial_state="BOOKING_OPEN")
        version_after_open = opened["version"]

        validate_error(
            api.open_booking(program_id, COMMERCIAL_DIRECTOR),
            ERR_INVALID_PROGRAM_STATE,
            expected_status=409,
        )

        after = read_program(api, program_id)
        assert_program_dimensions(
            after,
            schedule_state="CONSTRUCTION_COMPLETE",
            commercial_state="BOOKING_OPEN",
        )
        assert after["version"] == version_after_open

    def test_commercial_state_cycles_open_suspended_open_and_bumps_version_each_hop(
        self, api, clock_at_default
    ):
        """Sales are opened, paused during a permit review and opened again. Each
        hop is legal, each consumes exactly one programme version, and the
        delivery dimension is never disturbed.

        The `CommercialDirector` may also suspend acceptance manually with an optional `reason`, moving the commercial dimension `BOOKING_OPEN → BOOKING_SUSPENDED` and incrementing the program's `version` by one.

        Design: Corner/state_machines/commercial_state_cycles_open_suspended_open_and_bumps_version_each_hop
        """
        built = _thirty_day_construction_program(api)
        program_id = built["program"]["id"]
        version_before = read_program(api, program_id)["version"]

        opened = validate_success(api.open_booking(program_id, COMMERCIAL_DIRECTOR))
        assert opened["commercial_state"] == "BOOKING_OPEN"
        assert opened["version"] == version_before + 1

        suspended = validate_success(
            api.suspend_booking(
                program_id,
                COMMERCIAL_DIRECTOR,
                {"reason": "Sales pause during permit review"},
            )
        )
        assert suspended["commercial_state"] == "BOOKING_SUSPENDED"
        assert suspended["version"] == version_before + 2

        reopened = validate_success(api.open_booking(program_id, COMMERCIAL_DIRECTOR))
        assert reopened["commercial_state"] == "BOOKING_OPEN"
        assert reopened["version"] == version_before + 3
        assert reopened["schedule_state"] == "CONSTRUCTION_COMPLETE"


class TestSoftOpeningAuthorization:
    """The most heavily guarded delivery transition, LICENSING to SOFT_OPENING."""

    def test_soft_opening_date_after_committed_projection_is_refused(
        self, api, soft_opening_ready
    ):
        """Every licensing, punch, systems and staffing gate holds, but the
        director nominates 20 November while the committed projection stands at
        14 November. The date window alone defeats the call.

        The supplied `soft_opening_date` must fall on or after the logical clock date and on or before `projected_opening_date_committed`, else `ERR_SOFT_OPENING_DATE_INVALID`.

        Design: Corner/state_machines/soft_opening_authorized_when_every_licensing_gate_is_satisfied
        """
        program_id = soft_opening_ready["program"]["id"]
        before = read_program(api, program_id)
        assert before["schedule_state"] == "LICENSING"
        assert before["projected_opening_date_committed"] == "2026-11-14"

        validate_error(
            api.authorize_soft_opening(
                program_id,
                factories.soft_opening_payload("2026-11-20"),
                SOFT_OPENING_AUTHORIZER,
            ),
            ERR_SOFT_OPENING_DATE_INVALID,
            expected_status=422,
        )

        after = read_program(api, program_id)
        assert after["schedule_state"] == "LICENSING"
        assert after["soft_opening_date"] is None
        assert after["soft_opening_authorized_by_user_id"] is None

    def test_soft_opening_authorized_when_every_licensing_gate_is_satisfied(
        self, api, soft_opening_ready
    ):
        """All four mandatory permits are issued, no defect is open, no system is
        required and the single rooms department is onboarded. A date inside the
        window then carries the delivery dimension into soft opening.

        On success `soft_opening_date` and `soft_opening_authorized_by_user_id` are set, the posture computation reruns, and the program's `version` increments by one.

        Design: Corner/state_machines/soft_opening_authorized_when_every_licensing_gate_is_satisfied
        """
        program_id = soft_opening_ready["program"]["id"]
        before = read_program(api, program_id)
        assert before["schedule_state"] == "LICENSING"
        assert before["issued_mandatory_permit_count"] == 4
        assert before["open_critical_punch_count"] == 0
        assert before["required_system_count"] == 0
        assert before["certified_system_count"] == 0
        assert before["hiring_plan_count"] == 1
        assert before["departments_ready_count"] == 1
        assert before["projected_opening_date_committed"] == "2026-11-14"

        data = validate_success(
            api.authorize_soft_opening(
                program_id,
                factories.soft_opening_payload("2026-11-10"),
                SOFT_OPENING_AUTHORIZER,
            )
        )

        assert_program_dimensions(
            data, schedule_state="SOFT_OPENING", readiness_posture="MOBILIZING"
        )
        assert data["soft_opening_date"] == "2026-11-10"
        assert data["soft_opening_authorized_by_user_id"] == "pd-authorizer-2"
        assert data["version"] == before["version"] + 1

        readiness = validate_success(api.get_readiness(program_id, PROGRAM_DIRECTOR))
        assert_ratio(readiness["readiness_score"], 0.7)
        assert readiness["readiness_posture"] == "MOBILIZING"
        assert_cents(readiness["payroll_accrual_cents"], 1200000)
