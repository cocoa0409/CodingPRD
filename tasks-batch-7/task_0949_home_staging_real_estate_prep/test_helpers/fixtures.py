"""Composite setup helpers.

Every fixture builds its state from scratch through declared endpoints only:
the harness restarts the server with an empty store before each test, so no
fixture may assume any pre-existing row.

Identity threading: ListingAgent and Seller headers always carry the real
Client row id, BrokerageAdmin headers the real Brokerage row id and VendorRep
headers the real VendorPartner row id.
"""

import re

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    BASE_CLOCK,
    ITEM_BED,
    ITEM_SOFA,
    ITEM_TABLE,
    TIER_ESSENTIAL,
    TIER_LUXE,
    TIER_SIGNATURE,
)
from .test_users import (
    ADMIN,
    CLERK,
    COORD,
    WAREHOUSE,
    make_brokerage_admin_headers,
    make_listing_agent_headers,
    make_seller_headers,
    make_vendor_rep_headers,
)


# ------------------------------------------------------------------ primitives

def set_clock(instant):
    """Reposition the logical clock and return the reported current_utc."""
    return get_success_data(api_client.set_clock(instant, ADMIN))


def new_seller(email="dana@ex.com", full_name="Dana Reyes", **overrides):
    payload = {"client_type": "SELLER", "full_name": full_name, "email": email}
    payload.update(overrides)
    return get_success_data(api_client.create_client(payload, ADMIN))


def new_listing_agent(email="milo@ex.com", full_name="Milo Park",
                      personal_authorization_cap=4500.00, brokerage_id=None, **overrides):
    """A LISTING_AGENT client, standing up its own brokerage when none is supplied.

    PRD §3.1: "A `brokerage_id` is required when the client is a `LISTING_AGENT` or a
    `BROKERAGE_ADMIN` and is null when the client is a `SELLER`." An agent therefore
    cannot exist without a brokerage. The auto-created house sits at the platform hard
    ceiling of 15000.00 so that the agent's own `personal_authorization_cap` is what
    binds: "for a `LISTING_AGENT` it is the smaller of the client's
    `personal_authorization_cap` and the brokerage's `authorization_cap`".
    """
    if brokerage_id is None and "brokerage_id" not in overrides:
        slug = re.sub(r"[^A-Za-z0-9]", "", email).upper()[:16]
        brokerage_id = new_brokerage(
            name=f"House {slug}",
            license_code=f"BR-{slug}",
            billing_email=f"ap-{slug.lower()}@cedar.example",
        )["id"]
    payload = {
        "client_type": "LISTING_AGENT",
        "full_name": full_name,
        "email": email,
        "personal_authorization_cap": personal_authorization_cap,
    }
    if brokerage_id is not None:
        payload["brokerage_id"] = brokerage_id
    payload.update(overrides)
    return get_success_data(api_client.create_client(payload, ADMIN))


def new_brokerage_admin(brokerage_id, email="kit@cedar.example", full_name="Kit Yardley"):
    payload = {
        "client_type": "BROKERAGE_ADMIN",
        "full_name": full_name,
        "email": email,
        "brokerage_id": brokerage_id,
    }
    return get_success_data(api_client.create_client(payload, ADMIN))


def new_brokerage(**overrides):
    payload = {
        "name": "Cedar Realty",
        "license_code": "BR-4410",
        "authorization_cap": 15000.00,
        "tax_exempt": False,
        "billing_email": "ap@cedar.example",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_brokerage(payload, ADMIN))


def new_property(owner_client_id, occupancy="VACANT", distance_miles=22.0, room_count=4,
                 address_line="18 Larch Ct", **overrides):
    payload = {
        "owner_client_id": owner_client_id,
        "address_line": address_line,
        "city": "Bend",
        "state_code": "OR",
        "distance_miles": distance_miles,
        "occupancy": occupancy,
        "room_count": room_count,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_property(payload, COORD))


def new_listing(property_id, agent_id, mls_number="MLS-9001", list_price=749000.00):
    payload = {
        "property_id": property_id,
        "listing_agent_client_id": agent_id,
        "mls_number": mls_number,
        "list_price": list_price,
    }
    return get_success_data(api_client.create_listing(payload, COORD))


def new_tier(profile):
    return get_success_data(api_client.create_package_tier(dict(profile), ADMIN))


def new_vendor(name="Metro Rentals", lead_time_days=7, min_lease_cycles=4,
               cancel_cutoff_days=4, rate_multiplier=1.35):
    payload = {
        "name": name,
        "lead_time_days": lead_time_days,
        "min_lease_cycles": min_lease_cycles,
        "cancel_cutoff_days": cancel_cutoff_days,
        "rate_multiplier": rate_multiplier,
    }
    return get_success_data(api_client.create_vendor(payload, WAREHOUSE))


def new_item(profile, **overrides):
    payload = dict(profile)
    payload.update(overrides)
    return get_success_data(api_client.create_inventory_item(payload, WAREHOUSE))


def deposit_of(project_id):
    """The Deposit row is created as a side effect of authorization; find it by project."""
    data = get_success_data(api_client.list_deposits(CLERK, params={"project_id": project_id}))
    assert data, f"expected a deposit row for project {project_id}"
    return data[0]


def lease_of(project_id):
    """The Lease row is created as a side effect of scheduling the install."""
    data = get_success_data(api_client.list_leases(COORD, params={"project_id": project_id}))
    assert data, f"expected a lease row for project {project_id}"
    return data[0]


def pickup_of(project_id):
    """The Pickup row is auto-created when the lease reaches ENDING."""
    data = get_success_data(api_client.list_pickups(COORD, params={"project_id": project_id}))
    assert data, f"expected a pickup row for project {project_id}"
    return data[0]


def project_version(project_id, headers=None):
    data = get_success_data(api_client.get_project(project_id, headers or WAREHOUSE))
    return data["version"]


def lease_version(lease_id, headers=None):
    data = get_success_data(api_client.get_lease(lease_id, headers or COORD))
    return data["version"]


def pickup_version(pickup_id, headers=None):
    data = get_success_data(api_client.get_pickup(pickup_id, headers or WAREHOUSE))
    return data["version"]


# --------------------------------------------------- tier 1: minimal fixtures

def setup_clock_only():
    """Empty store with the logical clock repositioned to the fixture base instant."""
    set_clock(BASE_CLOCK)
    return {}


def setup_one_owned_item():
    """One AVAILABLE owned SOFA unit in the warehouse."""
    set_clock(BASE_CLOCK)
    item = new_item(ITEM_SOFA)
    return {"item_a": item["id"], "item_a_row": item}


def setup_three_owned_items():
    """Three AVAILABLE owned units: SOFA, BED and TABLE."""
    set_clock(BASE_CLOCK)
    a = new_item(ITEM_SOFA)
    b = new_item(ITEM_BED)
    c = new_item(ITEM_TABLE)
    return {"item_a": a["id"], "item_b": b["id"], "item_c": c["id"]}


def setup_vendor_only():
    """One ACTIVE partner rental house."""
    set_clock(BASE_CLOCK)
    vendor = new_vendor(min_lease_cycles=6)
    return {"vendor_id": vendor["id"], "vendor_row": vendor}


def setup_listing_ready():
    """A seller, a listing agent, a VACANT property and no listing yet."""
    set_clock(BASE_CLOCK)
    seller = new_seller()
    agent = new_listing_agent()
    prop = new_property(seller["id"])
    return {
        "seller_id": seller["id"],
        "agent_id": agent["id"],
        "prop_id": prop["id"],
    }


