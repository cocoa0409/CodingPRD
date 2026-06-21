"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the repair ticket to be in a specific lifecycle
state reached through 5-20 API calls. These helpers encapsulate those sequences
so tests focus on assertions.

Identity threading (mandatory): RepairTechnician and Customer are entity-backed
roles. After creating a Technician/Customer, every authorship- or
ownership-gated call uses make_technician_headers(tech_id) /
make_customer_headers(customer_id) with the ACTUAL entity id — never the shared
TEST_USERS fallback. Opaque roles (FrontDeskClerk, ShopManager) use the shared
constants.

All helpers use get_success_data() (lenient) so setup failures surface as clear
"setup failed" errors rather than confusing assertion failures.

The harness restarts the server (empty DB) before every test, so each helper
builds its whole world from scratch, including setting the server clock.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BASE_CLOCK
from .factories import (
    set_clock_payload,
    create_customer_payload,
    create_service_type_payload,
    create_technician_payload,
    create_repair_ticket_payload,
    create_ticket_item_payload,
    create_service_line_payload,
    create_estimate_payload,
    present_estimate_payload,
    create_parts_order_payload,
    create_payment_payload,
    create_warranty_claim_payload,
    rule_warranty_claim_payload,
)
from .test_users import (
    TEST_USERS,
    make_technician_headers,
    make_customer_headers,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
SHOP_MANAGER = TEST_USERS["shop_manager_headers"]


# ──────────────────────────────────────────────────────────────────────────
# Tier 0: clock + catalog primitives
# ──────────────────────────────────────────────────────────────────────────
def set_clock(to_iso8601: str = BASE_CLOCK) -> str:
    """Set the server's logical UTC clock. Returns the resulting `now`."""
    res = api_client.set_clock(set_clock_payload(to_iso8601), SHOP_MANAGER)
    return get_success_data(res).get("now")


def create_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), FRONT_DESK)
    )


def create_service_type(**overrides) -> dict:
    return get_success_data(
        api_client.create_service_type(create_service_type_payload(**overrides), SHOP_MANAGER)
    )


def create_technician(**overrides) -> dict:
    return get_success_data(
        api_client.create_technician(create_technician_payload(**overrides), SHOP_MANAGER)
    )


# ──────────────────────────────────────────────────────────────────────────
# Tier 1: intake + items + lines (ticket in INTAKE)
# ──────────────────────────────────────────────────────────────────────────
def create_ticket(customer_id: str, **overrides) -> dict:
    """Intake a ticket (repair_status INTAKE). overrides may carry priority /
    assigned_technician_id."""
    return get_success_data(
        api_client.create_repair_ticket(
            create_repair_ticket_payload(customer_id, **overrides), FRONT_DESK
        )
    )


def add_item(ticket_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_ticket_item(create_ticket_item_payload(ticket_id, **overrides), FRONT_DESK)
    )


def add_service_line(ticket_id: str, ticket_item_id: str, service_type_id: str,
                     tech_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_service_line(
            create_service_line_payload(ticket_id, ticket_item_id, service_type_id, **overrides),
            make_technician_headers(tech_id),
        )
    )


def add_part(ticket_id: str, service_line_id: str, supplier_cost_cents: int,
             lead_time_days: int, tech_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_parts_order(
            create_parts_order_payload(
                ticket_id, service_line_id, supplier_cost_cents, lead_time_days, **overrides
            ),
            make_technician_headers(tech_id),
        )
    )


def create_draft_estimate(ticket_id: str, tech_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_estimate(
            create_estimate_payload(ticket_id, tech_id, **overrides),
            make_technician_headers(tech_id),
        )
    )


def get_ticket_version(ticket_id: str) -> int:
    return get_success_data(api_client.get_repair_ticket(ticket_id, FRONT_DESK))["version"]


def present_estimate(estimate_id: str, ticket_id: str, tech_id: str) -> dict:
    """Present a draft estimate, supplying the live ticket version for the OCC
    guard (read just-in-time)."""
    v = get_ticket_version(ticket_id)
    return get_success_data(
        api_client.present_estimate(
            estimate_id, present_estimate_payload(v), make_technician_headers(tech_id)
        )
    )


def approve_estimate(estimate_id: str, customer_id: str) -> dict:
    return get_success_data(
        api_client.approve_estimate(estimate_id, make_customer_headers(customer_id))
    )


def reject_estimate(estimate_id: str, customer_id: str) -> dict:
    return get_success_data(
        api_client.reject_estimate(estimate_id, make_customer_headers(customer_id))
    )


