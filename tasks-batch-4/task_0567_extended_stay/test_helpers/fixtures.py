"""Composite setup helpers.

Each test runs against a freshly restarted, empty-database server, so every helper
builds its preconditions from scratch using only PRD-declared endpoints. Helpers
use get_success_data() (lenient) so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing assertion error.

Ownership threading: after a fixture creates a CorporateAccount / Employee, any
ownership-gated call uses make_corporate_admin_headers(account_id) /
make_employee_headers(employee_id) with the real id — never the shared fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_corporate_admin_headers,
    make_employee_headers,
)
from .factories import (
    create_corporate_account_payload,
    create_rate_plan_payload,
    create_unit_payload,
    create_master_lease_payload,
    create_employee_payload,
    create_stay_payload,
    create_damage_charge_payload,
    DEFAULT_MOVE_IN,
    DEFAULT_PLANNED_MOVE_OUT,
)

PM = TEST_USERS["property_manager_headers"]


# --- Primitive creators -----------------------------------------------------

def create_rate_plan(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_rate_plan(create_rate_plan_payload(**overrides), PM))


def create_unit(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_unit(create_unit_payload(**overrides), PM))


def create_corporate_account(api=api_client, **overrides) -> dict:
    return get_success_data(
        api.create_corporate_account(create_corporate_account_payload(**overrides), PM)
    )


def create_active_master_lease(api=api_client, account_id=None, **overrides) -> dict:
    """Create a DRAFT master lease and activate it -> ACTIVE. Returns the lease
    as read back after activation."""
    if account_id is None:
        account_id = create_corporate_account(api)["id"]
    lease = get_success_data(
        api.create_master_lease(create_master_lease_payload(account_id, **overrides), PM)
    )
    api.activate_master_lease(lease["id"], PM)
    return get_success_data(api.get_master_lease(lease["id"], PM))


def create_employee(api=api_client, account_id=None, **overrides) -> dict:
    """Add an employee to an account's roster (ownership-gated on the admin)."""
    if account_id is None:
        account_id = create_corporate_account(api)["id"]
    admin = make_corporate_admin_headers(account_id)
    return get_success_data(
        api.create_employee(create_employee_payload(account_id, **overrides), admin)
    )


# --- Retail-stay progressions -----------------------------------------------

def book_retail_stay(api=api_client, *, rate_plan_id=None, unit_id=None,
                     move_in=DEFAULT_MOVE_IN, planned_move_out=DEFAULT_PLANNED_MOVE_OUT,
                     deposit_held_cents=0, rate_overrides=None, unit_overrides=None) -> dict:
    """RatePlan + AVAILABLE Unit + one RESERVED retail stay. Returns
    {rate_plan, unit, stay}."""
    rate_plan = None
    unit = None
    if rate_plan_id is None:
        rate_plan = create_rate_plan(api, **(rate_overrides or {}))
        rate_plan_id = rate_plan["id"]
    if unit_id is None:
        unit = create_unit(api, **(unit_overrides or {}))
        unit_id = unit["id"]
    stay = get_success_data(api.create_stay(
        create_stay_payload(
            unit_id, rate_plan_id,
            move_in=move_in, planned_move_out=planned_move_out,
            deposit_held_cents=deposit_held_cents,
        ),
        PM,
    ))
    return {"rate_plan": rate_plan, "unit": unit, "stay": stay}


def checkin_retail_stay(api=api_client, *, move_in=DEFAULT_MOVE_IN,
                        planned_move_out=DEFAULT_PLANNED_MOVE_OUT,
                        deposit_held_cents=0, rate_overrides=None) -> dict:
    """RatePlan + Unit + retail stay CHECKED IN (ACTIVE, unit OCCUPIED, provisional
    invoice created). Returns {rate_plan, unit, stay}."""
    ctx = book_retail_stay(
        api, move_in=move_in, planned_move_out=planned_move_out,
        deposit_held_cents=deposit_held_cents, rate_overrides=rate_overrides,
    )
    api.check_in_stay(ctx["stay"]["id"], PM)
    ctx["stay"] = get_success_data(api.get_stay(ctx["stay"]["id"], PM))
    return ctx


