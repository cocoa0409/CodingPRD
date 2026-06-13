"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "Setup step failed" errors rather than confusing assertion
failures. Every fixture builds its preconditions from scratch via PRD-declared
endpoints — the test harness restarts the server (empty DB) before each test.

Identity threading: Customer is entity_backed:Account. Any ownership-gated
Customer call (POST /payments) uses make_customer_headers(account["id"]),
never the shared TEST_USERS["customer_headers"] fallback.

Standard scenario figures (canonical residential TOU tariff, fixed 1000c,
breakpoints [500,1000], rates [12,18,25], TOU 1.5/1.0/0.8, demand 800,
net-metering 10):
  - "2756" reads: 3x ON_PEAK import 2.0 (h16,17,18) + 1x MID_PEAK import 4.0
    (h07) over a period -> energy 156, demand 1600, actual 2756.
  - "2636" reads: 1x ON_PEAK import 2.0 (h16) -> energy 36, demand 1600,
    actual 2636.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_tariff_payload,
    create_account_payload,
    create_meter_payload,
    create_meter_read_payload,
    create_bill_payload,
    create_payment_payload,
    create_budget_plan_payload,
    create_assistance_grant_payload,
)
from .test_users import TEST_USERS, make_customer_headers

OPERATOR = TEST_USERS["operator_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]


# ---------------------------------------------------------------------------
# Read-set builders: hour-of-day -> tou_period (UTC) per the fixed schedule.
# Each read spans exactly one hour starting at the given day + hour.
# ---------------------------------------------------------------------------
def _iso(day: str, hour: int) -> str:
    return f"{day}T{hour:02d}:00:00Z"


def reads_for_2756(day: str = "2026-01-05"):
    """3x ON_PEAK import 2.0 (h16,17,18) + 1x MID_PEAK import 4.0 (h07)."""
    return [
        (_iso(day, 16), _iso(day, 17), 2.0, 0.0),
        (_iso(day, 17), _iso(day, 18), 2.0, 0.0),
        (_iso(day, 18), _iso(day, 19), 2.0, 0.0),
        (_iso(day, 7), _iso(day, 8), 4.0, 0.0),
    ]


def reads_for_2636(day: str = "2026-01-05"):
    """1x ON_PEAK import 2.0 (h16) -> energy 36, demand 1600 -> actual 2636."""
    return [
        (_iso(day, 16), _iso(day, 17), 2.0, 0.0),
    ]


# ---------------------------------------------------------------------------
# Tier 1: State progression — tariff and account setup
# ---------------------------------------------------------------------------
def create_active_tariff(headers=OPERATOR, **tariff_overrides):
    """Create a DRAFT tariff then activate it. Returns the ACTIVE tariff."""
    tariff = get_success_data(
        api_client.create_tariff(create_tariff_payload(**tariff_overrides), headers)
    )
    return get_success_data(api_client.activate_tariff(tariff["id"], headers))


def open_account(tariff_id, headers=OPERATOR, **acct_overrides):
    """Open a fresh account on the given tariff. Returns the account."""
    return get_success_data(
        api_client.create_account(
            create_account_payload(tariff_id, **acct_overrides), headers
        )
    )


def add_meter(account_id, headers=OPERATOR, **meter_overrides):
    """Register one meter on the account. Returns the meter."""
    return get_success_data(
        api_client.create_meter(
            create_meter_payload(account_id, **meter_overrides), headers
        )
    )


def set_clock(current_utc, headers=OPERATOR):
    """Advance the simulated clock; triggers system-wide arrears recompute."""
    return get_success_data(api_client.set_clock({"current_utc": current_utc}, headers))


def import_reads(meter_id, read_tuples, headers=OPERATOR):
    """Import a list of (interval_start, interval_end, import_kwh, export_kwh)
    interval reads onto a meter. Returns the list of created reads."""
    created = []
    for start, end, imp, exp in read_tuples:
        created.append(
            get_success_data(
                api_client.create_meter_read(
                    create_meter_read_payload(meter_id, start, end, imp, export_kwh=exp),
                    headers,
                )
            )
        )
    return created


# ---------------------------------------------------------------------------
# Tier 2 / 3: Account + meter + reads + bill, and issue-with-OCC
# ---------------------------------------------------------------------------
def setup_account_with_meter(headers=OPERATOR, tariff_overrides=None,
                             acct_overrides=None, meter_overrides=None):
    """ACTIVE tariff + account + one meter. Returns (tariff, account, meter)."""
    tariff = create_active_tariff(headers, **(tariff_overrides or {}))
    account = open_account(tariff["id"], headers, **(acct_overrides or {}))
    meter = add_meter(account["id"], headers, **(meter_overrides or {}))
    return tariff, account, meter


def create_draft_bill(account_id, period_start, period_end, due_date,
                      headers=OPERATOR):
    """Create one DRAFT bill over the period. Returns the bill."""
    return get_success_data(
        api_client.create_bill(
            create_bill_payload(account_id, period_start, period_end, due_date),
            headers,
        )
    )


def issue_bill_with_occ(bill_id, account_id, headers=OPERATOR):
    """Read the account's current version then issue the bill carrying it as
    expected_account_version. Returns the issued bill (data payload)."""
    acct = get_success_data(api_client.get_account(account_id, headers))
    return api_client.issue_bill(
        bill_id, {"expected_account_version": acct["version"]}, headers
    )


def issue_bill_with_occ_data(bill_id, account_id, headers=OPERATOR):
    """As issue_bill_with_occ but returns the parsed data of a successful issue."""
    return get_success_data(issue_bill_with_occ(bill_id, account_id, headers))


def setup_issued_bill(read_tuples=None, period_start="2026-01-01T00:00:00Z",
                      period_end="2026-02-01T00:00:00Z",
                      due_date="2026-02-20T00:00:00Z",
                      tariff_overrides=None, acct_overrides=None,
                      meter_overrides=None, clock=None):
    """Full chain: ACTIVE tariff + account + meter + reads + DRAFT bill, then
    issue it under OCC. Returns dict with tariff, account, meter, reads, bill
    (the issued bill payload). `read_tuples` defaults to the 2756 read set.

    `clock`, if given, is set before any account work so arrears age correctly.
    """
    if read_tuples is None:
        read_tuples = reads_for_2756()
    tariff = create_active_tariff(**(tariff_overrides or {}))
    if clock is not None:
        set_clock(clock)
    account = open_account(tariff["id"], **(acct_overrides or {}))
    meter = add_meter(account["id"], **(meter_overrides or {}))
    reads = import_reads(meter["id"], read_tuples)
    bill = create_draft_bill(account["id"], period_start, period_end, due_date)
    issued = issue_bill_with_occ_data(bill["id"], account["id"])
    return {
        "tariff": tariff,
        "account": account,
        "meter": meter,
        "reads": reads,
        "bill": issued,
    }


# ---------------------------------------------------------------------------
# Tier 4: Arrears / collections targeting
# ---------------------------------------------------------------------------
def setup_account_in_arrears(due_date="2026-01-01T00:00:00Z",
                            arrears_clock="2026-02-15T00:00:00Z",
                            read_tuples=None):
    """Drive an account to IN_ARREARS (service_status still ACTIVE, no grant):
    clock starts 2026-01-01, issue a bill due `due_date`, then advance the
    clock to `arrears_clock` (>= 45 days past due). Returns the setup dict
    (tariff, account, meter, reads, bill). The returned account/bill are the
    post-issuance snapshots; re-GET for the post-clock state.
    """
    if read_tuples is None:
        read_tuples = reads_for_2636()
    scene = setup_issued_bill(
        read_tuples=read_tuples,
        due_date=due_date,
        clock="2026-01-01T00:00:00Z",
    )
    set_clock(arrears_clock)
    return scene


def setup_disconnect_pending(due_date="2026-01-01T00:00:00Z",
                            arrears_clock="2026-02-15T00:00:00Z"):
    """Account driven IN_ARREARS then a disconnect-notice raised, leaving a
    SCHEDULED DISCONNECT ServiceOrder and service_status DISCONNECT_PENDING.
    Returns (scene, service_order).
    """
    scene = setup_account_in_arrears(due_date=due_date, arrears_clock=arrears_clock)
    order = get_success_data(api_client.disconnect_notice(scene["account"]["id"], OPERATOR))
    return scene, order


def setup_disconnected_account(due_date="2026-01-01T00:00:00Z",
                              arrears_clock="2026-02-15T00:00:00Z"):
    """Account driven all the way to service_status DISCONNECTED while still
    IN_ARREARS: arrears -> disconnect-notice -> field-complete the disconnect.
    Returns (scene, disconnect_order).
    """
    scene, order = setup_disconnect_pending(due_date=due_date, arrears_clock=arrears_clock)
    get_success_data(api_client.complete_service_order(order["id"], DISPATCHER))
    return scene, order


# ---------------------------------------------------------------------------
# Tier 4: Budget billing / assistance targeting
# ---------------------------------------------------------------------------
def enroll_budget_plan(account_id, levelized_amount_cents, headers=OPERATOR):
    """Enroll an ACTIVE budget plan. Returns the plan."""
    return get_success_data(
        api_client.create_budget_plan(
            create_budget_plan_payload(account_id, levelized_amount_cents), headers
        )
    )


def pledge_grant(account_id, pledged_cents, program="LIHEAP", headers=CASEWORKER):
    """Pledge an assistance grant (PLEDGED). Returns the grant."""
    return get_success_data(
        api_client.create_assistance_grant(
            create_assistance_grant_payload(account_id, pledged_cents, program=program),
            headers,
        )
    )


def setup_budget_billed_issued_bill(levelized_amount_cents=1500,
                                    read_tuples=None,
                                    period_start="2026-01-01T00:00:00Z",
                                    period_end="2026-02-01T00:00:00Z",
                                    due_date="2026-02-20T00:00:00Z"):
    """ACTIVE tariff + account + meter + reads + ACTIVE budget plan + DRAFT
    bill, then issue under OCC so the bill is levelized. Returns dict with
    tariff, account, meter, reads, plan, bill (issued).
    """
    if read_tuples is None:
        read_tuples = reads_for_2756()
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    reads = import_reads(meter["id"], read_tuples)
    plan = enroll_budget_plan(account["id"], levelized_amount_cents)
    bill = create_draft_bill(account["id"], period_start, period_end, due_date)
    issued = issue_bill_with_occ_data(bill["id"], account["id"])
    return {
        "tariff": tariff,
        "account": account,
        "meter": meter,
        "reads": reads,
        "plan": plan,
        "bill": issued,
    }


def setup_assisted_issued_bill(pledged_cents=2000, read_tuples=None,
                               period_start="2026-01-01T00:00:00Z",
                               period_end="2026-02-01T00:00:00Z",
                               due_date="2026-02-20T00:00:00Z"):
    """ACTIVE tariff + account + meter + reads + PLEDGED grant + DRAFT bill,
    then issue under OCC so assistance is consumed. Returns dict with tariff,
    account, meter, reads, grant, bill (issued).
    """
    if read_tuples is None:
        read_tuples = reads_for_2756()
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    reads = import_reads(meter["id"], read_tuples)
    grant = pledge_grant(account["id"], pledged_cents)
    bill = create_draft_bill(account["id"], period_start, period_end, due_date)
    issued = issue_bill_with_occ_data(bill["id"], account["id"])
    return {
        "tariff": tariff,
        "account": account,
        "meter": meter,
        "reads": reads,
        "grant": grant,
        "bill": issued,
    }


# ---------------------------------------------------------------------------
# Payment helper threading entity-backed Customer identity
# ---------------------------------------------------------------------------
def pay_account(account_id, amount_cents, method="ACH"):
    """Post a payment as the owning Customer (entity-backed identity).
    Returns the raw response so callers can validate success or status."""
    return api_client.create_payment(
        create_payment_payload(account_id, amount_cents, method=method),
        make_customer_headers(account_id),
    )


def pay_account_data(account_id, amount_cents, method="ACH"):
    """As pay_account but returns the parsed payment data of a success."""
    return get_success_data(pay_account(account_id, amount_cents, method=method))
