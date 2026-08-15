"""Composite setup helpers for multi-step test prerequisites.

The runner restarts the API server before every test, so every helper builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls
use get_success_data() so failures surface as clear "Setup step failed" errors.

Clock discipline: the logical clock starts at 2026-08-01T00:00:00Z (PRD §2.4),
which is AFTER the standard 2026-03-02 placement date used by most scenarios.
Any helper that schedules a group therefore rewinds the clock first, matching
the PRD's placement-date-not-in-the-past gate (§3.2).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_GROUP
from .factories import (
    create_barn_payload,
    create_barn_wash_payload,
    create_contract_payload,
    create_feed_order_payload,
    create_grower_payload,
    create_manure_application_payload,
    create_manure_plan_payload,
    create_market_load_payload,
    create_mortality_report_payload,
    create_packer_slot_payload,
    create_pig_group_payload,
    create_site_payload,
    create_truck_wash_payload,
    deliver_feed_order_payload,
    deliver_load_payload,
    dispatch_load_payload,
    quote_ticket_payload,
    schedule_feed_order_payload,
    create_maintenance_ticket_payload,
)
from .test_users import (
    TEST_USERS,
    make_grower_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN2 = TEST_USERS["admin2_headers"]
FIELDTECH = TEST_USERS["fieldtech_headers"]
FIELDTECH2 = TEST_USERS["fieldtech2_headers"]
FEEDMILL = TEST_USERS["feedmill_headers"]
TRANSPORT = TEST_USERS["transport_headers"]
ENVMGR = TEST_USERS["envmgr_headers"]

CLOCK_BEFORE_PLACEMENT = "2026-02-15T00:00:00Z"
CLOCK_PLACEMENT_DAY = "2026-03-02T00:00:00Z"


# ─── Tier 0: atomic creations ─────────────────────────

def set_clock(to_iso8601: str):
    """Advance or rewind the logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_site(**overrides):
    return get_success_data(
        api_client.create_site(create_site_payload(**overrides), ADMIN), 201
    )


def create_grower(grower_code="G-1", **overrides):
    overrides.setdefault("grower_code", grower_code)
    return get_success_data(
        api_client.create_grower(create_grower_payload(**overrides), ADMIN), 201
    )


def create_active_contract(grower_id, site_id, **overrides):
    contract = get_success_data(
        api_client.create_contract(
            create_contract_payload(grower_id, site_id, **overrides), ADMIN
        ),
        201,
    )
    return get_success_data(api_client.activate_contract(contract["id"], ADMIN))


def create_barn(site_id, barn_code="B1", **overrides):
    overrides.setdefault("barn_code", barn_code)
    return get_success_data(
        api_client.create_barn(create_barn_payload(site_id, **overrides), ADMIN), 201
    )


# ─── Tier 1/2: contract + barn hierarchy ──────────────

def setup_site_grower_contract(**contract_overrides):
    """Site + Grower + Contract activated (ACTIVE). Returns context dict."""
    site = create_site()
    grower = create_grower()
    contract = create_active_contract(grower["id"], site["id"], **contract_overrides)
    return {"site": site, "grower": grower, "contract": contract}


def setup_contract_with_barn(barn_code="B1", barn_overrides=None,
                             contract_overrides=None):
    """ACTIVE contract plus one barn on its site. Returns context dict."""
    ctx = setup_site_grower_contract(**(contract_overrides or {}))
    barn = create_barn(ctx["site"]["id"], barn_code=barn_code, **(barn_overrides or {}))
    ctx["barn"] = barn
    return ctx


# ─── Tier 3: pig group lifecycle ──────────────────────

def create_scheduled_group(barn_id, contract_id, clock=CLOCK_BEFORE_PLACEMENT,
                           **group_overrides):
    """Set the clock, read the fresh barn version, schedule a group (SCHEDULED).

    The barn's version is re-read at call time so the OCC field
    expected_barn_version always matches (PRD §2.7).
    """
    set_clock(clock)
    barn = get_success_data(api_client.get_barn(barn_id, ADMIN))
    payload = create_pig_group_payload(
        barn_id, contract_id, barn["version"], **group_overrides
    )
    return get_success_data(api_client.create_pig_group(payload, FIELDTECH), 201)


