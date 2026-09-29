"""Validation precedence and boundary precision.

Two families of behaviour live here. The first pits two genuinely violated
rules against each other on a single request and pins which identifier the API
must surface, following the fixed precedence of the specification. The second
walks the sharp edge of a threshold — a pass rate that lands exactly on the
certification floor, an empty milestone set, a pallet load that lands exactly
on the storage ceiling and the two strict comparisons that decide whether two
intervals contend for the same resource.
"""

from typing import Any, Dict

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_client import PreOpeningApiClient
from test_helpers.api_errors import (
    ERR_BOOKING_NOT_OPEN,
    ERR_DELIVERY_OUTSIDE_WINDOW,
    ERR_INVALID_SYSTEM_STATE,
    ERR_PROGRAM_FROZEN,
    ERR_ROOM_NIGHT_CEILING_EXCEEDED,
    ERR_SCHEDULE_EMPTY,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STORAGE_CAPACITY_EXCEEDED,
    ERR_SYSTEM_PASS_RATE_BELOW_THRESHOLD,
    ERR_TRAINING_ROOM_CONFLICT,
)
from test_helpers.assertions import (
    assert_budget_split,
    assert_cents,
    assert_ratio,
)
from test_helpers.constants import CODE_CONSTRUCTION_COMPLETE
from test_helpers.fixtures import (
    add_test_run,
    baseline,
    budget_line_version,
    complete_milestone,
    make_budget_line,
    make_milestone,
    make_ose_order,
    make_program,
    make_punch_item,
    make_system,
    make_training_session,
    open_booking,
    program_version,
    read_budget_lines,
    read_program,
    rule_on_punch_item,
    set_clock,
    start_milestone,
    submit_for_verification,
)
from test_helpers.test_users import (
    CERTIFYING_INTEGRATOR,
    COMMERCIAL_DIRECTOR,
    CONSTRUCTION_MANAGER,
    PROCUREMENT_MANAGER,
    PROGRAM_DIRECTOR,
    QUALITY_INSPECTOR,
    TALENT_MANAGER,
    TEST_RUNNER_INTEGRATOR,
    BASELINING_DIRECTOR,
)

# ─── File-local setup helpers ─────────────────────────────────────────────────


def _construction_complete_program(
    api: PreOpeningApiClient, duration_days: int = 90, **program_overrides: Any
) -> Dict[str, Any]:
    """A program driven to CONSTRUCTION_COMPLETE over 2026-09-01..2026-11-30.

    The single milestone carries the ``CONSTRUCTION_COMPLETE`` code, so its
    completion advances the delivery dimension. With a ninety-day duration and
    a fourteen-day licensing buffer the committed projection lands on
    2026-12-14.
    """
    program = make_program(api, **program_overrides)
    milestone = make_milestone(
        api,
        program["id"],
        code=CODE_CONSTRUCTION_COMPLETE,
        name="Construction complete",
        duration_days=duration_days,
        planned_start_date="2026-09-01",
    )
    baseline(api, program["id"], PROGRAM_DIRECTOR)
    set_clock(api, "2026-09-01T00:00:00Z", CONSTRUCTION_MANAGER)
    start_milestone(api, milestone["id"])
    set_clock(api, "2026-11-30T00:00:00Z", CONSTRUCTION_MANAGER)
    complete_milestone(api, milestone["id"])
    return {
        "program": read_program(api, program["id"]),
        "milestone": milestone,
    }


def _saltmarsh_program(api: PreOpeningApiClient) -> Dict[str, Any]:
    return _construction_complete_program(
        api,
        property_name="Saltmarsh Hotel",
        brand_code="SMH",
        room_count=100,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=60,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=10,
        contingency_liability_cap_cents=90000000,
        licensing_buffer_days=14,
    )


def _saltmarsh_block_payload(program_id: str, expected_program_version: int) -> Dict[str, Any]:
    return factories.reservation_block_payload(
        program_id,
        expected_program_version,
        account_name="Saltmarsh Tours",
        arrival_date="2026-12-01",
        night_count=4,
        room_count=19,
        rate_cents=20000,
    )


def _ironbark_program_with_committed_order(api: PreOpeningApiClient) -> Dict[str, Any]:
    """A FROZEN program holding one COMMITTED order whose window has closed."""
    program = make_program(
        api,
        property_name="Ironbark Hotel",
        brand_code="IBH",
        room_count=140,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=60,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=300,
        contingency_liability_cap_cents=90000000,
    )
    line = make_budget_line(api, program["id"], category="SETUP", authorized_cents=1000000)
    order = make_ose_order(
        api,
        program["id"],
        line["id"],
        line["version"],
        description="Guest room amenity kits",
        amount_cents=400000,
        pallet_count=6,
        delivery_window_start="2026-10-01",
        delivery_window_end="2026-10-10",
    )
    punch = make_punch_item(
        api,
        program["id"],
        headers=QUALITY_INSPECTOR,
        description="Sprinkler main not pressure tested",
        severity="CRITICAL",
    )
    set_clock(api, "2026-10-20T00:00:00Z", PROCUREMENT_MANAGER)
    return {
        "program": read_program(api, program["id"]),
        "budget_line": line,
        "order": order,
        "punch": punch,
    }