def depart_retail_stay(api=api_client, *, actual_move_out, move_in=DEFAULT_MOVE_IN,
                       planned_move_out=DEFAULT_PLANNED_MOVE_OUT,
                       deposit_held_cents=0, rate_overrides=None) -> dict:
    """Full retail lifecycle through departure. Returns
    {rate_plan, unit, stay, invoice} where the invoice is the FINAL, ISSUED one."""
    ctx = checkin_retail_stay(
        api, move_in=move_in, planned_move_out=planned_move_out,
        deposit_held_cents=deposit_held_cents, rate_overrides=rate_overrides,
    )
    api.depart_stay(ctx["stay"]["id"], {"actual_move_out": actual_move_out}, PM)
    ctx["stay"] = get_success_data(api.get_stay(ctx["stay"]["id"], PM))
    ctx["invoice"] = get_stay_invoice(api, ctx["stay"]["id"], PM)
    return ctx


def get_stay_invoice(api=api_client, stay_id=None, headers=PM) -> dict:
    """Return the (single) invoice for a stay via the filtered list endpoint."""
    resp = api.list_invoices(headers, params={"stay_id": stay_id})
    data = get_success_data(resp)
    assert data, f"Setup failed: no invoice found for stay {stay_id}"
    return data[0]


# --- Corporate-stay progressions --------------------------------------------

def setup_corporate_stay(api=api_client, *, committed_units=5,
                         move_in=DEFAULT_MOVE_IN, planned_move_out=DEFAULT_PLANNED_MOVE_OUT,
                         deposit_held_cents=0, unit_overrides=None) -> dict:
    """CorporateAccount + ACTIVE MasterLease + Employee + Unit + one RESERVED
    corporate stay booked by the owning CorporateAdmin. Returns
    {account, lease, employee, rate_plan, unit, stay, admin_headers, employee_headers}."""
    account = create_corporate_account(api)
    lease = create_active_master_lease(api, account["id"], committed_units=committed_units)
    employee = create_employee(api, account["id"])
    rate_plan = create_rate_plan(api)
    unit = create_unit(api, **(unit_overrides or {}))
    admin = make_corporate_admin_headers(account["id"])
    stay = get_success_data(api.create_stay(
        create_stay_payload(
            unit["id"], rate_plan["id"],
            move_in=move_in, planned_move_out=planned_move_out,
            deposit_held_cents=deposit_held_cents,
            master_lease_id=lease["id"], employee_id=employee["id"],
        ),
        admin,
    ))
    return {
        "account": account,
        "lease": lease,
        "employee": employee,
        "rate_plan": rate_plan,
        "unit": unit,
        "stay": stay,
        "admin_headers": admin,
        "employee_headers": make_employee_headers(employee["id"]),
    }


# --- Damage / deposit progressions ------------------------------------------

def assess_damage(api=api_client, *, stay_id, amount_cents=25_000,
                  description="Wall damage", headers=PM) -> dict:
    """Create one ASSESSED DamageCharge against a stay."""
    return get_success_data(api.create_damage_charge(
        create_damage_charge_payload(stay_id, amount_cents=amount_cents, description=description),
        headers,
    ))


def setup_departed_stay_with_assessed_damage(api=api_client, *, deposit_held_cents=100_000,
                                             amount_cents=25_000,
                                             actual_move_out="2026-06-30T00:00:00Z") -> dict:
    """Retail stay departed at plan (COMPLETED, FINAL invoice) + one ASSESSED damage.
    Returns {rate_plan, unit, stay, invoice, damage}."""
    ctx = depart_retail_stay(
        api, actual_move_out=actual_move_out, deposit_held_cents=deposit_held_cents,
    )
    ctx["damage"] = assess_damage(api, stay_id=ctx["stay"]["id"], amount_cents=amount_cents)
    return ctx
