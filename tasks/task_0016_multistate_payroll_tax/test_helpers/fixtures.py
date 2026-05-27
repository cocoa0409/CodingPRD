"""Composite setup helpers for multi-step preconditions.

Uses get_success_data() (lenient validator) so setup failures produce clear
"Setup failed" errors rather than confusing assertion failures.

The PRD-declared `_clock/set_current_utc` and `_employees/{id}/set_ytd`
test-driving endpoints are used to reach boundary states deterministically.

Identity threading: PRD §2.1 declares all roles `opaque`. Shared TEST_USERS
constants are safe across every step. For segregation-of-duties tests that
need distinct preparer / approver operator ids, callers can pass
`preparer_headers=` or `approver_headers=` overrides; defaults bind to
U_PREP / U_APPR respectively (matching the design-index conventions).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_employee_payload,
    update_employee_status_payload,
    create_w4_form_payload,
    create_paycheck_run_payload,
    create_paycheck_payload,
    regular_paycheck_payload,
    overtime_paycheck_payload,
    double_paycheck_payload,
    retro_paycheck_payload,
    create_garnishment_order_payload,
    create_tax_rate_table_payload,
    pay_paycheck_run_payload,
    set_clock_payload,
    set_ytd_payload,
)
from .test_users import TEST_USERS
from .constants import (
    FED_BRACKETS_2025_SINGLE,
    FED_SUPPLEMENTAL_BP_2025,
    CA_BRACKETS_2025_SINGLE,
    CA_SUPPLEMENTAL_BP_2025,
    NY_BRACKETS_2025_SINGLE,
    NY_SUPPLEMENTAL_BP_2025,
    NYC_BRACKETS_2025_SINGLE,
    NYC_SUPPLEMENTAL_BP_2025,
)


_HR = TEST_USERS["hr_clerk_headers"]
_PREP = TEST_USERS["payroll_preparer_headers"]
_APPR = TEST_USERS["payroll_approver_headers"]
_COMP = TEST_USERS["compliance_officer_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Tier 0: Clock + tax-rate seeding ─────────────────────────────────────

def set_clock(iso_instant: str) -> None:
    """Advance the server clock used for NOW_UTC (PRD §2.10)."""
    get_success_data(api_client.set_clock(set_clock_payload(iso_instant), _ADMIN))


def seed_federal_tax_table_2025_single() -> dict:
    """Seed the 2025 SINGLE federal bracket schedule (PRD §3.2)."""
    res = api_client.create_tax_rate_table(
        create_tax_rate_table_payload(
            jurisdiction="FEDERAL",
            tax_year=2025,
            filing_status="SINGLE",
            brackets_json=FED_BRACKETS_2025_SINGLE,
            supplemental_flat_basis_points=FED_SUPPLEMENTAL_BP_2025,
        ),
        _ADMIN,
    )
    return get_success_data(res)


def seed_california_tax_table_2025() -> dict:
    """Seed STATE:CA 2025 tax-rate table (PRD §3.2)."""
    res = api_client.create_tax_rate_table(
        create_tax_rate_table_payload(
            jurisdiction="STATE:CA",
            tax_year=2025,
            filing_status="SINGLE",
            brackets_json=CA_BRACKETS_2025_SINGLE,
            supplemental_flat_basis_points=CA_SUPPLEMENTAL_BP_2025,
        ),
        _ADMIN,
    )
    return get_success_data(res)


def seed_ny_tax_tables_2025() -> tuple[dict, dict]:
    """Seed STATE:NY and LOCAL:NYC 2025 tax-rate tables (PRD §3.2)."""
    state_res = api_client.create_tax_rate_table(
        create_tax_rate_table_payload(
            jurisdiction="STATE:NY",
            tax_year=2025,
            filing_status="SINGLE",
            brackets_json=NY_BRACKETS_2025_SINGLE,
            supplemental_flat_basis_points=NY_SUPPLEMENTAL_BP_2025,
        ),
        _ADMIN,
    )
    local_res = api_client.create_tax_rate_table(
        create_tax_rate_table_payload(
            jurisdiction="LOCAL:NYC",
            tax_year=2025,
            filing_status="SINGLE",
            brackets_json=NYC_BRACKETS_2025_SINGLE,
            supplemental_flat_basis_points=NYC_SUPPLEMENTAL_BP_2025,
        ),
        _ADMIN,
    )
    return get_success_data(state_res), get_success_data(local_res)


def seed_federal_and_california_2025() -> None:
    """Convenience: federal + CA seeded together. The most common setup."""
    seed_federal_tax_table_2025_single()
    seed_california_tax_table_2025()


# ─── Tier 1: Single-entity creation ───────────────────────────────────────

def create_employee(
    work_state_code: str = "CA",
    residence_state_code: str = "CA",
    locality_code: str | None = None,
    full_name: str = "Test Employee",
) -> dict:
    """Create an ACTIVE employee with the named work/residence/locality."""
    payload = create_employee_payload(
        full_name=full_name,
        work_state_code=work_state_code,
        residence_state_code=residence_state_code,
        locality_code=locality_code,
    )
    return get_success_data(api_client.create_employee(payload, _HR))


def terminate_employee(employee_id: str) -> dict:
    """Move an employee to TERMINATED."""
    res = api_client.update_employee_status(
        employee_id, update_employee_status_payload("TERMINATED"), _HR
    )
    return get_success_data(res)


def create_w4_draft(employee_id: str, tax_year: int = 2025,
                    filing_status: str = "SINGLE", **overrides) -> dict:
    """Create a DRAFT W-4."""
    payload = create_w4_form_payload(
        employee_id=employee_id,
        tax_year=tax_year,
        filing_status=filing_status,
        **overrides,
    )
    return get_success_data(api_client.create_w4_form(payload, _HR))


def create_and_file_w4(employee_id: str, tax_year: int = 2025,
                       filing_status: str = "SINGLE", **overrides) -> dict:
    """Create + file a W-4. Returns FILED W4Form (PRD §3.1)."""
    w4 = create_w4_draft(employee_id, tax_year, filing_status, **overrides)
    return get_success_data(api_client.file_w4_form(w4["id"], _HR))


# ─── Tier 2: Employee + filed W4 (most common preamble) ──────────────────

def setup_employee_with_filed_w4(
    work_state_code: str = "CA",
    residence_state_code: str = "CA",
    locality_code: str | None = None,
    filing_status: str = "SINGLE",
    tax_year: int = 2025,
    full_name: str = "Test Employee",
    **w4_overrides,
) -> tuple[dict, dict]:
    """Federal + CA tax tables seeded; ACTIVE employee; FILED W-4 for tax_year.
    Returns (employee, filed_w4)."""
    emp = create_employee(
        work_state_code=work_state_code,
        residence_state_code=residence_state_code,
        locality_code=locality_code,
        full_name=full_name,
    )
    w4 = create_and_file_w4(
        emp["id"], tax_year=tax_year,
        filing_status=filing_status, **w4_overrides,
    )
    return emp, w4


# ─── Tier 3: PaycheckRun lifecycle shortcuts ──────────────────────────────

def create_draft_paycheck_run(
    pay_period_start: str = "2025-11-01T00:00:00.000Z",
    pay_period_end: str = "2025-11-15T23:59:59.999Z",
    pay_date: str = "2025-11-15T00:00:00.000Z",
    preparer_headers: dict | None = None,
) -> dict:
    """Create a DRAFT PaycheckRun.
    `prepared_by_user_id` is taken from the preparer header's X-User-ID."""
    res = api_client.create_paycheck_run(
        create_paycheck_run_payload(
            pay_period_start=pay_period_start,
            pay_period_end=pay_period_end,
            pay_date=pay_date,
        ),
        preparer_headers or _PREP,
    )
    return get_success_data(res)


