"""Commission statements: upload, reconciliation, disputes, settlement."""
from datetime import datetime, timezone
from flask import Blueprint, request

import db
from db import now, touch
from errors import err, not_found, invalid_request
from middleware import api, body, ctx, ALL_ROLES
from response import success_object, success_list
from services import (
    LINE_TOLERANCE_CENTS, DRAW_RECOVERY_BP, split_rows_for, allocate,
    post_entry, recompute_rep,
)

bp = Blueprint("statements", __name__)


def _get_statement(sid):
    st = db.statements.get(sid)
    if st is None:
        raise not_found("CommissionStatement")
    return st


def _period_bounds(period_label):
    y, m = int(period_label[:4]), int(period_label[5:7])
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    end = datetime(y + 1, 1, 1, tzinfo=timezone.utc) if m == 12 else datetime(y, m + 1, 1, tzinfo=timezone.utc)
    return start, end


def _matched_order(st, line):
    for order in db.orders.values():
        if (order["principal_id"] == st["principal_id"]
                and order["external_order_ref"] == line["external_order_ref"]
                and order["fulfillment_status"] != "CANCELLED"):
            return order
    return None


@bp.route("/rep-agency/statements", methods=["POST"])
@api(["PrincipalOps"])
def create_statement():
    data = body()
    principal_id = data.get("principal_id")
    if not isinstance(principal_id, str):
        raise invalid_request("principal_id is required")
    period_label = data.get("period_label")
    if not isinstance(period_label, str):
        raise invalid_request("period_label is required")
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise invalid_request("lines must be a non-empty array")
    for ln in raw_lines:
        if (not isinstance(ln, dict) or not isinstance(ln.get("line_id"), str)
                or not ln.get("line_id")
                or not isinstance(ln.get("external_order_ref"), str)
                or not db.is_int(ln.get("amount_cents"))):
            raise invalid_request("each statement line requires {line_id, external_order_ref, amount_cents}")
    principal = db.principals.get(principal_id)
    if principal is None:
        raise not_found("Principal")
    if ctx()["user_id"] != principal["id"]:
        raise err("ERR_FORBIDDEN_NOT_OWNER",
                  "PrincipalOps may only upload statements for its own principal")
    # period label shape YYYY-MM
    parts = period_label.split("-")
    if (len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2
            or not parts[0].isdigit() or not parts[1].isdigit()
            or not (1 <= int(parts[1]) <= 12)):
        raise invalid_request("period_label must be in YYYY-MM form")
    seen = set()
    for ln in raw_lines:
        if ln["line_id"] in seen:
            raise invalid_request("duplicate line_id within statement")
        seen.add(ln["line_id"])
    for other in db.statements.values():
        if (other["principal_id"] == principal_id
                and other["period_label"] == period_label):
            raise err("ERR_DUPLICATE_PERIOD_LABEL",
                      "period_label already exists for this principal")
    lines = [{
        "line_id": ln["line_id"],
        "external_order_ref": ln["external_order_ref"],
        "amount_cents": ln["amount_cents"],
        "disposition": "PENDING",
        "_expected_cents": None,
        "_order_id": None,
        "_adjustment_amount_cents": None,
    } for ln in raw_lines]
    st = {
        "principal_id": principal_id,
        "period_label": period_label,
        "lines": lines,
        "stated_total_cents": sum(ln["amount_cents"] for ln in lines),
        "expected_total_cents": None,
        "expected_cash_basis_cents": None,
        "variance_cents": None,
        "status": "RECEIVED",
        "reconciled_at": None,
        "settled_at": None,
    }
    db.stamp_new(st)
    db.statements[st["id"]] = st
    return success_object(st, 201)


