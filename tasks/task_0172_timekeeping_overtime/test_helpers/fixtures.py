"""Composite setup helpers — multi-step preambles tests can reuse.

The timekeeping & overtime lifecycle takes 5–15 API calls to reach the
states a test wants to assert on (a NON_EXEMPT employee whose shift is
CLOSED with detention computed, a workweek with five shifts FINALIZED
and POSTED so a lock can be probed, a TimeEdit approved on a FINALIZED
shift so the FINALIZED → CLOSED revert path is observable). Each
fixture composes those lower-level steps so test bodies focus on the
rule under assertion.

IDENTITY THREADING — PRD §2.1:

    "When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the
    acting `Employee` record; ownership checks on any resource that
    references an employee compare the resource's `employee_id` field
    to `X-User-ID`."

After an Employee is created, fixtures act as that employee by minting
headers via `make_employee_headers(employee["id"])`. Supervisor and
PayrollAdmin are opaque per PRD §2.1; helpers use the shared
placeholders for those roles by default. `make_supervisor_headers` and
`make_payroll_admin_headers` are available for tests that need
distinct operators (e.g., segregation-of-duties on TimeEdit approval).

CLOCK ANCHORING — PRD §3.8:

    "A clock-set capability accepts an ISO 8601 timestamp `now` and
    sets the server's logical now to that instant".

Every fixture that depends on time-gated rules (punch window, time-
edit window, detention measurement) sets the clock explicitly via
`clock_set(...)` and advances it via `clock_advance(...)` so tests are
deterministic and never depend on wall-clock time.

Setup calls use `get_success_data` (lenient 2xx validator) so a failed
setup surfaces as a clear setup-failure rather than a confusing
downstream assertion failure.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    add_hours,
    add_minutes,
    add_seconds,
    clock_advance_payload,
    clock_set_payload,
    create_employee_payload,
    create_punch_payload,
    create_shift_payload,
    create_time_edit_payload,
    create_tip_declaration_payload,
    parse_iso,
    unique_idempotency_key,
)
from .test_users import (
    PAYROLL_ADMIN_SHARED_ID,
    PAYROLL_ADMIN_SECONDARY_ID,
    SUPERVISOR_SHARED_ID,
    SUPERVISOR_SECONDARY_ID,
    TEST_USERS,
    make_employee_headers,
    make_payroll_admin_headers,
    make_supervisor_headers,
)


# ===========================================================================
# Clock helpers — PRD §3.8
# ===========================================================================
def clock_set(now_iso: str,
              headers: Optional[Dict[str, str]] = None) -> None:
    """Set the server clock. PayrollAdmin only per PRD §3.8."""
    resp = api_client.clock_set(
        clock_set_payload(now_iso),
        headers or TEST_USERS["payroll_admin_headers"],
    )
    get_success_data(resp)


def clock_advance(seconds: int,
                  headers: Optional[Dict[str, str]] = None) -> None:
    """Advance the server clock by `seconds`. PRD §3.8 (PayrollAdmin)."""
    resp = api_client.clock_advance(
        clock_advance_payload(seconds),
        headers or TEST_USERS["payroll_admin_headers"],
    )
    get_success_data(resp)


# ===========================================================================
# Tier 1 — Entity creation primitives
# ===========================================================================
def create_employee(*,
                    full_name: Optional[str] = None,
                    jurisdiction: str = "FED",
                    classification: str = "NON_EXEMPT",
                    base_hourly_rate_cents: Optional[int] = None,
                    tipped_role: Optional[bool] = None,
                    tipped_cash_rate_cents: Optional[int] = None,
                    applicable_minimum_wage_cents: Optional[int] = None,
                    headers: Optional[Dict[str, str]] = None,
                    **extra: Any) -> Dict[str, Any]:
    """Create an employee.

    PRD §3.1: "An employee record ... the payroll administrator is the
    only role permitted to bring one into existence." Defaults
    `headers` to the shared PayrollAdmin headers (opaque role).
    """
    payload = create_employee_payload(
        full_name=full_name,
        jurisdiction=jurisdiction,
        classification=classification,
        base_hourly_rate_cents=base_hourly_rate_cents,
        tipped_role=tipped_role,
        tipped_cash_rate_cents=tipped_cash_rate_cents,
        applicable_minimum_wage_cents=applicable_minimum_wage_cents,
        **extra,
    )
    resp = api_client.create_employee(
        payload, headers or TEST_USERS["payroll_admin_headers"],
    )
    return get_success_data(resp)


def create_shift(employee_id: str,
                 *,
                 scheduled_start: Optional[str] = None,
                 scheduled_end: Optional[str] = None,
                 duration_hours: float = 8.0,
                 headers: Optional[Dict[str, str]] = None,
                 **extra: Any) -> Dict[str, Any]:
    """Create a shift via POST /timekeeping/shifts.

    PRD §3.2: Supervisor / PayrollAdmin roles. Defaults to the shared
    Supervisor headers (opaque role).
    """
    payload = create_shift_payload(
        employee_id,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        duration_hours=duration_hours,
        **extra,
    )
    resp = api_client.create_shift(
        payload, headers or TEST_USERS["supervisor_headers"],
    )
    return get_success_data(resp)


def post_punch(shift_id: str,
               punch_type: str,
               headers: Dict[str, str]) -> Dict[str, Any]:
    """POST a punch and return the punch resource."""
    resp = api_client.create_punch(
        shift_id, create_punch_payload(punch_type), headers,
    )
    return get_success_data(resp)


def finalize_shift(shift_id: str,
                   headers: Optional[Dict[str, str]] = None,
                   ) -> Dict[str, Any]:
    """Finalize a CLOSED shift (PayrollAdmin per PRD §3.6)."""
    resp = api_client.finalize_shift(
        shift_id, headers or TEST_USERS["payroll_admin_headers"],
    )
    return get_success_data(resp)


def get_shift(shift_id: str,
              headers: Optional[Dict[str, str]] = None,
              ) -> Dict[str, Any]:
    resp = api_client.get_shift(
        shift_id, headers or TEST_USERS["payroll_admin_headers"],
    )
    return get_success_data(resp)


def get_workweek(workweek_id: str,
                 headers: Optional[Dict[str, str]] = None,
                 ) -> Dict[str, Any]:
    resp = api_client.get_workweek(
        workweek_id, headers or TEST_USERS["payroll_admin_headers"],
    )
    return get_success_data(resp)


def list_audit(headers: Optional[Dict[str, str]] = None,
               *,
               subject_entity: Optional[str] = None,
               subject_id: Optional[str] = None,
               action: Optional[str] = None,
               limit: int = 100,
               ) -> List[Dict[str, Any]]:
    """List audit entries (PayrollAdmin per PRD §3.8)."""
    params: Dict[str, Any] = {"limit": limit}
    if subject_entity is not None:
        params["subject_entity"] = subject_entity
    if subject_id is not None:
        params["subject_id"] = subject_id
    if action is not None:
        params["action"] = action
    resp = api_client.list_audit(
        headers or TEST_USERS["payroll_admin_headers"], params=params,
    )
    body = resp.json()
    return body["data"]


# ===========================================================================
# Tier 2 — Shift lifecycle convenience
# ===========================================================================
def setup_open_shift(*,
                     employee: Optional[Dict[str, Any]] = None,
                     scheduled_start: Optional[str] = None,
                     duration_hours: float = 8.0,
                     jurisdiction: str = "FED",
                     base_hourly_rate_cents: Optional[int] = None,
                     ) -> Tuple[Dict[str, Any], Dict[str, Any],
                                Dict[str, Any]]:
    """Build a Shift in state OPEN with an IN punch already landed.

    PRD §3.2: First IN punch transitions SCHEDULED → OPEN. Clock is set
    to `scheduled_start` (which falls inside the punch window) so the
    IN punch validates.

    Returns (employee, shift, in_punch).
    """
    start = scheduled_start or TEST_DEFAULTS["MONDAY_0800"]
    if employee is None:
        employee = create_employee(
            jurisdiction=jurisdiction,
            classification="NON_EXEMPT",
            base_hourly_rate_cents=base_hourly_rate_cents,
        )
    shift = create_shift(
        employee["id"],
        scheduled_start=start,
        duration_hours=duration_hours,
    )
    clock_set(start)
    in_punch = post_punch(
        shift["id"], "IN", make_employee_headers(employee["id"]),
    )
    return employee, shift, in_punch


def setup_closed_shift(*,
                       employee: Optional[Dict[str, Any]] = None,
                       scheduled_start: Optional[str] = None,
                       duration_hours: float = 8.0,
                       worked_seconds: Optional[int] = None,
                       overrun_minutes: int = 0,
                       jurisdiction: str = "FED",
                       base_hourly_rate_cents: Optional[int] = None,
                       ) -> Dict[str, Any]:
    """Build a Shift in state CLOSED with IN + OUT punches.

    `worked_seconds` overrides the time between IN and OUT. If left as
    None, the shift runs from scheduled_start through scheduled_end +
    `overrun_minutes`. The latter knob is for detention tests that need
    `Shift.detention_minutes` to land at a specific value.

    Returns a dict with keys: employee, shift, in_punch, out_punch.
    """
    employee, shift, in_punch = setup_open_shift(
        employee=employee,
        scheduled_start=scheduled_start,
        duration_hours=duration_hours,
        jurisdiction=jurisdiction,
        base_hourly_rate_cents=base_hourly_rate_cents,
    )
    if worked_seconds is None:
        worked_seconds = int(duration_hours * 3600) + (overrun_minutes * 60)
    clock_advance(worked_seconds)
    out_punch = post_punch(
        shift["id"], "OUT", make_employee_headers(employee["id"]),
    )
    refreshed = get_shift(shift["id"])
    return {
        "employee": employee,
        "shift": refreshed,
        "in_punch": in_punch,
        "out_punch": out_punch,
    }


def setup_finalized_shift(*,
                          employee: Optional[Dict[str, Any]] = None,
                          scheduled_start: Optional[str] = None,
                          duration_hours: float = 8.0,
                          worked_seconds: Optional[int] = None,
                          overrun_minutes: int = 0,
                          jurisdiction: str = "FED",
                          base_hourly_rate_cents: Optional[int] = None,
                          ) -> Dict[str, Any]:
    """Build a Shift through to FINALIZED with the workweek POSTED.

    PRD §3.6: "if every sibling shift in the workweek is now
    `FINALIZED`, the workweek transitions `OPEN → POSTED` automatically."

    Returns dict with keys: employee, shift (finalized), workweek
    (posted), in_punch, out_punch.
    """
    state = setup_closed_shift(
        employee=employee,
        scheduled_start=scheduled_start,
        duration_hours=duration_hours,
        worked_seconds=worked_seconds,
        overrun_minutes=overrun_minutes,
        jurisdiction=jurisdiction,
        base_hourly_rate_cents=base_hourly_rate_cents,
    )
    finalized = finalize_shift(state["shift"]["id"])
    workweek = get_workweek(finalized["workweek_id"])
    state["shift"] = finalized
    state["workweek"] = workweek
    return state


def setup_shift_with_meal_break(*,
                                employee: Optional[Dict[str, Any]] = None,
                                scheduled_start: Optional[str] = None,
                                worked_hours_before_meal: float = 4.0,
                                meal_duration_minutes: int = 30,
                                worked_hours_after_meal: float = 4.0,
                                jurisdiction: str = "CA",
                                base_hourly_rate_cents: Optional[int] = None,
                                ) -> Dict[str, Any]:
    """Build a CLOSED shift with a MEAL_OUT/MEAL_IN pair.

    The clock walk is: IN at scheduled_start →
    advance `worked_hours_before_meal` hours → MEAL_OUT →
    advance `meal_duration_minutes` minutes → MEAL_IN →
    advance `worked_hours_after_meal` hours → OUT.

    Returns dict: employee, shift, in_punch, meal_out, meal_in,
    out_punch.
    """
    duration_hours = (
        worked_hours_before_meal
        + (meal_duration_minutes / 60.0)
        + worked_hours_after_meal
    )
    employee, shift, in_punch = setup_open_shift(
        employee=employee,
        scheduled_start=scheduled_start,
        duration_hours=duration_hours,
        jurisdiction=jurisdiction,
        base_hourly_rate_cents=base_hourly_rate_cents,
    )
    emp_headers = make_employee_headers(employee["id"])
    clock_advance(int(worked_hours_before_meal * 3600))
    meal_out = post_punch(shift["id"], "MEAL_OUT", emp_headers)
    clock_advance(int(meal_duration_minutes * 60))
    meal_in = post_punch(shift["id"], "MEAL_IN", emp_headers)
    clock_advance(int(worked_hours_after_meal * 3600))
    out_punch = post_punch(shift["id"], "OUT", emp_headers)
    refreshed = get_shift(shift["id"])
    return {
        "employee": employee,
        "shift": refreshed,
        "in_punch": in_punch,
        "meal_out": meal_out,
        "meal_in": meal_in,
        "out_punch": out_punch,
    }


# ===========================================================================
# Tier 3 — Multi-shift workweek constructions
# ===========================================================================
def setup_week_with_shifts(*,
                           employee: Optional[Dict[str, Any]] = None,
                           daily_hours: List[float],
                           jurisdiction: str = "FED",
                           base_hourly_rate_cents: Optional[int] = None,
                           anchor_iso: Optional[str] = None,
                           starting_day_offset: int = 1,
                           ) -> Dict[str, Any]:
    """Create a NON_EXEMPT employee and N shifts on consecutive days.

    `daily_hours[i]` is the worked hours for day `starting_day_offset +
    i` relative to the Sunday anchor (PRD §3.6: Sunday 00:00:00.000Z
    anchors the FLSA workweek). For each shift the clock is set to
    scheduled_start, an IN punch lands, then the clock advances by
    `hours * 3600` seconds and an OUT punch lands.

    PRD §3.3 requires a meal break for any NON_EXEMPT shift whose
    worked hours exceed 5; without one, the meal-break-premium
    (1 hour at base) is added to the workweek's gross_pay_cents.
    To let pay-engine tests assert clean gross totals (base + OT +
    DT only), this fixture auto-inserts a 30-minute MEAL_OUT/MEAL_IN
    pair at the 4-hour mark for any shift whose hours > 5, AND
    extends scheduled_end by 30 minutes so the unpaid meal does not
    register as overrun (detention). The taken-before-fifth-hour
    flag is therefore true and the premium computes to zero.

    Returns dict: employee, shifts (list).
    """
    anchor = anchor_iso or TEST_DEFAULTS["WORKWEEK_ANCHOR"]
    if employee is None:
        employee = create_employee(
            jurisdiction=jurisdiction,
            classification="NON_EXEMPT",
            base_hourly_rate_cents=base_hourly_rate_cents,
        )
    emp_headers = make_employee_headers(employee["id"])
    shifts: List[Dict[str, Any]] = []
    for i, hours in enumerate(daily_hours):
        day_offset = starting_day_offset + i
        scheduled_start = add_hours(anchor, day_offset * 24 + 8)  # 08:00 UTC
        # If worked hours > 5, schedule must extend by 30 min for the
        # mandatory meal break — otherwise OUT lands 30 min past
        # scheduled_end and detention fires.
        needs_meal = hours > 5.0
        scheduled_duration = hours + (0.5 if needs_meal else 0.0)
        shift = create_shift(
            employee["id"],
            scheduled_start=scheduled_start,
            duration_hours=scheduled_duration,
        )
        clock_set(scheduled_start)
        post_punch(shift["id"], "IN", emp_headers)
        if needs_meal:
            # Take a 30-min meal break starting at hour 4 (< 5h cutoff).
            clock_advance(4 * 3600)
            post_punch(shift["id"], "MEAL_OUT", emp_headers)
            clock_advance(30 * 60)
            post_punch(shift["id"], "MEAL_IN", emp_headers)
            # Remaining worked time after the meal: hours - 4 (paid).
            remaining_seconds = int((hours - 4.0) * 3600)
            if remaining_seconds > 0:
                clock_advance(remaining_seconds)
        else:
            clock_advance(int(hours * 3600))
        post_punch(shift["id"], "OUT", emp_headers)
        shifts.append(get_shift(shift["id"]))
    return {"employee": employee, "shifts": shifts}


def finalize_all_shifts(shifts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Finalize each shift in order. Returns the finalized resources."""
    finalized: List[Dict[str, Any]] = []
    for shift in shifts:
        finalized.append(finalize_shift(shift["id"]))
    return finalized


