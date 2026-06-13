"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear
"Setup step failed" errors rather than confusing assertion failures.

Identity threading: every Customer-acting call that is ownership-gated (approve,
request-changes, pay, cancel-own) uses make_customer_headers(customer_id) with the
real Customer entity id — never the shared constant — so ownership checks pass.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_shop_payload,
    create_customer_payload,
    create_decoration_method_payload,
    create_garment_style_payload,
    create_blank_sku_payload,
    create_press_payload,
    create_embroidery_station_payload,
    create_order_payload,
    create_line_payload,
    create_art_proof_payload,
    approve_proof_payload,
    create_production_run_payload,
    complete_run_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_customer_headers

SM = TEST_USERS["shop_manager_headers"]
ART = TEST_USERS["art_staff_headers"]


# ─── Tier 1: Atomic catalog builders ──────────────────────────────────────────

def create_shop(**overrides) -> dict:
    """Create a Shop. Returns the Shop dict."""
    return get_success_data(api_client.create_shop(create_shop_payload(**overrides), SM))


def set_clock(shop_id: str, to_iso8601: str) -> dict:
    """Advance the shop clock to a fixed instant (PRD §2.7)."""
    return get_success_data(api_client.set_clock(set_clock_payload(shop_id, to_iso8601), SM))


def create_customer(shop_id: str, **overrides) -> dict:
    """Create a Customer beneath a shop."""
    return get_success_data(
        api_client.create_customer(create_customer_payload(shop_id, **overrides), SM)
    )


def create_method(shop_id: str, method_type: str = "SCREEN_PRINT", **overrides) -> dict:
    """Create a DecorationMethod."""
    return get_success_data(
        api_client.create_decoration_method(
            create_decoration_method_payload(shop_id, method_type, **overrides), SM
        )
    )


def create_style(shop_id: str, **overrides) -> dict:
    """Create a GarmentStyle."""
    return get_success_data(
        api_client.create_garment_style(create_garment_style_payload(shop_id, **overrides), SM)
    )


def create_sku(style_id: str, color: str = "BLACK", size: str = "L",
               total_stock_qty: int = 200, **overrides) -> dict:
    """Create a BlankSku under a style."""
    return get_success_data(
        api_client.create_blank_sku(
            style_id, create_blank_sku_payload(color, size, total_stock_qty, **overrides), SM
        )
    )


def create_press(shop_id: str, **overrides) -> dict:
    """Create a Press."""
    return get_success_data(api_client.create_press(create_press_payload(shop_id, **overrides), SM))


def create_station(shop_id: str, **overrides) -> dict:
    """Create an EmbroideryStation."""
    return get_success_data(
        api_client.create_embroidery_station(
            create_embroidery_station_payload(shop_id, **overrides), SM
        )
    )


# ─── Tier 2: Shop + catalog setup ─────────────────────────────────────────────

def setup_shop_catalog(clock=None, method_type="SCREEN_PRINT", method_overrides=None,
                       style_overrides=None, sku_color="BLACK", sku_size="L",
                       stock_qty=200, shop_overrides=None, with_sku=True):
    """Shop + (optional clock) + customer + method + style + (optional) sku.

    Returns a dict with keys: shop, customer, method, style, sku (or None).
    """
    shop = create_shop(**(shop_overrides or {}))
    if clock is not None:
        set_clock(shop["id"], clock)
    customer = create_customer(shop["id"])
    method = create_method(shop["id"], method_type, **(method_overrides or {}))
    style = create_style(shop["id"], **(style_overrides or {}))
    sku = create_sku(style["id"], sku_color, sku_size, stock_qty) if with_sku else None
    return {
        "shop": shop,
        "customer": customer,
        "method": method,
        "style": style,
        "sku": sku,
    }


# ─── Tier 3: Order composition ────────────────────────────────────────────────

def create_draft_order(shop_id: str, customer_id: str, actor=None, **order_overrides) -> dict:
    """Create a DRAFT order. actor defaults to ShopManager; pass customer headers
    when the order must be customer-owned for later ownership checks."""
    headers = actor if actor is not None else SM
    return get_success_data(
        api_client.create_order(create_order_payload(shop_id, customer_id, **order_overrides), headers)
    )


def add_line(order_id: str, style_id: str, method_id: str, size_run: dict,
             actor=None, **line_overrides) -> dict:
    """Add an OrderLine to a DRAFT order."""
    headers = actor if actor is not None else SM
    return get_success_data(
        api_client.create_line(
            order_id, create_line_payload(style_id, method_id, size_run, **line_overrides), headers
        )
    )


def create_proof(order_id: str, title="Front", art_hash="h1") -> dict:
    """Create a DRAFT ArtProof (by ArtStaff)."""
    return get_success_data(
        api_client.create_art_proof(order_id, create_art_proof_payload(title, art_hash), ART)
    )


def submit_proof(order_id: str, proof_id: str) -> dict:
    """Submit/resubmit a proof (ArtStaff)."""
    return get_success_data(api_client.submit_proof(order_id, proof_id, ART))


def approve_proof(order_id: str, proof_id: str, customer_id: str, expected_order_version: int) -> dict:
    """Approve a proof as the owning Customer with the OCC version (PRD §2.9)."""
    return get_success_data(
        api_client.approve_proof(
            order_id, proof_id, approve_proof_payload(expected_order_version),
            make_customer_headers(customer_id),
        )
    )


