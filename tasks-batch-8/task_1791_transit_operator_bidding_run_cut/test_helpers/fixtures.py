"""Composite setup helpers.

Every fixture builds preconditions from scratch against an empty database,
using only PRD-declared endpoints. Fixtures use get_success_data() internally
so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_absence_case_payload,
    create_bid_entry_payload,
    create_grievance_case_payload,
    create_operator_payload,
    create_run_payload,
    create_run_piece,
    create_sign_up_period_payload,
    create_vacation_slot_payload,
    schedule_revision_payload,
)
from .test_users import (
    TEST_USERS,
    make_operator_headers,
)

SO_HEADERS = TEST_USERS["scheduling_officer_headers"]
PC_HEADERS = TEST_USERS["payroll_clerk_headers"]
UR_HEADERS = TEST_USERS["union_rep_headers"]

DEFAULT_WINDOW = ("2026-09-01", "2026-11-30")


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_period(name="Fall 2026 Sign-Up", **overrides):
    """Create a sign-up period (starts DRAFT). Returns the period dict."""
    payload = create_sign_up_period_payload(name=name, **overrides)
    resp = api_client.create_sign_up_period(payload, SO_HEADERS)
    return get_success_data(resp)


def create_operator(employee_number="E1", full_name="Op One", hire_date="2000-01-01", **overrides):
    """Register an operator (starts ACTIVE). Returns the operator dict."""
    payload = create_operator_payload(
        employee_number=employee_number, full_name=full_name, hire_date=hire_date, **overrides
    )
    resp = api_client.create_operator(payload, SO_HEADERS)
    return get_success_data(resp)


def create_run(period_id, run_number="R1", service_date="2026-09-07",
               pieces=None, **overrides):
    """Create a run (starts CUT) under the period's current revision."""
    if pieces is None:
        pieces = [create_run_piece(300, 700, 400)]
    payload = create_run_payload(
        run_number=run_number, service_date=service_date, pieces=pieces, **overrides
    )
    resp = api_client.create_run(period_id, payload, SO_HEADERS)
    return get_success_data(resp)


def get_period(period_id):
    resp = api_client.get_sign_up_period(period_id, SO_HEADERS)
    return get_success_data(resp)


def get_period_version(period_id):
    return get_period(period_id)["version"]


def get_operator(operator_id):
    resp = api_client.get_operator(operator_id, SO_HEADERS)
    return get_success_data(resp)


def get_run(run_id):
    resp = api_client.get_run(run_id, SO_HEADERS)
    return get_success_data(resp)


def get_assignment(assignment_id):
    resp = api_client.get_daily_assignment(assignment_id, PC_HEADERS)
    return get_success_data(resp)


def get_pay_records(assignment_id):
    resp = api_client.list_pay_records(assignment_id, PC_HEADERS)
    return get_success_data(resp)


def get_absence_case(case_id):
    resp = api_client.get_absence_case(case_id, SO_HEADERS)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: period lifecycle progression
# ---------------------------------------------------------------------------

def create_period_with_runs(run_specs=None, **period_overrides):
    """Create a period plus runs. run_specs: list of kwargs dicts for create_run.
    Returns (period, [runs])."""
    period = create_period(**period_overrides)
    if run_specs is None:
        run_specs = [{}]
    runs = [create_run(period["id"], **spec) for spec in run_specs]
    return period, runs


def cut_period(period_id):
    """DRAFT -> RUNS_CUT. Returns refreshed period."""
    resp = api_client.cut_runs(period_id, SO_HEADERS)
    return get_success_data(resp)


def post_period(period_id):
    """RUNS_CUT -> OPEN. Returns refreshed period."""
    resp = api_client.post_runs(period_id, SO_HEADERS)
    return get_success_data(resp)


def open_picking_period(period_id):
    """OPEN -> PICKING. Returns refreshed period."""
    resp = api_client.open_picking(period_id, SO_HEADERS)
    return get_success_data(resp)


def create_open_period(run_specs=None, **period_overrides):
    """Period with runs, cut and posted -> OPEN. Returns (period, [runs])."""
    period, runs = create_period_with_runs(run_specs, **period_overrides)
    cut_period(period["id"])
    period = post_period(period["id"])
    return period, runs


def create_picking_period(run_specs=None, **period_overrides):
    """Period progressed to PICKING. Returns (period, [runs])."""
    period, runs = create_open_period(run_specs, **period_overrides)
    period = open_picking_period(period["id"])
    return period, runs


# ---------------------------------------------------------------------------
# Tier 3: bidding helpers
# ---------------------------------------------------------------------------

