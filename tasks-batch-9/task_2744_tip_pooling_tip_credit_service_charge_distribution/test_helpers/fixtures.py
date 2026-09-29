"""Composite setup helpers.

Every test starts against an empty database, so each helper below builds its
preconditions from scratch through PRD-declared endpoints only. Setup calls use
the lenient ``get_success_data`` validator so a broken precondition reads as a
setup failure rather than as a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ASSIGNMENT_EFFECTIVE_FROM,
    BUSINESS_DATE_1,
    BUSINESS_DATE_2,
    BUSINESS_DATE_3,
    BUSINESS_DATE_4,
    BUSINESS_DATE_5,
    CLOCK_NOW,
    NOTICE_ACKNOWLEDGED_AT,
    PERIOD_END_DATE,
    PERIOD_START_DATE,
)
from .factories import (
    adjudicate_dispute_payload,
    create_back_wage_correction_payload,
    create_dispute_payload,
    create_employee_payload,
    create_job_role_payload,
    create_location_payload,
    create_pay_period_payload,
    create_role_assignment_payload,
    create_service_charge_payload,
    create_shift_payload,
    create_shift_tip_pool_payload,
    create_tip_pool_policy_payload,
    declare_tips_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_employee_headers,
)

ADMIN = TEST_USERS["payroll_admin_headers"]
PREPARER = TEST_USERS["payroll_preparer_headers"]
PREPARER_ALT = TEST_USERS["payroll_preparer_alt_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
COMPLIANCE_ALT = TEST_USERS["compliance_officer_alt_headers"]


# ---------------------------------------------------------------------------
# Primitive setup steps
# ---------------------------------------------------------------------------
def set_logical_clock(current_utc: str = CLOCK_NOW, headers: dict = ADMIN) -> None:
    """Move the server's logical clock. Every world starts with this call."""
    get_success_data(api_client.set_clock(set_clock_payload(current_utc), headers))


def new_location(headers: dict = ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_location(create_location_payload(**overrides), headers)
    )


def new_job_role(headers: dict = ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_job_role(create_job_role_payload(**overrides), headers)
    )


def new_employee(location_id: str, headers: dict = ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_employee(
            create_employee_payload(location_id, **overrides), headers
        )
    )


def new_role_assignment(
    employee_id: str, job_role_id: str, headers: dict = ADMIN, **overrides
) -> dict:
    return get_success_data(
        api_client.create_role_assignment(
            create_role_assignment_payload(employee_id, job_role_id, **overrides),
            headers,
        )
    )


def new_pay_period(location_id: str, headers: dict = PREPARER, **overrides) -> dict:
    return get_success_data(
        api_client.create_pay_period(
            create_pay_period_payload(location_id, **overrides), headers
        )
    )


def new_shift(
    employee_id: str,
    location_id: str,
    job_role_id: str,
    pay_period_id: str,
    headers: dict = PREPARER,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_shift(
            create_shift_payload(
                employee_id, location_id, job_role_id, pay_period_id, **overrides
            ),
            headers,
        )
    )


def close_shift(shift_id: str, headers: dict = PREPARER) -> dict:
    return get_success_data(api_client.close_shift(shift_id, headers))


def declare_shift_tips(
    shift_id: str,
    employee_id: str,
    declared_cash_tips_cents: int = 0,
    declared_charged_tips_cents: int = 0,
) -> dict:
    """Declared by the shift's own employee, so ownership resolves."""
    return get_success_data(
        api_client.declare_tips(
            shift_id,
            declare_tips_payload(
                declared_cash_tips_cents, declared_charged_tips_cents
            ),
            make_employee_headers(employee_id),
        )
    )


def void_shift(shift_id: str, reason: str = "recorded in error") -> dict:
    return get_success_data(
        api_client.void_shift(shift_id, PREPARER, {"reason": reason})
    )


def new_service_charge(location_id: str, headers: dict = PREPARER, **overrides) -> dict:
    return get_success_data(
        api_client.create_service_charge(
            create_service_charge_payload(location_id, **overrides), headers
        )
    )


def new_draft_policy(location_id: str, headers: dict = ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_tip_pool_policy(
            create_tip_pool_policy_payload(location_id, **overrides), headers
        )
    )


