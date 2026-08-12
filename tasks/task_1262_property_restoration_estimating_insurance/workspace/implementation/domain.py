"""Business logic: calculations, derived aggregates, and cascades."""
from datetime import timedelta
from decimal import Decimal

from store import (DB, now, fmt_clock, dec, rhu, touch, refresh, new_id,
                   stamp_new, WA_VALIDITY_DAYS, MOISTURE_WET_MARGIN)
from errors import ApiError


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get(table, rid):
    rec = DB[table].get(rid)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "Resource not found: %s" % rid)
    return rec


def find(table, **kw):
    out = []
    for rec in DB[table].values():
        if all(rec.get(k) == v for k, v in kw.items()):
            out.append(rec)
    return out


def claim_of_estimate(est):
    return DB["claims"].get(est["claim_id"])


def carrier_of_claim(claim):
    policy = DB["policies"].get(claim["policy_id"])
    return DB["carriers"].get(policy["carrier_id"]) if policy else None


def policy_of_claim(claim):
    return DB["policies"].get(claim["policy_id"])


def lines_of_estimate(est_id):
    return [l for l in DB["estimate_lines"].values() if l["estimate_id"] == est_id]


def rounds_of_estimate(est_id):
    return [r for r in DB["negotiation_rounds"].values() if r["estimate_id"] == est_id]


def dispositions_of_round(round_id):
    return [d for d in DB["line_dispositions"].values()
            if d["negotiation_round_id"] == round_id]


# ---------------------------------------------------------------------------
# Estimate money (provisional variant) — line_extended_pricing, sales_tax,
# overhead_profit, depreciation_split
# ---------------------------------------------------------------------------

def compute_line_money(line, carrier):
    line["extended_cents"] = rhu(dec(line["qty"]) * dec(line["unit_price_cents"]))
    line["depreciation_cents"] = rhu(dec(line["extended_cents"]) * dec(line["depreciation_pct"]))
    if line["tax_applicable"]:
        line["tax_cents"] = rhu(dec(line["extended_cents"]) * dec(carrier["tax_rate"]))
    else:
        line["tax_cents"] = 0


def estimate_totals(lines, carrier, recoverable_depreciation_enabled, variant="provisional"):
    """Compute estimate-level totals over the given lines.

    variant == "final": qty_actual overrides planned qty when recorded;
    a recorded qty_actual of 0 excludes the line entirely. Returns a dict of
    totals; per-line extended values for the final variant are computed
    on the fly and never stored.
    """
    active = [l for l in lines if l["negotiation_status"] != "REMOVED"]
    effective = []  # (line, effective_qty)
    for l in active:
        if variant == "final" and l.get("qty_actual") is not None:
            q = l["qty_actual"]
            if dec(q) == 0:
                continue
            effective.append((l, q))
        else:
            effective.append((l, l["qty"]))

    per_line = []
    for l, q in effective:
        ext = rhu(dec(q) * dec(l["unit_price_cents"]))
        dep = rhu(dec(ext) * dec(l["depreciation_pct"]))
        tax = rhu(dec(ext) * dec(carrier["tax_rate"])) if l["tax_applicable"] else 0
        per_line.append((l, ext, dep, tax))

    rcv = sum(p[1] for p in per_line)
    tax_total = sum(p[3] for p in per_line)
    dep_total = sum(p[2] for p in per_line)
    recoverable = 0
    if recoverable_depreciation_enabled:
        recoverable = sum(p[2] for p in per_line if p[0]["depreciation_recoverable"])

    trades = {p[0]["trade"] for p in per_line}
    if len(trades) >= carrier["o_and_p_min_trades"]:
        base = sum(p[1] for p in per_line if p[0]["o_and_p_eligible"])
        overhead = rhu(dec(base) * dec(carrier["overhead_rate"]))
        profit = rhu(dec(base + overhead) * dec(carrier["profit_rate"]))
        op_total = overhead + profit
    else:
        op_total = 0

    grand = rcv + tax_total + op_total
    return {
        "rcv_total_cents": rcv,
        "tax_total_cents": tax_total,
        "overhead_profit_total_cents": op_total,
        "depreciation_total_cents": dep_total,
        "recoverable_depreciation_cents": recoverable,
        "grand_total_cents": grand,
        "acv_total_cents": grand - dep_total,
    }


def recompute_estimate(est):
    """Provisional recompute: refresh each line's stored money, then roll up."""
    claim = claim_of_estimate(est)
    policy = policy_of_claim(claim)
    carrier = carrier_of_claim(claim)
    lines = lines_of_estimate(est["id"])
    for l in lines:
        compute_line_money(l, carrier)
    totals = estimate_totals(lines, carrier, policy["recoverable_depreciation"],
                             variant="provisional")
    est.update(totals)
    refresh(est)
    return est


