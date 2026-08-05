"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server before
each test), so every fixture builds its preconditions from scratch using only
PRD-declared endpoints. Setup calls use get_success_data (lenient) so a broken
precondition surfaces as a clear "Setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from . import factories as f
from .test_users import (
    TEST_USERS,
    make_assistance_caseworker_headers,
    make_supervisor_headers,
)

APRIL_START = "2026-04-01T00:00:00Z"
MAY_START = "2026-05-01T00:00:00Z"
DEFAULT_READ_DATE = "2026-04-15T00:00:00Z"

_BS = TEST_USERS["billing_specialist_headers"]
_MT = TEST_USERS["meter_tech_headers"]
_CO = TEST_USERS["collections_officer_headers"]
_CW = TEST_USERS["assistance_caseworker_headers"]


# --------------------------------------------------------------------------
# Primitive building blocks
# --------------------------------------------------------------------------
def set_clock(api, iso: str):
    return get_success_data(api.set_clock(iso, _BS))


def create_water_schedule(api, **overrides):
    return get_success_data(api.create_rate_schedule(f.water_rate_schedule_payload(**overrides), _BS))


def create_sewer_schedule(api, **overrides):
    return get_success_data(api.create_rate_schedule(f.sewer_rate_schedule_payload(**overrides), _BS))


def create_electric_schedule(api, **overrides):
    return get_success_data(api.create_rate_schedule(f.electric_rate_schedule_payload(**overrides), _BS))


def open_account(api, **overrides):
    return get_success_data(api.create_account(f.account_payload(**overrides), _BS))


def add_meter(api, account_id, service_type="WATER", **overrides):
    return get_success_data(api.create_meter(account_id, f.meter_payload(service_type, **overrides), _BS))


def add_reading(api, meter_id, reading_value, read_type="ACTUAL", read_date=DEFAULT_READ_DATE):
    return get_success_data(
        api.create_reading(meter_id, f.reading_payload(reading_value, read_type, read_date), _MT)
    )


def generate_bill(api, account_id, period_start=APRIL_START, period_end=MAY_START, **overrides):
    return get_success_data(
        api.create_bill(account_id, f.bill_payload(period_start, period_end, **overrides), _BS)
    )


def collect_deposit(api, account_id, amount_cents, reason="NEW_SERVICE"):
    return get_success_data(api.create_deposit(account_id, f.deposit_payload(amount_cents, reason), _BS))


def enroll_assistance(api, account_id, program, discount_pct):
    return get_success_data(api.enroll_assistance(account_id, f.assistance_payload(program, discount_pct), _CW))


def enroll_budget_plan(api, account_id, plan_year=2026):
    return get_success_data(api.create_budget_plan(account_id, f.budget_plan_payload(plan_year), _BS))


def make_payment(api, account_id, amount_cents, method="CASH"):
    return get_success_data(api.create_payment(account_id, f.payment_payload(amount_cents, method), _BS))


# --------------------------------------------------------------------------
# Tier 2: account + water meter + reading + one bill (the most common state)
# --------------------------------------------------------------------------
def setup_account_with_water_bill(
    api,
    reading_value=9500,
    read_type="ACTUAL",
    prior_reading=None,
    period_start=APRIL_START,
    period_end=MAY_START,
    read_date=DEFAULT_READ_DATE,
    estimated_monthly_units=0,
    account_overrides=None,
):
    """Active WATER schedule + account + one WATER meter + reading(s) + one bill.

    Returns dict: schedule, account, meter, bill. With defaults (reading 9500 ACTUAL)
    the water line is 4640 cents.
    """
    create_water_schedule(api)
    account = open_account(api, **(account_overrides or {}))
    meter = add_meter(api, account["id"], "WATER", estimated_monthly_units=estimated_monthly_units)
    if prior_reading is not None:
        add_reading(api, meter["id"], prior_reading, "ACTUAL", "2026-03-15T00:00:00Z")
    add_reading(api, meter["id"], reading_value, read_type, read_date)
    bill = generate_bill(api, account["id"], period_start, period_end)
    return {"schedule": None, "account": account, "meter": meter, "bill": bill}


