"""CountSession finalize: closing units, theoretical/actual depletion, variance
(PRD §3.7, depletion_variance calc).

Sales are recorded with a sold_at timestamp; to compute theoretical depletion
within a half-open window we keep an in-memory ledger of individual sales events
(menu_item_id, quantity, sold_at) alongside the cumulative units_sold counter.
Posted-invoice receipts are likewise queried by their post timestamp.
"""
from db import db, touch
from money import D, round_cents, round_half_up, to_number
from services.calc import resolve_closing_units
from services.product import set_on_hand
from timeutil import parse_iso

# In-memory sales ledger: list of dicts {menu_item_id, quantity, sold_at(dt), _seq}
SALES_LEDGER = []

# In-memory record of invoice post events: invoice_id -> posted_at (dt)
# stored on the invoice record as "_posted_at" (an internal field).


def record_sale(menu_item_id, quantity, sold_at_dt):
    SALES_LEDGER.append({
        "menu_item_id": menu_item_id,
        "quantity": int(quantity),
        "sold_at": sold_at_dt,
    })


def _prior_finalized_for_product(product_id, this_counted_at, exclude_session_id):
    """Most recent FINALIZED CountSession (counted_at < this_counted_at) that
    contains a CountLine for product_id. Returns (session, closing_units) or
    (None, 0)."""
    best_session = None
    best_dt = None
    for cs in db.count_sessions.values():
        if cs["id"] == exclude_session_id:
            continue
        if cs["status"] != "FINALIZED":
            continue
        cdt = cs["_counted_at_dt"]
        if not (cdt < this_counted_at):
            continue
        # does it contain this product?
        has = any(cl["count_session_id"] == cs["id"] and cl["product_id"] == product_id
                  for cl in db.count_lines.values())
        if not has:
            continue
        if best_dt is None or cdt > best_dt:
            best_dt = cdt
            best_session = cs
    if best_session is None:
        return None, D(0)
    prior_closing = D(0)
    for cl in db.count_lines.values():
        if cl["count_session_id"] == best_session["id"] and cl["product_id"] == product_id:
            prior_closing = D(cl["closing_units"])
            break
    return best_session, prior_closing


def _received_since(product_id, window_start, window_end):
    """Sum of InvoiceLine.received_qty for this product across invoices that
    POSTED within the half-open window (window_start, window_end]. If there is
    no prior finalized session, window_start is None (open-ended start)."""
    total = D(0)
    for inv in db.invoices.values():
        posted_at = inv.get("_posted_at")
        if posted_at is None:
            continue
        if window_start is not None and not (posted_at > window_start):
            continue
        if not (posted_at <= window_end):
            continue
        for il in db.invoice_lines.values():
            if il["invoice_id"] == inv["id"] and il["product_id"] == product_id:
                total += D(il["received_qty"])
    return total


def _theoretical_units(product_id, window_start, window_end):
    """Sum over each ACTIVE MenuItem selling a PUBLISHED recipe that contains
    this product: units_sold_in_window * pour_ml / container_volume_ml.
    Rounded half-up to 4 dp at the end (PRD §3.7)."""
    product = db.products.get(product_id)
    if product is None:
        return D(0)
    container_volume = D(product["container_volume_ml"])
    acc = D(0)
    for mi in db.menu_items.values():
        if mi["status"] != "ACTIVE":
            continue
        recipe = db.recipes.get(mi["recipe_id"])
        if recipe is None or recipe["status"] != "PUBLISHED":
            continue
        # find this product's pour_ml in the recipe
        pour_ml = None
        for rl in db.recipe_lines.values():
            if rl["recipe_id"] == recipe["id"] and rl["product_id"] == product_id:
                pour_ml = D(rl["pour_ml"])
                break
        if pour_ml is None:
            continue
        units_in_window = _menu_item_units_in_window(mi["id"], window_start, window_end)
        if units_in_window == 0:
            continue
        acc += D(units_in_window) * pour_ml / container_volume
    return round_half_up(acc, 4)


def _menu_item_units_in_window(menu_item_id, window_start, window_end):
    total = 0
    for sale in SALES_LEDGER:
        if sale["menu_item_id"] != menu_item_id:
            continue
        sdt = sale["sold_at"]
        if window_start is not None and not (sdt > window_start):
            continue
        if not (sdt <= window_end):
            continue
        total += sale["quantity"]
    return total


def compute_finalize(session):
    """Resolve every CountLine, compute theoretical/actual depletion + variance,
    roll up total_variance_cost_cents, overwrite each product's on_hand_units,
    recompute needs_reorder. Returns nothing; mutates in place. WEIGHT tare
    violations raise ERR_WEIGHT_BELOW_TARE (re-checked at finalize)."""
    this_counted_at = session["_counted_at_dt"]
    lines = [cl for cl in db.count_lines.values() if cl["count_session_id"] == session["id"]]
    lines.sort(key=lambda cl: (cl["created_at"], cl["_seq"]))
    total_variance = 0
    for cl in lines:
        product = db.products.get(cl["product_id"])
        # closing_units (re-checks WEIGHT tare at finalize)
        closing = resolve_closing_units(cl, product)
        cl["closing_units"] = closing
        # window per product
        prior_session, prior_closing = _prior_finalized_for_product(
            cl["product_id"], this_counted_at, session["id"])
        window_start = prior_session["_counted_at_dt"] if prior_session is not None else None
        window_end = this_counted_at
        received_since = _received_since(cl["product_id"], window_start, window_end)
        theoretical = _theoretical_units(cl["product_id"], window_start, window_end)
        cl["theoretical_units"] = to_number(theoretical)
        actual_depletion = prior_closing + received_since - D(closing)
        variance_units = round_half_up(actual_depletion - theoretical, 4)
        cl["variance_units"] = to_number(variance_units)
        variance_cost = round_cents(variance_units * D(product["unit_cost_cents"]))
        cl["variance_cost_cents"] = variance_cost
        total_variance += variance_cost
    session["total_variance_cost_cents"] = total_variance
    # overwrite on_hand for each counted product
    for cl in lines:
        product = db.products.get(cl["product_id"])
        set_on_hand(product, cl["closing_units"])
