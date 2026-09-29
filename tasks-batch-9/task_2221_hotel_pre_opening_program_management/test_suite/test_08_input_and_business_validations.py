"""Input and business-rule validations across the pre-opening workflows.

Each test drives one named condition to its refusal or to its satisfied edge and
checks that the surfaced error identifier and HTTP status are the ones the PRD
names for that condition.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_ARRIVAL_DATE_IN_PAST,
    ERR_CROSS_PROGRAM_REFERENCE,
    ERR_HEADCOUNT_EXCEEDED,
    ERR_OSE_ORDER_PENDING,
    ERR_PERMIT_PREREQUISITE_NOT_MET,
    ERR_PUNCH_LIST_OPEN,
    ERR_START_BEFORE_WAVE,
)
from test_helpers.assertions import assert_cents, assert_program_dimensions
from test_helpers.constants import CODE_CONSTRUCTION_COMPLETE, ROLE_PROGRAM_DIRECTOR
from test_helpers.factories import (
    hire_payload,
    permit_payload,
    program_payload,
    reservation_block_payload,
    soft_opening_payload,
)
from test_helpers.fixtures import (
    booking_open_program,
    cancel_order,
    construction_complete_program,
    make_budget_line,
    make_hire,
    make_hiring_plan,
    make_milestone,
    make_ose_order,
    make_permit,
    make_program,
    make_punch_item,
    read_program,
    rule_on_punch_item,
    set_clock,
    soft_opening_ready_program,
    submit_for_verification,
)
from test_helpers.test_users import (
    COMMERCIAL_DIRECTOR,
    LICENSING_COORDINATOR,
    PROGRAM_DIRECTOR,
    TALENT_MANAGER,
    headers_for,
)

CLOCK_START = "2026-09-01T00:00:00Z"

AURORA_OVERRIDES = {
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


def _plan_by_id(api, program_id, plan_id):
    plans = validate_success(
            api.list_hiring_plans(program_id, TALENT_MANAGER), expected_status=200
        )
    return next(plan for plan in plans if plan["id"] == plan_id)


class TestStaggeredWaveStart:
    """A department's wave start date is the earliest payroll day for that team."""

    def test_start_date_before_the_wave_start_is_refused(self, api):
        """The rooms department cannot put anybody on payroll before its wave opens
        on 2026-09-10, so an offer with a first payroll day of 2026-09-05 is refused
        and the plan's offer count is untouched.

        Two ceilings guard the offer: a `start_date` earlier than the plan's `wave_start_date` is refused with `ERR_START_BEFORE_WAVE`, and an offer that would push the plan's `offered_count` above its `headcount_target` is refused with `ERR_HEADCOUNT_EXCEEDED`.

        Design: Corner/validations/hire_start_date_before_wave_start_returns_start_before_wave
        """
        set_clock(api, CLOCK_START)
        program = make_program(api)
        plan = make_hiring_plan(
            api,
            program["id"],
            department="ROOMS",
            headcount_target=4,
            wave_start_date="2026-09-10",
        )

        response = api.create_hire(
            hire_payload(
                plan["id"],
                full_name="A. Early",
                hourly_rate_cents=2500,
                scheduled_hours_per_day=8,
                start_date="2026-09-05",
            ),
            TALENT_MANAGER,
        )
        validate_error(response, ERR_START_BEFORE_WAVE, expected_status=422)

        assert _plan_by_id(api, program["id"], plan["id"])["offered_count"] == 0

    def test_start_date_equal_to_the_wave_start_is_accepted(self, api):
        """The comparison is on a strictly earlier start date, so a first payroll day
        falling exactly on the wave start is inside the window and the offer is
        extended.

        Two ceilings guard the offer: a `start_date` earlier than the plan's `wave_start_date` is refused with `ERR_START_BEFORE_WAVE`, and an offer that would push the plan's `offered_count` above its `headcount_target` is refused with `ERR_HEADCOUNT_EXCEEDED`.

        Design: Corner/validations/hire_start_date_equal_to_wave_start_is_accepted
        """
        set_clock(api, CLOCK_START)
        program = make_program(api)
        plan = make_hiring_plan(
            api,
            program["id"],
            department="ROOMS",
            headcount_target=4,
            wave_start_date="2026-09-10",
        )

        response = api.create_hire(
            hire_payload(
                plan["id"],
                full_name="B. Exact",
                hourly_rate_cents=2500,
                scheduled_hours_per_day=8,
                start_date="2026-09-10",
            ),
            TALENT_MANAGER,
        )
        hire = validate_success(response, expected_status=201)

        assert hire["start_date"] == "2026-09-10"
        assert hire["state"] == "OFFERED"
        assert _plan_by_id(api, program["id"], plan["id"])["offered_count"] == 1