def _northgate_certified_system(api: PreOpeningApiClient) -> Dict[str, Any]:
    """A CERTIFIED PMS system whose only run was executed by si-runner-1."""
    program = make_program(
        api,
        property_name="Northgate Hotel",
        brand_code="NGH",
        room_count=110,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=60,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=300,
        contingency_liability_cap_cents=90000000,
    )
    system = make_system(api, program["id"], system_type="PMS", is_required=True)
    add_test_run(
        api,
        system["id"],
        "2026-09-10T10:00:00Z",
        40,
        40,
        headers=TEST_RUNNER_INTEGRATOR,
        blocker_count=0,
    )
    certified = get_success_data(api.certify_system(system["id"], CERTIFYING_INTEGRATOR))
    return {"program": program, "system": certified}


def _system_with_single_run(
    api: PreOpeningApiClient, cases_total: int, cases_passed: int
) -> Dict[str, Any]:
    """A PMS system in TESTING carrying exactly one run by si-runner-1."""
    program = make_program(
        api,
        property_name="Brightwater Hotel",
        brand_code="BWH",
        room_count=115,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=60,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=300,
        contingency_liability_cap_cents=90000000,
    )
    system = make_system(api, program["id"], system_type="PMS", is_required=True)
    run = add_test_run(
        api,
        system["id"],
        "2026-09-10T10:00:00Z",
        cases_total,
        cases_passed,
        headers=TEST_RUNNER_INTEGRATOR,
        blocker_count=0,
    )
    return {"program": program, "system": system, "run": run}


def _hollow_creek_program(api: PreOpeningApiClient) -> Dict[str, Any]:
    return make_program(
        api,
        property_name="Hollow Creek Lodge",
        brand_code="HCL",
        room_count=75,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=40,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=200,
        contingency_liability_cap_cents=90000000,
        licensing_buffer_days=14,
    )


def _storage_program(
    api: PreOpeningApiClient, property_name: str, brand_code: str, room_count: int
) -> Dict[str, Any]:
    """A program with forty pallet positions and a ten-million-cent SETUP line."""
    program = make_program(
        api,
        property_name=property_name,
        brand_code=brand_code,
        room_count=room_count,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=40,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=300,
        contingency_liability_cap_cents=90000000,
    )
    line = make_budget_line(api, program["id"], category="SETUP", authorized_cents=10000000)
    return {"program": program, "budget_line": line}


def _halden_court_program(api: PreOpeningApiClient) -> Dict[str, Any]:
    return make_program(
        api,
        property_name="Halden Court Hotel",
        brand_code="HCH",
        room_count=100,
        construction_start_date="2026-09-01",
        target_opening_date="2027-02-01",
        storage_capacity_pallets=60,
        relocation_rate_cents=25000,
        guarantee_penalty_cents=150000,
        room_night_ceiling=300,
        contingency_liability_cap_cents=90000000,
    )


# ─── Rule precedence: state before money ──────────────────────────────────────