def setup_listing_active():
    """A seller, a listing agent, a VACANT property, one ACTIVE listing and a
    consultation scheduled a month ahead of the clock."""
    set_clock(BASE_CLOCK)
    tier = new_tier(TIER_SIGNATURE)
    seller = new_seller()
    agent = new_listing_agent()
    prop = new_property(seller["id"])
    listing = new_listing(prop["id"], agent["id"])
    cons = get_success_data(api_client.create_consultation(
        {"property_id": prop["id"], "requested_by_client_id": agent["id"],
         "scheduled_at": "2026-07-01T09:00:00Z"}, COORD))
    return {
        "tier_sig": tier["id"],
        "seller_id": seller["id"],
        "agent_id": agent["id"],
        "prop_id": prop["id"],
        "listing_id": listing["id"],
        "cons_id": cons["id"],
    }


# --------------------------------------------- tier 2: consultations and scope

def setup_consultation_held_one_room():
    """A HELD VACANT consultation carrying a single PACKAGE_ROOM scope item.

    No package tier is declared here, so a project creation attempt against
    this consultation can exercise an unresolvable package_tier_id.
    """
    set_clock(BASE_CLOCK)
    seller = new_seller()
    agent = new_listing_agent()
    prop = new_property(seller["id"])
    listing = new_listing(prop["id"], agent["id"])
    cons = get_success_data(api_client.create_consultation(
        {"property_id": prop["id"], "requested_by_client_id": agent["id"],
         "scheduled_at": BASE_CLOCK}, COORD))
    get_success_data(api_client.hold_consultation(cons["id"], COORD))
    get_success_data(api_client.add_scope_item(
        cons["id"],
        {"room_label": "Living", "action": "PACKAGE_ROOM",
         "requires_rental": True, "accessory_set_count": 1},
        COORD))
    return {
        "seller_id": seller["id"], "agent_id": agent["id"], "prop_id": prop["id"],
        "listing_id": listing["id"], "cons_id": cons["id"],
    }


def setup_consultation_two_scope_items():
    """A HELD VACANT consultation with two PACKAGE_ROOM rooms; SIGNATURE and LUXE declared."""
    set_clock(BASE_CLOCK)
    tier_sig = new_tier(TIER_SIGNATURE)
    tier_luxe = new_tier(TIER_LUXE)
    seller = new_seller()
    agent = new_listing_agent()
    prop = new_property(seller["id"])
    listing = new_listing(prop["id"], agent["id"])
    cons = get_success_data(api_client.create_consultation(
        {"property_id": prop["id"], "requested_by_client_id": agent["id"],
         "scheduled_at": BASE_CLOCK}, COORD))
    get_success_data(api_client.hold_consultation(cons["id"], COORD))
    si_1 = get_success_data(api_client.add_scope_item(
        cons["id"],
        {"room_label": "Living", "action": "PACKAGE_ROOM",
         "requires_rental": True, "accessory_set_count": 1}, COORD))
    si_2 = get_success_data(api_client.add_scope_item(
        cons["id"],
        {"room_label": "Office", "action": "PACKAGE_ROOM",
         "requires_rental": True, "accessory_set_count": 2}, COORD))
    return {
        "tier_sig": tier_sig["id"], "tier_luxe": tier_luxe["id"],
        "seller_id": seller["id"], "agent_id": agent["id"], "prop_id": prop["id"],
        "listing_id": listing["id"], "cons_id": cons["id"],
        "si_1": si_1["id"], "si_2": si_2["id"],
    }


# ------------------------------------------------ tier 3: the vacant-arm chain

CANONICAL_VACANT_ROOMS = [
    ("Living", 1),
    ("Primary Bed", 1),
    ("Dining", 1),
    ("Office", 0),
]


def setup_vacant_project_draft():
    """The canonical four-room VACANT project sitting in DRAFT.

    SIGNATURE base 4200.00, one room over the cap, one accessory set over the
    allowance, 22.0 miles out and three cycles of forward package rent.
    """
    set_clock(BASE_CLOCK)
    tier_sig = new_tier(TIER_SIGNATURE)
    tier_luxe = new_tier(TIER_LUXE)
    brokerage = new_brokerage()
    seller = new_seller()
    agent = new_listing_agent(brokerage_id=brokerage["id"])
    prop = new_property(seller["id"], occupancy="VACANT", distance_miles=22.0, room_count=4)
    listing = new_listing(prop["id"], agent["id"], mls_number="MLS-9001")
    cons = get_success_data(api_client.create_consultation(
        {"property_id": prop["id"], "requested_by_client_id": agent["id"],
         "scheduled_at": BASE_CLOCK}, COORD))
    get_success_data(api_client.hold_consultation(cons["id"], COORD))
    for room_label, accessory_sets in CANONICAL_VACANT_ROOMS:
        get_success_data(api_client.add_scope_item(
            cons["id"],
            {"room_label": room_label, "action": "PACKAGE_ROOM",
             "requires_rental": True, "accessory_set_count": accessory_sets}, COORD))
    get_success_data(api_client.submit_scope(
        cons["id"], {"recommended_tier_code": "SIGNATURE"}, COORD))
    get_success_data(api_client.approve_scope(
        cons["id"], make_listing_agent_headers(agent["id"])))
    project = get_success_data(api_client.create_project(
        {"property_id": prop["id"], "consultation_id": cons["id"],
         "listing_id": listing["id"], "package_tier_id": tier_sig["id"],
         "payer_client_id": seller["id"], "payer_type": "SELLER"}, COORD))
    return {
        "tier_sig": tier_sig["id"], "tier_luxe": tier_luxe["id"], "brk_id": brokerage["id"],
        "seller_id": seller["id"], "agent_id": agent["id"], "prop_id": prop["id"],
        "listing_id": listing["id"], "cons_id": cons["id"], "proj_id": project["id"],
        "project_row": project,
    }


def setup_vacant_project_staged():
    """The canonical VACANT project taken all the way through install completion.

    Adds the collected deposit, a confirmed ten-unit vendor order, three owned
    units, a committed four-line pull, a completed install on 2026-06-10T09:00Z
    and the ACTIVE four-cycle lease that starts with it.
    """
    ctx = setup_vacant_project_draft()
    get_success_data(api_client.authorize_project(
        ctx["proj_id"], make_seller_headers(ctx["seller_id"])))
    deposit = deposit_of(ctx["proj_id"])
    get_success_data(api_client.collect_deposit(deposit["id"], CLERK))
    vendor = new_vendor(min_lease_cycles=6)
    order = get_success_data(api_client.create_rental_order(
        {"project_id": ctx["proj_id"], "vendor_id": vendor["id"], "unit_count": 10}, WAREHOUSE))
    get_success_data(api_client.place_rental_order(order["id"], WAREHOUSE))
    get_success_data(api_client.confirm_rental_order(
        order["id"], make_vendor_rep_headers(vendor["id"])))
    item_a = new_item(ITEM_SOFA)
    item_b = new_item(ITEM_BED)
    item_c = new_item(ITEM_TABLE)
    pull = get_success_data(api_client.open_pull(ctx["proj_id"], WAREHOUSE))
    line_a = get_success_data(api_client.add_pull_line(
        pull["id"], {"source": "OWNED", "category": "SOFA",
                     "room_label": "Living", "quantity": 1}, WAREHOUSE))
    line_b = get_success_data(api_client.add_pull_line(
        pull["id"], {"source": "OWNED", "category": "BED",
                     "room_label": "Primary Bed", "quantity": 1}, WAREHOUSE))
    line_c = get_success_data(api_client.add_pull_line(
        pull["id"], {"source": "OWNED", "category": "TABLE",
                     "room_label": "Dining", "quantity": 1}, WAREHOUSE))
    line_v = get_success_data(api_client.add_pull_line(
        pull["id"], {"source": "VENDOR", "category": "CHAIR", "room_label": "Office",
                     "quantity": 10, "rental_order_id": order["id"]}, WAREHOUSE))
    get_success_data(api_client.submit_pull(pull["id"], WAREHOUSE))
    get_success_data(api_client.commit_pull(
        pull["id"], project_version(ctx["proj_id"]), WAREHOUSE))
    install = get_success_data(api_client.schedule_install(
        ctx["proj_id"],
        {"scheduled_at": "2026-06-10T09:00:00Z", "crew_size": 3, "initial_cycles": 4}, COORD))
    set_clock("2026-06-10T09:00:00Z")
    get_success_data(api_client.start_install(install["id"], COORD))
    get_success_data(api_client.complete_install(install["id"], COORD))
    lease = lease_of(ctx["proj_id"])
    ctx.update({
        "dep_id": deposit["id"], "vendor_id": vendor["id"], "ro_id": order["id"],
        "item_a": item_a["id"], "item_b": item_b["id"], "item_c": item_c["id"],
        "pull_id": pull["id"], "line_a": line_a["id"], "line_b": line_b["id"],
        "line_c": line_c["id"], "line_v": line_v["id"],
        "install_id": install["id"], "lease_id": lease["id"],
    })
    return ctx


