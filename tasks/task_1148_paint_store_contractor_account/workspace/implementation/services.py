"""Store-derived computations and cascade side effects.

Derived fields (balances, spent totals, pull-through, order refunded amounts)
are recomputed from the underlying rows whenever read -- they are never stale
snapshots and never client-writable.
"""
from datetime import datetime, timezone, timedelta

import db
from calc import (
    banded, rebate_final_amount, rebate_provisional_amount, rebate_payable_amount,
    earn_points, clawback_points, mistint_current_price, pct_2dp,
)

PAID_SET = {"PAID", "PARTIALLY_REFUNDED", "REFUNDED"}


# --- entity lifecycle helpers ---------------------------------------------------
def stamp_new(entity):
    """Common system fields on creation: id/created_at/updated_at/version."""
    entity["id"] = db.new_id()
    entity["created_at"] = db.now()
    entity["updated_at"] = db.now()
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def stamp_event(entity):
    """Append-only ledger rows (ReturnRecord, LoyaltyTransaction): id + created_at only."""
    entity["id"] = db.new_id()
    entity["created_at"] = db.now()
    entity["_seq"] = db.next_seq()
    return entity


def bump(entity):
    """Every mutation increments version by 1 and refreshes updated_at."""
    entity["version"] += 1
    entity["updated_at"] = db.now()


# --- account derivations ----------------------------------------------------------
def orders_of_account(account_id):
    return [o for o in db.orders.values() if o["contractor_account_id"] == account_id]


def order_refunded_cents(order_id):
    """Sum of total_credit_cents over ReturnRecord rows of this order's lines."""
    total = 0
    for line in db.order_lines.values():
        if line["order_id"] != order_id:
            continue
        for rr in db.return_records.values():
            if rr["order_line_id"] == line["id"]:
                total += rr["total_credit_cents"]
    return total


def order_refund_merchandise_cents(order_id):
    """Sum of refund_merchandise_cents over ReturnRecord rows of this order's lines."""
    total = 0
    for line in db.order_lines.values():
        if line["order_id"] != order_id:
            continue
        for rr in db.return_records.values():
            if rr["order_line_id"] == line["id"]:
                total += rr["refund_merchandise_cents"]
    return total


def outstanding_balance(account_id):
    """Sum of total_cents over UNPAID orders (cancelled orders have left the set)."""
    return sum(
        o["total_cents"]
        for o in orders_of_account(account_id)
        if o["payment_status"] == "UNPAID" and o["fulfillment_status"] != "CANCELLED"
    )


def loyalty_balance(account_id):
    return sum(
        t["points_delta"]
        for t in db.loyalty_transactions.values()
        if t["contractor_account_id"] == account_id
    )


