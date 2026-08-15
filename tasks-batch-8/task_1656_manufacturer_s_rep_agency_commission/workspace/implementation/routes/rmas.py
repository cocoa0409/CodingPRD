"""Return authorizations + commission ledger entry reads."""
from flask import Blueprint, request

import db
from db import now, touch
from errors import err, not_found, invalid_request
from middleware import api, body, ctx, ALL_ROLES
from response import success_object, success_list
from services import (
    split_rows_for, allocate, post_entry, recompute_rep, active_schedule,
    family_base_rate, current_multiplier, rhu_div,
)

bp = Blueprint("rmas", __name__)


def _get_rma(rid):
    rma = db.rmas.get(rid)
    if rma is None:
        raise not_found("ReturnAuthorization")
    return rma


def _rma_principal_owned(rid):
    rma = _get_rma(rid)
    if ctx()["user_id"] != rma["principal_id"]:
        raise err("ERR_FORBIDDEN_NOT_OWNER",
                  "PrincipalOps may only act on RMAs of its own principal")
    return rma


@bp.route("/rep-agency/rmas", methods=["POST"])
@api(["AgencyAdmin"])
def create_rma():
    data = body()
    order_id = data.get("order_id")
    if not isinstance(order_id, str):
        raise invalid_request("order_id is required")
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise invalid_request("lines must be a non-empty array")
    for ln in raw_lines:
        if (not isinstance(ln, dict) or not isinstance(ln.get("line_id"), str)
                or not db.is_int(ln.get("qty"))):
            raise invalid_request("each RMA line requires {line_id, qty}")
    order = db.orders.get(order_id)
    if order is None:
        raise not_found("Order")
    # state gate: order must be SHIPPED / INVOICED / PAID
    if order["fulfillment_status"] not in ("SHIPPED", "INVOICED", "PAID"):
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "RMAs require an order in SHIPPED, INVOICED, or PAID")
    # shape
    order_lines = {ln["line_id"]: ln for ln in order["lines"]}
    seen = set()
    for ln in raw_lines:
        if ln["line_id"] not in order_lines:
            raise invalid_request("unknown order line_id %s" % ln["line_id"])
        if ln["line_id"] in seen:
            raise invalid_request("duplicate line_id within RMA")
        seen.add(ln["line_id"])
        if ln["qty"] <= 0:
            raise invalid_request("RMA line qty must be positive")
    # fiscal: qty <= shipped - returned - pending on open RMAs
    for ln in raw_lines:
        oline = order_lines[ln["line_id"]]
        pending = 0
        for other in db.rmas.values():
            if other["order_id"] == order["id"] and other["status"] in ("REQUESTED", "APPROVED"):
                for ol in other["lines"]:
                    if ol["line_id"] == ln["line_id"]:
                        pending += ol["qty"]
        if ln["qty"] > oline["shipped_qty"] - oline["returned_qty"] - pending:
            raise err("ERR_RETURN_QTY_EXCEEDS_SHIPPED",
                      "Return quantity exceeds returnable quantity for line %s" % ln["line_id"])
    rma = {
        "order_id": order["id"],
        "principal_id": order["principal_id"],
        "lines": [{"line_id": ln["line_id"], "qty": ln["qty"]} for ln in raw_lines],
        "status": "REQUESTED",
        "provisional_chargeback_cents": None,
        "final_chargeback_cents": None,
        "requested_at": now(),
        "approved_at": None,
        "received_at": None,
    }
    db.stamp_new(rma)
    db.rmas[rma["id"]] = rma
    return success_object(rma, 201)