class TestBookingClosedOutranksRoomNightCeiling:
    """A block that is both illegal and oversized reports the closed book."""

    def test_closed_book_is_the_surfaced_error(self, api: PreOpeningApiClient) -> None:
        """A property that never opened booking is offered a seventy-six
        room-night block against a ceiling of ten. Both the commercial state and
        the inventory ceiling forbid it, and the closed book is the answer.

        Blocks may not be created while the commercial dimension is anything other than `BOOKING_OPEN`, and the attempt is refused with `ERR_BOOKING_NOT_OPEN`; nor while the posture is `FROZEN`, refused with `ERR_PROGRAM_FROZEN`; nor at all once the delivery dimension has reached `STABILIZED`.

        Design: Difficulty/priority_pair_validation_conflict/booking_closed_state_outranks_room_night_ceiling_breach
        """
        built = _saltmarsh_program(api)
        program = built["program"]
        assert program["schedule_state"] == "CONSTRUCTION_COMPLETE"
        assert program["commercial_state"] == "BOOKING_CLOSED"

        response = api.create_reservation_block(
            _saltmarsh_block_payload(program["id"], program["version"]),
            COMMERCIAL_DIRECTOR,
        )

        validate_error(response, ERR_BOOKING_NOT_OPEN, 409)

    def test_rejected_block_leaves_the_inventory_counters_untouched(
        self, api: PreOpeningApiClient
    ) -> None:
        """The refused offer writes nothing: no block row, no held room-nights
        and no contingency exposure on the program.

        A block begins `ACCEPTED` with `at_risk_reason` null, raises the program's `committed_room_nights` by its `room_nights`, reruns the contingency computation and increments the program's `version` by one.

        Design: Difficulty/priority_pair_validation_conflict/booking_closed_state_outranks_room_night_ceiling_breach
        """
        built = _saltmarsh_program(api)
        program = built["program"]

        api.create_reservation_block(
            _saltmarsh_block_payload(program["id"], program["version"]),
            COMMERCIAL_DIRECTOR,
        )

        refreshed = read_program(api, program["id"])
        assert refreshed["committed_room_nights"] == 0
        assert_cents(refreshed["contingency_liability_cents"], 0)
        _, meta = validate_paginated(
            api.list_reservation_blocks(program["id"], COMMERCIAL_DIRECTOR)
        )
        assert meta["total_count"] == 0

    def test_ceiling_breach_is_real_and_surfaces_once_booking_is_open(
        self, api: PreOpeningApiClient
    ) -> None:
        """With the book opened and nothing else changed, the very same offer is
        refused for the inventory ceiling — the seventy-six room-nights really do
        break the ceiling of ten, so the earlier answer was a precedence choice.

        Three ceilings then apply: `committed_room_nights` plus the new block's `room_nights` may not be strictly greater than `room_night_ceiling`, else `ERR_ROOM_NIGHT_CEILING_EXCEEDED`; and the projected `contingency_liability_cents` after accepting the block — the existing liability plus this block's own `contingency_cents` — may not be strictly greater than `contingency_liability_cap_cents`, else `ERR_CONTINGENCY_LIABILITY_EXCEEDED`.

        Design: Difficulty/priority_pair_validation_conflict/booking_closed_state_outranks_room_night_ceiling_breach
        """
        built = _saltmarsh_program(api)
        program_id = built["program"]["id"]
        opened = open_booking(api, program_id)
        assert opened["commercial_state"] == "BOOKING_OPEN"
        assert opened["room_night_ceiling"] == 10

        response = api.create_reservation_block(
            _saltmarsh_block_payload(program_id, program_version(api, program_id)),
            COMMERCIAL_DIRECTOR,
        )

        validate_error(response, ERR_ROOM_NIGHT_CEILING_EXCEEDED, 422)
        assert read_program(api, program_id)["committed_room_nights"] == 0


# ─── Rule precedence: the freeze before the calendar ──────────────────────────


class TestFrozenPostureOutranksDeliveryWindow:
    """A late receipt on a frozen program reports the freeze, not the calendar."""

    def test_freeze_is_the_surfaced_error(self, api: PreOpeningApiClient) -> None:
        """An open critical defect has frozen the property, and the receiving
        team tries to book in a container ten days after its delivery window
        closed. The freeze is what the API reports.

        Receiving is also one of the five exposure-adding operations refused with `ERR_PROGRAM_FROZEN` while the posture is `FROZEN`.

        Design: Difficulty/priority_pair_validation_conflict/frozen_posture_outranks_delivery_window_violation
        """
        built = _ironbark_program_with_committed_order(api)
        assert built["program"]["readiness_posture"] == "FROZEN"

        response = api.receive_ose_order(
            built["order"]["id"],
            factories.receive_payload("BAY-3"),
            PROCUREMENT_MANAGER,
        )

        validate_error(response, ERR_PROGRAM_FROZEN, 422)

    def test_refused_receipt_moves_no_money_and_stores_no_bay(
        self, api: PreOpeningApiClient
    ) -> None:
        """The order stays committed, unreceived and unstored, and the budget
        line's commitment has not turned into spend.

        On success `received_at` and `stored_bay_code` are set, the money moves from commitment to spend — the line's `committed_cents` falls by `amount_cents` while its `spent_cents` rises by the same amount, leaving `available_cents` unchanged — the budget line's `version` increments by one, and the cost-at-completion computation reruns.

        Design: Difficulty/priority_pair_validation_conflict/frozen_posture_outranks_delivery_window_violation
        """
        built = _ironbark_program_with_committed_order(api)

        api.receive_ose_order(
            built["order"]["id"],
            factories.receive_payload("BAY-3"),
            PROCUREMENT_MANAGER,
        )

        order = get_success_data(
            api.get_ose_order(built["order"]["id"], PROCUREMENT_MANAGER)
        )
        assert order["state"] == "COMMITTED"
        assert order["received_at"] is None
        assert order["stored_bay_code"] is None

        line = read_budget_lines(api, built["program"]["id"])[0]
        assert_budget_split(line, 1000000, 400000, 0)
        assert_cents(line["available_cents"], 600000)

        program = read_program(api, built["program"]["id"])
        assert program["readiness_posture"] == "FROZEN"
        assert program["open_critical_punch_count"] == 1

    def test_delivery_window_breach_is_real_and_surfaces_once_the_freeze_lifts(
        self, api: PreOpeningApiClient
    ) -> None:
        """Verifying the critical defect clears the freeze; the same receipt at
        the same instant is then refused for falling outside the half-open
        delivery window, so the losing rule was genuinely broken all along.

        The receipt date, taken from the logical clock, must fall inside the half-open delivery window — on or after `delivery_window_start` and strictly before `delivery_window_end`; outside that, the request is refused with `ERR_DELIVERY_OUTSIDE_WINDOW`.

        Design: Difficulty/priority_pair_validation_conflict/frozen_posture_outranks_delivery_window_violation
        """
        built = _ironbark_program_with_committed_order(api)
        submit_for_verification(api, built["punch"]["id"], CONSTRUCTION_MANAGER)
        rule_on_punch_item(api, built["punch"]["id"], "VERIFY", QUALITY_INSPECTOR)
        cleared = read_program(api, built["program"]["id"])
        assert cleared["open_critical_punch_count"] == 0
        assert cleared["readiness_posture"] != "FROZEN"

        response = api.receive_ose_order(
            built["order"]["id"],
            factories.receive_payload("BAY-3"),
            PROCUREMENT_MANAGER,
        )

        validate_error(response, ERR_DELIVERY_OUTSIDE_WINDOW, 422)


