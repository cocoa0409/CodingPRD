"""Composite setup helpers.

Every helper builds its preconditions from scratch against a fresh server
(the harness restarts the API before every test) using only PRD-declared
endpoints. Setup calls use get_success_data() so failures surface as clear
"Setup step failed" errors rather than confusing assertion output.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_customer_payload,
    create_plating_bath_payload,
    create_press_line_payload,
    create_press_order_payload,
    create_print_job_payload,
    create_release_payload,
)
from .test_users import TEST_USERS, make_customer_headers, make_pm_headers, make_qa_headers

ADMIN = TEST_USERS["platform_admin_headers"]
CSR = TEST_USERS["csr_headers"]
PLANNER = TEST_USERS["planner_headers"]
OPERATOR = TEST_USERS["operator_headers"]
QA = TEST_USERS["qa_headers"]
PM = TEST_USERS["pm_headers"]
WH = TEST_USERS["warehouse_headers"]
BILLING = TEST_USERS["billing_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-resource creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = DEFAULT_CLOCK):
    """Drive the logical clock (PlatformAdmin only)."""
    get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_customer(**overrides) -> dict:
    resp = api_client.create_customer(create_customer_payload(**overrides), CSR)
    return get_success_data(resp)


def create_release(customer_id: str, **overrides) -> dict:
    resp = api_client.create_release(create_release_payload(customer_id, **overrides), CSR)
    return get_success_data(resp)


def create_press_line(**overrides) -> dict:
    resp = api_client.create_press_line(create_press_line_payload(**overrides), PLANNER)
    return get_success_data(resp)


def create_plating_bath(**overrides) -> dict:
    resp = api_client.create_plating_bath(create_plating_bath_payload(**overrides), PLANNER)
    return get_success_data(resp)


def create_inventory_lot(release_id: str, zone: str = "A") -> dict:
    resp = api_client.create_inventory_lot({"release_id": release_id, "zone": zone}, WH)
    return get_success_data(resp)


def receive_stock(lot_id: str, quantity: int, event_date: str = "2026-08-01") -> dict:
    resp = api_client.post_stock_event(
        lot_id, {"event": "RECEIVE", "quantity": quantity, "event_date": event_date}, WH
    )
    return get_success_data(resp)


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_press_order(order_id, CSR))


# ---------------------------------------------------------------------------
# Tier 1: world assembly
# ---------------------------------------------------------------------------

def setup_world(customer_over: dict = None, release_over: dict = None,
                line_over: dict = None, bath_over: dict = None,
                with_line: bool = True, with_bath: bool = True,
                clock: str = DEFAULT_CLOCK) -> dict:
    """Customer + one release (+ optionally a press line and plating bath)."""
    set_clock(clock)
    customer = create_customer(**(customer_over or {}))
    release = create_release(customer["id"], **(release_over or {}))
    line = create_press_line(**(line_over or {})) if with_line else None
    bath = create_plating_bath(**(bath_over or {})) if with_bath else None
    return {"customer": customer, "release": release, "line": line, "bath": bath}


# ---------------------------------------------------------------------------
# Tier 2: order pipeline stages (each returns the fresh order dict)
# ---------------------------------------------------------------------------

def create_order(release_id: str, quantity_ordered: int = 1000,
                 variants: list = None, **overrides) -> dict:
    payload = create_press_order_payload(release_id, quantity_ordered=quantity_ordered)
    if variants is not None:
        payload["variants"] = variants
    payload.update(overrides)
    return get_success_data(api_client.create_press_order(payload, CSR))


def quote_order(order: dict) -> dict:
    """Quote with the order's current version (OCC guard). Returns QUOTED order."""
    resp = api_client.quote_press_order(
        order["id"], {"expected_press_order_version": order["version"]}, CSR
    )
    return get_success_data(resp)


def confirm_order(order: dict, customer_id: str) -> dict:
    """Confirm as the owning customer (entity-backed role). Returns CONFIRMED order."""
    resp = api_client.confirm_press_order(
        order["id"],
        {"expected_press_order_version": order["version"]},
        make_customer_headers(customer_id),
    )
    return get_success_data(resp)


def start_tooling(order_id: str) -> dict:
    """CONFIRMED -> TOOLING; returns the round-1 ToolingJob."""
    get_success_data(api_client.start_tooling(order_id, PLANNER))
    jobs, _meta = _list(api_client.list_order_tooling_jobs(order_id, CSR))
    return jobs[0]


def advance_tooling(job_id: str, event: str, **extra) -> dict:
    payload = {"event": event}
    payload.update(extra)
    return get_success_data(api_client.advance_tooling_job(job_id, payload, OPERATOR))


def drive_tooling_to_stamper_ready(job_id: str, bath_id: str,
                                   plating_start: int = 2, plating_end: int = 6) -> dict:
    """Walk a fresh ToolingJob QUEUED -> STAMPER_READY, booking the bath."""
    advance_tooling(job_id, "START_CUT")
    advance_tooling(job_id, "CUT_DONE")
    advance_tooling(job_id, "START_PLATING", plating_bath_id=bath_id,
                    plating_start=plating_start, plating_end=plating_end)
    return advance_tooling(job_id, "PLATING_DONE")


def produce_test_pressing(order_id: str, quantity: int = 5) -> dict:
    resp = api_client.create_test_pressing(order_id, {"quantity": quantity}, OPERATOR)
    return get_success_data(resp)