def submit_bid(period_id, operator_id, run_id, preference_rank=1):
    """Submit a bid as the operator, reading the period's current version first
    so the OCC field is fresh. Returns the created BidEntry."""
    version = get_period_version(period_id)
    payload = create_bid_entry_payload(operator_id, run_id, preference_rank, version)
    resp = api_client.create_bid_entry(period_id, payload, make_operator_headers(operator_id))
    return get_success_data(resp)


def adjudicate(period_id):
    resp = api_client.adjudicate_next(period_id, SO_HEADERS)
    return get_success_data(resp)


def lock_period(period_id):
    resp = api_client.lock_sign_up_period(period_id, SO_HEADERS)
    return get_success_data(resp)


def implement_period(period_id):
    resp = api_client.implement_sign_up_period(period_id, SO_HEADERS)
    return get_success_data(resp)


def award_run_to_operator(period_id, operator_id, run_id, preference_rank=1):
    """Submit a bid for the operator and adjudicate so the run is awarded.
    Assumes the operator is the next-most-senior pending bidder."""
    bid = submit_bid(period_id, operator_id, run_id, preference_rank)
    adjudicate(period_id)
    return bid


# ---------------------------------------------------------------------------
# Tier 4: full lifecycle to IMPLEMENTED with one awarded run
# ---------------------------------------------------------------------------

def setup_implemented_with_award(
    run_pieces=None,
    service_date="2026-09-07",
    operator_overrides=None,
    period_overrides=None,
):
    """Full pipeline: period -> run -> cut -> post -> open-picking -> bid ->
    adjudicate -> lock -> implement.

    Returns dict with keys: period, run, operator, assignment (the
    BID_AWARD DailyAssignment materialized at implement).
    """
    period_overrides = period_overrides or {}
    operator_overrides = operator_overrides or {}
    pieces = run_pieces or [create_run_piece(300, 700, 400)]

    period, runs = create_picking_period(
        [{"run_number": "R1", "service_date": service_date, "pieces": pieces}],
        **period_overrides,
    )
    run = runs[0]
    operator = create_operator(**operator_overrides)
    award_run_to_operator(period["id"], operator["id"], run["id"])
    lock_period(period["id"])
    period = implement_period(period["id"])

    resp = api_client.list_daily_assignments(
        SO_HEADERS, params={"operator_id": operator["id"], "sign_up_period_id": period["id"]}
    )
    assignments = get_success_data(resp)
    assert len(assignments) == 1, f"expected exactly one assignment, got {len(assignments)}"
    return {
        "period": period,
        "run": get_run(run["id"]),
        "operator": operator,
        "assignment": assignments[0],
    }


def find_assignment(operator_id, period_id, service_date=None):
    params = {"operator_id": operator_id, "sign_up_period_id": period_id}
    if service_date is not None:
        params["service_date"] = service_date
    resp = api_client.list_daily_assignments(SO_HEADERS, params=params)
    data = get_success_data(resp)
    assert len(data) >= 1, f"no assignment found for operator {operator_id} in period {period_id}"
    return data[0]


# ---------------------------------------------------------------------------
# Tier 5: absence / coverage helpers
# ---------------------------------------------------------------------------

def create_absence(operator_id, absence_date="2026-09-07", reason_code="SICK", as_operator=False):
    headers = make_operator_headers(operator_id) if as_operator else SO_HEADERS
    resp = api_client.create_absence_case(
        create_absence_case_payload(operator_id, absence_date, reason_code), headers
    )
    return get_success_data(resp)


def setup_implemented_with_board_member(
    board_ratio_pct=40,
    run_pieces=None,
):
    """Two operators; the senior wins the only run, the junior's bid passes and
    the junior is demoted to the extra board (fills the single OPEN slot).
    Period is left IMPLEMENTED.

    board_ratio_pct must stay within the PRD §3.1 declared range of 5 to 40;
    with a single POSTED run every value in that range sizes the board at
    exactly one slot via the ceiling rule of §3.3.

    Returns dict: period, run, senior, junior (refreshed), assignment (senior's).
    """
    pieces = run_pieces or [create_run_piece(300, 700, 400)]
    period, runs = create_picking_period(
        [{"run_number": "R1", "service_date": "2026-09-07", "pieces": pieces}],
        extra_board_ratio_pct=board_ratio_pct,
    )
    run = runs[0]
    senior = create_operator(employee_number="E1", full_name="Senior", hire_date="2000-01-01")
    junior = create_operator(employee_number="E2", full_name="Junior", hire_date="2005-01-01")

    # Senior bids rank 1; junior bids rank 1 on the same run.
    submit_bid(period["id"], senior["id"], run["id"], preference_rank=1)
    submit_bid(period["id"], junior["id"], run["id"], preference_rank=1)
    adjudicate(period["id"])  # senior wins the run
    adjudicate(period["id"])  # junior's bid passes -> demoted to board
    lock_period(period["id"])
    period = implement_period(period["id"])

    assignment = find_assignment(senior["id"], period["id"])
    return {
        "period": period,
        "run": get_run(run["id"]),
        "senior": get_operator(senior["id"]),
        "junior": get_operator(junior["id"]),
        "assignment": assignment,
    }


