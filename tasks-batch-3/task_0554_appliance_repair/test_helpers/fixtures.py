"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient) internally so a setup failure surfaces as a clear
"Setup failed" rather than a confusing assertion error deep inside a test. Every helper
builds its preconditions from scratch using only PRD-declared endpoints, because the
server database is empty at the start of every test.

Identity threading: after creating a Customer or Technician (both entity-backed), any
ownership-gated call MUST use make_customer_headers(id) / make_technician_headers(id),
never the shared placeholder headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload, create_appliance_payload, create_warranty_contract_payload,
    create_part_payload, create_technician_payload, create_truck_stock_payload,
    create_service_zone_payload, create_service_request_payload, create_appointment_payload,
    create_diagnose_payload, create_revision_payload, create_recall_payload,
)
from .test_users import TEST_USERS, make_customer_headers, make_technician_headers

# Default dispatch window — 2026-06-10 is the canonical service date used across tests.
DEFAULT_WINDOW_START = "2026-06-10T09:00:00Z"
DEFAULT_WINDOW_END = "2026-06-10T10:00:00Z"
DEFAULT_LABOR = [{"minutes": 40}, {"minutes": 20}]


def _admin():
    return TEST_USERS["service_admin_headers"]


def _dispatcher():
    return TEST_USERS["dispatcher_headers"]


# ─── Building blocks ───────────────────────────────────────────────────────
def create_customer(**overrides):
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), _admin()))


def create_appliance(customer_id, **overrides):
    return get_success_data(
        api_client.create_appliance(create_appliance_payload(customer_id, **overrides), _admin()))


def create_technician(**overrides):
    return get_success_data(api_client.create_technician(create_technician_payload(**overrides), _admin()))


def create_part(**overrides):
    return get_success_data(api_client.create_part(create_part_payload(**overrides), _admin()))


def create_truck_stock(technician_id, part_id, **overrides):
    return get_success_data(api_client.create_truck_stock(
        create_truck_stock_payload(technician_id, part_id, **overrides), _admin()))


def create_zone(**overrides):
    return get_success_data(api_client.create_service_zone(create_service_zone_payload(**overrides), _admin()))


def create_warranty_contract(appliance_id, coverage_type, **overrides):
    return get_success_data(api_client.create_warranty_contract(
        create_warranty_contract_payload(appliance_id, coverage_type, **overrides), _admin()))


def create_request(customer_id, appliance_id, **overrides):
    return get_success_data(api_client.create_service_request(
        create_service_request_payload(customer_id, appliance_id, **overrides), _admin()))


def book_appointment(ctx, window_start=DEFAULT_WINDOW_START, window_end=DEFAULT_WINDOW_END,
                     technician_id=None, zone_id=None):
    appt = get_success_data(api_client.create_appointment(
        ctx["sr_id"],
        create_appointment_payload(
            technician_id=technician_id or ctx["tech_id"],
            zone_id=zone_id or ctx["zone_id"],
            window_start=window_start, window_end=window_end),
        _dispatcher()))
    ctx["appt_id"] = appt["id"]
    ctx["appointment"] = appt
    return appt


def diagnose_request(ctx, labor_tasks=None, required_parts=None):
    if labor_tasks is None:
        labor_tasks = [dict(t) for t in DEFAULT_LABOR]
    if required_parts is None:
        required_parts = [{"part_id": ctx["part_id"], "quantity": 2}]
    est = get_success_data(api_client.diagnose(
        ctx["sr_id"], create_diagnose_payload(labor_tasks, required_parts),
        make_technician_headers(ctx["tech_id"])))
    ctx["est_id"] = est["id"]
    ctx["estimate"] = est
    return est


def approve_request(ctx):
    est = get_success_data(api_client.decide_estimate(
        ctx["est_id"], {"decision": "APPROVE"}, make_customer_headers(ctx["cust_id"])))
    ctx["estimate"] = est
    return est


def decline_request(ctx):
    est = get_success_data(api_client.decide_estimate(
        ctx["est_id"], {"decision": "DECLINE"}, make_customer_headers(ctx["cust_id"])))
    ctx["estimate"] = est
    return est