class TestHeadcountCeiling:
    """The approved headcount is an aggregate ceiling over the plan's live offers."""

    def test_third_offer_beyond_the_headcount_target_is_refused(self, api):
        """Two offers already fill an approved headcount of two. A third offer is
        individually well formed but breaches the collective ceiling, so it is
        refused and the plan stays at two.

        Two ceilings guard the offer: a `start_date` earlier than the plan's `wave_start_date` is refused with `ERR_START_BEFORE_WAVE`, and an offer that would push the plan's `offered_count` above its `headcount_target` is refused with `ERR_HEADCOUNT_EXCEEDED`.

        Design: Corner/validations/third_offer_beyond_headcount_target_returns_headcount_exceeded
        """
        set_clock(api, CLOCK_START)
        program = make_program(api)
        plan = make_hiring_plan(
            api,
            program["id"],
            department="ROOMS",
            headcount_target=2,
            wave_start_date="2026-09-10",
        )

        for name in ("A. One", "B. Two"):
            make_hire(
                api,
                plan["id"],
                full_name=name,
                hourly_rate_cents=2500,
                scheduled_hours_per_day=8,
                start_date="2026-09-15",
            )
        assert _plan_by_id(api, program["id"], plan["id"])["offered_count"] == 2

        response = api.create_hire(
            hire_payload(
                plan["id"],
                full_name="C. Three",
                hourly_rate_cents=2500,
                scheduled_hours_per_day=8,
                start_date="2026-09-15",
            ),
            TALENT_MANAGER,
        )
        validate_error(response, ERR_HEADCOUNT_EXCEEDED, expected_status=422)

        assert _plan_by_id(api, program["id"], plan["id"])["offered_count"] == 2


