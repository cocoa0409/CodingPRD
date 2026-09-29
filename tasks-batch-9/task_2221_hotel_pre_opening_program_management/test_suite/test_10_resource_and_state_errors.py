"""Resource-resolution, duplication, graph and wrong-state rejections.

These tests exercise the tiers of the validation order that fire before any
business ceiling is consulted: an identifier that resolves to nothing, a
per-program uniqueness collision, a dependency edge that is a duplicate or a
cycle, a transition whose source state no longer matches, and the two temporal
or eligibility guards on the training calendar.
"""

from typing import Any, Callable, Dict

import pytest
import requests

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_client import PreOpeningApiClient
from test_helpers.api_errors import (
    ERR_DEPENDENCY_CYCLE,
    ERR_DUPLICATE_DEPENDENCY,
    ERR_DUPLICATE_RESOURCE,
    ERR_INVALID_HIRE_STATE,
    ERR_INVALID_PERMIT_STATE,
    ERR_INVALID_PUNCH_ITEM_STATE,
    ERR_INVALID_RESERVATION_STATE,
    ERR_PREDECESSOR_NOT_COMPLETE,
    ERR_TEST_RUN_EMPTY,
    ERR_TRAINING_DEPARTMENT_MISMATCH,
    ERR_TRAINING_SESSION_NOT_ENDED,
    ERROR_HTTP_STATUS,
    NOT_FOUND_BY_RESOURCE,
)
from test_helpers.assertions import assert_cents, assert_page
from test_helpers.constants import CODE_CONSTRUCTION_COMPLETE, DEFAULT_NOW
from test_helpers.factories import (
    assign_orientation_payload,
    hire_response_payload,
    milestone_payload,
    ose_order_payload,
    permit_review_payload,
    punch_verify_payload,
    resolve_contingency_payload,
)
from test_helpers.factories import test_run_payload as build_test_run_payload
from test_helpers.test_users import (
    COMMERCIAL_DIRECTOR,
    CONSTRUCTION_MANAGER,
    LICENSING_COORDINATOR,
    PROCUREMENT_MANAGER,
    PROGRAM_DIRECTOR,
    QUALITY_INSPECTOR,
    SYSTEMS_INTEGRATOR,
    TALENT_MANAGER,
    TEST_RUNNER_INTEGRATOR,
)

COMPLETION_INSTANT = "2026-10-01T00:00:00Z"

Context = Dict[str, Any]
MissingReferenceCall = Callable[[PreOpeningApiClient, Context], requests.Response]


# ─── Shared setups ────────────────────────────────────────────────────────────


def _program_with_setup_line(api: PreOpeningApiClient) -> Context:
    """A PLANNING program plus one SETUP budget line authorized at 1000000 cents."""
    fixtures.set_clock(api, DEFAULT_NOW)
    program = fixtures.make_program(api)
    line = fixtures.make_budget_line(
        api, program["id"], category="SETUP", authorized_cents=1000000
    )
    return {"program": program, "budget_line": line}


def _program_with_replayable_children(api: PreOpeningApiClient) -> Context:
    """One program carrying a DRAFT permit, an ACCEPTED hire and an OPEN defect."""
    fixtures.set_clock(api, DEFAULT_NOW)
    program = fixtures.make_program(api)
    milestone = fixtures.make_milestone(
        api,
        program["id"],
        code=CODE_CONSTRUCTION_COMPLETE,
        name="Construction complete",
        duration_days=30,
        planned_start_date="2026-09-01",
    )
    permit = fixtures.make_permit(
        api, program["id"], milestone["id"], permit_type="ELEVATOR", review_days=21
    )
    plan = fixtures.make_hiring_plan(
        api,
        program["id"],
        department="ROOMS",
        headcount_target=4,
        wave_start_date="2026-09-10",
    )
    hire = fixtures.make_hire(
        api,
        plan["id"],
        full_name="A. Keeper",
        hourly_rate_cents=2500,
        scheduled_hours_per_day=8,
        start_date="2026-09-15",
    )
    fixtures.respond_to_offer(api, hire["id"], "ACCEPT")
    punch_item = fixtures.make_punch_item(
        api,
        program["id"],
        milestone_id=milestone["id"],
        description="Corridor paint touch-up",
        severity="MINOR",
    )
    return {
        "program": program,
        "milestone": milestone,
        "permit": permit,
        "plan": plan,
        "hire": hire,
        "punch_item": punch_item,
    }


