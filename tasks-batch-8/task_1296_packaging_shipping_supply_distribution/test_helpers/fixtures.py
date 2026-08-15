"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly started server with an empty database).
Setup calls use the lenient get_success_data() so failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: Buyer and AccountApprover are entity-backed by Account, so
every ownership-gated call passes make_buyer_headers(account["id"]) or
make_approver_headers(account["id"]) — never the shared fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_account_payload,
    create_inventory_payload,
    create_order_line_payload,
    create_order_payload,
    create_product_payload,
    create_restock_notification_payload,
    create_return_payload,
    create_warehouse_payload,
)
from .test_users import TEST_USERS, make_buyer_headers

ADMIN = TEST_USERS["platform_admin_headers"]
CATALOG = TEST_USERS["catalog_manager_headers"]
OPS = TEST_USERS["warehouse_ops_headers"]
SERVICE = TEST_USERS["customer_service_headers"]

CLOCK_MON_AM = "2026-08-03T10:00:00Z"  # Monday morning UTC


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def set_clock(iso_ts: str) -> dict:
    """Advance the logical clock (PlatformAdmin-only, test-driving capability)."""
    resp = api_client.set_clock({"to_iso8601": iso_ts}, ADMIN)
    data = get_success_data(resp)
    assert data is not None, f"Setup failed: set_clock({iso_ts})"
    return data


def create_warehouse(code="ATL", name=None, zone=2, ship_cutoff_time="15:00",
                     timezone="America/New_York", **overrides) -> dict:
    name = name or {"ATL": "Atlanta DC", "RNO": "Reno DC", "DFW": "Dallas DC"}.get(code, f"{code} DC")
    payload = create_warehouse_payload(code=code, name=name, zone=zone,
                                       ship_cutoff_time=ship_cutoff_time,
                                       timezone=timezone, **overrides)
    data = get_success_data(api_client.create_warehouse(payload, ADMIN))
    assert data and data.get("id"), f"Setup failed: create_warehouse({code})"
    return data


def create_account(po_required=False, credit_limit_cents=100_000_000,
                   company_name="Acme Corp", account_type="CORPORATE",
                   default_warehouse_code="ATL", **overrides) -> dict:
    payload = create_account_payload(company_name=company_name,
                                     account_type=account_type,
                                     credit_limit_cents=credit_limit_cents,
                                     default_warehouse_code=default_warehouse_code,
                                     po_required=po_required, **overrides)
    data = get_success_data(api_client.create_account(payload, ADMIN))
    assert data and data.get("id"), f"Setup failed: create_account({company_name})"
    return data


def create_stock_product(sku="BX-100", base_price_cents=1000, pallet_qty=500,
                         weight_lbs_per_unit=10, density_pcf=20, category="BOXES",
                         uom="EACH", case_qty=1, name=None, **overrides) -> dict:
    payload = create_product_payload(sku=sku, name=name or sku, category=category,
                                     base_price_cents=base_price_cents, uom=uom,
                                     case_qty=case_qty, pallet_qty=pallet_qty,
                                     weight_lbs_per_unit=weight_lbs_per_unit,
                                     density_pcf=density_pcf, **overrides)
    data = get_success_data(api_client.create_product(payload, CATALOG))
    assert data and data.get("id"), f"Setup failed: create_stock_product({sku})"
    return data


def create_custom_product(sku="BX-C1", base_price_cents=1000, lead_time_days=3,
                          pallet_qty=500, weight_lbs_per_unit=5, density_pcf=20,
                          category="BOXES", name=None, **overrides) -> dict:
    payload = create_product_payload(sku=sku, name=name or sku, category=category,
                                     base_price_cents=base_price_cents,
                                     pallet_qty=pallet_qty,
                                     weight_lbs_per_unit=weight_lbs_per_unit,
                                     density_pcf=density_pcf,
                                     is_custom_print=True,
                                     lead_time_days=lead_time_days, **overrides)
    data = get_success_data(api_client.create_product(payload, CATALOG))
    assert data and data.get("id"), f"Setup failed: create_custom_product({sku})"
    return data


