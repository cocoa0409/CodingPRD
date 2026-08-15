"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints. Setup calls use get_success_data() so a
setup failure surfaces as a clear "Setup step failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_account_payload,
    create_booking_payload,
    create_branch_payload,
    create_delivery_slot_payload,
    create_kit_payload,
    create_order_line_payload,
    create_order_payload,
    create_product_payload,
    create_program_payload,
    create_quote_payload,
    create_quote_revision_payload,
    create_return_payload,
    create_sheet_payload,
    create_stage_kit_payload,
    create_stock_record_payload,
)
from .test_users import (
    TEST_USERS,
    make_contractor_headers,
    make_counterrep_headers,
    make_manager_headers,
)

MANAGER = TEST_USERS["manager_headers"]
REP = TEST_USERS["counterrep_headers"]
SALES = TEST_USERS["sales_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


# ─── Tier 1: single-resource creators ───────────────────────────────────────

def make_branch(code: str = TEST_DEFAULTS["BRANCH_CODE"], name: str = TEST_DEFAULTS["BRANCH_NAME"]):
    """Create a branch. Returns the Branch."""
    return get_success_data(api_client.create_branch(create_branch_payload(name=name, code=code), MANAGER))


def make_product(sku: str = TEST_DEFAULTS["SKU"], **overrides):
    """Create a catalog product. Returns the Product."""
    return get_success_data(api_client.create_product(create_product_payload(sku=sku, **overrides), MANAGER))


def make_account(**overrides):
    """Open a contractor account. Returns the ContractorAccount."""
    return get_success_data(api_client.create_account(create_account_payload(**overrides), SALES))


def make_stock(branch_id: str, product_id: str, on_hand: int):
    """Create the (branch, product) inventory record. Returns InventoryStock."""
    return get_success_data(api_client.create_stock_record(
        branch_id, create_stock_record_payload(product_id, initial_on_hand=on_hand), WAREHOUSE
    ))


def receive_stock(branch_id: str, product_id: str, qty: int, unit_cost_cents: int):
    """Post a one-line stock receipt. Returns the StockReceipt."""
    return get_success_data(api_client.create_stock_receipt(
        branch_id, {"lines": [{"product_id": product_id, "qty": qty, "unit_cost_cents": unit_cost_cents}]},
        WAREHOUSE,
    ))


def set_clock(to_iso8601: str):
    """Advance the logical clock (BranchManager-only test-driving capability)."""
    return get_success_data(api_client.set_clock(to_iso8601, MANAGER))


def get_stock_row(branch_id: str, product_id: str):
    """Read the (branch, product) stock row via the branch inventory list."""
    data = get_success_data(api_client.list_branch_inventory(
        branch_id, WAREHOUSE, params={"product_id": product_id}
    ))
    rows = data if isinstance(data, list) else data.get("data", [])
    assert len(rows) == 1, f"expected exactly one stock row for {product_id}, got {len(rows)}"
    return rows[0]


def get_order_line(line_id: str, order_id: str):
    """Read one order line via the order's lines list."""
    data = get_success_data(api_client.get_order_lines(order_id, SALES))
    rows = data if isinstance(data, list) else data.get("data", [])
    for row in rows:
        if row["id"] == line_id:
            return row
    raise AssertionError(f"line {line_id} not found in order {order_id}")


# ─── Tier 2: common hierarchy ────────────────────────────────────────────────

def setup_branch_product_account(
    sku: str = TEST_DEFAULTS["SKU"],
    product_overrides: dict | None = None,
    account_overrides: dict | None = None,
    stock: int | None = None,
):
    """Branch + product + account (+ optional stock record).

    Returns (branch, product, account).
    """
    branch = make_branch()
    product = make_product(sku=sku, **(product_overrides or {}))
    account = make_account(**(account_overrides or {}))
    if stock is not None:
        make_stock(branch["id"], product["id"], stock)
    return branch, product, account


# ─── Tier 3: order lifecycle shortcuts ───────────────────────────────────────

def create_draft_order(account_id: str, branch_id: str, lines: list, **order_overrides):
    """COUNTER order in DRAFT with the given [(product_id, qty, **line_kwargs)] lines.

    Returns (order, line_ids).
    """
    order = get_success_data(api_client.create_order(
        create_order_payload(account_id, branch_id, **order_overrides), REP
    ))
    line_ids = []
    for spec in lines:
        product_id, qty = spec[0], spec[1]
        line_kwargs = spec[2] if len(spec) > 2 else {}
        line = get_success_data(api_client.add_order_line(
            order["id"], create_order_line_payload(product_id, qty, **line_kwargs), REP
        ))
        line_ids.append(line["id"])
    return order, line_ids


def create_submitted_order(account_id: str, branch_id: str, lines: list, **order_overrides):
    """Order taken through submit (fulfillment OPEN or PICKING). Returns (order, line_ids)."""
    order, line_ids = create_draft_order(account_id, branch_id, lines, **order_overrides)
    submitted = get_success_data(api_client.submit_order(order["id"], REP))
    return submitted, line_ids


def create_picked_up_order(account_id: str, branch_id: str, lines: list, **order_overrides):
    """Will-call order driven to PICKED_UP / INVOICED. Returns (order, line_ids)."""
    order_overrides.setdefault("will_call", True)
    order, line_ids = create_submitted_order(account_id, branch_id, lines, **order_overrides)
    get_success_data(api_client.mark_staged(order["id"], WAREHOUSE))
    picked = get_success_data(api_client.pickup_order(order["id"], REP))
    return picked, line_ids


def create_delivered_order(account_id: str, branch_id: str, lines: list,
                           slot_id: str | None = None, **order_overrides):
    """Delivery order driven to DELIVERED / INVOICED. Returns (order, line_ids)."""
    order_overrides.setdefault("will_call", False)
    order, line_ids = create_submitted_order(account_id, branch_id, lines, **order_overrides)
    if slot_id is None:
        slot = get_success_data(api_client.create_delivery_slot(
            branch_id, create_delivery_slot_payload(capacity_cubes=10000), MANAGER
        ))
        slot_id = slot["id"]
    get_success_data(api_client.book_delivery(
        order["id"], create_booking_payload(slot_id, order["version"]), REP
    ))
    get_success_data(api_client.mark_staged(order["id"], WAREHOUSE))
    get_success_data(api_client.dispatch_order(order["id"], WAREHOUSE))
    delivered = get_success_data(api_client.confirm_delivery(order["id"], WAREHOUSE))
    return delivered, line_ids


def create_backordered_line(account_id: str, branch_id: str, product_id: str, qty: int,
                            **order_overrides):
    """Order whose single line is BACKORDERED (no stock). Returns (order, line_id)."""
    order, line_ids = create_submitted_order(
        account_id, branch_id, [(product_id, qty)], **order_overrides
    )
    return order, line_ids[0]


# ─── Tier 3b: quotes and sheets ──────────────────────────────────────────────

def create_quoted(account_id: str, branch_id: str, lines: list, **overrides):
    """Quote in DRAFT. lines = [{product_id, qty, unit_price_cents}]. Returns Quote."""
    return get_success_data(api_client.create_quote(
        create_quote_payload(account_id, branch_id, lines, **overrides), SALES
    ))


def create_awarded_quote(account_id: str, branch_id: str, lines: list, **overrides):
    """Quote driven DRAFT -> SUBMITTED -> AWARDED. Returns the awarded Quote."""
    quote = create_quoted(account_id, branch_id, lines, **overrides)
    get_success_data(api_client.submit_quote(quote["id"], SALES))
    return get_success_data(api_client.award_quote(quote["id"], make_contractor_headers(account_id)))


def create_presented_sheet(account_id: str, branch_id: str, selections: list, **overrides):
    """Selection sheet driven to PRESENTED. Returns the SelectionSheet."""
    sheet = get_success_data(api_client.create_sheet(
        create_sheet_payload(account_id, branch_id, selections, **overrides), SALES
    ))
    return get_success_data(api_client.present_sheet(sheet["id"], SALES))


def create_approved_sheet(account_id: str, branch_id: str, selections: list, **overrides):
    """Selection sheet driven to APPROVED. Returns the SelectionSheet."""
    sheet = create_presented_sheet(account_id, branch_id, selections, **overrides)
    return get_success_data(api_client.approve_sheet(sheet["id"], make_contractor_headers(account_id)))


# ─── Tier 3c: returns ────────────────────────────────────────────────────────

def create_submitted_return(order_id: str, lines: list, submitted_by: str = "rep-1"):
    """Return request in SUBMITTED. lines = [{order_line_id, qty}]. Returns ReturnRequest."""
    headers = make_counterrep_headers(submitted_by)
    ret = get_success_data(api_client.create_return(
        create_return_payload(order_id, lines), headers
    ))
    return get_success_data(api_client.submit_return(ret["id"], headers))


def create_approved_return(order_id: str, lines: list, submitted_by: str = "rep-1",
                           decided_by: str = "mgr-9"):
    """Return request in APPROVED (segregation of duties respected)."""
    ret = create_submitted_return(order_id, lines, submitted_by=submitted_by)
    return get_success_data(api_client.decide_return(
        ret["id"], {"decision": "APPROVE"}, make_manager_headers(decided_by)
    ))


def create_credited_return(order_id: str, lines: list, submitted_by: str = "rep-1",
                           decided_by: str = "mgr-9"):
    """Return request driven to CREDITED (restock + account credit posted)."""
    ret = create_approved_return(order_id, lines, submitted_by=submitted_by, decided_by=decided_by)
    return get_success_data(api_client.receive_return(ret["id"], WAREHOUSE))


# ─── Tier 4: compound domain states ──────────────────────────────────────────

def create_kitted_order(account_id: str, branch_id: str, product_id: str,
                        num_lines: int = 1, qty_per_line: int = 1):
    """Will-call order submitted with `num_lines` allocated lines, one kit per line.

    Returns (order, line_ids, kit_ids). Kits auto-assemble because the member
    lines are ALLOCATED at kit creation.
    """
    order, line_ids = create_submitted_order(
        account_id, branch_id, [(product_id, qty_per_line) for _ in range(num_lines)],
        will_call=True,
    )
    kit_ids = []
    for i, line_id in enumerate(line_ids):
        kit = get_success_data(api_client.create_kit(
            order["id"], create_kit_payload([line_id], floor_label=f"F{i + 1}"), SALES
        ))
        kit_ids.append(kit["id"])
    order = get_success_data(api_client.get_order(order["id"], SALES))
    return order, line_ids, kit_ids


def stage_kit(kit_id: str, bin_label: str = "B1", window_start: str = "2026-08-02T08:00:00Z",
              window_end: str = "2026-08-02T10:00:00Z"):
    """Stage an ASSEMBLED kit into a bin. Returns the staged Kit."""
    return get_success_data(api_client.stage_kit(
        kit_id, create_stage_kit_payload(
            staging_bin=bin_label, window_start=window_start, window_end=window_end
        ), WAREHOUSE
    ))


def make_slot(branch_id: str, **overrides):
    """Define a truck delivery window. Returns the DeliverySlot."""
    return get_success_data(api_client.create_delivery_slot(
        branch_id, create_delivery_slot_payload(**overrides), MANAGER
    ))


def book_order(order, slot_id: str):
    """Book a submitted order into a slot using the order's current version."""
    return get_success_data(api_client.book_delivery(
        order["id"], create_booking_payload(slot_id, order["version"]), REP
    ))


def make_program(**overrides):
    """Create a manufacturer stocking program. Returns the ManufacturerProgram."""
    return get_success_data(api_client.create_program(create_program_payload(**overrides), MANAGER))


def revise_quote(quote_id: str, expected_quote_version: int, **overrides):
    """Create a superseding revision of an AWARDED quote. Returns the new Quote (DRAFT)."""
    return get_success_data(api_client.create_quote_revision(
        quote_id, create_quote_revision_payload(expected_quote_version, **overrides), SALES
    ))
