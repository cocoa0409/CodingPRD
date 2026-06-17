"""Business-logic engine: calculations, project ledger recomputation, cascades.

Every rule traces to PRD §3 and SCAFFOLD §1.3.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

import db

# ---------------------------------------------------------------------------
# Status set helpers
# ---------------------------------------------------------------------------
COMMITTED_STATUSES = {"ORDERED", "IN_TRANSIT", "DELIVERED"}  # contribute to committed_cents (§3.6)
OUTSTANDING_STATUSES = {"ORDERED", "IN_TRANSIT", "DELIVERED"}  # waterfall targets (§3.10)
NON_TERMINAL_ORDER_STATUSES = {"DRAFT", "ORDERED", "IN_TRANSIT", "DELIVERED"}  # window-conflict set
NON_CANCELLED_ORDER_STATUSES = {"DRAFT", "ORDERED", "IN_TRANSIT", "DELIVERED", "CLOSED", "RETURNED"}


# ---------------------------------------------------------------------------
# Rounding (PRD §2.7: round-half-up universally)
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal/Fraction/number to a whole integer using round-half-up."""
    d = Decimal(value.numerator) / Decimal(value.denominator) if isinstance(value, Fraction) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# §1.3 selection_line_net
# ---------------------------------------------------------------------------
def selection_line_net(unit_cost_cents, quantity, trade_discount_pct):
    """round_half_up(unit_cost_cents * quantity * (1 - trade_discount_pct)).

    Rounding applied ONCE at the line level (PRD §3.4).
    """
    # Use exact rational arithmetic for the discount factor.
    disc = Fraction(str(trade_discount_pct)) if not isinstance(trade_discount_pct, Fraction) else trade_discount_pct
    exact = Fraction(unit_cost_cents) * Fraction(quantity) * (Fraction(1) - disc)
    return round_half_up(exact)


# ---------------------------------------------------------------------------
# §1.3 order_subtotal — round-then-sum (sum of frozen per-line snapshots)
# ---------------------------------------------------------------------------
def order_subtotal(order):
    lines = [ol for ol in db.order_lines.values() if ol["order_id"] == order["id"]]
    return sum(ol["line_net_cents_snapshot"] for ol in lines)


# ---------------------------------------------------------------------------
# §1.3 expected_delivery
# ---------------------------------------------------------------------------
def compute_expected_delivery(order, ordered_dt):
    """MAX over lines of (FFEItem.lead_time_days + Vendor.lead_time_buffer_days),
    added (whole days) to the moment the order entered ORDERED (PRD §3.6)."""
    vendor = db.vendors.get(order["vendor_id"])
    buffer_days = vendor["lead_time_buffer_days"] if vendor else 0
    lines = [ol for ol in db.order_lines.values() if ol["order_id"] == order["id"]]
    max_lead = 0
    for ol in lines:
        sel = db.selections.get(ol["selection_id"])
        if not sel:
            continue
        ffe = db.ffe_items.get(sel["ffe_item_id"])
        item_lead = ffe["lead_time_days"] if ffe else 0
        max_lead = max(max_lead, item_lead + buffer_days)
    delivery = ordered_dt + timedelta(days=max_lead)
    # ISO 8601 UTC with three fractional digits.
    return delivery.strftime("%Y-%m-%dT%H:%M:%S.") + f"{delivery.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# §1.3 design_fee_final / provisional (PRD §3.9)
# ---------------------------------------------------------------------------
def _ceil_to_quarter_hours(minutes):
    """ceil(m / 15) * 0.25 hours, as an exact Fraction."""
    import math
    increments = math.ceil(Fraction(minutes, 15))
    return Fraction(increments) * Fraction(1, 4)


def _hourly_billable_hours(project, statuses):
    total = Fraction(0)
    for te in db.time_entries.values():
        if te["project_id"] != project["id"]:
            continue
        if te["status"] in statuses and te["billable"]:
            total += _ceil_to_quarter_hours(te["minutes"])
    return total


def _markup_base(project, statuses):
    base = 0
    for o in db.orders.values():
        if o["project_id"] != project["id"]:
            continue
        if o["status"] in statuses:
            base += o["order_subtotal_cents"]
    return base


def design_fee(project, final):
    """Compute the design fee. final=True -> final variant; else provisional (§3.9)."""
    model = project["fee_model"]
    if model == "FLAT":
        # provisional == final
        return project["flat_fee_cents"]
    if model == "HOURLY":
        if final:
            statuses = {"APPROVED"}
        else:
            statuses = {"SUBMITTED", "APPROVED"}
        hours = _hourly_billable_hours(project, statuses)
        return round_half_up(hours * Fraction(project["hourly_rate_cents"]))
    if model == "MARKUP":
        if final:
            statuses = {"ORDERED", "IN_TRANSIT", "DELIVERED"}
        else:
            statuses = {"DRAFT", "ORDERED", "IN_TRANSIT", "DELIVERED"}
        base = _markup_base(project, statuses)
        markup = Fraction(str(project["markup_pct"]))
        return round_half_up(markup * Fraction(base))
    return 0