# ---------------------------------------------------------------------------
# Claim aggregates (rcv_acv_totals) and payment ledger (claim_payment_posture)
# ---------------------------------------------------------------------------

def recompute_claim_aggregates(claim):
    approved = [e for e in DB["estimates"].values()
                if e["claim_id"] == claim["id"] and e["status"] in ("APPROVED", "LOCKED")]
    claim["rcv_total_cents"] = sum(e["grand_total_cents"] for e in approved)
    claim["acv_total_cents"] = sum(e["acv_total_cents"] for e in approved)
    claim["recoverable_depreciation_cents"] = sum(
        e["recoverable_depreciation_cents"] for e in approved)
    refresh(claim)


def active_invoice(claim_id):
    invs = [i for i in DB["invoices"].values()
            if i["claim_id"] == claim_id and i["status"] != "VOIDED"]
    if not invs:
        return None
    invs.sort(key=lambda r: r["_seq"])
    return invs[-1]


def recompute_claim_ledger(claim):
    """Paid counters, active-invoice applied/outstanding, posture, and the
    claim's outstanding balance. May settle the invoice and close the claim."""
    payments = [p for p in DB["payments"].values() if p["claim_id"] == claim["id"]]
    cleared = [p for p in payments if p["status"] == "CLEARED"]
    claim["carrier_paid_cents"] = sum(
        p["amount_cents"] for p in cleared
        if p["direction"] == "CARRIER_TO_CONTRACTOR")
    claim["customer_paid_cents"] = sum(
        p["amount_cents"] for p in cleared
        if p["direction"] == "CUSTOMER_TO_CONTRACTOR")
    claim["deductible_collected_cents"] = sum(
        p["amount_cents"] for p in cleared if p["type"] == "DEDUCTIBLE")

    inv = active_invoice(claim["id"])
    if inv is not None and inv["status"] in ("ISSUED", "SETTLED"):
        inv["applied_cents"] = min(
            sum(p["amount_cents"] for p in cleared), inv["total_cents"])
        inv["outstanding_cents"] = inv["total_cents"] - inv["applied_cents"]
        refresh(inv)
        if inv["status"] == "ISSUED" and inv["applied_cents"] >= inv["total_cents"]:
            inv["status"] = "SETTLED"
            touch(inv)
            if claim["status"] == "INVOICED":
                claim["status"] = "CLOSED"
                touch(claim)

    inv = active_invoice(claim["id"])
    if inv is not None and inv["status"] == "SETTLED":
        posture = "PAID_IN_FULL"
    elif inv is not None and inv["status"] == "ISSUED":
        posture = "DEPRECIATION_PENDING"
    elif claim["carrier_paid_cents"] > 0:
        posture = "ADVANCE_PAID"
    else:
        posture = "UNPAID"
    claim["payment_posture"] = posture

    if inv is not None and inv["status"] in ("ISSUED", "SETTLED"):
        claim["outstanding_balance_cents"] = inv["outstanding_cents"]
    else:
        claim["outstanding_balance_cents"] = 0
    refresh(claim)


def recompute_ordinance_consumed(claim):
    approved = [c for c in DB["code_upgrades"].values()
                if c["claim_id"] == claim["id"] and c["status"] == "APPROVED"]
    claim["ordinance_consumed_cents"] = sum(c["covered_cents"] or 0 for c in approved)
    refresh(claim)


# ---------------------------------------------------------------------------
# Negotiation rounds and dispositions
# ---------------------------------------------------------------------------

def recompute_round_disputed(rnd):
    total = 0
    for d in dispositions_of_round(rnd["id"]):
        if d["status"] != "PENDING":
            continue
        line = DB["estimate_lines"].get(d["estimate_line_id"])
        if line is None:
            continue
        pq = d["proposed_qty"] if d["proposed_qty"] is not None else line["qty"]
        pp = (d["proposed_unit_price_cents"]
              if d["proposed_unit_price_cents"] is not None
              else line["unit_price_cents"])
        proposed_ext = rhu(dec(pq) * dec(pp))
        total += abs(line["extended_cents"] - proposed_ext)
    rnd["disputed_amount_cents"] = total
    refresh(rnd)


def apply_disposition(disp):
    """Apply a disposition's proposed values to its line (accept semantics)."""
    line = DB["estimate_lines"][disp["estimate_line_id"]]
    if disp["proposed_qty"] is not None:
        line["qty"] = disp["proposed_qty"]
    if disp["proposed_unit_price_cents"] is not None:
        line["unit_price_cents"] = disp["proposed_unit_price_cents"]
    if disp["propose_removal"]:
        line["negotiation_status"] = "REMOVED"
    else:
        line["negotiation_status"] = "AGREED"
    touch(line)
    return line