# ─── Rule precedence: duty separation before entity state ─────────────────────


class TestSegregationOfDutiesOutranksSystemState:
    """The tester who signs off is refused on duty grounds, not state grounds."""

    def test_duty_separation_is_the_surfaced_error(self, api: PreOpeningApiClient) -> None:
        """The engineer who ran the property-management system tests tries to
        certify a system that another operator has already certified. Both the
        duty rule and the system's state forbid it; the duty rule answers.

        A system implementation may not be certified by the operator recorded as `executed_by_user_id` on its most recent test run.

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_certified_system_state
        """
        built = _northgate_certified_system(api)
        assert built["system"]["state"] == "CERTIFIED"

        response = api.certify_system(built["system"]["id"], TEST_RUNNER_INTEGRATOR)

        validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)

    def test_refused_certification_leaves_the_original_certifier_in_place(
        self, api: PreOpeningApiClient
    ) -> None:
        """The system keeps its certification and its original certifier, and
        the program's certified-system count does not move.

        On success `certified_by_user_id` is set to the acting operator and `certified_at` to the logical clock instant, the program's `certified_system_count` is recomputed, and the posture computation reruns.

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_certified_system_state
        """
        built = _northgate_certified_system(api)

        api.certify_system(built["system"]["id"], TEST_RUNNER_INTEGRATOR)

        system = get_success_data(
            api.get_system_implementation(built["system"]["id"], CERTIFYING_INTEGRATOR)
        )
        assert system["state"] == "CERTIFIED"
        assert system["certified_by_user_id"] == "si-certifier-2"
        assert read_program(api, built["program"]["id"])["certified_system_count"] == 1

    def test_already_certified_state_is_real_and_surfaces_for_a_clean_operator(
        self, api: PreOpeningApiClient
    ) -> None:
        """An operator with no duty conflict — the original certifier — meets the
        state rule instead, which proves the already-certified obstacle was real
        and merely outranked.

        Certifying a system that is `PLANNED`, `FAILED` or already `CERTIFIED` is refused with `ERR_INVALID_SYSTEM_STATE`.

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_certified_system_state
        """
        built = _northgate_certified_system(api)

        response = api.certify_system(built["system"]["id"], CERTIFYING_INTEGRATOR)

        validate_error(response, ERR_INVALID_SYSTEM_STATE, 409)


# ─── Boundary: the certification pass-rate floor ──────────────────────────────