def setup_finalized_week(*,
                         daily_hours: List[float],
                         jurisdiction: str = "FED",
                         base_hourly_rate_cents: Optional[int] = None,
                         anchor_iso: Optional[str] = None,
                         starting_day_offset: int = 1,
                         employee: Optional[Dict[str, Any]] = None,
                         ) -> Dict[str, Any]:
    """Build a workweek where every shift is FINALIZED (so the workweek
    transitions OPEN → POSTED).

    Returns dict: employee, shifts (finalized), workweek (POSTED).
    """
    built = setup_week_with_shifts(
        employee=employee,
        daily_hours=daily_hours,
        jurisdiction=jurisdiction,
        base_hourly_rate_cents=base_hourly_rate_cents,
        anchor_iso=anchor_iso,
        starting_day_offset=starting_day_offset,
    )
    finalized = finalize_all_shifts(built["shifts"])
    workweek_id = finalized[-1]["workweek_id"]
    workweek = get_workweek(workweek_id)
    return {
        "employee": built["employee"],
        "shifts": finalized,
        "workweek": workweek,
    }


def setup_locked_workweek(*,
                          daily_hours: Optional[List[float]] = None,
                          jurisdiction: str = "FED",
                          base_hourly_rate_cents: Optional[int] = None,
                          ) -> Dict[str, Any]:
    """Build a POSTED workweek, then lock it.

    PRD §3.6: "A payroll administrator locks a workweek when its
    `payroll_status` is `POSTED` and no `PENDING` time edits exist on
    any constituent shift; the transition `POSTED → LOCKED` freezes
    the workweek".

    Returns dict: employee, shifts, workweek (LOCKED).
    """
    if daily_hours is None:
        daily_hours = [8.0]
    state = setup_finalized_week(
        daily_hours=daily_hours,
        jurisdiction=jurisdiction,
        base_hourly_rate_cents=base_hourly_rate_cents,
    )
    resp = api_client.lock_workweek(
        state["workweek"]["id"], TEST_USERS["payroll_admin_headers"],
    )
    locked = get_success_data(resp)
    state["workweek"] = locked
    return state