def _two_milestone_chain(api: PreOpeningApiClient) -> Context:
    """Two milestones joined by a single finish-to-start edge with no lag."""
    fixtures.set_clock(api, DEFAULT_NOW)
    built = fixtures.program_with_milestones(
        api,
        milestones=[
            {
                "code": "STRUCTURE_TOPPED_OUT",
                "name": "Structure topped out",
                "duration_days": 20,
                "planned_start_date": "2026-09-01",
            },
            {
                "code": "MEP_ROUGH_IN",
                "name": "MEP rough-in",
                "duration_days": 15,
                "planned_start_date": "2026-09-02",
            },
        ],
        edges=[
            {
                "predecessor": "STRUCTURE_TOPPED_OUT",
                "successor": "MEP_ROUGH_IN",
                "dependency_type": "FINISH_START",
                "lag_days": 0,
            }
        ],
    )
    return {
        "program": built["program"],
        "predecessor": built["milestones"]["STRUCTURE_TOPPED_OUT"],
        "successor": built["milestones"]["MEP_ROUGH_IN"],
    }


# ─── The nine unresolvable-reference calls ────────────────────────────────────


def _read_missing_program(api: PreOpeningApiClient, ctx: Context) -> requests.Response:
    return api.get_program(NON_EXISTENT_UUID, PROGRAM_DIRECTOR)


def _read_missing_permit(api: PreOpeningApiClient, ctx: Context) -> requests.Response:
    return api.get_permit_application(NON_EXISTENT_UUID, LICENSING_COORDINATOR)


def _read_missing_system(api: PreOpeningApiClient, ctx: Context) -> requests.Response:
    return api.get_system_implementation(NON_EXISTENT_UUID, SYSTEMS_INTEGRATOR)


def _read_missing_hire(api: PreOpeningApiClient, ctx: Context) -> requests.Response:
    return api.get_hire(NON_EXISTENT_UUID, TALENT_MANAGER)


def _read_missing_order(api: PreOpeningApiClient, ctx: Context) -> requests.Response:
    return api.get_ose_order(NON_EXISTENT_UUID, PROCUREMENT_MANAGER)


def _read_missing_punch_item(api: PreOpeningApiClient, ctx: Context) -> requests.Response:
    return api.get_punch_item(NON_EXISTENT_UUID, QUALITY_INSPECTOR)


def _complete_missing_session(
    api: PreOpeningApiClient, ctx: Context
) -> requests.Response:
    return api.complete_training_session(NON_EXISTENT_UUID, TALENT_MANAGER)


def _guarantee_missing_block(
    api: PreOpeningApiClient, ctx: Context
) -> requests.Response:
    return api.guarantee_block(NON_EXISTENT_UUID, COMMERCIAL_DIRECTOR)


def _commit_order_against_missing_line(
    api: PreOpeningApiClient, ctx: Context
) -> requests.Response:
    """A body reference that resolves to nothing, with a valid version token."""
    return api.create_ose_order(
        ose_order_payload(
            ctx["program"]["id"],
            NON_EXISTENT_UUID,
            ctx["budget_line"]["version"],
            description="Orphan order",
            amount_cents=1000,
            pallet_count=1,
            delivery_window_start="2026-09-05",
            delivery_window_end="2026-09-15",
        ),
        PROCUREMENT_MANAGER,
    )


MISSING_REFERENCE_CALLS = [
    ("programs", _read_missing_program),
    ("permit-applications", _read_missing_permit),
    ("system-implementations", _read_missing_system),
    ("hires", _read_missing_hire),
    ("ose-orders", _read_missing_order),
    ("punch-list-items", _read_missing_punch_item),
    ("training-sessions", _complete_missing_session),
    ("reservation-blocks", _guarantee_missing_block),
    ("budget-lines", _commit_order_against_missing_line),
]


