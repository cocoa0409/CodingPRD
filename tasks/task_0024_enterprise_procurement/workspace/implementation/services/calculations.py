"""Business calculations from SCAFFOLD §1.3 / PRD §3.

All money is integer cents. All scoring uses Decimal with ROUND_HALF_UP
applied at the precision specified by the scaffold.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import datetime as _dt

from db import db, parse_iso, fmt_iso

# --- Tier thresholds (SCAFFOLD calculations[po_tier_assignment].constants) ---
TIER1_MAX_CENTS = 500_000        # < $5,000
TIER2_MAX_CENTS = 5_000_000      # < $50,000
TIER3_MAX_CENTS = 50_000_000     # < $500,000

# --- Quote scoring weights ---
W_TECH = Decimal("0.40")
W_COMM = Decimal("0.60")

# --- Three-way match constants (SCAFFOLD calculations[three_way_match]) ---
QTY_TOLERANCE_PCT = Decimal("0.02")
AMT_TOLERANCE_PCT = Decimal("0.01")
TAX_TOLERANCE_CENTS = 1
ALLOWED_TAX_RATES = [Decimal("0.06"), Decimal("0.09"), Decimal("0.13")]


# ---------------------------------------------------------------------------
# Tier assignment
# ---------------------------------------------------------------------------


def tier_for_amount(total_cents: int) -> str:
    if total_cents < TIER1_MAX_CENTS:
        return "TIER_1"
    if total_cents < TIER2_MAX_CENTS:
        return "TIER_2"
    if total_cents < TIER3_MAX_CENTS:
        return "TIER_3"
    return "TIER_4"


# ---------------------------------------------------------------------------
# Quote pool scoring (SCAFFOLD calculations[quote_composite_score])
# ---------------------------------------------------------------------------


def _round_half_up_2dp(value: Decimal) -> float:
    quant = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Return a float to keep JSON-friendly output.
    return float(quant)


def recompute_pool_scores(requirement_id: str) -> None:
    """Recompute commercial_score and composite_score across the SUBMITTED pool.

    Per PRD §3.2: pool = quotes on this requirement currently in SUBMITTED.
    EXPIRED quotes are excluded. If min == max, every quote gets 100.00.
    Composite score: round((tech*0.4 + comm*0.6), 2) — rounding AFTER weighted sum.

    Note: only SUBMITTED-pool members get their scores updated. Quotes already
    in SHORTLISTED retain their existing stored scores (the recompute pertains
    to the SUBMITTED-state pool).
    """
    pool = [
        q for q in db.quotes.values()
        if q.get("requirement_id") == requirement_id and q.get("status") == "SUBMITTED"
    ]
    if not pool:
        return
    prices = [int(q["unit_price_cents"]) for q in pool]
    min_price = min(prices)
    max_price = max(prices)
    for q in pool:
        if max_price == min_price:
            comm = Decimal("100.00")
        else:
            num = Decimal(max_price - int(q["unit_price_cents"]))
            den = Decimal(max_price - min_price)
            comm = (num / den) * Decimal("100")
            comm = comm.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        q["commercial_score"] = float(comm)
        tech = Decimal(str(q["technical_score"]))
        composite = tech * W_TECH + Decimal(str(q["commercial_score"])) * W_COMM
        composite = composite.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        q["composite_score"] = float(composite)


# ---------------------------------------------------------------------------
# Three-way match (SCAFFOLD calculations[three_way_match])
# ---------------------------------------------------------------------------


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def three_way_match(invoice: dict, po: dict, requirement: dict, receipts: list[dict]) -> dict:
    """Compute three-way-match deltas + booleans. Returns a result dict.

    Receipts passed in must already be filtered to ACCEPTED / PARTIALLY_ACCEPTED.
    """
    received_qty = sum(int(r.get("accepted_quantity", 0)) for r in receipts)
    po_total = int(po["total_amount_cents"])
    req_qty = int(requirement["quantity"])

    # Pro-rata received amount (no rounding — keep as Decimal so the percentage
    # comparison is exact).
    if req_qty > 0:
        received_amt = (Decimal(received_qty) * Decimal(po_total)) / Decimal(req_qty)
    else:
        received_amt = Decimal(0)

    inv_qty = int(invoice["invoiced_quantity"])
    inv_amt = int(invoice["invoiced_amount_cents"])
    inv_tax_amt = int(invoice["tax_amount_cents"])
    rate = _to_decimal(invoice["tax_rate_declared"])

    # Quantity delta percent
    if received_qty > 0:
        qty_delta_pct = abs(Decimal(inv_qty) - Decimal(received_qty)) / Decimal(received_qty)
    else:
        # When received_qty is zero, any nonzero invoice quantity fails;
        # a zero-on-zero match passes.
        qty_delta_pct = Decimal("0") if inv_qty == 0 else Decimal("999")

    # Amount delta percent
    if received_amt > 0:
        amt_delta_pct = abs(Decimal(inv_amt) - received_amt) / received_amt
    else:
        amt_delta_pct = Decimal("0") if inv_amt == 0 else Decimal("999")

    # Expected tax = round_half_up( inv_amt - inv_amt / (1 + rate), 0 )
    # PRD §3.9: "rounded half-up to the nearest whole cent"
    one_plus_rate = Decimal("1") + rate
    if one_plus_rate > 0:
        net = Decimal(inv_amt) / one_plus_rate
        tax_expected_decimal = Decimal(inv_amt) - net
        tax_expected = int(tax_expected_decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        tax_expected = 0

    tax_delta_cents = abs(inv_tax_amt - tax_expected)

    quantity_match = qty_delta_pct <= QTY_TOLERANCE_PCT
    amount_match = amt_delta_pct <= AMT_TOLERANCE_PCT
    rate_allowed = any(rate == r for r in ALLOWED_TAX_RATES)
    tax_compliant = bool(tax_delta_cents <= TAX_TOLERANCE_CENTS and rate_allowed)

    return {
        "quantity_match": bool(quantity_match),
        "amount_match": bool(amount_match),
        "tax_compliant": bool(tax_compliant),
        "deltas": {
            "received_quantity": received_qty,
            "received_amount_cents": int(received_amt.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                if received_amt > 0 else 0,
            "qty_delta_pct": float(qty_delta_pct.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
            "amt_delta_pct": float(amt_delta_pct.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
            "tax_expected_cents": int(tax_expected),
            "tax_delta_cents": int(tax_delta_cents),
            "tax_rate_allowed": bool(rate_allowed),
        },
    }


# ---------------------------------------------------------------------------
# Supplier rating (SCAFFOLD calculations[supplier_rating_avg])
# ---------------------------------------------------------------------------


def recompute_supplier_rating(supplier_id: str) -> None:
    rs = [
        r for r in db.receipts.values()
        if r.get("supplier_id") == supplier_id and r.get("status") in ("ACCEPTED", "PARTIALLY_ACCEPTED")
    ]
    supplier = db.suppliers.get(supplier_id)
    if supplier is None:
        return
    if not rs:
        supplier["rating_avg"] = 0
        return
    total = Decimal(0)
    for r in rs:
        total += Decimal(str(r.get("quality_rating", 0)))
    avg = (total / Decimal(len(rs))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    supplier["rating_avg"] = float(avg)


# ---------------------------------------------------------------------------
# Payment schedule generation (SCAFFOLD calculations[payment_schedule_generation])
# ---------------------------------------------------------------------------


def generate_payment_schedule(contract: dict, po: dict, requirement: dict) -> list[dict]:
    """Generate the schedule rows at the moment a contract enters EXECUTED.

    Per PRD §3.7:
    - schedule "now" is the contract's execution time (db.now() captured by caller)
    - delivery anchor is the requirement's expected_delivery_date
    - INSTALLMENT cents remainder lands on the LAST installment
    Returns the freshly built schedule rows (caller persists them).
    """
    from db import stamp_create  # lazy import to avoid cycles

    total = int(po["total_amount_cents"])
    terms_type = contract["payment_terms_type"]
    params = contract.get("payment_terms_params") or {}

    now = db.now()
    delivery_due = parse_iso(requirement["expected_delivery_date"])

    rows: list[dict] = []

    def _add(installment_no: int, amount_cents: int, due_date: _dt.datetime) -> None:
        row = {
            "purchase_order_id": po["id"],
            "contract_id": contract["id"],
            "installment_no": installment_no,
            "due_date": fmt_iso(due_date),
            "amount_cents": amount_cents,
            "status": "PENDING",
        }
        stamp_create(row, common=False)  # only id + created_at on PaymentSchedule
        rows.append(row)

    if terms_type == "ADVANCE":
        _add(1, total, now)
    elif terms_type == "ON_DELIVERY":
        _add(1, total, delivery_due)
    elif terms_type == "NET_N_DAYS":
        net_days = int(params.get("net_days", 0))
        _add(1, total, delivery_due + _dt.timedelta(days=net_days))
    elif terms_type == "INSTALLMENT":
        schedule_items = list(params.get("schedule") or [])
        running = 0
        n = len(schedule_items)
        for i, item in enumerate(schedule_items):
            percent = int(item.get("percent", 0))
            offset_days = int(item.get("offset_days", 0))
            if i < n - 1:
                amt = (total * percent) // 100  # integer floor
            else:
                amt = total - running
            due = now + _dt.timedelta(days=offset_days)
            _add(i + 1, amt, due)
            running += amt
        # Invariant: sum equals total (guaranteed by construction).

    # Persist into db.payment_schedules and return
    for row in rows:
        db.payment_schedules[row["id"]] = row
    return rows