def activate_policy(
    policy_id: str, expected_location_version: int, headers: dict = COMPLIANCE
) -> dict:
    return get_success_data(
        api_client.activate_tip_pool_policy(
            policy_id, {"expected_location_version": expected_location_version}, headers
        )
    )


def new_active_policy(location_id: str, location_version: int, **overrides) -> dict:
    """Draft a policy for the unit and activate it under the unit's version."""
    policy = new_draft_policy(location_id, **overrides)
    return activate_policy(policy["id"], location_version)


def new_pool(
    location_id: str, business_date: str = BUSINESS_DATE_2, headers: dict = PREPARER
) -> dict:
    return get_success_data(
        api_client.create_shift_tip_pool(
            create_shift_tip_pool_payload(location_id, business_date=business_date),
            headers,
        )
    )


def distribute_pool(pool_id: str, headers: dict = PREPARER) -> dict:
    return get_success_data(api_client.distribute_shift_tip_pool(pool_id, headers))


def reverse_pool(
    pool_id: str, reason: str = "policy audit", headers: dict = COMPLIANCE
) -> dict:
    return get_success_data(
        api_client.reverse_shift_tip_pool(pool_id, headers, {"reason": reason})
    )


def compute_period(pay_period_id: str, headers: dict = PREPARER) -> dict:
    return get_success_data(api_client.compute_pay_period(pay_period_id, headers))


def approve_period(pay_period_id: str, headers: dict = COMPLIANCE) -> dict:
    return get_success_data(api_client.approve_pay_period(pay_period_id, headers))


def reopen_period(
    pay_period_id: str, reason: str = "wage-hour audit reopened the week",
    headers: dict = COMPLIANCE,
) -> dict:
    return get_success_data(
        api_client.reopen_pay_period(pay_period_id, headers, {"reason": reason})
    )


def new_dispute(pay_line_id: str, employee_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_dispute(
            create_dispute_payload(pay_line_id, employee_id, **overrides),
            make_employee_headers(employee_id),
        )
    )


def adjudicate_dispute(
    dispute_id: str, resolution: str, headers: dict = COMPLIANCE, **overrides
) -> dict:
    return get_success_data(
        api_client.adjudicate_dispute(
            dispute_id, adjudicate_dispute_payload(resolution, **overrides), headers
        )
    )


def new_correction(
    pay_line_id: str,
    expected_pay_line_version: int,
    headers: dict = COMPLIANCE,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_back_wage_correction(
            create_back_wage_correction_payload(
                pay_line_id, expected_pay_line_version, **overrides
            ),
            headers,
        )
    )


def apply_correction(correction_id: str, headers: dict = PREPARER_ALT) -> dict:
    """Applied by an operator who differs from the issuing ComplianceOfficer."""
    return get_success_data(
        api_client.apply_back_wage_correction(correction_id, headers)
    )


# ---------------------------------------------------------------------------
# Read-back helpers
# ---------------------------------------------------------------------------
def read_location(location_id: str, headers: dict = ADMIN) -> dict:
    return get_success_data(api_client.get_location(location_id, headers))


def read_employee(employee_id: str, headers: dict = ADMIN) -> dict:
    return get_success_data(api_client.get_employee(employee_id, headers))


def read_pay_period(pay_period_id: str, headers: dict = PREPARER) -> dict:
    return get_success_data(api_client.get_pay_period(pay_period_id, headers))


def read_shift(shift_id: str, headers: dict = PREPARER) -> dict:
    return get_success_data(api_client.get_shift(shift_id, headers))


def read_pool(pool_id: str, headers: dict = PREPARER) -> dict:
    return get_success_data(api_client.get_shift_tip_pool(pool_id, headers))


def read_policy(policy_id: str, headers: dict = ADMIN) -> dict:
    return get_success_data(api_client.get_tip_pool_policy(policy_id, headers))


def read_pay_line(pay_line_id: str, headers: dict = PREPARER) -> dict:
    return get_success_data(api_client.get_pay_line(pay_line_id, headers))


def read_dispute(dispute_id: str, headers: dict = COMPLIANCE) -> dict:
    return get_success_data(api_client.get_dispute(dispute_id, headers))