def end_term_and_get_pickup(ctx, at="2026-10-08T09:00:00Z"):
    """Mark the lease term complete and return the auto-created pickup id."""
    set_clock(at)
    get_success_data(api_client.mark_term_complete(ctx["lease_id"], COORD))
    pickup = pickup_of(ctx["proj_id"])
    ctx["pickup_id"] = pickup["id"]
    return pickup["id"]


def start_pickup_in_progress(ctx, at="2026-10-13T09:00:00Z"):
    """Take the canonical project's pickup into IN_PROGRESS at the given instant."""
    if "pickup_id" not in ctx:
        end_term_and_get_pickup(ctx)
    set_clock(at)
    get_success_data(api_client.start_pickup(ctx["pickup_id"], COORD))
    return ctx["pickup_id"]


def _single_room_vacant_authorized(mls_number, vendor_min_lease_cycles, unit_count=4):
    """One-room VACANT project, authorized, deposit collected, order confirmed."""
    set_clock(BASE_CLOCK)
    tier_sig = new_tier(TIER_SIGNATURE)
    seller = new_seller()
    agent = new_listing_agent()
    prop = new_property(seller["id"], occupancy="VACANT", distance_miles=8.0, room_count=1)
    listing = new_listing(prop["id"], agent["id"], mls_number=mls_number, list_price=600000.00)
    cons = get_success_data(api_client.create_consultation(
        {"property_id": prop["id"], "requested_by_client_id": agent["id"],
         "scheduled_at": BASE_CLOCK}, COORD))
    get_success_data(api_client.hold_consultation(cons["id"], COORD))
    get_success_data(api_client.add_scope_item(
        cons["id"], {"room_label": "Living", "action": "PACKAGE_ROOM",
                     "requires_rental": True, "accessory_set_count": 0}, COORD))
    get_success_data(api_client.submit_scope(
        cons["id"], {"recommended_tier_code": "SIGNATURE"}, COORD))
    get_success_data(api_client.approve_scope(
        cons["id"], make_listing_agent_headers(agent["id"])))
    project = get_success_data(api_client.create_project(
        {"property_id": prop["id"], "consultation_id": cons["id"],
         "listing_id": listing["id"], "package_tier_id": tier_sig["id"],
         "payer_client_id": seller["id"], "payer_type": "SELLER"}, COORD))
    get_success_data(api_client.authorize_project(
        project["id"], make_seller_headers(seller["id"])))
    deposit = deposit_of(project["id"])
    get_success_data(api_client.collect_deposit(deposit["id"], CLERK))
    vendor = new_vendor(min_lease_cycles=vendor_min_lease_cycles)
    order = get_success_data(api_client.create_rental_order(
        {"project_id": project["id"], "vendor_id": vendor["id"],
         "unit_count": unit_count}, WAREHOUSE))
    get_success_data(api_client.place_rental_order(order["id"], WAREHOUSE))
    get_success_data(api_client.confirm_rental_order(
        order["id"], make_vendor_rep_headers(vendor["id"])))
    pull = get_success_data(api_client.open_pull(project["id"], WAREHOUSE))
    return {
        "tier_sig": tier_sig["id"], "seller_id": seller["id"], "agent_id": agent["id"],
        "prop_id": prop["id"], "listing_id": listing["id"], "cons_id": cons["id"],
        "proj_id": project["id"], "dep_id": deposit["id"], "vendor_id": vendor["id"],
        "ro_id": order["id"], "pull_id": pull["id"],
    }


def setup_vacant_pull_draft():
    """A one-room VACANT project whose pull is still DRAFT and already carries a
    four-unit vendor line, against a vendor whose minimum term is twelve cycles."""
    ctx = _single_room_vacant_authorized("MLS-9007", vendor_min_lease_cycles=12)
    line_v = get_success_data(api_client.add_pull_line(
        ctx["pull_id"], {"source": "VENDOR", "category": "CHAIR", "room_label": "Living",
                         "quantity": 4, "rental_order_id": ctx["ro_id"]}, WAREHOUSE))
    ctx["line_v"] = line_v["id"]
    return ctx


def setup_vacant_pull_submitted():
    """The same one-room project with its pull SUBMITTED at full fill, and the
    project's current version already read for an optimistic-concurrency commit."""
    ctx = setup_vacant_pull_draft()
    get_success_data(api_client.submit_pull(ctx["pull_id"], WAREHOUSE))
    ctx["proj_v"] = project_version(ctx["proj_id"])
    return ctx


def setup_vacant_pull_committed():
    """The one-room VACANT project with its vendor-only pull COMMITTED."""
    ctx = _single_room_vacant_authorized("MLS-9006", vendor_min_lease_cycles=12)
    line_v = get_success_data(api_client.add_pull_line(
        ctx["pull_id"], {"source": "VENDOR", "category": "CHAIR", "room_label": "Living",
                         "quantity": 4, "rental_order_id": ctx["ro_id"]}, WAREHOUSE))
    get_success_data(api_client.submit_pull(ctx["pull_id"], WAREHOUSE))
    get_success_data(api_client.commit_pull(
        ctx["pull_id"], project_version(ctx["proj_id"]), WAREHOUSE))
    ctx["line_v"] = line_v["id"]
    return ctx