def setup_order_with_approved_proof(catalog: dict, size_run=None, line_overrides=None,
                                    order_overrides=None, customer_owned=False):
    """DRAFT order + one line + a proof walked to APPROVED.

    Returns dict: order, line, proof, plus carries catalog refs.
    The order's version captured at create is used as the OCC expected version.
    """
    size_run = size_run or {"L": 30}
    cust = catalog["customer"]
    cust_headers = make_customer_headers(cust["id"]) if customer_owned else SM

    order = create_draft_order(
        catalog["shop"]["id"], cust["id"], actor=cust_headers, **(order_overrides or {})
    )
    order_v = order["version"]
    line = add_line(
        order["id"], catalog["style"]["id"], catalog["method"]["id"], size_run,
        actor=cust_headers, **(line_overrides or {}),
    )
    proof = create_proof(order["id"])
    submit_proof(order["id"], proof["id"])
    approve_proof(order["id"], proof["id"], cust["id"], order_v)
    return {"order": order, "line": line, "proof": proof}


def setup_confirmed_order(catalog: dict, size_run=None, line_overrides=None,
                          order_overrides=None, customer_owned=False):
    """Order with approved proof, then CONFIRMED (reservations created, deposit set).

    Returns dict: order (the confirmed Order data), line, proof.
    """
    parts = setup_order_with_approved_proof(
        catalog, size_run, line_overrides, order_overrides, customer_owned
    )
    confirmed = get_success_data(api_client.confirm_order(parts["order"]["id"], SM))
    parts["order"] = confirmed
    return parts


def setup_started_run(catalog: dict, size_run=None, machine_id=None, machine_kind="press",
                      window_start="2026-06-02T10:00:00.000Z",
                      window_end="2026-06-02T12:00:00.000Z",
                      line_overrides=None, order_overrides=None):
    """Confirmed order + scheduled run + started run (blanks_pulled recorded).

    Returns dict: order, line, proof, run (started), machine_id.
    """
    parts = setup_confirmed_order(catalog, size_run, line_overrides, order_overrides)
    if machine_id is None:
        if machine_kind == "press":
            machine_id = create_press(catalog["shop"]["id"])["id"]
        else:
            machine_id = create_station(catalog["shop"]["id"])["id"]
    run_payload = create_production_run_payload(window_start, window_end)
    if machine_kind == "press":
        run_payload["press_id"] = machine_id
    else:
        run_payload["embroidery_station_id"] = machine_id
    run = get_success_data(api_client.create_production_run(parts["order"]["id"], run_payload, SM))
    run = get_success_data(api_client.start_run(parts["order"]["id"], run["id"], SM))
    parts["run"] = run
    parts["machine_id"] = machine_id
    return parts


def setup_fulfilled_order(catalog: dict, size_run=None, good_units=None, spoiled_units=0,
                          machine_kind="press", line_overrides=None, order_overrides=None):
    """Full lifecycle through FULFILLED (run completed with good_units >= ordered).

    good_units defaults to the sum of size_run quantities (the ordered total).
    Returns dict: order (FULFILLED), line, proof, run (COMPLETED), machine_id.
    """
    size_run = size_run or {"L": 30}
    if good_units is None:
        good_units = sum(size_run.values())
    parts = setup_started_run(
        catalog, size_run, machine_kind=machine_kind,
        line_overrides=line_overrides, order_overrides=order_overrides,
    )
    completed = get_success_data(
        api_client.complete_run(
            parts["order"]["id"], parts["run"]["id"],
            complete_run_payload(good_units, spoiled_units), SM,
        )
    )
    parts["run"] = completed
    parts["order"] = get_success_data(api_client.get_order(parts["order"]["id"], SM))
    return parts


def setup_invoiced_order(catalog: dict, size_run=None, good_units=None, spoiled_units=0,
                         line_overrides=None, order_overrides=None):
    """Full lifecycle through INVOICED. Returns dict: order (INVOICED), line, proof, run."""
    parts = setup_fulfilled_order(
        catalog, size_run, good_units, spoiled_units,
        line_overrides=line_overrides, order_overrides=order_overrides,
    )
    parts["order"] = get_success_data(api_client.invoice_order(parts["order"]["id"], SM))
    return parts


# ─── Tier 4: Reservation / SKU read helpers ───────────────────────────────────

def get_first_reservation(order_id: str) -> dict:
    """Return the order's first BlankReservation."""
    data, _meta = _list(api_client.list_reservations(order_id, SM))
    return data[0]


def get_sku(style_id: str, sku_id: str) -> dict:
    """Re-read a BlankSku to observe its current stock counters."""
    return get_success_data(api_client.get_blank_sku(style_id, sku_id, SM))


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, SM))


def get_quote(order_id: str) -> dict:
    """Return the order's ESTIMATE Quote. The quote endpoint returns an array;
    this returns the single Quote element."""
    data, _meta = _list(api_client.get_quote(order_id, SM))
    return data[0]


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, SM))


def _list(response):
    """Internal: read a list/array response's (data, meta) leniently for setup."""
    body = response.json()
    assert 200 <= response.status_code < 300, f"List failed: {response.text}"
    return body["data"], body.get("meta", {})