@bp.route("/rep-agency/statements", methods=["GET"])
@api(ALL_ROLES)
def list_statements():
    items = list(db.statements.values())
    for param in ("principal_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [s for s in items if s[param] == value]
    return success_list(items)


@bp.route("/rep-agency/statements/<sid>", methods=["GET"])
@api(ALL_ROLES)
def get_statement(sid):
    return success_object(_get_statement(sid))


@bp.route("/rep-agency/statements/<sid>/start_reconciliation", methods=["POST"])
@api(["AgencyAdmin"])
def start_reconciliation(sid):
    st = _get_statement(sid)
    if st["status"] != "RECEIVED":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only a RECEIVED statement can enter reconciliation")
    start, end = _period_bounds(st["period_label"])
    entries = [e for e in db.entries.values() if e["principal_id"] == st["principal_id"]]
    # accrual-basis expectation (canonical)
    expected = sum(e["amount_cents"] for e in entries
                   if e["type"] in ("ACCRUAL", "CHARGEBACK")
                   and start <= e["business_date"] < end)
    # cash-basis expectation (informational)
    cash = 0
    for e in entries:
        if e["type"] == "ACCRUAL":
            order = db.orders.get(e["order_id"]) if e["order_id"] else None
            if order is not None and order["paid_at"] is not None \
                    and start <= order["paid_at"] < end:
                cash += e["amount_cents"]
        elif e["type"] == "CHARGEBACK":
            if start <= e["business_date"] < end:
                cash += e["amount_cents"]
    st["expected_total_cents"] = expected
    st["expected_cash_basis_cents"] = cash
    st["variance_cents"] = st["stated_total_cents"] - expected
    # line matching; boundary inclusive at LINE_TOLERANCE_CENTS
    for line in st["lines"]:
        order = _matched_order(st, line)
        if order is None:
            line["disposition"] = "UNMATCHED_ORDER"
            line["_order_id"] = None
            line["_expected_cents"] = None
            continue
        expected_line = sum(e["amount_cents"] for e in db.entries.values()
                            if e["order_id"] == order["id"]
                            and e["business_date"] < end)
        line["_order_id"] = order["id"]
        line["_expected_cents"] = expected_line
        if abs(line["amount_cents"] - expected_line) <= LINE_TOLERANCE_CENTS:
            line["disposition"] = "MATCHED"
        else:
            line["disposition"] = "AMOUNT_VARIANCE"
    st["status"] = "IN_RECONCILIATION"
    st["reconciled_at"] = now()
    touch(st)
    return success_object(st)


def _get_line(st, line_id):
    for line in st["lines"]:
        if line["line_id"] == line_id:
            return line
    raise not_found("Statement line")


@bp.route("/rep-agency/statements/<sid>/lines/<lid>/accept_variance", methods=["POST"])
@api(["AgencyAdmin"])
def accept_variance(sid, lid):
    st = _get_statement(sid)
    line = _get_line(st, lid)
    if st["status"] not in ("IN_RECONCILIATION", "DISPUTED"):
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Statement is not in reconciliation")
    if line["disposition"] != "AMOUNT_VARIANCE":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only an AMOUNT_VARIANCE line can be accepted")
    line["disposition"] = "VARIANCE_ACCEPTED"
    touch(st)
    return success_object(st)


@bp.route("/rep-agency/statements/<sid>/lines/<lid>/dispute", methods=["POST"])
@api(["AgencyAdmin"])
def dispute_line(sid, lid):
    st = _get_statement(sid)
    line = _get_line(st, lid)
    data = body()
    if not isinstance(data.get("reason"), str) or not data.get("reason"):
        raise invalid_request("reason is required")
    if st["status"] not in ("IN_RECONCILIATION", "DISPUTED"):
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Statement is not in reconciliation")
    if line["disposition"] in ("DISPUTED", "RESOLVED"):
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Line cannot be disputed from its current disposition")
    line["disposition"] = "DISPUTED"
    st["status"] = "DISPUTED"
    touch(st)
    return success_object(st)


@bp.route("/rep-agency/statements/<sid>/respond_dispute", methods=["POST"])
@api(["PrincipalOps"])
def respond_dispute(sid):
    st = _get_statement(sid)
    if ctx()["user_id"] != st["principal_id"]:
        raise err("ERR_FORBIDDEN_NOT_OWNER",
                  "PrincipalOps may only respond for its own principal")
    data = body()
    line_id = data.get("line_id")
    if not isinstance(line_id, str):
        raise invalid_request("line_id is required")
    action = data.get("action")
    adjustment = data.get("adjustment_amount_cents")
    if adjustment is not None and not db.is_int(adjustment):
        raise invalid_request("adjustment_amount_cents must be an integer")
    line = _get_line(st, line_id)
    if st["status"] != "DISPUTED":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Statement has no open disputes")
    if line["disposition"] != "DISPUTED":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Line is not DISPUTED")
    if action == "ACCEPT":
        line["disposition"] = "RESOLVED"
        if adjustment is not None:
            line["_adjustment_amount_cents"] = adjustment
        if not any(l["disposition"] == "DISPUTED" for l in st["lines"]):
            st["status"] = "IN_RECONCILIATION"
    elif action == "REJECT":
        pass  # line stays DISPUTED, statement stays DISPUTED
    else:
        raise invalid_request("action must be ACCEPT or REJECT")
    touch(st)
    return success_object(st)


@bp.route("/rep-agency/statements/<sid>/settle", methods=["POST"])
@api(["AgencyAdmin"])
def settle_statement(sid):
    st = _get_statement(sid)
    if st["status"] not in ("IN_RECONCILIATION", "DISPUTED"):
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only a reconciled statement can be settled")
    if any(l["disposition"] == "DISPUTED" for l in st["lines"]):
        raise err("ERR_UNRESOLVED_DISPUTES", "Statement has DISPUTED lines")
    if any(l["disposition"] in ("PENDING", "AMOUNT_VARIANCE", "UNMATCHED_ORDER")
           for l in st["lines"]):
        raise err("ERR_LINES_NOT_DISPOSITIONED",
                  "Statement has un-dispositioned lines")
    ts = now()
    covered_orders = []
    for line in st["lines"]:
        if line["_order_id"] and line["_order_id"] not in covered_orders:
            covered_orders.append(line["_order_id"])

    # 1. absorbed deltas -> ADJUSTMENT entries allocated to matched order splits
    adj_by_rep = {}
    for line in st["lines"]:
        delta = None
        if line["disposition"] in ("MATCHED", "VARIANCE_ACCEPTED"):
            d = line["amount_cents"] - (line["_expected_cents"] or 0)
            if d != 0:
                delta = d
        elif line["disposition"] == "RESOLVED":
            if line["_adjustment_amount_cents"]:
                delta = line["_adjustment_amount_cents"]
        if delta is None:
            continue
        order = db.orders.get(line["_order_id"])
        if order is None:
            continue
        rows = split_rows_for(order["id"])
        n_lines = len({r["line_id"] for r in rows}) or 1
        alloc = allocate(delta, rows, total_weight=10000 * n_lines)
        for row in rows:
            if row["rep_id"] is None:
                continue
            cents = alloc.get(row["id"], 0)
            if cents == 0:
                continue
            adj_by_rep[row["rep_id"]] = adj_by_rep.get(row["rep_id"], 0) + cents
            post_entry(rep_id=row["rep_id"], principal_id=st["principal_id"],
                       order_id=order["id"], statement_id=None, etype="ADJUSTMENT",
                       amount_cents=cents, ref_line_id=line["line_id"],
                       business_date=ts)

    # 2. STATEMENT_PAYMENT per rep with accruals on covered orders, then draw recovery
    reps_with_accruals = {}
    for e in db.entries.values():
        if (e["type"] == "ACCRUAL" and e["order_id"] in covered_orders
                and e["rep_id"] is not None):
            reps_with_accruals.setdefault(e["rep_id"], 0)
            reps_with_accruals[e["rep_id"]] += e["amount_cents"]
    ordered_reps = sorted(
        (db.reps[rid] for rid in reps_with_accruals if rid in db.reps),
        key=lambda r: (r["created_at"], r["_seq"]))
    for rep in ordered_reps:
        rid = rep["id"]
        gross = reps_with_accruals[rid] + adj_by_rep.get(rid, 0)
        if gross <= 0:
            continue  # no payment, no recovery
        post_entry(rep_id=rid, principal_id=st["principal_id"],
                   order_id=None, statement_id=st["id"], etype="STATEMENT_PAYMENT",
                   amount_cents=-gross, business_date=ts)
        if rep["outstanding_draw_cents"] > 0:
            recovered = min(rep["outstanding_draw_cents"],
                            (gross * DRAW_RECOVERY_BP) // 10000)
            if recovered > 0:
                post_entry(rep_id=rid, principal_id=st["principal_id"],
                           order_id=None, statement_id=st["id"],
                           etype="DRAW_RECOVERY", amount_cents=-recovered,
                           business_date=ts)
                rep["outstanding_draw_cents"] -= recovered

    # 3. covered orders settle
    for oid in covered_orders:
        order = db.orders.get(oid)
        if order is not None and order["commission_status"] != "SETTLED":
            order["commission_status"] = "SETTLED"
            touch(order)

    st["status"] = "SETTLED"
    st["settled_at"] = ts
    touch(st)

    # 4. balances + hold posture
    affected = set(adj_by_rep) | set(reps_with_accruals)
    for rid in affected:
        recompute_rep(rid)
    return success_object(st)