def complete_request(ctx, actual_labor_tasks=None):
    if actual_labor_tasks is None:
        actual_labor_tasks = [dict(t) for t in DEFAULT_LABOR]
    sr = get_success_data(api_client.complete_service_request(
        ctx["sr_id"], {"actual_labor_tasks": actual_labor_tasks},
        make_technician_headers(ctx["tech_id"])))
    ctx["service_request"] = sr
    return sr


def second_trip_request(ctx, part_id=None, quantity=1):
    sr = get_success_data(api_client.second_trip(
        ctx["sr_id"], {"part_id": part_id or ctx["part_id"], "quantity": quantity},
        make_technician_headers(ctx["tech_id"])))
    ctx["service_request"] = sr
    return sr


def set_technician_off_duty(ctx):
    return get_success_data(api_client.update_technician_status(
        ctx["tech_id"], {"to_status": "OFF_DUTY"}, make_technician_headers(ctx["tech_id"])))


def create_and_activate_recall(brand, model, description="safety hazard"):
    """Create a RecallNotice (ISSUED) and activate it (ISSUED -> ACTIVE). Returns activated recall."""
    rec = get_success_data(api_client.create_recall(
        create_recall_payload(brand, model, description=description), _admin()))
    activated = get_success_data(api_client.update_recall_status(rec["id"], {"to_status": "ACTIVE"}, _admin()))
    return activated


def list_request_parts_orders(ctx):
    """All PartsOrders on the request (filtered by service_request_id)."""
    return get_success_data(api_client.list_parts_orders(
        _admin(), params={"service_request_id": ctx["sr_id"]}))


def set_parts_order_status(parts_order_id, to_status):
    return get_success_data(api_client.update_parts_order_status(
        parts_order_id, {"to_status": to_status}, _admin()))


def get_service_request(ctx):
    return get_success_data(api_client.get_service_request(ctx["sr_id"], _admin()))


def get_truck_stock(ctx):
    return get_success_data(api_client.get_truck_stock(ctx["ts_id"], _admin()))


def get_appliance(ctx):
    return get_success_data(api_client.get_appliance(ctx["app_id"], _admin()))


def get_warranty_contract(ctx):
    return get_success_data(api_client.get_warranty_contract(ctx["wc_id"], _admin()))


# ─── Provisioning ──────────────────────────────────────────────────────────
def provision_base(purchase_date="2022-01-15", brand="Kenmore", model="M1",
                   part_number="P1", part_price_cents=4500, quantity_on_hand=5,
                   zone_capacity=5, reported_issue="appliance malfunction", warranty=None,
                   recall=False):
    """Create a full single-request scaffold and return a mutable ctx dict.

    Creates: customer, appliance, technician, part, truck-stock line, zone, and an
    INTAKE service request (plus an optional warranty contract on the appliance).
    `warranty` is a dict of create_warranty_contract_payload overrides including
    coverage_type; when None no contract is created (out-of-warranty scenario).

    When `recall` is True, a RecallNotice matching the appliance's brand/model is
    created and activated *before* the service request is opened, so the request is
    born in INTAKE on an already-RECALLED appliance. (Recalling after a request
    exists would cascade the in-flight request to SAFETY_HOLD per PRD §2.6, which is
    a different scenario.)
    """
    cust = create_customer()
    app = create_appliance(cust["id"], brand=brand, model=model, purchase_date=purchase_date,
                           serial_number=f"SN-{model}")
    tech = create_technician()
    part = create_part(part_number=part_number, unit_price_cents=part_price_cents)
    ts = create_truck_stock(tech["id"], part["id"], quantity_on_hand=quantity_on_hand)
    zone = create_zone(name=f"Zone-{model}", max_concurrent_appointments=zone_capacity)
    wc = None
    if warranty is not None:
        coverage_type = warranty.get("coverage_type", "EXTENDED")
        rest = {k: v for k, v in warranty.items() if k != "coverage_type"}
        wc = create_warranty_contract(app["id"], coverage_type, **rest)
    if recall:
        create_and_activate_recall(brand, model)
    sr = create_request(cust["id"], app["id"], reported_issue=reported_issue)
    return {
        "cust_id": cust["id"], "app_id": app["id"], "tech_id": tech["id"],
        "part_id": part["id"], "ts_id": ts["id"], "zone_id": zone["id"],
        "sr_id": sr["id"], "wc_id": wc["id"] if wc else None,
        "brand": brand, "model": model,
        "customer": cust, "appliance": app, "technician": tech, "part": part,
        "truck_stock": ts, "zone": zone, "warranty_contract": wc, "service_request": sr,
    }


