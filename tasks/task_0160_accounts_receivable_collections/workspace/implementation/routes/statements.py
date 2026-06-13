"""Statement + cash-forecast endpoints (PRD §3.8, §3.9)."""
from flask import Blueprint, request

import db
from errors import err, ERR_VALIDATION
from middleware import get_identity, authorize
from response import success
from services import domain, lookup
from services.common import (
    stamp_create, get_json_body, require_str, round_half_up_int,
)
from timeutil import parse_iso_ms

bp = Blueprint("statements", __name__)

MONTHLY_RATE = 0.015
COLLECT_PROB = domain.COLLECT_PROB


@bp.route("/ar/customers/<cid>/statements", methods=["POST"])
def cut_statement(cid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "AR_CLERK"])
    customer = lookup.get_customer(cid)
    body = get_json_body()
    period_end = require_str(body, "period_end")
    period_end_ms = parse_iso_ms(period_end)

    invs = domain.customer_invoices(cid)

    # opening_balance: total_open_balance_cents as of the prior statement's
    # period_end. We use the most recent prior statement's snapshot if present.
    prior = None
    for s in db.statements.values():
        if s["customer_id"] != cid:
            continue
        if s["period_end_ms"] <= period_end_ms:
            if prior is None or s["period_end_ms"] > prior["period_end_ms"]:
                prior = s
    opening = prior["snapshot_total_open_cents"] if prior is not None else 0
    period_start_ms = prior["period_end_ms"] if prior is not None else None

    # new_charges: sum of face_amount over invoices issued within the period
    # (after the prior period_end, up to and including this period_end).
    new_charges = 0
    for iv in invs:
        issued = iv["invoice_date_ms"]
        if issued <= period_end_ms and (period_start_ms is None or issued > period_start_ms):
            new_charges += iv["face_amount_cents"]

    # finance_charge: per-invoice round-then-sum over overdue (invoice-date
    # basis worse than CURRENT), non-terminal {OPEN,PARTIAL,DISPUTED} invoices.
    finance_charge = 0
    for iv in invs:
        if iv["status"] not in ("OPEN", "PARTIAL", "DISPUTED"):
            continue
        if domain.aging_bucket(iv, "invoice") == "CURRENT":
            continue
        dun = domain.dunnable(iv)
        per_inv = round_half_up_int(dun * MONTHLY_RATE)
        finance_charge += per_inv

    # payments received within the period
    payments_in_period = 0
    for p in db.payments.values():
        if p["customer_id"] != cid:
            continue
        rec = p.get("received_at_ms")
        if rec is None:
            continue
        if rec <= period_end_ms and (period_start_ms is None or rec > period_start_ms):
            payments_in_period += p["amount_cents"]

    closing = opening + new_charges + finance_charge - payments_in_period

    s = {
        "customer_id": cid,
        "period_end": period_end,
        "period_end_ms": period_end_ms,
        "opening_balance_cents": opening,
        "new_charges_cents": new_charges,
        "finance_charge_cents": finance_charge,
        "closing_balance_cents": closing,
        # snapshot of the live total_open_balance at this period_end, used as the
        # opening balance for the next statement.
        "snapshot_total_open_cents": domain.compute_total_open_balance(cid),
    }
    stamp_create(s)
    db.statements[s["id"]] = s
    return success(domain.serialize_statement(s), status=201)


@bp.route("/ar/statements/<sid>", methods=["GET"])
def get_statement(sid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "AR_CLERK", "AUDITOR"])
    s = lookup.get_statement(sid)
    return success(domain.serialize_statement(s), status=200)


@bp.route("/ar/cash-forecast", methods=["GET"])
def cash_forecast():
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "COLLECTIONS_AGENT", "AUDITOR"])
    customer_id = request.args.get("customer_id")
    if customer_id is None or customer_id == "":
        raise err(ERR_VALIDATION, "customer_id is required")
    lookup.get_customer(customer_id)

    horizon_raw = request.args.get("horizon_days")
    if horizon_raw is None:
        raise err(ERR_VALIDATION, "horizon_days is required")
    try:
        horizon_days = int(horizon_raw)
    except (TypeError, ValueError):
        raise err(ERR_VALIDATION, "horizon_days must be an integer")
    if horizon_days < 1 or horizon_days > 365:
        raise err(ERR_VALIDATION, "horizon_days out of range [1,365]")

    method = request.args.get("method")
    if method not in ("EXPECTED", "CONSERVATIVE"):
        from errors import ERR_INVALID_ENUM
        if method is None:
            raise err(ERR_VALIDATION, "method is required")
        raise err(ERR_INVALID_ENUM, "method has invalid enum value: %s" % method)

    now = db.now_ms()
    horizon_end = now + horizon_days * domain.DAY_MS

    candidates = []
    for iv in domain.customer_invoices(customer_id):
        if iv["status"] not in ("OPEN", "PARTIAL", "DISPUTED"):
            continue
        if domain.dunnable(iv) <= 0:
            continue
        candidates.append(iv)

    total = 0.0
    if method == "EXPECTED":
        used_promises = set()
        active_promises = [
            p for p in db.promises.values()
            if p["customer_id"] == customer_id and p["status"] == "ACTIVE"
        ]
        for iv in candidates:
            dun = domain.dunnable(iv)
            best = None
            for p in active_promises:
                if id(p) in used_promises:
                    continue
                # covers when half-open window contains the invoice due_date and
                # coverage_end <= horizon_end
                if p["coverage_start_ms"] <= iv["due_date_ms"] < p["coverage_end_ms"] \
                        and p["coverage_end_ms"] <= horizon_end:
                    best = p
                    break
            if best is not None:
                used_promises.add(id(best))
                total += min(best["promised_amount_cents"], dun)
            # uncovered invoice contributes 0
    else:  # CONSERVATIVE
        for iv in candidates:
            dun = domain.dunnable(iv)
            bucket = domain.aging_bucket(iv, "due")
            total += dun * COLLECT_PROB[bucket]

    projected = round_half_up_int(total)

    forecast = {
        "customer_id": customer_id,
        "horizon_days": horizon_days,
        "method": method,
        "projected_cents": projected,
    }
    # CashForecast is ephemeral (PRD §2.4): only id + created_at, never stored.
    forecast["id"] = db.new_id()
    forecast["created_at"] = db.iso_now()
    out = {
        "id": forecast["id"],
        "created_at": forecast["created_at"],
        "customer_id": customer_id,
        "horizon_days": horizon_days,
        "method": method,
        "projected_cents": projected,
    }
    return success(out, status=200)
