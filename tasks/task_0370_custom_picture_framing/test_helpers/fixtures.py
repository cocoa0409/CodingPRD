"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the server starts against an empty database before each test.
Setup calls use get_success_data() (lenient) so setup failures surface clearly.

Role usage:
  - FrameDesigner: order/line intake, measure, void, quote, reorder
  - FrameProductionTech: workbench, task schedule/complete, start-production, mark-ready
  - FrontDeskClerk: payments, pickup, cancel
  - Customer: entity_backed reads (use make_customer_headers(customer_id))
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers
from .factories import (
    create_customer_payload,
    create_workbench_payload,
    create_order_payload,
    add_frame_line_payload,
    measure_payload,
    create_task_payload,
    payment_payload,
)

DESIGNER = TEST_USERS["frame_designer_headers"]
TECH = TEST_USERS["frame_production_tech_headers"]
CLERK = TEST_USERS["front_desk_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 1 / basic creation
# ---------------------------------------------------------------------------
def create_customer(loyalty_tier=None, email="cust@x.com", full_name="Cust", phone="555-0001"):
    """Create a Customer; defaults to STANDARD tier when loyalty_tier is None."""
    payload = create_customer_payload(full_name=full_name, email=email, phone=phone)
    if loyalty_tier is not None:
        payload["loyalty_tier"] = loyalty_tier
    return get_success_data(api_client.create_customer(payload, CLERK))


def create_workbench(bench_type="ASSEMBLY", clean_buffer_minutes=None, bench_name="Bench"):
    payload = create_workbench_payload(bench_name=bench_name, bench_type=bench_type)
    if clean_buffer_minutes is not None:
        payload["clean_buffer_minutes"] = clean_buffer_minutes
    return get_success_data(api_client.create_workbench(payload, TECH))


def create_order(customer_id, rush_requested=None, deposit_pct=None):
    payload = create_order_payload(customer_id)
    if rush_requested is not None:
        payload["rush_requested"] = rush_requested
    if deposit_pct is not None:
        payload["deposit_pct"] = deposit_pct
    return get_success_data(api_client.create_order(payload, DESIGNER))


def add_line(order_id, expected_order_version, **line_overrides):
    payload = add_frame_line_payload(expected_order_version, **line_overrides)
    return get_success_data(api_client.add_frame_line(order_id, payload, DESIGNER))


def measure_line(line_id, w, h):
    return get_success_data(api_client.measure_frame_line(line_id, measure_payload(w, h), DESIGNER))


def quote(order_id):
    return get_success_data(api_client.quote_order(order_id, DESIGNER))


def pay(order_id, kind, amount):
    return get_success_data(api_client.apply_payment(order_id, payment_payload(kind, amount), CLERK))


# ---------------------------------------------------------------------------
# Tier 2 / Tier 3 — quoted order with N lines, optionally measured/deposit-paid
# ---------------------------------------------------------------------------
def setup_order_with_line(customer_tier=None, rush_requested=None, deposit_pct=None,
                          line_overrides=None, measure_dims=None):
    """Create customer + order + one frame line.

    Returns (customer, order, line). If measure_dims=(w,h) is given, the line is
    measured (the returned line reflects the measured state). The order object is
    the freshly created INTAKE order (re-read with api to get latest version when
    needed via the captured version)."""
    line_overrides = line_overrides or {}
    cust = create_customer(loyalty_tier=customer_tier)
    order = create_order(cust["id"], rush_requested=rush_requested, deposit_pct=deposit_pct)
    line = add_line(order["id"], order["version"], **line_overrides)
    if measure_dims is not None:
        line = measure_line(line["id"], measure_dims[0], measure_dims[1])
    return cust, order, line


def setup_quoted_order(customer_tier=None, rush_requested=None, deposit_pct=None,
                       line_overrides=None, measure_dims=(8, 10)):
    """Customer + order + one measured line + QUOTE. Returns (customer, order_after_quote, line).

    measure_dims may be None to leave the line DRAFT (used for ERR_LINES_NOT_MEASURED-
    style setups where quote still needs >=1 non-void line — pass measure_dims=None only
    when the test does not require start-production)."""
    cust, order, line = setup_order_with_line(
        customer_tier=customer_tier, rush_requested=rush_requested,
        deposit_pct=deposit_pct, line_overrides=line_overrides, measure_dims=measure_dims,
    )
    quoted = quote(order["id"])
    return cust, quoted, line


def setup_deposit_paid_order(customer_tier=None, rush_requested=None, deposit_pct=0.30,
                             line_overrides=None, measure_dims=(8, 10), deposit_amount=None):
    """Customer + order + measured line + QUOTE + DEPOSIT paid (payment_status DEPOSIT_PAID).
    Returns (customer, order_after_quote, line). Re-read the order for latest fields.

    deposit_amount defaults to None, meaning "pay exactly the quoted order's
    deposit_required" (PRD §3.5: the deposit amount must be at least
    deposit_required, else ERR_DEPOSIT_TOO_LOW). Pass an explicit amount only when
    the test needs a specific deposit value."""
    cust, quoted, line = setup_quoted_order(
        customer_tier=customer_tier, rush_requested=rush_requested,
        deposit_pct=deposit_pct, line_overrides=line_overrides, measure_dims=measure_dims,
    )
    if deposit_amount is None:
        deposit_amount = quoted["deposit_required"]
    pay(quoted["id"], "DEPOSIT", deposit_amount)
    return cust, quoted, line


def setup_in_production_order(customer_tier=None, rush_requested=None, deposit_pct=0.30,
                              line_overrides=None, measure_dims=(8, 10), deposit_amount=None):
    """Customer + measured line + QUOTE + DEPOSIT + start-production (IN_PRODUCTION).
    Returns (customer, order, line)."""
    cust, quoted, line = setup_deposit_paid_order(
        customer_tier=customer_tier, rush_requested=rush_requested, deposit_pct=deposit_pct,
        line_overrides=line_overrides, measure_dims=measure_dims, deposit_amount=deposit_amount,
    )
    get_success_data(api_client.start_production(quoted["id"], TECH))
    return cust, quoted, line


def setup_ready_order(customer_tier=None, rush_requested=None, deposit_pct=0.30,
                      line_overrides=None, measure_dims=(8, 10), deposit_amount=None,
                      bench_type="ASSEMBLY", clean_buffer_minutes=None,
                      task_interval=(0, 30)):
    """Full chain to READY: customer + measured line + quote + deposit + start +
    one COMPLETED task + mark-ready. Returns (customer, ready_order, line, bench, task).
    ready_order is the mark-ready response (carries final_invoice_total)."""
    cust, quoted, line = setup_in_production_order(
        customer_tier=customer_tier, rush_requested=rush_requested, deposit_pct=deposit_pct,
        line_overrides=line_overrides, measure_dims=measure_dims, deposit_amount=deposit_amount,
    )
    bench = create_workbench(bench_type=bench_type, clean_buffer_minutes=clean_buffer_minutes)
    task = get_success_data(api_client.create_task(
        create_task_payload(quoted["id"], bench["id"], task_interval[0], task_interval[1]), TECH))
    get_success_data(api_client.complete_task(task["id"], TECH))
    ready = get_success_data(api_client.mark_ready(quoted["id"], TECH))
    return cust, ready, line, bench, task


def setup_picked_up_order(deposit_pct=0.30, deposit_amount=25.00, balance_amount=39.47,
                          measure_dims=(8, 10)):
    """Full chain to PICKED_UP. Returns (customer, picked_up_order, line, bench, task)."""
    cust, ready, line, bench, task = setup_ready_order(
        deposit_pct=deposit_pct, deposit_amount=deposit_amount, measure_dims=measure_dims)
    pay(ready["id"], "BALANCE", balance_amount)
    picked = get_success_data(api_client.pickup_order(ready["id"], CLERK))
    return cust, picked, line, bench, task


# ---------------------------------------------------------------------------
# Fragile-order helpers (museum-glass line forces glass-cutting bench)
# ---------------------------------------------------------------------------
def setup_fragile_in_production_order(deposit_pct=0.50, deposit_amount=200.00,
                                      measure_dims=(16, 20)):
    """Customer + one MUSEUM (fragile) measured 16x20 line + quote + deposit + start.
    Returns (customer, order, line). has_fragile_line is true."""
    cust, quoted, line = setup_in_production_order(
        deposit_pct=deposit_pct, deposit_amount=deposit_amount, measure_dims=measure_dims,
        line_overrides={"glass_type": "MUSEUM", "molding_rate_per_ui": 0.45,
                        "nominal_width_in": 16, "nominal_height_in": 20},
    )
    return cust, quoted, line


# ---------------------------------------------------------------------------
# Multi-line helper (for combinatorial rounding test)
# ---------------------------------------------------------------------------
def add_and_measure_lines(order_id, start_version, line_specs):
    """Add a sequence of lines (each spec is a dict of frame-line overrides plus an
    optional 'measure' tuple). Threads expected_order_version across adds, re-reading
    the order version after each add. Returns list of created line dicts (post-measure)."""
    lines = []
    current_version = start_version
    pending_measures = []
    for spec in line_specs:
        spec = dict(spec)
        measure = spec.pop("measure", None)
        ln = add_line(order_id, current_version, **spec)
        order = get_success_data(api_client.get_order(order_id, DESIGNER))
        current_version = order["version"]
        if measure is not None:
            pending_measures.append((ln["id"], measure))
        lines.append(ln)
    measured = []
    for line_id, (w, h) in pending_measures:
        measured.append(measure_line(line_id, w, h))
    # Re-fetch lines to reflect measured state where applicable.
    refreshed = []
    for ln in lines:
        refreshed.append(get_success_data(api_client.get_frame_line(ln["id"], DESIGNER)))
    return refreshed


# Convenience headers re-export for tests that need ownership-gated customer reads.
__all__ = [
    "create_customer", "create_workbench", "create_order", "add_line", "measure_line",
    "quote", "pay", "setup_order_with_line", "setup_quoted_order", "setup_deposit_paid_order",
    "setup_in_production_order", "setup_ready_order", "setup_picked_up_order",
    "setup_fragile_in_production_order", "add_and_measure_lines",
    "make_customer_headers", "DESIGNER", "TECH", "CLERK",
]
