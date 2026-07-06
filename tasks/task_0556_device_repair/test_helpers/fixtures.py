"""Composite setup helpers.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the harness restarts the server / empties the DB before each test). Helpers use
get_success_data() so a setup miss surfaces as a clear "Setup failed".

Identity threading: Customer and Technician are identity-backed roles, so calls
they own use make_customer_headers(customer_id) / make_technician_headers(tech_id)
with the real entity id. ServiceAdvisor and StoreManager are opaque (shared headers).
"""
import itertools

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS, make_customer_headers, make_technician_headers,
)

SA = TEST_USERS["service_advisor_headers"]     # ServiceAdvisor (opaque)
SM = TEST_USERS["store_manager_headers"]       # StoreManager (opaque)

_seq = itertools.count(1)


def _d(resp):
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Low-level creators
# ---------------------------------------------------------------------------
def create_customer(full_name=None, email=None, phone="555"):
    n = next(_seq)
    payload = {
        "full_name": full_name or f"Cust{n}",
        "email": email or f"cust{n}@x.com",
        "phone": phone,
    }
    return _d(api_client.create_customer(payload, SA))


def create_device(customer_id, market_value_cents=60000, category="PHONE",
                  brand="Acme", model="Z1", serial_number=None):
    payload = {
        "customer_id": customer_id,
        "category": category,
        "brand": brand,
        "model": model,
        "serial_number": serial_number or f"SN{next(_seq)}",
        "market_value_cents": market_value_cents,
    }
    return _d(api_client.create_device(payload, SA))


def create_technician(certification_level="STANDARD", full_name=None):
    payload = {"full_name": full_name or f"Tech{next(_seq)}",
               "certification_level": certification_level}
    return _d(api_client.create_technician(payload, SM))


def create_bay(bay_name=None):
    return _d(api_client.create_repair_bay({"bay_name": bay_name or f"Bay{next(_seq)}"}, SM))


def create_part(unit_price_cents=6000, on_hand_qty=10, sku=None, name="Screen"):
    payload = {"sku": sku or f"SKU{next(_seq)}", "name": name,
               "unit_price_cents": unit_price_cents, "on_hand_qty": on_hand_qty}
    return _d(api_client.create_part(payload, SM))


def create_ticket(device_id, customer_id, intake_channel="WALK_IN",
                  reported_issue="cracked", spend_cap_cents=100000, is_under_warranty=None):
    payload = {
        "device_id": device_id,
        "customer_id": customer_id,
        "intake_channel": intake_channel,
        "reported_issue": reported_issue,
        "spend_cap_cents": spend_cap_cents,
    }
    if is_under_warranty is not None:
        payload["is_under_warranty"] = is_under_warranty
    return _d(api_client.create_repair_ticket(payload, SA))


def set_clock(iso):
    return _d(api_client.set_clock(iso, SM))


def diagnose_ticket(ticket_id, technician_id, bay_id,
                    start="2026-05-02T10:00:00Z", end="2026-05-02T11:00:00Z"):
    payload = {"assigned_technician_id": technician_id, "assigned_bay_id": bay_id,
               "scheduled_start_at": start, "scheduled_end_at": end}
    return _d(api_client.diagnose(ticket_id, payload, make_technician_headers(technician_id)))


def post_estimate(ticket_id, technician_id, labor_hours, expected_version):
    payload = {"labor_hours": labor_hours, "expected_repair_ticket_version": expected_version}
    return _d(api_client.create_estimate(ticket_id, payload, make_technician_headers(technician_id)))


def add_part_order(ticket_id, technician_id, part_id, quantity):
    payload = {"part_id": part_id, "quantity": quantity}
    return _d(api_client.create_part_order(ticket_id, payload, make_technician_headers(technician_id)))


# ---------------------------------------------------------------------------
# Composite scenarios (return a dict of named entities)
# ---------------------------------------------------------------------------
def setup_diagnosed_ticket(market_value_cents=60000, certification_level="STANDARD",
                           is_under_warranty=False, spend_cap_cents=100000,
                           start="2026-05-02T10:00:00Z", end="2026-05-02T11:00:00Z"):
    """Customer + device + technician + bay + ticket walked to DIAGNOSING.

    Returns dict with: customer, device, technician, bay, ticket (post-diagnose,
    carries the current version for the OCC estimate call).
    """
    cust = create_customer()
    dev = create_device(cust["id"], market_value_cents=market_value_cents)
    tech = create_technician(certification_level)
    bay = create_bay()
    tkt = create_ticket(dev["id"], cust["id"], spend_cap_cents=spend_cap_cents,
                        is_under_warranty=is_under_warranty)
    diagnosed = diagnose_ticket(tkt["id"], tech["id"], bay["id"], start=start, end=end)
    return {"customer": cust, "device": dev, "technician": tech, "bay": bay,
            "ticket": diagnosed}


def setup_estimate_sent(market_value_cents=60000, certification_level="STANDARD",
                        is_under_warranty=False, spend_cap_cents=100000,
                        labor_hours=2, part_specs=None):
    """Ticket at AWAITING_APPROVAL with a live SENT estimate.

    part_specs: list of (unit_price_cents, on_hand_qty, order_quantity); each
    becomes a Part + a part order created before the estimate so its line cost
    is swept into the provisional parts total.

    Returns setup_diagnosed_ticket dict plus: parts, orders, estimate.
    """
    scn = setup_diagnosed_ticket(market_value_cents=market_value_cents,
                                 certification_level=certification_level,
                                 is_under_warranty=is_under_warranty,
                                 spend_cap_cents=spend_cap_cents)
    parts, orders = [], []
    for spec in (part_specs or []):
        price, on_hand, qty = spec
        part = create_part(unit_price_cents=price, on_hand_qty=on_hand)
        order = add_part_order(scn["ticket"]["id"], scn["technician"]["id"], part["id"], qty)
        parts.append(part)
        orders.append(order)
    est = post_estimate(scn["ticket"]["id"], scn["technician"]["id"],
                        labor_hours, scn["ticket"]["version"])
    scn["parts"] = parts
    scn["orders"] = orders
    scn["estimate"] = est
    return scn


