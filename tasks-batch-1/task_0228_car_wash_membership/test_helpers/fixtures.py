"""Composite setup helpers for multi-step test prerequisites.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness wipes the DB before every test). Setup calls use
get_success_data() so a setup failure surfaces clearly as "Setup step failed".

Identity threading: after create_account, every ownership-gated AccountHolder
call uses make_account_holder_headers(account["id"]) — never the shared fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_plan_payload, create_single_wash_plan_payload, create_location_payload,
    create_addon_payload, create_account_payload, create_fleet_account_payload,
    create_vehicle_payload, create_membership_payload, attach_addon_payload,
    topup_payload, freeze_scheduled_payload, adjustment_payload, wash_event_payload,
)
from .test_users import TEST_USERS, make_account_holder_headers

PA = TEST_USERS["platform_admin_headers"]
LO = TEST_USERS["location_operator_headers"]
BA = TEST_USERS["billing_admin_headers"]


# ─── Clock control (PRD Section 3.11) ──────────────────────────────────────

def set_clock(iso8601: str):
    """Advance / set the logical clock; fires due freeze transitions."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, PA))


# ─── Catalog builders (PRD Section 3.1) ────────────────────────────────────

def create_plan(**overrides):
    """Create an UNLIMITED plan (default). Returns the plan object."""
    return get_success_data(api_client.create_plan(create_plan_payload(**overrides), PA))


def create_single_wash_plan(**overrides):
    """Create a SINGLE_WASH plan. Returns the plan object."""
    return get_success_data(
        api_client.create_plan(create_single_wash_plan_payload(**overrides), PA)
    )


def create_location(**overrides):
    return get_success_data(api_client.create_location(create_location_payload(**overrides), PA))


def create_addon(**overrides):
    return get_success_data(api_client.create_addon(create_addon_payload(**overrides), PA))


# ─── Account / vehicle builders (PRD Section 3.2) ──────────────────────────

def create_account(**overrides):
    """Create an INDIVIDUAL account. Returns the account object."""
    return get_success_data(api_client.create_account(create_account_payload(**overrides), PA))


def create_fleet_account(**overrides):
    return get_success_data(
        api_client.create_account(create_fleet_account_payload(**overrides), PA)
    )


def create_vehicle(account_id, license_plate, state_code="CA", headers=None):
    """Register a vehicle under the account. Uses the owning-account holder headers."""
    hdr = headers or make_account_holder_headers(account_id)
    return get_success_data(
        api_client.create_vehicle(
            account_id, create_vehicle_payload(license_plate, state_code), hdr
        )
    )


def fund_wallet(account_id, amount_cents):
    """Post a positive manual adjustment to fund the account wallet."""
    return get_success_data(
        api_client.create_adjustment(account_id, adjustment_payload(amount_cents), BA)
    )


# ─── Membership lifecycle (PRD Sections 3.3, 3.4) ──────────────────────────

def _first_cycle_invoice_id(membership_id, headers):
    invoices, _ = _list_invoices(membership_id, "CYCLE", headers)
    assert invoices, f"Setup step failed: no CYCLE invoice for membership {membership_id}"
    return invoices[0]["id"]


def _list_invoices(membership_id, kind, headers):
    res = api_client.list_invoices(headers, params={"membership_id": membership_id, "kind": kind})
    data = get_success_data(res)
    body = res.json()
    return data, body.get("meta", {})


def enroll_membership(account_id, vehicle_id, plan_id, headers=None):
    """Enroll a vehicle in a plan; returns the PENDING membership (first CYCLE invoice issued)."""
    hdr = headers or make_account_holder_headers(account_id)
    return get_success_data(
        api_client.create_membership(
            create_membership_payload(account_id, vehicle_id, plan_id), hdr
        )
    )


def pay_first_cycle_invoice(membership_id, account_id, headers=None):
    """Simulate SUCCEEDED on the membership's first CYCLE invoice -> membership ACTIVE."""
    hdr = headers or make_account_holder_headers(account_id)
    inv_id = _first_cycle_invoice_id(membership_id, hdr)
    get_success_data(api_client.simulate_payment({"invoice_id": inv_id, "outcome": "SUCCEEDED"}, PA))
    return inv_id


