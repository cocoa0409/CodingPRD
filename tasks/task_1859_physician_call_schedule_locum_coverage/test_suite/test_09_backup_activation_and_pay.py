"""Backup activation windows and the call-pay dual variants: projected pay at
creation vs actual pay at serve time, tiered multipliers, and the pinned
per-entry rounding order of the program payroll total."""
from test_helpers import (
    ApiErrorId,
    activate_backup,
    activate_backup_payload,
    assign_staff,
    assert_pay_entry,
    cancel_assignment,
    create_published_program,
    create_staff_physician,
    get_pay_entry_for_assignment,
    get_program,
    get_slot_for_date,
    make_physician_headers,
    serve_assignment,
    set_clock,
    setup_published_with_assignment,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Activation preconditions ────────────────────────────────────────

def test_activate_backup_on_primary_slot_rejected(api):
    """PRD §3.3: "activates an assignment that is SCHEDULED
    (`ERR_ASSIGNMENT_NOT_ACTIVATABLE`), whose slot is BACKUP
    (`ERR_ACTIVATION_REQUIRES_BACKUP_SLOT`), at a moment inside the activation
    window that runs from `window_start` through two hours after `window_end`,
    both bounds inclusive (outside it, `ERR_ACTIVATION_WINDOW_CLOSED`)".

    Design: Corner/state_machines/activate_backup_on_primary_slot_rejected
    """
    _program, _physician, _slot, assignment = setup_published_with_assignment()
    set_clock("2026-09-08T10:00:00Z")  # inside the call window
    resp = api.activate_backup(
        assignment["id"], activate_backup_payload("SURGE"), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_ACTIVATION_REQUIRES_BACKUP_SLOT, 409)
    after = validate_success(api.get_assignment(assignment["id"], ADMIN))
    assert after["status"] == "SCHEDULED"
    assert after["activated_at"] is None


def test_activate_cancelled_backup_returns_not_activatable(api):
    """PRD §3.3: "activates an assignment that is SCHEDULED
    (`ERR_ASSIGNMENT_NOT_ACTIVATABLE`)".

    Design: Corner/errors/activate_cancelled_backup_returns_not_activatable
    """
    _program, _physician, _slot, assignment = setup_published_with_assignment(
        weekday_primary_required=0, weekday_backup_required=1, call_type="BACKUP"
    )
    cancel_assignment(assignment["id"])
    set_clock("2026-09-08T10:00:00Z")
    resp = api.activate_backup(
        assignment["id"], activate_backup_payload("SURGE"), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVATABLE, 409)


def test_activation_grace_boundary_exact_vs_one_second_over(api):
    """PRD §3.3: "at a moment inside the activation window that runs from
    `window_start` through two hours after `window_end`, both bounds inclusive
    (outside it, `ERR_ACTIVATION_WINDOW_CLOSED`)".

    The 2026-09-08 window ends 2026-09-09T07:00:00Z, so the grace boundary is
    2026-09-09T09:00:00Z: exactly on it is accepted, one second later fails.

    Design: Corner/validations/activation_grace_boundary_exact_vs_one_second_over
    """
    program = create_published_program(
        name="Cards Grace",
        period_start="2026-09-08",
        period_end="2026-09-08",
        weekday_primary_required=0,
        weekday_backup_required=2,
    )
    p1 = create_staff_physician("Dr A")
    p2 = create_staff_physician("Dr B")
    slot_b1 = get_slot_for_date(program["id"], "2026-09-08", call_type="BACKUP", index=0)
    slot_b2 = get_slot_for_date(program["id"], "2026-09-08", call_type="BACKUP", index=1)
    a1 = assign_staff(slot_b1["id"], p1["id"])
    a2 = assign_staff(slot_b2["id"], p2["id"])

    set_clock("2026-09-09T09:00:00Z")  # exactly window_end + 2h
    resp = api.activate_backup(
        a1["id"], activate_backup_payload(), make_physician_headers(p1["id"])
    )
    activated = validate_success(resp, 200)
    assert activated["status"] == "ACTIVATED"
    assert activated["activated_at"] is not None

    set_clock("2026-09-09T09:00:01Z")  # one second past the grace end
    resp = api.activate_backup(
        a2["id"], activate_backup_payload("SURGE"), make_physician_headers(p2["id"])
    )
    validate_error(resp, ApiErrorId.ERR_ACTIVATION_WINDOW_CLOSED, 409)
    after = validate_success(api.get_assignment(a2["id"], ADMIN))
    assert after["status"] == "SCHEDULED"


# ─── Pay: backup served without activation gets no multiplier ────────

def _setup_backup_day(activate):
    """PUBLISHED single-day program with one weekday BACKUP slot; one STAFF
    physician assigned and served (after activation, when requested)."""
    program = create_published_program(
        name="Cards Backup Day",
        period_start="2026-09-08",
        period_end="2026-09-08",
        payroll_budget_cents=500_000,
        weekday_primary_required=0,
        weekday_backup_required=1,
    )
    physician = create_staff_physician("Dr Alvarez")
    slot = get_slot_for_date(program["id"], "2026-09-08")
    assignment = assign_staff(slot["id"], physician["id"])
    if activate:
        set_clock("2026-09-08T10:00:00Z")  # inside the call window
        activate_backup(assignment["id"])
    set_clock("2026-09-09T08:00:00Z")  # past window_end 2026-09-09T07:00:00Z
    serve_assignment(assignment["id"])
    return program, physician, slot, assignment


def test_backup_served_without_activation_gets_no_multiplier(api):
    """PRD §3.3: "then by `backup_activation_multiplier` (default 2.0) when the
    assignment was ACTIVATED before serving and by one otherwise".

    Design: Corner/calculations/backup_served_without_activation_gets_no_multiplier
    """
    _program, _physician, _slot, assignment = _setup_backup_day(activate=False)
    entry = get_pay_entry_for_assignment(assignment["id"])
    assert_pay_entry(entry)
    assert entry["amount_cents"] == 20000  # 20000 base x 1.0 weekday, no activation
    assert entry["activation_applied"] is False
    assert entry["premium_applied"] is False


# ─── Dual variant: projected vs actual for an activated backup ───────

def test_call_pay_projected_vs_actual_backup_activation_amounts(api):
    """PRD §3.3: "the projected pay variant is computed — activation assumed
    absent, the premium tier evaluated on projected hours — and stored in
    `projected_pay_cents`"; "Serving an activated backup therefore pays more
    than its projection — the projected and actual variants diverge by design."

    Projected: 20000 (activation assumed false). Actual: 20000 x 1.0 weekday
    x 2.0 activated = 40000, no premium (0 prior served hours < 40).

    Design: Difficulty/dual_variant_calc/call_pay_projected_vs_actual_backup_activation
    """
    # Build to just before serving so we can observe the projection first.
    program = create_published_program(
        name="Cards Backup Day",
        period_start="2026-09-08",
        period_end="2026-09-08",
        payroll_budget_cents=500_000,
        weekday_primary_required=0,
        weekday_backup_required=1,
    )
    physician = create_staff_physician("Dr Alvarez")
    slot = get_slot_for_date(program["id"], "2026-09-08")
    resp = api.create_assignment(
        {"slot_id": slot["id"], "physician_id": physician["id"]}, ADMIN
    )
    assignment = validate_success(resp, 201)
    assert assignment["projected_pay_cents"] == 20000, (
        "projection fixes the activation multiplier to 1.0 at creation"
    )

    set_clock("2026-09-08T10:00:00Z")
    activate_backup(assignment["id"])
    set_clock("2026-09-09T08:00:00Z")
    serve_assignment(assignment["id"])

    entry = get_pay_entry_for_assignment(assignment["id"])
    assert entry["amount_cents"] == 40000
    assert entry["amount_cents"] != assignment["projected_pay_cents"]


def test_call_pay_actual_variant_entry_fields(api):
    """PRD §3.3: "The entry records which multipliers fired through
    `activation_applied` and `premium_applied`, and copies `slot_date`,
    `call_type`, and `date_type` from the slot alongside its `assignment_id`,
    `physician_id`, and `program_id`."; the base rate is "snapshotted onto the
    entry as `base_rate_cents`".

    Design: Difficulty/dual_variant_calc/call_pay_projected_vs_actual_backup_activation
    """
    program, physician, _slot, assignment = _setup_backup_day(activate=True)
    entry = get_pay_entry_for_assignment(assignment["id"])
    assert_pay_entry(entry)
    assert entry["amount_cents"] == 40000
    assert entry["activation_applied"] is True
    assert entry["premium_applied"] is False
    assert entry["base_rate_cents"] == 20000
    assert entry["call_type"] == "BACKUP"
    assert entry["date_type"] == "WEEKDAY"
    assert entry["slot_date"] == "2026-09-08"
    assert entry["assignment_id"] == assignment["id"]
    assert entry["physician_id"] == physician["id"]
    assert entry["program_id"] == program["id"]
    assert entry["status"] == "ACCRUED"


# ─── Combinatorial formula: four-input tiered pay ────────────────────

def _setup_labor_day_program():
    """PUBLISHED program 2026-09-03..2026-09-07 with 2026-09-07 a HOLIDAY
    (backup_rate 21500); P1 served two weekday primaries (48 rolling served
    hours -> premium tier) and then served the ACTIVATED holiday backup."""
    program = create_published_program(
        name="Cards Labor Day",
        period_start="2026-09-03",
        period_end="2026-09-07",
        holiday_dates=["2026-09-07"],
        payroll_budget_cents=5_000_000,
        backup_rate_cents=21500,
        weekday_primary_required=1,
        holiday_backup_required=1,
    )
    physician = create_staff_physician("Dr Alvarez")
    a_0903 = assign_staff(get_slot_for_date(program["id"], "2026-09-03")["id"], physician["id"])
    a_0904 = assign_staff(get_slot_for_date(program["id"], "2026-09-04")["id"], physician["id"])
    a_0907 = assign_staff(get_slot_for_date(program["id"], "2026-09-07")["id"], physician["id"])

    set_clock("2026-09-05T08:00:00Z")  # both weekday windows have ended
    serve_assignment(a_0903["id"])
    serve_assignment(a_0904["id"])

    set_clock("2026-09-07T10:00:00Z")  # inside the holiday call window
    activate_backup(a_0907["id"])
    set_clock("2026-09-08T08:00:00Z")
    serve_assignment(a_0907["id"])
    return program, physician, a_0903, a_0904, a_0907


def test_assignment_pay_tiered_branching_four_inputs_amount(api):
    """PRD §3.3: "The actual pay variant takes the base rate for the slot's call
    type ... multiplies it by the date multiplier (`holiday_multiplier`, default
    1.5, on HOLIDAY dates; ...) then by `backup_activation_multiplier` (default
    2.0) when the assignment was ACTIVATED before serving ..., and then by
    `moonlight_premium_multiplier` (default 1.15) when a STAFF physician reached
    the premium tier of §2.9 on served-only hours ...; the product is rounded
    half-up to whole cents in exactly one rounding step, applied after all
    multipliers, and stored immutably as `amount_cents`."

    21500 x 1.5 HOLIDAY x 2.0 ACTIVATED x 1.15 premium = 74175.

    Design: Difficulty/combinatorial_formula/assignment_pay_tiered_branching_four_inputs
    """
    _program, _physician, _a1, _a2, a_0907 = _setup_labor_day_program()
    entry = get_pay_entry_for_assignment(a_0907["id"])
    assert_pay_entry(entry)
    assert entry["amount_cents"] == 74175
    assert entry["date_type"] == "HOLIDAY"
    assert entry["activation_applied"] is True
    assert entry["premium_applied"] is True
    assert entry["base_rate_cents"] == 21500


def test_assignment_pay_premium_threshold_gates_below_40_served_hours(api):
    """PRD §2.9: "When those served hours reach or exceed the program's
    `moonlight_premium_threshold_hours` (default 40), the premium multiplier of
    §3.3 applies to that call's pay."

    The two weekday primaries are served with 0 and 24 prior served hours —
    both below 40 — so no premium applies: 50000 each.

    Design: Difficulty/combinatorial_formula/assignment_pay_tiered_branching_four_inputs
    """
    _program, _physician, a_0903, a_0904, _a_0907 = _setup_labor_day_program()
    for served in (a_0903, a_0904):
        entry = get_pay_entry_for_assignment(served["id"])
        assert entry["amount_cents"] == 50000
        assert entry["premium_applied"] is False
        assert entry["activation_applied"] is False


# ─── Nested rounding: per-entry round then integer sum ───────────────

def _setup_rounding_program():
    """PUBLISHED program 2026-09-08..2026-09-19 (weekday primaries, weekend
    backups at 21500); P1 (cap 120) serves both primaries (48 served hours ->
    premium tier) and all three weekend backups."""
    program = create_published_program(
        name="Cards Rounding",
        period_start="2026-09-08",
        period_end="2026-09-19",
        payroll_budget_cents=5_000_000,
        backup_rate_cents=21500,
        weekday_primary_required=1,
        weekend_backup_required=1,
    )
    physician = create_staff_physician("Dr Alvarez", moonlight_cap_hours=120)
    a_0908 = assign_staff(get_slot_for_date(program["id"], "2026-09-08")["id"], physician["id"])
    a_0909 = assign_staff(get_slot_for_date(program["id"], "2026-09-09")["id"], physician["id"])
    backups = {}
    for date in ("2026-09-12", "2026-09-13", "2026-09-19"):
        slot = get_slot_for_date(program["id"], date, call_type="BACKUP")
        backups[date] = assign_staff(slot["id"], physician["id"])

    set_clock("2026-09-10T08:00:00Z")
    serve_assignment(a_0908["id"])
    serve_assignment(a_0909["id"])
    set_clock("2026-09-13T08:00:00Z")
    serve_assignment(backups["2026-09-12"]["id"])
    set_clock("2026-09-14T08:00:00Z")
    serve_assignment(backups["2026-09-13"]["id"])
    set_clock("2026-09-20T08:00:00Z")
    serve_assignment(backups["2026-09-19"]["id"])
    return program, physician, (a_0908, a_0909), backups


def test_payroll_total_per_entry_rounding_order(api):
    """PRD §2.7: "Rounding order is pinned. Each pay entry's amount is rounded
    half-up to whole cents at serve time, and the program totals sum the
    already-rounded integers. The alternative order — summing unrounded
    products and rounding once at the end — yields different cents and is
    forbidden."

    Each premium weekend backup: 21500 x 1.25 x 1.15 = 30906.25, rounded
    per entry to 30906. Program accrual: 2 x 50000 + 3 x 30906 = 192718
    (sum-then-round would give 192719).

    Design: Difficulty/combinatorial_formula/payroll_total_per_entry_rounding_order
    """
    program, _physician, _primaries, backups = _setup_rounding_program()
    for date, assignment in backups.items():
        entry = get_pay_entry_for_assignment(assignment["id"])
        assert entry["amount_cents"] == 30906, (
            f"backup {date}: raw 30906.25 must round half-up per entry to 30906"
        )
        assert entry["premium_applied"] is True

    program_after = get_program(program["id"])
    assert program_after["payroll_accrued_cents"] == 192718


def test_payroll_total_primaries_pay_flat_and_reserve_drains(api):
    """PRD §3.3: "The reserve releases the assignment's projected pay,
    `payroll_accrued_cents` increases by `amount_cents`, and the program
    `version` increments."

    The two weekday primaries are served below the premium tier (0 and 24
    prior served hours): 50000 each, no premium. With everything served, the
    reserve has fully drained.

    Design: Difficulty/combinatorial_formula/payroll_total_per_entry_rounding_order
    """
    program, _physician, primaries, _backups = _setup_rounding_program()
    for served in primaries:
        entry = get_pay_entry_for_assignment(served["id"])
        assert entry["amount_cents"] == 50000
        assert entry["premium_applied"] is False

    program_after = get_program(program["id"])
    assert program_after["payroll_reserved_cents"] == 0
    assert program_after["payroll_accrued_cents"] == 192718