# ===========================================================================
# Tier 4 — TimeEdit flows
# ===========================================================================
def submit_time_edit(shift_id: str,
                     target_punch_id: str,
                     proposed_punched_at: str,
                     *,
                     reason_code: str = "CLERICAL",
                     idempotency_key: Optional[str] = None,
                     requester_headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    """Submit a TimeEdit and return the created resource.

    PRD §3.5: "Anyone (an employee on their own shift, a supervisor on
    a covered shift, or a payroll administrator on any shift) may
    submit one". Defaults the requester to the shared Supervisor.
    """
    payload = create_time_edit_payload(
        shift_id=shift_id,
        target_punch_id=target_punch_id,
        proposed_punched_at=proposed_punched_at,
        reason_code=reason_code,
        idempotency_key=idempotency_key,
    )
    resp = api_client.create_time_edit(
        payload,
        requester_headers or TEST_USERS["supervisor_headers"],
    )
    return get_success_data(resp)


def approve_time_edit(time_edit_id: str,
                      approver_headers: Optional[Dict[str, str]] = None,
                      ) -> Dict[str, Any]:
    """Approve a PENDING TimeEdit.

    PRD §3.5: approver's X-User-ID must not equal requester's
    X-User-ID (segregation of duties). Defaults approver to the shared
    PayrollAdmin so it differs from the default Supervisor requester.
    """
    resp = api_client.approve_time_edit(
        time_edit_id,
        approver_headers or TEST_USERS["payroll_admin_headers"],
    )
    return get_success_data(resp)


def reject_time_edit(time_edit_id: str,
                     approver_headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    """Reject a PENDING TimeEdit (PRD §3.5)."""
    resp = api_client.reject_time_edit(
        time_edit_id,
        approver_headers or TEST_USERS["payroll_admin_headers"],
    )
    return get_success_data(resp)


def revert_time_edit(time_edit_id: str,
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    """Revert an APPROVED TimeEdit (PayrollAdmin per PRD §3.5)."""
    resp = api_client.revert_time_edit(
        time_edit_id,
        headers or TEST_USERS["payroll_admin_headers"],
    )
    return get_success_data(resp)


def setup_pending_time_edit(*,
                            requester_headers: Optional[Dict[str, str]] = None,
                            reason_code: str = "CLERICAL",
                            scheduled_start: Optional[str] = None,
                            duration_hours: float = 8.0,
                            jurisdiction: str = "FED",
                            base_hourly_rate_cents: Optional[int] = None,
                            target_offset_minutes: int = -10,
                            ) -> Dict[str, Any]:
    """Build a CLOSED shift and submit a PENDING TimeEdit on its OUT
    punch.

    `target_offset_minutes` shifts the proposed time relative to the
    shift's scheduled_end. Default -10 mins keeps the proposal within
    the [scheduled_start - 4h, scheduled_end + 6h] envelope.

    Returns dict: employee, shift (DISPUTED post-submission), out_punch,
    time_edit (PENDING).
    """
    closed = setup_closed_shift(
        scheduled_start=scheduled_start,
        duration_hours=duration_hours,
        jurisdiction=jurisdiction,
        base_hourly_rate_cents=base_hourly_rate_cents,
    )
    proposed_at = add_minutes(
        closed["shift"]["scheduled_end"], target_offset_minutes,
    )
    edit = submit_time_edit(
        closed["shift"]["id"],
        closed["out_punch"]["id"],
        proposed_at,
        reason_code=reason_code,
        requester_headers=(
            requester_headers or TEST_USERS["supervisor_headers"]
        ),
    )
    refreshed_shift = get_shift(closed["shift"]["id"])
    return {
        "employee": closed["employee"],
        "shift": refreshed_shift,
        "in_punch": closed["in_punch"],
        "out_punch": closed["out_punch"],
        "time_edit": edit,
    }


def setup_revert_ready_finalized_shift(*,
                                       overrun_minutes: int = 65,
                                       jurisdiction: str = "FED",
                                       base_hourly_rate_cents: int = 2000,
                                       ) -> Dict[str, Any]:
    """Build a FINALIZED shift with detention (overrun_minutes past
    scheduled_end) so the FINALIZED → CLOSED revert cycle is reachable.

    Returns dict: employee, shift (FINALIZED), workweek (POSTED),
    in_punch, out_punch, gross_pay_before.
    """
    state = setup_finalized_shift(
        overrun_minutes=overrun_minutes,
        jurisdiction=jurisdiction,
        base_hourly_rate_cents=base_hourly_rate_cents,
    )
    state["gross_pay_before"] = state["workweek"]["gross_pay_cents"]
    return state


# ===========================================================================
# Tier 5 — Tip declaration / shortfall flows
# ===========================================================================
def setup_tipped_employee_closed_shift(*,
                                       worked_hours: float = 4.0,
                                       declared_tips_cents: int = 2000,
                                       tipped_cash_rate_cents: int = 213,
                                       applicable_minimum_wage_cents: int = 1500,
                                       base_hourly_rate_cents: int = 725,
                                       jurisdiction: str = "FED",
                                       scheduled_start: Optional[str] = None,
                                       ) -> Dict[str, Any]:
    """Build a tipped NON_EXEMPT employee, CLOSED shift, and a
    TipDeclaration on that shift.

    Returns dict: employee, shift (CLOSED), in_punch, out_punch,
    tip_declaration.
    """
    employee = create_employee(
        jurisdiction=jurisdiction,
        classification="NON_EXEMPT",
        base_hourly_rate_cents=base_hourly_rate_cents,
        tipped_role=True,
        tipped_cash_rate_cents=tipped_cash_rate_cents,
        applicable_minimum_wage_cents=applicable_minimum_wage_cents,
    )
    closed = setup_closed_shift(
        employee=employee,
        scheduled_start=scheduled_start,
        duration_hours=worked_hours,
    )
    tip_resp = api_client.create_tip_declaration(
        closed["shift"]["id"],
        create_tip_declaration_payload(declared_tips_cents),
        TEST_USERS["payroll_admin_headers"],
    )
    tip_decl = get_success_data(tip_resp)
    closed["tip_declaration"] = tip_decl
    return closed


# ===========================================================================
# Tier 6 — Difficulty-design composite recipes
# ===========================================================================
def setup_fed_vs_ca_workweek_pair(
        *,
        daily_hours: Optional[List[float]] = None,
        base_hourly_rate_cents: int = 2000,
        ) -> Dict[str, Any]:
    """Build two parallel employees (one FED, one CA) with the same
    daily hours [13, 8, 8, 8, 8] (sum 45h), all five shifts finalized
    so each workweek is POSTED.

    Recipe: scaffold_difficulty_design.dual_variant_calc.
    workweek_engine_fed_vs_ca.

    Returns dict with employee_fed, employee_ca, workweek_fed,
    workweek_ca.
    """
    if daily_hours is None:
        daily_hours = [13.0, 8.0, 8.0, 8.0, 8.0]
    fed = setup_finalized_week(
        daily_hours=daily_hours,
        jurisdiction="FED",
        base_hourly_rate_cents=base_hourly_rate_cents,
    )
    ca = setup_finalized_week(
        daily_hours=daily_hours,
        jurisdiction="CA",
        base_hourly_rate_cents=base_hourly_rate_cents,
    )
    return {
        "employee_fed": fed["employee"],
        "employee_ca": ca["employee"],
        "shifts_fed": fed["shifts"],
        "shifts_ca": ca["shifts"],
        "workweek_fed": fed["workweek"],
        "workweek_ca": ca["workweek"],
    }


def setup_tip_credit_integer_hours_scenario() -> Dict[str, Any]:
    """Build the canonical 4-hour tipped shift used by
    scaffold_difficulty_design.dual_variant_calc.
    tip_credit_per_line_vs_sum_then_round.

    PRD §3.1 requires base_hourly_rate_cents >= 725 (federal minimum)
    for NON_EXEMPT employees, including tipped ones. The pay engine
    (PRD §3.6 step 4) uses base_hourly_rate_cents in the base line,
    so base_line(4*725)=2900 + shortfall_topup(3148) = 6048.

    declared_tips=2000, cash_wage=852, min_required=6000,
    expected tip_credit_applied=2000, shortfall_topup=3148,
    expected gross_pay=6048.
    """
    state = setup_tipped_employee_closed_shift(
        worked_hours=4.0,
        declared_tips_cents=2000,
        tipped_cash_rate_cents=213,
        applicable_minimum_wage_cents=1500,
        base_hourly_rate_cents=725,
        jurisdiction="FED",
    )
    finalized = finalize_shift(state["shift"]["id"])
    workweek = get_workweek(finalized["workweek_id"])
    state["shift"] = finalized
    state["workweek"] = workweek
    return state


def setup_tip_credit_fractional_hours_scenario() -> Dict[str, Any]:
    """Build the 3.5-hour tipped scenario used by
    scaffold_difficulty_design.combinatorial_formula.
    tip_credit_per_line_rounding_order.

    PRD §3.1 requires base_hourly_rate_cents >= 725; base_line is
    round(3.5*725) = round(2537.5) = 2538.

    declared_tips=4000, expected cash_wage=746, min_required=5250,
    tip_credit_applied=4000, shortfall_topup=504,
    expected gross_pay = 2538 + 504 = 3042.
    """
    state = setup_tipped_employee_closed_shift(
        worked_hours=3.5,
        declared_tips_cents=4000,
        tipped_cash_rate_cents=213,
        applicable_minimum_wage_cents=1500,
        base_hourly_rate_cents=725,
        jurisdiction="FED",
    )
    finalized = finalize_shift(state["shift"]["id"])
    workweek = get_workweek(finalized["workweek_id"])
    state["shift"] = finalized
    state["workweek"] = workweek
    return state


def setup_overrun_finalized_shift_for_cascade(
        *,
        overrun_minutes: int = 65,
        base_hourly_rate_cents: int = 2000,
        ) -> Dict[str, Any]:
    """Single CA shift, 8h scheduled, 65 minutes overrun → DetentionEvent
    TIER_2 with premium 2000c, then finalized; used by
    scaffold_difficulty_design.transitive_cascade.
    out_punch_triggers_detention_then_workweek and its sibling.
    """
    return setup_finalized_shift(
        jurisdiction="CA",
        base_hourly_rate_cents=base_hourly_rate_cents,
        overrun_minutes=overrun_minutes,
    )


def setup_shift_with_pending_time_edit_for_finalize_block(
        ) -> Dict[str, Any]:
    """CLOSED shift with a PENDING CLERICAL TimeEdit, ready for a
    finalize attempt that should hit ERR_SHIFT_INVALID_STATE per
    scaffold_difficulty_design.cross_entity_state_dependency.
    shift_finalize_blocked_by_pending_timeedit.
    """
    return setup_pending_time_edit(
        jurisdiction="FED",
        base_hourly_rate_cents=2000,
        target_offset_minutes=-10,
    )


__all__ = [
    # Clock
    "clock_set",
    "clock_advance",
    # Entity primitives
    "create_employee",
    "create_shift",
    "post_punch",
    "finalize_shift",
    "get_shift",
    "get_workweek",
    "list_audit",
    # Shift lifecycle
    "setup_open_shift",
    "setup_closed_shift",
    "setup_finalized_shift",
    "setup_shift_with_meal_break",
    # Workweek
    "setup_week_with_shifts",
    "finalize_all_shifts",
    "setup_finalized_week",
    "setup_locked_workweek",
    # TimeEdit
    "submit_time_edit",
    "approve_time_edit",
    "reject_time_edit",
    "revert_time_edit",
    "setup_pending_time_edit",
    "setup_revert_ready_finalized_shift",
    # Tipped
    "setup_tipped_employee_closed_shift",
    # Difficulty-design
    "setup_fed_vs_ca_workweek_pair",
    "setup_tip_credit_integer_hours_scenario",
    "setup_tip_credit_fractional_hours_scenario",
    "setup_overrun_finalized_shift_for_cascade",
    "setup_shift_with_pending_time_edit_for_finalize_block",
]