def ship_test_pressing(tp_id: str) -> dict:
    return get_success_data(api_client.ship_test_pressing(tp_id, PLANNER))


def review_test_pressing(tp_id: str, customer_id: str, decision: str = "APPROVE",
                         notes: str = None) -> dict:
    payload = {"decision": decision}
    if notes is not None:
        payload["notes"] = notes
    resp = api_client.review_test_pressing(tp_id, payload, make_customer_headers(customer_id))
    return get_success_data(resp)


def _list(resp):
    body = resp.json()
    return body["data"], body.get("meta", {})


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_queued_order(world: dict, quantity_ordered: int = 1000,
                        variants: list = None, order_over: dict = None,
                        tp_quantity: int = 5, release: dict = None) -> dict:
    """Create an order on a release (world['release'] unless `release` given)
    and drive DRAFT->...->QUEUED.

    Returns {"order", "tooling_job", "test_pressing"}."""
    customer_id = world["customer"]["id"]
    rel = release or world["release"]
    order = create_order(rel["id"], quantity_ordered=quantity_ordered,
                         variants=variants, **(order_over or {}))
    order = quote_order(order)
    order = confirm_order(order, customer_id)
    job = start_tooling(order["id"])
    job = drive_tooling_to_stamper_ready(job["id"], world["bath"]["id"])
    tp = produce_test_pressing(order["id"], quantity=tp_quantity)
    tp = ship_test_pressing(tp["id"])
    tp = review_test_pressing(tp["id"], customer_id, "APPROVE")
    order = get_order(order["id"])
    assert order["production_status"] == "QUEUED", (
        f"Setup drift: expected QUEUED, got {order['production_status']}"
    )
    return {"order": order, "tooling_job": job, "test_pressing": tp}


def schedule_order(order: dict, line_id: str, date: str = "2026-08-10",
                   start_hour: int = 0, end_hour: int = 8,
                   planned_units: int = None, slots: list = None) -> dict:
    """Commit slots for a QUEUED order. Returns the SCHEDULED order."""
    if slots is None:
        slots = [{
            "press_line_id": line_id,
            "date": date,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "planned_units": planned_units if planned_units is not None
            else order["quantity_ordered"] - order.get("accepted_units", 0),
        }]
    resp = api_client.commit_schedule(
        order["id"],
        {"expected_press_order_version": order["version"], "slots": slots},
        PLANNER,
    )
    return get_success_data(resp)


def press_run(order_id: str, slot_date: str = "2026-08-10") -> dict:
    """Advance the logical clock to the slot date and run START/COMPLETE_PRESSING."""
    set_clock(f"{slot_date}T00:00:00Z")
    get_success_data(api_client.post_production_event(
        order_id, {"event": "START_PRESSING"}, OPERATOR))
    resp = api_client.post_production_event(
        order_id, {"event": "COMPLETE_PRESSING"}, OPERATOR)
    return get_success_data(resp)


def file_qc_report(order_id: str, units_pressed: int, units_rejected: int,
                   filer: str = "qa-1") -> dict:
    resp = api_client.file_qc_report(
        order_id,
        {"units_pressed": units_pressed, "units_rejected": units_rejected},
        make_qa_headers(filer),
    )
    return get_success_data(resp)


def decide_qc_report(qc_id: str, decision: str = "ACCEPT", fault: str = "NONE",
                     decider: str = "pm-1") -> dict:
    resp = api_client.decide_qc_report(
        qc_id, {"decision": decision, "fault": fault}, make_pm_headers(decider)
    )
    return get_success_data(resp)


def create_completed_order(world: dict, quantity_ordered: int = 1000,
                           units_pressed: int = 1000, units_rejected: int = 30,
                           variants: list = None, order_over: dict = None,
                           slot_over: dict = None, qc_filer: str = "qa-1",
                           qc_decider: str = "pm-1") -> dict:
    """Full pipeline through QC ACCEPT. Order ends COMPLETED.

    Returns {"order", "qc_report", "tooling_job", "test_pressing"}."""
    staged = create_queued_order(world, quantity_ordered=quantity_ordered,
                                 variants=variants, order_over=order_over)
    order = schedule_order(staged["order"], world["line"]["id"], **(slot_over or {}))
    press_run(order["id"], slot_date=(slot_over or {}).get("date", "2026-08-10"))
    qc = file_qc_report(order["id"], units_pressed, units_rejected, filer=qc_filer)
    qc = decide_qc_report(qc["id"], "ACCEPT", "NONE", decider=qc_decider)
    order = get_order(order["id"])
    assert order["production_status"] == "COMPLETED", (
        f"Setup drift: expected COMPLETED, got {order['production_status']}"
    )
    return {"order": order, "qc_report": qc,
            "tooling_job": staged["tooling_job"], "test_pressing": staged["test_pressing"]}


def issue_standard_invoice(order_id: str) -> dict:
    resp = api_client.issue_invoice(order_id, BILLING)
    return get_success_data(resp)


def create_print_job(order_id: str, quantity: int = None, **overrides) -> dict:
    payload = create_print_job_payload(quantity=quantity, **overrides)
    return get_success_data(api_client.create_print_job(order_id, payload, CSR))


def suspend_customer(customer_id: str) -> dict:
    return get_success_data(
        api_client.set_credit_status(customer_id, {"action": "SUSPEND"}, BILLING)
    )


def reinstate_customer(customer_id: str) -> dict:
    return get_success_data(
        api_client.set_credit_status(customer_id, {"action": "REINSTATE"}, BILLING)
    )
