"""Cross-entity services: existence lookup, derived ledgers (availability,
encumbrance, exposure), standing cascade, and the daily sweep."""
from db import db
from errors import ApiError
from util import now_date, touch

# Lines holding physical copies out of the pool. A LOST copy never returns, so
# it stays subtracted from the pool permanently (PRD 3.2: "a lost line
# restores nothing").
_HELD_STATUSES = {"RESERVED", "DISPATCHED", "ON_LOAN", "OVERDUE", "LOST"}
# Statuses that block new allocations for overlapping windows (SCAFFOLD
# set_availability_projection selector).
_BLOCKING_STATUSES = {"RESERVED", "DISPATCHED", "ON_LOAN", "OVERDUE"}
_ORDER_NON_TERMINAL = {"DRAFT", "RESERVED", "DISPATCHED", "ON_LOAN", "OVERDUE", "RETURNED", "DISPUTED"}


def get_or_404(collection, rec_id, error_id):
    rec = db[collection].get(rec_id)
    if rec is None:
        raise ApiError(error_id, 404, "%s not found: %s" % (collection, rec_id))
    return rec


def order_of_line(line):
    return db["rental_orders"].get(line["rental_order_id"])


def lines_of_order(order_id):
    out = [ln for ln in db["rental_lines"].values() if ln["rental_order_id"] == order_id]
    out.sort(key=lambda ln: ln["copy_seq"])
    return out


def lines_of_set(set_id):
    return [
        ln
        for ln in db["rental_lines"].values()
        if (order_of_line(ln) or {}).get("rental_set_id") == set_id
    ]


def invoices_of_order(order_id):
    line_ids = {ln["id"] for ln in lines_of_order(order_id)}
    return [inv for inv in db["damage_invoices"].values() if inv["rental_line_id"] in line_ids]


def reports_of_line(line_id):
    return [r for r in db["condition_reports"].values() if r["rental_line_id"] == line_id]


# ---------------------------------------------------------------- derived ledgers

def compute_available_copy_count(rental_set):
    held = sum(1 for ln in lines_of_set(rental_set["id"]) if ln["status"] in _HELD_STATUSES)
    return max(0, rental_set["copy_count"] - held)


def compute_encumbered(po):
    total = 0
    for o in db["rental_orders"].values():
        if o.get("purchase_order_id") == po["id"] and o["status"] in _ORDER_NON_TERMINAL:
            total += o["estimated_fee_cents"] or 0
    return total


def compute_exposures(account_id):
    """account_exposure: returns (open_exposure_cents, settled_exposure_cents)."""
    open_x = 0
    settled = 0
    for inv in db["damage_invoices"].values():
        if inv["account_id"] != account_id:
            continue
        if inv["status"] in ("DRAFT", "ISSUED", "DISPUTED"):
            open_x += inv["amount_cents"]
        if inv["status"] in ("ISSUED", "DISPUTED"):
            settled += inv["amount_cents"]
    for o in db["rental_orders"].values():
        if o["account_id"] != account_id:
            continue
        if o["status"] in ("RESERVED", "DISPATCHED", "ON_LOAN", "OVERDUE"):
            open_x += o["estimated_fee_cents"] or 0
        if o["status"] in ("DISPATCHED", "ON_LOAN", "OVERDUE"):
            settled += o["estimated_fee_cents"] or 0
        if o["status"] in ("RETURNED", "DISPUTED") and o["final_fee_cents"] is not None:
            open_x += o["final_fee_cents"]
            settled += o["final_fee_cents"]
    for s in db["sale_records"].values():
        if s["account_id"] == account_id and s["status"] == "INVOICED":
            open_x += s["balance_due_cents"]
            settled += s["balance_due_cents"]
    return open_x, settled


# ---------------------------------------------------------------- overlap

def count_blocking_copies(rental_set, new_start, new_due, exclude_order_id=None):
    """Copies held by live lines whose half-open windows overlap [start, due).
    Touching endpoints do not overlap."""
    n = 0
    for ln in lines_of_set(rental_set["id"]):
        if ln["status"] not in _BLOCKING_STATUSES:
            continue
        o = order_of_line(ln)
        if exclude_order_id is not None and o["id"] == exclude_order_id:
            continue
        if o["checkout_date"] < new_due and new_start < o["due_date"]:
            n += 1
    return n