def confirm_group(group_id, clock=CLOCK_PLACEMENT_DAY, **confirm_overrides):
    """Set the clock to placement day and confirm (SCHEDULED -> PLACED)."""
    set_clock(clock)
    return get_success_data(
        api_client.confirm_placement(group_id, confirm_overrides, FIELDTECH)
    )


def setup_placed_group(head_placed=DEFAULT_GROUP["head_placed"], barn_code="B1",
                       barn_overrides=None, contract_overrides=None,
                       confirm_clock=None, **group_overrides):
    """Full chain: site/grower/contract ACTIVE + barn + group PLACED.

    Returns context dict with keys: site, grower, contract, barn, group.
    Confirmation runs at the placement date (confirm clock must have reached
    placement_date, PRD §3.2) unless confirm_clock overrides it.
    """
    ctx = setup_contract_with_barn(
        barn_code=barn_code, barn_overrides=barn_overrides,
        contract_overrides=contract_overrides,
    )
    group = create_scheduled_group(
        ctx["barn"]["id"], ctx["contract"]["id"], head_placed=head_placed,
        **group_overrides,
    )
    if confirm_clock is None:
        placement_date = group_overrides.get(
            "placement_date", DEFAULT_GROUP["placement_date"]
        )
        confirm_clock = f"{placement_date}T00:00:00Z"
    ctx["group"] = confirm_group(group["id"], clock=confirm_clock)
    return ctx


# ─── Feed orders ──────────────────────────────────────

def create_feed_order(group_id, **overrides):
    return get_success_data(
        api_client.create_feed_order(
            create_feed_order_payload(group_id, **overrides), FIELDTECH
        ),
        201,
    )


def schedule_feed(order_id, scheduled_delivery_date="2026-03-05"):
    return get_success_data(
        api_client.schedule_feed_order(
            order_id,
            schedule_feed_order_payload(scheduled_delivery_date=scheduled_delivery_date),
            FEEDMILL,
        )
    )


def deliver_feed(order_id, delivered_lbs):
    return get_success_data(
        api_client.deliver_feed_order(
            order_id, deliver_feed_order_payload(delivered_lbs), FEEDMILL
        )
    )


def create_and_deliver_feed(group_id, quantity_lbs, delivered_lbs=None,
                            req_date="2026-03-05", sched_date="2026-03-05",
                            **order_overrides):
    """Create + schedule + deliver a feed order. Returns the terminal order."""
    order = create_feed_order(
        group_id, quantity_lbs=quantity_lbs, requested_delivery_date=req_date,
        **order_overrides,
    )
    schedule_feed(order["id"], sched_date)
    return deliver_feed(order["id"],
                        quantity_lbs if delivered_lbs is None else delivered_lbs)


# ─── Mortality reports ────────────────────────────────

def report_mortality(group_id, grower_id, report_date, mortality_count,
                     cull_count=0, reason_code="DISEASE", clock=None):
    """File a mortality report as the owning grower (entity-backed identity)."""
    if clock is not None:
        set_clock(clock)
    payload = create_mortality_report_payload(
        report_date=report_date, mortality_count=mortality_count,
        cull_count=cull_count, reason_code=reason_code,
    )
    return get_success_data(
        api_client.create_mortality_report(
            group_id, payload, make_grower_headers(grower_id)
        ),
        201,
    )


# ─── Packer slots / market loads / truck washes ───────

def create_slot(**overrides):
    return get_success_data(
        api_client.create_packer_slot(create_packer_slot_payload(**overrides), ADMIN),
        201,
    )


def get_slot_version(slot_id):
    slot = get_success_data(api_client.get_packer_slot(slot_id, ADMIN))
    return slot["version"]


def book_load(group_id, slot_id, head_count):
    """Book a market load with a freshly read slot version (OCC, PRD §2.7)."""
    payload = create_market_load_payload(
        group_id, slot_id, get_slot_version(slot_id), head_count=head_count
    )
    return get_success_data(api_client.create_market_load(payload, FIELDTECH), 201)


