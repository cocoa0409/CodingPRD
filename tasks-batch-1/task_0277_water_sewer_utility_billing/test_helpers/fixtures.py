"""Composite setup helpers.

Each test runs against a freshly launched server with an empty database, so
every fixture builds its preconditions from scratch using only PRD endpoints.
Fixtures use get_success_data() (lenient) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: the Customer role is entity-backed by an Account; any
ownership-gated customer call uses make_customer_headers(account["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers
from . import factories as f
from .constants import CANONICAL_RATE_SCHEDULE

CLERK = TEST_USERS["billing_clerk_headers"]
FIELDOPS = TEST_USERS["field_ops_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]


# ---------------------------------------------------------------------------
# Low-level building blocks
# ---------------------------------------------------------------------------
def set_clock(iso):
    return get_success_data(api_client.set_clock(iso, CLERK))


def create_rate_schedule(**overrides):
    payload = f.rate_schedule_payload(**overrides)
    return get_success_data(api_client.create_rate_schedule(payload, CLERK))


def create_account(rate_schedule_id, **overrides):
    payload = f.account_payload(rate_schedule_id, **overrides)
    return get_success_data(api_client.create_account(payload, CLERK))


def create_meter(account_id, meter_type="POTABLE", serial="P1"):
    payload = f.meter_payload(meter_type=meter_type, serial=serial)
    return get_success_data(api_client.create_meter(account_id, payload, CLERK))


def create_cycle(label="2026-01",
                 period_start="2026-01-01T00:00:00Z",
                 period_end="2026-02-01T00:00:00Z",
                 due_date="2026-02-15T00:00:00Z"):
    payload = f.billing_cycle_payload(label, period_start, period_end, due_date)
    return get_success_data(api_client.create_billing_cycle(payload, CLERK))


def add_read(meter_id, reading_gallons, read_date, source=None):
    overrides = {}
    if source is not None:
        overrides["source"] = source
    payload = f.read_payload(reading_gallons, read_date, **overrides)
    return get_success_data(api_client.create_read(meter_id, payload, CLERK))


def generate_bill(account_id, cycle_id):
    payload = f.bill_payload(account_id, cycle_id)
    return get_success_data(api_client.create_bill(payload, CLERK))


def post_bill(bill_id):
    return get_success_data(api_client.post_bill(bill_id, CLERK))


# ---------------------------------------------------------------------------
# Tier 2/3: canonical billed account
# ---------------------------------------------------------------------------
def setup_account_with_meters(rate_overrides=None, with_irrigation=True):
    """Rate schedule + account + POTABLE (+ optional IRRIGATION) meter.

    Returns dict with rs, account, potable_meter, irrigation_meter (or None).
    """
    rs = create_rate_schedule(**(rate_overrides or {}))
    account = create_account(rs["id"])
    potable = create_meter(account["id"], "POTABLE", "P1")
    irrigation = create_meter(account["id"], "IRRIGATION", "I1") if with_irrigation else None
    return {"rs": rs, "account": account, "potable_meter": potable,
            "irrigation_meter": irrigation}


def setup_canonical_draft_bill(potable=12000, irrigation=8000,
                               rate_overrides=None,
                               period_start="2026-01-01T00:00:00Z",
                               period_end="2026-02-01T00:00:00Z"):
    """Canonical residential schedule, one POTABLE + one IRRIGATION meter, reads
    0->potable and 0->irrigation inside the cycle window, then a DRAFT bill.

    Returns (account, bill, rs, cycle, potable_meter, irrigation_meter).
    """
    ctx = setup_account_with_meters(rate_overrides=rate_overrides, with_irrigation=irrigation is not None)
    account, rs = ctx["account"], ctx["rs"]
    cycle = create_cycle(period_start=period_start, period_end=period_end)
    add_read(ctx["potable_meter"]["id"], 0, period_start)
    add_read(ctx["potable_meter"]["id"], potable, "2026-01-31T00:00:00Z")
    if irrigation is not None and ctx["irrigation_meter"]:
        add_read(ctx["irrigation_meter"]["id"], 0, period_start)
        add_read(ctx["irrigation_meter"]["id"], irrigation, "2026-01-31T00:00:00Z")
    bill = generate_bill(account["id"], cycle["id"])
    return account, bill, rs, cycle, ctx["potable_meter"], ctx["irrigation_meter"]


def setup_canonical_posted_bill(potable=12000, irrigation=8000, rate_overrides=None):
    """Canonical DRAFT bill, then posted. Returns (account, bill, rs, cycle)."""
    account, bill, rs, cycle, _, _ = setup_canonical_draft_bill(
        potable=potable, irrigation=irrigation, rate_overrides=rate_overrides)
    bill = post_bill(bill["id"])
    return account, bill, rs, cycle


# ---------------------------------------------------------------------------
# Tier 1/4: past-due account at a controllable arrears level
# ---------------------------------------------------------------------------
def setup_past_due_account(potable=12000, irrigation=8000, rate_overrides=None,
                           initial_clock="2026-01-15T00:00:00Z",
                           close_clock="2026-03-01T00:00:00Z"):
    """Canonical posted bill, then advance clock and CLOSE the cycle so the
    account flips to PAST_DUE with a late fee assessed.

    Returns (account_after_close, bill_after_close, rs, cycle).
    """
    set_clock(initial_clock)
    account, bill, rs, cycle, _, _ = setup_canonical_draft_bill(
        potable=potable, irrigation=irrigation, rate_overrides=rate_overrides)
    bill = post_bill(bill["id"])
    set_clock(close_clock)
    get_success_data(api_client.close_billing_cycle(cycle["id"], CLERK))
    account = get_success_data(api_client.get_account(account["id"], CLERK))
    bill = get_success_data(api_client.get_bill(bill["id"], CLERK))
    return account, bill, rs, cycle


def setup_flat_past_due_account(potable, arrears_threshold=7500,
                                initial_clock="2026-01-15T00:00:00Z",
                                close_clock="2026-03-01T00:00:00Z"):
    """Flat-rate schedule (no fixed charge, no sewer, late_fee_pct=0) so the
    posted bill's amount_billed_cents == potable_gallons * 500 / 1000, letting a
    test target an exact past_due figure. Returns (account, bill, rs, cycle)."""
    set_clock(initial_clock)
    rs = create_rate_schedule(
        name="Flat",
        fixed_water_charge_cents=0,
        fixed_sewer_charge_cents=0,
        water_tiers=[{"up_to_gallons": None, "rate_cents_per_kgal": 500}],
        sewer_rate_cents_per_kgal=0,
        sewer_ratio_pct=0,
        arrears_shutoff_threshold_cents=arrears_threshold,
        late_fee_pct=0,
    )
    account = create_account(rs["id"])
    potable_meter = create_meter(account["id"], "POTABLE", "P1")
    cycle = create_cycle()
    add_read(potable_meter["id"], 0, "2026-01-01T00:00:00Z")
    add_read(potable_meter["id"], potable, "2026-01-31T00:00:00Z")
    bill = generate_bill(account["id"], cycle["id"])
    bill = post_bill(bill["id"])
    set_clock(close_clock)
    get_success_data(api_client.close_billing_cycle(cycle["id"], CLERK))
    account = get_success_data(api_client.get_account(account["id"], CLERK))
    bill = get_success_data(api_client.get_bill(bill["id"], CLERK))
    return account, bill, rs, cycle


def setup_protected_past_due_account(potable, arrears_threshold=7500,
                                     initial_clock="2026-01-15T00:00:00Z",
                                     close_clock="2026-03-01T00:00:00Z"):
    """Flat-rate PAST_DUE account that carries an ACTIVE shutoff-protection
    assistance enrollment while remaining in PAST_DUE (not DELINQUENT_PROTECTED).

    Per PRD §3.10 the DELINQUENT_PROTECTED transition fires only when a
    protection-granting enrollment is created *while the account is currently
    PAST_DUE*. Enrolling protection here while the account is still CURRENT (the
    cycle is not yet closed) therefore leaves billing_status at CURRENT; closing
    the cycle afterward flips CURRENT -> PAST_DUE (§3.3). The result is an
    account that is genuinely PAST_DUE with an ACTIVE protection enrollment — the
    only state from which the §3.9 ERR_SHUTOFF_PROTECTED guard is reachable,
    because scheduling out of any non-PAST_DUE state is an ERR_INVALID_STATE
    (higher precedence per §2.9). Returns (account, bill, rs, cycle)."""
    set_clock(initial_clock)
    rs = create_rate_schedule(
        name="Flat",
        fixed_water_charge_cents=0,
        fixed_sewer_charge_cents=0,
        water_tiers=[{"up_to_gallons": None, "rate_cents_per_kgal": 500}],
        sewer_rate_cents_per_kgal=0,
        sewer_ratio_pct=0,
        arrears_shutoff_threshold_cents=arrears_threshold,
        late_fee_pct=0,
    )
    account = create_account(rs["id"])
    potable_meter = create_meter(account["id"], "POTABLE", "P1")
    cycle = create_cycle()
    add_read(potable_meter["id"], 0, "2026-01-01T00:00:00Z")
    add_read(potable_meter["id"], potable, "2026-01-31T00:00:00Z")
    bill = generate_bill(account["id"], cycle["id"])
    bill = post_bill(bill["id"])
    # Enroll protection while account is still CURRENT: no DELINQUENT_PROTECTED
    # transition; the ACTIVE protection enrollment persists.
    get_success_data(api_client.create_assistance_enrollment(
        account["id"], f.assistance_enrollment_payload(grants_shutoff_protection=True),
        CASEWORKER))
    set_clock(close_clock)
    get_success_data(api_client.close_billing_cycle(cycle["id"], CLERK))
    account = get_success_data(api_client.get_account(account["id"], CLERK))
    bill = get_success_data(api_client.get_bill(bill["id"], CLERK))
    return account, bill, rs, cycle


# ---------------------------------------------------------------------------
# Tier 3/5: shutoff lifecycle
# ---------------------------------------------------------------------------
def setup_scheduled_shutoff(potable=12000, irrigation=8000,
                            scheduled_for="2026-03-10T00:00:00Z"):
    """Past-due account with one SCHEDULED shutoff order (account
    SHUTOFF_PENDING). Returns (account, bill, order, rs, cycle)."""
    account, bill, rs, cycle = setup_past_due_account(potable=potable, irrigation=irrigation)
    order = get_success_data(api_client.create_shutoff_order(
        f.shutoff_order_payload(account["id"], bill["id"], scheduled_for), FIELDOPS))
    account = get_success_data(api_client.get_account(account["id"], CLERK))
    return account, bill, order, rs, cycle


def setup_executed_shutoff(potable=12000, irrigation=8000,
                           scheduled_for="2026-03-10T00:00:00Z",
                           execute_clock="2026-03-10T00:00:00Z"):
    """Scheduled shutoff advanced to EXECUTED (account SUSPENDED). Returns
    (account, bill, order, rs, cycle)."""
    account, bill, order, rs, cycle = setup_scheduled_shutoff(
        potable=potable, irrigation=irrigation, scheduled_for=scheduled_for)
    set_clock(execute_clock)
    order = get_success_data(api_client.execute_shutoff_order(order["id"], FIELDOPS))
    account = get_success_data(api_client.get_account(account["id"], CLERK))
    return account, bill, order, rs, cycle


# ---------------------------------------------------------------------------
# Tier 4: budget-billing two-cycle setup for true-up
# ---------------------------------------------------------------------------
def setup_budget_plan_two_posted_bills(monthly_amount_cents=10000):
    """Account on an ACTIVE budget plan (monthly_amount), with two posted bills
    whose ACTUAL amount_billed_cents are 18980 (cyc1: potable 12000 + irrigation
    8000) and 7240 (cyc2: potable 18000-12000=6000 only, no new irrigation).

      bill2 amount_billed: water_volumetric over 6000 gal =
        5000*300 + 1000*500 = 2,000,000 /1000 = 2000 cents
        sewer billable = round_half_up(6000*90/100)=5400 -> 5400*600/1000=3240
        fixed = 2000 ; total amount_billed = 2000 + 3240 + 2000 = 7240
      trued_up_delta = (18980 + 7240) - (2 * 10000) = 26220 - 20000 = 6220

    Returns dict: account, plan, bill1, bill2, rs, cyc1, cyc2.
    """
    rs = create_rate_schedule()
    account = create_account(rs["id"])
    potable = create_meter(account["id"], "POTABLE", "P1")
    irrigation = create_meter(account["id"], "IRRIGATION", "I1")
    plan = get_success_data(api_client.create_budget_plan(
        account["id"],
        f.budget_plan_payload(monthly_amount_cents, account["version"]),
        CLERK))
    # Cycle 1: potable 0->12000, irrigation 0->8000
    cyc1 = create_cycle(label="2026-01",
                        period_start="2026-01-01T00:00:00Z",
                        period_end="2026-02-01T00:00:00Z",
                        due_date="2026-02-15T00:00:00Z")
    add_read(potable["id"], 0, "2026-01-01T00:00:00Z")
    add_read(potable["id"], 12000, "2026-01-31T00:00:00Z")
    add_read(irrigation["id"], 0, "2026-01-01T00:00:00Z")
    add_read(irrigation["id"], 8000, "2026-01-31T00:00:00Z")
    bill1 = generate_bill(account["id"], cyc1["id"])
    bill1 = post_bill(bill1["id"])
    # Cycle 2: potable 12000->18000 (6000 gal), no new irrigation reads
    cyc2 = create_cycle(label="2026-02",
                        period_start="2026-02-01T00:00:00Z",
                        period_end="2026-03-01T00:00:00Z",
                        due_date="2026-03-15T00:00:00Z")
    add_read(potable["id"], 18000, "2026-02-28T00:00:00Z")
    bill2 = generate_bill(account["id"], cyc2["id"])
    bill2 = post_bill(bill2["id"])
    return {"account": account, "plan": plan, "bill1": bill1, "bill2": bill2,
            "rs": rs, "cyc1": cyc1, "cyc2": cyc2}


# ---------------------------------------------------------------------------
# Sewer-cap variant pair
# ---------------------------------------------------------------------------
def setup_sewer_variant_bills(potable=12000):
    """Two accounts on two schedules differing only in sewer_cap_gallons
    (null vs 8000), each billed at the same potable consumption. Returns
    (bill_uncapped, bill_capped)."""
    rs_unc = create_rate_schedule(name="Uncapped")
    rs_cap = create_rate_schedule(name="Capped", sewer_cap_gallons=8000)
    acct_u = create_account(rs_unc["id"], holder_name="U", service_address="2 St")
    acct_c = create_account(rs_cap["id"], holder_name="C", service_address="3 St")
    mpu = create_meter(acct_u["id"], "POTABLE", "PU")
    mpc = create_meter(acct_c["id"], "POTABLE", "PC")
    cycle = create_cycle()
    add_read(mpu["id"], 0, "2026-01-01T00:00:00Z")
    add_read(mpu["id"], potable, "2026-01-31T00:00:00Z")
    add_read(mpc["id"], 0, "2026-01-01T00:00:00Z")
    add_read(mpc["id"], potable, "2026-01-31T00:00:00Z")
    bill_u = generate_bill(acct_u["id"], cycle["id"])
    bill_c = generate_bill(acct_c["id"], cycle["id"])
    return bill_u, bill_c


# ---------------------------------------------------------------------------
# Single-potable boundary setup (water tier ceilings)
# ---------------------------------------------------------------------------
def setup_single_potable_bill(potable_reading, rate_overrides=None):
    """Canonical schedule, one POTABLE meter, single span 0->potable_reading,
    DRAFT bill. Returns (account, bill)."""
    rs = create_rate_schedule(**(rate_overrides or {}))
    account = create_account(rs["id"])
    meter = create_meter(account["id"], "POTABLE", "P1")
    cycle = create_cycle()
    add_read(meter["id"], 0, "2026-01-01T00:00:00Z")
    add_read(meter["id"], potable_reading, "2026-01-31T00:00:00Z")
    bill = generate_bill(account["id"], cycle["id"])
    return account, bill


# ---------------------------------------------------------------------------
# Leak adjustment: pending request on a (DRAFT or POSTED) bill
# ---------------------------------------------------------------------------
def setup_pending_leak_on_draft(baseline_gallons=4000, potable=12000):
    """DRAFT bill with a PENDING leak adjustment (caseworker-requested).
    Returns (account, bill, leak)."""
    account, bill, rs, cycle, _, _ = setup_canonical_draft_bill(
        potable=potable, irrigation=None)
    leak = get_success_data(api_client.create_leak_adjustment(
        f.leak_adjustment_payload(bill["id"], baseline_gallons), CASEWORKER))
    return account, bill, leak


def setup_pending_leak_on_posted(baseline_gallons=4000, potable=12000, irrigation=8000):
    """POSTED bill with a PENDING leak adjustment requested by the owning
    Customer (ownership-threaded). Returns (account, bill, leak)."""
    account, bill, rs, cycle = setup_canonical_posted_bill(
        potable=potable, irrigation=irrigation)
    cust = make_customer_headers(account["id"])
    leak = get_success_data(api_client.create_leak_adjustment(
        f.leak_adjustment_payload(bill["id"], baseline_gallons), cust))
    return account, bill, leak