class TestCertifyAtExactPassRateFloor:
    """Thirty-eight of forty cases is exactly the floor, and the floor passes."""

    def test_run_of_thirty_eight_of_forty_reads_as_a_passing_rate(
        self, api: PreOpeningApiClient
    ) -> None:
        """Thirty-eight of forty cases with no blockers is exactly nine five
        hundred in four-decimal terms, which is a passing run.

        Each run's `pass_rate` is `cases_passed` divided by `cases_total`, rounded half up to four decimal places, and its `result` is `PASSED` when that rounded pass rate is at least 0.95 **and** its `blocker_count` is zero, and `FAILED` otherwise.

        Design: Difficulty/boundary_precision_check/certify_at_exact_ninety_five_percent_latest_pass_rate
        """
        built = _system_with_single_run(api, 40, 38)

        assert_ratio(built["run"]["pass_rate"], 0.95)
        assert built["run"]["result"] == "PASSED"
        assert built["run"]["blocker_count"] == 0

    def test_certification_succeeds_exactly_on_the_floor(
        self, api: PreOpeningApiClient
    ) -> None:
        """Because the floor is a not-below comparison, the independent
        certifier may sign the system off at exactly nine five hundred.

        The system's `latest_pass_rate` must be at least 0.95, else `ERR_SYSTEM_PASS_RATE_BELOW_THRESHOLD` — and this reads the **latest** rate, never the pooled one, so a system whose `cumulative_pass_rate` sits comfortably above the floor but whose most recent run fell below it must still be refused.

        Design: Difficulty/boundary_precision_check/certify_at_exact_ninety_five_percent_latest_pass_rate
        """
        built = _system_with_single_run(api, 40, 38)

        response = api.certify_system(built["system"]["id"], CERTIFYING_INTEGRATOR)

        system = validate_success(response, 200)
        assert system["state"] == "CERTIFIED"
        assert system["certified_by_user_id"] == "si-certifier-2"
        assert_ratio(system["latest_pass_rate"], 0.95)
        assert_ratio(system["cumulative_pass_rate"], 0.95)
        assert system["test_run_count"] == 1

        program = read_program(api, built["program"]["id"])
        assert program["certified_system_count"] == 1
        assert program["required_system_count"] == 1

    def test_one_case_below_the_floor_is_refused(self, api: PreOpeningApiClient) -> None:
        """One case fewer — thirty-seven of forty, or nine two five zero — sits
        under the floor and cannot be certified.

        The system's `latest_pass_rate` must be at least 0.95, else `ERR_SYSTEM_PASS_RATE_BELOW_THRESHOLD` — and this reads the **latest** rate, never the pooled one, so a system whose `cumulative_pass_rate` sits comfortably above the floor but whose most recent run fell below it must still be refused.

        Design: Difficulty/boundary_precision_check/certify_at_exact_ninety_five_percent_latest_pass_rate
        """
        built = _system_with_single_run(api, 40, 37)
        assert_ratio(built["run"]["pass_rate"], 0.925)

        response = api.certify_system(built["system"]["id"], CERTIFYING_INTEGRATOR)

        validate_error(response, ERR_SYSTEM_PASS_RATE_BELOW_THRESHOLD, 422)
        system = get_success_data(
            api.get_system_implementation(built["system"]["id"], CERTIFYING_INTEGRATOR)
        )
        assert system["state"] == "TESTING"
        assert system["certified_by_user_id"] is None
        assert read_program(api, built["program"]["id"])["certified_system_count"] == 0


# ─── Boundary: the empty milestone set ────────────────────────────────────────


class TestBaselineWithEmptyMilestoneSet:
    """A plan of record needs at least one milestone to freeze."""

    def test_baselining_a_program_with_no_milestones_is_refused(
        self, api: PreOpeningApiClient
    ) -> None:
        """A director tries to freeze a plan of record before anyone has entered
        a single milestone. There is no network to run, so the call is refused.

        It requires the program to be in `PLANNING`, requires at least one milestone — a program with none is refused with `ERR_SCHEDULE_EMPTY` and no dates are written — and requires the dependency graph to be acyclic.

        Design: Difficulty/boundary_precision_check/baseline_schedule_with_zero_milestones_rejected_as_empty_set
        """
        program = _hollow_creek_program(api)

        response = api.baseline_schedule(program["id"], BASELINING_DIRECTOR)

        validate_error(response, ERR_SCHEDULE_EMPTY, 422)

    def test_refused_baseline_writes_no_dates_and_no_baselining_director(
        self, api: PreOpeningApiClient
    ) -> None:
        """Nothing at all is written: the program stays in planning, both
        projections stay null and the acting director is not recorded.

        Both projected opening dates, `projected_opening_date_optimistic` and `projected_opening_date_committed`, are null until the first schedule computation, as are `soft_opening_date`, `baselined_by_user_id` and `soft_opening_authorized_by_user_id`.

        Design: Difficulty/boundary_precision_check/baseline_schedule_with_zero_milestones_rejected_as_empty_set
        """
        program = _hollow_creek_program(api)

        api.baseline_schedule(program["id"], BASELINING_DIRECTOR)

        refreshed = read_program(api, program["id"])
        assert refreshed["schedule_state"] == "PLANNING"
        assert refreshed["projected_opening_date_committed"] is None
        assert refreshed["projected_opening_date_optimistic"] is None
        assert refreshed["projected_opening_date"] is None
        assert refreshed["schedule_slip_days"] == 0
        assert refreshed["critical_path_milestone_count"] == 0
        assert refreshed["baselined_by_user_id"] is None
        assert refreshed["version"] == program["version"]

    def test_one_milestone_is_enough_to_baseline(self, api: PreOpeningApiClient) -> None:
        """The other side of the empty-set edge: a single ninety-day milestone
        gives the run something to order, and the projection lands fourteen days
        after the network finishes.

        Baselining is the `ProgramDirector`'s act of freezing a plan of record: it moves the delivery dimension `PLANNING → BASELINED`, records the acting operator in `baselined_by_user_id`, runs the schedule computation and then the posture computation, and increments the program's `version` by one.

        Design: Difficulty/boundary_precision_check/baseline_schedule_with_zero_milestones_rejected_as_empty_set
        """
        program = _hollow_creek_program(api)
        make_milestone(
            api,
            program["id"],
            code=CODE_CONSTRUCTION_COMPLETE,
            name="Construction complete",
            duration_days=90,
            planned_start_date="2026-09-01",
        )

        response = api.baseline_schedule(program["id"], BASELINING_DIRECTOR)

        baselined = validate_success(response, 200)
        assert baselined["schedule_state"] == "BASELINED"
        assert baselined["baselined_by_user_id"] == "pd-baseline-1"
        assert baselined["projected_opening_date_committed"] == "2026-12-14"
        assert baselined["projected_opening_date_optimistic"] == "2026-12-14"
        assert baselined["projected_opening_date"] == "2026-12-14"
        assert baselined["schedule_slip_days"] == 0
        assert baselined["critical_path_milestone_count"] == 1