def setup_absence_case_with_board_cover():
    """Implemented period, senior has a SCHEDULED assignment, junior is
    EXTRA_BOARD. Absence case REPORTED for the senior on the assignment date.

    Returns dict with period, run, senior, junior, assignment, absence_case.
    """
    ctx = setup_implemented_with_board_member()
    absence = create_absence(ctx["senior"]["id"], absence_date=ctx["assignment"]["service_date"])
    ctx["absence_case"] = absence
    return ctx


# ---------------------------------------------------------------------------
# Tier 6: vacation / grievance helpers
# ---------------------------------------------------------------------------

def create_vacation_slot(period_id, week_start_date="2026-10-05", capacity=1):
    resp = api_client.create_vacation_slot(
        period_id, create_vacation_slot_payload(week_start_date=week_start_date, capacity=capacity),
        SO_HEADERS,
    )
    return get_success_data(resp)


def get_vacation_slot(period_id, slot_id):
    resp = api_client.list_vacation_slots(period_id, SO_HEADERS)
    slots = get_success_data(resp)
    for slot in slots:
        if slot["id"] == slot_id:
            return slot
    raise AssertionError(f"vacation slot {slot_id} not found in period {period_id}")


def create_grievance(filed_by_operator_id, sign_up_period_id, category="SENIORITY_BYPASS",
                     detail="detail", as_union_rep=True):
    headers = UR_HEADERS if as_union_rep else make_operator_headers(filed_by_operator_id)
    resp = api_client.create_grievance_case(
        create_grievance_case_payload(
            filed_by_operator_id, sign_up_period_id, category=category, detail=detail
        ),
        headers,
    )
    return get_success_data(resp)


def list_bids(period_id, operator_id=None):
    params = {}
    if operator_id is not None:
        params["operator_id"] = operator_id
    resp = api_client.list_bid_entries(period_id, SO_HEADERS, params=params)
    return get_success_data(resp)


def list_board_slots(period_id):
    resp = api_client.list_extra_board_slots(period_id, SO_HEADERS)
    return get_success_data(resp)


def close_out(assignment_id, actual_platform_minutes):
    resp = api_client.close_out_assignment(
        assignment_id, {"actual_platform_minutes": actual_platform_minutes}, PC_HEADERS
    )
    return get_success_data(resp)


def find_pay_record(assignment_id, variant):
    records = get_pay_records(assignment_id)
    matches = [r for r in records if r["variant"] == variant]
    assert len(matches) == 1, (
        f"expected exactly one {variant} pay record for {assignment_id}, got {len(matches)}"
    )
    return matches[0]


def setup_operator_with_two_assignments_same_week(
    weekly_ot_threshold_minutes=2400,
    daily_ot_threshold_minutes=480,
):
    """Give one ACTIVE operator two dated SCHEDULED assignments in the same ISO
    week: an OVERTIME_OFFER cover on Monday 2026-09-07 plus their own
    BID_AWARD on Tuesday 2026-09-08.

    Flow: two runs (Mon, Tue); senior operator S bids and wins the Monday run;
    operator O bids and wins the Tuesday run. After implement, S is reported
    absent on Monday and covered through the overtime path (board empty), which
    selects O (only ACTIVE candidate besides S). O therefore holds:
      - an OVERTIME_OFFER assignment dated 2026-09-07 (covering S's run), and
      - their own BID_AWARD assignment dated 2026-09-08.

    Returns dict: period, senior (S), ot_operator (O), monday_assignment,
    tuesday_assignment.
    """
    period, runs = create_picking_period(
        [
            {"run_number": "R1", "service_date": "2026-09-07",
             "pieces": [create_run_piece(300, 760, 460)]},
            {"run_number": "R2", "service_date": "2026-09-08",
             "pieces": [create_run_piece(300, 800, 500)]},
        ],
        name="WeekPair",
        daily_ot_threshold_minutes=daily_ot_threshold_minutes,
        weekly_ot_threshold_minutes=weekly_ot_threshold_minutes,
    )
    senior = create_operator(employee_number="ES", full_name="Senior", hire_date="2000-01-01")
    ot_op = create_operator(employee_number="EO", full_name="OtOp", hire_date="2005-01-01")
    submit_bid(period["id"], senior["id"], runs[0]["id"], preference_rank=1)
    submit_bid(period["id"], ot_op["id"], runs[1]["id"], preference_rank=1)
    adjudicate(period["id"])  # senior (rank 1) wins Monday run
    adjudicate(period["id"])  # ot_op (rank 2) wins Tuesday run
    lock_period(period["id"])
    period = implement_period(period["id"])

    senior_monday = find_assignment(senior["id"], period["id"], service_date="2026-09-07")
    # Suspend the senior so they are excluded from the overtime candidate pool
    # (the OT path considers ACTIVE operators only); suspension does not cancel
    # their existing SCHEDULED assignment.
    get_success_data(api_client.suspend_operator(senior["id"], SO_HEADERS))
    # Report senior absent on Monday; cover via overtime path (board is empty).
    ac = create_absence(senior["id"], absence_date="2026-09-07")
    resp = api_client.cover_absence_case(
        ac["id"],
        {"allow_overtime": True, "expected_absence_case_version": ac["version"]},
        SO_HEADERS,
    )
    covered = get_success_data(resp)
    assert covered["status"] == "COVERED", f"cover failed: {covered}"
    ot_monday = get_assignment(covered["covering_assignment_id"])
    assert ot_monday["operator_id"] == ot_op["id"], (
        "OT cover should select the only other ACTIVE operator"
    )
    tuesday = find_assignment(ot_op["id"], period["id"], service_date="2026-09-08")
    return {
        "period": period,
        "senior": senior,
        "ot_operator": ot_op,
        "monday_assignment": ot_monday,
        "tuesday_assignment": tuesday,
    }