def read_correction(correction_id: str, headers: dict = COMPLIANCE) -> dict:
    return get_success_data(api_client.get_back_wage_correction(correction_id, headers))


def read_service_charge(service_charge_id: str, headers: dict = PREPARER) -> dict:
    return get_success_data(api_client.get_service_charge(service_charge_id, headers))


def list_pay_lines_of(pay_period_id: str, headers: dict = PREPARER, **params) -> list:
    query = {"pay_period_id": pay_period_id}
    query.update(params)
    return get_success_data(api_client.list_pay_lines(headers, params=query))


def list_allocations_of(pool_id: str, headers: dict = PREPARER, **params) -> list:
    query = {"shift_tip_pool_id": pool_id}
    query.update(params)
    return get_success_data(api_client.list_pool_allocations(headers, params=query))


def list_corrections_of(headers: dict = COMPLIANCE, **params) -> list:
    return get_success_data(
        api_client.list_back_wage_corrections(headers, params=params)
    )


def sole_pay_line_of(pay_period_id: str, headers: dict = PREPARER) -> dict:
    rows = list_pay_lines_of(pay_period_id, headers)
    assert len(rows) == 1, f"expected exactly one pay line, got {len(rows)}"
    return rows[0]


# ---------------------------------------------------------------------------
# Composite world: the Texas wage unit (no pool policy)
# ---------------------------------------------------------------------------
def setup_texas_wage_world(
    employee_overrides: dict = None,
    role_overrides: dict = None,
    assignment_overrides: dict = None,
    period_overrides: dict = None,
    **location_overrides,
) -> dict:
    """Clock at 2026-08-10T12:00Z, one Texas unit at 725/213 claiming a tip
    credit, one SERVER job role, one employee with the notice on file and an
    OPEN pay period covering 2026-08-03 to 2026-08-09."""
    set_logical_clock()
    location = new_location(**location_overrides)
    role_server = new_job_role(**(role_overrides or {}))
    employee = new_employee(location["id"], **(employee_overrides or {}))
    assignment = new_role_assignment(
        employee["id"], role_server["id"], **(assignment_overrides or {})
    )
    pay_period = new_pay_period(location["id"], **(period_overrides or {}))
    return {
        "location": location,
        "role_server": role_server,
        "employee": employee,
        "assignment": assignment,
        "pay_period": pay_period,
    }


def setup_texas_two_shift_world(
    compute: bool = False,
    approve: bool = False,
    tips_first: int = 5000,
    tips_second: int = 500,
    **location_overrides,
) -> dict:
    """The Texas wage world plus two CLOSED and DECLARED 480-minute shifts on
    2026-08-04 and 2026-08-05 declaring 5000 and 500 cents of cash tips."""
    world = setup_texas_wage_world(**location_overrides)
    location, employee, period = (
        world["location"],
        world["employee"],
        world["pay_period"],
    )
    role_id = world["role_server"]["id"]

    shift_a = new_shift(
        employee["id"],
        location["id"],
        role_id,
        period["id"],
        business_date=BUSINESS_DATE_2,
        start_at="2026-08-04T16:00:00Z",
        end_at="2026-08-05T00:00:00Z",
    )
    close_shift(shift_a["id"])
    declare_shift_tips(shift_a["id"], employee["id"], tips_first, 0)

    shift_b = new_shift(
        employee["id"],
        location["id"],
        role_id,
        period["id"],
        business_date=BUSINESS_DATE_3,
        start_at="2026-08-05T16:00:00Z",
        end_at="2026-08-06T00:00:00Z",
    )
    close_shift(shift_b["id"])
    declare_shift_tips(shift_b["id"], employee["id"], tips_second, 0)

    world["shift_a"] = shift_a
    world["shift_b"] = shift_b

    if compute or approve:
        compute_period(period["id"])
    if approve:
        approve_period(period["id"])
    if compute or approve:
        world["pay_line"] = sole_pay_line_of(period["id"])
    return world


def setup_texas_final_pay_line_world(**location_overrides) -> dict:
    """The two-shift Texas week computed by op_prep_1 and approved by op_comp_1,
    leaving one FINAL PayLine at version 2 with total_gross_cents 7004."""
    return setup_texas_two_shift_world(approve=True, **location_overrides)