def create_active_membership(plan_id, account_id=None, vehicle_id=None,
                             license_plate="ACT001", state_code="CA"):
    """Full path to an ACTIVE membership on the given plan.

    Creates (or reuses) an INDIVIDUAL account + vehicle, enrolls, pays the first
    CYCLE invoice. Returns (account, vehicle, membership) — all freshly read.
    """
    if account_id is None:
        account = create_account()
        account_id = account["id"]
    else:
        account = get_success_data(
            api_client.get_account(account_id, make_account_holder_headers(account_id))
        )
    hdr = make_account_holder_headers(account_id)
    if vehicle_id is None:
        vehicle = create_vehicle(account_id, license_plate, state_code, hdr)
        vehicle_id = vehicle["id"]
    else:
        vehicle = get_success_data(api_client.get_vehicle(vehicle_id, hdr))

    membership = enroll_membership(account_id, vehicle_id, plan_id, hdr)
    pay_first_cycle_invoice(membership["id"], account_id, hdr)
    membership = get_success_data(api_client.get_membership(membership["id"], hdr))
    account = get_success_data(api_client.get_account(account_id, hdr))
    return account, vehicle, membership


def setup_unlimited_active(monthly_fee_cents=3000, wash_cooldown_hours=0, max_addons=3,
                           clock="2026-06-01T00:00:00Z", license_plate="UNL001"):
    """Clock + UNLIMITED plan + INDIVIDUAL account + vehicle + ACTIVE membership.

    Returns (plan, account, vehicle, membership).
    """
    set_clock(clock)
    plan = create_plan(
        monthly_fee_cents=monthly_fee_cents,
        wash_cooldown_hours=wash_cooldown_hours,
        max_addons=max_addons,
    )
    account, vehicle, membership = create_active_membership(
        plan["id"], license_plate=license_plate
    )
    return plan, account, vehicle, membership


def setup_single_wash_active(included_credits=2, per_credit_price_cents=1200,
                             clock="2026-06-01T00:00:00Z", license_plate="SWL001",
                             fund_cents=0):
    """Clock + SINGLE_WASH plan + INDIVIDUAL account (optionally funded) + vehicle +
    ACTIVE membership. Returns (plan, account, vehicle, membership)."""
    set_clock(clock)
    plan = create_single_wash_plan(
        included_credits=included_credits, per_credit_price_cents=per_credit_price_cents
    )
    account = create_account()
    if fund_cents:
        fund_wallet(account["id"], fund_cents)
    hdr = make_account_holder_headers(account["id"])
    vehicle = create_vehicle(account["id"], license_plate, "CA", hdr)
    membership = enroll_membership(account["id"], vehicle["id"], plan["id"], hdr)
    pay_first_cycle_invoice(membership["id"], account["id"], hdr)
    membership = get_success_data(api_client.get_membership(membership["id"], hdr))
    account = get_success_data(api_client.get_account(account["id"], hdr))
    return plan, account, vehicle, membership


# ─── Add-on attachment (PRD Section 3.9) ───────────────────────────────────

def attach_one_addon(membership_id, addon_id, account_id):
    """Read the membership's current version, then attach the add-on (OCC-correct).
    Returns the created MembershipAddOn object."""
    hdr = make_account_holder_headers(account_id)
    mem = get_success_data(api_client.get_membership(membership_id, hdr))
    res = api_client.attach_addon(
        membership_id, attach_addon_payload(addon_id, mem["version"]), hdr
    )
    return get_success_data(res)


# ─── Wash admission (PRD Section 3.6) ──────────────────────────────────────

def submit_wash(location_id, license_plate, state_code="CA"):
    """Submit an LPR wash entry as the LocationOperator. Returns the WashEvent."""
    return get_success_data(
        api_client.create_wash_event(
            wash_event_payload(location_id, license_plate, state_code), LO
        )
    )


# ─── Freeze scheduling (PRD Section 3.8) ───────────────────────────────────

def schedule_freeze(membership_id, account_id, start_utc, end_utc):
    """Schedule a future freeze window on the membership. Returns the Freeze."""
    hdr = make_account_holder_headers(account_id)
    res = api_client.freeze_scheduled(
        membership_id, freeze_scheduled_payload(start_utc, end_utc), hdr
    )
    return get_success_data(res)


# ─── Billing (PRD Section 3.4) ─────────────────────────────────────────────

def run_billing(membership_id=None, headers=None):
    """Run the recurring billing cycle, optionally scoped to one membership.
    Returns the list of issued invoices (the data array)."""
    hdr = headers or BA
    payload = {} if membership_id is None else {"membership_id": membership_id}
    return get_success_data(api_client.billing_run(payload, hdr))


def simulate(invoice_id, outcome):
    """Resolve an invoice charge deterministically. Returns the invoice."""
    return get_success_data(
        api_client.simulate_payment({"invoice_id": invoice_id, "outcome": outcome}, PA)
    )


def latest_wallet_transaction(account_id, headers=None):
    """Return the most recent WalletTransaction (created_at ASC -> last element)."""
    hdr = headers or make_account_holder_headers(account_id)
    res = api_client.list_wallet_transactions(account_id, hdr)
    data = get_success_data(res)
    return data[-1] if data else None