def _four_room_vacant_authorized(mls_number, distance_miles=8.0, vendor_min_lease_cycles=4,
                                 unit_count=6, collect_deposit=False):
    """Four-room VACANT project (Living, Primary Bed, Dining, Office), authorized."""
    set_clock(BASE_CLOCK)
    tier_sig = new_tier(TIER_SIGNATURE)
    seller = new_seller()
    agent = new_listing_agent()
    prop = new_property(seller["id"], occupancy="VACANT",
                        distance_miles=distance_miles, room_count=4)
    listing = new_listing(prop["id"], agent["id"], mls_number=mls_number, list_price=700000.00)
    cons = get_success_data(api_client.create_consultation(
        {"property_id": prop["id"], "requested_by_client_id": agent["id"],
         "scheduled_at": BASE_CLOCK}, COORD))
    get_success_data(api_client.hold_consultation(cons["id"], COORD))
    for room_label in ("Living", "Primary Bed", "Dining", "Office"):
        get_success_data(api_client.add_scope_item(
            cons["id"], {"room_label": room_label, "action": "PACKAGE_ROOM",
                         "requires_rental": True, "accessory_set_count": 0}, COORD))
    get_success_data(api_client.submit_scope(
        cons["id"], {"recommended_tier_code": "SIGNATURE"}, COORD))
    get_success_data(api_client.approve_scope(
        cons["id"], make_listing_agent_headers(agent["id"])))
    project = get_success_data(api_client.create_project(
        {"property_id": prop["id"], "consultation_id": cons["id"],
         "listing_id": listing["id"], "package_tier_id": tier_sig["id"],
         "payer_client_id": seller["id"], "payer_type": "SELLER"}, COORD))
    get_success_data(api_client.authorize_project(
        project["id"], make_seller_headers(seller["id"])))
    ctx = {
        "tier_sig": tier_sig["id"], "seller_id": seller["id"], "agent_id": agent["id"],
        "prop_id": prop["id"], "listing_id": listing["id"], "cons_id": cons["id"],
        "proj_id": project["id"],
    }
    if collect_deposit:
        deposit = deposit_of(project["id"])
        get_success_data(api_client.collect_deposit(deposit["id"], CLERK))
        ctx["dep_id"] = deposit["id"]
    vendor = new_vendor(min_lease_cycles=vendor_min_lease_cycles)
    order = get_success_data(api_client.create_rental_order(
        {"project_id": project["id"], "vendor_id": vendor["id"],
         "unit_count": unit_count}, WAREHOUSE))
    get_success_data(api_client.place_rental_order(order["id"], WAREHOUSE))
    get_success_data(api_client.confirm_rental_order(
        order["id"], make_vendor_rep_headers(vendor["id"])))
    pull = get_success_data(api_client.open_pull(project["id"], WAREHOUSE))
    ctx.update({"vendor_id": vendor["id"], "ro_id": order["id"], "pull_id": pull["id"]})
    return ctx


def setup_vacant_pull_partial_sixty_percent():
    """A pull of one six-unit vendor line plus four owned lines no stock can fill,
    submitted against an empty warehouse so it lands PARTIAL at fill_rate 0.6000."""
    ctx = _four_room_vacant_authorized("MLS-9014", unit_count=6)
    line_v = get_success_data(api_client.add_pull_line(
        ctx["pull_id"], {"source": "VENDOR", "category": "CHAIR", "room_label": "Office",
                         "quantity": 6, "rental_order_id": ctx["ro_id"]}, WAREHOUSE))
    owned = []
    for category, room_label in (("SOFA", "Living"), ("BED", "Primary Bed"),
                                 ("TABLE", "Dining"), ("RUG", "Living")):
        owned.append(get_success_data(api_client.add_pull_line(
            ctx["pull_id"], {"source": "OWNED", "category": category,
                             "room_label": room_label, "quantity": 1}, WAREHOUSE))["id"])
    get_success_data(api_client.submit_pull(ctx["pull_id"], WAREHOUSE))
    ctx["proj_v"] = project_version(ctx["proj_id"])
    ctx["line_v"] = line_v["id"]
    ctx["owned_lines"] = owned
    return ctx


def setup_vacant_pull_exactly_seventy_percent():
    """Ten requested units of which seven fill: one seven-unit vendor line plus
    three owned lines that an empty warehouse cannot satisfy."""
    set_clock(BASE_CLOCK)
    tier_sig = new_tier(TIER_SIGNATURE)
    seller = new_seller()
    agent = new_listing_agent()
    prop = new_property(seller["id"], occupancy="VACANT", distance_miles=8.0, room_count=4)
    listing = new_listing(prop["id"], agent["id"], mls_number="MLS-9004", list_price=640000.00)
    cons = get_success_data(api_client.create_consultation(
        {"property_id": prop["id"], "requested_by_client_id": agent["id"],
         "scheduled_at": BASE_CLOCK}, COORD))
    get_success_data(api_client.hold_consultation(cons["id"], COORD))
    for room_label in ("Living", "Office"):
        get_success_data(api_client.add_scope_item(
            cons["id"], {"room_label": room_label, "action": "PACKAGE_ROOM",
                         "requires_rental": True, "accessory_set_count": 0}, COORD))
    get_success_data(api_client.submit_scope(
        cons["id"], {"recommended_tier_code": "SIGNATURE"}, COORD))
    get_success_data(api_client.approve_scope(
        cons["id"], make_listing_agent_headers(agent["id"])))
    project = get_success_data(api_client.create_project(
        {"property_id": prop["id"], "consultation_id": cons["id"],
         "listing_id": listing["id"], "package_tier_id": tier_sig["id"],
         "payer_client_id": seller["id"], "payer_type": "SELLER"}, COORD))
    get_success_data(api_client.authorize_project(
        project["id"], make_seller_headers(seller["id"])))
    vendor = new_vendor(min_lease_cycles=4)
    order = get_success_data(api_client.create_rental_order(
        {"project_id": project["id"], "vendor_id": vendor["id"], "unit_count": 7}, WAREHOUSE))
    get_success_data(api_client.place_rental_order(order["id"], WAREHOUSE))
    get_success_data(api_client.confirm_rental_order(
        order["id"], make_vendor_rep_headers(vendor["id"])))
    pull = get_success_data(api_client.open_pull(project["id"], WAREHOUSE))
    line_v = get_success_data(api_client.add_pull_line(
        pull["id"], {"source": "VENDOR", "category": "CHAIR", "room_label": "Office",
                     "quantity": 7, "rental_order_id": order["id"]}, WAREHOUSE))
    owned = []
    for category in ("SOFA", "BED", "RUG"):
        owned.append(get_success_data(api_client.add_pull_line(
            pull["id"], {"source": "OWNED", "category": category,
                         "room_label": "Living", "quantity": 1}, WAREHOUSE))["id"])
    get_success_data(api_client.submit_pull(pull["id"], WAREHOUSE))
    return {
        "tier_sig": tier_sig["id"], "seller_id": seller["id"], "agent_id": agent["id"],
        "prop_id": prop["id"], "listing_id": listing["id"], "cons_id": cons["id"],
        "proj_id": project["id"], "vendor_id": vendor["id"], "ro_id": order["id"],
        "pull_id": pull["id"], "line_v": line_v["id"], "line_o1": owned[0],
        "line_o2": owned[1], "line_o3": owned[2],
        "proj_v": project_version(project["id"]),
    }