# ──────────────────────────────────────────────────────────────────────────
# Tier 2: standard "world" bootstrap
# ──────────────────────────────────────────────────────────────────────────
def bootstrap_world(clock: str = BASE_CLOCK, tech_skills=None, service_overrides=None):
    """Set clock, create one customer, one technician, one SHOE service-type.
    Returns dict with customer, technician, service_type."""
    set_clock(clock)
    customer = create_customer()
    technician = create_technician(skills=tech_skills or ["SHOE", "LEATHER", "WATCH"])
    service_type = create_service_type(**(service_overrides or {}))
    return {"customer": customer, "technician": technician, "service_type": service_type}


def setup_ticket_with_line(clock: str = BASE_CLOCK, priority: str = "STANDARD",
                           service_overrides=None, item_category: str = "SHOE",
                           tech_skills=None):
    """Set clock + customer + technician + service-type + ticket (with assigned
    technician) + one item + one QUOTED service line. Ticket is in INTAKE.

    Returns dict: customer, technician, service_type, ticket, item, line.
    """
    world = bootstrap_world(clock, tech_skills=tech_skills, service_overrides=service_overrides)
    customer = world["customer"]
    technician = world["technician"]
    service_type = world["service_type"]

    ticket = create_ticket(customer["id"], priority=priority,
                           assigned_technician_id=technician["id"])
    item = add_item(ticket["id"], item_category=item_category)
    line = add_service_line(ticket["id"], item["id"], service_type["id"], technician["id"])
    return {
        "customer": customer,
        "technician": technician,
        "service_type": service_type,
        "ticket": ticket,
        "item": item,
        "line": line,
    }


# ──────────────────────────────────────────────────────────────────────────
# Tier 3: lifecycle shortcuts (approve / in-repair / ready)
# ──────────────────────────────────────────────────────────────────────────
def setup_presented(clock: str = BASE_CLOCK, priority: str = "STANDARD",
                    service_overrides=None, item_category: str = "SHOE",
                    tech_skills=None):
    """Ticket carried to AWAITING_APPROVAL with a PRESENTED first estimate.
    Returns the setup_ticket_with_line dict plus `estimate`."""
    s = setup_ticket_with_line(clock, priority, service_overrides, item_category, tech_skills)
    est = create_draft_estimate(s["ticket"]["id"], s["technician"]["id"])
    est = present_estimate(est["id"], s["ticket"]["id"], s["technician"]["id"])
    s["estimate"] = est
    return s


def setup_approved(clock: str = BASE_CLOCK, priority: str = "STANDARD",
                   service_overrides=None, item_category: str = "SHOE",
                   tech_skills=None):
    """Ticket approved (no parts -> APPROVED). Returns setup_presented dict."""
    s = setup_presented(clock, priority, service_overrides, item_category, tech_skills)
    approve_estimate(s["estimate"]["id"], s["customer"]["id"])
    return s


def setup_in_repair(clock: str = BASE_CLOCK, priority: str = "STANDARD",
                    service_overrides=None, item_category: str = "SHOE",
                    tech_skills=None):
    """Ticket in IN_REPAIR (approved with no parts, start-repair called).
    Returns setup_approved dict."""
    s = setup_approved(clock, priority, service_overrides, item_category, tech_skills)
    get_success_data(
        api_client.start_repair(s["ticket"]["id"], make_technician_headers(s["technician"]["id"]))
    )
    return s


def complete_line(line_id: str, tech_id: str, adjusted_price_cents=None) -> dict:
    payload = {"status": "COMPLETED"}
    if adjusted_price_cents is not None:
        payload["adjusted_price_cents"] = adjusted_price_cents
    return get_success_data(
        api_client.patch_service_line(line_id, payload, make_technician_headers(tech_id))
    )


def setup_ready_for_pickup(clock: str = BASE_CLOCK, priority: str = "STANDARD",
                           service_overrides=None, item_category: str = "SHOE",
                           tech_skills=None, mark_ready_clock=None):
    """Ticket in READY_FOR_PICKUP: line completed, mark-ready called.
    Optionally advance the clock to mark_ready_clock before mark-ready (to drive
    sla_breached). Returns setup_in_repair dict plus `ready_ticket`."""
    s = setup_in_repair(clock, priority, service_overrides, item_category, tech_skills)
    complete_line(s["line"]["id"], s["technician"]["id"])
    if mark_ready_clock:
        set_clock(mark_ready_clock)
    ready = get_success_data(
        api_client.mark_ready(s["ticket"]["id"], make_technician_headers(s["technician"]["id"]))
    )
    s["ready_ticket"] = ready
    return s


def capture_full_payment(ticket_id: str, amount_cents: int) -> dict:
    """Capture an OCC-guarded payment for `amount_cents` (reads the live version
    just-in-time)."""
    v = get_ticket_version(ticket_id)
    return get_success_data(
        api_client.create_payment(
            create_payment_payload(ticket_id, amount_cents, v), FRONT_DESK
        )
    )