# ---------------------------------------------------------------- standing cascade

def has_overdue_rentals(account_id):
    return any(
        o["account_id"] == account_id and o["status"] == "OVERDUE"
        for o in db["rental_orders"].values()
    )


def has_overdue_perusals(account_id):
    return any(
        p["account_id"] == account_id and p["status"] == "OVERDUE_PERUSAL"
        for p in db["perusal_requests"].values()
    )


def apply_hold(account):
    """GOOD -> HOLD, suspending every APPROVED purchase order. Returns True if flipped."""
    if account["standing"] != "GOOD":
        return False
    account["standing"] = "HOLD"
    touch(account)
    for po in db["purchase_orders"].values():
        if po["account_id"] == account["id"] and po["status"] == "APPROVED":
            po["status"] = "SUSPENDED"
            touch(po)
    return True


def restore_pos_to_approved(account_id):
    for po in db["purchase_orders"].values():
        if po["account_id"] == account_id and po["status"] == "SUSPENDED":
            po["status"] = "APPROVED"
            touch(po)


def maybe_restore_standing(account):
    """HOLD -> GOOD once no overdue rentals/perusals remain and settled
    exposure sits below the credit limit (limit 0 == uncapped)."""
    if account["standing"] != "HOLD":
        return False
    if has_overdue_rentals(account["id"]) or has_overdue_perusals(account["id"]):
        return False
    limit = account["credit_limit_cents"]
    if limit and limit > 0:
        _, settled = compute_exposures(account["id"])
        if settled >= limit:
            return False
    account["standing"] = "GOOD"
    touch(account)
    restore_pos_to_approved(account["id"])
    return True


# ---------------------------------------------------------------- daily sweep

def run_daily_sweep():
    today = now_date()
    swept_rentals = 0
    swept_perusals = 0
    swept_pos = 0
    standing_flips = 0

    # Overdue rentals: ON_LOAN with due_date passed. Batch order: due_date ASC,
    # then created_at ASC.
    orders = sorted(
        db["rental_orders"].values(),
        key=lambda o: (o["due_date"], o["created_at"], o["_seq"]),
    )
    for order in orders:
        if order["status"] == "ON_LOAN" and today > order["due_date"]:
            order["status"] = "OVERDUE"
            touch(order)
            for ln in lines_of_order(order["id"]):
                if ln["status"] == "ON_LOAN":
                    ln["status"] = "OVERDUE"
                    touch(ln)
            swept_rentals += 1
            account = db["customer_accounts"].get(order["account_id"])
            if account is not None and apply_hold(account):
                standing_flips += 1

    # Perusals: SHIPPED past return_due_date -> OVERDUE_PERUSAL (account HOLD);
    # APPROVED unshipped for > 10 days -> EXPIRED.
    perusals = sorted(
        db["perusal_requests"].values(),
        key=lambda p: (p["created_at"], p["_seq"]),
    )
    for p in perusals:
        if p["status"] == "SHIPPED" and today > p["return_due_date"].date():
            p["status"] = "OVERDUE_PERUSAL"
            touch(p)
            swept_perusals += 1
            account = db["customer_accounts"].get(p["account_id"])
            if account is not None and apply_hold(account):
                standing_flips += 1
        elif p["status"] == "APPROVED" and (today - p["ship_date"].date()).days > 10:
            p["status"] = "EXPIRED"
            touch(p)
            swept_perusals += 1

    # Purchase orders: APPROVED past valid_until -> EXPIRED, unless non-terminal
    # rental orders still reference it.
    for po in sorted(db["purchase_orders"].values(), key=lambda x: (x["created_at"], x["_seq"])):
        if po["status"] == "APPROVED" and today > po["valid_until"]:
            open_refs = any(
                o.get("purchase_order_id") == po["id"] and o["status"] in _ORDER_NON_TERMINAL
                for o in db["rental_orders"].values()
            )
            if not open_refs:
                po["status"] = "EXPIRED"
                touch(po)
                swept_pos += 1

    # Standing recompute with PO cascade (restoration direction; overdue items
    # flipped their accounts above).
    for account in list(db["customer_accounts"].values()):
        if maybe_restore_standing(account):
            standing_flips += 1

    return {
        "swept_rentals": swept_rentals,
        "swept_perusals": swept_perusals,
        "swept_pos": swept_pos,
        "standing_flips": standing_flips,
    }
