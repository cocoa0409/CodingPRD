"""Composite setup helpers.

Everything here builds preconditions through the published API only, so each
test starts from an empty database and walks the same lifecycle a real operator
would. Setup calls use ``get_success_data`` so that a broken precondition reads
as a setup failure rather than as a compliance failure.

Layered roughly by depth:

* single-resource creators (``create_station`` .. ``create_hiring_roster``)
* state progression (``publish_shift``, ``seat_member``, ``complete_shift``)
* entity hierarchy (``standup_station``)
* lifecycle shortcuts (``staffed_shift_via_overtime``, ``approved_leave_with_backfill``)
* threshold targeting (``push_scheduled_hours_to``)
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import SHIFT_DATE_PLATOON_C
from .test_users import (
    PAYROLL_ANALYST,
    STAFFING_OFFICER,
    make_company_officer_headers,
    make_firefighter_headers,
)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(api, now: str) -> None:
    """Move the logical duty clock to a named UTC instant."""
    get_success_data(api.set_clock(now, STAFFING_OFFICER))


# ---------------------------------------------------------------------------
# Single-resource creators
# ---------------------------------------------------------------------------
def create_station(api, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_station(f.station_payload(**overrides), STAFFING_OFFICER)
    )


def create_apparatus(api, station_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_apparatus(
            f.apparatus_payload(station_id, **overrides), STAFFING_OFFICER
        )
    )


def create_firefighter(api, station_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_firefighter(
            f.firefighter_payload(station_id, **overrides), STAFFING_OFFICER
        )
    )


def create_hiring_roster(
    api,
    station_id: str,
    roster_type: str = "VOLUNTARY_OT",
    certification_scope: str = "NONE",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_hiring_roster(
            f.hiring_roster_payload(
                station_id,
                roster_type=roster_type,
                certification_scope=certification_scope,
            ),
            STAFFING_OFFICER,
        )
    )


def create_duty_shift(
    api, station_id: str, shift_date: str = SHIFT_DATE_PLATOON_C, platoon: str = "C"
) -> Dict[str, Any]:
    return get_success_data(
        api.create_duty_shift(
            f.duty_shift_payload(station_id, shift_date=shift_date, platoon=platoon),
            STAFFING_OFFICER,
        )
    )


# ---------------------------------------------------------------------------
# Reads used to thread derived state through a setup chain
# ---------------------------------------------------------------------------
def read_station(api, station_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_station(station_id, STAFFING_OFFICER))


def read_firefighter(api, firefighter_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_firefighter(firefighter_id, STAFFING_OFFICER))


def read_shift(api, duty_shift_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_duty_shift(duty_shift_id, STAFFING_OFFICER))


def shift_version(api, duty_shift_id: str) -> int:
    """Re-read the shift's current version before an optimistically locked write."""
    return read_shift(api, duty_shift_id)["version"]


def read_assignment(api, assignment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_shift_assignment(assignment_id, STAFFING_OFFICER))


def read_vacancy(api, vacancy_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_vacancy(vacancy_id, STAFFING_OFFICER))


def read_offer(api, offer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_overtime_offer(offer_id, STAFFING_OFFICER))


def read_leave(api, leave_request_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_leave_request(leave_request_id, STAFFING_OFFICER))


def read_trade(api, trade_request_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_trade_request(trade_request_id, STAFFING_OFFICER))


def read_work_period(api, work_period_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_work_period(work_period_id, PAYROLL_ANALYST))


def work_period_of(api, firefighter_id: str) -> Dict[str, Any]:
    """The work period opened when the member was enrolled."""
    data = get_success_data(
        api.list_work_periods(PAYROLL_ANALYST, firefighter_id=firefighter_id)
    )
    assert data, f"no work period exists for firefighter {firefighter_id}"
    return data[0]


def work_periods_of(api, firefighter_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_work_periods(PAYROLL_ANALYST, firefighter_id=firefighter_id)
    )