class TestUnresolvableReferences:
    """Every entity answers an unknown identifier with its own not-found error."""

    @pytest.mark.parametrize(
        "resource, call_with_missing_id",
        MISSING_REFERENCE_CALLS,
        ids=[resource for resource, _ in MISSING_REFERENCE_CALLS],
    )
    def test_each_entity_returns_its_own_not_found_error(
        self,
        api: PreOpeningApiClient,
        resource: str,
        call_with_missing_id: MissingReferenceCall,
    ) -> None:
        """Nine different entities are addressed with an identifier that no record
        carries. Each answers with the not-found error of that entity rather than
        one shared body, and the order commitment shows that an unresolvable
        budget line is caught before its version token is ever compared.

        The first identifier that resolves to nothing determines the error: `ERR_PROGRAM_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_PERMIT_APPLICATION_NOT_FOUND`, `ERR_SYSTEM_IMPLEMENTATION_NOT_FOUND`, `ERR_HIRING_PLAN_NOT_FOUND`, `ERR_HIRE_NOT_FOUND`, `ERR_TRAINING_SESSION_NOT_FOUND`, `ERR_BUDGET_LINE_NOT_FOUND`, `ERR_OSE_ORDER_NOT_FOUND`, `ERR_RESERVATION_BLOCK_NOT_FOUND` or `ERR_PUNCH_LIST_ITEM_NOT_FOUND`, each returned with HTTP 404.

        Design: Corner/errors/every_child_resource_id_that_does_not_resolve_returns_its_own_not_found_error
        """
        ctx = _program_with_setup_line(api)

        response = call_with_missing_id(api, ctx)

        expected = NOT_FOUND_BY_RESOURCE[resource]
        validate_error(response, expected, ERROR_HTTP_STATUS[expected])


class TestReplayedTransitions:
    """A finished action replayed answers with that entity's own state error."""

    @pytest.mark.parametrize(
        "entity, expected_error",
        [
            ("permit", ERR_INVALID_PERMIT_STATE),
            ("hire", ERR_INVALID_HIRE_STATE),
            ("punch_item", ERR_INVALID_PUNCH_ITEM_STATE),
        ],
    )
    def test_wrong_source_state_yields_the_entity_specific_conflict(
        self, api: PreOpeningApiClient, entity: str, expected_error: str
    ) -> None:
        """Three transitions are attempted from a source state that does not admit
        them: a review recorded against a still-drafted permit file, a second
        acceptance of an already accepted offer, and a verification of a defect
        that was never submitted. Each is a conflict named after its own entity.

        This covers the program's `schedule_state` and `commercial_state`, a milestone's state, a permit application's state, a system implementation's state, a hire's state, an order's state, a block's state and a punch item's state, and it yields the state error matching the resource: `ERR_INVALID_PROGRAM_STATE`, `ERR_INVALID_MILESTONE_STATE`, `ERR_INVALID_PERMIT_STATE`, `ERR_INVALID_SYSTEM_STATE`, `ERR_INVALID_HIRE_STATE`, `ERR_INVALID_OSE_ORDER_STATE`, `ERR_INVALID_RESERVATION_STATE`, `ERR_INVALID_PUNCH_ITEM_STATE`, or — where the obstacle is that the program is not accepting bookings — `ERR_BOOKING_NOT_OPEN`.

        Design: Corner/errors/replaying_a_finished_action_is_rejected_with_the_entity_specific_invalid_state_error
        """
        ctx = _program_with_replayable_children(api)

        if entity == "permit":
            response = api.record_permit_review(
                ctx["permit"]["id"],
                permit_review_payload("ISSUE"),
                LICENSING_COORDINATOR,
            )
        elif entity == "hire":
            response = api.respond_to_offer(
                ctx["hire"]["id"], hire_response_payload("ACCEPT"), TALENT_MANAGER
            )
        else:
            response = api.verify_punch_item(
                ctx["punch_item"]["id"],
                punch_verify_payload("VERIFY"),
                QUALITY_INSPECTOR,
            )

        validate_error(response, expected_error, 409)


