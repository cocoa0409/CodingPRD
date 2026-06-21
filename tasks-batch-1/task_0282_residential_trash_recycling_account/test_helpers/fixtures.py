"""Composite setup helpers.

Each test runs against a freshly-launched empty server, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Setup steps use
get_success_data() so a broken precondition surfaces as a clear "Setup failed".
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_account_holder_headers
from .factories import (
    create_service_plan_payload,
    create_collection_zone_payload,
    create_account_payload,
    create_cart_payload,
    create_extra_pickup_payload,
    report_event_payload,
    generate_invoice_payload,
)

DISP = TEST_USERS["dispatcher_headers"]
CREW = TEST_USERS["crew_lead_headers"]

# A spread of distinct addresses so concurrently-reused fixtures inside one test
# (rare, since each test owns its DB) never collide on address uniqueness.
_ADDR_SEQ = {"n": 0}


def _next_address(prefix="Oak St"):
    _ADDR_SEQ["n"] += 1
    return f"{_ADDR_SEQ['n']} {prefix}"


# --------------------------------------------------------------------------
# Tier 1 / 2: reference data + account scaffolding
# --------------------------------------------------------------------------
def create_plan(plan_overrides=None):
    payload = create_service_plan_payload(**(plan_overrides or {}))
    return get_success_data(api_client.create_service_plan(payload, DISP))


def create_zone(zone_overrides=None):
    payload = create_collection_zone_payload(**(zone_overrides or {}))
    return get_success_data(api_client.create_collection_zone(payload, DISP))


def set_clock(iso: str):
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, DISP))


def create_account(plan_id, zone_id, address=None, **acct_overrides):
    address = address or _next_address()
    payload = create_account_payload(plan_id, zone_id, service_address=address, **acct_overrides)
    return get_success_data(api_client.create_account(payload, DISP))


def add_standard_carts(account_id, trash_size=65, recycling_size=65):
    """Add the one TRASH + one RECYCLING cart needed for activation."""
    get_success_data(api_client.create_cart(
        account_id, create_cart_payload("TRASH", trash_size), DISP))
    get_success_data(api_client.create_cart(
        account_id, create_cart_payload("RECYCLING", recycling_size), DISP))


def create_active_account(plan_overrides=None, zone_overrides=None, address=None,
                          clock=None, account_overrides=None):
    """Plan + zone + account + one TRASH + one RECYCLING cart + activate-start.

    Returns (plan, zone, account_after_activate). The most common scaffold.
    """
    plan = create_plan(plan_overrides)
    zone = create_zone(zone_overrides)
    if clock:
        set_clock(clock)
    acct = create_account(plan["id"], zone["id"], address=address, **(account_overrides or {}))
    add_standard_carts(acct["id"])
    activated = get_success_data(api_client.activate_start(acct["id"], DISP))
    return plan, zone, activated


def get_account(account_id):
    return get_success_data(api_client.get_account(account_id, DISP))


def account_version(account_id):
    return get_account(account_id)["version"]


# --------------------------------------------------------------------------
# Tier 1: pickup-schedule helpers
# --------------------------------------------------------------------------
def list_schedules(account_id, stream=None, status=None):
    """Schedules ordered by (service_date ASC, TRASH before RECYCLING same date)."""
    params = {}
    if stream is not None:
        params["stream"] = stream
    if status is not None:
        params["status"] = status
    data, _ = _paged(api_client.list_pickup_schedules(account_id, DISP, params or None))
    return data


def _paged(resp):
    body = get_success_data(resp)
    # get_success_data returns the data payload (list for array responses)
    raw = resp.json()
    return body, raw.get("meta", {})


def first_schedule(account_id, stream):
    rows = list_schedules(account_id, stream=stream)
    assert rows, f"Setup failed: no {stream} schedules generated for account {account_id}"
    return rows[0]


def report(schedule_id, outcome, reported_at, crew=None):
    return get_success_data(api_client.report_event(
        schedule_id, report_event_payload(outcome, reported_at), crew or CREW))


# --------------------------------------------------------------------------
# Tier 4: accumulation / threshold-targeting fixtures
# --------------------------------------------------------------------------
def setup_account_with_missed_trash_credit(clock="2026-03-02T00:00:00Z",
                                           plan_overrides=None, address=None):
    """Active account, first TRASH schedule reported MISSED -> one ISSUED 300 credit.

    Returns dict: plan, zone, account, schedule, event, credit.
    """
    plan, zone, acct = create_active_account(
        plan_overrides=plan_overrides, address=address, clock=clock)
    sched = first_schedule(acct["id"], "TRASH")
    event = report(sched["id"], "MISSED", sched["effective_pickup_date"])
    credits, _ = _paged(api_client.list_account_credits(acct["id"], DISP))
    assert credits, "Setup failed: MISSED event did not issue a credit"
    return {
        "plan": plan, "zone": zone, "account": acct,
        "schedule": sched, "event": event, "credit": credits[0],
    }


def setup_account_with_scheduled_extra_pickup(requested_date, bulk_item_count,
                                              clock=None, plan_overrides=None, address=None):
    """Active account + one extra pickup advanced REQUESTED -> SCHEDULED.

    Returns dict: plan, zone, account, request (post-schedule).
    """
    plan, zone, acct = create_active_account(
        plan_overrides=plan_overrides, address=address, clock=clock)
    holder = make_account_holder_headers(acct["id"])
    req = get_success_data(api_client.create_extra_pickup(
        acct["id"], create_extra_pickup_payload(requested_date, bulk_item_count), holder))
    scheduled = get_success_data(api_client.schedule_extra_pickup(req["id"], DISP))
    return {"plan": plan, "zone": zone, "account": acct, "request": scheduled}


def setup_account_with_requested_extra_pickup(requested_date, bulk_item_count,
                                              clock=None, plan_overrides=None, address=None):
    """Active account + one REQUESTED (not yet scheduled) extra pickup."""
    plan, zone, acct = create_active_account(
        plan_overrides=plan_overrides, address=address, clock=clock)
    holder = make_account_holder_headers(acct["id"])
    req = get_success_data(api_client.create_extra_pickup(
        acct["id"], create_extra_pickup_payload(requested_date, bulk_item_count), holder))
    return {"plan": plan, "zone": zone, "account": acct, "request": req}


def setup_account_with_open_invoice(period_start="2026-03-01T00:00:00Z",
                                    period_end="2026-04-01T00:00:00Z",
                                    due_date="2026-04-15T00:00:00Z",
                                    clock=None, plan_overrides=None, address=None):
    """Active account + one freshly-generated OPEN invoice (base only).

    Returns dict: plan, zone, account, invoice.
    """
    plan, zone, acct = create_active_account(
        plan_overrides=plan_overrides, address=address, clock=clock)
    v = account_version(acct["id"])
    inv = get_success_data(api_client.generate_invoice(
        acct["id"], generate_invoice_payload(v, period_start, period_end, due_date), DISP))
    return {"plan": plan, "zone": zone, "account": acct, "invoice": inv}


def setup_account_with_n_contamination_notices(n, clock="2026-03-02T00:00:00Z",
                                               last_severity="MINOR",
                                               plan_overrides=None, address=None):
    """Active account with the first `n` RECYCLING schedules reported CONTAMINATED.

    The first notice is a free warning (fee 0); subsequent ones are charged. The
    final notice's severity is `last_severity`. Returns dict: plan, zone, account,
    notices (list, in creation order), events (list).
    """
    plan, zone, acct = create_active_account(
        plan_overrides=plan_overrides, address=address, clock=clock)
    rec = list_schedules(acct["id"], stream="RECYCLING")
    assert len(rec) >= n, f"Setup failed: need {n} RECYCLING schedules, got {len(rec)}"
    events = []
    for i in range(n):
        sev = last_severity if i == n - 1 else "MINOR"
        ev = get_success_data(api_client.report_event(
            rec[i]["id"],
            {"outcome": "CONTAMINATED", "reported_at": rec[i]["effective_pickup_date"],
             "severity": sev},
            CREW))
        events.append(ev)
    notices, _ = _paged(api_client.list_account_contamination_notices(acct["id"], DISP))
    return {"plan": plan, "zone": zone, "account": acct,
            "notices": notices, "events": events}


def generate_invoice(account_id, period_start="2026-03-01T00:00:00Z",
                     period_end="2026-04-01T00:00:00Z",
                     due_date="2026-04-15T00:00:00Z", expected_version=None):
    v = expected_version if expected_version is not None else account_version(account_id)
    return get_success_data(api_client.generate_invoice(
        account_id, generate_invoice_payload(v, period_start, period_end, due_date), DISP))