def ytd_net_volume(account_id, at=None):
    """Merchandise basis: SUM(subtotal) over paid-set orders with paid_at inside the
    current calendar year of the logical clock, MINUS those orders' refund merchandise."""
    at = at or db.now()
    jan1 = datetime(at.year, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    total = 0
    for o in orders_of_account(account_id):
        if o["payment_status"] in PAID_SET and o["paid_at"] is not None \
                and jan1 <= o["paid_at"] <= at:
            total += o["subtotal_cents"] - order_refund_merchandise_cents(o["id"])
    return total


def lifetime_rebate_paid(account_id):
    return sum(
        s["payable_cents"] or 0
        for s in db.rebate_statements.values()
        if s["contractor_account_id"] == account_id and s["status"] == "PAID"
    )


# --- job derivations ---------------------------------------------------------------
def job_spent(job_id):
    """SUM(total_cents - refunded_cents) over PAID / PARTIALLY_REFUNDED orders."""
    return sum(
        o["total_cents"] - order_refunded_cents(o["id"])
        for o in db.orders.values()
        if o["job_account_id"] == job_id and o["payment_status"] in {"PAID", "PARTIALLY_REFUNDED"}
    )


# --- spec pull-through ---------------------------------------------------------------
def spec_line_ordered_qty(line_id):
    total = 0
    for ol in db.order_lines.values():
        if ol.get("spec_line_id") != line_id:
            continue
        o = db.orders.get(ol["order_id"])
        if o is not None and o["payment_status"] in {"PAID", "PARTIALLY_REFUNDED"}:
            total += ol["quantity"] - ol["returned_quantity"]
    return total


def spec_line_delivered_qty(line_id):
    total = 0
    for ol in db.order_lines.values():
        if ol.get("spec_line_id") != line_id:
            continue
        o = db.orders.get(ol["order_id"])
        if o is not None and o["fulfillment_status"] == "DELIVERED":
            total += ol["quantity"] - ol["returned_quantity"]
    return total


def sheet_lines(sheet_id):
    return [l for l in db.spec_lines.values() if l["spec_sheet_id"] == sheet_id]


def sheet_pull_through(sheet_id):
    """Both variants over the sheet's current lines; 0 when the sheet has no lines."""
    lines = sheet_lines(sheet_id)
    if not lines:
        return 0, 0
    spec_sum = sum(l["specified_qty"] for l in lines)
    ordered_sum = sum(min(spec_line_ordered_qty(l["id"]), l["specified_qty"]) for l in lines)
    delivered_sum = sum(min(spec_line_delivered_qty(l["id"]), l["specified_qty"]) for l in lines)
    return pct_2dp(ordered_sum, spec_sum), pct_2dp(delivered_sum, spec_sum)


# --- VOC regulation ------------------------------------------------------------------
def voc_rule_at(jurisdiction_id, category, at):
    """The VocRule effective at instant `at` for (jurisdiction, category); None when
    no rule is effective (unrestricted). Windows are half-open [from, to)."""
    for r in db.voc_rules.values():
        if r["jurisdiction_id"] != jurisdiction_id or r["category"] != category:
            continue
        if r["effective_from"] <= at and (r["effective_to"] is None or at < r["effective_to"]):
            return r
    return None


# --- rebates --------------------------------------------------------------------------
def period_net(account_id, period_start, period_end):
    """Merchandise basis over [period_start, period_end): SUM(subtotal) over paid-set
    orders with paid_at in the window, MINUS all refund merchandise on those orders."""
    total = 0
    for o in orders_of_account(account_id):
        if o["payment_status"] in PAID_SET and o["paid_at"] is not None \
                and period_start <= o["paid_at"] < period_end:
            total += o["subtotal_cents"] - order_refund_merchandise_cents(o["id"])
    return total


def whole_days(start, end):
    return int((end - start).total_seconds() // 86400)


def compute_provisional(account_id, period_start, period_end, at):
    days_total = whole_days(period_start, period_end)
    elapsed_end = min(at, period_end)
    days_elapsed = whole_days(period_start, elapsed_end)
    net_so_far = period_net(account_id, period_start, elapsed_end)
    return rebate_provisional_amount(net_so_far, days_total, days_elapsed)


def compute_final(account_id, period_start, period_end):
    """Chronological event stream: +subtotal at paid_at for in-period paid-set orders,
    -refund_merchandise at ReturnRecord.created_at for in-period returns of the
    account's order lines. Sort: event ts asc, payments before refunds, then row
    created_at asc (id is never a tiebreaker)."""
    events = []
    for o in orders_of_account(account_id):
        if o["payment_status"] in PAID_SET and o["paid_at"] is not None \
                and period_start <= o["paid_at"] < period_end:
            events.append((o["paid_at"], 0, o["created_at"], o["_seq"], o["subtotal_cents"]))
    for ol in db.order_lines.values():
        o = db.orders.get(ol["order_id"])
        if o is None or o["contractor_account_id"] != account_id:
            continue
        for rr in db.return_records.values():
            if rr["order_line_id"] != ol["id"]:
                continue
            if period_start <= rr["created_at"] < period_end:
                events.append((rr["created_at"], 1, rr["created_at"], rr["_seq"],
                               -rr["refund_merchandise_cents"]))
    events.sort(key=lambda e: (e[0], e[1], e[2], e[3]))
    return rebate_final_amount([e[4] for e in events])


def compute_payable(statement):
    return rebate_payable_amount(
        statement["final_amount_cents"], statement["adjustment_cents"],
        statement["period_net_cents"],
    )


# --- loyalty ledger ---------------------------------------------------------------------
def post_loyalty(account_id, order_id, txn_type, points_delta, note):
    txn = stamp_event({
        "contractor_account_id": account_id,
        "order_id": order_id,
        "type": txn_type,
        "points_delta": points_delta,
        "note": note,
    })
    db.loyalty_transactions[txn["id"]] = txn
    return txn


def post_earn(order):
    points = earn_points(order["tier_snapshot"], order["subtotal_cents"])
    return post_loyalty(
        order["contractor_account_id"], order["id"], "EARN", points,
        "Earned %d points on order %s" % (points, order["id"]),
    )


def post_clawback(order, refund_merchandise_cents):
    points = clawback_points(order["tier_snapshot"], refund_merchandise_cents)
    return post_loyalty(
        order["contractor_account_id"], order["id"], "CLAWBACK", -points,
        "Clawed back %d points on order %s" % (points, order["id"]),
    )


# --- cascades ------------------------------------------------------------------------------
def create_formula(product_id, color_code, name, shots, source):
    """Supersede semantics: the prior ACTIVE formula for (product_id, color_code) is
    RETIRED with the supersedes link; revision is prior max + 1 (or 1)."""
    prior = None
    max_revision = 0
    for f in db.tint_formulas.values():
        if f["product_id"] == product_id and f["color_code"] == color_code:
            if f["revision"] > max_revision:
                max_revision = f["revision"]
            if f["status"] == "ACTIVE":
                prior = f
    if prior is not None:
        prior["status"] = "RETIRED"
        bump(prior)
    formula = stamp_new({
        "product_id": product_id,
        "color_code": color_code,
        "name": name,
        "shots": shots,
        "revision": max_revision + 1,
        "source": source,
        "status": "ACTIVE",
        "supersedes_formula_id": prior["id"] if prior is not None else None,
    })
    db.tint_formulas[formula["id"]] = formula
    return formula


def retire_formula(formula):
    if formula["status"] == "ACTIVE":
        formula["status"] = "RETIRED"
        bump(formula)


def bulletin_take_effect(bulletin):
    """Four-hop discontinuation cascade:
    hop 1: subject product ACTIVE -> DISCONTINUED, replacement recorded;
    hop 2 (caused by hop 1): the product's ACTIVE formulas RETIRED, and spec lines
           referencing it on SUBMITTED/APPROVED sheets flagged obsoleted;
    hop 3 (caused by hop 2): APPROVED sheets with a newly-obsoleted line ->
           NEEDS_REVISION;
    the bulletin itself stamps effected_at. Every mutated entity bumps version."""
    now = db.now()
    product = db.products[bulletin["product_id"]]
    product["status"] = "DISCONTINUED"
    product["replacement_product_id"] = bulletin["replacement_product_id"]
    bump(product)

    for f in db.tint_formulas.values():
        if f["product_id"] == product["id"] and f["status"] == "ACTIVE":
            f["status"] = "RETIRED"
            bump(f)

    affected_sheets = {}
    for line in db.spec_lines.values():
        if line["product_id"] != product["id"]:
            continue
        sheet = db.spec_sheets.get(line["spec_sheet_id"])
        if sheet is None or sheet["status"] not in {"SUBMITTED", "APPROVED"}:
            continue
        if not line["obsoleted"]:
            line["obsoleted"] = True
            bump(line)
            affected_sheets[sheet["id"]] = sheet

    for sheet in affected_sheets.values():
        if sheet["status"] == "APPROVED":
            sheet["status"] = "NEEDS_REVISION"
            bump(sheet)

    bulletin["status"] = "EFFECTIVE"
    bulletin["effected_at"] = now
    bump(bulletin)


def process_return(line, quantity):
    """Return cascade: ReturnRecord -> line.returned_quantity -> order refund state
    -> loyalty clawback -> account/job ledger sync. Order, line, account, and job
    each bump version."""
    from calc import refund_amounts

    order = db.orders[line["order_id"]]
    merch, tax, credit = refund_amounts(line["unit_price_cents"], quantity)
    rr = stamp_event({
        "order_line_id": line["id"],
        "quantity": quantity,
        "refund_merchandise_cents": merch,
        "tax_refund_cents": tax,
        "total_credit_cents": credit,
    })
    db.return_records[rr["id"]] = rr

    line["returned_quantity"] += quantity
    bump(line)

    refunded = order_refunded_cents(order["id"])
    if refunded >= order["total_cents"]:
        order["payment_status"] = "REFUNDED"
    else:
        order["payment_status"] = "PARTIALLY_REFUNDED"
    bump(order)

    post_clawback(order, merch)

    account = db.contractor_accounts.get(order["contractor_account_id"])
    if account is not None:
        bump(account)
    job = db.job_accounts.get(order["job_account_id"])
    if job is not None:
        bump(job)
    return rr


# --- mistint --------------------------------------------------------------------------------
def mistint_price_now(listing, at=None):
    at = at or db.now()
    elapsed = (at - listing["created_at"]).total_seconds()
    weeks = int(elapsed // (7 * 86400))
    return mistint_current_price(
        listing["list_price_cents"], listing["cost_basis_cents"], weeks
    )


# --- delivery helpers --------------------------------------------------------------------------
def deliveries_of_job(job_id):
    return [d for d in db.deliveries.values() if d["job_account_id"] == job_id]


def deliveries_of_order(order_id):
    return [d for d in db.deliveries.values() if d["order_id"] == order_id]


def delivery_window_conflict(job_id, window_start, window_end):
    """30-minute clearance against every SCHEDULED/EN_ROUTE delivery of the job:
    OK iff new.start >= existing.end + 30min OR new.end + 30min <= existing.start.
    Mere adjacency is NOT sufficient."""
    buf = timedelta(minutes=30)
    for d in deliveries_of_job(job_id):
        if d["status"] not in {"SCHEDULED", "EN_ROUTE"}:
            continue
        if window_start >= d["window_end"] + buf:
            continue
        if window_end + buf <= d["window_start"]:
            continue
        return True
    return False