# ─── Boundary: the storage ceiling ────────────────────────────────────────────


class TestStorageLoadAtExactCapacity:
    """Forty pallets fit forty bays; the forty-first does not."""

    def test_overlapping_orders_summing_to_capacity_are_both_committed(
        self, api: PreOpeningApiClient
    ) -> None:
        """Twenty-five pallets of case goods and fifteen pallets of soft goods
        share the receiving area over overlapping windows, landing exactly on the
        forty available positions.

        If that occupied load plus the candidate's own `pallet_count` is **strictly greater** than the program's `storage_capacity_pallets`, the order is refused with `ERR_STORAGE_CAPACITY_EXCEEDED`; a total that lands exactly on the capacity is accepted.

        Design: Difficulty/boundary_precision_check/storage_load_accepts_exact_capacity_and_rejects_one_more_pallet
        """
        built = _storage_program(api, "Stonefield Hotel", "SFH", 125)
        program_id = built["program"]["id"]
        line = built["budget_line"]
        make_ose_order(
            api,
            program_id,
            line["id"],
            line["version"],
            description="Case goods - guest rooms",
            amount_cents=100000,
            pallet_count=25,
            delivery_window_start="2026-12-01",
            delivery_window_end="2026-12-10",
        )

        response = api.create_ose_order(
            factories.ose_order_payload(
                program_id,
                line["id"],
                budget_line_version(api, program_id, line["id"]),
                description="Soft goods - guest rooms",
                amount_cents=100000,
                pallet_count=15,
                delivery_window_start="2026-12-05",
                delivery_window_end="2026-12-15",
            ),
            PROCUREMENT_MANAGER,
        )

        order_b = validate_success(response, 201)
        assert order_b["state"] == "COMMITTED"
        assert order_b["pallet_count"] == 15

    def test_one_pallet_past_capacity_is_refused(self, api: PreOpeningApiClient) -> None:
        """A single extra trolley pallet inside the contended days would make
        forty-one against forty positions, so it is turned away and the
        receiving area keeps its two shipments.

        If that occupied load plus the candidate's own `pallet_count` is **strictly greater** than the program's `storage_capacity_pallets`, the order is refused with `ERR_STORAGE_CAPACITY_EXCEEDED`; a total that lands exactly on the capacity is accepted.

        Design: Difficulty/boundary_precision_check/storage_load_accepts_exact_capacity_and_rejects_one_more_pallet
        """
        built = _storage_program(api, "Stonefield Hotel", "SFH", 125)
        program_id = built["program"]["id"]
        line = built["budget_line"]
        make_ose_order(
            api,
            program_id,
            line["id"],
            line["version"],
            description="Case goods - guest rooms",
            amount_cents=100000,
            pallet_count=25,
            delivery_window_start="2026-12-01",
            delivery_window_end="2026-12-10",
        )
        make_ose_order(
            api,
            program_id,
            line["id"],
            budget_line_version(api, program_id, line["id"]),
            description="Soft goods - guest rooms",
            amount_cents=100000,
            pallet_count=15,
            delivery_window_start="2026-12-05",
            delivery_window_end="2026-12-15",
        )

        response = api.create_ose_order(
            factories.ose_order_payload(
                program_id,
                line["id"],
                budget_line_version(api, program_id, line["id"]),
                description="Banquet trolleys",
                amount_cents=50000,
                pallet_count=1,
                delivery_window_start="2026-12-06",
                delivery_window_end="2026-12-08",
            ),
            PROCUREMENT_MANAGER,
        )

        validate_error(response, ERR_STORAGE_CAPACITY_EXCEEDED, 422)
        _, meta = validate_paginated(
            api.list_ose_orders(PROCUREMENT_MANAGER, {"program_id": program_id})
        )
        assert meta["total_count"] == 2
        refreshed = read_budget_lines(api, program_id)[0]
        assert_cents(refreshed["committed_cents"], 200000)
        assert_cents(refreshed["available_cents"], 9800000)


