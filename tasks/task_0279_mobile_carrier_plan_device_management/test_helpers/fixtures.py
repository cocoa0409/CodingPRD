"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be walked into a specific state
(active line on an open billing cycle, a line carrying an active EIP and an
add-on, an account with N active lines, a completed PORT_IN, ...). These helpers
encapsulate those chains so test bodies focus on assertions.

All helpers use get_success_data() (the lenient 2xx validator) so a setup
failure surfaces as a clear "setup failed" rather than a confusing assertion.
Every database starts empty before each test, so each helper builds its world
from scratch using only PRD-declared endpoints.

Identity threading: Subscriber is entity_backed:Account, so any ownership-gated
Subscriber call uses make_subscriber_headers(account_id) with the real account id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_account_payload, create_plan_payload, create_device_payload,
    create_line_payload, create_sim_assignment_payload,
    create_installment_plan_payload, create_port_request_payload,
    create_addon_payload, create_usage_record_payload, create_billing_cycle_payload,
)
from .test_users import TEST_USERS, make_subscriber_headers

CA = TEST_USERS["carrier_agent_headers"]
PO = TEST_USERS["porting_ops_headers"]
BS = TEST_USERS["billing_system_headers"]


# ─── Atomic helpers ───────────────────────────────────────────────────────

def set_clock(iso: str):
    """Pin the server's logical UTC clock."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, BS))


def create_account(**overrides):
    """Create an ACTIVE account. Returns the account dict."""
    return get_success_data(api_client.create_account(create_account_payload(**overrides), CA))


def create_plan(**overrides):
    """Create an ACTIVE plan. Returns the plan dict."""
    return get_success_data(api_client.create_plan(create_plan_payload(**overrides), CA))


def create_device(**overrides):
    """Create a device. Returns the device dict."""
    return get_success_data(api_client.create_device(create_device_payload(**overrides), CA))


def create_billing_cycle(account_id, cycle_start, cycle_end):
    """Open a billing cycle for an account. Returns the cycle dict."""
    return get_success_data(api_client.create_billing_cycle(
        create_billing_cycle_payload(account_id, cycle_start, cycle_end), BS))


def current_account_version(account_id) -> int:
    """Re-read the account and return its current version (for OCC chains)."""
    return get_success_data(api_client.get_account(account_id, CA))["version"]


# ─── Tier 1/2: line provisioning + activation ─────────────────────────────

def provision_line(account_id, plan_id, sim_type="PHYSICAL", **overrides):
    """Provision a PENDING_ACTIVATION line using the account's current version.
    Returns the line dict."""
    ver = current_account_version(account_id)
    return get_success_data(api_client.create_line(
        create_line_payload(account_id, plan_id, ver, sim_type=sim_type, **overrides), CA))


def issue_sim(line_id, sim_type="PHYSICAL", iccid=None):
    """Issue an ISSUED SimAssignment for a line. Returns the sim dict."""
    return get_success_data(api_client.create_sim_assignment(
        create_sim_assignment_payload(line_id, sim_type=sim_type, iccid=iccid), CA))


def provision_and_activate_line(account_id, plan_id, sim_type="PHYSICAL"):
    """Provision a line, issue its SIM, and activate it. Returns the ACTIVE line."""
    line = provision_line(account_id, plan_id, sim_type=sim_type)
    issue_sim(line["id"], sim_type=sim_type)
    return get_success_data(api_client.activate_line(line["id"], CA))


def setup_account_plan():
    """ACTIVE account + ACTIVE plan. Returns (account, plan)."""
    account = create_account()
    plan = create_plan()
    return account, plan


def setup_active_line(sim_type="PHYSICAL"):
    """ACTIVE account + plan + one ACTIVE line. Returns (account, plan, line)."""
    account, plan = setup_account_plan()
    line = provision_and_activate_line(account["id"], plan["id"], sim_type=sim_type)
    return account, plan, line


def setup_active_line_on_open_cycle(cycle_start="2026-06-01T00:00:00Z",
                                    cycle_end="2026-07-01T00:00:00Z",
                                    clock_after_activate="2026-06-15T00:00:00Z",
                                    sim_type="ESIM"):
    """ACTIVE account + plan + one ACTIVE line on an OPEN 30-day cycle.

    Clock is set to cycle_start, the cycle opened, the line activated, then the
    clock advanced to clock_after_activate (still inside the cycle).
    Returns (account, plan, line, cycle).
    """
    account, plan = setup_account_plan()
    set_clock(cycle_start)
    cycle = create_billing_cycle(account["id"], cycle_start, cycle_end)
    line = provision_and_activate_line(account["id"], plan["id"], sim_type=sim_type)
    if clock_after_activate:
        set_clock(clock_after_activate)
    return account, plan, line, cycle


def setup_n_active_lines(n, sim_type="ESIM", plan_overrides=None):
    """ACTIVE account + plan + N ACTIVE lines (each provisioned with a fresh
    version read so the OCC guard is satisfied). Returns (account, plan, [lines])."""
    account = create_account()
    plan = create_plan(**(plan_overrides or {}))
    lines = []
    for _ in range(n):
        lines.append(provision_and_activate_line(account["id"], plan["id"], sim_type=sim_type))
    return account, plan, lines


# ─── Tier 3: device financing ─────────────────────────────────────────────

def create_eip(line_id, device_id, term_months=24, down_payment_cents=9900):
    """Open an ACTIVE installment plan on a line. Returns the EIP dict."""
    return get_success_data(api_client.create_installment_plan(
        create_installment_plan_payload(line_id, device_id,
                                        term_months=term_months,
                                        down_payment_cents=down_payment_cents), CA))


def setup_line_with_active_eip(retail_price_cents=99900, down_payment_cents=9900,
                               term_months=24, stock_count=5):
    """ACTIVE line with one ACTIVE EIP. Returns (account, plan, line, device, eip)."""
    account, plan = setup_account_plan()
    device = create_device(retail_price_cents=retail_price_cents, stock_count=stock_count)
    line = provision_and_activate_line(account["id"], plan["id"])
    eip = create_eip(line["id"], device["id"],
                     term_months=term_months, down_payment_cents=down_payment_cents)
    return account, plan, line, device, eip


def setup_cancel_ready_line(cycle_start="2026-06-01T00:00:00Z",
                            cycle_end="2026-07-01T00:00:00Z",
                            cancel_clock="2026-06-18T00:00:00Z",
                            with_addon=False):
    """ACTIVE line carrying one ACTIVE EIP (retail 99900, down 9900 -> remaining
    90000) on an OPEN 30-day cycle, clock advanced to cancel_clock. Optionally
    attaches one INTL_MONTHLY add-on spanning the cycle.

    Returns (account, plan, line, device, eip, addon_or_None).
    """
    account, plan = setup_account_plan()
    set_clock(cycle_start)
    create_billing_cycle(account["id"], cycle_start, cycle_end)
    device = create_device(retail_price_cents=99900, stock_count=5)
    line = provision_and_activate_line(account["id"], plan["id"])
    eip = create_eip(line["id"], device["id"], term_months=24, down_payment_cents=9900)
    addon = None
    if with_addon:
        addon = get_success_data(api_client.create_addon(
            create_addon_payload(line["id"], "INTL_MONTHLY", cycle_start, cycle_end,
                                 monthly_fee_cents=3000),
            make_subscriber_headers(account["id"])))
    if cancel_clock:
        set_clock(cancel_clock)
    return account, plan, line, device, eip, addon


# ─── Tier 4: number portability ───────────────────────────────────────────

def open_port_request(account_id, line_id, direction="PORT_IN",
                      external_number="12025550100", account_pin="1234",
                      donor_carrier="OtherCo"):
    """Open a REQUESTED port request (Subscriber on their own line).
    Returns the port-request dict."""
    return get_success_data(api_client.create_port_request(
        create_port_request_payload(line_id, direction=direction,
                                    external_number=external_number,
                                    donor_carrier=donor_carrier,
                                    account_pin=account_pin),
        make_subscriber_headers(account_id)))


def complete_port_in(account_id, line_id, external_number="12025550100",
                     account_pin="1234"):
    """Open -> validate -> complete a PORT_IN. Returns (line, port_request).
    After this the line holds external_number as its phone_number."""
    pr = open_port_request(account_id, line_id, direction="PORT_IN",
                           external_number=external_number, account_pin=account_pin)
    get_success_data(api_client.validate_port_request(pr["id"], {"account_pin": account_pin}, PO))
    pr = get_success_data(api_client.complete_port_request(pr["id"], PO))
    line = get_success_data(api_client.get_line(line_id, CA))
    return line, pr


def setup_completed_portin_line(external_number="12025550111", account_pin="9999"):
    """ACTIVE line with a COMPLETED PORT_IN holding external_number.
    Returns (account, plan, line, port_request)."""
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    line, pr = complete_port_in(account["id"], line["id"],
                                external_number=external_number, account_pin=account_pin)
    return account, plan, line, pr


def setup_validated_portout(account_id, line_id, external_number="12025550199",
                            account_pin="1234"):
    """Open -> validate a PORT_OUT on an existing ACTIVE line. Returns the
    VALIDATED port-request dict."""
    pr = open_port_request(account_id, line_id, direction="PORT_OUT",
                           external_number=external_number, account_pin=account_pin)
    return get_success_data(api_client.validate_port_request(
        pr["id"], {"account_pin": account_pin}, PO))


# ─── Tier 5: usage ────────────────────────────────────────────────────────

def ingest_data_usage(line_id, data_mb, occurred_at):
    """Ingest one DATA usage record. Returns the usage record dict."""
    return get_success_data(api_client.create_usage_record(
        create_usage_record_payload(line_id, usage_type="DATA",
                                    data_mb=data_mb, occurred_at=occurred_at), CA))
