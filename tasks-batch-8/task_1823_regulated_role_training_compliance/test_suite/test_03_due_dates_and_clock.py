"""Due-date computation (CALENDAR vs BUSINESS_DAYS) and the logical clock."""
from test_helpers import (
    TEST_USERS,
    activate_curriculum,
    add_curriculum_version,
    add_requirement,
    assert_instant_equal,
    create_active_curriculum,
    create_curriculum,
    create_employee,
    create_leave,
    create_regulator,
    create_role,
    find_assignment,
    get_employee,
    parse_instant,
    set_clock,
)

ADMIN = TEST_USERS["compliance_admin_headers"]
HR = TEST_USERS["hr_admin_headers"]


def _setup_dual_variant():
    """Two regulators (CALENDAR + BUSINESS_DAYS), one role requiring both
    curricula with due_in_days 5, clock at Monday 2026-08-03T09:00:00Z."""
    set_clock("2026-08-03T09:00:00Z")
    reg_cal = create_regulator(code="REG-CAL", name="Calendar Regulator")
    reg_bus = create_regulator(
        code="REG-BUS", name="Business Regulator", deadline_mode="BUSINESS_DAYS",
    )
    cur_cal = create_active_curriculum(reg_cal["id"], code="CUR-CAL", title="Calendar Course")
    cur_bus = create_active_curriculum(reg_bus["id"], code="CUR-BUS", title="Business Course")
    role = create_role(code="R-DUAL", name="Dual Role")
    add_requirement(role["id"], cur_cal["id"], due_in_days=5)
    add_requirement(role["id"], cur_bus["id"], due_in_days=5)
    return reg_cal, reg_bus, cur_cal, cur_bus, role


def test_calendar_mode_due_date_is_plain_day_arithmetic(api):
    """PRD §3.5: "Under `CALENDAR`, the base due date is exactly `due_in_days`
    days after the assignment instant, weekends included. Under `BUSINESS_DAYS`,
    the count starts on the day *after* the assignment date and walks forward
    counting only days that fall on a Monday through Friday — Saturdays and
    Sundays are skipped, and no holiday calendar is consulted; the base due date
    is the N-th such weekday, carrying the assignment instant's time-of-day in
    UTC."
    PRD §3.3: "Registration triggers the new-hire sweep: one training assignment
    per `ACTIVE` requirement of the employee's role, stamped with
    `trigger_source` `NEW_HIRE` and `assigned_at` equal to the logical clock at
    creation."

    Design: Difficulty/dual_variant_calc/due_date_calendar_vs_business_day_variants
    """
    _, _, cur_cal, _, role = _setup_dual_variant()
    emp = create_employee("E-DUAL-1", role["id"], full_name="Dual Hire")

    asg = find_assignment(emp["id"], curriculum_id=cur_cal["id"])
    assert_instant_equal(asg["assigned_at"], "2026-08-03T09:00:00Z", "assigned_at")
    assert_instant_equal(asg["base_due_at"], "2026-08-08T09:00:00Z", "base_due_at")
    assert asg["trigger_source"] == "NEW_HIRE"


def test_business_day_mode_skips_weekends(api):
    """PRD §3.5: "Under `CALENDAR`, the base due date is exactly `due_in_days`
    days after the assignment instant, weekends included. Under `BUSINESS_DAYS`,
    the count starts on the day *after* the assignment date and walks forward
    counting only days that fall on a Monday through Friday — Saturdays and
    Sundays are skipped, and no holiday calendar is consulted; the base due date
    is the N-th such weekday, carrying the assignment instant's time-of-day in
    UTC."

    Design: Difficulty/dual_variant_calc/due_date_calendar_vs_business_day_variants
    """
    _, _, cur_cal, cur_bus, role = _setup_dual_variant()
    emp = create_employee("E-DUAL-1", role["id"], full_name="Dual Hire")

    cal_due = find_assignment(emp["id"], curriculum_id=cur_cal["id"])["base_due_at"]
    bus_due = find_assignment(emp["id"], curriculum_id=cur_bus["id"])["base_due_at"]
    assert_instant_equal(bus_due, "2026-08-10T09:00:00Z", "business-day base_due_at")
    assert parse_instant(cal_due) != parse_instant(bus_due), (
        "identical inputs must yield different due dates across the two modes"
    )


