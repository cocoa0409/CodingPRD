"""Routes: invoices and the conserved client balance ledger."""
from flask import Blueprint, request

from store import db, new_record, touch, serialize
from common import auth, get_body, require_fields, get_or_404, fk_or_404, paginate
from envelope import object_response, list_response
from errors import err
from timeutil import parse_dt
import calc

bp = Blueprint("billing", __name__)


def _in_period(iso_value, start, end):
    if iso_value is None:
        return False
    t = parse_dt(iso_value)
    return start <= t <= end


def _build_line_items(client_id, period_start, period_end, manual):
    start = parse_dt(period_start)
    end = parse_dt(period_end)
    items = []
    # RELEASED storage placements (final_fee_cents), released within the period
    placements = sorted(db["storage_placements"].values(), key=lambda r: r["_seq"])
    for p in placements:
        if p["status"] != "RELEASED":
            continue
        art = db["artworks"].get(p["artwork_id"])
        if art is None or art["client_id"] != client_id:
            continue
        if not _in_period(p.get("released_at"), start, end):
            continue
        items.append({"description": "Storage placement %s" % p["id"],
                      "amount_cents": int(p["final_fee_cents"] or 0)})
    # COMPLETED transport jobs (transport_charge_cents), scheduled_end within the period
    jobs = sorted(db["transport_jobs"].values(), key=lambda r: r["_seq"])
    for j in jobs:
        if j["status"] != "COMPLETED":
            continue
        art = db["artworks"].get(j["artwork_id"])
        if art is None or art["client_id"] != client_id:
            continue
        if not _in_period(j.get("scheduled_end"), start, end):
            continue
        items.append({"description": "Transport job %s" % j["id"],
                      "amount_cents": int(j["transport_charge_cents"] or 0)})
    # manual line items
    if manual:
        for m in manual:
            items.append({"description": m.get("description"),
                          "amount_cents": int(m.get("amount_cents", 0))})
    return items


@bp.route("/invoices", methods=["POST"])
def create_invoice():
    auth(["BillingAdmin"])
    body = get_body()
    fk_or_404("clients", body.get("client_id"))
    require_fields(body, ["client_id", "billing_period_start", "billing_period_end"])
    manual = body.get("manual_line_items")
    if manual is not None and not isinstance(manual, list):
        raise err("ERR_VALIDATION", "manual_line_items must be an array")
    line_items = _build_line_items(body["client_id"], body["billing_period_start"],
                                   body["billing_period_end"], manual)
    subtotal, tax, total = calc.invoice_total(line_items)
    rec = new_record({
        "client_id": body["client_id"],
        "billing_period_start": body["billing_period_start"],
        "billing_period_end": body["billing_period_end"],
        "line_items": line_items,
        "subtotal_cents": subtotal,
        "tax_cents": tax,
        "total_cents": total,
        "status": "DRAFT",
    })
    db["invoices"][rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/invoices/<rid>/state", methods=["POST"])
def invoice_state(rid):
    auth(["BillingAdmin"])
    rec = get_or_404("invoices", rid)
    body = get_body()
    require_fields(body, ["to_status"])
    to_status = body["to_status"]
    if to_status not in {"DRAFT", "ISSUED", "PAID", "VOID"}:
        raise err("ERR_VALIDATION", "invalid to_status")
    cur = rec["status"]
    valid = {("DRAFT", "ISSUED"), ("ISSUED", "PAID"), ("ISSUED", "VOID"), ("DRAFT", "VOID")}
    if (cur, to_status) not in valid:
        raise err("ERR_INVALID_STATE", "cannot move invoice from %s to %s" % (cur, to_status))
    client = db["clients"].get(rec["client_id"])
    if (cur, to_status) == ("DRAFT", "ISSUED"):
        if client is not None:
            client["outstanding_balance_cents"] += rec["total_cents"]
            touch(client)
    elif (cur, to_status) in (("ISSUED", "PAID"), ("ISSUED", "VOID")):
        if client is not None:
            client["outstanding_balance_cents"] -= rec["total_cents"]
            touch(client)
    rec["status"] = to_status
    touch(rec)
    return object_response(serialize(rec))


@bp.route("/invoices/<rid>", methods=["GET"])
def get_invoice(rid):
    uid, role = auth(["BillingAdmin", "Client"])
    rec = get_or_404("invoices", rid)
    if role == "Client" and rec["client_id"] != uid:
        raise err("ERR_OWNERSHIP_REQUIRED", "not your invoice")
    return object_response(serialize(rec))


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    uid, role = auth(["BillingAdmin", "Client"])
    cid = request.args.get("client_id")
    st = request.args.get("status")
    if role == "Client":
        if cid is not None and cid != uid:
            raise err("ERR_OWNERSHIP_REQUIRED", "not your client scope")
        cid = uid
    recs = [r for r in db["invoices"].values()
            if (cid is None or r["client_id"] == cid) and (st is None or r["status"] == st)]
    items, limit, offset, total = paginate(recs)
    return list_response(items, limit, offset, total)