class TestPerProgramUniqueness:
    """A milestone code may not be used twice inside one program."""

    def test_repeating_a_milestone_code_is_a_duplicate_resource(
        self, api: PreOpeningApiClient
    ) -> None:
        """A program already carries a milestone coded MEP_ROUGH_IN. A second
        milestone reusing that code, with a different name, duration and planned
        start, is refused, and the program's network still holds one milestone.

        Any of these collisions is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409).

        Design: Corner/errors/duplicate_milestone_code_returns_duplicate_resource
        """
        fixtures.set_clock(api, DEFAULT_NOW)
        program = fixtures.make_program(api)
        fixtures.make_milestone(
            api,
            program["id"],
            code="MEP_ROUGH_IN",
            name="MEP rough-in",
            duration_days=20,
            planned_start_date="2026-09-01",
        )

        response = api.create_milestone(
            milestone_payload(
                program["id"],
                code="MEP_ROUGH_IN",
                name="MEP rough-in (second pass)",
                duration_days=12,
                planned_start_date="2026-09-20",
            ),
            CONSTRUCTION_MANAGER,
        )

        validate_error(response, ERR_DUPLICATE_RESOURCE, 409)
        _, meta = validate_paginated(
            api.list_milestones(CONSTRUCTION_MANAGER, {"program_id": program["id"]})
        )
        assert_page(meta, total_count=1, has_more=False)


class TestDependencyGraphIntegrity:
    """The edge set stays acyclic and free of duplicated pairs."""

    def test_self_edge_and_closing_edge_are_both_cycles(
        self, api: PreOpeningApiClient
    ) -> None:
        """One edge already runs from the structural milestone into the rough-in
        milestone. An edge from a milestone to itself and an edge back from the
        rough-in to the structure are both refused, and neither is stored.

        An edge that would close a cycle in the program's milestone graph is refused with `ERR_DEPENDENCY_CYCLE`, and a self edge — the same milestone on both ends — counts as a cycle for this purpose.

        Design: Corner/errors/dependency_self_edge_and_closing_edge_return_dependency_cycle
        """
        ctx = _two_milestone_chain(api)
        predecessor_id = ctx["predecessor"]["id"]
        successor_id = ctx["successor"]["id"]

        self_edge = api.create_dependency(
            {
                "predecessor_milestone_id": predecessor_id,
                "successor_milestone_id": predecessor_id,
                "dependency_type": "FINISH_START",
                "lag_days": 0,
            },
            CONSTRUCTION_MANAGER,
        )
        validate_error(self_edge, ERR_DEPENDENCY_CYCLE, 422)

        closing_edge = api.create_dependency(
            {
                "predecessor_milestone_id": successor_id,
                "successor_milestone_id": predecessor_id,
                "dependency_type": "FINISH_START",
                "lag_days": 0,
            },
            CONSTRUCTION_MANAGER,
        )
        validate_error(closing_edge, ERR_DEPENDENCY_CYCLE, 422)

        _, meta = validate_paginated(
            api.list_dependencies(predecessor_id, CONSTRUCTION_MANAGER)
        )
        assert_page(meta, total_count=1, has_more=False)

    def test_repeating_a_pair_is_a_duplicate_dependency(
        self, api: PreOpeningApiClient
    ) -> None:
        """The same ordered pair of milestones is linked a second time, this time
        as a start-to-start edge with four days of lag. The pair is what is
        unique, so the second edge is refused and the stored edge is untouched.

        An edge that repeats an existing predecessor/successor pair is refused with `ERR_DUPLICATE_DEPENDENCY`.

        Design: Corner/errors/duplicate_dependency_pair_returns_duplicate_dependency
        """
        ctx = _two_milestone_chain(api)

        response = api.create_dependency(
            {
                "predecessor_milestone_id": ctx["predecessor"]["id"],
                "successor_milestone_id": ctx["successor"]["id"],
                "dependency_type": "START_START",
                "lag_days": 4,
            },
            CONSTRUCTION_MANAGER,
        )

        validate_error(response, ERR_DUPLICATE_DEPENDENCY, 422)
        edges, meta = validate_paginated(
            api.list_dependencies(ctx["successor"]["id"], CONSTRUCTION_MANAGER)
        )
        assert_page(meta, total_count=1, has_more=False)
        assert edges[0]["lag_days"] == 0

    def test_successor_cannot_start_before_its_predecessor_completes(
        self, api: PreOpeningApiClient
    ) -> None:
        """The network is baselined with both milestones still not started, so the
        program state admits a start. The rough-in milestone is nevertheless
        refused because the structural milestone it follows has not completed.

        Starting a milestone moves it `NOT_STARTED → IN_PROGRESS` and stamps `actual_start_date` from the logical clock date; it requires the program's delivery dimension to be one of `BASELINED`, `CONSTRUCTION_COMPLETE` or `LICENSING` (otherwise `ERR_INVALID_PROGRAM_STATE`), and it requires every predecessor joined by a `FINISH_START` edge to be `COMPLETE`, failing which the request is refused with `ERR_PREDECESSOR_NOT_COMPLETE`.

        Design: Corner/errors/successor_start_before_predecessor_complete_returns_predecessor_not_complete
        """
        ctx = _two_milestone_chain(api)
        program = fixtures.baseline(api, ctx["program"]["id"])
        assert program["schedule_state"] == "BASELINED"

        response = api.start_milestone(ctx["successor"]["id"], CONSTRUCTION_MANAGER)

        validate_error(response, ERR_PREDECESSOR_NOT_COMPLETE, 422)
        milestone = validate_success(
            api.get_milestone(ctx["successor"]["id"], CONSTRUCTION_MANAGER), 200
        )
        assert milestone["state"] == "NOT_STARTED"
        assert milestone["actual_start_date"] is None