def setup_vacant_three_owned_lines_submitted():
    """Three AVAILABLE owned units reserved by a submitted three-line pull."""
    set_clock(BASE_CLOCK)
    tier_sig = new_tier(TIER_SIGNATURE)
    seller = new_seller()
    agent = new_listing_agent()
    prop = new_property(seller["id"], occupancy="VACANT", distance_miles=8.0, room_count=3)
    listing = new_listing(prop["id"], agent["id"], mls_number="MLS-9005", list_price=660000.00)
    cons = get_success_data(api_client.create_consultation(
        {"property_id": prop["id"], "requested_by_client_id": agent["id"],
         "scheduled_at": BASE_CLOCK}, COORD))
    get_success_data(api_client.hold_consultation(cons["id"], COORD))
    for room_label in ("Living", "Primary Bed", "Dining"):
        get_success_data(api_client.add_scope_item(
            cons["id"], {"room_label": room_label, "action": "PACKAGE_ROOM",
                         "requires_rental": True, "accessory_set_count": 0}, COORD))
    get_success_data(api_client.submit_scope(
        cons["id"], {"recommended_tier_code": "SIGNATURE"}, COORD))
    get_success_data(api_client.approve_scope(
        cons["id"], make_listing_agent_headers(agent["id"])))
    project = get_success_data(api_client.create_project(
        {"property_id": prop["id"], "consultation_id": cons["id"],
         "listing_id": listing["id"], "package_tier_id": tier_sig["id"],
         "payer_client_id": seller["id"], "payer_type": "SELLER"}, COORD))
    get_success_data(api_client.authorize_project(
        project["id"], make_seller_headers(seller["id"])))
    item_a = new_item(ITEM_SOFA)
    item_b = new_item(ITEM_BED)
    item_c = new_item(ITEM_TABLE)
    pull = get_success_data(api_client.open_pull(project["id"], WAREHOUSE))
    for category, room_label in (("SOFA", "Living"), ("BED", "Primary Bed"),
                                 ("TABLE", "Dining")):
        get_success_data(api_client.add_pull_line(
            pull["id"], {"source": "OWNED", "category": category,
                         "room_label": room_label, "quantity": 1}, WAREHOUSE))
    get_success_data(api_client.submit_pull(pull["id"], WAREHOUSE))
    return {
        "proj_id": project["id"], "pull_id": pull["id"], "item_a": item_a["id"],
        "item_b": item_b["id"], "item_c": item_c["id"], "seller_id": seller["id"],
        "agent_id": agent["id"], "prop_id": prop["id"], "listing_id": listing["id"],
    }


def _two_room_vacant_base(mls_number, distance_miles, accessory_sets, vendor_kwargs,
                          unit_count, room_labels=("Living", "Office")):
    """Two-room VACANT project taken to PULL_OPEN with a confirmed vendor order."""
    set_clock(BASE_CLOCK)
    tier_sig = new_tier(TIER_SIGNATURE)
    seller = new_seller()
    agent = new_listing_agent()
    prop = new_property(seller["id"], occupancy="VACANT",
                        distance_miles=distance_miles, room_count=2)
    listing = new_listing(prop["id"], agent["id"], mls_number=mls_number, list_price=640000.00)
    cons = get_success_data(api_client.create_consultation(
        {"property_id": prop["id"], "requested_by_client_id": agent["id"],
         "scheduled_at": BASE_CLOCK}, COORD))
    get_success_data(api_client.hold_consultation(cons["id"], COORD))
    for room_label, sets in zip(room_labels, accessory_sets):
        get_success_data(api_client.add_scope_item(
            cons["id"], {"room_label": room_label, "action": "PACKAGE_ROOM",
                         "requires_rental": True, "accessory_set_count": sets}, COORD))
    get_success_data(api_client.submit_scope(
        cons["id"], {"recommended_tier_code": "SIGNATURE"}, COORD))
    get_success_data(api_client.approve_scope(
        cons["id"], make_listing_agent_headers(agent["id"])))
    project = get_success_data(api_client.create_project(
        {"property_id": prop["id"], "consultation_id": cons["id"],
         "listing_id": listing["id"], "package_tier_id": tier_sig["id"],
         "payer_client_id": seller["id"], "payer_type": "SELLER"}, COORD))
    get_success_data(api_client.authorize_project(
        project["id"], make_seller_headers(seller["id"])))
    deposit = deposit_of(project["id"])
    get_success_data(api_client.collect_deposit(deposit["id"], CLERK))
    vendor = new_vendor(**vendor_kwargs)
    order = get_success_data(api_client.create_rental_order(
        {"project_id": project["id"], "vendor_id": vendor["id"],
         "unit_count": unit_count}, WAREHOUSE))
    get_success_data(api_client.place_rental_order(order["id"], WAREHOUSE))
    get_success_data(api_client.confirm_rental_order(
        order["id"], make_vendor_rep_headers(vendor["id"])))
    pull = get_success_data(api_client.open_pull(project["id"], WAREHOUSE))
    return {
        "tier_sig": tier_sig["id"], "seller_id": seller["id"], "agent_id": agent["id"],
        "prop_id": prop["id"], "listing_id": listing["id"], "cons_id": cons["id"],
        "proj_id": project["id"], "dep_id": deposit["id"], "vendor_id": vendor["id"],
        "ro_id": order["id"], "pull_id": pull["id"],
    }


def setup_vendor_rate_rounding_install_started():
    """Two three-unit vendor lines against a 1.333 multiplier, install started but
    not yet complete, so the caller can trigger the completion itself."""
    ctx = _two_room_vacant_base(
        "MLS-9003", distance_miles=8.0, accessory_sets=(0, 0),
        vendor_kwargs={"min_lease_cycles": 4, "rate_multiplier": 1.333}, unit_count=6)
    line_1 = get_success_data(api_client.add_pull_line(
        ctx["pull_id"], {"source": "VENDOR", "category": "CHAIR", "room_label": "Living",
                         "quantity": 3, "rental_order_id": ctx["ro_id"]}, WAREHOUSE))
    line_2 = get_success_data(api_client.add_pull_line(
        ctx["pull_id"], {"source": "VENDOR", "category": "CHAIR", "room_label": "Office",
                         "quantity": 3, "rental_order_id": ctx["ro_id"]}, WAREHOUSE))
    get_success_data(api_client.submit_pull(ctx["pull_id"], WAREHOUSE))
    get_success_data(api_client.commit_pull(
        ctx["pull_id"], project_version(ctx["proj_id"]), WAREHOUSE))
    install = get_success_data(api_client.schedule_install(
        ctx["proj_id"],
        {"scheduled_at": "2026-06-10T09:00:00Z", "crew_size": 3, "initial_cycles": 4}, COORD))
    set_clock("2026-06-10T09:00:00Z")
    get_success_data(api_client.start_install(install["id"], COORD))
    ctx.update({"line_1": line_1["id"], "line_2": line_2["id"], "install_id": install["id"]})
    return ctx


def setup_vacant_mixed_pool_pickup_in_progress():
    """A two-room VACANT project carrying one owned SOFA line and one ten-unit
    vendor line, driven through install completion to a pickup IN_PROGRESS on
    2026-10-13T09:00:00Z so per-pool damage valuation can be compared."""
    ctx = _two_room_vacant_base(
        "MLS-9001", distance_miles=22.0, accessory_sets=(1, 2),
        vendor_kwargs={"min_lease_cycles": 6}, unit_count=10)
    item_a = new_item(ITEM_SOFA)
    line_a = get_success_data(api_client.add_pull_line(
        ctx["pull_id"], {"source": "OWNED", "category": "SOFA",
                         "room_label": "Living", "quantity": 1}, WAREHOUSE))
    line_v = get_success_data(api_client.add_pull_line(
        ctx["pull_id"], {"source": "VENDOR", "category": "CHAIR", "room_label": "Office",
                         "quantity": 10, "rental_order_id": ctx["ro_id"]}, WAREHOUSE))
    get_success_data(api_client.submit_pull(ctx["pull_id"], WAREHOUSE))
    get_success_data(api_client.commit_pull(
        ctx["pull_id"], project_version(ctx["proj_id"]), WAREHOUSE))
    install = get_success_data(api_client.schedule_install(
        ctx["proj_id"],
        {"scheduled_at": "2026-06-10T09:00:00Z", "crew_size": 3, "initial_cycles": 4}, COORD))
    set_clock("2026-06-10T09:00:00Z")
    get_success_data(api_client.start_install(install["id"], COORD))
    get_success_data(api_client.complete_install(install["id"], COORD))
    lease = lease_of(ctx["proj_id"])
    ctx.update({"item_a": item_a["id"], "line_a": line_a["id"], "line_v": line_v["id"],
                "install_id": install["id"], "lease_id": lease["id"]})
    start_pickup_in_progress(ctx)
    return ctx