def setup_operator_with_five_assignments_same_week(
    weekly_ot_threshold_minutes=2100,
    daily_ot_threshold_minutes=480,
):
    """Give one ACTIVE operator five dated SCHEDULED assignments in the same
    ISO week (2026-W37): OVERTIME_OFFER covers on Mon 2026-09-07 through Thu
    2026-09-10 plus their own BID_AWARD on Fri 2026-09-11.

    Flow: five runs (Mon-Fri); four senior operators S1..S4 bid and win the
    Mon-Thu runs; operator O bids and wins the Friday run. After implement,
    all four seniors are suspended up front (the OT path considers ACTIVE
    operators only; suspension does not cancel their existing SCHEDULED
    assignments), then each is reported absent on their run's date and covered
    through the overtime path with the board empty, which selects O — the
    only ACTIVE candidate.

    Closing out the four covers before the Friday award accumulates prior
    FINAL straight time in the week, letting tests exercise the weekly
    reclassification of PRD §3.8 against a threshold inside the PRD-declared
    2100..2700 range.

    Returns dict: period, seniors, ot_operator, cover_assignments (Mon-Thu,
    in date order), friday_assignment.
    """
    dates = ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]
    period, runs = create_picking_period(
        [
            {"run_number": f"R{i + 1}", "service_date": d,
             "pieces": [create_run_piece(300, 760, 460)]}
            for i, d in enumerate(dates)
        ],
        name="WeekFive",
        daily_ot_threshold_minutes=daily_ot_threshold_minutes,
        weekly_ot_threshold_minutes=weekly_ot_threshold_minutes,
    )
    seniors = [
        create_operator(employee_number=f"ES{i + 1}", full_name=f"Senior {i + 1}",
                        hire_date=f"200{i}-01-01")
        for i in range(4)
    ]
    ot_op = create_operator(employee_number="EO", full_name="OtOp", hire_date="2005-01-01")
    for senior, run in zip(seniors, runs[:4]):
        submit_bid(period["id"], senior["id"], run["id"], preference_rank=1)
    submit_bid(period["id"], ot_op["id"], runs[4]["id"], preference_rank=1)
    for _ in range(5):
        adjudicate(period["id"])  # ranks 1..5 each win their bid
    lock_period(period["id"])
    period = implement_period(period["id"])

    covers = []
    # Suspend all four seniors up front so the overtime candidate pool
    # (ACTIVE operators only, per PRD §3.7) holds exactly one member: O.
    for senior in seniors:
        get_success_data(api_client.suspend_operator(senior["id"], SO_HEADERS))
    for senior, d in zip(seniors, dates[:4]):
        ac = create_absence(senior["id"], absence_date=d)
        resp = api_client.cover_absence_case(
            ac["id"],
            {"allow_overtime": True, "expected_absence_case_version": ac["version"]},
            SO_HEADERS,
        )
        covered = get_success_data(resp)
        assert covered["status"] == "COVERED", f"cover failed: {covered}"
        cover = get_assignment(covered["covering_assignment_id"])
        assert cover["operator_id"] == ot_op["id"], (
            "OT cover should select the only ACTIVE operator"
        )
        covers.append(cover)
    friday = find_assignment(ot_op["id"], period["id"], service_date=dates[4])
    return {
        "period": period,
        "seniors": seniors,
        "ot_operator": ot_op,
        "cover_assignments": covers,
        "friday_assignment": friday,
    }