def setup_threshold_pair_world(
    tips_first: int = 3000, tips_second: int = 2999
) -> dict:
    """Two SERVER employees, each with one CLOSED 480-minute shift on
    2026-08-04 and no card sales, declaring the two amounts supplied."""
    set_logical_clock()
    location = new_location()
    role_server = new_job_role()
    employee_first = new_employee(
        location["id"], full_name="At Threshold", external_payroll_ref="T1",
        monthly_tip_baseline_cents=0,
    )
    employee_second = new_employee(
        location["id"], full_name="One Cent Short", external_payroll_ref="T2",
        monthly_tip_baseline_cents=0,
    )
    new_role_assignment(employee_first["id"], role_server["id"])
    new_role_assignment(employee_second["id"], role_server["id"])
    pay_period = new_pay_period(location["id"])

    shift_first = new_shift(
        employee_first["id"], location["id"], role_server["id"], pay_period["id"]
    )
    shift_second = new_shift(
        employee_second["id"], location["id"], role_server["id"], pay_period["id"]
    )
    close_shift(shift_first["id"])
    close_shift(shift_second["id"])
    declare_shift_tips(shift_first["id"], employee_first["id"], tips_first, 0)
    declare_shift_tips(shift_second["id"], employee_second["id"], tips_second, 0)
    return {
        "location": location,
        "role_server": role_server,
        "employee_first": employee_first,
        "employee_second": employee_second,
        "pay_period": pay_period,
        "shift_first": shift_first,
        "shift_second": shift_second,
    }


def setup_side_work_pair_world() -> dict:
    """Two SERVER employees, each holding one OPEN 480-minute shift on
    2026-08-04: the first at 96 side-work minutes with a 30-minute continuous
    stretch, the second at 97 and 31."""
    set_logical_clock()
    location = new_location()
    role_server = new_job_role()
    employee_first = new_employee(
        location["id"], full_name="Edge Under", external_payroll_ref="B1"
    )
    employee_second = new_employee(
        location["id"], full_name="Edge Over", external_payroll_ref="B2"
    )
    new_role_assignment(employee_first["id"], role_server["id"])
    new_role_assignment(employee_second["id"], role_server["id"])
    pay_period = new_pay_period(location["id"])
    shift_first = new_shift(
        employee_first["id"],
        location["id"],
        role_server["id"],
        pay_period["id"],
        side_work_minutes=96,
        max_continuous_side_work_minutes=30,
    )
    shift_second = new_shift(
        employee_second["id"],
        location["id"],
        role_server["id"],
        pay_period["id"],
        side_work_minutes=97,
        max_continuous_side_work_minutes=31,
    )
    return {
        "location": location,
        "role_server": role_server,
        "employee_first": employee_first,
        "employee_second": employee_second,
        "pay_period": pay_period,
        "shift_first": shift_first,
        "shift_second": shift_second,
    }