def record_truck_wash(washed_at, truck_code="T-1", wash_type="FULL_DISINFECT",
                      recorder=TRANSPORT):
    return get_success_data(
        api_client.create_truck_wash(
            create_truck_wash_payload(
                truck_code=truck_code, washed_at=washed_at, wash_type=wash_type
            ),
            recorder,
        ),
        201,
    )


def verify_truck_wash(wash_id, admin=ADMIN):
    return get_success_data(api_client.verify_truck_wash(wash_id, admin))


def create_verified_truck_wash(washed_at, truck_code="T-1", wash_type="FULL_DISINFECT"):
    """Record (TransportCoordinator) + verify (IntegratorAdmin, distinct id)."""
    wash = record_truck_wash(washed_at, truck_code=truck_code, wash_type=wash_type)
    return verify_truck_wash(wash["id"])


def dispatch_load(load_id, wash_id):
    return get_success_data(
        api_client.dispatch_market_load(
            load_id, dispatch_load_payload(wash_id), TRANSPORT
        )
    )


def deliver_load(load_id, live_weight_lbs_total):
    return get_success_data(
        api_client.deliver_market_load(
            load_id, deliver_load_payload(live_weight_lbs_total), TRANSPORT
        )
    )


def setup_dispatched_load(group_id, slot_date="2026-07-13", head_count=100,
                          slot_overrides=None, washed_at="2026-07-12T08:00:00Z",
                          dispatch_clock="2026-07-12T08:00:00Z"):
    """Book a load, record+verify a fresh wash, dispatch it.

    Returns (slot, load, wash). Leaves the clock at dispatch_clock.
    """
    slot = create_slot(slot_date=slot_date, **(slot_overrides or {}))
    load = book_load(group_id, slot["id"], head_count)
    set_clock(dispatch_clock)
    wash = create_verified_truck_wash(washed_at)
    dispatch_load(load["id"], wash["id"])
    return slot, load, wash


# ─── Settlements ──────────────────────────────────────

def get_settlement_for_group(group_id):
    """Fetch the group's single settlement via the filtered list endpoint."""
    resp = api_client.list_settlements(ADMIN, params={"group_id": group_id})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, (
        f"expected exactly one settlement for group {group_id}, "
        f"got {meta['total_count']}"
    )
    return data[0]


def setup_closed_group_with_settlement(head_placed=100, live_weight_lbs_total=28000,
                                       feed_lbs=None, slot_date="2026-07-13",
                                       slot_overrides=None,
                                       deliver_clock="2026-07-13T00:00:00Z",
                                       **group_overrides):
    """Full lifecycle through a natural close: one load delivers the entire
    group, head_current hits zero, the settlement is minted FINALIZED.

    Returns context dict: site, grower, contract, barn, group, load, settlement.
    """
    ctx = setup_placed_group(head_placed=head_placed, **group_overrides)
    if feed_lbs:
        create_and_deliver_feed(ctx["group"]["id"], feed_lbs)
    slot, load, _wash = setup_dispatched_load(
        ctx["group"]["id"], slot_date=slot_date, head_count=head_placed,
        slot_overrides=slot_overrides,
    )
    set_clock(deliver_clock)
    deliver_load(load["id"], live_weight_lbs_total)
    ctx["slot"] = slot
    ctx["load"] = load
    ctx["group"] = get_success_data(api_client.get_pig_group(ctx["group"]["id"], FIELDTECH))
    ctx["settlement"] = get_settlement_for_group(ctx["group"]["id"])
    return ctx


def setup_paid_settlement(**kwargs):
    """Full lifecycle through PAID: approve (adm_1) then pay (adm_2)."""
    ctx = setup_closed_group_with_settlement(**kwargs)
    settlement_id = ctx["settlement"]["id"]
    get_success_data(api_client.approve_settlement(settlement_id, ADMIN))
    get_success_data(api_client.pay_settlement(settlement_id, ADMIN2))
    ctx["settlement"] = get_success_data(api_client.get_settlement(settlement_id, ADMIN))
    return ctx