@bp.route("/rep-agency/rmas", methods=["GET"])
@api(ALL_ROLES)
def list_rmas():
    items = list(db.rmas.values())
    for param in ("order_id", "principal_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r[param] == value]
    return success_list(items)


@bp.route("/rep-agency/rmas/<rid>", methods=["GET"])
@api(ALL_ROLES)
def get_rma(rid):
    return success_object(_get_rma(rid))


def _chargeback_per_line(rma, order, variant):
    """Return list of (line, amount_cents) with per-line round-half-up, then summed."""
    order_lines = {ln["line_id"]: ln for ln in order["lines"]}
    principal = db.principals[order["principal_id"]]
    schedule = active_schedule(order["principal_id"])
    mult = current_multiplier(principal, schedule) if schedule else 10000
    per_line = []
    for ln in rma["lines"]:
        oline = order_lines[ln["line_id"]]
        if variant == "ORIGINAL_RATE":
            rate = oline["applied_rate_bp"] or 0
        else:  # CURRENT_RATE: current schedule base * current tier multiplier, no bonus
            base = family_base_rate(schedule, oline["family_code"]) if schedule else None
            rate = ((base or 0) * mult) // 10000
        amount = rhu_div(ln["qty"] * oline["unit_price_cents"] * rate, 10000)
        per_line.append((oline, ln["qty"], amount))
    return per_line


@bp.route("/rep-agency/rmas/<rid>/approve", methods=["POST"])
@api(["PrincipalOps"])
def approve_rma(rid):
    rma = _rma_principal_owned(rid)
    if rma["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only a REQUESTED RMA can be approved")
    order = db.orders[rma["order_id"]]
    per_line = _chargeback_per_line(rma, order, "CURRENT_RATE")
    rma["status"] = "APPROVED"
    rma["approved_at"] = now()
    rma["provisional_chargeback_cents"] = sum(a for _, _, a in per_line)
    touch(rma)
    return success_object(rma)


@bp.route("/rep-agency/rmas/<rid>/reject", methods=["POST"])
@api(["PrincipalOps"])
def reject_rma(rid):
    rma = _rma_principal_owned(rid)
    if rma["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only a REQUESTED RMA can be rejected")
    rma["status"] = "REJECTED"
    touch(rma)
    return success_object(rma)


@bp.route("/rep-agency/rmas/<rid>/receive", methods=["POST"])
@api(["PrincipalOps"])
def receive_rma(rid):
    rma = _rma_principal_owned(rid)
    if rma["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only an APPROVED RMA can be received")
    order = db.orders[rma["order_id"]]
    principal = db.principals[rma["principal_id"]]
    received_at = now()
    per_line = _chargeback_per_line(rma, order, "ORIGINAL_RATE")
    final_total = sum(a for _, _, a in per_line)
    rep_totals = {}
    rep_seq = []
    returned_value = 0
    for oline, qty, amount in per_line:
        oline["returned_qty"] += qty
        returned_value += qty * oline["unit_price_cents"]
        rows = split_rows_for(order["id"], oline["line_id"])
        alloc = allocate(amount, rows)
        for row in rows:
            if row["rep_id"] is None:
                continue
            cents = alloc.get(row["id"], 0)
            if row["rep_id"] not in rep_totals:
                rep_totals[row["rep_id"]] = 0
                rep_seq.append(row["rep_id"])
            rep_totals[row["rep_id"]] += cents
    touch(order)
    rma["status"] = "CLOSED"
    rma["received_at"] = received_at
    rma["final_chargeback_cents"] = final_total
    touch(rma)
    for rep_id in rep_seq:
        total = rep_totals[rep_id]
        if total == 0:
            continue
        post_entry(rep_id=rep_id, principal_id=rma["principal_id"],
                   order_id=order["id"], statement_id=None, etype="CHARGEBACK",
                   amount_cents=-total, business_date=received_at)
    for rep_id in rep_seq:
        recompute_rep(rep_id)
    principal["credited_ytd_sales_cents"] = max(
        0, principal["credited_ytd_sales_cents"] - returned_value)
    touch(principal)
    return success_object(rma)


# ---------------------------------------------------------------------------
# CommissionEntry reads
# ---------------------------------------------------------------------------
@bp.route("/rep-agency/commission-entries", methods=["GET"])
@api(ALL_ROLES)
def list_entries():
    items = list(db.entries.values())
    for param in ("rep_id", "principal_id", "order_id", "statement_id", "type"):
        value = request.args.get(param)
        if value is not None:
            items = [e for e in items if e[param] == value]
    return success_list(items)


@bp.route("/rep-agency/commission-entries/<eid>", methods=["GET"])
@api(ALL_ROLES)
def get_entry(eid):
    entry = db.entries.get(eid)
    if entry is None:
        raise not_found("CommissionEntry")
    return success_object(entry)