# ─── Temporal overlap: the training-room turnover buffer ──────────────────────


class TestTrainingRoomTurnoverBuffer:
    """Rooms are single-occupancy and need half an hour on each side."""

    def test_session_starting_when_the_incumbent_ends_conflicts(
        self, api: PreOpeningApiClient
    ) -> None:
        """An afternoon brand-standards class is scheduled to start the moment
        the morning class ends, leaving no time to reset the room. The buffer
        makes that a conflict.

        Both comparisons are strict, which has a sharp practical edge: a candidate whose `starts_at` is exactly thirty minutes after an existing session's `ends_at` is accepted, while a candidate whose `starts_at` coincides exactly with an existing session's `ends_at` is rejected.

        Design: Difficulty/resource_temporal_overlap/training_room_rejects_session_inside_thirty_minute_turnover_buffer
        """
        program = _halden_court_program(api)
        make_training_session(
            api,
            program["id"],
            title="Brand standards - morning",
            training_room_code="TR-1",
            starts_at="2026-09-10T09:00:00Z",
            ends_at="2026-09-10T12:00:00Z",
            capacity=10,
            department="ALL",
        )

        response = api.create_training_session(
            factories.training_session_payload(
                program["id"],
                title="Brand standards - afternoon",
                training_room_code="TR-1",
                starts_at="2026-09-10T12:00:00Z",
                ends_at="2026-09-10T14:00:00Z",
                capacity=10,
                department="ALL",
            ),
            TALENT_MANAGER,
        )

        validate_error(response, ERR_TRAINING_ROOM_CONFLICT, 422)

    def test_conflicting_session_is_not_created_and_the_incumbent_is_untouched(
        self, api: PreOpeningApiClient
    ) -> None:
        """The calendar for the room still holds exactly one scheduled class,
        with nobody enrolled in it, and spare capacity cannot absorb the clash.

        Unlike storage, this resource has no aggregate capacity — a single overlapping session is a conflict regardless of either session's `capacity` or `enrolled_count`.

        Design: Difficulty/resource_temporal_overlap/training_room_rejects_session_inside_thirty_minute_turnover_buffer
        """
        program = _halden_court_program(api)
        morning = make_training_session(
            api,
            program["id"],
            title="Brand standards - morning",
            training_room_code="TR-1",
            starts_at="2026-09-10T09:00:00Z",
            ends_at="2026-09-10T12:00:00Z",
            capacity=10,
            department="ALL",
        )

        api.create_training_session(
            factories.training_session_payload(
                program["id"],
                title="Brand standards - afternoon",
                training_room_code="TR-1",
                starts_at="2026-09-10T12:00:00Z",
                ends_at="2026-09-10T14:00:00Z",
                capacity=10,
                department="ALL",
            ),
            TALENT_MANAGER,
        )

        sessions, meta = validate_paginated(
            api.list_training_sessions(
                program["id"], TALENT_MANAGER, {"training_room_code": "TR-1"}
            )
        )
        assert meta["total_count"] == 1
        assert sessions[0]["id"] == morning["id"]
        assert sessions[0]["state"] == "SCHEDULED"
        assert sessions[0]["enrolled_count"] == 0

    def test_session_starting_exactly_thirty_minutes_later_is_accepted(
        self, api: PreOpeningApiClient
    ) -> None:
        """Pushing the afternoon class back to half past noon buys exactly the
        turnover the rule demands, so the booking stands.

        Both comparisons are strict, which has a sharp practical edge: a candidate whose `starts_at` is exactly thirty minutes after an existing session's `ends_at` is accepted, while a candidate whose `starts_at` coincides exactly with an existing session's `ends_at` is rejected.

        Design: Difficulty/resource_temporal_overlap/training_room_rejects_session_inside_thirty_minute_turnover_buffer
        """
        program = _halden_court_program(api)
        make_training_session(
            api,
            program["id"],
            title="Brand standards - morning",
            training_room_code="TR-1",
            starts_at="2026-09-10T09:00:00Z",
            ends_at="2026-09-10T12:00:00Z",
            capacity=10,
            department="ALL",
        )

        response = api.create_training_session(
            factories.training_session_payload(
                program["id"],
                title="Brand standards - afternoon",
                training_room_code="TR-1",
                starts_at="2026-09-10T12:30:00Z",
                ends_at="2026-09-10T14:00:00Z",
                capacity=10,
                department="ALL",
            ),
            TALENT_MANAGER,
        )

        created = validate_success(response, 201)
        assert created["state"] == "SCHEDULED"
        assert created["starts_at"] == "2026-09-10T12:30:00Z"
        _, meta = validate_paginated(
            api.list_training_sessions(
                program["id"], TALENT_MANAGER, {"training_room_code": "TR-1"}
            )
        )
        assert meta["total_count"] == 2