class TestReservationBlockStateGuards:
    """One reservation error covers two different wrong-state paths."""

    def test_resolving_an_accepted_block_and_replaying_a_guarantee_both_conflict(
        self, api: PreOpeningApiClient
    ) -> None:
        """A regatta block of five rooms for two nights is accepted while booking
        is open. Settling it as though it were at risk is refused, the guarantee
        then succeeds once and adds the flat penalty, and the replayed guarantee
        is refused without charging a second penalty.

        Resolving a block that is not `AT_RISK` is refused with `ERR_INVALID_RESERVATION_STATE`.

        Design: Corner/errors/acting_on_a_block_in_the_wrong_state_returns_invalid_reservation_state
        """
        fixtures.set_clock(api, DEFAULT_NOW)
        built = fixtures.construction_complete_program(
            api, finish_iso=COMPLETION_INSTANT, duration_days=30
        )
        program_id = built["program"]["id"]
        fixtures.open_booking(api, program_id)
        block = fixtures.make_block(
            api,
            program_id,
            account_name="Harbour Regatta",
            arrival_date="2026-10-05",
            night_count=2,
            room_count=5,
            rate_cents=20000,
        )
        assert block["state"] == "ACCEPTED"

        refused_resolve = api.resolve_contingency(
            block["id"],
            resolve_contingency_payload("CANCEL"),
            COMMERCIAL_DIRECTOR,
        )
        validate_error(refused_resolve, ERR_INVALID_RESERVATION_STATE, 409)
        program = fixtures.read_program(api, program_id)
        assert program["committed_room_nights"] == 10
        assert_cents(program["contingency_liability_cents"], 262500)

        guaranteed = validate_success(
            api.guarantee_block(block["id"], COMMERCIAL_DIRECTOR), 200
        )
        assert guaranteed["state"] == "GUARANTEED"
        program = fixtures.read_program(api, program_id)
        assert_cents(program["contingency_liability_cents"], 412500)

        replayed = api.guarantee_block(block["id"], COMMERCIAL_DIRECTOR)
        validate_error(replayed, ERR_INVALID_RESERVATION_STATE, 409)
        program = fixtures.read_program(api, program_id)
        assert_cents(program["contingency_liability_cents"], 412500)


