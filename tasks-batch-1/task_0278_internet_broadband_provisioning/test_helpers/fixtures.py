"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test). These helpers build preconditions from scratch using only
PRD-declared endpoints, returning dicts of the entities tests assert against.

All setup calls use get_success_data() (lenient) so a setup failure surfaces a
clear "Setup failed" error rather than a confusing assertion deep in a test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, build_customer_headers
from . import factories as F


AGENT = TEST_USERS["provisioning_agent_headers"]
NETOPS = TEST_USERS["network_ops_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]

CYCLE_START = "2026-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Clock + reference catalogs
# ---------------------------------------------------------------------------
def set_clock(iso, headers=NETOPS):
    return get_success_data(api_client.set_clock(iso, headers))


def create_address(headers=AGENT, **overrides):
    return get_success_data(
        api_client.create_service_address(F.create_service_address_payload(**overrides), headers)
    )


def create_plan(headers=AGENT, **overrides):
    return get_success_data(
        api_client.create_service_plan(F.create_service_plan_payload(**overrides), headers)
    )


def create_equipment(headers=AGENT, **overrides):
    return get_success_data(
        api_client.create_equipment_unit(F.create_equipment_unit_payload(**overrides), headers)
    )


def create_technician(headers=DISPATCH, **overrides):
    return get_success_data(
        api_client.create_technician(F.create_technician_payload(**overrides), headers)
    )


def create_slot(technician_id, headers=DISPATCH, **overrides):
    return get_success_data(
        api_client.create_install_slot(
            F.create_install_slot_payload(technician_id, **overrides), headers)
    )


def create_account(address_id, plan_id, customer_user_id="cust-test",
                   headers=AGENT, **overrides):
    return get_success_data(
        api_client.create_account(
            F.create_account_payload(address_id, plan_id, customer_user_id, **overrides), headers)
    )


def create_order(account_id, plan_id, order_type="NEW_INSTALL",
                 install_mode="SELF_INSTALL", headers=AGENT, **overrides):
    return get_success_data(
        api_client.create_service_order(
            F.create_service_order_payload(account_id, plan_id, order_type,
                                           install_mode, **overrides), headers)
    )


def get_open_cycle(account_id, headers=NETOPS):
    """Return the (single) OPEN billing cycle for an account after activation."""
    data, _meta = _list(api_client.list_billing_cycles(headers, params={"account_id": account_id}))
    open_cycles = [c for c in data if c["billing_state"] == "OPEN"]
    assert open_cycles, f"expected an OPEN billing cycle for account {account_id}, got {data}"
    return open_cycles[0]


def _list(response):
    """Unwrap a paginated list response into (data_list, meta)."""
    body = response.json() if hasattr(response, "json") else response
    data = body["data"]
    meta = body.get("meta", {})
    return data, meta


def list_account_credits(account_id, headers=AGENT):
    data, _meta = _list(api_client.list_account_credits(headers, params={"account_id": account_id}))
    return data


def get_account_version(account_id, headers=AGENT):
    acct = get_success_data(api_client.get_account(account_id, headers))
    return acct["version"]


# ---------------------------------------------------------------------------
# Tier 1/2/3: Activated accounts (the workhorse precondition)
# ---------------------------------------------------------------------------
def setup_active_self_install_account(clock=CYCLE_START, customer_user_id="cust-test",
                                      address_overrides=None, plan_overrides=None,
                                      equipment_overrides=None):
    """Activate a SELF_INSTALL account from empty DB.

    Sequence: set clock -> address -> plan -> equipment -> account -> order ->
    ship-kit -> activate. Leaves the account ACTIVE with a leased unit and one
    OPEN billing cycle.

    Returns dict: address, plan, equipment, account, order, cycle.
    """
    set_clock(clock)
    addr = create_address(**(address_overrides or {}))
    plan = create_plan(**(plan_overrides or {}))
    unit = create_equipment(**(equipment_overrides or {}))
    acct = create_account(addr["id"], plan["id"], customer_user_id)
    order = create_order(acct["id"], plan["id"], install_mode="SELF_INSTALL")
    get_success_data(api_client.ship_kit(order["id"], AGENT))
    get_success_data(api_client.activate_order(order["id"], AGENT))
    cycle = get_open_cycle(acct["id"])
    acct = get_success_data(api_client.get_account(acct["id"], AGENT))
    unit = get_success_data(api_client.get_equipment_unit(unit["id"], AGENT))
    order = get_success_data(api_client.get_service_order(order["id"], AGENT))
    return {"address": addr, "plan": plan, "equipment": unit, "account": acct,
            "order": order, "cycle": cycle}


def setup_active_tech_install_account(clock=CYCLE_START, customer_user_id="cust-test",
                                      address_overrides=None, plan_overrides=None,
                                      slot_capacity=2, customer_headers=False):
    """Activate a TECH_INSTALL account from empty DB through a completed appointment.

    Sequence: clock -> address -> plan -> equipment -> technician -> slot ->
    account -> order(TECH_INSTALL) -> book appointment -> complete -> activate.

    Returns dict: address, plan, equipment, technician, slot, account, order,
    appointment, cycle.
    """
    set_clock(clock)
    addr = create_address(self_install_eligible=False, **(address_overrides or {}))
    plan = create_plan(**(plan_overrides or {}))
    unit = create_equipment()
    tech = create_technician()
    slot = create_slot(tech["id"], capacity=slot_capacity)
    acct_headers = build_customer_headers(customer_user_id) if customer_headers else AGENT
    acct = create_account(addr["id"], plan["id"], customer_user_id, headers=acct_headers)
    order = create_order(acct["id"], plan["id"], install_mode="TECH_INSTALL",
                         headers=acct_headers)
    appt = get_success_data(api_client.create_install_appointment(
        F.create_install_appointment_payload(order["id"], slot["id"], acct["version"]),
        acct_headers))
    get_success_data(api_client.complete_appointment(appt["id"], AGENT))
    get_success_data(api_client.activate_order(order["id"], AGENT))
    cycle = get_open_cycle(acct["id"])
    acct = get_success_data(api_client.get_account(acct["id"], AGENT))
    order = get_success_data(api_client.get_service_order(order["id"], AGENT))
    return {"address": addr, "plan": plan, "equipment": unit, "technician": tech,
            "slot": slot, "account": acct, "order": order, "appointment": appt,
            "cycle": cycle}


def setup_draft_tech_install_order(clock=CYCLE_START, address_overrides=None,
                                   plan_overrides=None, slot_overrides=None,
                                   slot_capacity=2):
    """Empty DB -> a DRAFT TECH_INSTALL order plus an OPEN slot, ready to book.

    Returns dict: address, plan, technician, slot, account, order.
    """
    set_clock(clock)
    addr = create_address(self_install_eligible=False, **(address_overrides or {}))
    plan = create_plan(**(plan_overrides or {}))
    tech = create_technician()
    slot = create_slot(tech["id"], capacity=slot_capacity, **(slot_overrides or {}))
    acct = create_account(addr["id"], plan["id"], "cust-draft")
    order = create_order(acct["id"], plan["id"], install_mode="TECH_INSTALL")
    acct = get_success_data(api_client.get_account(acct["id"], AGENT))
    return {"address": addr, "plan": plan, "technician": tech, "slot": slot,
            "account": acct, "order": order}


def setup_draft_self_install_order(clock=CYCLE_START, address_overrides=None,
                                   plan_overrides=None, with_equipment=True):
    """Empty DB -> a DRAFT SELF_INSTALL order (kit not yet shipped).

    Returns dict: address, plan, equipment (or None), account, order.
    """
    set_clock(clock)
    addr = create_address(**(address_overrides or {}))
    plan = create_plan(**(plan_overrides or {}))
    unit = create_equipment() if with_equipment else None
    acct = create_account(addr["id"], plan["id"], "cust-draft-si")
    order = create_order(acct["id"], plan["id"], install_mode="SELF_INSTALL")
    return {"address": addr, "plan": plan, "equipment": unit, "account": acct,
            "order": order}


# ---------------------------------------------------------------------------
# Tier 4: Metering / cycle state targeting
# ---------------------------------------------------------------------------
def setup_active_account_with_usage(gb, clock=CYCLE_START, plan_overrides=None,
                                    posted_at_iso="2026-06-10T00:00:00Z"):
    """Activate a SELF_INSTALL account and post a single usage record of `gb`.

    Returns the dict from setup_active_self_install_account plus a refreshed
    cycle reflecting the posted usage.
    """
    ctx = setup_active_self_install_account(clock=clock, plan_overrides=plan_overrides)
    get_success_data(api_client.create_usage_record(
        F.create_usage_record_payload(ctx["account"]["id"], ctx["cycle"]["id"], gb,
                                      posted_at_iso=posted_at_iso), NETOPS))
    ctx["cycle"] = get_success_data(api_client.get_billing_cycle(ctx["cycle"]["id"], NETOPS))
    return ctx


def setup_resolved_outage(duration_minutes, clock=CYCLE_START,
                          started_at_iso="2026-06-05T00:00:00Z", plan_overrides=None):
    """Activate an account and create one RESOLVED outage of `duration_minutes`.

    Returns the activation ctx plus `outage` (the RESOLVED outage event).
    """
    ctx = setup_active_self_install_account(clock=clock, plan_overrides=plan_overrides)
    outage = get_success_data(api_client.create_outage_event(
        F.create_outage_event_payload(ctx["account"]["id"], ctx["cycle"]["id"],
                                      started_at_iso=started_at_iso), NETOPS))
    # ended = start + duration_minutes
    end_iso = _add_minutes(started_at_iso, duration_minutes)
    outage = get_success_data(api_client.resolve_outage(
        outage["id"], {"ended_at_iso": end_iso}, NETOPS))
    ctx["outage"] = outage
    return ctx


def _add_minutes(iso, minutes):
    from datetime import datetime, timedelta, timezone
    dt = datetime.strptime(iso.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
    dt = dt + timedelta(minutes=minutes)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Tier 5: Terminal-state / cascade setups
# ---------------------------------------------------------------------------
def setup_disconnected_account(clock=CYCLE_START, disconnect_clock=None,
                               plan_overrides=None):
    """Activate a SELF_INSTALL account, then disconnect it (OCC-correct version).

    Optionally advances the clock to `disconnect_clock` before disconnecting so
    lease/ETF proration land on a chosen day.

    Returns the activation ctx plus `disconnect` (the disconnected account body).
    """
    ctx = setup_active_self_install_account(clock=clock, plan_overrides=plan_overrides)
    if disconnect_clock:
        set_clock(disconnect_clock)
    v = get_account_version(ctx["account"]["id"])
    ctx["version_before_disconnect"] = v
    disc = get_success_data(api_client.disconnect_account(
        ctx["account"]["id"], {"expected_account_version": v}, AGENT))
    ctx["disconnect"] = disc
    return ctx


def setup_approved_transfer(clock=CYCLE_START, waive_etf=True, plan_overrides=None):
    """Activate a SELF_INSTALL account and approve a transfer back to its own address.

    Returns the activation ctx plus `transfer` (the APPROVED transfer request).
    """
    ctx = setup_active_self_install_account(clock=clock, plan_overrides=plan_overrides)
    xfer = get_success_data(api_client.create_transfer_request(
        F.create_transfer_request_payload(ctx["account"]["id"], ctx["address"]["id"],
                                          ctx["plan"]["id"], waive_etf=waive_etf), AGENT))
    xfer = get_success_data(api_client.approve_transfer(xfer["id"], AGENT))
    ctx["transfer"] = xfer
    return ctx
