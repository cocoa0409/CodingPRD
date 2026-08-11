"""Drift complaints (with the disciplinary cascade) and invoices."""

from flask import Blueprint, request

from store import store
from util import (require_roles, get_body, req_str, req_nonempty_str, req_enum,
                  ok, paginate, now, not_found, forbidden, invalid_state, conflict)
from domain import (new_mutable, serialize, touch, find_open_complaint,
                    revert_scheduled_work_orders, severity_weight,
                    ROLLING_WINDOW, RECENCY_WINDOW, RECENCY_MULTIPLIER,
                    REVOKE_THRESHOLD, COMPLAINT_WINDOW, SEVERITIES)

bp = Blueprint("compliance", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# Drift complaints
# ---------------------------------------------------------------------------

@bp.post("/drift-complaints")
def create_drift_complaint():
    uid, _role = require_roles("Grower")
    body = get_body()
    work_order_id = req_str(body, "work_order_id")
    description = req_nonempty_str(body, "description")
    severity = req_enum(body, "severity", SEVERITIES)
    w = store.work_orders.get(work_order_id)
    if w is None:
        raise not_found("work order not found")
    if uid not in store.customers:
        raise not_found("complainant customer not found")
    if w["status"] != "COMPLETED":
        raise invalid_state("a drift complaint may only be filed against a COMPLETED work order")
    t = now()
    if t > w["completed_at"] + COMPLAINT_WINDOW:
        raise conflict("ERR_COMPLAINT_WINDOW_CLOSED",
                       "complaint filed more than 30 days after work order completion")
    if find_open_complaint(w["id"]) is not None:
        raise conflict("ERR_DUPLICATE_OPEN_COMPLAINT",
                       "a complaint for this work order is already FILED or INVESTIGATING")
    c = new_mutable({
        "complainant_customer_id": uid,
        "work_order_id": w["id"],
        "applicator_id": w["applicator_id"],
        "description": description,
        "severity": severity,
        "status": "FILED",
        "findings_note": None,
    })
    store.drift_complaints[c["id"]] = c
    return ok(serialize("drift_complaint", c), 201)


@bp.get("/drift-complaints/<cid>")
def get_drift_complaint(cid):
    require_roles("Grower", "ComplianceOfficer", "CoopAdmin")
    c = store.drift_complaints.get(cid)
    if c is None:
        raise not_found("drift complaint not found")
    return ok(serialize("drift_complaint", c))


@bp.get("/drift-complaints")
def list_drift_complaints():
    require_roles("Grower", "ComplianceOfficer", "CoopAdmin")
    items = sorted(store.drift_complaints.values(), key=lambda c: (c["created_at"], c["_seq"]))
    for param in ("complainant_customer_id", "work_order_id", "applicator_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[param] == v]
    return paginate([serialize("drift_complaint", c) for c in items])


@bp.post("/drift-complaints/<cid>/open-investigation")
def open_investigation(cid):
    require_roles("ComplianceOfficer")
    c = store.drift_complaints.get(cid)
    if c is None:
        raise not_found("drift complaint not found")
    if c["status"] != "FILED":
        raise invalid_state("only a FILED complaint can move to INVESTIGATING")
    # investigation alone does not suspend; it blocks invoice issue and reinstate
    c["status"] = "INVESTIGATING"
    touch(c)
    return ok(serialize("drift_complaint", c))


@bp.post("/drift-complaints/<cid>/substantiate")
def substantiate_complaint(cid):
    require_roles("ComplianceOfficer")
    c = store.drift_complaints.get(cid)
    if c is None:
        raise not_found("drift complaint not found")
    note = req_nonempty_str(get_body(), "findings_note")
    if c["status"] != "INVESTIGATING":
        raise invalid_state("only an INVESTIGATING complaint can be substantiated")
    t = now()
    c["status"] = "SUBSTANTIATED"
    c["findings_note"] = note
    touch(c)  # updated_at of this transition is the substantiation timestamp
    app = store.applicators.get(c["applicator_id"])
    if app is not None:
        # Cascade hop 1: penalty weight lands; rolling score recomputed
        app["penalty_points_lifetime"] += severity_weight(c["severity"])
        subs = [x for x in store.drift_complaints.values()
                if x["applicator_id"] == app["id"] and x["status"] == "SUBSTANTIATED"]
        rolling = sum(severity_weight(x["severity"]) for x in subs
                      if x["updated_at"] >= t - ROLLING_WINDOW)
        recent = sum(1 for x in subs if x["updated_at"] >= t - RECENCY_WINDOW)
        if recent >= 2:
            rolling *= RECENCY_MULTIPLIER
        app["rolling_score_365"] = rolling
        touch(app)
        # Cascade hop 2: license movement (revocation boundary: exactly 10 revokes)
        status_changed = False
        if rolling >= REVOKE_THRESHOLD and app["status"] in ("ACTIVE", "SUSPENDED"):
            app["status"] = "REVOKED"
            status_changed = True
        elif app["status"] == "ACTIVE":
            app["status"] = "SUSPENDED"
            status_changed = True
        if status_changed:
            touch(app)
            # Cascade hop 3: pull the applicator's scheduled work back to DRAFT
            revert_scheduled_work_orders(applicator_id=app["id"])
    # Void the complained work order's invoice in the same breath
    inv = None
    for i in store.invoices.values():
        if i["work_order_id"] == c["work_order_id"]:
            inv = i
            break
    if inv is not None and inv["status"] in ("DRAFT", "ISSUED"):
        if inv["status"] == "ISSUED":
            w = store.work_orders[inv["work_order_id"]]
            cust = store.customers[w["customer_id"]]
            cust["outstanding_cents"] -= inv["final_amount_cents"]
            touch(cust)
        inv["status"] = "VOIDED"
        touch(inv)
    return ok(serialize("drift_complaint", c))


@bp.post("/drift-complaints/<cid>/dismiss")
def dismiss_complaint(cid):
    require_roles("ComplianceOfficer")
    c = store.drift_complaints.get(cid)
    if c is None:
        raise not_found("drift complaint not found")
    note = req_nonempty_str(get_body(), "findings_note")
    if c["status"] != "INVESTIGATING":
        raise invalid_state("only an INVESTIGATING complaint can be dismissed")
    c["status"] = "DISMISSED"
    c["findings_note"] = note
    touch(c)
    return ok(serialize("drift_complaint", c))


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@bp.get("/invoices/<iid>")
def get_invoice(iid):
    require_roles("Grower", "Dispatcher", "CoopAdmin", "ComplianceOfficer")
    inv = store.invoices.get(iid)
    if inv is None:
        raise not_found("invoice not found")
    return ok(serialize("invoice", inv))


@bp.get("/invoices")
def list_invoices():
    require_roles("Grower", "Dispatcher", "CoopAdmin", "ComplianceOfficer")
    items = sorted(store.invoices.values(), key=lambda i: (i["created_at"], i["_seq"]))
    for param in ("work_order_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [i for i in items if i[param] == v]
    return paginate([serialize("invoice", i) for i in items])


@bp.post("/invoices/<iid>/issue")
def issue_invoice(iid):
    require_roles("CoopAdmin")
    inv = store.invoices.get(iid)
    if inv is None:
        raise not_found("invoice not found")
    if inv["status"] != "DRAFT":
        raise invalid_state("only a DRAFT invoice can be issued")
    w = store.work_orders[inv["work_order_id"]]
    rec = None
    for r in store.application_records.values():
        if r["work_order_id"] == w["id"]:
            rec = r
            break
    if rec is None or rec["status"] != "CERTIFIED":
        raise conflict("ERR_RECORD_NOT_CERTIFIED",
                       "the application record must be CERTIFIED before issuing")
    if find_open_complaint(w["id"]) is not None:
        raise conflict("ERR_COMPLAINT_HOLD",
                       "a complaint on this work order is FILED or INVESTIGATING")
    cust = store.customers[w["customer_id"]]
    if cust["outstanding_cents"] + inv["final_amount_cents"] > cust["credit_limit_cents"]:
        raise conflict("ERR_CREDIT_LIMIT_EXCEEDED",
                       "outstanding balance plus final amount exceeds the credit limit")
    cust["outstanding_cents"] += inv["final_amount_cents"]
    touch(cust)
    inv["status"] = "ISSUED"
    touch(inv)
    return ok(serialize("invoice", inv))


@bp.post("/invoices/<iid>/pay")
def pay_invoice(iid):
    uid, _role = require_roles("Grower")
    inv = store.invoices.get(iid)
    if inv is None:
        raise not_found("invoice not found")
    w = store.work_orders[inv["work_order_id"]]
    if w["customer_id"] != uid:
        raise forbidden("a Grower may pay only invoices belonging to their own account")
    if inv["status"] != "ISSUED":
        raise invalid_state("only an ISSUED invoice can be paid")
    cust = store.customers[w["customer_id"]]
    cust["outstanding_cents"] -= inv["final_amount_cents"]
    touch(cust)
    inv["status"] = "PAID"
    touch(inv)
    return ok(serialize("invoice", inv))


@bp.post("/invoices/<iid>/void")
def void_invoice(iid):
    require_roles("CoopAdmin")
    inv = store.invoices.get(iid)
    if inv is None:
        raise not_found("invoice not found")
    if inv["status"] not in ("DRAFT", "ISSUED"):
        raise invalid_state("only a DRAFT or ISSUED invoice can be voided")
    if inv["status"] == "ISSUED":
        # voiding an issued invoice credits the balance back; a DRAFT never debited
        w = store.work_orders[inv["work_order_id"]]
        cust = store.customers[w["customer_id"]]
        cust["outstanding_cents"] -= inv["final_amount_cents"]
        touch(cust)
    inv["status"] = "VOIDED"
    touch(inv)
    return ok(serialize("invoice", inv))