def setup_two_projects_one_install_day():
    """Project A holds a SCHEDULED install on 2026-06-10; project B sits at
    PULL_OPEN with a committed vendor-only pull and no install yet."""
    set_clock(BASE_CLOCK)
    tier_sig = new_tier(TIER_SIGNATURE)
    vendor = new_vendor(min_lease_cycles=4)
    ctx = {"tier_sig": tier_sig["id"], "vendor_id": vendor["id"]}
    for suffix, seller_email, agent_email, mls, address in (
        ("a", "dana@ex.com", "milo@ex.com", "MLS-A", "18 Larch Ct"),
        ("b", "sam@ex.com", "vi@ex.com", "MLS-B", "77 Alder Way"),
    ):
        seller = new_seller(email=seller_email, full_name=f"Seller {suffix.upper()}")
        agent = new_listing_agent(email=agent_email, full_name=f"Agent {suffix.upper()}")
        prop = new_property(seller["id"], occupancy="VACANT", distance_miles=8.0,
                            room_count=1, address_line=address)
        listing = new_listing(prop["id"], agent["id"], mls_number=mls, list_price=600000.00)
        cons = get_success_data(api_client.create_consultation(
            {"property_id": prop["id"], "requested_by_client_id": agent["id"],
             "scheduled_at": BASE_CLOCK}, COORD))
        get_success_data(api_client.hold_consultation(cons["id"], COORD))
        get_success_data(api_client.add_scope_item(
            cons["id"], {"room_label": "Living", "action": "PACKAGE_ROOM",
                         "requires_rental": True, "accessory_set_count": 0}, COORD))
        get_success_data(api_client.submit_scope(
            cons["id"], {"recommended_tier_code": "SIGNATURE"}, COORD))
        get_success_data(api_client.approve_scope(
            cons["id"], make_listing_agent_headers(agent["id"])))
        project = get_success_data(api_client.create_project(
            {"property_id": prop["id"], "consultation_id": cons["id"],
             "listing_id": listing["id"], "package_tier_id": tier_sig["id"],
             "payer_client_id": seller["id"], "payer_type": "SELLER"}, COORD))
        get_success_data(api_client.authorize_project(
            project["id"], make_seller_headers(seller["id"])))
        deposit = deposit_of(project["id"])
        get_success_data(api_client.collect_deposit(deposit["id"], CLERK))
        order = get_success_data(api_client.create_rental_order(
            {"project_id": project["id"], "vendor_id": vendor["id"],
             "unit_count": 4}, WAREHOUSE))
        get_success_data(api_client.place_rental_order(order["id"], WAREHOUSE))
        get_success_data(api_client.confirm_rental_order(
            order["id"], make_vendor_rep_headers(vendor["id"])))
        pull = get_success_data(api_client.open_pull(project["id"], WAREHOUSE))
        get_success_data(api_client.add_pull_line(
            pull["id"], {"source": "VENDOR", "category": "CHAIR", "room_label": "Living",
                         "quantity": 4, "rental_order_id": order["id"]}, WAREHOUSE))
        get_success_data(api_client.submit_pull(pull["id"], WAREHOUSE))
        get_success_data(api_client.commit_pull(
            pull["id"], project_version(project["id"]), WAREHOUSE))
        ctx[f"proj_{suffix}"] = project["id"]
        ctx[f"pull_{suffix}"] = pull["id"]
        ctx[f"seller_{suffix}"] = seller["id"]
        ctx[f"agent_{suffix}"] = agent["id"]
        if suffix == "a":
            install = get_success_data(api_client.schedule_install(
                project["id"],
                {"scheduled_at": "2026-06-10T09:00:00Z", "crew_size": 3,
                 "initial_cycles": 4}, COORD))
            ctx["install_a"] = install["id"]
    return ctx


def setup_vacant_zone1_scope_approved():
    """A two-room VACANT property at exactly 15.0 miles with an approved scope."""
    set_clock(BASE_CLOCK)
    tier_sig = new_tier(TIER_SIGNATURE)
    seller = new_seller()
    agent = new_listing_agent()
    prop = new_property(seller["id"], occupancy="VACANT", distance_miles=15.0, room_count=2)
    listing = new_listing(prop["id"], agent["id"], mls_number="MLS-9008", list_price=600000.00)
    cons = get_success_data(api_client.create_consultation(
        {"property_id": prop["id"], "requested_by_client_id": agent["id"],
         "scheduled_at": BASE_CLOCK}, COORD))
    get_success_data(api_client.hold_consultation(cons["id"], COORD))
    for room_label in ("Living", "Office"):
        get_success_data(api_client.add_scope_item(
            cons["id"], {"room_label": room_label, "action": "PACKAGE_ROOM",
                         "requires_rental": True, "accessory_set_count": 0}, COORD))
    get_success_data(api_client.submit_scope(
        cons["id"], {"recommended_tier_code": "SIGNATURE"}, COORD))
    get_success_data(api_client.approve_scope(
        cons["id"], make_listing_agent_headers(agent["id"])))
    return {"tier_sig": tier_sig["id"], "seller_id": seller["id"], "agent_id": agent["id"],
            "prop_id": prop["id"], "listing_id": listing["id"], "cons_id": cons["id"]}


def setup_vacant_at_room_cap_scope_approved():
    """Exactly three PACKAGE_ROOM rooms and exactly two accessory sets, 8.0 miles out."""
    set_clock(BASE_CLOCK)
    tier_sig = new_tier(TIER_SIGNATURE)
    seller = new_seller()
    agent = new_listing_agent()
    prop = new_property(seller["id"], occupancy="VACANT", distance_miles=8.0, room_count=3)
    listing = new_listing(prop["id"], agent["id"], mls_number="MLS-9010", list_price=600000.00)
    cons = get_success_data(api_client.create_consultation(
        {"property_id": prop["id"], "requested_by_client_id": agent["id"],
         "scheduled_at": BASE_CLOCK}, COORD))
    get_success_data(api_client.hold_consultation(cons["id"], COORD))
    for room_label, sets in (("Living", 1), ("Primary Bed", 1), ("Dining", 0)):
        get_success_data(api_client.add_scope_item(
            cons["id"], {"room_label": room_label, "action": "PACKAGE_ROOM",
                         "requires_rental": True, "accessory_set_count": sets}, COORD))
    get_success_data(api_client.submit_scope(
        cons["id"], {"recommended_tier_code": "SIGNATURE"}, COORD))
    get_success_data(api_client.approve_scope(
        cons["id"], make_listing_agent_headers(agent["id"])))
    return {"tier_sig": tier_sig["id"], "seller_id": seller["id"], "agent_id": agent["id"],
            "prop_id": prop["id"], "listing_id": listing["id"], "cons_id": cons["id"]}


# ---------------------------------------------- tier 4: the occupied-arm chain