# ─── Composite state-progression fixtures ──────────────────────────────────
def setup_scheduled_request(window_start=DEFAULT_WINDOW_START, window_end=DEFAULT_WINDOW_END, **base):
    """Provisioned scaffold advanced INTAKE -> SCHEDULED (one BOOKED appointment)."""
    ctx = provision_base(**base)
    book_appointment(ctx, window_start=window_start, window_end=window_end)
    return ctx


def setup_diagnosed_request(labor_tasks=None, required_parts=None,
                            window_start=DEFAULT_WINDOW_START, window_end=DEFAULT_WINDOW_END, **base):
    """SCHEDULED -> DIAGNOSED with a PENDING_APPROVAL estimate."""
    ctx = setup_scheduled_request(window_start=window_start, window_end=window_end, **base)
    diagnose_request(ctx, labor_tasks=labor_tasks, required_parts=required_parts)
    return ctx


def setup_approved_request(labor_tasks=None, required_parts=None,
                           window_start=DEFAULT_WINDOW_START, window_end=DEFAULT_WINDOW_END, **base):
    """DIAGNOSED -> APPROVED (parts reserved, warranty claim committed)."""
    ctx = setup_diagnosed_request(labor_tasks=labor_tasks, required_parts=required_parts,
                                  window_start=window_start, window_end=window_end, **base)
    approve_request(ctx)
    return ctx


def setup_declined_none_request(**base):
    """A NONE-routing request declined at DIAGNOSED; amount_due_cents == diagnostic fee (8900).

    No warranty contract exists, so routing resolves to NONE and diagnostic_fee_cents is
    set to 8900 at diagnosis; declining then sets amount_due_cents to that fee.
    """
    ctx = setup_scheduled_request(**base)
    diagnose_request(ctx, labor_tasks=[{"minutes": 40}],
                     required_parts=[{"part_id": ctx["part_id"], "quantity": 1}])
    decline_request(ctx)
    return ctx


def setup_completed_request(labor_tasks=None, required_parts=None, actual_labor_tasks=None, **base):
    """Full lifecycle through COMPLETED on the same visit (APPROVED -> COMPLETED)."""
    ctx = setup_approved_request(labor_tasks=labor_tasks, required_parts=required_parts, **base)
    complete_request(ctx, actual_labor_tasks=actual_labor_tasks)
    return ctx


# ─── Multi-request scheduling-conflict scaffolds ───────────────────────────
def setup_scheduling_conflict_base(num_techs=1, zone_capacity=5):
    """One customer, two appliances, `num_techs` technicians, one zone, two INTAKE requests.

    Returns a dict with tech_ids (list), zone_id, and sr1_id / sr2_id. Used for the
    technician-timeline and zone-capacity conflict scenarios where a first appointment is
    booked, then a second overlapping booking is attempted.
    """
    cust = create_customer()
    app1 = create_appliance(cust["id"], model="MA", serial_number="SN-A")
    app2 = create_appliance(cust["id"], model="MB", serial_number="SN-B")
    techs = [create_technician(full_name=f"Tech {i}") for i in range(num_techs)]
    zone = create_zone(max_concurrent_appointments=zone_capacity)
    sr1 = create_request(cust["id"], app1["id"], reported_issue="one")
    sr2 = create_request(cust["id"], app2["id"], reported_issue="two")
    return {
        "cust_id": cust["id"],
        "app1_id": app1["id"], "app2_id": app2["id"],
        "tech_ids": [t["id"] for t in techs],
        "zone_id": zone["id"],
        "sr1_id": sr1["id"], "sr2_id": sr2["id"],
    }


def book_conflict_appointment(scaffold, sr_key, tech_index, window_start, window_end):
    """Book an appointment for one of the two requests in a conflict scaffold."""
    return get_success_data(api_client.create_appointment(
        scaffold[sr_key],
        create_appointment_payload(
            technician_id=scaffold["tech_ids"][tech_index],
            zone_id=scaffold["zone_id"],
            window_start=window_start, window_end=window_end),
        _dispatcher()))