def setup_ticket_in_repair(market_value_cents=60000, certification_level="STANDARD",
                           is_under_warranty=False, spend_cap_cents=100000,
                           labor_hours=2, part_specs=None):
    """setup_estimate_sent, then the owning customer approves -> ticket IN_REPAIR."""
    scn = setup_estimate_sent(market_value_cents=market_value_cents,
                              certification_level=certification_level,
                              is_under_warranty=is_under_warranty,
                              spend_cap_cents=spend_cap_cents,
                              labor_hours=labor_hours, part_specs=part_specs)
    approved = _d(api_client.approve_estimate(
        scn["ticket"]["id"], scn["estimate"]["id"],
        make_customer_headers(scn["customer"]["id"])))
    scn["estimate"] = approved
    return scn


def setup_completed_ticket(market_value_cents=60000, certification_level="STANDARD",
                           is_under_warranty=False, spend_cap_cents=100000,
                           labor_hours=2, actual_labor_hours=2, part_specs=None,
                           completed_at=None):
    """Full lifecycle through COMPLETED. If completed_at given, the clock is set
    to it before completion so completed_at is deterministic."""
    scn = setup_ticket_in_repair(market_value_cents=market_value_cents,
                                 certification_level=certification_level,
                                 is_under_warranty=is_under_warranty,
                                 spend_cap_cents=spend_cap_cents,
                                 labor_hours=labor_hours, part_specs=part_specs)
    if completed_at is not None:
        set_clock(completed_at)
    completed = _d(api_client.complete_ticket(
        scn["ticket"]["id"], {"actual_labor_hours": actual_labor_hours},
        make_technician_headers(scn["technician"]["id"])))
    scn["ticket"] = completed
    return scn


# ---------------------------------------------------------------------------
# Trade-in scenarios
# ---------------------------------------------------------------------------
def setup_trade_in_submitted(market_value_cents=50000, declared_grade="A"):
    """Customer + device + technician + trade-in in SUBMITTED (quoted computed)."""
    cust = create_customer()
    dev = create_device(cust["id"], market_value_cents=market_value_cents)
    tech = create_technician("STANDARD")
    ti = _d(api_client.create_trade_in(
        {"customer_id": cust["id"], "device_id": dev["id"], "declared_grade": declared_grade}, SA))
    return {"customer": cust, "device": dev, "technician": tech, "trade_in": ti}


def offer_trade_in(scn, assessed_grade, has_accessories=False, assessed_cosmetic_defect_count=0):
    payload = {"assessed_grade": assessed_grade, "has_accessories": has_accessories,
               "assessed_cosmetic_defect_count": assessed_cosmetic_defect_count}
    offered = _d(api_client.offer_trade_in(
        scn["trade_in"]["id"], payload, make_technician_headers(scn["technician"]["id"])))
    scn["trade_in"] = offered
    return offered


def setup_trade_in_offer_made(market_value_cents=50000, declared_grade="A",
                              assessed_grade="A", has_accessories=False,
                              assessed_cosmetic_defect_count=0):
    scn = setup_trade_in_submitted(market_value_cents=market_value_cents,
                                   declared_grade=declared_grade)
    offer_trade_in(scn, assessed_grade, has_accessories, assessed_cosmetic_defect_count)
    return scn


def setup_trade_in_accepted(market_value_cents=50000, declared_grade="A",
                            assessed_grade="A", has_accessories=False,
                            assessed_cosmetic_defect_count=0):
    scn = setup_trade_in_offer_made(market_value_cents=market_value_cents,
                                    declared_grade=declared_grade,
                                    assessed_grade=assessed_grade,
                                    has_accessories=has_accessories,
                                    assessed_cosmetic_defect_count=assessed_cosmetic_defect_count)
    accepted = _d(api_client.accept_trade_in(
        scn["trade_in"]["id"], make_customer_headers(scn["customer"]["id"])))
    scn["trade_in"] = accepted
    return scn


def issue_wipe_certificate(device_id, trade_in_id=None, method="CRYPTO_ERASE",
                           wipe_result="SUCCESS", technician_id=None):
    """Issue a DataWipeCertificate. Technician is opaque-for-existence here; use the
    shared technician header unless a specific persisted technician id is given."""
    headers = make_technician_headers(technician_id) if technician_id else TEST_USERS["technician_headers"]
    payload = {"device_id": device_id, "method": method, "wipe_result": wipe_result}
    if trade_in_id is not None:
        payload["trade_in_id"] = trade_in_id
    return _d(api_client.create_data_wipe_certificate(payload, headers))


# ---------------------------------------------------------------------------
# Protection-plan claim scenarios
# ---------------------------------------------------------------------------
def file_claim(ticket_id, customer_id, plan_type="ADH"):
    return _d(api_client.create_claim(
        {"repair_ticket_id": ticket_id, "customer_id": customer_id, "plan_type": plan_type}, SA))


def route_claim(claim_id):
    return _d(api_client.route_claim(claim_id, SA))


def setup_claim_routed(ticket_id, customer_id, plan_type="ADH"):
    claim = file_claim(ticket_id, customer_id, plan_type)
    routed = route_claim(claim["id"])
    return routed