# ---------------------------------------------------------------------------
# §1.3 committed_cents (§3.6)
# ---------------------------------------------------------------------------
def committed_cents(project):
    total = 0
    for o in db.orders.values():
        if o["project_id"] == project["id"] and o["status"] in COMMITTED_STATUSES:
            total += o["order_subtotal_cents"]
    return total


# ---------------------------------------------------------------------------
# §1.3 budget_health (§3.8)
# ---------------------------------------------------------------------------
def budget_status(committed, fee_cents, budget):
    """GREEN if util<=0.80, AMBER if 0.80<util<=1.00, RED if util>1.00.
    Exact rational comparison, no pre-rounding (PRD §2.7, §3.8)."""
    if budget <= 0:
        # budget_cents must be > 0 at creation; defensive fallback.
        return "RED" if (committed + fee_cents) > 0 else "GREEN"
    util = Fraction(committed + fee_cents, budget)
    if util <= Fraction(80, 100):
        return "GREEN"
    if util <= Fraction(100, 100):
        return "AMBER"
    return "RED"


# ---------------------------------------------------------------------------
# §1.3 deposit_waterfall (§3.10)
# ---------------------------------------------------------------------------
def run_deposit_waterfall(project):
    """Allocate the full deposit pool across outstanding orders, created_at ASC.
    Sets each order's amount_paid_cents / balance_due_cents and the project's
    client_credit_cents. Non-outstanding orders get amount_paid_cents = 0."""
    pool = sum(
        p["amount_cents"] for p in db.payments.values() if p["project_id"] == project["id"]
    )

    outstanding = [
        o for o in db.orders.values()
        if o["project_id"] == project["id"] and o["status"] in OUTSTANDING_STATUSES
    ]
    # created_at ASC; earlier-inserted wins on tie (use insertion seq, never id).
    outstanding.sort(key=lambda o: (o["created_at"], o["_seq"]))

    pool_remaining = pool
    for o in outstanding:
        pay = min(pool_remaining, o["order_subtotal_cents"])
        o["amount_paid_cents"] = pay
        o["balance_due_cents"] = o["order_subtotal_cents"] - pay
        pool_remaining -= pay

    # Orders not in the outstanding set: amount_paid_cents = 0.
    outstanding_ids = {o["id"] for o in outstanding}
    for o in db.orders.values():
        if o["project_id"] != project["id"]:
            continue
        if o["id"] not in outstanding_ids:
            o["amount_paid_cents"] = 0
            o["balance_due_cents"] = o["order_subtotal_cents"]

    project["client_credit_cents"] = pool_remaining


# ---------------------------------------------------------------------------
# Posture (PRD §2.8) — first matching rule wins
# ---------------------------------------------------------------------------
def compute_posture(project):
    # 1) FROZEN if any OPEN+BLOCKING punch item on any of the project's orders.
    project_order_ids = {o["id"] for o in db.orders.values() if o["project_id"] == project["id"]}
    for pi in db.punch_items.values():
        if pi["order_id"] in project_order_ids and pi["status"] == "OPEN" and pi["severity"] == "BLOCKING":
            return "FROZEN"
    # 2) FROZEN if budget_status RED.
    bs = project["budget_status"]
    if bs == "RED":
        return "FROZEN"
    # 3) BUDGET_REVIEW if budget_status AMBER.
    if bs == "AMBER":
        return "BUDGET_REVIEW"
    # 4) BUDGET_REVIEW if any revision SUBMITTED or CHANGES_REQUESTED.
    for r in db.revisions.values():
        if r["project_id"] == project["id"] and r["status"] in ("SUBMITTED", "CHANGES_REQUESTED"):
            return "BUDGET_REVIEW"
    # 5) Otherwise OPEN.
    return "OPEN"


# ---------------------------------------------------------------------------
# Full project ledger recompute. Versioned mutation (PRD §2.4, §2.8).
# ---------------------------------------------------------------------------
def recompute_project(project, bump_version=True):
    """Re-derive committed_cents, design_fee_cents, budget_remaining_cents,
    budget_status, posture, client_credit_cents. This is itself a mutation of
    the Project (updated_at advances, version increments) per PRD §2.4."""
    closed = project["status"] == "CLOSED"

    # design_fee uses provisional while open, final at close (§3.8/§3.9).
    project["design_fee_cents"] = design_fee(project, final=closed)

    project["committed_cents"] = committed_cents(project)
    project["budget_remaining_cents"] = (
        project["budget_cents"] - project["committed_cents"] - project["design_fee_cents"]
    )
    project["budget_status"] = budget_status(
        project["committed_cents"], project["design_fee_cents"], project["budget_cents"]
    )
    # deposit allocation drives client_credit_cents; run before posture.
    run_deposit_waterfall(project)
    project["posture"] = compute_posture(project)

    if bump_version:
        db.touch(project)