# ─── Barn wash / downtime cycle ───────────────────────

def record_barn_wash(barn_id, grower_id, completed_at, wash_type="FULL_DISINFECT",
                     clock=None):
    """Record a barn wash as the owning grower (entity-backed identity)."""
    if clock is not None:
        set_clock(clock)
    return get_success_data(
        api_client.create_barn_wash(
            create_barn_wash_payload(
                barn_id, wash_type=wash_type, completed_at=completed_at
            ),
            make_grower_headers(grower_id),
        ),
        201,
    )


def wash_barn_to_downtime(barn_id, grower_id, completed_at, clock=None):
    """Record + verify a FULL_DISINFECT barn wash: barn WASH_REQUIRED ->
    WASHING -> DOWNTIME. Returns the verified wash."""
    wash = record_barn_wash(barn_id, grower_id, completed_at, clock=clock)
    return get_success_data(api_client.verify_barn_wash(wash["id"], ADMIN))


# ─── Manure planning ──────────────────────────────────

def setup_manure_plan(**plan_overrides):
    """Site + DRAFT manure plan. Returns (site, plan)."""
    site = create_site()
    plan = get_success_data(
        api_client.create_manure_plan(
            create_manure_plan_payload(site["id"], **plan_overrides), ENVMGR
        ),
        201,
    )
    return site, plan


def setup_approved_manure_plan(**plan_overrides):
    """Site + plan walked DRAFT -> SUBMITTED -> APPROVED."""
    site, plan = setup_manure_plan(**plan_overrides)
    get_success_data(api_client.submit_manure_plan(plan["id"], ENVMGR))
    get_success_data(api_client.approve_manure_plan(plan["id"], ADMIN))
    return site, get_success_data(api_client.get_manure_plan(plan["id"], ENVMGR))


def record_application(plan_id, **overrides):
    return get_success_data(
        api_client.create_manure_application(
            create_manure_application_payload(plan_id, **overrides), ENVMGR
        ),
        201,
    )


# ─── Maintenance tickets ──────────────────────────────

def create_ticket(barn_id, grower_id, category="EQUIPMENT", description="repair"):
    """Open a ticket as the owning grower (entity-backed identity)."""
    return get_success_data(
        api_client.create_maintenance_ticket(
            create_maintenance_ticket_payload(
                barn_id, category=category, description=description
            ),
            make_grower_headers(grower_id),
        ),
        201,
    )


def quote_ticket(ticket_id, cost_cents=30000, cause="WEAR", quoter=FIELDTECH):
    return get_success_data(
        api_client.quote_maintenance_ticket(
            ticket_id,
            quote_ticket_payload(cost_cents=cost_cents, cause=cause),
            quoter,
        )
    )


def create_quoted_ticket(barn_id, grower_id, cost_cents=30000, cause="WEAR",
                         category="EQUIPMENT", quoter=FIELDTECH):
    """OPEN -> QUOTED with cost and cause recorded."""
    ticket = create_ticket(barn_id, grower_id, category=category)
    return quote_ticket(ticket["id"], cost_cents=cost_cents, cause=cause,
                        quoter=quoter)


def approve_ticket(ticket_id, approver=FIELDTECH2):
    return get_success_data(
        api_client.approve_maintenance_ticket(ticket_id, approver)
    )


def get_group(group_id, headers=FIELDTECH):
    return get_success_data(api_client.get_pig_group(group_id, headers))


def get_barn(barn_id):
    return get_success_data(api_client.get_barn(barn_id, ADMIN))


def get_grower(grower_id):
    return get_success_data(api_client.get_grower(grower_id, ADMIN))


def get_plan(plan_id):
    return get_success_data(api_client.get_manure_plan(plan_id, ENVMGR))


def get_settlement(settlement_id):
    return get_success_data(api_client.get_settlement(settlement_id, ADMIN))


def get_ticket(ticket_id):
    return get_success_data(api_client.get_maintenance_ticket(ticket_id, ADMIN))