# --------------------------------------------------------------------------
# Tier 1/3: reach DELINQUENT account state
# --------------------------------------------------------------------------
def setup_delinquent_account(api, reading_value=9500, clock_at="2026-06-15T00:00:00Z"):
    """WATER account with one bill, clock advanced past the 21-day grace, bill marked
    delinquent → account DELINQUENT. Returns dict: account, meter, bill.

    reading 9500 → delinquent_balance 4640; reading 18000 → delinquent_balance 10690.
    """
    ctx = setup_account_with_water_bill(api, reading_value=reading_value)
    set_clock(api, clock_at)
    get_success_data(api.mark_delinquent(ctx["bill"]["id"], _CO))
    return ctx


def setup_delinquent_with_scheduled_shutoff(api, reading_value=9500, scheduled_date="2026-06-20T00:00:00Z"):
    """DELINQUENT account with a manually SCHEDULED shutoff order.
    Returns dict: account, meter, bill, shutoff."""
    ctx = setup_delinquent_account(api, reading_value=reading_value)
    shutoff = get_success_data(
        api.create_shutoff_order(ctx["account"]["id"], f.shutoff_order_payload(scheduled_date), _CO)
    )
    ctx["shutoff"] = shutoff
    return ctx


def setup_pending_lien(api, reading_value=18000, tax_parcel_ref="PARCEL-TEST"):
    """DELINQUENT account with arrears >= 10000 and a PENDING lien transfer.
    Returns dict: account, meter, bill, lien."""
    ctx = setup_delinquent_account(api, reading_value=reading_value)
    lien = get_success_data(
        api.create_lien_transfer(ctx["account"]["id"], f.lien_transfer_payload(tax_parcel_ref), _CO)
    )
    ctx["lien"] = lien
    return ctx


# --------------------------------------------------------------------------
# Tier 3: payment arrangements
# --------------------------------------------------------------------------
def setup_active_arrangement(api, total_arranged_cents=30000, installment_count=3, account_overrides=None):
    """Account with one ACTIVE payment arrangement. Returns dict: account, arrangement."""
    account = open_account(api, **(account_overrides or {}))
    arrangement = get_success_data(
        api.create_arrangement(
            account["id"],
            f.arrangement_payload(total_arranged_cents, installment_count, account["version"]),
            _CW,
        )
    )
    return {"account": account, "arrangement": arrangement}


def setup_account_with_bill_and_arrangement(api, reading_value=9500, total_arranged_cents=4640, installment_count=4):
    """WATER account with one UNPAID CURRENT bill and one ACTIVE arrangement.
    Returns dict: account, meter, bill, arrangement. Used for the default cascade."""
    ctx = setup_account_with_water_bill(api, reading_value=reading_value)
    account = get_success_data(api.get_account(ctx["account"]["id"], _BS))
    arrangement = get_success_data(
        api.create_arrangement(
            account["id"],
            f.arrangement_payload(total_arranged_cents, installment_count, account["version"]),
            _CW,
        )
    )
    ctx["arrangement"] = arrangement
    return ctx


# --------------------------------------------------------------------------
# Tier 3: paid bill / reversal preconditions
# --------------------------------------------------------------------------
def setup_paid_bill(api, reading_value=9500, amount_cents=4640, method="ACH"):
    """WATER account with one bill fully paid (bill PAID, balance 0).
    Returns dict: account, meter, bill, payment."""
    ctx = setup_account_with_water_bill(api, reading_value=reading_value)
    payment = make_payment(api, ctx["account"]["id"], amount_cents, method)
    ctx["payment"] = payment
    return ctx


# --------------------------------------------------------------------------
# Tier 5: deposits / finalization
# --------------------------------------------------------------------------
def setup_account_with_meter_and_deposit(api, reading_value=9500, deposit_amount=6000):
    """WATER account with a metered reading (no bill yet) and one HELD deposit.
    Returns dict: account, meter, deposit."""
    create_water_schedule(api)
    account = open_account(api)
    meter = add_meter(api, account["id"], "WATER")
    add_reading(api, meter["id"], reading_value, "ACTUAL", DEFAULT_READ_DATE)
    deposit = collect_deposit(api, account["id"], deposit_amount)
    return {"account": account, "meter": meter, "deposit": deposit}