class TestTrainingCalendarGuards:
    """The calendar refuses an early delivery and a cross-department seat."""

    def test_completing_a_session_before_its_end_instant_is_refused(
        self, api: PreOpeningApiClient
    ) -> None:
        """A rooms orientation is scheduled for the afternoon of 14 September
        while the logical clock still reads the first of the month. Marking it
        delivered thirteen days early is refused and the session stays scheduled.

        A session is marked delivered by the `TalentManager`, moving it `SCHEDULED → COMPLETED`, only once the logical clock instant has reached or passed its `ends_at`; an earlier attempt is refused with `ERR_TRAINING_SESSION_NOT_ENDED`.

        Design: Corner/errors/complete_session_before_ends_at_returns_training_session_not_ended
        """
        fixtures.set_clock(api, DEFAULT_NOW)
        program = fixtures.make_program(api)
        session = fixtures.make_training_session(
            api,
            program["id"],
            title="Rooms orientation",
            training_room_code="TR-1",
            starts_at="2026-09-14T09:00:00Z",
            ends_at="2026-09-14T12:00:00Z",
            capacity=5,
            department="ROOMS",
        )

        response = api.complete_training_session(session["id"], TALENT_MANAGER)

        validate_error(response, ERR_TRAINING_SESSION_NOT_ENDED, 409)
        sessions, _ = validate_paginated(
            api.list_training_sessions(program["id"], TALENT_MANAGER)
        )
        unchanged = next(row for row in sessions if row["id"] == session["id"])
        assert unchanged["state"] == "SCHEDULED"

    def test_a_rooms_hire_cannot_take_a_food_and_beverage_seat(
        self, api: PreOpeningApiClient
    ) -> None:
        """A kitchen safety session has nine free seats out of ten, so nothing
        about capacity blocks the enrolment. The hire belongs to a rooms plan and
        the session is restricted to food and beverage, so the seat is refused.

        Two eligibility rules apply: enrolling a hire that would push the session's `enrolled_count` above its `capacity` is refused with `ERR_TRAINING_SESSION_FULL`, and a session whose `department` is neither `ALL` nor the `department` of the hire's plan is refused with `ERR_TRAINING_DEPARTMENT_MISMATCH`.

        Design: Corner/errors/assign_orientation_across_departments_returns_training_department_mismatch
        """
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
            title="Kitchen safety",
            training_room_code="TR-2",
            starts_at="2026-09-14T09:00:00Z",
            ends_at="2026-09-14T12:00:00Z",
            capacity=10,
            department="FOOD_BEVERAGE",
        )
        assert session["capacity"] == 10
        assert session["enrolled_count"] == 0
        hire = fixtures.make_hire(
            api,
            plan["id"],
            full_name="A. Keeper",
            hourly_rate_cents=2500,
            scheduled_hours_per_day=8,
            start_date="2026-09-15",
        )

        response = api.assign_orientation(
            hire["id"], assign_orientation_payload(session["id"]), TALENT_MANAGER
        )

        validate_error(response, ERR_TRAINING_DEPARTMENT_MISMATCH, 422)
        unchanged = validate_success(api.get_hire(hire["id"], TALENT_MANAGER), 200)
        assert unchanged["orientation_session_id"] is None


class TestEmptyTestRun:
    """A run with no cases defines no pass rate and is refused."""

    def test_a_run_with_zero_cases_is_rejected_as_empty(
        self, api: PreOpeningApiClient
    ) -> None:
        """A required key system has no evidence yet. A run claiming zero cases
        executed and zero passed is refused rather than stored as a zero pass
        rate, and the system keeps both of its pass-rate aggregates null.

        Cases passed may not exceed cases total, and both, along with the blocker count, must be zero or more; a run recorded with `cases_total` of zero defines no pass rate at all and is refused with `ERR_TEST_RUN_EMPTY`.

        Design: Corner/errors/test_run_with_zero_cases_returns_test_run_empty
        """
        fixtures.set_clock(api, DEFAULT_NOW)
        program = fixtures.make_program(api)
        system = fixtures.make_system(
            api, program["id"], system_type="KEY", is_required=True
        )

        response = api.create_test_run(
            system["id"],
            build_test_run_payload(
                "2026-09-01T09:00:00Z", cases_total=0, cases_passed=0, blocker_count=0
            ),
            TEST_RUNNER_INTEGRATOR,
        )

        validate_error(response, ERR_TEST_RUN_EMPTY, 422)
        unchanged = validate_success(
            api.get_system_implementation(system["id"], SYSTEMS_INTEGRATOR), 200
        )
        assert unchanged["state"] == "PLANNED"
        assert unchanged["latest_pass_rate"] is None
        assert unchanged["cumulative_pass_rate"] is None
        _, meta = validate_paginated(
            api.list_test_runs(system["id"], SYSTEMS_INTEGRATOR)
        )
        assert_page(meta, total_count=0, has_more=False)