def create_inventory(product_id, warehouse_id, on_hand_qty, backorderable=False,
                     reorder_point_qty=0, **overrides) -> dict:
    payload = create_inventory_payload(product_id=product_id, warehouse_id=warehouse_id,
                                       on_hand_qty=on_hand_qty,
                                       backorderable=backorderable,
                                       reorder_point_qty=reorder_point_qty, **overrides)
    data = get_success_data(api_client.create_inventory(payload, OPS))
    assert data and data.get("id"), "Setup failed: create_inventory"
    return data


def create_subscription(account_id, product_id) -> dict:
    payload = create_restock_notification_payload(account_id=account_id, product_id=product_id)
    data = get_success_data(api_client.create_restock_notification(
        payload, make_buyer_headers(account_id)))
    assert data and data.get("id"), "Setup failed: create_restock_notification"
    return data


# ---------------------------------------------------------------------------
# Tier 2: account + warehouse world
# ---------------------------------------------------------------------------

def setup_warehouse_and_account(po_required=False, credit_limit_cents=100_000_000,
                                company_name="Acme Corp", warehouse_code="ATL",
                                warehouse_zone=2, **warehouse_overrides):
    """Warehouse (default ATL zone 2) plus a CORPORATE account preferring it."""
    wh = create_warehouse(code=warehouse_code, zone=warehouse_zone, **warehouse_overrides)
    acct = create_account(po_required=po_required, credit_limit_cents=credit_limit_cents,
                          company_name=company_name, default_warehouse_code=warehouse_code)
    return wh, acct


# ---------------------------------------------------------------------------
# Tier 3: order drafting and submission
# ---------------------------------------------------------------------------

def create_draft_order(account_id, ship_zone=5, po_number=None) -> dict:
    payload = create_order_payload(account_id=account_id, ship_zone=ship_zone)
    if po_number is not None:
        payload["po_number"] = po_number
    data = get_success_data(api_client.create_order(payload, make_buyer_headers(account_id)))
    assert data and data.get("id"), "Setup failed: create_draft_order"
    return data


def add_line(order_id, account_id, product_id, qty, **extra) -> dict:
    payload = create_order_line_payload(product_id=product_id, qty=qty, **extra)
    data = get_success_data(api_client.add_order_line(
        order_id, payload, make_buyer_headers(account_id)))
    assert data and data.get("id"), f"Setup failed: add_line(qty={qty})"
    return data


def submit_order(order_id, account_id) -> dict:
    data = get_success_data(api_client.submit_order(order_id, make_buyer_headers(account_id)))
    assert data and data.get("id"), f"Setup failed: submit_order({order_id})"
    return data


def ship_order(order_id) -> dict:
    data = get_success_data(api_client.ship_order(order_id, OPS))
    assert data and data.get("id"), f"Setup failed: ship_order({order_id})"
    return data


def setup_submitted_stock_order(qty=100, on_hand=500, ship_zone=5,
                                base_price_cents=1000, pallet_qty=500,
                                weight_lbs_per_unit=10, density_pcf=20,
                                sku="BX-100", po_required=False, po_number=None,
                                clock=CLOCK_MON_AM, reorder_point_qty=0,
                                backorderable=False, credit_limit_cents=100_000_000,
                                account_type="CORPORATE") -> dict:
    """Warehouse + account + stocked product + one-line order submitted.

    Returns a namespace dict: warehouse, account, product, inventory, order
    (post-submit), line, buyer_headers.
    """
    wh, acct = setup_warehouse_and_account(po_required=po_required,
                                           credit_limit_cents=credit_limit_cents,
                                           account_type=account_type)
    prod = create_stock_product(sku=sku, base_price_cents=base_price_cents,
                                pallet_qty=pallet_qty,
                                weight_lbs_per_unit=weight_lbs_per_unit,
                                density_pcf=density_pcf)
    inv = create_inventory(prod["id"], wh["id"], on_hand,
                           backorderable=backorderable,
                           reorder_point_qty=reorder_point_qty)
    if clock:
        set_clock(clock)
    order = create_draft_order(acct["id"], ship_zone=ship_zone, po_number=po_number)
    line = add_line(order["id"], acct["id"], prod["id"], qty)
    submitted = submit_order(order["id"], acct["id"])
    return {
        "warehouse": wh, "account": acct, "product": prod, "inventory": inv,
        "order": submitted, "line": line,
        "buyer_headers": make_buyer_headers(acct["id"]),
    }