class TestPermitSequencing:
    """The prerequisite map is keyed on the permit type being submitted."""

    def _two_draft_permits(self, api):
        built = construction_complete_program(
            api, finish_iso="2026-10-01T00:00:00Z", duration_days=30
        )
        program_id = built["program"]["id"]
        gating_id = built["milestones"][CODE_CONSTRUCTION_COMPLETE]["id"]
        liquor = make_permit(
            api, program_id, gating_id, permit_type="LIQUOR_LICENSE", review_days=45
        )
        elevator = make_permit(
            api, program_id, gating_id, permit_type="ELEVATOR", review_days=21
        )
        return {"program": built["program"], "liquor": liquor, "elevator": elevator}

    def test_liquor_license_cannot_be_submitted_before_its_prerequisites(self, api):
        """A liquor licence sits at the end of the sequence: it needs both the
        certificate of occupancy and the food-service approval in hand. Neither
        application even exists, so the submission is refused.

        The sequence is short but strict — a `CERTIFICATE_OF_OCCUPANCY` requires the `ELEVATOR` approval to be issued first, and a `LIQUOR_LICENSE` requires both the `CERTIFICATE_OF_OCCUPANCY` and the `FOOD_SERVICE` approvals to be issued first; `FOOD_SERVICE`, `ELEVATOR`, `FIRE_ALARM` and `SIGNAGE` have no permit prerequisites of their own.

        Design: Corner/validations/prerequisite_rule_applies_to_liquor_license_but_not_to_elevator
        """
        set_clock(api, CLOCK_START)
        built = self._two_draft_permits(api)

        response = api.submit_permit_application(
            built["liquor"]["id"], LICENSING_COORDINATOR
        )
        validate_error(response, ERR_PERMIT_PREREQUISITE_NOT_MET, expected_status=422)

    def test_elevator_carries_no_prerequisite_and_moves_the_program_to_licensing(
        self, api
    ):
        """The elevator approval has no permit prerequisite of its own, so it submits
        from the very same state in the same programme. Being the first mandatory
        file to reach the authority, it also moves the delivery dimension.

        The sequence is short but strict — a `CERTIFICATE_OF_OCCUPANCY` requires the `ELEVATOR` approval to be issued first, and a `LIQUOR_LICENSE` requires both the `CERTIFICATE_OF_OCCUPANCY` and the `FOOD_SERVICE` approvals to be issued first; `FOOD_SERVICE`, `ELEVATOR`, `FIRE_ALARM` and `SIGNAGE` have no permit prerequisites of their own.

        Design: Corner/validations/prerequisite_rule_applies_to_liquor_license_but_not_to_elevator
        """
        set_clock(api, CLOCK_START)
        built = self._two_draft_permits(api)

        response = api.submit_permit_application(
            built["elevator"]["id"], LICENSING_COORDINATOR
        )
        submitted = validate_success(response, expected_status=200)

        assert submitted["state"] == "SUBMITTED"
        assert submitted["is_mandatory"] is True

        program = read_program(api, built["program"]["id"])
        assert_program_dimensions(program, schedule_state="LICENSING")


class TestArrivalDateAgainstTheLogicalClock:
    """Every "now" comparison reads the injected logical clock, not wall time."""

    def test_arrival_date_behind_the_clock_date_is_refused(self, api):
        """The logical clock has been driven to 2026-10-01 by the construction
        completion, so a group arriving on 2026-09-25 is asking for a room-night
        that is already in the past.

        An `arrival_date` earlier than the logical clock date is refused with `ERR_ARRIVAL_DATE_IN_PAST`.

        Design: Corner/validations/reservation_block_arrival_before_clock_returns_arrival_date_in_past
        """
        set_clock(api, CLOCK_START)
        built = booking_open_program(
            api, finish_iso="2026-10-01T00:00:00Z", duration_days=30
        )
        program = built["program"]

        assert_program_dimensions(
            program,
            schedule_state="CONSTRUCTION_COMPLETE",
            commercial_state="BOOKING_OPEN",
        )
        assert program["committed_room_nights"] == 0

        response = api.create_reservation_block(
            reservation_block_payload(
                program["id"],
                program["version"],
                account_name="Backdated Group",
                arrival_date="2026-09-25",
                night_count=2,
                room_count=5,
                rate_cents=20000,
            ),
            COMMERCIAL_DIRECTOR,
        )
        validate_error(response, ERR_ARRIVAL_DATE_IN_PAST, expected_status=422)

        refreshed = read_program(api, program["id"])
        assert refreshed["committed_room_nights"] == 0
        assert_cents(refreshed["contingency_liability_cents"], 0)


class TestCrossProgramReferences:
    """Cross-aggregate references must stay inside one pre-opening programme."""

    def test_gating_milestone_from_another_program_is_refused(self, api):
        """The permit application names a milestone that belongs to a second hotel.
        Both identifiers resolve, so this is a boundary violation rather than a
        missing record.

        A reference that crosses a program boundary is rejected with `ERR_CROSS_PROGRAM_REFERENCE` (HTTP 422).

        Design: Corner/validations/cross_program_gating_milestone_returns_cross_program_reference
        """
        set_clock(api, CLOCK_START)
        program = make_program(api)
        other = validate_success(
                api.create_program(
                    program_payload(
                        property_name="Marble Court Hotel",
                        brand_code="MCH",
                        room_count=90,
                        storage_capacity_pallets=30,
                    ),
                    PROGRAM_DIRECTOR,
                ),
                expected_status=201,
            )
        other_milestone = make_milestone(
            api,
            other["id"],
            code=CODE_CONSTRUCTION_COMPLETE,
            name="Construction complete",
            duration_days=30,
            planned_start_date="2026-09-01",
        )

        response = api.create_permit_application(
            permit_payload(
                program["id"],
                other_milestone["id"],
                permit_type="ELEVATOR",
                review_days=21,
            ),
            LICENSING_COORDINATOR,
        )
        # The milestone exists, so the boundary error must win over any not-found.
        validate_error(response, ERR_CROSS_PROGRAM_REFERENCE, expected_status=422)