def approve_estimate(est):
    """Shared estimate-approval side effects: stamp, claim aggregates, claim
    transitions, and the SUPPLEMENT scope-drift cascade. Caller has already
    applied any disposition values and recomputed totals."""
    est["status"] = "APPROVED"
    est["approved_at"] = fmt_clock(now())
    touch(est)
    claim = claim_of_estimate(est)
    recompute_claim_aggregates(claim)
    if est["type"] == "INITIAL" and claim["status"] == "NEGOTIATING":
        claim["status"] = "APPROVED"
        touch(claim)
    if est["type"] == "SUPPLEMENT":
        scope_drift_check(claim)


def scope_drift_check(claim):
    """scope_drift_check: void the SIGNED WA when drift strictly exceeds the
    rounded 10% threshold; drop an IN_PROGRESS claim to ON_HOLD."""
    was = [w for w in DB["work_authorizations"].values()
           if w["claim_id"] == claim["id"] and w["status"] == "SIGNED"]
    if not was:
        return
    wa = sorted(was, key=lambda r: r["_seq"])[-1]
    threshold = rhu(dec("0.10") * dec(wa["scope_rcv_cents"]))
    if abs(claim["rcv_total_cents"] - wa["scope_rcv_cents"]) > threshold:
        wa["status"] = "VOIDED"
        wa["voided_reason"] = "SCOPE_DRIFT"
        touch(wa)
        if claim["status"] == "IN_PROGRESS":
            claim["status"] = "ON_HOLD"
            touch(claim)


def maybe_resolve_round(rnd):
    """After a disposition answer: auto-resolve when nothing remains PENDING;
    when every disposition was ACCEPTED the estimate auto-approves."""
    disps = dispositions_of_round(rnd["id"])
    if any(d["status"] == "PENDING" for d in disps):
        recompute_round_disputed(rnd)
        return
    rnd["status"] = "RESOLVED"
    touch(rnd)
    recompute_round_disputed(rnd)
    if disps and all(d["status"] == "ACCEPTED" for d in disps):
        est = DB["estimates"].get(rnd["estimate_id"])
        if est is not None and est["status"] == "COUNTERED":
            recompute_estimate(est)
            approve_estimate(est)


def expire_round(rnd):
    """Deemed acceptance: auto-accept every PENDING disposition at its
    proposed values and auto-approve a COUNTERED estimate."""
    rnd["status"] = "EXPIRED"
    touch(rnd)
    est = DB["estimates"].get(rnd["estimate_id"])
    for d in dispositions_of_round(rnd["id"]):
        if d["status"] != "PENDING":
            continue
        d["status"] = "ACCEPTED"
        touch(d)
        if est is not None and est["status"] == "COUNTERED":
            apply_disposition(d)
    recompute_round_disputed(rnd)
    if est is not None and est["status"] == "COUNTERED":
        recompute_estimate(est)
        approve_estimate(est)


def clock_sweep():
    """Expire every OPEN round whose due_at is strictly before the clock."""
    expired = []
    rounds = sorted(DB["negotiation_rounds"].values(), key=lambda r: r["_seq"])
    for rnd in rounds:
        if rnd["status"] == "OPEN" and now() > rnd["_due_at_instant"]:
            expire_round(rnd)
            expired.append(rnd["id"])
    return expired


# ---------------------------------------------------------------------------
# Drying days
# ---------------------------------------------------------------------------

def compute_drying_days(readings):
    exceedances = [dec(r["reading_value"]) - dec(r["dry_standard"]) for r in readings]
    if exceedances:
        worst_e = max(exceedances)
    else:
        worst_e = dec(0)
    if worst_e <= 8:
        worst_days = 1
    elif worst_e <= 20:
        worst_days = 3
    else:
        worst_days = 5
    wet = [ex for r, ex in zip(readings, exceedances) if r["is_wet"]]
    if wet:
        mean_e = sum(wet) / len(wet)
    else:
        mean_e = dec(0)
    if mean_e <= 8:
        mean_days = 1
    elif mean_e <= 20:
        mean_days = 2
    else:
        mean_days = 4
    return worst_days, mean_days


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

PAYMENT_DIRECTION = {
    "ACV_ADVANCE": "CARRIER_TO_CONTRACTOR",
    "DEPRECIATION_RECOVERY": "CARRIER_TO_CONTRACTOR",
    "DEDUCTIBLE": "CUSTOMER_TO_CONTRACTOR",
    "CUSTOMER_BALANCE": "CUSTOMER_TO_CONTRACTOR",
}


def create_payment(claim_id, ptype, amount, auto_created, invoice_id=None):
    rec = {
        "id": new_id(),
        "claim_id": claim_id,
        "invoice_id": invoice_id,
        "type": ptype,
        "direction": PAYMENT_DIRECTION[ptype],
        "amount_cents": amount,
        "auto_created": auto_created,
        "status": "REQUESTED",
    }
    stamp_new(rec)
    DB["payments"][rec["id"]] = rec
    return rec