def _occupied_base(mls_number, scope_hours, submitted_hours, approver,
                   accessory_set_count=0):
    """An OCCUPIED property 8.0 miles out with one EDIT room and an approved scope.

    `approver` is either "agent" or "seller"; both are legal approvers of a scope
    on a property they are a party to.
    """
    set_clock(BASE_CLOCK)
    tier_ess = new_tier(TIER_ESSENTIAL)
    seller = new_seller(email="ada@ex.com", full_name="Ada Fenn")
    agent = new_listing_agent(email="rio@ex.com", full_name="Rio Vance")
    prop = new_property(seller["id"], occupancy="OCCUPIED", distance_miles=8.0,
                        room_count=2, address_line="4 Fir Ln")
    listing = new_listing(prop["id"], agent["id"], mls_number=mls_number,
                          list_price=512000.00)
    cons = get_success_data(api_client.create_consultation(
        {"property_id": prop["id"], "requested_by_client_id": agent["id"],
         "scheduled_at": BASE_CLOCK}, COORD))
    get_success_data(api_client.hold_consultation(cons["id"], COORD))
    get_success_data(api_client.add_scope_item(
        cons["id"], {"room_label": "Living", "action": "EDIT",
                     "estimated_hours": scope_hours,
                     "accessory_set_count": accessory_set_count}, COORD))
    get_success_data(api_client.submit_scope(
        cons["id"], {"recommended_tier_code": "ESSENTIAL",
                     "estimated_hours": submitted_hours}, COORD))
    approver_headers = (make_listing_agent_headers(agent["id"]) if approver == "agent"
                        else make_seller_headers(seller["id"]))
    get_success_data(api_client.approve_scope(cons["id"], approver_headers))
    return {
        "tier_ess": tier_ess["id"], "seller_id": seller["id"], "agent_id": agent["id"],
        "prop_id": prop["id"], "listing_id": listing["id"], "cons_id": cons["id"],
    }


def setup_occupied_agent_draft():
    """OCCUPIED AGENT-payer project in DRAFT: 2400.00 base plus ten hours and the
    first-visit surcharge, comfortably under the agent's 4500.00 ceiling."""
    ctx = _occupied_base("MLS-9009", scope_hours=4.0, submitted_hours=10.0, approver="agent")
    project = get_success_data(api_client.create_project(
        {"property_id": ctx["prop_id"], "consultation_id": ctx["cons_id"],
         "listing_id": ctx["listing_id"], "package_tier_id": ctx["tier_ess"],
         "payer_client_id": ctx["agent_id"], "payer_type": "AGENT"}, COORD))
    ctx["proj_id"] = project["id"]
    ctx["project_row"] = project
    return ctx


def setup_occupied_agent_over_cap_draft():
    """OCCUPIED AGENT-payer project in DRAFT whose thirty consultant hours push the
    contract past the acting agent's own ceiling."""
    ctx = _occupied_base("MLS-9002", scope_hours=4.0, submitted_hours=30.0, approver="agent")
    project = get_success_data(api_client.create_project(
        {"property_id": ctx["prop_id"], "consultation_id": ctx["cons_id"],
         "listing_id": ctx["listing_id"], "package_tier_id": ctx["tier_ess"],
         "payer_client_id": ctx["agent_id"], "payer_type": "AGENT"}, COORD))
    ctx["proj_id"] = project["id"]
    return ctx


def setup_occupied_over_hard_cap_draft():
    """OCCUPIED SELLER-payer project in DRAFT whose eighty consultant hours push the
    contract above the platform's own 15000.00 ceiling."""
    ctx = _occupied_base("MLS-9002", scope_hours=4.0, submitted_hours=80.0, approver="seller")
    project = get_success_data(api_client.create_project(
        {"property_id": ctx["prop_id"], "consultation_id": ctx["cons_id"],
         "listing_id": ctx["listing_id"], "package_tier_id": ctx["tier_ess"],
         "payer_client_id": ctx["seller_id"], "payer_type": "SELLER"}, COORD))
    ctx["proj_id"] = project["id"]
    return ctx


def setup_occupied_pay_at_closing_authorized():
    """OCCUPIED PAY_AT_CLOSING project authorized on 2026-06-01T00:00:00Z with its
    deposit still in REQUIRED, so the deposit gate is open for testing."""
    ctx = _occupied_base("MLS-9002", scope_hours=2.0, submitted_hours=60.0, approver="seller")
    project = get_success_data(api_client.create_project(
        {"property_id": ctx["prop_id"], "consultation_id": ctx["cons_id"],
         "listing_id": ctx["listing_id"], "package_tier_id": ctx["tier_ess"],
         "payer_client_id": ctx["seller_id"], "payer_type": "PAY_AT_CLOSING"}, COORD))
    get_success_data(api_client.authorize_project(
        project["id"], make_seller_headers(ctx["seller_id"])))
    deposit = deposit_of(project["id"])
    ctx.update({"proj_id": project["id"], "dep_id": deposit["id"]})
    return ctx


def setup_occupied_small_contract_authorized():
    """OCCUPIED AGENT-payer project with zero consultant hours, so the deposit
    lands under the collection minimum without any floor being applied."""
    ctx = _occupied_base("MLS-9012", scope_hours=0.0, submitted_hours=0.0, approver="agent")
    project = get_success_data(api_client.create_project(
        {"property_id": ctx["prop_id"], "consultation_id": ctx["cons_id"],
         "listing_id": ctx["listing_id"], "package_tier_id": ctx["tier_ess"],
         "payer_client_id": ctx["agent_id"], "payer_type": "AGENT"}, COORD))
    get_success_data(api_client.authorize_project(
        project["id"], make_listing_agent_headers(ctx["agent_id"])))
    deposit = deposit_of(project["id"])
    ctx.update({"proj_id": project["id"], "dep_id": deposit["id"]})
    return ctx


def occupied_authorize_and_collect(ctx, actor="agent"):
    """Authorize an OCCUPIED draft project and collect the resulting deposit."""
    headers = (make_listing_agent_headers(ctx["agent_id"]) if actor == "agent"
               else make_seller_headers(ctx["seller_id"]))
    get_success_data(api_client.authorize_project(ctx["proj_id"], headers))
    deposit = deposit_of(ctx["proj_id"])
    get_success_data(api_client.collect_deposit(deposit["id"], CLERK))
    ctx["dep_id"] = deposit["id"]
    return deposit["id"]


def setup_occupied_agent_visit_completed():
    """OCCUPIED AGENT-payer project, deposit collected, one two-hour visit completed
    on 2026-06-02T09:00:00Z."""
    ctx = setup_occupied_agent_draft()
    occupied_authorize_and_collect(ctx, actor="agent")
    visit = get_success_data(api_client.schedule_visit(
        ctx["proj_id"], "2026-06-02T09:00:00Z", COORD))
    set_clock("2026-06-02T09:00:00Z")
    get_success_data(api_client.complete_visit(visit["id"], 2.0, COORD))
    ctx["visit_id"] = visit["id"]
    return ctx


def setup_occupied_invoice_issued():
    """OCCUPIED AGENT-payer project with its closeout invoice ISSUED."""
    ctx = setup_occupied_agent_visit_completed()
    invoice = get_success_data(api_client.open_closeout(ctx["proj_id"], CLERK))
    get_success_data(api_client.issue_invoice(invoice["id"], CLERK))
    ctx["inv_id"] = invoice["id"]
    return ctx


def setup_occupied_split_visit_completed():
    """OCCUPIED SPLIT-payer project with payer_split_agent_pct 0.333 and one
    completed two-hour visit."""
    ctx = _occupied_base("MLS-9011", scope_hours=4.0, submitted_hours=10.0, approver="seller")
    project = get_success_data(api_client.create_project(
        {"property_id": ctx["prop_id"], "consultation_id": ctx["cons_id"],
         "listing_id": ctx["listing_id"], "package_tier_id": ctx["tier_ess"],
         "payer_client_id": ctx["seller_id"], "payer_type": "SPLIT",
         "payer_split_agent_pct": 0.333}, COORD))
    ctx["proj_id"] = project["id"]
    get_success_data(api_client.authorize_project(
        project["id"], make_seller_headers(ctx["seller_id"])))
    deposit = deposit_of(project["id"])
    get_success_data(api_client.collect_deposit(deposit["id"], CLERK))
    visit = get_success_data(api_client.schedule_visit(
        project["id"], "2026-06-02T09:00:00Z", COORD))
    set_clock("2026-06-02T09:00:00Z")
    get_success_data(api_client.complete_visit(visit["id"], 2.0, COORD))
    ctx.update({"dep_id": deposit["id"], "visit_id": visit["id"]})
    return ctx