def setup_shipped_stock_order(**kwargs) -> dict:
    """setup_submitted_stock_order + ship. Namespace gains 'shipped' order."""
    ctx = setup_submitted_stock_order(**kwargs)
    ctx["shipped"] = ship_order(ctx["order"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: custom-print production
# ---------------------------------------------------------------------------

def find_job_for_line(line_id, status=None) -> dict:
    """Return the first custom print job for the line (optionally status-filtered)."""
    params = {"order_line_id": line_id}
    if status:
        params["status"] = status
    rows = get_success_data(api_client.list_custom_print_jobs(ADMIN, params=params))
    assert isinstance(rows, list) and rows, f"Setup failed: no print job for line {line_id}"
    return rows[0]


def run_job_to_printing(job_id) -> dict:
    """QUEUED -> PLATING -> PRINTING. Returns the PRINTING job."""
    get_success_data(api_client.start_custom_print_job(job_id, OPS))
    data = get_success_data(api_client.advance_custom_print_job(job_id, OPS))
    assert data and data.get("status") == "PRINTING", f"Setup failed: run_job_to_printing({job_id})"
    return data


def complete_print_job(job_id, actual_qty, receive_note=None) -> dict:
    """Start + advance + receive with actual_qty. Returns the post-receive job."""
    run_job_to_printing(job_id)
    payload = {"actual_qty": actual_qty}
    if receive_note is not None:
        payload["receive_note"] = receive_note
    return get_success_data(api_client.receive_custom_print_job(job_id, payload, OPS))


def setup_custom_order_with_job(qty=10, lead_time_days=3, tolerance_pct=10,
                                base_price_cents=1000, sku="BX-C1", pallet_qty=500,
                                weight_lbs_per_unit=5, density_pcf=20,
                                ship_zone=5, clock=CLOCK_MON_AM,
                                artwork="art-1", credit_limit_cents=100_000_000,
                                po_required=False, po_number=None,
                                category="BOXES", name=None) -> dict:
    """Warehouse + account + custom product + submitted order with a QUEUED job.

    Returns namespace: warehouse, account, product, order (CUSTOM_PRODUCTION),
    line, job (QUEUED), buyer_headers.
    """
    wh, acct = setup_warehouse_and_account(po_required=po_required,
                                           credit_limit_cents=credit_limit_cents)
    prod = create_custom_product(sku=sku, base_price_cents=base_price_cents,
                                 lead_time_days=lead_time_days, pallet_qty=pallet_qty,
                                 weight_lbs_per_unit=weight_lbs_per_unit,
                                 density_pcf=density_pcf, category=category,
                                 name=name)
    if clock:
        set_clock(clock)
    order = create_draft_order(acct["id"], ship_zone=ship_zone, po_number=po_number)
    line = add_line(order["id"], acct["id"], prod["id"], qty,
                    print_artwork_ref=artwork, over_under_tolerance_pct=tolerance_pct)
    submitted = submit_order(order["id"], acct["id"])
    job = find_job_for_line(line["id"])
    return {
        "warehouse": wh, "account": acct, "product": prod,
        "order": submitted, "line": line, "job": job,
        "buyer_headers": make_buyer_headers(acct["id"]),
    }


def setup_shipped_custom_order(actual_qty=None, **kwargs) -> dict:
    """Custom order taken through production and ship. Namespace gains 'shipped'."""
    ctx = setup_custom_order_with_job(**kwargs)
    produced = actual_qty if actual_qty is not None else ctx["line"]["qty"]
    complete_print_job(ctx["job"]["id"], produced)
    ctx["shipped"] = ship_order(ctx["order"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: returns
# ---------------------------------------------------------------------------

def request_return(order_id, account_id, lines, return_type="STOCK",
                   reason_code="CHANGED_MIND") -> dict:
    payload = create_return_payload(order_id=order_id, return_type=return_type,
                                    reason_code=reason_code, lines=lines)
    data = get_success_data(api_client.create_return(payload, make_buyer_headers(account_id)))
    assert data and data.get("id"), "Setup failed: request_return"
    return data


def approve_return(return_id) -> dict:
    data = get_success_data(api_client.approve_return(return_id, SERVICE))
    assert data and data.get("id"), f"Setup failed: approve_return({return_id})"
    return data