def attach_regular_paycheck(
    run_id: str,
    employee_id: str,
    regular_hours_e2: int = 4000,
    hourly_rate_cents: int = 5000,
    preparer_headers: dict | None = None,
) -> dict:
    """Add a REGULAR Paycheck to a DRAFT run; withholding pipeline fires (PRD §3.4)."""
    payload = regular_paycheck_payload(
        paycheck_run_id=run_id,
        employee_id=employee_id,
        regular_hours_e2=regular_hours_e2,
        hourly_rate_cents=hourly_rate_cents,
    )
    return get_success_data(api_client.create_paycheck(payload, preparer_headers or _PREP))


def attach_overtime_paycheck(
    run_id: str, employee_id: str,
    overtime_hours_e2: int = 4000,
    hourly_rate_cents: int = 2500,
    preparer_headers: dict | None = None,
) -> dict:
    payload = overtime_paycheck_payload(
        paycheck_run_id=run_id,
        employee_id=employee_id,
        overtime_hours_e2=overtime_hours_e2,
        hourly_rate_cents=hourly_rate_cents,
    )
    return get_success_data(api_client.create_paycheck(payload, preparer_headers or _PREP))


def attach_double_paycheck(
    run_id: str, employee_id: str,
    double_hours_e2: int = 2000,
    hourly_rate_cents: int = 2500,
    preparer_headers: dict | None = None,
) -> dict:
    payload = double_paycheck_payload(
        paycheck_run_id=run_id,
        employee_id=employee_id,
        double_hours_e2=double_hours_e2,
        hourly_rate_cents=hourly_rate_cents,
    )
    return get_success_data(api_client.create_paycheck(payload, preparer_headers or _PREP))


