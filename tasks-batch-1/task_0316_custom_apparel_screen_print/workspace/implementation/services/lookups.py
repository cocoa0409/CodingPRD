"""Entity lookups with left-to-right existence validation (PRD §2.5).

A path that names more than one identifier is validated left-to-right; the
first identifier that does not resolve raises ERR_NOT_FOUND (404).
"""
from db import store
from errors import err


def get_shop(shop_id):
    shop = store.shops.get(shop_id)
    if shop is None:
        raise err("ERR_NOT_FOUND", "Shop not found")
    return shop


def get_customer(customer_id):
    cust = store.customers.get(customer_id)
    if cust is None:
        raise err("ERR_NOT_FOUND", "Customer not found")
    return cust


def get_decoration_method(method_id):
    m = store.decoration_methods.get(method_id)
    if m is None:
        raise err("ERR_NOT_FOUND", "DecorationMethod not found")
    return m


def get_garment_style(style_id):
    s = store.garment_styles.get(style_id)
    if s is None:
        raise err("ERR_NOT_FOUND", "GarmentStyle not found")
    return s


def get_blank_sku_under_style(style_id, blank_sku_id):
    """Validate style first (left), then the blank sku scoped to it (right)."""
    get_garment_style(style_id)
    sku = store.blank_skus.get(blank_sku_id)
    if sku is None or sku["garment_style_id"] != style_id:
        raise err("ERR_NOT_FOUND", "BlankSku not found")
    return sku


def get_blank_sku(blank_sku_id):
    sku = store.blank_skus.get(blank_sku_id)
    if sku is None:
        raise err("ERR_NOT_FOUND", "BlankSku not found")
    return sku


def get_press(press_id):
    p = store.presses.get(press_id)
    if p is None:
        raise err("ERR_NOT_FOUND", "Press not found")
    return p


def get_embroidery_station(station_id):
    s = store.embroidery_stations.get(station_id)
    if s is None:
        raise err("ERR_NOT_FOUND", "EmbroideryStation not found")
    return s


def get_order(order_id):
    o = store.orders.get(order_id)
    if o is None:
        raise err("ERR_NOT_FOUND", "Order not found")
    return o


def get_order_line(line_id):
    line = store.order_lines.get(line_id)
    if line is None:
        raise err("ERR_NOT_FOUND", "OrderLine not found")
    return line


def get_proof_under_order(order_id, proof_id):
    """Validate order first (left), then the proof scoped to it (right)."""
    get_order(order_id)
    proof = store.art_proofs.get(proof_id)
    if proof is None or proof["order_id"] != order_id:
        raise err("ERR_NOT_FOUND", "ArtProof not found")
    return proof


def get_run_under_order(order_id, run_id):
    get_order(order_id)
    run = store.production_runs.get(run_id)
    if run is None or run["order_id"] != order_id:
        raise err("ERR_NOT_FOUND", "ProductionRun not found")
    return run


def get_reservation(res_id):
    r = store.blank_reservations.get(res_id)
    if r is None:
        raise err("ERR_NOT_FOUND", "BlankReservation not found")
    return r


def get_production_run(run_id):
    r = store.production_runs.get(run_id)
    if r is None:
        raise err("ERR_NOT_FOUND", "ProductionRun not found")
    return r


# ---- Child-collection helpers ----

def lines_of_order(order_id):
    return [l for l in store.order_lines.values() if l["order_id"] == order_id]


def proofs_of_order(order_id):
    return [p for p in store.art_proofs.values() if p["order_id"] == order_id]


def reservations_of_order(order_id):
    return [r for r in store.blank_reservations.values() if r["order_id"] == order_id]


def active_reservations_of_order(order_id):
    return [r for r in reservations_of_order(order_id) if r["status"] == "ACTIVE"]


def runs_of_order(order_id):
    return [r for r in store.production_runs.values() if r["order_id"] == order_id]


def blank_skus_of_style(style_id):
    return [s for s in store.blank_skus.values() if s["garment_style_id"] == style_id]