def test_business_day_due_from_friday_lands_on_monday(api):
    """PRD §3.5: "Under `BUSINESS_DAYS`, the count starts on the day *after* the
    assignment date and walks forward counting only days that fall on a Monday
    through Friday — Saturdays and Sundays are skipped, and no holiday calendar
    is consulted; the base due date is the N-th such weekday, carrying the
    assignment instant's time-of-day in UTC."

    Design: Corner/calculations/business_day_due_skips_weekend_from_friday
    """
    set_clock("2026-08-07T09:00:00Z")  # a Friday
    reg = create_regulator(code="REG-FRI", name="Friday Regulator", deadline_mode="BUSINESS_DAYS")
    cur = create_active_curriculum(reg["id"], code="CUR-FRI", title="Friday Course")
    role = create_role(code="R-FRI", name="FRI Role")
    add_requirement(role["id"], cur["id"], due_in_days=1)

    emp = create_employee("E-FRI-1", role["id"], full_name="Fri Emp",
                          hired_at="2026-08-07T09:00:00Z")
    asg = find_assignment(emp["id"], curriculum_id=cur["id"])
    assert_instant_equal(asg["assigned_at"], "2026-08-07T09:00:00Z", "assigned_at")
    assert_instant_equal(asg["base_due_at"], "2026-08-10T09:00:00Z", "base_due_at")


def test_default_logical_clock_is_2026_08_01(api):
    """PRD §2.5: "Before any explicit clock-setting call has been made, the
    logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back
    to wall-clock time at any point afterwards."
    PRD §3.3: "Registration triggers the new-hire sweep: one training assignment
    per `ACTIVE` requirement of the employee's role, stamped with
    `trigger_source` `NEW_HIRE` and `assigned_at` equal to the logical clock at
    creation."

    Design: Corner/endpoints/default_clock_is_2026_08_01_without_clock_set
    """
    # Deliberately NO clock-setting call in this test.
    reg = create_regulator(code="REG-DEF8", name="DEF8 Regulator")
    cur = create_curriculum(reg["id"], code="CUR-DEF8", title="DEF8 Course")
    add_curriculum_version(cur["id"], version_no=1, effective_from="2020-01-01T00:00:00Z")
    cur = activate_curriculum(cur["id"])
    role = create_role(code="R-DEF8", name="DEF8 Role")
    add_requirement(role["id"], cur["id"], due_in_days=1)

    emp = create_employee("E-DEF8", role["id"], full_name="Def8 Emp",
                          hired_at="2026-01-15T00:00:00Z")
    asg = find_assignment(emp["id"], curriculum_id=cur["id"])
    assert_instant_equal(asg["assigned_at"], "2026-08-01T00:00:00Z", "assigned_at")
    assert_instant_equal(asg["base_due_at"], "2026-08-02T00:00:00Z", "base_due_at")


def test_assignment_born_frozen_for_employee_on_leave(api):
    """PRD §3.2: "Adding a requirement has an immediate seeding effect known as
    the requirement sweep: for every employee whose `current_role_id` is that
    role and whose `status` is `ACTIVE` or `ON_LEAVE`, the system creates a
    training assignment with `trigger_source` `REQUIREMENT_SWEEP` — born with
    its deadline dimension `FROZEN` for employees on leave."

    Design: Corner/state_machines/assignment_born_frozen_when_employee_on_leave
    """
    set_clock("2026-08-03T09:00:00Z")
    reg = create_regulator(code="REG-FRZ", name="FRZ Regulator")
    cur = create_active_curriculum(reg["id"], code="CUR-FRZ", title="FRZ Course")
    role = create_role(code="R-FRZ", name="FRZ Role")
    emp = create_employee("E-FRZ-1", role["id"], full_name="FRZ Emp")
    create_leave(emp["id"])  # 2026-08-03 .. 2026-08-07 covers the clock

    employee = get_employee(emp["id"])
    assert employee["status"] == "ON_LEAVE"

    add_requirement(role["id"], cur["id"], due_in_days=5)
    asg = find_assignment(emp["id"], curriculum_id=cur["id"])
    assert asg["progress_status"] == "ASSIGNED"
    assert asg["deadline_status"] == "FROZEN", "born frozen because employee is on leave"
    assert_instant_equal(asg["base_due_at"], "2026-08-08T09:00:00Z", "base_due_at")
    assert asg["trigger_source"] == "REQUIREMENT_SWEEP"