def list_vacancies(api, **filters) -> List[Dict[str, Any]]:
    return get_success_data(api.list_vacancies(STAFFING_OFFICER, **filters))


def first_vacancy(api, **filters) -> Dict[str, Any]:
    rows = list_vacancies(api, **filters)
    assert rows, f"no vacancy matched {filters}"
    return rows[0]


def list_assignments(api, **filters) -> List[Dict[str, Any]]:
    return get_success_data(api.list_shift_assignments(STAFFING_OFFICER, **filters))


def list_offers(api, **filters) -> List[Dict[str, Any]]:
    return get_success_data(api.list_overtime_offers(STAFFING_OFFICER, **filters))


# ---------------------------------------------------------------------------
# State progression
# ---------------------------------------------------------------------------
def publish_shift(api, duty_shift_id: str) -> Dict[str, Any]:
    return get_success_data(api.publish_duty_shift(duty_shift_id, STAFFING_OFFICER))


def seat_member(
    api,
    duty_shift_id: str,
    firefighter_id: str,
    apparatus_id: str,
    officer_id: str,
    expected_duty_shift_version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """Seat one member, re-reading the shift version unless one is supplied."""
    version = (
        expected_duty_shift_version
        if expected_duty_shift_version is not None
        else shift_version(api, duty_shift_id)
    )
    payload = f.shift_assignment_payload(
        duty_shift_id, firefighter_id, apparatus_id, version, **overrides
    )
    return get_success_data(
        api.create_shift_assignment(payload, make_company_officer_headers(officer_id))
    )


def cancel_seat(
    api,
    assignment_id: str,
    officer_id: str,
    reason: str = "member reported sick before the tour began",
) -> Dict[str, Any]:
    return get_success_data(
        api.cancel_shift_assignment(
            assignment_id, {"reason": reason}, make_company_officer_headers(officer_id)
        )
    )


def set_availability(
    api,
    firefighter_id: str,
    effective_date: str = "2026-08-05",
    employment_status: Optional[str] = None,
    roster_standing: Optional[str] = None,
    expected_firefighter_version: Optional[int] = None,
) -> Dict[str, Any]:
    version = (
        expected_firefighter_version
        if expected_firefighter_version is not None
        else read_firefighter(api, firefighter_id)["version"]
    )
    return get_success_data(
        api.set_availability(
            firefighter_id,
            f.availability_payload(
                version,
                effective_date=effective_date,
                employment_status=employment_status,
                roster_standing=roster_standing,
            ),
            STAFFING_OFFICER,
        )
    )


def file_leave(
    api,
    firefighter_id: str,
    duty_shift_id: str,
    leave_type: str = "VACATION",
    requested_hours: int = 24,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_leave_request(
            f.leave_request_payload(
                firefighter_id,
                duty_shift_id,
                leave_type=leave_type,
                requested_hours=requested_hours,
            ),
            make_firefighter_headers(firefighter_id),
        )
    )


def adjudicate_leave(api, duty_shift_id: str, officer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.leave_adjudication(duty_shift_id, make_company_officer_headers(officer_id))
    )


def revoke_leave(api, leave_request_id: str, firefighter_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.revoke_leave_request(
            leave_request_id, make_firefighter_headers(firefighter_id)
        )
    )


def dispatch_offer(
    api, vacancy_id: str, hiring_mode: str = "VOLUNTARY", offer_hours: int = 24
) -> Dict[str, Any]:
    return get_success_data(
        api.offer_vacancy(
            vacancy_id, f.offer_payload(hiring_mode, offer_hours), STAFFING_OFFICER
        )
    )


def answer_offer(
    api, offer_id: str, firefighter_id: str, response: str = "ACCEPT"
) -> Dict[str, Any]:
    return get_success_data(
        api.respond_to_offer(
            offer_id, {"response": response}, make_firefighter_headers(firefighter_id)
        )
    )


def assignment_from_offer(api, offer_id: str) -> Dict[str, Any]:
    rows = list_assignments(api, source_offer_id=offer_id)
    assert rows, f"no assignment was created from offer {offer_id}"
    return rows[0]


def adjust_hours(
    api,
    work_period_id: str,
    adjustment_hours: int,
    adjustment_basis: str = "SCHEDULED",
    reason: str = "carry-in hours from the prior 7(k) period",
) -> Dict[str, Any]:
    return get_success_data(
        api.hour_adjustment(
            work_period_id,
            f.hour_adjustment_payload(adjustment_hours, adjustment_basis, reason),
            PAYROLL_ANALYST,
        )
    )


def run_staffing_checkpoint(api, duty_shift_id: str) -> Dict[str, Any]:
    return get_success_data(api.staffing_run(duty_shift_id, STAFFING_OFFICER))


def close_company(
    api,
    duty_shift_id: str,
    justification: str = "battalion cannot fill the remaining seats for this tour",
    expected_duty_shift_version: Optional[int] = None,
) -> Dict[str, Any]:
    version = (
        expected_duty_shift_version
        if expected_duty_shift_version is not None
        else shift_version(api, duty_shift_id)
    )
    return get_success_data(
        api.company_closure(
            duty_shift_id, f.closure_payload(version, justification), STAFFING_OFFICER
        )
    )


def complete_shift(api, duty_shift_id: str) -> Dict[str, Any]:
    return get_success_data(api.complete_duty_shift(duty_shift_id, PAYROLL_ANALYST))


def propose_trade(
    api,
    requesting_firefighter_id: str,
    counterparty_firefighter_id: str,
    duty_shift_id: str,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_trade_request(
            f.trade_request_payload(
                requesting_firefighter_id, counterparty_firefighter_id, duty_shift_id
            ),
            make_firefighter_headers(requesting_firefighter_id),
        )
    )


def countersign_trade(api, trade_id: str, counterparty_firefighter_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.countersign_trade_request(
            trade_id, make_firefighter_headers(counterparty_firefighter_id)
        )
    )


def decide_trade(
    api, trade_id: str, officer_id: str, decision: str, note: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api.decide_trade_request(
            trade_id, payload, make_company_officer_headers(officer_id)
        )
    )


# ---------------------------------------------------------------------------
# Entity hierarchy
# ---------------------------------------------------------------------------
def standup_station(
    api,
    station: Optional[Dict[str, Any]] = None,
    companies: Optional[List[Dict[str, Any]]] = None,
    members: Optional[List[Dict[str, Any]]] = None,
    rosters: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Create a station with its companies, members and hiring rosters.

    ``companies``, ``members`` and ``rosters`` are lists of override dicts. The
    return value carries the created rows in creation order under the keys
    ``station``, ``companies``, ``members`` and ``rosters``.
    """
    station_row = create_station(api, **(station or {}))
    company_rows = [
        create_apparatus(api, station_row["id"], **spec) for spec in (companies or [])
    ]
    member_rows = [
        create_firefighter(api, station_row["id"], **spec) for spec in (members or [])
    ]
    roster_rows = [
        create_hiring_roster(api, station_row["id"], **spec) for spec in (rosters or [])
    ]
    return {
        "station": station_row,
        "companies": company_rows,
        "members": member_rows,
        "rosters": roster_rows,
    }


def published_shift(
    api,
    station_id: str,
    shift_date: str = SHIFT_DATE_PLATOON_C,
    platoon: str = "C",
) -> Dict[str, Any]:
    """Open a shift and publish it so its open seats become vacancies."""
    shift = create_duty_shift(api, station_id, shift_date=shift_date, platoon=platoon)
    return publish_shift(api, shift["id"])


def published_shift_with_seats(
    api,
    station_id: str,
    seats: List[Dict[str, Any]],
    officer_id: str,
    shift_date: str = SHIFT_DATE_PLATOON_C,
    platoon: str = "C",
) -> Dict[str, Any]:
    """Publish a shift then seat each entry of ``seats`` in order.

    Every entry needs ``firefighter_id`` and ``apparatus_id``; any other key is
    passed through as an assignment override.
    """
    shift = published_shift(api, station_id, shift_date=shift_date, platoon=platoon)
    assignments = []
    for seat in seats:
        spec = dict(seat)
        firefighter_id = spec.pop("firefighter_id")
        apparatus_id = spec.pop("apparatus_id")
        assignments.append(
            seat_member(api, shift["id"], firefighter_id, apparatus_id, officer_id, **spec)
        )
    return {"shift": read_shift(api, shift["id"]), "assignments": assignments}


# ---------------------------------------------------------------------------
# Lifecycle shortcuts
# ---------------------------------------------------------------------------
def hire_into_vacancy(
    api,
    vacancy_id: str,
    firefighter_id: str,
    hiring_mode: str = "VOLUNTARY",
    offer_hours: int = 24,
) -> Dict[str, Any]:
    """Dispatch an offer on a vacancy and have the named member accept it."""
    offer = dispatch_offer(api, vacancy_id, hiring_mode, offer_hours)
    assert offer["firefighter_id"] == firefighter_id, (
        f"hiring order dispatched to {offer['firefighter_id']}, "
        f"expected {firefighter_id}"
    )
    answer_offer(api, offer["id"], firefighter_id, "ACCEPT")
    return {
        "offer": read_offer(api, offer["id"]),
        "assignment": assignment_from_offer(api, offer["id"]),
        "vacancy": read_vacancy(api, vacancy_id),
    }


def staffed_shift_via_overtime(
    api,
    station_id: str,
    duty_shift_id: str,
    firefighter_id: str,
    hiring_mode: str = "VOLUNTARY",
    offer_hours: int = 24,
) -> Dict[str, Any]:
    """Fill the shift's single open vacancy by hiring the named member."""
    vacancy = first_vacancy(api, duty_shift_id=duty_shift_id, status="OPEN")
    hired = hire_into_vacancy(
        api, vacancy["id"], firefighter_id, hiring_mode, offer_hours
    )
    hired["shift"] = read_shift(api, duty_shift_id)
    hired["station"] = read_station(api, station_id)
    return hired


def approved_leave_with_backfill(
    api,
    duty_shift_id: str,
    firefighter_id: str,
    officer_id: str,
    leave_type: str = "VACATION",
    requested_hours: int = 24,
) -> Dict[str, Any]:
    """File leave, adjudicate it, and return the leave plus its backfill vacancy."""
    leave = file_leave(
        api, firefighter_id, duty_shift_id, leave_type, requested_hours
    )
    summary = adjudicate_leave(api, duty_shift_id, officer_id)
    vacancy = first_vacancy(api, duty_shift_id=duty_shift_id, driver="LEAVE", status="OPEN")
    return {
        "leave": read_leave(api, leave["id"]),
        "summary": summary,
        "vacancy": vacancy,
        "shift": read_shift(api, duty_shift_id),
    }


# ---------------------------------------------------------------------------
# Threshold targeting
# ---------------------------------------------------------------------------
def push_scheduled_hours_to(
    api, work_period_id: str, target_adjusted_scheduled_hours: int
) -> Dict[str, Any]:
    """Adjust the scheduled basis until the adjusted total hits an exact figure."""
    period = read_work_period(api, work_period_id)
    delta = target_adjusted_scheduled_hours - period["adjusted_scheduled_hours"]
    if delta:
        adjust_hours(api, work_period_id, delta, "SCHEDULED")
    return read_work_period(api, work_period_id)


def push_worked_hours_to(
    api, work_period_id: str, target_adjusted_worked_hours: int
) -> Dict[str, Any]:
    period = read_work_period(api, work_period_id)
    delta = target_adjusted_worked_hours - period["adjusted_worked_hours"]
    if delta:
        adjust_hours(api, work_period_id, delta, "WORKED")
    return read_work_period(api, work_period_id)