def setup_account_with_deposit_no_meters(api, deposit_amount=3000):
    """Account with no meters and one HELD deposit (a future final bill will be 0).
    Returns dict: account, deposit."""
    account = open_account(api)
    deposit = collect_deposit(api, account["id"], deposit_amount)
    return {"account": account, "deposit": deposit}


# --------------------------------------------------------------------------
# Tier 3: adjustments (request + approve, controlling SoD identities)
# --------------------------------------------------------------------------
def request_adjustment(api, bill_id, requester_id, **payload_overrides):
    """Request an adjustment as an AssistanceCaseworker with an explicit X-User-ID."""
    headers = make_assistance_caseworker_headers(requester_id)
    adj_type = payload_overrides.pop("adjustment_type", "GOODWILL")
    return get_success_data(
        api.create_adjustment(bill_id, f.adjustment_payload(adj_type, **payload_overrides), headers)
    )


def approve_adjustment(api, adjustment_id, approver_id):
    """Approve an adjustment as a Supervisor with an explicit X-User-ID."""
    return get_success_data(api.approve_adjustment(adjustment_id, make_supervisor_headers(approver_id)))


def setup_bill_with_leak_adjustment(api, relief_method, reading_value=9500, baseline_units=3000, requester_id="cw_1"):
    """WATER account with a bill (4640), plus a REQUESTED LEAK adjustment of the given
    relief_method. Returns dict: account, meter, bill, adjustment."""
    ctx = setup_account_with_water_bill(api, reading_value=reading_value)
    adjustment = request_adjustment(
        api,
        ctx["bill"]["id"],
        requester_id,
        adjustment_type="LEAK",
        relief_method=relief_method,
        baseline_units=baseline_units,
    )
    ctx["adjustment"] = adjustment
    return ctx


def setup_bill_with_approved_goodwill(api, requester_id="cw_shared", approver_id="sup_a", goodwill_amount_cents=500):
    """WATER account with a GOODWILL adjustment already APPROVED. Returns dict:
    account, meter, bill, adjustment."""
    ctx = setup_account_with_water_bill(api)
    adjustment = request_adjustment(
        api, ctx["bill"]["id"], requester_id, adjustment_type="GOODWILL", goodwill_amount_cents=goodwill_amount_cents
    )
    approve_adjustment(api, adjustment["id"], approver_id)
    ctx["adjustment"] = adjustment
    return ctx


# --------------------------------------------------------------------------
# Tier 4/5: budget billing accumulation
# --------------------------------------------------------------------------
def setup_budget_plan_with_two_bills(api, prior_annual_charges_cents=48000):
    """Budget-enrolled account (monthly 4000) with two budget_billed bills, each metered
    to a 9500-gallon delta (actual 4640 each). Returns dict: account, plan, bill1, bill2."""
    create_water_schedule(api)
    account = open_account(api, prior_annual_charges_cents=prior_annual_charges_cents)
    plan = enroll_budget_plan(api, account["id"])
    meter = add_meter(api, account["id"], "WATER")
    add_reading(api, meter["id"], 9500, "ACTUAL", "2026-01-31T00:00:00Z")
    bill1 = generate_bill(api, account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z", budget_billed=True)
    add_reading(api, meter["id"], 19000, "ACTUAL", "2026-02-28T00:00:00Z")
    bill2 = generate_bill(api, account["id"], "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z", budget_billed=True)
    return {"account": account, "plan": plan, "bill1": bill1, "bill2": bill2, "meter": meter}


def setup_account_with_two_bills(api):
    """WATER account with a Jan bill (6000 gal → 2890) and a Feb bill (9500 gal delta → 4640).
    Returns dict: account, meter, bill1 (Jan), bill2 (Feb)."""
    create_water_schedule(api)
    account = open_account(api)
    meter = add_meter(api, account["id"], "WATER")
    add_reading(api, meter["id"], 6000, "ACTUAL", "2026-01-31T00:00:00Z")
    bill1 = generate_bill(api, account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")
    add_reading(api, meter["id"], 15500, "ACTUAL", "2026-02-28T00:00:00Z")
    bill2 = generate_bill(api, account["id"], "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z")
    return {"account": account, "meter": meter, "bill1": bill1, "bill2": bill2}