def setup_occupied_pay_at_closing_deferred():
    """OCCUPIED PAY_AT_CLOSING project with a completed visit, a completed shoot
    and a DEFERRED_CLOSING invoice issued at 2026-06-02T14:00:00Z."""
    ctx = _occupied_base("MLS-9015", scope_hours=4.0, submitted_hours=10.0, approver="seller")
    project = get_success_data(api_client.create_project(
        {"property_id": ctx["prop_id"], "consultation_id": ctx["cons_id"],
         "listing_id": ctx["listing_id"], "package_tier_id": ctx["tier_ess"],
         "payer_client_id": ctx["seller_id"], "payer_type": "PAY_AT_CLOSING"}, COORD))
    ctx["proj_id"] = project["id"]
    get_success_data(api_client.authorize_project(
        project["id"], make_seller_headers(ctx["seller_id"])))
    deposit = deposit_of(project["id"])
    get_success_data(api_client.collect_deposit(deposit["id"], CLERK))
    visit = get_success_data(api_client.schedule_visit(
        project["id"], "2026-06-02T09:00:00Z", COORD))
    shoot = get_success_data(api_client.schedule_photo_shoot(
        project["id"], {"scheduled_at": "2026-06-02T14:00:00Z", "is_reshoot": False}, COORD))
    set_clock("2026-06-02T09:00:00Z")
    get_success_data(api_client.complete_visit(visit["id"], 2.0, COORD))
    set_clock("2026-06-02T14:00:00Z")
    get_success_data(api_client.complete_photo_shoot(shoot["id"], COORD))
    invoice = get_success_data(api_client.open_closeout(project["id"], CLERK))
    get_success_data(api_client.defer_invoice_to_closing(invoice["id"], CLERK))
    ctx.update({"dep_id": deposit["id"], "visit_id": visit["id"],
                "shoot_id": shoot["id"], "inv_id": invoice["id"]})
    return ctx


def setup_occupied_tax_exempt_brokerage_visit_completed():
    """OCCUPIED BROKERAGE-payer project billed to a tax-exempt brokerage, with its
    zero-value deposit collected and one visit completed at zero reported hours."""
    set_clock(BASE_CLOCK)
    tier_ess = new_tier(TIER_ESSENTIAL)
    brokerage = new_brokerage(tax_exempt=True)
    seller = new_seller(email="ada@ex.com", full_name="Ada Fenn")
    badmin = new_brokerage_admin(brokerage["id"])
    agent = new_listing_agent(email="rio@ex.com", full_name="Rio Vance",
                              brokerage_id=brokerage["id"])
    prop = new_property(seller["id"], occupancy="OCCUPIED", distance_miles=8.0,
                        room_count=2, address_line="4 Fir Ln")
    listing = new_listing(prop["id"], agent["id"], mls_number="MLS-9002",
                          list_price=512000.00)
    cons = get_success_data(api_client.create_consultation(
        {"property_id": prop["id"], "requested_by_client_id": agent["id"],
         "scheduled_at": BASE_CLOCK}, COORD))
    get_success_data(api_client.hold_consultation(cons["id"], COORD))
    get_success_data(api_client.add_scope_item(
        cons["id"], {"room_label": "Living", "action": "EDIT",
                     "estimated_hours": 2.0, "accessory_set_count": 1}, COORD))
    get_success_data(api_client.submit_scope(
        cons["id"], {"recommended_tier_code": "ESSENTIAL", "estimated_hours": 0.0}, COORD))
    get_success_data(api_client.approve_scope(
        cons["id"], make_listing_agent_headers(agent["id"])))
    project = get_success_data(api_client.create_project(
        {"property_id": prop["id"], "consultation_id": cons["id"],
         "listing_id": listing["id"], "package_tier_id": tier_ess["id"],
         "payer_client_id": badmin["id"], "payer_type": "BROKERAGE",
         "brokerage_id": brokerage["id"]}, COORD))
    get_success_data(api_client.authorize_project(
        project["id"], make_brokerage_admin_headers(brokerage["id"])))
    deposit = deposit_of(project["id"])
    get_success_data(api_client.collect_deposit(deposit["id"], CLERK))
    visit = get_success_data(api_client.schedule_visit(
        project["id"], "2026-06-02T09:00:00Z", COORD))
    set_clock("2026-06-02T09:00:00Z")
    get_success_data(api_client.complete_visit(visit["id"], 0.0, COORD))
    return {
        "tier_ess": tier_ess["id"], "brk_id": brokerage["id"], "seller_id": seller["id"],
        "badmin_id": badmin["id"], "agent_id": agent["id"], "prop_id": prop["id"],
        "listing_id": listing["id"], "cons_id": cons["id"], "proj_id": project["id"],
        "dep_id": deposit["id"], "visit_id": visit["id"],
    }


def setup_occupied_mixed_scope_draft():
    """OCCUPIED AGENT-payer project in DRAFT scoped as two worked rooms plus one
    accessory-only room, 8.0 miles out, with ten consultant hours submitted."""
    set_clock(BASE_CLOCK)
    tier_ess = new_tier(TIER_ESSENTIAL)
    seller = new_seller(email="ada@ex.com", full_name="Ada Fenn")
    agent = new_listing_agent(email="rio@ex.com", full_name="Rio Vance")
    prop = new_property(seller["id"], occupancy="OCCUPIED", distance_miles=8.0,
                        room_count=3, address_line="4 Fir Ln")
    listing = new_listing(prop["id"], agent["id"], mls_number="MLS-9002",
                          list_price=512000.00)
    cons = get_success_data(api_client.create_consultation(
        {"property_id": prop["id"], "requested_by_client_id": agent["id"],
         "scheduled_at": BASE_CLOCK}, COORD))
    get_success_data(api_client.hold_consultation(cons["id"], COORD))
    for room_label, action, hours, sets in (
        ("Living", "EDIT", 4.0, 1),
        ("Kitchen", "DECLUTTER", 6.0, 0),
        ("Entry", "ACCESSORY_ONLY", 0.0, 1),
    ):
        get_success_data(api_client.add_scope_item(
            cons["id"], {"room_label": room_label, "action": action,
                         "estimated_hours": hours, "accessory_set_count": sets}, COORD))
    get_success_data(api_client.submit_scope(
        cons["id"], {"recommended_tier_code": "ESSENTIAL", "estimated_hours": 10.0}, COORD))
    get_success_data(api_client.approve_scope(
        cons["id"], make_listing_agent_headers(agent["id"])))
    project = get_success_data(api_client.create_project(
        {"property_id": prop["id"], "consultation_id": cons["id"],
         "listing_id": listing["id"], "package_tier_id": tier_ess["id"],
         "payer_client_id": agent["id"], "payer_type": "AGENT"}, COORD))
    return {
        "tier_ess": tier_ess["id"], "seller_id": seller["id"], "agent_id": agent["id"],
        "prop_id": prop["id"], "listing_id": listing["id"], "cons_id": cons["id"],
        "proj_id": project["id"], "project_row": project,
    }