class TestStabilizationClosureGates:
    """Handing the property to operations audits the punch list and the order book."""

    def test_open_punch_item_then_pending_order_are_surfaced_in_turn(self, api):
        """The stabilization window has already elapsed, so the run exposes the two
        closure gates in the order the specification lists them: the open defect
        first, then the still-committed shipment, and only then the handover.

        Three conditions guard it: every punch-list item of the program must be `VERIFIED`, else `ERR_PUNCH_LIST_OPEN`; no OS&E order of the program may still be `COMMITTED` — every shipment either received or cancelled — else `ERR_OSE_ORDER_PENDING`; and the logical clock date must have reached or passed `soft_opening_date` plus the program's `stabilization_window_days`, else `ERR_STABILIZATION_WINDOW_NOT_ELAPSED`.

        Design: Corner/validations/stabilization_gates_reject_open_punch_then_pending_order
        """
        set_clock(api, CLOCK_START)
        built = soft_opening_ready_program(
            api,
            finish_iso="2026-10-31T00:00:00Z",
            duration_days=60,
            program_overrides=dict(AURORA_OVERRIDES),
        )
        program_id = built["program"]["id"]
        gating_id = built["milestones"][CODE_CONSTRUCTION_COMPLETE]["id"]

        authorizer = headers_for(ROLE_PROGRAM_DIRECTOR, "pd-authorizer-2")
        soft_opened = validate_success(
                api.authorize_soft_opening(
                    program_id, soft_opening_payload("2026-11-10"), authorizer
                ),
                expected_status=200,
            )
        assert_program_dimensions(soft_opened, schedule_state="SOFT_OPENING")
        assert soft_opened["soft_opening_date"] == "2026-11-10"

        punch_item = make_punch_item(
            api,
            program_id,
            description="Lobby signage alignment",
            severity="MINOR",
            milestone_id=gating_id,
        )
        line = make_budget_line(
            api, program_id, category="SETUP", authorized_cents=1000000
        )
        order = make_ose_order(
            api,
            program_id,
            line["id"],
            line["version"],
            description="Banquet chairs",
            amount_cents=400000,
            pallet_count=5,
            delivery_window_start="2026-12-15",
            delivery_window_end="2026-12-25",
        )

        # 2026-11-10 plus the thirty-day stabilization window lands exactly here,
        # so the temporal gate is satisfied for every attempt below.
        set_clock(api, "2026-12-10T00:00:00Z")

        validate_error(
            api.transition_to_stabilized(program_id, PROGRAM_DIRECTOR),
            ERR_PUNCH_LIST_OPEN,
            expected_status=422,
        )

        submit_for_verification(api, punch_item["id"])
        verified = rule_on_punch_item(api, punch_item["id"], "VERIFY")
        assert verified["state"] == "VERIFIED"

        validate_error(
            api.transition_to_stabilized(program_id, PROGRAM_DIRECTOR),
            ERR_OSE_ORDER_PENDING,
            expected_status=422,
        )

        cancelled = cancel_order(api, order["id"])
        assert cancelled["state"] == "CANCELLED"

        stabilized = validate_success(
                api.transition_to_stabilized(program_id, PROGRAM_DIRECTOR),
                expected_status=200,
            )
        assert_program_dimensions(stabilized, schedule_state="STABILIZED")
