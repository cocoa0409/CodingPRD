"""Composite setup helpers (PRD §3 workflows).

Every fixture builds its preconditions from scratch against a fresh server,
using only PRD-declared endpoints. Setup calls use get_success_data() so a
setup failure surfaces as a clear "Setup failed" error rather than a confusing
assertion failure.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_employee_payload,
    create_extra_board_payload,
    create_job_payload,
    create_leave_bid_payload,
    create_slot_payload,
)
from .test_users import TEST_USERS, make_employee_headers

MANAGER = TEST_USERS["crew_manager_headers"]
CALLER = TEST_USERS["crew_caller_headers"]

CLOCK_START_ISO = "2026-08-01T00:00:00Z"

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(_TS_FMT)


def _parse(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    text = ts.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------

def set_clock(iso: str = CLOCK_START_ISO) -> dict:
    """Advance the logical clock (CrewManager)."""
    resp = api_client.set_clock({"to_iso8601": iso}, MANAGER)
    return get_success_data(resp)


def create_employee(**overrides) -> dict:
    resp = api_client.create_employee(create_employee_payload(**overrides), MANAGER)
    return get_success_data(resp)


def create_board(**overrides) -> dict:
    resp = api_client.create_extra_board(create_extra_board_payload(**overrides), MANAGER)
    return get_success_data(resp)


def place_slot(board_id: str, employee_id: str) -> dict:
    resp = api_client.create_board_slot(
        board_id, create_slot_payload(employee_id), MANAGER
    )
    return get_success_data(resp)


def create_job(**overrides) -> dict:
    resp = api_client.create_job(create_job_payload(**overrides), MANAGER)
    return get_success_data(resp)


def get_employee(employee_id: str) -> dict:
    return get_success_data(api_client.get_employee(employee_id, MANAGER))


def get_job(job_id: str) -> dict:
    return get_success_data(api_client.get_job(job_id, MANAGER))


def get_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.get_assignment(assignment_id, MANAGER))


def get_call(call_id: str) -> dict:
    return get_success_data(api_client.get_call(call_id, CALLER))


def fresh_job_version(job_id: str) -> int:
    """Re-read the job and return its current version (OCC-safe accept helper)."""
    return get_job(job_id)["version"]


def issue_call(job_id: str) -> dict:
    resp = api_client.issue_call(job_id, CALLER)
    return get_success_data(resp)


def list_board_slots_all(board_id: str) -> list:
    resp = api_client.list_extra_board_slots(MANAGER, params={"board_id": board_id})
    return get_success_data(resp)


def slot_for_employee(board_id: str, employee_id: str) -> dict:
    rows = [
        s for s in list_board_slots_all(board_id) if s["employee_id"] == employee_id
    ]
    assert rows, f"Setup failed: no slot for employee {employee_id} on board {board_id}"
    return rows[0]


def accept_call_with_fresh_version(call_id: str, employee_id: str,
                                   deadhead_minutes=None, deadhead_mode=None):
    """Accept a call using the job's current version (re-read just before the
    call), so the OCC guard never fires accidentally. Returns the raw Response.
    """
    call = get_call(call_id)
    version = fresh_job_version(call["job_id"])
    payload = {"expected_job_version": version}
    if deadhead_minutes is not None:
        payload["deadhead_minutes"] = deadhead_minutes
    if deadhead_mode is not None:
        payload["deadhead_mode"] = deadhead_mode
    return api_client.accept_call(call_id, payload, make_employee_headers(employee_id))


# ---------------------------------------------------------------------------
# Tier 1/2: hierarchy + state progression
# ---------------------------------------------------------------------------

def setup_employee_on_board(craft: str = "CONDUCTOR", terminal: str = "CHI",
                            employee_overrides: dict = None,
                            board_overrides: dict = None) -> dict:
    """Employee + matching board + one ACTIVE slot. Returns the three entities."""
    employee_overrides = employee_overrides or {}
    board_overrides = board_overrides or {}
    employee_overrides.setdefault("craft", craft)
    employee_overrides.setdefault("home_terminal", terminal)
    board_overrides.setdefault("craft", craft)
    board_overrides.setdefault("terminal", terminal)
    emp = create_employee(**employee_overrides)
    board = create_board(**board_overrides)
    slot = place_slot(board["id"], emp["id"])
    return {"employee": emp, "board": board, "slot": slot}


def setup_offered_call(craft: str = "CONDUCTOR", terminal: str = "CHI",
                       report_time: str = "2026-08-03T08:00:00Z",
                       crew_required: int = 1,
                       employee_overrides: dict = None,
                       job_overrides: dict = None) -> dict:
    """Employee on board + bulletined job + issued call (OFFERED to employee)."""
    ctx = setup_employee_on_board(craft, terminal, employee_overrides)
    job_overrides = job_overrides or {}
    job_overrides.setdefault("craft", craft)
    job_overrides.setdefault("origin_terminal", terminal)
    job_overrides.setdefault("report_time", report_time)
    job_overrides.setdefault("crew_required", crew_required)
    job = create_job(**job_overrides)
    call = issue_call(job["id"])
    ctx.update({"job": job, "call": call})
    return ctx


def setup_accepted_assignment(report_time: str = "2026-08-03T08:00:00Z",
                              crew_required: int = 1,
                              deadhead_minutes=None, deadhead_mode=None,
                              craft: str = "CONDUCTOR", terminal: str = "CHI",
                              employee_overrides: dict = None,
                              job_overrides: dict = None) -> dict:
    """Offered call accepted; assignment MARKED_UP exists."""
    ctx = setup_offered_call(craft, terminal, report_time, crew_required,
                             employee_overrides, job_overrides)
    resp = accept_call_with_fresh_version(
        ctx["call"]["id"], ctx["employee"]["id"], deadhead_minutes, deadhead_mode
    )
    assignment = get_success_data(resp)
    ctx["assignment"] = assignment
    return ctx


def setup_on_duty_assignment(report_time: str = "2026-08-02T06:00:00Z",
                             deadhead_minutes=None, deadhead_mode=None,
                             craft: str = "CONDUCTOR", terminal: str = "CHI",
                             employee_overrides: dict = None,
                             job_overrides: dict = None) -> dict:
    """Assignment advanced to ON_DUTY at exactly report_time."""
    ctx = setup_accepted_assignment(report_time, deadhead_minutes=deadhead_minutes,
                                    deadhead_mode=deadhead_mode, craft=craft,
                                    terminal=terminal,
                                    employee_overrides=employee_overrides,
                                    job_overrides=job_overrides)
    set_clock(report_time)
    resp = api_client.assignment_on_duty(
        ctx["assignment"]["id"], make_employee_headers(ctx["employee"]["id"])
    )
    ctx["assignment"] = get_success_data(resp)
    return ctx


def setup_tied_up_assignment(tour_minutes: int = 300,
                             report_time: str = "2026-08-02T06:00:00Z",
                             deadhead_minutes=None, deadhead_mode=None,
                             craft: str = "CONDUCTOR", terminal: str = "CHI",
                             employee_overrides: dict = None,
                             job_overrides: dict = None) -> dict:
    """Assignment tied up after `tour_minutes` on duty; includes the auto-created
    DRAFT pay record."""
    ctx = setup_on_duty_assignment(report_time, deadhead_minutes, deadhead_mode,
                                   craft, terminal, employee_overrides,
                                   job_overrides)
    tie_up_at = _parse(report_time) + timedelta(minutes=tour_minutes)
    set_clock(_iso(tie_up_at))
    resp = api_client.assignment_tie_up(
        ctx["assignment"]["id"], make_employee_headers(ctx["employee"]["id"])
    )
    ctx["assignment"] = get_success_data(resp)
    ctx["pay_record"] = get_auto_pay_record(ctx["assignment"]["id"])
    return ctx


def get_auto_pay_record(assignment_id: str) -> dict:
    resp = api_client.list_pay_records(MANAGER, params={"assignment_id": assignment_id})
    rows = get_success_data(resp)
    assert rows, f"Setup failed: no pay record for assignment {assignment_id}"
    return rows[0]


def rest_periods_for(employee_id: str) -> list:
    resp = api_client.list_rest_periods(MANAGER, params={"employee_id": employee_id})
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_employee_with_monthly_minutes(tour_minutes: int = 16080,
                                        add_one_minute_tour: bool = False,
                                        craft: str = "ENGINEER",
                                        terminal: str = "CHI") -> dict:
    """Employee whose chronological ledger holds exactly `tour_minutes` for the
    current calendar month, now AVAILABLE again (rest satisfied, marked up).

    Chain: job reporting at the clock-start instant -> accept -> on-duty ->
    tie-up `tour_minutes` later -> rest 780 minutes -> mark-up.

    When add_one_minute_tour is True, a second 1-minute tour is appended
    (accept at equality projection, on-duty, tie-up one minute later, rest,
    mark-up), leaving cumulative_duty_minutes_month == tour_minutes + 1 and the
    logical clock at 2026-08-13T06:02:00Z.
    """
    set_clock(CLOCK_START_ISO)
    ctx = setup_employee_on_board(
        craft, terminal,
        employee_overrides={"craft": craft, "home_terminal": terminal},
    )
    emp_id = ctx["employee"]["id"]
    job1 = create_job(craft=craft, origin_terminal=terminal,
                      report_time=CLOCK_START_ISO, crew_required=1)
    call1 = issue_call(job1["id"])
    resp = accept_call_with_fresh_version(call1["id"], emp_id)
    asg1 = get_success_data(resp)
    resp = api_client.assignment_on_duty(asg1["id"], make_employee_headers(emp_id))
    get_success_data(resp)
    tie_up_at = _parse(CLOCK_START_ISO) + timedelta(minutes=tour_minutes)
    set_clock(_iso(tie_up_at))
    resp = api_client.assignment_tie_up(asg1["id"], make_employee_headers(emp_id))
    get_success_data(resp)
    mark_up_at = tie_up_at + timedelta(minutes=780)
    set_clock(_iso(mark_up_at))
    resp = api_client.mark_up_employee(emp_id, make_employee_headers(emp_id))
    get_success_data(resp)
    ctx["first_assignment"] = asg1

    if add_one_minute_tour:
        job2 = create_job(craft=craft, origin_terminal=terminal,
                          report_time="2026-08-12T20:00:00Z", crew_required=1)
        call2 = issue_call(job2["id"])
        resp = accept_call_with_fresh_version(call2["id"], emp_id)
        asg2 = get_success_data(resp)
        ctx["second_assignment"] = asg2
        set_clock("2026-08-12T20:00:00Z")
        resp = api_client.assignment_on_duty(asg2["id"], make_employee_headers(emp_id))
        get_success_data(resp)
        set_clock("2026-08-12T20:01:00Z")
        resp = api_client.assignment_tie_up(asg2["id"], make_employee_headers(emp_id))
        get_success_data(resp)
        set_clock("2026-08-13T06:02:00Z")
        resp = api_client.mark_up_employee(emp_id, make_employee_headers(emp_id))
        get_success_data(resp)

    ctx["employee"] = get_employee(emp_id)
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: multi-employee boards
# ---------------------------------------------------------------------------

def setup_board_with_employees(count: int, craft: str = "CONDUCTOR",
                               terminal: str = "CHI") -> dict:
    """Board with `count` employees slotted in order (positions 1..count)."""
    emps = [
        create_employee(craft=craft, home_terminal=terminal) for _ in range(count)
    ]
    board = create_board(craft=craft, terminal=terminal,
                         guaranteed_slots=count)
    slots = [place_slot(board["id"], e["id"]) for e in emps]
    return {"employees": emps, "board": board, "slots": slots}


def setup_submitted_leave_bid(employee_id: str,
                              start_date: str = "2026-08-10T00:00:00Z",
                              end_date: str = "2026-08-12T00:00:00Z",
                              leave_type: str = "VACATION") -> dict:
    payload = create_leave_bid_payload(
        employee_id, leave_type=leave_type, start_date=start_date, end_date=end_date
    )
    resp = api_client.create_leave_bid(payload, make_employee_headers(employee_id))
    return get_success_data(resp)