# ---------------------------------------------------------------------------
# Composite world: the Texas pool unit (SERVER + BARTENDER + BUSSER)
# ---------------------------------------------------------------------------
def setup_texas_pool_world(
    create_pool: bool = True,
    distribute: bool = False,
    compute: bool = False,
    cc_processing_fee_bps: int = 250,
    policy_overrides: dict = None,
    server_tips: tuple = (4000, 30020),
    bartender_tips: tuple = (2000, 12020),
    busser_tips: tuple = (0, 0),
    **location_overrides,
) -> dict:
    """A Texas unit whose card-fee policy is ACTUAL_ONLY and whose service
    charges are treated as TIPS, carrying an ACTIVE TIPPED_ONLY /
    TIPS_RECEIVED_PCT / HOURS_WEIGHTED_POINTS policy with cc_fee_pass_through
    true, plus three CLOSED and DECLARED shifts on 2026-08-04 of 480, 480 and
    360 minutes."""
    set_logical_clock()
    location_defaults = {"name": "Plano Unit", "service_charge_treatment": "TIPS"}
    location_defaults.update(location_overrides)
    location = new_location(**location_defaults)

    role_server = new_job_role()
    role_bartender = new_job_role(
        code="BARTENDER",
        title="Bartender",
        pool_contribution_pct_bps=1000,
        pool_share_points=8,
    )
    role_busser = new_job_role(
        code="BUSSER",
        title="Busser",
        pool_contribution_pct_bps=0,
        pool_share_points=5,
    )

    employee_server = new_employee(
        location["id"], full_name="Sam Server", external_payroll_ref="P1"
    )
    employee_bartender = new_employee(
        location["id"], full_name="Bea Bartender", external_payroll_ref="P2"
    )
    employee_busser = new_employee(
        location["id"], full_name="Cal Busser", external_payroll_ref="P3"
    )
    new_role_assignment(employee_server["id"], role_server["id"])
    new_role_assignment(employee_bartender["id"], role_bartender["id"])
    new_role_assignment(employee_busser["id"], role_busser["id"])

    policy = new_active_policy(
        location["id"], location["version"], **(policy_overrides or {})
    )
    pay_period = new_pay_period(location["id"])

    shift_server = new_shift(
        employee_server["id"],
        location["id"],
        role_server["id"],
        pay_period["id"],
        gross_sales_cents=120000,
        charged_sales_cents=90000,
        cc_processing_fee_bps=cc_processing_fee_bps,
    )
    shift_bartender = new_shift(
        employee_bartender["id"],
        location["id"],
        role_bartender["id"],
        pay_period["id"],
        gross_sales_cents=60000,
        charged_sales_cents=40000,
        cc_processing_fee_bps=cc_processing_fee_bps,
    )
    shift_busser = new_shift(
        employee_busser["id"],
        location["id"],
        role_busser["id"],
        pay_period["id"],
        start_at="2026-08-04T16:00:00Z",
        end_at="2026-08-04T22:00:00Z",
        cc_processing_fee_bps=cc_processing_fee_bps,
    )
    for shift in (shift_server, shift_bartender, shift_busser):
        close_shift(shift["id"])
    declare_shift_tips(shift_server["id"], employee_server["id"], *server_tips)
    declare_shift_tips(shift_bartender["id"], employee_bartender["id"], *bartender_tips)
    declare_shift_tips(shift_busser["id"], employee_busser["id"], *busser_tips)

    world = {
        "location": location,
        "role_server": role_server,
        "role_bartender": role_bartender,
        "role_busser": role_busser,
        "employee_server": employee_server,
        "employee_bartender": employee_bartender,
        "employee_busser": employee_busser,
        "policy": policy,
        "pay_period": pay_period,
        "shift_server": shift_server,
        "shift_bartender": shift_bartender,
        "shift_busser": shift_busser,
    }
    if create_pool or distribute or compute:
        world["pool"] = new_pool(location["id"], BUSINESS_DATE_2)
    if distribute or compute:
        distribute_pool(world["pool"]["id"])
    if compute:
        compute_period(pay_period["id"])
    return world


