"""Moonlight rolling-hour cap, half-open assignment overlap, and the fiscal
budget gate — with exact boundary precision on each metric."""
from test_helpers import (
    ApiErrorId,
    assign_staff,
    create_assignment_payload,
    create_published_program,
    create_staff_physician,
    get_program,
    get_slot_for_date,
    serve_assignment,
    set_clock,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Moonlight cap boundary (equality allowed) ───────────────────────

def _setup_cap_boundary_program(cap_hours):
    """PUBLISHED 3-weekday program, fiscal rule disarmed; one STAFF physician
    with the given cap; first weekday already assigned."""
    program = create_published_program(
        name="Cards Cap Boundary",
        period_start="2026-09-08",
        period_end="2026-09-10",
        payroll_budget_cents=5_000_000,
    )
    physician = create_staff_physician(
        "Dr Alvarez", moonlight_cap_hours=cap_hours
    )
    slot1 = get_slot_for_date(program["id"], "2026-09-08")
    assign_staff(slot1["id"], physician["id"])  # 24 rolling hours
    return program, physician


def test_moonlight_cap_exact_fit_accepted(api):
    """PRD §2.9: "A new commitment is allowed only when the projected rolling
    hours plus the new call's own 24 hours remain less than or equal to the
    physician's `moonlight_cap_hours` (default 96). An exact fit is permitted;
    anything more is rejected with `ERR_MOONLIGHT_CAP_EXCEEDED`."

    Cap 48, one 24h assignment held: the second 24h call lands exactly on
    48 == 48 and is accepted.

    Design: Difficulty/boundary_precision_check/moonlight_cap_equality_allowed_overage_rejected
    """
    program, physician = _setup_cap_boundary_program(48)
    slot2 = get_slot_for_date(program["id"], "2026-09-09")
    resp = api.create_assignment(
        create_assignment_payload(slot2["id"], physician["id"]), ADMIN
    )
    assignment = validate_success(resp, 201)
    assert assignment["status"] == "SCHEDULED"


def test_moonlight_cap_overage_rejected(api):
    """PRD §2.9: "An exact fit is permitted; anything more is rejected with
    `ERR_MOONLIGHT_CAP_EXCEEDED`."

    Cap 48 with 48 already committed: a third 24h call would reach 72 > 48.

    Design: Difficulty/boundary_precision_check/moonlight_cap_equality_allowed_overage_rejected
    """
    program, physician = _setup_cap_boundary_program(48)
    slot2 = get_slot_for_date(program["id"], "2026-09-09")
    assign_staff(slot2["id"], physician["id"])  # now exactly at cap
    slot3 = get_slot_for_date(program["id"], "2026-09-10")
    resp = api.create_assignment(
        create_assignment_payload(slot3["id"], physician["id"]), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_MOONLIGHT_CAP_EXCEEDED, 409)
    slot_after = validate_success(api.get_slot(slot3["id"], ADMIN))
    assert slot_after["status"] == "OPEN"


# ─── Priority pair: business safety beats the fiscal gate ────────────

def _setup_dual_fail_program():
    """PUBLISHED 3-weekday program with budget exactly two weekday primaries
    (100000); one STAFF physician with cap 48 already at 48 committed hours and
    the reserve exactly at budget."""
    program = create_published_program(
        name="Cards Dual Fail",
        period_start="2026-09-08",
        period_end="2026-09-10",
        payroll_budget_cents=100_000,
    )
    physician = create_staff_physician("Dr Alvarez", moonlight_cap_hours=48)
    assign_staff(get_slot_for_date(program["id"], "2026-09-08")["id"], physician["id"])
    second = assign_staff(
        get_slot_for_date(program["id"], "2026-09-09")["id"], physician["id"]
    )
    return program, physician, second


def test_dual_fail_second_assignment_at_equality_accepted(api):
    """PRD §2.9: "An exact fit is permitted; anything more is rejected with
    `ERR_MOONLIGHT_CAP_EXCEEDED`."
    PRD §2.7: "must remain less than or equal to the program's
    `payroll_budget_cents`; equality is permitted".

    The second assignment lands at 48 == 48 hours and 100000 == 100000 cents;
    both equality semantics allow it.

    Design: Difficulty/priority_pair_validation_conflict/manual_assignment_safety_beats_fiscal_budget
    """
    _program, _physician, second = _setup_dual_fail_program()
    assert second["status"] == "SCHEDULED"


def test_dual_fail_third_assignment_reports_moonlight_before_budget(api):
    """PRD §2.11: "When a request would fail several checks at once, the server
    reports the earliest failure in a fixed evaluation order rather than an
    arbitrary one: ... 8. Business safety — ... the moonlight cap ... 11. The
    fiscal gate — `ERR_PAYROLL_BUDGET_EXCEEDED` — always evaluated last."

    The third assignment breaches both the moonlight cap (72 > 48) and the
    budget (150000 > 100000); the safety error must win.

    Design: Difficulty/priority_pair_validation_conflict/manual_assignment_safety_beats_fiscal_budget
    """
    program, physician, _second = _setup_dual_fail_program()
    slot3 = get_slot_for_date(program["id"], "2026-09-10")
    resp = api.create_assignment(
        create_assignment_payload(slot3["id"], physician["id"]), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_MOONLIGHT_CAP_EXCEEDED, 409)


# ─── Half-open assignment overlap (adjacency allowed) ────────────────

def _setup_adjacency_program():
    """PUBLISHED 3-day program with two weekday primaries per day; one STAFF
    physician with a 192-hour cap."""
    program = create_published_program(
        name="Cards Adjacency",
        period_start="2026-09-08",
        period_end="2026-09-10",
        payroll_budget_cents=5_000_000,
        weekday_primary_required=2,
    )
    physician = create_staff_physician("Dr Alvarez", moonlight_cap_hours=192)
    return program, physician


def test_assignment_adjacent_days_allowed(api):
    """PRD §2.6: "Assignment conflict checks instead use half-open window
    overlap: two calls whose windows merely touch at 07:00 UTC do not conflict,
    so a physician may legitimately take consecutive call days."

    Design: Difficulty/resource_temporal_overlap/assignment_half_open_adjacency_allowed_same_day_conflict
    """
    program, physician = _setup_adjacency_program()
    for date in ("2026-09-08", "2026-09-09", "2026-09-10"):
        slot = get_slot_for_date(program["id"], date, index=0)
        assignment = assign_staff(slot["id"], physician["id"])
        assert assignment["status"] == "SCHEDULED"


def test_assignment_same_day_overlap_rejected(api):
    """PRD §3.3: "the new commitment must not half-open-overlap any of the
    physician's SCHEDULED, ACTIVATED, or SERVED assignments — adjacent call
    days are allowed (`ERR_ASSIGNMENT_OVERLAP`)".

    The second slot on 2026-09-10 has the identical half-open window as the
    position-1 slot the physician already holds.

    Design: Difficulty/resource_temporal_overlap/assignment_half_open_adjacency_allowed_same_day_conflict
    """
    program, physician = _setup_adjacency_program()
    for date in ("2026-09-08", "2026-09-09", "2026-09-10"):
        assign_staff(get_slot_for_date(program["id"], date, index=0)["id"], physician["id"])
    same_day_second = get_slot_for_date(program["id"], "2026-09-10", index=1)
    resp = api.create_assignment(
        create_assignment_payload(same_day_second["id"], physician["id"]), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_OVERLAP, 409)
    slot_after = validate_success(api.get_slot(same_day_second["id"], ADMIN))
    assert slot_after["status"] == "OPEN"


# ─── Rolling 28-day window inclusion boundary ────────────────────────

def _setup_rolling_window_program():
    """PUBLISHED long-range program; P1 (cap 48) assigned to the 2026-08-22 and
    2026-08-23 weekend slots and to 2026-09-19 position 1, then the two August
    assignments are served."""
    program = create_published_program(
        name="Cards Rolling",
        period_start="2026-08-22",
        period_end="2026-09-19",
        payroll_budget_cents=1_000_000,
        weekday_primary_required=1,
        weekend_primary_required=2,
    )
    physician = create_staff_physician("Dr A", moonlight_cap_hours=48)
    a1 = assign_staff(
        get_slot_for_date(program["id"], "2026-08-22")["id"], physician["id"]
    )
    a2 = assign_staff(
        get_slot_for_date(program["id"], "2026-08-23")["id"], physician["id"]
    )
    a3_slot = get_slot_for_date(program["id"], "2026-09-19", index=0)
    return program, physician, a1, a2, a3_slot


def test_rolling_window_excludes_call_at_d_minus_28(api):
    """PRD §2.9: "Fatigue governance uses a rolling window of 28 dates: for a
    slot on date D, the window is the closed interval from 27 days before D
    through D itself."
    PRD §2.9: "An exact fit is permitted; anything more is rejected with
    `ERR_MOONLIGHT_CAP_EXCEEDED`."

    For D = 2026-09-19 the window starts 2026-08-23; the 2026-08-22 call falls
    outside it, so position 1 (24 + 24 == 48 == cap) is accepted.

    Design: Corner/calculations/rolling_window_28day_inclusion_boundary
    """
    program, physician, _a1, _a2, a3_slot = _setup_rolling_window_program()
    resp = api.create_assignment(
        create_assignment_payload(a3_slot["id"], physician["id"]), ADMIN
    )
    assignment = validate_success(resp, 201)
    assert assignment["status"] == "SCHEDULED"


def test_rolling_window_includes_call_at_d_minus_27(api):
    """PRD §2.9: "Fatigue governance uses a rolling window of 28 dates: for a
    slot on date D, the window is the closed interval from 27 days before D
    through D itself."

    The 2026-08-23 call (D-27) is inside the window: position 2 on 2026-09-19
    would total 72 > 48 and is rejected.

    Design: Corner/calculations/rolling_window_28day_inclusion_boundary
    """
    program, physician, a1, a2, a3_slot = _setup_rolling_window_program()
    assign_staff(a3_slot["id"], physician["id"])
    set_clock("2026-08-24T08:00:00Z")
    serve_assignment(a1["id"])
    serve_assignment(a2["id"])

    pos2 = get_slot_for_date(program["id"], "2026-09-19", index=1)
    resp = api.create_assignment(
        create_assignment_payload(pos2["id"], physician["id"]), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_MOONLIGHT_CAP_EXCEEDED, 409)


# ─── Fiscal gate, pure (moonlight disarmed) ──────────────────────────

def test_payroll_budget_exceeded_pure_fiscal(api):
    """PRD §2.7: "On each, the resulting reserve — the current
    `payroll_reserved_cents` plus the new assignment's projected pay — must
    remain less than or equal to the program's `payroll_budget_cents`; equality
    is permitted, and a breach is rejected with `ERR_PAYROLL_BUDGET_EXCEEDED`
    (HTTP 402)."

    With the moonlight cap disarmed (192h), the second assignment lands the
    reserve exactly on the 100000 budget (allowed) and the third breaches it.

    Design: Corner/validations/payroll_budget_exceeded_pure_fiscal
    """
    program = create_published_program(
        name="Cards Fiscal",
        period_start="2026-09-08",
        period_end="2026-09-10",
        payroll_budget_cents=100_000,
    )
    physician = create_staff_physician("Dr A", moonlight_cap_hours=192)
    assign_staff(get_slot_for_date(program["id"], "2026-09-08")["id"], physician["id"])
    second = assign_staff(
        get_slot_for_date(program["id"], "2026-09-09")["id"], physician["id"]
    )
    assert second["status"] == "SCHEDULED"
    program_after = get_program(program["id"])
    assert program_after["payroll_reserved_cents"] == 100_000

    slot3 = get_slot_for_date(program["id"], "2026-09-10")
    resp = api.create_assignment(
        create_assignment_payload(slot3["id"], physician["id"]), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_PAYROLL_BUDGET_EXCEEDED, 402)