def attach_retro_paycheck(
    run_id: str, employee_id: str,
    retro_amount_cents: int = 150000,
    preparer_headers: dict | None = None,
) -> dict:
    payload = retro_paycheck_payload(
        paycheck_run_id=run_id,
        employee_id=employee_id,
        retro_amount_cents=retro_amount_cents,
    )
    return get_success_data(api_client.create_paycheck(payload, preparer_headers or _PREP))


def approve_run(run_id: str, approver_headers: dict | None = None) -> dict:
    return get_success_data(api_client.approve_paycheck_run(run_id, approver_headers or _APPR))


def pay_run(run_id: str, is_year_end_run: bool | None = None,
            approver_headers: dict | None = None) -> dict:
    res = api_client.pay_paycheck_run(
        run_id, pay_paycheck_run_payload(is_year_end_run), approver_headers or _APPR
    )
    return get_success_data(res)


def void_run(run_id: str, approver_headers: dict | None = None) -> dict:
    return get_success_data(api_client.void_paycheck_run(run_id, approver_headers or _APPR))


# ─── Tier 4: Composite "PaycheckRun with N paychecks" ────────────────────

def setup_paid_regular_run(
    *,
    work_state_code: str = "CA",
    residence_state_code: str = "CA",
    locality_code: str | None = None,
    pay_period_start: str = "2025-11-01T00:00:00.000Z",
    pay_period_end: str = "2025-11-15T23:59:59.999Z",
    pay_date: str = "2025-11-15T00:00:00.000Z",
    regular_hours_e2: int = 4000,
    hourly_rate_cents: int = 5000,
    is_year_end_run: bool | None = None,
) -> tuple[dict, dict, dict, dict]:
    """Full lifecycle: seeded tables -> employee -> W4 FILED -> DRAFT run ->
    one REGULAR paycheck -> APPROVED -> PAID. Returns (employee, w4, run, paycheck).
    Cascades fire on /pay per PRD §3.6 (Paycheck PENDING -> PAID; YTD increments;
    Remittance rows created/incremented)."""
    emp, w4 = setup_employee_with_filed_w4(
        work_state_code=work_state_code,
        residence_state_code=residence_state_code,
        locality_code=locality_code,
    )
    run = create_draft_paycheck_run(
        pay_period_start=pay_period_start,
        pay_period_end=pay_period_end,
        pay_date=pay_date,
    )
    pay = attach_regular_paycheck(
        run["id"], emp["id"],
        regular_hours_e2=regular_hours_e2,
        hourly_rate_cents=hourly_rate_cents,
    )
    approve_run(run["id"])
    paid_run = pay_run(run["id"], is_year_end_run=is_year_end_run)
    return emp, w4, paid_run, pay


def setup_approved_regular_run(
    *,
    work_state_code: str = "CA",
    residence_state_code: str = "CA",
    locality_code: str | None = None,
    pay_period_start: str = "2025-11-01T00:00:00.000Z",
    pay_period_end: str = "2025-11-15T23:59:59.999Z",
    pay_date: str = "2025-11-15T00:00:00.000Z",
    regular_hours_e2: int = 4000,
    hourly_rate_cents: int = 5000,
) -> tuple[dict, dict, dict, dict]:
    """Setup through APPROVED (stops short of /pay). Returns (employee, w4, run, paycheck)."""
    emp, w4 = setup_employee_with_filed_w4(
        work_state_code=work_state_code,
        residence_state_code=residence_state_code,
        locality_code=locality_code,
    )
    run = create_draft_paycheck_run(
        pay_period_start=pay_period_start,
        pay_period_end=pay_period_end,
        pay_date=pay_date,
    )
    pay = attach_regular_paycheck(
        run["id"], emp["id"],
        regular_hours_e2=regular_hours_e2,
        hourly_rate_cents=hourly_rate_cents,
    )
    approved = get_success_data(api_client.approve_paycheck_run(run["id"], _APPR))
    return emp, w4, approved, pay


