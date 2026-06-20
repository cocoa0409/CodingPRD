"""Composite setup helpers.

These encapsulate the multi-step setup sequences that most interesting test claims
require. Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the test harness restarts the server (empty DB) before every test.

Fixtures use get_success_data() (lenient) internally, so a setup failure surfaces as a
clear "Setup failed" error rather than a confusing assertion failure.
"""
import itertools
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_account_headers,
)
from . import factories as F

ADMIN = TEST_USERS["billing_admin_headers"]
CS = TEST_USERS["customer_service_headers"]
FT = TEST_USERS["field_tech_headers"]

# Monotonic counters so repeated fixture calls within one test never collide on
# unique fields (RateSchedule.code, PremiseMeter.serial_no).
_code_counter = itertools.count(1)
_serial_counter = itertools.count(1)


def _unique_code(prefix="RS"):
    return f"{prefix}-{next(_code_counter):04d}"


def _unique_serial(prefix="M"):
    return f"{prefix}-{next(_serial_counter):05d}"


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(current_utc="2026-02-15T00:00:00.000Z", heating_season_active=False):
    resp = api_client.set_clock(
        F.set_clock_payload(current_utc=current_utc, heating_season_active=heating_season_active),
        headers=ADMIN,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1 — config + account creation
# ---------------------------------------------------------------------------
def create_rate_schedule(customer_class="RESIDENTIAL", fixed_customer_charge_cents=1200,
                         distribution_rate_cents_per_therm=15, btu_factor=1.025,
                         minimum_bill_cents=0, code=None):
    payload = F.create_rate_schedule_payload(
        code=code or _unique_code("RES"),
        customer_class=customer_class,
        fixed_customer_charge_cents=fixed_customer_charge_cents,
        distribution_rate_cents_per_therm=distribution_rate_cents_per_therm,
        btu_factor=btu_factor,
        minimum_bill_cents=minimum_bill_cents,
    )
    resp = api_client.create_rate_schedule(payload, headers=ADMIN)
    return get_success_data(resp)


def create_pga_schedule(effective_month="2026-02", customer_class="RESIDENTIAL",
                        commodity_rate_cents_per_therm=40, supplier_refund_cents_per_therm=5):
    payload = F.create_pga_schedule_payload(
        effective_month=effective_month,
        customer_class=customer_class,
        commodity_rate_cents_per_therm=commodity_rate_cents_per_therm,
        supplier_refund_cents_per_therm=supplier_refund_cents_per_therm,
    )
    resp = api_client.create_pga_schedule(payload, headers=ADMIN)
    return get_success_data(resp)


def create_account(rate_schedule_id, holder_name="Test Holder"):
    resp = api_client.create_account(
        F.create_account_payload(rate_schedule_id=rate_schedule_id, holder_name=holder_name),
        headers=CS,
    )
    return get_success_data(resp)


def account_version(account_id):
    resp = api_client.get_account(account_id, headers=ADMIN)
    return get_success_data(resp)["version"]


def get_account(account_id):
    resp = api_client.get_account(account_id, headers=ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1/2 — meter set lifecycle
# ---------------------------------------------------------------------------
def register_meter(account_id, uom="CCF", install_index=1000, serial_no=None):
    resp = api_client.create_meter(
        account_id,
        F.create_meter_payload(serial_no=serial_no or _unique_serial("M"),
                               uom=uom, install_index=install_index),
        headers=FT,
    )
    return get_success_data(resp)


def set_meter(account_id, meter_id, completed_index, scheduled_date="2026-02-01T00:00:00.000Z"):
    """Create + dispatch + complete a METER_SET order, bringing the meter to SET."""
    order = get_success_data(api_client.create_service_order(
        F.create_service_order_payload(account_id=account_id, order_type="METER_SET",
                                       premise_meter_id=meter_id, scheduled_date=scheduled_date),
        headers=FT,
    ))
    get_success_data(api_client.dispatch_service_order(order["id"], headers=FT))
    get_success_data(api_client.complete_service_order(
        order["id"], {"completed_index": completed_index}, headers=FT))
    return order


def setup_account_with_set_meter(customer_class="RESIDENTIAL", fixed_customer_charge_cents=1200,
                                 distribution_rate_cents_per_therm=15, btu_factor=1.025,
                                 minimum_bill_cents=0, uom="CCF", install_index=1000,
                                 set_clock_first=True,
                                 clock_utc="2026-02-15T00:00:00.000Z", heating_season_active=False):
    """Active account with a SET meter. Returns (rate_schedule, account, meter)."""
    if set_clock_first:
        set_clock(clock_utc, heating_season_active)
    rs = create_rate_schedule(customer_class=customer_class,
                              fixed_customer_charge_cents=fixed_customer_charge_cents,
                              distribution_rate_cents_per_therm=distribution_rate_cents_per_therm,
                              btu_factor=btu_factor, minimum_bill_cents=minimum_bill_cents)
    acct = create_account(rs["id"])
    meter = register_meter(acct["id"], uom=uom, install_index=install_index)
    set_meter(acct["id"], meter["id"], completed_index=install_index)
    return rs, acct, meter


# ---------------------------------------------------------------------------
# Tier 1/2 — reads and bills
# ---------------------------------------------------------------------------
def post_read(meter_id, reading_index, read_date, read_type="ACTUAL"):
    resp = api_client.post_read(
        meter_id,
        F.create_meter_read_payload(reading_index=reading_index, read_date=read_date,
                                    read_type=read_type),
        headers=FT,
    )
    return get_success_data(resp)


def create_bill(account_id, service_month, to_read_id, from_read_id=None, corrects_bill_id=None):
    payload = F.create_bill_payload(service_month=service_month, to_read_id=to_read_id)
    if from_read_id is not None:
        payload["from_read_id"] = from_read_id
    if corrects_bill_id is not None:
        payload["corrects_bill_id"] = corrects_bill_id
    resp = api_client.create_bill(account_id, payload, headers=ADMIN)
    return get_success_data(resp)


def issue_bill(account_id, bill_id, expected_account_version=None):
    if expected_account_version is None:
        expected_account_version = account_version(account_id)
    resp = api_client.issue_bill(
        account_id, bill_id,
        F.issue_bill_payload(expected_account_version=expected_account_version),
        headers=ADMIN,
    )
    return get_success_data(resp)


def setup_issued_bill(service_month="2026-02", reading_index=1100,
                      read_date="2026-02-28T00:00:00.000Z",
                      fixed_customer_charge_cents=1200, distribution_rate_cents_per_therm=15,
                      minimum_bill_cents=0, pga_commodity=40, pga_refund=5,
                      install_index=1000, btu_factor=1.025,
                      clock_utc="2026-02-15T00:00:00.000Z"):
    """Canonical: active RES account with one ISSUED bill. Returns
    (rate_schedule, account, meter, read, bill)."""
    rs, acct, meter = setup_account_with_set_meter(
        fixed_customer_charge_cents=fixed_customer_charge_cents,
        distribution_rate_cents_per_therm=distribution_rate_cents_per_therm,
        minimum_bill_cents=minimum_bill_cents, install_index=install_index,
        btu_factor=btu_factor, clock_utc=clock_utc)
    create_pga_schedule(effective_month=service_month, customer_class="RESIDENTIAL",
                        commodity_rate_cents_per_therm=pga_commodity,
                        supplier_refund_cents_per_therm=pga_refund)
    read = post_read(meter["id"], reading_index, read_date)
    bill = create_bill(acct["id"], service_month, read["id"])
    issued = issue_bill(acct["id"], bill["id"])
    return rs, acct, meter, read, issued


def setup_draft_bill(service_month="2026-02", reading_index=1100,
                     read_date="2026-02-28T00:00:00.000Z",
                     create_pga=True, pga_commodity=40, pga_refund=5,
                     fixed_customer_charge_cents=1200, distribution_rate_cents_per_therm=15,
                     minimum_bill_cents=0, install_index=1000, btu_factor=1.025,
                     clock_utc="2026-02-15T00:00:00.000Z"):
    """Active RES account with a SET meter, a posted read, and a DRAFT bill (not yet issued).
    Returns (rate_schedule, account, meter, read, draft_bill)."""
    rs, acct, meter = setup_account_with_set_meter(
        fixed_customer_charge_cents=fixed_customer_charge_cents,
        distribution_rate_cents_per_therm=distribution_rate_cents_per_therm,
        minimum_bill_cents=minimum_bill_cents, install_index=install_index,
        btu_factor=btu_factor, clock_utc=clock_utc)
    if create_pga:
        create_pga_schedule(effective_month=service_month, customer_class="RESIDENTIAL",
                            commodity_rate_cents_per_therm=pga_commodity,
                            supplier_refund_cents_per_therm=pga_refund)
    read = post_read(meter["id"], reading_index, read_date)
    bill = create_bill(acct["id"], service_month, read["id"])
    return rs, acct, meter, read, bill


# ---------------------------------------------------------------------------
# Tier 3 — budget plans
# ---------------------------------------------------------------------------
def enroll_budget_plan(account_id, anchor_month="2026-02", projected_annual_cents=96000,
                       expected_account_version=None):
    if expected_account_version is None:
        expected_account_version = account_version(account_id)
    resp = api_client.create_budget_plan(
        account_id,
        F.create_budget_plan_payload(anchor_month=anchor_month,
                                     projected_annual_cents=projected_annual_cents,
                                     expected_account_version=expected_account_version),
        headers=ADMIN,
    )
    return get_success_data(resp)


def setup_budget_enrolled_issued_bill(anchor_month="2026-02", projected_annual_cents=96000,
                                      service_month="2026-02"):
    """Active RES account enrolled in a budget plan (installment from projected/12),
    with one bill issued under the plan. Returns (account, meter, plan, bill)."""
    rs, acct, meter = setup_account_with_set_meter()
    create_pga_schedule(effective_month=service_month, customer_class="RESIDENTIAL",
                        commodity_rate_cents_per_therm=40, supplier_refund_cents_per_therm=5)
    read = post_read(meter["id"], 1100, "2026-02-28T00:00:00.000Z")
    plan = enroll_budget_plan(acct["id"], anchor_month=anchor_month,
                              projected_annual_cents=projected_annual_cents)
    bill = create_bill(acct["id"], service_month, read["id"])
    issued = issue_bill(acct["id"], bill["id"])
    return acct, meter, plan, issued


# ---------------------------------------------------------------------------
# Tier 3 — low-income credits
# ---------------------------------------------------------------------------
def submit_low_income_credit(account_id, household_size=1, annual_income_cents=1400000):
    resp = api_client.create_low_income_credit(
        account_id,
        F.create_low_income_credit_payload(household_size=household_size,
                                           annual_income_cents=annual_income_cents),
        headers=CS,
    )
    return get_success_data(resp)


def setup_enrolled_low_income_account(household_size=1, annual_income_cents=1400000):
    """RES account with one APPROVED low-income credit (account ENROLLED).
    Returns (rate_schedule, account, credit)."""
    rs = create_rate_schedule()
    acct = create_account(rs["id"])
    credit = submit_low_income_credit(acct["id"], household_size, annual_income_cents)
    get_success_data(api_client.approve_low_income_credit(acct["id"], credit["id"], headers=CS))
    return rs, acct, credit


def setup_low_income_issued_bill(household_size=1, annual_income_cents=1400000,
                                 service_month="2026-02"):
    """RES account ENROLLED at TIER_1 (default income), with one ISSUED bill that earns the
    per-cycle credit. Returns (account, meter, credit, bill)."""
    set_clock("2026-02-15T00:00:00.000Z", False)
    rs = create_rate_schedule()
    acct = create_account(rs["id"])
    credit = submit_low_income_credit(acct["id"], household_size, annual_income_cents)
    get_success_data(api_client.approve_low_income_credit(acct["id"], credit["id"], headers=CS))
    create_pga_schedule(effective_month=service_month, customer_class="RESIDENTIAL",
                        commodity_rate_cents_per_therm=40, supplier_refund_cents_per_therm=5)
    meter = register_meter(acct["id"], uom="CCF", install_index=1000)
    set_meter(acct["id"], meter["id"], completed_index=1000)
    read = post_read(meter["id"], 1100, "2026-02-28T00:00:00.000Z")
    bill = create_bill(acct["id"], service_month, read["id"])
    issued = issue_bill(acct["id"], bill["id"])
    return acct, meter, credit, issued


# ---------------------------------------------------------------------------
# Tier 4 — past-due / shutoff targeting
# ---------------------------------------------------------------------------
def setup_past_due_account(past_due_amount=7500, service_month="2026-02",
                           read_date="2026-02-20T00:00:00.000Z",
                           past_clock="2026-04-01T00:00:00.000Z"):
    """RES account with one ISSUED past-due bill of `past_due_amount`, clock advanced past
    the 21-day due window. Achieved with fixed_customer_charge = past_due_amount, zero
    commodity/distribution. Returns (rate_schedule, account, meter, bill)."""
    set_clock("2026-02-15T00:00:00.000Z", False)
    rs = create_rate_schedule(fixed_customer_charge_cents=past_due_amount,
                              distribution_rate_cents_per_therm=0)
    acct = create_account(rs["id"])
    create_pga_schedule(effective_month=service_month, customer_class="RESIDENTIAL",
                        commodity_rate_cents_per_therm=0, supplier_refund_cents_per_therm=0)
    meter = register_meter(acct["id"], uom="CCF", install_index=1000)
    set_meter(acct["id"], meter["id"], completed_index=1000)
    read = post_read(meter["id"], 1000, read_date)
    bill = create_bill(acct["id"], service_month, read["id"])
    issued = issue_bill(acct["id"], bill["id"])
    set_clock(past_clock, False)
    return rs, acct, meter, issued


def find_shutoff_order(account_id):
    """Return the SHUTOFF service order for an account (auto-created by shutoff-notice)."""
    resp = api_client.list_service_orders(headers=FT, params={"account_id": account_id})
    orders = get_success_data(resp)
    if isinstance(orders, dict):
        orders = orders.get("data", orders)
    for order in orders:
        if order.get("order_type") == "SHUTOFF":
            return order
    return None


def setup_shutoff_pending_dispatched(past_due_amount=7500):
    """RES account driven to SHUTOFF_PENDING with a DISPATCHED SHUTOFF order; no emergency,
    no moratorium. Returns (account, meter, shutoff_order)."""
    rs, acct, meter, bill = setup_past_due_account(past_due_amount=past_due_amount)
    get_success_data(api_client.shutoff_notice(acct["id"], headers=CS))
    shut = find_shutoff_order(acct["id"])
    get_success_data(api_client.dispatch_service_order(shut["id"], headers=FT))
    return acct, meter, shut


def setup_disconnected_account(past_due_amount=7500):
    """RES account driven to DISCONNECTED (shutoff order completed). Meter LOCKED.
    Returns (account, meter, bill)."""
    rs, acct, meter, bill = setup_past_due_account(past_due_amount=past_due_amount)
    get_success_data(api_client.shutoff_notice(acct["id"], headers=CS))
    shut = find_shutoff_order(acct["id"])
    get_success_data(api_client.dispatch_service_order(shut["id"], headers=FT))
    get_success_data(api_client.complete_service_order(shut["id"], {"completed_index": 1000}, headers=FT))
    return acct, meter, bill


def pay_off_bill(account_id, bill_id, amount_cents, posted_date="2026-04-02T00:00:00.000Z"):
    resp = api_client.create_payment(
        account_id,
        F.create_payment_payload(bill_id=bill_id, amount_cents=amount_cents, posted_date=posted_date),
        headers=CS,
    )
    return get_success_data(resp)


def create_held_deposit(account_id, reason="RECONNECT"):
    """Create + collect a deposit, bringing it to HELD. Returns the deposit (after collect)."""
    dep = get_success_data(api_client.create_deposit(
        account_id, F.create_deposit_payload(reason=reason), headers=CS))
    collected = get_success_data(api_client.collect_deposit(account_id, dep["id"], headers=CS))
    return collected


def inject_ontime_count(account_id, count):
    resp = api_client.inject_ontime_count(
        {"account_id": account_id, "count": count}, headers=ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3 — tickets
# ---------------------------------------------------------------------------
def open_ticket(meter_id, account_id=None, kind="ODOR", reported_indoors=False):
    payload = F.create_ticket_payload(premise_meter_id=meter_id, kind=kind,
                                      reported_indoors=reported_indoors)
    if account_id is not None:
        payload["account_id"] = account_id
    resp = api_client.create_ticket(payload, headers=FT)
    return get_success_data(resp)


def setup_dispatched_grade1_ticket():
    """RES account with SET meter; a GRADE_1 (LEAK indoors) ticket driven to DISPATCHED.
    Returns (account, meter, ticket)."""
    rs, acct, meter = setup_account_with_set_meter()
    ticket = open_ticket(meter["id"], account_id=acct["id"], kind="LEAK", reported_indoors=True)
    get_success_data(api_client.dispatch_ticket(ticket["id"], headers=FT))
    return acct, meter, ticket