def setup_picked_up(clock: str = BASE_CLOCK, priority: str = "STANDARD",
                    service_overrides=None, item_category: str = "SHOE",
                    tech_skills=None):
    """Ticket carried all the way to PICKED_UP (line completed, mark-ready,
    full payment matching final_charge_cents, pickup). Returns the
    setup_ready_for_pickup dict plus `picked_up_ticket`."""
    s = setup_ready_for_pickup(clock, priority, service_overrides, item_category, tech_skills)
    final_charge = s["ready_ticket"]["final_charge_cents"]
    capture_full_payment(s["ticket"]["id"], final_charge)
    picked = get_success_data(api_client.pickup(s["ticket"]["id"], FRONT_DESK))
    s["picked_up_ticket"] = picked
    return s


# ──────────────────────────────────────────────────────────────────────────
# Tier 4: warranty flow (segregation needs a SECOND, ruling technician)
# ──────────────────────────────────────────────────────────────────────────
def setup_filed_warranty_claim(clock: str = BASE_CLOCK, item_category: str = "WATCH",
                               service_overrides=None):
    """Carry a ticket to PICKED_UP within warranty, then file a warranty claim
    against its completed line.

    Builds TWO technicians: `technician` (authors the estimate / does the work)
    and `ruling_technician` (eligible to adjudicate without a segregation
    violation). Returns dict with customer, technician, ruling_technician,
    service_type, ticket, item, line, claim, picked_up_ticket.
    """
    set_clock(clock)
    customer = create_customer()
    technician = create_technician(display_name="Author Tech", skills=["SHOE", "LEATHER", "WATCH"])
    ruling_technician = create_technician(display_name="Ruling Tech",
                                          skills=["SHOE", "LEATHER", "WATCH"])
    so = {"item_category": item_category, "warranty_days": 90, "standard_turnaround_days": 1,
          "base_price_cents": 1500}
    so.update(service_overrides or {})
    service_type = create_service_type(**so)

    ticket = create_ticket(customer["id"], assigned_technician_id=technician["id"])
    item = add_item(ticket["id"], item_category=item_category)
    line = add_service_line(ticket["id"], item["id"], service_type["id"], technician["id"])

    est = create_draft_estimate(ticket["id"], technician["id"])
    est = present_estimate(est["id"], ticket["id"], technician["id"])
    approve_estimate(est["id"], customer["id"])
    get_success_data(api_client.start_repair(ticket["id"], make_technician_headers(technician["id"])))
    complete_line(line["id"], technician["id"])
    ready = get_success_data(api_client.mark_ready(ticket["id"], make_technician_headers(technician["id"])))
    capture_full_payment(ticket["id"], ready["final_charge_cents"])
    picked = get_success_data(api_client.pickup(ticket["id"], FRONT_DESK))

    claim = get_success_data(
        api_client.create_warranty_claim(
            create_warranty_claim_payload(ticket["id"], line["id"], customer["id"]),
            make_customer_headers(customer["id"]),
        )
    )
    return {
        "customer": customer,
        "technician": technician,
        "ruling_technician": ruling_technician,
        "service_type": service_type,
        "ticket": ticket,
        "item": item,
        "line": line,
        "estimate": est,
        "picked_up_ticket": picked,
        "claim": claim,
    }


def approve_claim(claim_id: str, ruling_tech_id: str) -> dict:
    return get_success_data(
        api_client.approve_warranty_claim(
            claim_id, rule_warranty_claim_payload(ruling_tech_id), SHOP_MANAGER
        )
    )


def deny_claim(claim_id: str, ruling_tech_id: str) -> dict:
    return get_success_data(
        api_client.deny_warranty_claim(
            claim_id, rule_warranty_claim_payload(ruling_tech_id), SHOP_MANAGER
        )
    )


# ──────────────────────────────────────────────────────────────────────────
# Tier 5: unclaimed / disposal staging
# ──────────────────────────────────────────────────────────────────────────
def setup_flagged_unclaimed(clock: str = BASE_CLOCK, flag_clock: str = "2026-03-31T09:00:00Z"):
    """Ticket READY_FOR_PICKUP at `clock` (= ready_at), then clock advanced to
    `flag_clock` and flag-unclaimed called -> UNCLAIMED + UNCLAIMED_WARNED.
    Returns the setup_ready_for_pickup dict plus `unclaimed_ticket`."""
    s = setup_ready_for_pickup(clock, item_category="SHOE")
    set_clock(flag_clock)
    flagged = get_success_data(api_client.flag_unclaimed(s["ticket"]["id"], FRONT_DESK))
    s["unclaimed_ticket"] = flagged
    return s