def setup_draft_run_with_paycheck(
    *,
    work_state_code: str = "CA",
    locality_code: str | None = None,
    pay_period_start: str = "2025-11-01T00:00:00.000Z",
    pay_period_end: str = "2025-11-15T23:59:59.999Z",
    pay_date: str = "2025-11-15T00:00:00.000Z",
    regular_hours_e2: int = 4000,
    hourly_rate_cents: int = 5000,
) -> tuple[dict, dict, dict, dict]:
    """Setup through DRAFT with one REGULAR paycheck attached (stops short of /approve).
    Returns (employee, w4, run, paycheck)."""
    emp, w4 = setup_employee_with_filed_w4(
        work_state_code=work_state_code, locality_code=locality_code,
    )
    run = create_draft_paycheck_run(
        pay_period_start=pay_period_start,
        pay_period_end=pay_period_end,
        pay_date=pay_date,
    )
    pay = attach_regular_paycheck(
        run["id"], emp["id"],
        regular_hours_e2=regular_hours_e2,
        hourly_rate_cents=hourly_rate_cents,
    )
    return emp, w4, run, pay


# ─── Tier 5: Garnishment helpers ──────────────────────────────────────────

def create_garnishment_order(
    employee_id: str,
    order_type: str = "CHILD_SUPPORT",
    weekly_cap_cents: int = 30000,
    original_balance_cents: int = 100000,
    served_on: str = "2025-06-01T00:00:00.000Z",
) -> dict:
    """Create a garnishment order (ACTIVE)."""
    payload = create_garnishment_order_payload(
        employee_id=employee_id,
        order_type=order_type,
        weekly_cap_cents=weekly_cap_cents,
        original_balance_cents=original_balance_cents,
        served_on=served_on,
    )
    return get_success_data(api_client.create_garnishment_order(payload, _COMP))


def suspend_garnishment(order_id: str) -> dict:
    return get_success_data(api_client.suspend_garnishment_order(order_id, _COMP))


def reactivate_garnishment(order_id: str) -> dict:
    return get_success_data(api_client.reactivate_garnishment_order(order_id, _COMP))


def release_garnishment(order_id: str) -> dict:
    return get_success_data(api_client.release_garnishment_order(order_id, _COMP))


# ─── Tier 6: YTD seeding for boundary tests ──────────────────────────────

def seed_employee_ytd(employee_id: str, **ytd_fields) -> dict:
    """Directly seed YTD wage/tax fields on an employee (PRD §2.10)."""
    res = api_client.set_employee_ytd(employee_id, set_ytd_payload(**ytd_fields), _ADMIN)
    return get_success_data(res)


# ─── Tier 7: Remittance lookup ────────────────────────────────────────────

def find_remittance(period_month: str, jurisdiction: str, tax_type: str) -> dict:
    """Locate a Remittance row by (period_month, jurisdiction, tax_type).
    Pay cascade creates rows on first need (PRD §3.7)."""
    res = api_client.list_remittances(
        _COMP,
        params={
            "period_month": period_month,
            "jurisdiction": jurisdiction,
            "tax_type": tax_type,
        },
    )
    data = get_success_data(res)
    # The framework's get_success_data returns the data payload directly.
    # For list endpoints that's the list itself.
    if isinstance(data, list):
        assert data, f"No Remittance found for ({period_month}, {jurisdiction}, {tax_type})"
        return data[0]
    # Some implementations may wrap data; defensive fallback:
    raise AssertionError(
        f"Expected list of remittances, got {type(data).__name__}: {data!r}"
    )


def get_remittance(remittance_id: str) -> dict:
    return get_success_data(api_client.get_remittance(remittance_id, _COMP))


def close_remittance(remittance_id: str) -> dict:
    return get_success_data(api_client.close_remittance_period(remittance_id, _COMP))


# ─── Tier 8: Helpers consumed across many tests ──────────────────────────

def get_employee(employee_id: str) -> dict:
    return get_success_data(api_client.get_employee(employee_id, _HR))


def get_paycheck(paycheck_id: str) -> dict:
    return get_success_data(api_client.get_paycheck(paycheck_id, _PREP))


def get_paycheck_run(run_id: str) -> dict:
    return get_success_data(api_client.get_paycheck_run(run_id, _PREP))


def get_w4_form(w4_id: str) -> dict:
    return get_success_data(api_client.get_w4_form(w4_id, _HR))


def get_garnishment_order(order_id: str) -> dict:
    return get_success_data(api_client.get_garnishment_order(order_id, _COMP))