# ─── Temporal overlap: touching delivery windows ──────────────────────────────


class TestTouchingDeliveryWindows:
    """Half-open day windows that merely touch do not contend for the bays."""

    def _wexley_with_first_wave(self, api: PreOpeningApiClient) -> Dict[str, Any]:
        built = _storage_program(api, "Wexley Hotel", "WXH", 128)
        built["order_a"] = make_ose_order(
            api,
            built["program"]["id"],
            built["budget_line"]["id"],
            built["budget_line"]["version"],
            description="Banquet chairs - wave 1",
            amount_cents=100000,
            pallet_count=40,
            delivery_window_start="2026-12-01",
            delivery_window_end="2026-12-10",
        )
        return built

    def test_second_full_load_starting_on_the_first_window_s_end_is_accepted(
        self, api: PreOpeningApiClient
    ) -> None:
        """The first forty-pallet wave of banquet chairs vacates the bays on the
        tenth of December, which is the day the second wave lands, so the room
        takes both.

        Touching windows do not overlap: when one window's end equals another's start, the earlier shipment's pallets are gone before the later shipment lands, so the bays are shared rather than contended.

        Design: Difficulty/resource_temporal_overlap/storage_load_ignores_touching_delivery_windows
        """
        built = self._wexley_with_first_wave(api)
        program_id = built["program"]["id"]
        line = built["budget_line"]

        response = api.create_ose_order(
            factories.ose_order_payload(
                program_id,
                line["id"],
                budget_line_version(api, program_id, line["id"]),
                description="Banquet chairs - wave 2",
                amount_cents=100000,
                pallet_count=40,
                delivery_window_start="2026-12-10",
                delivery_window_end="2026-12-20",
            ),
            PROCUREMENT_MANAGER,
        )

        order_b = validate_success(response, 201)
        assert order_b["state"] == "COMMITTED"
        assert order_b["pallet_count"] == 40
        assert order_b["delivery_window_start"] == "2026-12-10"
        assert built["order_a"]["delivery_window_end"] == order_b["delivery_window_start"]

    def test_both_waves_are_on_the_books_and_the_line_carries_both_commitments(
        self, api: PreOpeningApiClient
    ) -> None:
        """Eighty pallets in total sit in a forty-position room without conflict,
        because they never share a day, and both commitments are charged.

        Delivery windows are half-open day intervals, so two windows overlap exactly when the first window's start falls before the second window's end **and** the second window's start falls before the first window's end.

        Design: Difficulty/resource_temporal_overlap/storage_load_ignores_touching_delivery_windows
        """
        built = self._wexley_with_first_wave(api)
        program_id = built["program"]["id"]
        line = built["budget_line"]
        make_ose_order(
            api,
            program_id,
            line["id"],
            budget_line_version(api, program_id, line["id"]),
            description="Banquet chairs - wave 2",
            amount_cents=100000,
            pallet_count=40,
            delivery_window_start="2026-12-10",
            delivery_window_end="2026-12-20",
        )

        _, meta = validate_paginated(
            api.list_ose_orders(PROCUREMENT_MANAGER, {"program_id": program_id})
        )
        assert meta["total_count"] == 2
        refreshed = read_budget_lines(api, program_id)[0]
        assert_cents(refreshed["committed_cents"], 200000)
        assert_cents(refreshed["available_cents"], 9800000)

    def test_second_wave_landing_one_day_early_does_contend(
        self, api: PreOpeningApiClient
    ) -> None:
        """Moving the second wave one day earlier makes the windows genuinely
        share the ninth of December, and eighty pallets do not fit forty
        positions.

        The occupied load for a candidate order is the sum of `pallet_count` over every other order of the same program whose state is `COMMITTED` or `STORED` — cancelled orders have released their pallets — and whose window overlaps the candidate's by that rule.

        Design: Difficulty/resource_temporal_overlap/storage_load_ignores_touching_delivery_windows
        """
        built = self._wexley_with_first_wave(api)
        program_id = built["program"]["id"]
        line = built["budget_line"]

        response = api.create_ose_order(
            factories.ose_order_payload(
                program_id,
                line["id"],
                budget_line_version(api, program_id, line["id"]),
                description="Banquet chairs - wave 2",
                amount_cents=100000,
                pallet_count=40,
                delivery_window_start="2026-12-09",
                delivery_window_end="2026-12-20",
            ),
            PROCUREMENT_MANAGER,
        )

        validate_error(response, ERR_STORAGE_CAPACITY_EXCEEDED, 422)
        _, meta = validate_paginated(
            api.list_ose_orders(PROCUREMENT_MANAGER, {"program_id": program_id})
        )
        assert meta["total_count"] == 1