# ---------------------------------------------------------------------------
# Composite world: two units differing only in their card-fee policy
# ---------------------------------------------------------------------------
def setup_two_unit_card_fee_world(cc_processing_fee_bps: int = 400) -> dict:
    """Two Texas units with identical wage figures, shifts and declarations:
    one at cc_fee_policy ACTUAL_ONLY, one at CAPPED_BPS with cc_fee_cap_bps 300.
    Both hold an ACTIVE HOURS_WEIGHTED_POINTS policy passing the card fee
    through, and both end with a PENDING pool for 2026-08-04."""
    set_logical_clock()
    location_actual = new_location(
        name="Austin Actual",
        cc_fee_policy="ACTUAL_ONLY",
        service_charge_treatment="TIPS",
    )
    location_capped = new_location(
        name="Houston Capped",
        cc_fee_policy="CAPPED_BPS",
        cc_fee_cap_bps=300,
        service_charge_treatment="TIPS",
    )
    role_server = new_job_role()
    role_bartender = new_job_role(
        code="BARTENDER",
        title="Bartender",
        pool_contribution_pct_bps=1000,
        pool_share_points=8,
    )

    units = {}
    for label, location, refs, names in (
        ("actual", location_actual, ("A1", "A2"), ("A Server", "A Bartender")),
        ("capped", location_capped, ("B1", "B2"), ("B Server", "B Bartender")),
    ):
        employee_server = new_employee(
            location["id"], full_name=names[0], external_payroll_ref=refs[0]
        )
        employee_bartender = new_employee(
            location["id"], full_name=names[1], external_payroll_ref=refs[1]
        )
        new_role_assignment(employee_server["id"], role_server["id"])
        new_role_assignment(employee_bartender["id"], role_bartender["id"])
        policy = new_active_policy(location["id"], location["version"])
        pay_period = new_pay_period(location["id"])
        shift_server = new_shift(
            employee_server["id"],
            location["id"],
            role_server["id"],
            pay_period["id"],
            gross_sales_cents=120000,
            charged_sales_cents=90000,
            cc_processing_fee_bps=cc_processing_fee_bps,
        )
        shift_bartender = new_shift(
            employee_bartender["id"],
            location["id"],
            role_bartender["id"],
            pay_period["id"],
            gross_sales_cents=60000,
            charged_sales_cents=40000,
            cc_processing_fee_bps=cc_processing_fee_bps,
        )
        close_shift(shift_server["id"])
        close_shift(shift_bartender["id"])
        declare_shift_tips(shift_server["id"], employee_server["id"], 4000, 30020)
        declare_shift_tips(shift_bartender["id"], employee_bartender["id"], 2000, 12020)
        pool = new_pool(location["id"], BUSINESS_DATE_2)
        units[label] = {
            "location": location,
            "policy": policy,
            "pay_period": pay_period,
            "employee_server": employee_server,
            "employee_bartender": employee_bartender,
            "shift_server": shift_server,
            "shift_bartender": shift_bartender,
            "pool": pool,
        }
    units["role_server"] = role_server
    units["role_bartender"] = role_bartender
    return units


# ---------------------------------------------------------------------------
# Composite world: the New York overtime unit with a WAGES service charge
# ---------------------------------------------------------------------------
def setup_new_york_overtime_world(
    service_charge_amount_cents: int = 6000,
    tips_per_shift: int = 8000,
) -> dict:
    """A New York unit at 1500/1000 forbidding card-fee deduction and treating
    service charges as WAGES, with one SERVER working five CLOSED and DECLARED
    540-minute shifts from 2026-08-03 to 2026-08-07 — 2700 minutes in all — and
    one mandatory service charge recorded on 2026-08-03."""
    set_logical_clock()
    location = new_location(
        name="Manhattan Unit",
        state_code="NY",
        state_min_wage_cents=1500,
        cash_wage_cents=1000,
        cc_fee_policy="PROHIBITED",
        service_charge_treatment="WAGES",
    )
    role_server = new_job_role()
    employee = new_employee(
        location["id"], full_name="Nora Nguyen", external_payroll_ref="NY1"
    )
    new_role_assignment(employee["id"], role_server["id"])
    pay_period = new_pay_period(location["id"])
    service_charge = new_service_charge(
        location["id"],
        business_date=BUSINESS_DATE_1,
        amount_cents=service_charge_amount_cents,
        description="20 percent large-party charge",
    )

    shifts = []
    for business_date, start_at, end_at in (
        (BUSINESS_DATE_1, "2026-08-03T16:00:00Z", "2026-08-04T01:00:00Z"),
        (BUSINESS_DATE_2, "2026-08-04T16:00:00Z", "2026-08-05T01:00:00Z"),
        (BUSINESS_DATE_3, "2026-08-05T16:00:00Z", "2026-08-06T01:00:00Z"),
        (BUSINESS_DATE_4, "2026-08-06T16:00:00Z", "2026-08-07T01:00:00Z"),
        (BUSINESS_DATE_5, "2026-08-07T16:00:00Z", "2026-08-08T01:00:00Z"),
    ):
        shifts.append(
            new_shift(
                employee["id"],
                location["id"],
                role_server["id"],
                pay_period["id"],
                business_date=business_date,
                start_at=start_at,
                end_at=end_at,
                gross_sales_cents=100000,
                charged_sales_cents=0,
            )
        )
    for shift in shifts:
        close_shift(shift["id"])
    for shift in shifts:
        declare_shift_tips(shift["id"], employee["id"], tips_per_shift, 0)

    return {
        "location": location,
        "role_server": role_server,
        "employee": employee,
        "pay_period": pay_period,
        "service_charge": service_charge,
        "shifts": shifts,
    }
